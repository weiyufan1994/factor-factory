from __future__ import annotations

import re
from typing import Any

from .guards import FORBIDDEN_TEXT_TOKEN, scan_forbidden_text
from .schema import (
    CONFIDENCE_VALUES,
    COUNCIL_AGENT_ROLES,
    COUNCIL_PROPOSAL_VERSION,
    FAILURE_SIGNATURES,
    PROPOSAL_REQUIRED_FIELDS,
    PRODUCER_VALUES,
    PROPOSAL_GENERATION_MODE_VALUES,
    REQUIRED_GUARDS,
    RESEARCH_DEPTH_VALUES,
    RETURN_SOURCE_VALUES,
    REVISION_TYPES,
    SYMBOLIC_MATH_TOOLS,
)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _nonempty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _nonempty_object_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)


def _has_nonempty_text(obj: Any, key: str) -> bool:
    return isinstance(obj, dict) and _nonempty_str(obj.get(key))


def _nonempty_str_list(value: Any, *, min_count: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len([item for item in value if _nonempty_str(item)]) >= min_count
        and all(isinstance(item, str) for item in value)
    )


def _normalized_words(value: Any) -> str:
    return " ".join(re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", str(value or "").lower()))


VALID_REVISION_MODEL_LAYERS = {
    "economic_hypothesis",
    "primary_mechanism_model",
    "stochastic_projection",
    "observable_estimator",
    "implementation_contract",
}
VALID_RESEARCH_EQUATION_REVISION_TARGETS = {
    "assumptions",
    "latent_state",
    "observable_estimator",
    "price_process_projection",
    "implementation_contract",
    "trading_cost",
    "drawdown_geometry",
}
GENERIC_RESEARCH_EQUATION_REVISION_TEXT = {
    "improve the model",
    "improve model",
    "metrics improve",
    "test metrics",
    "make it better",
    "fix the model",
}
REVISION_TARGET_EVIDENCE_TERMS = {
    "assumptions": {"assumption", "assumptions", "validity", "scope", "regime"},
    "latent_state": {"latent", "state"},
    "observable_estimator": {"observable", "estimator", "measurement", "equation", "detector", "rank_ic"},
    "price_process_projection": {"drift", "diffusion", "jump", "friction", "regime_transition", "projection"},
    "implementation_contract": {"implementation", "contract", "direct_code", "operator", "hybrid"},
    "trading_cost": {"turnover", "cost", "cogs", "slippage", "fee"},
    "drawdown_geometry": {"drawdown", "recovery", "area", "pain"},
}

VALID_FORMULA_IMPLIED_IMPLICATION_CLASSES = {
    "bug",
    "data_artifact",
    "implementation_artifact",
    "benign_model_implication",
    "tradable_anomaly",
    "new_factor_seed",
}
DIRAC_REPORT_REQUIRED_SECTIONS = {
    "research_equation_or_soft_law",
    "formula_implied_information",
    "metric_anomaly_review",
    "model_linked_metric_signature",
    "stochastic_projection_consistency_check",
    "volatility_drag_review",
    "drawdown_recovery_area_review",
    "component_level_revision_axes",
    "direction_losing_transform_review",
    "dimensional_or_unit_consistency_review",
}
DIRAC_ANOMALY_CLASSES = {
    "bug",
    "data_artifact",
    "implementation_artifact",
    "direction_or_sign_error",
    "formula_measures_avoid_state",
    "tradable_anomaly",
    "new_factor_seed",
    "kill_signal",
    "under_specified",
}


def validate_dirac_research_report_contract(report: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not isinstance(report, dict):
        return ["BLOCK_DIRAC_RESEARCH_REPORT_NOT_OBJECT"]
    missing = sorted(section for section in DIRAC_REPORT_REQUIRED_SECTIONS if not report.get(section))
    if missing:
        reasons.append("BLOCK_DIRAC_RESEARCH_REPORT_SECTION_MISSING:" + ",".join(missing))
    info = report.get("formula_implied_information")
    if not _nonempty_object_list(info):
        reasons.append("BLOCK_DIRAC_FORMULA_IMPLIED_INFORMATION_MISSING")
    else:
        for idx, item in enumerate(info):
            required = [
                "formula_component",
                "observable",
                "implied_latent_state",
                "payer_or_constraint",
                "expected_sign",
                "falsification_metric",
            ]
            if any(not _has_nonempty_text(item, key) for key in required):
                reasons.append(f"BLOCK_DIRAC_FORMULA_IMPLIED_INFORMATION_MISSING:{idx}")
                continue
            latent = _normalized_words(item.get("implied_latent_state"))
            if latent in {"close", "volume", "vwap", "returns", "formula", "raw field", "raw fields"}:
                reasons.append(f"BLOCK_DIRAC_FORMULA_RAW_RESTATEMENT:{idx}")
    anomaly = report.get("metric_anomaly_review")
    if not isinstance(anomaly, dict):
        reasons.append("BLOCK_DIRAC_ANOMALY_CLASSIFICATION_MISSING")
    else:
        classifications = anomaly.get("classifications")
        if not isinstance(classifications, list) or not classifications:
            reasons.append("BLOCK_DIRAC_ANOMALY_CLASSIFICATION_MISSING")
        else:
            for item in classifications:
                if not isinstance(item, dict) or item.get("classification") not in DIRAC_ANOMALY_CLASSES:
                    reasons.append("BLOCK_DIRAC_ANOMALY_CLASSIFICATION_MISSING")
                    break
        signature = anomaly.get("positive_ic_negative_long_side")
        if signature is True and not any(
            isinstance(item, dict) and item.get("classification") in {"direction_or_sign_error", "formula_measures_avoid_state", "tradable_anomaly", "under_specified"}
            for item in classifications or []
        ):
            reasons.append("BLOCK_DIRAC_POSITIVE_IC_NEGATIVE_LONG_WITHOUT_ANOMALY")
    for section, token in [
        ("model_linked_metric_signature", "BLOCK_DIRAC_MODEL_LINKED_METRICS_MISSING"),
        ("stochastic_projection_consistency_check", "BLOCK_DIRAC_STOCHASTIC_PROJECTION_CHECK_MISSING"),
        ("volatility_drag_review", "BLOCK_DIRAC_VOLATILITY_DRAG_REVIEW_MISSING"),
        ("drawdown_recovery_area_review", "BLOCK_DIRAC_DRAWDOWN_RECOVERY_AREA_REVIEW_MISSING"),
    ]:
        if not isinstance(report.get(section), dict) or not report.get(section):
            reasons.append(token)
    return list(dict.fromkeys(reasons))


def validate_component_council_packet(packet: dict[str, Any], *, formula_text: str = "", metrics: dict[str, Any] | None = None) -> list[str]:
    reasons: list[str] = []
    if not isinstance(packet, dict):
        return ["BLOCK_COUNCIL_COMPONENT_PACKET_MISSING"]
    required = [
        "component_revision_axes",
        "component_ablation_plan",
        "direction_losing_transform_review",
        "dimensional_consistency_review",
        "latent_state_independence_review",
        "stochastic_projection_falsification",
        "branch_kill_criteria",
    ]
    missing = [key for key in required if key not in packet]
    if missing:
        reasons.append("BLOCK_COUNCIL_COMPONENT_PACKET_MISSING:" + ",".join(missing))
    text = str(formula_text or "").lower()
    if ("+" in text or "add(" in text or "weighted" in text) and not _nonempty_list(packet.get("component_ablation_plan")):
        reasons.append("BLOCK_COUNCIL_COMPONENT_ABLATION_MISSING")
    if "abs(" in text and "corr" in text and not _nonempty_dict(packet.get("direction_losing_transform_review")):
        reasons.append("BLOCK_COUNCIL_DIRECTION_LOSS_REVIEW_MISSING")
    horizons = []
    for func in re.finditer(r"\b(?:delay|delta|sum|mean|corr|correlation|adv|ts_rank)\s*\(([^)]*)\)", text):
        horizons.extend(int(item) for item in re.findall(r"\b([1-9][0-9]*)\b", func.group(1)))
    horizons.extend(int(item) for item in re.findall(r"\badv([1-9][0-9]*)\b", text))
    if horizons and (max(horizons) / max(1, min(horizons)) >= 5) and not packet.get("time_scale_consistency_review"):
        reasons.append("BLOCK_COUNCIL_TIME_SCALE_REVIEW_MISSING")
    metrics = metrics or {}
    if metrics.get("rank_ic_mean", 0) > 0 and metrics.get("long_side_annual_return", 0) < 0 and not packet.get("positive_ic_negative_long_branch"):
        reasons.append("BLOCK_COUNCIL_POSITIVE_IC_NEGATIVE_LONG_BRANCH_MISSING")
    return list(dict.fromkeys(reasons))


def _model_layer_attribution_present(proposal: dict[str, Any]) -> bool:
    layer = proposal.get("revision_model_layer") or proposal.get("revision_model_target")
    if layer in VALID_REVISION_MODEL_LAYERS:
        return True
    record = proposal.get("derivation_record") if isinstance(proposal.get("derivation_record"), dict) else {}
    if record.get("revision_model_layer") in VALID_REVISION_MODEL_LAYERS:
        return True
    for item in record.get("revision_hypotheses") or []:
        if isinstance(item, dict) and item.get("revision_model_layer") in VALID_REVISION_MODEL_LAYERS:
            return True
    for law in proposal.get("candidate_revision_laws") or []:
        if isinstance(law, dict) and law.get("revision_model_layer") in VALID_REVISION_MODEL_LAYERS:
            return True
    return False


def _validate_derivation_record(proposal: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    role = proposal.get("agent_role")
    record = proposal.get("derivation_record")
    if not _nonempty_dict(record):
        return ["BLOCK_REVISION_COUNCIL_DERIVATION_MISSING"]

    if not _has_nonempty_text(record, "research_question"):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_RESEARCH_QUESTION_MISSING")

    assumptions = record.get("assumptions")
    if not _nonempty_object_list(assumptions):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_ASSUMPTIONS_MISSING")
    else:
        for idx, item in enumerate(assumptions):
            if (
                not _has_nonempty_text(item, "assumption")
                or item.get("status") not in {"hypothesis", "observed", "imported", "rejected"}
                or not _has_nonempty_text(item, "why_needed")
                or not _has_nonempty_text(item, "how_to_falsify")
            ):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_ASSUMPTION_INVALID:{idx}")

    objects = record.get("mathematical_objects")
    if not _nonempty_object_list(objects):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_OBJECTS_MISSING")
    else:
        for idx, item in enumerate(objects):
            if (
                not _has_nonempty_text(item, "name")
                or not _has_nonempty_text(item, "meaning")
                or not _has_nonempty_text(item, "unit_or_dimension")
                or not _has_nonempty_text(item, "information_set")
            ):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_OBJECT_INVALID:{idx}")

    selected_tools = record.get("selected_tools")
    if not _nonempty_object_list(selected_tools):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_TOOLS_MISSING")
    else:
        for idx, item in enumerate(selected_tools):
            if (
                not _has_nonempty_text(item, "tool")
                or not _has_nonempty_text(item, "why_selected")
                or not _has_nonempty_text(item, "what_it_can_answer")
                or not _has_nonempty_text(item, "what_it_cannot_answer")
            ):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_TOOL_INVALID:{idx}")
            elif role == "symbolic_law_discovery" and item.get("tool") not in SYMBOLIC_MATH_TOOLS:
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_TOOL_INVALID:{idx}")
        if role == "symbolic_law_discovery":
            derivation_tool_names = {item.get("tool") for item in selected_tools if isinstance(item, dict)}
            legacy_tools = set(proposal.get("selected_math_tools") or [])
            if not legacy_tools.issubset(derivation_tool_names):
                reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_TOOL_MISMATCH")

    if "rejected_tools" not in record or not isinstance(record.get("rejected_tools"), list):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_REJECTED_TOOLS_MISSING")

    steps = record.get("derivation_steps")
    if not _nonempty_object_list(steps):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_STEPS_MISSING")
    else:
        formula_claim_terms = ("formula", "derive", "推导", "公式", "symbolic relation")
        for idx, item in enumerate(steps):
            if (
                not isinstance(item.get("step_no"), int)
                or not _has_nonempty_text(item, "statement")
                or not _has_nonempty_text(item, "justification")
                or not isinstance(item.get("depends_on"), list)
                or "formula" not in item
            ):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_STEP_INVALID:{idx}")
                continue
            claim_text = f"{item.get('statement', '')} {item.get('justification', '')}".lower()
            if any(term in claim_text for term in formula_claim_terms) and not _nonempty_str(item.get("formula")):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_FORMULA_MISSING:{idx}")

    implications = record.get("derived_implications")
    if not _nonempty_object_list(implications):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_IMPLICATIONS_MISSING")
    else:
        for idx, item in enumerate(implications):
            if not _has_nonempty_text(item, "claim") or not _nonempty_str_list(item.get("expected_metric_signature"), min_count=2):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_IMPLICATION_INVALID:{idx}")

    hypotheses = record.get("revision_hypotheses")
    if not _nonempty_object_list(hypotheses):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_REVISION_HYPOTHESES_MISSING")
    else:
        for idx, item in enumerate(hypotheses):
            if (
                not _has_nonempty_text(item, "hypothesis")
                or not _has_nonempty_text(item, "expression_direction")
                or not _nonempty_str_list(item.get("expected_metric_change"), min_count=2)
                or not _nonempty_str_list(item.get("falsification_tests"), min_count=2)
                or not _nonempty_str_list(item.get("kill_criteria"), min_count=2)
            ):
                reasons.append(f"BLOCK_REVISION_COUNCIL_DERIVATION_REVISION_HYPOTHESIS_INVALID:{idx}")

    confidence = record.get("confidence_and_limits")
    if not isinstance(confidence, dict) or confidence.get("mathematical_confidence") not in CONFIDENCE_VALUES or confidence.get("empirical_confidence") not in CONFIDENCE_VALUES or not isinstance(confidence.get("known_gaps"), list):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_CONFIDENCE_MISSING")
    elif not _has_nonempty_text(confidence, "overclaim_guard"):
        reasons.append("BLOCK_REVISION_COUNCIL_DERIVATION_OVERCLAIM_GUARD_MISSING")

    return reasons


def _validate_formula_implied_information_review(proposal: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    review = proposal.get("formula_implied_information_review")
    if review is None:
        return reasons
    if not isinstance(review, dict):
        return ["BLOCK_COUNCIL_UNCLASSIFIED_UNEXPECTED_IMPLICATION"]
    implications = review.get("unexpected_implications") or []
    if not isinstance(implications, list):
        return ["BLOCK_COUNCIL_UNCLASSIFIED_UNEXPECTED_IMPLICATION"]
    for item in implications:
        if not isinstance(item, dict):
            reasons.append("BLOCK_COUNCIL_UNCLASSIFIED_UNEXPECTED_IMPLICATION")
            continue
        classification = item.get("classification")
        if classification not in VALID_FORMULA_IMPLIED_IMPLICATION_CLASSES or not _nonempty_str(item.get("reasoning")):
            reasons.append("BLOCK_COUNCIL_UNCLASSIFIED_UNEXPECTED_IMPLICATION")
            continue
        if classification in {"tradable_anomaly", "new_factor_seed"}:
            branch = item.get("branch_seed_if_any")
            branch_has_law = isinstance(branch, dict) and _nonempty_str(branch.get("child_formula_or_law"))
            law_has_child = any(
                isinstance(law, dict)
                and (
                    _nonempty_str(law.get("child_formula_or_law"))
                    or _nonempty_str(law.get("candidate_formula"))
                    or _nonempty_str(law.get("expression"))
                )
                for law in proposal.get("candidate_revision_laws") or []
            )
            if not (branch_has_law or law_has_child):
                reasons.append("BLOCK_COUNCIL_ANOMALY_BRANCH_LAW_MISSING")
    return list(dict.fromkeys(reasons))


def _validate_research_equation_revision(proposal: dict[str, Any]) -> list[str]:
    revision = proposal.get("research_equation_revision")
    if not isinstance(revision, dict):
        return ["BLOCK_COUNCIL_RESEARCH_EQUATION_REVISION_MISSING"]
    target = revision.get("equation_component_target")
    equation_change = revision.get("equation_change")
    signature_change = revision.get("expected_metric_signature_change")
    falsification_tests = revision.get("falsification_tests")
    if (
        target not in VALID_RESEARCH_EQUATION_REVISION_TARGETS
        or not _nonempty_str(revision.get("equation_change"))
        or not _nonempty_str_list(revision.get("expected_metric_signature_change"), min_count=1)
        or not _nonempty_str_list(revision.get("falsification_tests"), min_count=1)
    ):
        return ["BLOCK_COUNCIL_RESEARCH_EQUATION_REVISION_MISSING"]
    texts = [equation_change, *(signature_change or []), *(falsification_tests or [])]
    normalized_texts = [_normalized_words(text) for text in texts]
    blob = " ".join(normalized_texts)
    target_terms = REVISION_TARGET_EVIDENCE_TERMS.get(str(target), set())
    metric_terms = {
        "rank_ic",
        "long_side_return",
        "cost_adjusted_return",
        "turnover",
        "volatility_drag",
        "max_drawdown",
        "drawdown",
        "recovery",
    }
    has_target_or_metric_evidence = any(term in blob for term in target_terms | metric_terms)
    has_generic_revision_text = any(
        text in GENERIC_RESEARCH_EQUATION_REVISION_TEXT
        or any(phrase in text for phrase in GENERIC_RESEARCH_EQUATION_REVISION_TEXT)
        for text in normalized_texts
    )
    if has_generic_revision_text and not has_target_or_metric_evidence:
        return ["BLOCK_COUNCIL_RESEARCH_EQUATION_REVISION_GENERIC"]
    if not has_target_or_metric_evidence:
        return ["BLOCK_COUNCIL_RESEARCH_EQUATION_REVISION_GENERIC"]
    return []


def validate_revision_council_proposal(proposal: dict[str, Any]) -> list[str]:
    """Return block reasons. Empty means valid."""
    reasons: list[str] = []
    if not isinstance(proposal, dict):
        return ["revision_council_proposal_not_object"]

    for field in PROPOSAL_REQUIRED_FIELDS:
        if field not in proposal:
            reasons.append(f"revision_council_missing_field:{field}")

    if proposal.get("contract_version") != COUNCIL_PROPOSAL_VERSION:
        reasons.append("revision_council_contract_version_invalid")

    role = proposal.get("agent_role")
    if role not in COUNCIL_AGENT_ROLES:
        reasons.append("revision_council_agent_role_invalid")

    if proposal.get("revision_type") not in REVISION_TYPES:
        reasons.append("revision_council_revision_type_invalid")
    if proposal.get("target_failure_signature") not in FAILURE_SIGNATURES:
        reasons.append("revision_council_failure_signature_invalid")
    if proposal.get("return_source_hypothesis") not in RETURN_SOURCE_VALUES:
        reasons.append("revision_council_return_source_invalid")
    if proposal.get("confidence") not in CONFIDENCE_VALUES:
        reasons.append("revision_council_confidence_invalid")

    producer = proposal.get("producer")
    research_depth = proposal.get("research_depth")
    generation_mode = proposal.get("proposal_generation_mode")
    if producer not in PRODUCER_VALUES:
        reasons.append("revision_council_producer_invalid")
    if research_depth not in RESEARCH_DEPTH_VALUES:
        reasons.append("revision_council_research_depth_invalid")
    if generation_mode not in PROPOSAL_GENERATION_MODE_VALUES:
        reasons.append("revision_council_generation_mode_invalid")
    if producer == "deterministic_scaffold" and research_depth != "low":
        reasons.append("BLOCK_REVISION_COUNCIL_SCAFFOLD_DEPTH_INVALID")
    if generation_mode == "deterministic_scaffold" and producer != "deterministic_scaffold":
        reasons.append("revision_council_generation_mode_invalid")
    if producer == "agentic_research" and research_depth not in {"medium", "high"}:
        reasons.append("BLOCK_REVISION_COUNCIL_AGENTIC_DEPTH_INVALID")

    if not _model_layer_attribution_present(proposal):
        reasons.append("BLOCK_COUNCIL_REVISION_MODEL_LAYER_MISSING")

    reasons.extend(_validate_derivation_record(proposal))
    reasons.extend(_validate_formula_implied_information_review(proposal))
    reasons.extend(_validate_research_equation_revision(proposal))

    guards = proposal.get("forbidden_changes_ack") or []
    missing_guards = [item for item in REQUIRED_GUARDS if item not in guards]
    if missing_guards:
        reasons.append("revision_council_forbidden_guards_missing:" + ",".join(missing_guards))

    if not _nonempty_str(proposal.get("why_not_portfolio_fix")):
        reasons.append("revision_council_why_not_portfolio_fix_missing")

    symbolic_model = proposal.get("symbolic_model")
    if not isinstance(symbolic_model, dict):
        reasons.append("revision_council_symbolic_model_missing")
    else:
        for key in ["state_or_object", "target_functional"]:
            if not _nonempty_str(symbolic_model.get(key)):
                reasons.append(f"revision_council_symbolic_model_{key}_missing")

    laws = proposal.get("candidate_revision_laws") or []
    if proposal.get("revision_type") == "expression_revision":
        if not _nonempty_list(laws):
            reasons.append("revision_council_expression_revision_laws_missing")
        for idx, law in enumerate(laws):
            if not isinstance(law, dict):
                reasons.append(f"revision_council_law_{idx}_not_object")
                continue
            if not _nonempty_list(law.get("falsification_tests")):
                reasons.append(f"revision_council_law_{idx}_falsification_tests_missing")
            if not _nonempty_list(law.get("kill_criteria")):
                reasons.append(f"revision_council_law_{idx}_kill_criteria_missing")
            if not _nonempty_str_list(law.get("expected_metric_change"), min_count=2):
                reasons.append(f"BLOCK_REVISION_COUNCIL_EXPECTED_METRIC_CHANGE_MISSING:law_{idx}")

    tools = proposal.get("selected_math_tools") or []
    if role == "symbolic_law_discovery":
        if not _nonempty_list(tools):
            reasons.append("revision_council_symbolic_math_tools_missing")
        unknown_tools = [str(item) for item in tools if item not in SYMBOLIC_MATH_TOOLS]
        if unknown_tools:
            reasons.append("revision_council_symbolic_math_tools_unknown:" + ",".join(unknown_tools))
        review = proposal.get("dimensional_scaling_review")
        if not isinstance(review, dict) or not review:
            reasons.append("revision_council_dimensional_scaling_review_missing")
        else:
            for key in [
                "raw_field_units",
                "formula_output_dimension",
                "dimension_erasing_transforms",
                "scale_invariance_claims",
                "natural_time_scale",
                "dimension_risks",
                "limiting_cases",
            ]:
                if key not in review:
                    reasons.append(f"revision_council_dimensional_scaling_review_{key}_missing")

    forbidden = scan_forbidden_text(proposal)
    if forbidden:
        reasons.append(FORBIDDEN_TEXT_TOKEN + ":" + ",".join(f"{item['path']}={item['pattern']}" for item in forbidden))

    return reasons
