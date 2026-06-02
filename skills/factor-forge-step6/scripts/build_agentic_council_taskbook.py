#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OBJ = FF / "objects"
TASKBOOK_VERSION = "factorforge_agentic_revision_council_taskbook_v1"
RUNTIME_POLICY_VERSION = "factorforge_runtime_dispatch_policy_v1"
RUNTIME_VALUES = {"codex", "openclaw", "manual_file", "unknown"}
TOKEN_PACKET_MISSING = "BLOCK_REVISION_COUNCIL_PACKET_MISSING"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def relpath(path: Path) -> str:
    try:
        return str(path.relative_to(FF))
    except ValueError:
        return str(path)


def nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur


def component_review_requirements(packet: dict[str, Any]) -> list[dict[str, Any]]:
    component_map = packet.get("main_agent_formula_component_map") or []
    requirements: list[dict[str, Any]] = []
    if isinstance(component_map, list):
        for idx, item in enumerate(component_map):
            if not isinstance(item, dict):
                continue
            component = item.get("formula_component") or item.get("component") or item.get("name") or f"component_{idx}"
            requirements.append(
                {
                    "formula_component": component,
                    "required_questions": [
                        "What information about the market state does this component imply?",
                        "Which economic hypothesis or payer mechanism does this component test?",
                        "Which mathematical object, latent state, or estimator does this component represent?",
                        "Which metric signature should improve if this component is correct?",
                        "What falsification would force revision or removal of this component?",
                    ],
                    "source_mapping": item,
                }
            )
    if requirements:
        return requirements
    return [
        {
            "formula_component": "whole_formula",
            "required_questions": [
                "Decompose the composite expression into economically meaningful terms before proposing a revision.",
                "State the formula-implied information that is not already explicit in the main-agent memo.",
                "Map each proposed term to a mathematical object and falsification metric.",
            ],
            "source_mapping": {},
        }
    ]


def agent_task(role: str, question: str, tools: list[str], report_id: str, component_requirements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "agent_role": role,
        "task_id": f"agent_{role}",
        "research_question": question + " Critique the main agent mechanism memo and any prior executable revision outcome. Do not reconstruct from a generic family label or repeat a falsified revision rule.",
        "main_agent_mechanism_memo_ref": f"objects/research_iteration_master/main_agent_mechanism_memo__{report_id}.json",
        "required_outputs": [
            "economic_hypothesis_review",
            "math_mechanism_derivation",
            "model_to_formula_translation",
            "public_derivation_record",
            "candidate_revision_laws",
            "main_agent_memo_agreement",
            "model_selection_critique",
            "component_mapping_critique",
            "component_level_taskbook_response",
            "payer_derivation_critique",
            "evidence_contradiction_review",
            "prior_revision_outcome_review",
            "repeated_revision_guard",
            "revision_or_kill_recommendation",
            "profit_payer_derivation",
            "model_mutation_proposal",
            "critique_of_formula_specific_derivation",
            "proposed_alternative_latent_state_mapping",
            "expected_metric_signature",
            "falsification_tests",
            "kill_criteria",
            "terminal_scope_and_stop_authority_if_recommending_stop",
            "overclaim_guard",
        ],
        "allowed_tools": tools,
        "component_review_requirements": component_requirements,
        "forbidden_changes": [
            "portfolio expression",
            "short-leg adoption",
            "long-short adoption",
            "decile trading",
            "shared clean data mutation",
            "repeat a falsified executable revision rule",
        ],
        "write_scope": f"objects/research_iteration_master/revision_council/{report_id}/agent_results/",
    }


