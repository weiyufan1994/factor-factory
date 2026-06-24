#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_alpha101_operator_oos_refresh import forbidden_label_columns, resolve_catalog_path, source_fields_for_formula_field  # noqa: E402


def main() -> int:
    tmp_root = Path("/tmp/factorforge_alpha101_oos_refresh_smoke")
    if tmp_root.exists():
        import shutil

        shutil.rmtree(tmp_root)
    workspace = tmp_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_alpha101_operator_oos_refresh.py"),
        "--workspace",
        str(workspace),
        "--source-report-id",
        "SMOKE_ALPHA101_OOS_REFRESH",
        "--factor-id",
        "SMOKE",
        "--formula",
        "rank(close)",
        "--target-start",
        "20250714",
        "--target-end",
        "20250715",
        "--history-start",
        "20250714",
        "--universe",
        "000001.SZ,000002.SZ",
    ]
    env = dict(os.environ)
    env["FACTORFORGE_DATA_CACHE"] = str(tmp_root / "data_api_cache")
    completed = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env, check=False)
    if completed.returncode != 0:
        print(completed.stdout)
        print(completed.stderr, file=sys.stderr)
        return completed.returncode
    payload = json.loads(completed.stdout)
    factor_path = Path(payload["factor_values_path"])
    metadata_path = Path(payload["metadata_path"])
    compatibility_path = Path(payload["compatibility_path"])
    assert factor_path.exists(), factor_path
    assert metadata_path.exists(), metadata_path
    assert compatibility_path.exists(), compatibility_path
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    compatibility = json.loads(compatibility_path.read_text(encoding="utf-8"))
    parent_path = workspace / "runs" / "SMOKE_ALPHA101_OOS_REFRESH" / "factor_values__SMOKE_ALPHA101_OOS_REFRESH.parquet"
    checks = {
        "metadata_success": metadata.get("status") == "success",
        "window_scoped_output": "/oos_refresh/20250714_20250715/" in str(factor_path),
        "parent_factor_parquet_not_written": not parent_path.exists(),
        "formula_hash_present": bool(metadata.get("formula_ir", {}).get("formula_hash")),
        "revision_fitting_forbidden": metadata.get("refresh_policy", {}).get("revision_fitting_allowed") is False,
        "append_compatibility_accept": compatibility.get("verdict") == "ACCEPT",
        "no_future_return_label": compatibility.get("contains_future_return_label") is False,
        "no_forbidden_label_columns": compatibility.get("contains_forbidden_label_columns") is False
        and compatibility.get("forbidden_label_columns") == [],
        "forbidden_label_detector_blocks_common_labels": forbidden_label_columns(
            ["ts_code", "trade_date", "factor_value", "future_return_1d", "next_return", "target", "label", "lookahead_flag"]
        )
        == ["future_return_1d", "next_return", "target", "label", "lookahead_flag"],
        "default_catalog_resolves": bool(resolve_catalog_path(None)),
        "formula_alias_sources": all(
            {
                "volume": source_fields_for_formula_field("volume") == ["vol"],
                "returns": source_fields_for_formula_field("returns") == ["pct_chg"],
                "turnover": source_fields_for_formula_field("turnover") == ["turnover_rate"],
                "adv20": source_fields_for_formula_field("adv20") == ["vol"],
            }.values()
        ),
        "duplicate_key_count_zero": compatibility.get("duplicate_key_count") == 0,
        "rows_positive": payload.get("row_count", 0) > 0,
    }
    verdict = "ACCEPT" if all(checks.values()) else "BLOCK"
    print(json.dumps({"verdict": verdict, "checks": checks, "payload": payload}, ensure_ascii=False, indent=2))
    return 0 if verdict == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
