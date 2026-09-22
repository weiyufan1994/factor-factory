from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_step4():
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("run_step4_parent_evaluation_memory_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_same_canonical_daily_input_is_read_once(tmp_path: Path) -> None:
    run_step4 = _load_run_step4()
    daily = tmp_path / "daily.parquet"
    daily.write_bytes(b"fixture")
    calls: list[Path] = []
    frame = object()

    def reader(path: Path):
        calls.append(path)
        return frame

    evaluation, signal, shared = run_step4.read_evaluation_daily_frames(daily, daily, reader)
    assert calls == [daily]
    assert evaluation is signal is frame
    assert shared is True


def test_distinct_daily_inputs_keep_existing_two_read_behavior(tmp_path: Path) -> None:
    run_step4 = _load_run_step4()
    evaluation_path, signal_path = tmp_path / "evaluation.parquet", tmp_path / "signal.parquet"
    evaluation_path.write_bytes(b"evaluation")
    signal_path.write_bytes(b"signal")
    calls: list[Path] = []

    def reader(path: Path):
        calls.append(path)
        return {"path": path}

    evaluation, signal, shared = run_step4.read_evaluation_daily_frames(evaluation_path, signal_path, reader)
    assert calls == [evaluation_path, signal_path]
    assert evaluation is not signal
    assert shared is False


def test_only_custom_primary_releases_parent_evaluation_frames() -> None:
    run_step4 = _load_run_step4()
    daily, signal, minute = object(), object(), object()
    preserved = run_step4.release_parent_evaluation_frames_for_custom_primary(None, daily, signal, minute)
    assert preserved == (daily, signal, minute, False)
    released = run_step4.release_parent_evaluation_frames_for_custom_primary({"backend": "study_local"}, daily, signal, minute)
    assert released == (None, None, None, True)


def _factor_parquet(path: Path) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 3 + ["000002.SZ"] * 3,
            "trade_date": ["20160104", "20160105", "20160106"] * 2,
            "factor_value": [np.nan, np.nan, 0.2, np.nan, np.nan, -0.3],
            "PF": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "VV": [5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
            "component_z": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "warmup": [True, True, False, True, True, False],
            "producer_audit_only": ["retain"] * 6,
        }
    )
    frame.to_parquet(path, index=False)
    return frame


def test_prepared_custom_primary_projects_arrow_diagnostics_and_preserves_full_parquet(
    tmp_path: Path,
) -> None:
    run_step4 = _load_run_step4()
    path = tmp_path / "factor.parquet"
    full = _factor_parquet(path)

    projected, profile = run_step4.read_parent_diagnostics_arrow_projection(
        path,
        run_step4.PARENT_DIAGNOSTIC_FACTOR_COLUMNS,
        available_memory_bytes=1024 * 1024,
    )

    assert projected.columns.tolist() == ["ts_code", "trade_date", "factor_value"]
    assert all("pyarrow" in str(projected[column].dtype) for column in projected.columns)
    assert projected["factor_value"].isna().sum() == 4
    assert profile["dtype_backend"] == "pyarrow"
    assert profile["row_count"] == len(full)
    assert profile["sample_rows"] > 0
    daily_keys, daily_profile = run_step4.read_parent_diagnostics_arrow_projection(
        path,
        run_step4.PARENT_DIAGNOSTIC_DAILY_COLUMNS,
        already_reserved_bytes=profile["estimated_arrow_frame_bytes"],
        available_memory_bytes=1024 * 1024,
    )
    assert daily_keys.columns.tolist() == ["ts_code", "trade_date"]
    assert all("pyarrow" in str(daily_keys[column].dtype) for column in daily_keys.columns)
    assert daily_profile["reserved_before_bytes"] == profile["estimated_arrow_frame_bytes"]
    assert pd.read_parquet(path).columns.tolist() == full.columns.tolist()


