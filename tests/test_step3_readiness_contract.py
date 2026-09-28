from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

from factor_factory.step3_execution_readiness import require_execution_readiness


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_validate_step3():
    path = REPO_ROOT / "skills/factor-forge-step3/scripts/validate_step3.py"
    spec = importlib.util.spec_from_file_location("validate_step3_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _base_artifacts(tmp_path):
    daily = tmp_path / "daily.parquet"
    daily.write_bytes(b"not-used-by-readiness-helper")
    prep = {
        "report_id": "R",
        "factor_id": "R",
        "feasibility": "ready",
        "sample_window": {"start": "20260101", "end": "20260131"},
        "data_sources": [{"name": "clean_daily_bar"}],
        "step4_data_contract": {
            "version": "factorforge_step4_data_contract_v1",
            "data_api_package": "factorforge_data_api",
            "formal_factor_values_owner": "Step4",
            "full_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20260101",
                    "end_date": "20260131",
                    "universe": "a_share_all",
                    "fields": ["close"],
                    "frequency": "daily",
                }
            },
            "sample_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20260101",
                    "end_date": "20260131",
                    "universe": ["000001.SZ"],
                    "fields": ["close"],
                    "frequency": "daily",
                }
            },
            "catalog_bindings": {"clean_daily_bar": {}},
        },
        "local_input_paths": {
            "input_mode": "daily_only",
            "data_api_resolution": {
                "clean_daily_bar": {
                    "status": "ready",
                    "daily_filter_policy": {
                        "drop_suspended": True,
                        "drop_limit_events": True,
                        "invalid_days_do_not_enter_window": True,
                        "minimum_effective_days": 10,
                    },
                }
            },
        },
        "daily_filter_policy": {
            "drop_suspended": True,
            "drop_limit_events": True,
            "invalid_days_do_not_enter_window": True,
            "minimum_effective_days": 10,
        },
    }
    qcfg = {
        "report_id": "R",
        "logical_fields": {"close": "close"},
        "qlib_field_map": {"$close": "close"},
        "instrument_field": "ts_code",
        "date_field": "trade_date",
        "step4_data_contract": prep["step4_data_contract"],
    }
    impl = {"report_id": "R", "implementation_mode": "operator"}
    handoff = {"report_id": "R", "step3a_ready": True, "step3b_ready": False}
    return prep, qcfg, impl, handoff


def test_blocked_step3a_cannot_claim_step3b_ready(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    prep["feasibility"] = "blocked"
    prep["blocked_items"] = [{"code": "CLEAN_DAILY_BAR_MISSING"}]
    handoff["step3a_ready"] = False
    handoff["step3b_ready"] = True

    try:
        validate_step3.validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=tmp_path)
    except AssertionError as exc:
        assert "BLOCK_STEP3A_HANDOFF_CONTRADICTION" in str(exc)
    else:
        raise AssertionError("expected blocked Step3A + step3b_ready=true to fail")


