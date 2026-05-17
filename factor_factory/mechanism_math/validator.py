from __future__ import annotations

import re
from typing import Any

from .schema import (
    CONTRACT_VERSION,
    FORBIDDEN_REPAIR_TERMS,
    FUNDAMENTAL_FIELDS,
    PRICE_FIELDS,
    REQUIRED_INFORMATION_SET_FIELDS,
    REQUIRED_REVISION_OPERATOR_FIELDS,
    REQUIRED_SPECIFIED_FIELDS,
    REVISION_TARGET_MATH_OBJECTS,
    VALID_MODEL_FAMILIES,
    VALID_MODEL_STATUSES,
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
