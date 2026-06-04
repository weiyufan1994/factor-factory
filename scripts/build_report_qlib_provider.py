#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIELD_COLUMNS = ['open', 'high', 'low', 'close', 'volume', 'factor', 'change', 'amount', 'pre_close']


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def resolve_factorforge_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return REPO_ROOT


def resolve_source_path(factorforge_root: Path, report_id: str, explicit_source: str | None) -> Path:
    if explicit_source:
        return Path(explicit_source).expanduser().resolve()

    prep_path = factorforge_root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    if not prep_path.exists():
        raise SystemExit(f'missing Step3A data_prep_master: {prep_path}')
    prep = load_json(prep_path)
    local_inputs = prep.get('local_input_paths') if isinstance(prep.get('local_input_paths'), dict) else {}
    for key in ['daily_df_parquet', 'daily_df_csv', 'daily_df_csv_sample']:
        raw = local_inputs.get(key)
        if raw:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = factorforge_root.parent / candidate
            if candidate.exists():
                return candidate.resolve()
    raise SystemExit(f'no usable Step3A daily snapshot path found in {prep_path}')


def load_daily_source(source_path: Path) -> pd.DataFrame:
    if source_path.suffix.lower() == '.parquet':
        df = pd.read_parquet(source_path)
    elif source_path.suffix.lower() == '.csv':
        df = pd.read_csv(source_path)
    else:
        raise SystemExit(f'unsupported source snapshot extension: {source_path}')
    required = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount']
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise SystemExit(f'source snapshot missing columns for qlib provider: {missing}')
    return df


def normalize_qlib_symbol(ts_code: str, style: str = 'ts_code') -> str:
    value = str(ts_code)
    if style in {'ts_code', 'tushare', 'provider'}:
        return value
    if style in {'legacy_qlib', 'qlib'} and '.' in value:
        code, market = value.split('.', 1)
        return f'{market.upper()}{code}'
    if style == 'raw':
        return value
    raise SystemExit(f'unsupported qlib instrument style: {style}')


def normalize_source(df: pd.DataFrame, instrument_style: str = 'ts_code') -> pd.DataFrame:
    out = df.copy()
    out['symbol'] = out['ts_code'].map(lambda value: normalize_qlib_symbol(value, style=instrument_style))
    out['date'] = pd.to_datetime(
        out['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8),
        format='%Y%m%d',
        errors='raise',
    )
    out['volume'] = pd.to_numeric(out['vol'], errors='coerce')
    out['factor'] = 1.0
    if 'pct_chg' in out.columns:
        out['change'] = pd.to_numeric(out['pct_chg'], errors='coerce') / 100.0
    elif 'change' not in out.columns:
        out['change'] = np.nan
    for column in ['open', 'high', 'low', 'close', 'amount', 'pre_close', 'change']:
        if column not in out.columns:
            out[column] = np.nan
        out[column] = pd.to_numeric(out[column], errors='coerce')
    return out[
        ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'factor', 'change', 'amount', 'pre_close']
    ].sort_values(['symbol', 'date']).reset_index(drop=True)