def test_blocked_record_can_be_structurally_valid_but_not_execution_ready(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    prep["feasibility"] = "blocked"
    prep["blocked_items"] = [{"code": "CLEAN_DAILY_BAR_MISSING"}]
    handoff["step3a_ready"] = False
    handoff["step3b_ready"] = False

    validate_step3.validate_step3_readiness_contract(
        prep, qcfg, impl, handoff, workspace=tmp_path
    )
    with pytest.raises(ValueError, match="BLOCK_STEP3A_NOT_READY"):
        require_execution_readiness(
            prep,
            handoff,
            {"report_id": "R", "final_result": "blocked"},
        )


def test_execution_readiness_requires_matching_native_report(tmp_path):
    prep, _qcfg, _impl, handoff = _base_artifacts(tmp_path)
    with pytest.raises(ValueError, match="FEASIBILITY_REPORT_MISMATCH"):
        require_execution_readiness(
            prep,
            handoff,
            {"report_id": "OTHER", "final_result": "ready"},
        )
    require_execution_readiness(
        prep,
        handoff,
        {"report_id": "R", "final_result": "ready"},
    )
    with pytest.raises(ValueError, match="BLOCK_STEP3B_NOT_READY"):
        require_execution_readiness(
            prep,
            handoff,
            {"report_id": "R", "final_result": "ready"},
            step3b=True,
        )


def test_ready_daily_step3a_requires_data_api_resolution(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    prep["local_input_paths"].pop("data_api_resolution")

    try:
        validate_step3.validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=tmp_path)
    except AssertionError as exc:
        assert "BLOCK_STEP3A_DATA_API_RESOLUTION_MISSING" in str(exc)
    else:
        raise AssertionError("expected missing Data API resolution to fail")


def test_ready_daily_step3a_requires_effective_day_policy(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    prep["daily_filter_policy"] = None
    prep["local_input_paths"]["data_api_resolution"]["clean_daily_bar"]["daily_filter_policy"] = None

    try:
        validate_step3.validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=tmp_path)
    except AssertionError as exc:
        assert "BLOCK_STEP3A_DAILY_FILTER_POLICY_MISSING" in str(exc)
    else:
        raise AssertionError("expected missing daily filter policy to fail")


def test_ready_daily_step3a_requires_step4_data_contract(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    prep.pop("step4_data_contract")
    qcfg.pop("step4_data_contract")

    try:
        validate_step3.validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=tmp_path)
    except AssertionError as exc:
        assert "BLOCK_STEP3A_STEP4_DATA_CONTRACT_MISSING" in str(exc)
    else:
        raise AssertionError("expected missing Step4 data contract to fail")


def test_ready_daily_step3a_readiness_contract_passes(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)

    validate_step3.validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=tmp_path)


def _bind_event_state(prep, qcfg):
    contract = prep["step4_data_contract"]
    contract["primary_daily_dataset_id"] = "daily_event_state_v1"
    for query_set in ("full_queries", "sample_queries"):
        query = contract[query_set].pop("clean_daily_bar")
        query["dataset"] = "daily_event_state_v1"
        contract[query_set]["daily_event_state_v1"] = query
    contract["catalog_bindings"] = {"daily_event_state_v1": {}}
    observability_fields = [
        "is_tradable_default",
        "tradable_exclusion_reason",
        "tradable_policy_version",
    ]
    for query_set in ("full_queries", "sample_queries"):
        contract[query_set]["daily_event_state_v1"]["fields"].extend(
            observability_fields
        )
    resolution = prep["local_input_paths"]["data_api_resolution"].pop(
        "clean_daily_bar"
    )
    prep["local_input_paths"]["data_api_resolution"][
        "daily_event_state_v1"
    ] = resolution
    resolution["schema"] = {"columns": ["ts_code", "trade_date", *observability_fields]}
    resolution["freshness"] = {"event_markers_complete": True}
    qcfg["step4_data_contract"] = contract


def test_declared_event_state_ready_passes(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    _bind_event_state(prep, qcfg)
    validate_step3.validate_step3_readiness_contract(
        prep, qcfg, impl, handoff, workspace=tmp_path
    )


@pytest.mark.parametrize("status", [None, "missing"])
def test_declared_event_state_missing_or_unready_blocks(tmp_path, status):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    _bind_event_state(prep, qcfg)
    if status is None:
        prep["local_input_paths"]["data_api_resolution"].pop(
            "daily_event_state_v1"
        )
    else:
        prep["local_input_paths"]["data_api_resolution"][
            "daily_event_state_v1"
        ]["status"] = status
    with pytest.raises(AssertionError, match="DATA_API_RESOLUTION_MISSING"):
        validate_step3.validate_step3_readiness_contract(
            prep, qcfg, impl, handoff, workspace=tmp_path
        )


def test_declared_event_state_mismatched_resolution_key_blocks(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)
    _bind_event_state(prep, qcfg)
    resolution = prep["local_input_paths"]["data_api_resolution"].pop(
        "daily_event_state_v1"
    )
    prep["local_input_paths"]["data_api_resolution"]["clean_daily_bar"] = resolution
    with pytest.raises(AssertionError, match="DATA_API_RESOLUTION_MISSING"):
        validate_step3.validate_step3_readiness_contract(
            prep, qcfg, impl, handoff, workspace=tmp_path
        )
