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

from factor_factory.research_conjecture import (
    PROTOCOL_VERSION,
    load_json as load_protocol_json,
    research_protocol_paths,
    validate_protocol_bundle,
)
from factor_factory.measurement_program import (
    build_measurement_program_binding,
    validate_measurement_program,
)

OBJ = FF / "objects"
TASKBOOK_VERSION = "factorforge_agentic_revision_council_taskbook_v1"
RUNTIME_POLICY_VERSION = "factorforge_runtime_dispatch_policy_v1"
RUNTIME_VALUES = {"codex", "openclaw", "manual_file", "unknown"}
TOKEN_PACKET_MISSING = "BLOCK_REVISION_COUNCIL_PACKET_MISSING"
TOKEN_MEASUREMENT_PROGRAM_INVALID = "BLOCK_FACTORFORGE_MEASUREMENT_PROGRAM_INVALID"


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


def safe_token(value: Any) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "route"))
    return "_".join(part for part in text.split("_") if part)[:72] or "route"


def agent_task(
    role: str,
    question: str,
    tools: list[str],
    report_id: str,
    *,
    route: dict[str, Any],
    visible_context: dict[str, Any],
) -> dict[str, Any]:
    route_id = str(route.get("route_id") or role)
    favored_visible = route.get("favored_thesis_visible") is True
    measurement_program = visible_context.get(
        "mechanism_conditioned_measurement_program"
    )
    measurement_program_binding = build_measurement_program_binding(
        measurement_program
    )
    return {
        "agent_role": role,
        "task_id": f"route_{safe_token(route_id)}",
        "research_protocol_version": PROTOCOL_VERSION,
        "route_id": route_id,
        "route_family": route.get("route_family"),
        "route_status_at_dispatch": route.get("status") or "open",
        "route_fingerprint": route.get("route_fingerprint"),
        "blind_context_hash": route.get("blind_context_hash"),
        "expected_agent_identifier": route.get("agent_identity"),
        "blind_context_policy": {
            "blind_phase": not favored_visible,
            "favored_thesis_visible": favored_visible,
            "independence_attestation_required": True,
            "withheld_context_keys": (
                []
                if favored_visible
                else [
                    "main_agent_mechanism_memo_ref",
                    "main_agent_math_hypothesis",
                    "final_revision_strategy",
                    "favored_route_id",
                ]
            ),
        },
        "visible_context": visible_context,
        "measurement_program_binding": measurement_program_binding,
        "research_question": question
        + (
            " Work independently from formula facts and executed evidence; the favored thesis is intentionally withheld."
            if not favored_visible
            else " Critique the main agent mechanism memo and any prior executable revision outcome."
        )
        + " Do not reconstruct from a generic family label or repeat a falsified revision rule.",
        "main_agent_mechanism_memo_ref": (
            f"objects/research_iteration_master/main_agent_mechanism_memo__{report_id}.json"
            if favored_visible
            else None
        ),
        "proof_obligation_ids": route.get("proof_obligation_ids") or [],
        "exact_gap": route.get("exact_gap"),
        "reopen_only_if": route.get("reopen_only_if") or [],
        "required_outputs": [
            "approach_route",
            "proof_obligation_updates",
            "counterexamples",
            "route_status",
            "reopen_criteria",
            "independence_attestation",
            "economic_hypothesis_review",
            "math_mechanism_derivation",
            "measurement_program_binding",
            "model_to_formula_translation",
            "public_derivation_record",
            "candidate_revision_laws",
            "main_agent_memo_agreement",
            "model_selection_critique",
            "component_mapping_critique",
            "payer_derivation_critique",
            "evidence_contradiction_review",
            "prior_revision_outcome_review",
            "repeated_revision_guard",
            "revision_or_kill_recommendation",
            "profit_payer_derivation",
            "model_mutation_proposal",
            "critique_of_formula_specific_derivation",
            "proposed_alternative_mathematical_object_mapping",
            "expected_metric_signature",
            "falsification_tests",
            "kill_criteria",
            "terminal_scope_and_stop_authority_if_recommending_stop",
            "overclaim_guard",
        ],
        "allowed_tools": tools,
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


def default_routes(failure_signature: str | None) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = [
        {
            "route_id": "economic_game_payer",
            "route_family": "economic_game",
            "status": "open",
            "research_question": "Which constrained participant transfers the payoff, and what observation would distinguish that transfer from a story?",
            "core_hypothesis": "A repeatable participant constraint creates a falsifiable transfer of PnL.",
            "distinct_from_other_routes": "Starts from actors, constraints, and payoff transfer rather than formula geometry.",
            "proof_obligation_ids": ["economic_game", "payer"],
            "exact_gap": "payer and persistence identification",
            "favored_thesis_visible": False,
        },
        {
            "route_id": "mechanism_object_measurement",
            "route_family": "mechanism_object_measurement",
            "status": "open",
            "research_question": "What mechanism-specific mathematical object is identifiable from the exact formula, and what observation equation separates it from measurement noise?",
            "core_hypothesis": "The expression estimates a selected mathematical object rather than restating raw fields.",
            "distinct_from_other_routes": "Starts from the selected mechanism, identifiability, observation mapping, and measurement error.",
            "proof_obligation_ids": ["measurement_validity", "component_ablation"],
            "exact_gap": "mathematical-object identifiability and formula-component mapping",
            "favored_thesis_visible": False,
        },
        {
            "route_id": "null_alias_counterexample",
            "route_family": "null_alias_counterexample",
            "status": "open",
            "research_question": "What null, alias, boundary case, or counterexample can reproduce the observed metrics without the preferred mechanism?",
            "core_hypothesis": "The observed signal may be an alias, implementation artifact, or unstable sample relation.",
            "distinct_from_other_routes": "Attempts to eliminate the preferred explanation rather than repair it.",
            "proof_obligation_ids": ["null_alias", "information_set"],
            "exact_gap": "strongest discriminating counterexample",
            "favored_thesis_visible": False,
        },
        {
            "route_id": "symbolic_law",
            "route_family": "symbolic_law",
            "status": "open",
            "research_question": "Which invariant, limiting case, or symbolic relation survives exact formula decomposition?",
            "core_hypothesis": "A low-complexity relation can derive a testable estimator law.",
            "distinct_from_other_routes": "Starts from mathematical structure and limiting cases.",
            "proof_obligation_ids": ["math_derivation", "implementation_parity"],
            "exact_gap": "formula-mappable derivation rather than decorative mathematics",
            "favored_thesis_visible": True,
        },
    ]
    conditional = {
        "cost_too_high": (
            "microstructure_cost",
            "Can the exact gross edge survive turnover, impact, capacity, and execution timing?",
            ["cost_capacity"],
        ),
        "unstable_regime": (
            "regime_transition",
            "Which state transition or regime boundary explains instability without outcome-driven segmentation?",
            ["regime", "state_transition"],
        ),
        "implementation_suspect": (
            "implementation_identity",
            "Do formula identity, information timing, and implementation parity invalidate the evidence?",
            ["implementation_parity", "information_set"],
        ),
        "same_factor_identity_mismatch": (
            "implementation_identity",
            "Do factor identity and implementation lineage invalidate the claimed comparison?",
            ["implementation_parity", "information_set"],
        ),
    }
    family, question, obligation_ids = conditional.get(
        str(failure_signature or ""),
        (
            "empirical_identification",
            "Which pre-registered test best distinguishes the competing mechanisms under fixed IS and sealed OOS?",
            ["mechanism_discrimination", "regime"],
        ),
    )
    routes.append(
        {
            "route_id": family,
            "route_family": family,
            "status": "open",
            "research_question": question,
            "core_hypothesis": "The preferred route must survive a route-specific executable test.",
            "distinct_from_other_routes": "Targets the dominant observed failure signature.",
            "proof_obligation_ids": obligation_ids,
            "exact_gap": "route-specific executed evidence",
            "favored_thesis_visible": True,
        }
    )
    return routes


def route_role_and_tools(route_family: str) -> tuple[str, list[str]]:
    mapping = {
        "economic_game": (
            "economic_mechanism_agent",
            ["microstructure_reasoning", "causal_identification", "institutional_analysis"],
        ),
        "mechanism_object_measurement": (
            "mechanism_measurement_modeler",
            ["open_math_tool_search", "observation_equation", "statistical_inference"],
        ),
        "latent_state_measurement": (
            "mechanism_measurement_modeler",
            ["open_math_tool_search", "observation_equation", "statistical_inference"],
        ),
        "null_alias_counterexample": (
            "statistical_falsification_agent",
            ["statistical_inference", "causal_identification", "counterexample_search"],
        ),
        "symbolic_law": (
            "symbolic_law_discovery",
            ["open_math_tool_search", "limiting_case_analysis", "counterexample_search"],
        ),
        "microstructure_cost": (
            "microstructure_cost_analyst",
            ["microstructure_reasoning", "statistical_inference", "capacity_modeling"],
        ),
        "regime_transition": (
            "regime_transition_critic",
            ["stochastic_process_modeling", "change_point_analysis", "statistical_inference"],
        ),
        "implementation_identity": (
            "implementation_identity_auditor",
            ["formula_ir", "information_set_audit", "implementation_parity"],
        ),
        "empirical_identification": (
            "empirical_identification_agent",
            ["statistical_inference", "causal_identification", "robustness_design"],
        ),
        "data_feasibility": (
            "data_feasibility_agent",
            ["data_catalog", "information_set_audit", "coverage_analysis"],
        ),
    }
    return mapping.get(
        route_family,
        (
            f"{safe_token(route_family)}_investigator",
            ["statistical_inference", "counterexample_search"],
        ),
    )


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
    parser.add_argument(
        "--research-protocol",
        default="required",
        choices=["required", "optional", "off"],
    )
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

    protocol_gate: dict[str, Any] = {
        "mode": args.research_protocol,
        "protocol_version": PROTOCOL_VERSION,
        "status": "off" if args.research_protocol == "off" else "missing",
        "block_reasons": [],
    }
    routes: list[dict[str, Any]] = []
    protocol_artifacts: dict[str, str] = {}
    if args.research_protocol != "off":
        paths = research_protocol_paths(FF, rid)
        protocol_artifacts = {key: relpath(path) for key, path in paths.items()}
        conjecture_path = paths["conjecture"]
        approaches_path = paths["approaches"]
        if conjecture_path.exists() and approaches_path.exists():
            registry = load_protocol_json(approaches_path)
            protocol_report = validate_protocol_bundle(
                root=FF,
                report_id=rid,
                stage="pre_council",
            )
            protocol_reasons = protocol_report.get("block_reasons") or []
            protocol_gate["block_reasons"] = list(dict.fromkeys(protocol_reasons))
            protocol_gate["status"] = "valid" if not protocol_reasons else "invalid"
            if not protocol_reasons:
                routes = [
                    route
                    for route in registry.get("routes") or []
                    if isinstance(route, dict)
                    and route.get("status")
                    in {"open", "active", "supported", "inconclusive"}
                ][:8]
        if args.research_protocol == "required" and protocol_gate["status"] != "valid":
            print(
                "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_PROTOCOL_REQUIRED: "
                + json.dumps(
                    {
                        "report_id": rid,
                        "protocol_gate": protocol_gate,
                        "artifact_paths": protocol_artifacts,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            raise SystemExit(1)

    measurement_program = packet.get("mechanism_conditioned_measurement_program")
    declared_node_ids = {
        str(node_id)
        for component in (
            ((measurement_program or {}).get("implementation") or {}).get(
                "components"
            )
            or []
        )
        if isinstance(component, dict)
        for node_id in (component.get("knowledge_node_ids") or [])
        if str(node_id).strip()
    }
    measurement_program_failures = validate_measurement_program(
        measurement_program,
        available_knowledge_node_ids=declared_node_ids,
        require_web_executable=False,
    )
    measurement_program_binding = build_measurement_program_binding(
        measurement_program
    )
    if measurement_program_failures or not measurement_program_binding:
        print(
            TOKEN_MEASUREMENT_PROGRAM_INVALID
            + ": "
            + json.dumps(
                {
                    "report_id": rid,
                    "failures": measurement_program_failures
                    or ["measurement_program_binding_missing"],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)

    failure_signature = (
        revision.get("primary_failure_signature")
        if isinstance(revision, dict)
        else None
    )
    if not routes:
        routes = default_routes(failure_signature)

    fact_context = {
        "decision": (iteration.get("research_judgment") or {}).get("decision"),
        "mechanism_fit": mechanism.get("mechanism_fit") if isinstance(mechanism, dict) else None,
        "primary_failure_signature": failure_signature,
        "mechanism_conditioned_measurement_program": packet.get("mechanism_conditioned_measurement_program") or {},
        "legacy_mechanism_math_contract": (
            packet.get("legacy_mechanism_math_contract")
            or packet.get("mechanism_math_contract")
            or {}
        ),
        "formula_specific_derivation": packet.get("formula_specific_derivation") or {},
        "mechanism_formula_consistency": packet.get("mechanism_formula_consistency") or {},
        "prior_revision_memory": packet.get("prior_revision_memory") or {},
        "supplemental_research_context": packet.get("supplemental_research_context") or {},
        "loop_research_brief_ref": brief_ref,
        "key_metrics": packet.get("metrics") or {},
        "chart_evidence": packet.get("chart_evidence") or {},
    }
    tasks: list[dict[str, Any]] = []
    for route in routes:
        family = str(route.get("route_family") or "unclassified")
        role, tools = route_role_and_tools(family)
        tasks.append(
            agent_task(
                role,
                str(route.get("research_question") or "Evaluate this research route."),
                tools,
                rid,
                route=route,
                visible_context={
                    **fact_context,
                    "route_contract": {
                        "route_id": route.get("route_id"),
                        "route_family": family,
                        "core_hypothesis": route.get("core_hypothesis"),
                        "distinct_from_other_routes": route.get(
                            "distinct_from_other_routes"
                        ),
                        "exact_gap": route.get("exact_gap"),
                    },
                },
            )
        )
    taskbook = {
        "taskbook_version": TASKBOOK_VERSION,
        "report_id": rid,
        "factor_id": iteration.get("factor_id") or rid,
        "created_at_utc": utc_now(),
        "source_packet_path": relpath(packet_path),
        "source_step6_iteration_path": relpath(iteration_path),
        "council_mode": "agentic",
        "executor": args.executor,
        "research_protocol_version": PROTOCOL_VERSION,
        "research_protocol_gate": protocol_gate,
        "research_protocol_artifacts": protocol_artifacts,
        "route_selection_policy": {
            "selection_mode": (
                "approach_registry"
                if protocol_gate.get("status") == "valid"
                else "contextual_default_routes"
            ),
            "dynamic_by_research_gap": True,
            "route_family_is_research_identity": True,
            "early_independence_required": True,
            "majority_vote_forbidden": True,
        },
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
            **fact_context,
            "main_agent_mechanism_memo_ref": packet.get("main_agent_mechanism_memo_ref"),
            "main_agent_formula_component_map": packet.get("main_agent_formula_component_map") or [],
            "main_agent_math_hypothesis": packet.get("main_agent_math_hypothesis") or {},
            "main_agent_evidence_comparison": packet.get("main_agent_evidence_comparison") or {},
            "council_required_critiques": packet.get("council_required_critiques") or [],
        },
        "agent_tasks": tasks,
    }
    out = council_dir / f"agentic_taskbook__{rid}.json"
    write_json(out, taskbook)
    print(json.dumps({"status": "written", "path": str(out), "report_id": rid, "agent_task_count": len(tasks)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
