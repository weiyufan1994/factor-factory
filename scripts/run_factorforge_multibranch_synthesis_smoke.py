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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.parser import parse_formula

REPORT_ID = "MULTIBRANCH_SYNTHESIS_SMOKE"
CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
POLLUTION_MARKERS = ["MULTIBRANCH_SYNTHESIS_SMOKE", "factorforge_multibranch_synthesis"]


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


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if root.exists():
            files.update(str(item.relative_to(REPO_ROOT)) for item in root.rglob("*") if item.is_file())
    return files


def pollution_matches(new_files: set[str]) -> list[str]:
    return sorted(item for item in new_files if any(marker in item for marker in POLLUTION_MARKERS))


def formula_hash(formula: str) -> str:
    parsed = parse_formula(formula)
    if parsed.get("parse_status") != "success":
        raise RuntimeError(f"formula parse failed: {formula}: {parsed.get('parse_errors')}")
    return str(parsed.get("formula_hash") or "")


def council_dir(root: Path, report_id: str = REPORT_ID) -> Path:
    return root / "objects" / "research_iteration_master" / "revision_council" / report_id


def synthesis_path(root: Path, report_id: str = REPORT_ID) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.json"


def markdown_path(root: Path, report_id: str = REPORT_ID) -> Path:
    return council_dir(root, report_id) / f"main_agent_multibranch_synthesis__{report_id}.md"


def write_markdown(root: Path, title: str = "Main Agent Multi-Branch Synthesis") -> None:
    path = markdown_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\nSynthetic /tmp-only smoke artifact.\n", encoding="utf-8")


def run_cmd(root: Path, cmd: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, text=True, capture_output=True)
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-4000:], "stderr_tail": proc.stderr[-4000:]}


def validate(root: Path) -> dict[str, Any]:
    return run_cmd(root, [sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_multibranch_synthesis.py", "--report-id", REPORT_ID])


def setup_root(root: Path) -> None:
    (root / "objects" / "factor_spec_master").mkdir(parents=True, exist_ok=True)
    parent_formula = "rank(close)"
    write_json(
        root / "objects" / "factor_spec_master" / f"factor_spec_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "canonical_spec": {
                "formula_text": parent_formula,
                "formula_hash": formula_hash(parent_formula),
            },
        },
    )
    prior = {
        "contract_version": "factorforge_prior_revision_memory_v1",
        "forbidden_repeat_formula_hashes": [formula_hash("rank(open)")],
        "forbidden_repeat_revision_rules": ["forbidden_prior_law"],
    }
    write_json(council_dir(root) / f"revision_council_packet__{REPORT_ID}.json", {"report_id": REPORT_ID, "prior_revision_memory": prior})


def valid_synthesis() -> dict[str, Any]:
    return {
        "contract_version": "factorforge_main_agent_multibranch_synthesis_v1",
        "report_id": REPORT_ID,
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
                "law_id": "exploit_smoothing_state_law",
                "child_formula": "rank(delta(close, 1))",
                "why_selected": "Best supported local estimator repair from Council evidence.",
                "economic_mechanism_link": "Preserves the broad price-state payoff while testing cleaner timing.",
                "math_model_link": "Stochastic process estimator repair of the observed price state.",
                "expected_metric_signature": {"rank_ic_mean": "non_decreasing", "turnover": "not_materially_higher"},
                "falsification_tests": ["Rank IC deteriorates versus parent.", "Cost-adjusted annual return remains materially negative."],
                "kill_criteria": ["Formula repeats a falsified ancestor.", "Net evidence worsens after costs."],
                "source_agent_roles": ["statistical_falsification_agent"],
            },
            {
                "branch_role": "exploration",
                "law_id": "explore_participation_state_law",
                "child_formula": "rank(volume)",
                "why_selected": "A minority Council direction changes the latent state rather than only smoothing the exploit estimator.",
                "how_it_differs_from_exploit": "Changes the latent state to participation shock and conditioning flow pressure, not just a window parameter.",
                "mechanism_difference_class": "latent_state",
                "economic_mechanism_link": "Tests whether abnormal participation pressure is the payer-facing state.",
                "math_model_link": "Changes the stochastic process state variable from price timing to flow pressure.",
                "expected_metric_signature": {"rank_ic_mean": "positive_if_state_valid", "turnover": "bounded"},
                "falsification_tests": ["Participation state has weaker IC than exploit.", "Drawdown worsens versus parent."],
                "kill_criteria": ["No gross payoff.", "No net payoff after cost."],
                "source_agent_roles": ["microstructure_cost_analyst"],
            },
        ],
        "rejected_branches": [{"law_id": "duplicate_parent_law", "reason": "repeats parent formula"}],
    }


