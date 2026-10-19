from pathlib import Path
import copy
import hashlib
import json
import importlib.util

import pandas as pd
import pytest

from factor_factory.prepared_inputs import bind_prepared_inputs, verify_prepared_binding, write_prepared_inputs


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def prepared(tmp_path):
    def state(name, days):
        root = tmp_path / name
        root.mkdir()
        daily = root / 'daily.parquet'
        pd.DataFrame({'ts_code': ['A'] * len(days), 'trade_date': days}).to_parquet(daily)
        partitions = {}
        for day in days:
            p = root / (day + '.parquet')
            pd.DataFrame({'ts_code': ['A'], 'state_return': [0.1]}).to_parquet(p)
            partitions[day] = {'relative_path': p.name, 'sha256': sha(p)}
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({'calendar_dates': days, 'partitions': partitions}))
        return {'input_mode': 'derived_state_with_daily', 'daily_df_parquet': str(daily),
                'derived_state_root': str(root), 'partition_manifest_path': str(manifest),
                'partition_manifest_sha256': sha(manifest), 'calendar_dates': days,
                'sample_window_actual': {'start': days[0], 'end': days[-1]}}
    full = state('full', ['20160104', '20160105'])
    sample = state('sample', ['20160104'])
    config = tmp_path / 'controller.json'
    config.write_text(json.dumps({'controller': 'sample', 'sample_budget': {'max_calendar_days': 1}, 'local_inputs': sample}))
    prices = tmp_path / 'prices.parquet'
    pd.DataFrame({'ts_code': ['A', 'A'], 'trade_date': full['calendar_dates'], 'close': [10., 11.]}).to_parquet(prices)
    producer = tmp_path / 'reviewed.py'
    producer.write_text('# frozen reviewed transformation\n')
    return full, dict(sample_controller=config, evaluation_daily=prices, base_dir=tmp_path, dependencies=(producer,))


def test_binds_existing_data_and_native_step3_without_copying(prepared, tmp_path):
    full, kwargs = prepared
    original = {str(p): sha(p) for p in tmp_path.rglob('*') if p.is_file()}
    result = bind_prepared_inputs(full, **kwargs)
    assert result['signal_daily_df_parquet'] != result['evaluation_daily_df_parquet']
    assert result['derived_state_root'] == full['derived_state_root']
    assert original == {str(p): sha(p) for p in tmp_path.rglob('*') if p.is_file()}
    output = tmp_path / 'inputs.json'
    write_prepared_inputs(output, result)
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('step3_bind_test', repo / 'skills/factor-forge-step3/scripts/run_step3.py')
    step3 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(step3)
    assert step3.load_prepared_local_inputs(str(output)) == result
    with pytest.raises(FileExistsError):
        write_prepared_inputs(output, result)


@pytest.mark.parametrize('change', ['partition', 'producer', 'selector', 'calendar'])
def test_reuse_rejects_stale_bytes_or_changed_request(prepared, change):
    full, kwargs = prepared
    bound = bind_prepared_inputs(full, **kwargs)
    if change == 'partition':
        (Path(full['derived_state_root']) / '20160104.parquet').write_bytes(b'changed')
    elif change == 'producer':
        kwargs['dependencies'][0].write_text('# different formula\n')
    elif change == 'selector':
        bound['evaluation_daily_df_parquet'] = full['daily_df_parquet']
    else:
        bound['calendar_dates'] = ['20160104']
    with pytest.raises(ValueError, match='changed'):
        verify_prepared_binding(bound, base_dir=kwargs['base_dir'])


def test_calendar_only_daily_cannot_be_used_as_prices(prepared):
    full, kwargs = prepared
    kwargs['evaluation_daily'] = Path(full['daily_df_parquet'])
    with pytest.raises(ValueError, match='evaluation daily: missing columns.*close'):
        bind_prepared_inputs(full, **kwargs)


def test_rejects_sample_outside_full_scope(prepared):
    full, kwargs = prepared
    sample = Path(json.loads(kwargs['sample_controller'].read_text())['local_inputs']['daily_df_parquet'])
    pd.DataFrame({'ts_code': ['OTHER'], 'trade_date': ['20160104']}).to_parquet(sample)
    with pytest.raises(ValueError, match='symbol/date coverage mismatch'):
        bind_prepared_inputs(full, **kwargs)


def test_rejects_duplicate_evaluation_keys(prepared):
    full, kwargs = prepared
    frame = pd.read_parquet(kwargs['evaluation_daily'])
    pd.concat([frame, frame.iloc[:1]]).to_parquet(kwargs['evaluation_daily'])
    with pytest.raises(ValueError, match='duplicate'):
        bind_prepared_inputs(full, **kwargs)


def test_rejects_wrong_symbol_date_pairs_with_same_dates_and_symbols(prepared):
    full, kwargs = prepared
    frame = pd.read_parquet(kwargs['evaluation_daily'])
    frame.loc[0, 'ts_code'] = 'B'
    frame.to_parquet(kwargs['evaluation_daily'])
    with pytest.raises(ValueError, match='coverage mismatch'):
        bind_prepared_inputs(full, **kwargs)


def test_rejects_incomplete_evaluation_window(prepared):
    full, kwargs = prepared
    pd.DataFrame({'ts_code': ['A'], 'trade_date': ['20160104'], 'close': [10.]}).to_parquet(kwargs['evaluation_daily'])
    with pytest.raises(ValueError, match='actual dates differ'):
        bind_prepared_inputs(full, **kwargs)


def test_legacy_inputs_keep_existing_controller_validation():
    verify_prepared_binding({'input_mode': 'derived_state_with_daily'}, base_dir=Path('/'))
