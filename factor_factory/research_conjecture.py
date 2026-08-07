from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
    validate_evidence_reference,
)
from factor_factory.research_proof import (
    CLAIM_CLASSES,
    factor_proof_certificate_path,
    validate_factor_proof_certificate,
)
from factor_factory.research_obligation_verifier import (
    VERIFIER_CONTRACT_VERSION as COMPONENT_VERIFIER_CONTRACT_VERSION,
    VERIFIER_ID as COMPONENT_VERIFIER_ID,
    stable_hash as stable_obligation_hash,
    validate_component_obligation_report,
    verifier_source_sha256 as component_verifier_source_sha256,
)


PROTOCOL_VERSION = "factorforge_research_conjecture_protocol_v1"
CLAIM_LEVELS = (
    "none",
    "narrative_only",
    "math_framed",
    "metric_candidate",
    "metric_consistent",
    "component_validated",
    "stochastic_validated",
    "payer_validated",
)
ROUTE_STATUSES = {
    "open",
    "active",
    "blocked",
    "falsified",
    "supported",
    "inconclusive",
    "closed",
}
OBLIGATION_STATUSES = {"open", "blocked", "failed", "passed", "not_applicable"}
TERMINAL_DECISIONS = {"promote_official", "reject", "exhausted", "blocked"}
TERMINAL_RECOMMENDATION_VALUES = {
    "reject",
    "kill",
    "stop",
    "terminal_reject",
    "no_revision",
    "no_derived_revision",
}
REQUIRED_ROUTE_FAMILIES = {
    "economic_game",
    "null_alias_counterexample",
}
MEASUREMENT_ROUTE_FAMILIES = {
    "mechanism_object_measurement",
    "latent_state_measurement",  # legacy compatibility
}
RESEARCH_PHASES = {
    "FORMULATE",
    "DIVERSIFY",
    "ATTACK",
    "DERIVE",
    "TEST",
    "SYNTHESIZE",
    "REDIRECT",
    "VERIFY",
    "ACCEPT",
    "REJECT",
    "BLOCK",
}
ALLOWED_PHASE_TRANSITIONS = {
    None: {"FORMULATE"},
    "FORMULATE": {"DIVERSIFY", "BLOCK"},
    "DIVERSIFY": {"ATTACK", "DERIVE", "BLOCK"},
    "ATTACK": {"DERIVE", "TEST", "REDIRECT", "BLOCK"},
    "DERIVE": {"ATTACK", "TEST", "REDIRECT", "BLOCK"},
    "TEST": {"SYNTHESIZE", "REDIRECT", "BLOCK"},
    "SYNTHESIZE": {"REDIRECT", "VERIFY", "BLOCK"},
    "REDIRECT": {"DIVERSIFY", "ATTACK", "DERIVE", "TEST", "BLOCK"},
    "VERIFY": {"ACCEPT", "REJECT", "BLOCK"},
    "ACCEPT": set(),
    "REJECT": set(),
    "BLOCK": set(),
}
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
TRUSTED_OBLIGATION_VERIFIERS = {
    "measurement_validity": COMPONENT_VERIFIER_ID,
    "component_ablation": COMPONENT_VERIFIER_ID,
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value: Any, minimum: int = 1) -> bool:
    return isinstance(value, list) and len(value) >= minimum


def nonempty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def sha256_value(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value.strip().lower()))


