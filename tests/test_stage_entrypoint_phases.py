"""Small independent oracles for the extracted stage phases; no market data."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_stage(stage: str):
    directory = "step3" if stage == "step3b" else stage
    path = ROOT / f"skills/factor-forge-{directory}/scripts/run_{stage}.py"
    spec = importlib.util.spec_from_file_location(f"phase_test_{stage}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_catalog_descriptor_does_not_fall_back_to_fetch(monkeypatch):
    stage = load_stage("step3")

    def unexpected(*args, **kwargs):
        pytest.fail("describing unavailable inputs must not fetch replacement data")

    monkeypatch.setattr(stage, "build_local_price_volume_snapshots", unexpected)
    monkeypatch.setattr(stage, "build_local_daily_snapshot", unexpected)
    sources, coverage, proxies, blocked, fields, notes, inputs = stage.describe_step3_source_requirements(
        explicitly_required_intraday_proxy_datasets=["synthetic_missing_state"],
        intraday_proxy_catalog_path="synthetic_catalog.json",
        missing_intraday_proxy_datasets=["synthetic_missing_state"],
        moneyflow_fields=[], need_daily=False, need_daily_basic=False,
        need_minute=False, need_moneyflow=False,
    )
    assert [row["normalized_dataset"] for row in sources] == ["synthetic_missing_state"]
    assert coverage[0]["status"] == "blocked"
    assert blocked[0]["missing_datasets"] == ["synthetic_missing_state"]
    assert inputs["input_mode"] == "blocked"
    assert inputs["step4_data_contract"]["forbidden_fallback"] == "raw minute_bar fetch"
    assert proxies == [] and notes == []
    assert fields["instrument"] == "ts_code"


def sample_frame():
    return pd.DataFrame({
        "ts_code": ["000002.SZ", "000001.SZ", "000001.SZ"],
        "trade_date": ["20240103", "20240103", "20240102"],
        "factor_value": [0.0, float("nan"), 2.0],
    })


def test_sample_normalization_preserves_nan_zero_and_date_order():
    stage = load_stage("step3b")
    frame = sample_frame()
    original = frame.copy(deep=True)
    profile = {}
    values, audit, signal, sorting, already_sorted = stage.normalize_step3b_sample_result(
        result_df=frame, prepared_sample_calendar=["20240102", "20240103"],
        timer=stage.PhaseTimer(), factor_id="SYNTHETIC", local_inputs={},
        daily_df=frame, trust_sort_contract=False, formula_engine_profile=profile,
    )
    assert signal == "factor_value"
    assert values["trade_date"].tolist() == ["20240102", "20240103", "20240103"]
    assert values["factor_value"].iloc[0] == 2.0
    assert pd.isna(values["factor_value"].iloc[1])
    assert values["factor_value"].iloc[2] == 0.0
    assert not already_sorted and not sorting["full_sort_skipped"]
    pd.testing.assert_frame_equal(values, audit)
    pd.testing.assert_frame_equal(frame, original)


def test_sample_normalization_rejects_dates_outside_declared_calendar():
    stage = load_stage("step3b")
    with pytest.raises(SystemExit, match="OUTPUT_OUTSIDE_CALENDAR"):
        stage.normalize_step3b_sample_result(
            result_df=sample_frame(), prepared_sample_calendar=["20240102"],
            timer=stage.PhaseTimer(), factor_id="SYNTHETIC", local_inputs={},
            daily_df=sample_frame(), trust_sort_contract=False, formula_engine_profile={},
        )


@pytest.mark.parametrize("policy", ["full_csv", "sample_csv", "no_csv"])
def test_csv_phase_only_writes_the_declared_sample_path(tmp_path, policy):
    stage = load_stage("step3b")
    path = tmp_path / "sample.csv"
    full, sample, rows, strategy, available = stage.write_step3b_sample_csv(
        timer=stage.PhaseTimer(), csv_policy=policy,
        result_df=sample_frame(), step3b_cache_csv=path,
    )
    assert path.exists() == (policy != "no_csv")
    assert full == (path if policy == "full_csv" else None)
    assert sample == (path if policy == "sample_csv" else None)
    assert rows == (0 if policy == "no_csv" else 3)
    assert available == (policy == "full_csv")
    assert strategy == {"full_csv": "full", "sample_csv": "head_tail", "no_csv": "none"}[policy]
    assert sorted(p.name for p in tmp_path.iterdir()) == ([] if policy == "no_csv" else ["sample.csv"])


def test_local_rejection_does_not_enter_promotion_checks(monkeypatch):
    stage = load_stage("step6")

    def unexpected(*args, **kwargs):
        pytest.fail("a local reject is not a promotion request")

    monkeypatch.setenv("FACTORFORGE_ULTIMATE_RUN", "1")
    monkeypatch.setattr(stage, "research_protocol_paths", unexpected)
    iteration = {"research_judgment": {"decision": "reject"}}
    assert stage.check_step6_promotion_evidence(
        iteration=iteration, bundle={}, report_id="SYNTHETIC", protocol_scope="local_is",
    ) == []
    assert iteration == {"research_judgment": {"decision": "reject"}}


def test_no_prewrite_failure_does_not_write_or_read_memo(tmp_path, monkeypatch):
    stage = load_stage("step6")

    def unexpected(*args, **kwargs):
        pytest.fail("the successful check must not manufacture a failure record")

    monkeypatch.setattr(stage, "write_step6_prewrite_block", unexpected)
    stage.handle_step6_prewrite_failure(
        prewrite_failures=[], report_id="SYNTHETIC", iteration={}, would_have_written=[],
        memo_revision_failures=[], main_agent_memo_json_path=tmp_path / "absent.json",
        prior_main_agent_status={}, main_agent_questionnaire_json_path=tmp_path / "absent_qa.json",
        main_agent_questionnaire_ref={}, main_agent_memo_ref={},
        main_agent_status_path=tmp_path / "status.json",
    )
    assert list(tmp_path.iterdir()) == []
