"""SDK-backed, bounded PF/VV day preparation with verified checkpoints.

Each worker owns a complete source day. Only reduced daily outputs leave the
worker; the existing rolling controller consumes the final calendar order.
"""
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import asdict
from functools import lru_cache
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import resource
import sys
import time
import uuid
import pandas as pd
import tempfile

from factorforge_data_api import DataApiClient, DataQuery
from factorforge_data_api.runtime import ReadPolicy
from factorforge_data_api.backends.cache import cache_lock, file_sha256
from factorforge_data_api.backends.scanning import datasets, reservation_bytes
from factorforge_data_api import snapshots


@lru_cache(maxsize=4)
def _producer(path):
    spec = importlib.util.spec_from_file_location('pfvv_sdk_day_producer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_identity(producer_path):
    import factorforge_data_api
    sdk = Path(factorforge_data_api.__file__).resolve().parent
    source = Path(producer_path).resolve().parent
    files = {f'sdk/{p.relative_to(sdk)}': file_sha256(p) for p in sdk.rglob('*.py')}
    for name in ['pfvv_daily_measurements_v1.py', 'pfvv_source_baseline_partitioned_v1.py',
                 'pfvv_source_baseline_dataframe_adapter_v1.py', 'pfvv_source_baseline_v1.py']:
        files[f'producer/{name}'] = file_sha256(source/name)
    files['factor_factory/pfvv_preparation.py'] = file_sha256(__file__)
    return {'files': files, 'sha256': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def day_query(day, calendar_identity):
    return DataQuery('minute_bar', day, day, 'a_share_all',
        ['open', 'high', 'low', 'close', 'vol', 'amount'], '1min',
        expected_trade_dates=(day,), calendar_identity=calendar_identity,
        # Preserve the frozen consumer's narrower symbol/window duplicate rule.
        # Raw duplicates are still reported by SDK; consumer validation decides.
        allow_duplicate_keys=True)


def input_identity(client, query):
    entry = client.read_policy.resolve_entry(client.catalog.datasets['minute_bar'], operation='iter_days')
    objects = []
    for dataset, _, receipts in datasets(entry, query):
        if receipts:
            objects.extend({'uri': r['uri'], 'sha256': r['sha256'], 'bytes': r['bytes']} for r in receipts)
        else:
            for filename in dataset.files:
                path = Path(filename)
                if not path.is_file():
                    raise ValueError('checkpoint input identity requires local bytes or verified SDK cache')
                objects.append({'uri': str(path.resolve()), 'sha256': file_sha256(path), 'bytes': path.stat().st_size})
    return sorted(objects, key=lambda r: r['uri'])


def _worker(config, day):
    started = time.time()
    client = DataApiClient.from_catalog(config['catalog_path'], expected_sha256=config['catalog_sha256'],
        source_uri=config['catalog_source'], read_policy=ReadPolicy(**config['read_policy']))
    query = day_query(day, config['calendar_identity'])
    if config.get('snapshot') is None:
        # Standalone worker callers still bind bytes before validation/fetch.
        with tempfile.TemporaryDirectory(prefix='pfvv-date-snapshot-') as root:
            snapshot = client.capture_snapshot(query, root=root)
            return _worker({**config, 'snapshot': snapshot}, day)
    snapshot = config['snapshot']
    snapshots.validate(snapshot, client, query)
    before = sorted([{'uri': r['uri'], 'sha256': r['sha256'], 'bytes': r['bytes']}
        for r in snapshot['source_objects']], key=lambda r: r['uri'])
    if not before:
        raise ValueError(f'missing source day: {day}')
    # The frozen raw producer rejected cross-day rows before selecting symbols.
    # Check date/time columns without a predicate so SDK pushdown cannot hide
    # malformed rows in an otherwise plausible daily object.
    from factorforge_data_api.delivery import normalize_dates
    for dataset, _, _ in snapshots.scan(snapshot):
        columns = [c for c in ('trade_time', 'trade_date') if c in dataset.schema.names]
        for batch in dataset.scanner(columns=columns, batch_size=65536, batch_readahead=1,
                                     fragment_readahead=1).to_batches():
            dates = batch.to_pandas()
            if 'trade_time' not in dates:
                raise ValueError('raw PF/VV object requires trade_time')
            timestamps = pd.to_datetime(dates.trade_time, errors='raise')
            if timestamps.dt.tz is not None or not timestamps.dt.normalize().eq(pd.Timestamp(day)).all():
                raise ValueError('raw PF/VV object contains timestamps outside its requested naive day')
            if 'trade_date' in dates and not normalize_dates(dates.trade_date).eq(day).all():
                raise ValueError('raw PF/VV object trade_date differs from requested day')
    result = client.fetch(query, snapshot=snapshot)
    if result.status not in {'ready', 'proxy_ready'}:
        raise ValueError(f'SDK minute read blocked: {result.blocked_reason}')
    producer = _producer(config['producer_path'])
    measurements, prices, facts = producer.compute_daily_bundle(result.frame, day,
        normalized_minute=result.normalized_minute)
    actual = sorted([{'uri': r['uri'], 'sha256': r['sha256'], 'bytes': r['bytes']}
        for r in result.performance_profile.get('source_objects', [])], key=lambda r: r['uri'])
    if before != actual or result.performance_profile.get('query_snapshot_sha256') != snapshot['snapshot_sha256']:
        raise ValueError(f'actual SDK read differs from fixed day snapshot: {day}')
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    telemetry = {'pid': os.getpid(), 'started_at_unix': started, 'finished_at_unix': time.time(),
        'peak_worker_rss_bytes': peak if sys.platform == 'darwin' else peak * 1024,
        'input_objects': before, 'SDK_source': result.to_metadata()['source'],
        'SDK_coverage': result.to_metadata()['coverage'], 'SDK_profile': result.performance_profile,
        'query_snapshot_sha256': snapshot['snapshot_sha256']}
    return measurements, prices, facts, telemetry


def _atomic_json(path, value):
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with tmp.open('x') as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write('\n')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def materialize_sdk(plan, output_root, client, *, producer_path, workers=1,
                    memory_budget_bytes=2*1024**3, resume=False, prewarm=False,
                    calendar_identity=None):
    producer_path = str(Path(producer_path).resolve())
    producer = _producer(producer_path)
    days = producer.validate_plan(plan)
    root = Path(output_root)
    if not root.is_absolute() or root.parent.resolve() != root.parent or '..' in root.parts:
        raise ValueError('output_must_be_absolute_resolved_child')
    if root.exists() and not resume:
        raise ValueError('output_must_be_new_unless_resume_is_explicit')
    if not root.parent.is_dir() or workers < 1 or memory_budget_bytes <= 0:
        raise ValueError('invalid output parent or resource budget')
    entry = client.catalog.datasets['minute_bar']
    expected_uri = f's3://{producer.SOURCE_BUCKET}/{producer.SOURCE_PREFIX}'
    if entry.uri.startswith('s3://') and entry.uri.rstrip('/') != expected_uri.rstrip('/'):
        raise ValueError('SDK source route does not match frozen source plan')
    root.mkdir(exist_ok=resume)
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    calendar_identity = calendar_identity or f'explicit_source_plan:{plan_hash}'
    identity = {'plan_sha256': plan_hash, 'catalog_binding': client.catalog.binding('minute_bar'),
                'code_identity': code_identity(producer_path), 'calendar_identity': calendar_identity,
                'source_policy': asdict(client.read_policy),
                'preparation_parameters': {'workers': workers, 'memory_budget_bytes': memory_budget_bytes,
                    'prewarm': prewarm}}
    config = {'catalog_path': str(client.catalog.path), 'catalog_sha256': client.catalog.sha256,
        'catalog_source': client.catalog.source_uri, 'read_policy': asdict(client.read_policy),
        'calendar_identity': calendar_identity, 'producer_path': producer_path}
    with cache_lock(root/'.preparation'):
        header = root/'preparation_identity.json'
        if header.exists():
            if json.loads(header.read_text()) != identity:
                raise ValueError('resume_plan_catalog_or_code_identity_mismatch')
        else:
            _atomic_json(header, identity)
            _atomic_json(root/'source_plan.json', plan)
        if prewarm:
            query = DataQuery('minute_bar', days[0], days[-1], 'a_share_all', ['close'], '1min',
                expected_trade_dates=tuple(days), calendar_identity=calendar_identity)
            receipt = client.prewarm(query, workers=workers, max_inflight_bytes=min(memory_budget_bytes, 256*1024**2))
            _atomic_json(root/('prewarm-' + uuid.uuid4().hex + '.json'), receipt)
        rows, pending_days = {}, []
        for day in days:
            checkpoint = root/f'checkpoint_{day}.json'
            if checkpoint.exists():
                row = json.loads(checkpoint.read_text())
                try:
                    matches = (row.get('identity_sha256') == identity['code_identity']['sha256']
                        and file_sha256(root/row['path']) == row['output_sha256']
                        and file_sha256(root/row['execution_path']) == row['execution_sha256']
                        and input_identity(client, day_query(day, calendar_identity)) == row['input_objects'])
                except (ValueError, OSError, KeyError) as exc:
                    raise ValueError(f'resume_input_code_or_output_identity_mismatch: {day}') from exc
                if not matches:
                    raise ValueError(f'resume_input_code_or_output_identity_mismatch: {day}')
                rows[day] = row
            else:
                pending_days.append(day)
        pending, reserved, max_reserved = {}, 0, 0
        cursor = 0
        next_job = None
        effective_entry = client.read_policy.resolve_entry(entry, operation='iter_days')
        try:
            with ProcessPoolExecutor(max_workers=min(workers, max(1, len(pending_days))),
                    mp_context=multiprocessing.get_context('spawn')) as pool:
                while cursor < len(pending_days) or pending or next_job:
                    while len(pending) < workers and cursor < len(pending_days):
                        if next_job is None:
                            day = pending_days[cursor]
                            query = day_query(day, calendar_identity)
                            resolved, missing, _ = client._resolve_fields(entry, query.fields)
                            if missing:
                                raise ValueError(f'missing PF/VV source fields: {missing}')
                            # Fixed PF/VV panel allowance plus SDK decoded input reservation.
                            snapshot = client.capture_snapshot(query, root=root/'input_snapshots')
                            reserve = 512*1024**2 + snapshots.reservation_bytes(snapshot,
                                client._projection_columns(entry, query, resolved))
                            if reserve > memory_budget_bytes:
                                raise MemoryError(f'PF/VV day reservation {reserve} exceeds total budget {memory_budget_bytes}')
                            next_job = day, reserve, snapshot
                        day, reserve, snapshot = next_job
                        if reserved + reserve > memory_budget_bytes:
                            break
                        future = pool.submit(_worker, {**config, 'snapshot': snapshot}, day)
                        pending[future] = (day, reserve)
                        reserved += reserve; max_reserved = max(max_reserved, reserved)
                        cursor += 1; next_job = None
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        day, reserve = pending.pop(future)
                        measurements, prices, facts, telemetry = future.result()
                        path, price_path = root/f'daily_{day}.parquet', root/f'execution_{day}.parquet'
                        for frame, target in [(measurements, path), (prices, price_path)]:
                            temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex)
                            try:
                                frame.to_parquet(temporary, index=False)
                                temporary.replace(target)
                            finally:
                                temporary.unlink(missing_ok=True)
                        objects = telemetry['input_objects']
                        row = {'trade_date': day, 'path': path.name, 'rows': len(measurements),
                            'execution_path': price_path.name, 'execution_sha256': file_sha256(price_path),
                            'output_sha256': file_sha256(path), 'source_uri': entry.uri,
                            'source_bytes': sum(r['bytes'] for r in objects),
                            'source_sha256': objects[0]['sha256'] if len(objects) == 1 else hashlib.sha256(json.dumps(objects, sort_keys=True).encode()).hexdigest(),
                            'source_identity': objects, 'input_objects': objects,
                            'identity_sha256': identity['code_identity']['sha256'],
                            'coverage': facts, 'telemetry': telemetry, 'memory_reservation_bytes': reserve}
                        _atomic_json(root/f'checkpoint_{day}.json', row)
                        rows[day] = row; reserved -= reserve
            if code_identity(producer_path) != identity['code_identity']:
                raise ValueError('code changed during preparation')
            ordered = [rows[day] for day in days]
            result = {'version': 'pfvv_daily_measurements_manifest_v1', 'status': 'COMPLETE',
                'research_id': plan['research_id'], 'trading_calendar': days, 'days': ordered,
                'columns': ['ts_code', 'trade_date', 'pf_daily', 'vv_daily'],
                'domain': 'OBSERVED_SH_SZ_A_SHARE_MINUTE_CROSS_SECTION',
                'vv_cs_standardized': False, 'rolling_applied': False,
                'pfvv_prepared_daily_state': {'contract_version': 'pfvv_prepared_daily_state_v1',
                    'measurement_authority': 'pfvv_source_baseline_v1', 'calendar_dates': days,
                    'day_paths': {r['trade_date']: r['path'] for r in ordered},
                    'required_columns': ['ts_code', 'trade_date', 'pf_daily', 'vv_daily']},
                'preparation_identity': identity, 'factor_returns_evaluated': False, 'oos_accessed': False,
                'performance': {'requested_workers': workers, 'memory_budget_bytes': memory_budget_bytes,
                    'max_reserved_bytes': max_reserved, 'days_reused': len(days)-len(pending_days),
                    'new_days': len(pending_days), 'worker_pids': sorted({r['telemetry']['pid'] for r in ordered})}}
            final = root/'daily_measurements_manifest.json'
            if final.exists():
                receipt_path = root/'completion_receipt.json'
                if not receipt_path.exists() or json.loads(receipt_path.read_text()).get('manifest_sha256') != file_sha256(final):
                    raise ValueError('completed_manifest_identity_mismatch')
                existing = json.loads(final.read_text())
                if {k: v for k, v in existing.items() if k != 'performance'} != {k: v for k, v in result.items() if k != 'performance'}:
                    raise ValueError('completed_manifest_semantics_conflict_with_verified_checkpoints')
                return {**existing, 'resume_verified': True}
            _atomic_json(final, result)
            _atomic_json(root/'completion_receipt.json', {'manifest_sha256': file_sha256(final)})
            return result
        except BaseException as exc:
            for future in pending:
                future.cancel()
            _atomic_json(root/('failure-' + uuid.uuid4().hex + '.json'), {'status': 'PARTIAL_CHECKPOINTS_REQUIRE_VERIFICATION',
                'completed_dates': sorted(rows), 'error': f'{type(exc).__name__}: {exc}', 'auto_retry': False})
            raise
