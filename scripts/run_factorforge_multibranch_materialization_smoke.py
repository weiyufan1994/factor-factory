#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.parser import parse_formula

REPORT_ID = "MULTIBRANCH_MATERIALIZATION_SMOKE"
CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
POLLUTION_MARKERS = ["MULTIBRANCH_MATERIALIZATION_SMOKE", "factorforge_multibranch_materialization"]


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def formula_hash(formula: str) -> str:
    parsed = parse_formula(formula)
    if parsed.get("parse_status") != "success":
        raise RuntimeError(f"formula parse failed: {formula}: {parsed.get('parse_errors')}")
    return str(parsed.get("formula_hash") or "")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if root.exists():
            files.update(str(item.relative_to(REPO_ROOT)) for item in root.rglob("*") if item.is_file())
    return files


def pollution_matches(new_files: set[str]) -> list[str]:
    return sorted(item for item in new_files if any(marker in item for marker in POLLUTION_MARKERS))


def council_dir(root: Path, report_id: str = REPORT_ID) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def synthesis_path(root: Path, report_id: str = REPORT_ID) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.json"


def markdown_path(root: Path, report_id: str = REPORT_ID) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.md"


def approval_path(root: Path, report_id: str = REPORT_ID) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis_approval__{report_id}.json"


def aggregate_path(root: Path, report_id: str = REPORT_ID) -> Path:
    return root / "objects" / "runtime_context" / f"multibranch_child_materialization__{report_id}__loop01.json"


def daily_dir(root: Path, report_id: str) -> Path:
    return root / "runs" / report_id / "step3a_local_inputs"


def run_cmd(root: Path, cmd: list[str], *, materialize: bool = False) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    if materialize:
        env["FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE"] = "1"
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {
        "command": cmd,
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-5000:],
        "stderr_tail": proc.stderr[-5000:],
    }


def approve(root: Path) -> dict[str, Any]:
    return run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/approve_main_agent_multibranch_synthesis.py",
            "--report-id",
            REPORT_ID,
            "--factorforge-root",
            str(root),
            "--loop-index",
            "1",
            "--approval-source",
            "smoke",
        ],
    )


def materialize(root: Path) -> dict[str, Any]:
    return run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/materialize_step6_multibranch_children.py",
            "--report-id",
            REPORT_ID,
            "--factorforge-root",
            str(root),
            "--loop-index",
            "1",
        ],
        materialize=True,
    )


def repair_lineage(root: Path, *, report_id: str = REPORT_ID, source_report_id: str = "MULTIBRANCH_MATERIALIZATION_ANCESTOR") -> dict[str, Any]:
    return run_cmd(
        root,
        [
            sys.executable,
            "scripts/repair_factorforge_report_lineage_artifacts.py",
            "--factorforge-root",
            str(root),
            "--report-id",
            report_id,
            "--source-report-id",
            source_report_id,
            "--artifact-kind",
            "alpha_idea_master",
            "--reason",
            "smoke_ancestor_alpha_idea_wrapper_repair",
        ],
    )


def write_daily_fixture(root: Path, report_id: str) -> dict[str, str]:
    path = daily_dir(root, report_id)
    path.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for date_idx in range(5):
        for code_idx, code in enumerate(["000001.SZ", "000002.SZ"]):
            rows.append(
                {
                    "trade_date": f"2020-01-0{date_idx + 1}",
                    "datetime": f"2020-01-0{date_idx + 1}",
                    "ts_code": code,
                    "code": code,
                    "open": 10.0 + date_idx + code_idx,
                    "close": 10.5 + date_idx + code_idx,
                    "volume": 1000 + date_idx * 10 + code_idx,
                    "pct_chg": 1.0 + date_idx * 0.1,
                }
            )
    df = pd.DataFrame(rows)
    parquet = path / f"daily_input__{report_id}.parquet"
    csv = path / f"daily_input__{report_id}.csv"
    meta = path / f"daily_input_meta__{report_id}.json"
    df.to_parquet(parquet, index=False)
    df.to_csv(csv, index=False)
    write_json(meta, {"report_id": report_id, "row_count": len(df), "created_at_utc": utc_now()})
    return {"parquet": str(parquet), "csv": str(csv), "meta": str(meta)}


