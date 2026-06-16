#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.state_reuse import (
    BLOCK_DATA_REQUEST_REQUIRED,
    BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN,
    BLOCK_STATE_COVERAGE_INSUFFICIENT,
    BLOCK_STATE_DEPENDENCY_UNDECLARED,
    BLOCK_STATE_SCHEMA_VERSION_MISMATCH,
    REVISION_DATA_PLAN_VERSION,
    STATE_DEPENDENCY_CONTRACT_VERSION,
    assert_no_raw_minute_full_window_scan,
    build_step4_state_reuse_provenance,
    portfolio_only_revision_allows_skip,
    validate_revision_data_plan,
)


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)


def expect_rc(name: str, proc: subprocess.CompletedProcess[str], rc: int, token: str | None = None) -> dict:
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ok = proc.returncode == rc and (token is None or token in output)
    if not ok:
        raise AssertionError(f"{name} failed: rc={proc.returncode} expected={rc} token={token}\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}")
    return {"name": name, "rc": proc.returncode, "token": token, "status": "PASS"}


def base_contract(dataset_id: str = "intraday_flow_state_v2") -> dict:
    return {
        "contract_version": STATE_DEPENDENCY_CONTRACT_VERSION,
        "required_datasets": [
            {
                "dataset_id": dataset_id,
                "schema_version": "intraday_flow_state_v2_schema_v2.1",
                "window": {"start": "20160104", "end": "20250711"},
                "required_fields": ["flow_z", "large_flow_z", "ret_1450"],
                "parameters": {"cutoff_time": "14:50:00"},
                "qa_required": True,
                "lookahead_policy_required": True,
                "no_future_intraday_minutes": True,
            }
        ],
        "allowed_missing_behavior": "block",
        "raw_minute_full_window_allowed": False,
        "bounded_smoke_allowed": True,
        "data_request_on_missing": True,
    }


def base_catalog() -> dict:
    return {
        "datasets": {
            "intraday_flow_state_v2": {
                "dataset_id": "intraday_flow_state_v2",
                "schema_version": "intraday_flow_state_v2_schema_v2.1",
                "schema": ["ts_code", "trade_date", "flow_z", "large_flow_z", "ret_1450"],
                "coverage": {"start": "20160104", "end": "20250711"},
                "qa_verdict": "ACCEPT",
                "qa_path": "/tmp/fake_qa/intraday_flow_state_v2.json",
                "materialized_root": "s3://example/factorforge/datamart/intraday_flow_state/v2",
                "lookahead_policy": {"no_future_intraday_minutes": True},
            }
        }
    }


