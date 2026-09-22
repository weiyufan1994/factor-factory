from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd

from factor_factory.evo_oos import (
    consume_oos_allocation_for_release,
    formal_oos_incident_reasons,
    validate_oos_release_preflight,
    validate_oos_release_consumption,
    validate_oos_release_consumption_structural,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
)


SEARCH_TRIAL_LEDGER_VERSION = "factorforge_search_trial_ledger_v1"
OOS_RELEASE_MANIFEST_VERSION = "factorforge_oos_release_manifest_v1"
METRIC_VERIFIER_SPEC_VERSION = "factorforge_metric_verifier_spec_v2"
COMPONENT_VERIFIER_SPEC_VERSION = "factorforge_component_obligation_spec_v1"
METRIC_THRESHOLD_REGISTRATION_VERSION = (
    "factorforge_threshold_registration_v2"
)
COMPONENT_THRESHOLD_REGISTRATION_VERSION = (
    "factorforge_component_obligation_threshold_registration_v1"
)
MINIMUM_FORMAL_DAILY_PERIODS = 60
SHA256_HEX_LENGTH = 64
METRIC_CLAIM_CLASSES = {
    "risk_premium",
    "information_rent",
    "liquidity_rent",
    "institutional_constraint_rent",
    "behavioral_rent",
    "time_option_rent",
    "mixed",
    "unknown",
}
METRIC_REQUIRED_DECISION_PATHS = {
    "ic": {"metrics.ic.mean"},
    "icir": {"metrics.icir.value"},
    "volatility_cost": {
        "metrics.volatility_cost.realized_volatility_drag"
    },
    "transaction_cost": {
        "metrics.transaction_cost.net_return_annual"
    },
    "drawdown": {"metrics.drawdown.max_drawdown"},
    "long_end": {"metrics.long_end.net_geometric_return_annual"},
    "fama_macbeth": {"metrics.fama_macbeth.lambda_tstat"},
    "bucket_monotonicity": {
        "metrics.bucket_monotonicity.monotonicity_score"
    },
}
METRIC_ALLOWED_DECISION_PATHS = set().union(
    *METRIC_REQUIRED_DECISION_PATHS.values()
).union(
    {
        "metrics.volatility_cost.geometric_return_annual",
        "metrics.transaction_cost.modeled_cost_annual",
        "metrics.drawdown.recovery_days",
        "metrics.drawdown.recovery_area",
        "metrics.long_end.sharpe_net",
        "metrics.long_end.coverage",
        "metrics.long_end.terminal_wealth",
        "metrics.long_end.minimum_wealth",
        "metrics.control_residualization.residual_rank_ic_mean",
        "metrics.fama_macbeth.lambda_mean",
        "metrics.bucket_monotonicity.adjacent_pairs_violated",
    }
)
METRIC_CORE_RULE_GUARDRAILS = {
    "metrics.ic.mean": ({">", ">="}, 0.0, None),
    "metrics.icir.value": ({">", ">="}, 0.0, None),
    "metrics.volatility_cost.realized_volatility_drag": (
        {"<", "<="},
        0.0,
        None,
    ),
    "metrics.transaction_cost.net_return_annual": (
        {">", ">="},
        0.0,
        None,
    ),
    "metrics.drawdown.max_drawdown": ({">", ">="}, -0.8, 0.0),
    "metrics.long_end.net_geometric_return_annual": (
        {">", ">="},
        0.0,
        None,
    ),
    "metrics.fama_macbeth.lambda_tstat": ({">", ">="}, 0.0, None),
    "metrics.bucket_monotonicity.monotonicity_score": (
        {">", ">="},
        0.5,
        1.0,
    ),
}
COMPONENT_SUPPORTED_OBLIGATION_KINDS = {
    "measurement_validity",
    "component_ablation",
}
COMPONENT_ALLOWED_DECISION_PATHS = {
    "metrics.full_rank_ic_mean",
    "metrics.ablated_rank_ic_mean",
    "metrics.residual_rank_ic_mean",
    "metrics.rank_ic_delta",
    "metrics.full_long_end_mean",
    "metrics.ablated_long_end_mean",
    "metrics.long_end_delta",
}
COMPONENT_REQUIRED_DECISION_PATHS = {
    "measurement_validity": {
        "metrics.full_rank_ic_mean",
        "metrics.residual_rank_ic_mean",
    },
    "component_ablation": {
        "metrics.rank_ic_delta",
        "metrics.long_end_delta",
    },
}
DECISION_OPERATORS = {">", ">=", "<", "<=", "==", "abs>=", "abs<="}


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _write_immutable_json(
    path: Path,
    payload: dict[str, Any],
    *,
    block_token: str,
) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
        return
    except FileExistsError:
        pass
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(block_token) from exc
    if existing != payload:
        raise ValueError(block_token)


