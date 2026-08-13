from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from factor_factory.data_access.paths import resolve_local_tushare_paths
from factor_factory.data_access.step4 import (
    build_forward_return_frame,
    normalize_trade_date_series,
)
from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.parser import parse_formula
from factor_factory.evo_oos import (
    OOS_ALLOCATION_AUTHORITY_SECURE,
    formal_oos_incident_reasons,
    oos_allocation_path,
    validate_oos_release_authorization,
    validate_oos_release_consumption,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.metric_verifier import (
    LABEL_CONTRACT_VERSION,
    TRADING_CALENDAR_REGISTRY_PATH,
    TRADING_CALENDAR_REGISTRY_TRUST_BLOB,
    TRADING_CALENDAR_REGISTRY_TRUST_COMMIT,
    TRADING_CALENDAR_REGISTRY_TRUST_SHA256,
    VERIFIER_SPEC_VERSION,
    metric_verifier_identities,
    run_metric_verifier,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_conjecture import (
    epistemic_evolution_enabled,
    epistemic_evolution_lifecycle_path,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.research_obligation_verifier import (
    component_verifier_identities,
    run_component_obligation_verifier,
    validate_component_obligation_report,
)
from factor_factory.research_proof import (
    CERTIFICATE_VERSION,
    derive_factor_proof_verdict,
    factor_proof_certificate_path,
    validate_factor_proof_certificate,
)
from factor_factory.research_release import (
    COMPONENT_THRESHOLD_REGISTRATION_VERSION,
    COMPONENT_VERIFIER_SPEC_VERSION,
    MINIMUM_FORMAL_DAILY_PERIODS,
    METRIC_THRESHOLD_REGISTRATION_VERSION,
    METRIC_VERIFIER_SPEC_VERSION,
    SEARCH_TRIAL_LEDGER_VERSION,
    evaluation_contract_hash,
    stable_hash,
    validate_threshold_decision_rules,
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)


PREREGISTRATION_VERSION = "factorforge_web_factor_proof_preregistration_v1"
FINALIZATION_VERSION = "factorforge_web_factor_proof_finalization_v1"
BOUND_VERIFIER_VERSION = "factorforge_console_bound_factor_proof_verifier_v1"
EVO_IS_DIAGNOSTICS_VERSION = "factorforge_web_evo_is_diagnostics_v1"
EVO_IS_DIAGNOSTICS_VERIFIER_ID = "factorforge_web_evo_is_diagnostics_verifier_v1"
HOST_AGENT_TERMINATION_AUTHORITY_VERSION = (
    "factorforge_web_host_agent_termination_authority_v1"
)
BLOCK_PREREGISTRATION = "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PREREGISTRATION_INVALID"
BLOCK_FINALIZATION = "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_FINALIZATION_INVALID"
BLOCK_EVO_IS_DIAGNOSTICS = "BLOCK_FACTORFORGE_WEB_EVO_IS_DIAGNOSTICS_INVALID"
BLOCK_EVO_OOS_SEQUENCE = "BLOCK_FACTORFORGE_WEB_EVO_OOS_SEQUENCE_INVALID"
CALENDAR_SNAPSHOT_ID = "tushare_sse_open_days_19901219_20261231"
RISK_PROOF_CONTROL_COLUMNS = ("total_mv", "turnover_rate")
BEHAVIORAL_PROOF_SOURCE_CONTROL_COLUMNS = (
    "pct_chg",
    "turnover_rate",
    "ln_mcap_free",
    "volume_ratio",
)
BEHAVIORAL_PROOF_CONTROL_COLUMNS = (
    "pct_chg",
    "abs_pct_chg",
    "turnover_rate",
    "ln_mcap_free",
    "volume_ratio",
)


def _resolve_web_incident_host_context(
    trust_root: Path | str | None,
    installation_id: str | None,
    *,
    block_token: str,
) -> tuple[Path, str]:
    trust_raw = (
        str(trust_root)
        if trust_root is not None
        else os.environ.get("FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT")
        or os.environ.get("FACTORFORGE_OOS_HOST_TRUST_ROOT")
    )
    installation_raw = (
        installation_id
        or os.environ.get("FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID")
        or os.environ.get("FACTORFORGE_OOS_HOST_INSTALLATION_ID")
    )
    if not trust_raw or not installation_raw:
        raise ValueError(f"{block_token}: incident Host context required")
    return Path(trust_raw).expanduser().resolve(strict=True), str(installation_raw)


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_host_agent_termination_authority(
    authority: Any,
    *,
    report_id: str,
) -> dict[str, Any]:
    fields = {
        "authority_version",
        "termination_receipt_ref",
        "termination_receipt_id",
        "termination_receipt_sha256",
        "stage_name",
        "attempt",
        "parent_report_id",
        "child_report_id",
        "job_id_sha256",
        "expected_host_trust_manifest_sha256",
        "admission_receipt_id",
        "inflight_receipt_id",
        "logical_command_sha256",
        "image_digest_sha256",
        "mounts_sha256",
        "workspace_post_tree_sha256",
        "network",
        "process_tree_absent",
    }
    hashes = {
        "termination_receipt_id",
        "termination_receipt_sha256",
        "job_id_sha256",
        "expected_host_trust_manifest_sha256",
        "logical_command_sha256",
        "image_digest_sha256",
        "mounts_sha256",
        "workspace_post_tree_sha256",
        "admission_receipt_id",
        "inflight_receipt_id",
    }
    if (
        not isinstance(authority, dict)
        or set(authority) != fields
        or authority.get("authority_version")
        != HOST_AGENT_TERMINATION_AUTHORITY_VERSION
        or authority.get("termination_receipt_ref")
        != "HOST_PRIVATE_SIGNED_EVO_CHILD_CONTAINER_TERMINATION"
        or authority.get("stage_name") != "validate_step4"
        or isinstance(authority.get("attempt"), bool)
        or not isinstance(authority.get("attempt"), int)
        or authority.get("attempt", 0) < 1
        or not isinstance(authority.get("parent_report_id"), str)
        or not authority.get("parent_report_id")
        or authority.get("child_report_id") != report_id
        or any(not _valid_sha256(authority.get(field)) for field in hashes)
        or authority.get("network") != "none"
        or authority.get("process_tree_absent") is not True
    ):
        raise ValueError(
            f"{BLOCK_FINALIZATION}: Host Agent termination authority invalid"
        )
    return dict(authority)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_json_immutable(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or _read_json(path) != payload:
            raise ValueError(f"{BLOCK_FINALIZATION}: immutable output mismatch")
        return
    _write_json_atomic(path, payload)


def _workspace_path(root: Path, raw: str | Path, *, must_exist: bool) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"{BLOCK_FINALIZATION}: path escapes workspace")
    if must_exist and (not candidate.is_file() or candidate.is_symlink()):
        raise ValueError(f"{BLOCK_FINALIZATION}: workspace input missing or unsafe")
    return candidate


def web_factor_proof_paths(root: Path, report_id: str) -> dict[str, Path]:
    protocol = root / "objects" / "research_protocol"
    return {
        "search_ledger": protocol / f"search_trial_ledger__{report_id}.json",
        "spec": protocol / f"metric_verifier_spec__{report_id}.json",
        "bound_spec": protocol / f"metric_verifier_bound_spec__{report_id}.json",
        "threshold": protocol / f"threshold_registration__{report_id}.json",
        "release": protocol / f"oos_release_manifest__{report_id}.json",
        "panel": protocol / f"factor_proof_panel__{report_id}.parquet",
        "certificate": factor_proof_certificate_path(root, report_id),
        "verifier": protocol / f"factor_proof_verifier_report__{report_id}.json",
        "preregistration": protocol / f"web_factor_proof_preregistration__{report_id}.json",
        "finalization": protocol / f"web_factor_proof_finalization__{report_id}.json",
        "evo_is_panel": protocol / f"evo_purged_is_panel__{report_id}.parquet",
        "evo_is_diagnostics": protocol / f"evo_purged_is_diagnostics__{report_id}.json",
    }


def _component_obligation_paths(
    root: Path,
    report_id: str,
    component_id: str,
) -> dict[str, Path]:
    protocol = root / "objects" / "research_protocol"
    suffix = f"{report_id}__{component_id}"
    return {
        "spec": protocol / f"component_obligation_spec__{suffix}.json",
        "threshold": protocol
        / f"component_obligation_threshold__{suffix}.json",
        "release": protocol / f"component_oos_release__{suffix}.json",
    }


def _component_obligation_specs(
    *,
    root: Path,
    plan: dict[str, Any],
    metric_spec: dict[str, Any],
) -> list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Path]]]:
    program = plan.get("measurement_program")
    search = (
        program.get("search_policy")
        if isinstance(program, dict)
        and isinstance(program.get("search_policy"), dict)
        else {}
    )
    diagnostics = [
        item
        for item in search.get("registered_diagnostic_trials") or []
        if isinstance(item, dict) and item.get("role") == "leave_one_out"
    ]
    output = []
    for item in diagnostics:
        component_id = str(item["component_id"])
        trial_id = str(item["trial_id"])
        paths = _component_obligation_paths(
            root,
            str(plan["identity"]["report_id"]),
            component_id,
        )
        window = dict(metric_spec["window_contract"])
        window["oos_release_manifest_ref"] = str(
            paths["release"].relative_to(root)
        )
        spec = {
            "version": "factorforge_component_obligation_spec_v1",
            "report_id": plan["identity"]["report_id"],
            "factor_id": plan["identity"]["factor_id"],
            "obligation_id": f"component_ablation__{component_id}",
            "obligation_kind": "component_ablation",
            "window_contract": window,
            "panel": {
                "date_column": metric_spec["panel"]["date_column"],
                "asset_column": metric_spec["panel"]["asset_column"],
                "full_signal_column": metric_spec["panel"]["signal_column"],
                "ablated_signal_column": f"diagnostic__{trial_id}",
                "forward_return_column": metric_spec["panel"][
                    "forward_return_column"
                ],
            },
            "test": {
                "expected_direction": "positive",
                "long_quantile": metric_spec["portfolio"]["long_quantile"],
            },
            "threshold_registration_ref": str(
                paths["threshold"].relative_to(root)
            ),
        }
        rules = [
            {
                "rule_id": f"{component_id}_rank_ic_incremental",
                "metric_path": "metrics.rank_ic_delta",
                "operator": ">=",
                "threshold": 0.0,
            },
            {
                "rule_id": f"{component_id}_long_end_incremental",
                "metric_path": "metrics.long_end_delta",
                "operator": ">=",
                "threshold": 0.0,
            },
        ]
        output.append((spec, rules, paths))
    return output


def _trusted_calendar_snapshot(*, workspace_root: Path | None = None) -> dict[str, Any]:
    configured = os.getenv("FACTORFORGE_TRUSTED_TRADE_CAL_CSV")
    calendar_path = (
        Path(configured).expanduser().resolve(strict=False)
        if configured
        else Path(resolve_local_tushare_paths().trade_cal_csv).expanduser().resolve(
            strict=False
        )
    )
    if workspace_root is not None:
        root = workspace_root.resolve(strict=False)
        if calendar_path == root or root in calendar_path.parents:
            raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar is not independent")
    if not calendar_path.is_file():
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar missing")
    if sha256_file(TRADING_CALENDAR_REGISTRY_PATH) != TRADING_CALENDAR_REGISTRY_TRUST_SHA256:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar registry diverged")
    registry = _read_json(TRADING_CALENDAR_REGISTRY_PATH)
    matches = [
        row
        for row in registry.get("snapshots") or []
        if isinstance(row, dict) and row.get("snapshot_id") == CALENDAR_SNAPSHOT_ID
    ]
    if len(matches) != 1 or matches[0].get("scope") != "production":
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar snapshot invalid")
    trusted = matches[0]
    frame = pd.read_csv(
        calendar_path,
        usecols=lambda column: column in {"exchange", "cal_date", "is_open"},
        dtype={"exchange": "string", "cal_date": "string", "is_open": "string"},
    )
    if "exchange" in frame.columns and (frame["exchange"] == "SSE").any():
        frame = frame[frame["exchange"] == "SSE"]
    dates = (
        frame.loc[frame["is_open"].astype(str) == "1", "cal_date"]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.zfill(8)
    )
    parsed = pd.to_datetime(dates, errors="coerce", utc=True)
    if parsed.isna().any():
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar dates invalid")
    normalized = parsed.dt.strftime("%Y-%m-%d").tolist()
    if normalized != sorted(set(normalized)):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: trusted calendar is not canonical")
    open_dates_sha256 = _stable_hash(normalized)
    if (
        trusted.get("open_dates_sha256") != open_dates_sha256
        or trusted.get("raw_file_sha256") != sha256_file(calendar_path)
        or trusted.get("date_count") != len(normalized)
        or trusted.get("date_min") != normalized[0]
        or trusted.get("date_max") != normalized[-1]
    ):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar snapshot is untrusted")
    return {
        "path": calendar_path,
        "dates": normalized,
        "open_dates_sha256": open_dates_sha256,
        "raw_file_sha256": sha256_file(calendar_path),
        "registry_sha256": TRADING_CALENDAR_REGISTRY_TRUST_SHA256,
        "registry_git_commit": TRADING_CALENDAR_REGISTRY_TRUST_COMMIT,
        "registry_git_blob": TRADING_CALENDAR_REGISTRY_TRUST_BLOB,
        "snapshot_id": CALENDAR_SNAPSHOT_ID,
    }


def validate_trusted_calendar_snapshot() -> dict[str, Any]:
    """Validate the independent production calendar before accepting formal work."""
    return _trusted_calendar_snapshot()


def trusted_calendar_healthy() -> bool:
    try:
        validate_trusted_calendar_snapshot()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return False
    return True


