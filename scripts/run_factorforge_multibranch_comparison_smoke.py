#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.mechanism_math.main_agent_memo import build_main_agent_mechanism_memo

REPORT_ID = "MULTIBRANCH_COMPARISON_SMOKE"
CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
POLLUTION_MARKERS = ["MULTIBRANCH_COMPARISON_SMOKE", "factorforge_multibranch_comparison"]


def load_p2_smoke_module():
    path = REPO_ROOT / "scripts" / "run_factorforge_multibranch_materialization_smoke.py"
    spec = importlib.util.spec_from_file_location("run_factorforge_multibranch_materialization_smoke", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P2 = load_p2_smoke_module()
P2.REPORT_ID = REPORT_ID


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


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if root.exists():
            files.update(str(item.relative_to(REPO_ROOT)) for item in root.rglob("*") if item.is_file())
    return files


def pollution_matches(new_files: set[str]) -> list[str]:
    return sorted(item for item in new_files if any(marker in item for marker in POLLUTION_MARKERS))


def run_cmd(root: Path, cmd: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {
        "command": cmd,
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-5000:],
        "stderr_tail": proc.stderr[-5000:],
    }


def metric_payload(
    *,
    rank_ic: float,
    annual: float,
    cost: float,
    turnover: float,
    drawdown: float,
    recovery: float,
) -> dict[str, Any]:
    return {
        "key_metrics": {
            "rank_ic_mean": rank_ic,
            "long_side_annual_return": annual,
            "cost_adjusted_annual_return": cost,
            "turnover": turnover,
            "long_side_max_drawdown": drawdown,
            "long_side_recovery_days": recovery,
        }
    }


def object_path(root: Path, kind: str, report_id: str) -> Path:
    mapping = {
        "factor_evaluation": root / "objects" / "validation" / f"factor_evaluation__{report_id}.json",
        "factor_case_master": root / "objects" / "factor_case_master" / f"factor_case_master__{report_id}.json",
        "factor_run_master": root / "objects" / "factor_run_master" / f"factor_run_master__{report_id}.json",
        "research_iteration_master": root / "objects" / "research_iteration_master" / f"research_iteration_master__{report_id}.json",
        "factor_spec_master": root / "objects" / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        "main_agent_memo": root / "objects" / "research_iteration_master" / f"main_agent_mechanism_memo__{report_id}.json",
    }
    return mapping[kind]


def write_valid_main_agent_memo(root: Path, report_id: str, factor_spec: dict[str, Any], evaluation: dict[str, Any]) -> None:
    factor_case = {
        "report_id": report_id,
        "artifact_identity": {"report_id": report_id, "artifact_role": "factor_case_master"},
        "headline_metrics": evaluation["key_metrics"],
    }
    iteration = load_json(object_path(root, "research_iteration_master", report_id))
    memo = build_main_agent_mechanism_memo(
        report_id=report_id,
        factor_spec=factor_spec,
        factor_case=factor_case,
        evaluation_summary=evaluation,
        step6_iteration=iteration,
    )
    memo["producer"] = "smoke_current_main_agent"
    memo["agent_authorship"] = {
        "authoring_mode": "current_agent_freeform",
        "agent_role": "smoke_main_agent",
        "answered_without_deterministic_template": True,
    }
    formula = str((factor_spec.get("canonical_spec") or {}).get("formula_text") or factor_spec.get("formula_text") or "close")
    memo["mechanism_qa"] = {
        "formula_state_answer": f"The child formula `{formula}` is the state definition; its own close, delta, or volume token determines which observable state is being ranked.",
        "economic_hypothesis_answer": f"`{formula}` tests whether that formula-specific state identifies constrained rebalancers or liquidity demanders forced to transact at a next-horizon concession.",
        "math_model_answer": f"`{formula}` is treated as an observable estimator in a stochastic-process conditional-return model, not as a generic family label.",
        "payer_answer": f"The payer for `{formula}` is the constrained rebalancer or late liquidity demander whose immediacy objective makes the formula state temporarily mispriced.",
        "payoff_answer": f"`{formula}` should monetize through positive high-score long-side return after costs; otherwise this branch is falsified or inconclusive.",
        "estimator_mapping_answer": f"The mapping is direct: `{formula}` supplies the estimator and branch comparison checks whether this child estimator improves parent metrics.",
        "metric_signature_answer": f"`{formula}` should produce non-worse rank IC, better cost-adjusted annual return, lower drawdown pressure, and no destructive turnover increase.",
        "falsification_answer": f"`{formula}` is falsified if rank IC, long-side return, cost-adjusted return, drawdown, or recovery evidence deteriorates versus the parent.",
    }
    write_json(object_path(root, "main_agent_memo", report_id), memo)


def seed_step6_inputs(root: Path, report_id: str, metrics: dict[str, Any]) -> None:
    factor_spec = load_json(object_path(root, "factor_spec_master", report_id))
    evaluation = metric_payload(**metrics)
    write_json(object_path(root, "factor_evaluation", report_id), evaluation)
    write_json(
        object_path(root, "factor_case_master", report_id),
        {
            "report_id": report_id,
            "artifact_identity": {"report_id": report_id, "artifact_role": "factor_case_master"},
            "headline_metrics": evaluation["key_metrics"],
        },
    )
    write_json(
        object_path(root, "factor_run_master", report_id),
        {"report_id": report_id, "artifact_identity": {"report_id": report_id, "artifact_role": "factor_run_master"}},
    )
    write_json(
        object_path(root, "research_iteration_master", report_id),
        {
            "report_id": report_id,
            "artifact_identity": {"report_id": report_id, "artifact_role": "research_iteration_master"},
            "research_judgment": {
                "research_memo": {
                    "mechanism_analysis": {},
                    "evidence_audit": {},
                    "case_comparison": {},
                    "revision_strategy": {},
                    "search_policy_decision": {},
                }
            },
        },
    )
    write_valid_main_agent_memo(root, report_id, factor_spec, evaluation)


def setup_materialized_multibranch(root: Path) -> dict[str, Any]:
    P2.setup_parent(root, REPORT_ID)
    P2.write_synthesis(root, P2.valid_synthesis(REPORT_ID), REPORT_ID)
    approval = P2.approve(root)
    materialize = P2.materialize(root)
    aggregate = load_json(P2.aggregate_path(root, REPORT_ID))
    children = aggregate.get("children") if isinstance(aggregate.get("children"), list) else []
    seed_step6_inputs(
        root,
        REPORT_ID,
        {"rank_ic": 0.030, "annual": 0.040, "cost": -0.120, "turnover": 0.30, "drawdown": -0.42, "recovery": 1500.0},
    )
    if len(children) >= 1:
        seed_step6_inputs(
            root,
            children[0]["child_report_id"],
            {"rank_ic": 0.040, "annual": 0.070, "cost": -0.050, "turnover": 0.24, "drawdown": -0.36, "recovery": 900.0},
        )
    if len(children) >= 2:
        seed_step6_inputs(
            root,
            children[1]["child_report_id"],
            {"rank_ic": 0.010, "annual": -0.020, "cost": -0.180, "turnover": 0.42, "drawdown": -0.55, "recovery": 2200.0},
        )
    return {"approval": approval, "materialize": materialize, "aggregate": aggregate, "children": children}


def build_packet(root: Path, report_id: str) -> dict[str, Any]:
    return run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_revision_council_packet.py",
            "--report-id",
            report_id,
        ],
    )