def evaluation_contract_hash(spec: dict[str, Any]) -> str:
    version = spec.get("version")
    common = {
        "version": version,
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "window_contract": spec.get("window_contract"),
        "panel": spec.get("panel"),
        "threshold_registration_ref": spec.get(
            "threshold_registration_ref"
        ),
    }
    if version == METRIC_VERIFIER_SPEC_VERSION:
        common.update(
            {
                "claim_class": spec.get("claim_class"),
                "cost_policy_id": spec.get("cost_policy_id"),
                "portfolio": spec.get("portfolio"),
                "label_contract": spec.get("label_contract"),
                "fama_macbeth": spec.get("fama_macbeth"),
                "bucket_monotonicity": spec.get("bucket_monotonicity"),
            }
        )
    elif version == COMPONENT_VERIFIER_SPEC_VERSION:
        common.update(
            {
                "obligation_id": spec.get("obligation_id"),
                "obligation_kind": spec.get("obligation_kind"),
                "test": spec.get("test"),
            }
        )
    else:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFIER_SPEC_UNSUPPORTED"
        )
    return stable_hash(common)


def valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_HEX_LENGTH
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _validate_metric_decision_rules(
    spec: dict[str, Any],
    decision_rules: list[dict[str, Any]],
) -> None:
    claim_class = spec.get("claim_class")
    if claim_class not in METRIC_CLAIM_CLASSES:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_CLAIM_CLASS_INVALID"
        )
    rule_ids: set[str] = set()
    rule_paths: set[str] = set()
    for index, rule in enumerate(decision_rules):
        if not isinstance(rule, dict):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_INVALID:"
                f"{index}"
            )
        rule_id = rule.get("rule_id")
        metric_path = rule.get("metric_path")
        operator = rule.get("operator")
        threshold = _finite_number(rule.get("threshold"))
        on_fail = rule.get("on_fail")
        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
            or rule_id in rule_ids
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_ID_INVALID:"
                f"{index}"
            )
        rule_ids.add(rule_id)
        if metric_path not in METRIC_ALLOWED_DECISION_PATHS:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_PATH_INVALID:"
                f"{index}"
            )
        rule_paths.add(str(metric_path))
        if (
            operator not in DECISION_OPERATORS
            or threshold is None
            or on_fail not in {"REJECT", "INCONCLUSIVE", "BLOCK"}
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_INVALID:"
                f"{index}"
            )
        guardrail = METRIC_CORE_RULE_GUARDRAILS.get(str(metric_path))
        if guardrail is not None:
            operators, minimum, maximum = guardrail
            if (
                operator not in operators
                or threshold < minimum
                or (maximum is not None and threshold > maximum)
            ):
                raise ValueError(
                    "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_GUARDRAIL_INVALID:"
                    f"{rule_id}"
                )
    required = {
        family: paths
        for family, paths in METRIC_REQUIRED_DECISION_PATHS.items()
        if (
            claim_class == "risk_premium"
            or family not in {"fama_macbeth", "bucket_monotonicity"}
        )
    }
    for family, paths in required.items():
        if not rule_paths.intersection(paths):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_COVERAGE_MISSING:"
                f"{family}"
            )
    if claim_class != "risk_premium":
        forbidden = {
            path
            for family in ("fama_macbeth", "bucket_monotonicity")
            for path in METRIC_REQUIRED_DECISION_PATHS[family]
        }
        if rule_paths.intersection(forbidden):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RISK_PREMIUM_RULE_FORBIDDEN"
            )