def write_synthesis(root: Path, payload: dict[str, Any]) -> None:
    write_json(synthesis_path(root), payload)
    write_markdown(root)


def case_valid(root: Path) -> dict[str, Any]:
    write_synthesis(root, valid_synthesis())
    proc = validate(root)
    payload = load_json(synthesis_path(root))
    return {"case": "valid_exploit_plus_exploration_pass", "ok": proc["rc"] == 0, "validate": proc, "branch_count": len(payload.get("selected_branches") or [])}


def direct_code_synthesis() -> dict[str, Any]:
    payload = valid_synthesis()
    payload["selected_branches"] = [
        {
            "branch_role": "exploit",
            "law_id": "miller_flow_v18a_absolute_long_edge_gate_v1",
            "implementation_mode": "direct_code",
            "child_formula": "direct_code_law:miller_flow_v18a_absolute_long_edge_gate_v1",
            "why_selected": "Tests the strongest exploit branch as a direct-code moneyflow law.",
            "economic_mechanism_link": "Keeps the V15 repaired absorption state but requires positive long-edge drift.",
            "math_model_link": "Direct-code derived-state law for an absorbing stochastic process with long-edge gate.",
            "expected_metric_signature": {"long_side_annual_return_after_cost": "positive", "rank_ic_mean": "non_decreasing"},
            "falsification_tests": ["Long-side return remains negative.", "Rank IC deteriorates versus V15."],
            "kill_criteria": ["No positive top-bucket return after cost.", "No IC improvement versus V15."],
            "source_agent_roles": ["main_agent_orchestrator"],
            "direct_code_revision_contract": {
                "target_function": "factor_factory.factor_laws.moneyflow.derived_state.compute_factor_from_state_frame",
                "code_law_id": "miller_flow_v18a_absolute_long_edge_gate_v1",
                "required_fields": ["v15_repair_confirmed_absorption", "intraday_flow_signal", "circ_mv"],
                "information_set": "cutoff_state_only_no_future_minutes",
                "mutation_scope": "registered_moneyflow_law_only",
            },
        },
        {
            "branch_role": "exploration",
            "law_id": "miller_flow_v18b_first_passage_repair_edge_v1",
            "implementation_mode": "direct_code",
            "child_formula": "direct_code_law:miller_flow_v18b_first_passage_repair_edge_v1",
            "why_selected": "Explores a first-passage payoff form rather than an additive repaired score.",
            "how_it_differs_from_exploit": "Changes the mathematical object from long-edge drift gate to first-passage payoff process with up/down hitting probabilities.",
            "mechanism_difference_class": "first_passage_payoff",
            "economic_mechanism_link": "Tests whether repaired absorption predicts upward barrier hit before downside failure.",
            "math_model_link": "First-passage stochastic process payoff with asymmetric up/down barriers.",
            "expected_metric_signature": {"long_side_annual_return_after_cost": "positive_if_hitting_model_valid", "rank_ic_mean": "positive"},
            "falsification_tests": ["No improvement versus V18A.", "Long-side risk-adjusted return remains weak."],
            "kill_criteria": ["No positive top-bucket return.", "Worse drawdown than V15."],
            "source_agent_roles": ["main_agent_orchestrator"],
            "direct_code_revision_contract": {
                "target_function": "factor_factory.factor_laws.moneyflow.derived_state.compute_factor_from_state_frame",
                "code_law_id": "miller_flow_v18b_first_passage_repair_edge_v1",
                "required_fields": ["v15_repair_confirmed_absorption", "intraday_flow_signal", "circ_mv"],
                "information_set": "cutoff_state_only_no_future_minutes",
                "mutation_scope": "registered_moneyflow_law_only",
            },
        },
    ]
    return payload


