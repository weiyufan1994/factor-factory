"""Old/new entrypoint parity on synthetic inputs, not empirical factor evidence."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
ENTRY = REPO / 'skills/factor-forge-step4/scripts/run_step4.py'
FROZEN = REPO / 'tests/fixtures/step4_main_before_cleanup.py'


def _load_step4(*, frozen=False):
    spec = importlib.util.spec_from_file_location('step4_refactor_test', ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if frozen:
        exec(compile(FROZEN.read_text(), str(FROZEN), 'exec'), module.__dict__)
    return module


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _normalize(value, root):
    if isinstance(value, dict):
        return {_normalize(key, root): _normalize(item, root) for key, item in value.items()
                if key != 'traceback'}  # source lines necessarily move in the refactor
    if isinstance(value, list):
        return [_normalize(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), '<study>')
    return value


def _run(root, case, monkeypatch, *, frozen):
    root.mkdir()
    canonical = root / 'canonical'
    canonical.mkdir()
    shared_inputs = root.parent / 'inputs'
    shared_inputs.mkdir(exist_ok=True)
    report_id = 'STEP4_REFACTOR_SYNTHETIC'
    dates = pd.bdate_range('2024-01-02', periods=20).strftime('%Y%m%d')
    daily = pd.DataFrame([
        {'ts_code': code, 'trade_date': day, 'close': float(index + 10)}
        for code in ('000001.SZ', '000002.SZ') for index, day in enumerate(dates)
    ])
    daily_path = shared_inputs / 'daily.parquet'
    daily.to_parquet(daily_path, index=False)
    code = """def compute_factor(daily_df, minute_df=None):
    result = daily_df[['ts_code', 'trade_date']].copy()
    result['factor_value'] = daily_df['close'] / 10.0
    return result
