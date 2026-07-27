#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.miner.capability_inventory import build_capability_inventory
from factor_factory.miner.candidates import build_candidate_packets
from factor_factory.miner.cheap_screen import (
    _adjust_p_values,
    _endpoint_metrics,
    _signal_rank_turnover,
    run_cheap_screen,
    validate_search_control,
)
from factor_factory.miner.data_gap import build_data_gap_report
from factor_factory.miner.data_split import write_data_split_manifest
from factor_factory.miner.evolution import build_evolution_round
from factor_factory.miner.program_executor import execute_candidate_programs
from factor_factory.miner.research_queue import build_research_queue
from factor_factory.miner.template_registry import load_template_registry
from factor_factory.research_evidence import sha256_file


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


def write_fixture_panel(
    path: Path,
    factor_col: str = "factor_ready_signal",
    *,
    month: str = "202501",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for date_index in range(12):
        trade_date = f"{month}{date_index + 2:02d}"
        for asset_index, code in enumerate(("AAA", "BBB", "CCC", "DDD")):
            centered = float(asset_index - 1.5)
            rows.append(
                (
                    trade_date,
                    code,
                    float(asset_index + 1),
                    centered + 0.03 * ((date_index + asset_index) % 3 - 1),
                    float((asset_index + 1) * (10 + 2 * date_index)),
                    100.0,
                    100.0 + centered,
                    1000.0,
                )
            )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["trade_date", "ts_code", factor_col, "forward_return", "turnover", "open", "close", "vol"])
        writer.writerows(rows)


def write_negative_fixture_panel(
    path: Path,
    factor_col: str = "factor_ready_signal",
    *,
    month: str = "202501",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for date_index in range(12):
        trade_date = f"{month}{date_index + 2:02d}"
        for asset_index, code in enumerate(("AAA", "BBB", "CCC", "DDD")):
            centered = float(asset_index - 1.5)
            rows.append(
                (
                    trade_date,
                    code,
                    float(asset_index + 1),
                    -centered,
                    float((asset_index + 1) * (10 + 2 * date_index)),
                )
            )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["trade_date", "ts_code", factor_col, "forward_return", "turnover"])
        writer.writerows(rows)


def search_control(
    *,
    campaign_id: str,
    workspace_root: Path,
    data_split_manifest_path: Path,
    panel_path: Path,
    tested_program_hashes: list[str],
    generation: int = 0,
    previous_search_control_path: Path | None = None,
    trial_budget: int = 40,
    selection_window_id: str = "20250102..20250113",
    universe_id: str = "smoke_universe",
) -> dict:
    payload = {
        "version": "factorforge_miner_search_control_v1",
        "campaign_id": campaign_id,
        "generation": generation,
        "selection_window_role": "IS_SEARCH",
        "selection_window_id": selection_window_id,
        "universe_id": universe_id,
        "oos_sealed": True,
        "sealed_oos_token_hash": sha256_file(
            data_split_manifest_path
        ),
        "data_snapshot_hash": sha256_file(panel_path),
        "data_split_manifest_ref": str(
            data_split_manifest_path.resolve(strict=False).relative_to(
                workspace_root.resolve(strict=False)
            )
        ),
        "data_split_manifest_sha256": sha256_file(
            data_split_manifest_path
        ),
        "purge_days": 5,
        "embargo_days": 5,
        "trial_budget": trial_budget,
        "trials_used": len(tested_program_hashes),
        "tested_program_hashes": tested_program_hashes,
        "multiple_testing_policy": "BH_FDR",
        "multiplicity_alpha": 0.1,
        "cost_model_id": "a_share_cost_v1",
        "capacity_model_id": "adv_participation_v1",
        "regime_plan_id": "bull_bear_volatility_liquidity_v1",
        "screening_policy": {
            "version": "factorforge_miner_cheap_screen_policy_v1",
            "return_unit": "decimal",
            "send_min_rank_ic": 0.05,
            "send_min_group_spread": 0.5,
            "send_min_long_end": 0.0,
            "keep_min_abs_rank_ic": 0.02,
            "keep_min_abs_group_spread": 0.2,
        },
    }
    if generation == 0:
        payload["previous_search_control_ref"] = None
        payload["previous_search_control_sha256"] = None
    else:
        if previous_search_control_path is None:
            raise ValueError(
                "generation > 0 requires workspace and previous control"
            )
        payload["previous_search_control_ref"] = str(
            previous_search_control_path.resolve(strict=False).relative_to(
                workspace_root.resolve(strict=False)
            )
        )
        payload["previous_search_control_sha256"] = sha256_file(
            previous_search_control_path
        )
    return payload


