from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from factor_factory.research_evidence import (
    resolve_workspace_evidence_path,
    sha256_file,
)
from factor_factory.research_release import (
    COMPONENT_ALLOWED_DECISION_PATHS as ALLOWED_DECISION_PATHS,
    COMPONENT_REQUIRED_DECISION_PATHS as REQUIRED_DECISION_PATHS,
    COMPONENT_SUPPORTED_OBLIGATION_KINDS as SUPPORTED_OBLIGATION_KINDS,
    MINIMUM_FORMAL_DAILY_PERIODS,
    observed_panel_dates,
    validate_evaluation_release_chain,
    validate_evaluation_release_chain_current,
    validate_observed_oos_window,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
)


VERIFIER_ID = "factorforge_component_obligation_verifier_v1"
VERIFIER_CONTRACT_VERSION = "factorforge_component_obligation_report_v1"
VERIFIER_SPEC_VERSION = "factorforge_component_obligation_spec_v1"
THRESHOLD_REGISTRATION_VERSION = (
    "factorforge_component_obligation_threshold_registration_v1"
)
SHA256_HEX_LENGTH = 64


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def verifier_source_sha256() -> str:
    return sha256_file(Path(__file__))


def _load_panel(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(
        "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_FORMAT_UNSUPPORTED"
    )


def component_verifier_identities(
    *,
    workspace_root: Path,
    panel_path: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=False)
    panel = panel_path.expanduser().resolve(strict=False)
    if panel != root and root not in panel.parents:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_OUTSIDE_WORKSPACE"
        )
    if not panel.is_file():
        raise ValueError("BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_MISSING")
    window_contract = spec.get("window_contract")
    if not isinstance(window_contract, dict) or not window_contract:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_WINDOW_CONTRACT_MISSING"
        )
    panel_contract = spec.get("panel")
    if not isinstance(panel_contract, dict):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:panel"
        )
    date_column = panel_contract.get("date_column")
    if not isinstance(date_column, str) or not date_column:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:panel.date_column"
        )
    observed = observed_panel_dates(
        _load_panel(panel),
        date_column=date_column,
    )
    return {
        "dataset_snapshot_hash": sha256_file(panel),
        "window_hash": stable_hash(window_contract),
        **observed,
    }


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_HEX_LENGTH
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def _validate_spec(
    spec: dict[str, Any],
    *,
    identities: dict[str, Any],
) -> None:
    if spec.get("version") != VERIFIER_SPEC_VERSION:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:version"
        )
    for field in ("report_id", "factor_id", "obligation_id"):
        if not isinstance(spec.get(field), str) or not spec[field].strip():
            raise ValueError(
                f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:{field}"
            )
    obligation_kind = spec.get("obligation_kind")
    if obligation_kind not in SUPPORTED_OBLIGATION_KINDS:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_OBLIGATION_KIND_UNSUPPORTED"
        )
    if spec.get("dataset_snapshot_hash") != identities["dataset_snapshot_hash"]:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_DATASET_HASH_MISMATCH"
        )
    if spec.get("window_hash") != identities["window_hash"]:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_WINDOW_HASH_MISMATCH"
        )
    window = spec.get("window_contract")
    if window.get("evaluation_window_role") != "OOS_FINAL":
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_WINDOW_NOT_OOS_FINAL"
        )
    if window.get("search_frozen_before_oos_release") is not True:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SEARCH_NOT_FROZEN"
        )
    if not _valid_sha256(window.get("oos_release_token_hash")):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_OOS_RELEASE_HASH_INVALID"
        )
    for field in (
        "oos_window",
        "observed_start_date",
        "observed_end_date",
        "forward_return_horizon",
        "signal_timestamp",
        "execution_timestamp",
        "universe_id",
        "investability_mask_id",
        "search_trial_ledger_ref",
        "oos_release_manifest_ref",
    ):
        if not isinstance(window.get(field), str) or not window[field].strip():
            raise ValueError(
                "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_WINDOW_FIELD_MISSING:"
                f"{field}"
            )
    if window.get("return_convention") != "simple_return":
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RETURN_CONVENTION_UNSUPPORTED"
        )
    panel = spec.get("panel")
    if not isinstance(panel, dict):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:panel"
        )
    for field in (
        "date_column",
        "asset_column",
        "full_signal_column",
        "ablated_signal_column",
        "forward_return_column",
    ):
        if not isinstance(panel.get(field), str) or not panel[field].strip():
            raise ValueError(
                "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:"
                f"panel.{field}"
            )
    test = spec.get("test")
    if not isinstance(test, dict):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SPEC_INVALID:test"
        )
    if test.get("expected_direction") not in {"positive", "negative"}:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_DIRECTION_INVALID"
        )
    long_quantile = test.get("long_quantile")
    if (
        isinstance(long_quantile, bool)
        or not isinstance(long_quantile, (int, float))
        or not 0 < float(long_quantile) <= 0.5
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_LONG_QUANTILE_INVALID"
        )
    if window.get("sample_frequency") != "daily":
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SAMPLE_FREQUENCY_UNSUPPORTED"
        )
    validate_observed_oos_window(window, identities)


