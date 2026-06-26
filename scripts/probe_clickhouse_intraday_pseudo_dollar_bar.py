#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Bounded clickhouse-local probe for intraday_pseudo_dollar_bar_v1 parquet.')
    ap.add_argument('--clickhouse', required=True)
    ap.add_argument('--parquet', required=True)
    ap.add_argument('--trade-date', required=True)
    ap.add_argument('--proof-output', required=True)
    ap.add_argument('--host', default='unknown')
    ap.add_argument('--instance-id', default='unknown')
    ap.add_argument('--s3-source')
    ap.add_argument('--verified-download-sha256')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    clickhouse = Path(args.clickhouse)
    parquet = Path(args.parquet)
    proof_output = Path(args.proof_output)
    version = _run([str(clickhouse), 'local', '--version']).strip()

    reference, reference_seconds = _reference_metrics(parquet)
    observed, clickhouse_scan_seconds = _clickhouse_metrics(clickhouse, parquet)
    bucket_reference, reference_bucket_seconds = _reference_bucket_metrics(parquet)
    bucket_observed, clickhouse_bucket_seconds = _clickhouse_bucket_metrics(clickhouse, parquet)

    issues = _compare_metrics(reference, observed)
    issues.extend(_compare_bucket_metrics(bucket_reference, bucket_observed))
    if not reference['no_future_intraday_minutes_all']:
        issues.append('no_future_intraday_minutes_not_all_true')
    if reference['threshold_source_values'] != ['prior_dates']:
        issues.append(f"threshold_source_unexpected:{reference['threshold_source_values']}")
    if reference['research_window_values'] != ['IS']:
        issues.append(f"research_window_unexpected:{reference['research_window_values']}")

    proof = {
        'verdict': 'ACCEPT' if not issues else 'BLOCK',
        'dataset_id': 'intraday_pseudo_dollar_bar_v1',
        'host': args.host,
        'instance_id': args.instance_id,
        'engine': 'clickhouse-local',
        'clickhouse_version': version,
        'verified_download_sha256': args.verified_download_sha256,
        'runtime_clickhouse_sha256': _sha256(clickhouse),
        'runtime_clickhouse_size_bytes': clickhouse.stat().st_size,
        'trade_date': args.trade_date,
        'data_paths': {'local_parquet': str(parquet), 's3_source': args.s3_source},
        'input_file_size_bytes': parquet.stat().st_size,
        'reference': reference,
        'observed': observed,
        'bucket_reference': bucket_reference,
        'bucket_observed': bucket_observed,
        'timings': {
            'reference_scan_seconds': reference_seconds,
            'clickhouse_scan_seconds': clickhouse_scan_seconds,
            'reference_bucket_groupby_seconds': reference_bucket_seconds,
            'clickhouse_bucket_groupby_seconds': clickhouse_bucket_seconds,
        },
        'isolation': {
            'root': str(proof_output.parent),
            'uses_research_worker': False,
            'writes_research_artifacts': False,
            'starts_clickhouse_server': False,
            'creates_aws_resources': False,
            'bounded_single_partition_only': True,
        },
        'notes': [
            'Pseudo dollar bar is derived from 1m bar; it is not true tick dollar bar.',
            'Single-date bounded proof only; not a full-window production performance proof.',
        ],
        'issues': issues,
        'generated_at_epoch': time.time(),
    }
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps({'proof': str(proof_output), 'verdict': proof['verdict'], 'issues': issues, 'timings': proof['timings']}, indent=2))
    return 0 if proof['verdict'] == 'ACCEPT' else 1


def _reference_metrics(parquet: Path) -> tuple[dict, float]:
    columns = [
        'ts_code',
        'bucket_id',
        'amount',
        'signed_amount',
        'large_proxy_amount',
        'small_proxy_amount',
        'threshold_source',
        'no_future_intraday_minutes',
        'research_window',
    ]
    start = time.perf_counter()
    df = pd.read_parquet(parquet, columns=columns)
    metrics = {
        'row_count': int(len(df)),
        'ticker_count': int(df['ts_code'].nunique()),
        'bucket_count': int(df['bucket_id'].nunique()),
        'bucket_id_min': int(df['bucket_id'].min()),
        'bucket_id_max': int(df['bucket_id'].max()),
        'duplicate_key_count': int(df.duplicated(['ts_code', 'bucket_id']).sum()),
        'amount_sum': float(df['amount'].sum()),
        'signed_amount_sum': float(df['signed_amount'].sum()),
        'large_proxy_amount_sum': float(df['large_proxy_amount'].sum()),
        'small_proxy_amount_sum': float(df['small_proxy_amount'].sum()),
        'threshold_source_values': sorted(map(str, df['threshold_source'].dropna().unique().tolist())),
        'no_future_intraday_minutes_all': bool(df['no_future_intraday_minutes'].all()),
        'research_window_values': sorted(map(str, df['research_window'].dropna().unique().tolist())),
    }
    return metrics, time.perf_counter() - start