def main() -> int:
    root = Path("/tmp/factorforge_miner_mvp_smoke")
    if not str(root).startswith("/tmp/"):
        raise SystemExit("refusing non-/tmp smoke root")
    shutil.rmtree(root, ignore_errors=True)
    workspace = root / "factor_research" / "miner" / "smoke_campaign"
    workspace.mkdir(parents=True)

    bh = _adjust_p_values(
        {"a": 0.01, "b": 0.04, "c": 0.2},
        method="BH_FDR",
    )
    holm = _adjust_p_values(
        {"a": 0.01, "b": 0.04, "c": 0.2},
        method="holm_bonferroni",
    )
    if any(
        abs(bh[key] - expected) > 1e-12
        for key, expected in {"c": 0.2, "b": 0.06, "a": 0.03}.items()
    ):
        raise AssertionError(f"BH-FDR adjustment incorrect: {bh}")
    if any(
        abs(holm[key] - expected) > 1e-12
        for key, expected in {"a": 0.03, "b": 0.08, "c": 0.2}.items()
    ):
        raise AssertionError(f"Holm adjustment incorrect: {holm}")

    cross_section_fixture = [
        {
            "trade_date": trade_date,
            "ts_code": code,
            "factor": factor,
            "forward_return": forward_return + date_offset,
            "turnover": 1000.0 + factor,
        }
        for trade_date, date_offset, scale in (
            ("20250102", 0.0, 1.0),
            ("20250103", 100.0, 100.0),
        )
        for code, factor, forward_return in (
            ("AAA", 1.0 * scale, -1.0),
            ("BBB", 2.0 * scale, -0.5),
            ("CCC", 3.0 * scale, 0.5),
            ("DDD", 4.0 * scale, 1.0),
        )
    ]
    high, low, spread, monotonicity = _endpoint_metrics(
        cross_section_fixture,
        "factor",
    )
    if (high, low, spread, monotonicity) != (51.0, 49.0, 2.0, 1.0):
        raise AssertionError(
            "endpoint metrics were not computed within each date before "
            f"time aggregation: {(high, low, spread, monotonicity)}"
        )
    if _signal_rank_turnover(cross_section_fixture, "factor") != 0.0:
        raise AssertionError(
            "stable factor ranks should have zero signal turnover regardless "
            "of the source stock-turnover column"
        )
    tied_endpoint_fixture = [
        {
            "trade_date": "20250102",
            "ts_code": code,
            "factor": 1.0,
            "forward_return": float(index),
        }
        for index, code in enumerate(("AAA", "BBB", "CCC", "DDD"))
    ]
    if _endpoint_metrics(tied_endpoint_fixture, "factor") != (
        None,
        None,
        None,
        None,
    ):
        raise AssertionError(
            "cheap-screen endpoints split equal factor values by row order"
        )

    catalog = root / "mock_catalog.json"
    panel_path = (
        workspace / "objects" / "inputs" / "cheap_screen_panel.csv"
    )
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
                    "uri": str(panel_path),
                },
            ]
        },
    )
    write_fixture_panel(panel_path)
    oos_panel_path = (
        workspace / "objects" / "inputs" / "sealed_oos_panel.csv"
    )
    write_fixture_panel(oos_panel_path, month="202502")
    data_split_manifest_path, _ = write_data_split_manifest(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        is_panel_path=panel_path,
        is_window_id="20250102..20250113",
        universe_id="smoke_universe",
        oos_windows=[
            {
                "panel_path": oos_panel_path,
                "window_id": "20250202..20250213",
                "release_state": "SEALED_UNRELEASED",
            }
        ],
    )

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
        data_split_manifest_path=data_split_manifest_path,
        template_ids=[
            "turnover_acceleration",
            "up_down_volume_imbalance_proxy",
            "cutoff_flow_persistence",
        ],
        inventory=inventory,
    )
    candidate_manifest = read_json(workspace / "objects" / "candidates" / "candidate_manifest.json")
    if len(candidate_manifest["candidates"]) != 3:
        raise AssertionError("candidate manifest did not include all requested candidates")
    ready_candidate = next(row for row in candidates if row["template_id"] == "turnover_acceleration")
    blocked_candidate = next(row for row in candidates if row["template_id"] == "cutoff_flow_persistence")
    if ready_candidate["promotion_forbidden_until_formal"] is not True:
        raise AssertionError("ready candidate did not forbid formal promotion")
    if not ready_candidate.get("template_lineage"):
        raise AssertionError("ready candidate missing template lineage")
    if blocked_candidate["cheap_screen_status"] != "needs_data":
        raise AssertionError(f"missing-data candidate not marked needs_data: {blocked_candidate}")
    execution = execute_candidate_programs(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidate_manifest=candidate_manifest,
        source_panel_path=panel_path,
        data_split_manifest_path=data_split_manifest_path,
        artifact_tag="g00",
    )
    if len(execution["executed_program_hashes"]) != 2:
        raise AssertionError(f"expected two executed candidate programs: {execution}")
    if len(set(execution["executed_program_hashes"])) != 2:
        raise AssertionError("candidate programs did not have distinct hashes")
    outside_source = root / "outside_miner_source_panel.csv"
    shutil.copy2(panel_path, outside_source)
    try:
        execute_candidate_programs(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest=candidate_manifest,
            source_panel_path=outside_source,
            data_split_manifest_path=data_split_manifest_path,
            artifact_tag="outside_source",
        )
    except ValueError as exc:
        if "PROGRAM_INPUT_INVALID:source_outside_workspace" not in str(exc):
            raise
    else:
        raise AssertionError(
            "program executor accepted an outside-workspace source panel"
        )
    try:
        execute_candidate_programs(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest=candidate_manifest,
            source_panel_path=oos_panel_path,
            data_split_manifest_path=data_split_manifest_path,
            artifact_tag="oos_relabel_attack",
        )
    except ValueError as exc:
        if "is_panel_hash_mismatch" not in str(exc):
            raise
    else:
        raise AssertionError(
            "program executor accepted a registered OOS panel as IS"
        )
    oos_relabel_control = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=oos_panel_path,
        tested_program_hashes=execution["executed_program_hashes"],
    )
    oos_relabel_reasons = validate_search_control(
        oos_relabel_control,
        required_trial_count=len(execution["executed_program_hashes"]),
        required_program_hashes=set(execution["executed_program_hashes"]),
        workspace_root=workspace,
        expected_generation=0,
        expected_campaign_id="smoke_campaign",
        expected_data_snapshot_hash=sha256_file(oos_panel_path),
        expected_is_source_hash=sha256_file(oos_panel_path),
        expected_selection_window_id="20250102..20250113",
        expected_universe_id="smoke_universe",
    )
    if not any("is_panel_hash_mismatch" in reason for reason in oos_relabel_reasons):
        raise AssertionError(
            "search control accepted a registered OOS panel relabeled as IS"
        )
    executed_panel = Path(execution["output_panel_path"])
    execution_report_path = (
        workspace
        / "objects"
        / "program_execution"
        / "g00"
        / "program_execution_report.json"
    )

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

    control_g00 = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=executed_panel,
        tested_program_hashes=execution["executed_program_hashes"],
    )
    control_g00_path = (
        workspace
        / "objects"
        / "search_control"
        / "search_control__g00.json"
    )
    write_json(control_g00_path, control_g00)
    summary = run_cheap_screen(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidate_manifest_path=workspace / "objects" / "candidates" / "candidate_manifest.json",
        panel_path=executed_panel,
        program_execution_report_path=execution_report_path,
        screen_window="20250102..20250113",
        universe="smoke_universe",
        search_control=control_g00,
    )
    if summary["evidence_role"] != "exploratory_evidence":
        raise AssertionError("cheap screen evidence role is not exploratory")
    if summary["promotion_forbidden_until_formal"] is not True:
        raise AssertionError("cheap screen did not forbid formal promotion")
    result_rows = summary["results"]
    ready_result = next(row for row in result_rows if row["candidate_id"] == ready_candidate["candidate_id"])
    if ready_result["rank_ic_mean"] is None or ready_result["group_spread_gross"] is None:
        raise AssertionError(f"cheap screen missing metrics: {ready_result}")
    if ready_result["rank_ic_mean"] <= 0 or ready_result["group_spread_gross"] <= 0:
        raise AssertionError(f"ready candidate should be long-side positive in smoke: {ready_result}")
    if ready_result["decision"] != "send_to_formal_research":
        raise AssertionError(f"positive ready candidate should enter research queue: {ready_result}")
    if (
        ready_result.get("multiplicity_pass") is not True
        or ready_result.get("adjusted_p_value") is None
        or ready_result["adjusted_p_value"] > 0.1
    ):
        raise AssertionError(
            f"positive candidate did not pass computed multiplicity: {ready_result}"
        )
    if (
        summary.get("program_execution_report_sha256")
        != sha256_file(execution_report_path)
        or summary.get("program_execution_output_sha256")
        != summary.get("source_panel_sha256")
    ):
        raise AssertionError("cheap screen did not bind executor report lineage")
    if ready_result["monotonicity_score"] is None:
        raise AssertionError("cheap screen missing monotonicity")
    if (
        ready_result["turnover_definition"]
        != "mean_one_way_cross_sectional_percentile_rank_migration"
    ):
        raise AssertionError(
            f"cheap screen used the wrong turnover definition: {ready_result}"
        )
    if (
        ready_result["endpoint_aggregation"]
        != "equal_weighted_daily_cross_sections"
    ):
        raise AssertionError(
            f"cheap screen did not declare its endpoint aggregation: {ready_result}"
        )
    blocked_result = next(row for row in result_rows if row["candidate_id"] == blocked_candidate["candidate_id"])
    if blocked_result["decision"] != "needs_data":
        raise AssertionError(f"blocked candidate should remain needs_data: {blocked_result}")
    rewritten_control = deepcopy(control_g00)
    rewritten_control["screening_policy"]["send_min_rank_ic"] = 0.06
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=(
                workspace
                / "objects"
                / "candidates"
                / "candidate_manifest.json"
            ),
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=rewritten_control,
        )
    except ValueError as exc:
        if "canonical_control_immutable" not in str(exc):
            raise
    else:
        raise AssertionError(
            "Miner accepted different thresholds for an existing generation"
        )

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
    if any(item.get("multiplicity_policy") != "BH_FDR" for item in queue["items"]):
        raise AssertionError("research queue lost multiplicity provenance")
    for item in queue["items"]:
        if (
            not isinstance(item.get("mechanism_hypothesis"), dict)
            or not item["mechanism_hypothesis"].get("math_object")
            or not isinstance(item.get("data_requirements"), dict)
            or not isinstance(item.get("known_failure_modes"), dict)
            or not isinstance(item.get("trial_lineage"), dict)
            or not item["trial_lineage"].get("data_split_manifest_ref")
            or not item["trial_lineage"].get("data_split_manifest_sha256")
            or not isinstance(item.get("factor_workspace_plan"), dict)
            or item["factor_workspace_plan"].get(
                "creation_required_before_ultimate"
            )
            is not True
        ):
            raise AssertionError(
                f"research queue item missing formal handoff context: {item}"
            )
    bad_queue_summary = deepcopy(summary)
    bad_queue_summary["promotion_forbidden_until_formal"] = False
    try:
        build_research_queue(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            cheap_screen_summary=bad_queue_summary,
        )
    except ValueError as exc:
        if "CHEAP_SCREEN_REPLAY_INVALID:evidence_boundary" not in str(exc):
            raise
    else:
        raise AssertionError(
            "research queue accepted evidence without the exploratory boundary"
        )
    bad_queue_summary = deepcopy(summary)
    bad_queue_summary["multiplicity"]["family_size"] += 1
    try:
        build_research_queue(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            cheap_screen_summary=bad_queue_summary,
        )
    except ValueError as exc:
        if "CHEAP_SCREEN_REPLAY_INVALID:multiplicity" not in str(exc):
            raise
    else:
        raise AssertionError("research queue accepted forged multiplicity")
    bad_queue_summary = deepcopy(summary)
    forged_ready = next(
        row
        for row in bad_queue_summary["results"]
        if row["candidate_id"] == ready_candidate["candidate_id"]
    )
    forged_ready["rank_ic_mean"] = 0.999999
    forged_ready["adjusted_p_value"] = 0.0
    forged_ready["multiplicity_pass"] = True
    forged_ready["eligible_for_research_queue"] = True
    forged_ready["decision"] = "send_to_formal_research"
    try:
        build_research_queue(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            cheap_screen_summary=bad_queue_summary,
        )
    except ValueError as exc:
        if "CHEAP_SCREEN_REPLAY_INVALID:results" not in str(exc):
            raise
    else:
        raise AssertionError(
            "research queue accepted hand-authored cheap-screen results"
        )
    evolution = build_evolution_round(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidate_manifest=read_json(
            workspace / "objects" / "candidates" / "candidate_manifest.json"
        ),
        cheap_screen_summary=summary,
        generation=0,
        elite_limit=2,
    )
    if not evolution["elites"] or not evolution["mutation_briefs"]:
        raise AssertionError(f"evolution round missing elites or mutations: {evolution}")
    if evolution["oos_sealed"] is not True:
        raise AssertionError("evolution round did not seal OOS")
    mutation_manifest_path = (
        workspace
        / "objects"
        / "evolution"
        / "g01"
        / "mutation_candidate_manifest.json"
    )
    mutation_manifest = read_json(mutation_manifest_path)
    mutation_execution = execute_candidate_programs(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidate_manifest=mutation_manifest,
        source_panel_path=panel_path,
        data_split_manifest_path=data_split_manifest_path,
        artifact_tag="g01",
    )
    mutation_count = mutation_manifest["candidate_count"]
    if len(mutation_execution["executed_program_hashes"]) != mutation_count:
        raise AssertionError(
            f"mutation programs were not all executed: {mutation_execution}"
        )
    if len(set(mutation_execution["executed_program_hashes"])) != mutation_count:
        raise AssertionError("mutation program hashes are not distinct")
    control_g01 = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=Path(mutation_execution["output_panel_path"]),
        tested_program_hashes=[
            *execution["executed_program_hashes"],
            *mutation_execution["executed_program_hashes"],
        ],
        generation=1,
        previous_search_control_path=control_g00_path,
    )
    control_g01_path = (
        workspace
        / "objects"
        / "search_control"
        / "search_control__g01.json"
    )
    write_json(control_g01_path, control_g01)
    mutation_summary = run_cheap_screen(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        candidate_manifest_path=mutation_manifest_path,
        panel_path=Path(mutation_execution["output_panel_path"]),
        program_execution_report_path=(
            workspace
            / "objects"
            / "program_execution"
            / "g01"
            / "program_execution_report.json"
        ),
        screen_window="20250102..20250113",
        universe="smoke_universe",
        search_control=control_g01,
    )
    if any(
        row.get("signal_source") != "candidate_specific"
        for row in mutation_summary["results"]
    ):
        raise AssertionError("mutation population reused a shared signal")
    shrunken_family_control = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=Path(mutation_execution["output_panel_path"]),
        tested_program_hashes=[
            execution["executed_program_hashes"][0],
            *mutation_execution["executed_program_hashes"],
        ],
        generation=1,
        previous_search_control_path=control_g00_path,
    )
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=mutation_manifest_path,
            panel_path=Path(mutation_execution["output_panel_path"]),
            program_execution_report_path=(
                workspace
                / "objects"
                / "program_execution"
                / "g01"
                / "program_execution_report.json"
            ),
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=shrunken_family_control,
        )
    except ValueError as exc:
        if "history_not_append_only" not in str(exc):
            raise
    else:
        raise AssertionError(
            "later Miner generation shrank the cumulative trial family"
        )

    negative_workspace = root / "factor_research" / "miner" / "negative_campaign"
    negative_inventory = build_capability_inventory(
        campaign_id="negative_campaign",
        workspace_root=negative_workspace,
        catalog_paths=[catalog],
    )
    negative_panel = (
        negative_workspace
        / "objects"
        / "inputs"
        / "negative_cheap_screen_panel.csv"
    )
    write_negative_fixture_panel(negative_panel)
    negative_oos_panel = (
        negative_workspace
        / "objects"
        / "inputs"
        / "sealed_oos_panel.csv"
    )
    write_negative_fixture_panel(
        negative_oos_panel,
        month="202502",
    )
    negative_split_path, _ = write_data_split_manifest(
        campaign_id="negative_campaign",
        workspace_root=negative_workspace,
        is_panel_path=negative_panel,
        is_window_id="20250102..20250113",
        universe_id="smoke_universe",
        oos_windows=[
            {
                "panel_path": negative_oos_panel,
                "window_id": "20250202..20250213",
                "release_state": "SEALED_UNRELEASED",
            }
        ],
    )
    negative_candidates = build_candidate_packets(
        campaign_id="negative_campaign",
        workspace_root=negative_workspace,
        data_split_manifest_path=negative_split_path,
        template_ids=["turnover_acceleration"],
        inventory=negative_inventory,
    )
    negative_manifest = read_json(
        negative_workspace / "objects" / "candidates" / "candidate_manifest.json"
    )
    negative_execution = execute_candidate_programs(
        campaign_id="negative_campaign",
        workspace_root=negative_workspace,
        candidate_manifest=negative_manifest,
        source_panel_path=negative_panel,
        data_split_manifest_path=negative_split_path,
        artifact_tag="g00",
    )
    negative_summary = run_cheap_screen(
        campaign_id="negative_campaign",
        workspace_root=negative_workspace,
        candidate_manifest_path=negative_workspace / "objects" / "candidates" / "candidate_manifest.json",
        panel_path=Path(negative_execution["output_panel_path"]),
        program_execution_report_path=(
            negative_workspace
            / "objects"
            / "program_execution"
            / "g00"
            / "program_execution_report.json"
        ),
        screen_window="20250102..20250113",
        universe="smoke_universe",
        search_control=search_control(
            campaign_id="negative_campaign",
            workspace_root=negative_workspace,
            data_split_manifest_path=negative_split_path,
            panel_path=Path(negative_execution["output_panel_path"]),
            tested_program_hashes=negative_execution["executed_program_hashes"],
        ),
    )
    negative_result = negative_summary["results"][0]
    if negative_result["rank_ic_mean"] >= 0 or negative_result["group_spread_gross"] >= 0:
        raise AssertionError(f"negative fixture should be short-side-only: {negative_result}")
    if negative_result["decision"] == "send_to_formal_research":
        raise AssertionError(f"short-side-only candidate must not enter formal queue: {negative_result}")
    negative_queue = build_research_queue(
        campaign_id="negative_campaign",
        workspace_root=negative_workspace,
        cheap_screen_summary=negative_summary,
    )
    if negative_queue["items"]:
        raise AssertionError(f"short-side-only candidate entered research queue: {negative_queue}")
    if len(negative_candidates) != 1:
        raise AssertionError("negative campaign did not produce exactly one candidate")

    bad_control = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=executed_panel,
        tested_program_hashes=execution["executed_program_hashes"],
    )
    bad_control["data_snapshot_hash"] = "b" * 64
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=workspace
            / "objects"
            / "candidates"
            / "candidate_manifest.json",
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=bad_control,
        )
    except ValueError as exc:
        if "data_snapshot_hash_mismatch" not in str(exc):
            raise
    else:
        raise AssertionError("changed screen panel hash was accepted")

    bad_control = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=executed_panel,
        tested_program_hashes=execution["executed_program_hashes"],
    )
    bad_control.pop("screening_policy")
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=workspace
            / "objects"
            / "candidates"
            / "candidate_manifest.json",
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=bad_control,
        )
    except ValueError as exc:
        if "screening_policy" not in str(exc):
            raise
    else:
        raise AssertionError("unregistered cheap-screen thresholds were accepted")

    unsupported_multiplicity = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=executed_panel,
        tested_program_hashes=execution["executed_program_hashes"],
    )
    unsupported_multiplicity["multiple_testing_policy"] = (
        "deflated_sharpe_plus_pbo"
    )
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=workspace
            / "objects"
            / "candidates"
            / "candidate_manifest.json",
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=unsupported_multiplicity,
        )
    except ValueError as exc:
        if "multiple_testing_policy" not in str(exc):
            raise
    else:
        raise AssertionError(
            "named-but-unimplemented multiplicity policy was accepted"
        )

    forged_panel = (
        workspace
        / "objects"
        / "program_execution"
        / "g00"
        / "forged_candidate_signal_panel.parquet"
    )
    forged_frame = pd.read_parquet(executed_panel)
    forged_factor_column = ready_candidate["cheap_screen_factor_column"]
    forged_index = forged_frame[forged_factor_column].dropna().index[0]
    forged_frame.loc[forged_index, forged_factor_column] += 100.0
    forged_frame.to_parquet(forged_panel, index=False)
    forged_execution_report = deepcopy(read_json(execution_report_path))
    forged_execution_report["output_panel_path"] = str(forged_panel)
    forged_execution_report["output_panel_sha256"] = sha256_file(forged_panel)
    forged_execution_report_path = (
        workspace
        / "objects"
        / "program_execution"
        / "g00"
        / "forged_program_execution_report.json"
    )
    write_json(forged_execution_report_path, forged_execution_report)
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=workspace
            / "objects"
            / "candidates"
            / "candidate_manifest.json",
            panel_path=forged_panel,
            program_execution_report_path=forged_execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=search_control(
                campaign_id="smoke_campaign",
                workspace_root=workspace,
                data_split_manifest_path=data_split_manifest_path,
                panel_path=forged_panel,
                tested_program_hashes=execution["executed_program_hashes"],
            ),
        )
    except ValueError as exc:
        if "PROGRAM_EXECUTION_LINEAGE_INVALID:factor_values" not in str(exc):
            raise
    else:
        raise AssertionError(
            "handcrafted signal panel entered cheap screen with a forged report"
        )

    outside_manifest = root / "outside_candidate_manifest.json"
    write_json(outside_manifest, candidate_manifest)
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=outside_manifest,
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=search_control(
                campaign_id="smoke_campaign",
                workspace_root=workspace,
                data_split_manifest_path=data_split_manifest_path,
                panel_path=executed_panel,
                tested_program_hashes=execution["executed_program_hashes"],
            ),
        )
    except ValueError as exc:
        if "candidate_manifest_outside_workspace" not in str(exc):
            raise
    else:
        raise AssertionError("outside-workspace candidate manifest was accepted")

    duplicate_manifest = deepcopy(candidate_manifest)
    duplicate_packet = deepcopy(
        next(
            packet
            for packet in duplicate_manifest["candidates"]
            if packet.get("dependency_status") == "ready"
        )
    )
    duplicate_packet["candidate_id"] += "__duplicate_program"
    duplicate_column = f"factor__{duplicate_packet['candidate_id']}"
    duplicate_packet["cheap_screen_factor_column"] = duplicate_column
    duplicate_packet["candidate_program_contract"][
        "expected_factor_column"
    ] = duplicate_column
    duplicate_manifest["candidates"].append(duplicate_packet)
    duplicate_manifest_path = (
        workspace / "objects" / "candidates" / "duplicate_program_manifest.json"
    )
    write_json(duplicate_manifest_path, duplicate_manifest)
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=duplicate_manifest_path,
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=search_control(
                campaign_id="smoke_campaign",
                workspace_root=workspace,
                data_split_manifest_path=data_split_manifest_path,
                panel_path=executed_panel,
                tested_program_hashes=execution["executed_program_hashes"],
            ),
        )
    except ValueError as exc:
        if "duplicate_program_hash" not in str(exc):
            raise
    else:
        raise AssertionError("duplicate executable program hash was accepted")

    bad_control = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=executed_panel,
        tested_program_hashes=execution["executed_program_hashes"][:1],
    )
    try:
        run_cheap_screen(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest_path=workspace
            / "objects"
            / "candidates"
            / "candidate_manifest.json",
            panel_path=executed_panel,
            program_execution_report_path=execution_report_path,
            screen_window="20250102..20250113",
            universe="smoke_universe",
            search_control=bad_control,
        )
    except ValueError as exc:
        if "current_programs_unrecorded" not in str(exc):
            raise
    else:
        raise AssertionError("unrecorded candidate program trial was accepted")

    exhausted_summary = deepcopy(summary)
    exhausted_summary["search_control"] = search_control(
        campaign_id="smoke_campaign",
        workspace_root=workspace,
        data_split_manifest_path=data_split_manifest_path,
        panel_path=executed_panel,
        tested_program_hashes=execution["executed_program_hashes"],
        trial_budget=len(execution["executed_program_hashes"]),
    )
    try:
        build_evolution_round(
            campaign_id="smoke_campaign",
            workspace_root=workspace,
            candidate_manifest=candidate_manifest,
            cheap_screen_summary=exhausted_summary,
            generation=0,
            elite_limit=2,
        )
    except ValueError as exc:
        if "CHEAP_SCREEN_REPLAY_INVALID:search_control_binding" not in str(
            exc
        ):
            raise
    else:
        raise AssertionError(
            "evolution accepted an edited embedded search control"
        )

    expected_paths = [
        inventory_path,
        inventory_doc,
        workspace / "objects" / "candidates" / "candidate_manifest.json",
        workspace / "objects" / "cheap_screen" / "cheap_screen_summary.json",
        workspace / "objects" / "cheap_screen" / "cheap_screen_results.parquet",
        workspace / "objects" / "research_queue" / "research_queue.jsonl",
        workspace / "objects" / "evolution" / "evolution_round__g00.json",
        workspace / "objects" / "evolution" / "candidate_archive.json",
        workspace / "objects" / "evolution" / "g01" / "mutation_candidate_manifest.json",
        workspace / "objects" / "program_execution" / "g00" / "program_execution_report.json",
        workspace / "objects" / "program_execution" / "g01" / "program_execution_report.json",
        data_split_manifest_path,
        control_g00_path,
        control_g01_path,
        workspace / "objects" / "data_gap_report.json",
        workspace / "docs" / "data_gap_report.md",
    ]
    expected_paths.extend(workspace / "objects" / "data_requests" / f"{request_id}.json" for request_id in gap["data_request_ids"])
    for path in expected_paths:
        if not path.exists():
            raise AssertionError(f"expected output missing: {path}")
        assert_under(path, workspace, str(path))

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
