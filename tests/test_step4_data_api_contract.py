from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


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
