"""Content-bound raw minute/daily snapshots for bounded local-IS engineering.

This route reads only declared Parquet files. It never fetches data, constructs
states, infers an investable universe, or supplies research/release approval.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

MODE = 'raw_local_snapshot'
VERSION = 'factorforge_raw_local_snapshot_v1'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _bound_file(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
        raise ValueError('raw snapshot file entry requires path and sha256')
    path = Path(entry['path'])
    if not path.is_absolute() or not path.is_file():
        raise ValueError(f'raw snapshot requires an existing absolute file: {path}')
    if digest(path) != entry.get('sha256'):
        raise ValueError(f'raw snapshot sha256 mismatch: {path}')
    return path.resolve()


def _scope(value):
    symbols, dates = value.get('symbols'), value.get('calendar_dates')
    for name, items in [('symbols', symbols), ('calendar_dates', dates)]:
        if not isinstance(items, list) or not items or not all(isinstance(x, str) and x for x in items):
            raise ValueError(f'raw snapshot requires explicit {name}')
        if items != sorted(set(items)):
            raise ValueError(f'raw snapshot {name} must be sorted and unique')
    for day in dates:
        if len(day) != 8 or datetime.strptime(day, '%Y%m%d').strftime('%Y%m%d') != day:
            raise ValueError('invalid raw snapshot calendar date')
    return symbols, dates


def _frames(section, symbols, dates):
    import pandas as pd
    paths = {role: _bound_file(section[role]) for role in ('daily', 'minute')}
    daily, minute = (pd.read_parquet(paths[role]) for role in ('daily', 'minute'))
    expected = {(symbol, day) for symbol in symbols for day in dates}
    for role, frame, columns in (
        ('daily', daily, {'ts_code', 'trade_date', 'close'}),
        ('minute', minute, {'ts_code', 'trade_date', 'trade_time', 'close', 'vol'}),
    ):
        if not columns <= set(frame.columns) or frame.empty:
            raise ValueError(f'raw {role} snapshot missing required columns or rows')
        pairs = set(zip(frame.ts_code.astype(str), frame.trade_date.astype(str)))
        if pairs != expected:
            raise ValueError(f'raw {role} snapshot differs from declared symbol/date grid')
    if daily.duplicated(['ts_code', 'trade_date']).any():
        raise ValueError('duplicate raw daily keys')
    raw_date = minute.trade_date.astype(str)
    raw_time = minute.trade_time.astype(str).str.strip()
    clock_only = raw_time.str.fullmatch(r'\d{2}:\d{2}:\d{2}')
    full = pd.to_datetime(raw_time.where(~clock_only), errors='coerce', format='mixed')
    # The contract uses exchange-local wall time, with no implicit timezone
    # conversion or mixed-offset interpretation.
    if not pd.api.types.is_datetime64_dtype(full.dtype):
        raise ValueError('raw minute timestamp must be timezone-naive exchange-local time')
    clock = pd.to_datetime(raw_date + ' ' + raw_time.where(clock_only),
                           format='%Y%m%d %H:%M:%S', errors='coerce')
    observed = full.where(~clock_only, clock)
    if observed.isna().any() or observed.dt.strftime('%Y%m%d').ne(raw_date).any():
        raise ValueError('raw minute timestamp date mismatch or invalid timestamp')
    session_close = pd.to_datetime(raw_date, format='%Y%m%d') + pd.Timedelta(hours=15)
    if observed.gt(session_close).any():
        raise ValueError('raw minute observation after session close')
    if minute.assign(_observed=observed).duplicated(['ts_code', '_observed']).any():
        raise ValueError('duplicate raw minute observation keys')
    return paths, daily, minute


def validate_raw_local_inputs(payload, *, sample=False):
    """Verify immutable scope/data again at each physical consumer boundary."""
    if os.getenv('FACTORFORGE_LOCAL_IS_ONLY') != '1':
        raise ValueError('raw snapshot requires local_is_only')
    if not isinstance(payload, dict) or payload.get('input_mode') != MODE:
        raise ValueError('raw snapshot input_mode mismatch')
    allowed = {'input_mode', 'snapshot_manifest_path', 'snapshot_manifest_sha256',
               'daily_df_parquet', 'minute_df_parquet', 'step3b_daily_df_parquet',
               'step3b_minute_df_parquet', 'calendar_dates', 'step3b_calendar_dates',
               'sample_window_actual', 'step3b_sample_window', 'source_identity',
               'signal_timing', 'evaluation_plan'}
    if set(payload) - allowed:
        raise ValueError('raw snapshot forbids undeclared paths, derived states and API fallback')
    manifest_path = _bound_file({'path': payload.get('snapshot_manifest_path'),
                                 'sha256': payload.get('snapshot_manifest_sha256')})
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != VERSION or manifest.get('scope') != 'bounded_local_is_engineering':
        raise ValueError('raw snapshot schema/scope mismatch')
    if manifest.get('signal_timing') != 'after_close_next_session':
        raise ValueError('raw snapshot requires after-close/next-session signal timing')
    identity = manifest.get('source_identity')
    if not isinstance(identity, dict) or not all(identity.get(k) for k in
            ('catalog_sha256', 'daily_dataset_version', 'minute_dataset_version', 'daily_price_basis')):
        raise ValueError('raw snapshot requires explicit source and price identity')
    symbols, dates = _scope(manifest)
    sub = manifest['step3b_sample']
    sample_symbols, sample_dates = _scope(sub)
    if not set(sample_symbols) <= set(symbols) or not set(sample_dates) <= set(dates):
        raise ValueError('raw Step3B sample outside full scope')
    budget = sub.get('budget') or {}
    for key, actual in [('max_symbols', len(sample_symbols)), ('max_calendar_days', len(sample_dates))]:
        limit = budget.get(key)
        if type(limit) is not int or limit < actual:
            raise ValueError(f'raw Step3B sample exceeds explicit {key}')
    # Step3B reads/hashes only its bounded sample files; its manifest pins the
    # full files and Step3A/Step4 validate those independently.
    full_paths = {role: Path(manifest[role]['path']).resolve() for role in ('daily', 'minute')}
    sample_paths = {role: Path(sub[role]['path']).resolve() for role in ('daily', 'minute')}
    if any(full_paths[r] == sample_paths[r] for r in full_paths):
        raise ValueError('raw Step3B requires separate sample files')
    sample_paths, sample_daily, sample_minute = _frames(sub, sample_symbols, sample_dates)
    limit = budget.get('max_minute_rows')
    if type(limit) is not int or limit < len(sample_minute):
        raise ValueError('raw Step3B sample exceeds max_minute_rows')
    if not sample:
        full_paths, daily, minute = _frames(manifest, symbols, dates)
        import pandas as pd
        for full, small, keys in [(daily, sample_daily, ['ts_code', 'trade_date']),
                                  (minute, sample_minute, ['ts_code', 'trade_date', 'trade_time'])]:
            expected = full[full.ts_code.astype(str).isin(sample_symbols)
                            & full.trade_date.astype(str).isin(sample_dates)]
            pd.testing.assert_frame_equal(expected.sort_values(keys).reset_index(drop=True),
                                          small.sort_values(keys).reset_index(drop=True), check_exact=True)
    normalized = {
        'input_mode': MODE, 'snapshot_manifest_path': str(manifest_path),
        'snapshot_manifest_sha256': payload['snapshot_manifest_sha256'],
        'daily_df_parquet': str(full_paths['daily']), 'minute_df_parquet': str(full_paths['minute']),
        'step3b_daily_df_parquet': str(sample_paths['daily']),
        'step3b_minute_df_parquet': str(sample_paths['minute']),
        'calendar_dates': dates, 'step3b_calendar_dates': sample_dates,
        'sample_window_actual': {'start': dates[0], 'end': dates[-1]},
        'step3b_sample_window': {'start': sample_dates[0], 'end': sample_dates[-1]},
        'source_identity': identity, 'signal_timing': manifest['signal_timing'],
    }
    if 'evaluation_plan' in manifest:
        normalized['evaluation_plan'] = manifest['evaluation_plan']
    for key, value in payload.items():
        if normalized.get(key) != value:
            raise ValueError(f'raw snapshot declaration differs from bound manifest: {key}')
    if sample:
        normalized.update(daily_df_parquet=str(sample_paths['daily']),
                          minute_df_parquet=str(sample_paths['minute']),
                          calendar_dates=sample_dates,
                          sample_window_actual=normalized['step3b_sample_window'])
    return normalized


def load_raw_local_inputs(path):
    if not path:
        return None
    return validate_raw_local_inputs(json.loads(Path(path).read_text()))