def _clickhouse_metrics(clickhouse: Path, parquet: Path) -> tuple[dict, float]:
    sql = f"""
    SELECT
        count() AS row_count,
        uniqExact(ts_code) AS ticker_count,
        uniqExact(bucket_id) AS bucket_count,
        min(bucket_id) AS bucket_id_min,
        max(bucket_id) AS bucket_id_max,
        count() - uniqExact(tuple(ts_code, bucket_id)) AS duplicate_key_count,
        sum(amount) AS amount_sum,
        sum(signed_amount) AS signed_amount_sum,
        sum(large_proxy_amount) AS large_proxy_amount_sum,
        sum(small_proxy_amount) AS small_proxy_amount_sum,
        groupUniqArray(threshold_source) AS threshold_source_values,
        min(no_future_intraday_minutes) AS no_future_intraday_minutes_min,
        max(no_future_intraday_minutes) AS no_future_intraday_minutes_max,
        groupUniqArray(research_window) AS research_window_values
    FROM file('{parquet}', Parquet)
    FORMAT JSONEachRow
    """
    start = time.perf_counter()
    row = json.loads(_run([str(clickhouse), 'local', '--query', sql]))
    seconds = time.perf_counter() - start
    metrics = {
        'row_count': int(row['row_count']),
        'ticker_count': int(row['ticker_count']),
        'bucket_count': int(row['bucket_count']),
        'bucket_id_min': int(row['bucket_id_min']),
        'bucket_id_max': int(row['bucket_id_max']),
        'duplicate_key_count': int(row['duplicate_key_count']),
        'amount_sum': float(row['amount_sum']),
        'signed_amount_sum': float(row['signed_amount_sum']),
        'large_proxy_amount_sum': float(row['large_proxy_amount_sum']),
        'small_proxy_amount_sum': float(row['small_proxy_amount_sum']),
        'threshold_source_values': sorted(map(str, row['threshold_source_values'])),
        'no_future_intraday_minutes_all': bool(row['no_future_intraday_minutes_min']) and bool(row['no_future_intraday_minutes_max']),
        'research_window_values': sorted(map(str, row['research_window_values'])),
    }
    return metrics, seconds


def _reference_bucket_metrics(parquet: Path) -> tuple[dict, float]:
    start = time.perf_counter()
    df = pd.read_parquet(parquet, columns=['bucket_id', 'amount', 'signed_amount'])
    grouped = df.groupby('bucket_id', observed=True).agg(
        row_count=('bucket_id', 'size'),
        amount_sum=('amount', 'sum'),
        signed_amount_sum=('signed_amount', 'sum'),
    )
    metrics = {
        'group_count': int(len(grouped)),
        'row_count_sum': int(grouped['row_count'].sum()),
        'amount_sum': float(grouped['amount_sum'].sum()),
        'signed_amount_sum': float(grouped['signed_amount_sum'].sum()),
    }
    return metrics, time.perf_counter() - start


def _clickhouse_bucket_metrics(clickhouse: Path, parquet: Path) -> tuple[dict, float]:
    sql = f"""
    SELECT
        count() AS group_count,
        sum(row_count) AS row_count_sum,
        sum(amount_sum) AS amount_sum,
        sum(signed_amount_sum) AS signed_amount_sum
    FROM
    (
        SELECT
            bucket_id,
            count() AS row_count,
            sum(amount) AS amount_sum,
            sum(signed_amount) AS signed_amount_sum
        FROM file('{parquet}', Parquet)
        GROUP BY bucket_id
    )
    FORMAT JSONEachRow
    """
    start = time.perf_counter()
    row = json.loads(_run([str(clickhouse), 'local', '--query', sql]))
    seconds = time.perf_counter() - start
    return {
        'group_count': int(row['group_count']),
        'row_count_sum': int(row['row_count_sum']),
        'amount_sum': float(row['amount_sum']),
        'signed_amount_sum': float(row['signed_amount_sum']),
    }, seconds


def _compare_metrics(reference: dict, observed: dict) -> list[str]:
    issues = []
    exact_keys = [
        'row_count',
        'ticker_count',
        'bucket_count',
        'bucket_id_min',
        'bucket_id_max',
        'duplicate_key_count',
        'threshold_source_values',
        'no_future_intraday_minutes_all',
        'research_window_values',
    ]
    float_keys = ['amount_sum', 'signed_amount_sum', 'large_proxy_amount_sum', 'small_proxy_amount_sum']
    for key in exact_keys:
        if reference[key] != observed[key]:
            issues.append(f'{key}_mismatch:{observed[key]}!=reference:{reference[key]}')
    for key in float_keys:
        if not _float_close(reference[key], observed[key]):
            issues.append(f'{key}_mismatch:{observed[key]}!=reference:{reference[key]}')
    return issues


def _compare_bucket_metrics(reference: dict, observed: dict) -> list[str]:
    issues = []
    for key in ['group_count', 'row_count_sum']:
        if reference[key] != observed[key]:
            issues.append(f'bucket_{key}_mismatch:{observed[key]}!=reference:{reference[key]}')
    for key in ['amount_sum', 'signed_amount_sum']:
        if not _float_close(reference[key], observed[key]):
            issues.append(f'bucket_{key}_mismatch:{observed[key]}!=reference:{reference[key]}')
    return issues


def _float_close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-6, abs(left) * 1e-12)


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == '__main__':
    raise SystemExit(main())
