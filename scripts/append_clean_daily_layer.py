#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access import (  # noqa: E402
    DailyFilterPolicy,
    default_clean_daily_layer_root,
    default_local_data_root,
    get_clean_daily,
    resolve_local_tushare_paths,
)
from factor_factory.data_access.mutation_guard import require_data_mutation_authority  # noqa: E402
from scripts.build_daily_clean_enhanced import (  # noqa: E402
    build_daily_basic_enrichment,
    forward_fill_free_share,
    load_all_daily_basic,
)

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


def normalize_date(value: str | int | None) -> str | None:
    if value is None:
        return None
    text = str(value).replace('-', '').strip()
    if text.lower() == 'current':
        return 'current'
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f'expected YYYYMMDD date, got {value!r}')
    return text


def next_calendar_day(date_text: str) -> str:
    return (datetime.strptime(date_text, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')


def lookback_date(date_text: str, days: int) -> str:
    return (datetime.strptime(date_text, '%Y%m%d') - timedelta(days=days)).strftime('%Y%m%d')


def read_meta(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def policy_from_meta(meta: dict) -> DailyFilterPolicy:
    raw = meta.get('policy')
    if not isinstance(raw, dict):
        raw = (meta.get('clean_meta') or {}).get('policy')
    if not isinstance(raw, dict):
        return DailyFilterPolicy()
    allowed = {item.name for item in fields(DailyFilterPolicy)}
    return DailyFilterPolicy(**{key: value for key, value in raw.items() if key in allowed})


def parquet_trade_date_max(path: Path) -> str | None:
    if not path.exists():
        return None
    frame = pd.read_parquet(path, columns=['trade_date'])
    if frame.empty:
        return None
    return str(frame['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8).max())


def read_daily_csv_last_trade_date(path: Path) -> str | None:
    if not path.exists():
        return None
    last = None
    for chunk in pd.read_csv(path, usecols=['trade_date'], dtype={'trade_date': 'string'}, chunksize=1_000_000):
        if not chunk.empty:
            last = str(chunk['trade_date'].iloc[-1]).replace('.0', '').zfill(8)
    return last


def ensure_enhanced_slice(clean_slice: pd.DataFrame, daily_basic_dir: Path, start: str, end: str, lookback_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_basic_start = lookback_date(start, lookback_days)
    daily_basic = load_all_daily_basic(daily_basic_dir, start=daily_basic_start, end=end)
    daily_basic = forward_fill_free_share(daily_basic)
    enrichment = build_daily_basic_enrichment(daily_basic)
    enrichment = enrichment[enrichment['trade_date'].between(start, end)].copy()
    before = len(clean_slice)
    merged = clean_slice.merge(enrichment, on=['ts_code', 'trade_date'], how='left', validate='many_to_one')
    if len(merged) != before:
        raise AssertionError(f'incremental enhancement changed row count: before={before} after={len(merged)}')
    return merged, enrichment


def update_meta(meta_path: Path, payload: dict, append_summary: dict, enrichment: pd.DataFrame, output: pd.DataFrame) -> None:
    payload.setdefault('artifacts', {})
    payload['artifacts']['daily_parquet'] = str(meta_path.with_name('daily_clean.parquet'))
    payload['artifacts']['metadata_json'] = str(meta_path)
    payload['last_update_mode'] = 'incremental_append'
    payload['incremental_append'] = append_summary
    if not enrichment.empty:
        payload['daily_basic_enrichment'] = {
            'source': append_summary.get('daily_basic_dir'),
            'source_trade_date_start': str(enrichment['trade_date'].min()),
            'source_trade_date_end': str(enrichment['trade_date'].max()),
            'source_rows': int(len(enrichment)),
            'source_tickers': int(enrichment['ts_code'].nunique()),
            'merged_at': datetime.now().isoformat(timespec='seconds'),
            'columns_added': [col for col in enrichment.columns if col not in {'ts_code', 'trade_date'}],
            'null_ratios': {
                col: float(output[col].isna().mean())
                for col in ['free_share', 'free_float_mcap', 'ln_mcap_free', 'total_mv', 'circ_mv']
                if col in output.columns
            },
        }
    payload['output_summary'] = {
        'rows': int(len(output)),
        'tickers': int(output['ts_code'].nunique()) if 'ts_code' in output.columns else None,
        'trade_dates': int(output['trade_date'].nunique()) if 'trade_date' in output.columns else None,
        'columns': list(output.columns),
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Append newly available trade dates to shared daily_clean.parquet without full historical rebuild.')
    parser.add_argument('--local-root', type=Path, default=default_local_data_root())
    parser.add_argument('--clean-dir', type=Path, default=default_clean_daily_layer_root())
    parser.add_argument('--start', help='Inclusive append start date. Defaults to day after current clean max trade_date.')
    parser.add_argument('--end', default='current', help='Inclusive append end date. Defaults to raw daily last trade_date when current.')
    parser.add_argument('--daily-basic-lookback-days', type=int, default=370)
    parser.add_argument('--operator', default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_data_mutation_authority(args.operator, operation='append_clean_daily_layer')
    args.local_root = args.local_root.expanduser()
    args.clean_dir = args.clean_dir.expanduser()
    daily_clean = args.clean_dir / 'daily_clean.parquet'
    daily_meta = args.clean_dir / 'daily_clean.meta.json'
    if not daily_clean.exists() or not daily_meta.exists():
        raise SystemExit(f'clean layer missing; full build required first: {args.clean_dir}')

    raw_paths = resolve_local_tushare_paths(require_daily_basic=True)
    if args.local_root:
        from factor_factory.data_access.paths import _paths_for_root  # local private helper, stable inside repo scripts
        raw_paths = _paths_for_root(args.local_root, source_label='explicit_append_local_root')

    clean_last = parquet_trade_date_max(daily_clean)
    raw_last = read_daily_csv_last_trade_date(raw_paths.daily_csv)
    if not clean_last or not raw_last:
        raise SystemExit('cannot determine clean/raw last trade_date')

    start = normalize_date(args.start) if args.start else next_calendar_day(clean_last)
    end = normalize_date(args.end)
    if end == 'current':
        end = raw_last
    if not end:
        end = raw_last
    if start > end:
        summary = {
            'mode': 'incremental_append',
            'skipped': True,
            'reason': 'clean_layer_current',
            'clean_last_trade_date': clean_last,
            'raw_last_trade_date': raw_last,
            'start': start,
            'end': end,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    meta = read_meta(daily_meta)
    policy = policy_from_meta(meta)
    clean_slice, slice_meta = get_clean_daily(
        start=start,
        end=end,
        paths=raw_paths,
        policy=policy,
        return_metadata=True,
    )
    if clean_slice.empty:
        raise SystemExit(f'no clean rows produced for append window {start}..{end}')

    import pyarrow.parquet as pq
    missing_columns = REQUIRED_ENHANCED_COLUMNS - set(pq.ParquetFile(daily_clean).schema_arrow.names)
    if missing_columns:
        raise SystemExit(f'existing clean layer lacks enhanced columns; run build_daily_clean_enhanced once first: {sorted(missing_columns)}')

    enhanced_slice, enrichment = ensure_enhanced_slice(
        clean_slice,
        raw_paths.daily_basic_dir,
        start,
        end,
        args.daily_basic_lookback_days,
    )

    existing = pd.read_parquet(daily_clean)
    existing['trade_date'] = existing['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)
    existing = existing[existing['trade_date'] < start].copy()
    combined = pd.concat([existing, enhanced_slice], ignore_index=True, sort=False)
    combined = combined.sort_values(['trade_date', 'ts_code']).reset_index(drop=True)

    tmp = daily_clean.with_suffix('.parquet.tmp')
    combined.to_parquet(tmp, index=False)
    tmp.replace(daily_clean)

    append_summary = {
        'start': start,
        'end': end,
        'raw_last_trade_date': raw_last,
        'previous_clean_last_trade_date': clean_last,
        'appended_rows': int(len(enhanced_slice)),
        'appended_trade_dates': int(enhanced_slice['trade_date'].nunique()),
        'daily_basic_dir': str(raw_paths.daily_basic_dir),
        'clean_meta': slice_meta,
    }
    update_meta(daily_meta, meta, append_summary, enrichment, combined)
    print(json.dumps({
        'mode': 'incremental_append',
        'skipped': False,
        'paths': {
            'daily_clean': str(daily_clean),
            'daily_meta': str(daily_meta),
            'raw_daily': str(raw_paths.daily_csv),
            'daily_basic_dir': str(raw_paths.daily_basic_dir),
        },
        'summary': append_summary,
        'after': {
            'rows': int(len(combined)),
            'date_min': str(combined['trade_date'].min()),
            'date_max': str(combined['trade_date'].max()),
            'date_count': int(combined['trade_date'].nunique()),
            'size_mb': round(daily_clean.stat().st_size / 1024**2, 1),
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