def _prepare_panel(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    panel = spec["panel"]
    date_col = panel["date_column"]
    asset_col = panel["asset_column"]
    full_col = panel["full_signal_column"]
    ablated_col = panel["ablated_signal_column"]
    return_col = panel["forward_return_column"]
    required = [date_col, asset_col, full_col, ablated_col, return_col]
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_COLUMNS_MISSING:"
            + ",".join(missing)
        )
    work = frame[required].copy()
    parsed_dates = pd.to_datetime(work[date_col], errors="coerce", utc=True)
    if parsed_dates.isna().any():
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_DATE_INVALID"
        )
    work[date_col] = parsed_dates.dt.strftime("%Y-%m-%d")
    work[asset_col] = work[asset_col].astype(str)
    for column in (full_col, ablated_col, return_col):
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work.replace([np.inf, -np.inf], np.nan)
    work = work.dropna(subset=required)
    if work.duplicated([date_col, asset_col]).any():
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_IDENTITY_DUPLICATE"
        )
    minimum_periods = int(spec["window_contract"]["minimum_periods"])
    if (
        minimum_periods < MINIMUM_FORMAL_DAILY_PERIODS
        or work[date_col].nunique() < minimum_periods
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_PANEL_PERIODS_INSUFFICIENT"
        )
    if work.groupby(date_col)[asset_col].nunique().min() < 4:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_CROSS_SECTION_INSUFFICIENT"
        )
    if (work[return_col] <= -1.0).any():
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_SIMPLE_RETURN_RANGE_INVALID"
        )
    direction = 1.0 if spec["test"]["expected_direction"] == "positive" else -1.0
    work[full_col] *= direction
    work[ablated_col] *= direction
    return work.sort_values([date_col, asset_col]).reset_index(drop=True)


def _rank_ic_series(
    frame: pd.DataFrame,
    *,
    date_col: str,
    signal_col: str,
    return_col: str,
) -> pd.Series:
    values: dict[str, float] = {}
    for date, group in frame.groupby(date_col, sort=True):
        signal_rank = group[signal_col].rank(method="average")
        return_rank = group[return_col].rank(method="average")
        value = signal_rank.corr(return_rank)
        if pd.notna(value):
            values[str(date)] = float(value)
    return pd.Series(values, dtype=float)


def _residual_rank_ic_series(
    frame: pd.DataFrame,
    *,
    date_col: str,
    full_col: str,
    ablated_col: str,
    return_col: str,
) -> pd.Series:
    values: dict[str, float] = {}
    for date, group in frame.groupby(date_col, sort=True):
        full_rank = group[full_col].rank(method="average").to_numpy(dtype=float)
        ablated_rank = (
            group[ablated_col].rank(method="average").to_numpy(dtype=float)
        )
        return_rank = (
            group[return_col].rank(method="average").to_numpy(dtype=float)
        )
        design = np.column_stack([np.ones(len(group)), ablated_rank])
        beta, _, _, _ = np.linalg.lstsq(design, full_rank, rcond=None)
        residual = full_rank - design @ beta
        if np.std(residual) <= 0 or np.std(return_rank) <= 0:
            continue
        value = float(np.corrcoef(residual, return_rank)[0, 1])
        if math.isfinite(value):
            values[str(date)] = value
    return pd.Series(values, dtype=float)