"""
    if case == 'partial':
        code = code.replace('return result', "return result[result['trade_date'] > result['trade_date'].min()].copy()")
    elif case == 'all_null':
        code = code.replace("daily_df['close'] / 10.0", "float('nan')")
    elif case == 'empty':
        code = code.replace('return result', 'return result.iloc[:0].copy()')
    elif case == 'missing_callable':
        code = 'VALUE = 1\n'
    elif case == 'compute_error':
        code = "def compute_factor(daily_df, minute_df=None):\n    raise ValueError('synthetic compute failure')\n"
    implementation = shared_inputs / 'factor.py'
    implementation.write_text(code)
    local_inputs = {'input_mode': 'daily_only', 'daily_df_parquet': str(daily_path)}
    fsm = {
        'report_id': report_id, 'factor_id': 'refactor_synthetic',
        'implementation_mode': 'direct_code',
        'artifact_identity': {'implementation_mode': 'direct_code', 'spec_hash': 'synthetic-spec-v1'},
        'implementation_contract': {'mode': 'direct_code', 'code_contract': {
            'performance_scope': {'formal_step4_full_window_execution_allowed': True},
        }},
        'canonical_spec': {'standard_formula_fields_contract': {'required_standard_formula_fields': []}},
    }
    dpm = {
        'report_id': report_id, 'factor_id': 'refactor_synthetic',
        'sample_window': {'start': dates[0], 'end': dates[-1]},
        'field_mapping': {'close': 'close'}, 'data_sources': ['synthetic_only'],
        'local_input_paths': local_inputs,
    }
    handoff = {
        'report_id': report_id, 'implementation_path': str(implementation),
        'local_input_paths': local_inputs,
        'evaluation_plan': {'backends': [{'name': 'self_quant_analyzer'}]},
    }
    for directory, name, value in (
        ('factor_spec_master', 'factor_spec_master', fsm),
        ('data_prep_master', 'data_prep_master', dpm),
        ('handoff', 'handoff_to_step4', handoff),
    ):
        _write_json(root / 'objects' / directory / f'{name}__{report_id}.json', value)
    with monkeypatch.context() as patch:
        patch.setenv('FACTORFORGE_ROOT', str(canonical))
        patch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
        patch.setenv('FACTORFORGE_ALLOW_DIRECT_STEP', '1')
        patch.setenv('FACTORFORGE_DEBUG_ROOT', str(root))
        module = _load_step4(frozen=frozen)
        patch.setattr(sys, 'argv', [str(ENTRY), '--report-id', report_id])
        patch.setattr(module, 'utc_now', lambda: '2026-10-10T00:00:00Z')
        patch.setattr(module, 'current_repo_sha', lambda: 'a' * 40)
        # Backend dispatch is outside this parity test; PFVV integration exercises
        # the real subprocess backend separately. No synthetic return is invented.
        patch.setattr(module, 'write_backend_payloads', lambda _id, runs, **kwargs: (runs, {}))
        error = None
        try:
            module.main()
            if case == 'reuse':
                # A fresh CLI process starts from its configured canonical root.
                module.FACTORFORGE = canonical
                module.main()
        except (ValueError, SystemExit) as exc:
            error = (type(exc).__name__, str(exc))
    outputs = {str(p.relative_to(root)): _normalize(json.loads(p.read_text()), root)
               for p in root.rglob('*.json')}
    factor_path = root / 'runs' / report_id / f'factor_values__{report_id}.parquet'
    frame = pd.read_parquet(factor_path) if factor_path.exists() else None
    return error, outputs, frame


@pytest.mark.parametrize('case', ['normal', 'partial', 'all_null', 'empty', 'missing_callable', 'compute_error', 'reuse'])
def test_complete_entrypoint_matches_frozen_main(tmp_path, monkeypatch, case):
    old_error, old_outputs, old_frame = _run(tmp_path / 'original', case, monkeypatch, frozen=True)
    new_error, new_outputs, new_frame = _run(tmp_path / 'refactor', case, monkeypatch, frozen=False)
    assert new_error == old_error
    if case not in {'compute_error', 'empty'}:
        assert new_error is None
    if case == 'empty':
        assert new_error == ('ValueError', 'empty input frame')
    if case == 'compute_error':
        assert new_error == ('ValueError', 'synthetic compute failure')
    assert new_outputs == old_outputs
    run = next(value for key, value in new_outputs.items() if key.startswith('objects/factor_run_master/'))
    if case in {'normal', 'reuse'}:
        assert run['run_status'] == 'success'
        assert run['diagnostic_summary'] == {'row_count': 40, 'date_count': 20, 'ticker_count': 2}
        assert new_frame['factor_value'].tolist() == [float(i + 10) / 10 for i in range(20)] * 2
    if case == 'all_null':
        assert run['run_status'] == 'failed'
        assert run['failure_reason'] == 'BLOCK_STEP4_FORMAL_SIGNAL_NON_NULL_COVERAGE_LOW'
    if case == 'partial':
        assert run['run_status'] == 'partial'
    if case == 'reuse':
        metadata = next(value for key, value in new_outputs.items() if '/run_metadata__' in key)
        assert metadata['step4_factor_io_profile']['recomputed_factor'] is False
    if old_frame is None:
        assert new_frame is None
    else:
        pd.testing.assert_frame_equal(new_frame, old_frame, check_exact=True)


def test_refactored_helpers_have_single_bounded_responsibilities():
    tree = ast.parse(ENTRY.read_text(), feature_version=(3, 11))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ('summarize_step4_coverage', 'build_step4_completed_run_master',
                 'build_step4_completed_diagnostics', 'build_completed_step5_handoff',
                 'write_completed_step4_results', 'compute_declared_minute_factor',
                 'build_step4_input_io_profile', 'resolve_step4_diagnostic_contract',
                 'resolve_step4_input_selection', 'build_step4_web_evaluation_contract',
                 'summarize_step4_output_quality', 'build_recomputed_factor_io_profile'):
        function = functions[name]
        assert function.end_lineno - function.lineno < 150
    assert functions['main'].end_lineno - functions['main'].lineno < 900


@pytest.mark.parametrize('route', ['flow_state', 'other_derived', 'fast', 'stream', 'forbidden'])
def test_minute_dispatch_selects_only_the_declared_kernel(monkeypatch, tmp_path, route):
    """Routing mocks exercise orchestration only; derived-state kernels have exact parity tests."""
    module = _load_step4()
    daily, result, implementation = object(), object(), object()
    query = {'start_date': '20240102', 'end_date': '20240102'}
    calls = []
    requirement = ({'dataset_id': module.MINUTE_DERIVED_FLOW_STATE_V1} if route == 'flow_state'
                   else {'dataset_id': 'synthetic_other_state'} if route == 'other_derived' else None)
    monkeypatch.setattr(module, '_minute_flow_state_requirement', lambda contract, dpm: requirement)
    monkeypatch.setattr(module, '_daily_trade_dates_for_minute_query', lambda frame, query: ['20240102'])
    monkeypatch.setattr(module, '_generic_minute_full_window_forbidden', lambda dates: route == 'forbidden')
    monkeypatch.setattr(module, '_supports_sp3_intraday_flow_fast_path', lambda factor: route == 'fast')

    def record(name, output):
        def invoke(*args, **kwargs):
            assert kwargs['daily_df'] is daily
            calls.append(name)
            return output
        return invoke

    monkeypatch.setattr(module, '_load_required_minute_flow_state', record('load', (object(), {'load_seconds': 2.0})))
    monkeypatch.setattr(module, 'compute_factor_from_minute_derived_state', record('flow_state', (result, {'factor_compute_seconds': 3.0})))
    monkeypatch.setattr(module, 'compute_factor_from_data_api_minute_derived_state_batches', record('other_derived', (result, {'derived': True}, {'factor_compute_seconds': 4.0})))
    monkeypatch.setattr(module, 'compute_factor_intraday_flow_daily_preagg_contract', record('fast', (result, {'fast': True})))
    monkeypatch.setattr(module, 'compute_factor_streaming_minute_contract', record('stream', (result, {'stream': True})))
    kwargs = dict(signal_daily_df=daily, minute_streaming_query=query, step4_contract={}, dpm={}, report_id='SYNTHETIC', run_dir=tmp_path)
    if route == 'forbidden':
        with pytest.raises(SystemExit, match='BLOCK_STEP4_MINUTE_GENERIC_STREAMING_FULL_WINDOW_FORBIDDEN'):
            module.compute_declared_minute_factor(implementation, **kwargs)
        assert calls == []
        return
    actual, stream, fast, derived, factor = module.compute_declared_minute_factor(implementation, **kwargs)
    assert actual is result
    assert calls == (['load', 'flow_state'] if route == 'flow_state' else [route])
    assert bool(stream) == (route == 'stream')
    assert bool(fast) == (route == 'fast')
    assert bool(derived) == (route in {'flow_state', 'other_derived'})
    assert bool(factor) == (route in {'flow_state', 'other_derived'})


def test_output_quality_is_measured_not_assumed():
    module = _load_step4()
    frame = pd.DataFrame({'ts_code': ['000002.SZ', '000001.SZ', '000001.SZ'],
                          'trade_date': ['20240102'] * 3, 'factor_value': [1.0, None, 2.0]})
    before = frame.copy(deep=True)
    nulls, duplicates, sorted_keys = module.summarize_step4_output_quality(
        frame, parent_factor_summary=None, signal_col='factor_value', row_count=3,
    )
    assert nulls == {'factor_value': 1 / 3}
    assert duplicates == {'ts_code_trade_date': 1 / 3}
    assert sorted_keys is False
    pd.testing.assert_frame_equal(frame, before)