def main() -> int:
    root = Path("/tmp/factorforge_state_reuse_contract_smoke")
    if not str(root).startswith("/tmp/"):
        raise SystemExit("refusing non-/tmp smoke root")
    shutil.rmtree(root, ignore_errors=True)
    results = []

    report_id = "state_reuse_smoke_report"
    factor_id = "state_reuse_smoke_factor"
    research_id = "state_reuse_smoke_research"
    contract_path = write_json(root / "contract.json", {"state_dependency_contract": base_contract()})
    catalog_path = write_json(root / "catalog.json", base_catalog())
    resolution_path = root / "state_resolution.json"
    request_dir = root / "data_requests"

    results.append(expect_rc("state_reuse_hit_smoke", run([
        sys.executable,
        "scripts/validate_factorforge_state_dependency.py",
        "--dependency-contract", str(contract_path),
        "--catalog", str(catalog_path),
        "--report-id", report_id,
        "--factor-id", factor_id,
        "--research-id", research_id,
        "--output-state-resolution", str(resolution_path),
        "--output-data-request-dir", str(request_dir),
    ]), 0))
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    if resolution.get("blocked") is not False or not resolution.get("reuse_hits"):
        raise AssertionError(f"expected reuse hit resolution: {resolution}")
    provenance = build_step4_state_reuse_provenance(state_resolution_path=resolution_path)
    if provenance.get("raw_minute_full_window_scan") is not False or provenance.get("reuse_hit") is not True:
        raise AssertionError(f"invalid Step4 provenance: {provenance}")

    missing_contract = write_json(root / "missing_contract.json", {"state_dependency_contract": base_contract("moneyflow_xxx_state_v1")})
    missing_resolution = root / "missing_state_resolution.json"
    results.append(expect_rc("state_missing_data_request_smoke", run([
        sys.executable,
        "scripts/validate_factorforge_state_dependency.py",
        "--dependency-contract", str(missing_contract),
        "--catalog", str(catalog_path),
        "--report-id", report_id,
        "--factor-id", factor_id,
        "--research-id", research_id,
        "--output-state-resolution", str(missing_resolution),
        "--output-data-request-dir", str(request_dir),
    ]), 1, BLOCK_DATA_REQUEST_REQUIRED))
    if not list(request_dir.glob("data_request__*.json")):
        raise AssertionError("missing datamart did not write data_request_v1")

    try:
        assert_no_raw_minute_full_window_scan(
            input_paths=["s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/"],
            production=True,
        )
    except Exception as exc:
        if BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN not in str(exc):
            raise
        results.append({"name": "raw_minute_forbidden_smoke", "rc": 1, "token": BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN, "status": "PASS"})
    else:
        raise AssertionError("raw minute production path was not blocked")

    portfolio_plan = {
        "contract_version": REVISION_DATA_PLAN_VERSION,
        "reuse_existing_state": True,
        "new_state_required": False,
        "data_request_required": False,
        "portfolio_only_revision": True,
        "factor_value_recompute_required": False,
        "required_datasets": ["intraday_flow_state_v2"],
        "new_state_candidates": [],
        "raw_minute_full_window_allowed": False,
        "reason": "only rebalance policy changed",
    }
    if validate_revision_data_plan(portfolio_plan):
        raise AssertionError("portfolio-only revision data plan did not validate")
    if not portfolio_only_revision_allows_skip(portfolio_plan):
        raise AssertionError("portfolio-only revision did not allow factor recompute skip")
    results.append({"name": "portfolio_only_revision_smoke", "rc": 0, "token": None, "status": "PASS"})

    schema_catalog = base_catalog()
    schema_catalog["datasets"]["intraday_flow_state_v2"]["schema_version"] = "old_schema"
    schema_catalog_path = write_json(root / "schema_catalog.json", schema_catalog)
    results.append(expect_rc("schema_negative_smoke", run([
        sys.executable,
        "scripts/validate_factorforge_state_dependency.py",
        "--dependency-contract", str(contract_path),
        "--catalog", str(schema_catalog_path),
        "--report-id", report_id,
        "--output-state-resolution", str(root / "schema_resolution.json"),
        "--output-data-request-dir", str(request_dir),
    ]), 1, BLOCK_STATE_SCHEMA_VERSION_MISMATCH))

    coverage_catalog = base_catalog()
    coverage_catalog["datasets"]["intraday_flow_state_v2"]["coverage"] = {"start": "20200101", "end": "20210101"}
    coverage_catalog_path = write_json(root / "coverage_catalog.json", coverage_catalog)
    results.append(expect_rc("coverage_negative_smoke", run([
        sys.executable,
        "scripts/validate_factorforge_state_dependency.py",
        "--dependency-contract", str(contract_path),
        "--catalog", str(coverage_catalog_path),
        "--report-id", report_id,
        "--output-state-resolution", str(root / "coverage_resolution.json"),
        "--output-data-request-dir", str(request_dir),
    ]), 1, BLOCK_STATE_COVERAGE_INSUFFICIENT))

    undeclared_contract = write_json(root / "undeclared_contract.json", {"state_dependency_contract": {}})
    results.append(expect_rc("undeclared_contract_smoke", run([
        sys.executable,
        "scripts/validate_factorforge_state_dependency.py",
        "--dependency-contract", str(undeclared_contract),
        "--catalog", str(catalog_path),
        "--report-id", report_id,
        "--output-state-resolution", str(root / "undeclared_resolution.json"),
        "--output-data-request-dir", str(request_dir),
    ]), 1, BLOCK_STATE_DEPENDENCY_UNDECLARED))

    ultimate_root = root / "ultimate_factorforge"
    ultimate_resolution = root / "ultimate_state_resolution.json"
    results.append(expect_rc("ultimate_state_reuse_gate_passes", run([
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id", report_id,
        "--start-step", "4",
        "--end-step", "4",
        "--factorforge-root", str(ultimate_root),
        "--allow-legacy-global-runtime",
        "--dry-run",
        "--require-state-reuse-contract",
        "--state-dependency-contract", str(contract_path),
        "--state-catalog", str(catalog_path),
        "--state-resolution", str(ultimate_resolution),
        "--state-data-request-dir", str(request_dir),
        "--council-mode", "off",
    ]), 0))

    results.append(expect_rc("ultimate_missing_state_contract_blocks", run([
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id", report_id,
        "--start-step", "4",
        "--end-step", "4",
        "--factorforge-root", str(ultimate_root),
        "--allow-legacy-global-runtime",
        "--dry-run",
        "--require-state-reuse-contract",
        "--council-mode", "off",
    ]), 1, BLOCK_STATE_DEPENDENCY_UNDECLARED))

    results.append(expect_rc("ultimate_raw_minute_path_blocks", run([
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id", report_id,
        "--start-step", "4",
        "--end-step", "4",
        "--factorforge-root", str(ultimate_root),
        "--allow-legacy-global-runtime",
        "--dry-run",
        "--require-state-reuse-contract",
        "--state-dependency-contract", str(contract_path),
        "--state-catalog", str(catalog_path),
        "--state-resolution", str(root / "ultimate_raw_state_resolution.json"),
        "--state-data-request-dir", str(request_dir),
        "--state-input-path", "s3://yufan-data-lake/tushares/分钟数据/raw/stk_mins_1min/",
        "--council-mode", "off",
    ]), 1, BLOCK_RAW_MINUTE_FULL_WINDOW_FORBIDDEN))

    summary = {
        "verdict": "ACCEPT",
        "production_research_started": False,
        "worker_started": False,
        "full_window_step4_started": False,
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print("FACTORFORGE_STATE_REUSE_CONTRACT_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
