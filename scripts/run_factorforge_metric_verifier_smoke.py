#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.metric_verifier import (
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
    trade_dates = pd.bdate_range("2026-01-05", periods=64)
    for date_index, date_value in enumerate(trade_dates):
        trade_date = date_value.strftime("%Y-%m-%d")
        slope = 0.0015 + 0.00025 * math.sin(date_index)
        for asset_index in range(10):
            signal = float(asset_index - 4.5)
            size_control = float((asset_index * 3 + date_index) % 7 - 3)
            residual = 0.0015 * math.cos(
                (date_index + 1) * (asset_index + 2)
            )
            rows.append(
                {
                    "trade_date": trade_date,
                    "ts_code": f"ASSET{asset_index:02d}",
                    "signal": signal + 0.05 * math.sin(date_index + asset_index),
                    "forward_return": (
                        slope * signal
                        + 0.00015 * size_control
                        + residual
                    ),
                    "size_control": size_control,
                }
            )
    pd.DataFrame(rows).to_csv(panel_path, index=False)
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
        "forward_return_horizon": "t+1 close-to-close",
        "sample_frequency": "daily",
        "signal_timestamp": "t close",
        "execution_timestamp": "t+1 close",
        "universe_id": "metric_verifier_smoke_universe",
        "investability_mask_id": "metric_verifier_smoke_mask",
        "search_frozen_before_oos_release": True,
        "return_convention": "simple_return",
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "oos_release_manifest_ref": str(release_path.relative_to(root)),
    }
    spec = {
        "version": "factorforge_metric_verifier_spec_v1",
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
        "window_contract": window_contract,
        "portfolio": {
            "annualization_factor": 252,
            "long_quantile": 0.2,
            "cost_bps_per_turnover": 20.0,
            "other_annual_costs": 0.001,
            "cost_scope": "commission and deterministic slippage proxy",
            "execution_assumption": "verified t+1 close forward return",
            "rebalance_frequency": "daily",
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
            "forward_return_horizon": "t+1 close-to-close",
            "signal_timestamp": "t close",
            "execution_timestamp": "t+1 close",
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
    changed_panel = pd.read_csv(panel_path)
    changed_panel.loc[0, "forward_return"] += 1.0
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
