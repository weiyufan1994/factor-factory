from __future__ import annotations

import builtins
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_step4():
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("run_step4_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_validate_step4():
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/validate_step4.py"
    spec = importlib.util.spec_from_file_location("validate_step4_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_step4_repo_identity_uses_and_validates_host_admitted_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted = "a" * 40
    monkeypatch.setenv("FACTORFORGE_ADMITTED_ENGINE_COMMIT", admitted)
    monkeypatch.setenv("FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY", "DENY")
    assert _load_run_step4().current_repo_sha() == admitted

    validator = _load_validate_step4()
    issues: list[dict[str, object]] = []
    validator.validate_acceptance_summary(
        {
            "version": "factorforge_production_acceptance_summary_v1",
            "report_id": "EVO_CHILD",
            "factor_id": "factor",
            "run_id": "run",
            "artifact_root": "/workspace",
            "repo_sha": "b" * 40,
            "step4": {
                "self_quant_status": "success",
                "qlib_native_status": "not_attempted",
            },
            "reuse": {"reuse_gate_status": "recomputed"},
            "side_effects": {
                "clean_data_mutated": False,
                "generated_code_digest_changed": False,
                "official_record_written": False,
                "search_worker_started": False,
            },
        },
        issues,
    )
    assert "BLOCK_ACCEPTANCE_SUMMARY_REPO_IDENTITY_MISMATCH" in {
        issue["code"] for issue in issues
    }


def test_evo_agent_import_does_not_require_data_api_and_fetch_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def forbid_independent_data_api(name, *args, **kwargs):
        if name == "factorforge_data_api" or name.startswith(
            "factorforge_data_api."
        ):
            raise AssertionError("Agent import must not load the Data API runtime")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_independent_data_api)
    run_step4 = _load_run_step4()
    assert run_step4.fetch_data_api_dataset is None
    monkeypatch.setenv("FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY", "DENY")
    with pytest.raises(
        SystemExit, match="EVO_AGENT_DATA_API_FETCH_FORBIDDEN"
    ):
        run_step4._host_fetch_data_api_dataset("clean_daily_bar")


def test_evo_host_prefetch_blocks_deferred_minute_query_before_agent_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_step4 = _load_run_step4()
    monkeypatch.setattr(
        run_step4,
        "materialize_step4_data_inputs_from_contract",
        lambda *_args, **_kwargs: (
            {
                "input_mode": "price_volume_minute",
                "daily_df_parquet": str(tmp_path / "daily.parquet"),
                "minute_streaming_query": {"dataset": "minute_bar"},
            },
            {"source": "host_prefetch"},
        ),
    )
    with pytest.raises(
        SystemExit, match="host_prefetch_did_not_materialize_minute"
    ):
        run_step4.materialize_evo_pre_release_data_receipt(
            report_id="EVO_CHILD",
            dpm={
                "research_windows": {
                    "is_start": "2025-01-01",
                    "is_end": "2025-12-31",
                },
                "step4_data_contract": {
                    "full_queries": {
                        "minute_bar": {"dataset": "minute_bar"}
                    }
                },
            },
            handoff={},
            run_dir=tmp_path,
        )


@pytest.mark.parametrize(
    "observed_dates",
    [
        ["20250103", "20250106"],
        ["20250102", "20250106"],
        ["20250106"],
    ],
)
def test_evo_host_prefetch_rejects_incomplete_calendar_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observed_dates: list[str],
) -> None:
    run_step4 = _load_run_step4()
    run_dir = tmp_path / "runs/EVO_CHILD"
    data_dir = run_dir / "step4_data_inputs"
    data_dir.mkdir(parents=True)
    daily = data_dir / "daily.parquet"
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": date, "close": 10.0}
            for date in observed_dates
        ]
    ).to_parquet(daily, index=False)
    contract = {
        "version": "factorforge_step4_data_contract_v1",
        "full_queries": {
            "clean_daily_bar": {
                "dataset": "clean_daily_bar",
                "start_date": "20250102",
                "end_date": "20250106",
                "fields": ["close"],
            }
        },
    }
    monkeypatch.setattr(
        run_step4,
        "validate_trusted_calendar_snapshot",
        lambda: {
            "dates": ["20250102", "20250103", "20250106"],
            "snapshot_id": "fixture-calendar",
            "raw_file_sha256": "a" * 64,
            "open_dates_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        run_step4,
        "materialize_step4_data_inputs_from_contract",
        lambda *_args, **_kwargs: (
            {"input_mode": "daily_only", "daily_df_parquet": str(daily)},
            {"source": "host_prefetch", "queries": contract["full_queries"]},
        ),
    )
    with pytest.raises(SystemExit, match="full_contract_input_coverage"):
        run_step4.materialize_evo_pre_release_data_receipt(
            report_id="EVO_CHILD",
            dpm={
                "research_windows": {
                    "is_start": "2025-01-02",
                    "is_end": "2025-01-06",
                },
                "step4_data_contract": contract,
            },
            handoff={},
            run_dir=run_dir,
        )


def test_evo_host_prefetch_receipt_binds_complete_calendar_and_required_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_step4 = _load_run_step4()
    run_dir = tmp_path / "runs/EVO_CHILD"
    data_dir = run_dir / "step4_data_inputs"
    data_dir.mkdir(parents=True)
    daily = data_dir / "daily.parquet"
    expected_dates = ["20250102", "20250103", "20250106"]
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": date, "close": 10.0}
            for date in expected_dates
        ]
    ).to_parquet(daily, index=False)
    contract = {
        "version": "factorforge_step4_data_contract_v1",
        "full_queries": {
            "clean_daily_bar": {
                "dataset": "clean_daily_bar",
                "start_date": "20250102",
                "end_date": "20250106",
                "fields": ["close"],
            }
        },
    }
    monkeypatch.setattr(
        run_step4,
        "validate_trusted_calendar_snapshot",
        lambda: {
            "dates": expected_dates,
            "snapshot_id": "fixture-calendar",
            "raw_file_sha256": "a" * 64,
            "open_dates_sha256": "b" * 64,
        },
    )
    monkeypatch.setattr(
        run_step4,
        "materialize_step4_data_inputs_from_contract",
        lambda *_args, **_kwargs: (
            {"input_mode": "daily_only", "daily_df_parquet": str(daily)},
            {"source": "host_prefetch", "queries": contract["full_queries"]},
        ),
    )
    receipt = run_step4.materialize_evo_pre_release_data_receipt(
        report_id="EVO_CHILD",
        dpm={
            "research_windows": {
                "is_start": "2025-01-02",
                "is_end": "2025-01-06",
            },
            "step4_data_contract": contract,
        },
        handoff={},
        run_dir=run_dir,
    )
    coverage = receipt["artifacts"][0]["calendar_coverage"]
    assert receipt["full_contract_input"] is True
    assert coverage["expected_open_dates"] == expected_dates
    assert coverage["observed_dates"] == expected_dates
    assert coverage["coverage_ratio"] == 1.0
    assert coverage["required_fields"] == ["ts_code", "trade_date", "close"]


