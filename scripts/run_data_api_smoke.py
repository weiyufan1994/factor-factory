#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import DataApiClient, DataQuery, DataQueryInvalid, validate_data_api_result  # noqa: E402

FORBIDDEN_ROOTS = ['data/clean', 'objects', 'runs', 'evaluations', 'generated_code', 'archive']


def parse_args():
    ap = argparse.ArgumentParser(description='Run isolated Factor Data API smoke tests.')
    ap.add_argument('--root', default=None)
    ap.add_argument('--fresh', action='store_true')
    return ap.parse_args()


def write_catalog(path: Path, datasets: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'catalog_version': 'factorforge_data_catalog_v1', 'datasets': datasets}, indent=2), encoding='utf-8')


def snapshot_forbidden() -> dict[str, set[str]]:
    out = {}
    for rel in FORBIDDEN_ROOTS:
        root = REPO_ROOT / rel
        out[rel] = {str(p.relative_to(REPO_ROOT)) for p in root.rglob('*') if p.is_file()} if root.exists() else set()
    return out


def build_fixture(root: Path) -> Path:
    daily = root / 'daily.parquet'
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'open': 10.0, 'high': 11.0, 'low': 9.5, 'close': 10.5, 'vol': 100, 'amount': 1000},
        {'ts_code': '000002.SZ', 'trade_date': '20260102', 'open': 20.0, 'high': 21.0, 'low': 19.5, 'close': 20.5, 'vol': 200, 'amount': 2000},
    ]).to_parquet(daily, index=False)
    basic = root / 'basic.parquet'
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'turnover_rate': 1.0, 'pe': 10.0, 'pb': 1.1, 'total_mv': 100.0, 'circ_mv': 80.0},
    ]).to_parquet(basic, index=False)
    minute_part = root / 'minute' / 'trade_date=20260102'
    minute_part.mkdir(parents=True)
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_time': pd.Timestamp('2026-01-02 09:30:00'), 'trade_date': '20260102', 'open': 10.0, 'high': 10.2, 'low': 9.9, 'close': 10.1, 'vol': 100, 'amount': 1000},
    ]).to_parquet(minute_part / 'part-000.parquet', index=False)
    dup = root / 'dup.parquet'
    pd.DataFrame([
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0},
        {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 11.0},
    ]).to_parquet(dup, index=False)
    catalog = root / 'data_catalog.json'
    write_catalog(catalog, {
        'clean_daily_bar': {'uri': str(daily), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount'], 'qlib_field_map': {'$volume': 'vol'}},
        'daily_basic': {'uri': str(basic), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'turnover_rate', 'pe', 'pb', 'total_mv', 'circ_mv'], 'proxy_fields': {'market_cap': {'field': 'total_mv', 'rationale': 'catalog_configured_proxy'}}},
        'minute_bar': {'uri': str(root / 'minute'), 'format': 'parquet', 'columns': ['ts_code', 'trade_time', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount'], 'partition_columns': ['trade_date']},
        'duplicate_daily': {'uri': str(dup), 'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'close']},
    })
    return catalog


def case_ok(name: str, ok: bool, **extra) -> dict:
    return {'case': name, 'ok': bool(ok), **extra}


def main() -> int:
    args = parse_args()
    root = Path(args.root) if args.root else Path('/tmp') / f'factorforge_data_api_smoke_{next(tempfile._get_candidate_names())}'
    if not str(root).startswith('/tmp/'):
        print('BLOCK_NON_TMP_FACTORFORGE_ROOT', root)
        return 1
    if args.fresh and root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = snapshot_forbidden()
    catalog = build_fixture(root)
    client = DataApiClient.from_catalog(catalog)
    results = []

    daily = client.fetch(DataQuery('clean_daily_bar', '20260102', '20260102', 'a_share_all', ['open', 'high', 'low', 'close', 'vol', 'amount']))
    results.append(case_ok('clean_daily_bar_fetch_pass', daily.status == 'ready' and len(daily.frame) == 2, status=daily.status))
    basic = client.fetch(DataQuery('daily_basic', '20260102', '20260102', 'a_share_all', ['pe', 'pb']))
    results.append(case_ok('daily_basic_fetch_pass', basic.status == 'ready' and len(basic.frame) == 1, status=basic.status))
    minute = client.fetch(DataQuery('minute_bar', '20260102', '20260102', ['000001.SZ'], ['open', 'close', 'vol'], frequency='1min'))
    results.append(case_ok('minute_bar_fetch_pass', minute.status == 'ready' and len(minute.frame) == 1, status=minute.status))
    alias = client.fetch(DataQuery('clean_daily_bar', '20260102', '20260102', 'a_share_all', ['volume']))
    results.append(case_ok('volume_alias_pass', alias.status == 'ready' and alias.resolved_fields.get('volume') == 'vol', resolved=alias.resolved_fields))
    missing = client.fetch(DataQuery('clean_daily_bar', '20260102', '20260102', 'a_share_all', ['industry_code']))
    results.append(case_ok('missing_field_block', missing.status == 'blocked' and missing.coverage.missing_fields == ['industry_code'], reason=missing.blocked_reason))
    proxy = client.fetch(DataQuery('daily_basic', '20260102', '20260102', 'a_share_all', ['market_cap']))
    results.append(case_ok('market_cap_proxy_ready_if_configured', proxy.status == 'proxy_ready' and proxy.proxy_rules, status=proxy.status))
    unknown = client.fetch(DataQuery('unknown_dataset', '20260102', '20260102', 'a_share_all', ['close']))
    results.append(case_ok('unknown_dataset_block', unknown.status == 'blocked', reason=unknown.blocked_reason))
    try:
        DataQuery('clean_daily_bar', 'bad-date', '20260102', 'a_share_all', ['close'])
        bad_date = False
    except DataQueryInvalid:
        bad_date = True
    results.append(case_ok('bad_date_block', bad_date))
    uni = client.fetch(DataQuery('clean_daily_bar', '20260102', '20260102', ['000001.SZ'], ['close']))
    results.append(case_ok('universe_list_filter_pass', uni.status == 'ready' and uni.frame['ts_code'].tolist() == ['000001.SZ']))
    dup = client.fetch(DataQuery('duplicate_daily', '20260102', '20260102', 'a_share_all', ['close']))
    results.append(case_ok('duplicate_key_detection_block', dup.status == 'blocked' and dup.coverage.duplicate_key_count == 1, validation=validate_data_api_result(dup).result))

    after = snapshot_forbidden()
    new_files = {rel: sorted(after[rel] - before[rel]) for rel in FORBIDDEN_ROOTS}
    polluted = any(new_files.values())
    results.append(case_ok('no_clean_data_mutation', not polluted, new_files=new_files))
    verdict = 'ACCEPT' if all(item['ok'] for item in results) else 'BLOCK'
    summary = {'verdict': verdict, 'root': str(root), 'cases': results}
    summary_path = root / 'data_api_smoke_summary.json'
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
