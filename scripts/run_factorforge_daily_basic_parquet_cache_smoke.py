#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_step4_module():
    path = REPO_ROOT / "skills" / "factor-forge-step4" / "scripts" / "run_step4.py"
    spec = importlib.util.spec_from_file_location("factorforge_step4_daily_basic_smoke_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Step4 module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_daily_basic_fixture(root: Path) -> None:
    base = root / "行情数据" / "daily_basic_incremental"
    (root / "行情数据").mkdir(parents=True, exist_ok=True)
    (root / "基础数据").mkdir(parents=True, exist_ok=True)
    for path in [
        root / "行情数据" / "daily.csv",
        root / "行情数据" / "adj_factor.csv",
        root / "基础数据" / "trade_cal.csv",
        root / "基础数据" / "stock_basic.csv",
        root / "基础数据" / "stock_st.csv",
    ]:
        path.write_text("stub\n", encoding="utf-8")
    rows = {
        "20240102": [
            {"ts_code": "000001.SZ", "trade_date": "20240102", "turnover_rate": 1.0, "volume_ratio": 0.9, "total_mv": 100.0, "circ_mv": 80.0, "pb": 1.1, "pe": 9.0},
            {"ts_code": "000002.SZ", "trade_date": "20240102", "turnover_rate": 2.0, "volume_ratio": 1.9, "total_mv": 200.0, "circ_mv": 160.0, "pb": 1.2, "pe": 10.0},
        ],
        "20240103": [
            {"ts_code": "000001.SZ", "trade_date": "20240103", "turnover_rate": 1.1, "volume_ratio": 1.0, "total_mv": 101.0, "circ_mv": 81.0, "pb": 1.1, "pe": 9.1},
            {"ts_code": "000002.SZ", "trade_date": "20240103", "turnover_rate": 2.1, "volume_ratio": 2.0, "total_mv": 201.0, "circ_mv": 161.0, "pb": 1.2, "pe": 10.1},
        ],
    }
    for trade_date, part_rows in rows.items():
        part_dir = base / f"trade_date={trade_date}"
        part_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(part_rows).to_csv(part_dir / f"daily_basic_{trade_date}.csv", index=False)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="factorforge_daily_basic_cache_smoke_") as tmp:
        tmpdir = Path(tmp)
        raw_root = tmpdir / "raw_tushare"
        parquet_root = tmpdir / "daily_basic_cache"
        backtest_base_root = tmpdir / "backtest_base_cache"
        write_daily_basic_fixture(raw_root)
        os.environ["FACTORFORGE_LOCAL_DATA_ROOT"] = str(raw_root)
        os.environ["FACTORFORGE_DAILY_BASIC_DIR"] = str(raw_root / "行情数据" / "daily_basic_incremental")
        os.environ["FACTORFORGE_DAILY_BASIC_PARQUET_ROOT"] = str(parquet_root)
        os.environ["FACTORFORGE_BACKTEST_BASE_CACHE_ROOT"] = str(backtest_base_root)

        from factor_factory.data_access.daily_basic import get_daily_basic_with_profile
        from factor_factory.data_api.client import fetch_data_api_dataset

        first_df, first_profile = get_daily_basic_with_profile(
            start="20240102",
            end="20240103",
            columns=["ts_code", "trade_date", "turnover_rate", "volume_ratio", "total_mv", "circ_mv"],
        )
        second_df, second_profile = get_daily_basic_with_profile(
            start="20240102",
            end="20240103",
            columns=["ts_code", "trade_date", "turnover_rate", "volume_ratio", "total_mv", "circ_mv"],
        )
        data_api_result = fetch_data_api_dataset(
            "daily_basic",
            start="20240102",
            end="20240103",
            fields=["turnover_rate", "volume_ratio", "total_mv", "circ_mv"],
        )
        data_api_meta = data_api_result.to_metadata()
        data_api_perf = data_api_meta.get("performance_profile") or {}

        step4 = load_step4_module()
        contract = {
            "version": "factorforge_step4_data_contract_v1",
            "formal_factor_values_owner": "Step4",
            "data_api_package": "factorforge_data_api",
            "catalog_path": None,
            "full_queries": {
                "clean_daily_bar": {
                    "dataset": "clean_daily_bar",
                    "start_date": "20240102",
                    "end_date": "20240103",
                    "fields": ["open", "high", "low", "close", "pct_chg"],
                    "universe": "a_share_all",
                    "frequency": "daily",
                },
                "daily_basic": {
                    "dataset": "daily_basic",
                    "start_date": "20240102",
                    "end_date": "20240103",
                    "fields": ["turnover_rate", "volume_ratio", "total_mv", "circ_mv"],
                    "universe": "a_share_all",
                    "frequency": "daily",
                },
            },
        }
        daily_df = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20240102", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "pct_chg": 0.5},
                {"ts_code": "000002.SZ", "trade_date": "20240102", "open": 20.0, "high": 20.2, "low": 19.9, "close": 20.1, "pct_chg": -0.2},
                {"ts_code": "000001.SZ", "trade_date": "20240103", "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "pct_chg": 1.0},
                {"ts_code": "000002.SZ", "trade_date": "20240103", "open": 20.1, "high": 20.3, "low": 20.0, "close": 20.2, "pct_chg": 0.4},
            ]
        )
        fetch_counts = {"clean_daily_bar": 0, "daily_basic": 0}

        def fake_fetch(query):
            dataset = query.get("dataset")
            fetch_counts[dataset] = fetch_counts.get(dataset, 0) + 1
            if dataset == "clean_daily_bar":
                return daily_df.copy(), {
                    "dataset_id": dataset,
                    "status": "ready",
                    "coverage": {"row_count": len(daily_df), "date_count": 2, "ticker_count": 2},
                }
            if dataset == "daily_basic":
                result = fetch_data_api_dataset(
                    "daily_basic",
                    start=query.get("start_date"),
                    end=query.get("end_date"),
                    fields=list(query.get("fields") or []),
                )
                return result.frame, result.to_metadata()
            raise AssertionError(f"unexpected dataset: {dataset}")

        original_fetch = step4._fetch_contract_frame
        step4._fetch_contract_frame = fake_fetch
        try:
            first_inputs, first_step4_profile = step4.materialize_step4_data_inputs_from_contract(
                "DAILY_BASIC_SMOKE",
                contract,
                tmpdir / "run1",
            )
            second_inputs, second_step4_profile = step4.materialize_step4_data_inputs_from_contract(
                "DAILY_BASIC_SMOKE",
                contract,
                tmpdir / "run2",
            )
        finally:
            step4._fetch_contract_frame = original_fetch

        first_base = (first_step4_profile.get("backtest_base_reuse_profile") or {})
        second_base = (second_step4_profile.get("backtest_base_reuse_profile") or {})
        checks = {
            "first_daily_basic_backfills_parquet": len(first_df) == 4 and first_profile.get("cache_status") == "backfilled_from_csv",
            "second_daily_basic_warm_cache_hit": len(second_df) == 4 and second_profile.get("cache_hit") is True,
            "data_api_daily_basic_reports_parquet": data_api_perf.get("daily_basic_selected_format") == "parquet",
            "data_api_daily_basic_reports_cache_hit": data_api_perf.get("daily_basic_cache_hit") is True,
            "step4_first_builds_backtest_base": first_base.get("backtest_base_reuse_hit") is False and Path(first_inputs["daily_df_parquet"]).exists(),
            "step4_second_reuses_backtest_base": second_base.get("backtest_base_reuse_hit") is True and Path(second_inputs["daily_df_parquet"]).exists(),
            "step4_second_skips_daily_fetch": fetch_counts.get("clean_daily_bar") == 1 and fetch_counts.get("daily_basic") == 1,
        }
        verdict = "ACCEPT" if all(checks.values()) else "REJECT"
        print(json.dumps({
            "verdict": verdict,
            "checks": checks,
            "first_profile": first_profile,
            "second_profile": second_profile,
            "data_api_performance_profile": data_api_perf,
            "first_step4_profile": first_step4_profile,
            "second_step4_profile": second_step4_profile,
            "fetch_counts": fetch_counts,
            "tmp_root": str(tmpdir),
        }, ensure_ascii=False, indent=2, default=str))
        if verdict != "ACCEPT":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