def _write_catalog(tmp_path: Path) -> Path:
    daily_path = tmp_path / "daily_clean.parquet"
    pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260102", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 1000.0, "amount": 10200.0, "pct_chg": 0.1},
            {"ts_code": "000002.SZ", "trade_date": "20260102", "open": 20.0, "high": 20.5, "low": 19.8, "close": 20.2, "vol": 2000.0, "amount": 40400.0, "pct_chg": 0.2},
        ]
    ).to_parquet(daily_path, index=False)
    catalog_path = tmp_path / "data_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "catalog_version": "factorforge_data_catalog_v1",
                "datasets": {
                    "clean_daily_bar": {
                        "uri": str(daily_path),
                        "format": "parquet",
                        "columns": ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"],
                        "qlib_field_map": {"$close": "close", "$ret": "pct_chg"},
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return catalog_path


def test_backend_failure_note_preserves_only_sanitized_error_class(tmp_path, monkeypatch):
    run_step4 = _load_run_step4()
    backend = tmp_path / "backend.py"
    backend.write_text(
        "raise ModuleNotFoundError(\"No module named 'required_backend_package'; token=TOPSECRET\")\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(run_step4, "runtime_python", lambda: Path(sys.executable))

    returncode, note = run_step4.run_backend_script(
        "REPORT",
        "self_quant_analyzer",
        backend,
        tmp_path / "payload.json",
        {},
    )

    assert returncode == 1
    assert "error_class=ModuleNotFoundError:required_backend_package" in note
    assert "TOPSECRET" not in note
    assert str(tmp_path) not in note


def test_step4_materializes_full_inputs_from_data_api_contract(tmp_path, monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.setenv("FACTORFORGE_BACKTEST_BASE_CACHE_ROOT", str(tmp_path / "backtest_base_cache"))
    monkeypatch.setenv("FACTORFORGE_DISABLE_CLEAN_DAILY_LOCAL_PARQUET", "1")
    catalog_path = _write_catalog(tmp_path)
    contract = {
        "version": "factorforge_step4_data_contract_v1",
        "data_api_package": "factorforge_data_api",
        "catalog_path": str(catalog_path),
        "formal_factor_values_owner": "Step4",
        "full_queries": {
            "clean_daily_bar": {
                "dataset": "clean_daily_bar",
                "start_date": "20260101",
                "end_date": "20260131",
                "universe": "a_share_all",
                "fields": ["open", "high", "low", "close", "vol", "amount", "pct_chg"],
                "frequency": "daily",
            }
        },
    }

    local_inputs, profile = run_step4.materialize_step4_data_inputs_from_contract("R", contract, tmp_path / "runs" / "R")

    daily_path = Path(local_inputs["daily_df_parquet"])
    assert local_inputs["input_mode"] == "daily_only"
    assert daily_path.exists()
    assert profile["source"] == "factorforge_data_api_full_query"
    assert profile["result_metadata"]["clean_daily_bar"]["status"] == "ready"
    assert len(pd.read_parquet(daily_path)) == 2


def test_step4_does_not_reuse_step3b_sample_or_legacy_factor_parquet():
    run_step4 = _load_run_step4()

    classified = run_step4.classify_existing_factor_parquet_source({"producer": "step3b_sample_proof"})

    assert classified["source"] == "step3b_sample_or_legacy_factor_parquet"
    assert classified["upstream_recomputed_factor"] is False


def test_step4_rejects_backtest_base_cache_with_polluted_daily_basic_controls(tmp_path, monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.setenv("FACTORFORGE_BACKTEST_BASE_CACHE_ROOT", str(tmp_path / "backtest_base_cache"))
    monkeypatch.setenv("FACTORFORGE_BACKTEST_BASE_MIN_CONTROL_TICKERS", "2")
    contract = {
        "version": "factorforge_step4_data_contract_v1",
        "data_api_package": "factorforge_data_api",
        "catalog_path": str(tmp_path / "catalog.json"),
        "formal_factor_values_owner": "Step4",
        "full_queries": {
            "clean_daily_bar": {
                "dataset": "clean_daily_bar",
                "start_date": "20200101",
                "end_date": "20200131",
                "universe": "a_share_all",
            },
            "daily_basic": {
                "dataset": "daily_basic",
                "start_date": "20200101",
                "end_date": "20200131",
                "universe": "a_share_all",
                "fields": ["turnover_rate"],
            },
        },
    }
    polluted_base = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20200102", "close": 10.0, "turnover_rate": 1.0},
            {"ts_code": "000002.SZ", "trade_date": "20200102", "close": 20.0, "turnover_rate": None},
            {"ts_code": "000003.SZ", "trade_date": "20200102", "close": 30.0, "turnover_rate": None},
        ]
    )
    run_step4._write_backtest_base_cache(polluted_base, contract, result_metadata={})

    cached_path, profile = run_step4._load_backtest_base_cache(contract)

    assert cached_path is None
    assert profile is None


def test_step4_rejects_cache_hash_or_query_window_drift(tmp_path, monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.setenv(
        "FACTORFORGE_BACKTEST_BASE_CACHE_ROOT", str(tmp_path / "backtest_base_cache")
    )
    contract = {
        "version": "factorforge_step4_data_contract_v1",
        "data_api_package": "factorforge_data_api",
        "full_queries": {
            "clean_daily_bar": {
                "dataset": "clean_daily_bar",
                "start_date": "20200101",
                "end_date": "20200131",
            }
        },
    }
    out_of_window = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20200102", "close": 10.0},
            {"ts_code": "000001.SZ", "trade_date": "20200203", "close": 11.0},
        ]
    )
    data_path, _profile = run_step4._write_backtest_base_cache(
        out_of_window, contract, result_metadata={}
    )
    cached_path, profile = run_step4._load_backtest_base_cache(contract)
    assert cached_path is None
    assert profile is None

    in_window = out_of_window.iloc[:1].copy()
    data_path, _profile = run_step4._write_backtest_base_cache(
        in_window, contract, result_metadata={}
    )
    data_path.write_bytes(data_path.read_bytes() + b"tamper")
    cached_path, profile = run_step4._load_backtest_base_cache(contract)
    assert cached_path is None
    assert profile is None


def test_step4_optional_legacy_paths_skip_permission_errors(monkeypatch):
    run_step4 = _load_run_step4()
    worker_cache = Path(
        "/home/ubuntu/factorforge_data_api_cache/backtest_base_daily_controls_v1"
    )
    worker_parent = worker_cache.parent
    legacy_qlib = Path("/home/ubuntu/.qlib/qlib_data/cn_data")
    legacy_minute = Path(
        "/home/ubuntu/factorforge_data_api_cache/"
        "s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6"
    )
    legacy_minute_alt = Path("/home/ubuntu/.qlib/raw_tushare/分钟数据/raw/stk_mins_1min")
    inaccessible_exists = {
        worker_cache,
        legacy_qlib,
        legacy_minute,
    }
    original_exists = Path.exists
    original_is_dir = Path.is_dir

    def guarded_exists(path):
        if path in inaccessible_exists:
            raise PermissionError("optional legacy path is outside the service boundary")
        if path == worker_parent:
            return True
        if path == legacy_minute_alt:
            return True
        return original_exists(path)

    def guarded_is_dir(path):
        if path == legacy_minute_alt:
            raise PermissionError("optional legacy directory check denied")
        return original_is_dir(path)

    monkeypatch.delenv("FACTORFORGE_BACKTEST_BASE_CACHE_ROOT", raising=False)
    monkeypatch.delenv("FACTORFORGE_DATA_CACHE", raising=False)
    monkeypatch.delenv("FACTORFORGE_LOCAL_MINUTE_ROOT", raising=False)
    monkeypatch.delenv("FACTORFORGE_LOCAL_DATA_ROOT", raising=False)
    monkeypatch.setattr(Path, "exists", guarded_exists)
    monkeypatch.setattr(Path, "is_dir", guarded_is_dir)

    assert run_step4._backtest_base_cache_root() == (
        Path.home() / ".cache" / "factorforge_data_api" / "backtest_base_daily_controls_v1"
    )
    assert legacy_qlib not in [
        path
        for path in run_step4._default_qlib_provider_candidates("R")
        if run_step4._legacy_path_if_accessible(path) is not None
    ]
    assert run_step4._local_minute_partition_roots() == []


def test_step4_explicit_qlib_provider_permission_error_blocks(tmp_path, monkeypatch):
    run_step4 = _load_run_step4()
    explicit = tmp_path / "qlib-provider"
    original_exists = Path.exists

    def guarded_exists(path):
        if path == explicit:
            raise PermissionError("configured qlib provider is inaccessible")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", guarded_exists)

    with pytest.raises(SystemExit, match="BLOCK_STEP4_EXPLICIT_PATH_UNAVAILABLE"):
        run_step4.preflight_qlib_native("R", {"provider_uri": str(explicit)})


@pytest.mark.parametrize(
    ("setting", "relative"),
    [
        ("FACTORFORGE_LOCAL_MINUTE_ROOT", ""),
        ("FACTORFORGE_LOCAL_DATA_ROOT", "分钟数据/raw/stk_mins_1min"),
        (
            "FACTORFORGE_DATA_CACHE",
            "s3_parquet/minute_bar-raw_v1-0b2b836c57d763c6",
        ),
    ],
)
def test_step4_explicit_minute_path_permission_error_blocks(
    tmp_path,
    monkeypatch,
    setting,
    relative,
):
    run_step4 = _load_run_step4()
    root = tmp_path / setting.lower()
    candidate = root / relative if relative else root
    original_exists = Path.exists

    def guarded_exists(path):
        if path == candidate:
            raise PermissionError("configured minute path is inaccessible")
        return original_exists(path)

    for name in (
        "FACTORFORGE_LOCAL_MINUTE_ROOT",
        "FACTORFORGE_LOCAL_DATA_ROOT",
        "FACTORFORGE_DATA_CACHE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(setting, str(root))
    monkeypatch.setattr(Path, "exists", guarded_exists)

    with pytest.raises(SystemExit, match="BLOCK_STEP4_EXPLICIT_PATH_UNAVAILABLE"):
        run_step4._local_minute_partition_roots()


def test_web_evaluation_contract_must_match_step4_semantics():
    run_step4 = _load_run_step4()
    contract = {
        "version": "factorforge_web_evaluation_contract_v2",
        "rebalance_frequency": "daily",
        "signal_timestamp_policy": "after_close_t",
        "position_entry_policy": "close_t_plus_1",
        "position_exit_policy": "close_t_plus_2",
        "payoff_label_expression": "close.shift(-2) / close.shift(-1) - 1",
        "availability_lags": ["t open is available after the opening auction"],
        "missing_data_policy": "drop and audit missing rows",
        "forward_horizon": "1d",
        "label_policy": {
            "horizon": "one_trading_day_after_execution",
            "return_type": "simple",
            "entry_price_field": "close",
            "exit_price_field": "close",
            "execution_lag_sessions": 1,
            "holding_period_sessions": 1,
            "return_window": "close_t_plus_1_to_close_t_plus_2",
        },
        "transaction_cost_bps": 30.0,
        "cost_model_id": "factorforge_step4_turnover_30bps_v1",
        "cost_formula": "one_way_turnover * 0.003",
    }
    fsm = {
        "evaluation_contract": contract,
        "canonical_spec": {"evaluation_contract": contract},
    }

    run_step4.validate_web_evaluation_contract(fsm)
    fsm["evaluation_contract"] = {**contract, "transaction_cost_bps": 10.0}
    with pytest.raises(SystemExit, match="WEB_EVALUATION_CONTRACT_UNSUPPORTED"):
        run_step4.validate_web_evaluation_contract(fsm)
    for field in ("position_exit_policy", "payoff_label_expression"):
        missing = dict(contract)
        missing.pop(field)
        fsm["evaluation_contract"] = missing
        with pytest.raises(
            SystemExit,
            match="WEB_EVALUATION_CONTRACT_UNSUPPORTED",
        ):
            run_step4.validate_web_evaluation_contract(fsm)


def test_web_shared_evaluation_uses_delayed_close_ratio_not_pct_chg(
    tmp_path,
    monkeypatch,
):
    run_step4 = _load_run_step4()
    monkeypatch.setattr(
        run_step4,
        "validate_trusted_calendar_snapshot",
        lambda: {
            "dates": [
                "2026-01-02",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
            ]
        },
    )
    factor_df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260102", "signal": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260105", "signal": 2.0},
        ]
    )
    daily_df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260102", "close": 100.0, "pct_chg": 0.0, "turnover_rate": 1.0, "ln_mcap_free": 20.0, "volume_ratio": 0.8},
            {"ts_code": "000001.SZ", "trade_date": "20260105", "close": 110.0, "pct_chg": 2.0, "turnover_rate": 1.1, "ln_mcap_free": 20.1, "volume_ratio": 0.9},
            {"ts_code": "000001.SZ", "trade_date": "20260106", "close": 121.0, "pct_chg": 3.0, "turnover_rate": 1.2, "ln_mcap_free": 20.2, "volume_ratio": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260107", "close": 108.9, "pct_chg": 4.0, "turnover_rate": 1.3, "ln_mcap_free": 20.3, "volume_ratio": 1.1},
        ]
    )
    factor_path = tmp_path / "factor.parquet"
    daily_path = tmp_path / "daily.parquet"
    factor_df.to_parquet(factor_path, index=False)
    daily_df.to_parquet(daily_path, index=False)
    contract = {
        "version": "factorforge_web_evaluation_contract_v2",
        "position_exit_policy": "close_t_plus_2",
        "payoff_label_expression": "close.shift(-2) / close.shift(-1) - 1",
        "label_policy": {
            "horizon": "one_trading_day_after_execution",
            "return_type": "simple",
            "entry_price_field": "close",
            "exit_price_field": "close",
            "execution_lag_sessions": 1,
            "holding_period_sessions": 1,
            "return_window": "close_t_plus_1_to_close_t_plus_2",
        },
        "proof_control_columns": [
            "pct_chg",
            "turnover_rate",
            "ln_mcap_free",
            "volume_ratio",
        ],
        "diagnostic_trials": [
            {
                "trial_id": "diag_close",
                "role": "standalone_component",
                "component_id": "close_component",
                "formula_or_law": "-close",
                "signal_column": "diagnostic__diag_close",
                "affects_acceptance": False,
            }
        ],
    }

    context = run_step4.build_shared_evaluation_context(
        report_id="R",
        factor_id="F",
        implementation_mode_decision={"implementation_mode": "operator"},
        base_identity={"spec_hash": "spec", "code_hash": "code"},
        run_dir=tmp_path / "run",
        factor_df=factor_df,
        daily_df=daily_df,
        signal_col="signal",
        factor_parquet_path=factor_path,
        daily_input_path=daily_path,
        target_window={"start": "20260102", "end": "20260107"},
        effective_target_window={"start": "20260102", "end": "20260107"},
        evaluation_contract=contract,
    )

    daily_forward = pd.read_parquet(
        context["paths"]["daily_forward_returns_parquet"]
    )
    merged = pd.read_parquet(context["paths"]["merged_signal_return_parquet"])
    assert daily_forward.columns.is_unique
    assert merged.columns.is_unique
    assert daily_forward.columns.tolist().count("pct_chg") == 1
    assert merged.columns.tolist().count("pct_chg") == 1
    first = float(merged.loc[merged["trade_date"] == "20260102", "future_return_1d"].iloc[0])
    assert first == pytest.approx(121.0 / 110.0 - 1.0)
    assert first != pytest.approx(0.02)
    first_row = merged.loc[merged["trade_date"] == "20260102"].iloc[0]
    assert str(first_row["label_start_date"]) == "20260105"
    assert str(first_row["label_end_date"]) == "20260106"
    assert float(first_row["label_start_price"]) == pytest.approx(110.0)
    assert float(first_row["label_end_price"]) == pytest.approx(121.0)
    assert float(first_row["pct_chg"]) == pytest.approx(0.0)
    assert float(first_row["turnover_rate"]) == pytest.approx(1.0)
    assert float(first_row["ln_mcap_free"]) == pytest.approx(20.0)
    assert float(first_row["volume_ratio"]) == pytest.approx(0.8)
    assert float(first_row["diagnostic__diag_close"]) == pytest.approx(-100.0)
    assert context["version"] == "factorforge_shared_evaluation_context_v2"
    assert context["label_policy"] == contract["label_policy"]