def build_source_snapshot(report_id: str, source_csv: Path, out_dir: Path) -> tuple[Path, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_dir = out_dir / 'source_daily'
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    df = normalize_source(load_daily_source(source_csv))
    for symbol, symbol_df in df.groupby('symbol', sort=True):
        serializable = symbol_df.copy()
        serializable['date'] = serializable['date'].dt.strftime('%Y-%m-%d')
        serializable.to_csv(source_dir / f'{symbol}.csv', index=False)
    stats = {
        'report_id': report_id,
        'rows': int(len(df)),
        'symbols': int(df['symbol'].nunique()),
        'dates': int(df['date'].nunique()),
        'source_dir': str(source_dir),
    }
    return source_dir, stats


def write_feature_bin(path: Path, start_index: int, values: pd.Series) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pd.to_numeric(values, errors='coerce').astype('float32').to_numpy()
    np.hstack([[float(start_index)], data]).astype('<f4').tofile(path)


def build_provider(df: pd.DataFrame, provider_dir: Path, *, instrument_style: str = 'ts_code', source_path: Path | None = None) -> dict:
    if provider_dir.exists():
        shutil.rmtree(provider_dir)
    calendars_dir = provider_dir / 'calendars'
    instruments_dir = provider_dir / 'instruments'
    features_dir = provider_dir / 'features'
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)

    calendar = pd.Index(sorted(df['date'].dropna().unique()))
    if calendar.empty:
        raise SystemExit('cannot build qlib provider from empty daily snapshot')
    calendar_strings = pd.Series(calendar).dt.strftime('%Y-%m-%d')
    (calendars_dir / 'day.txt').write_text('\n'.join(calendar_strings.tolist()) + '\n', encoding='utf-8')

    calendar_pos = {pd.Timestamp(value): idx for idx, value in enumerate(calendar)}
    field_columns = DEFAULT_FIELD_COLUMNS
    instrument_lines: list[str] = []
    feature_files = 0

    for symbol, symbol_df in df.groupby('symbol', sort=True):
        symbol_df = symbol_df.dropna(subset=['date']).sort_values('date')
        if symbol_df.empty:
            continue
        start = pd.Timestamp(symbol_df['date'].min())
        end = pd.Timestamp(symbol_df['date'].max())
        start_idx = calendar_pos[start]
        end_idx = calendar_pos[end]
        date_range = calendar[start_idx:end_idx + 1]
        aligned = symbol_df.drop_duplicates('date', keep='last').set_index('date').reindex(date_range)
        instrument_lines.append(f'{symbol}\t{start.strftime("%Y-%m-%d")}\t{end.strftime("%Y-%m-%d")}')
        symbol_dir = features_dir / symbol.lower()
        for field in field_columns:
            write_feature_bin(symbol_dir / f'{field}.day.bin', start_idx, aligned[field])
            feature_files += 1

    if not instrument_lines:
        raise SystemExit('cannot build qlib provider without instruments')
    (instruments_dir / 'all.txt').write_text('\n'.join(instrument_lines) + '\n', encoding='utf-8')
    stats = {
        'version': 'factorforge_qlib_provider_v1',
        'rows': int(len(df)),
        'symbols': int(df['symbol'].nunique()),
        'dates': int(len(calendar)),
        'calendar_start': calendar_strings.iloc[0],
        'calendar_end': calendar_strings.iloc[-1],
        'feature_files': feature_files,
        'provider_dir': str(provider_dir),
        'instrument_style': instrument_style,
        'field_columns': field_columns,
    }
    if source_path is not None:
        stats['source_path'] = str(source_path)
        if source_path.exists() and source_path.is_file():
            stats['source_sha256'] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    (provider_dir / 'provider_metadata.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    return stats


def dump_provider(source_dir: Path, provider_dir: Path) -> None:
    frames = []
    for csv_path in sorted(source_dir.glob('*.csv')):
        frames.append(pd.read_csv(csv_path))
    if not frames:
        raise SystemExit(f'no source CSV files under {source_dir}')
    df = pd.concat(frames, ignore_index=True)
    df['date'] = pd.to_datetime(df['date'], errors='raise')
    build_provider(df, provider_dir)


def raw_format_smoke(provider_dir: Path) -> dict:
    calendar_path = provider_dir / 'calendars' / 'day.txt'
    instrument_path = provider_dir / 'instruments' / 'all.txt'
    features_dir = provider_dir / 'features'
    if not calendar_path.exists():
        raise SystemExit(f'missing qlib calendar: {calendar_path}')
    if not instrument_path.exists():
        raise SystemExit(f'missing qlib instruments: {instrument_path}')
    if not features_dir.exists():
        raise SystemExit(f'missing qlib features dir: {features_dir}')
    calendar = [line.strip() for line in calendar_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    instruments = [line.split('\t')[0] for line in instrument_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not calendar:
        raise SystemExit('empty qlib calendar')
    if not instruments:
        raise SystemExit('empty qlib instruments')
    first = instruments[0]
    first_feature = features_dir / first.lower() / 'close.day.bin'
    if not first_feature.exists():
        raise SystemExit(f'missing first close feature: {first_feature}')
    raw = np.fromfile(first_feature, dtype='<f4')
    if len(raw) < 2:
        raise SystemExit(f'close feature is too short: {first_feature}')
    start_index = int(raw[0])
    values = raw[1:]
    if start_index < 0 or start_index >= len(calendar):
        raise SystemExit(f'invalid qlib feature start_index={start_index} for calendar length={len(calendar)}')
    if start_index + len(values) > len(calendar):
        raise SystemExit(
            f'qlib feature overflows calendar: start_index={start_index}, values={len(values)}, calendar={len(calendar)}'
        )
    return {
        'status': 'PASS',
        'calendar_count': len(calendar),
        'instrument_count': len(instruments),
        'first_instrument': first,
        'first_close_feature': str(first_feature),
        'first_start_index': start_index,
        'first_value_count': int(len(values)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--factorforge-root')
    ap.add_argument('--source')
    ap.add_argument('--source-csv', help='Backward-compatible alias for --source.')
    ap.add_argument('--source-parquet', help='Backward-compatible alias for --source.')
    ap.add_argument('--provider-dir')
    ap.add_argument('--instrument-style', default='ts_code', choices=['ts_code', 'tushare', 'provider', 'legacy_qlib', 'qlib', 'raw'])
    ap.add_argument('--raw-smoke', action='store_true')
    args = ap.parse_args()

    factorforge_root = resolve_factorforge_root(args.factorforge_root)
    source = args.source or args.source_parquet or args.source_csv
    source_path = resolve_source_path(factorforge_root, args.report_id, source)
    provider_dir = (
        Path(args.provider_dir).expanduser().resolve()
        if args.provider_dir
        else factorforge_root / 'runs' / args.report_id / 'qlib_provider'
    )

    df = normalize_source(load_daily_source(source_path), instrument_style=args.instrument_style)
    stats = build_provider(df, provider_dir, instrument_style=args.instrument_style, source_path=source_path)
    print(f'[OK] report_id={args.report_id}')
    print(f'[SOURCE] {source_path}')
    print(f'[PROVIDER] {provider_dir}')
    print('[STATS] ' + json.dumps(stats, ensure_ascii=False, sort_keys=True))
    if args.raw_smoke:
        print('[RAW_SMOKE] ' + json.dumps(raw_format_smoke(provider_dir), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
