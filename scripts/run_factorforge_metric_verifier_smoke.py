#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import factor_factory.metric_verifier as metric_verifier_module
from factor_factory.metric_verifier import (
    TRADING_CALENDAR_REGISTRY_PATH,
    TRADING_CALENDAR_REGISTRY_TRUST_BLOB,
    TRADING_CALENDAR_REGISTRY_TRUST_COMMIT,
    _bucket_returns,
    _drawdown_geometry,
    _validate_spec,
    metric_verifier_identities,
    run_metric_verifier,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_release import (
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)
from factor_factory.research_proof import (
    CERTIFICATE_VERSION,
    REQUIRED_DECISION_PATHS,
    stable_hash,
    validate_factor_proof_certificate,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_release_cli_smoke(
    *,
    source_panel: Path,
    source_calendar: Path,
    bound_spec: dict,
    decision_rules: list[dict],
) -> dict[str, bool]:
    root = Path("/tmp/factorforge_release_chain_cli_smoke")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    panel_path = root / "runs" / "release_smoke" / "frozen_oos_panel.csv"
    panel_path.parent.mkdir(parents=True)
    shutil.copy2(source_panel, panel_path)

    spec = deepcopy(bound_spec)
    spec.pop("dataset_snapshot_hash", None)
    spec.pop("window_hash", None)
    child_env = os.environ.copy()
    child_env["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
        source_calendar
    )
    spec_path = root / "objects" / "research_protocol" / "metric_spec.json"
    rules_path = root / "objects" / "research_protocol" / "rules.json"
    trials_path = root / "objects" / "research_protocol" / "trials.json"
    candidate_space_path = (
        root / "objects" / "research_protocol" / "candidate_space.json"
    )
    selected_path = (
        root / "objects" / "research_protocol" / "selected_hypothesis.json"
    )
    ledger_path = (
        root
        / "objects"
        / "research_protocol"
        / f"search_trial_ledger__{spec['report_id']}.json"
    )
    write_json(spec_path, spec)
    write_json(rules_path, decision_rules)
    write_json(trials_path, [{"trial_id": "trial_001", "decision": "selected"}])
    write_json(candidate_space_path, {"family": "linear_signal"})
    write_json(selected_path, {"signal": "metric_verifier_smoke_signal"})
    cli = REPO_ROOT / "scripts" / "write_factorforge_evaluation_release_chain.py"

    freeze = subprocess.run(
        [
            sys.executable,
            str(cli),
            "freeze-search",
            "--workspace-root",
            str(root),
            "--report-id",
            spec["report_id"],
            "--factor-id",
            spec["factor_id"],
            "--trials",
            str(trials_path),
            "--candidate-space",
            str(candidate_space_path),
            "--selected-hypothesis",
            str(selected_path),
            "--output",
            str(ledger_path),
        ],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
    )
    invalid_rules = [
        rule
        for rule in decision_rules
        if rule.get("metric_path")
        != "metrics.bucket_monotonicity.monotonicity_score"
    ]
    write_json(rules_path, invalid_rules)
    invalid_register = subprocess.run(
        [
            sys.executable,
            str(cli),
            "register-threshold",
            "--workspace-root",
            str(root),
            "--spec",
            str(spec_path),
            "--decision-rules",
            str(rules_path),
        ],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
    )
    threshold_path = root / str(spec["threshold_registration_ref"])
    release_path = root / spec["window_contract"]["oos_release_manifest_ref"]
    invalid_registration_left_no_release_artifacts = (
        invalid_register.returncode != 0
        and "THRESHOLD_RULE_COVERAGE_MISSING:bucket_monotonicity"
        in invalid_register.stderr
        and not threshold_path.exists()
        and not release_path.exists()
    )
    write_json(rules_path, decision_rules)
    register = subprocess.run(
        [
            sys.executable,
            str(cli),
            "register-threshold",
            "--workspace-root",
            str(root),
            "--spec",
            str(spec_path),
            "--decision-rules",
            str(rules_path),
        ],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
    )
    release = subprocess.run(
        [
            sys.executable,
            str(cli),
            "release-oos",
            "--workspace-root",
            str(root),
            "--panel",
            str(panel_path),
            "--spec",
            str(spec_path),
        ],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
    )
    rebound_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    escape = subprocess.run(
        [
            sys.executable,
            str(cli),
            "freeze-search",
            "--workspace-root",
            str(root),
            "--report-id",
            spec["report_id"],
            "--factor-id",
            spec["factor_id"],
            "--trials",
            str(trials_path),
            "--candidate-space",
            str(candidate_space_path),
            "--selected-hypothesis",
            str(selected_path),
            "--output",
            "/tmp/factorforge_release_chain_escape.json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return {
        "three_stage_cli_passes": (
            freeze.returncode == 0
            and register.returncode == 0
            and release.returncode == 0
            and bool(rebound_spec.get("dataset_snapshot_hash"))
            and bool(rebound_spec.get("window_hash"))
            and release_path.is_file()
        ),
        "workspace_escape_blocks": (
            escape.returncode != 0
            and "BLOCK_FACTORFORGE_RESEARCH_RELEASE_PATH_OUTSIDE_WORKSPACE"
            in escape.stderr
        ),
        "invalid_rules_block_before_oos_release": (
            invalid_registration_left_no_release_artifacts
        ),
    }


def main() -> int:
    root = Path("/tmp/factorforge_metric_verifier_smoke")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    report_id = "METRIC_VERIFIER_SMOKE"
    factor_id = "METRIC_VERIFIER_FACTOR"
    panel_path = root / "runs" / report_id / "frozen_oos_panel.csv"
    panel_path.parent.mkdir(parents=True)
    rows: list[dict] = []
    trusted_calendar_fixture = (
        REPO_ROOT
        / "tests"
        / "fixtures"
        / "trusted_calendar"
        / "tushare_sse_trade_cal_19901219_20261231.csv"
    )
    authority_calendar_frame = pd.read_csv(
        trusted_calendar_fixture,
        encoding="utf-8-sig",
        dtype={"exchange": "string", "cal_date": "string", "is_open": "string"},
    )
    open_calendar_rows = authority_calendar_frame["is_open"] == "1"
    if "exchange" in authority_calendar_frame.columns:
        open_calendar_rows &= authority_calendar_frame["exchange"] == "SSE"
    authority_calendar_dates = pd.DatetimeIndex(
        pd.to_datetime(
            authority_calendar_frame.loc[
                open_calendar_rows,
                "cal_date",
            ],
            format="%Y%m%d",
        ).sort_values()
    )
    calendar_start = int(
        authority_calendar_dates.searchsorted(pd.Timestamp("2026-01-05"))
    )
    calendar_dates = authority_calendar_dates[
        calendar_start : calendar_start + 66
    ]
    authority_calendar_sha256 = stable_hash(
        [
            value.strftime("%Y-%m-%d")
            for value in authority_calendar_dates
        ]
    )
    registry_sha256 = sha256_file(TRADING_CALENDAR_REGISTRY_PATH)
    trade_dates = calendar_dates[:64]
    for date_index, date_value in enumerate(trade_dates):
        trade_date = date_value.strftime("%Y-%m-%d")
        label_start_date = calendar_dates[date_index + 1].strftime(
            "%Y-%m-%d"
        )
        label_end_date = calendar_dates[date_index + 2].strftime(
            "%Y-%m-%d"
        )
        slope = 0.0015 + 0.00025 * math.sin(date_index)
        for asset_index in range(10):
            signal = float(asset_index - 4.5)
            size_control = float((asset_index * 3 + date_index) % 7 - 3)
            residual = 0.0015 * math.cos(
                (date_index + 1) * (asset_index + 2)
            )
            forward_return = (
                slope * signal
                + 0.00015 * size_control
                + residual
            )
            label_start_price = 100.0 + asset_index + date_index * 0.1
            rows.append(
                {
                    "trade_date": trade_date,
                    "ts_code": f"ASSET{asset_index:02d}",
                    "signal": signal + 0.05 * math.sin(date_index + asset_index),
                    "forward_return": forward_return,
                    "fwd_ret_5d": forward_return * 5.0,
                    "label_start_date": label_start_date,
                    "label_end_date": label_end_date,
                    "label_start_price": label_start_price,
                    "label_end_price": label_start_price
                    * (1.0 + forward_return),
                    "size_control": size_control,
                }
            )
    pd.DataFrame(rows).to_csv(panel_path, index=False)
    calendar_authority_root = Path(
        "/tmp/factorforge_data_api_calendar_authority_metric_smoke"
    )
    shutil.rmtree(calendar_authority_root, ignore_errors=True)
    calendar_authority_root.mkdir(parents=True)
    calendar_path = calendar_authority_root / "trade_cal.csv"
    shutil.copy2(trusted_calendar_fixture, calendar_path)
    os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
        calendar_path
    )
    ledger_path = (
        root
        / "objects"
        / "research_protocol"
        / f"search_trial_ledger__{report_id}.json"
    )
    write_search_trial_ledger(
        ledger_path,
        report_id=report_id,
        factor_id=factor_id,
        trials=[{"trial_id": "trial_001", "decision": "selected"}],
        candidate_space={"family": "linear_signal"},
        selected_hypothesis={"signal": "metric_verifier_smoke_signal"},
    )
    release_path = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{report_id}.json"
    )
    window_contract = {
        "evaluation_window_role": "OOS_FINAL",
        "oos_window": (
            f"{trade_dates[0].strftime('%Y-%m-%d')}/"
            f"{trade_dates[-1].strftime('%Y-%m-%d')}"
        ),
        "observed_start_date": trade_dates[0].strftime("%Y-%m-%d"),
        "observed_end_date": trade_dates[-1].strftime("%Y-%m-%d"),
        "minimum_periods": 60,
        "oos_release_token_hash": "f" * 64,
        "forward_return_horizon": "t+1 close to t+2 close",
        "forward_return_horizon_days": 1,
        "sample_frequency": "daily",
        "signal_timestamp": "t close",
        "execution_timestamp": "t+1 close",
        "label_start_timestamp": "t+1 close",
        "label_end_timestamp": "t+2 close",
        "forward_return_formula": "label_end_price/label_start_price-1",
        "path_is_disjoint": True,
        "universe_id": "metric_verifier_smoke_universe",
        "investability_mask_id": "metric_verifier_smoke_mask",
        "search_frozen_before_oos_release": True,
        "return_convention": "simple_return",
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "oos_release_manifest_ref": str(release_path.relative_to(root)),
    }
    spec = {
        "version": "factorforge_metric_verifier_spec_v2",
        "verification_scope": "production",
        "report_id": report_id,
        "factor_id": factor_id,
        "claim_class": "risk_premium",
        "cost_policy_id": "metric_verifier_smoke_cost_v1",
        "panel": {
            "date_column": "trade_date",
            "asset_column": "ts_code",
            "signal_column": "signal",
            "forward_return_column": "forward_return",
            "control_columns": ["size_control"],
        },
        "label_contract": {
            "version": "factorforge_daily_return_label_contract_v1",
            "signal_date_column": "trade_date",
            "label_start_date_column": "label_start_date",
            "label_end_date_column": "label_end_date",
            "label_start_price_column": "label_start_price",
            "label_end_price_column": "label_end_price",
            "forward_return_column": "forward_return",
            "return_formula": "label_end_price/label_start_price-1",
            "return_tolerance": 1e-12,
            "signal_to_label_start_trading_days": 1,
            "holding_period_trading_days": 1,
            "path_is_disjoint": True,
            "label_start_timestamp": "t+1 close",
            "label_end_timestamp": "t+2 close",
            "trading_calendar_ref": (
                "factorforge_data_access.trade_cal_csv"
            ),
            "trading_calendar_sha256": authority_calendar_sha256,
            "trading_calendar_registry_sha256": registry_sha256,
            "trading_calendar_registry_git_commit": (
                TRADING_CALENDAR_REGISTRY_TRUST_COMMIT
            ),
            "trading_calendar_registry_git_blob": (
                TRADING_CALENDAR_REGISTRY_TRUST_BLOB
            ),
            "trading_calendar_snapshot_id": (
                "tushare_sse_open_days_19901219_20261231"
            ),
            "trading_calendar_id": "cn_a_share_tushare_open_days",
        },
        "window_contract": window_contract,
        "portfolio": {
            "annualization_factor": 252,
            "long_quantile": 0.2,
            "cost_bps_per_turnover": 20.0,
            "other_annual_costs": 0.001,
            "cost_scope": "commission and deterministic slippage proxy",
            "execution_assumption": "verified t+1 close forward return",
            "rebalance_frequency": "daily",
            "return_path_mode": "daily_one_period_forward_return",
            "holding_period_days": 1,
        },
        "fama_macbeth": {"newey_west_lags": 3},
        "bucket_monotonicity": {
            "bucket_count": 5,
            "expected_direction": "ascending",
        },
        "threshold_registration_ref": (
            "objects/research_protocol/"
            f"thresholds__{report_id}.json"
        ),
    }
    decision_rules = [
        {
            "rule_id": "ic_floor",
            "metric_path": "metrics.ic.mean",
            "operator": ">=",
            "threshold": 0.0,
            "on_fail": "REJECT",
        },
        {
            "rule_id": "icir_floor",
            "metric_path": "metrics.icir.value",
            "operator": ">=",
            "threshold": 0.0,
            "on_fail": "REJECT",
        },
        {
            "rule_id": "volatility_drag_ceiling",
            "metric_path": "metrics.volatility_cost.realized_volatility_drag",
            "operator": "<=",
            "threshold": 100.0,
            "on_fail": "INCONCLUSIVE",
        },
        {
            "rule_id": "net_after_cost_floor",
            "metric_path": "metrics.transaction_cost.net_return_annual",
            "operator": ">=",
            "threshold": 0.0,
            "on_fail": "REJECT",
        },
        {
            "rule_id": "drawdown_floor",
            "metric_path": "metrics.drawdown.max_drawdown",
            "operator": ">=",
            "threshold": -0.8,
            "on_fail": "INCONCLUSIVE",
        },
        {
            "rule_id": "long_end_floor",
            "metric_path": "metrics.long_end.net_geometric_return_annual",
            "operator": ">=",
            "threshold": 0.0,
            "on_fail": "REJECT",
        },
        {
            "rule_id": "fama_macbeth_tstat_floor",
            "metric_path": "metrics.fama_macbeth.lambda_tstat",
            "operator": ">=",
            "threshold": 0.0,
            "on_fail": "REJECT",
        },
        {
            "rule_id": "monotonicity_floor",
            "metric_path": "metrics.bucket_monotonicity.monotonicity_score",
            "operator": ">=",
            "threshold": 0.5,
            "on_fail": "INCONCLUSIVE",
        },
    ]
    threshold_path = root / spec["threshold_registration_ref"]
    write_threshold_registration(
        threshold_path,
        workspace_root=root,
        spec=spec,
        decision_rules=decision_rules,
    )
    threshold_idempotent = (
        write_threshold_registration(
            threshold_path,
            workspace_root=root,
            spec=spec,
            decision_rules=decision_rules,
        )["evaluation_contract_hash"]
        == json.loads(threshold_path.read_text(encoding="utf-8"))[
            "evaluation_contract_hash"
        ]
    )
    threshold_overwrite_blocked = False
    changed_registration_spec = deepcopy(spec)
    changed_registration_spec["portfolio"]["cost_bps_per_turnover"] += 1.0
    try:
        write_threshold_registration(
            threshold_path,
            workspace_root=root,
            spec=changed_registration_spec,
            decision_rules=decision_rules,
        )
    except ValueError as exc:
        threshold_overwrite_blocked = (
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_REGISTRATION_IMMUTABLE"
            in str(exc)
        )
    identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=panel_path,
        spec=spec,
    )
    spec.update(identities)
    write_oos_release_manifest(
        release_path,
        workspace_root=root,
        spec=spec,
        identities=identities,
        threshold_path=threshold_path,
    )
    spec_path = root / "objects" / "research_protocol" / "metric_spec.json"
    write_json(spec_path, spec)
    bundle = run_metric_verifier(
        workspace_root=root,
        panel_path=panel_path,
        spec=spec,
    )
    release_cli_cases = run_release_cli_smoke(
        source_panel=panel_path,
        source_calendar=calendar_path,
        bound_spec=spec,
        decision_rules=decision_rules,
    )
    certificate = {
        "certificate_version": CERTIFICATE_VERSION,
        "report_id": report_id,
        "factor_id": factor_id,
        "claim_class": "risk_premium",
        "data_contract": {
            "is_window": "2020-01-01/2025-12-31",
            "universe": "metric verifier smoke universe",
            "universe_id": "metric_verifier_smoke_universe",
            "investability_mask_id": "metric_verifier_smoke_mask",
            "sample_frequency": "daily",
            "forward_return_horizon": "t+1 close to t+2 close",
            "forward_return_horizon_days": 1,
            "return_path_mode": "daily_one_period_forward_return",
            "holding_period_days": 1,
            "rebalance_frequency": "daily",
            "signal_timestamp": "t close",
            "execution_timestamp": "t+1 close",
            "label_start_timestamp": "t+1 close",
            "label_end_timestamp": "t+2 close",
            "forward_return_formula": (
                "label_end_price/label_start_price-1"
            ),
            "path_is_disjoint": True,
            "label_contract_version": (
                "factorforge_daily_return_label_contract_v1"
            ),
            "signal_date_column": "trade_date",
            "label_start_date_column": "label_start_date",
            "label_end_date_column": "label_end_date",
            "label_start_price_column": "label_start_price",
            "label_end_price_column": "label_end_price",
            "forward_return_column": "forward_return",
            "return_tolerance": 1e-12,
            "trading_calendar_ref": (
                "factorforge_data_access.trade_cal_csv"
            ),
            "trading_calendar_id": "cn_a_share_tushare_open_days",
            "cost_policy_id": "metric_verifier_smoke_cost_v1",
            "label_definition": "verified forward return",
            "return_convention": "simple_return",
            **identities,
            "oos_status": "released_once_for_final_evaluation",
            "evaluation_window_role": "OOS_FINAL",
            "oos_window": window_contract["oos_window"],
            "observed_start_date": identities["observed_start_date"],
            "observed_end_date": identities["observed_end_date"],
            "minimum_periods": 60,
            "search_frozen_before_oos_release": True,
            "oos_evidence_included": True,
            "oos_release_token_hash": "f" * 64,
            "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
            "oos_release_manifest_ref": str(release_path.relative_to(root)),
            "same_sample_for_all_required_metrics": True,
        },
        "metrics": bundle["metrics"],
        "evidence_bindings": bundle["evidence_bindings"],
        "threshold_registration": {
            "registered_before_evaluation": True,
            "registration_ref": str(threshold_path.relative_to(root)),
            "registration_sha256": sha256_file(threshold_path),
            "rule_set_sha256": stable_hash(decision_rules),
        },
        "decision_rules": decision_rules,
        "declared_verdict": "ACCEPT",
    }
    report = validate_factor_proof_certificate(
        certificate,
        workspace_root=root,
        expected_report_id=report_id,
        expected_factor_id=factor_id,
    )
    certificate_label_contract_tamper_blocked = True
    for field, value in (
        ("label_start_timestamp", "t close"),
        ("label_end_timestamp", "t+6 close"),
        ("forward_return_formula", "label_end_price-label_start_price"),
        ("path_is_disjoint", False),
        ("verification_scope", "smoke_only"),
        ("trading_calendar_snapshot_id", "forged_sparse_production"),
        ("trading_calendar_registry_git_commit", "0" * 40),
        ("trading_calendar_registry_git_blob", "0" * 40),
    ):
        tampered_certificate = deepcopy(certificate)
        tampered_certificate["data_contract"][field] = value
        tampered_report = validate_factor_proof_certificate(
            tampered_certificate,
            workspace_root=root,
            expected_report_id=report_id,
            expected_factor_id=factor_id,
        )
        certificate_label_contract_tamper_blocked = (
            certificate_label_contract_tamper_blocked
            and tampered_report["verdict"] == "BLOCK"
        )
    first_loss_drawdown, first_loss_recovery, _ = _drawdown_geometry(
        pd.Series([-0.2, 0.25], dtype=float)
    )
    first_period_loss_captured = (
        abs(first_loss_drawdown - (-0.2)) <= 1e-12
        and first_loss_recovery == 2
    )
    oos_date_mismatch_blocked = False
    bad_date_spec = deepcopy(spec)
    bad_date_spec["window_contract"]["observed_start_date"] = "2030-01-01"
    bad_date_spec["window_contract"]["observed_end_date"] = "2030-12-31"
    bad_date_identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=panel_path,
        spec=bad_date_spec,
    )
    bad_date_spec.update(bad_date_identities)
    try:
        _validate_spec(bad_date_spec, identities=bad_date_identities)
    except ValueError as exc:
        oos_date_mismatch_blocked = (
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_OBSERVED_DATE_MISMATCH"
            in str(exc)
        )
    formal_scope_required = False
    bad_scope_spec = deepcopy(spec)
    bad_scope_spec["report_id"] = "REAL_FACTOR_SMOKE"
    bad_scope_spec["verification_scope"] = "smoke_only"
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=bad_scope_spec,
        )
    except ValueError as exc:
        formal_scope_required = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_VERIFICATION_SCOPE_INVALID"
            in str(exc)
        )
    multi_period_path_blocked = False
    bad_horizon_spec = deepcopy(spec)
    bad_horizon_spec["window_contract"]["forward_return_horizon"] = (
        "t+1 close to t+6 close"
    )
    bad_horizon_spec["window_contract"]["forward_return_horizon_days"] = 5
    bad_horizon_spec["window_contract"]["label_end_timestamp"] = "t+6 close"
    bad_horizon_spec["label_contract"]["label_end_timestamp"] = "t+6 close"
    bad_horizon_spec["window_contract"]["path_is_disjoint"] = True
    bad_horizon_spec["portfolio"]["holding_period_days"] = 5
    bad_horizon_identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=panel_path,
        spec=bad_horizon_spec,
    )
    bad_horizon_spec.update(bad_horizon_identities)
    try:
        _validate_spec(
            bad_horizon_spec,
            identities=bad_horizon_identities,
        )
    except ValueError as exc:
        multi_period_path_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_MULTI_PERIOD_PORTFOLIO_PATH_REQUIRED"
            in str(exc)
        )
    execution_label_mismatch_blocked = False
    bad_timing_spec = deepcopy(spec)
    bad_timing_spec["window_contract"]["label_start_timestamp"] = "t close"
    bad_timing_spec["label_contract"]["label_start_timestamp"] = "t close"
    bad_timing_identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=panel_path,
        spec=bad_timing_spec,
    )
    bad_timing_spec.update(bad_timing_identities)
    try:
        _validate_spec(
            bad_timing_spec,
            identities=bad_timing_identities,
        )
    except ValueError as exc:
        execution_label_mismatch_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_EXECUTION_LABEL_START_MISMATCH"
            in str(exc)
        )
    five_day_column_masquerade_blocked = False
    masquerade_spec = deepcopy(spec)
    masquerade_spec["panel"]["forward_return_column"] = "fwd_ret_5d"
    masquerade_spec["label_contract"]["forward_return_column"] = "fwd_ret_5d"
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=masquerade_spec,
        )
    except ValueError as exc:
        five_day_column_masquerade_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_FORWARD_RETURN_RECONCILIATION_FAILED"
            in str(exc)
        )
    sparse_h5_masquerade_blocked = False
    sparse_calendar_dates = authority_calendar_dates[:307]
    sparse_rows: list[dict] = []
    for period_index in range(60):
        signal_index = period_index * 5
        for asset_index in range(10):
            forward_return = 0.005 + asset_index * 0.0005
            label_start_price = 100.0 + asset_index
            sparse_rows.append(
                {
                    "trade_date": sparse_calendar_dates[
                        signal_index
                    ].strftime("%Y-%m-%d"),
                    "ts_code": f"ASSET{asset_index:02d}",
                    "signal": float(asset_index),
                    "forward_return": forward_return,
                    "fwd_ret_5d": forward_return,
                    "label_start_date": sparse_calendar_dates[
                        signal_index + 1
                    ].strftime("%Y-%m-%d"),
                    "label_end_date": sparse_calendar_dates[
                        signal_index + 5
                    ].strftime("%Y-%m-%d"),
                    "label_start_price": label_start_price,
                    "label_end_price": label_start_price
                    * (1.0 + forward_return),
                    "size_control": float(asset_index - 5),
                }
            )
    sparse_panel_path = (
        root / "runs" / report_id / "sparse_h5_attack.csv"
    )
    pd.DataFrame(sparse_rows).to_csv(sparse_panel_path, index=False)
    sparse_h5_spec = deepcopy(spec)
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=sparse_panel_path,
            spec=sparse_h5_spec,
        )
    except ValueError as exc:
        sparse_h5_masquerade_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_LABEL_PERIOD_NOT_ONE_TRADING_DAY"
            in str(exc)
        )
    finally:
        os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
            calendar_path
        )
    self_declared_sparse_calendar_blocked = False
    self_declared_calendar_path = (
        calendar_authority_root / "self_declared_sparse_trade_cal.csv"
    )
    self_declared_dates = sparse_calendar_dates[::5]
    pd.DataFrame(
        {
            "exchange": ["SSE"] * len(self_declared_dates),
            "cal_date": [
                value.strftime("%Y%m%d")
                for value in self_declared_dates
            ],
            "is_open": ["1"] * len(self_declared_dates),
        }
    ).to_csv(self_declared_calendar_path, index=False)
    self_declared_rows: list[dict] = []
    for period_index in range(60):
        for asset_index in range(10):
            forward_return = 0.005 + asset_index * 0.0005
            label_start_price = 100.0 + asset_index
            self_declared_rows.append(
                {
                    "trade_date": self_declared_dates[
                        period_index
                    ].strftime("%Y-%m-%d"),
                    "ts_code": f"ASSET{asset_index:02d}",
                    "signal": float(asset_index),
                    "forward_return": forward_return,
                    "fwd_ret_5d": forward_return,
                    "label_start_date": self_declared_dates[
                        period_index + 1
                    ].strftime("%Y-%m-%d"),
                    "label_end_date": self_declared_dates[
                        period_index + 2
                    ].strftime("%Y-%m-%d"),
                    "label_start_price": label_start_price,
                    "label_end_price": label_start_price
                    * (1.0 + forward_return),
                    "size_control": float(asset_index - 5),
                }
            )
    self_declared_panel_path = (
        root / "runs" / report_id / "self_declared_sparse_h5.csv"
    )
    pd.DataFrame(self_declared_rows).to_csv(
        self_declared_panel_path,
        index=False,
    )
    self_declared_spec = deepcopy(sparse_h5_spec)
    self_declared_spec["label_contract"][
        "trading_calendar_sha256"
    ] = stable_hash(
        [
            value.strftime("%Y-%m-%d")
            for value in self_declared_dates
        ]
    )
    os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
        self_declared_calendar_path
    )
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=self_declared_panel_path,
            spec=self_declared_spec,
        )
    except ValueError as exc:
        self_declared_sparse_calendar_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_TRADING_CALENDAR_SNAPSHOT_UNTRUSTED"
            in str(exc)
        )
    finally:
        os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
            calendar_path
        )
    explicit_snapshot_id_required = False
    missing_snapshot_spec = deepcopy(spec)
    missing_snapshot_spec["label_contract"].pop(
        "trading_calendar_snapshot_id",
        None,
    )
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=missing_snapshot_spec,
        )
    except ValueError as exc:
        explicit_snapshot_id_required = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_TRADING_CALENDAR_SNAPSHOT_ID_INVALID"
            in str(exc)
        )
    git_anchor_required = False
    original_trust_commit = (
        metric_verifier_module.TRADING_CALENDAR_REGISTRY_TRUST_COMMIT
    )
    metric_verifier_module.TRADING_CALENDAR_REGISTRY_TRUST_COMMIT = "0" * 40
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=panel_path,
            spec=spec,
        )
    except ValueError as exc:
        git_anchor_required = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_TRADING_CALENDAR_TRUST_ANCHOR_MISSING"
            in str(exc)
        )
    finally:
        metric_verifier_module.TRADING_CALENDAR_REGISTRY_TRUST_COMMIT = (
            original_trust_commit
        )
    missing_label_provenance_blocked = False
    missing_label_panel = root / "runs" / report_id / "missing_labels.csv"
    pd.read_csv(panel_path).drop(
        columns=[
            "label_start_date",
            "label_end_date",
            "label_start_price",
            "label_end_price",
        ]
    ).to_csv(missing_label_panel, index=False)
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=missing_label_panel,
            spec=spec,
        )
    except ValueError as exc:
        missing_label_provenance_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_PANEL_COLUMNS_MISSING"
            in str(exc)
        )
    label_end_semantic_tamper_blocked = False
    bad_label_end_spec = deepcopy(spec)
    bad_label_end_spec["window_contract"][
        "label_end_timestamp"
    ] = "t+6 close"
    bad_label_end_identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=panel_path,
        spec=bad_label_end_spec,
    )
    bad_label_end_spec.update(bad_label_end_identities)
    try:
        _validate_spec(
            bad_label_end_spec,
            identities=bad_label_end_identities,
        )
    except ValueError as exc:
        label_end_semantic_tamper_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_LABEL_CONTRACT_MAPPING_INVALID"
            in str(exc)
        )
    return_formula_tamper_blocked = False
    bad_formula_spec = deepcopy(spec)
    bad_formula_spec["window_contract"]["forward_return_formula"] = (
        "label_end_price-label_start_price"
    )
    bad_formula_identities = metric_verifier_identities(
        workspace_root=root,
        panel_path=panel_path,
        spec=bad_formula_spec,
    )
    bad_formula_spec.update(bad_formula_identities)
    try:
        _validate_spec(
            bad_formula_spec,
            identities=bad_formula_identities,
        )
    except ValueError as exc:
        return_formula_tamper_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_MULTI_PERIOD_PORTFOLIO_PATH_REQUIRED"
            in str(exc)
        )
    evaluation_contract_tamper_blocked = False
    tampered_cost_spec = deepcopy(spec)
    tampered_cost_spec["portfolio"]["cost_bps_per_turnover"] += 1.0
    try:
        run_metric_verifier(
            workspace_root=root,
            panel_path=panel_path,
            spec=tampered_cost_spec,
        )
    except ValueError as exc:
        evaluation_contract_tamper_blocked = (
            "evaluation_contract_hash" in str(exc)
        )
    tied_panel = pd.DataFrame(
        {
            "trade_date": ["2026-01-05"] * 10,
            "signal": [1.0] * 10,
            "forward_return": [float(index) for index in range(10)],
        }
    )
    tied_bucket_blocked = False
    try:
        _bucket_returns(
            tied_panel,
            date_col="trade_date",
            signal_col="signal",
            return_col="forward_return",
            bucket_count=5,
        )
    except ValueError as exc:
        tied_bucket_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_BUCKET_TIES_UNRESOLVED"
            in str(exc)
        )
    geometric_gate_bound = REQUIRED_DECISION_PATHS["long_end"] == {
        "metrics.long_end.net_geometric_return_annual"
    }
    alternating_returns = pd.Series([0.9, -0.8] * 30, dtype=float)
    arithmetic_annual = float(alternating_returns.mean() * 252)
    geometric_annual = float(
        (1.0 + alternating_returns).prod()
        ** (252 / len(alternating_returns))
        - 1.0
    )
    volatility_trap_exposed = arithmetic_annual > 0 and geometric_annual < 0
    post_release_threshold_blocked = False
    try:
        write_threshold_registration(
            root
            / "objects"
            / "research_protocol"
            / "thresholds_after_release.json",
            workspace_root=root,
            spec=spec,
            decision_rules=decision_rules,
        )
    except ValueError as exc:
        post_release_threshold_blocked = (
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_AFTER_OOS_BINDING"
            in str(exc)
        )
    invalid_rule_replay_blocked = False
    original_threshold_text = threshold_path.read_text(encoding="utf-8")
    original_release_text = release_path.read_text(encoding="utf-8")
    tampered_threshold = json.loads(original_threshold_text)
    tampered_threshold["decision_rules"] = [
        rule
        for rule in tampered_threshold["decision_rules"]
        if not str(rule.get("metric_path") or "").startswith(
            ("metrics.fama_macbeth.", "metrics.bucket_monotonicity.")
        )
    ]
    tampered_threshold["rule_set_sha256"] = stable_hash(
        tampered_threshold["decision_rules"]
    )
    write_json(threshold_path, tampered_threshold)
    tampered_release = json.loads(original_release_text)
    tampered_release["threshold_registration_sha256"] = sha256_file(
        threshold_path
    )
    tampered_release["release_manifest_sha256"] = stable_hash(
        {
            key: value
            for key, value in tampered_release.items()
            if key != "release_manifest_sha256"
        }
    )
    write_json(release_path, tampered_release)
    try:
        run_metric_verifier(
            workspace_root=root,
            panel_path=panel_path,
            spec=spec,
        )
    except ValueError as exc:
        invalid_rule_replay_blocked = (
            "BLOCK_FACTORFORGE_RESEARCH_RELEASE_THRESHOLD_RULE_COVERAGE_MISSING"
            in str(exc)
        )
    threshold_path.write_text(original_threshold_text, encoding="utf-8")
    release_path.write_text(original_release_text, encoding="utf-8")
    release_trust_identity_tamper_blocked = True
    for field, value in (
        ("verification_scope", "smoke_only"),
        ("trading_calendar_snapshot_id", "forged_sparse_production"),
        ("trading_calendar_registry_git_commit", "0" * 40),
        ("trading_calendar_registry_git_blob", "0" * 40),
    ):
        identity_tampered_release = json.loads(original_release_text)
        identity_tampered_release[field] = value
        identity_tampered_release["release_manifest_sha256"] = stable_hash(
            {
                key: item
                for key, item in identity_tampered_release.items()
                if key != "release_manifest_sha256"
            }
        )
        write_json(release_path, identity_tampered_release)
        try:
            run_metric_verifier(
                workspace_root=root,
                panel_path=panel_path,
                spec=spec,
            )
        except ValueError as exc:
            release_trust_identity_tamper_blocked = (
                release_trust_identity_tamper_blocked
                and "BLOCK_FACTORFORGE_RESEARCH_RELEASE_MANIFEST_BINDING_MISMATCH"
                in str(exc)
                and field in str(exc)
            )
        else:
            release_trust_identity_tamper_blocked = False
    release_path.write_text(original_release_text, encoding="utf-8")
    forged_certificate = deepcopy(certificate)
    forged_reference = forged_certificate["evidence_bindings"]["ic"]
    original_evidence_path = root / forged_reference["path"]
    forged_evidence = json.loads(
        original_evidence_path.read_text(encoding="utf-8")
    )
    forged_evidence["metric_payload"]["mean"] = 0.999999
    forged_evidence_path = (
        root / "objects" / "evidence" / "forged_metric_evidence.json"
    )
    write_json(forged_evidence_path, forged_evidence)
    forged_reference["path"] = str(forged_evidence_path.relative_to(root))
    forged_reference["sha256"] = sha256_file(forged_evidence_path)
    forged_report = validate_factor_proof_certificate(
        forged_certificate,
        workspace_root=root,
        expected_report_id=report_id,
        expected_factor_id=factor_id,
    )
    forged_evidence_blocked = any(
        "BLOCK_FACTORFORGE_METRIC_EVIDENCE_REPLAY_MISMATCH:metric_payload"
        in reason
        for reason in forged_report.get("block_reasons") or []
    )
    calendar_tamper_blocked = False
    original_calendar_text = calendar_path.read_text(encoding="utf-8")
    tampered_calendar = pd.read_csv(calendar_path)
    tampered_calendar = tampered_calendar.iloc[:-1]
    tampered_calendar.to_csv(calendar_path, index=False)
    try:
        run_metric_verifier(
            workspace_root=root,
            panel_path=panel_path,
            spec=spec,
        )
    except ValueError as exc:
        calendar_tamper_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_TRADING_CALENDAR_HASH_MISMATCH"
            in str(exc)
        )
    calendar_path.write_text(original_calendar_text, encoding="utf-8")
    forged_registry_blocked = False
    forged_registry_path = (
        calendar_authority_root / "forged_trading_calendar_registry.json"
    )
    forged_registry = json.loads(
        TRADING_CALENDAR_REGISTRY_PATH.read_text(encoding="utf-8")
    )
    forged_registry["snapshots"].append(
        {
            "date_count": len(self_declared_dates),
            "date_max": self_declared_dates[-1].strftime("%Y-%m-%d"),
            "date_min": self_declared_dates[0].strftime("%Y-%m-%d"),
            "open_dates_sha256": self_declared_spec["label_contract"][
                "trading_calendar_sha256"
            ],
            "raw_file_sha256": sha256_file(self_declared_calendar_path),
            "scope": "production",
            "snapshot_id": "forged_sparse_production",
        }
    )
    write_json(forged_registry_path, forged_registry)
    forged_registry_spec = deepcopy(self_declared_spec)
    forged_registry_spec["label_contract"][
        "trading_calendar_registry_sha256"
    ] = sha256_file(forged_registry_path)
    forged_registry_spec["label_contract"][
        "trading_calendar_snapshot_id"
    ] = "forged_sparse_production"
    original_registry_path = metric_verifier_module.TRADING_CALENDAR_REGISTRY_PATH
    metric_verifier_module.TRADING_CALENDAR_REGISTRY_PATH = forged_registry_path
    os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
        self_declared_calendar_path
    )
    try:
        metric_verifier_identities(
            workspace_root=root,
            panel_path=self_declared_panel_path,
            spec=forged_registry_spec,
        )
    except ValueError as exc:
        forged_registry_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_TRADING_CALENDAR_REGISTRY_DIVERGED"
            in str(exc)
        )
    finally:
        metric_verifier_module.TRADING_CALENDAR_REGISTRY_PATH = (
            original_registry_path
        )
        os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(calendar_path)
    changed_panel = pd.read_csv(panel_path)
    changed_panel.loc[0, "forward_return"] += 0.01
    changed_panel.loc[0, "label_end_price"] = (
        changed_panel.loc[0, "label_start_price"]
        * (1.0 + changed_panel.loc[0, "forward_return"])
    )
    changed_panel.to_csv(panel_path, index=False)
    changed_data_blocked = False
    try:
        run_metric_verifier(
            workspace_root=root,
            panel_path=panel_path,
            spec=spec,
        )
    except ValueError as exc:
        changed_data_blocked = (
            "BLOCK_FACTORFORGE_METRIC_VERIFIER_DATASET_HASH_MISMATCH"
            in str(exc)
        )
    ok = (
        report["verdict"] == "ACCEPT"
        and bundle["verifier_status"] == "PASS"
        and forged_evidence_blocked
        and first_period_loss_captured
        and changed_data_blocked
        and oos_date_mismatch_blocked
        and formal_scope_required
        and multi_period_path_blocked
        and execution_label_mismatch_blocked
        and five_day_column_masquerade_blocked
        and sparse_h5_masquerade_blocked
        and self_declared_sparse_calendar_blocked
        and explicit_snapshot_id_required
        and git_anchor_required
        and missing_label_provenance_blocked
        and label_end_semantic_tamper_blocked
        and return_formula_tamper_blocked
        and certificate_label_contract_tamper_blocked
        and calendar_tamper_blocked
        and forged_registry_blocked
        and release_trust_identity_tamper_blocked
        and evaluation_contract_tamper_blocked
        and threshold_idempotent
        and threshold_overwrite_blocked
        and tied_bucket_blocked
        and geometric_gate_bound
        and volatility_trap_exposed
        and post_release_threshold_blocked
        and invalid_rule_replay_blocked
        and all(release_cli_cases.values())
        and {
            "ic",
            "icir",
            "volatility_cost",
            "transaction_cost",
            "drawdown",
            "long_end",
            "fama_macbeth",
            "bucket_monotonicity",
        }.issubset(bundle["metrics"])
    )
    print(
        json.dumps(
            {
                "verdict": "ACCEPT" if ok else "BLOCK",
                "factor_proof_verdict": report["verdict"],
                "metric_families": sorted(bundle["metrics"]),
                "changed_panel_hash_blocked": changed_data_blocked,
                "hand_authored_metric_evidence_blocked": forged_evidence_blocked,
                "first_period_loss_in_drawdown": first_period_loss_captured,
                "actual_oos_dates_bound": oos_date_mismatch_blocked,
                "formal_verification_scope_required": formal_scope_required,
                "multi_period_forward_return_path_blocked": (
                    multi_period_path_blocked
                ),
                "execution_label_start_mismatch_blocked": (
                    execution_label_mismatch_blocked
                ),
                "five_day_column_masquerade_blocked": (
                    five_day_column_masquerade_blocked
                ),
                "sparse_h5_masquerade_blocked": (
                    sparse_h5_masquerade_blocked
                ),
                "self_declared_sparse_calendar_blocked": (
                    self_declared_sparse_calendar_blocked
                ),
                "explicit_calendar_snapshot_id_required": (
                    explicit_snapshot_id_required
                ),
                "calendar_registry_git_anchor_required": git_anchor_required,
                "missing_label_provenance_blocked": (
                    missing_label_provenance_blocked
                ),
                "label_end_semantic_tamper_blocked": (
                    label_end_semantic_tamper_blocked
                ),
                "return_formula_tamper_blocked": (
                    return_formula_tamper_blocked
                ),
                "certificate_label_contract_tamper_blocked": (
                    certificate_label_contract_tamper_blocked
                ),
                "trading_calendar_tamper_blocked": (
                    calendar_tamper_blocked
                ),
                "forged_production_registry_blocked": (
                    forged_registry_blocked
                ),
                "release_trust_identity_tamper_blocked": (
                    release_trust_identity_tamper_blocked
                ),
                "evaluation_contract_tamper_blocked": (
                    evaluation_contract_tamper_blocked
                ),
                "threshold_registration_idempotent": threshold_idempotent,
                "threshold_registration_overwrite_blocked": (
                    threshold_overwrite_blocked
                ),
                "tie_safe_bucket_gate": tied_bucket_blocked,
                "geometric_long_end_gate_bound": geometric_gate_bound,
                "arithmetic_positive_geometric_negative_exposed": (
                    volatility_trap_exposed
                ),
                "post_release_threshold_registration_blocked": (
                    post_release_threshold_blocked
                ),
                "invalid_threshold_rule_replay_blocked": (
                    invalid_rule_replay_blocked
                ),
                "release_chain_cli": release_cli_cases,
                "production_research_started": False,
                "worker_started": False,
                "clean_data_mutated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if not ok:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    print("FACTORFORGE_METRIC_VERIFIER_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
