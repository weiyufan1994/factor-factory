"""Bind existing prepared observations to the standard Step3/4 input format.

No data fetch, producer execution, factor computation or registry lives here.
The research author supplies the reviewed producer/controller and observation
contract; this module removes repeated path, scope and byte-identity wiring.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

_BIND_KEYS = ('input_mode', 'daily_df_parquet', 'signal_daily_df_parquet',
              'evaluation_daily_df_parquet', 'derived_state_root',
              'partition_manifest_path', 'partition_manifest_sha256',
              'calendar_dates', 'sample_window_actual',
              'step3b_daily_df_parquet', 'step3b_derived_state_root',
              'step3b_partition_manifest_path', 'step3b_partition_manifest_sha256',
              'step3b_calendar_dates', 'step3b_sample_window',
              'step3b_prepared_controller_config', 'signal_timing',
              'prepared_input_hashes')


def _binding_hash(inputs):
    return hashlib.sha256(json.dumps({k: inputs.get(k) for k in _BIND_KEYS},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _file(value, base: Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve(strict=True)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _calendar(values, window, role):
    from datetime import datetime
    if not isinstance(values, list) or not values:
        raise ValueError(f'prepared {role}: explicit calendar_dates required')
    days = [str(v) for v in values]
    for day in days:
        datetime.strptime(day, '%Y%m%d')
        if len(day) != 8:
            raise ValueError(f'prepared {role}: YYYYMMDD dates required')
    if days != sorted(set(days)) or window != {'start': days[0], 'end': days[-1]}:
        raise ValueError(f'prepared {role}: calendar/window mismatch')
    return days


def _daily(path, days, role, *, db, table, prices=False):
    import pyarrow.parquet as pq
    import pandas as pd
    source = pq.ParquetFile(path)
    required = {'ts_code', 'trade_date'} | ({'close'} if prices else set())
    if not required <= set(source.schema_arrow.names):
        raise ValueError(f'prepared {role}: missing columns {sorted(required - set(source.schema_arrow.names))}')
    if table not in {'signal', 'sample', 'prices'}:
        raise ValueError('invalid internal key table')
    db.execute(f'CREATE TABLE {table} (symbol TEXT, day TEXT, PRIMARY KEY(symbol, day)) WITHOUT ROWID')
    observed, symbols = set(), set()
    for batch in source.iter_batches(columns=['trade_date', 'ts_code'], batch_size=65536):
        frame = batch.to_pandas()
        if frame.isna().any().any():
            raise ValueError(f'prepared {role}: null observation keys')
        symbols.update(frame['ts_code'].astype(str))
        values = frame['trade_date'].astype(str).str.replace('-', '', regex=False).str[:8]
        pd.to_datetime(values, format='%Y%m%d', errors='raise')
        observed.update(values)
        try:
            db.executemany(f'INSERT INTO {table} VALUES (?, ?)', zip(frame['ts_code'].astype(str), values))
        except sqlite3.IntegrityError as exc:
            raise ValueError(f'prepared {role}: duplicate (ts_code, trade_date)') from exc
    if observed != set(days):
        raise ValueError(f'prepared {role}: actual dates differ from declared calendar')
    return symbols


def _daily_domains(payload, full_days, sample_days):
    # Disk-backed keys avoid retaining a full-market multi-year price table in
    # memory. This temporary validation index is removed when binding finishes.
    with tempfile.TemporaryDirectory(prefix='factorforge-input-keys-') as root:
        with sqlite3.connect(str(Path(root) / 'keys.sqlite')) as db:
            full = _daily(payload['daily_df_parquet'], full_days, 'signal daily', db=db, table='signal')
            sample = _daily(payload['step3b_daily_df_parquet'], sample_days, 'sample daily', db=db, table='sample')
            _daily(payload['evaluation_daily_df_parquet'], full_days, 'evaluation daily', db=db, table='prices', prices=True)
            for left, right in (('sample', 'signal'), ('signal', 'prices')):
                missing = db.execute(f'SELECT symbol,day FROM {left} EXCEPT SELECT symbol,day FROM {right} LIMIT 1').fetchone()
                if missing:
                    raise ValueError(f'prepared symbol/date coverage mismatch: {left} key {missing} missing in {right}')
    return full, sample


def _manifest_files(inputs, base, prefix=''):
    """Inspect the existing partition manifest; never select files by recency."""
    key = prefix + 'partition_manifest_path'
    if not inputs.get(key):
        raise ValueError(f'prepared reuse requires {key}; keep custom controllers on their existing route')
    path = _file(inputs[key], base)
    if _sha(path) != inputs.get(prefix + 'partition_manifest_sha256'):
        raise ValueError(f'prepared {key}: manifest hash mismatch')
    manifest = json.loads(path.read_text())
    root = _file(inputs[prefix + 'derived_state_root'], base)
    days = inputs[prefix + 'calendar_dates']
    if manifest.get('calendar_dates') != days or set(manifest.get('partitions', {})) != set(days):
        raise ValueError(f'prepared {key}: partition calendar mismatch')
    files = [path]
    for day, part in manifest['partitions'].items():
        rel = Path(part['relative_path'])
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'prepared {day}: partition path escapes state root')
        target = (root / rel).resolve(strict=True)
        if not target.is_relative_to(root) or _sha(target) != part.get('sha256'):
            raise ValueError(f'prepared {day}: partition hash/path mismatch')
        files.append(target)
    return files


def verify_prepared_binding(inputs: dict, *, base_dir: Path) -> None:
    """Recheck opt-in bindings at actual Step3 and Step4 consumption.