def setup_parent(root: Path, report_id: str = REPORT_ID) -> None:
    for rel in ("objects/alpha_idea_master", "objects/factor_spec_master", "objects/data_prep_master", "objects/handoff", "objects/research_iteration_master"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    parent_formula = "rank(close)"
    daily = write_daily_fixture(root, report_id)
    write_json(
        root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json",
        {"report_id": report_id, "artifact_identity": {"report_id": report_id, "artifact_role": "alpha_idea_master"}},
    )
    formula_ir = parse_formula(parent_formula)
    write_json(
        root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        {
            "report_id": report_id,
            "artifact_identity": {"report_id": report_id, "artifact_role": "factor_spec_master"},
            "canonical_spec": {
                "formula_text": parent_formula,
                "formula_hash": formula_hash(parent_formula),
                "formula_ir": formula_ir,
                "operator_set": formula_ir.get("operator_set") or [],
                "required_fields": formula_ir.get("required_fields") or [],
            },
        },
    )
    write_json(
        root / "objects" / "data_prep_master" / f"data_prep_master__{report_id}.json",
        {
            "report_id": report_id,
            "artifact_identity": {"report_id": report_id, "artifact_role": "data_prep_master"},
            "local_input_paths": {
                "daily_df_parquet": daily["parquet"],
                "daily_df_csv": daily["csv"],
                "daily_input_meta_json": daily["meta"],
                "preferred_daily_format": "parquet",
                "audit_daily_format": "csv",
                "daily_io_contract": {"performance_path": "parquet", "audit_path": "csv", "csv_path": daily["csv"], "csv_sample_path": None},
            },
        },
    )
    handoff = {
        "report_id": report_id,
        "status": "approved_for_step3b_handoff",
        "loop_authorization": "approved_for_step3b_handoff",
        "new_branch_id": "multibranch_seed",
        "parent_identity": {"report_id": report_id, "run_id": f"{report_id}__run_001"},
        "parent_run_id": f"{report_id}__run_001",
    }
    write_json(root / "objects" / "handoff" / f"handoff_to_step3b__{report_id}.json", handoff)
    write_json(root / "objects" / "handoff" / f"handoff_to_step3__{report_id}.json", {"report_id": report_id, "artifact_identity": {"report_id": report_id}})
    write_json(root / "objects" / "handoff" / f"handoff_to_step4__{report_id}.json", {"report_id": report_id, "artifact_identity": {"report_id": report_id}})
    write_json(
        root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json",
        {
            "report_id": report_id,
            "decision": "iterate",
            "research_judgment": {
                "research_memo": {
                    "revision_strategy": {
                        "loop_authorization": "approved_for_step3b_handoff",
                        "revision_needed": True,
                    }
                }
            },
        },
    )


def valid_synthesis(report_id: str = REPORT_ID) -> dict[str, Any]:
    return {
        "contract_version": "factorforge_main_agent_multibranch_synthesis_v1",
        "report_id": report_id,
        "created_at_utc": utc_now(),
        "producer": "current_main_agent",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "branch_selection_policy": {
            "max_total_branches": 3,
            "max_exploit_branches": 1,
            "max_exploration_branches": 2,
            "selection_standard": "promising_and_solid",
            "preserve_broad_economic_hypothesis": True,
        },
        "selected_branches": [
            {
                "branch_role": "exploit",
                "law_id": "exploit_delta_state",
                "child_formula": "rank(delta(close, 1))",
                "why_selected": "Tests the strongest local estimator repair.",
                "economic_mechanism_link": "Preserves price-state payoff while testing cleaner timing.",
                "math_model_link": "Stochastic-process estimator repair.",
                "expected_metric_signature": {"rank_ic_mean": "non_decreasing"},
                "falsification_tests": ["Rank IC deteriorates.", "Cost-adjusted annual return remains negative."],
                "kill_criteria": ["Repeats parent formula.", "Net evidence worsens after costs."],
                "source_agent_roles": ["statistical_falsification_agent"],
            },
            {
                "branch_role": "exploration",
                "law_id": "explore_participation_state",
                "child_formula": "rank(volume)",
                "why_selected": "Tests a different latent state proposed by a minority Council role.",
                "how_it_differs_from_exploit": "Changes the latent state to participation pressure rather than price timing.",
                "mechanism_difference_class": "latent_state",
                "economic_mechanism_link": "Tests whether abnormal participation pressure is payer-facing state.",
                "math_model_link": "Changes stochastic-process state variable from price timing to flow pressure.",
                "expected_metric_signature": {"rank_ic_mean": "positive_if_state_valid"},
                "falsification_tests": ["Participation state has weaker IC than exploit.", "Drawdown worsens."],
                "kill_criteria": ["No gross payoff.", "No net payoff after cost."],
                "source_agent_roles": ["microstructure_cost_analyst"],
            },
        ],
        "rejected_branches": [],
    }


def direct_code_synthesis(report_id: str = REPORT_ID) -> dict[str, Any]:
    payload = valid_synthesis(report_id)
    common_contract = {
        "target_function": "factor_factory.factor_laws.moneyflow.derived_state.compute_factor_from_state_frame",
        "required_fields": ["v15_repair_confirmed_absorption", "intraday_flow_signal", "circ_mv"],
        "information_set": "cutoff_state_only_no_future_minutes",
        "mutation_scope": "registered_moneyflow_law_only",
    }
    payload["selected_branches"] = [
        {
            "branch_role": "exploit",
            "law_id": "miller_flow_v18a_absolute_long_edge_gate_v1",
            "implementation_mode": "direct_code",
            "child_formula": "direct_code_law:miller_flow_v18a_absolute_long_edge_gate_v1",
            "why_selected": "Tests the strongest exploit branch as a direct-code moneyflow law.",
            "economic_mechanism_link": "Keeps the repaired absorption state but requires positive long-edge drift.",
            "math_model_link": "Direct-code derived-state law for absorbing stochastic process with long-edge gate.",
            "expected_metric_signature": {"long_side_annual_return_after_cost": "positive", "rank_ic_mean": "non_decreasing"},
            "falsification_tests": ["Long-side return remains negative.", "Rank IC deteriorates versus parent."],
            "kill_criteria": ["No positive top-bucket return after cost.", "No IC improvement versus parent."],
            "source_agent_roles": ["main_agent_orchestrator"],
            "direct_code_revision_contract": {**common_contract, "code_law_id": "miller_flow_v18a_absolute_long_edge_gate_v1"},
        },
        {
            "branch_role": "exploration",
            "law_id": "miller_flow_v18b_first_passage_repair_edge_v1",
            "implementation_mode": "direct_code",
            "child_formula": "direct_code_law:miller_flow_v18b_first_passage_repair_edge_v1",
            "why_selected": "Explores first-passage payoff instead of additive score repair.",
            "how_it_differs_from_exploit": "Changes the mathematical object from long-edge drift gate to first-passage payoff process with up/down hitting probabilities.",
            "mechanism_difference_class": "first_passage_payoff",
            "economic_mechanism_link": "Tests whether repaired absorption predicts upward barrier hit before downside failure.",
            "math_model_link": "First-passage stochastic process payoff with asymmetric up/down barriers.",
            "expected_metric_signature": {"long_side_annual_return_after_cost": "positive_if_hitting_model_valid", "rank_ic_mean": "positive"},
            "falsification_tests": ["No improvement versus V18A.", "Long-side risk-adjusted return remains weak."],
            "kill_criteria": ["No positive top-bucket return.", "Worse drawdown than parent."],
            "source_agent_roles": ["main_agent_orchestrator"],
            "direct_code_revision_contract": {**common_contract, "code_law_id": "miller_flow_v18b_first_passage_repair_edge_v1"},
        },
    ]
    return payload


def write_synthesis(root: Path, payload: dict[str, Any], report_id: str = REPORT_ID) -> None:
    write_json(synthesis_path(root, report_id), payload)
    markdown_path(root, report_id).parent.mkdir(parents=True, exist_ok=True)
    markdown_path(root, report_id).write_text("# Main Agent Multibranch Synthesis\n\nSynthetic smoke.\n", encoding="utf-8")


def case_happy(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    mat = materialize(root)
    report = load_json(aggregate_path(root))
    children = report.get("children") if isinstance(report.get("children"), list) else []
    specs = [load_json(Path(child["executable_revision_spec_path"])) for child in children]
    materialization_reports = [load_json(Path(child["materialization_report_path"])) for child in children]
    hashes = [spec.get("child_formula_hash") for spec in specs]
    child_snapshots_ok = all(
        (daily_dir(root, child["child_report_id"]) / f"daily_input__{child['child_report_id']}.parquet").exists()
        and (daily_dir(root, child["child_report_id"]) / f"daily_input__{child['child_report_id']}.csv").exists()
        for child in children
    )
    branch_context_ok = all(
        spec.get("branch_group_id")
        and spec.get("branch_context", {}).get("source_multibranch_synthesis_sha256")
        and spec.get("branch_role") in {"exploit", "exploration"}
        for spec in specs
    )
    materialization_branch_context_ok = all(
        materialization.get("branch_id") == spec.get("branch_id")
        and materialization.get("source_branch_id") == "multibranch_seed"
        and materialization.get("branch_group_id") == spec.get("branch_group_id")
        and materialization.get("source_multibranch_synthesis_sha256") == spec.get("source_multibranch_synthesis_sha256")
        and materialization.get("branch_context", {}).get("law_id") == spec.get("branch_context", {}).get("law_id")
        for materialization, spec in zip(materialization_reports, specs)
    )
    return {
        "case": "multibranch_materializes_exploit_and_exploration_children",
        "ok": approval["rc"] == 0 and mat["rc"] == 0 and report.get("status") == "PASS" and len(children) == 2 and len(set(hashes)) == 2 and child_snapshots_ok and branch_context_ok and materialization_branch_context_ok,
        "approval": approval,
        "materialize": mat,
        "child_count": len(children),
        "child_formula_hashes": hashes,
        "child_snapshots_ok": child_snapshots_ok,
        "branch_context_ok": branch_context_ok,
        "materialization_branch_context_ok": materialization_branch_context_ok,
        "aggregate_report": str(aggregate_path(root)),
    }


def case_direct_code_materialization(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, direct_code_synthesis())
    approval = approve(root)
    mat = materialize(root)
    report = load_json(aggregate_path(root))
    children = report.get("children") if isinstance(report.get("children"), list) else []
    specs = [load_json(Path(child["executable_revision_spec_path"])) for child in children]
    materialization_reports = [load_json(Path(child["materialization_report_path"])) for child in children]
    direct_contracts_present = all(isinstance(spec.get("direct_code_revision_contract"), dict) and spec["direct_code_revision_contract"] for spec in specs)
    direct_modes_present = all(spec.get("implementation_mode") == "direct_code" for spec in specs)
    qlib_not_applicable = all(
        load_json(Path(materialization["materialized_artifacts"]["qlib_adapter_config"])).get("qlib_native_status") == "not_applicable"
        for materialization in materialization_reports
    )
    unique_code_hashes = len({spec.get("child_formula_hash") for spec in specs}) == len(specs)
    return {
        "case": "multibranch_materializes_direct_code_children",
        "ok": approval["rc"] == 0
        and mat["rc"] == 0
        and report.get("status") == "PASS"
        and len(children) == 2
        and direct_contracts_present
        and direct_modes_present
        and qlib_not_applicable
        and unique_code_hashes,
        "approval": approval,
        "materialize": mat,
        "child_count": len(children),
        "implementation_modes": [spec.get("implementation_mode") for spec in specs],
        "child_code_law_hashes": [spec.get("child_formula_hash") for spec in specs],
        "direct_contracts_present": direct_contracts_present,
        "qlib_not_applicable": qlib_not_applicable,
        "aggregate_report": str(aggregate_path(root)),
    }


def case_existing_materialization_reused(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    first = materialize(root)
    aggregate = aggregate_path(root)
    before_sha = sha256_file(aggregate) if aggregate.exists() else ""
    before_report = load_json(aggregate)
    second = materialize(root)
    after_sha = sha256_file(aggregate) if aggregate.exists() else ""
    after_report = load_json(aggregate)
    children = after_report.get("children") if isinstance(after_report.get("children"), list) else []
    return {
        "case": "multibranch_existing_materialization_reused_without_rewrite",
        "ok": (
            approval["rc"] == 0
            and first["rc"] == 0
            and second["rc"] == 0
            and before_report.get("status") == "PASS"
            and after_report.get("status") == "PASS"
            and before_sha == after_sha
            and len(children) == 2
            and "SKIPPED_EXISTING_MULTIBRANCH_MATERIALIZATION" in second["stdout_tail"]
        ),
        "approval": approval,
        "first_materialize": first,
        "second_materialize": second,
        "before_sha": before_sha,
        "after_sha": after_sha,
        "before_status": before_report.get("status"),
        "after_status": after_report.get("status"),
        "skip_token_present": "SKIPPED_EXISTING_MULTIBRANCH_MATERIALIZATION" in second["stdout_tail"],
        "child_count": len(children),
        "aggregate_report": str(aggregate),
    }


def case_source_mutation(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    payload = load_json(synthesis_path(root))
    payload["rejected_branches"].append({"law_id": "mutated_after_approval", "reason": "test mutation"})
    write_json(synthesis_path(root), payload)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_SOURCE_SYNTHESIS_CHANGED"
    return {"case": "multibranch_source_mutation_blocks", "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text, "token_present": token in text, "materialize": mat}


def case_adapter_synthesis_mutation(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    payload = load_json(approval_path(root))
    adapter_path = Path(payload["selected_branches"][0]["adapter_synthesis_path"])
    adapter = load_json(adapter_path)
    adapter["selected_revision"]["child_formula"] = "rank(high)"
    adapter["selected_revision"]["law_id"] = "mutated_adapter_law"
    write_json(adapter_path, adapter)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_ADAPTER_SYNTHESIS_CHANGED"
    return {"case": "multibranch_adapter_synthesis_mutation_blocks", "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text, "token_present": token in text, "materialize": mat}


def case_duplicate_approval_hash(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    payload = load_json(approval_path(root))
    payload["selected_branches"][1]["child_formula_hash"] = payload["selected_branches"][0]["child_formula_hash"]
    write_json(approval_path(root), payload)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_CHILD_FORMULA_DUPLICATE"
    return {"case": "multibranch_duplicate_child_formula_blocks", "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text, "token_present": token in text, "materialize": mat}


def case_missing_approval(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_APPROVAL_MISSING"
    return {"case": "multibranch_missing_approval_blocks", "ok": mat["rc"] == 1 and token in text, "token_present": token in text, "materialize": mat}


def case_missing_parent_alpha_preflight_blocks(root: Path) -> dict[str, Any]:
    setup_parent(root)
    (root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json").unlink()
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_PREFLIGHT_FAILED"
    return {
        "case": "multibranch_missing_parent_alpha_preflight_blocks",
        "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text and "alpha_idea_master" in text,
        "token_present": token in text,
        "approval": approval,
        "materialize": mat,
    }


def case_missing_daily_source_preflight_blocks(root: Path) -> dict[str, Any]:
    setup_parent(root)
    data_prep_path = root / "objects" / "data_prep_master" / f"data_prep_master__{REPORT_ID}.json"
    data_prep = load_json(data_prep_path)
    data_prep["local_input_paths"] = {}
    write_json(data_prep_path, data_prep)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_PREFLIGHT_FAILED"
    return {
        "case": "multibranch_missing_daily_source_preflight_blocks",
        "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text and "daily_df_parquet" in text,
        "token_present": token in text,
        "approval": approval,
        "materialize": mat,
    }


def case_qlib_target_collision_preflight_blocks(root: Path) -> dict[str, Any]:
    setup_parent(root)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    approval_payload = load_json(approval_path(root))
    child = approval_payload["selected_branches"][0]["child_report_id"]
    qlib_path = root / "objects" / "data_prep_master" / f"qlib_adapter_config__{child}.json"
    write_json(qlib_path, {"report_id": child, "preexisting": True})
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_PREFLIGHT_FAILED"
    qlib_after = load_json(qlib_path)
    return {
        "case": "multibranch_qlib_target_collision_preflight_blocks",
        "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text and "qlib_adapter_config" in text and qlib_after.get("preexisting") is True,
        "token_present": token in text,
        "preexisting_preserved": qlib_after.get("preexisting") is True,
        "approval": approval,
        "materialize": mat,
    }


def case_lineage_repair_enables_materialization(root: Path) -> dict[str, Any]:
    ancestor = "MULTIBRANCH_MATERIALIZATION_ANCESTOR"
    setup_parent(root, ancestor)
    setup_parent(root)
    target_alpha = root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json"
    target_alpha.unlink()
    repair = repair_lineage(root, report_id=REPORT_ID, source_report_id=ancestor)
    repaired_payload = load_json(target_alpha)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    mat = materialize(root)
    report = load_json(aggregate_path(root))
    repair_contract = repaired_payload.get("lineage_repair") if isinstance(repaired_payload.get("lineage_repair"), dict) else {}
    return {
        "case": "multibranch_lineage_repair_enables_materialization",
        "ok": (
            repair["rc"] == 0
            and repair_contract.get("status") == "pass"
            and repair_contract.get("source_report_id") == ancestor
            and repaired_payload.get("report_id") == REPORT_ID
            and approval["rc"] == 0
            and mat["rc"] == 0
            and report.get("status") == "PASS"
        ),
        "repair": repair,
        "lineage_repair": repair_contract,
        "approval": approval,
        "materialize": mat,
    }


def case_lineage_repair_semantic_drift_blocks(root: Path) -> dict[str, Any]:
    ancestor = "MULTIBRANCH_MATERIALIZATION_ANCESTOR"
    setup_parent(root, ancestor)
    setup_parent(root)
    target_alpha = root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json"
    target_alpha.unlink()
    repair = repair_lineage(root, report_id=REPORT_ID, source_report_id=ancestor)
    repaired_payload = load_json(target_alpha)
    repaired_payload["semantic_drift_after_repair"] = True
    write_json(target_alpha, repaired_payload)
    write_synthesis(root, valid_synthesis())
    approval = approve(root)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_PREFLIGHT_FAILED"
    return {
        "case": "lineage_repair_semantic_drift_blocks",
        "ok": repair["rc"] == 0 and approval["rc"] == 0 and mat["rc"] == 1 and token in text and "semantic payload changed" in text,
        "token_present": token in text,
        "repair": repair,
        "approval": approval,
        "materialize": mat,
    }


def case_lineage_repair_source_missing_blocks(root: Path) -> dict[str, Any]:
    setup_parent(root)
    missing_source = "MULTIBRANCH_MATERIALIZATION_MISSING_ANCESTOR"
    repair = repair_lineage(root, report_id=REPORT_ID, source_report_id=missing_source)
    text = repair["stdout_tail"] + repair["stderr_tail"]
    token = "BLOCK_FACTORFORGE_LINEAGE_REPAIR_SOURCE_MISSING"
    return {
        "case": "lineage_repair_source_missing_blocks",
        "ok": repair["rc"] == 1 and token in text,
        "token_present": token in text,
        "repair": repair,
    }


def case_lineage_repair_target_exists_blocks(root: Path) -> dict[str, Any]:
    ancestor = "MULTIBRANCH_MATERIALIZATION_ANCESTOR"
    setup_parent(root, ancestor)
    setup_parent(root)
    repair = repair_lineage(root, report_id=REPORT_ID, source_report_id=ancestor)
    text = repair["stdout_tail"] + repair["stderr_tail"]
    token = "BLOCK_FACTORFORGE_LINEAGE_REPAIR_TARGET_EXISTS"
    return {
        "case": "lineage_repair_target_exists_blocks",
        "ok": repair["rc"] == 1 and token in text,
        "token_present": token in text,
        "repair": repair,
    }


def case_direct_code_law_unavailable_preflight_blocks(root: Path) -> dict[str, Any]:
    setup_parent(root)
    payload = direct_code_synthesis()
    payload["selected_branches"][0]["law_id"] = "miller_flow_missing_registry_law_v1"
    payload["selected_branches"][0]["child_formula"] = "direct_code_law:miller_flow_missing_registry_law_v1"
    payload["selected_branches"][0]["direct_code_revision_contract"]["code_law_id"] = "miller_flow_missing_registry_law_v1"
    write_synthesis(root, payload)
    approval = approve(root)
    mat = materialize(root)
    text = mat["stdout_tail"] + mat["stderr_tail"]
    token = "BLOCK_FACTORFORGE_MULTIBRANCH_PREFLIGHT_FAILED"
    return {
        "case": "multibranch_direct_code_law_unavailable_preflight_blocks",
        "ok": approval["rc"] == 0 and mat["rc"] == 1 and token in text and "direct_code law unavailable" in text,
        "token_present": token in text,
        "approval": approval,
        "materialize": mat,
    }


def case_non_tmp_root_blocks() -> dict[str, Any]:
    root = Path("/dev/null/factorforge_multibranch_materialization_non_tmp_probe")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_factorforge_multibranch_materialization_smoke.py"), "--root", str(root)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    text = proc.stdout + proc.stderr
    token = "BLOCK_NON_TMP_FACTORFORGE_ROOT"
    return {"case": "multibranch_non_tmp_root_blocks", "ok": proc.returncode == 1 and token in text and not root.exists(), "token_present": token in text, "rc": proc.returncode}


def run_case(root: Path, name: str, fn) -> dict[str, Any]:
    case_root = root / name
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True, exist_ok=True)
    try:
        return fn(case_root)
    except Exception as exc:  # smoke summary should preserve the failure cause
        return {"case": name, "ok": False, "error": repr(exc)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/tmp/factorforge_multibranch_materialization_smoke")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).expanduser()
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT", file=sys.stderr)
        return 1

    before = file_snapshot()
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cases = [
        run_case(root, "happy_path", case_happy),
        run_case(root, "direct_code_materialization", case_direct_code_materialization),
        run_case(root, "existing_materialization_reused", case_existing_materialization_reused),
        run_case(root, "source_mutation", case_source_mutation),
        run_case(root, "adapter_synthesis_mutation", case_adapter_synthesis_mutation),
        run_case(root, "duplicate_approval_hash", case_duplicate_approval_hash),
        run_case(root, "missing_approval", case_missing_approval),
        run_case(root, "missing_parent_alpha_preflight", case_missing_parent_alpha_preflight_blocks),
        run_case(root, "missing_daily_source_preflight", case_missing_daily_source_preflight_blocks),
        run_case(root, "qlib_target_collision_preflight", case_qlib_target_collision_preflight_blocks),
        run_case(root, "direct_code_law_unavailable_preflight", case_direct_code_law_unavailable_preflight_blocks),
        run_case(root, "lineage_repair_enables_materialization", case_lineage_repair_enables_materialization),
        run_case(root, "lineage_repair_semantic_drift", case_lineage_repair_semantic_drift_blocks),
        run_case(root, "lineage_repair_source_missing", case_lineage_repair_source_missing_blocks),
        run_case(root, "lineage_repair_target_exists", case_lineage_repair_target_exists_blocks),
        case_non_tmp_root_blocks(),
    ]
    after = file_snapshot()
    polluted = pollution_matches(after - before)
    summary = {
        "verdict": "ACCEPT" if all(case.get("ok") for case in cases) and not polluted else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(polluted), "new_files": polluted},
        "notes": [
            "Synthetic /tmp-only P2 multibranch materialization smoke.",
            "No real factor research, clean data processing, search worker, official promotion, or production loop execution.",
        ],
    }
    summary_path = root / "multibranch_materialization_smoke_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[SUMMARY] {summary_path}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
