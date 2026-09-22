import hashlib
import json
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from factor_factory.data_api import fetch_data_api_dataset, resolve_data_api_dataset


@pytest.mark.parametrize('dataset', ['clean_daily_bar', 'daily_basic'])
@pytest.mark.parametrize('explicit', [True, False])
def test_explicit_catalog_cannot_be_overridden_by_another_hot_local_version(tmp_path, monkeypatch, dataset, explicit):
    cold, hot = tmp_path / 'v1.parquet', tmp_path / 'v2.parquet'
    frame = pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['20160104'], 'close': [10.]})
    frame.to_parquet(cold, index=False)
    frame.assign(close=999.).to_parquet(hot, index=False)
    monkeypatch.setenv('FACTORFORGE_CLEAN_DAILY_PARQUET', str(hot))
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'datasets': {dataset: {'uri': str(cold), 'version': 'frozen-v1',
        'format': 'parquet', 'columns': list(frame)}}}))
    resolution = resolve_data_api_dataset(dataset, start='20160104', end='20160104', fields=['close'], catalog_path=catalog)
    digest = resolution['catalog_binding']['catalog_sha256']
    monkeypatch.setenv('FACTORFORGE_DATA_CATALOG', str(catalog))
    kwargs = {'catalog_path': catalog, 'catalog_sha256': digest} if explicit else {}
    result = fetch_data_api_dataset(dataset, start='20160104', end='20160104', fields=['close'],
        **kwargs)
    assert result.frame.close.tolist() == [10.]
    assert result.source.uri == str(cold)
    assert result.source.dataset_version == 'frozen-v1'
    assert result.source.catalog_sha256 == digest
    catalog.write_text(catalog.read_text() + '\n')
    with pytest.raises(ValueError, match='catalog_hash_mismatch'):
        fetch_data_api_dataset(dataset, start='20160104', end='20160104', fields=['close'],
            catalog_path=catalog, catalog_sha256=digest)


def test_step4_consumes_the_catalog_pin_from_step3_contract(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step4/scripts/run_step4.py'
    spec = importlib.util.spec_from_file_location('pinned_step4', path)
    step4 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step4)
    frame = pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['20160104'], 'close': [10.]})
    data = tmp_path / 'daily.parquet'
    frame.to_parquet(data, index=False)
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'datasets': {'clean_daily_bar': {'uri': str(data), 'format': 'parquet', 'columns': list(frame)}}}))
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    contract = {'full_queries': {'clean_daily_bar': {'dataset': 'clean_daily_bar', 'start_date': '20160104',
        'end_date': '20160104', 'fields': ['close']}}, 'catalog_bindings': {'clean_daily_bar': {
            'catalog_path': str(catalog), 'catalog_sha256': digest}}}
    query = step4._contract_query(contract, 'full_queries', 'clean_daily_bar')
    assert step4._fetch_contract_frame(query)[0].close.tolist() == [10.]
    catalog.write_text(catalog.read_text() + '\n')
    with pytest.raises(ValueError, match='catalog_hash_mismatch'):
        step4._fetch_contract_frame(query)


def test_resolution_metadata_and_hash_use_one_atomic_byte_snapshot(tmp_path, monkeypatch):
    catalog = tmp_path / 'catalog.json'
    original = {'datasets': {'clean_daily_bar': {'uri': 's3://bucket/v1/data.parquet', 'version': 'v1',
        'format': 'parquet', 'columns': ['ts_code', 'trade_date', 'close']}}}
    first = json.dumps(original).encode()
    catalog.write_bytes(first)
    changed = json.loads(first)
    changed['datasets']['clean_daily_bar'].update(uri='s3://bucket/v2/data.parquet', version='v2')
    second = json.dumps(changed).encode()
    read = Path.read_bytes
    reads = []
    def racing_read(path):
        result = read(path)
        if path == catalog:
            reads.append(1)
            catalog.write_bytes(second)
        return result
    monkeypatch.setattr(Path, 'read_bytes', racing_read)
    resolved = resolve_data_api_dataset('clean_daily_bar', start='20160104', end='20160104', catalog_path=catalog)
    assert resolved['metadata']['dataset_version'] == 'v1'
    assert resolved['catalog_binding']['catalog_sha256'] == hashlib.sha256(first).hexdigest()
    assert len(reads) == 1
    with pytest.raises(ValueError, match='catalog_hash_mismatch'):
        fetch_data_api_dataset('clean_daily_bar', start='20160104', end='20160104', fields=['close'],
            catalog_path=catalog, catalog_sha256=resolved['catalog_binding']['catalog_sha256'])


@pytest.mark.parametrize('target', ['clean_daily_bar', 'minute_bar', 'daily_basic'])
def test_step3_samples_reject_catalog_change_between_resolution_and_fetch(tmp_path, monkeypatch, target):
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step3/scripts/run_step3.py'
    spec = importlib.util.spec_from_file_location('pinned_step3', path)
    step3 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step3)
    monkeypatch.setattr(step3, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(step3, 'WORKSPACE', tmp_path)
    catalog = tmp_path / 'catalog.json'
    catalog.write_text('{"datasets": {}}')
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    def resolve(dataset, **kwargs):
        return {'dataset_id': dataset, 'status': 'ready', 'catalog_path': str(catalog),
            'catalog_binding': {'catalog_sha256': digest}, 'schema': {'columns': []}}
    frame = pd.DataFrame({'ts_code': ['000001.SZ'], 'trade_date': ['20160104'], 'close': [10.]})
    def fetch(dataset, **kwargs):
        assert kwargs.get('catalog_sha256') == digest
        if dataset == target:
            catalog.write_text(catalog.read_text() + '\n')
            return fetch_data_api_dataset(dataset, **kwargs)
        return SimpleNamespace(frame=frame, status='ready', to_metadata=lambda: {})
    monkeypatch.setattr(step3, 'resolve_data_api_dataset', resolve)
    monkeypatch.setattr(step3, 'fetch_data_api_dataset', fetch)
    with pytest.raises(ValueError, match='catalog_hash_mismatch'):
        step3.build_local_price_volume_snapshots('PIN_TEST', {'start': '2016-01-04', 'end': '2016-01-05'}, required_fields=['pe'])


def test_parallel_bridge_transport_never_changes_arrow_global_constructor():
    import pyarrow.fs as fs
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from factor_factory.data_api.client import _hardened_pyarrow_s3_transport
    constructor = fs.S3FileSystem
    barrier = Barrier(2)
    def enter(_):
        with _hardened_pyarrow_s3_transport():
            barrier.wait(timeout=5)
            assert fs.S3FileSystem is constructor
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(enter, range(2)))
    assert fs.S3FileSystem is constructor