Older declarations retain their existing controller validation. An identity
check is not a substitute for Step2's mathematical review or controller checks.
"""
    hashes = inputs.get('prepared_input_hashes')
    if hashes is None:
        return
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('prepared input hash inventory is empty')
    if inputs.get('prepared_input_binding_sha256') != _binding_hash(inputs):
        raise ValueError('prepared input selectors/identity changed; bind a new declaration')
    for name, expected in hashes.items():
        if _sha(_file(name, base_dir)) != expected:
            raise ValueError(f'prepared input changed: {name}')


def bind_prepared_inputs(full_inputs: dict, *, sample_controller: Path,
                         evaluation_daily: Path, base_dir: Path,
                         dependencies: tuple[Path, ...] = ()) -> dict:
    """Return a reusable declaration without copying or modifying any data.

Use existing full prepared metadata and the independently bounded Step3B
controller. Evaluation prices are mandatory; a key-only state carrier cannot
silently become the evaluator's market data. Relative paths use base_dir.
Dependencies are the reviewed producer, consumer and invoked helper files.
"""
    base = Path(base_dir).resolve(strict=True)
    payload = copy.deepcopy(full_inputs)
    if payload.get('input_mode') != 'derived_state_with_daily':
        raise ValueError('prepared binding requires derived_state_with_daily; use the ordinary daily API for daily factors')
    if any(payload.get(k) for k in ('minute_df_parquet', 'minute_df_csv', 'minute_streaming_query')):
        raise ValueError('prepared binding cannot read or declare raw minute inputs')
    config_path = _file(sample_controller, base)
    config = json.loads(config_path.read_text())
    sample = config['local_inputs']
    if config.get('controller') != 'sample' or sample.get('input_mode') != payload['input_mode']:
        raise ValueError('prepared Step3B controller/mode mismatch')
    full_days = _calendar(payload.get('calendar_dates'), payload.get('sample_window_actual'), 'full')
    sample_days = _calendar(sample.get('calendar_dates'), sample.get('sample_window_actual'), 'sample')
    budget = config.get('sample_budget', {}).get('max_calendar_days')
    if type(budget) is not int or budget < len(sample_days) or not set(sample_days) <= set(full_days):
        raise ValueError('prepared sample outside full calendar or sample budget')
    for key in ('daily_df_parquet', 'derived_state_root', 'partition_manifest_path'):
        payload[key] = str(_file(payload[key], base))
        payload['step3b_' + key] = str(_file(sample[key], base))
    # The actual controller will interpret its own paths; do not silently
    # rebase a relative config differently from the native Step3B consumer.
    for key in ('daily_df_parquet', 'derived_state_root', 'partition_manifest_path'):
        if not Path(sample[key]).is_absolute():
            raise ValueError(f'prepared sample controller requires absolute {key}')
    payload.update(step3b_calendar_dates=sample_days,
                   step3b_sample_window=dict(sample['sample_window_actual']),
                   step3b_partition_manifest_sha256=sample['partition_manifest_sha256'],
                   step3b_prepared_controller_config=str(config_path),
                   signal_daily_df_parquet=payload['daily_df_parquet'],
                   evaluation_daily_df_parquet=str(_file(evaluation_daily, base)))
    payload.pop('run_config_path', None)
    payload.pop('step3b_run_config_path', None)
    full_symbols, sample_symbols = _daily_domains(payload, full_days, sample_days)
    max_symbols = config.get('sample_budget', {}).get('max_symbols')
    if max_symbols is not None and (type(max_symbols) is not int or len(sample_symbols) > max_symbols):
        raise ValueError('prepared sample exceeds symbol budget')
    if sample_days != full_days:
        for key in ('daily_df_parquet', 'derived_state_root'):
            if payload[key] == payload['step3b_' + key]:
                raise ValueError(f'prepared full/sample alias: {key}')
    files = [config_path, Path(payload['daily_df_parquet']),
             Path(payload['step3b_daily_df_parquet']), Path(payload['evaluation_daily_df_parquet'])]
    files += _manifest_files(payload, base) + _manifest_files(payload, base, 'step3b_')
    if not dependencies:
        raise ValueError('prepared binding requires reviewed producer/consumer/helper dependencies')
    files += [_file(p, base) for p in dependencies]
    # Additive metadata within the existing prepared input object, no registry.
    payload['prepared_input_hashes'] = {str(p): _sha(p) for p in sorted(set(files))}
    payload['prepared_input_binding_sha256'] = _binding_hash(payload)
    verify_prepared_binding(payload, base_dir=base)
    return payload


def write_prepared_inputs(path: Path, payload: dict) -> None:
    """A second binding must have a new name; never rewrite old study inputs."""
    with Path(path).open('x') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