def _validate_component_decision_rules(
    spec: dict[str, Any],
    decision_rules: list[dict[str, Any]],
) -> None:
    obligation_kind = spec.get("obligation_kind")
    if obligation_kind not in COMPONENT_SUPPORTED_OBLIGATION_KINDS:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_OBLIGATION_KIND_INVALID"
        )
    rule_ids: set[str] = set()
    rule_paths: set[str] = set()
    for index, rule in enumerate(decision_rules):
        if not isinstance(rule, dict):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_INVALID:"
                f"{index}"
            )
        rule_id = rule.get("rule_id")
        metric_path = rule.get("metric_path")
        operator = rule.get("operator")
        threshold = _finite_number(rule.get("threshold"))
        if (
            not isinstance(rule_id, str)
            or not rule_id.strip()
            or rule_id in rule_ids
        ):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_ID_INVALID:"
                f"{index}"
            )
        rule_ids.add(rule_id)
        if metric_path not in COMPONENT_ALLOWED_DECISION_PATHS:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_PATH_INVALID:"
                f"{index}"
            )
        rule_paths.add(str(metric_path))
        if operator not in {">", ">="} or threshold is None or threshold < 0:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_GUARDRAIL_INVALID:"
                f"{rule_id}"
            )
    missing = (
        COMPONENT_REQUIRED_DECISION_PATHS[str(obligation_kind)] - rule_paths
    )
    if missing:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_COVERAGE_MISSING:"
            + ",".join(sorted(missing))
        )


def validate_threshold_decision_rules(
    spec: dict[str, Any],
    decision_rules: Any,
) -> None:
    if not isinstance(decision_rules, list) or not decision_rules:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULES_MISSING"
        )
    version = spec.get("version")
    if version == METRIC_VERIFIER_SPEC_VERSION:
        _validate_metric_decision_rules(spec, decision_rules)
        return
    if version == COMPONENT_VERIFIER_SPEC_VERSION:
        _validate_component_decision_rules(spec, decision_rules)
        return
    raise ValueError(
        "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFIER_SPEC_UNSUPPORTED"
    )


def write_search_trial_ledger(
    path: Path,
    *,
    report_id: str,
    factor_id: str,
    trials: list[dict[str, Any]],
    candidate_space: Any,
    selected_hypothesis: Any,
    freeze_sequence: int = 10,
) -> dict[str, Any]:
    payload = {
        "version": SEARCH_TRIAL_LEDGER_VERSION,
        "search_status": "FROZEN",
        "report_id": report_id,
        "factor_id": factor_id,
        "freeze_sequence": freeze_sequence,
        "trial_count": len(trials),
        "trials": trials,
        "trial_set_sha256": stable_hash(trials),
        "candidate_space_sha256": stable_hash(candidate_space),
        "selected_hypothesis_sha256": stable_hash(selected_hypothesis),
    }
    _write_immutable_json(
        path,
        payload,
        block_token=(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_SEARCH_LEDGER_IMMUTABLE"
        ),
    )
    return payload


def write_threshold_registration(
    path: Path,
    *,
    workspace_root: Path,
    spec: dict[str, Any],
    decision_rules: list[dict[str, Any]],
    registration_sequence: int = 20,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    resolved_path = path.expanduser().resolve(strict=False)
    if resolved_path != root and root not in resolved_path.parents:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_INVALID"
        )
    if spec.get("dataset_snapshot_hash"):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_AFTER_OOS_BINDING"
        )
    declared_path = resolve_workspace_evidence_path(
        root, spec.get("threshold_registration_ref")
    )
    if declared_path is None or declared_path != resolved_path:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_MISMATCH"
        )
    window = spec.get("window_contract")
    if not isinstance(window, dict) or not window:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_WINDOW_CONTRACT_MISSING"
        )
    ledger_path = resolve_workspace_evidence_path(
        root, window.get("search_trial_ledger_ref")
    )
    if ledger_path is None or not ledger_path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_MISSING"
        )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if (
        ledger.get("version") != SEARCH_TRIAL_LEDGER_VERSION
        or ledger.get("search_status") != "FROZEN"
        or ledger.get("report_id") != spec.get("report_id")
        or ledger.get("factor_id") != spec.get("factor_id")
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_IDENTITY_MISMATCH"
        )
    trials = ledger.get("trials")
    if (
        not isinstance(trials, list)
        or ledger.get("trial_count") != len(trials)
        or ledger.get("trial_set_sha256") != stable_hash(trials)
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_INVALID"
        )
    freeze_sequence = ledger.get("freeze_sequence")
    if (
        isinstance(freeze_sequence, bool)
        or not isinstance(freeze_sequence, int)
        or isinstance(registration_sequence, bool)
        or not isinstance(registration_sequence, int)
        or freeze_sequence >= registration_sequence
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_REGISTRATION_ORDER_INVALID"
        )
    validate_threshold_decision_rules(spec, decision_rules)

    version = spec.get("version")
    payload: dict[str, Any] = {
        "registration_status": "LOCKED",
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "window_hash": stable_hash(window),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "registered_before_evaluation": True,
        "registration_sequence": registration_sequence,
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "search_trial_ledger_sha256": sha256_file(ledger_path),
        "decision_rules": decision_rules,
        "rule_set_sha256": stable_hash(decision_rules),
    }
    if version == METRIC_VERIFIER_SPEC_VERSION:
        if spec.get("verification_scope") != "production":
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFICATION_SCOPE_INVALID"
            )
        payload.update(
            {
                "version": METRIC_THRESHOLD_REGISTRATION_VERSION,
                "claim_class": spec.get("claim_class"),
                "verification_scope": "production",
                "label_contract_hash": stable_hash(
                    spec.get("label_contract")
                ),
            }
        )
    elif version == COMPONENT_VERIFIER_SPEC_VERSION:
        payload.update(
            {
                "version": COMPONENT_THRESHOLD_REGISTRATION_VERSION,
                "obligation_id": spec.get("obligation_id"),
                "obligation_kind": spec.get("obligation_kind"),
            }
        )
    else:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFIER_SPEC_UNSUPPORTED"
        )
    _write_immutable_json(
        resolved_path,
        payload,
        block_token=(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_REGISTRATION_IMMUTABLE"
        ),
    )
    return payload


