from __future__ import annotations

import re
import json
from typing import Any

from .schema import (
    CONTRACT_VERSION,
    CONTRACT_VERSION_V2,
    FORBIDDEN_REPAIR_TERMS,
    FUNDAMENTAL_FIELDS,
    PRICE_FIELDS,
    REQUIRED_INFORMATION_SET_FIELDS,
    REQUIRED_REVISION_OPERATOR_FIELDS,
    REQUIRED_SPECIFIED_FIELDS,
    VALID_FORMULA_MODEL_ROLES_V2,
    REVISION_TARGET_MATH_OBJECTS,
    VALID_MODEL_FAMILIES,
    VALID_MODEL_STATUSES,
    VALID_PRICE_PROCESS_PROJECTION_ROLES_V2,
    VALID_PRICE_PROCESS_TERMS_V2,
    VALID_PRIMARY_MODEL_FAMILIES_V2,
    VALID_TOOLKITS,
    VOLUME_FIELDS,
)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _nonempty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _failures_add(failures: list[dict[str, str]], code: str, message: str) -> None:
    failures.append({"code": code, "message": message})


def _text_blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value or "")


def _meaningful_str(value: Any) -> bool:
    if not _nonempty_str(value):
        return False
    text = str(value).strip().lower()
    return text not in {"under_specified", "unknown", "n/a", "none", "tbd", "todo"}


def _nonempty_meaningful_list(value: Any) -> bool:
    return isinstance(value, list) and any(_meaningful_str(item) or _nonempty_dict(item) for item in value)


def _is_vague_sde(contract: dict[str, Any]) -> bool:
    """Block decorative stochastic language even when surrounded by plausible fields."""
    text = _text_blob(contract).lower()
    vague_patterns = [
        r"\bds\s*=\s*mu\s*s\s*dt\s*\+\s*sigma\s*s\s*dw\b",
        r"\bds\s*=\s*μ\s*s\s*dt\s*\+\s*σ\s*s\s*dw\b",
        r"\bgeneric stochastic process\b",
        r"\bstandard sde\b",
        r"\bbrownian motion\b",
        r"\bgeometric brownian motion\b",
    ]
    mentions_vague = any(re.search(pattern, text) for pattern in vague_patterns)
    return mentions_vague


def _canonical_expression_text(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"[^a-z0-9_]+", "", text)


def _formula_mapping_is_self_referential(item: dict[str, Any]) -> bool:
    component_text = str(item.get("formula_component") or "").strip().lower()
    proxy_text = str(item.get("observable_proxy_for") or "").strip().lower()
    if not component_text or not proxy_text:
        return True
    if component_text == proxy_text:
        return True
    component = _canonical_expression_text(component_text)
    proxy = _canonical_expression_text(proxy_text)
    if component and proxy and component == proxy:
        return True
    formula_call_pattern = re.compile(
        r"(?<![a-z0-9_])(?:rank|ts_rank|delta|delay|corr|cov|sum|mean|std|argmin|argmax)\s*\(",
    )
    if formula_call_pattern.search(proxy_text):
        return True
    return False