def test_arrow_projection_coverage_matches_reference_and_keeps_warmup_nulls(tmp_path: Path) -> None:
    run_step4 = _load_run_step4()
    path = tmp_path / "factor.parquet"
    full = _factor_parquet(path)
    projected, _ = run_step4.read_parent_diagnostics_arrow_projection(
        path,
        run_step4.PARENT_DIAGNOSTIC_FACTOR_COLUMNS,
        available_memory_bytes=1024 * 1024,
    )
    kwargs = {
        "signal_col": "factor_value",
        "actual_start": "20160104",
        "actual_end": "20160106",
        "effective_target_start": "20160104",
        "effective_target_end": "20160106",
        "formula_max_lookback": 2,
    }
    expected = run_step4.build_formal_signal_coverage_profile(result_df=full, **kwargs)
    actual = run_step4.build_formal_signal_coverage_profile(result_df=projected, **kwargs)
    assert actual == expected
    assert actual["warmup_skipped_dates"] == 1
    assert actual["coverage_non_null"] == 2


def test_streamed_parent_summary_matches_coverage_without_full_pandas_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_step4 = _load_run_step4()
    path = tmp_path / "factor.parquet"
    full = _factor_parquet(path)

    def fail_full_pandas_read(*_args, **_kwargs):
        raise AssertionError("streamed parent diagnostics must not call pandas.read_parquet")

    monkeypatch.setattr(run_step4.pd, "read_parquet", fail_full_pandas_read)
    summary, profile = run_step4.stream_parent_diagnostics_summary(
        path,
        run_step4.PARENT_DIAGNOSTIC_FACTOR_COLUMNS,
        signal_col="factor_value",
        available_memory_bytes=1024 * 1024,
    )
    kwargs = {
        "signal_col": "factor_value",
        "actual_start": "20160104",
        "actual_end": "20160106",
        "effective_target_start": "20160104",
        "effective_target_end": "20160106",
        "formula_max_lookback": 2,
    }
    expected = run_step4.build_formal_signal_coverage_profile(result_df=full, **kwargs)
    actual = run_step4.build_formal_signal_coverage_profile_from_stream_summary(
        summary=summary,
        **kwargs,
    )
    assert actual == expected
    assert summary["row_count"] == len(full)
    assert summary["ticker_count"] == 2
    assert profile["mode"] == "streamed_arrow_batches_no_parent_frame"


def test_projection_budget_fails_closed_before_full_read(tmp_path: Path) -> None:
    run_step4 = _load_run_step4()
    path = tmp_path / "factor.parquet"
    _factor_parquet(path)
    with pytest.raises(SystemExit, match="PARENT_DIAGNOSTICS_MEMORY_BUDGET"):
        run_step4.read_parent_diagnostics_arrow_projection(
            path,
            run_step4.PARENT_DIAGNOSTIC_FACTOR_COLUMNS,
            available_memory_bytes=1,
        )


def test_projection_route_requires_every_explicit_local_condition() -> None:
    run_step4 = _load_run_step4()
    base = {
        "prepared_derived_state": True,
        "custom_primary": {"backend": "study_local"},
        "local_is_only": True,
        "shared_context_enabled": False,
    }
    assert run_step4.parent_diagnostics_arrow_projection_eligible(**base) is True
    for field, value in (("prepared_derived_state", False), ("custom_primary", None), ("local_is_only", False), ("shared_context_enabled", True)):
        candidate = {**base, field: value}
        assert run_step4.parent_diagnostics_arrow_projection_eligible(**candidate) is False


def test_factor_key_order_check_avoids_sorted_copy_for_projection_domain() -> None:
    run_step4 = _load_run_step4()
    ordered = pd.DataFrame(
        {"ts_code": ["000001.SZ", "000001.SZ", "000002.SZ"], "trade_date": ["20160104", "20160105", "20160104"]}
    ).convert_dtypes(dtype_backend="pyarrow")
    assert run_step4.is_sorted_by_factor_key_without_sort(ordered) is True
    assert run_step4.is_sorted_by_factor_key_without_sort(ordered.iloc[[1, 0, 2]].reset_index(drop=True)) is False


def _formal_step4_identity() -> dict[str, object]:
    return {
        "producer": "step4_formal_compute",
        "is_formal_factor_values": True,
        "report_id": "RPT_PFVV",
        "factor_id": "PFVV_SOURCE_BASELINE",
        "implementation_mode": "direct_code",
        "spec_hash": "spec-v1",
        "code_hash": "code-v1",
        "data_catalog_hash": "catalog-v1",
        "data_api_contract_version": "factorforge_step4_data_contract_v1",
        "universe_hash": "universe-v1",
        "frequency": "daily",
        "window": {"start": "20160104", "end": "20250711"},
    }


