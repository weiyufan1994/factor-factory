#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.qlib import (  # noqa: E402
    daily_to_qlib_features, normalize_qlib_instrument, to_qlib_frame,
)
from factor_factory.research_api import _dates  # noqa: E402

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
    return normalize_qlib_instrument(ts_code, style=style)


def normalize_source(df: pd.DataFrame, instrument_style: str = 'ts_code', *,
                     volume_unit='source', amount_unit='source', return_unit='percent',
                     price_basis=None, adjustment_factor_col=None) -> pd.DataFrame:
    """Shared formatter; unspecified price scale stays missing, never factor=1.

    pct_chg is a declared return; a source column named change may be an absolute
    price difference and is not a fallback return. No market values are filled.
    """
    frame = df.copy()
    for name in ('pre_close', 'pct_chg'):
        if name not in frame:
            frame[name] = np.nan
    fields = ['open', 'high', 'low', 'close', 'vol', 'amount', 'pct_chg', 'pre_close']
    mapped = daily_to_qlib_features(
        frame, value_columns=fields, instrument_style=instrument_style,
        rename_fields={x: '$' + {'vol': 'volume', 'pct_chg': 'change'}.get(x, x) for x in fields},
        volume_unit=volume_unit, amount_unit=amount_unit, return_unit=return_unit,
        price_basis=price_basis, adjustment_factor_col=adjustment_factor_col,
    )
    if '$factor' not in mapped:
        mapped['$factor'] = np.nan
    semantics = mapped.attrs['qlib_semantics']
    out = mapped.reset_index().rename(columns={'datetime': 'date', 'instrument': 'symbol',
                                               **{'$' + x: x for x in DEFAULT_FIELD_COLUMNS}})
    out = out[['symbol', 'date', *DEFAULT_FIELD_COLUMNS]].sort_values(['symbol', 'date']).reset_index(drop=True)
    out.attrs['qlib_semantics'] = semantics
    return out


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


