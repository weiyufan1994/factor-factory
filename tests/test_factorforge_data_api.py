from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _write_clean_daily_layer(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260102",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "vol": 1000.0,
                "amount": 10200.0,
            },
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260105",
                "open": 10.2,
                "high": 10.7,
                "low": 10.0,
                "close": 10.4,
                "vol": 1100.0,
                "amount": 11440.0,
            },
        ]
    ).to_parquet(root / "daily_clean.parquet", index=False)
    (root / "daily_clean.meta.json").write_text(
        json.dumps(
            {
                "policy": {
                    "drop_suspended": True,
                    "drop_limit_events": True,
                    "invalid_days_do_not_enter_window": True,
                    "minimum_effective_days": 10,
                },
                "clean_meta": {"counts": {"rows": 2}, "drop_counts": {"limit_events": 0}},
                "output_summary": {"rows": 2, "tickers": 1, "trade_dates": 2},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_clean_daily_bar_resolution_reports_policy_schema_and_coverage(tmp_path):
    from factor_factory.data_api import resolve_data_api_dataset

    clean_root = tmp_path / "clean"
    _write_clean_daily_layer(clean_root)
    catalog_path = tmp_path / "data_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "datasets": {
                    "clean_daily_bar": {
                        "dataset_id": "clean_daily_bar",
                        "source_uri": "s3://example/clean_daily_bar/v1/daily_clean.parquet",
                        "artifacts": {
                            "daily_parquet": str(clean_root / "daily_clean.parquet"),
                            "metadata_json": str(clean_root / "daily_clean.meta.json"),
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resolution = resolve_data_api_dataset(
        "clean_daily_bar",
        start="20260101",
        end="20260131",
        catalog_path=catalog_path,
    )

    assert resolution["dataset_id"] == "clean_daily_bar"
    assert resolution["status"] == "ready"
    assert resolution["access_mode"] == "catalog"
    assert resolution["artifacts"]["daily_parquet"] == str(clean_root / "daily_clean.parquet")
    assert resolution["daily_filter_policy"]["drop_suspended"] is True
    assert resolution["daily_filter_policy"]["invalid_days_do_not_enter_window"] is True
    assert "close" in resolution["schema"]["columns"]
    assert resolution["coverage"]["rows"] == 2


def test_missing_clean_minute_bar_resolution_blocks_without_silent_fallback(tmp_path):
    from factor_factory.data_api import resolve_data_api_dataset

    resolution = resolve_data_api_dataset(
        "clean_minute_bar",
        start="20260101",
        end="20260131",
        catalog_path=tmp_path / "missing_catalog.json",
    )

    assert resolution["dataset_id"] == "clean_minute_bar"
    assert resolution["status"] == "catalog_missing"
    assert resolution["block_code"] == "DATA_API_CATALOG_MISSING"