def _prior_step4_metadata(identity: dict[str, object]) -> dict[str, object]:
    return {
        "step4_factor_io_profile": {
            "source": "step4_prepared_derived_state_partitioned_controller",
            "recomputed_factor": True,
        },
        "step4_formal_factor_identity": identity,
    }


def test_matching_step4_formal_parquet_reuses_current_readback_without_full_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_step4 = _load_run_step4()
    parquet_path = tmp_path / "formal_factor.parquet"
    _factor_parquet(parquet_path)
    identity = _formal_step4_identity()

    def fail_full_pandas_read(*_args, **_kwargs):
        raise AssertionError("formal reuse must not materialise the full parquet")

    monkeypatch.setattr(run_step4.pd, "read_parquet", fail_full_pandas_read)
    source, gate, reusable = run_step4.resolve_existing_step4_formal_reuse(
        _prior_step4_metadata(identity),
        identity,
        source_artifact=str(parquet_path),
    )

    assert reusable is True
    assert source["source"] == "prior_step4_parquet"
    assert gate["decision"] == "reuse_allowed"
    assert gate["artifact_readback"]["observed_now"] is True
    assert gate["artifact_readback"]["historical_binding_present"] is False
    assert len(gate["artifact_readback"]["actual"]["selected_factor_sha256"]) == 64

    repeated_meta = _prior_step4_metadata(identity)
    repeated_meta["step4_factor_io_profile"] = {
        "source": "prior_step4_parquet",
        "recomputed_factor": False,
    }
    source, repeated_gate, repeated_reusable = run_step4.resolve_existing_step4_formal_reuse(
        repeated_meta,
        identity,
        source_artifact=str(parquet_path),
    )
    assert repeated_reusable is True
    assert source["source"] == "prior_step4_parquet"
    assert repeated_gate["artifact_readback"]["observed_now"] is True


def test_formal_reuse_rejects_identity_or_prior_byte_mismatch(tmp_path: Path) -> None:
    run_step4 = _load_run_step4()
    parquet_path = tmp_path / "formal_factor.parquet"
    _factor_parquet(parquet_path)
    identity = _formal_step4_identity()
    bad_expected = {**identity, "code_hash": "different-code"}
    _, mismatch_gate, reusable = run_step4.resolve_existing_step4_formal_reuse(
        _prior_step4_metadata(identity),
        bad_expected,
        source_artifact=str(parquet_path),
    )
    assert reusable is False
    assert mismatch_gate["decision"] == "recompute_required"
    assert "code_hash" in mismatch_gate["mismatched_fields"]

    observed = run_step4.formal_factor_parquet_readback_profile(
        parquet_path, include_key_hash=False
    )
    bound_identity = {
        **identity,
        "selected_factor_sha256": "0" * 64,
        "selected_factor_row_count": observed["selected_factor_row_count"],
        "selected_factor_schema": observed["selected_factor_schema"],
    }
    _, byte_gate, reusable = run_step4.resolve_existing_step4_formal_reuse(
        _prior_step4_metadata(bound_identity),
        identity,
        source_artifact=str(parquet_path),
    )
    assert reusable is False
    assert byte_gate["decision"] == "recompute_required"
    assert "selected_factor_sha256" in byte_gate["mismatched_fields"]


def test_step3b_sample_is_never_reused_as_formal_step4_parquet(tmp_path: Path) -> None:
    run_step4 = _load_run_step4()
    parquet_path = tmp_path / "factor_values.parquet"
    _factor_parquet(parquet_path)
    identity = _formal_step4_identity()
    sample_meta = {
        **_prior_step4_metadata(identity),
        "producer": "step3b_sample_proof",
    }
    source, gate, reusable = run_step4.resolve_existing_step4_formal_reuse(
        sample_meta,
        identity,
        source_artifact=str(parquet_path),
    )
    assert reusable is False
    assert source["source"] == "step3b_sample_or_legacy_factor_parquet"
    assert gate is None