def build_provider(df: pd.DataFrame, provider_dir: Path, *, instrument_style: str = 'ts_code',
                   source_path: Path | None = None, calendar=None,
                   instruments: pd.DataFrame | None = None) -> dict:
    """Write supplied data, not a listing/membership inference or backtest.

    Explicit calendar and instrument/start_time/end_time intervals are needed
    for declared semantics. Legacy observed spans remain labeled as such. Gaps
    stay NaN, including entire missing sessions and instruments without bars.
    Inputs are validated before writing; an existing output is never replaced.
    """
    explicit_calendar, explicit_instruments = calendar is not None, instruments is not None
    semantics = dict(df.attrs.get('qlib_semantics', {}))
    mapped = to_qlib_frame(df, DEFAULT_FIELD_COLUMNS, instrument_col='symbol', date_col='date',
                           instrument_style=instrument_style)
    df = mapped.reset_index().rename(columns={'datetime': 'date', 'instrument': 'symbol'})
    calendar = (_dates(calendar, name='provider calendar') if explicit_calendar
                else pd.DatetimeIndex(sorted(df['date'].unique())))
    if calendar.empty:
        raise SystemExit('cannot build qlib provider from empty daily snapshot')
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError('provider calendar must be sorted and unique')
    if not df.date.isin(calendar).all():
        raise ValueError('bar outside provider calendar')
    if explicit_instruments:
        if (not isinstance(instruments, pd.DataFrame) or instruments.columns.has_duplicates
                or set(instruments.columns) != {'instrument', 'start_time', 'end_time'}):
            raise ValueError('instruments requires instrument/start_time/end_time columns')
        spans = instruments.copy()
        spans['instrument'] = spans.instrument.map(lambda x: normalize_qlib_symbol(x, instrument_style))
        for column in ('start_time', 'end_time'):
            spans[column] = _dates(spans[column], name=column)
    else:
        spans = df.groupby('symbol').date.agg(start_time='min', end_time='max').reset_index().rename(columns={'symbol': 'instrument'})
    spans = spans.sort_values(['instrument', 'start_time']).reset_index(drop=True)
    if spans.empty or not set(df.symbol).issubset(set(spans.instrument)):
        raise ValueError('provider instruments missing supplied bar symbols')
    if not spans.instrument.map(lambda x: bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', x))).all():
        raise ValueError('unsafe provider instrument path')
    if spans.instrument.str.lower().nunique() != spans.instrument.nunique():
        raise ValueError('provider instrument directory collision')
    if (not spans.start_time.isin(calendar).all() or not spans.end_time.isin(calendar).all()
            or (spans.start_time > spans.end_time).any()):
        raise ValueError('instrument intervals must use ordered provider sessions')
    bar_groups = df.groupby('symbol', sort=False).indices
    for symbol, group in spans.groupby('instrument', sort=True):
        if (group.start_time <= group.end_time.shift()).any():
            raise ValueError('overlapping instrument intervals')
        dates = df.iloc[bar_groups.get(symbol, [])].date
        inside = pd.Series(False, index=dates.index)
        for row in group.itertuples(index=False):
            inside |= dates.between(row.start_time, row.end_time)
        if not inside.all():
            raise ValueError('bar outside declared instrument intervals')
    with np.errstate(over='ignore'):
        if np.isinf(df[DEFAULT_FIELD_COLUMNS].to_numpy(dtype='float32')).any():
            raise ValueError('feature float32 overflow')
    if len(calendar) > 2**24:
        raise ValueError('calendar index cannot be represented exactly in float32')

    # A compatibility trial must never replace an existing provider, including
    # an empty directory or a symlink. Choose a fresh output path for each build.
    provider_dir.mkdir(parents=True, exist_ok=False)
    calendars_dir, instruments_dir, features_dir = (provider_dir / name for name in ('calendars', 'instruments', 'features'))
    for path in (calendars_dir, instruments_dir, features_dir):
        path.mkdir(parents=True, exist_ok=True)
    calendar_strings = pd.Series(calendar).dt.strftime('%Y-%m-%d')
    (calendars_dir / 'day.txt').write_text('\n'.join(calendar_strings.tolist()) + '\n', encoding='utf-8')

    calendar_pos = {pd.Timestamp(value): idx for idx, value in enumerate(calendar)}
    field_columns = DEFAULT_FIELD_COLUMNS
    instrument_lines: list[str] = []
    feature_files = 0

    for symbol, group in spans.groupby('instrument', sort=True):
        symbol_df = df.iloc[bar_groups.get(symbol, [])]
        start, end = group.start_time.min(), group.end_time.max()
        start_idx = calendar_pos[start]
        end_idx = calendar_pos[end]
        date_range = calendar[start_idx:end_idx + 1]
        aligned = symbol_df.set_index('date').reindex(date_range)
        for row in group.itertuples(index=False):
            instrument_lines.append(f'{symbol}\t{row.start_time:%Y-%m-%d}\t{row.end_time:%Y-%m-%d}')
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
        'symbols': int(spans.instrument.nunique()),
        'dates': int(len(calendar)),
        'calendar_start': calendar_strings.iloc[0],
        'calendar_end': calendar_strings.iloc[-1],
        'feature_files': feature_files,
        'provider_dir': str(provider_dir),
        'instrument_style': instrument_style,
        'field_columns': field_columns,
        'calendar_source': 'explicit_sessions' if explicit_calendar else 'observed_bar_union_not_exchange_calendar',
        'instrument_intervals_source': 'explicit_intervals' if explicit_instruments else 'observed_bar_extent_not_listing_or_membership',
        'instrument_intervals': len(spans),
        'data_semantics': semantics,
        'native_data_contract_declared': native_contract_declared(semantics, explicit_calendar, explicit_instruments),
        'native_execution_equivalence': 'not_verified',
    }
    if source_path is not None:
        stats['source_path'] = str(source_path)
        if source_path.exists() and source_path.is_file():
            stats['source_sha256'] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    (provider_dir / 'provider_metadata.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    return stats


def native_contract_declared(semantics: dict, calendar_supplied: bool, instruments_supplied: bool) -> bool:
    """Declaration completeness only, not provenance or native-engine validation."""
    return bool(calendar_supplied and instruments_supplied
                and semantics.get('price_basis') in {'raw', 'adjusted'}
                and semantics.get('volume_unit') in {'share', 'adjusted_price_units'}
                and semantics.get('amount_unit') == 'cny' and semantics.get('return_unit') == 'decimal')


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


def add_semantic_arguments(parser: argparse.ArgumentParser) -> None:
    """Existing publisher/standalone CLI share the same opt-in contract."""
    parser.add_argument('--calendar-file', help='Explicit CSV/Parquet with one trade_date column.')
    parser.add_argument('--instrument-intervals-file', help='Explicit instrument/start_time/end_time CSV/Parquet.')
    parser.add_argument('--volume-unit', choices=['source', 'lot100', 'share'], default='source')
    parser.add_argument('--amount-unit', choices=['source', 'cny_thousand', 'cny'], default='source')
    parser.add_argument('--return-unit', choices=['source', 'percent', 'decimal'], default='percent')
    parser.add_argument('--price-basis', choices=['raw', 'adjusted'])
    parser.add_argument('--adjustment-factor-column', help='Positive adjusted_price/raw_price scale, not a research signal.')


def semantic_options(args: argparse.Namespace) -> tuple[dict, dict]:
    def read(path):
        p = Path(path).expanduser().resolve()
        if p.suffix.lower() == '.parquet':
            return pd.read_parquet(p)
        if p.suffix.lower() == '.csv':
            return pd.read_csv(p)
        raise ValueError('explicit metadata must be CSV or Parquet')
    provider = {}
    if args.calendar_file:
        calendar = read(args.calendar_file)
        if list(calendar.columns) != ['trade_date']:
            raise ValueError('calendar file must contain only trade_date')
        provider['calendar'] = calendar.trade_date
    if args.instrument_intervals_file:
        provider['instruments'] = read(args.instrument_intervals_file)
    normalizer = dict(volume_unit=args.volume_unit, amount_unit=args.amount_unit,
                      return_unit=args.return_unit, price_basis=args.price_basis,
                      adjustment_factor_col=args.adjustment_factor_column)
    return normalizer, provider


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
    add_semantic_arguments(ap)
    args = ap.parse_args()

    factorforge_root = resolve_factorforge_root(args.factorforge_root)
    source = args.source or args.source_parquet or args.source_csv
    source_path = resolve_source_path(factorforge_root, args.report_id, source)
    provider_dir = (
        Path(args.provider_dir).expanduser().absolute()
        if args.provider_dir
        else factorforge_root / 'runs' / args.report_id / 'qlib_provider'
    )

    normalizer_options, provider_options = semantic_options(args)
    df = normalize_source(load_daily_source(source_path), instrument_style=args.instrument_style, **normalizer_options)
    stats = build_provider(df, provider_dir, instrument_style=args.instrument_style, source_path=source_path, **provider_options)
    print(f'[OK] report_id={args.report_id}')
    print(f'[SOURCE] {source_path}')
    print(f'[PROVIDER] {provider_dir}')
    print('[STATS] ' + json.dumps(stats, ensure_ascii=False, sort_keys=True))
    if args.raw_smoke:
        print('[RAW_SMOKE] ' + json.dumps(raw_format_smoke(provider_dir), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
