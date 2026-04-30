#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import default_clean_daily_layer_root, default_local_data_root
from factor_factory.data_access.mutation_guard import require_data_mutation_authority


DEFAULT_LOCAL_ROOT = default_local_data_root()
DEFAULT_CLEAN_DIR = default_clean_daily_layer_root()
DEFAULT_DAILY_CLEAN = DEFAULT_CLEAN_DIR / 'daily_clean.parquet'
DEFAULT_DAILY_META = DEFAULT_CLEAN_DIR / 'daily_clean.meta.json'
REQUIRED_ENHANCED_COLUMNS = {
    'daily_basic_close',
    'turnover_rate',
    'turnover_rate_f',
    'volume_ratio',
    'pe',
    'pe_ttm',
    'pb',
    'ps',
    'ps_ttm',
    'dv_ratio',
    'dv_ttm',
    'total_share',
    'float_share',
    'free_share',
    'total_mv',
    'circ_mv',
    'free_float_mcap',
    'ln_mcap_free',
    'ln_total_mv',
    'ln_circ_mv',
}


def run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=capture, cwd=REPO_ROOT)


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).replace('-', '').strip()
    if text.lower() == 'current':
        return 'current'
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f'expected YYYYMMDD date, got {value!r}')
    return text


def next_calendar_day(date_text: str) -> str:
    return (datetime.strptime(date_text, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')


def read_daily_csv_last_trade_date(path: Path) -> str | None:
    if not path.exists():
        return None
    last = None
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            value = row.get('trade_date')
            if value:
                last = str(value).replace('.0', '').zfill(8)
    return last


def daily_basic_trade_dates(root: Path) -> list[str]:
    if not root.exists():
        return []
    dates = []
    for part_dir in root.glob('trade_date=*'):
        if not part_dir.is_dir():
            continue
        date = part_dir.name.replace('trade_date=', '')
        if len(date) == 8 and date.isdigit():
            dates.append(date)
    return sorted(set(dates))


def parquet_columns(path: Path) -> list[str]:
    if not path.exists():
        return []
    return pq.ParquetFile(path).schema_arrow.names


def parquet_trade_date_max(path: Path) -> str | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=['trade_date'])
    if frame.empty:
        return None
    return str(frame['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8).max())


def read_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def sync_daily_basic_if_needed(args: argparse.Namespace, daily_basic_dates: list[str]) -> dict:
    if args.skip_sync_daily_basic:
        return {'skipped': True, 'reason': 'skip_sync_daily_basic'}

    end_date = normalize_date(args.end_date)
    if end_date == 'current':
        end_date = datetime.now().strftime('%Y%m%d')

    if not end_date:
        return {'skipped': True, 'reason': 'no_end_date'}

    if daily_basic_dates and daily_basic_dates[-1] >= end_date:
        return {
            'skipped': True,
            'reason': 'local_daily_basic_up_to_date',
            'local_last_trade_date': daily_basic_dates[-1],
            'end_date': end_date,
        }

    if not daily_basic_dates:
        if not args.sync_all_daily_basic_if_missing:
            return {
                'skipped': True,
                'reason': 'daily_basic_missing_and_sync_all_not_requested',
                'end_date': end_date,
            }
        cmd = [
            sys.executable,
            'scripts/sync_tushare_raw_from_s3.py',
            '--local-root',
            str(args.local_root),
            '--operator',
            args.operator,
            'sync-daily-basic-all',
        ]
    else:
        start = next_calendar_day(daily_basic_dates[-1])
        cmd = [
            sys.executable,
            'scripts/sync_tushare_raw_from_s3.py',
            '--local-root',
            str(args.local_root),
            '--operator',
            args.operator,
            'sync-daily-basic-range',
            '--start',
            start,
            '--end',
            end_date,
        ]

    result = run(cmd)
    return {
        'skipped': False,
        'command': cmd,
        'stdout_tail': result.stdout[-4000:],
        'stderr_tail': result.stderr[-2000:] if result.stderr else '',
    }


def build_clean_layer(args: argparse.Namespace) -> dict:
    cmd = [
        sys.executable,
        'scripts/build_clean_daily_layer.py',
        '--start',
        args.clean_start,
        '--end',
        args.clean_end,
        '--ensure-daily-basic',
        '--operator',
        args.operator,
    ]
    result = run(cmd)
    return {
        'mode': 'full_rebuild',
        'command': cmd,
        'stdout_tail': result.stdout[-4000:],
        'stderr_tail': result.stderr[-2000:] if result.stderr else '',
    }


def append_clean_layer(args: argparse.Namespace, start: str, end: str) -> dict:
    cmd = [
        sys.executable,
        'scripts/append_clean_daily_layer.py',
        '--local-root',
        str(args.local_root),
        '--clean-dir',
        str(args.clean_dir),
        '--start',
        start,
        '--end',
        end,
        '--operator',
        args.operator,
    ]
    result = run(cmd)
    return {
        'mode': 'incremental_append',
        'command': cmd,
        'stdout_tail': result.stdout[-4000:],
        'stderr_tail': result.stderr[-2000:] if result.stderr else '',
    }


def merge_daily_basic_enhancement(args: argparse.Namespace) -> dict:
    cmd = [
        sys.executable,
        'scripts/build_daily_clean_enhanced.py',
        '--replace',
        '--daily-basic-dir',
        str(args.daily_basic_dir),
        '--operator',
        args.operator,
    ]
    if args.backup:
        cmd.append('--backup')
    result = run(cmd)
    return {
        'command': cmd,
        'stdout_tail': result.stdout[-4000:],
        'stderr_tail': result.stderr[-2000:] if result.stderr else '',
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Refresh the shared clean daily layer and merge daily_basic enhancement fields after raw Tushare updates.'
    )
    parser.add_argument('--local-root', type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument('--clean-dir', type=Path, default=DEFAULT_CLEAN_DIR)
    parser.add_argument('--end-date', default=datetime.now().strftime('%Y%m%d'))
    parser.add_argument('--clean-start', default='20100104')
    parser.add_argument('--clean-end', default='current')
    parser.add_argument('--force', action='store_true', help='Force a full rebuild and re-merge daily_basic even if it appears current.')
    parser.add_argument('--update-mode', choices=['auto', 'append', 'rebuild'], default='auto', help='auto uses incremental append for ordinary new dates; rebuild is reserved for schema/policy changes.')
    parser.add_argument('--backup', action='store_true', help='Ask the enhancement script to keep large parquet backups before replacement.')
    parser.add_argument('--skip-sync-daily-basic', action='store_true')
    parser.add_argument('--sync-all-daily-basic-if-missing', action='store_true')
    parser.add_argument('--operator', default=None, help='Data mutation operator. Must be codex for shared clean-layer writes.')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    require_data_mutation_authority(args.operator, operation='refresh_clean_daily_after_tushare_update')
    args.local_root = args.local_root.expanduser()
    args.clean_dir = args.clean_dir.expanduser()
    args.daily_csv = args.local_root / '行情数据' / 'daily.csv'
    args.daily_basic_dir = args.local_root / '行情数据' / 'daily_basic_incremental'
    args.daily_clean = args.clean_dir / 'daily_clean.parquet'
    args.daily_meta = args.clean_dir / 'daily_clean.meta.json'
    args.clean_start = normalize_date(args.clean_start) or '20100104'
    args.clean_end = normalize_date(args.clean_end) or 'current'

    before_daily_basic_dates = daily_basic_trade_dates(args.daily_basic_dir)
    summary: dict[str, object] = {
        'paths': {
            'local_root': str(args.local_root),
            'daily_csv': str(args.daily_csv),
            'daily_basic_dir': str(args.daily_basic_dir),
            'daily_clean': str(args.daily_clean),
            'daily_meta': str(args.daily_meta),
        },
        'before': {
            'raw_daily_last_trade_date': read_daily_csv_last_trade_date(args.daily_csv),
            'daily_basic_first_trade_date': before_daily_basic_dates[0] if before_daily_basic_dates else None,
            'daily_basic_last_trade_date': before_daily_basic_dates[-1] if before_daily_basic_dates else None,
            'daily_basic_partition_count': len(before_daily_basic_dates),
            'clean_last_trade_date': parquet_trade_date_max(args.daily_clean),
            'clean_columns': parquet_columns(args.daily_clean),
        },
    }

    summary['sync_daily_basic'] = sync_daily_basic_if_needed(args, before_daily_basic_dates)

    after_daily_basic_dates = daily_basic_trade_dates(args.daily_basic_dir)
    raw_daily_last = read_daily_csv_last_trade_date(args.daily_csv)
    clean_last = parquet_trade_date_max(args.daily_clean)
    columns = set(parquet_columns(args.daily_clean))
    meta = read_meta(args.daily_meta)
    enrichment = meta.get('daily_basic_enrichment') or {}
    enrichment_end = enrichment.get('source_trade_date_end')

    missing_required = REQUIRED_ENHANCED_COLUMNS - columns
    raw_ahead = bool(raw_daily_last and clean_last and clean_last < raw_daily_last)
    clean_missing = not args.daily_clean.exists() or not args.daily_meta.exists() or clean_last is None
    needs_base_update = args.force or clean_missing or raw_ahead
    base_update_mode = 'skip'
    if needs_base_update:
        if args.force or args.update_mode == 'rebuild' or clean_missing:
            base_update_mode = 'full_rebuild'
        elif args.update_mode in {'auto', 'append'} and not missing_required:
            base_update_mode = 'incremental_append'
        else:
            base_update_mode = 'full_rebuild'

    needs_enhancement = (
        args.force
        or bool(missing_required)
        or (after_daily_basic_dates and (not enrichment_end or enrichment_end < after_daily_basic_dates[-1]))
    )

    summary['decision'] = {
        'needs_base_update': needs_base_update,
        'base_update_mode': base_update_mode,
        'needs_enhancement': needs_enhancement,
        'raw_daily_last_trade_date': raw_daily_last,
        'clean_last_trade_date': clean_last,
        'daily_basic_last_trade_date': after_daily_basic_dates[-1] if after_daily_basic_dates else None,
        'enrichment_source_trade_date_end': enrichment_end,
        'missing_required_enhanced_columns': sorted(missing_required),
    }

    if base_update_mode == 'full_rebuild':
        summary['build_clean_layer'] = build_clean_layer(args)
        needs_enhancement = True
    elif base_update_mode == 'incremental_append':
        append_start = next_calendar_day(clean_last)
        append_end = raw_daily_last or normalize_date(args.end_date) or args.end_date
        summary['build_clean_layer'] = append_clean_layer(args, append_start, append_end)
        needs_enhancement = False
    else:
        summary['build_clean_layer'] = {'skipped': True, 'reason': 'clean_layer_current'}

    final_columns_after_base = set(parquet_columns(args.daily_clean))
    final_meta_after_base = read_meta(args.daily_meta)
    final_enrichment_after_base = final_meta_after_base.get('daily_basic_enrichment') or {}
    if base_update_mode == 'incremental_append':
        needs_enhancement = (
            bool(REQUIRED_ENHANCED_COLUMNS - final_columns_after_base)
            or (after_daily_basic_dates and (not final_enrichment_after_base.get('source_trade_date_end') or final_enrichment_after_base.get('source_trade_date_end') < after_daily_basic_dates[-1]))
        )

    if needs_enhancement:
        summary['merge_daily_basic_enhancement'] = merge_daily_basic_enhancement(args)
    else:
        summary['merge_daily_basic_enhancement'] = {'skipped': True, 'reason': 'daily_basic_enrichment_current_or_incrementally_appended'}

    final_columns = parquet_columns(args.daily_clean)
    final_meta = read_meta(args.daily_meta)
    final_enrichment = final_meta.get('daily_basic_enrichment') or {}
    summary['after'] = {
        'clean_last_trade_date': parquet_trade_date_max(args.daily_clean),
        'daily_basic_last_trade_date': after_daily_basic_dates[-1] if after_daily_basic_dates else None,
        'daily_basic_partition_count': len(after_daily_basic_dates),
        'has_required_enhanced_columns': REQUIRED_ENHANCED_COLUMNS.issubset(set(final_columns)),
        'enrichment_source_trade_date_end': final_enrichment.get('source_trade_date_end'),
        'daily_clean_size_mb': round(args.daily_clean.stat().st_size / 1024**2, 1) if args.daily_clean.exists() else None,
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary['after']['has_required_enhanced_columns']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