def _long_end_daily_mean(
    frame: pd.DataFrame,
    *,
    date_col: str,
    signal_col: str,
    return_col: str,
    long_quantile: float,
) -> tuple[float, int]:
    daily: list[float] = []
    for _, group in frame.groupby(date_col, sort=True):
        threshold = group[signal_col].quantile(1.0 - long_quantile)
        selected = group[group[signal_col] >= threshold]
        if not selected.empty:
            daily.append(float(selected[return_col].mean()))
    if len(daily) < 2:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_LONG_END_PERIODS_INSUFFICIENT"
        )
    return float(np.mean(daily)), len(daily)


def _build_metrics(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    panel = spec["panel"]
    date_col = panel["date_column"]
    full_col = panel["full_signal_column"]
    ablated_col = panel["ablated_signal_column"]
    return_col = panel["forward_return_column"]
    full_ic = _rank_ic_series(
        frame,
        date_col=date_col,
        signal_col=full_col,
        return_col=return_col,
    )
    ablated_ic = _rank_ic_series(
        frame,
        date_col=date_col,
        signal_col=ablated_col,
        return_col=return_col,
    )
    residual_ic = _residual_rank_ic_series(
        frame,
        date_col=date_col,
        full_col=full_col,
        ablated_col=ablated_col,
        return_col=return_col,
    )
    if min(len(full_ic), len(ablated_ic), len(residual_ic)) < 2:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_IC_PERIODS_INSUFFICIENT"
        )
    full_long, full_long_periods = _long_end_daily_mean(
        frame,
        date_col=date_col,
        signal_col=full_col,
        return_col=return_col,
        long_quantile=float(spec["test"]["long_quantile"]),
    )
    ablated_long, ablated_long_periods = _long_end_daily_mean(
        frame,
        date_col=date_col,
        signal_col=ablated_col,
        return_col=return_col,
        long_quantile=float(spec["test"]["long_quantile"]),
    )
    full_ic_mean = float(full_ic.mean())
    ablated_ic_mean = float(ablated_ic.mean())
    return {
        "full_rank_ic_mean": full_ic_mean,
        "ablated_rank_ic_mean": ablated_ic_mean,
        "residual_rank_ic_mean": float(residual_ic.mean()),
        "rank_ic_delta": full_ic_mean - ablated_ic_mean,
        "full_long_end_mean": full_long,
        "ablated_long_end_mean": ablated_long,
        "long_end_delta": full_long - ablated_long,
        "full_ic_period_count": int(len(full_ic)),
        "ablated_ic_period_count": int(len(ablated_ic)),
        "residual_ic_period_count": int(len(residual_ic)),
        "full_long_end_period_count": full_long_periods,
        "ablated_long_end_period_count": ablated_long_periods,
        "expected_direction": spec["test"]["expected_direction"],
        "long_quantile": float(spec["test"]["long_quantile"]),
    }


def _nested(payload: dict[str, Any], dotted_path: str) -> Any:
    value: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _compare(actual: float, operator: str, threshold: float) -> bool:
    if operator == ">":
        return actual > threshold
    if operator == ">=":
        return actual >= threshold
    if operator == "<":
        return actual < threshold
    if operator == "<=":
        return actual <= threshold
    raise ValueError(
        f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RULE_OPERATOR_INVALID:{operator}"
    )


