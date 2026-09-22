import json
from pathlib import Path

import pandas as pd
import pytest

from factorforge_data_api import DataApiClient
from factor_factory.pfvv_preparation import materialize_sdk
from test_mszq_pfvv_daily_measurements_v1 import source, plan
from test_mszq_pfvv_source_baseline_partitioned_v1 import load_module


PRODUCER = Path(__file__).resolve().parents[1]/'examples/mszq_intraday_momentum_pulse/pfvv_daily_measurements_v1.py'


def setup(tmp_path, days=3):
    producer = load_module('sdk_preparation_test_producer', PRODUCER)
    frame, calendar = source(days)
    root = tmp_path/'minute'
    for day in calendar.trade_date:
        partition = root/f'trade_date={day}'
        partition.mkdir(parents=True)
        frame.loc[frame.trade_time.dt.normalize().eq(pd.Timestamp(day))].assign(trade_date=day).to_parquet(partition/'data.parquet', index=False)
    catalog = tmp_path/'catalog.json'
    catalog.write_text(json.dumps({'datasets': {'minute_bar': {'uri': str(root), 'format': 'parquet',
        'version': 'synthetic_frozen', 'columns': [*frame.columns, 'trade_date'], 'partition_columns': ['trade_date']}}}))
    return producer, calendar, DataApiClient.from_catalog(catalog), root


def test_sdk_parallel_daily_producer_matches_reference_math_and_retains_calendar_order(tmp_path):
    producer, calendar, client, source_root = setup(tmp_path)
    manifest = materialize_sdk(plan(producer, calendar), tmp_path/'out', client, producer_path=PRODUCER,
        workers=2, memory_budget_bytes=2*1024**3)
    assert [r['trade_date'] for r in manifest['days']] == calendar.trade_date.tolist()
    for row in manifest['days']:
        raw = pd.read_parquet(source_root/f"trade_date={row['trade_date']}"/'data.parquet')
        validated, codes = producer._ADAPTER._validate_minute_rows(raw, pd.DatetimeIndex([pd.Timestamp(row['trade_date'])]))
        close, opening, volume = producer._ADAPTER._one_day_panels(validated, pd.Timestamp(row['trade_date']), codes)
        returns = producer._KERNEL.minute_returns(close, opening)
        actual = pd.read_parquet(tmp_path/'out'/row['path']).set_index('ts_code')
        pd.testing.assert_series_equal(actual.pf_daily, producer._KERNEL.pf_daily(returns)['daily'], check_names=False)
        pd.testing.assert_series_equal(actual.vv_daily, producer._KERNEL.vv_daily(returns, volume)['daily'], check_names=False)
        assert row['telemetry']['SDK_source']['catalog_sha256'] == client.catalog.sha256
    assert manifest['performance']['max_reserved_bytes'] <= 2*1024**3
    assert manifest['pfvv_prepared_daily_state']['calendar_dates'] == calendar.trade_date.tolist()


def test_partial_failure_resumes_only_after_input_code_and_output_verification(tmp_path):
    producer, calendar, client, source_root = setup(tmp_path, days=2)
    missing = source_root/f'trade_date={calendar.trade_date.iloc[1]}'/'data.parquet'
    saved = missing.read_bytes(); missing.unlink()
    out = tmp_path/'out'
    with pytest.raises(ValueError, match='missing source day'):
        materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER)
    checkpoint = out/f'checkpoint_{calendar.trade_date.iloc[0]}.json'
    old = checkpoint.read_bytes()
    missing.write_bytes(saved)
    result = materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER, resume=True)
    assert checkpoint.read_bytes() == old
    assert result['performance']['days_reused'] == 1
    assert list(out.glob('failure-*.json'))
    assert materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER, resume=True)['resume_verified']


@pytest.mark.parametrize('mutation', ['input', 'output', 'code'])
def test_resume_rejects_changed_identities(tmp_path, monkeypatch, mutation):
    import factor_factory.pfvv_preparation as preparation
    producer, calendar, client, source_root = setup(tmp_path, days=1)
    out = tmp_path/'out'
    result = materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER)
    if mutation == 'code':
        original = preparation.code_identity
        monkeypatch.setattr(preparation, 'code_identity', lambda path: {**original(path), 'sha256': 'changed'})
    else:
        path = source_root/f'trade_date={calendar.trade_date.iloc[0]}'/'data.parquet' if mutation == 'input' else out/result['days'][0]['path']
        path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='identity_mismatch'):
        materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER, resume=True)


def test_preparation_rejects_memory_budget_before_starting_a_day(tmp_path):
    producer, calendar, client, _ = setup(tmp_path, days=1)
    with pytest.raises(MemoryError, match='reservation'):
        materialize_sdk(plan(producer, calendar), tmp_path/'out', client, producer_path=PRODUCER, memory_budget_bytes=1)
    assert not list((tmp_path/'out').glob('checkpoint_*.json'))


