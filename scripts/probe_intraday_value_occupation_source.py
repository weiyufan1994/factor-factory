#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_api import DataApiClient, DataQuery  # noqa: E402
from factor_factory.data_api.catalog import DataCatalog, resolve_default_catalog_path  # noqa: E402
from factor_factory.data_api.value_occupation import normalize_trade_date  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Probe source coverage for intraday_value_occupation_state_v1 without running backfill.')
    ap.add_argument('--catalog', help='Data API catalog path. Defaults to DataApiClient default catalog resolution.')
    ap.add_argument('--minute-dataset', default='minute_bar')
    ap.add_argument('--calendar-dataset', default='clean_daily_bar')
    ap.add_argument('--expected-dates-file', help='Text or JSON file containing expected open trade dates.')
    ap.add_argument('--local-minute-root', action='append', default=[], help='Optional local/worker warm minute cache root to compare.')
    ap.add_argument('--start', default='20160104')
    ap.add_argument('--end', default='20250711')
    ap.add_argument('--output', default='factorforge/data/proofs/intraday_value_occupation_source_probe.json')
    ap.add_argument('--s3-ls-timeout', type=int, default=300)
    return ap.parse_args()


def parse_s3_partition_dates(output: str) -> list[str]:
    dates = set()
    for match in re.finditer(r'trade_date=([0-9]{8})/?', output):
        dates.add(normalize_trade_date(match.group(1)))
    return sorted(dates)


def discover_local_partition_dates(root: str | Path) -> list[str]:
    base = Path(root).expanduser()
    if not base.exists():
        return []
    return sorted({
        normalize_trade_date(path.name.split('=', 1)[1])
        for path in base.glob('trade_date=*')
        if path.is_dir() and '=' in path.name
    })


def coverage_summary(expected_dates: Iterable[str], available_dates: Iterable[str], label: str) -> dict[str, object]:
    expected = sorted({normalize_trade_date(date) for date in expected_dates})
    available = sorted({normalize_trade_date(date) for date in available_dates})
    expected_set = set(expected)
    available_set = set(available)
    missing = sorted(expected_set - available_set)
    extra = sorted(available_set - expected_set)
    ratio = (len(expected_set & available_set) / len(expected)) if expected else 0.0
    return {
        'label': label,
        'expected_date_count': len(expected),
        'available_date_count': len(available),
        'covered_date_count': len(expected_set & available_set),
        'missing_date_count': len(missing),
        'extra_date_count': len(extra),
        'coverage_ratio': ratio,
        'min_available_date': min(available) if available else None,
        'max_available_date': max(available) if available else None,
        'missing_dates': missing,
        'extra_dates_sample': extra[:20],
    }


def read_dates_file(path: str | Path, start: str, end: str) -> list[str]:
    source = Path(path).expanduser()
    text = source.read_text(encoding='utf-8')
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raw = re.findall(r'[0-9]{8}', text)
    else:
        if isinstance(payload, dict):
            raw = payload.get('trade_dates') or payload.get('dates') or payload.get('expected_dates') or []
        else:
            raw = payload
    return filter_date_range([str(item) for item in raw], start, end)


def filter_date_range(dates: Iterable[str], start: str, end: str) -> list[str]:
    start_date = normalize_trade_date(start)
    end_date = normalize_trade_date(end)
    return sorted({date for date in (normalize_trade_date(item) for item in dates) if start_date <= date <= end_date})


def expected_dates_from_catalog(catalog_path: str | Path, dataset_id: str, start: str, end: str) -> list[str]:
    catalog = DataCatalog.load(catalog_path)
    entry = catalog.datasets[dataset_id]
    client = DataApiClient(catalog)
    result = client.fetch(DataQuery(dataset_id, start, end, 'a_share_all', [entry.date_column]))
    if result.status == 'blocked':
        raise RuntimeError(f'calendar dataset blocked: {result.blocked_reason}')
    return filter_date_range(result.frame[entry.date_column].astype(str).unique().tolist(), start, end)


def s3_ls(uri: str, timeout: int = 300) -> str:
    proc = subprocess.run(['aws', 's3', 'ls', uri.rstrip('/') + '/'], check=True, text=True, capture_output=True, timeout=timeout)
    return proc.stdout


def partition_dates_for_entry(catalog: DataCatalog, dataset_id: str, s3_ls_timeout: int = 300) -> list[str]:
    entry = catalog.datasets[dataset_id]
    if entry.uri.startswith('s3://') or entry.storage == 's3':
        return parse_s3_partition_dates(s3_ls(entry.uri, timeout=s3_ls_timeout))
    return discover_local_partition_dates(entry.uri.removeprefix('file://'))


def main() -> int:
    args = parse_args()
    catalog_path = Path(args.catalog).expanduser() if args.catalog else resolve_default_catalog_path()
    catalog = DataCatalog.load(catalog_path)
    if args.expected_dates_file:
        expected_dates = read_dates_file(args.expected_dates_file, args.start, args.end)
        expected_source = str(Path(args.expected_dates_file).expanduser())
    else:
        expected_dates = expected_dates_from_catalog(catalog_path, args.calendar_dataset, args.start, args.end)
        expected_source = f'catalog:{args.calendar_dataset}'

    minute_dates = partition_dates_for_entry(catalog, args.minute_dataset, args.s3_ls_timeout)
    checks = [
        coverage_summary(expected_dates, minute_dates, f'catalog:{args.minute_dataset}'),
    ]
    for root in args.local_minute_root:
        checks.append(coverage_summary(expected_dates, discover_local_partition_dates(root), f'local_cache:{Path(root).expanduser()}'))

    summary = {
        'verdict': 'ACCEPT' if checks and checks[0]['missing_date_count'] == 0 else 'BLOCK',
        'probe_type': 'intraday_value_occupation_source_coverage',
        'catalog_path': str(catalog_path),
        'minute_dataset': args.minute_dataset,
        'expected_dates_source': expected_source,
        'start': normalize_trade_date(args.start),
        'end': normalize_trade_date(args.end),
        'checks': checks,
    }
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['verdict'] == 'ACCEPT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
