from __future__ import annotations

import importlib.util
from pathlib import Path


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
        "local_input_paths": {
            "input_mode": "daily_only",
            "daily_df_parquet": str(daily.relative_to(tmp_path)),
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


def test_ready_daily_step3a_readiness_contract_passes(tmp_path):
    validate_step3 = _load_validate_step3()
    prep, qcfg, impl, handoff = _base_artifacts(tmp_path)

    validate_step3.validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=tmp_path)
