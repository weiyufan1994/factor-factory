from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_qlib_adapter(monkeypatch, root: Path):
    monkeypatch.setenv("FACTORFORGE_ROOT", str(root))
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/qlib_backtest_adapter.py"
    spec = importlib.util.spec_from_file_location("qlib_resource_guard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_qlib_native_resource_guard_skips_large_full_native_backtest(monkeypatch, tmp_path):
    report_id = "QLIB_RESOURCE_GUARD_SMOKE"
    adapter = _load_qlib_adapter(monkeypatch, tmp_path)
    monkeypatch.setenv("FACTORFORGE_QLIB_NATIVE_MAX_MERGED_ROWS", "1")

    cfg_path = tmp_path / "objects/data_prep_master" / f"qlib_adapter_config__{report_id}.json"
    factor_path = tmp_path / "runs" / report_id / f"factor_values__{report_id}.parquet"
    cfg_path.parent.mkdir(parents=True)
    factor_path.parent.mkdir(parents=True)
    cfg_path.write_text('{"sample_window": {"start": "20160101", "end": "current"}}')
    factor_path.write_text("exists")

    factor_df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20160104", "signal": 1.0},
            {"ts_code": "000002.SZ", "trade_date": "20160104", "signal": 2.0},
            {"ts_code": "000003.SZ", "trade_date": "20160104", "signal": 3.0},
            {"ts_code": "000001.SZ", "trade_date": "20160105", "signal": 1.5},
            {"ts_code": "000002.SZ", "trade_date": "20160105", "signal": 2.5},
            {"ts_code": "000003.SZ", "trade_date": "20160105", "signal": 3.5},
        ]
    )
    daily_df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "trade_date": "20160104", "close": 10.0, "pct_chg": 0.0},
            {"ts_code": "000002.SZ", "trade_date": "20160104", "close": 20.0, "pct_chg": 0.0},
            {"ts_code": "000003.SZ", "trade_date": "20160104", "close": 30.0, "pct_chg": 0.0},
            {"ts_code": "000001.SZ", "trade_date": "20160105", "close": 11.0, "pct_chg": 10.0},
            {"ts_code": "000002.SZ", "trade_date": "20160105", "close": 19.0, "pct_chg": -5.0},
            {"ts_code": "000003.SZ", "trade_date": "20160105", "close": 33.0, "pct_chg": 10.0},
        ]
    )

    monkeypatch.setattr(adapter, "load_factor_values_with_signal", lambda _report_id: (factor_df.copy(), "signal", "smoke_factor"))
    monkeypatch.setattr(adapter, "load_daily_snapshot", lambda _report_id, columns=None: daily_df.copy())
    monkeypatch.setattr(
        adapter,
        "_import_native_qlib",
        lambda: (_ for _ in ()).throw(AssertionError("native qlib should be resource-guarded")),
    )

    payload = adapter.run_qlib_backtest_stub(report_id)

    assert payload["status"] == "partial"
    assert payload["mode"] == "sample_stub"
    assert payload["qlib_native_status"] == "partial_payload"
    assert payload["resource_guard"]["native_backtest_skipped"] is True
    assert payload["resource_guard"]["reason"] == "merged_rows_exceeds_limit"
    assert payload["input_summary"]["merged_rows"] == 3
    assert payload["performance_profile"]["phase_seconds"]["native_resource_guard"] >= 0