def write_oos_release_manifest(
    path: Path,
    *,
    workspace_root: Path,
    spec: dict[str, Any],
    identities: dict[str, Any],
    threshold_path: Path,
    release_sequence: int = 30,
    host_agent_termination_authority: dict[str, Any] | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    trust_raw = (
        str(incident_trust_root)
        if incident_trust_root is not None
        else os.environ.get("FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT")
        or os.environ.get("FACTORFORGE_OOS_HOST_TRUST_ROOT")
    )
    incident_installation_id = (
        incident_installation_id
        or os.environ.get("FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID")
        or os.environ.get("FACTORFORGE_OOS_HOST_INSTALLATION_ID")
    )
    if not trust_raw or not incident_installation_id:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_INCIDENT_HOST_CONTEXT_REQUIRED"
        )
    trust_root = Path(trust_raw).expanduser().resolve(strict=True)
    if _incident_guard is not None:
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=trust_root,
            installation_id=incident_installation_id,
        )
        return _write_oos_release_manifest_guarded(
            path,
            workspace_root=workspace_root,
            spec=spec,
            identities=identities,
            threshold_path=threshold_path,
            release_sequence=release_sequence,
            host_agent_termination_authority=host_agent_termination_authority,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=incident_installation_id,
    ) as guard:
        return _write_oos_release_manifest_guarded(
            path,
            workspace_root=workspace_root,
            spec=spec,
            identities=identities,
            threshold_path=threshold_path,
            release_sequence=release_sequence,
            host_agent_termination_authority=host_agent_termination_authority,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=guard,
        )


