#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api.universe_builders import expand_index_weight_universe_daily


DEFAULT_INDEXES = {
    '000300.SH': '沪深300',
    '000510.SH': '中证A500',
    '000852.SH': '中证1000',
    '000905.SH': '中证500',
    '000906.SH': '中证800',
    '000985.CSI': '中证全指',
    '932000.CSI': '中证2000',
}
DEFAULT_BUCKET = 'yufan-data-lake'
DEFAULT_RAW_PREFIX = 'tushares/指数专题数据/指数成分权重'
DEFAULT_PARQUET_URI = 's3://yufan-data-lake/factorforge/datamart/index_weight_universe/v1'


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Download CSI index constituents/weights from Tushare and publish a backtest universe parquet dataset.')
    ap.add_argument('--token', default=os.getenv('TUSHARE_TOKEN'))
    ap.add_argument('--token-file', default='/home/ubuntu/.openclaw/media/inbound/tushares_token---f5492736-ee8f-4214-b0de-0422f0cfa0a3')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default=datetime.utcnow().strftime('%Y%m%d'))
    ap.add_argument('--indexes', nargs='*', default=[f'{code}:{name}' for code, name in DEFAULT_INDEXES.items()])
    ap.add_argument('--local-root', default='factorforge/data/index_weight_universe_build')
    ap.add_argument('--raw-s3-prefix', default=f's3://{DEFAULT_BUCKET}/{DEFAULT_RAW_PREFIX}')
    ap.add_argument('--parquet-s3-uri', default=DEFAULT_PARQUET_URI)
    ap.add_argument('--local-parquet-root', default='factorforge/data/datamart/index_weight_universe')
    ap.add_argument('--qa-output', default='factorforge/data/proofs/index_weight_universe.qa.json')
    ap.add_argument('--catalog-output', default='factorforge/data/catalog/index_weight_universe.catalog.json')
    ap.add_argument('--sleep', type=float, default=0.25)
    ap.add_argument('--retry', type=int, default=3)
    ap.add_argument('--reuse-raw', action='store_true', help='Reuse existing local raw index_weight CSV files instead of calling Tushare again.')
    ap.add_argument('--skip-upload', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token or read_token(args.token_file)
    if not token and not args.dry_run:
        raise ValueError('missing Tushare token; set TUSHARE_TOKEN or --token-file')
    indexes = parse_indexes(args.indexes)
    local_root = Path(args.local_root).expanduser()
    raw_root = local_root / 'raw'
    local_parquet_root = Path(args.local_parquet_root).expanduser()
    raw_root.mkdir(parents=True, exist_ok=True)

    raw_frames: list[pd.DataFrame] = []
    failures: list[dict[str, Any]] = []
    if args.dry_run:
        print(json.dumps({'verdict': 'DRY_RUN', 'indexes': indexes}, indent=2, ensure_ascii=False))
        return 0

    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api(token)
    for index_code, index_name in indexes.items():
        path = raw_root / f'index_code={index_code}' / 'index_weight.csv'
        if args.reuse_raw and path.exists():
            frame = pd.read_csv(path, dtype={'index_code': 'string', 'con_code': 'string', 'trade_date': 'string'})
            raw_frames.append(frame)
            print(json.dumps({'event': 'index_weight_reused', 'index_code': index_code, 'rows': int(len(frame))}, ensure_ascii=False), flush=True)
            continue
        try:
            frame = fetch_index_weight(pro, index_code, args.start, args.end, args.retry, args.sleep)
        except Exception as exc:  # noqa: BLE001
            failures.append({'index_code': index_code, 'index_name': index_name, 'error': str(exc)})
            print(json.dumps({'event': 'index_weight_failed', 'index_code': index_code, 'error': str(exc)}, ensure_ascii=False), flush=True)
            continue
        if frame.empty:
            failures.append({'index_code': index_code, 'index_name': index_name, 'error': 'empty_result'})
            continue
        frame['index_code'] = frame['index_code'].fillna(index_code) if 'index_code' in frame.columns else index_code
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        raw_frames.append(frame)
        if not args.skip_upload:
            upload_path(path, f'{args.raw_s3_prefix.rstrip("/")}/index_code={index_code}/index_weight.csv')
        print(json.dumps({'event': 'index_weight_downloaded', 'index_code': index_code, 'rows': int(len(frame))}, ensure_ascii=False), flush=True)
        time.sleep(args.sleep)

    if not raw_frames:
        raise RuntimeError(f'no index_weight rows downloaded; failures={failures}')

    raw = pd.concat(raw_frames, ignore_index=True, sort=False)
    trade_dates = fetch_trade_dates(pro, args.start, args.end)
    universe = expand_index_weight_universe_daily(raw, trade_dates=trade_dates, index_names=indexes)
    local_parquet_root.mkdir(parents=True, exist_ok=True)
    write_trade_date_partitions(universe, local_parquet_root)
    if not args.skip_upload:
        upload_tree(local_parquet_root, args.parquet_s3_uri)

    qa = {
        'verdict': 'ACCEPT' if not failures else 'WARN',
        'dataset_id': 'index_weight_universe',
        'source_api': 'tushare.index_weight',
        'source_dataset': 'index_weight',
        'start': args.start,
        'end': args.end,
        'indexes': indexes,
        'row_count': int(len(universe)),
        'date_count': int(universe['trade_date'].nunique()) if not universe.empty else 0,
        'source_weight_date_count': int(universe['source_weight_date'].nunique()) if not universe.empty else 0,
        'ticker_count': int(universe['ts_code'].nunique()) if not universe.empty else 0,
        'duplicate_key_count': int(universe.duplicated(['universe_id', 'trade_date', 'ts_code']).sum()) if not universe.empty else 0,
        'missing_indexes': [code for code in indexes if code not in set(universe['index_code'])],
        'failures': failures,
        'raw_s3_prefix': None if args.skip_upload else args.raw_s3_prefix,
        'local_parquet_root': str(local_parquet_root),
        'parquet_s3_uri': None if args.skip_upload else args.parquet_s3_uri,
        'generated_at_utc': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    qa_path = Path(args.qa_output).expanduser()
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False), encoding='utf-8')
    write_catalog(args, indexes, qa_path)
    print(json.dumps({
        'verdict': qa['verdict'],
        'dataset_id': qa['dataset_id'],
        'row_count': qa['row_count'],
        'date_count': qa['date_count'],
        'ticker_count': qa['ticker_count'],
        'duplicate_key_count': qa['duplicate_key_count'],
        'missing_indexes': qa['missing_indexes'],
        'qa_output': str(qa_path),
        'catalog_output': args.catalog_output,
        'local_parquet_root': str(local_parquet_root),
        'parquet_s3_uri': qa['parquet_s3_uri'],
    }, indent=2, ensure_ascii=False))
    return 0