def _require_sha256(
    reasons: list[str],
    data: dict[str, Any],
    key: str,
    token: str,
    *,
    allow_not_materialized: bool = False,
) -> None:
    value = data.get(key)
    if allow_not_materialized and value == "not_materialized_before_step3":
        return
    if not sha256_value(value):
        reasons.append(f"{token}:{key}")


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_research_state(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_STATE_VERSION_INVALID")
    for field in ("report_id", "factor_id", "research_id", "round_id"):
        _require_str(
            reasons,
            payload,
            field,
            "BLOCK_FACTORFORGE_RESEARCH_STATE_IDENTITY_MISSING",
        )
    phase = payload.get("phase")
    previous = payload.get("previous_phase")
    if phase not in RESEARCH_PHASES:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_STATE_PHASE_INVALID")
    if previous is not None and previous not in RESEARCH_PHASES:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_STATE_PREVIOUS_PHASE_INVALID")
    if phase in RESEARCH_PHASES and previous in ALLOWED_PHASE_TRANSITIONS:
        if phase not in ALLOWED_PHASE_TRANSITIONS[previous]:
            reasons.append(
                f"BLOCK_FACTORFORGE_RESEARCH_STATE_TRANSITION_INVALID:{previous}->{phase}"
            )
    _require_str(
        reasons,
        payload,
        "transition_reason",
        "BLOCK_FACTORFORGE_RESEARCH_STATE_TRANSITION_REASON_MISSING",
    )
    if previous is not None:
        _require_list(
            reasons,
            payload,
            "transition_evidence_refs",
            "BLOCK_FACTORFORGE_RESEARCH_STATE_TRANSITION_EVIDENCE_MISSING",
        )
    budget = payload.get("budget_used")
    if not isinstance(budget, dict):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_STATE_BUDGET_MISSING")
    else:
        trials_used = budget.get("trials_used")
        trial_budget = budget.get("trial_budget")
        if (
            not isinstance(trials_used, int)
            or not isinstance(trial_budget, int)
            or trials_used < 0
            or trial_budget < 1
        ):
            reasons.append("BLOCK_FACTORFORGE_RESEARCH_STATE_BUDGET_INVALID")
        elif trials_used > trial_budget:
            reasons.append("BLOCK_FACTORFORGE_RESEARCH_TRIAL_BUDGET_EXCEEDED")
    return reasons


def _require_str(
    reasons: list[str],
    data: dict[str, Any],
    key: str,
    token: str,
) -> None:
    if not nonempty_str(data.get(key)):
        reasons.append(f"{token}:{key}")


def _require_list(
    reasons: list[str],
    data: dict[str, Any],
    key: str,
    token: str,
    minimum: int = 1,
) -> None:
    if not nonempty_list(data.get(key), minimum):
        reasons.append(f"{token}:{key}")


def _iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return (item for item in value if isinstance(item, dict))


def validate_research_conjecture(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_VERSION_INVALID")
    for field in ("report_id", "factor_id"):
        _require_str(
            reasons,
            payload,
            field,
            "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_IDENTITY_MISSING",
        )
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_LINEAGE_MISSING")
        identity = {}
    for field in ("research_id", "round_id"):
        _require_str(
            reasons,
            identity,
            field,
            "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_LINEAGE_MISSING",
        )
    for field in (
        "workspace_manifest_sha256",
        "parent_artifact_sha256",
        "formula_hash",
        "data_catalog_snapshot_sha256",
    ):
        _require_sha256(
            reasons,
            identity,
            field,
            "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_LINEAGE_HASH_INVALID",
        )
    _require_sha256(
        reasons,
        identity,
        "code_hash",
        "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_LINEAGE_HASH_INVALID",
        allow_not_materialized=True,
    )

    task = payload.get("task_statement")
    if not nonempty_dict(task):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_TASK_MISSING")
        task = {}
    for field in (
        "research_question",
        "alpha_claim",
        "null_hypothesis",
        "admissible_information_set",
        "terminal_success_condition",
        "terminal_reject_condition",
        "terminal_block_condition",
    ):
        _require_str(
            reasons,
            task,
            field,
            "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_TASK_UNDERSPECIFIED",
        )
    _require_list(
        reasons,
        task,
        "forbidden_evidence",
        "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_FORBIDDEN_EVIDENCE_MISSING",
    )

    hypotheses = list(_iter_dicts(payload.get("hypotheses")))
    kinds = {str(item.get("kind") or "") for item in hypotheses}
    if not {"preferred", "null"}.issubset(kinds):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_DUAL_HYPOTHESIS_MISSING")
    if "alternative" not in kinds:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_ALTERNATIVE_MISSING")
    hypothesis_ids: set[str] = set()
    for idx, item in enumerate(hypotheses):
        hypothesis_id = item.get("hypothesis_id")
        if not nonempty_str(hypothesis_id):
            reasons.append(
                f"BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_HYPOTHESIS_INVALID:{idx}:hypothesis_id"
            )
        elif hypothesis_id in hypothesis_ids:
            reasons.append(
                f"BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_HYPOTHESIS_DUPLICATE:{hypothesis_id}"
            )
        else:
            hypothesis_ids.add(hypothesis_id)
        for field in ("claim", "expected_signature"):
            _require_str(
                reasons,
                item,
                field,
                f"BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_HYPOTHESIS_INVALID:{idx}",
            )
        _require_list(
            reasons,
            item,
            "falsification_tests",
            f"BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_HYPOTHESIS_INVALID:{idx}",
            minimum=2,
        )
        _require_list(
            reasons,
            item,
            "kill_criteria",
            f"BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_HYPOTHESIS_INVALID:{idx}",
        )

    game = payload.get("economic_game")
    if not nonempty_dict(game):
        reasons.append("BLOCK_FACTORFORGE_ECONOMIC_GAME_CONTRACT_MISSING")
        game = {}
    _require_list(
        reasons,
        game,
        "participants",
        "BLOCK_FACTORFORGE_ECONOMIC_GAME_UNDERSPECIFIED",
        minimum=2,
    )
    _require_list(
        reasons,
        game,
        "payer_candidates",
        "BLOCK_FACTORFORGE_ECONOMIC_GAME_UNDERSPECIFIED",
    )
    _require_list(
        reasons,
        game,
        "participant_constraints",
        "BLOCK_FACTORFORGE_ECONOMIC_GAME_UNDERSPECIFIED",
    )
    if not nonempty_str(
        game.get("action_to_market_outcome") or game.get("action_to_price_path")
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_ECONOMIC_GAME_UNDERSPECIFIED:action_to_market_outcome"
        )
    if not nonempty_str(
        game.get("payoff_or_profit_transfer_equation")
        or game.get("profit_transfer_equation")
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_ECONOMIC_GAME_UNDERSPECIFIED:payoff_or_profit_transfer_equation"
        )
    for field in (
        "persistence_boundary",
        "capacity_boundary",
        "failure_condition",
    ):
        _require_str(
            reasons,
            game,
            field,
            "BLOCK_FACTORFORGE_ECONOMIC_GAME_UNDERSPECIFIED",
        )
    for idx, item in enumerate(_iter_dicts(game.get("participant_constraints"))):
        for field in (
            "actor",
            "constraint",
            "why_persistent",
            "observable_proxy",
            "falsifier",
        ):
            _require_str(
                reasons,
                item,
                field,
                f"BLOCK_FACTORFORGE_ECONOMIC_CONSTRAINT_UNDERSPECIFIED:{idx}",
            )

    math = payload.get("math_mechanism")
    if not nonempty_dict(math):
        reasons.append("BLOCK_FACTORFORGE_MATH_MECHANISM_CONTRACT_MISSING")
        math = {}
    for field in (
        "model_family",
        "observation_equation",
        "factor_estimator",
        "information_set",
    ):
        _require_str(
            reasons,
            math,
            field,
            "BLOCK_FACTORFORGE_MATH_MECHANISM_UNDERSPECIFIED",
        )
    if not nonempty_str(
        math.get("mathematical_object") or math.get("latent_state")
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_MATH_MECHANISM_UNDERSPECIFIED:mathematical_object"
        )
    if not nonempty_str(
        math.get("mechanism_equation_or_functional")
        or math.get("core_equation_or_functional")
        or math.get("process_or_distribution")
        or math.get("return_equation")
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_MATH_MECHANISM_UNDERSPECIFIED:mechanism_equation_or_functional"
        )
    if not nonempty_str(
        math.get("market_outcome_equation") or math.get("return_equation")
    ):
        reasons.append("BLOCK_FACTORFORGE_MARKET_OUTCOME_PROJECTION_UNDERSPECIFIED")
    _require_list(
        reasons,
        math,
        "alternative_models",
        "BLOCK_FACTORFORGE_MATH_ALTERNATIVE_MODELS_MISSING",
    )
    _require_list(
        reasons,
        math,
        "component_map",
        "BLOCK_FACTORFORGE_MATH_COMPONENT_MAP_MISSING",
    )
    _require_list(
        reasons,
        math,
        "limiting_cases",
        "BLOCK_FACTORFORGE_MATH_LIMITING_CASES_MISSING",
        minimum=3,
    )
    _require_list(
        reasons,
        math,
        "expected_metric_signatures",
        "BLOCK_FACTORFORGE_MATH_METRIC_SIGNATURES_MISSING",
        minimum=2,
    )
    for idx, item in enumerate(_iter_dicts(math.get("component_map"))):
        for field in (
            "formula_component",
            "model_term",
            "preserved_information",
            "deleted_or_aliased_information",
            "ablation_test",
        ):
            _require_str(
                reasons,
                item,
                field,
                f"BLOCK_FACTORFORGE_MATH_COMPONENT_MAP_INVALID:{idx}",
            )

    evidence = payload.get("evidence_policy")
    if not nonempty_dict(evidence):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_EVIDENCE_POLICY_MISSING")
        evidence = {}
    if evidence.get("oos_sealed_during_search") is not True:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_OOS_NOT_SEALED")
    _require_str(
        reasons,
        evidence,
        "is_window",
        "BLOCK_FACTORFORGE_RESEARCH_EVIDENCE_POLICY_UNDERSPECIFIED",
    )
    _require_list(
        reasons,
        evidence,
        "promotion_evidence_requirements",
        "BLOCK_FACTORFORGE_RESEARCH_EVIDENCE_POLICY_UNDERSPECIFIED",
    )
    for field in (
        "is_start",
        "is_end",
        "oos_start",
        "oos_end",
        "multiple_testing_policy",
        "cost_model_id",
        "impact_model_id",
        "capacity_model_id",
        "regime_plan",
        "universe_id",
        "investability_mask_id",
    ):
        _require_str(
            reasons,
            evidence,
            field,
            "BLOCK_FACTORFORGE_RESEARCH_FINANCIAL_CONTROL_MISSING",
        )
    _require_sha256(
        reasons,
        evidence,
        "sealed_oos_token_hash",
        "BLOCK_FACTORFORGE_RESEARCH_FINANCIAL_CONTROL_MISSING",
    )
    is_start = _parse_date(evidence.get("is_start"))
    is_end = _parse_date(evidence.get("is_end"))
    oos_start = _parse_date(evidence.get("oos_start"))
    oos_end = _parse_date(evidence.get("oos_end"))
    if None in {is_start, is_end, oos_start, oos_end}:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_WINDOW_DATE_INVALID")
    elif not (is_start <= is_end < oos_start <= oos_end):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_WINDOW_ORDER_INVALID")
    for field in ("purge_days", "embargo_days", "trial_budget", "trials_used"):
        value = evidence.get(field)
        if not isinstance(value, int) or value < 0:
            reasons.append(f"BLOCK_FACTORFORGE_RESEARCH_FINANCIAL_CONTROL_INVALID:{field}")
    if isinstance(evidence.get("trial_budget"), int) and evidence.get("trial_budget") < 1:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_TRIAL_BUDGET_INVALID")
    if (
        isinstance(evidence.get("trial_budget"), int)
        and isinstance(evidence.get("trials_used"), int)
        and evidence["trials_used"] > evidence["trial_budget"]
    ):
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_TRIAL_BUDGET_EXCEEDED")

    claim_class = payload.get("claim_class")
    if claim_class not in CLAIM_CLASSES:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CLAIM_CLASS_INVALID")
    claim_level = payload.get("claim_level")
    if claim_level not in CLAIM_LEVELS:
        reasons.append("BLOCK_FACTORFORGE_RESEARCH_CLAIM_LEVEL_INVALID")
    return reasons


def validate_approach_registry(
    payload: dict[str, Any],
    *,
    stage: str,
) -> list[str]:
    reasons: list[str] = []
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        reasons.append("BLOCK_FACTORFORGE_APPROACH_REGISTRY_VERSION_INVALID")
    _require_str(
        reasons,
        payload,
        "report_id",
        "BLOCK_FACTORFORGE_APPROACH_REGISTRY_IDENTITY_MISSING",
    )
    routes = list(_iter_dicts(payload.get("routes")))
    if len(routes) < 3:
        reasons.append("BLOCK_FACTORFORGE_APPROACH_REGISTRY_ROUTE_DIVERSITY_MISSING")
    route_ids: set[str] = set()
    route_families: set[str] = set()
    route_fingerprints: set[str] = set()
    blind_context_hashes: set[str] = set()
    blind_count = 0
    for idx, route in enumerate(routes):
        route_id = route.get("route_id")
        family = route.get("route_family")
        status = route.get("status")
        if not nonempty_str(route_id):
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_INVALID:{idx}:route_id")
        elif route_id in route_ids:
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_DUPLICATE:{route_id}")
        else:
            route_ids.add(route_id)
        if not nonempty_str(family):
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_INVALID:{idx}:route_family")
        else:
            route_families.add(str(family))
        if status not in ROUTE_STATUSES:
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_STATUS_INVALID:{idx}")
        if route.get("favored_thesis_visible") is False:
            blind_count += 1
        fingerprint = route.get("route_fingerprint")
        if not sha256_value(fingerprint):
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_FINGERPRINT_INVALID:{idx}")
        elif fingerprint in route_fingerprints:
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_FINGERPRINT_DUPLICATE:{idx}")
        else:
            route_fingerprints.add(str(fingerprint))
        blind_hash = route.get("blind_context_hash")
        if not sha256_value(blind_hash):
            reasons.append(f"BLOCK_FACTORFORGE_APPROACH_ROUTE_BLIND_HASH_INVALID:{idx}")
        elif route.get("favored_thesis_visible") is False:
            if blind_hash in blind_context_hashes:
                reasons.append(
                    f"BLOCK_FACTORFORGE_APPROACH_ROUTE_BLIND_CONTEXT_DUPLICATE:{idx}"
                )
            blind_context_hashes.add(str(blind_hash))
        _require_str(
            reasons,
            route,
            "agent_identity",
            f"BLOCK_FACTORFORGE_APPROACH_ROUTE_AGENT_IDENTITY_MISSING:{idx}",
        )
        for field in (
            "research_question",
            "core_hypothesis",
            "distinct_from_other_routes",
            "exact_gap",
        ):
            _require_str(
                reasons,
                route,
                field,
                f"BLOCK_FACTORFORGE_APPROACH_ROUTE_INVALID:{idx}",
            )
        _require_list(
            reasons,
            route,
            "proof_obligation_ids",
            f"BLOCK_FACTORFORGE_APPROACH_ROUTE_INVALID:{idx}",
        )
        if status == "blocked":
            _require_str(
                reasons,
                route,
                "blocked_reason",
                f"BLOCK_FACTORFORGE_APPROACH_ROUTE_BLOCK_REASON_MISSING:{idx}",
            )
            _require_list(
                reasons,
                route,
                "reopen_only_if",
                f"BLOCK_FACTORFORGE_APPROACH_ROUTE_REOPEN_CRITERIA_MISSING:{idx}",
            )
            _require_list(
                reasons,
                route,
                "reopen_requires_delta_fields",
                f"BLOCK_FACTORFORGE_APPROACH_ROUTE_REOPEN_DELTA_POLICY_MISSING:{idx}",
            )
        if route.get("reopened_from_status") == "blocked":
            _require_sha256(
                reasons,
                route,
                "reopen_delta_hash",
                f"BLOCK_FACTORFORGE_APPROACH_ROUTE_REOPEN_DELTA_MISSING:{idx}",
            )
        if status in {"supported", "falsified", "closed"}:
            _require_list(
                reasons,
                route,
                "evidence_refs",
                f"BLOCK_FACTORFORGE_APPROACH_ROUTE_EVIDENCE_MISSING:{idx}",
            )
    if stage == "pre_council":
        missing = REQUIRED_ROUTE_FAMILIES - route_families
        if not (route_families & MEASUREMENT_ROUTE_FAMILIES):
            missing.add("mechanism_object_measurement")
        if missing:
            reasons.append(
                "BLOCK_FACTORFORGE_APPROACH_REGISTRY_CORE_FAMILIES_MISSING:"
                + ",".join(sorted(missing))
            )
        if blind_count < 2:
            reasons.append("BLOCK_FACTORFORGE_APPROACH_REGISTRY_BLIND_INDEPENDENCE_MISSING")
    return reasons


def validate_proof_obligation_ledger(
    payload: dict[str, Any],
    *,
    stage: str,
    workspace_root: Path | None = None,
) -> list[str]:
    reasons: list[str] = []
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        reasons.append("BLOCK_FACTORFORGE_PROOF_OBLIGATION_VERSION_INVALID")
    obligations = list(_iter_dicts(payload.get("obligations")))
    if not obligations:
        reasons.append("BLOCK_FACTORFORGE_PROOF_OBLIGATION_LEDGER_EMPTY")
        return reasons
    obligation_ids: set[str] = set()
    kinds: set[str] = set()
    for idx, obligation in enumerate(obligations):
        obligation_id = obligation.get("obligation_id")
        status = obligation.get("status")
        if not nonempty_str(obligation_id):
            reasons.append(f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_INVALID:{idx}:obligation_id")
        elif obligation_id in obligation_ids:
            reasons.append(f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_DUPLICATE:{obligation_id}")
        else:
            obligation_ids.add(obligation_id)
        _require_str(
            reasons,
            obligation,
            "route_id",
            f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_INVALID:{idx}",
        )
        executable = obligation.get("executable_test")
        if not isinstance(executable, dict):
            reasons.append(
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_EXECUTABLE_TEST_MISSING:{idx}"
            )
            executable = {}
        for field in ("command", "expected_output"):
            _require_str(
                reasons,
                executable,
                field,
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_EXECUTABLE_TEST_INVALID:{idx}",
            )
        timeout = executable.get("timeout_seconds")
        if not isinstance(timeout, int) or timeout < 1:
            reasons.append(
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_EXECUTABLE_TEST_INVALID:{idx}:timeout_seconds"
            )
        _require_list(
            reasons,
            obligation,
            "preregistered_thresholds",
            f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_THRESHOLDS_MISSING:{idx}",
        )
        for field in ("dataset_snapshot_hash", "window_hash"):
            _require_sha256(
                reasons,
                obligation,
                field,
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_HASH_INVALID:{idx}",
            )
        _require_str(
            reasons,
            obligation,
            "verifier_id",
            f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_VERIFIER_MISSING:{idx}",
        )
        _require_str(
            reasons,
            obligation,
            "claim",
            f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_INVALID:{idx}",
        )
        _require_str(
            reasons,
            obligation,
            "verification_method",
            f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_INVALID:{idx}",
        )
        kind = obligation.get("obligation_kind")
        if nonempty_str(kind):
            kinds.add(str(kind))
        else:
            reasons.append(f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_INVALID:{idx}:kind")
        if status not in OBLIGATION_STATUSES:
            reasons.append(f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_STATUS_INVALID:{idx}")
        if status == "passed":
            _require_list(
                reasons,
                obligation,
                "evidence_refs",
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_EVIDENCE_MISSING:{idx}",
            )
            if obligation.get("status_source") != "verifier":
                reasons.append(
                    f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_STATUS_SOURCE_INVALID:{idx}"
                )
            trusted_verifier_id = TRUSTED_OBLIGATION_VERIFIERS.get(str(kind))
            if trusted_verifier_id is None:
                reasons.append(
                    "BLOCK_FACTORFORGE_PROOF_OBLIGATION_VERIFIER_UNSUPPORTED:"
                    f"{idx}:{kind}"
                )
            elif obligation.get("verifier_id") != trusted_verifier_id:
                reasons.append(
                    "BLOCK_FACTORFORGE_PROOF_OBLIGATION_VERIFIER_UNTRUSTED:"
                    f"{idx}:{kind}"
                )
            expected_rule_hash = stable_obligation_hash(
                obligation.get("preregistered_thresholds") or []
            )
            expected_bindings = {
                "obligation_id": obligation_id,
                "obligation_kind": kind,
                "dataset_snapshot_hash": obligation.get("dataset_snapshot_hash"),
                "window_hash": obligation.get("window_hash"),
                "threshold_rule_set_sha256": expected_rule_hash,
                "verifier_contract_version": COMPONENT_VERIFIER_CONTRACT_VERSION,
            }
            for reference in obligation.get("evidence_refs") or []:
                token_prefix = (
                    "BLOCK_FACTORFORGE_PROOF_OBLIGATION_EVIDENCE_INVALID"
                    f":{idx}"
                )
                reasons.extend(
                    validate_evidence_reference(
                        reference,
                        workspace_root=workspace_root,
                        token_prefix=token_prefix,
                        allowed_verifier_ids=(
                            {trusted_verifier_id}
                            if trusted_verifier_id is not None
                            else set()
                        ),
                        expected_verifier_source_sha256=(
                            component_verifier_source_sha256()
                            if trusted_verifier_id == COMPONENT_VERIFIER_ID
                            else None
                        ),
                        expected_bindings=expected_bindings,
                    )
                )
                if (
                    trusted_verifier_id == COMPONENT_VERIFIER_ID
                    and workspace_root is not None
                    and isinstance(reference, dict)
                ):
                    evidence_path = resolve_workspace_evidence_path(
                        workspace_root,
                        reference.get("path"),
                    )
                    if evidence_path is not None and evidence_path.is_file():
                        try:
                            evidence_payload = load_json(evidence_path)
                        except Exception:
                            evidence_payload = {}
                        for replay_reason in validate_component_obligation_report(
                            evidence_payload,
                            workspace_root=workspace_root,
                        ):
                            reasons.append(f"{token_prefix}_{replay_reason}")
        if status == "blocked":
            _require_str(
                reasons,
                obligation,
                "blocked_reason",
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_BLOCK_REASON_MISSING:{idx}",
            )
    if stage in {"pre_revision", "pre_promotion", "final"}:
        required = {"economic_game", "measurement_validity", "null_alias", "information_set"}
        missing = required - kinds
        if missing:
            reasons.append(
                "BLOCK_FACTORFORGE_PROOF_OBLIGATION_CORE_KINDS_MISSING:"
                + ",".join(sorted(missing))
            )
    return reasons


def validate_counterexample_registry(
    payload: dict[str, Any],
    *,
    stage: str,
    workspace_root: Path | None = None,
) -> list[str]:
    reasons: list[str] = []
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        reasons.append("BLOCK_FACTORFORGE_COUNTEREXAMPLE_REGISTRY_VERSION_INVALID")
    counterexamples = list(_iter_dicts(payload.get("counterexamples")))
    if (
        stage in {"pre_revision", "pre_promotion", "final"}
        and len(counterexamples) < 2
    ):
        reasons.append("BLOCK_FACTORFORGE_COUNTEREXAMPLE_SEARCH_INSUFFICIENT")
    attack_types: set[str] = set()
    for idx, counterexample in enumerate(counterexamples):
        for field in (
            "counterexample_id",
            "route_id",
            "attack_type",
            "construction_or_scenario",
            "predicted_failure",
            "discriminating_test",
            "status",
            "actual_result",
        ):
            _require_str(
                reasons,
                counterexample,
                field,
                f"BLOCK_FACTORFORGE_COUNTEREXAMPLE_INVALID:{idx}",
            )
        if nonempty_str(counterexample.get("attack_type")):
            attack_types.add(str(counterexample["attack_type"]))
        if counterexample.get("status") in {"confirmed", "rejected"}:
            _require_list(
                reasons,
                counterexample,
                "evidence_refs",
                f"BLOCK_FACTORFORGE_COUNTEREXAMPLE_EVIDENCE_MISSING:{idx}",
            )
            for reference in counterexample.get("evidence_refs") or []:
                reasons.extend(
                    validate_evidence_reference(
                        reference,
                        workspace_root=workspace_root,
                        token_prefix=(
                            "BLOCK_FACTORFORGE_COUNTEREXAMPLE_EVIDENCE_INVALID"
                            f":{idx}"
                        ),
                    )
                )
    if stage in {"pre_revision", "pre_promotion", "final"}:
        if not ({"null", "alias"} & attack_types):
            reasons.append("BLOCK_FACTORFORGE_COUNTEREXAMPLE_NULL_OR_ALIAS_MISSING")
        if not ({"regime", "boundary", "payer", "measurement"} & attack_types):
            reasons.append("BLOCK_FACTORFORGE_COUNTEREXAMPLE_BOUNDARY_MISSING")
    return reasons


def _claim_level_rank(level: Any) -> int:
    try:
        return CLAIM_LEVELS.index(str(level))
    except ValueError:
        return -1


def validate_terminal_semantics(
    iteration: dict[str, Any],
    *,
    obligations: dict[str, Any] | None = None,
    workspace_root: Path | None = None,
    factor_proof_report: dict[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    judgment = iteration.get("research_judgment")
    judgment = judgment if isinstance(judgment, dict) else {}
    decision = judgment.get("decision")
    loop_action = iteration.get("loop_action")
    loop_action = loop_action if isinstance(loop_action, dict) else {}
    final = ((judgment.get("research_memo") or {}).get("final_revision_strategy") or {})
    final = final if isinstance(final, dict) else {}

    if decision in {"reject", "exhausted", "blocked"}:
        if loop_action.get("should_modify_step3b") is True:
            reasons.append("BLOCK_FACTORFORGE_TERMINAL_VERDICT_ALLOWS_STEP3B_MUTATION")
        if loop_action.get("next_runner") == "step3b":
            reasons.append("BLOCK_FACTORFORGE_TERMINAL_VERDICT_HAS_STEP3B_NEXT_RUNNER")
        if loop_action.get("parallel_exploration_branches"):
            reasons.append("BLOCK_FACTORFORGE_TERMINAL_VERDICT_HAS_ACTIVE_BRANCHES")
        if final.get("loop_authorization") == "approved_for_step3b_handoff":
            reasons.append("BLOCK_FACTORFORGE_TERMINAL_VERDICT_HAS_ACTIVE_HANDOFF")

    claim_level = (
        judgment.get("mechanism_claim_level")
        or (judgment.get("research_memo") or {}).get("mechanism_claim_level")
        or iteration.get("mechanism_claim_level")
    )
    if decision == "promote_official" and _claim_level_rank(claim_level) < _claim_level_rank(
        "component_validated"
    ):
        reasons.append("BLOCK_FACTORFORGE_PROMOTION_WITHOUT_COMPONENT_VALIDATION")

    obligation_rows = list(_iter_dicts((obligations or {}).get("obligations")))
    passed_kinds: set[str] = set()
    for idx, row in enumerate(obligation_rows):
        if row.get("status") != "passed" or row.get("status_source") != "verifier":
            continue
        evidence_reasons: list[str] = []
        evidence_refs = row.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            continue
        trusted_verifier_id = TRUSTED_OBLIGATION_VERIFIERS.get(
            str(row.get("obligation_kind"))
        )
        if trusted_verifier_id is None or row.get("verifier_id") != trusted_verifier_id:
            continue
        expected_bindings = {
            "obligation_id": row.get("obligation_id"),
            "obligation_kind": row.get("obligation_kind"),
            "dataset_snapshot_hash": row.get("dataset_snapshot_hash"),
            "window_hash": row.get("window_hash"),
            "threshold_rule_set_sha256": stable_obligation_hash(
                row.get("preregistered_thresholds") or []
            ),
            "verifier_contract_version": COMPONENT_VERIFIER_CONTRACT_VERSION,
        }
        for reference in evidence_refs:
            token_prefix = (
                f"BLOCK_FACTORFORGE_PROOF_OBLIGATION_EVIDENCE_INVALID:{idx}"
            )
            evidence_reasons.extend(
                validate_evidence_reference(
                    reference,
                    workspace_root=workspace_root,
                    token_prefix=token_prefix,
                    allowed_verifier_ids={trusted_verifier_id},
                    expected_verifier_source_sha256=(
                        component_verifier_source_sha256()
                    ),
                    expected_bindings=expected_bindings,
                )
            )
            if (
                workspace_root is not None
                and isinstance(reference, dict)
            ):
                evidence_path = resolve_workspace_evidence_path(
                    workspace_root,
                    reference.get("path"),
                )
                if evidence_path is not None and evidence_path.is_file():
                    try:
                        evidence_payload = load_json(evidence_path)
                    except Exception:
                        evidence_payload = {}
                    evidence_reasons.extend(
                        validate_component_obligation_report(
                            evidence_payload,
                            workspace_root=workspace_root,
                        )
                    )
        if not evidence_reasons:
            passed_kinds.add(str(row.get("obligation_kind")))
    proof_accept = (factor_proof_report or {}).get("verdict") == "ACCEPT"
    if _claim_level_rank(claim_level) >= _claim_level_rank("metric_consistent"):
        if not proof_accept:
            reasons.append("BLOCK_FACTORFORGE_METRIC_CLAIM_WITHOUT_ACCEPTED_FACTOR_PROOF")
    if _claim_level_rank(claim_level) >= _claim_level_rank("component_validated"):
        required = {"measurement_validity", "component_ablation"}
        if not required.issubset(passed_kinds):
            reasons.append(
                "BLOCK_FACTORFORGE_COMPONENT_CLAIM_WITHOUT_PASSED_ABLATION"
            )
    if claim_level == "payer_validated" and "payer" not in passed_kinds:
        reasons.append("BLOCK_FACTORFORGE_PAYER_CLAIM_WITHOUT_PASSED_OBLIGATION")
    if claim_level == "stochastic_validated":
        required = {"state_transition", "conditional_distribution", "tail_or_barrier"}
        if not required.issubset(passed_kinds):
            reasons.append("BLOCK_FACTORFORGE_STOCHASTIC_CLAIM_WITHOUT_PASSED_OBLIGATIONS")
    if decision == "promote_official":
        if not proof_accept:
            reasons.append("BLOCK_FACTORFORGE_PROMOTION_WITHOUT_ACCEPTED_FACTOR_PROOF")
        if not {"measurement_validity", "component_ablation"}.issubset(passed_kinds):
            reasons.append("BLOCK_FACTORFORGE_PROMOTION_WITHOUT_VERIFIED_COMPONENT_ABLATION")
    return reasons


def validate_root_synthesis(
    synthesis: dict[str, Any],
    approval: dict[str, Any],
    *,
    approach_registry: dict[str, Any] | None,
    council_summary: dict[str, Any] | None,
    workspace_root: Path,
    synthesis_path: Path,
) -> list[str]:
    reasons: list[str] = []
    expected_routes = {
        str(route.get("route_id"))
        for route in _iter_dicts((approach_registry or {}).get("routes"))
        if nonempty_str(route.get("route_id"))
    }
    comparisons = list(_iter_dicts(synthesis.get("route_comparison")))
    compared_routes = {
        str(row.get("route_id"))
        for row in comparisons
        if nonempty_str(row.get("route_id"))
    }
    if not expected_routes or compared_routes != expected_routes:
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_ROUTE_COVERAGE_MISMATCH")
    for idx, row in enumerate(comparisons):
        if row.get("disposition") not in {
            "selected",
            "rejected",
            "blocked",
            "carry_forward",
        }:
            reasons.append(f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_DISPOSITION_INVALID:{idx}")
        for field in ("reason", "exact_gap_or_closed_obligation"):
            _require_str(
                reasons,
                row,
                field,
                f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_ROUTE_UNDERSPECIFIED:{idx}",
            )
    if synthesis.get("selection_rule") in {
        "majority_vote",
        "agent_count",
        "consensus_only",
    }:
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_MAJORITY_VOTE_FORBIDDEN")
    _require_str(
        reasons,
        synthesis,
        "dissent_resolution",
        "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_DISSENT_MISSING",
    )
    selected = synthesis.get("selected_revision")
    if not isinstance(selected, dict):
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SELECTED_REVISION_MISSING")
        selected = {}
    source_route_ids = selected.get("source_route_ids")
    if (
        not isinstance(source_route_ids, list)
        or not source_route_ids
        or not set(str(value) for value in source_route_ids).issubset(expected_routes)
    ):
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_ROUTES_INVALID")
    source_hashes = selected.get("source_result_hashes")
    if not isinstance(source_hashes, list) or not source_hashes:
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_HASHES_MISSING")
    else:
        for idx, value in enumerate(source_hashes):
            if not sha256_value(value):
                reasons.append(
                    f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_HASH_INVALID:{idx}"
                )
    summary_routes = list(
        _iter_dicts((council_summary or {}).get("research_route_summary"))
    )
    selected_route_ids = {
        str(value) for value in source_route_ids or [] if nonempty_str(value)
    }
    bound_summary_routes = [
        row
        for row in summary_routes
        if row.get("route_id") in selected_route_ids
    ]
    expected_result_hashes = {
        str(row.get("source_result_sha256"))
        for row in bound_summary_routes
        if sha256_value(row.get("source_result_sha256"))
    }
    if (
        not selected_route_ids
        or {str(row.get("route_id")) for row in bound_summary_routes}
        != selected_route_ids
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_COUNCIL_ROUTE_BINDING_MISSING"
        )
    if (
        not isinstance(source_hashes, list)
        or set(str(value) for value in source_hashes) != expected_result_hashes
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_COUNCIL_RESULT_HASH_MISMATCH"
        )
    loaded_results: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(bound_summary_routes):
        raw_path = row.get("source_result_path") or row.get("source_path")
        result_path = resolve_workspace_evidence_path(workspace_root, raw_path)
        if result_path is None or not result_path.is_file():
            reasons.append(
                f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_RESULT_MISSING:{idx}"
            )
            continue
        actual_hash = sha256_file(result_path)
        expected_hash = row.get("source_result_sha256")
        if actual_hash != expected_hash:
            reasons.append(
                f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_RESULT_HASH_MISMATCH:{idx}"
            )
            continue
        try:
            result_payload = load_json(result_path)
        except Exception:
            reasons.append(
                f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_RESULT_INVALID:{idx}"
            )
            continue
        validator_path = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "factor-forge-step6"
            / "scripts"
            / "validate_agentic_council_result.py"
        )
        validator_env = os.environ.copy()
        validator_env["FACTORFORGE_ROOT"] = str(workspace_root)
        validator = subprocess.run(
            [
                sys.executable,
                str(validator_path),
                "--report-id",
                str(synthesis.get("report_id") or ""),
                "--result-path",
                str(result_path),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=validator_env,
            text=True,
            capture_output=True,
        )
        if validator.returncode != 0:
            reasons.append(
                "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_RESULT_VALIDATION_FAILED:"
                f"{idx}"
            )
            continue
        route = result_payload.get("approach_route")
        route = route if isinstance(route, dict) else {}
        if route.get("route_id") != row.get("route_id"):
            reasons.append(
                f"BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_RESULT_ROUTE_MISMATCH:{idx}"
            )
        loaded_results[actual_hash] = result_payload
    law_id = selected.get("law_id")
    law_index = list(_iter_dicts((council_summary or {}).get("candidate_law_index")))
    selected_law = next(
        (
            row
            for row in law_index
            if row.get("law_id") == law_id
            and row.get("route_id") in selected_route_ids
            and row.get("source_result_sha256") in expected_result_hashes
        ),
        None,
    )
    if selected_law is None:
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_LAW_SOURCE_BINDING_MISSING")
    elif selected.get("law_or_formula_hash") != selected_law.get("law_hash"):
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_LAW_SOURCE_HASH_MISMATCH")
    elif selected_law.get("source_result_sha256") in loaded_results:
        source_result = loaded_results[str(selected_law["source_result_sha256"])]
        source_law = next(
            (
                row
                for row in _iter_dicts(source_result.get("candidate_revision_laws"))
                if row.get("law_id") == law_id
            ),
            None,
        )
        if (
            source_law is None
            or stable_obligation_hash(source_law) != selected_law.get("law_hash")
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_LAW_NOT_IN_SOURCE_RESULT"
            )
    _require_sha256(
        reasons,
        selected,
        "law_or_formula_hash",
        "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_LAW_HASH_INVALID",
    )
    if not isinstance(selected.get("open_proof_obligation_ids"), list):
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_OPEN_OBLIGATIONS_MISSING")
    if approval.get("approval_source") in {
        None,
        "",
        "current_main_agent_default_approval",
        "automatic",
    }:
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_EXPLICIT_APPROVAL_MISSING")
    if approval.get("synthesis_sha256") != sha256_file(synthesis_path):
        reasons.append("BLOCK_FACTORFORGE_ROOT_SYNTHESIS_APPROVAL_HASH_MISMATCH")
    return reasons


def validate_terminal_council_rejection(
    rejection: dict[str, Any],
    *,
    root: Path,
    report_id: str,
    council_summary_path: Path,
    iteration: dict[str, Any] | None,
    factor_proof_report: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if rejection.get("terminal_rejection_version") != (
        "factorforge_terminal_council_rejection_v1"
    ):
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_VERSION_INVALID")
    if rejection.get("report_id") != report_id:
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_IDENTITY_MISMATCH")

    bindings = (
        ("summary_path", "summary_sha256", council_summary_path),
        (
            "collection_path",
            "collection_sha256",
            council_summary_path.parent
            / f"agentic_result_collection__{report_id}.json",
        ),
        (
            "factor_proof_path",
            "factor_proof_sha256",
            factor_proof_certificate_path(root, report_id),
        ),
        (
            "dispatch_manifest_path",
            "dispatch_manifest_sha256",
            council_summary_path.parent / f"dispatch_manifest__{report_id}.json",
        ),
    )
    for path_field, hash_field, expected_path in bindings:
        path = resolve_workspace_evidence_path(root, rejection.get(path_field))
        if path is None or not path.is_file() or path.is_symlink():
            reasons.append(
                f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_BINDING_MISSING:{path_field}"
            )
            continue
        if expected_path is not None and path.resolve(strict=False) != expected_path.resolve(
            strict=False
        ):
            reasons.append(
                f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_BINDING_PATH_MISMATCH:{path_field}"
            )
        if rejection.get(hash_field) != sha256_file(path):
            reasons.append(
                f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_BINDING_HASH_MISMATCH:{path_field}"
            )

    selected = rejection.get("selected_agent_result_ids")
    recommendations = rejection.get("terminal_recommendations")
    if (
        not isinstance(selected, list)
        or not selected
        or len(set(str(value) for value in selected)) != len(selected)
    ):
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULTS_MISSING")
    if not isinstance(recommendations, list) or len(recommendations) != len(selected or []):
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULTS_MISMATCH")
    elif isinstance(selected, list):
        recommendation_ids = {
            str(row.get("task_id"))
            for row in recommendations
            if isinstance(row, dict) and nonempty_str(row.get("task_id"))
        }
        terminal_recommendations = [
            row
            for row in recommendations
            if isinstance(row, dict)
            and str(row.get("recommendation") or "").strip().lower()
            in TERMINAL_RECOMMENDATION_VALUES
        ]
        if (
            recommendation_ids != {str(value) for value in selected}
            or len(terminal_recommendations) != len(recommendations)
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RECOMMENDATIONS_INVALID"
            )
    result_bindings = rejection.get("agent_result_bindings")
    if (
        not isinstance(result_bindings, list)
        or not result_bindings
        or len(result_bindings) != len(selected or [])
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_BINDINGS_MISSING"
        )
    else:
        canonical_collection_path = (
            council_summary_path.parent
            / f"agentic_result_collection__{report_id}.json"
        )
        try:
            collection = load_json(canonical_collection_path)
        except Exception:
            collection = {}
            reasons.append(
                "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_COLLECTION_INVALID"
            )
        valid_results = collection.get("valid_results")
        dispatch_path = (
            council_summary_path.parent / f"dispatch_manifest__{report_id}.json"
        )
        try:
            dispatch = load_json(dispatch_path)
        except Exception:
            dispatch = {}
            reasons.append(
                "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_DISPATCH_INVALID"
            )
        required_tasks = [
            task
            for task in dispatch.get("agent_tasks") or []
            if isinstance(task, dict) and task.get("required") is True
        ]
        required_ids = [str(task.get("task_id") or "") for task in required_tasks]
        valid_ids = [
            str(row.get("task_id") or "")
            for row in valid_results or []
            if isinstance(row, dict)
        ]
        if (
            collection.get("collection_version")
            != "factorforge_agentic_council_result_collection_v1"
            or collection.get("report_id") != report_id
            or collection.get("status") != "complete"
            or collection.get("ready_for_finalize") is not True
            or not isinstance(valid_results, list)
            or collection.get("valid_result_count") != len(valid_results or [])
            or collection.get("required_result_count") != len(required_tasks)
            or collection.get("present_result_count") != len(required_tasks)
            or collection.get("valid_result_count") != len(required_tasks)
            or collection.get("invalid_result_count") != 0
            or collection.get("missing_result_count") != 0
            or dispatch.get("dispatch_manifest_version")
            != "factorforge_agentic_council_dispatch_manifest_v1"
            or dispatch.get("report_id") != report_id
            or not required_ids
            or any(not task_id for task_id in required_ids)
            or len(set(required_ids)) != len(required_ids)
            or len(valid_ids) != len(required_ids)
            or set(valid_ids) != set(required_ids)
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_COLLECTION_INVALID"
            )
            valid_results = []
        collection_paths: dict[str, Path] = {}
        required_paths = {
            str(task.get("task_id")): resolve_workspace_evidence_path(
                root,
                task.get("expected_result_path"),
            )
            for task in required_tasks
        }
        for row in valid_results:
            if not isinstance(row, dict) or row.get("status") != "final":
                continue
            task_id = str(row.get("task_id") or "")
            result_path = resolve_workspace_evidence_path(
                root,
                row.get("result_path"),
            )
            if (
                task_id
                and result_path is not None
                and required_paths.get(task_id) == result_path
            ):
                collection_paths[task_id] = result_path

        recommendation_map = {
            str(row.get("task_id")): str(row.get("recommendation") or "")
            .strip()
            .lower()
            for row in recommendations or []
            if isinstance(row, dict) and nonempty_str(row.get("task_id"))
        }
        bound_ids: set[str] = set()
        bound_paths: set[Path] = set()
        validator_path = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "factor-forge-step6"
            / "scripts"
            / "validate_agentic_council_result.py"
        )
        for idx, binding in enumerate(result_bindings):
            if not isinstance(binding, dict):
                reasons.append(
                    f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_BINDING_INVALID:{idx}"
                )
                continue
            task_id = str(binding.get("task_id") or "")
            recommendation = str(binding.get("recommendation") or "").strip().lower()
            result_path = resolve_workspace_evidence_path(
                root,
                binding.get("result_path"),
            )
            if (
                not task_id
                or task_id in bound_ids
                or recommendation not in TERMINAL_RECOMMENDATION_VALUES
                or recommendation_map.get(task_id) != recommendation
                or result_path is None
                or not result_path.is_file()
                or result_path.is_symlink()
                or collection_paths.get(task_id) != result_path
            ):
                reasons.append(
                    f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_BINDING_INVALID:{idx}"
                )
                continue
            bound_ids.add(task_id)
            bound_paths.add(result_path)
            if binding.get("result_sha256") != sha256_file(result_path):
                reasons.append(
                    f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_HASH_MISMATCH:{idx}"
                )
                continue
            try:
                result_payload = load_json(result_path)
            except Exception:
                reasons.append(
                    f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_INVALID:{idx}"
                )
                continue
            payload_recommendation = str(
                ((result_payload.get("revision_or_kill_recommendation") or {}).get(
                    "recommendation"
                ))
                or ""
            ).strip().lower()
            if (
                result_payload.get("report_id") != report_id
                or result_payload.get("task_id") != task_id
                or payload_recommendation != recommendation
            ):
                reasons.append(
                    f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_IDENTITY_MISMATCH:{idx}"
                )
                continue
            validator_env = os.environ.copy()
            validator_env["FACTORFORGE_ROOT"] = str(root)
            validator = subprocess.run(
                [
                    sys.executable,
                    str(validator_path),
                    "--report-id",
                    report_id,
                    "--result-path",
                    str(result_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=validator_env,
                text=True,
                capture_output=True,
            )
            if validator.returncode != 0:
                reasons.append(
                    f"BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_VALIDATION_FAILED:{idx}"
                )
        declared_paths = {
            path
            for raw_path in rejection.get("agent_result_paths") or []
            if (path := resolve_workspace_evidence_path(root, raw_path)) is not None
        }
        if (
            bound_ids != {str(value) for value in selected or []}
            or bound_paths != declared_paths
            or bound_ids != set(collection_paths)
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_RESULT_SET_MISMATCH"
            )
    proof_report = factor_proof_report or {}
    if (
        rejection.get("factor_proof_verdict") != "REJECT"
        or proof_report.get("verdict") != "REJECT"
        or proof_report.get("block_reasons")
    ):
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_PROOF_NOT_REJECTED")
    iteration_decision = (
        ((iteration or {}).get("research_judgment") or {}).get("decision")
        if isinstance((iteration or {}).get("research_judgment"), dict)
        else None
    )
    if rejection.get("iteration_decision") != "reject" or iteration_decision != "reject":
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_ITERATION_MISMATCH")
    if rejection.get("canonical_write_permission") is not False:
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_CANONICAL_WRITE")
    if rejection.get("execution_allowed_by_default") is not False:
        reasons.append("BLOCK_FACTORFORGE_TERMINAL_COUNCIL_REJECTION_EXECUTION_ALLOWED")
    return reasons


def research_protocol_paths(root: Path, report_id: str) -> dict[str, Path]:
    base = root / "objects" / "research_protocol"
    return {
        "state": base / f"research_state__{report_id}.json",
        "conjecture": base / f"research_conjecture__{report_id}.json",
        "approaches": base / f"approach_registry__{report_id}.json",
        "obligations": base / f"proof_obligation_ledger__{report_id}.json",
        "counterexamples": base / f"counterexample_registry__{report_id}.json",
        "factor_proof": factor_proof_certificate_path(root, report_id),
        "root_synthesis": (
            root
            / "objects"
            / "research_iteration_master"
            / "revision_council"
            / report_id
            / f"main_agent_council_synthesis__{report_id}.json"
        ),
        "root_synthesis_approval": (
            root
            / "objects"
            / "research_iteration_master"
            / "revision_council"
            / report_id
            / f"main_agent_council_synthesis_approval__{report_id}.json"
        ),
        "terminal_rejection": (
            root
            / "objects"
            / "research_iteration_master"
            / "revision_council"
            / report_id
            / f"terminal_council_rejection__{report_id}.json"
        ),
        "council_summary": (
            root
            / "objects"
            / "research_iteration_master"
            / "revision_council"
            / report_id
            / f"revision_council_summary__{report_id}.json"
        ),
        "verifier": base / f"semantic_verifier_report__{report_id}.json",
    }


def validate_protocol_bundle(
    *,
    root: Path,
    report_id: str,
    stage: str,
    iteration_path: Path | None = None,
    iteration_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in {
        "pre_council",
        "pre_revision",
        "pre_promotion",
        "final",
    }:
        raise ValueError(f"unsupported research protocol stage: {stage}")
    paths = research_protocol_paths(root, report_id)
    reasons: list[str] = []
    artifacts: dict[str, Any] = {}
    required = ["state", "conjecture", "approaches"]
    if stage in {"pre_revision", "pre_promotion", "final"}:
        required.extend(["obligations", "counterexamples"])
    if stage in {"pre_promotion", "final"}:
        required.append("factor_proof")
    if stage == "final":
        required.append("council_summary")
        if paths["terminal_rejection"].is_file():
            required.append("terminal_rejection")
        else:
            required.extend(["root_synthesis", "root_synthesis_approval"])
    for key in required:
        path = paths[key]
        if not path.exists():
            reasons.append(f"BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_ARTIFACT_MISSING:{key}")
            continue
        try:
            artifacts[key] = load_json(path)
        except Exception as exc:
            reasons.append(f"BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_ARTIFACT_INVALID:{key}:{exc}")

    for key, artifact in artifacts.items():
        artifact_report_id = artifact.get("report_id")
        if artifact_report_id is not None and artifact_report_id != report_id:
            reasons.append(
                f"BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_REPORT_ID_MISMATCH:{key}"
            )
    if "state" in artifacts:
        reasons.extend(validate_research_state(artifacts["state"]))
    if "conjecture" in artifacts:
        reasons.extend(validate_research_conjecture(artifacts["conjecture"]))
    if "approaches" in artifacts:
        reasons.extend(validate_approach_registry(artifacts["approaches"], stage=stage))
    if "obligations" in artifacts:
        reasons.extend(
            validate_proof_obligation_ledger(
                artifacts["obligations"],
                stage=stage,
                workspace_root=root,
            )
        )
    if "counterexamples" in artifacts:
        reasons.extend(
            validate_counterexample_registry(
                artifacts["counterexamples"],
                stage=stage,
                workspace_root=root,
            )
        )
    factor_proof_report: dict[str, Any] | None = None
    if "factor_proof" in artifacts:
        conjecture_for_proof = artifacts.get("conjecture")
        expected_factor_id = (
            conjecture_for_proof.get("factor_id")
            if isinstance(conjecture_for_proof, dict)
            else None
        )
        factor_proof_report = validate_factor_proof_certificate(
            artifacts["factor_proof"],
            workspace_root=root,
            expected_report_id=report_id,
            expected_factor_id=expected_factor_id,
        )
        if factor_proof_report.get("verdict") == "BLOCK":
            reasons.extend(factor_proof_report.get("block_reasons") or [])
    conjecture = artifacts.get("conjecture")
    if isinstance(conjecture, dict):
        expected_factor_id = conjecture.get("factor_id")
        conjecture_identity = (
            conjecture.get("identity")
            if isinstance(conjecture.get("identity"), dict)
            else {}
        )
        state = artifacts.get("state")
        if isinstance(state, dict):
            if state.get("factor_id") != expected_factor_id:
                reasons.append(
                    "BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_FACTOR_ID_MISMATCH:state"
                )
            for field in ("research_id", "round_id"):
                if state.get(field) != conjecture_identity.get(field):
                    reasons.append(
                        "BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_LINEAGE_MISMATCH:"
                        f"{field}"
                    )
        factor_proof = artifacts.get("factor_proof")
        if isinstance(factor_proof, dict):
            if factor_proof.get("factor_id") != expected_factor_id:
                reasons.append(
                    "BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_FACTOR_ID_MISMATCH:"
                    "factor_proof"
                )
            if factor_proof.get("claim_class") != conjecture.get("claim_class"):
                reasons.append(
                    "BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_CLAIM_CLASS_MISMATCH"
                )
    if "root_synthesis" in artifacts and "root_synthesis_approval" in artifacts:
        reasons.extend(
            validate_root_synthesis(
                artifacts["root_synthesis"],
                artifacts["root_synthesis_approval"],
                approach_registry=artifacts.get("approaches"),
                council_summary=artifacts.get("council_summary"),
                workspace_root=root,
                synthesis_path=paths["root_synthesis"],
            )
        )
    iteration: dict[str, Any] | None = iteration_payload
    if iteration is None and stage in {"pre_promotion", "final"}:
        path = iteration_path
        if path is None:
            path = (
                root
                / "objects"
                / "research_iteration_master"
                / f"research_iteration_master__{report_id}.json"
            )
        if path.exists():
            try:
                iteration = load_json(path)
            except Exception as exc:
                reasons.append(f"BLOCK_FACTORFORGE_RESEARCH_ITERATION_INVALID:{exc}")
        else:
            reasons.append("BLOCK_FACTORFORGE_RESEARCH_ITERATION_MISSING")
    if "terminal_rejection" in artifacts:
        reasons.extend(
            validate_terminal_council_rejection(
                artifacts["terminal_rejection"],
                root=root,
                report_id=report_id,
                council_summary_path=paths["council_summary"],
                iteration=iteration,
                factor_proof_report=factor_proof_report,
            )
        )
    if stage in {"pre_promotion", "final"}:
        if isinstance(iteration, dict):
            reasons.extend(
                validate_terminal_semantics(
                    iteration,
                    obligations=artifacts.get("obligations"),
                    workspace_root=root,
                    factor_proof_report=factor_proof_report,
                )
            )
        elif iteration is not None:
            reasons.append("BLOCK_FACTORFORGE_RESEARCH_ITERATION_INVALID")

    deduped = list(dict.fromkeys(reasons))
    return {
        "protocol_version": PROTOCOL_VERSION,
        "report_id": report_id,
        "stage": stage,
        "verdict": "BLOCK" if deduped else "PASS",
        "block_reasons": deduped,
        "artifact_paths": {key: str(value) for key, value in paths.items()},
    }