def _write_oos_release_manifest_guarded(
    path: Path,
    *,
    workspace_root: Path,
    spec: dict[str, Any],
    identities: dict[str, Any],
    threshold_path: Path,
    release_sequence: int,
    host_agent_termination_authority: dict[str, Any] | None,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=str(spec.get("report_id") or ""),
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    resolved_path = path.expanduser().resolve(strict=False)
    if resolved_path != root and root not in resolved_path.parents:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_PATH_INVALID"
        )
    declared_release_path = resolve_workspace_evidence_path(
        root,
        (spec.get("window_contract") or {}).get(
            "oos_release_manifest_ref"
        ),
    )
    if declared_release_path is None or declared_release_path != resolved_path:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_PATH_MISMATCH"
        )
    window = spec["window_contract"]
    ledger_path = resolve_workspace_evidence_path(
        root, window["search_trial_ledger_ref"]
    )
    if ledger_path is None or not ledger_path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_MISSING"
        )
    resolved_threshold = threshold_path.expanduser().resolve(strict=False)
    declared_threshold = resolve_workspace_evidence_path(
        root, spec.get("threshold_registration_ref")
    )
    if (
        declared_threshold is None
        or declared_threshold != resolved_threshold
        or not resolved_threshold.is_file()
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_MISMATCH"
        )
    threshold_payload = json.loads(
        resolved_threshold.read_text(encoding="utf-8")
    )
    rules = threshold_payload.get("decision_rules")
    validate_threshold_decision_rules(spec, rules)
    expected_threshold_version = (
        METRIC_THRESHOLD_REGISTRATION_VERSION
        if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION
        else COMPONENT_THRESHOLD_REGISTRATION_VERSION
    )
    expected_threshold = {
        "version": expected_threshold_version,
        "registration_status": "LOCKED",
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "window_hash": stable_hash(window),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "registered_before_evaluation": True,
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "search_trial_ledger_sha256": sha256_file(ledger_path),
        "rule_set_sha256": stable_hash(rules),
    }
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        expected_threshold.update(
            {
                "claim_class": spec.get("claim_class"),
                "verification_scope": "production",
                "label_contract_hash": identities.get(
                    "label_contract_hash"
                ),
            }
        )
    elif spec.get("version") == COMPONENT_VERIFIER_SPEC_VERSION:
        expected_threshold.update(
            {
                "obligation_id": spec.get("obligation_id"),
                "obligation_kind": spec.get("obligation_kind"),
            }
        )
    else:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFIER_SPEC_UNSUPPORTED"
        )
    for field, expected in expected_threshold.items():
        if threshold_payload.get(field) != expected:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_BINDING_MISMATCH:"
                f"{field}"
            )
    registration_sequence = threshold_payload.get("registration_sequence")
    if (
        isinstance(registration_sequence, bool)
        or not isinstance(registration_sequence, int)
        or isinstance(release_sequence, bool)
        or not isinstance(release_sequence, int)
        or release_sequence <= registration_sequence
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_ORDER_INVALID"
        )
    payload = {
        "version": OOS_RELEASE_MANIFEST_VERSION,
        "release_status": "RELEASED",
        "report_id": spec["report_id"],
        "factor_id": spec["factor_id"],
        "release_sequence": release_sequence,
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "search_trial_ledger_sha256": sha256_file(ledger_path),
        "threshold_registration_ref": str(
            resolved_threshold.relative_to(root)
        ),
        "threshold_registration_sha256": sha256_file(resolved_threshold),
        "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
        "window_hash": identities["window_hash"],
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "oos_window": window["oos_window"],
        "observed_start_date": identities["observed_start_date"],
        "observed_end_date": identities["observed_end_date"],
        "observed_period_count": identities["observed_period_count"],
        "oos_release_token_hash": window["oos_release_token_hash"],
    }
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        payload.update(
            {
                "label_contract_hash": identities.get(
                    "label_contract_hash"
                ),
                "trading_calendar_sha256": identities.get(
                    "trading_calendar_sha256"
                ),
                "trading_calendar_file_sha256": identities.get(
                    "trading_calendar_file_sha256"
                ),
                "trading_calendar_registry_sha256": identities.get(
                    "trading_calendar_registry_sha256"
                ),
                "trading_calendar_registry_git_commit": identities.get(
                    "trading_calendar_registry_git_commit"
                ),
                "trading_calendar_registry_git_blob": identities.get(
                    "trading_calendar_registry_git_blob"
                ),
                "trading_calendar_snapshot_id": identities.get(
                    "trading_calendar_snapshot_id"
                ),
                "trading_calendar_source_snapshot_hash": identities.get(
                    "trading_calendar_source_snapshot_hash"
                ),
                "calendar_period_count": identities.get(
                    "calendar_period_count"
                ),
                "label_observed_start_date": identities.get(
                    "label_observed_start_date"
                ),
                "label_observed_end_date": identities.get(
                    "label_observed_end_date"
                ),
                "signal_period_count": identities.get(
                    "signal_period_count"
                ),
                "independent_path_period_count": identities.get(
                    "independent_path_period_count"
                ),
                "signal_coverage_ratio": identities.get(
                    "signal_coverage_ratio"
                ),
                "return_reconciliation_max_abs_error": identities.get(
                    "return_reconciliation_max_abs_error"
                ),
                "verification_scope": identities.get("verification_scope"),
            }
        )
    if host_agent_termination_authority is not None:
        if not isinstance(host_agent_termination_authority, dict):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_HOST_TERMINATION_AUTHORITY_INVALID"
            )
        payload["host_agent_termination_authority"] = dict(
            host_agent_termination_authority
        )
    payload["release_manifest_sha256"] = stable_hash(payload)
    existing_identical = False
    if resolved_path.is_file() and not resolved_path.is_symlink():
        try:
            existing_identical = (
                json.loads(resolved_path.read_text(encoding="utf-8")) == payload
            )
        except (OSError, json.JSONDecodeError):
            existing_identical = False
    if (
        spec.get("version") == METRIC_VERIFIER_SPEC_VERSION
        and not existing_identical
    ):
        preflight_reasons = validate_oos_release_preflight(
            workspace_root=root,
            report_id=str(spec["report_id"]),
            release_manifest_payload=payload,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        if preflight_reasons:
            raise ValueError(";".join(preflight_reasons))
    _write_immutable_json(
        resolved_path,
        payload,
        block_token=(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_OOS_MANIFEST_IMMUTABLE"
        ),
    )
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        consume_oos_allocation_for_release(
            workspace_root=root,
            report_id=str(spec["report_id"]),
            release_manifest_path=resolved_path,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    return payload


def observed_panel_dates(
    frame: pd.DataFrame,
    *,
    date_column: str,
) -> dict[str, Any]:
    if date_column not in frame.columns:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_DATE_COLUMN_MISSING"
        )
    parsed = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_DATE_VALUE_INVALID"
        )
    normalized = parsed.dt.strftime("%Y-%m-%d")
    unique_dates = sorted(normalized.unique().tolist())
    if not unique_dates:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_DATES_MISSING"
        )
    return {
        "observed_start_date": unique_dates[0],
        "observed_end_date": unique_dates[-1],
        "observed_period_count": len(unique_dates),
    }