def test_resume_parameters_must_match_the_prepared_identity(tmp_path):
    producer, calendar, client, source_root = setup(tmp_path, days=1)
    out = tmp_path/'out'
    materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER)
    with pytest.raises(ValueError, match='identity_mismatch'):
        materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER, resume=True, workers=2)


def test_sdk_pushdown_cannot_hide_cross_day_raw_source_rows(tmp_path):
    producer, calendar, client, source_root = setup(tmp_path, days=1)
    source_file = source_root/f'trade_date={calendar.trade_date.iloc[0]}'/'data.parquet'
    frame = pd.read_parquet(source_file)
    extra = frame.head(1).copy()
    extra['trade_time'] += pd.Timedelta(days=1)
    extra['trade_date'] = '20160105'
    pd.concat([frame, extra], ignore_index=True).to_parquet(source_file, index=False)
    with pytest.raises(ValueError, match='outside its requested naive day'):
        materialize_sdk(plan(producer, calendar), tmp_path/'out', client, producer_path=PRODUCER)


@pytest.mark.parametrize('field', ['mapping', 'calendar', 'identity', 'status'])
def test_completed_manifest_authority_cannot_be_changed_on_resume(tmp_path, field):
    producer, calendar, client, source_root = setup(tmp_path, days=2)
    out = tmp_path/'out'
    materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER)
    path = out/'daily_measurements_manifest.json'; manifest=json.loads(path.read_text())
    if field == 'mapping':
        a,b=calendar.trade_date
        paths=manifest['pfvv_prepared_daily_state']['day_paths'];paths[a],paths[b]=paths[b],paths[a]
    elif field == 'calendar': manifest['trading_calendar'].reverse()
    elif field == 'identity': manifest['preparation_identity']['calendar_identity']='forged'
    else: manifest['status']='UNVERIFIED'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='manifest_identity_mismatch'):
        materialize_sdk(plan(producer, calendar), out, client, producer_path=PRODUCER, resume=True)


@pytest.mark.parametrize('remote', [False, True])
def test_worker_computes_from_one_fixed_snapshot_despite_source_a_b_a(tmp_path, monkeypatch, remote):
    from dataclasses import asdict, replace
    from factor_factory.pfvv_preparation import _worker
    from factorforge_data_api.runtime import ReadPolicy
    from factorforge_data_api.backends import s3_file
    import hashlib
    producer,calendar,client,source_root=setup(tmp_path,days=1)
    day=calendar.trade_date.iloc[0];path=source_root/f'trade_date={day}'/'data.parquet'
    a=path.read_bytes();frame=pd.read_parquet(path);frame['close']*=1.03
    other=tmp_path/'alternate.parquet';frame.to_parquet(other,index=False);b=other.read_bytes()
    source=[a]
    if remote:
        catalog=json.loads(client.catalog.path.read_text());item=catalog['datasets']['minute_bar']
        item.update(uri='s3://bucket/minute/',metadata={'partition_file_name':'data.parquet'})
        client.catalog.path.write_text(json.dumps(catalog))
        monkeypatch.setattr(s3_file,'_download_s3_parquet_to_path',lambda uri,target: target.write_bytes(source[0]) and None)
        client=DataApiClient.from_catalog(client.catalog.path,read_policy=ReadPolicy(cache_mode='on',cache_root=str(tmp_path/'cache')))
    original=DataApiClient.fetch
    def interleaved(self,query,**kwargs):
        if remote:
            source[0]=b
            entry=self.read_policy.resolve_entry(self.catalog.datasets['minute_bar'])
            fresh=replace(entry,metadata={**entry.metadata,'_runtime_cache_max_age_seconds':0})
            target=s3_file._s3_parquet_cache_root(entry)/f'trade_date={day}'/'data.parquet'
            s3_file._ensure_source_cached(fresh,f's3://bucket/minute/trade_date={day}/data.parquet',target)
        else: path.write_bytes(b)
        try: return original(self,query,**kwargs)
        finally:
            source[0]=a
            if not remote:path.write_bytes(a)
    monkeypatch.setattr(DataApiClient,'fetch',interleaved)
    config={'catalog_path':str(client.catalog.path),'catalog_sha256':client.catalog.sha256,'catalog_source':client.catalog.source_uri,
        'read_policy':asdict(client.read_policy),'calendar_identity':'synthetic_day','producer_path':str(PRODUCER)}
    daily,execution,facts,telemetry=_worker(config,day)
    expected,prices,_=producer.compute_daily_bundle(pd.read_parquet(path),day)
    pd.testing.assert_frame_equal(daily,expected,check_exact=True)
    pd.testing.assert_frame_equal(execution,prices,check_exact=True)
    assert telemetry['input_objects'][0]['sha256']==hashlib.sha256(a).hexdigest()
    assert telemetry['SDK_profile']['source_objects'][0]['sha256']==hashlib.sha256(a).hexdigest()
    assert telemetry['query_snapshot_sha256']