def validate_mechanism_math_contract_v2(contract: Any) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if not isinstance(contract, dict) or not contract:
        _failures_add(failures, "mechanism_math_contract_missing", "mechanism_math_contract_v2 must be a nonempty object")
        return failures
    if contract.get("contract_version") != CONTRACT_VERSION_V2:
        _failures_add(failures, "mechanism_math_contract_version_invalid", f"contract_version must be {CONTRACT_VERSION_V2}")
        return failures

    thesis = contract.get("market_process_thesis") if isinstance(contract.get("market_process_thesis"), dict) else {}
    primary = contract.get("primary_mechanism_model") if isinstance(contract.get("primary_mechanism_model"), dict) else {}
    projection = contract.get("stochastic_price_process_projection") if isinstance(contract.get("stochastic_price_process_projection"), dict) else {}
    mapping = contract.get("formula_component_mapping")
    expected = contract.get("expected_metric_signature")
    tests = contract.get("falsification_tests")

    family = primary.get("selected_model_family")
    if (
        not _nonempty_dict(primary)
        or not _meaningful_str(family)
        or family not in VALID_PRIMARY_MODEL_FAMILIES_V2
        or not _meaningful_str(primary.get("selected_model_reason"))
        or not _nonempty_meaningful_list(primary.get("state_variables"))
        or not _nonempty_meaningful_list(primary.get("observable_proxies"))
        or not _meaningful_str(primary.get("target_functional"))
    ):
        _failures_add(
            failures,
            "BLOCK_MECHANISM_MATH_V2_MISSING_PRIMARY_MODEL",
            "v2 contract requires a formula-specific primary_mechanism_model with selected family, reason, state variables, proxies, and target functional",
        )

    affected = projection.get("affected_price_process_terms")
    invalid_terms = [str(item) for item in affected or [] if item not in VALID_PRICE_PROCESS_TERMS_V2]
    if (
        not _nonempty_dict(projection)
        or projection.get("projection_required") is not True
        or not _nonempty_meaningful_list(affected)
        or invalid_terms
        or not _meaningful_str(projection.get("price_process_form"))
        or not _meaningful_str(projection.get("conditional_distribution_claim"))
        or not _meaningful_str(projection.get("formula_should_estimate"))
        or not _meaningful_str(projection.get("expected_return_distribution_change"))
    ):
        _failures_add(
            failures,
            "BLOCK_MECHANISM_MATH_V2_EMPTY_STOCHASTIC_PROJECTION",
            "v2 contract requires a nonempty stochastic_price_process_projection with valid affected terms and conditional distribution claim",
        )

    if not isinstance(mapping, list) or not mapping:
        _failures_add(
            failures,
            "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_MISSING",
            "v2 contract requires formula_component_mapping",
        )
    else:
        for idx, item in enumerate(mapping):
            if not isinstance(item, dict):
                _failures_add(failures, "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_MISSING", f"formula_component_mapping[{idx}] must be an object")
                continue
            if (
                not _meaningful_str(item.get("formula_component"))
                or not _meaningful_str(item.get("observable_proxy_for"))
                or item.get("model_role") not in VALID_FORMULA_MODEL_ROLES_V2
                or item.get("price_process_projection_role") not in VALID_PRICE_PROCESS_PROJECTION_ROLES_V2
            ):
                _failures_add(
                    failures,
                    "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_MISSING",
                    f"formula_component_mapping[{idx}] missing required component/proxy/model/projection role",
                )
            elif _formula_mapping_is_self_referential(item):
                _failures_add(
                    failures,
                    "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_SELF_REFERENTIAL",
                    f"formula_component_mapping[{idx}] cannot map a formula component back to itself instead of an economic/model state or market observable",
                )

    if not _nonempty_dict(expected):
        _failures_add(failures, "BLOCK_MECHANISM_MATH_V2_EXPECTED_METRIC_SIGNATURE_MISSING", "v2 contract requires expected_metric_signature")
    if not _nonempty_meaningful_list(tests):
        _failures_add(failures, "BLOCK_MECHANISM_MATH_V2_FALSIFICATION_TESTS_MISSING", "v2 contract requires falsification_tests")
    if not _nonempty_dict(thesis) or not _meaningful_str(thesis.get("economic_hypothesis")) or not _meaningful_str(thesis.get("payer_or_counterparty")):
        _failures_add(failures, "BLOCK_MECHANISM_MATH_V2_MARKET_PROCESS_THESIS_MISSING", "v2 contract requires market_process_thesis economic hypothesis and payer")

    if _is_vague_sde(contract):
        _failures_add(
            failures,
            "BLOCK_MECHANISM_MATH_V2_VAGUE_SDE",
            "v2 contract cannot pass with decorative generic SDE/Brownian language; state, estimator, projection, and formula mapping must be formula-specific",
        )
    return failures


def _text_contains_forbidden(value: Any) -> list[str]:
    text = str(value or "").lower()
    return [term for term in FORBIDDEN_REPAIR_TERMS if term in text]


def _contains_field_token(text: str, tokens: set[str]) -> bool:
    for token in tokens:
        if re.search(rf"(?<![a-z0-9_]){re.escape(token)}(?![a-z0-9_])", text):
            return True
    return False


def _input_set(contract: dict[str, Any]) -> set[str]:
    return {str(item).lower() for item in contract.get("observable_inputs") or []}