def validate_observed_oos_window(
    window: dict[str, Any],
    identities: dict[str, Any],
) -> None:
    for field in ("observed_start_date", "observed_end_date"):
        if window.get(field) != identities.get(field):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_OBSERVED_DATE_MISMATCH:"
                f"{field}"
            )
    raw_window = window.get("oos_window")
    if not isinstance(raw_window, str) or raw_window.count("/") != 1:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_OOS_WINDOW_INVALID"
        )
    start_raw, end_raw = raw_window.split("/", 1)
    start = pd.to_datetime(start_raw, errors="coerce", utc=True)
    end = pd.to_datetime(end_raw, errors="coerce", utc=True)
    observed_start = pd.to_datetime(
        identities["observed_start_date"], errors="coerce", utc=True
    )
    observed_end = pd.to_datetime(
        identities["observed_end_date"], errors="coerce", utc=True
    )
    if any(pd.isna(value) for value in (start, end, observed_start, observed_end)):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_OOS_WINDOW_INVALID"
        )
    if start > end or observed_start < start or observed_end > end:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_PANEL_OUTSIDE_OOS_WINDOW"
        )
    minimum_periods = window.get("minimum_periods")
    if (
        isinstance(minimum_periods, bool)
        or not isinstance(minimum_periods, int)
        or minimum_periods < MINIMUM_FORMAL_DAILY_PERIODS
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MINIMUM_PERIOD_POLICY_INVALID"
        )
    if identities.get("observed_period_count", 0) < minimum_periods:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_PERIODS_INSUFFICIENT"
        )


