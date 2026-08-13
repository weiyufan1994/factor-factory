from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
    validate_evidence_reference,
)
from factor_factory.metric_verifier import (
    TRADING_CALENDAR_REGISTRY_TRUST_BLOB,
    TRADING_CALENDAR_REGISTRY_TRUST_COMMIT,
    validate_metric_verifier_report,
    verifier_source_sha256,
)
from factor_factory.evo_oos import formal_oos_incident_reasons
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_release import (
    METRIC_ALLOWED_DECISION_PATHS as ALLOWED_DECISION_PATHS,
    METRIC_CLAIM_CLASSES as CLAIM_CLASSES,
    METRIC_CORE_RULE_GUARDRAILS as CORE_RULE_GUARDRAILS,
    METRIC_REQUIRED_DECISION_PATHS as REQUIRED_DECISION_PATHS,
    MINIMUM_FORMAL_DAILY_PERIODS,
)


CERTIFICATE_VERSION = "factorforge_factor_proof_certificate_v2"
VERDICTS = {"ACCEPT", "REJECT", "INCONCLUSIVE", "BLOCK"}
COMMON_REQUIRED_METRICS = {
    "ic",
    "icir",
    "volatility_cost",
    "transaction_cost",
    "drawdown",
    "long_end",
}
RISK_PREMIUM_REQUIRED_METRICS = {"fama_macbeth", "bucket_monotonicity"}
PROMOTION_EVIDENCE_ROLE = "promotion_gate_evidence"
SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
THRESHOLD_REGISTRATION_VERSION = "factorforge_threshold_registration_v2"
METRIC_VERIFIER_REPORT_VERSION = "factorforge_metric_verifier_report_v2"
TRUSTED_FACTOR_PROOF_VERIFIERS = {
    "factorforge_step4_metric_verifier_v2",
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


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def close_enough(left: Any, right: Any, tolerance: float = 1e-8) -> bool:
    a = number(left)
    b = number(right)
    return a is not None and b is not None and abs(a - b) <= tolerance


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def nested(payload: dict[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _metric(payload: dict[str, Any], name: str) -> dict[str, Any]:
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return {}
    value = metrics.get(name)
    return value if isinstance(value, dict) else {}


def _minimum_periods(payload: dict[str, Any]) -> int:
    contract = payload.get("data_contract")
    contract = contract if isinstance(contract, dict) else {}
    value = contract.get("minimum_periods")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(MINIMUM_FORMAL_DAILY_PERIODS, value)
    return MINIMUM_FORMAL_DAILY_PERIODS


def factor_proof_certificate_path(workspace_root: Path, report_id: str) -> Path:
    return (
        workspace_root
        / "objects"
        / "research_protocol"
        / f"factor_proof_certificate__{report_id}.json"
    )


def _validate_evidence_bindings(
    payload: dict[str, Any],
    *,
    workspace_root: Path | None,
    required_metrics: set[str],
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    reasons: list[str] = []
    bindings = payload.get("evidence_bindings")
    if not isinstance(bindings, dict):
        return ["BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_BINDINGS_MISSING"]
    data_contract = payload.get("data_contract")
    data_contract = data_contract if isinstance(data_contract, dict) else {}
    expected_dataset_hash = data_contract.get("dataset_snapshot_hash")
    expected_window_hash = data_contract.get("window_hash")
    threshold_registration = payload.get("threshold_registration")
    threshold_registration = (
        threshold_registration
        if isinstance(threshold_registration, dict)
        else {}
    )
    expected_threshold_registration_hash = threshold_registration.get(
        "registration_sha256"
    )
    expected_threshold_rule_set_hash = threshold_registration.get(
        "rule_set_sha256"
    )
    expected_verifier_source_hash = verifier_source_sha256()
    for metric_name in sorted(required_metrics):
        reference = bindings.get(metric_name)
        if not isinstance(reference, dict):
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_BINDING_MISSING:{metric_name}"
            )
            continue
        if reference.get("metric") != metric_name:
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_METRIC_MISMATCH:{metric_name}"
            )
        if reference.get("dataset_snapshot_hash") != expected_dataset_hash:
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_DATASET_MISMATCH:{metric_name}"
            )
        if reference.get("window_hash") != expected_window_hash:
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_WINDOW_MISMATCH:{metric_name}"
            )
        if (
            reference.get("threshold_registration_sha256")
            != expected_threshold_registration_hash
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_THRESHOLD_REGISTRATION_MISMATCH:"
                f"{metric_name}"
            )
        if (
            reference.get("threshold_rule_set_sha256")
            != expected_threshold_rule_set_hash
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_THRESHOLD_RULE_SET_MISMATCH:"
                f"{metric_name}"
            )
        if (
            reference.get("verifier_source_sha256")
            != expected_verifier_source_hash
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_VERIFIER_SOURCE_MISMATCH:"
                f"{metric_name}"
            )
        reasons.extend(
            validate_evidence_reference(
                reference,
                workspace_root=workspace_root,
                token_prefix=(
                    "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE"
                    f":{metric_name}"
                ),
                allowed_verifier_ids=TRUSTED_FACTOR_PROOF_VERIFIERS,
            )
        )
        if workspace_root is not None:
            evidence_path = resolve_workspace_evidence_path(
                workspace_root,
                reference.get("path"),
            )
            if evidence_path is not None and evidence_path.is_file():
                try:
                    evidence_payload = load_json(evidence_path)
                except Exception:
                    evidence_payload = {}
                if evidence_payload.get("metric") != metric_name:
                    reasons.append(
                        "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_REPORT_METRIC_MISMATCH:"
                        f"{metric_name}"
                    )
                if (
                    evidence_payload.get("verifier_contract_version")
                    != METRIC_VERIFIER_REPORT_VERSION
                ):
                    reasons.append(
                        "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_VERIFIER_CONTRACT_INVALID:"
                        f"{metric_name}"
                    )
                for field, expected in (
                    (
                        "threshold_registration_sha256",
                        expected_threshold_registration_hash,
                    ),
                    ("threshold_rule_set_sha256", expected_threshold_rule_set_hash),
                    ("verifier_source_sha256", expected_verifier_source_hash),
                    (
                        "evaluation_contract_hash",
                        data_contract.get("evaluation_contract_hash"),
                    ),
                    (
                        "label_contract_hash",
                        data_contract.get("label_contract_hash"),
                    ),
                ):
                    if evidence_payload.get(field) != expected:
                        reasons.append(
                            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_THRESHOLD_BINDING_MISMATCH:"
                            f"{metric_name}:{field}"
                        )
                if evidence_payload.get("metric_payload") != _metric(
                    payload,
                    metric_name,
                ):
                    reasons.append(
                        "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_VALUE_MISMATCH:"
                        f"{metric_name}"
                    )
                verifier_spec = evidence_payload.get("verifier_spec")
                verifier_spec = (
                    verifier_spec if isinstance(verifier_spec, dict) else {}
                )
                for field, expected in (
                    ("report_id", payload.get("report_id")),
                    ("factor_id", payload.get("factor_id")),
                    ("claim_class", payload.get("claim_class")),
                    ("cost_policy_id", data_contract.get("cost_policy_id")),
                    (
                        "verification_scope",
                        data_contract.get("verification_scope"),
                    ),
                ):
                    if verifier_spec.get(field) != expected:
                        reasons.append(
                            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_SPEC_IDENTITY_MISMATCH:"
                            f"{metric_name}:{field}"
                        )
                verifier_window = verifier_spec.get("window_contract")
                verifier_window = (
                    verifier_window
                    if isinstance(verifier_window, dict)
                    else {}
                )
                for certificate_field, verifier_field in (
                    ("sample_frequency", "sample_frequency"),
                    ("forward_return_horizon", "forward_return_horizon"),
                    (
                        "forward_return_horizon_days",
                        "forward_return_horizon_days",
                    ),
                    ("signal_timestamp", "signal_timestamp"),
                    ("execution_timestamp", "execution_timestamp"),
                    ("label_start_timestamp", "label_start_timestamp"),
                    ("label_end_timestamp", "label_end_timestamp"),
                    ("forward_return_formula", "forward_return_formula"),
                    ("path_is_disjoint", "path_is_disjoint"),
                    ("evaluation_window_role", "evaluation_window_role"),
                    ("oos_window", "oos_window"),
                    ("observed_start_date", "observed_start_date"),
                    ("observed_end_date", "observed_end_date"),
                    ("minimum_periods", "minimum_periods"),
                    ("oos_release_token_hash", "oos_release_token_hash"),
                    ("search_trial_ledger_ref", "search_trial_ledger_ref"),
                    ("oos_release_manifest_ref", "oos_release_manifest_ref"),
                    (
                        "search_frozen_before_oos_release",
                        "search_frozen_before_oos_release",
                    ),
                    ("universe_id", "universe_id"),
                    ("investability_mask_id", "investability_mask_id"),
                    ("return_convention", "return_convention"),
                ):
                    if data_contract.get(certificate_field) != verifier_window.get(
                        verifier_field
                    ):
                        reasons.append(
                            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_WINDOW_CONTRACT_MISMATCH:"
                            f"{metric_name}:{certificate_field}"
                        )
                verifier_portfolio = verifier_spec.get("portfolio")
                verifier_portfolio = (
                    verifier_portfolio
                    if isinstance(verifier_portfolio, dict)
                    else {}
                )
                for certificate_field, verifier_field in (
                    ("return_path_mode", "return_path_mode"),
                    ("holding_period_days", "holding_period_days"),
                    ("rebalance_frequency", "rebalance_frequency"),
                ):
                    if data_contract.get(
                        certificate_field
                    ) != verifier_portfolio.get(verifier_field):
                        reasons.append(
                            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_PORTFOLIO_CONTRACT_MISMATCH:"
                            f"{metric_name}:{certificate_field}"
                        )
                verifier_label = verifier_spec.get("label_contract")
                verifier_label = (
                    verifier_label
                    if isinstance(verifier_label, dict)
                    else {}
                )
                for certificate_field, verifier_field in (
                    ("label_contract_version", "version"),
                    ("signal_date_column", "signal_date_column"),
                    ("label_start_date_column", "label_start_date_column"),
                    ("label_end_date_column", "label_end_date_column"),
                    ("label_start_price_column", "label_start_price_column"),
                    ("label_end_price_column", "label_end_price_column"),
                    ("forward_return_column", "forward_return_column"),
                    ("return_tolerance", "return_tolerance"),
                    ("trading_calendar_ref", "trading_calendar_ref"),
                    ("trading_calendar_id", "trading_calendar_id"),
                    (
                        "trading_calendar_sha256",
                        "trading_calendar_sha256",
                    ),
                    (
                        "trading_calendar_registry_sha256",
                        "trading_calendar_registry_sha256",
                    ),
                    (
                        "trading_calendar_registry_git_commit",
                        "trading_calendar_registry_git_commit",
                    ),
                    (
                        "trading_calendar_registry_git_blob",
                        "trading_calendar_registry_git_blob",
                    ),
                    (
                        "trading_calendar_snapshot_id",
                        "trading_calendar_snapshot_id",
                    ),
                ):
                    if data_contract.get(
                        certificate_field
                    ) != verifier_label.get(verifier_field):
                        reasons.append(
                            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_LABEL_CONTRACT_MISMATCH:"
                            f"{metric_name}:{certificate_field}"
                        )
                for field in (
                    "trading_calendar_sha256",
                    "trading_calendar_file_sha256",
                    "trading_calendar_registry_sha256",
                    "trading_calendar_registry_git_commit",
                    "trading_calendar_registry_git_blob",
                    "trading_calendar_snapshot_id",
                    "label_observed_start_date",
                    "label_observed_end_date",
                    "signal_period_count",
                    "independent_path_period_count",
                    "calendar_period_count",
                    "signal_coverage_ratio",
                    "trading_calendar_source_snapshot_hash",
                    "return_reconciliation_max_abs_error",
                    "verification_scope",
                ):
                    if data_contract.get(field) != evidence_payload.get(field):
                        reasons.append(
                            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_LABEL_PATH_MISMATCH:"
                            f"{metric_name}:{field}"
                        )
                for replay_reason in validate_metric_verifier_report(
                    evidence_payload,
                    workspace_root=workspace_root,
                    incident_trust_root=incident_trust_root,
                    incident_installation_id=incident_installation_id,
                    _incident_guard=_incident_guard,
                ):
                    reasons.append(f"{replay_reason}:{metric_name}")
    return reasons


