#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_evidence import sha256_file
from factor_factory.research_release import (
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)
from factor_factory.metric_verifier import (
    TRADING_CALENDAR_REGISTRY_PATH,
    TRADING_CALENDAR_REGISTRY_TRUST_BLOB,
    TRADING_CALENDAR_REGISTRY_TRUST_COMMIT,
    metric_verifier_identities,
    run_metric_verifier,
    verifier_source_sha256,
)
from factor_factory.research_proof import (
    CERTIFICATE_VERSION,
    stable_hash,
    validate_factor_proof_certificate,
)

FIXTURE_SEQUENCE = 0


def write_evidence(
    root: Path,
    name: str,
    *,
    metric_payload: dict[str, Any],
    metric: str | None = None,
    dataset_snapshot_hash: str = "d" * 64,
    window_hash: str = "e" * 64,
    verifier_id: str = "factorforge_step4_metric_verifier_v2",
    threshold_registration_sha256: str,
    threshold_rule_set_sha256: str,
) -> dict[str, Any]:
    path = root / "objects" / "evidence" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    metric = metric or name
    path.write_text(
        json.dumps(
            {
                "verifier_contract_version": "factorforge_metric_verifier_report_v2",
                "metric": metric,
                "metric_payload": metric_payload,
                "verifier_id": verifier_id,
                "verifier_status": "PASS",
                "verifier_source_sha256": verifier_source_sha256(),
                "dataset_snapshot_hash": dataset_snapshot_hash,
                "window_hash": window_hash,
                "threshold_registration_sha256": (
                    threshold_registration_sha256
                ),
                "threshold_rule_set_sha256": threshold_rule_set_sha256,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "path": str(path.relative_to(root)),
        "metric": metric,
        "sha256": sha256_file(path),
        "dataset_snapshot_hash": dataset_snapshot_hash,
        "window_hash": window_hash,
        "verifier_id": verifier_id,
        "verifier_status": "PASS",
        "verifier_source_sha256": verifier_source_sha256(),
        "threshold_registration_sha256": threshold_registration_sha256,
        "threshold_rule_set_sha256": threshold_rule_set_sha256,
    }


def rewrite_threshold_registration(
    root: Path,
    certificate: dict[str, Any],
) -> None:
    registration = certificate["threshold_registration"]
    decision_rules = certificate["decision_rules"]
    rule_set_sha256 = stable_hash(decision_rules)
    data_contract = certificate["data_contract"]
    registration_path = root / registration["registration_ref"]
    registration_path.write_text(
        json.dumps(
            {
                "version": "factorforge_threshold_registration_v2",
                "registration_status": "LOCKED",
                "report_id": certificate["report_id"],
                "factor_id": certificate["factor_id"],
                "claim_class": certificate["claim_class"],
                "window_hash": data_contract["window_hash"],
                "evaluation_contract_hash": data_contract[
                    "evaluation_contract_hash"
                ],
                "label_contract_hash": data_contract[
                    "label_contract_hash"
                ],
                "registered_before_evaluation": True,
                "registration_sequence": 20,
                "search_trial_ledger_ref": data_contract[
                    "search_trial_ledger_ref"
                ],
                "search_trial_ledger_sha256": sha256_file(
                    root / data_contract["search_trial_ledger_ref"]
                ),
                "rule_set_sha256": rule_set_sha256,
                "decision_rules": decision_rules,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    registration["rule_set_sha256"] = rule_set_sha256
    registration["registration_sha256"] = sha256_file(registration_path)


def valid_certificate(
    root: Path,
    *,
    claim_class: str,
    report_id: str = "FACTOR_PROOF_SMOKE",
    factor_id: str = "SMOKE_FACTOR",
) -> dict[str, Any]:
    global FIXTURE_SEQUENCE
    FIXTURE_SEQUENCE += 1
    fixture_id = f"{claim_class}_{FIXTURE_SEQUENCE:03d}"
    panel_path = (
        root
        / "runs"
        / report_id
        / fixture_id
        / "frozen_oos_panel.csv"
    )
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
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
        authority_calendar_dates.searchsorted(pd.Timestamp("2025-01-06"))
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
        slope = 0.0015 + 0.00025 * math.sin(date_index)
        label_start_date = calendar_dates[date_index + 1].strftime(
            "%Y-%m-%d"
        )
        label_end_date = calendar_dates[date_index + 2].strftime(
            "%Y-%m-%d"
        )
        for asset_index in range(12):
            signal = float(asset_index - 5.5)
            control = float((asset_index * 5 + date_index * 2) % 11 - 5)
            noise = 0.0015 * math.sin(
                (date_index + 1) * (asset_index + 1)
            )
            forward_return = slope * signal + 0.00005 * control + noise
            label_start_price = 100.0 + asset_index + date_index * 0.1
            rows.append(
                {
                    "trade_date": date_value.strftime("%Y-%m-%d"),
                    "asset": f"A{asset_index:03d}",
                    "signal": signal + 0.02 * math.cos(date_index + asset_index),
                    "forward_return": forward_return,
                    "label_start_date": label_start_date,
                    "label_end_date": label_end_date,
                    "label_start_price": label_start_price,
                    "label_end_price": label_start_price
                    * (1.0 + forward_return),
                    "size_control": control,
                }
            )
    pd.DataFrame(rows).to_csv(panel_path, index=False)
    calendar_path = (
        Path("/tmp/factorforge_data_api_calendar_authority_proof_smoke")
        / f"trade_cal__{report_id}__{fixture_id}.csv"
    )
    calendar_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(trusted_calendar_fixture, calendar_path)
    os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(
        calendar_path
    )
    ledger_path = (
        root
        / "objects"
        / "research_protocol"
        / f"search_trial_ledger__{report_id}__{fixture_id}.json"
    )
    write_search_trial_ledger(
        ledger_path,
        report_id=report_id,
        factor_id=factor_id,
        trials=[{"trial_id": "trial_001", "decision": "selected"}],
        candidate_space={"claim_class": claim_class},
        selected_hypothesis={"factor_id": factor_id},
    )
    release_path = (
        root
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{report_id}__{fixture_id}.json"
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
        "universe_id": "factor_proof_smoke_universe",
        "investability_mask_id": "factor_proof_smoke_mask",
        "search_frozen_before_oos_release": True,
        "return_convention": "simple_return",
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "oos_release_manifest_ref": str(release_path.relative_to(root)),
    }
    spec: dict[str, Any] = {
        "version": "factorforge_metric_verifier_spec_v2",
        "verification_scope": "production",
        "report_id": report_id,
        "factor_id": factor_id,
        "claim_class": claim_class,
        "cost_policy_id": "cost_policy_smoke_v1",
        "panel": {
            "date_column": "trade_date",
            "asset_column": "asset",
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
            "cost_bps_per_turnover": 0.0,
            "other_annual_costs": 0.0,
            "cost_scope": "zero-cost smoke boundary",
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
            "rule_id": "net_return_after_cost_floor",
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
            "rule_id": "long_net_floor",
            "metric_path": "metrics.long_end.net_geometric_return_annual",
            "operator": ">=",
            "threshold": 0.0,
            "on_fail": "REJECT",
        },
    ]
    if claim_class == "risk_premium":
        decision_rules.extend(
            [
                {
                    "rule_id": "fama_macbeth_tstat_floor",
                    "metric_path": "metrics.fama_macbeth.lambda_tstat",
                    "operator": ">=",
                    "threshold": 0.0,
                    "on_fail": "REJECT",
                },
                {
                    "rule_id": "bucket_monotonicity_floor",
                    "metric_path": "metrics.bucket_monotonicity.monotonicity_score",
                    "operator": ">=",
                    "threshold": 0.5,
                    "on_fail": "INCONCLUSIVE",
                },
            ]
        )
    rule_set_sha256 = stable_hash(decision_rules)
    registration_path = (
        root
        / "objects"
        / "research_protocol"
        / f"thresholds_smoke__{report_id}__{fixture_id}.json"
    )
    spec["threshold_registration_ref"] = str(
        registration_path.relative_to(root)
    )
    write_threshold_registration(
        registration_path,
        workspace_root=root,
        spec=spec,
        decision_rules=decision_rules,
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
        threshold_path=registration_path,
    )
    bundle = run_metric_verifier(
        workspace_root=root,
        panel_path=panel_path,
        spec=spec,
    )
    metrics = deepcopy(bundle["metrics"])
    if claim_class != "risk_premium":
        metrics["bucket_monotonicity"] = {
            "bucket_count": 5,
            "required_for_acceptance": False,
            "evidence_role": "diagnostic_evidence",
            "monotonicity_score": 0.75,
            "adjacent_pairs_total": 4,
            "adjacent_pairs_violated": 1,
            "expected_direction": "ascending",
            "bucket_returns": [0.01, 0.02, 0.03, 0.025, 0.05],
        }
    return {
        "certificate_version": CERTIFICATE_VERSION,
        "report_id": report_id,
        "factor_id": factor_id,
        "claim_class": claim_class,
        "data_contract": {
            "is_window": "2020-01-01/2024-12-31",
            "universe": "A-share investable core",
            "universe_id": "factor_proof_smoke_universe",
            "investability_mask_id": "factor_proof_smoke_mask",
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
            "cost_policy_id": "cost_policy_smoke_v1",
            "label_definition": "net investable forward return",
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
        "metrics": metrics,
        "evidence_bindings": bundle["evidence_bindings"],
        "threshold_registration": {
            "registered_before_evaluation": True,
            "registration_ref": str(registration_path.relative_to(root)),
            "registration_sha256": sha256_file(registration_path),
            "rule_set_sha256": rule_set_sha256,
        },
        "decision_rules": decision_rules,
        "declared_verdict": "ACCEPT",
    }


def has(report: dict[str, Any], token: str) -> bool:
    return any(token in reason for reason in report.get("block_reasons") or [])


def main() -> int:
    root = Path("/tmp/factorforge_factor_proof_smoke")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    cases: dict[str, dict[str, Any]] = {}

    info = valid_certificate(root, claim_class="information_rent")
    report = validate_factor_proof_certificate(info, workspace_root=root)
    cases["information_rent_valid"] = {"ok": report["verdict"] == "ACCEPT", "report": report}

    bad = deepcopy(info)
    bad["data_contract"]["oos_status"] = "sealed"
    bad["data_contract"]["evaluation_window_role"] = "IS_CONFIRMATION"
    bad["data_contract"]["oos_evidence_included"] = False
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["accept_requires_one_time_oos_release"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_ACCEPT_WITHOUT_OOS_RELEASE",
        ),
        "report": report,
    }

    bad = deepcopy(info)
    bad["data_contract"]["execution_timestamp"] = "t+1 open"
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["certificate_window_contract_must_match_replayed_spec"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_WINDOW_CONTRACT_MISMATCH:"
            "ic:execution_timestamp",
        ),
        "report": report,
    }

    bad = deepcopy(info)
    bad["metrics"]["bucket_monotonicity"]["required_for_acceptance"] = True
    bad["metrics"]["bucket_monotonicity"]["evidence_role"] = "promotion_gate_evidence"
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["monotonicity_not_universal_gate"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_MONOTONICITY_GATE_OUTSIDE_RISK_PREMIUM"),
        "report": report,
    }

    risk = valid_certificate(
        root,
        claim_class="risk_premium",
        report_id="FACTOR_PROOF_RISK_SMOKE",
    )
    bad = deepcopy(risk)
    bad["metrics"].pop("fama_macbeth")
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["risk_premium_requires_fama_macbeth"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_RISK_PREMIUM_FAMA_MACBETH_MISSING"),
        "report": report,
    }

    bad = deepcopy(risk)
    bad["metrics"].pop("bucket_monotonicity")
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["risk_premium_requires_quintile_or_decile"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_MISSING"),
        "report": report,
    }

    report = validate_factor_proof_certificate(risk, workspace_root=root)
    cases["risk_premium_valid"] = {"ok": report["verdict"] == "ACCEPT", "report": report}

    bad = deepcopy(risk)
    bad["metrics"]["bucket_monotonicity"]["monotonicity_score"] = 0.5
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["risk_premium_monotonicity_reconciles_from_bucket_returns"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_RISK_PREMIUM_MONOTONICITY_SCORE_MISMATCH",
        ),
        "report": report,
    }

    bad = deepcopy(info)
    bad["metrics"]["icir"]["value"] = 9.0
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["icir_reconciliation"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_FACTOR_PROOF_ICIR_RECONCILIATION_FAILED"),
        "report": report,
    }

    bad = deepcopy(info)
    bad["metrics"]["transaction_cost"]["modeled_cost_annual"] = 0.01
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["transaction_cost_reconciliation"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_TRANSACTION_COST_MODEL_RECONCILIATION_FAILED"),
        "report": report,
    }

    bad = deepcopy(info)
    bad["metrics"]["volatility_cost"]["half_variance_benchmark"] = 0.5
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["volatility_cost_reconciliation"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_HALF_VARIANCE_BENCHMARK_RECONCILIATION_FAILED"),
        "report": report,
    }

    bad = deepcopy(info)
    bad["declared_verdict"] = "REJECT"
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["declared_verdict_reconciles"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_FACTOR_PROOF_VERDICT_MISMATCH"),
        "report": report,
    }

    bad = deepcopy(info)
    bad["threshold_registration"]["registered_before_evaluation"] = False
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["post_hoc_thresholds_block"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLDS_POST_HOC"),
        "report": report,
    }

    bad = deepcopy(info)
    bad["evidence_bindings"]["ic"]["sha256"] = "0" * 64
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["evidence_hash_mismatch_blocks"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE:ic_SHA256_MISMATCH"),
        "report": report,
    }

    bad = deepcopy(info)
    bad["evidence_bindings"]["ic"]["path"] = "objects/evidence/does_not_exist.json"
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["nonexistent_evidence_blocks"] = {
        "ok": has(report, "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE:ic_PATH_MISSING"),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["evidence_bindings"]["ic"]["metric"] = "transaction_cost"
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["metric_evidence_binding_blocks"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_METRIC_MISMATCH:ic",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["evidence_bindings"]["ic"] = write_evidence(
        root,
        "ic_other_window",
        metric_payload=bad["metrics"]["ic"],
        metric="ic",
        window_hash="a" * 64,
        threshold_registration_sha256=bad["threshold_registration"][
            "registration_sha256"
        ],
        threshold_rule_set_sha256=bad["threshold_registration"][
            "rule_set_sha256"
        ],
    )
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["cross_window_evidence_splice_blocks"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_WINDOW_MISMATCH:ic",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["metrics"]["ic"]["mean"] = 0.03
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["evidence_metric_values_cannot_be_substituted"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_VALUE_MISMATCH:ic",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["evidence_bindings"]["ic"] = write_evidence(
        root,
        "ic_untrusted_verifier",
        metric_payload=bad["metrics"]["ic"],
        metric="ic",
        verifier_id="self_asserted_researcher_verifier",
        threshold_registration_sha256=bad["threshold_registration"][
            "registration_sha256"
        ],
        threshold_rule_set_sha256=bad["threshold_registration"][
            "rule_set_sha256"
        ],
    )
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["untrusted_metric_verifier_blocks"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE:ic_VERIFIER_UNTRUSTED",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["factor_id"] = "OTHER_FACTOR"
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["threshold_registration_cannot_cross_factor_identity"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_THRESHOLD_REGISTRATION_IDENTITY_MISMATCH:factor_id",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["decision_rules"][0]["threshold"] = 0.019
    rewrite_threshold_registration(root, bad)
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["post_evidence_threshold_rewrite_breaks_evidence_binding"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_THRESHOLD_REGISTRATION_MISMATCH:ic",
        )
        and has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_EVIDENCE_THRESHOLD_RULE_SET_MISMATCH:ic",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["decision_rules"][0]["threshold"] = -1.0
    rewrite_threshold_registration(root, bad)
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["negative_ic_acceptance_threshold_is_forbidden"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_GUARDRAIL_INVALID:ic_floor",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["claim_class"] = "unknown"
    rewrite_threshold_registration(root, bad)
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["ambiguous_claim_class_cannot_accept"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_ACCEPT_WITH_AMBIGUOUS_CLAIM_CLASS",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["metrics"]["fama_macbeth"] = {
        "applicable": True,
        "lambda_mean": 0.003,
        "lambda_tstat": 2.3,
        "period_count": 100,
        "newey_west_lags": 5,
        "cross_sectional_regression": "forward_return ~ signal + controls",
        "exposure_timing": "signal at t close",
        "return_horizon": "t+1 close to t+2 close",
        "return_horizon_days": 1,
        "controls": ["size", "beta", "liquidity"],
        "required_for_acceptance": True,
        "evidence_role": "promotion_gate_evidence",
    }
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["fama_macbeth_not_non_risk_promotion_gate"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FAMA_MACBETH_GATE_OUTSIDE_RISK_PREMIUM",
        )
        and has(
            report,
            "BLOCK_FACTORFORGE_FAMA_MACBETH_PROMOTION_ROLE_OUTSIDE_RISK_PREMIUM",
        ),
        "report": report,
    }

    diagnostic = valid_certificate(root, claim_class="information_rent")
    diagnostic["metrics"]["fama_macbeth"] = {
        "applicable": True,
        "lambda_mean": 0.003,
        "lambda_tstat": 2.3,
        "period_count": 100,
        "newey_west_lags": 5,
        "cross_sectional_regression": "forward_return ~ signal + controls",
        "exposure_timing": "signal at t close",
        "return_horizon": "t+1 close to t+2 close",
        "return_horizon_days": 1,
        "controls": ["size", "beta", "liquidity"],
        "required_for_acceptance": False,
        "evidence_role": "diagnostic_evidence",
    }
    report = validate_factor_proof_certificate(diagnostic, workspace_root=root)
    cases["non_risk_fama_macbeth_diagnostic_allowed"] = {
        "ok": report["verdict"] == "ACCEPT",
        "report": report,
    }

    bad = valid_certificate(root, claim_class="risk_premium")
    bad["metrics"]["fama_macbeth"]["required_for_acceptance"] = False
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["risk_premium_fama_macbeth_must_be_required"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_RISK_PREMIUM_FAMA_MACBETH_NOT_REQUIRED",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    for rule in bad["decision_rules"]:
        if rule.get("rule_id") == "ic_floor":
            rule["metric_path"] = "metrics.ic.period_count"
    rewrite_threshold_registration(root, bad)
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["non_decisive_family_field_cannot_satisfy_rule_coverage"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_COVERAGE_MISSING:ic",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["decision_rules"] = [
        rule
        for rule in bad["decision_rules"]
        if not str(rule.get("metric_path")).startswith("metrics.icir.")
    ]
    registration = bad["threshold_registration"]
    rewrite_threshold_registration(root, bad)
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["every_required_metric_needs_preregistered_rule"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_FACTOR_PROOF_DECISION_RULE_COVERAGE_MISSING:icir",
        ),
        "report": report,
    }

    bad = valid_certificate(root, claim_class="information_rent")
    bad["decision_rules"].append(
        {
            "rule_id": "invalid_non_risk_monotonicity_gate",
            "metric_path": "metrics.bucket_monotonicity.monotonicity_score",
            "operator": ">=",
            "threshold": 0.5,
            "on_fail": "REJECT",
        }
    )
    registration = bad["threshold_registration"]
    rewrite_threshold_registration(root, bad)
    report = validate_factor_proof_certificate(bad, workspace_root=root)
    cases["non_risk_claim_cannot_gate_on_monotonicity"] = {
        "ok": has(
            report,
            "BLOCK_FACTORFORGE_RISK_PREMIUM_RULE_OUTSIDE_RISK_PREMIUM",
        ),
        "report": report,
    }

    failed = [name for name, row in cases.items() if not row.get("ok")]
    print(
        json.dumps(
            {"verdict": "ACCEPT" if not failed else "BLOCK", "failed": failed, "cases": cases},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    if failed:
        return 1
    print("FACTORFORGE_FACTOR_PROOF_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
