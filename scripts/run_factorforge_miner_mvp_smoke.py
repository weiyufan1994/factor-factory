#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.capability_inventory import build_capability_inventory
from factor_factory.miner.candidates import build_candidate_packets
from factor_factory.miner.cheap_screen import run_cheap_screen
from factor_factory.miner.data_gap import build_data_gap_report
from factor_factory.miner.research_queue import build_research_queue
from factor_factory.miner.template_registry import load_template_registry


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_under(path: Path, root: Path, label: str) -> None:
    resolved = path.resolve(strict=False)
    workspace = root.resolve(strict=False)
    if resolved != workspace and workspace not in resolved.parents:
        raise AssertionError(f"{label} outside workspace: {resolved} workspace={workspace}")


def write_fixture_panel(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("20250102", "AAA", 1.0, 1.0, 10.0),
        ("20250102", "BBB", 2.0, 0.5, 20.0),
        ("20250102", "CCC", 3.0, -0.5, 30.0),
        ("20250102", "DDD", 4.0, -1.0, 40.0),
        ("20250103", "AAA", 1.2, 1.1, 11.0),
        ("20250103", "BBB", 2.2, 0.4, 22.0),
        ("20250103", "CCC", 3.2, -0.4, 32.0),
        ("20250103", "DDD", 4.2, -1.1, 42.0),
        ("20250104", "AAA", 1.4, 1.2, 12.0),
        ("20250104", "BBB", 2.4, 0.3, 24.0),
        ("20250104", "CCC", 3.4, -0.3, 34.0),
        ("20250104", "DDD", 4.4, -1.2, 44.0),
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["trade_date", "ts_code", "factor_ready_signal", "forward_return", "turnover"])
        writer.writerows(rows)


