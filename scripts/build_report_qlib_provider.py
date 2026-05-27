#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def normalize_source(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out['symbol'] = out['ts_code'].astype(str)
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


def build_provider(df: pd.DataFrame, provider_dir: Path) -> dict:
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
    field_columns = ['open', 'high', 'low', 'close', 'volume', 'factor', 'change', 'amount', 'pre_close']
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
    return {
        'rows': int(len(df)),
        'symbols': int(df['symbol'].nunique()),
        'dates': int(len(calendar)),
        'calendar_start': calendar_strings.iloc[0],
        'calendar_end': calendar_strings.iloc[-1],
        'feature_files': feature_files,
        'provider_dir': str(provider_dir),
    }


def dump_provider(source_dir: Path, provider_dir: Path) -> None:
    frames = []
    for csv_path in sorted(source_dir.glob('*.csv')):
        frames.append(pd.read_csv(csv_path))
    if not frames:
        raise SystemExit(f'no source CSV files under {source_dir}')
    df = pd.concat(frames, ignore_index=True)
    df['date'] = pd.to_datetime(df['date'], errors='raise')
    build_provider(df, provider_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--factorforge-root')
    ap.add_argument('--source')
    ap.add_argument('--source-csv', help='Backward-compatible alias for --source.')
    ap.add_argument('--source-parquet', help='Backward-compatible alias for --source.')
    ap.add_argument('--provider-dir')
    args = ap.parse_args()

    factorforge_root = resolve_factorforge_root(args.factorforge_root)
    source = args.source or args.source_parquet or args.source_csv
    source_path = resolve_source_path(factorforge_root, args.report_id, source)
    provider_dir = (
        Path(args.provider_dir).expanduser().resolve()
        if args.provider_dir
        else factorforge_root / 'runs' / args.report_id / 'qlib_provider'
    )

    df = normalize_source(load_daily_source(source_path))
    stats = build_provider(df, provider_dir)
    print(f'[OK] report_id={args.report_id}')
    print(f'[SOURCE] {source_path}')
    print(f'[PROVIDER] {provider_dir}')
    print('[STATS] ' + json.dumps(stats, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