def _evaluate_rules(
    metrics: dict[str, Any],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluation_payload = {"metrics": metrics}
    outcomes: list[dict[str, Any]] = []
    for rule in rules:
        actual = _nested(evaluation_payload, str(rule["metric_path"]))
        if (
            isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isfinite(float(actual))
        ):
            passed = False
        else:
            passed = _compare(
                float(actual),
                str(rule["operator"]),
                float(rule["threshold"]),
            )
        outcomes.append(
            {
                "rule_id": rule["rule_id"],
                "metric_path": rule["metric_path"],
                "operator": rule["operator"],
                "threshold": rule["threshold"],
                "actual": actual,
                "passed": passed,
            }
        )
    return outcomes


def _load_threshold_registration(
    *,
    workspace_root: Path,
    raw_path: Any,
    spec: dict[str, Any],
    identities: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    path = resolve_workspace_evidence_path(workspace_root, raw_path)
    if path is None or not path.is_file():
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_THRESHOLD_REGISTRATION_MISSING"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "version": THRESHOLD_REGISTRATION_VERSION,
        "registration_status": "LOCKED",
        "report_id": spec["report_id"],
        "factor_id": spec["factor_id"],
        "obligation_id": spec["obligation_id"],
        "obligation_kind": spec["obligation_kind"],
        "window_hash": identities["window_hash"],
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise ValueError(
                "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_THRESHOLD_IDENTITY_MISMATCH:"
                f"{field}"
            )
    rules = payload.get("decision_rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_THRESHOLD_RULES_MISSING"
        )
    if payload.get("rule_set_sha256") != stable_hash(rules):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_THRESHOLD_RULE_HASH_MISMATCH"
        )
    if payload.get("registered_before_evaluation") is not True:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_THRESHOLDS_POST_HOC"
        )
    rule_ids: set[str] = set()
    rule_paths: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(
                f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RULE_INVALID:{index}"
            )
        rule_id = rule.get("rule_id")
        metric_path = rule.get("metric_path")
        operator = rule.get("operator")
        threshold = rule.get("threshold")
        if not isinstance(rule_id, str) or not rule_id.strip() or rule_id in rule_ids:
            raise ValueError(
                f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RULE_ID_INVALID:{index}"
            )
        rule_ids.add(rule_id)
        if metric_path not in ALLOWED_DECISION_PATHS:
            raise ValueError(
                f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RULE_PATH_INVALID:{index}"
            )
        rule_paths.add(str(metric_path))
        if operator not in {">", ">="}:
            raise ValueError(
                f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RULE_DIRECTION_INVALID:{index}"
            )
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(float(threshold))
            or float(threshold) < 0
        ):
            raise ValueError(
                f"BLOCK_FACTORFORGE_COMPONENT_VERIFIER_RULE_THRESHOLD_INVALID:{index}"
            )
    missing_paths = REQUIRED_DECISION_PATHS[spec["obligation_kind"]] - rule_paths
    if missing_paths:
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_CORE_RULE_MISSING:"
            + ",".join(sorted(missing_paths))
        )
    return path, payload