def test_web_shared_evaluation_excludes_suspended_security_label_path(
    tmp_path,
    monkeypatch,
):
    run_step4 = _load_run_step4()
    calendar = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    monkeypatch.setattr(
        run_step4,
        "validate_trusted_calendar_snapshot",
        lambda: {"dates": calendar},
    )
    factor_df = pd.DataFrame(
        [
            {"ts_code": code, "trade_date": "20260102", "signal": signal}
            for code, signal in (("000001.SZ", 1.0), ("000002.SZ", 2.0))
        ]
    )
    daily_rows = [
        {"ts_code": "000001.SZ", "trade_date": date, "close": close}
        for date, close in zip(calendar, [100.0, 101.0, 102.0, 103.0])
    ]
    daily_rows.extend(
        [
            {"ts_code": "000002.SZ", "trade_date": "20260102", "close": 200.0},
            {"ts_code": "000002.SZ", "trade_date": "20260106", "close": 202.0},
            {"ts_code": "000002.SZ", "trade_date": "20260107", "close": 203.0},
        ]
    )
    daily_df = pd.DataFrame(daily_rows)
    factor_path = tmp_path / "factor.parquet"
    daily_path = tmp_path / "daily.parquet"
    factor_df.to_parquet(factor_path, index=False)
    daily_df.to_parquet(daily_path, index=False)
    label_policy = {
        "horizon": "one_trading_day_after_execution",
        "return_type": "simple",
        "entry_price_field": "close",
        "exit_price_field": "close",
        "execution_lag_sessions": 1,
        "holding_period_sessions": 1,
        "return_window": "close_t_plus_1_to_close_t_plus_2",
    }

    context = run_step4.build_shared_evaluation_context(
        report_id="SUSPENSION",
        factor_id="F",
        implementation_mode_decision={"implementation_mode": "operator"},
        base_identity={"spec_hash": "spec", "code_hash": "code"},
        run_dir=tmp_path / "run",
        factor_df=factor_df,
        daily_df=daily_df,
        signal_col="signal",
        factor_parquet_path=factor_path,
        daily_input_path=daily_path,
        target_window={"start": "20260102", "end": "20260107"},
        effective_target_window={"start": "20260102", "end": "20260107"},
        evaluation_contract={
            "version": "factorforge_web_evaluation_contract_v2",
            "position_exit_policy": "close_t_plus_2",
            "payoff_label_expression": "close.shift(-2) / close.shift(-1) - 1",
            "label_policy": label_policy,
            "proof_control_columns": [],
        },
    )

    merged = pd.read_parquet(context["paths"]["merged_signal_return_parquet"])
    assert merged["code"].tolist() == ["000001.SZ"]
    assert merged.iloc[0]["label_start_date"] == "20260105"
    assert merged.iloc[0]["label_end_date"] == "20260106"


