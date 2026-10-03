"""Role-specific Council disclosure, shared by task production and dispatch."""
from __future__ import annotations

from typing import Any


TOKEN_BLIND_CONTEXT_LEAK = "BLOCK_AGENTIC_COUNCIL_DISPATCH_BLIND_CONTEXT_LEAK"
BLIND_VISIBLE_CONTEXT_KEYS = frozenset({
    "factor_formula", "implementation_mode", "factor_family",
    "mechanism_conditioned_measurement_program", "key_metrics", "chart_evidence",
    "evo_v2", "route_contract",
})
WITHHELD_CONTEXT_KEYS = frozenset({
    "decision", "mechanism_fit", "primary_failure_signature",
    "formula_specific_derivation", "mechanism_formula_consistency",
    "legacy_mechanism_math_contract", "mechanism_math_contract",
    "main_agent_mechanism_memo_ref", "main_agent_mechanism_memo",
    "main_agent_math_hypothesis", "main_agent_formula_component_map",
    "main_agent_evidence_comparison", "main_math_context",
    "final_revision_strategy", "favored_route_id", "favored_thesis",
    "preferred_thesis", "root_thesis", "root_judgment",
    "prior_revision_memory", "supplemental_research_context",
    "loop_research_brief", "loop_research_brief_ref", "council_required_critiques",
    "research_memo", "research_judgment", "source_packet_path",
    "source_taskbook_path", "source_step6_iteration_path", "source_paths",
    "selected_model_authority", "main_agent_selected_model",
})


def _has_value(value: Any) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def blind_context_leak_keys(value: Any, prefix: str = "") -> list[str]:
    """Reject structured root judgments and pointers, including nested copies.

    The exact author-disclosed measurement program remains public and bound;
    an explicit main-agent/preferred-thesis authority marker remains forbidden.
    This is a disclosure contract, not a natural-language secrecy classifier.
    """
    leaked: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in WITHHELD_CONTEXT_KEYS and _has_value(item):
                leaked.append(path)
            elif key == "selected_model_source" and str(item or "").strip().lower() in {
                "main_agent", "main_agent_memo", "preferred_thesis",
            }:
                leaked.append(path)
            else:
                leaked.extend(blind_context_leak_keys(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaked.extend(blind_context_leak_keys(item, f"{prefix}[{index}]"))
    return leaked


def blind_visible_context_leak_keys(context: dict[str, Any]) -> list[str]:
    unexpected = [key for key, value in context.items()
                  if key not in BLIND_VISIBLE_CONTEXT_KEYS and _has_value(value)]
    return sorted(set(unexpected + blind_context_leak_keys(context)))


def context_for_route(context: dict[str, Any], *, favored_visible: bool) -> dict[str, Any]:
    if favored_visible:
        return dict(context)
    return {key: value for key, value in context.items() if key in BLIND_VISIBLE_CONTEXT_KEYS}


def blind_task_packet_leak_keys(packet: dict[str, Any]) -> list[str]:
    context = packet.get("shared_context") or {}
    if not isinstance(context, dict):
        return ["shared_context"]
    return sorted(set(blind_context_leak_keys(packet) + [
        f"shared_context.{key}" for key in blind_visible_context_leak_keys(context)
    ]))