def _validate_data_contract(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    contract = payload.get("data_contract")
    if not isinstance(contract, dict):
        return ["BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_MISSING"]
    for field in (
        "is_window",
        "universe",
        "universe_id",
        "investability_mask_id",
        "sample_frequency",
        "forward_return_horizon",
        "return_path_mode",
        "rebalance_frequency",
        "signal_timestamp",
        "execution_timestamp",
        "label_start_timestamp",
        "label_end_timestamp",
        "forward_return_formula",
        "label_contract_version",
        "signal_date_column",
        "label_start_date_column",
        "label_end_date_column",
        "label_start_price_column",
        "label_end_price_column",
        "forward_return_column",
        "trading_calendar_ref",
        "trading_calendar_id",
        "cost_policy_id",
        "label_definition",
        "return_convention",
        "dataset_snapshot_hash",
        "window_hash",
        "evaluation_contract_hash",
        "label_contract_hash",
        "trading_calendar_sha256",
        "trading_calendar_file_sha256",
        "trading_calendar_registry_sha256",
        "trading_calendar_registry_git_commit",
        "trading_calendar_registry_git_blob",
        "trading_calendar_snapshot_id",
        "trading_calendar_source_snapshot_hash",
        "observed_start_date",
        "observed_end_date",
        "label_observed_start_date",
        "label_observed_end_date",
        "search_trial_ledger_ref",
        "oos_release_manifest_ref",
        "verification_scope",
    ):
        if not nonempty_str(contract.get(field)):
            reasons.append(f"BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_MISSING:{field}")
    for field in (
        "dataset_snapshot_hash",
        "window_hash",
        "evaluation_contract_hash",
        "label_contract_hash",
        "trading_calendar_sha256",
        "trading_calendar_file_sha256",
        "trading_calendar_registry_sha256",
        "trading_calendar_source_snapshot_hash",
    ):
        value = contract.get(field)
        if (
            isinstance(value, str)
            and value
            and not SHA256_RE.fullmatch(value.strip().lower())
        ):
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_HASH_INVALID:{field}"
            )
    for field in (
        "forward_return_horizon_days",
        "holding_period_days",
        "signal_period_count",
        "independent_path_period_count",
        "calendar_period_count",
    ):
        value = contract.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_INVALID:{field}"
            )
    return_tolerance = contract.get("return_tolerance")
    if (
        isinstance(return_tolerance, bool)
        or not isinstance(return_tolerance, (int, float))
        or not 0 < float(return_tolerance) <= 1e-8
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_INVALID:"
            "return_tolerance"
        )
    signal_coverage_ratio = contract.get("signal_coverage_ratio")
    if (
        isinstance(signal_coverage_ratio, bool)
        or not isinstance(signal_coverage_ratio, (int, float))
        or not math.isfinite(float(signal_coverage_ratio))
        or not close_enough(float(signal_coverage_ratio), 1.0)
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_INVALID:"
            "signal_coverage_ratio"
        )
    reconciliation_error = contract.get(
        "return_reconciliation_max_abs_error"
    )
    if (
        isinstance(reconciliation_error, bool)
        or not isinstance(reconciliation_error, (int, float))
        or not math.isfinite(float(reconciliation_error))
        or float(reconciliation_error) < 0
        or (
            isinstance(return_tolerance, (int, float))
            and not isinstance(return_tolerance, bool)
            and float(reconciliation_error) > float(return_tolerance)
        )
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DATA_CONTRACT_INVALID:"
            "return_reconciliation_max_abs_error"
        )
    if (
        contract.get("forward_return_horizon_days") != 1
        or contract.get("holding_period_days") != 1
        or contract.get("return_path_mode")
        != "daily_one_period_forward_return"
        or contract.get("rebalance_frequency") != "daily"
        or contract.get("path_is_disjoint") is not True
        or contract.get("forward_return_formula")
        != "label_end_price/label_start_price-1"
        or contract.get("label_contract_version")
        != "factorforge_daily_return_label_contract_v1"
        or contract.get("signal_period_count")
        != contract.get("independent_path_period_count")
        or contract.get("trading_calendar_sha256")
        != contract.get("trading_calendar_source_snapshot_hash")
        or contract.get("verification_scope") != "production"
        or contract.get("trading_calendar_registry_git_commit")
        != TRADING_CALENDAR_REGISTRY_TRUST_COMMIT
        or contract.get("trading_calendar_registry_git_blob")
        != TRADING_CALENDAR_REGISTRY_TRUST_BLOB
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_MULTI_PERIOD_PORTFOLIO_PATH_REQUIRED"
        )
    if contract.get("oos_status") not in {
        "sealed",
        "released_once_for_final_evaluation",
    }:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_OOS_STATUS_INVALID")
    if contract.get("same_sample_for_all_required_metrics") is not True:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_SAMPLE_MISMATCH")
    minimum_periods = contract.get("minimum_periods")
    if (
        isinstance(minimum_periods, bool)
        or not isinstance(minimum_periods, int)
        or minimum_periods < MINIMUM_FORMAL_DAILY_PERIODS
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_MINIMUM_PERIOD_POLICY_INVALID"
        )
    if payload.get("declared_verdict") == "ACCEPT":
        if contract.get("oos_status") != "released_once_for_final_evaluation":
            reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_ACCEPT_WITHOUT_OOS_RELEASE")
        if contract.get("evaluation_window_role") != "OOS_FINAL":
            reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_ACCEPT_WITHOUT_OOS_EVIDENCE")
        if contract.get("search_frozen_before_oos_release") is not True:
            reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_OOS_RELEASE_BEFORE_SEARCH_FREEZE")
        if contract.get("oos_evidence_included") is not True:
            reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_OOS_EVIDENCE_NOT_INCLUDED")
        if not nonempty_str(contract.get("oos_window")):
            reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_OOS_WINDOW_MISSING")
        release_hash = contract.get("oos_release_token_hash")
        if not isinstance(release_hash, str) or not SHA256_RE.fullmatch(
            release_hash.strip().lower()
        ):
            reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_OOS_RELEASE_HASH_INVALID")
    return reasons


