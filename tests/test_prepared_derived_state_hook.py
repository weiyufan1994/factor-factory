from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from factor_factory.partitioned_direct_code import run_partitioned_controller


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_step3():
    path = REPO_ROOT / 'skills/factor-forge-step3/scripts/run_step3.py'
    spec = importlib.util.spec_from_file_location('run_step3_prepared_inputs_test', path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_validate_step3():
    path = REPO_ROOT / 'skills/factor-forge-step3/scripts/validate_step3.py'
    spec = importlib.util.spec_from_file_location('validate_step3_prepared_inputs_test', path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _prepared_inputs() -> dict:
    return {
        'input_mode': 'derived_state_with_daily',
        'sample_window_actual': {'start': '20160104', 'end': '20250711'},
        'daily_df_parquet': 'study/full/daily.parquet',
        'derived_state_root': 'study/full/state',
        'calendar_dates': ['20160104', '20160105'],
        'step3b_daily_df_parquet': 'study/sample/daily.parquet',
        'step3b_derived_state_root': 'study/sample/state',
        'step3b_calendar_dates': ['20160104'],
        'step3b_sample_window': {'start': '20160104', 'end': '20160331'},
    }


def test_prepared_inputs_require_explicit_derived_state_and_windows() -> None:
    step3 = _load_step3()
    assert step3.validate_prepared_local_inputs(_prepared_inputs()) == _prepared_inputs()

    invalid = _prepared_inputs()
    invalid['minute_df_parquet'] = 'forbidden/full-minute.parquet'
    with pytest.raises(SystemExit, match='RAW_MINUTE_FORBIDDEN'):
        step3.validate_prepared_local_inputs(invalid)

    missing_sample_selector = _prepared_inputs()
    missing_sample_selector.pop('step3b_calendar_dates')
    with pytest.raises(SystemExit, match='step3b_calendar_dates'):
        step3.validate_prepared_local_inputs(missing_sample_selector)


def test_prepared_route_is_explicit_not_inferred_from_missing_data_api_resolution() -> None:
    validator = _load_validate_step3()
    assert validator._is_prepared_derived_state_route(_prepared_inputs()) is True
    assert validator._is_prepared_derived_state_route({
        'input_mode': 'derived_state_with_daily',
        'daily_df_parquet': 'study/full/daily.parquet',
    }) is False
    assert validator._is_prepared_derived_state_route({
        'daily_df_parquet': 'study/full/daily.parquet',
        'derived_state_root': 'study/full/state',
    }) is False


def test_step3b_validator_accepts_partitioned_controller_without_raw_fixture(tmp_path: Path) -> None:
    validator = importlib.util.module_from_spec(
        spec := importlib.util.spec_from_file_location(
            'validate_step3b_prepared_controller_test',
            REPO_ROOT / 'skills/factor-forge-step3/scripts/validate_step3b.py',
        )
    )
    assert spec and spec.loader
    spec.loader.exec_module(validator)
    implementation = tmp_path / 'prepared_controller.py'
    implementation.write_text(
        'METADATA = {"prepared_state_projection": True, "raw_minute_access": False}\n'
        'def compute_factor_partitioned(**kwargs):\n'
        '    return kwargs["output_path"]\n',
        encoding='utf-8',
    )
    validator.validate_prepared_partitioned_controller(implementation)


def test_partitioned_controller_receives_only_prepared_paths(tmp_path: Path) -> None:
    output = tmp_path / 'factor.parquet'
    derived_root = tmp_path / 'state'
    derived_root.mkdir()
    daily_path = tmp_path / 'daily.parquet'
    daily_path.write_bytes(b'not-read-by-adapter')
    captured: dict = {}

    def compute_factor_partitioned(*, derived_state_root, daily_input_path, output_path):
        captured.update(
            derived_state_root=derived_state_root,
            daily_input_path=daily_input_path,
            output_path=output_path,
        )
        output_path.write_bytes(b'controller-owned-output')
        return output_path

    result = run_partitioned_controller(
        SimpleNamespace(compute_factor_partitioned=compute_factor_partitioned),
        local_inputs=_prepared_inputs(),
        derived_state_root=derived_root,
        daily_input_path=daily_path,
        output_path=output,
        run_dir=tmp_path,
        report_id='RID',
        factor_id='factor',
        factorforge_root=tmp_path,
        workspace_root=tmp_path,
    )

    assert result == output.resolve()
    assert captured == {
        'derived_state_root': derived_root,
        'daily_input_path': daily_path,
        'output_path': output,
    }


def test_partitioned_controller_cannot_redirect_step_owned_output(tmp_path: Path) -> None:
    expected = tmp_path / 'expected.parquet'
    redirected = tmp_path / 'redirected.parquet'

    def compute_factor_partitioned(*, output_path):
        del output_path
        redirected.write_bytes(b'wrong-location')
        return redirected

    with pytest.raises(ValueError, match='outside the Step-owned target'):
        run_partitioned_controller(
            SimpleNamespace(compute_factor_partitioned=compute_factor_partitioned),
            local_inputs=_prepared_inputs(),
            derived_state_root=tmp_path,
            daily_input_path=tmp_path / 'daily.parquet',
            output_path=expected,
            run_dir=tmp_path,
            report_id='RID',
            factor_id='factor',
            factorforge_root=tmp_path,
            workspace_root=tmp_path,
        )


def test_partitioned_controller_resume_uses_new_internal_create_only_target(tmp_path: Path) -> None:
    step3b_path = REPO_ROOT / 'skills/factor-forge-step3/scripts/run_step3b.py'
    spec = importlib.util.spec_from_file_location('run_step3b_partitioned_resume_test', step3b_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    first = module.partitioned_controller_attempt_path(tmp_path, 'RID')
    first.write_bytes(b'prior-attempt')
    second = module.partitioned_controller_attempt_path(tmp_path, 'RID')
    assert first != second
    assert not second.exists()
    assert second.parent == tmp_path