def read_token(path: str) -> str:
    token_path = Path(path).expanduser()
    if not token_path.exists():
        return ''
    return token_path.read_text(encoding='utf-8').strip()


def parse_indexes(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        code, sep, name = item.partition(':')
        code = code.strip()
        if not code:
            continue
        out[code] = name.strip() if sep else DEFAULT_INDEXES.get(code, code)
    return out


def fetch_index_weight(pro, index_code: str, start: str, end: str, retry: int, sleep: float) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in month_ranges(start, end):
        last_exc: Exception | None = None
        for attempt in range(1, retry + 1):
            try:
                frame = pro.index_weight(index_code=index_code, start_date=chunk_start, end_date=chunk_end)
                if frame is not None and not frame.empty:
                    frames.append(frame)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(sleep * attempt)
        else:
            raise RuntimeError(f'index_weight failed for {index_code} {chunk_start}-{chunk_end}: {last_exc}')
        time.sleep(sleep)
    if not frames:
        return pd.DataFrame(columns=['index_code', 'con_code', 'trade_date', 'weight'])
    return (
        pd.concat(frames, ignore_index=True, sort=False)
        .drop_duplicates(['index_code', 'con_code', 'trade_date'], keep='last')
        .reset_index(drop=True)
    )


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    start_dt = datetime.strptime(start, '%Y%m%d')
    end_dt = datetime.strptime(end, '%Y%m%d')
    out: list[tuple[str, str]] = []
    current = start_dt.replace(day=1)
    while current <= end_dt:
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1)
        else:
            next_month = current.replace(month=current.month + 1)
        chunk_start = max(start_dt, current)
        chunk_end = min(end_dt, next_month - timedelta(days=1))
        out.append((chunk_start.strftime('%Y%m%d'), chunk_end.strftime('%Y%m%d')))
        current = next_month
    return out


def fetch_trade_dates(pro, start: str, end: str) -> list[str]:
    frame = pro.trade_cal(exchange='', start_date=start, end_date=end, is_open='1')
    if frame is None or frame.empty:
        raise RuntimeError(f'trade_cal returned no open dates for {start}-{end}')
    return sorted(frame['cal_date'].astype(str).unique())


def upload_path(local_path: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'cp', str(local_path), s3_uri, '--only-show-errors'], check=True)


def upload_tree(local_root: Path, s3_uri: str) -> None:
    subprocess.run(['aws', 's3', 'sync', str(local_root), s3_uri.rstrip('/'), '--only-show-errors'], check=True)


def write_trade_date_partitions(frame: pd.DataFrame, output_root: Path) -> None:
    if output_root.exists():
        for old in output_root.glob('trade_date=*'):
            if old.is_dir():
                for item in old.glob('*'):
                    item.unlink()
                old.rmdir()
    output_root.mkdir(parents=True, exist_ok=True)
    for trade_date, group in frame.groupby('trade_date', sort=True, observed=True):
        part_dir = output_root / f'trade_date={trade_date}'
        part_dir.mkdir(parents=True, exist_ok=True)
        group.drop(columns=['trade_date']).to_parquet(part_dir / 'part-000.parquet', index=False)


def write_catalog(args: argparse.Namespace, indexes: dict[str, str], qa_path: Path) -> None:
    catalog_path = Path(args.catalog_output).expanduser()
    uri = args.parquet_s3_uri if not args.skip_upload else str(Path(args.local_parquet_root).expanduser())
    catalog = {
        'catalog_version': 'factorforge_data_catalog_v1',
        'datasets': {
            'index_weight_universe': {
                'uri': uri,
                'format': 'parquet',
                'storage': 's3' if uri.startswith('s3://') else 'local',
                'description': 'CSI index constituents and weights converted to backtest-ready time-series universe membership.',
                'columns': [
                    'universe_id',
                    'index_code',
                    'index_name',
                    'trade_date',
                    'source_weight_date',
                    'ts_code',
                    'weight',
                    'in_universe',
                ],
                'partition_columns': ['trade_date'],
                'date_column': 'trade_date',
                'symbol_column': 'ts_code',
                'metadata': {
                    'source_api': 'tushare.index_weight',
                    'source_dataset': 'index_weight',
                    'unique_key': ['universe_id', 'trade_date', 'ts_code'],
                    'sort_keys': ['universe_id', 'trade_date', 'ts_code'],
                    'indexes': indexes,
                    'qa_summary_path': str(qa_path),
                },
                'freshness': {
                    'trade_date_min': args.start,
                    'trade_date_max': args.end,
                },
            },
        },
    }
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