def validate_evaluation_release_chain(
    *,
    workspace_root: Path,
    spec: dict[str, Any],
    identities: dict[str, Any],
    threshold_path: Path,
    threshold_payload: dict[str, Any],
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    resolved_threshold = threshold_path.expanduser().resolve(strict=False)
    if (
        resolved_threshold != root
        and root not in resolved_threshold.parents
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_INVALID"
        )
    if not resolved_threshold.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_REGISTRATION_MISSING"
        )
    on_disk_threshold = json.loads(
        resolved_threshold.read_text(encoding="utf-8")
    )
    if on_disk_threshold != threshold_payload:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PAYLOAD_MISMATCH"
        )
    threshold_path = resolved_threshold
    window = spec.get("window_contract")
    if not isinstance(window, dict):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_WINDOW_CONTRACT_MISSING"
        )
    validate_observed_oos_window(window, identities)

    ledger_path = resolve_workspace_evidence_path(
        root, window.get("search_trial_ledger_ref")
    )
    if ledger_path is None or not ledger_path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_MISSING"
        )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_ref = str(ledger_path.relative_to(root))
    ledger_sha256 = sha256_file(ledger_path)
    expected_ledger = {
        "version": SEARCH_TRIAL_LEDGER_VERSION,
        "search_status": "FROZEN",
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
    }
    for field, expected in expected_ledger.items():
        if ledger.get(field) != expected:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_IDENTITY_MISMATCH:"
                f"{field}"
            )
    trials = ledger.get("trials")
    if not isinstance(trials, list) or ledger.get("trial_count") != len(trials):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_INVALID"
        )
    if ledger.get("trial_set_sha256") != stable_hash(trials):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_HASH_MISMATCH"
        )
    for field in ("candidate_space_sha256", "selected_hypothesis_sha256"):
        if not valid_sha256(ledger.get(field)):
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_TRIAL_LEDGER_INVALID:"
                f"{field}"
            )
    freeze_sequence = ledger.get("freeze_sequence")
    registration_sequence = threshold_payload.get("registration_sequence")
    if (
        isinstance(freeze_sequence, bool)
        or not isinstance(freeze_sequence, int)
        or isinstance(registration_sequence, bool)
        or not isinstance(registration_sequence, int)
        or freeze_sequence >= registration_sequence
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_REGISTRATION_ORDER_INVALID"
        )
    expected_threshold_search = {
        "search_trial_ledger_ref": ledger_ref,
        "search_trial_ledger_sha256": ledger_sha256,
    }
    for field, expected in expected_threshold_search.items():
        if threshold_payload.get(field) != expected:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_SEARCH_BINDING_MISMATCH:"
                f"{field}"
            )
    threshold_ref = str(threshold_path.relative_to(root))
    if spec.get("threshold_registration_ref") != threshold_ref:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_PATH_MISMATCH"
        )
    rules = threshold_payload.get("decision_rules")
    validate_threshold_decision_rules(spec, rules)
    expected_threshold_version = (
        METRIC_THRESHOLD_REGISTRATION_VERSION
        if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION
        else COMPONENT_THRESHOLD_REGISTRATION_VERSION
    )
    expected_threshold = {
        "version": expected_threshold_version,
        "registration_status": "LOCKED",
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "window_hash": identities.get("window_hash"),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "registered_before_evaluation": True,
        "rule_set_sha256": stable_hash(rules),
    }
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        expected_threshold.update(
            {
                "claim_class": spec.get("claim_class"),
                "verification_scope": "production",
                "label_contract_hash": identities.get(
                    "label_contract_hash"
                ),
            }
        )
    elif spec.get("version") == COMPONENT_VERIFIER_SPEC_VERSION:
        expected_threshold.update(
            {
                "obligation_id": spec.get("obligation_id"),
                "obligation_kind": spec.get("obligation_kind"),
            }
        )
    else:
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_VERIFIER_SPEC_UNSUPPORTED"
        )
    for field, expected in expected_threshold.items():
        if threshold_payload.get(field) != expected:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_BINDING_MISMATCH:"
                f"{field}"
            )

    release_path = resolve_workspace_evidence_path(
        root, window.get("oos_release_manifest_ref")
    )
    if release_path is None or not release_path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_MISSING"
        )
    release = json.loads(release_path.read_text(encoding="utf-8"))
    expected_release = {
        "version": OOS_RELEASE_MANIFEST_VERSION,
        "release_status": "RELEASED",
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "search_trial_ledger_ref": ledger_ref,
        "search_trial_ledger_sha256": ledger_sha256,
        "threshold_registration_ref": threshold_ref,
        "threshold_registration_sha256": sha256_file(threshold_path),
        "dataset_snapshot_hash": identities.get("dataset_snapshot_hash"),
        "window_hash": identities.get("window_hash"),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "oos_window": window.get("oos_window"),
        "observed_start_date": identities.get("observed_start_date"),
        "observed_end_date": identities.get("observed_end_date"),
        "observed_period_count": identities.get("observed_period_count"),
        "oos_release_token_hash": window.get("oos_release_token_hash"),
    }
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        expected_release.update(
            {
                "label_contract_hash": identities.get(
                    "label_contract_hash"
                ),
                "trading_calendar_sha256": identities.get(
                    "trading_calendar_sha256"
                ),
                "trading_calendar_file_sha256": identities.get(
                    "trading_calendar_file_sha256"
                ),
                "trading_calendar_registry_sha256": identities.get(
                    "trading_calendar_registry_sha256"
                ),
                "trading_calendar_registry_git_commit": identities.get(
                    "trading_calendar_registry_git_commit"
                ),
                "trading_calendar_registry_git_blob": identities.get(
                    "trading_calendar_registry_git_blob"
                ),
                "trading_calendar_snapshot_id": identities.get(
                    "trading_calendar_snapshot_id"
                ),
                "trading_calendar_source_snapshot_hash": identities.get(
                    "trading_calendar_source_snapshot_hash"
                ),
                "calendar_period_count": identities.get(
                    "calendar_period_count"
                ),
                "label_observed_start_date": identities.get(
                    "label_observed_start_date"
                ),
                "label_observed_end_date": identities.get(
                    "label_observed_end_date"
                ),
                "signal_period_count": identities.get(
                    "signal_period_count"
                ),
                "independent_path_period_count": identities.get(
                    "independent_path_period_count"
                ),
                "signal_coverage_ratio": identities.get(
                    "signal_coverage_ratio"
                ),
                "return_reconciliation_max_abs_error": identities.get(
                    "return_reconciliation_max_abs_error"
                ),
                "verification_scope": identities.get("verification_scope"),
            }
        )
    for field, expected in expected_release.items():
        if release.get(field) != expected:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_BINDING_MISMATCH:"
                f"{field}"
            )
    release_sequence = release.get("release_sequence")
    if (
        isinstance(release_sequence, bool)
        or not isinstance(release_sequence, int)
        or release_sequence <= registration_sequence
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_ORDER_INVALID"
        )
    if release.get("release_manifest_sha256") != stable_hash(
        {
            key: value
            for key, value in release.items()
            if key != "release_manifest_sha256"
        }
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_HASH_MISMATCH"
        )
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        consumption_reasons = validate_oos_release_consumption_structural(
            workspace_root=root,
            report_id=str(spec.get("report_id") or ""),
            release_manifest_path=release_path,
        )
        if consumption_reasons:
            raise ValueError(";".join(consumption_reasons))
    return {
        "search_trial_ledger_ref": ledger_ref,
        "search_trial_ledger_sha256": ledger_sha256,
        "threshold_registration_ref": threshold_ref,
        "threshold_registration_sha256": sha256_file(threshold_path),
        "oos_release_manifest_ref": str(release_path.relative_to(root)),
        "oos_release_manifest_sha256": sha256_file(release_path),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "label_contract_hash": identities.get("label_contract_hash"),
        "verification_scope": identities.get("verification_scope"),
        "trading_calendar_registry_git_commit": identities.get(
            "trading_calendar_registry_git_commit"
        ),
        "trading_calendar_registry_git_blob": identities.get(
            "trading_calendar_registry_git_blob"
        ),
        "freeze_sequence": freeze_sequence,
        "registration_sequence": registration_sequence,
        "release_sequence": release_sequence,
        "current_formal_authority_verified": False,
    }


