#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.data_access.minute_derived import (  # noqa: E402
    FLOW_STATE_REQUIRED_COLUMNS,
    MINUTE_DERIVED_FLOW_STATE_V1,
    load_flow_state_partitions,
    minute_derived_flow_state_requirement,
    research_window_contract,
)


def load_step4_module():
    path = REPO_ROOT / "skills" / "factor-forge-step4" / "scripts" / "run_step4.py"
    spec = importlib.util.spec_from_file_location("factorforge_step4_smoke_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import Step4 module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_minute_fixture(root: Path) -> None:
    rows = []
    for trade_date in ["20240102", "20240103"]:
        for code_i, ts_code in enumerate(["000001.SZ", "000002.SZ"]):
            for minute_i, hhmm in enumerate(["09:31:00", "10:01:00", "14:31:00", "14:49:00"]):
                base = 10 + code_i
                open_px = base + minute_i * 0.01
                close_px = open_px + (0.02 if (minute_i + code_i) % 2 == 0 else -0.01)
                amount = 1000 + code_i * 100 + minute_i * 10
                rows.append({
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "trade_time": f"{trade_date} {hhmm}",
                    "open": open_px,
                    "close": close_px,
                    "vol": amount / close_px,
                    "amount": amount,
                })
    frame = pd.DataFrame(rows)
    for trade_date, day in frame.groupby("trade_date"):
        out_dir = root / f"trade_date={trade_date}"
        out_dir.mkdir(parents=True, exist_ok=True)
        day.to_parquet(out_dir / "part-000.parquet", index=False)


class DerivedStateModule:
    @staticmethod
    def compute_factor_from_derived_state(daily_df, derived_state_df):
        del daily_df
        out = derived_state_df[["ts_code", "trade_date", "signed_pressure_sum", "gross_pressure_sum"]].copy()
        out["factor_value"] = out["signed_pressure_sum"] / out["gross_pressure_sum"].replace(0, pd.NA)
        return out[["ts_code", "trade_date", "factor_value"]].dropna()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="factorforge_minute_derived_smoke_") as tmp:
        tmpdir = Path(tmp)
        raw_root = tmpdir / "raw_minute"
        derived_root = tmpdir / "derived"
        write_minute_fixture(raw_root)

        backfill_cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_minute_derived_datamart.py"),
            "--start-date",
            "2024-01-02",
            "--end-date",
            "2024-01-03",
            "--minute-root",
            str(raw_root),
            "--output-root",
            str(derived_root),
            "--source-data-version",
            "smoke_raw_v1",
        ]
        proc = subprocess.run(backfill_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        backfill_ok = proc.returncode == 0 and '"verdict": "ACCEPT"' in proc.stdout

        loaded = load_flow_state_partitions(
            start_date="20240102",
            end_date="20240103",
            root=derived_root,
            cutoff_time="14:50:00",
            source_data_version="smoke_raw_v1",
            required_fields=FLOW_STATE_REQUIRED_COLUMNS,
        )
        load_ok = loaded.status == "ready" and len(loaded.frame) == 4

        step4 = load_step4_module()
        requirement = minute_derived_flow_state_requirement(
            start_date="2024-01-02",
            end_date="2024-01-03",
            root=derived_root,
            source_data_version="smoke_raw_v1",
        )
        daily_df = pd.DataFrame({
            "ts_code": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": ["20240102", "20240102", "20240103", "20240103"],
            "close": [10, 11, 10.1, 11.1],
        })
        minute_query = {"dataset": "minute_bar", "start_date": "20240102", "end_date": "20240103"}
        flow_state, load_profile = step4._load_required_minute_flow_state(
            requirement=requirement,
            daily_df=daily_df,
            minute_query=minute_query,
        )
        result, factor_profile = step4.compute_factor_from_minute_derived_state(
            DerivedStateModule,
            daily_df=daily_df,
            flow_state_df=flow_state,
        )
        step4_consume_ok = len(result) == 4 and factor_profile.get("compute_mode") == "module_compute_factor_from_derived_state"

        missing_token_ok = False
        try:
            step4._load_required_minute_flow_state(
                requirement=requirement,
                daily_df=pd.concat([daily_df, pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240104"], "close": [10.2]})], ignore_index=True),
                minute_query={"dataset": "minute_bar", "start_date": "20240102", "end_date": "20240104"},
            )
        except SystemExit as exc:
            missing_token_ok = str(exc).startswith("BLOCK_MINUTE_DERIVED_STATE_COVERAGE_INCOMPLETE")

        generic_guard_ok = step4._generic_minute_full_window_forbidden([f"2024{i:04d}" for i in range(121)])
        window = research_window_contract({"start": "2016-01-01", "end": "current"})
        window_ok = window["in_sample"]["end"] == "2025-07-11" and window["oos"]["policy"] == "holdout_only_no_revision_fitting"

        checks = {
            "backfill_runner_accepts": backfill_ok,
            "load_derived_state_ready": load_ok,
            "step4_consumes_derived_state": step4_consume_ok,
            "missing_coverage_blocks": missing_token_ok,
            "generic_full_window_streaming_forbidden": generic_guard_ok,
            "research_window_contract_oos_holdout": window_ok,
        }
        verdict = "ACCEPT" if all(checks.values()) else "BLOCK"
        print(json.dumps({
            "verdict": verdict,
            "checks": checks,
            "backfill_stdout": proc.stdout[-1000:],
            "backfill_stderr": proc.stderr[-1000:],
            "derived_profile": load_profile,
            "factor_profile": factor_profile,
            "tmp_root": str(tmpdir),
            "dataset_id": MINUTE_DERIVED_FLOW_STATE_V1,
        }, ensure_ascii=False, indent=2, default=str))
        raise SystemExit(0 if verdict == "ACCEPT" else 1)


if __name__ == "__main__":
    main()
