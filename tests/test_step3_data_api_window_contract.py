from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_step3():
    path = REPO_ROOT / "skills/factor-forge-step3/scripts/run_step3.py"
    spec = importlib.util.spec_from_file_location("run_step3_window_contract_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _ready_resolution(dataset: str, **kwargs):
    status = "proxy_ready" if dataset == "minute_bar" else "ready"
    return {
        "dataset_id": dataset,
        "status": status,
        "catalog_path": "/tmp/factorforge_data_catalog.json",
        "daily_filter_policy": {
            "drop_suspended": True,
            "drop_limit_events": True,
            "invalid_days_do_not_enter_window": True,
            "minimum_effective_days": 10,
        },
        "coverage": {"row_count": 1},
        "request": kwargs,
    }


def test_data_api_query_payload_normalizes_current_end_date(monkeypatch):
    run_step3 = _load_run_step3()
    monkeypatch.setenv("FACTORFORGE_DATA_API_CURRENT_END_DATE", "20260603")

    payload = run_step3.data_api_query_payload(
        "clean_daily_bar",
        {"start": "2016-01-01", "end": "current"},
        ["close"],
    )

    assert payload["start_date"] == "20160101"
    assert payload["end_date"] == "20260603"


def test_daily_step3a_snapshot_uses_query_safe_current_end(monkeypatch, tmp_path):
    run_step3 = _load_run_step3()
    monkeypatch.setenv("FACTORFORGE_DATA_API_CURRENT_END_DATE", "20260603")
    monkeypatch.setattr(run_step3, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_step3, "WORKSPACE", tmp_path)
    monkeypatch.setattr(run_step3.pd.DataFrame, "to_parquet", lambda self, path, index=False: Path(path).write_text("parquet-smoke"))
    monkeypatch.setattr(run_step3, "materialize_daily_audit_csv", lambda *args, **kwargs: {"csv_output_policy": "no_csv"})

    calls = []

    def fake_resolve(dataset, **kwargs):
        calls.append(("resolve", dataset, kwargs))
        return _ready_resolution(dataset, **kwargs)

    class FakeResult:
        status = "ready"
        frame = pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20160104",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "vol": 100.0,
                    "amount": 1010.0,
                    "pct_chg": 0.1,
                }
            ]
        )

        def to_metadata(self):
            return {"status": "ready"}

    def fake_fetch(dataset, **kwargs):
        calls.append(("fetch", dataset, kwargs))
        return FakeResult()

    monkeypatch.setattr(run_step3, "resolve_data_api_dataset", fake_resolve)
    monkeypatch.setattr(run_step3, "fetch_data_api_dataset", fake_fetch)

    result = run_step3.materialize_shared_daily_slice(
        "STEP3A_CURRENT_WINDOW_DAILY",
        {"start": "2016-01-01", "end": "current"},
        required_fields=["close"],
    )

    assert result["sample_window_actual"]["end"] == "current"
    assert result["step4_data_contract"]["full_queries"]["clean_daily_bar"]["end_date"] == "20260603"
    assert calls
    assert all(call[2].get("start") == "20160101" for call in calls)
    assert all(call[2].get("end") == "20260603" for call in calls)


def test_minute_step3a_snapshot_resolution_uses_query_safe_current_end(monkeypatch, tmp_path):
    run_step3 = _load_run_step3()
    monkeypatch.setenv("FACTORFORGE_DATA_API_CURRENT_END_DATE", "20260603")
    monkeypatch.setattr(run_step3, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run_step3, "WORKSPACE", tmp_path)

    calls = []

    def fake_resolve(dataset, **kwargs):
        calls.append((dataset, kwargs))
        return _ready_resolution(dataset, **kwargs)

    monkeypatch.setattr(run_step3, "resolve_data_api_dataset", fake_resolve)

    result = run_step3.build_local_price_volume_snapshots(
        "STEP3A_CURRENT_WINDOW_MINUTE",
        {"start": "2016-01-01", "end": "current"},
    )

    assert result["sample_window_actual"]["end"] == "current"
    assert result["step4_data_contract"]["full_queries"]["clean_daily_bar"]["end_date"] == "20260603"
    assert result["step4_data_contract"]["full_queries"]["minute_bar"]["end_date"] == "20260603"
    assert {dataset for dataset, _kwargs in calls} == {"clean_daily_bar", "minute_bar"}
    assert all(kwargs.get("start") == "20160101" for _dataset, kwargs in calls)
    assert all(kwargs.get("end") == "20260603" for _dataset, kwargs in calls)