def main() -> int:
    root = Path("/tmp/factorforge_miner_mvp_smoke")
    if not str(root).startswith("/tmp/"):
        raise SystemExit("refusing non-/tmp smoke root")
    shutil.rmtree(root, ignore_errors=True)
    workspace = root / "factor_research" / "miner" / "smoke_campaign"
    workspace.mkdir(parents=True)

    catalog = root / "mock_catalog.json"
    write_json(
        catalog,
        {
            "datasets": [
                {
                    "dataset_id": "minute_bar",
                    "columns": ["ts_code", "trade_date", "trade_time", "open", "high", "low", "close", "vol", "amount"],
                    "metadata": {
                        "coverage": {"start": "20250102", "end": "20250104"},
                        "qa_verdict": "ACCEPT",
                        "no_future_intraday_minutes": "true",
                    },
                    "uri": str(root / "minute_bar"),
                },
                {
                    "dataset_id": "daily_basic",
                    "columns": ["ts_code", "trade_date", "turnover", "total_mv"],
                    "metadata": {"coverage": {"start": "20250102", "end": "20250104"}, "qa_verdict": "ACCEPT"},
                    "uri": str(root / "daily_basic"),
                },
                {
                    "dataset_id": "cheap_screen_panel",
                    "columns": ["trade_date", "ts_code", "factor_ready_signal", "forward_return", "turnover"],
                    "metadata": {"coverage": {"start": "20250102", "end": "20250104"}, "qa_verdict": "ACCEPT"},
                    "uri": str(root / "cheap_screen_panel.csv"),
                },
            ]
        },
    )
    panel_path = root / "cheap_screen_panel.csv"
    write_fixture_panel(panel_path)

    templates = load_template_registry()
    if len(templates) < 10:
        raise AssertionError(f"expected at least 10 templates, got {len(templates)}")

    inventory = build_capability_inventory(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        catalog_paths=[catalog],
    )
    inventory_path = workspace / "objects" / "miner_capability_inventory.json"
    inventory_doc = workspace / "docs" / "miner_capability_inventory.md"
    if not inventory_path.exists() or not inventory_doc.exists():
        raise AssertionError("capability inventory outputs missing")
    skew_template = next(row for row in inventory["template_support"] if row["template_id"] == "intraday_return_skew")
    if skew_template["support_status"] == "ready":
        raise AssertionError(f"intraday_return_skew should not be ready when skew operator module is unavailable: {skew_template}")
    ready_template_support = next(row for row in inventory["template_support"] if row["template_id"] == "turnover_acceleration")
    if ready_template_support["support_status"] != "ready":
        raise AssertionError(f"turnover_acceleration should be ready in smoke fixture: {ready_template_support}")
    missing_template = next(row for row in inventory["template_support"] if row["template_id"] == "cutoff_flow_persistence")
    if missing_template["support_status"] != "needs_data":
        raise AssertionError(f"expected cutoff_flow_persistence needs_data, got {missing_template}")
    bad_catalog = root / "bad_catalog.json"
    write_json(
        bad_catalog,
        {
            "datasets": [
                {
                    "dataset_id": "minute_bar",
                    "columns": ["ts_code", "trade_date", "close"],
                    "metadata": {"qa_verdict": "BLOCK"},
                    "uri": str(root / "bad_minute_bar"),
                }
            ]
        },
    )
    bad_workspace = root / "factor_research" / "miner" / "bad_campaign"
    bad_inventory = build_capability_inventory(
        campaign_id="bad_campaign",
        workspace_root=bad_workspace,
        catalog_paths=[bad_catalog],
    )
    bad_open_gap = next(row for row in bad_inventory["template_support"] if row["template_id"] == "intraday_return_skew")
    if bad_open_gap["support_status"] == "ready":
        raise AssertionError(f"QA/coverage/lookahead failure incorrectly marked ready: {bad_open_gap}")
    try:
        build_capability_inventory(
            campaign_id="bad_workspace",
            workspace_root=root / "not_a_miner_workspace",
            catalog_paths=[catalog],
        )
    except ValueError as exc:
        if "BLOCK_FACTORFORGE_MINER_WORKSPACE_MISSING" not in str(exc):
            raise
    else:
        raise AssertionError("non-miner workspace was accepted")
    try:
        build_capability_inventory(
            campaign_id="expected_campaign",
            workspace_root=root / "factor_research" / "miner" / "wrong_campaign",
            catalog_paths=[catalog],
        )
    except ValueError as exc:
        if "campaign_id mismatch" not in str(exc):
            raise
    else:
        raise AssertionError("wrong campaign workspace was accepted")
    try:
        build_capability_inventory(
            campaign_id="expected_campaign",
            workspace_root=root / "factor_research" / "miner" / "expected_campaign" / "nested_output_root",
            catalog_paths=[catalog],
        )
    except ValueError as exc:
        if "must end at factor_research/miner" not in str(exc):
            raise
    else:
        raise AssertionError("nested miner workspace was accepted")

    candidates = build_candidate_packets(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        template_ids=["turnover_acceleration", "cutoff_flow_persistence"],
        inventory=inventory,
    )
    candidate_manifest = read_json(workspace / "objects" / "candidates" / "candidate_manifest.json")
    if len(candidate_manifest["candidates"]) != 2:
        raise AssertionError("candidate manifest did not include both requested candidates")
    ready_candidate = next(row for row in candidates if row["template_id"] == "turnover_acceleration")
    blocked_candidate = next(row for row in candidates if row["template_id"] == "cutoff_flow_persistence")
    if ready_candidate["promotion_forbidden_until_formal"] is not True:
        raise AssertionError("ready candidate did not forbid formal promotion")
    if not ready_candidate.get("template_lineage"):
        raise AssertionError("ready candidate missing template lineage")
    if blocked_candidate["cheap_screen_status"] != "needs_data":
        raise AssertionError(f"missing-data candidate not marked needs_data: {blocked_candidate}")

    gap = build_data_gap_report(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidates=candidates,
        inventory=inventory,
    )
    if not gap["gaps"]:
        raise AssertionError("data gap report did not record missing dependency")
    if not gap["data_request_ids"]:
        raise AssertionError("missing reusable state did not create data_request_v1")
    if not (workspace / "docs" / "data_gap_report.md").exists():
        raise AssertionError("data gap markdown missing")
    for request_id in gap["data_request_ids"]:
        request_path = workspace / "objects" / "data_requests" / f"{request_id}.json"
        if not request_path.exists():
            raise AssertionError(f"data request missing: {request_path}")

    summary = run_cheap_screen(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidate_manifest_path=workspace / "objects" / "candidates" / "candidate_manifest.json",
        panel_path=panel_path,
        screen_window="20250102..20250104",
        universe="smoke_universe",
    )
    if summary["evidence_role"] != "exploratory_evidence":
        raise AssertionError("cheap screen evidence role is not exploratory")
    if summary["promotion_forbidden_until_formal"] is not True:
        raise AssertionError("cheap screen did not forbid formal promotion")
    result_rows = summary["results"]
    ready_result = next(row for row in result_rows if row["candidate_id"] == ready_candidate["candidate_id"])
    if ready_result["rank_ic_mean"] is None or ready_result["group_spread_gross"] is None:
        raise AssertionError(f"cheap screen missing metrics: {ready_result}")
    if ready_result["monotonicity_score"] is None:
        raise AssertionError("cheap screen missing monotonicity")
    blocked_result = next(row for row in result_rows if row["candidate_id"] == blocked_candidate["candidate_id"])
    if blocked_result["decision"] != "needs_data":
        raise AssertionError(f"blocked candidate should remain needs_data: {blocked_result}")

    queue = build_research_queue(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        cheap_screen_summary=summary,
    )
    if not queue["items"]:
        raise AssertionError("research queue should include at least one formal candidate")
    if any(item["candidate_id"] == blocked_candidate["candidate_id"] for item in queue["items"]):
        raise AssertionError("needs_data candidate entered research queue")
    if not (workspace / "objects" / "research_queue" / "research_queue.jsonl").exists():
        raise AssertionError("research queue jsonl missing")

    expected_paths = [
        inventory_path,
        inventory_doc,
        workspace / "objects" / "candidates" / "candidate_manifest.json",
        workspace / "objects" / "cheap_screen" / "cheap_screen_summary.json",
        workspace / "objects" / "cheap_screen" / "cheap_screen_results.parquet",
        workspace / "objects" / "research_queue" / "research_queue.jsonl",
        workspace / "objects" / "data_gap_report.json",
        workspace / "docs" / "data_gap_report.md",
    ]
    expected_paths.extend(workspace / "objects" / "data_requests" / f"{request_id}.json" for request_id in gap["data_request_ids"])
    for path in expected_paths:
        if not path.exists():
            raise AssertionError(f"expected output missing: {path}")
        assert_under(path, workspace, str(path))

    ultimate_diff = subprocess.run(
        ["git", "diff", "--quiet", "--", "skills/factor-forge-ultimate/SKILL.md", "scripts/run_factorforge_ultimate.py"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    if ultimate_diff.returncode != 0:
        raise AssertionError(f"Ultimate paths have a git diff:\n{ultimate_diff.stdout}\n{ultimate_diff.stderr}")
    clean_data_root = REPO_ROOT / "data" / "clean"
    for path in expected_paths:
        resolved = path.resolve(strict=False)
        if clean_data_root == resolved or clean_data_root in resolved.parents:
            raise AssertionError(f"smoke wrote under clean data: {resolved}")

    print(json.dumps({
        "verdict": "ACCEPT",
        "workspace_root": str(workspace),
        "candidate_count": len(candidates),
        "queue_count": len(queue["items"]),
        "production_research_started": False,
        "worker_started": False,
        "formal_step3b_step4_step6_started": False,
        "clean_data_mutated": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    print("FACTORFORGE_MINER_MVP_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