def _classification_text(contract: dict[str, Any]) -> str:
    evidence = contract.get("classification_evidence") if isinstance(contract.get("classification_evidence"), dict) else {}
    parts = [
        evidence.get("formula_text"),
        contract.get("economic_mechanism"),
        contract.get("state_or_object"),
        contract.get("factor_as_estimator"),
        contract.get("observable_estimator"),
    ]
    parts.extend(str(item) for item in contract.get("observable_inputs") or [])
    return " ".join(str(item) for item in parts if item).lower()


def _formula_text(contract: dict[str, Any]) -> str:
    evidence = contract.get("classification_evidence") if isinstance(contract.get("classification_evidence"), dict) else {}
    return str(evidence.get("formula_text") or "").lower()


def _has_price_volume_dependence(contract: dict[str, Any]) -> bool:
    text = _classification_text(contract)
    inputs = _input_set(contract)
    price_tokens = set(PRICE_FIELDS) | {"vwap"}
    volume_tokens = set(VOLUME_FIELDS) | {"money", "traded_value"}
    has_price = bool(inputs & price_tokens) or _contains_field_token(text, price_tokens)
    has_volume = bool(inputs & volume_tokens) or _contains_field_token(text, volume_tokens)
    has_dependence = any(
        token in text
        for token in [
            "correlation",
            "corr",
            "covariance",
            "rolling_cov",
            "rolling_corr",
            "rank-dependence",
            "rank dependence",
            "co-movement",
            "comovement",
        ]
    ) or bool(re.search(r"\bcov\s*\(", text))
    return has_price and has_volume and has_dependence


def _has_true_projection_language(contract: dict[str, Any]) -> bool:
    text = _classification_text(contract)
    return any(
        token in text
        for token in [
            "neutralize",
            "neutralization",
            "residualize",
            "residualization",
            "projection",
            "pca",
            "orthogonal",
            "beta neutral",
            "factor neutral",
        ]
    )


def _has_true_projection_formula(contract: dict[str, Any]) -> bool:
    text = _formula_text(contract)
    return any(
        token in text
        for token in [
            "neutralize",
            "residualize",
            "projection",
            "pca",
            "orthogonal",
            "beta_neutral",
            "factor_neutral",
        ]
    )


