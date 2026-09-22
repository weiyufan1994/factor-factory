"""Recheck a completed candidate's daily projections without reading labels.

This is NOT a formal Step4 run or a full EVENT_U v2 recomputation. It only
compares the old raw U/score with the repaired cross-sectional mapping. Baseline
availability cannot be reconstructed from U alone, so no new factor is emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from candidate_v2 import _robust_z


def recheck(root: Path) -> dict:
    config = json.loads((root / "run_config.json").read_text())
    planned = config["planned_dates"]
    if not planned or planned != sorted(set(planned)):
        raise ValueError("expected nonempty unique ordered dates")
    if planned[0] < "20160104" or planned[-1] > "20250711":
        raise ValueError("only the user-selected IS window is supported")
    rows = []
    for date in planned:
        day = root / "days" / f"trade_date={date}"
        path = day / "branch_lattice.parquet"
        receipt = json.loads((day / "receipt.json").read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["files"]["branch_lattice"]:
            raise ValueError(f"existing output changed: {date}")
        frame = pd.read_parquet(path, columns=["ts_code", "trade_date", "event_u", "factor_value"])
        if set(frame["trade_date"].astype(str)) != {date} or frame["ts_code"].duplicated().any():
            raise ValueError(f"invalid existing stock-date partition: {date}")
        raw = pd.to_numeric(frame["event_u"], errors="coerce")
        old = pd.to_numeric(frame["factor_value"], errors="coerce")
        repaired_projection_only = -_robust_z(raw)
        rows.append({
            "date": date, "rows": len(frame), "raw_unique": int(raw.nunique()),
            "old_score_unique": int(old.nunique()),
            "repaired_projection_unique": int(repaired_projection_only.nunique()),
            "equal_raw_values_remain_tied": bool(pd.DataFrame({"u": raw, "s": repaired_projection_only}).groupby("u")["s"].nunique().le(1).all()),
        })
    return {
        "scope": "REAL_EXISTING_IS_OUTPUT_PROJECTION_DIAGNOSIS_ONLY",
        "date_count": len(rows), "stock_day_rows": sum(x["rows"] for x in rows),
        "raw_variable_dates": sum(x["raw_unique"] > 1 for x in rows),
        "old_variable_dates": sum(x["old_score_unique"] > 1 for x in rows),
        "repaired_projection_variable_dates": sum(x["repaired_projection_unique"] > 1 for x in rows),
        "formation_dates": [x for x in rows if x["date"] in ("20160129", "20160229", "20160331")],
        "all_ties_preserved": all(x["equal_raw_values_remain_tied"] for x in rows),
        "full_v2_event_recompute": False,
        "event_baseline_coverage_reverified": False,
        "factor_values_written": False, "returns_read": False, "oos_read": False,
        "research_complete": False,
        "limitation": "A raw-U-only recheck cannot certify per-stock warmup or baseline coverage; full event-state replay remains necessary before evaluation.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(recheck(args.input_root), ensure_ascii=False, indent=2))