def _planned_signal_window(plan: dict[str, Any], calendar_dates: list[str]) -> dict[str, Any]:
    evidence = plan["evidence_policy"]
    oos_start = pd.Timestamp(str(evidence["oos_start"]), tz="UTC")
    oos_end = pd.Timestamp(str(evidence["oos_end"]), tz="UTC")
    eligible = [
        value
        for value in calendar_dates
        if oos_start <= pd.Timestamp(value, tz="UTC") <= oos_end
    ]
    if len(eligible) < MINIMUM_FORMAL_DAILY_PERIODS + 2:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: OOS window is too short")
    signal_dates = eligible[:-2]
    return {
        "oos_window": f"{evidence['oos_start']}/{evidence['oos_end']}",
        "observed_start_date": signal_dates[0],
        "observed_end_date": signal_dates[-1],
        "signal_dates": signal_dates,
    }


def _risk_control_columns(plan: dict[str, Any]) -> list[str]:
    claim_class = plan["economic_mechanism"]["claim_class"]
    if claim_class == "risk_premium":
        return list(RISK_PROOF_CONTROL_COLUMNS)
    if claim_class in {
        "behavioral_rent",
        "information_rent",
        "institutional_constraint_rent",
        "liquidity_rent",
        "mixed",
        "time_option_rent",
    }:
        return list(BEHAVIORAL_PROOF_CONTROL_COLUMNS)
    return []


def _source_control_columns(plan: dict[str, Any]) -> list[str]:
    if plan["economic_mechanism"]["claim_class"] == "risk_premium":
        return list(RISK_PROOF_CONTROL_COLUMNS)
    if _risk_control_columns(plan):
        return list(BEHAVIORAL_PROOF_SOURCE_CONTROL_COLUMNS)
    return []


def default_web_decision_rules(claim_class: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {"rule_id": "rank_ic_positive", "metric_path": "metrics.ic.mean", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "icir_positive", "metric_path": "metrics.icir.value", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "volatility_drag_bounded", "metric_path": "metrics.volatility_cost.realized_volatility_drag", "operator": "<=", "threshold": 1.0, "on_fail": "INCONCLUSIVE"},
        {"rule_id": "net_return_after_cost_positive", "metric_path": "metrics.transaction_cost.net_return_annual", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "drawdown_survival", "metric_path": "metrics.drawdown.max_drawdown", "operator": ">=", "threshold": -0.35, "on_fail": "REJECT"},
        {"rule_id": "long_end_positive", "metric_path": "metrics.long_end.net_geometric_return_annual", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "long_side_candidate_sharpe", "metric_path": "metrics.long_end.sharpe_net", "operator": ">=", "threshold": 0.5, "on_fail": "REJECT"},
    ]
    if claim_class == "risk_premium":
        rules.extend(
            [
                {"rule_id": "fama_macbeth_positive", "metric_path": "metrics.fama_macbeth.lambda_tstat", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
                {"rule_id": "bucket_monotonicity", "metric_path": "metrics.bucket_monotonicity.monotonicity_score", "operator": ">=", "threshold": 0.5, "on_fail": "INCONCLUSIVE"},
            ]
        )
    if claim_class != "unknown":
        rules.append(
            {
                "rule_id": "control_residual_rank_ic_positive",
                "metric_path": (
                    "metrics.control_residualization.residual_rank_ic_mean"
                ),
                "operator": ">",
                "threshold": 0.0,
                "on_fail": "REJECT",
            }
        )
    return rules


def build_web_metric_verifier_spec(
    plan: dict[str, Any],
    *,
    workspace_root: Path,
    calendar: dict[str, Any],
    oos_release_token_hash: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    identity = plan["identity"]
    evidence = plan["evidence_policy"]
    claim_class = str(plan["economic_mechanism"]["claim_class"])
    paths = web_factor_proof_paths(workspace_root, str(identity["report_id"]))
    planned = _planned_signal_window(plan, list(calendar["dates"]))
    controls = _risk_control_columns(plan)
    source_controls = _source_control_columns(plan)
    measurement_program = plan.get("measurement_program")
    search_policy = (
        measurement_program.get("search_policy")
        if isinstance(measurement_program, dict)
        and isinstance(measurement_program.get("search_policy"), dict)
        else {}
    )
    diagnostic_signal_columns = {
        str(item["trial_id"]): f"diagnostic__{item['trial_id']}"
        for item in search_policy.get("registered_diagnostic_trials") or []
        if isinstance(item, dict)
    }
    release_token = oos_release_token_hash or stable_hash(
        {
            "job_id": identity["job_id"],
            "oos_start": evidence["oos_start"],
            "oos_end": evidence["oos_end"],
        }
    )
    window = {
        "evaluation_window_role": "OOS_FINAL",
        "oos_window": planned["oos_window"],
        "observed_start_date": planned["observed_start_date"],
        "observed_end_date": planned["observed_end_date"],
        "minimum_periods": MINIMUM_FORMAL_DAILY_PERIODS,
        "oos_release_token_hash": release_token,
        "forward_return_horizon": "t+1 close to t+2 close",
        "forward_return_horizon_days": 1,
        "sample_frequency": "daily",
        "signal_timestamp": "t close",
        "execution_timestamp": "t+1 close",
        "label_start_timestamp": "t+1 close",
        "label_end_timestamp": "t+2 close",
        "forward_return_formula": "label_end_price/label_start_price-1",
        "path_is_disjoint": True,
        "universe_id": evidence["universe_id"],
        "investability_mask_id": evidence["investability_mask_id"],
        "search_frozen_before_oos_release": True,
        "return_convention": "simple_return",
        "search_trial_ledger_ref": str(paths["search_ledger"].relative_to(workspace_root)),
        "oos_release_manifest_ref": str(paths["release"].relative_to(workspace_root)),
    }
    spec: dict[str, Any] = {
        "version": VERIFIER_SPEC_VERSION,
        "verification_scope": "production",
        "report_id": identity["report_id"],
        "factor_id": identity["factor_id"],
        "research_id": identity["research_id"],
        "claim_class": claim_class,
        "cost_policy_id": evidence["cost_model_id"],
        "research_windows": {
            "is_window": f"{evidence['is_start']}/{evidence['is_end']}",
            "oos_window": planned["oos_window"],
        },
        "panel": {
            "date_column": "trade_date",
            "asset_column": "code",
            "signal_column": "factor_value",
            "forward_return_column": "future_return_1d",
            "control_columns": controls,
            "source_control_columns": source_controls,
            "diagnostic_signal_columns": diagnostic_signal_columns,
        },
        "label_contract": {
            "version": LABEL_CONTRACT_VERSION,
            "signal_date_column": "trade_date",
            "label_start_date_column": "label_start_date",
            "label_end_date_column": "label_end_date",
            "label_start_price_column": "label_start_price",
            "label_end_price_column": "label_end_price",
            "forward_return_column": "future_return_1d",
            "return_formula": "label_end_price/label_start_price-1",
            "return_tolerance": 1e-12,
            "signal_to_label_start_trading_days": 1,
            "holding_period_trading_days": 1,
            "path_is_disjoint": True,
            "label_start_timestamp": "t+1 close",
            "label_end_timestamp": "t+2 close",
            "trading_calendar_ref": "factorforge_data_access.trade_cal_csv",
            "trading_calendar_sha256": calendar["open_dates_sha256"],
            "trading_calendar_registry_sha256": calendar["registry_sha256"],
            "trading_calendar_registry_git_commit": calendar["registry_git_commit"],
            "trading_calendar_registry_git_blob": calendar["registry_git_blob"],
            "trading_calendar_snapshot_id": calendar["snapshot_id"],
            "trading_calendar_id": "cn_a_share_tushare_open_days",
        },
        "window_contract": window,
        "portfolio": {
            "annualization_factor": 252,
            "long_quantile": 0.1,
            "cost_bps_per_turnover": float(evidence["transaction_cost_bps"]),
            "other_annual_costs": 0.0,
            "cost_scope": "one-way turnover at the preregistered web research cost",
            "execution_assumption": "signal after t close; execute t+1 close; exit t+2 close",
            "rebalance_frequency": "daily",
            "return_path_mode": "daily_one_period_forward_return",
            "holding_period_days": 1,
        },
        "fama_macbeth": {"newey_west_lags": 3},
        "bucket_monotonicity": {"bucket_count": 10, "expected_direction": "ascending"},
        "threshold_registration_ref": str(paths["threshold"].relative_to(workspace_root)),
    }
    spec["window_hash"] = stable_hash(window)
    return spec, default_web_decision_rules(claim_class), planned["signal_dates"]


def _project_threshold_registration_from_frozen_controls(
    *,
    spec: dict[str, Any],
    decision_rules: list[dict[str, Any]],
    search_ledger_ref: str,
    search_ledger_sha256: str,
    freeze_sequence: int,
    registration_sequence: int = 20,
) -> dict[str, Any]:
    """Pure counterpart of the immutable threshold writer.

    This is intentionally private to the Web preregistration projector.  The
    caller must still publish the returned bytes through its own atomic Host
    transaction and replay them with the normal threshold/preregistration
    validators.
    """

    if (
        isinstance(freeze_sequence, bool)
        or not isinstance(freeze_sequence, int)
        or isinstance(registration_sequence, bool)
        or not isinstance(registration_sequence, int)
        or freeze_sequence >= registration_sequence
    ):
        raise ValueError(
            f"{BLOCK_PREREGISTRATION}: threshold registration order invalid"
        )
    validate_threshold_decision_rules(spec, decision_rules)
    window = spec.get("window_contract")
    if not isinstance(window, dict) or not window:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: window contract missing")
    base: dict[str, Any] = {
        "registration_status": "LOCKED",
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "window_hash": stable_hash(window),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "registered_before_evaluation": True,
        "registration_sequence": registration_sequence,
        "search_trial_ledger_ref": search_ledger_ref,
        "search_trial_ledger_sha256": search_ledger_sha256,
        "decision_rules": decision_rules,
        "rule_set_sha256": stable_hash(decision_rules),
    }
    if spec.get("version") == METRIC_VERIFIER_SPEC_VERSION:
        if spec.get("verification_scope") != "production":
            raise ValueError(
                f"{BLOCK_PREREGISTRATION}: verification scope invalid"
            )
        base.update(
            {
                "version": METRIC_THRESHOLD_REGISTRATION_VERSION,
                "claim_class": spec.get("claim_class"),
                "verification_scope": "production",
                "label_contract_hash": stable_hash(spec.get("label_contract")),
            }
        )
    elif spec.get("version") == COMPONENT_VERIFIER_SPEC_VERSION:
        base.update(
            {
                "version": COMPONENT_THRESHOLD_REGISTRATION_VERSION,
                "obligation_id": spec.get("obligation_id"),
                "obligation_kind": spec.get("obligation_kind"),
            }
        )
    else:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: verifier spec unsupported")
    return base


def _canonical_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_web_factor_proof_preregistration_from_frozen_controls(
    *,
    workspace_root: Path,
    plan: dict[str, Any],
    search_trial_ledger: dict[str, Any],
    metric_verifier_spec: dict[str, Any],
    threshold_registration: dict[str, Any],
    calendar: dict[str, Any],
    oos_release_token_hash: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
    current_authority: bool = True,
) -> dict[str, Any]:
    """Project a Web proof preregistration without writing or replacing controls.

    EVO child preregistration owns the atomic publication transaction.  This
    pure helper proves that its already-frozen ledger/spec/threshold are the
    exact Web-plan projection, then returns only the additional component
    controls and closed preregistration receipt that transaction must publish.
    """

    root = Path(workspace_root).expanduser().resolve(strict=True)
    report_id = str((plan.get("identity") or {}).get("report_id") or "")
    if current_authority and (
        incident_trust_root is None or not incident_installation_id
    ):
        raise ValueError(
            f"{BLOCK_PREREGISTRATION}: incident Host context required"
        )
    if _incident_guard is not None:
        if incident_trust_root is None or not incident_installation_id:
            raise ValueError(
                f"{BLOCK_PREREGISTRATION}: incident Host context incomplete"
            )
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=Path(incident_trust_root),
            installation_id=incident_installation_id,
        )
    if current_authority:
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=root,
            report_id=report_id,
            trust_root=(
                Path(incident_trust_root)
                if incident_trust_root is not None
                else None
            ),
            installation_id=incident_installation_id,
        )
        if incident_reasons:
            raise ValueError(";".join(incident_reasons))
    if not report_id or not isinstance(oos_release_token_hash, str):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: child inputs invalid")
    paths = web_factor_proof_paths(root, report_id)
    trusted_calendar = _trusted_calendar_snapshot(workspace_root=root)
    calendar_projection_fields = (
        "dates",
        "open_dates_sha256",
        "raw_file_sha256",
        "registry_sha256",
        "registry_git_commit",
        "registry_git_blob",
        "snapshot_id",
    )
    if any(calendar.get(key) != trusted_calendar.get(key) for key in calendar_projection_fields):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: calendar projection mismatch")
    expected_spec, _default_rules, signal_dates = build_web_metric_verifier_spec(
        plan,
        workspace_root=root,
        calendar=calendar,
        oos_release_token_hash=oos_release_token_hash,
    )
    if metric_verifier_spec != expected_spec:
        raise ValueError(f"{BLOCK_PREREGISTRATION}: metric spec projection mismatch")
    if (
        search_trial_ledger.get("version") != SEARCH_TRIAL_LEDGER_VERSION
        or search_trial_ledger.get("search_status") != "FROZEN"
        or search_trial_ledger.get("report_id") != report_id
        or search_trial_ledger.get("factor_id")
        != plan.get("identity", {}).get("factor_id")
        or search_trial_ledger.get("trial_count")
        != len(search_trial_ledger.get("trials") or [])
        or search_trial_ledger.get("trial_set_sha256")
        != stable_hash(search_trial_ledger.get("trials") or [])
    ):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: search ledger invalid")
    ledger_sha256 = _canonical_payload_sha256(search_trial_ledger)
    spec_sha256 = _canonical_payload_sha256(metric_verifier_spec)
    threshold_sha256 = _canonical_payload_sha256(threshold_registration)
    if (
        threshold_registration.get("registration_status") != "LOCKED"
        or threshold_registration.get("report_id") != report_id
        or threshold_registration.get("factor_id")
        != plan.get("identity", {}).get("factor_id")
        or threshold_registration.get("search_trial_ledger_ref")
        != str(paths["search_ledger"].relative_to(root))
        or threshold_registration.get("search_trial_ledger_sha256")
        != ledger_sha256
        or threshold_registration.get("window_hash")
        != stable_hash(metric_verifier_spec.get("window_contract"))
        or threshold_registration.get("evaluation_contract_hash")
        != evaluation_contract_hash(metric_verifier_spec)
        or threshold_registration.get("label_contract_hash")
        != stable_hash(metric_verifier_spec.get("label_contract"))
        or threshold_registration.get("rule_set_sha256")
        != stable_hash(threshold_registration.get("decision_rules"))
    ):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: threshold projection mismatch")
    validate_threshold_decision_rules(
        metric_verifier_spec,
        list(threshold_registration.get("decision_rules") or []),
    )

    component_artifacts: list[dict[str, Any]] = []
    component_preregistrations: list[dict[str, Any]] = []
    for component_spec, component_rules, component_paths in _component_obligation_specs(
        root=root,
        plan=plan,
        metric_spec=metric_verifier_spec,
    ):
        component_threshold = _project_threshold_registration_from_frozen_controls(
            spec=component_spec,
            decision_rules=component_rules,
            search_ledger_ref=str(paths["search_ledger"].relative_to(root)),
            search_ledger_sha256=ledger_sha256,
            freeze_sequence=int(search_trial_ledger["freeze_sequence"]),
        )
        component_spec_sha256 = _canonical_payload_sha256(component_spec)
        component_threshold_sha256 = _canonical_payload_sha256(component_threshold)
        component_artifacts.append(
            {
                "spec_path": component_paths["spec"],
                "spec": component_spec,
                "threshold_path": component_paths["threshold"],
                "threshold": component_threshold,
            }
        )
        component_preregistrations.append(
            {
                "obligation_id": component_spec["obligation_id"],
                "component_id": component_spec["obligation_id"].split(
                    "component_ablation__", 1
                )[1],
                "spec_ref": str(component_paths["spec"].relative_to(root)),
                "spec_sha256": component_spec_sha256,
                "threshold_ref": str(component_paths["threshold"].relative_to(root)),
                "threshold_sha256": component_threshold_sha256,
                "threshold_rule_set_sha256": component_threshold[
                    "rule_set_sha256"
                ],
            }
        )
    receipt = {
        "version": PREREGISTRATION_VERSION,
        "status": "LOCKED",
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
        "web_research_plan_sha256": stable_hash(plan),
        "search_trial_ledger_ref": str(paths["search_ledger"].relative_to(root)),
        "search_trial_ledger_sha256": ledger_sha256,
        "metric_verifier_spec_ref": str(paths["spec"].relative_to(root)),
        "metric_verifier_spec_sha256": spec_sha256,
        "evaluation_contract_hash": evaluation_contract_hash(metric_verifier_spec),
        "window_hash": stable_hash(metric_verifier_spec["window_contract"]),
        "label_contract_hash": stable_hash(metric_verifier_spec["label_contract"]),
        "threshold_registration_ref": str(paths["threshold"].relative_to(root)),
        "threshold_registration_sha256": threshold_sha256,
        "threshold_rule_set_sha256": threshold_registration["rule_set_sha256"],
        "planned_signal_dates_sha256": stable_hash(signal_dates),
        "planned_signal_period_count": len(signal_dates),
        "calendar_snapshot_id": calendar["snapshot_id"],
        "calendar_open_dates_sha256": calendar["open_dates_sha256"],
        "registered_before_step4": True,
        "oos_released": False,
        "component_obligation_preregistrations": component_preregistrations,
    }
    return {
        "preregistration_path": paths["preregistration"],
        "preregistration": receipt,
        "component_artifacts": component_artifacts,
    }