def case_direct_code_valid(root: Path) -> dict[str, Any]:
    write_synthesis(root, direct_code_synthesis())
    proc = validate(root)
    payload = load_json(synthesis_path(root))
    return {
        "case": "direct_code_multibranch_laws_pass",
        "ok": proc["rc"] == 0,
        "validate": proc,
        "branch_count": len(payload.get("selected_branches") or []),
        "law_ids": [branch.get("law_id") for branch in payload.get("selected_branches") or []],
    }


def case_mutation(root: Path, name: str, mutate, token: str) -> dict[str, Any]:
    payload = valid_synthesis()
    mutate(payload)
    write_synthesis(root, payload)
    proc = validate(root)
    out = proc["stdout_tail"] + proc["stderr_tail"]
    return {"case": name, "ok": proc["rc"] == 1 and token in out, "expected_token": token, "token_present": token in out, "validate": proc}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/tmp/factorforge_multibranch_synthesis_smoke")
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
    setup_root(root)

    cases: list[dict[str, Any]] = []
    cases.append(case_valid(root))
    cases.append(case_direct_code_valid(root))
    cases.append(case_mutation(root, "duplicate_formula_hash_blocks", lambda p: p["selected_branches"].__setitem__(1, {**p["selected_branches"][1], "child_formula": p["selected_branches"][0]["child_formula"]}), "BLOCK_FACTORFORGE_MULTIBRANCH_DUPLICATE_FORMULA_HASH"))
    cases.append(case_mutation(root, "missing_exploit_branch_blocks", lambda p: p["selected_branches"][0].__setitem__("branch_role", "exploration"), "BLOCK_FACTORFORGE_MULTIBRANCH_EXPLOIT_BRANCH_COUNT"))
    cases.append(case_mutation(root, "too_many_branches_blocks", lambda p: p["selected_branches"].extend([copy.deepcopy(p["selected_branches"][1]), {**copy.deepcopy(p["selected_branches"][1]), "law_id": "extra_branch", "child_formula": "rank(high)"}]), "BLOCK_FACTORFORGE_MULTIBRANCH_TOO_MANY_BRANCHES"))
    cases.append(case_mutation(root, "exploration_parameter_only_blocks", lambda p: p["selected_branches"][1].update({"how_it_differs_from_exploit": "uses a different lookback window parameter only", "economic_mechanism_link": p["selected_branches"][0]["economic_mechanism_link"], "math_model_link": p["selected_branches"][0]["math_model_link"], "mechanism_difference_class": "parameter_tuning"}), "BLOCK_FACTORFORGE_MULTIBRANCH_NO_MECHANISM_DIVERSITY"))
    cases.append(case_mutation(root, "forbidden_prior_hash_blocks", lambda p: p["selected_branches"][1].__setitem__("child_formula", "rank(open)"), "BLOCK_FACTORFORGE_MULTIBRANCH_FORBIDDEN_FORMULA_HASH"))
    cases.append(case_mutation(root, "forbidden_prior_rule_blocks", lambda p: p["selected_branches"][1].__setitem__("law_id", "forbidden_prior_law"), "BLOCK_FACTORFORGE_MULTIBRANCH_FORBIDDEN_REVISION_RULE"))
    cases.append(case_mutation(root, "parent_formula_repeat_blocks", lambda p: p["selected_branches"][0].__setitem__("child_formula", "rank(close)"), "BLOCK_FACTORFORGE_MULTIBRANCH_PARENT_FORMULA_REPEATED"))
    cases.append(case_mutation(root, "branch_unsafe_permissions_block", lambda p: p["selected_branches"][0].update({"canonical_write_permission": True, "execution_allowed_by_default": True, "human_approval_required": False}), "BLOCK_FACTORFORGE_MULTIBRANCH_BRANCH_PERMISSION_UNSAFE"))

    after = file_snapshot()
    polluted = pollution_matches(after - before)
    summary = {
        "verdict": "ACCEPT" if all(case.get("ok") for case in cases) and not polluted else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": True, "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(polluted), "new_files": polluted},
        "notes": ["Synthetic /tmp-only multibranch synthesis contract smoke.", "No real factor research, clean data processing, search worker, materialization, or official promotion."],
    }
    summary_path = root / "multibranch_synthesis_smoke_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[SUMMARY] {summary_path}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