def build_runtime_dispatch_policy(runtime: str, provider: str | None, model: str | None) -> dict[str, Any]:
    if runtime not in RUNTIME_VALUES:
        raise ValueError(f"unsupported runtime dispatch policy: {runtime}")
    provider_override = None
    model_override = None
    if provider:
        provider_override = {"provider": provider, "reason": "explicit_user_request"}
    if model:
        model_override = {"model": model, "reason": "explicit_user_request"}
    return {
        "policy_version": RUNTIME_POLICY_VERSION,
        "runtime": runtime,
        "subagent_dispatcher": "main_agent",
        "default_model_policy": "inherit_main_model",
        "provider_override_policy": "only_if_user_explicitly_requests",
        "provider_required_by_factor_forge": False,
        "external_provider_selection_allowed": bool(provider_override),
        "manual_provider_override": provider_override,
        "model_override": model_override,
        "runtime_notes": [
            "Codex runtime may spawn Codex subagents directly.",
            "OpenClaw runtime may spawn OpenClaw subagents with the main model/provider by default.",
            "Factor Forge validates result artifacts, not LLM provider identity.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--executor", default="local_mock", choices=["local_mock", "dispatch_manifest"])
    parser.add_argument("--runtime-dispatch", default="unknown", choices=sorted(RUNTIME_VALUES))
    parser.add_argument("--subagent-provider")
    parser.add_argument("--subagent-model")
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    packet_path = council_dir / f"revision_council_packet__{rid}.json"
    iteration_path = OBJ / "research_iteration_master" / f"research_iteration_master__{rid}.json"
    if not packet_path.exists():
        print(TOKEN_PACKET_MISSING + ": " + json.dumps({"packet_path": str(packet_path)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    packet = load_json(packet_path)
    iteration = load_json(iteration_path) if iteration_path.exists() else {}
    memo = nested(iteration, "research_judgment", "research_memo")
    if not isinstance(memo, dict):
        memo = {}
    revision = nested(packet, "research_memo", "revision_strategy")
    mechanism = nested(packet, "research_memo", "mechanism_analysis")
    brief_ref = (packet.get("loop_research_brief") or {}).get("reference") or iteration.get("loop_research_brief") or {}
    component_requirements = component_review_requirements(packet)

    common_tools = [
        "dimensional_analysis",
        "stochastic_process_modeling",
        "statistical_inference",
        "linear_algebra",
        "functional_analysis",
        "fourier_analysis",
        "microstructure_reasoning",
    ]
    tasks = [
        agent_task(
            "symbolic_law_discovery",
            "What symbolic or mathematical law should be challenged before any expression revision is approved?",
            common_tools,
            rid,
            component_requirements,
        ),
        agent_task(
            "dimensional_scaling_critic",
            "Do formula units, scale invariance, and natural time scale support the claimed factor state?",
            ["dimensional_analysis", "linear_algebra", "statistical_inference"],
            rid,
            component_requirements,
        ),
        agent_task(
            "stochastic_process_modeler",
            "What latent stochastic state and target functional could this expression estimate?",
            ["stochastic_process_modeling", "functional_analysis", "statistical_inference"],
            rid,
            component_requirements,
        ),
        agent_task(
            "microstructure_cost_analyst",
            "Why might gross signal exist while cost-adjusted long-side alpha fails?",
            ["microstructure_reasoning", "statistical_inference", "stochastic_process_modeling"],
            rid,
            component_requirements,
        ),
        agent_task(
            "statistical_falsification_agent",
            "Which falsification, stability, regime, and overfit tests should kill or preserve this direction?",
            ["statistical_inference", "fourier_analysis", "linear_algebra"],
            rid,
            component_requirements,
        ),
    ]
    taskbook = {
        "taskbook_version": TASKBOOK_VERSION,
        "report_id": rid,
        "factor_id": iteration.get("factor_id") or rid,
        "created_at_utc": utc_now(),
        "source_packet_path": relpath(packet_path),
        "source_step6_iteration_path": relpath(iteration_path),
        "council_mode": "agentic",
        "executor": args.executor,
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval_required": True,
        "runtime_dispatch_policy": build_runtime_dispatch_policy(
            args.runtime_dispatch,
            args.subagent_provider,
            args.subagent_model,
        ),
        "forbidden_write_targets": [
            f"objects/handoff/handoff_to_step3b__{rid}.json",
            f"generated_code/{rid}/",
            f"objects/factor_library_official/factor_record__{rid}.json",
            "data/clean/",
        ],
        "shared_context": {
            "decision": (iteration.get("research_judgment") or {}).get("decision"),
            "mechanism_fit": mechanism.get("mechanism_fit") if isinstance(mechanism, dict) else None,
            "primary_failure_signature": revision.get("primary_failure_signature") if isinstance(revision, dict) else None,
            "mechanism_math_contract": packet.get("mechanism_math_contract") or {},
            "formula_specific_derivation": packet.get("formula_specific_derivation") or {},
            "mechanism_formula_consistency": packet.get("mechanism_formula_consistency") or {},
            "main_agent_mechanism_memo_ref": packet.get("main_agent_mechanism_memo_ref"),
            "main_agent_formula_component_map": packet.get("main_agent_formula_component_map") or [],
            "component_review_requirements": component_requirements,
            "main_agent_math_hypothesis": packet.get("main_agent_math_hypothesis") or {},
            "main_agent_evidence_comparison": packet.get("main_agent_evidence_comparison") or {},
            "prior_revision_memory": packet.get("prior_revision_memory") or {},
            "council_required_critiques": packet.get("council_required_critiques") or [],
            "supplemental_research_context": packet.get("supplemental_research_context") or {},
            "loop_research_brief_ref": brief_ref,
            "key_metrics": packet.get("metrics") or {},
            "chart_evidence": packet.get("chart_evidence") or {},
        },
        "agent_tasks": tasks,
    }
    out = council_dir / f"agentic_taskbook__{rid}.json"
    write_json(out, taskbook)
    print(json.dumps({"status": "written", "path": str(out), "report_id": rid, "agent_task_count": len(tasks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