def validate_evaluation_release_chain_current(
    *,
    workspace_root: Path,
    spec: dict[str, Any],
    identities: dict[str, Any],
    threshold_path: Path,
    threshold_payload: dict[str, Any],
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    """Host-current replay, linearized against private incident registration."""

    trust_root = incident_trust_root.expanduser().resolve(strict=True)
    if _incident_guard is None:
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id=incident_installation_id,
        ) as guard:
            return validate_evaluation_release_chain_current(
                workspace_root=workspace_root,
                spec=spec,
                identities=identities,
                threshold_path=threshold_path,
                threshold_payload=threshold_payload,
                incident_trust_root=trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=guard,
            )
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=trust_root,
        installation_id=incident_installation_id,
    )
    root = workspace_root.expanduser().resolve(strict=False)
    report_id = str(spec.get("report_id") or "")
    reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=trust_root,
        installation_id=incident_installation_id,
    )
    if reasons:
        raise ValueError(";".join(reasons))
    structural = validate_evaluation_release_chain(
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
        threshold_payload=threshold_payload,
    )
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        release_path = resolve_workspace_evidence_path(
            root,
            (spec.get("window_contract") or {}).get("oos_release_manifest_ref"),
        )
        if release_path is None:
            raise ValueError(
                "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_MISSING"
            )
        consumption_reasons = validate_oos_release_consumption(
            workspace_root=root,
            report_id=report_id,
            release_manifest_path=release_path,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        if consumption_reasons:
            raise ValueError(";".join(consumption_reasons))
    return {**structural, "current_formal_authority_verified": True}