def _validate_ic(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    ic = _metric(payload, "ic")
    if ic.get("method") not in {"rank_ic", "pearson_ic", "both"}:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_IC_METHOD_INVALID")
    for field in ("mean", "std", "period_count"):
        if number(ic.get(field)) is None:
            reasons.append(f"BLOCK_FACTORFORGE_FACTOR_PROOF_IC_FIELD_MISSING:{field}")
    if number(ic.get("std")) is not None and float(ic["std"]) < 0:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_IC_STD_INVALID")
    if (
        not isinstance(ic.get("period_count"), int)
        or ic["period_count"] < _minimum_periods(payload)
    ):
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_IC_PERIOD_COUNT_INVALID")
    if not nonempty_str(ic.get("horizon")):
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_IC_HORIZON_MISSING")
    if ic.get("horizon_days") != (
        (payload.get("data_contract") or {}).get(
            "forward_return_horizon_days"
        )
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_IC_HORIZON_DAYS_MISMATCH"
        )
    if ic.get("evidence_role") != PROMOTION_EVIDENCE_ROLE:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_IC_EVIDENCE_ROLE_INVALID")
    return reasons


def _validate_icir(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    ic = _metric(payload, "ic")
    icir = _metric(payload, "icir")
    value = number(icir.get("value"))
    annualization = number(icir.get("annualization_factor"))
    mean_ic = number(ic.get("mean"))
    std_ic = number(ic.get("std"))
    if value is None or annualization is None or mean_ic is None or std_ic is None:
        return ["BLOCK_FACTORFORGE_FACTOR_PROOF_ICIR_FIELDS_MISSING"]
    if std_ic <= 0 or annualization <= 0:
        return ["BLOCK_FACTORFORGE_FACTOR_PROOF_ICIR_DENOMINATOR_INVALID"]
    if not isinstance(icir.get("annualized"), bool):
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_ICIR_ANNUALIZATION_INVALID")
    expected = mean_ic / std_ic
    if icir.get("annualized") is True:
        expected *= math.sqrt(annualization)
    tolerance = number(icir.get("reconciliation_tolerance"))
    if tolerance is None:
        tolerance = 1e-8
    if not close_enough(value, expected, tolerance):
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_ICIR_RECONCILIATION_FAILED")
    if icir.get("evidence_role") != PROMOTION_EVIDENCE_ROLE:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_ICIR_EVIDENCE_ROLE_INVALID")
    return reasons


def _validate_control_residualization(payload: dict[str, Any]) -> list[str]:
    data_contract = (
        payload.get("data_contract")
        if isinstance(payload.get("data_contract"), dict)
        else {}
    )
    controls = data_contract.get("control_columns") or []
    metric = _metric(payload, "control_residualization")
    if not controls:
        if metric and metric.get("required_for_acceptance") is True:
            return ["BLOCK_FACTORFORGE_CONTROL_RESIDUALIZATION_UNDECLARED"]
        return []
    reasons: list[str] = []
    if metric.get("required_for_acceptance") is not True:
        reasons.append(
            "BLOCK_FACTORFORGE_CONTROL_RESIDUALIZATION_NOT_REQUIRED"
        )
    if metric.get("control_columns") != controls:
        reasons.append(
            "BLOCK_FACTORFORGE_CONTROL_RESIDUALIZATION_CONTROLS_MISMATCH"
        )
    if number(metric.get("residual_rank_ic_mean")) is None:
        reasons.append(
            "BLOCK_FACTORFORGE_CONTROL_RESIDUALIZATION_VALUE_MISSING"
        )
    if metric.get("period_count") != _metric(payload, "ic").get("period_count"):
        reasons.append(
            "BLOCK_FACTORFORGE_CONTROL_RESIDUALIZATION_SAMPLE_MISMATCH"
        )
    if metric.get("method") != (
        "daily_cross_sectional_ols_signal_on_controls_with_intercept"
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_CONTROL_RESIDUALIZATION_METHOD_INVALID"
        )
    return reasons


def _validate_fama_macbeth(payload: dict[str, Any], claim_class: str) -> list[str]:
    reasons: list[str] = []
    fmb = _metric(payload, "fama_macbeth")
    required = claim_class == "risk_premium"
    if not fmb:
        return (
            ["BLOCK_FACTORFORGE_RISK_PREMIUM_FAMA_MACBETH_MISSING"]
            if required
            else []
        )
    if required:
        if fmb.get("required_for_acceptance") is not True:
            reasons.append(
                "BLOCK_FACTORFORGE_RISK_PREMIUM_FAMA_MACBETH_NOT_REQUIRED"
            )
    else:
        if fmb.get("required_for_acceptance") is True:
            reasons.append(
                "BLOCK_FACTORFORGE_FAMA_MACBETH_GATE_OUTSIDE_RISK_PREMIUM"
            )
        if fmb.get("evidence_role") == PROMOTION_EVIDENCE_ROLE:
            reasons.append(
                "BLOCK_FACTORFORGE_FAMA_MACBETH_PROMOTION_ROLE_OUTSIDE_RISK_PREMIUM"
            )
    if fmb.get("applicable") is not True:
        if required:
            reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_FAMA_MACBETH_NOT_APPLICABLE")
        return reasons
    for field in ("lambda_mean", "lambda_tstat", "period_count", "newey_west_lags"):
        if number(fmb.get(field)) is None:
            reasons.append(f"BLOCK_FACTORFORGE_FAMA_MACBETH_FIELD_MISSING:{field}")
    if (
        not isinstance(fmb.get("period_count"), int)
        or fmb["period_count"] < _minimum_periods(payload)
    ):
        reasons.append("BLOCK_FACTORFORGE_FAMA_MACBETH_PERIOD_COUNT_INVALID")
    if (
        not isinstance(fmb.get("newey_west_lags"), int)
        or fmb["newey_west_lags"] < 0
    ):
        reasons.append("BLOCK_FACTORFORGE_FAMA_MACBETH_LAGS_INVALID")
    for field in ("cross_sectional_regression", "exposure_timing", "return_horizon"):
        if not nonempty_str(fmb.get(field)):
            reasons.append(f"BLOCK_FACTORFORGE_FAMA_MACBETH_FIELD_MISSING:{field}")
    if fmb.get("return_horizon_days") != (
        (payload.get("data_contract") or {}).get(
            "forward_return_horizon_days"
        )
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FAMA_MACBETH_HORIZON_DAYS_MISMATCH"
        )
    if not nonempty_list(fmb.get("controls")):
        reasons.append("BLOCK_FACTORFORGE_FAMA_MACBETH_CONTROLS_MISSING")
    if required and fmb.get("evidence_role") != PROMOTION_EVIDENCE_ROLE:
        reasons.append("BLOCK_FACTORFORGE_FAMA_MACBETH_EVIDENCE_ROLE_INVALID")
    if not required and fmb.get("evidence_role") not in {
        None,
        "diagnostic_evidence",
    }:
        reasons.append(
            "BLOCK_FACTORFORGE_FAMA_MACBETH_DIAGNOSTIC_ROLE_INVALID"
        )
    ic_period_count = _metric(payload, "ic").get("period_count")
    if required and fmb.get("period_count") != ic_period_count:
        reasons.append("BLOCK_FACTORFORGE_FAMA_MACBETH_SAMPLE_MISMATCH")
    return reasons


def _validate_return_path_binding(
    payload: dict[str, Any],
    metric_name: str,
) -> list[str]:
    reasons: list[str] = []
    metric = _metric(payload, metric_name)
    contract = payload.get("data_contract") or {}
    for field in ("return_path_mode", "observation_frequency"):
        if not nonempty_str(metric.get(field)):
            reasons.append(
                "BLOCK_FACTORFORGE_RETURN_PATH_CONTRACT_MISSING:"
                f"{metric_name}:{field}"
            )
    holding_period_days = metric.get("holding_period_days")
    if (
        isinstance(holding_period_days, bool)
        or not isinstance(holding_period_days, int)
        or holding_period_days < 1
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_RETURN_PATH_CONTRACT_INVALID:"
            f"{metric_name}:holding_period_days"
        )
    for field in ("return_path_mode", "holding_period_days"):
        if metric.get(field) != contract.get(field):
            reasons.append(
                "BLOCK_FACTORFORGE_RETURN_PATH_CONTRACT_MISMATCH:"
                f"{metric_name}:{field}"
            )
    if metric.get("observation_frequency") != "daily":
        reasons.append(
            "BLOCK_FACTORFORGE_RETURN_PATH_OBSERVATION_UNSUPPORTED:"
            f"{metric_name}"
        )
    return reasons


def _validate_volatility_cost(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    metric = _metric(payload, "volatility_cost")
    arithmetic_return = number(metric.get("arithmetic_return_annual"))
    geometric_return = number(metric.get("geometric_return_annual"))
    realized_drag = number(metric.get("realized_volatility_drag"))
    realized_vol = number(metric.get("realized_volatility_annual"))
    half_variance = number(metric.get("half_variance_benchmark"))
    if None in {
        arithmetic_return,
        geometric_return,
        realized_drag,
        realized_vol,
        half_variance,
    }:
        return ["BLOCK_FACTORFORGE_VOLATILITY_COST_FIELDS_MISSING"]
    if (
        realized_vol < 0
        or realized_drag < 0
        or half_variance < 0
    ):
        reasons.append("BLOCK_FACTORFORGE_VOLATILITY_COST_RANGE_INVALID")
    tolerance = number(metric.get("reconciliation_tolerance")) or 1e-8
    if not close_enough(
        realized_drag,
        arithmetic_return - geometric_return,
        tolerance,
    ):
        reasons.append("BLOCK_FACTORFORGE_VOLATILITY_COST_RECONCILIATION_FAILED")
    if not close_enough(half_variance, 0.5 * realized_vol * realized_vol, tolerance):
        reasons.append("BLOCK_FACTORFORGE_HALF_VARIANCE_BENCHMARK_RECONCILIATION_FAILED")
    if not nonempty_str(metric.get("return_compounding_convention")):
        reasons.append("BLOCK_FACTORFORGE_VOLATILITY_COST_CONVENTION_MISSING")
    reasons.extend(_validate_return_path_binding(payload, "volatility_cost"))
    return reasons


def _validate_transaction_cost(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    metric = _metric(payload, "transaction_cost")
    gross = number(metric.get("gross_return_annual"))
    net = number(metric.get("net_return_annual"))
    turnover = number(metric.get("annual_turnover"))
    cost_bps = number(metric.get("cost_bps_per_turnover"))
    other = number(metric.get("other_annual_costs"))
    modeled = number(metric.get("modeled_cost_annual"))
    if None in {gross, net, turnover, cost_bps, other, modeled}:
        return ["BLOCK_FACTORFORGE_TRANSACTION_COST_FIELDS_MISSING"]
    if turnover < 0 or cost_bps < 0 or other < 0 or modeled < 0:
        reasons.append("BLOCK_FACTORFORGE_TRANSACTION_COST_RANGE_INVALID")
    tolerance = number(metric.get("reconciliation_tolerance")) or 1e-8
    expected_cost = turnover * cost_bps / 10000.0 + other
    if not close_enough(modeled, expected_cost, tolerance):
        reasons.append("BLOCK_FACTORFORGE_TRANSACTION_COST_MODEL_RECONCILIATION_FAILED")
    if not close_enough(net, gross - modeled, tolerance):
        reasons.append("BLOCK_FACTORFORGE_NET_RETURN_RECONCILIATION_FAILED")
    long_end = _metric(payload, "long_end")
    if number(long_end.get("gross_return_annual")) is not None and not close_enough(
        long_end.get("gross_return_annual"),
        gross,
        tolerance,
    ):
        reasons.append("BLOCK_FACTORFORGE_LONG_END_GROSS_COST_SAMPLE_MISMATCH")
    if number(long_end.get("net_return_annual")) is not None and not close_enough(
        long_end.get("net_return_annual"),
        net,
        tolerance,
    ):
        reasons.append("BLOCK_FACTORFORGE_LONG_END_NET_COST_SAMPLE_MISMATCH")
    for field in (
        "turnover_definition",
        "cost_scope",
        "execution_assumption",
        "annual_return_convention",
    ):
        if not nonempty_str(metric.get(field)):
            reasons.append(f"BLOCK_FACTORFORGE_TRANSACTION_COST_CONVENTION_MISSING:{field}")
    reasons.extend(_validate_return_path_binding(payload, "transaction_cost"))
    return reasons


def _validate_drawdown(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    metric = _metric(payload, "drawdown")
    max_drawdown = number(metric.get("max_drawdown"))
    recovery_days = number(metric.get("recovery_days"))
    recovery_area = number(metric.get("recovery_area"))
    if max_drawdown is None or recovery_days is None or recovery_area is None:
        return ["BLOCK_FACTORFORGE_DRAWDOWN_FIELDS_MISSING"]
    if max_drawdown > 0 or max_drawdown < -1:
        reasons.append("BLOCK_FACTORFORGE_MAX_DRAWDOWN_SIGN_INVALID")
    if recovery_days < 0 or recovery_area < 0:
        reasons.append("BLOCK_FACTORFORGE_DRAWDOWN_GEOMETRY_INVALID")
    if not nonempty_str(metric.get("nav_definition")):
        reasons.append("BLOCK_FACTORFORGE_DRAWDOWN_NAV_DEFINITION_MISSING")
    reasons.extend(_validate_return_path_binding(payload, "drawdown"))
    return reasons


def _validate_long_end(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    metric = _metric(payload, "long_end")
    for field in (
        "gross_return_annual",
        "net_return_annual",
        "net_geometric_return_annual",
        "terminal_wealth",
        "minimum_wealth",
        "sharpe_net",
        "coverage",
    ):
        if number(metric.get(field)) is None:
            reasons.append(f"BLOCK_FACTORFORGE_LONG_END_FIELD_MISSING:{field}")
    for field in (
        "selection_rule",
        "weighting",
        "rebalance_frequency",
        "annual_return_convention",
    ):
        if not nonempty_str(metric.get(field)):
            reasons.append(f"BLOCK_FACTORFORGE_LONG_END_CONTRACT_MISSING:{field}")
    coverage = number(metric.get("coverage"))
    if coverage is not None and not 0 <= coverage <= 1:
        reasons.append("BLOCK_FACTORFORGE_LONG_END_COVERAGE_INVALID")
    if metric.get("short_leg_used_for_acceptance") is not False:
        reasons.append("BLOCK_FACTORFORGE_LONG_END_ACCEPTANCE_USES_SHORT_LEG")
    terminal_wealth = number(metric.get("terminal_wealth"))
    minimum_wealth = number(metric.get("minimum_wealth"))
    if (
        terminal_wealth is None
        or minimum_wealth is None
        or terminal_wealth <= 0
        or minimum_wealth <= 0
    ):
        reasons.append("BLOCK_FACTORFORGE_LONG_END_WEALTH_SURVIVAL_FAILED")
    if metric.get("evidence_role") != PROMOTION_EVIDENCE_ROLE:
        reasons.append("BLOCK_FACTORFORGE_LONG_END_EVIDENCE_ROLE_INVALID")
    if (
        (payload.get("data_contract") or {}).get(
            "same_sample_for_all_required_metrics"
        )
        is True
        and coverage is not None
        and not close_enough(coverage, 1.0)
    ):
        reasons.append("BLOCK_FACTORFORGE_LONG_END_SAMPLE_COVERAGE_MISMATCH")
    reasons.extend(_validate_return_path_binding(payload, "long_end"))
    return reasons


def _validate_monotonicity(payload: dict[str, Any], claim_class: str) -> list[str]:
    reasons: list[str] = []
    metric = _metric(payload, "bucket_monotonicity")
    if claim_class != "risk_premium":
        if metric.get("required_for_acceptance") is True:
            reasons.append("BLOCK_FACTORFORGE_MONOTONICITY_GATE_OUTSIDE_RISK_PREMIUM")
        if metric.get("evidence_role") == PROMOTION_EVIDENCE_ROLE:
            reasons.append("BLOCK_FACTORFORGE_MONOTONICITY_PROMOTION_ROLE_OUTSIDE_RISK_PREMIUM")
        return reasons
    if not metric:
        return ["BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_MISSING"]
    bucket_count = metric.get("bucket_count")
    if bucket_count not in {5, 10}:
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_BUCKET_COUNT_INVALID")
    if metric.get("required_for_acceptance") is not True:
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_NOT_REQUIRED")
    if metric.get("evidence_role") != PROMOTION_EVIDENCE_ROLE:
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_ROLE_INVALID")
    for field in (
        "monotonicity_score",
        "adjacent_pairs_total",
        "adjacent_pairs_violated",
        "period_count",
    ):
        if number(metric.get(field)) is None:
            reasons.append(f"BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_FIELD_MISSING:{field}")
    direction = metric.get("expected_direction")
    if direction not in {"ascending", "descending"}:
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_DIRECTION_MISSING")
    bucket_returns = metric.get("bucket_returns")
    if (
        not isinstance(bucket_returns, list)
        or bucket_count not in {5, 10}
        or len(bucket_returns) != bucket_count
        or any(number(value) is None for value in bucket_returns)
    ):
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_BUCKET_RETURNS_INVALID")
        return reasons
    values = [float(value) for value in bucket_returns]
    pairs_total = len(values) - 1
    pairs_violated = sum(
        1
        for left, right in zip(values, values[1:])
        if (
            (direction == "ascending" and right < left)
            or (direction == "descending" and right > left)
        )
    )
    score = (pairs_total - pairs_violated) / pairs_total
    if not close_enough(metric.get("adjacent_pairs_total"), pairs_total):
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_TOTAL_MISMATCH")
    if not close_enough(metric.get("adjacent_pairs_violated"), pairs_violated):
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_VIOLATIONS_MISMATCH")
    if not close_enough(metric.get("monotonicity_score"), score):
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_SCORE_MISMATCH")
    if metric.get("period_count") != _metric(payload, "ic").get("period_count"):
        reasons.append("BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_SAMPLE_MISMATCH")
    if (
        not isinstance(metric.get("period_count"), int)
        or metric["period_count"] < _minimum_periods(payload)
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_PERIOD_COUNT_INVALID"
        )
    return reasons


def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return actual > threshold
    if operator == ">=":
        return actual >= threshold
    if operator == "<":
        return actual < threshold
    if operator == "<=":
        return actual <= threshold
    if operator == "==":
        return actual == threshold
    if operator == "abs>=":
        return abs(actual) >= threshold
    if operator == "abs<=":
        return abs(actual) <= threshold
    raise ValueError(f"unsupported decision operator: {operator}")


def _validate_threshold_registration(
    payload: dict[str, Any],
    *,
    workspace_root: Path | None,
) -> list[str]:
    registration = payload.get("threshold_registration")
    if not isinstance(registration, dict):
        return ["BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLDS_UNREGISTERED"]
    reasons: list[str] = []
    if registration.get("registered_before_evaluation") is not True:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLDS_POST_HOC")
    rules = payload.get("decision_rules")
    rules = rules if isinstance(rules, list) else []
    expected_rule_set_hash = stable_hash(rules)
    if registration.get("rule_set_sha256") != expected_rule_set_hash:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_RULE_SET_HASH_MISMATCH")
    for field in ("registration_ref", "registration_sha256"):
        if not nonempty_str(registration.get(field)):
            reasons.append(
                f"BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_PROVENANCE_MISSING:{field}"
            )
    registration_sha = registration.get("registration_sha256")
    if (
        isinstance(registration_sha, str)
        and registration_sha
        and not SHA256_RE.fullmatch(registration_sha.strip().lower())
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_HASH_INVALID"
        )
    if workspace_root is None:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_WORKSPACE_MISSING")
        return reasons
    path = resolve_workspace_evidence_path(
        workspace_root,
        registration.get("registration_ref"),
    )
    if path is None:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_PATH_INVALID")
        return reasons
    if not path.is_file():
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_MISSING")
        return reasons
    if registration_sha and sha256_file(path) != registration_sha:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_HASH_MISMATCH")
        return reasons
    try:
        registration_payload = load_json(path)
    except Exception:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_INVALID")
        return reasons
    if registration_payload.get("registration_status") != "LOCKED":
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_NOT_LOCKED")
    if registration_payload.get("version") != THRESHOLD_REGISTRATION_VERSION:
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_VERSION_INVALID"
        )
    data_contract = payload.get("data_contract")
    data_contract = data_contract if isinstance(data_contract, dict) else {}
    expected_bindings = {
        "report_id": payload.get("report_id"),
        "factor_id": payload.get("factor_id"),
        "claim_class": payload.get("claim_class"),
        "window_hash": data_contract.get("window_hash"),
        "evaluation_contract_hash": data_contract.get(
            "evaluation_contract_hash"
        ),
        "label_contract_hash": data_contract.get("label_contract_hash"),
        "search_trial_ledger_ref": data_contract.get(
            "search_trial_ledger_ref"
        ),
    }
    for field, expected in expected_bindings.items():
        if registration_payload.get(field) != expected:
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_IDENTITY_MISMATCH:"
                f"{field}"
            )
    if registration_payload.get("rule_set_sha256") != expected_rule_set_hash:
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_CONTENT_MISMATCH"
        )
    if registration_payload.get("decision_rules") != rules:
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_RULES_MISMATCH"
        )
    return reasons


def _required_rule_families(claim_class: str) -> dict[str, set[str]]:
    families = {
        family: REQUIRED_DECISION_PATHS[family]
        for family in (
            "ic",
            "icir",
            "volatility_cost",
            "transaction_cost",
            "drawdown",
            "long_end",
        )
    }
    if claim_class == "risk_premium":
        families.update(
            {
                "fama_macbeth": REQUIRED_DECISION_PATHS["fama_macbeth"],
                "bucket_monotonicity": REQUIRED_DECISION_PATHS[
                    "bucket_monotonicity"
                ],
            }
        )
    return families


def _derive_verdict(
    payload: dict[str, Any],
    *,
    workspace_root: Path | None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    registration = payload.get("threshold_registration")
    if not isinstance(registration, dict):
        return "BLOCK", [], ["BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLDS_UNREGISTERED"]
    registration_reasons = _validate_threshold_registration(
        payload,
        workspace_root=workspace_root,
    )
    if registration_reasons:
        return "BLOCK", [], registration_reasons
    rules = payload.get("decision_rules")
    if not isinstance(rules, list) or not rules:
        return "BLOCK", [], ["BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULES_MISSING"]
    outcomes: list[dict[str, Any]] = []
    failure_verdicts: list[str] = []
    reasons: list[str] = []
    rule_ids: set[str] = set()
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            reasons.append(f"BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_INVALID:{idx}")
            continue
        path = rule.get("metric_path")
        operator = rule.get("operator")
        threshold = number(rule.get("threshold"))
        on_fail = rule.get("on_fail")
        actual = nested(payload, str(path or ""))
        actual_number = number(actual)
        rule_id = rule.get("rule_id")
        if (
            not nonempty_str(rule_id)
            or not nonempty_str(path)
            or path not in ALLOWED_DECISION_PATHS
            or operator not in {">", ">=", "<", "<=", "==", "abs>=", "abs<="}
            or threshold is None
            or on_fail not in {"REJECT", "INCONCLUSIVE", "BLOCK"}
        ):
            reasons.append(f"BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_INVALID:{idx}")
            continue
        if rule_id in rule_ids:
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_ID_DUPLICATE:"
                f"{rule_id}"
            )
            continue
        rule_ids.add(str(rule_id))
        guardrail = CORE_RULE_GUARDRAILS.get(str(path))
        if guardrail is not None:
            allowed_operators, minimum, maximum = guardrail
            if (
                operator not in allowed_operators
                or threshold < minimum
                or (maximum is not None and threshold > maximum)
            ):
                reasons.append(
                    "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_GUARDRAIL_INVALID:"
                    f"{rule_id}"
                )
        if actual_number is None:
            passed = False
            outcome = "BLOCK"
        else:
            passed = _compare(actual_number, str(operator), threshold)
            outcome = "PASS" if passed else str(on_fail)
        if not passed:
            failure_verdicts.append(outcome)
        outcomes.append(
            {
                "rule_id": rule_id,
                "metric_path": path,
                "actual": actual_number,
                "operator": operator,
                "threshold": threshold,
                "passed": passed,
                "outcome": outcome,
            }
        )
    rule_paths = {
        str(rule.get("metric_path") or "")
        for rule in rules
        if isinstance(rule, dict)
    }
    claim_class = str(payload.get("claim_class") or "")
    for family, allowed_paths in _required_rule_families(claim_class).items():
        if not rule_paths.intersection(allowed_paths):
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_COVERAGE_MISSING:"
                f"{family}"
            )
    control_columns = (
        (payload.get("data_contract") or {}).get("control_columns")
        if isinstance(payload.get("data_contract"), dict)
        else []
    )
    if (
        control_columns
        and "metrics.control_residualization.residual_rank_ic_mean"
        not in rule_paths
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_COVERAGE_MISSING:"
            "control_residualization"
        )
    if claim_class != "risk_premium":
        for forbidden_prefix in (
            "metrics.fama_macbeth.",
            "metrics.bucket_monotonicity.",
        ):
            if any(path.startswith(forbidden_prefix) for path in rule_paths):
                reasons.append(
                    "BLOCK_FACTORFORGE_RISK_PREMIUM_RULE_OUTSIDE_RISK_PREMIUM:"
                    f"{forbidden_prefix.rstrip('.')}"
                )
    if reasons or "BLOCK" in failure_verdicts:
        return "BLOCK", outcomes, reasons
    if "REJECT" in failure_verdicts:
        return "REJECT", outcomes, reasons
    if "INCONCLUSIVE" in failure_verdicts:
        return "INCONCLUSIVE", outcomes, reasons
    return "ACCEPT", outcomes, reasons


def derive_factor_proof_verdict(
    payload: dict[str, Any],
    *,
    workspace_root: Path | None,
) -> dict[str, Any]:
    """Evaluate preregistered decision rules without trusting a declared verdict."""
    verdict, outcomes, reasons = _derive_verdict(
        payload,
        workspace_root=workspace_root,
    )
    return {
        "verdict": verdict,
        "decision_rule_outcomes": outcomes,
        "block_reasons": list(dict.fromkeys(reasons)),
    }


def validate_factor_proof_certificate(
    payload: dict[str, Any],
    *,
    workspace_root: Path | None = None,
    expected_report_id: str | None = None,
    expected_factor_id: str | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    current_replay = bool(
        incident_trust_root is not None and incident_installation_id
    )
    if bool(incident_trust_root is not None) != bool(incident_installation_id):
        return {
            "certificate_version": CERTIFICATE_VERSION,
            "report_id": payload.get("report_id"),
            "factor_id": payload.get("factor_id"),
            "verdict": "BLOCK",
            "declared_verdict": payload.get("declared_verdict"),
            "block_reasons": [
                "BLOCK_FACTORFORGE_FACTOR_PROOF_INCIDENT_HOST_CONTEXT_INCOMPLETE"
            ],
            "decision_rule_outcomes": [],
            "current_formal_authority_verified": False,
        }
    if current_replay and _incident_guard is None:
        trust_root = incident_trust_root.expanduser().resolve(strict=True)
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id=str(incident_installation_id),
        ) as guard:
            return validate_factor_proof_certificate(
                payload,
                workspace_root=workspace_root,
                expected_report_id=expected_report_id,
                expected_factor_id=expected_factor_id,
                incident_trust_root=trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=guard,
            )
    reasons: list[str] = []
    if current_replay:
        assert incident_trust_root is not None
        assert incident_installation_id is not None
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=incident_trust_root,
            installation_id=incident_installation_id,
        )
        if workspace_root is None:
            reasons.append(
                "BLOCK_FACTORFORGE_FACTOR_PROOF_CURRENT_WORKSPACE_REQUIRED"
            )
        else:
            reasons.extend(
                formal_oos_incident_reasons(
                    workspace_root=workspace_root,
                    report_id=str(payload.get("report_id") or ""),
                    trust_root=incident_trust_root,
                    installation_id=incident_installation_id,
                )
            )
    if payload.get("certificate_version") != CERTIFICATE_VERSION:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_VERSION_INVALID")
    for field in ("report_id", "factor_id"):
        if not nonempty_str(payload.get(field)):
            reasons.append(f"BLOCK_FACTORFORGE_FACTOR_PROOF_IDENTITY_MISSING:{field}")
    if expected_report_id is not None and payload.get("report_id") != expected_report_id:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_REPORT_ID_MISMATCH")
    if expected_factor_id is not None and payload.get("factor_id") != expected_factor_id:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_FACTOR_ID_MISMATCH")
    claim_class = str(payload.get("claim_class") or "")
    if claim_class not in CLAIM_CLASSES:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_CLAIM_CLASS_INVALID")
    if (
        payload.get("declared_verdict") == "ACCEPT"
        and claim_class in {"mixed", "unknown"}
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_ACCEPT_WITH_AMBIGUOUS_CLAIM_CLASS"
        )
    reasons.extend(_validate_data_contract(payload))
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    required_metrics = set(COMMON_REQUIRED_METRICS)
    control_columns = (
        (payload.get("data_contract") or {}).get("control_columns")
        if isinstance(payload.get("data_contract"), dict)
        else []
    )
    if control_columns:
        required_metrics.add("control_residualization")
    if claim_class == "risk_premium":
        required_metrics.update(RISK_PREMIUM_REQUIRED_METRICS)
    missing_metrics = sorted(name for name in required_metrics if not isinstance(metrics.get(name), dict))
    if missing_metrics:
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_REQUIRED_METRICS_MISSING:"
            + ",".join(missing_metrics)
        )
    reasons.extend(
        _validate_evidence_bindings(
            payload,
            workspace_root=workspace_root,
            required_metrics=required_metrics,
            incident_trust_root=(incident_trust_root if current_replay else None),
            incident_installation_id=(
                incident_installation_id if current_replay else None
            ),
            _incident_guard=(_incident_guard if current_replay else None),
        )
    )
    reasons.extend(_validate_ic(payload))
    reasons.extend(_validate_icir(payload))
    reasons.extend(_validate_control_residualization(payload))
    reasons.extend(_validate_fama_macbeth(payload, claim_class))
    reasons.extend(_validate_volatility_cost(payload))
    reasons.extend(_validate_transaction_cost(payload))
    reasons.extend(_validate_drawdown(payload))
    reasons.extend(_validate_long_end(payload))
    reasons.extend(_validate_monotonicity(payload, claim_class))

    derived_verdict, rule_outcomes, rule_reasons = _derive_verdict(
        payload,
        workspace_root=workspace_root,
    )
    reasons.extend(rule_reasons)
    declared_verdict = payload.get("declared_verdict")
    if declared_verdict not in VERDICTS:
        reasons.append("BLOCK_FACTORFORGE_FACTOR_PROOF_DECLARED_VERDICT_INVALID")
    if reasons:
        derived_verdict = "BLOCK"
    elif declared_verdict != derived_verdict:
        reasons.append(
            "BLOCK_FACTORFORGE_FACTOR_PROOF_VERDICT_MISMATCH:"
            f"declared={declared_verdict}:derived={derived_verdict}"
        )
        derived_verdict = "BLOCK"
    return {
        "certificate_version": CERTIFICATE_VERSION,
        "report_id": payload.get("report_id"),
        "factor_id": payload.get("factor_id"),
        "claim_class": claim_class,
        "verdict": derived_verdict,
        "declared_verdict": declared_verdict,
        "block_reasons": list(dict.fromkeys(reasons)),
        "decision_rule_outcomes": rule_outcomes,
        "current_formal_authority_verified": bool(current_replay and not reasons),
        "risk_premium_specific": {
            "fama_macbeth_required": claim_class == "risk_premium",
            "quintile_or_decile_monotonicity_required": claim_class == "risk_premium",
        },
    }