def test_web_shared_evaluation_dedupes_repeated_proof_control_input(
    tmp_path,
    monkeypatch,
):
    run_step4 = _load_run_step4()
    calendar = ["2026-01-02", "2026-01-05", "2026-01-06"]
    monkeypatch.setattr(
        run_step4,
        "validate_trusted_calendar_snapshot",
        lambda: {"dates": calendar},
    )
    factor_df = pd.DataFrame(
        [{"ts_code": "000001.SZ", "trade_date": "20260102", "signal": 1.0}]
    )
    daily_df = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": date.replace("-", ""),
                "close": 100.0 + index,
                "pct_chg": float(index),
                "turnover_rate": 1.0 + index,
            }
            for index, date in enumerate(calendar)
        ]
    )
    factor_path = tmp_path / "factor.parquet"
    daily_path = tmp_path / "daily.parquet"
    factor_df.to_parquet(factor_path, index=False)
    daily_df.to_parquet(daily_path, index=False)

    context = run_step4.build_shared_evaluation_context(
        report_id="REPEATED_CONTROLS",
        factor_id="F",
        implementation_mode_decision={"implementation_mode": "operator"},
        base_identity={"spec_hash": "spec", "code_hash": "code"},
        run_dir=tmp_path / "run",
        factor_df=factor_df,
        daily_df=daily_df,
        signal_col="signal",
        factor_parquet_path=factor_path,
        daily_input_path=daily_path,
        target_window={"start": "20260102", "end": "20260106"},
        effective_target_window={"start": "20260102", "end": "20260106"},
        evaluation_contract={
            "version": "factorforge_web_evaluation_contract_v2",
            "label_policy": {},
            "proof_control_columns": [
                "pct_chg",
                "pct_chg",
                "turnover_rate",
                "turnover_rate",
            ],
        },
    )

    daily_forward = pd.read_parquet(
        context["paths"]["daily_forward_returns_parquet"]
    )
    merged = pd.read_parquet(context["paths"]["merged_signal_return_parquet"])
    assert daily_forward.columns.is_unique
    assert merged.columns.is_unique
    assert daily_forward.columns.tolist().count("pct_chg") == 1
    assert daily_forward.columns.tolist().count("turnover_rate") == 1
    assert merged.columns.tolist().count("pct_chg") == 1
    assert merged.columns.tolist().count("turnover_rate") == 1


