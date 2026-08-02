from __future__ import annotations

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


def test_web_shared_evaluation_uses_delayed_close_ratio_not_pct_chg(tmp_path):
    run_step4 = _load_run_step4()
    factor_df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260102", "signal": 1.0},
            {"ts_code": "000001.SZ", "trade_date": "20260105", "signal": 2.0},
        ]
    )
    daily_df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20260102", "close": 100.0, "pct_chg": 0.0},
            {"ts_code": "000001.SZ", "trade_date": "20260105", "close": 110.0, "pct_chg": 2.0},
            {"ts_code": "000001.SZ", "trade_date": "20260106", "close": 121.0, "pct_chg": 3.0},
            {"ts_code": "000001.SZ", "trade_date": "20260107", "close": 108.9, "pct_chg": 4.0},
        ]
    )
    factor_path = tmp_path / "factor.parquet"
    daily_path = tmp_path / "daily.parquet"
    factor_df.to_parquet(factor_path, index=False)
    daily_df.to_parquet(daily_path, index=False)
    contract = {
        "version": "factorforge_web_evaluation_contract_v2",
        "label_policy": {
            "horizon": "one_trading_day_after_execution",
            "return_type": "simple",
            "entry_price_field": "close",
            "exit_price_field": "close",
            "execution_lag_sessions": 1,
            "holding_period_sessions": 1,
            "return_window": "close_t_plus_1_to_close_t_plus_2",
        },
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

    merged = pd.read_parquet(context["paths"]["merged_signal_return_parquet"])
    first = float(merged.loc[merged["trade_date"] == "20260102", "future_return_1d"].iloc[0])
    assert first == pytest.approx(121.0 / 110.0 - 1.0)
    assert first != pytest.approx(0.02)
    assert context["version"] == "factorforge_shared_evaluation_context_v2"
    assert context["label_policy"] == contract["label_policy"]