def prepare_web_factor_proof(
    *,
    workspace_root: Path,
    plan: dict[str, Any],
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    report_id = str((plan.get("identity") or {}).get("report_id") or "")
    marker_reasons = [
        reason
        for reason in formal_oos_incident_reasons(
            workspace_root=root,
            report_id=report_id,
        )
        if reason.endswith(":marker_present")
    ]
    if marker_reasons:
        raise ValueError(";".join(marker_reasons))
    trust_root, incident_installation_id = _resolve_web_incident_host_context(
        incident_trust_root,
        incident_installation_id,
        block_token=BLOCK_PREREGISTRATION,
    )
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=incident_installation_id,
    ) as guard:
        return _prepare_web_factor_proof_guarded(
            workspace_root=workspace_root,
            plan=plan,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=guard,
        )


def _prepare_web_factor_proof_guarded(
    *,
    workspace_root: Path,
    plan: dict[str, Any],
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    report_id = str(plan["identity"]["report_id"])
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=(
            Path(incident_trust_root)
            if incident_trust_root is not None
            else None
        ),
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    factor_id = str(plan["identity"]["factor_id"])
    paths = web_factor_proof_paths(root, report_id)
    if paths["preregistration"].is_file():
        return validate_web_factor_proof_preregistration(
            root,
            plan,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    spec, rules, signal_dates = build_web_metric_verifier_spec(
        plan,
        workspace_root=root,
        calendar=calendar,
    )
    preferred = next(
        row for row in plan["hypotheses"] if row.get("kind") == "preferred"
    )
    trial = {
        "trial_id": "web_intake_candidate_001",
        "status": "REGISTERED_NOT_EVALUATED",
        "hypothesis_id": preferred["hypothesis_id"],
        "formula_sha256": _stable_hash(plan["research_object"]["formula_or_law"]),
    }
    diagnostic_trials = []
    measurement_program = plan.get("measurement_program")
    search_policy = (
        measurement_program.get("search_policy")
        if isinstance(measurement_program, dict)
        and isinstance(measurement_program.get("search_policy"), dict)
        else {}
    )
    for item in search_policy.get("registered_diagnostic_trials") or []:
        diagnostic_trials.append(
            {
                "trial_id": item["trial_id"],
                "status": "REGISTERED_DIAGNOSTIC_NOT_EVALUATED",
                "hypothesis_id": preferred["hypothesis_id"],
                "formula_sha256": _stable_hash(item["formula_or_law"]),
                "role": item["role"],
                "component_id": item["component_id"],
                "affects_acceptance": False,
                "multiple_testing_family": item["multiple_testing_family"],
            }
        )
    write_search_trial_ledger(
        paths["search_ledger"],
        report_id=report_id,
        factor_id=factor_id,
        trials=[trial, *diagnostic_trials],
        candidate_space={
            "formula_or_law": plan["research_object"]["formula_or_law"],
            "hypotheses": plan["hypotheses"],
            "trial_budget": plan["evidence_policy"]["trial_budget"],
            "multiple_testing_policy": plan["evidence_policy"].get(
                "multiple_testing_policy", "UNSPECIFIED_LEGACY"
            ),
            "quarantined_sensitivities": search_policy.get("quarantined_sensitivities") or [],
        },
        selected_hypothesis=preferred,
    )
    component_preregistrations = []
    for component_spec, component_rules, component_paths in (
        _component_obligation_specs(root=root, plan=plan, metric_spec=spec)
    ):
        _write_json_immutable(component_paths["spec"], component_spec)
        component_threshold = write_threshold_registration(
            component_paths["threshold"],
            workspace_root=root,
            spec=component_spec,
            decision_rules=component_rules,
        )
        component_preregistrations.append(
            {
                "obligation_id": component_spec["obligation_id"],
                "component_id": component_spec["obligation_id"].split(
                    "component_ablation__", 1
                )[1],
                "spec_ref": str(component_paths["spec"].relative_to(root)),
                "spec_sha256": sha256_file(component_paths["spec"]),
                "threshold_ref": str(
                    component_paths["threshold"].relative_to(root)
                ),
                "threshold_sha256": sha256_file(component_paths["threshold"]),
                "threshold_rule_set_sha256": component_threshold[
                    "rule_set_sha256"
                ],
            }
        )
    _write_json_atomic(paths["spec"], spec)
    threshold = write_threshold_registration(
        paths["threshold"],
        workspace_root=root,
        spec=spec,
        decision_rules=rules,
    )
    receipt = {
        "version": PREREGISTRATION_VERSION,
        "status": "LOCKED",
        "report_id": report_id,
        "factor_id": factor_id,
        "research_id": plan["identity"]["research_id"],
        "web_research_plan_sha256": stable_hash(plan),
        "search_trial_ledger_ref": str(paths["search_ledger"].relative_to(root)),
        "search_trial_ledger_sha256": sha256_file(paths["search_ledger"]),
        "metric_verifier_spec_ref": str(paths["spec"].relative_to(root)),
        "metric_verifier_spec_sha256": sha256_file(paths["spec"]),
        "evaluation_contract_hash": evaluation_contract_hash(spec),
        "window_hash": stable_hash(spec["window_contract"]),
        "label_contract_hash": stable_hash(spec["label_contract"]),
        "threshold_registration_ref": str(paths["threshold"].relative_to(root)),
        "threshold_registration_sha256": sha256_file(paths["threshold"]),
        "threshold_rule_set_sha256": threshold["rule_set_sha256"],
        "planned_signal_dates_sha256": stable_hash(signal_dates),
        "planned_signal_period_count": len(signal_dates),
        "calendar_snapshot_id": calendar["snapshot_id"],
        "calendar_open_dates_sha256": calendar["open_dates_sha256"],
        "registered_before_step4": True,
        "oos_released": False,
        "component_obligation_preregistrations": component_preregistrations,
    }
    _write_json_atomic(paths["preregistration"], receipt)
    return validate_web_factor_proof_preregistration(
        root,
        plan,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )


def validate_web_factor_proof_preregistration(
    workspace_root: Path,
    plan: dict[str, Any],
    *,
    oos_release_token_hash: str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    report_id = str((plan.get("identity") or {}).get("report_id") or "")
    marker_reasons = [
        reason
        for reason in formal_oos_incident_reasons(
            workspace_root=root,
            report_id=report_id,
        )
        if reason.endswith(":marker_present")
    ]
    if marker_reasons:
        raise ValueError(";".join(marker_reasons))
    trust_root, incident_installation_id = _resolve_web_incident_host_context(
        incident_trust_root,
        incident_installation_id,
        block_token=BLOCK_PREREGISTRATION,
    )
    if _incident_guard is not None:
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=trust_root,
            installation_id=incident_installation_id,
        )
        return _validate_web_factor_proof_preregistration_guarded(
            workspace_root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=incident_installation_id,
    ) as guard:
        return _validate_web_factor_proof_preregistration_guarded(
            workspace_root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=guard,
        )


def _validate_web_factor_proof_preregistration_guarded(
    workspace_root: Path,
    plan: dict[str, Any],
    *,
    oos_release_token_hash: str | None,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    report_id = str(plan["identity"]["report_id"])
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=(
            Path(incident_trust_root)
            if incident_trust_root is not None
            else None
        ),
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    return validate_web_factor_proof_preregistration_structural(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
    )


def validate_web_factor_proof_preregistration_structural(
    workspace_root: Path,
    plan: dict[str, Any],
    *,
    oos_release_token_hash: str | None = None,
) -> dict[str, Any]:
    """Replay frozen preregistration bytes without granting current authority."""

    root = workspace_root.expanduser().resolve(strict=True)
    report_id = str(plan["identity"]["report_id"])
    paths = web_factor_proof_paths(root, report_id)
    for name in ("search_ledger", "spec", "threshold", "preregistration"):
        if not paths[name].is_file() or paths[name].is_symlink():
            raise ValueError(f"{BLOCK_PREREGISTRATION}: missing or unsafe {name}")
    receipt = _read_json(paths["preregistration"])
    spec = _read_json(paths["spec"])
    threshold = _read_json(paths["threshold"])
    expected_identity = {
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
    }
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    expected_spec, _expected_rules, expected_signal_dates = (
        build_web_metric_verifier_spec(
            plan,
            workspace_root=root,
            calendar=calendar,
            oos_release_token_hash=oos_release_token_hash,
        )
    )
    expected_component_preregistrations = []
    for component_spec, component_rules, component_paths in (
        _component_obligation_specs(
            root=root,
            plan=plan,
            metric_spec=expected_spec,
        )
    ):
        if (
            not component_paths["spec"].is_file()
            or component_paths["spec"].is_symlink()
            or not component_paths["threshold"].is_file()
            or component_paths["threshold"].is_symlink()
            or _read_json(component_paths["spec"]) != component_spec
        ):
            raise ValueError(
                f"{BLOCK_PREREGISTRATION}: component preregistration missing or mismatched"
            )
        component_threshold = _read_json(component_paths["threshold"])
        if (
            component_threshold.get("decision_rules") != component_rules
            or component_threshold.get("rule_set_sha256")
            != stable_hash(component_rules)
        ):
            raise ValueError(
                f"{BLOCK_PREREGISTRATION}: component threshold mismatch"
            )
        expected_component_preregistrations.append(
            {
                "obligation_id": component_spec["obligation_id"],
                "component_id": component_spec["obligation_id"].split(
                    "component_ablation__", 1
                )[1],
                "spec_ref": str(component_paths["spec"].relative_to(root)),
                "spec_sha256": sha256_file(component_paths["spec"]),
                "threshold_ref": str(
                    component_paths["threshold"].relative_to(root)
                ),
                "threshold_sha256": sha256_file(component_paths["threshold"]),
                "threshold_rule_set_sha256": component_threshold[
                    "rule_set_sha256"
                ],
            }
        )
    if (
        receipt.get("version") != PREREGISTRATION_VERSION
        or receipt.get("status") != "LOCKED"
        or any(receipt.get(key) != value for key, value in expected_identity.items())
        or receipt.get("web_research_plan_sha256") != stable_hash(plan)
        or receipt.get("registered_before_step4") is not True
        or receipt.get("evaluation_contract_hash") != evaluation_contract_hash(spec)
        or receipt.get("metric_verifier_spec_sha256") != sha256_file(paths["spec"])
        or receipt.get("window_hash") != stable_hash(spec.get("window_contract"))
        or receipt.get("label_contract_hash") != stable_hash(spec.get("label_contract"))
        or receipt.get("search_trial_ledger_sha256") != sha256_file(paths["search_ledger"])
        or receipt.get("threshold_registration_sha256") != sha256_file(paths["threshold"])
        or receipt.get("threshold_rule_set_sha256") != threshold.get("rule_set_sha256")
        or threshold.get("search_trial_ledger_sha256")
        != sha256_file(paths["search_ledger"])
        or threshold.get("registered_before_evaluation") is not True
        or threshold.get("window_hash") != stable_hash(spec.get("window_contract"))
        or threshold.get("evaluation_contract_hash") != evaluation_contract_hash(spec)
        or threshold.get("label_contract_hash") != stable_hash(spec.get("label_contract"))
        or spec != expected_spec
        or receipt.get("planned_signal_dates_sha256")
        != stable_hash(expected_signal_dates)
        or receipt.get("planned_signal_period_count") != len(expected_signal_dates)
        or receipt.get("calendar_snapshot_id") != calendar["snapshot_id"]
        or receipt.get("calendar_open_dates_sha256")
        != calendar["open_dates_sha256"]
        or receipt.get("component_obligation_preregistrations")
        != expected_component_preregistrations
    ):
        raise ValueError(f"{BLOCK_PREREGISTRATION}: preregistration binding mismatch")
    return {
        "version": PREREGISTRATION_VERSION,
        "status": "PASS",
        "report_id": report_id,
        "preregistration_sha256": sha256_file(paths["preregistration"]),
        "metric_verifier_spec_ref": str(paths["spec"].relative_to(root)),
        "threshold_registration_ref": str(paths["threshold"].relative_to(root)),
        "registered_before_step4": True,
    }


def _expected_label_dates(calendar_dates: list[str], signal_dates: list[str]) -> dict[str, tuple[str, str]]:
    index = {value: offset for offset, value in enumerate(calendar_dates)}
    mapping: dict[str, tuple[str, str]] = {}
    for signal_date in signal_dates:
        offset = index.get(signal_date)
        if offset is None or offset + 2 >= len(calendar_dates):
            raise ValueError(f"{BLOCK_FINALIZATION}: signal date outside trusted calendar")
        mapping[signal_date] = (calendar_dates[offset + 1], calendar_dates[offset + 2])
    return mapping


def _legacy_oos_workspace_temps(output: Path) -> list[Path]:
    """Find crash residue from the former workspace-local panel staging path."""

    parent = output.parent
    if not parent.is_dir():
        return []
    prefix = f".{output.name}."
    return sorted(
        (
            candidate
            for candidate in parent.iterdir()
            if candidate.name.startswith(prefix) and candidate.name.endswith(".tmp")
        ),
        key=lambda item: item.name,
    )


def _prepare_host_private_oos_staging(
    *,
    private_parent: Path,
    report_id: str,
    output: Path,
) -> Path:
    """Recover one deterministic private stage and block legacy hidden stages."""

    stage_key = hashlib.sha256(
        f"{report_id}\0{output.expanduser().resolve(strict=False)}".encode("utf-8")
    ).hexdigest()
    staging = private_parent / f".factorforge_derived_oos_{stage_key}.staging"
    legacy = sorted(
        candidate
        for candidate in private_parent.iterdir()
        if candidate.name.startswith(".factorforge_derived_oos_")
        and candidate != staging
    )
    if legacy:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: legacy Host-private OOS staging exists:"
            + ",".join(path.name for path in legacy)
        )
    if staging.exists() or staging.is_symlink():
        metadata = staging.lstat()
        if (
            staging.is_symlink()
            or not staging.is_dir()
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            raise ValueError(
                f"{BLOCK_FINALIZATION}: Host-private OOS staging unsafe"
            )
        shutil.rmtree(staging)
    staging.mkdir(mode=0o700)
    return staging


def _build_oos_panel(
    *,
    root: Path,
    report_id: str,
    spec: dict[str, Any],
    calendar: dict[str, Any],
    output: Path,
    plan: dict[str, Any] | None = None,
    sealed_oos_carrier_path: Path | None = None,
    sealed_oos_private_root: Path | None = None,
    sealed_oos_agent_visible_roots: list[Path] | None = None,
    expected_dataset_snapshot_sha256: str | None = None,
    expected_sealed_carrier_sha256: str | None = None,
) -> dict[str, Any]:
    legacy_temps = _legacy_oos_workspace_temps(output)
    if legacy_temps:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: legacy hidden OOS workspace temp exists:"
            + ",".join(path.name for path in legacy_temps)
        )
    if sealed_oos_carrier_path is not None:
        if (
            plan is None
            or not expected_sealed_carrier_sha256
            or sealed_oos_private_root is None
        ):
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier authority missing")
        private_root_raw = Path(sealed_oos_private_root).expanduser()
        carrier_raw = Path(sealed_oos_carrier_path).expanduser()
        if private_root_raw.is_symlink() or carrier_raw.is_symlink():
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier path symlink")
        private_root = private_root_raw.resolve(strict=True)
        carrier = carrier_raw.resolve(strict=True)
        if (
            not private_root.is_dir()
            or private_root.stat().st_uid != os.getuid()
            or private_root.stat().st_mode & 0o077
            or private_root == root
            or root in private_root.parents
            or private_root in root.parents
        ):
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier private root unsafe")
        for raw_visible_root in sealed_oos_agent_visible_roots or []:
            visible_root = Path(raw_visible_root).expanduser().resolve(strict=True)
            if (
                private_root == visible_root
                or visible_root in private_root.parents
                or private_root in visible_root.parents
            ):
                raise ValueError(
                    f"{BLOCK_FINALIZATION}: sealed carrier private root is Agent-visible"
                )
        if private_root not in carrier.parents:
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier outside private root")
        relative_parts = carrier.relative_to(private_root).parts
        current = private_root
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier path symlink")
        if carrier == root or root in carrier.parents:
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier exposed in workspace")
        if (
            carrier.is_symlink()
            or not carrier.is_file()
            or carrier.stat().st_uid != os.getuid()
            or carrier.stat().st_mode & 0o077
            or carrier.stat().st_nlink != 1
        ):
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier unsafe")
        if sha256_file(carrier) != expected_sealed_carrier_sha256:
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier snapshot mismatch")
        daily = (
            pd.read_parquet(carrier)
            if carrier.suffix.lower() == ".parquet"
            else pd.read_csv(carrier)
        )
        required_daily = set(plan["data_plan"]["daily_fields"]) | {
            "ts_code",
            "trade_date",
            "close",
            *set(spec["panel"].get("source_control_columns") or []),
        }
        missing = sorted(required_daily - set(daily.columns))
        if missing:
            raise ValueError(
                f"{BLOCK_FINALIZATION}: sealed carrier fields missing:{','.join(missing)}"
            )
        formula_ir = parse_formula(
            str(plan["research_object"]["formula_or_law"]),
            available_columns=[str(item) for item in daily.columns],
        )
        if formula_ir.get("parse_status") != "success":
            raise ValueError(f"{BLOCK_FINALIZATION}: sealed carrier formula invalid")
        signal = evaluate_formula_frame(formula_ir, daily, engine="optimized")
        signal = signal.rename(columns={"ts_code": "code"})
        signal["datetime"] = normalize_trade_date_series(signal["trade_date"])
        forward = build_forward_return_frame(
            daily.rename(columns={"ts_code": "code"}),
            instrument_col="code",
            date_col="trade_date",
            price_col="close",
            return_col=None,
            horizon=1,
            entry_offset=1,
            exit_offset=2,
            include_label_path=True,
            calendar_dates=calendar["dates"],
        )
        source_controls = list(spec["panel"].get("source_control_columns") or [])
        frame = signal[["datetime", "trade_date", "code", "factor_value"]].merge(
            forward[
                [
                    "datetime",
                    "code",
                    "future_return_1d",
                    "label_start_date",
                    "label_end_date",
                    "label_start_price",
                    "label_end_price",
                    *source_controls,
                ]
            ],
            on=["datetime", "code"],
            how="left",
        )
        signal_column = str(spec["panel"]["signal_column"])
        frame = frame.rename(columns={"factor_value": signal_column})
        diagnostic_columns = dict(
            spec["panel"].get("diagnostic_signal_columns") or {}
        )
        search_policy = (
            ((plan.get("measurement_program") or {}).get("search_policy") or {})
            if isinstance(plan.get("measurement_program"), dict)
            else {}
        )
        trials = {
            str(item.get("trial_id") or ""): item
            for item in search_policy.get("registered_diagnostic_trials") or []
            if isinstance(item, dict) and item.get("trial_id")
        }
        if set(trials) != set(diagnostic_columns):
            raise ValueError(
                f"{BLOCK_FINALIZATION}: sealed carrier diagnostic trial binding mismatch"
            )
        for trial_id, diagnostic_column in diagnostic_columns.items():
            trial_formula = str(trials[trial_id].get("formula_or_law") or "")
            trial_ir = parse_formula(
                trial_formula,
                available_columns=[str(item) for item in daily.columns],
            )
            if trial_ir.get("parse_status") != "success":
                raise ValueError(
                    f"{BLOCK_FINALIZATION}: sealed carrier diagnostic formula invalid:{trial_id}"
                )
            diagnostic = evaluate_formula_frame(
                trial_ir, daily, engine="optimized"
            ).rename(
                columns={"ts_code": "code", "factor_value": diagnostic_column}
            )
            diagnostic["datetime"] = normalize_trade_date_series(
                diagnostic["trade_date"]
            )
            frame = frame.merge(
                diagnostic[
                    ["datetime", "trade_date", "code", diagnostic_column]
                ],
                on=["datetime", "trade_date", "code"],
                how="left",
            )
        carrier_source = carrier
    else:
        carrier_source = None
    context_path = root / "runs" / report_id / f"shared_evaluation_context__{report_id}.json"
    panel_contract = spec["panel"]
    label = spec["label_contract"]
    columns = list(
        dict.fromkeys(
            [
                panel_contract["date_column"],
                panel_contract["asset_column"],
                panel_contract["signal_column"],
                panel_contract["forward_return_column"],
                label["label_start_date_column"],
                label["label_end_date_column"],
                label["label_start_price_column"],
                label["label_end_price_column"],
                *list(panel_contract.get("source_control_columns") or panel_contract.get("control_columns") or []),
                *list(
                    (panel_contract.get("diagnostic_signal_columns") or {}).values()
                ),
            ]
        )
    )
    if carrier_source is None:
        context = _read_json(_workspace_path(root, context_path, must_exist=True))
        merged_path = _workspace_path(
            root,
            str((context.get("paths") or {}).get("merged_signal_return_parquet") or ""),
            must_exist=True,
        )
        artifact = (context.get("artifacts") or {}).get("merged_signal_return") or {}
        expected_hash = str(artifact.get("sha256") or artifact.get("file_sha256") or "")
        if not expected_hash or sha256_file(merged_path) != expected_hash:
            raise ValueError(f"{BLOCK_FINALIZATION}: shared panel hash mismatch")
        frame = pd.read_parquet(merged_path, columns=columns)
    else:
        merged_path = carrier_source
    if "abs_pct_chg" in panel_contract.get("control_columns", []):
        frame["abs_pct_chg"] = pd.to_numeric(
            frame["pct_chg"], errors="coerce"
        ).abs()
    required_columns = list(
        dict.fromkeys(
            [
                *columns,
                *list(panel_contract.get("control_columns") or []),
            ]
        )
    )
    for column in (
        panel_contract["date_column"],
        label["label_start_date_column"],
        label["label_end_date_column"],
    ):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
    window = spec["window_contract"]
    signal_dates = [
        value
        for value in calendar["dates"]
        if window["observed_start_date"] <= value <= window["observed_end_date"]
    ]
    expected = _expected_label_dates(calendar["dates"], signal_dates)
    frame = frame[frame[panel_contract["date_column"]].isin(signal_dates)].copy()
    start_expected = frame[panel_contract["date_column"]].map(
        lambda value: expected.get(value, (None, None))[0]
    )
    end_expected = frame[panel_contract["date_column"]].map(
        lambda value: expected.get(value, (None, None))[1]
    )
    date_mismatch = (
        (frame[label["label_start_date_column"]] != start_expected)
        | (frame[label["label_end_date_column"]] != end_expected)
    )
    if bool(date_mismatch.any()):
        raise ValueError(
            f"{BLOCK_FINALIZATION}: OOS label dates do not match the trusted calendar"
        )
    missing_required = frame[required_columns].isna().any(axis=1)
    if bool(missing_required.any()):
        raise ValueError(
            f"{BLOCK_FINALIZATION}: OOS proof rows contain missing required values"
        )
    observed_dates = sorted(frame[panel_contract["date_column"]].unique().tolist())
    if observed_dates != signal_dates:
        raise ValueError(f"{BLOCK_FINALIZATION}: OOS signal-date coverage is incomplete")
    frame = frame.sort_values(
        [panel_contract["date_column"], panel_contract["asset_column"]]
    ).reset_index(drop=True)
    host_private_directory: Path | None = None
    host_private_panel: Path | None = None
    validated_panel_sha256: str | None = None
    if carrier_source is not None:
        host_private_directory = _prepare_host_private_oos_staging(
            private_parent=carrier_source.parent,
            report_id=report_id,
            output=output,
        )
        host_private_panel = host_private_directory / output.name
        frame.to_parquet(host_private_panel, index=False)
        host_private_panel.chmod(0o600)
        if host_private_panel.lstat().st_nlink != 1:
            shutil.rmtree(host_private_directory, ignore_errors=True)
            raise ValueError(
                f"{BLOCK_FINALIZATION}: Host-private derived projection hardlinked"
            )
        validated_panel_sha256 = sha256_file(host_private_panel)
        if not expected_dataset_snapshot_sha256:
            resolved_output = output.expanduser().resolve(strict=False)
            if private_root not in resolved_output.parents:
                shutil.rmtree(host_private_directory, ignore_errors=True)
                raise ValueError(
                    f"{BLOCK_FINALIZATION}: derived OOS panel authority missing"
                )
            if output.exists() or output.is_symlink():
                shutil.rmtree(host_private_directory, ignore_errors=True)
                raise ValueError(
                    f"{BLOCK_FINALIZATION}: Host-private derived projection exists"
                )
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(host_private_panel, output)
            output.chmod(0o600)
            shutil.rmtree(host_private_directory, ignore_errors=True)
            return {
                "source_panel_ref": "HOST_PRIVATE_SEALED_OOS_CARRIER",
                "source_panel_sha256": sha256_file(merged_path),
                "panel_ref": "HOST_PRIVATE_DERIVED_OOS_PROJECTION",
                "panel_sha256": validated_panel_sha256,
                "row_count": int(len(frame)),
                "period_count": len(signal_dates),
                "authority_status": "HOST_PRIVATE_PROJECTION_NOT_RELEASED",
            }
        if (
            validated_panel_sha256 != expected_dataset_snapshot_sha256
        ):
            shutil.rmtree(host_private_directory, ignore_errors=True)
            raise ValueError(
                f"{BLOCK_FINALIZATION}: derived OOS panel snapshot mismatch"
            )
    if output.exists() or output.is_symlink():
        if output.is_symlink() or not output.is_file():
            raise ValueError(f"{BLOCK_FINALIZATION}: OOS proof panel is unsafe")
        if output.lstat().st_nlink != 1:
            raise ValueError(f"{BLOCK_FINALIZATION}: OOS proof panel is hardlinked")
        existing = pd.read_parquet(output).reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(
                existing,
                frame,
                check_dtype=False,
                check_exact=True,
            )
        except AssertionError as exc:
            if host_private_directory is not None:
                shutil.rmtree(host_private_directory, ignore_errors=True)
            raise ValueError(
                f"{BLOCK_FINALIZATION}: OOS proof panel retry mismatch"
            ) from exc
        if (
            carrier_source is not None
            and expected_dataset_snapshot_sha256
            and sha256_file(output) != expected_dataset_snapshot_sha256
        ):
            if host_private_directory is not None:
                shutil.rmtree(host_private_directory, ignore_errors=True)
            raise ValueError(
                f"{BLOCK_FINALIZATION}: derived OOS panel snapshot mismatch"
            )
        if host_private_directory is not None:
            shutil.rmtree(host_private_directory, ignore_errors=True)
        return {
            "source_panel_ref": (
                str(merged_path.relative_to(root))
                if carrier_source is None
                else "HOST_PRIVATE_SEALED_OOS_CARRIER"
            ),
            "source_panel_sha256": sha256_file(merged_path),
            "panel_ref": str(output.relative_to(root)),
            "panel_sha256": sha256_file(output),
            "row_count": int(len(frame)),
            "period_count": len(signal_dates),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    if host_private_panel is not None:
        try:
            os.replace(host_private_panel, output)
        except OSError as exc:
            if host_private_directory is not None:
                shutil.rmtree(host_private_directory, ignore_errors=True)
            raise ValueError(
                f"{BLOCK_FINALIZATION}: Host-private OOS atomic publish failed"
            ) from exc
        output.chmod(0o600)
    else:
        temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        frame.to_parquet(temporary, index=False)
        temporary.replace(output)
    if host_private_directory is not None:
        shutil.rmtree(host_private_directory, ignore_errors=True)
    return {
        "source_panel_ref": (
            str(merged_path.relative_to(root))
            if carrier_source is None
            else "HOST_PRIVATE_SEALED_OOS_CARRIER"
        ),
        "source_panel_sha256": sha256_file(merged_path),
        "panel_ref": str(output.relative_to(root)),
        "panel_sha256": sha256_file(output),
        "row_count": int(len(frame)),
        "period_count": len(signal_dates),
    }


def project_host_private_sealed_oos_panel(
    *,
    workspace_root: Path,
    report_id: str,
    plan: dict[str, Any],
    metric_verifier_spec: dict[str, Any],
    calendar: dict[str, Any],
    sealed_oos_carrier_path: Path,
    sealed_oos_private_root: Path,
    expected_sealed_carrier_sha256: str,
    private_output_path: Path,
    sealed_oos_agent_visible_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Derive the allocation panel hash without publishing OOS to a workspace."""

    private_root = Path(sealed_oos_private_root).expanduser().resolve(strict=True)
    private_output = Path(private_output_path).expanduser().resolve(strict=False)
    if private_root not in private_output.parents:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: Host-private projection output outside private root"
        )
    return _build_oos_panel(
        root=Path(workspace_root).expanduser().resolve(strict=True),
        report_id=report_id,
        spec=metric_verifier_spec,
        calendar=calendar,
        output=private_output,
        plan=plan,
        sealed_oos_carrier_path=sealed_oos_carrier_path,
        sealed_oos_private_root=private_root,
        sealed_oos_agent_visible_roots=sealed_oos_agent_visible_roots,
        expected_sealed_carrier_sha256=expected_sealed_carrier_sha256,
    )


def _web_evo_conjecture(root: Path, report_id: str) -> dict[str, Any]:
    path = (
        root
        / "objects"
        / "research_protocol"
        / f"research_conjecture__{report_id}.json"
    )
    if not path.is_file() or path.is_symlink():
        return {}
    return _read_json(path)


def _web_evo_is_enabled(root: Path, report_id: str) -> bool:
    return epistemic_evolution_enabled(_web_evo_conjecture(root, report_id))


def _evo_oos_artifacts(root: Path, report_id: str) -> list[Path]:
    paths = web_factor_proof_paths(root, report_id)
    protocol = root / "objects" / "research_protocol"
    candidates = [
        paths["bound_spec"],
        paths["release"],
        paths["panel"],
        paths["certificate"],
        paths["verifier"],
        paths["finalization"],
        protocol / f"metric_verifier_bundle__{report_id}.json",
    ]
    candidates.extend(_legacy_oos_workspace_temps(paths["panel"]))
    preregistration = paths["preregistration"]
    if preregistration.is_file() and not preregistration.is_symlink():
        receipt = _read_json(preregistration)
        for item in receipt.get("component_obligation_preregistrations") or []:
            if not isinstance(item, dict):
                continue
            component_id = str(item.get("component_id") or "")
            if component_id:
                candidates.append(
                    _component_obligation_paths(root, report_id, component_id)[
                        "release"
                    ]
                )
    return list(dict.fromkeys(candidates))


def web_factor_proof_oos_recovery_state(
    workspace_root: Path,
    report_id: str,
) -> dict[str, Any]:
    """Detect an OOS publication that forbids returning to Agent phases.

    Existence is deliberately sufficient. A corrupt, symlinked, or only
    partially written artifact is still an information-release boundary and
    may only be handled by the trusted finalizer/terminal path.
    """

    root = Path(workspace_root).expanduser().resolve(strict=True)
    artifacts = [
        path
        for path in _evo_oos_artifacts(root, report_id)
        if path.exists() or path.is_symlink()
    ]
    paths = web_factor_proof_paths(root, report_id)
    return {
        "recovery_required": bool(artifacts),
        "allowed_execution": (
            "HOST_FINALIZER_OR_TERMINAL_ONLY" if artifacts else "NORMAL"
        ),
        "artifact_refs": [str(path.relative_to(root)) for path in artifacts],
        "finalization_receipt_present": (
            paths["finalization"].exists()
            or paths["finalization"].is_symlink()
        ),
    }


def _validated_web_evo_lifecycle(root: Path, report_id: str) -> dict[str, Any]:
    lifecycle_path = epistemic_evolution_lifecycle_path(root, report_id)
    if not lifecycle_path.is_file() or lifecycle_path.is_symlink():
        raise ValueError(f"{BLOCK_EVO_OOS_SEQUENCE}: lifecycle missing or unsafe")
    lifecycle = _read_json(lifecycle_path)
    reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if reasons:
        raise ValueError(f"{BLOCK_EVO_OOS_SEQUENCE}: {';'.join(reasons)}")
    generation = len(lifecycle.get("events") or [])
    from factor_factory.research_conjecture import (
        epistemic_evolution_lifecycle_snapshot_path,
    )

    snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
        root,
        report_id,
        generation,
    )
    if (
        not snapshot_path.is_file()
        or snapshot_path.is_symlink()
        or snapshot_path.read_bytes() != lifecycle_path.read_bytes()
    ):
        raise ValueError(
            f"{BLOCK_EVO_OOS_SEQUENCE}: immutable lifecycle snapshot mismatch"
        )
    return lifecycle


def _evo_is_window_contract(
    plan: dict[str, Any],
    *,
    calendar_dates: list[str],
) -> tuple[dict[str, Any], list[str]]:
    evidence = plan.get("evidence_policy")
    if not isinstance(evidence, dict):
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: evidence policy missing")
    try:
        is_start = pd.Timestamp(str(evidence["is_start"]), tz="UTC")
        is_end = pd.Timestamp(str(evidence["is_end"]), tz="UTC")
        oos_start = pd.Timestamp(str(evidence["oos_start"]), tz="UTC")
        purge_days = int(evidence["purge_days"])
        embargo_days = int(evidence["embargo_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"{BLOCK_EVO_IS_DIAGNOSTICS}: invalid evidence window"
        ) from exc
    if (
        purge_days < 0
        or embargo_days < 0
        or not (is_start <= is_end < oos_start)
    ):
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: invalid IS/OOS ordering")
    is_dates = [
        value
        for value in calendar_dates
        if is_start <= pd.Timestamp(value, tz="UTC") <= is_end
    ]
    # The final purge_days are absent from the diagnostic sample.  Two more
    # dates are reserved for the frozen t+1/t+2 label path, so no selected
    # signal can use a label outside the purged IS boundary.
    usable_count = len(is_dates) - purge_days - 2
    if usable_count < 3:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: purged IS is too short")
    signal_dates = is_dates[:usable_count]
    purged_dates = is_dates[len(is_dates) - purge_days :] if purge_days else []
    contract = {
        "window_role": "PURGED_IS_DIAGNOSTIC_ONLY",
        "is_start": str(evidence["is_start"]),
        "is_end": str(evidence["is_end"]),
        "oos_start": str(evidence["oos_start"]),
        "purge_days": purge_days,
        "embargo_days_reserved_for_future_oos_release": embargo_days,
        "label_horizon": "t+1 close to t+2 close",
        "expected_signal_start_date": signal_dates[0],
        "expected_signal_end_date": signal_dates[-1],
        "expected_signal_period_count": len(signal_dates),
        "purged_tail_dates_sha256": stable_hash(purged_dates),
        "uses_oos": False,
    }
    return contract, signal_dates


def _derive_web_evo_is_panel(
    *,
    root: Path,
    plan: dict[str, Any],
    calendar: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    report_id = str(plan["identity"]["report_id"])
    context_path = (
        root / "runs" / report_id / f"shared_evaluation_context__{report_id}.json"
    )
    context_path = _workspace_path(root, context_path, must_exist=True)
    context = _read_json(context_path)
    merged_path = _workspace_path(
        root,
        str((context.get("paths") or {}).get("merged_signal_return_parquet") or ""),
        must_exist=True,
    )
    artifact = (context.get("artifacts") or {}).get("merged_signal_return") or {}
    expected_source_hash = str(
        artifact.get("sha256") or artifact.get("file_sha256") or ""
    )
    if not expected_source_hash or sha256_file(merged_path) != expected_source_hash:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: shared panel hash mismatch")

    paths = web_factor_proof_paths(root, report_id)
    spec = _read_json(paths["spec"])
    panel_contract = spec["panel"]
    label = spec["label_contract"]
    columns = list(
        dict.fromkeys(
            [
                panel_contract["date_column"],
                panel_contract["asset_column"],
                panel_contract["signal_column"],
                panel_contract["forward_return_column"],
                label["label_start_date_column"],
                label["label_end_date_column"],
                label["label_start_price_column"],
                label["label_end_price_column"],
            ]
        )
    )
    window, expected_signal_dates = _evo_is_window_contract(
        plan,
        calendar_dates=list(calendar["dates"]),
    )
    date_type = pq.ParquetFile(merged_path).schema_arrow.field(
        panel_contract["date_column"]
    ).type
    lower_iso = expected_signal_dates[0]
    upper_iso = expected_signal_dates[-1]
    if pa.types.is_string(date_type) or pa.types.is_large_string(date_type):
        filters: Any = [
            [
                (panel_contract["date_column"], ">=", lower_iso),
                (panel_contract["date_column"], "<=", upper_iso),
            ],
            [
                (panel_contract["date_column"], ">=", lower_iso.replace("-", "")),
                (panel_contract["date_column"], "<=", upper_iso.replace("-", "")),
            ],
        ]
    elif pa.types.is_integer(date_type):
        filters = [
            (panel_contract["date_column"], ">=", int(lower_iso.replace("-", ""))),
            (panel_contract["date_column"], "<=", int(upper_iso.replace("-", ""))),
        ]
    elif pa.types.is_timestamp(date_type) or pa.types.is_date(date_type):
        filters = [
            (panel_contract["date_column"], ">=", pd.Timestamp(lower_iso)),
            (panel_contract["date_column"], "<=", pd.Timestamp(upper_iso)),
        ]
    else:
        raise ValueError(
            f"{BLOCK_EVO_IS_DIAGNOSTICS}: unsupported trade-date storage type"
        )
    # The Arrow predicate is part of the secrecy boundary: the checkpoint
    # process never receives rows outside the purged IS signal window.
    frame = pd.read_parquet(merged_path, columns=columns, filters=filters)
    for column in (
        panel_contract["date_column"],
        label["label_start_date_column"],
        label["label_end_date_column"],
    ):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
    expected_labels = _expected_label_dates(
        list(calendar["dates"]), expected_signal_dates
    )
    frame = frame[
        frame[panel_contract["date_column"]].isin(expected_signal_dates)
    ].copy()
    if frame.empty:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: no purged IS observations")
    if frame[columns].isna().any(axis=None):
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: missing IS values")
    if frame.duplicated(
        [panel_contract["date_column"], panel_contract["asset_column"]]
    ).any():
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: duplicate IS keys")
    start_expected = frame[panel_contract["date_column"]].map(
        lambda value: expected_labels.get(value, (None, None))[0]
    )
    end_expected = frame[panel_contract["date_column"]].map(
        lambda value: expected_labels.get(value, (None, None))[1]
    )
    if (
        (frame[label["label_start_date_column"]] != start_expected)
        | (frame[label["label_end_date_column"]] != end_expected)
    ).any():
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: IS label calendar mismatch")
    if (
        pd.to_datetime(frame[label["label_end_date_column"]], utc=True)
        >= pd.Timestamp(window["oos_start"], tz="UTC")
    ).any():
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: OOS label exposure")
    calculated_return = (
        pd.to_numeric(frame[label["label_end_price_column"]], errors="coerce")
        / pd.to_numeric(frame[label["label_start_price_column"]], errors="coerce")
        - 1.0
    )
    observed_return = pd.to_numeric(
        frame[panel_contract["forward_return_column"]], errors="coerce"
    )
    reconciliation_error = (calculated_return - observed_return).abs()
    if reconciliation_error.isna().any() or float(reconciliation_error.max()) > 1e-12:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: IS return mismatch")
    frame = frame.sort_values(
        [panel_contract["date_column"], panel_contract["asset_column"]]
    ).reset_index(drop=True)
    observed_dates = sorted(
        frame[panel_contract["date_column"]].astype(str).unique().tolist()
    )
    if any(value not in expected_signal_dates for value in observed_dates):
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: non-IS date present")
    source = {
        "context_ref": str(context_path.relative_to(root)),
        "context_sha256": sha256_file(context_path),
        "source_panel_ref": str(merged_path.relative_to(root)),
        "source_panel_sha256": expected_source_hash,
    }
    coverage = {
        "observed_signal_dates": observed_dates,
        "observed_signal_period_count": len(observed_dates),
        "expected_signal_period_count": len(expected_signal_dates),
        "coverage_ratio": len(observed_dates) / len(expected_signal_dates),
        "coverage_status": (
            "COMPLETE"
            if observed_dates == expected_signal_dates
            else "INCOMPLETE_REQUIRES_HOST_REVIEW"
        ),
        "return_reconciliation_max_abs_error": float(
            reconciliation_error.max()
        ),
    }
    return frame, {**window, **coverage}, source


def _web_evo_is_observed_signature(
    frame: pd.DataFrame,
    *,
    spec: dict[str, Any],
) -> dict[str, Any]:
    date_column = spec["panel"]["date_column"]
    asset_column = spec["panel"]["asset_column"]
    signal_column = spec["panel"]["signal_column"]
    return_column = spec["panel"]["forward_return_column"]
    rank_ics: list[float] = []
    gross_returns: list[float] = []
    net_returns: list[float] = []
    turnovers: list[float] = []
    previous_weights: dict[str, float] = {}
    cost_rate = float(spec["portfolio"]["cost_bps_per_turnover"]) / 10_000.0
    for _date, group in frame.groupby(date_column, sort=True):
        ranked_signal = pd.to_numeric(group[signal_column], errors="coerce").rank()
        ranked_return = pd.to_numeric(group[return_column], errors="coerce").rank()
        rank_ic = ranked_signal.corr(ranked_return)
        if pd.notna(rank_ic):
            rank_ics.append(float(rank_ic))
        ordered = group.sort_values(
            [signal_column, asset_column], ascending=[False, True]
        )
        long_count = max(
            1,
            int(math.ceil(len(ordered) * float(spec["portfolio"]["long_quantile"]))),
        )
        selected = ordered.head(long_count)
        weights = {
            str(asset): 1.0 / long_count
            for asset in selected[asset_column].astype(str).tolist()
        }
        names = set(previous_weights) | set(weights)
        turnover = (
            sum(abs(weights.get(name, 0.0) - previous_weights.get(name, 0.0)) for name in names)
            / 2.0
            if previous_weights
            else 1.0
        )
        gross_return = float(
            pd.to_numeric(selected[return_column], errors="coerce").mean()
        )
        net_return = gross_return - turnover * cost_rate
        turnovers.append(float(turnover))
        gross_returns.append(gross_return)
        net_returns.append(net_return)
        previous_weights = weights

    def _mean(values: list[float]) -> float | None:
        return float(pd.Series(values, dtype="float64").mean()) if values else None

    def _std(values: list[float]) -> float | None:
        if len(values) < 2:
            return None
        value = float(pd.Series(values, dtype="float64").std(ddof=1))
        return value if math.isfinite(value) else None

    ic_mean = _mean(rank_ics)
    ic_std = _std(rank_ics)
    net_mean = _mean(net_returns)
    net_std = _std(net_returns)
    wealth = pd.Series(net_returns, dtype="float64").add(1.0).cumprod()
    drawdown = wealth.div(wealth.cummax()).sub(1.0) if not wealth.empty else wealth
    annual_return = None
    if not wealth.empty and bool((pd.Series(net_returns) > -1.0).all()):
        annual_return = float(wealth.iloc[-1] ** (252.0 / len(wealth)) - 1.0)
    return {
        "diagnostic_only": True,
        "rank_ic": {
            "mean": ic_mean,
            "standard_deviation": ic_std,
            "icir_annualized": (
                ic_mean / ic_std * math.sqrt(252.0)
                if ic_mean is not None and ic_std not in {None, 0.0}
                else None
            ),
            "period_count": len(rank_ics),
        },
        "high_score_long": {
            "gross_mean_daily_return": _mean(gross_returns),
            "net_mean_daily_return": net_mean,
            "net_annualized_geometric_return": annual_return,
            "net_sharpe_annualized": (
                net_mean / net_std * math.sqrt(252.0)
                if net_mean is not None and net_std not in {None, 0.0}
                else None
            ),
            "maximum_drawdown": (
                float(drawdown.min()) if not drawdown.empty else None
            ),
            "mean_turnover": _mean(turnovers),
            "period_count": len(net_returns),
        },
    }


def _web_evo_prediction_registry(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "hypothesis_id": item.get("hypothesis_id"),
            "kind": item.get("kind"),
            "expected_signature": item.get("expected_signature"),
            "falsification_tests": item.get("falsification_tests"),
            "kill_criteria": item.get("kill_criteria"),
        }
        for item in plan.get("hypotheses") or []
        if isinstance(item, dict)
    ]


def materialize_web_evo_is_checkpoint(
    *,
    workspace_root: Path,
    plan: dict[str, Any],
    oos_release_token_hash: str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    report_id = str(plan["identity"]["report_id"])
    if incident_trust_root is None or not incident_installation_id:
        raise ValueError(
            f"{BLOCK_EVO_IS_DIAGNOSTICS}: incident Host context required"
        )
    trust_root, resolved_installation = _resolve_web_incident_host_context(
        incident_trust_root,
        incident_installation_id,
        block_token=BLOCK_EVO_IS_DIAGNOSTICS,
    )
    if _incident_guard is None:
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id=resolved_installation,
        ) as guard:
            return materialize_web_evo_is_checkpoint(
                workspace_root=root,
                plan=plan,
                oos_release_token_hash=oos_release_token_hash,
                incident_trust_root=trust_root,
                incident_installation_id=resolved_installation,
                _incident_guard=guard,
            )
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=trust_root,
        installation_id=resolved_installation,
    )
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=trust_root,
        installation_id=resolved_installation,
    )
    if incident_reasons:
        raise ValueError(";".join(incident_reasons))
    if not _web_evo_is_enabled(root, report_id):
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: EVO V2 is not enabled")
    lifecycle = _validated_web_evo_lifecycle(root, report_id)
    if lifecycle.get("current_state") != "PREDICTIONS_FROZEN":
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: predictions are not frozen")
    released = [path for path in _evo_oos_artifacts(root, report_id) if path.exists()]
    if released:
        raise ValueError(f"{BLOCK_EVO_OOS_SEQUENCE}: OOS already materialized")
    prereg = validate_web_factor_proof_preregistration(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
        incident_trust_root=trust_root,
        incident_installation_id=resolved_installation,
        _incident_guard=_incident_guard,
    )
    paths = web_factor_proof_paths(root, report_id)
    if paths["evo_is_diagnostics"].is_file():
        validated = validate_web_evo_is_checkpoint(
            root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
        )
        return {**validated, "current_formal_authority_verified": True}
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    frame, window, source = _derive_web_evo_is_panel(
        root=root,
        plan=plan,
        calendar=calendar,
    )
    paths["evo_is_panel"].parent.mkdir(parents=True, exist_ok=True)
    temporary = paths["evo_is_panel"].with_name(
        f".{paths['evo_is_panel'].name}.{os.getpid()}.tmp"
    )
    frame.to_parquet(temporary, index=False)
    if paths["evo_is_panel"].exists() or paths["evo_is_panel"].is_symlink():
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: immutable panel exists")
    temporary.replace(paths["evo_is_panel"])
    panel_sha256 = sha256_file(paths["evo_is_panel"])
    spec = _read_json(paths["spec"])
    report = {
        "contract_version": EVO_IS_DIAGNOSTICS_VERSION,
        "verifier_status": "PASS",
        "verifier_id": EVO_IS_DIAGNOSTICS_VERIFIER_ID,
        "verifier_source_sha256": sha256_file(Path(__file__)),
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
        "web_research_plan_sha256": stable_hash(plan),
        "preregistration_ref": str(paths["preregistration"].relative_to(root)),
        "preregistration_sha256": prereg["preregistration_sha256"],
        "source": source,
        "dataset_snapshot_hash": panel_sha256,
        "window_hash": stable_hash(window),
        "window_contract": window,
        "panel_ref": str(paths["evo_is_panel"].relative_to(root)),
        "panel_sha256": panel_sha256,
        "row_count": int(len(frame)),
        "prediction_registry": _web_evo_prediction_registry(plan),
        "observed_signature": _web_evo_is_observed_signature(frame, spec=spec),
        "lower_layer_checkpoint": {
            "data_integrity": "PASS",
            "label_information_set": "PASS",
            "implementation_parity": "NOT_REVIEWED_BY_THIS_CHECKPOINT",
            "measurement_validity": "NOT_REVIEWED_BY_THIS_CHECKPOINT",
            "alias_and_controls": "NOT_REVIEWED_BY_THIS_CHECKPOINT",
        },
        "qualification": {
            "status": "HOST_REVIEW_REQUIRED",
            "qualified_contradiction": None,
            "automatic_qualification_allowed": False,
            "required_next_artifact": "objects/evo_v2/<report_id>/feedback_ledger.json",
        },
        "uses_oos": False,
        "oos_release_observed_at_materialization": False,
        "factor_verdict": "NOT_ISSUED",
        "canonical_write_permission": False,
    }
    _write_json_immutable(paths["evo_is_diagnostics"], report)
    validated = validate_web_evo_is_checkpoint(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
    )
    return {**validated, "current_formal_authority_verified": True}


def validate_web_evo_is_checkpoint(
    workspace_root: Path,
    plan: dict[str, Any],
    *,
    oos_release_token_hash: str | None = None,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    report_id = str(plan["identity"]["report_id"])
    paths = web_factor_proof_paths(root, report_id)
    for key in ("evo_is_panel", "evo_is_diagnostics"):
        if not paths[key].is_file() or paths[key].is_symlink():
            raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: missing or unsafe {key}")
    prereg = validate_web_factor_proof_preregistration_structural(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
    )
    report = _read_json(paths["evo_is_diagnostics"])
    expected_fields = {
        "contract_version",
        "verifier_status",
        "verifier_id",
        "verifier_source_sha256",
        "report_id",
        "factor_id",
        "research_id",
        "web_research_plan_sha256",
        "preregistration_ref",
        "preregistration_sha256",
        "source",
        "dataset_snapshot_hash",
        "window_hash",
        "window_contract",
        "panel_ref",
        "panel_sha256",
        "row_count",
        "prediction_registry",
        "observed_signature",
        "lower_layer_checkpoint",
        "qualification",
        "uses_oos",
        "oos_release_observed_at_materialization",
        "factor_verdict",
        "canonical_write_permission",
    }
    if set(report) != expected_fields:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: report shape invalid")
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    expected_frame, expected_window, expected_source = _derive_web_evo_is_panel(
        root=root,
        plan=plan,
        calendar=calendar,
    )
    actual_frame = pd.read_parquet(paths["evo_is_panel"]).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(
            actual_frame,
            expected_frame,
            check_dtype=False,
            check_exact=True,
        )
    except AssertionError as exc:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: IS panel replay mismatch") from exc
    panel_sha256 = sha256_file(paths["evo_is_panel"])
    spec = _read_json(paths["spec"])
    expected = {
        "contract_version": EVO_IS_DIAGNOSTICS_VERSION,
        "verifier_status": "PASS",
        "verifier_id": EVO_IS_DIAGNOSTICS_VERIFIER_ID,
        "verifier_source_sha256": sha256_file(Path(__file__)),
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
        "web_research_plan_sha256": stable_hash(plan),
        "preregistration_ref": str(paths["preregistration"].relative_to(root)),
        "preregistration_sha256": prereg["preregistration_sha256"],
        "source": expected_source,
        "dataset_snapshot_hash": panel_sha256,
        "window_hash": stable_hash(expected_window),
        "window_contract": expected_window,
        "panel_ref": str(paths["evo_is_panel"].relative_to(root)),
        "panel_sha256": panel_sha256,
        "row_count": int(len(expected_frame)),
        "prediction_registry": _web_evo_prediction_registry(plan),
        "observed_signature": _web_evo_is_observed_signature(
            expected_frame, spec=spec
        ),
        "lower_layer_checkpoint": {
            "data_integrity": "PASS",
            "label_information_set": "PASS",
            "implementation_parity": "NOT_REVIEWED_BY_THIS_CHECKPOINT",
            "measurement_validity": "NOT_REVIEWED_BY_THIS_CHECKPOINT",
            "alias_and_controls": "NOT_REVIEWED_BY_THIS_CHECKPOINT",
        },
        "qualification": {
            "status": "HOST_REVIEW_REQUIRED",
            "qualified_contradiction": None,
            "automatic_qualification_allowed": False,
            "required_next_artifact": "objects/evo_v2/<report_id>/feedback_ledger.json",
        },
        "uses_oos": False,
        "oos_release_observed_at_materialization": False,
        "factor_verdict": "NOT_ISSUED",
        "canonical_write_permission": False,
    }
    if report != expected:
        raise ValueError(f"{BLOCK_EVO_IS_DIAGNOSTICS}: report replay mismatch")
    return {
        "contract_version": EVO_IS_DIAGNOSTICS_VERSION,
        "status": "PASS",
        "report_id": report_id,
        "checkpoint_ref": str(paths["evo_is_diagnostics"].relative_to(root)),
        "checkpoint_sha256": sha256_file(paths["evo_is_diagnostics"]),
        "dataset_snapshot_hash": panel_sha256,
        "window_hash": report["window_hash"],
        "uses_oos": False,
        "qualification_status": "HOST_REVIEW_REQUIRED",
    }


def resolve_web_evo_execution_gate(
    *,
    workspace_root: Path,
    report_id: str,
    plan: dict[str, Any],
    oos_release_token_hash: str | None = None,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    if not _web_evo_is_enabled(root, report_id):
        return {
            "enabled": False,
            "current_state": None,
            "action": "LEGACY_WEB_EXECUTION",
        }
    lifecycle = _validated_web_evo_lifecycle(root, report_id)
    state = str(lifecycle["current_state"])
    paths = web_factor_proof_paths(root, report_id)
    checkpoint_exists = paths["evo_is_diagnostics"].is_file()
    checkpoint = (
        validate_web_evo_is_checkpoint(
            root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
        )
        if checkpoint_exists
        else None
    )
    if state != "PREDICTIONS_FROZEN" and checkpoint is None:
        raise ValueError(f"{BLOCK_EVO_OOS_SEQUENCE}: IS checkpoint missing")
    released = [
        str(path.relative_to(root))
        for path in _evo_oos_artifacts(root, report_id)
        if path.exists() or path.is_symlink()
    ]
    if state != "NO_QUALIFIED_CONTRADICTION" and released:
        raise ValueError(
            f"{BLOCK_EVO_OOS_SEQUENCE}: OOS materialized in state {state}"
        )
    actions = {
        "PREDICTIONS_FROZEN": (
            "AWAIT_HOST_QUALIFICATION"
            if checkpoint_exists
            else "MATERIALIZE_PURGED_IS_AND_PAUSE"
        ),
        "NO_QUALIFIED_CONTRADICTION": "RELEASE_ORIGINAL_CANDIDATE_OOS",
        "QUALIFIED_CONTRADICTION": "RUN_PRE_OOS_REVISION_COUNCIL",
        "MINIMAL_MECHANISM_DELTA": "AWAIT_EVO_V2_TRANSFER_AND_USE",
        "NO_DERIVED_LAW": "TERMINAL_KILL_AND_LEARN",
        "TRANSFER_RECORDED": "AWAIT_EXTERNAL_APPROVAL_AND_CHILD",
        "COLD_START_RECORDED": "AWAIT_EXTERNAL_APPROVAL_AND_CHILD",
    }
    return {
        "enabled": True,
        "current_state": state,
        "action": actions[state],
        "checkpoint": checkpoint,
        "oos_artifacts": released,
        "oos_release_allowed": state == "NO_QUALIFIED_CONTRADICTION",
        "step5_step6_allowed": state == "NO_QUALIFIED_CONTRADICTION",
        "council_allowed": state == "QUALIFIED_CONTRADICTION",
        "automatic_qualification_allowed": False,
    }


def _certificate_from_bundle(
    *,
    root: Path,
    spec: dict[str, Any],
    bundle: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    window = spec["window_contract"]
    label = spec["label_contract"]
    portfolio = spec["portfolio"]
    identities = {
        key: bundle[key]
        for key in (
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
            "calendar_period_count",
            "label_observed_start_date",
            "label_observed_end_date",
            "signal_period_count",
            "independent_path_period_count",
            "signal_coverage_ratio",
            "return_reconciliation_max_abs_error",
            "verification_scope",
        )
    }
    certificate: dict[str, Any] = {
        "certificate_version": CERTIFICATE_VERSION,
        "report_id": spec["report_id"],
        "factor_id": spec["factor_id"],
        "research_id": spec.get("research_id"),
        "claim_class": spec["claim_class"],
        "formal_proof_eligible": True,
        "data_contract": {
            "is_window": spec["research_windows"]["is_window"],
            "universe": f"Web research universe: {window['universe_id']}",
            "universe_id": window["universe_id"],
            "investability_mask_id": window["investability_mask_id"],
            "sample_frequency": window["sample_frequency"],
            "forward_return_horizon": window["forward_return_horizon"],
            "forward_return_horizon_days": window["forward_return_horizon_days"],
            "return_path_mode": portfolio["return_path_mode"],
            "holding_period_days": portfolio["holding_period_days"],
            "rebalance_frequency": portfolio["rebalance_frequency"],
            "signal_timestamp": window["signal_timestamp"],
            "execution_timestamp": window["execution_timestamp"],
            "label_start_timestamp": window["label_start_timestamp"],
            "label_end_timestamp": window["label_end_timestamp"],
            "forward_return_formula": window["forward_return_formula"],
            "path_is_disjoint": window["path_is_disjoint"],
            "label_contract_version": label["version"],
            "signal_date_column": label["signal_date_column"],
            "label_start_date_column": label["label_start_date_column"],
            "label_end_date_column": label["label_end_date_column"],
            "label_start_price_column": label["label_start_price_column"],
            "label_end_price_column": label["label_end_price_column"],
            "forward_return_column": label["forward_return_column"],
            "return_tolerance": label["return_tolerance"],
            "trading_calendar_ref": label["trading_calendar_ref"],
            "trading_calendar_id": label["trading_calendar_id"],
            "cost_policy_id": spec["cost_policy_id"],
            "label_definition": "verified t+1 close to t+2 close simple return",
            "return_convention": window["return_convention"],
            **identities,
            "oos_status": "released_once_for_final_evaluation",
            "evaluation_window_role": window["evaluation_window_role"],
            "oos_window": window["oos_window"],
            "observed_start_date": bundle["verifier_spec"]["window_contract"]["observed_start_date"],
            "observed_end_date": bundle["verifier_spec"]["window_contract"]["observed_end_date"],
            "minimum_periods": window["minimum_periods"],
            "search_frozen_before_oos_release": True,
            "oos_evidence_included": True,
            "oos_release_token_hash": window["oos_release_token_hash"],
            "search_trial_ledger_ref": window["search_trial_ledger_ref"],
            "oos_release_manifest_ref": window["oos_release_manifest_ref"],
            "same_sample_for_all_required_metrics": True,
            "control_columns": list(
                spec["panel"].get("control_columns") or []
            ),
        },
        "metrics": bundle["metrics"],
        "evidence_bindings": bundle["evidence_bindings"],
        "threshold_registration": {
            "registered_before_evaluation": True,
            "registration_ref": spec["threshold_registration_ref"],
            "registration_sha256": sha256_file(
                root / spec["threshold_registration_ref"]
            ),
            "rule_set_sha256": threshold["rule_set_sha256"],
        },
        "decision_rules": threshold["decision_rules"],
    }
    derived = derive_factor_proof_verdict(certificate, workspace_root=root)
    if derived["verdict"] == "BLOCK":
        raise ValueError(
            f"{BLOCK_FINALIZATION}: {'; '.join(derived['block_reasons'])}"
        )
    certificate["declared_verdict"] = derived["verdict"]
    return certificate


def _finalize_component_obligations(
    *,
    root: Path,
    plan: dict[str, Any],
    metric_spec: dict[str, Any],
    panel_path: Path,
    incident_trust_root: Path,
    incident_installation_id: str,
    incident_guard: object,
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for component_spec, _rules, component_paths in _component_obligation_specs(
        root=root,
        plan=plan,
        metric_spec=metric_spec,
    ):
        identities = component_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=component_spec,
        )
        bound_spec = {**component_spec, **identities}
        write_oos_release_manifest(
            component_paths["release"],
            workspace_root=root,
            spec=bound_spec,
            identities=identities,
            threshold_path=component_paths["threshold"],
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=incident_guard,
        )
        bundle = run_component_obligation_verifier(
            workspace_root=root,
            panel_path=panel_path,
            spec=bound_spec,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=incident_guard,
        )
        report = bundle.get("report")
        replay_reasons = validate_component_obligation_report(
            report,
            workspace_root=root,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=incident_guard,
        )
        if bundle.get("verifier_status") != "PASS" or replay_reasons:
            component_id = component_spec["obligation_id"].split(
                "component_ablation__", 1
            )[1]
            raise ValueError(
                f"{BLOCK_FINALIZATION}: component obligation failed:"
                f"{component_id}:{','.join(replay_reasons)}"
            )
        reference = bundle["evidence_reference"]
        bindings.append(
            {
                "obligation_id": component_spec["obligation_id"],
                "component_id": component_spec["obligation_id"].split(
                    "component_ablation__", 1
                )[1],
                "report_ref": reference["path"],
                "report_sha256": reference["sha256"],
                "verifier_source_sha256": reference[
                    "verifier_source_sha256"
                ],
                "release_manifest_ref": str(
                    component_paths["release"].relative_to(root)
                ),
                "release_manifest_sha256": sha256_file(
                    component_paths["release"]
                ),
            }
        )
    return bindings


def validate_web_factor_proof_finalization(
    workspace_root: Path,
    plan: dict[str, Any],
    *,
    oos_release_token_hash: str | None = None,
    host_agent_termination_authority: dict[str, Any] | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    trust_root, incident_installation_id = _resolve_web_incident_host_context(
        incident_trust_root,
        incident_installation_id,
        block_token=BLOCK_FINALIZATION,
    )
    if _incident_guard is not None:
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=trust_root,
            installation_id=incident_installation_id,
        )
        return _validate_web_factor_proof_finalization_guarded(
            workspace_root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
            host_agent_termination_authority=host_agent_termination_authority,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=incident_installation_id,
    ) as guard:
        return _validate_web_factor_proof_finalization_guarded(
            workspace_root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
            host_agent_termination_authority=host_agent_termination_authority,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=guard,
        )


def _validate_web_factor_proof_finalization_guarded(
    workspace_root: Path,
    plan: dict[str, Any],
    *,
    oos_release_token_hash: str | None,
    host_agent_termination_authority: dict[str, Any] | None,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    report_id = str(plan["identity"]["report_id"])
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(f"{BLOCK_FINALIZATION}: " + ";".join(incident_reasons))
    preregistration = validate_web_factor_proof_preregistration(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    allocation_path = oos_allocation_path(root, report_id)
    secure_child_oos = False
    if allocation_path.exists() or allocation_path.is_symlink():
        if not allocation_path.is_file() or allocation_path.is_symlink():
            raise ValueError(f"{BLOCK_FINALIZATION}: OOS allocation unsafe")
        allocation = _read_json(allocation_path)
        secure_child_oos = (
            allocation.get("allocation_authority_mode")
            == OOS_ALLOCATION_AUTHORITY_SECURE
        )
    if secure_child_oos:
        termination_authority = _validate_host_agent_termination_authority(
            host_agent_termination_authority,
            report_id=report_id,
        )
    elif host_agent_termination_authority is not None:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: unexpected Host Agent termination authority"
        )
    else:
        termination_authority = None
    if _web_evo_is_enabled(root, report_id):
        gate = resolve_web_evo_execution_gate(
            workspace_root=root,
            report_id=report_id,
            plan=plan,
            oos_release_token_hash=oos_release_token_hash,
        )
        if gate["action"] != "RELEASE_ORIGINAL_CANDIDATE_OOS":
            raise ValueError(
                f"{BLOCK_EVO_OOS_SEQUENCE}: OOS release forbidden in "
                f"{gate['current_state']}"
            )
    paths = web_factor_proof_paths(root, report_id)
    if not paths["finalization"].is_file() or paths["finalization"].is_symlink():
        raise ValueError(f"{BLOCK_FINALIZATION}: finalization receipt missing")
    result = _read_json(paths["finalization"])
    expected_identity = {
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
    }
    if (
        result.get("version") != FINALIZATION_VERSION
        or result.get("status") != "PASS"
        or any(result.get(key) != value for key, value in expected_identity.items())
        or result.get("preregistration_sha256")
        != preregistration["preregistration_sha256"]
        or result.get("formal_proof_eligible") is not True
        or result.get("host_agent_termination_authority")
        != termination_authority
    ):
        raise ValueError(f"{BLOCK_FINALIZATION}: finalization receipt invalid")
    expected_outputs = {
        "metric_verifier_spec_sha256": paths["spec"],
        "bound_metric_verifier_spec_sha256": paths["bound_spec"],
        "oos_release_manifest_sha256": paths["release"],
        "metric_verifier_bundle_sha256": (
            root
            / "objects"
            / "research_protocol"
            / f"metric_verifier_bundle__{report_id}.json"
        ),
        "factor_proof_certificate_sha256": paths["certificate"],
        "factor_proof_verifier_sha256": paths["verifier"],
    }
    for hash_field, path in expected_outputs.items():
        if (
            not path.is_file()
            or path.is_symlink()
            or result.get(hash_field) != sha256_file(path)
        ):
            raise ValueError(
                f"{BLOCK_FINALIZATION}: final output binding mismatch:{hash_field}"
            )
    consumption_reasons = validate_oos_release_consumption(
        workspace_root=root,
        report_id=report_id,
        release_manifest_path=paths["release"],
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    if consumption_reasons:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: " + ";".join(consumption_reasons)
        )
    panel = result.get("panel") if isinstance(result.get("panel"), dict) else {}
    if (
        panel.get("panel_ref") != str(paths["panel"].relative_to(root))
        or not paths["panel"].is_file()
        or paths["panel"].is_symlink()
        or panel.get("panel_sha256") != sha256_file(paths["panel"])
    ):
        raise ValueError(f"{BLOCK_FINALIZATION}: proof panel binding mismatch")
    release_payload = _read_json(paths["release"])
    if (
        release_payload.get("host_agent_termination_authority")
        != termination_authority
    ):
        raise ValueError(
            f"{BLOCK_FINALIZATION}: Host Agent termination release binding mismatch"
        )
    preregistered_spec = _read_json(paths["spec"])
    bound_spec = _read_json(paths["bound_spec"])
    current_identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=paths["panel"],
        spec=preregistered_spec,
    )
    if bound_spec != {**preregistered_spec, **current_identities}:
        raise ValueError(f"{BLOCK_FINALIZATION}: bound verifier spec mismatch")
    certificate = _read_json(paths["certificate"])
    report = validate_factor_proof_certificate(
        certificate,
        workspace_root=root,
        expected_report_id=report_id,
        expected_factor_id=str(plan["identity"]["factor_id"]),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    verifier = _read_json(paths["verifier"])
    component_bindings = result.get("component_obligation_bindings")
    if not isinstance(component_bindings, list):
        raise ValueError(f"{BLOCK_FINALIZATION}: component bindings missing")
    expected_component_specs = _component_obligation_specs(
        root=root,
        plan=plan,
        metric_spec=preregistered_spec,
    )
    if len(component_bindings) != len(expected_component_specs):
        raise ValueError(f"{BLOCK_FINALIZATION}: component binding count mismatch")
    for binding in component_bindings:
        report_path = _workspace_path(
            root,
            str(binding.get("report_ref") or ""),
            must_exist=True,
        )
        component_report = _read_json(report_path)
        if (
            binding.get("report_sha256") != sha256_file(report_path)
            or validate_component_obligation_report(
                component_report,
                workspace_root=root,
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
        ):
            raise ValueError(
                f"{BLOCK_FINALIZATION}: component report replay failed"
            )
    if (
        report.get("verdict") == "BLOCK"
        or report.get("block_reasons")
        or report.get("current_formal_authority_verified") is not True
        or result.get("factor_verdict") != report.get("verdict")
        or verifier.get("verifier_contract_version") != BOUND_VERIFIER_VERSION
        or verifier.get("verdict") != report.get("verdict")
        or verifier.get("block_reasons")
        or verifier.get("formal_proof_eligible") is not True
        or verifier.get("component_obligation_bindings") != component_bindings
        or certificate.get("component_obligation_bindings") != component_bindings
    ):
        raise ValueError(f"{BLOCK_FINALIZATION}: bound factor proof invalid")
    return result


def finalize_web_factor_proof(
    *,
    workspace_root: Path,
    plan: dict[str, Any],
    oos_release_token_hash: str | None = None,
    sealed_oos_carrier_path: Path | None = None,
    sealed_oos_private_root: Path | None = None,
    sealed_oos_agent_visible_roots: list[Path] | None = None,
    expected_dataset_snapshot_sha256: str | None = None,
    expected_sealed_carrier_sha256: str | None = None,
    host_agent_termination_authority: dict[str, Any] | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    trust_root, incident_installation_id = _resolve_web_incident_host_context(
        incident_trust_root,
        incident_installation_id,
        block_token=BLOCK_FINALIZATION,
    )
    if _incident_guard is not None:
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=trust_root,
            installation_id=incident_installation_id,
        )
        return _finalize_web_factor_proof_guarded(
            workspace_root=workspace_root,
            plan=plan,
            oos_release_token_hash=oos_release_token_hash,
            sealed_oos_carrier_path=sealed_oos_carrier_path,
            sealed_oos_private_root=sealed_oos_private_root,
            sealed_oos_agent_visible_roots=sealed_oos_agent_visible_roots,
            expected_dataset_snapshot_sha256=expected_dataset_snapshot_sha256,
            expected_sealed_carrier_sha256=expected_sealed_carrier_sha256,
            host_agent_termination_authority=host_agent_termination_authority,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=incident_installation_id,
    ) as guard:
        return _finalize_web_factor_proof_guarded(
            workspace_root=workspace_root,
            plan=plan,
            oos_release_token_hash=oos_release_token_hash,
            sealed_oos_carrier_path=sealed_oos_carrier_path,
            sealed_oos_private_root=sealed_oos_private_root,
            sealed_oos_agent_visible_roots=sealed_oos_agent_visible_roots,
            expected_dataset_snapshot_sha256=expected_dataset_snapshot_sha256,
            expected_sealed_carrier_sha256=expected_sealed_carrier_sha256,
            host_agent_termination_authority=host_agent_termination_authority,
            incident_trust_root=trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=guard,
        )


def _finalize_web_factor_proof_guarded(
    *,
    workspace_root: Path,
    plan: dict[str, Any],
    oos_release_token_hash: str | None,
    sealed_oos_carrier_path: Path | None,
    sealed_oos_private_root: Path | None,
    sealed_oos_agent_visible_roots: list[Path] | None,
    expected_dataset_snapshot_sha256: str | None,
    expected_sealed_carrier_sha256: str | None,
    host_agent_termination_authority: dict[str, Any] | None,
    incident_trust_root: Path,
    incident_installation_id: str,
    _incident_guard: object,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    report_id = str(plan["identity"]["report_id"])
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=report_id,
        trust_root=incident_trust_root,
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise ValueError(f"{BLOCK_FINALIZATION}: " + ";".join(incident_reasons))
    prereg = validate_web_factor_proof_preregistration(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    allocation_path = oos_allocation_path(root, report_id)
    secure_child_oos = False
    if allocation_path.exists() or allocation_path.is_symlink():
        if not allocation_path.is_file() or allocation_path.is_symlink():
            raise ValueError(f"{BLOCK_FINALIZATION}: OOS allocation unsafe")
        allocation = _read_json(allocation_path)
        secure_child_oos = (
            allocation.get("allocation_authority_mode")
            == OOS_ALLOCATION_AUTHORITY_SECURE
        )
    if secure_child_oos:
        termination_authority = _validate_host_agent_termination_authority(
            host_agent_termination_authority,
            report_id=report_id,
        )
    elif host_agent_termination_authority is not None:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: unexpected Host Agent termination authority"
        )
    else:
        termination_authority = None
    if _web_evo_is_enabled(root, report_id):
        gate = resolve_web_evo_execution_gate(
            workspace_root=root,
            report_id=report_id,
            plan=plan,
            oos_release_token_hash=oos_release_token_hash,
        )
        if gate["action"] != "RELEASE_ORIGINAL_CANDIDATE_OOS":
            raise ValueError(
                f"{BLOCK_EVO_OOS_SEQUENCE}: OOS release forbidden in "
                f"{gate['current_state']}"
            )
    paths = web_factor_proof_paths(root, report_id)
    if paths["finalization"].is_file():
        return validate_web_factor_proof_finalization(
            root,
            plan,
            oos_release_token_hash=oos_release_token_hash,
            host_agent_termination_authority=termination_authority,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    spec = _read_json(paths["spec"])
    authorization_reasons = validate_oos_release_authorization(
        workspace_root=root,
        report_id=report_id,
        oos_window=spec["window_contract"].get("oos_window"),
        sealed_token_sha256=spec["window_contract"].get(
            "oos_release_token_hash"
        ),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    if authorization_reasons:
        raise ValueError(
            f"{BLOCK_FINALIZATION}: " + ";".join(authorization_reasons)
        )
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    panel = _build_oos_panel(
        root=root,
        report_id=report_id,
        spec=spec,
        calendar=calendar,
        output=paths["panel"],
        plan=plan,
        sealed_oos_carrier_path=sealed_oos_carrier_path,
        sealed_oos_private_root=sealed_oos_private_root,
        sealed_oos_agent_visible_roots=sealed_oos_agent_visible_roots,
        expected_dataset_snapshot_sha256=expected_dataset_snapshot_sha256,
        expected_sealed_carrier_sha256=expected_sealed_carrier_sha256,
    )
    identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=paths["panel"],
        spec=spec,
    )
    threshold = _read_json(paths["threshold"])
    write_oos_release_manifest(
        paths["release"],
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=paths["threshold"],
        host_agent_termination_authority=termination_authority,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    bound_spec = {**spec, **identities}
    _write_json_immutable(paths["bound_spec"], bound_spec)
    bundle = run_metric_verifier(
        workspace_root=root,
        panel_path=paths["panel"],
        spec=bound_spec,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    component_bindings = _finalize_component_obligations(
        root=root,
        plan=plan,
        metric_spec=spec,
        panel_path=paths["panel"],
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        incident_guard=_incident_guard,
    )
    certificate = _certificate_from_bundle(
        root=root,
        spec=bound_spec,
        bundle=bundle,
        threshold=threshold,
    )
    certificate["component_obligation_bindings"] = component_bindings
    report = validate_factor_proof_certificate(
        certificate,
        workspace_root=root,
        expected_report_id=report_id,
        expected_factor_id=str(plan["identity"]["factor_id"]),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    if (
        report.get("verdict") == "BLOCK"
        or report.get("block_reasons")
        or report.get("current_formal_authority_verified") is not True
    ):
        raise ValueError(
            f"{BLOCK_FINALIZATION}: {'; '.join(report.get('block_reasons') or [])}"
        )
    _write_json_immutable(paths["certificate"], certificate)
    verifier = {
        **report,
        "certificate_path": str(paths["certificate"]),
        "verifier_contract_version": BOUND_VERIFIER_VERSION,
        "research_id": plan["identity"]["research_id"],
        "formal_proof_eligible": True,
        "component_obligation_bindings": component_bindings,
    }
    _write_json_immutable(paths["verifier"], verifier)
    result = {
        "version": FINALIZATION_VERSION,
        "status": "PASS",
        "report_id": report_id,
        "factor_id": plan["identity"]["factor_id"],
        "research_id": plan["identity"]["research_id"],
        "preregistration_sha256": prereg["preregistration_sha256"],
        "factor_verdict": report["verdict"],
        "formal_proof_eligible": True,
        "component_obligation_bindings": component_bindings,
        "panel": panel,
        "metric_verifier_spec_sha256": sha256_file(paths["spec"]),
        "bound_metric_verifier_spec_ref": str(paths["bound_spec"].relative_to(root)),
        "bound_metric_verifier_spec_sha256": sha256_file(paths["bound_spec"]),
        "oos_release_manifest_ref": str(paths["release"].relative_to(root)),
        "oos_release_manifest_sha256": sha256_file(paths["release"]),
        "metric_verifier_bundle_ref": str(
            (
                root
                / "objects"
                / "research_protocol"
                / f"metric_verifier_bundle__{report_id}.json"
            ).relative_to(root)
        ),
        "metric_verifier_bundle_sha256": sha256_file(
            root
            / "objects"
            / "research_protocol"
            / f"metric_verifier_bundle__{report_id}.json"
        ),
        "factor_proof_certificate_ref": str(paths["certificate"].relative_to(root)),
        "factor_proof_certificate_sha256": sha256_file(paths["certificate"]),
        "factor_proof_verifier_ref": str(paths["verifier"].relative_to(root)),
        "factor_proof_verifier_sha256": sha256_file(paths["verifier"]),
    }
    if termination_authority is not None:
        result["host_agent_termination_authority"] = termination_authority
    _write_json_atomic(paths["finalization"], result)
    return validate_web_factor_proof_finalization(
        root,
        plan,
        oos_release_token_hash=oos_release_token_hash,
        host_agent_termination_authority=termination_authority,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