def test_web_shared_evaluation_rejects_whitespace_mutated_proof_control(
    tmp_path,
):
    run_step4 = _load_run_step4()
    factor_df = pd.DataFrame(
        [{"ts_code": "000001.SZ", "trade_date": "20260102", "signal": 1.0}]
    )
    daily_df = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260102",
                "close": 100.0,
                "pct_chg": 1.0,
            }
        ]
    )
    factor_path = tmp_path / "factor.parquet"
    daily_path = tmp_path / "daily.parquet"
    factor_df.to_parquet(factor_path, index=False)
    daily_df.to_parquet(daily_path, index=False)

    with pytest.raises(
        ValueError,
        match=r"shared evaluation context requires daily columns: \[' pct_chg '\]",
    ):
        run_step4.build_shared_evaluation_context(
            report_id="WHITESPACE_CONTROL",
            factor_id="F",
            implementation_mode_decision={"implementation_mode": "operator"},
            base_identity={"spec_hash": "spec", "code_hash": "code"},
            run_dir=tmp_path / "run",
            factor_df=factor_df,
            daily_df=daily_df,
            signal_col="signal",
            factor_parquet_path=factor_path,
            daily_input_path=daily_path,
            target_window={"start": "20260102", "end": "20260102"},
            effective_target_window={"start": "20260102", "end": "20260102"},
            evaluation_contract={
                "version": "factorforge_web_evaluation_contract_v2",
                "label_policy": {},
                "proof_control_columns": [" pct_chg "],
            },
        )
