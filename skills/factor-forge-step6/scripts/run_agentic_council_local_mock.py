#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OBJ = FF / "objects"
RESULT_VERSION = "factorforge_agentic_revision_council_result_v1"
TOKEN_TASKBOOK_MISSING = "BLOCK_REVISION_COUNCIL_AGENTIC_TASKBOOK_MISSING"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def relation_for_role(role: str) -> str:
    relations = {
        "symbolic_law_discovery": "factor_t = estimator_kernel(observable_state_t); higher persistence should improve net long-side evidence",
        "dimensional_scaling_critic": "normalized_state_t = rank_or_scale_adjust(raw_input_t); scale pollution should fall after normalization",
        "stochastic_process_modeler": "state_{t+1} = rho * state_t + shock_{t+1}; rho must be large enough to survive costs",
        "microstructure_cost_analyst": "net_alpha = gross_signal - turnover * cost_rate; durable pressure should lower turnover drag",
        "statistical_falsification_agent": "accepted_revision iff out_of_sample_net_metrics improve and falsification tests do not fail",
    }
    return relations.get(role, "candidate_state_t maps to future long-side evidence under current information set")


def result_for_task(task: dict[str, Any], taskbook: dict[str, Any]) -> dict[str, Any]:
    role = task.get("agent_role") or "unknown_agent"
    task_id = task.get("task_id") or f"agent_{role}"
    report_id = taskbook.get("report_id")
    shared = taskbook.get("shared_context") or {}
    failure = shared.get("primary_failure_signature") or "mechanism_unclear"
    mechanism_fit = shared.get("mechanism_fit") or "unknown"
    metrics = shared.get("key_metrics") or {}
    selected_tool = (task.get("allowed_tools") or ["statistical_inference"])[0]
    gross = metrics.get("long_side_annual_return")
    net = metrics.get("cost_adjusted_annual_return")
    law_id = f"{role}_law_001"
    expression_direction = (
        "Challenge the estimator state, then test expression-level persistence confirmation or smoothing under human approval."
        if role in {"symbolic_law_discovery", "stochastic_process_modeler", "microstructure_cost_analyst"}
        else "Use expression-level normalization and falsification checks before approving any revision path."
    )
    return {
        "result_version": RESULT_VERSION,
        "status": "final",
        "report_id": report_id,
        "task_id": task_id,
        "agent_role": role,
        "producer": "local_mock_agentic_contract",
        "research_depth": "medium",
        "proposal_generation_mode": "agentic_contract_mock",
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "public_derivation_record": {
            "research_question": task.get("research_question") or "What should this agent test?",
            "assumptions": [
                {
                    "assumption": "Step4/5/6 artifacts are the only evidence inputs for this mock agent contract run.",
                    "status": "hypothesis",
                    "why_needed": "The local mock executor does not rerun factors or inspect clean data.",
                    "how_to_falsify": "Invalidate the result if packet identity, metrics, or provenance are blocked.",
                }
            ],
            "mathematical_objects": [
                {
                    "name": "factor_value",
                    "meaning": "The current Step3B factor signal evaluated by Step4/5.",
                    "unit_or_dimension": "dimensionless_or_unknown",
                    "information_set": "factor timestamp and historical observations only",
                },
                {
                    "name": "net_long_side_evidence",
                    "meaning": "Cost-adjusted long-side metric signature used by Step6 admission gates.",
                    "unit_or_dimension": "annualized_return_or_ratio",
                    "information_set": "post-evaluation evidence artifact",
                },
            ],
            "selected_tools": [
                {
                    "tool": selected_tool,
                    "why_selected": "This tool matches the agent role and can produce falsifiable implications from the packet.",
                    "what_it_can_answer": "It can define a public hypothesis and metric signature to test later.",
                    "what_it_cannot_answer": "It cannot prove alpha, approve code changes, or modify canonical artifacts.",
                }
            ],
            "formula_claims": [
                {
                    "claim": "The factor can be treated as an estimator of a latent state only if the implied state survives the observed cost and stability tests.",
                    "formula_or_relation": relation_for_role(role),
                    "status": "hypothesis",
                    "derivation_summary": f"Mock {role} maps the packet failure signature {failure} and mechanism fit {mechanism_fit} into a testable relation.",
                }
            ],
            "derivation_steps_summary": [
                {
                    "step_no": 1,
                    "statement": "Read packet metrics and mechanism claims without rerunning data.",
                    "depends_on": [],
                },
                {
                    "step_no": 2,
                    "statement": "Translate the role-specific mathematical relation into metric expectations.",
                    "depends_on": [1],
                },
            ],
            "limiting_cases": [
                "If turnover cost dominates gross evidence, a short-lived state is insufficient.",
                "If gross evidence also disappears, the mechanism challenge should reject the direction.",
            ],
            "falsification_tests": [
                "Cost-adjusted long-side Sharpe remains negative after the expression-level hypothesis is tested.",
                "Long-side gross signal disappears when persistence or normalization is applied.",
            ],
            "kill_criteria": [
                "High-score long side remains non-positive.",
                "Improvement appears only in diagnostic spread metrics, not long-side admission metrics.",
            ],
            "overclaim_guard": "This mock result validates the agentic artifact contract only and cannot justify promotion or code mutation.",
        },
        "candidate_revision_laws": [
            {
                "law_id": law_id,
                "revision_type": "expression_revision" if failure in {"cost_too_high", "non_monotonic"} else "mechanism_challenge",
                "law_statement": "A valid revision must improve the mathematical estimator state before any code path is considered.",
                "expression_change_direction": expression_direction,
                "expected_metric_change": [
                    "Cost-adjusted long-side return should improve if the estimator state is persistent.",
                    "Turnover or estimator variance should not worsen materially.",
                ],
                "falsification_tests": [
                    "Net long-side Sharpe remains negative after the expression hypothesis is tested.",
                    "Gross signal disappears after applying the proposed expression discipline.",
                ],
                "kill_criteria": [
                    "High-score long side remains non-positive.",
                    "Any apparent improvement depends only on diagnostic spread behavior.",
                ],
                "why_not_portfolio_fix": "The law targets the factor expression and estimator state, not trading wrapper behavior.",
            }
        ],
        "recommended_branch_templates": [],
        "blocked_reason": None,
        "mock_observed_context": {
            "gross_long_side_annual_return": gross,
            "cost_adjusted_annual_return": net,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    taskbook_path = council_dir / f"agentic_taskbook__{rid}.json"
    if not taskbook_path.exists():
        print(TOKEN_TASKBOOK_MISSING + ": " + json.dumps({"taskbook_path": str(taskbook_path)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    taskbook = load_json(taskbook_path)
    out_dir = council_dir / "agent_results"
    paths = []
    for task in taskbook.get("agent_tasks") or []:
        if not isinstance(task, dict):
            continue
        result = result_for_task(task, taskbook)
        task_id = result["task_id"]
        path = out_dir / f"agent_result__{rid}__{task_id}.json"
        write_json(path, result)
        paths.append(str(path))
    print(json.dumps({"status": "written", "report_id": rid, "agent_result_paths": paths, "agent_result_count": len(paths)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