def build_comparison(root: Path, selected_child: str) -> dict[str, Any]:
    return run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_branch_comparison.py",
            "--parent-report-id",
            REPORT_ID,
            "--loop-index",
            "1",
            "--selected-next-parent-child-report-id",
            selected_child,
            "--factorforge-root",
            str(root),
            "--why",
            "childA improves net evidence while preserving formula-law distinction",
            "--what-learned-from-exploration",
            "childB falsifies the exploration state and must be retained as sibling evidence",
        ],
    )


def validate_comparison(root: Path) -> dict[str, Any]:
    return run_cmd(
        root,
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/validate_branch_comparison.py",
            "--parent-report-id",
            REPORT_ID,
            "--loop-index",
            "1",
            "--factorforge-root",
            str(root),
        ],
    )


def comparison_path(root: Path) -> Path:
    return root / "objects" / "research_iteration_master" / f"branch_comparison__{REPORT_ID}__loop01.json"


def packet_path(root: Path, report_id: str) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id / f"revision_council_packet__{report_id}.json"


def case_missing_comparison_blocks(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child = setup["children"][0]["child_report_id"]
    packet = build_packet(root, child)
    text = packet["stdout_tail"] + packet["stderr_tail"]
    token = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_MISSING"
    return {"case": "branch_comparison_missing_blocks_next_council", "ok": packet["rc"] == 1 and token in text, "token_present": token in text, "packet": packet}


def case_sibling_memory_propagates(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child_a = setup["children"][0]["child_report_id"]
    child_b = setup["children"][1]["child_report_id"]
    comparison = build_comparison(root, child_a)
    validation = validate_comparison(root)
    packet = build_packet(root, child_a)
    payload = load_json(packet_path(root, child_a))
    sibling_memory = payload.get("sibling_branch_memory") if isinstance(payload.get("sibling_branch_memory"), dict) else {}
    siblings = sibling_memory.get("siblings") if isinstance(sibling_memory.get("siblings"), list) else []
    sibling_ids = {item.get("child_report_id") for item in siblings if isinstance(item, dict)}
    sibling_has_delta = bool(siblings and isinstance(siblings[0].get("metric_delta_vs_parent"), dict) and siblings[0]["metric_delta_vs_parent"].get("rank_ic_mean"))
    return {
        "case": "sibling_branch_memory_propagates_to_next_packet",
        "ok": comparison["rc"] == 0
        and validation["rc"] == 0
        and packet["rc"] == 0
        and payload.get("prior_revision_memory", {}).get("is_child_revision") is True
        and sibling_memory.get("required") is True
        and sibling_memory.get("branch_group_id") == setup["aggregate"].get("branch_group_id")
        and child_b in sibling_ids
        and child_a not in sibling_ids
        and sibling_has_delta,
        "comparison": comparison,
        "validation": validation,
        "packet": packet,
        "sibling_ids": sorted(str(item) for item in sibling_ids),
        "sibling_has_delta": sibling_has_delta,
    }


def case_unselected_sibling_packet_blocks(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child_a = setup["children"][0]["child_report_id"]
    child_b = setup["children"][1]["child_report_id"]
    comparison = build_comparison(root, child_a)
    packet = build_packet(root, child_b)
    text = packet["stdout_tail"] + packet["stderr_tail"]
    token = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SELECTED_CHILD_INVALID"
    return {
        "case": "unselected_sibling_packet_blocks",
        "ok": comparison["rc"] == 0 and packet["rc"] == 1 and token in text,
        "token_present": token in text,
        "comparison": comparison,
        "packet": packet,
    }


def case_comparison_source_hash_mutation_blocks(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child_a = setup["children"][0]["child_report_id"]
    build = build_comparison(root, child_a)
    payload = load_json(comparison_path(root))
    payload["source_multibranch_materialization_sha256"] = "0" * 64
    payload["children"][1]["metric_delta_vs_parent"]["rank_ic_mean"]["delta"] = -999.0
    write_json(comparison_path(root), payload)
    validation = validate_comparison(root)
    packet = build_packet(root, child_a)
    text = validation["stdout_tail"] + validation["stderr_tail"] + packet["stdout_tail"] + packet["stderr_tail"]
    token = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SOURCE_CHANGED"
    return {
        "case": "branch_comparison_source_hash_mutation_blocks",
        "ok": build["rc"] == 0 and validation["rc"] == 1 and packet["rc"] == 1 and token in text,
        "token_present": token in text,
        "validation": validation,
        "packet": packet,
    }


def case_selected_child_invalid_blocks(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child_a = setup["children"][0]["child_report_id"]
    build = build_comparison(root, child_a)
    payload = load_json(comparison_path(root))
    payload["main_agent_selection"]["selected_next_parent_child_report_id"] = "NOT_A_CHILD"
    write_json(comparison_path(root), payload)
    validation = validate_comparison(root)
    text = validation["stdout_tail"] + validation["stderr_tail"]
    token = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_SELECTED_CHILD_INVALID"
    return {"case": "branch_comparison_selected_child_invalid_blocks", "ok": build["rc"] == 0 and validation["rc"] == 1 and token in text, "token_present": token in text, "validation": validation}


def case_duplicate_formula_blocks(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child_a = setup["children"][0]["child_report_id"]
    build = build_comparison(root, child_a)
    payload = load_json(comparison_path(root))
    payload["children"][1]["formula_hash"] = payload["children"][0]["formula_hash"]
    write_json(comparison_path(root), payload)
    validation = validate_comparison(root)
    text = validation["stdout_tail"] + validation["stderr_tail"]
    token = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_DUPLICATE"
    return {"case": "branch_comparison_duplicate_formula_blocks", "ok": build["rc"] == 0 and validation["rc"] == 1 and token in text, "token_present": token in text, "validation": validation}


def case_missing_metrics_blocks(root: Path) -> dict[str, Any]:
    setup = setup_materialized_multibranch(root)
    child_a = setup["children"][0]["child_report_id"]
    build = build_comparison(root, child_a)
    payload = load_json(comparison_path(root))
    payload["children"][0]["metrics"].pop("rank_ic_mean", None)
    write_json(comparison_path(root), payload)
    validation = validate_comparison(root)
    text = validation["stdout_tail"] + validation["stderr_tail"]
    token = "BLOCK_FACTORFORGE_BRANCH_COMPARISON_CHILD_METRICS_MISSING"
    return {"case": "branch_comparison_missing_metrics_blocks", "ok": build["rc"] == 0 and validation["rc"] == 1 and token in text, "token_present": token in text, "validation": validation}


def case_non_tmp_root_blocks() -> dict[str, Any]:
    root = REPO_ROOT / "_factorforge_multibranch_comparison_non_tmp_probe"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_factorforge_multibranch_comparison_smoke.py"), "--root", str(root)],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    text = proc.stdout + proc.stderr
    token = "BLOCK_NON_TMP_FACTORFORGE_ROOT"
    return {"case": "multibranch_comparison_non_tmp_root_blocks", "ok": proc.returncode == 1 and token in text and not root.exists(), "token_present": token in text, "rc": proc.returncode}


def run_case(root: Path, name: str, fn: Callable[[Path], dict[str, Any]]) -> dict[str, Any]:
    case_root = root / name
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True, exist_ok=True)
    try:
        return fn(case_root)
    except Exception as exc:
        return {"case": name, "ok": False, "error": repr(exc)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/tmp/factorforge_multibranch_comparison_smoke")
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
        run_case(root, "missing_comparison", case_missing_comparison_blocks),
        run_case(root, "sibling_memory", case_sibling_memory_propagates),
        run_case(root, "unselected_sibling_packet", case_unselected_sibling_packet_blocks),
        run_case(root, "source_hash_mutation", case_comparison_source_hash_mutation_blocks),
        run_case(root, "selected_child_invalid", case_selected_child_invalid_blocks),
        run_case(root, "duplicate_formula", case_duplicate_formula_blocks),
        run_case(root, "missing_metrics", case_missing_metrics_blocks),
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
            "Synthetic /tmp-only P3 branch comparison and sibling-memory smoke.",
            "No real factor research, clean data processing, search worker, official promotion, or production loop execution.",
        ],
    }
    summary_path = root / "multibranch_comparison_smoke_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[SUMMARY] {summary_path}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