def validate_mechanism_math_contract(contract: Any) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if not isinstance(contract, dict) or not contract:
        _failures_add(failures, "mechanism_math_contract_missing", "mechanism_math_contract must be a nonempty object")
        return failures

    if contract.get("contract_version") == CONTRACT_VERSION_V2:
        return validate_mechanism_math_contract_v2(contract)

    if contract.get("contract_version") != CONTRACT_VERSION:
        _failures_add(failures, "mechanism_math_contract_version_invalid", f"contract_version must be {CONTRACT_VERSION}")
    status = contract.get("math_model_status")
    if status not in VALID_MODEL_STATUSES:
        _failures_add(failures, "mechanism_math_status_invalid", f"math_model_status must be one of {sorted(VALID_MODEL_STATUSES)}")
        return failures

    family = contract.get("model_family")
    if family not in VALID_MODEL_FAMILIES:
        _failures_add(failures, "mechanism_math_model_family_invalid", f"model_family must be one of {sorted(VALID_MODEL_FAMILIES)}")

    toolkits = contract.get("math_toolkits") or []
    if not isinstance(toolkits, list):
        _failures_add(failures, "mechanism_math_toolkits_not_list", "math_toolkits must be a list")
    else:
        invalid = sorted(str(item) for item in toolkits if item not in VALID_TOOLKITS)
        if invalid:
            _failures_add(failures, "mechanism_math_toolkits_invalid", f"invalid math_toolkits: {invalid}")

    if status == "under_specified":
        if not _nonempty_str(contract.get("under_specified_reason")):
            _failures_add(failures, "mechanism_math_under_specified_reason_missing", "under_specified contract requires under_specified_reason")
        if not _nonempty_str(contract.get("next_human_research_question")):
            _failures_add(failures, "mechanism_math_next_human_question_missing", "under_specified contract requires next_human_research_question")
        return failures

    if status == "invalid":
        if not _nonempty_str(contract.get("invalid_reason") or contract.get("under_specified_reason")):
            _failures_add(failures, "mechanism_math_invalid_reason_missing", "invalid contract requires invalid_reason")
        return failures

    for field in REQUIRED_SPECIFIED_FIELDS:
        value = contract.get(field)
        if field in {
            "math_toolkits",
            "observable_inputs",
            "necessary_conditions",
            "revision_operators",
            "falsification_tests",
            "mechanism_falsification_tests",
            "kill_criteria",
        }:
            if not _nonempty_list(value):
                _failures_add(failures, f"mechanism_math_{field}_missing", f"specified contract requires nonempty {field}")
        elif field in {"information_set", "expected_metric_signature"}:
            if not _nonempty_dict(value):
                _failures_add(failures, f"mechanism_math_{field}_missing", f"specified contract requires nonempty {field}")
        elif not _nonempty_str(value):
            _failures_add(failures, f"mechanism_math_{field}_missing", f"specified contract requires nonempty {field}")

    info = contract.get("information_set") or {}
    if isinstance(info, dict):
        for field in REQUIRED_INFORMATION_SET_FIELDS:
            if field not in info:
                _failures_add(failures, f"mechanism_math_information_set_{field}_missing", f"information_set.{field} missing")
        if info.get("uses_future_information") is True:
            _failures_add(failures, "mechanism_math_future_information_forbidden", "mechanism math contract cannot declare future information usage")

    for idx, operator in enumerate(contract.get("revision_operators") or []):
        if not isinstance(operator, dict):
            _failures_add(failures, f"mechanism_math_revision_operator_{idx}_not_object", "revision_operators entries must be objects")
            continue
        for field in REQUIRED_REVISION_OPERATOR_FIELDS:
            value = operator.get(field)
            if field == "expected_effects":
                if not _nonempty_list(value):
                    _failures_add(failures, f"mechanism_math_revision_operator_{idx}_{field}_missing", f"revision operator requires {field}")
            elif not _nonempty_str(value):
                _failures_add(failures, f"mechanism_math_revision_operator_{idx}_{field}_missing", f"revision operator requires {field}")
        target = operator.get("revision_target_math_object")
        if target not in REVISION_TARGET_MATH_OBJECTS:
            _failures_add(failures, f"mechanism_math_revision_operator_{idx}_target_invalid", f"invalid revision_target_math_object: {target}")
        forbidden = _text_contains_forbidden(operator.get("math_change"))
        if forbidden:
            _failures_add(failures, f"mechanism_math_revision_operator_{idx}_portfolio_repair_forbidden", f"math_change contains forbidden repair terms: {forbidden}")

    inputs = _input_set(contract)
    if family == "valuation_identity":
        has_fundamental = bool(inputs & FUNDAMENTAL_FIELDS)
        only_price_volume = bool(inputs) and inputs.issubset(PRICE_FIELDS | VOLUME_FIELDS)
        explanation = " ".join(str(contract.get(key) or "").lower() for key in ["economic_mechanism", "factor_as_estimator", "state_or_object"])
        mentions_valuation = any(token in explanation for token in ["valuation", "account", "book", "roe", "profit", "residual", "earnings"])
        if only_price_volume and not has_fundamental and not mentions_valuation:
            _failures_add(
                failures,
                "mechanism_math_model_family_observable_inputs_contradiction",
                "valuation_identity cannot be silently accepted with only price/volume observables and no valuation/accounting explanation",
            )

    if family == "linear_factor_projection":
        if _has_price_volume_dependence(contract) and not _has_true_projection_formula(contract):
            _failures_add(
                failures,
                "mechanism_math_price_volume_dependence_family_mismatch",
                "price-volume covariance/correlation/rank-dependence formulas must not be classified as linear_factor_projection without explicit projection or residualization language",
            )
        elif not _has_true_projection_language(contract):
            _failures_add(
                failures,
                "mechanism_math_linear_projection_evidence_missing",
                "linear_factor_projection requires explicit projection, residualization, neutralization, PCA, orthogonalization, or beta-neutral language",
            )

    if family == "price_volume_microstructure" and _has_true_projection_formula(contract):
        _failures_add(
            failures,
            "mechanism_math_price_volume_projection_family_mismatch",
            "formula-level projection, residualization, or neutralization must be classified as linear_factor_projection or an explicit composite, not pure price_volume_microstructure",
        )

    return failures


def is_valid_mechanism_math_contract(contract: Any) -> bool:
    return not validate_mechanism_math_contract(contract)
