from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from factor_factory.data_access.paths import resolve_local_tushare_paths
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
from factor_factory.research_proof import (
    CERTIFICATE_VERSION,
    derive_factor_proof_verdict,
    factor_proof_certificate_path,
    validate_factor_proof_certificate,
)
from factor_factory.research_release import (
    MINIMUM_FORMAL_DAILY_PERIODS,
    evaluation_contract_hash,
    stable_hash,
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)


PREREGISTRATION_VERSION = "factorforge_web_factor_proof_preregistration_v1"
FINALIZATION_VERSION = "factorforge_web_factor_proof_finalization_v1"
BOUND_VERIFIER_VERSION = "factorforge_console_bound_factor_proof_verifier_v1"
BLOCK_PREREGISTRATION = "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_PREREGISTRATION_INVALID"
BLOCK_FINALIZATION = "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_FINALIZATION_INVALID"
CALENDAR_SNAPSHOT_ID = "tushare_sse_open_days_19901219_20261231"
RISK_PROOF_CONTROL_COLUMNS = ("total_mv", "turnover_rate")


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
    }


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
    if plan["economic_mechanism"]["claim_class"] != "risk_premium":
        return []
    return list(RISK_PROOF_CONTROL_COLUMNS)


def default_web_decision_rules(claim_class: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {"rule_id": "rank_ic_positive", "metric_path": "metrics.ic.mean", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "icir_positive", "metric_path": "metrics.icir.value", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "volatility_drag_bounded", "metric_path": "metrics.volatility_cost.realized_volatility_drag", "operator": "<=", "threshold": 1.0, "on_fail": "INCONCLUSIVE"},
        {"rule_id": "net_return_after_cost_positive", "metric_path": "metrics.transaction_cost.net_return_annual", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
        {"rule_id": "drawdown_survival", "metric_path": "metrics.drawdown.max_drawdown", "operator": ">=", "threshold": -0.8, "on_fail": "INCONCLUSIVE"},
        {"rule_id": "long_end_positive", "metric_path": "metrics.long_end.net_geometric_return_annual", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
    ]
    if claim_class == "risk_premium":
        rules.extend(
            [
                {"rule_id": "fama_macbeth_positive", "metric_path": "metrics.fama_macbeth.lambda_tstat", "operator": ">", "threshold": 0.0, "on_fail": "REJECT"},
                {"rule_id": "bucket_monotonicity", "metric_path": "metrics.bucket_monotonicity.monotonicity_score", "operator": ">=", "threshold": 0.5, "on_fail": "INCONCLUSIVE"},
            ]
        )
    return rules


def build_web_metric_verifier_spec(
    plan: dict[str, Any],
    *,
    workspace_root: Path,
    calendar: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    identity = plan["identity"]
    evidence = plan["evidence_policy"]
    claim_class = str(plan["economic_mechanism"]["claim_class"])
    paths = web_factor_proof_paths(workspace_root, str(identity["report_id"]))
    planned = _planned_signal_window(plan, list(calendar["dates"]))
    controls = _risk_control_columns(plan)
    release_token = stable_hash(
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


def prepare_web_factor_proof(*, workspace_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    report_id = str(plan["identity"]["report_id"])
    factor_id = str(plan["identity"]["factor_id"])
    paths = web_factor_proof_paths(root, report_id)
    if paths["preregistration"].is_file():
        return validate_web_factor_proof_preregistration(root, plan)
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
    write_search_trial_ledger(
        paths["search_ledger"],
        report_id=report_id,
        factor_id=factor_id,
        trials=[trial],
        candidate_space={
            "formula_or_law": plan["research_object"]["formula_or_law"],
            "hypotheses": plan["hypotheses"],
            "trial_budget": plan["evidence_policy"]["trial_budget"],
        },
        selected_hypothesis=preferred,
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
    }
    _write_json_atomic(paths["preregistration"], receipt)
    return validate_web_factor_proof_preregistration(root, plan)


def validate_web_factor_proof_preregistration(
    workspace_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
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
        )
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


def _build_oos_panel(
    *,
    root: Path,
    report_id: str,
    spec: dict[str, Any],
    calendar: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    context_path = root / "runs" / report_id / f"shared_evaluation_context__{report_id}.json"
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
                *list(panel_contract.get("control_columns") or []),
            ]
        )
    )
    frame = pd.read_parquet(merged_path, columns=columns)
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
    missing_required = frame[columns].isna().any(axis=1)
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
    if output.exists() or output.is_symlink():
        if output.is_symlink() or not output.is_file():
            raise ValueError(f"{BLOCK_FINALIZATION}: OOS proof panel is unsafe")
        existing = pd.read_parquet(output).reset_index(drop=True)
        try:
            pd.testing.assert_frame_equal(
                existing,
                frame,
                check_dtype=False,
                check_exact=True,
            )
        except AssertionError as exc:
            raise ValueError(
                f"{BLOCK_FINALIZATION}: OOS proof panel retry mismatch"
            ) from exc
        return {
            "source_panel_ref": str(merged_path.relative_to(root)),
            "source_panel_sha256": sha256_file(merged_path),
            "panel_ref": str(output.relative_to(root)),
            "panel_sha256": sha256_file(output),
            "row_count": int(len(frame)),
            "period_count": len(signal_dates),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(output)
    return {
        "source_panel_ref": str(merged_path.relative_to(root)),
        "source_panel_sha256": sha256_file(merged_path),
        "panel_ref": str(output.relative_to(root)),
        "panel_sha256": sha256_file(output),
        "row_count": int(len(frame)),
        "period_count": len(signal_dates),
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


def validate_web_factor_proof_finalization(
    workspace_root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    preregistration = validate_web_factor_proof_preregistration(root, plan)
    report_id = str(plan["identity"]["report_id"])
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
    panel = result.get("panel") if isinstance(result.get("panel"), dict) else {}
    if (
        panel.get("panel_ref") != str(paths["panel"].relative_to(root))
        or not paths["panel"].is_file()
        or paths["panel"].is_symlink()
        or panel.get("panel_sha256") != sha256_file(paths["panel"])
    ):
        raise ValueError(f"{BLOCK_FINALIZATION}: proof panel binding mismatch")
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
    )
    verifier = _read_json(paths["verifier"])
    if (
        report.get("verdict") == "BLOCK"
        or report.get("block_reasons")
        or result.get("factor_verdict") != report.get("verdict")
        or verifier.get("verifier_contract_version") != BOUND_VERIFIER_VERSION
        or verifier.get("verdict") != report.get("verdict")
        or verifier.get("block_reasons")
        or verifier.get("formal_proof_eligible") is not True
    ):
        raise ValueError(f"{BLOCK_FINALIZATION}: bound factor proof invalid")
    return result


def finalize_web_factor_proof(*, workspace_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    prereg = validate_web_factor_proof_preregistration(root, plan)
    report_id = str(plan["identity"]["report_id"])
    paths = web_factor_proof_paths(root, report_id)
    if paths["finalization"].is_file():
        return validate_web_factor_proof_finalization(root, plan)
    spec = _read_json(paths["spec"])
    calendar = _trusted_calendar_snapshot(workspace_root=root)
    panel = _build_oos_panel(
        root=root,
        report_id=report_id,
        spec=spec,
        calendar=calendar,
        output=paths["panel"],
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
    )
    bound_spec = {**spec, **identities}
    _write_json_immutable(paths["bound_spec"], bound_spec)
    bundle = run_metric_verifier(
        workspace_root=root,
        panel_path=paths["panel"],
        spec=bound_spec,
    )
    certificate = _certificate_from_bundle(
        root=root,
        spec=bound_spec,
        bundle=bundle,
        threshold=threshold,
    )
    report = validate_factor_proof_certificate(
        certificate,
        workspace_root=root,
        expected_report_id=report_id,
        expected_factor_id=str(plan["identity"]["factor_id"]),
    )
    if report.get("verdict") == "BLOCK" or report.get("block_reasons"):
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
    _write_json_atomic(paths["finalization"], result)
    return validate_web_factor_proof_finalization(root, plan)
