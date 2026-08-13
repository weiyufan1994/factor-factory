from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from factor_factory.console.models import (
    PILOT_TRIAL_BUDGET,
    RESEARCH_REQUEST_VERSION,
    RESEARCH_REQUEST_VERSION_V2,
)


def research_request_version(request: Mapping[str, Any]) -> str:
    value = (
        request["contract_version"]
        if "contract_version" in request
        else RESEARCH_REQUEST_VERSION
    )
    if not isinstance(value, str) or value not in {
        RESEARCH_REQUEST_VERSION,
        RESEARCH_REQUEST_VERSION_V2,
    }:
        raise ValueError("request.contract_version")
    return value


def request_trial_budget(request: Mapping[str, Any]) -> int:
    """Return an authority-bearing v2 budget; v1 retains legacy semantics."""
    version = research_request_version(request)
    if version == RESEARCH_REQUEST_VERSION:
        if "trial_budget" in request:
            raise ValueError("request.v1_trial_budget_forbidden")
        return PILOT_TRIAL_BUDGET
    if version != RESEARCH_REQUEST_VERSION_V2:
        raise ValueError("request.contract_version")
    value = request.get("trial_budget")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= PILOT_TRIAL_BUDGET
    ):
        raise ValueError("request.trial_budget")
    return value


def trial_budget_binding_reasons(
    *,
    request: Mapping[str, Any],
    plan: Mapping[str, Any],
    observed_registered_trial_count: int | None = None,
) -> list[str]:
    reasons: list[str] = []
    try:
        version = research_request_version(request)
    except ValueError as exc:
        reasons.append(str(exc))
        version = ""
    if version:
        try:
            authoritative_budget = request_trial_budget(request)
        except ValueError as exc:
            reasons.append(str(exc))
            authoritative_budget = None
    else:
        authoritative_budget = None

    evidence = (
        plan.get("evidence_policy")
        if isinstance(plan.get("evidence_policy"), Mapping)
        else {}
    )
    evidence_budget = evidence.get("trial_budget")
    if (
        isinstance(evidence_budget, bool)
        or not isinstance(evidence_budget, int)
        or not 1 <= evidence_budget <= PILOT_TRIAL_BUDGET
    ):
        reasons.append("evidence_policy.trial_budget")

    measurement = (
        plan.get("measurement_program")
        if isinstance(plan.get("measurement_program"), Mapping)
        else {}
    )
    search = (
        measurement.get("search_policy")
        if isinstance(measurement.get("search_policy"), Mapping)
        else {}
    )
    raw_diagnostics = search.get("registered_diagnostic_trials")
    diagnostics = []
    if raw_diagnostics is None and version == RESEARCH_REQUEST_VERSION:
        # Legacy proof fixtures and persisted v1 plans predate this list.  They
        # registered only the one base candidate.
        diagnostics = []
    elif not isinstance(raw_diagnostics, list) or any(
        not isinstance(item, Mapping) for item in raw_diagnostics
    ):
        reasons.append(
            "measurement_program.search_policy.registered_diagnostic_trials"
        )
    else:
        diagnostics = raw_diagnostics
    expected_total = 1 + len(diagnostics)
    observed_count_valid = (
        observed_registered_trial_count is None
        or (
            not isinstance(observed_registered_trial_count, bool)
            and isinstance(observed_registered_trial_count, int)
            and observed_registered_trial_count >= 0
        )
    )
    if not observed_count_valid:
        reasons.append("search_trial_ledger.trial_count")

    if version == RESEARCH_REQUEST_VERSION_V2:
        if evidence_budget != authoritative_budget:
            reasons.append("evidence_policy.trial_budget_request_mismatch")

    if isinstance(evidence_budget, int) and not isinstance(evidence_budget, bool):
        if expected_total > evidence_budget:
            reasons.append(
                "measurement_program.search_policy.diagnostics_exceed_trial_budget"
            )
        if (
            observed_count_valid
            and observed_registered_trial_count is not None
            and observed_registered_trial_count > evidence_budget
        ):
            reasons.append("search_trial_ledger.trial_budget_exceeded")
    if (
        observed_count_valid
        and observed_registered_trial_count is not None
        and observed_registered_trial_count != expected_total
    ):
        reasons.append("search_trial_ledger.registered_trial_count_mismatch")
    return list(dict.fromkeys(reasons))