def run_component_obligation_verifier(
    *,
    workspace_root: Path,
    panel_path: Path,
    spec: dict[str, Any],
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    current_context = (
        incident_trust_root is not None,
        bool(incident_installation_id),
    )
    if current_context[0] != current_context[1] or (
        _incident_guard is not None and not all(current_context)
    ):
        raise ValueError(
            "BLOCK_FACTORFORGE_COMPONENT_VERIFIER_INCIDENT_HOST_CONTEXT_INCOMPLETE"
        )
    if all(current_context) and _incident_guard is None:
        assert incident_trust_root is not None
        trust_root = incident_trust_root.expanduser().resolve(strict=True)
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id=str(incident_installation_id),
        ) as guard:
            return run_component_obligation_verifier(
                workspace_root=workspace_root,
                panel_path=panel_path,
                spec=spec,
                incident_trust_root=trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=guard,
            )
    root = workspace_root.expanduser().resolve(strict=False)
    resolved_panel = panel_path.expanduser().resolve(strict=False)
    identities = component_verifier_identities(
        workspace_root=root,
        panel_path=resolved_panel,
        spec=spec,
    )
    _validate_spec(spec, identities=identities)
    threshold_path, threshold_payload = _load_threshold_registration(
        workspace_root=root,
        raw_path=spec.get("threshold_registration_ref"),
        spec=spec,
        identities=identities,
    )
    if incident_trust_root is not None and incident_installation_id:
        release_chain = validate_evaluation_release_chain_current(
            workspace_root=root,
            spec=spec,
            identities=identities,
            threshold_path=threshold_path,
            threshold_payload=threshold_payload,
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    else:
        release_chain = validate_evaluation_release_chain(
            workspace_root=root,
            spec=spec,
            identities=identities,
            threshold_path=threshold_path,
            threshold_payload=threshold_payload,
        )
    frame = _prepare_panel(_load_panel(resolved_panel), spec)
    metrics = _build_metrics(frame, spec)
    outcomes = _evaluate_rules(metrics, threshold_payload["decision_rules"])
    verifier_status = (
        "PASS" if outcomes and all(item["passed"] for item in outcomes) else "FAIL"
    )
    threshold_sha256 = sha256_file(threshold_path)
    source_sha256 = verifier_source_sha256()
    report = {
        "verifier_contract_version": VERIFIER_CONTRACT_VERSION,
        "verifier_id": VERIFIER_ID,
        "verifier_source_sha256": source_sha256,
        "verifier_status": verifier_status,
        "report_id": spec["report_id"],
        "factor_id": spec["factor_id"],
        "obligation_id": spec["obligation_id"],
        "obligation_kind": spec["obligation_kind"],
        "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
        "window_hash": identities["window_hash"],
        "threshold_registration_ref": str(threshold_path.relative_to(root)),
        "threshold_registration_sha256": threshold_sha256,
        "threshold_rule_set_sha256": threshold_payload["rule_set_sha256"],
        "decision_rules": threshold_payload["decision_rules"],
        "rule_outcomes": outcomes,
        "metrics": metrics,
        "source_panel_ref": str(resolved_panel.relative_to(root)),
        "source_panel_sha256": identities["dataset_snapshot_hash"],
        "source_row_count": int(len(frame)),
        "verifier_spec": spec,
        "evaluation_release_chain": release_chain,
    }
    output_path = (
        root
        / "objects"
        / "evidence"
        / "research_obligations"
        / str(spec["report_id"])
        / f"{spec['obligation_id']}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    reference = {
        "path": str(output_path.relative_to(root)),
        "sha256": sha256_file(output_path),
        "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
        "window_hash": identities["window_hash"],
        "verifier_id": VERIFIER_ID,
        "verifier_source_sha256": source_sha256,
        "verifier_status": verifier_status,
        "verifier_contract_version": VERIFIER_CONTRACT_VERSION,
        "obligation_id": spec["obligation_id"],
        "obligation_kind": spec["obligation_kind"],
        "threshold_registration_sha256": threshold_sha256,
        "threshold_rule_set_sha256": threshold_payload["rule_set_sha256"],
    }
    return {
        "version": "factorforge_component_obligation_bundle_v1",
        "verifier_status": verifier_status,
        "report": report,
        "evidence_reference": reference,
    }


def validate_component_obligation_report(
    report: dict[str, Any],
    *,
    workspace_root: Path,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    current_context = (
        incident_trust_root is not None,
        bool(incident_installation_id),
    )
    if current_context[0] != current_context[1] or (
        _incident_guard is not None and not all(current_context)
    ):
        return [
            "COMPONENT_EVIDENCE_INCIDENT_HOST_CONTEXT_INCOMPLETE"
        ]
    if all(current_context) and _incident_guard is None:
        assert incident_trust_root is not None
        trust_root = incident_trust_root.expanduser().resolve(strict=True)
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id=str(incident_installation_id),
        ) as guard:
            return validate_component_obligation_report(
                report,
                workspace_root=workspace_root,
                incident_trust_root=trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=guard,
            )
    reasons: list[str] = []
    if not isinstance(report, dict):
        return ["COMPONENT_EVIDENCE_REPORT_INVALID"]
    if report.get("verifier_contract_version") != VERIFIER_CONTRACT_VERSION:
        reasons.append("COMPONENT_EVIDENCE_CONTRACT_INVALID")
    if report.get("verifier_id") != VERIFIER_ID:
        reasons.append("COMPONENT_EVIDENCE_VERIFIER_ID_INVALID")
    if report.get("verifier_source_sha256") != verifier_source_sha256():
        reasons.append("COMPONENT_EVIDENCE_SOURCE_HASH_MISMATCH")
    spec = report.get("verifier_spec")
    if not isinstance(spec, dict):
        reasons.append("COMPONENT_EVIDENCE_SPEC_MISSING")
        return reasons
    root = workspace_root.expanduser().resolve(strict=False)
    panel_path = resolve_workspace_evidence_path(root, report.get("source_panel_ref"))
    if panel_path is None or not panel_path.is_file():
        reasons.append("COMPONENT_EVIDENCE_PANEL_MISSING")
        return reasons
    try:
        identities = component_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=spec,
        )
        _validate_spec(spec, identities=identities)
        threshold_path, threshold_payload = _load_threshold_registration(
            workspace_root=root,
            raw_path=spec.get("threshold_registration_ref"),
            spec=spec,
            identities=identities,
        )
        current_replay = bool(
            incident_trust_root is not None and incident_installation_id
        )
        if current_replay:
            release_chain = validate_evaluation_release_chain_current(
                workspace_root=root,
                spec=spec,
                identities=identities,
                threshold_path=threshold_path,
                threshold_payload=threshold_payload,
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
            )
        else:
            release_chain = validate_evaluation_release_chain(
                workspace_root=root,
                spec=spec,
                identities=identities,
                threshold_path=threshold_path,
                threshold_payload=threshold_payload,
            )
            claimed_chain = report.get("evaluation_release_chain")
            if isinstance(claimed_chain, dict):
                if "current_formal_authority_verified" in claimed_chain:
                    release_chain["current_formal_authority_verified"] = (
                        claimed_chain["current_formal_authority_verified"]
                    )
                else:
                    release_chain.pop("current_formal_authority_verified", None)
        claimed_chain = report.get("evaluation_release_chain")
        if isinstance(claimed_chain, dict):
            if "current_formal_authority_verified" in claimed_chain:
                release_chain["current_formal_authority_verified"] = (
                    claimed_chain["current_formal_authority_verified"]
                )
            else:
                release_chain.pop("current_formal_authority_verified", None)
        frame = _prepare_panel(_load_panel(panel_path), spec)
        metrics = _build_metrics(frame, spec)
        outcomes = _evaluate_rules(metrics, threshold_payload["decision_rules"])
    except Exception as exc:
        reasons.append(f"COMPONENT_EVIDENCE_REPLAY_FAILED:{exc}")
        return reasons
    verifier_status = (
        "PASS" if outcomes and all(item["passed"] for item in outcomes) else "FAIL"
    )
    expected = {
        "report_id": spec.get("report_id"),
        "factor_id": spec.get("factor_id"),
        "obligation_id": spec.get("obligation_id"),
        "obligation_kind": spec.get("obligation_kind"),
        "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
        "window_hash": identities["window_hash"],
        "threshold_registration_ref": str(threshold_path.relative_to(root)),
        "threshold_registration_sha256": sha256_file(threshold_path),
        "threshold_rule_set_sha256": threshold_payload.get("rule_set_sha256"),
        "decision_rules": threshold_payload.get("decision_rules"),
        "rule_outcomes": outcomes,
        "metrics": metrics,
        "source_panel_sha256": identities["dataset_snapshot_hash"],
        "source_row_count": int(len(frame)),
        "verifier_status": verifier_status,
        "evaluation_release_chain": release_chain,
    }
    for field, value in expected.items():
        if report.get(field) != value:
            reasons.append(f"COMPONENT_EVIDENCE_REPLAY_MISMATCH:{field}")
    return reasons
