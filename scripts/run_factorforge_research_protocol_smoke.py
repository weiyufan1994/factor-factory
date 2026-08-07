#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_conjecture import (
    PROTOCOL_VERSION,
    research_protocol_paths,
    validate_approach_registry,
    validate_counterexample_registry,
    validate_proof_obligation_ledger,
    validate_protocol_bundle,
    validate_research_conjecture,
    validate_terminal_semantics,
    write_json,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_release import (
    write_oos_release_manifest,
    write_search_trial_ledger,
    write_threshold_registration,
)
from factor_factory.research_obligation_verifier import (
    VERIFIER_ID as COMPONENT_VERIFIER_ID,
    VERIFIER_SPEC_VERSION as COMPONENT_SPEC_VERSION,
    component_verifier_identities,
    run_component_obligation_verifier,
)
from factor_factory.research_proof import factor_proof_certificate_path
from scripts.run_factorforge_factor_proof_smoke import valid_certificate


REPORT_ID = "RESEARCH_PROTOCOL_SMOKE"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def evidence_ref(root: Path, name: str) -> dict[str, Any]:
    path = root / "objects" / "evidence" / f"{name}.json"
    verifier_id = "factorforge_research_protocol_smoke_verifier_v1"
    write_json(
        path,
        {
            "evidence_id": name,
            "verifier_id": verifier_id,
            "verifier_status": "PASS",
            "dataset_snapshot_hash": HASH_C,
            "window_hash": HASH_D,
        },
    )
    return {
        "path": str(path.relative_to(root)),
        "sha256": sha256_file(path),
        "dataset_snapshot_hash": HASH_C,
        "window_hash": HASH_D,
        "verifier_id": verifier_id,
        "verifier_status": "PASS",
    }


def component_obligation_evidence(
    root: Path,
    *,
    obligation_id: str,
    obligation_kind: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    panel_path = root / "objects" / "evidence" / "component_panel.csv"
    trade_dates = pd.bdate_range("2025-01-06", periods=64)
    if not panel_path.exists():
        rows: list[dict[str, Any]] = []
        for date_index, date_value in enumerate(trade_dates):
            for asset_index in range(24):
                latent = (asset_index - 11.5) / 12.0
                alias = (
                    ((asset_index * 7 + date_index * 3) % 24) - 11.5
                ) / 12.0
                rows.append(
                    {
                        "trade_date": date_value.strftime("%Y-%m-%d"),
                        "asset": f"A{asset_index:03d}",
                        "full_signal": latent + 0.05 * alias,
                        "ablated_signal": alias,
                        "forward_return": (
                            0.02 * latent
                            + 0.0002 * ((asset_index + date_index) % 3 - 1)
                        ),
                    }
                )
        panel_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(panel_path, index=False)
    ledger_path = (
        root
        / "objects"
        / "research_protocol"
        / f"component_search_trial_ledger__{obligation_id}.json"
    )
    write_search_trial_ledger(
        ledger_path,
        report_id=REPORT_ID,
        factor_id="SMOKE_FACTOR",
        trials=[{"trial_id": "component_trial_001", "decision": "selected"}],
        candidate_space={"obligation_kind": obligation_kind},
        selected_hypothesis={"obligation_id": obligation_id},
    )
    release_path = (
        root
        / "objects"
        / "research_protocol"
        / f"component_oos_release__{obligation_id}.json"
    )
    window_contract = {
        "evaluation_window_role": "OOS_FINAL",
        "sample_frequency": "daily",
        "oos_window": (
            f"{trade_dates[0].strftime('%Y-%m-%d')}/"
            f"{trade_dates[-1].strftime('%Y-%m-%d')}"
        ),
        "observed_start_date": trade_dates[0].strftime("%Y-%m-%d"),
        "observed_end_date": trade_dates[-1].strftime("%Y-%m-%d"),
        "minimum_periods": 60,
        "oos_release_token_hash": HASH_A,
        "search_frozen_before_oos_release": True,
        "signal_timestamp": "t_close",
        "execution_timestamp": "t+1_close",
        "forward_return_horizon": "t+1",
        "universe_id": "component_smoke_universe",
        "investability_mask_id": "component_smoke_mask",
        "return_convention": "simple_return",
        "search_trial_ledger_ref": str(ledger_path.relative_to(root)),
        "oos_release_manifest_ref": str(release_path.relative_to(root)),
    }
    spec: dict[str, Any] = {
        "version": COMPONENT_SPEC_VERSION,
        "report_id": REPORT_ID,
        "factor_id": "SMOKE_FACTOR",
        "obligation_id": obligation_id,
        "obligation_kind": obligation_kind,
        "dataset_snapshot_hash": "",
        "window_hash": "",
        "window_contract": window_contract,
        "panel": {
            "date_column": "trade_date",
            "asset_column": "asset",
            "full_signal_column": "full_signal",
            "ablated_signal_column": "ablated_signal",
            "forward_return_column": "forward_return",
        },
        "test": {
            "expected_direction": "positive",
            "long_quantile": 0.2,
        },
    }
    if obligation_kind == "measurement_validity":
        rules = [
            {
                "rule_id": "full_ic_positive",
                "metric_path": "metrics.full_rank_ic_mean",
                "operator": ">=",
                "threshold": 0.5,
            },
            {
                "rule_id": "residual_ic_positive",
                "metric_path": "metrics.residual_rank_ic_mean",
                "operator": ">=",
                "threshold": 0.5,
            },
        ]
    else:
        rules = [
            {
                "rule_id": "ic_ablation_delta",
                "metric_path": "metrics.rank_ic_delta",
                "operator": ">=",
                "threshold": 0.5,
            },
            {
                "rule_id": "long_end_ablation_delta",
                "metric_path": "metrics.long_end_delta",
                "operator": ">=",
                "threshold": 0.005,
            },
        ]
    registration_path = (
        root
        / "objects"
        / "research_protocol"
        / f"component_thresholds__{obligation_id}.json"
    )
    spec["threshold_registration_ref"] = str(
        registration_path.relative_to(root)
    )
    write_threshold_registration(
        registration_path,
        workspace_root=root,
        spec=spec,
        decision_rules=rules,
    )
    identities = component_verifier_identities(
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
    result = run_component_obligation_verifier(
        workspace_root=root,
        panel_path=panel_path,
        spec=spec,
    )
    if result["verifier_status"] != "PASS":
        raise RuntimeError(f"component smoke verifier failed: {result}")
    return result["evidence_reference"], rules, identities


def valid_state() -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "report_id": REPORT_ID,
        "factor_id": "SMOKE_FACTOR",
        "research_id": "smoke_research",
        "round_id": "round_01",
        "phase": "DIVERSIFY",
        "previous_phase": "FORMULATE",
        "transition_reason": "Conjecture is frozen; launch independent routes.",
        "transition_evidence_refs": ["objects/research_protocol/research_conjecture.json"],
        "budget_used": {"trials_used": 3, "trial_budget": 20},
    }


def valid_conjecture() -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "report_id": REPORT_ID,
        "factor_id": "SMOKE_FACTOR",
        "identity": {
            "research_id": "smoke_research",
            "round_id": "round_01",
            "workspace_manifest_sha256": HASH_A,
            "parent_artifact_sha256": HASH_B,
            "formula_hash": HASH_C,
            "code_hash": "not_materialized_before_step3",
            "data_catalog_snapshot_sha256": HASH_D,
        },
        "task_statement": {
            "research_question": "Does a constrained flow state predict positive next-period long-side return?",
            "alpha_claim": "Higher legal-time pressure state raises conditional next-period return.",
            "null_hypothesis": "The estimator is only a liquidity or reversal alias.",
            "admissible_information_set": "Data timestamped no later than t close; position begins t+1.",
            "forbidden_evidence": ["sealed OOS", "future return labels in features"],
            "terminal_success_condition": "Component evidence and long-side after-cost evidence support the state.",
            "terminal_reject_condition": "The preferred route fails its preregistered tests and no distinct route survives.",
            "terminal_block_condition": "Information timing, data identity, or implementation parity is unresolved.",
        },
        "hypotheses": [
            {
                "hypothesis_id": "preferred_flow_constraint",
                "kind": "preferred",
                "claim": "A constrained participant creates persistent flow pressure.",
                "expected_signature": "Positive conditional long-side return with finite decay.",
                "falsification_tests": ["No endpoint separation.", "No persistence after controls."],
                "kill_criteria": ["Long-side payoff is non-positive after cost."],
            },
            {
                "hypothesis_id": "null_noise",
                "kind": "null",
                "claim": "The estimator is noise or an implementation artifact.",
                "expected_signature": "No stable component or regime evidence.",
                "falsification_tests": ["Parity succeeds.", "State survives placebo labels."],
                "kill_criteria": ["Null cannot reproduce the component evidence."],
            },
            {
                "hypothesis_id": "alternative_reversal",
                "kind": "alternative",
                "claim": "The signal is unconditional reversal.",
                "expected_signature": "Incremental state delta vanishes after reversal control.",
                "falsification_tests": ["Residual state remains.", "State-by-reversal interaction differs."],
                "kill_criteria": ["No incremental information beyond reversal."],
            },
        ],
        "economic_game": {
            "participants": ["constrained liquidity demander", "patient liquidity supplier"],
            "payer_candidates": ["constrained liquidity demander"],
            "participant_constraints": [
                {
                    "actor": "constrained liquidity demander",
                    "constraint": "Must complete inventory adjustment within a bounded horizon.",
                    "why_persistent": "The inventory mandate cannot be delayed without external cost.",
                    "observable_proxy": "Legal-time flow pressure and inventory proxy.",
                    "falsifier": "The proxy does not condition future return or decay.",
                }
            ],
            "action_to_market_outcome": "Forced demand moves price before patient capital fully absorbs it.",
            "payoff_or_profit_transfer_equation": "strategy_pnl = temporary_price_repair - execution_cost",
            "persistence_boundary": "Ends when forced inventory is absorbed or the mandate expires.",
            "capacity_boundary": "Capacity is bounded by available opposite-side liquidity.",
            "failure_condition": "No observable constraint proxy or no positive receiver payoff.",
        },
        "math_mechanism": {
            "model_family": "latent flow pressure with temporary impact",
            "mathematical_object": "X_t = unabsorbed constrained inventory pressure",
            "mechanism_equation_or_functional": "impact_t = beta * X_t - absorption_t",
            "observation_equation": "Y_t = h(X_t, liquidity_t) + epsilon_t",
            "factor_estimator": "f_t = phi(Y_<=t)",
            "market_outcome_equation": "r_{t+1} = beta X_t - cost_t + eta_{t+1}",
            "information_set": "F_t only; earliest execution t+1",
            "alternative_models": ["unconditional reversal", "liquidity risk premium"],
            "component_map": [
                {
                    "formula_component": "pressure_z",
                    "model_term": "X_t observation",
                    "preserved_information": "signed pressure",
                    "deleted_or_aliased_information": "participant identity",
                    "ablation_test": "Remove pressure_z and compare information delta.",
                }
            ],
            "limiting_cases": [
                "X_t=0 implies no conditional drift.",
                "Liquidity tends to infinity implies zero temporary impact.",
                "Execution cost exceeds impact implies non-positive net payoff.",
            ],
            "expected_metric_signatures": [
                {"metric": "long_side_return", "direction": "positive"},
                {"metric": "state_half_life", "direction": "finite_positive"},
            ],
        },
        "evidence_policy": {
            "is_window": "fixed in-sample only",
            "oos_sealed_during_search": True,
            "promotion_evidence_requirements": [
                "component validation",
                "after-cost long-side evidence",
                "regime stability",
            ],
            "is_start": "2020-01-01",
            "is_end": "2024-12-31",
            "oos_start": "2025-01-01",
            "oos_end": "2025-12-31",
            "sealed_oos_token_hash": HASH_A,
            "purge_days": 5,
            "embargo_days": 5,
            "trial_budget": 20,
            "trials_used": 3,
            "multiple_testing_policy": "BH_FDR",
            "cost_model_id": "a_share_cost_v1",
            "impact_model_id": "capacity_impact_v1",
            "capacity_model_id": "adv_participation_v1",
            "regime_plan": "bull, bear, high volatility, low liquidity",
            "universe_id": "a_share_investable_core",
            "investability_mask_id": "tradability_risk_flags_daily",
        },
        "claim_class": "information_rent",
        "claim_level": "math_framed",
    }


def valid_approaches() -> dict[str, Any]:
    families = (
        ("route_economic", "economic_game", False, ["economic_game", "payer"], "1"),
        (
            "route_measurement",
            "mechanism_object_measurement",
            False,
            ["measurement_validity", "component_ablation"],
            "2",
        ),
        (
            "route_null",
            "null_alias_counterexample",
            True,
            ["null_alias", "information_set"],
            "3",
        ),
    )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "report_id": REPORT_ID,
        "round": 1,
        "routes": [
            {
                "route_id": route_id,
                "route_family": family,
                "route_fingerprint": digit * 64,
                "blind_context_hash": chr(ord("a") + int(digit)) * 64,
                "agent_identity": f"independent_agent_{digit}",
                "status": "open",
                "research_question": f"Evaluate {family}.",
                "core_hypothesis": f"{family} can distinguish the research claim.",
                "distinct_from_other_routes": f"Uses the {family} object.",
                "proof_obligation_ids": obligation_ids,
                "exact_gap": f"Missing executed evidence for {family}.",
                "favored_thesis_visible": favored_visible,
                "reopen_only_if": [],
                "evidence_refs": [],
            }
            for route_id, family, favored_visible, obligation_ids, digit in families
        ],
    }


def valid_obligations(root: Path) -> dict[str, Any]:
    trusted: dict[str, tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]] = {
        kind: component_obligation_evidence(
            root,
            obligation_id=kind,
            obligation_kind=kind,
        )
        for kind in ("measurement_validity", "component_ablation")
    }

    def row(
        obligation_id: str,
        route_id: str,
        claim: str,
        kind: str,
        method: str,
    ) -> dict[str, Any]:
        payload = {
            "obligation_id": obligation_id,
            "route_id": route_id,
            "claim": claim,
            "obligation_kind": kind,
            "verification_method": method,
            "executable_test": {
                "command": f"python3 verifier.py --test {obligation_id}",
                "expected_output": "PASS",
                "timeout_seconds": 60,
            },
            "preregistered_thresholds": [
                {"metric": f"{obligation_id}.score", "operator": ">=", "value": 0.0}
            ],
            "dataset_snapshot_hash": HASH_C,
            "window_hash": HASH_D,
            "verifier_id": f"verifier_not_run_{obligation_id}_v1",
            "status": "open",
            "status_source": "researcher",
            "evidence_refs": [],
        }
        if kind in trusted:
            reference, rules, identities = trusted[kind]
            payload.update(
                {
                    "preregistered_thresholds": rules,
                    "dataset_snapshot_hash": identities["dataset_snapshot_hash"],
                    "window_hash": identities["window_hash"],
                    "verifier_id": COMPONENT_VERIFIER_ID,
                    "status": "passed",
                    "status_source": "verifier",
                    "evidence_refs": [reference],
                }
            )
        return payload
    return {
        "protocol_version": PROTOCOL_VERSION,
        "report_id": REPORT_ID,
        "obligations": [
            row(
                "economic_game",
                "route_economic",
                "Constraint creates repeatable transfer.",
                "economic_game",
                "payer proxy conditional test",
            ),
            row(
                "measurement_validity",
                "route_measurement",
                "Estimator contains incremental state information.",
                "measurement_validity",
                "component information delta test",
            ),
            row(
                "component_ablation",
                "route_measurement",
                "Removing the state component destroys incremental information.",
                "component_ablation",
                "component ablation",
            ),
            row(
                "null_alias",
                "route_null",
                "Preferred route is not an unconditional reversal alias.",
                "null_alias",
                "control and residual test",
            ),
            row(
                "information_set",
                "route_null",
                "All inputs are legal at F_t.",
                "information_set",
                "timing audit",
            ),
        ],
    }


def valid_counterexamples(root: Path) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "report_id": REPORT_ID,
        "counterexamples": [
            {
                "counterexample_id": "alias_reversal",
                "route_id": "route_null",
                "attack_type": "alias",
                "construction_or_scenario": "Replace state with unconditional reversal.",
                "predicted_failure": "Preferred state adds no residual information.",
                "discriminating_test": "Compare residual and joint-state metrics.",
                "status": "rejected",
                "actual_result": "Residual state retains incremental information.",
                "evidence_refs": [evidence_ref(root, "counterexample_alias")],
            },
            {
                "counterexample_id": "liquidity_boundary",
                "route_id": "route_economic",
                "attack_type": "boundary",
                "construction_or_scenario": "Restrict to abundant-liquidity regime.",
                "predicted_failure": "Temporary impact and payer transfer vanish.",
                "discriminating_test": "State-by-liquidity interaction.",
                "status": "confirmed",
                "actual_result": "Effect weakens in abundant-liquidity regime.",
                "evidence_refs": [evidence_ref(root, "counterexample_boundary")],
            },
        ],
    }


def valid_iteration() -> dict[str, Any]:
    return {
        "report_id": REPORT_ID,
        "factor_id": "SMOKE_FACTOR",
        "research_judgment": {
            "decision": "reject",
            "mechanism_claim_level": "component_validated",
            "research_memo": {
                "final_revision_strategy": {
                    "loop_authorization": "advisory_only",
                    "revision_needed": False,
                }
            },
        },
        "loop_action": {
            "should_modify_step3b": False,
            "modification_targets": [],
            "parallel_exploration_branches": [],
            "stop_reason": "research routes exhausted",
        },
    }


def has(reasons: list[str], token: str) -> bool:
    return any(token in reason for reason in reasons)


def run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def main() -> int:
    root = Path("/tmp/factorforge_research_protocol_smoke")
    shutil.rmtree(root, ignore_errors=True)
    paths = research_protocol_paths(root, REPORT_ID)
    state = valid_state()
    conjecture = valid_conjecture()
    approaches = valid_approaches()
    obligations = valid_obligations(root)
    counterexamples = valid_counterexamples(root)
    iteration = valid_iteration()
    write_json(paths["state"], state)
    write_json(paths["conjecture"], conjecture)
    write_json(paths["approaches"], approaches)
    write_json(paths["obligations"], obligations)
    write_json(paths["counterexamples"], counterexamples)
    factor_proof = valid_certificate(
        root,
        claim_class="information_rent",
        report_id=REPORT_ID,
        factor_id="SMOKE_FACTOR",
    )
    write_json(factor_proof_certificate_path(root, REPORT_ID), factor_proof)
    iteration_path = (
        root
        / "objects"
        / "research_iteration_master"
        / f"research_iteration_master__{REPORT_ID}.json"
    )
    write_json(iteration_path, iteration)
    council_dir = (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
    )
    write_json(
        council_dir / f"revision_council_packet__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "research_memo": {
                "revision_strategy": {
                    "primary_failure_signature": "cost_too_high"
                },
                "mechanism_analysis": {"mechanism_fit": "partial"},
            },
            "metrics": {"long_side_annual_return": 0.01},
            "forbidden_writeback_baseline": {
                "contract_version": (
                    "factorforge_revision_council_forbidden_writeback_baseline_v1"
                ),
                "captured_at": "2025-01-01T00:00:00Z",
                "paths": {
                    "handoff_to_step3b": {
                        "path": (
                            "objects/handoff/"
                            f"handoff_to_step3b__{REPORT_ID}.json"
                        ),
                        "exists": False,
                        "kind": "file",
                        "mtime_ns": None,
                        "sha256": None,
                    },
                    "generated_code": {
                        "path": f"generated_code/{REPORT_ID}",
                        "exists": False,
                        "kind": "directory",
                        "mtime_ns": None,
                        "digest": None,
                    },
                    "official_library": {
                        "path": (
                            "objects/factor_library_official/"
                            f"factor_record__{REPORT_ID}.json"
                        ),
                        "exists": False,
                        "kind": "file",
                        "mtime_ns": None,
                        "sha256": None,
                    },
                    "data_clean": {
                        "path": "data/clean",
                        "exists": False,
                        "kind": "directory",
                        "mtime_ns": None,
                        "digest": None,
                    },
                },
            },
        },
    )
    council_setup_commands = [
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py",
            "--report-id",
            REPORT_ID,
            "--executor",
            "local_mock",
            "--research-protocol",
            "required",
        ],
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py",
            "--report-id",
            REPORT_ID,
        ],
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/run_agentic_council_local_mock.py",
            "--report-id",
            REPORT_ID,
        ],
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/validate_agentic_council_result.py",
            "--report-id",
            REPORT_ID,
        ],
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/merge_revision_council.py",
            "--report-id",
            REPORT_ID,
        ],
    ]
    for setup_command in council_setup_commands:
        setup_process = run(setup_command, root)
        if setup_process.returncode != 0:
            raise RuntimeError(
                "council setup failed: "
                + " ".join(setup_command)
                + "\n"
                + setup_process.stdout
                + "\n"
                + setup_process.stderr
            )
    council_summary = json.loads(
        paths["council_summary"].read_text(encoding="utf-8")
    )
    summary_routes = council_summary.get("research_route_summary") or []
    law_index = council_summary.get("candidate_law_index") or []
    if not summary_routes or not law_index:
        raise RuntimeError("validated Council summary missing routes or laws")
    selected_law = law_index[0]
    selected_law_hash = selected_law["law_hash"]
    selected_route_ids = [
        str(row["route_id"]) for row in summary_routes
    ]
    selected_result_hashes = [
        str(row["source_result_sha256"]) for row in summary_routes
    ]
    write_json(
        paths["root_synthesis"],
        {
            "contract_version": "factorforge_main_agent_council_synthesis_v1",
            "report_id": REPORT_ID,
            "route_comparison": [
                {
                    "route_id": route["route_id"],
                    "disposition": "rejected",
                    "reason": "Terminal reject after executable evidence.",
                    "exact_gap_or_closed_obligation": "closed",
                }
                for route in approaches["routes"]
            ],
            "dissent_resolution": "Preserve the liquidity-boundary dissent.",
            "selection_rule": "evidence_weighted_falsification",
            "selected_revision": {
                "source_route_ids": selected_route_ids,
                "source_result_hashes": selected_result_hashes,
                "law_id": selected_law["law_id"],
                "law_or_formula_hash": selected_law_hash,
                "open_proof_obligation_ids": [],
            },
        },
    )
    write_json(
        paths["root_synthesis_approval"],
        {
            "approval_version": "factorforge_main_agent_council_synthesis_approval_v1",
            "report_id": REPORT_ID,
            "approval_source": "explicit_smoke_reviewer",
            "synthesis_sha256": sha256_file(paths["root_synthesis"]),
        },
    )
    cases: dict[str, dict[str, Any]] = {}

    bad = deepcopy(conjecture)
    bad["hypotheses"] = [
        item for item in bad["hypotheses"] if item["kind"] != "null"
    ]
    reasons = validate_research_conjecture(bad)
    cases["dual_hypothesis_required"] = {
        "ok": has(reasons, "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_DUAL_HYPOTHESIS_MISSING"),
        "reasons": reasons,
    }

    bad = deepcopy(approaches)
    bad["routes"] = bad["routes"][:2]
    reasons = validate_approach_registry(bad, stage="pre_council")
    cases["route_diversity_required"] = {
        "ok": has(reasons, "BLOCK_FACTORFORGE_APPROACH_REGISTRY_ROUTE_DIVERSITY_MISSING"),
        "reasons": reasons,
    }

    bad = deepcopy(approaches)
    bad["routes"][0]["status"] = "blocked"
    bad["routes"][0]["blocked_reason"] = "unidentified payer"
    bad["routes"][0]["reopen_only_if"] = []
    reasons = validate_approach_registry(bad, stage="pre_council")
    cases["blocked_route_requires_reopen_condition"] = {
        "ok": has(reasons, "BLOCK_FACTORFORGE_APPROACH_ROUTE_REOPEN_CRITERIA_MISSING"),
        "reasons": reasons,
    }

    bad = deepcopy(obligations)
    bad["obligations"][1]["evidence_refs"] = []
    reasons = validate_proof_obligation_ledger(
        bad,
        stage="final",
        workspace_root=root,
    )
    cases["passed_obligation_requires_evidence"] = {
        "ok": has(reasons, "BLOCK_FACTORFORGE_PROOF_OBLIGATION_EVIDENCE_MISSING"),
        "reasons": reasons,
    }

    bad = deepcopy(obligations)
    bad["obligations"][1]["evidence_refs"][0]["path"] = (
        "objects/evidence/does_not_exist.json"
    )
    reasons = validate_proof_obligation_ledger(
        bad,
        stage="final",
        workspace_root=root,
    )
    cases["passed_obligation_requires_existing_hashed_evidence"] = {
        "ok": has(
            reasons,
            "BLOCK_FACTORFORGE_PROOF_OBLIGATION_EVIDENCE_INVALID:1_PATH_MISSING",
        ),
        "reasons": reasons,
    }

    forged_obligations = deepcopy(obligations)
    forged_reference = forged_obligations["obligations"][1]["evidence_refs"][0]
    original_evidence_path = root / forged_reference["path"]
    forged_payload = json.loads(original_evidence_path.read_text(encoding="utf-8"))
    forged_payload["metrics"]["full_rank_ic_mean"] = 0.999999
    forged_evidence_path = (
        root / "objects" / "evidence" / "forged_component_evidence.json"
    )
    write_json(forged_evidence_path, forged_payload)
    forged_reference["path"] = str(forged_evidence_path.relative_to(root))
    forged_reference["sha256"] = sha256_file(forged_evidence_path)
    reasons = validate_proof_obligation_ledger(
        forged_obligations,
        stage="final",
        workspace_root=root,
    )
    cases["hand_authored_component_pass_cannot_replace_verifier_replay"] = {
        "ok": has(reasons, "COMPONENT_EVIDENCE_REPLAY_MISMATCH:metrics"),
        "reasons": reasons,
    }

    bad = deepcopy(counterexamples)
    bad["counterexamples"] = bad["counterexamples"][:1]
    reasons = validate_counterexample_registry(
        bad,
        stage="pre_revision",
        workspace_root=root,
    )
    cases["counterexample_coverage_required"] = {
        "ok": has(reasons, "BLOCK_FACTORFORGE_COUNTEREXAMPLE_SEARCH_INSUFFICIENT"),
        "reasons": reasons,
    }

    bad = deepcopy(iteration)
    bad["loop_action"]["next_runner"] = "step3b"
    bad["loop_action"]["parallel_exploration_branches"] = [{"branch_id": "stale"}]
    proof_report = {
        "verdict": "ACCEPT",
    }
    reasons = validate_terminal_semantics(
        bad,
        obligations=obligations,
        workspace_root=root,
        factor_proof_report=proof_report,
    )
    cases["terminal_semantic_conflict_blocks"] = {
        "ok": has(reasons, "BLOCK_FACTORFORGE_TERMINAL_VERDICT_HAS_STEP3B_NEXT_RUNNER")
        and has(reasons, "BLOCK_FACTORFORGE_TERMINAL_VERDICT_HAS_ACTIVE_BRANCHES"),
        "reasons": reasons,
    }

    missing_ablation = deepcopy(obligations)
    missing_ablation["obligations"] = [
        row
        for row in missing_ablation["obligations"]
        if row.get("obligation_kind") != "component_ablation"
    ]
    reasons = validate_terminal_semantics(
        iteration,
        obligations=missing_ablation,
        workspace_root=root,
        factor_proof_report={"verdict": "ACCEPT"},
    )
    cases["component_claim_requires_verified_ablation"] = {
        "ok": has(
            reasons,
            "BLOCK_FACTORFORGE_COMPONENT_CLAIM_WITHOUT_PASSED_ABLATION",
        ),
        "reasons": reasons,
    }

    valid_synthesis = json.loads(paths["root_synthesis"].read_text(encoding="utf-8"))
    bad_synthesis = deepcopy(valid_synthesis)
    bad_synthesis["selected_revision"]["source_result_hashes"] = [HASH_A, HASH_B]
    write_json(paths["root_synthesis"], bad_synthesis)
    write_json(
        paths["root_synthesis_approval"],
        {
            "approval_version": "factorforge_main_agent_council_synthesis_approval_v1",
            "report_id": REPORT_ID,
            "approval_source": "explicit_smoke_reviewer",
            "synthesis_sha256": sha256_file(paths["root_synthesis"]),
        },
    )
    bad_binding_report = validate_protocol_bundle(
        root=root,
        report_id=REPORT_ID,
        stage="final",
        iteration_path=iteration_path,
    )
    cases["root_synthesis_must_bind_actual_council_result_hashes"] = {
        "ok": has(
            bad_binding_report.get("block_reasons") or [],
            "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_COUNCIL_RESULT_HASH_MISMATCH",
        ),
        "report": bad_binding_report,
    }
    write_json(paths["root_synthesis"], valid_synthesis)
    write_json(
        paths["root_synthesis_approval"],
        {
            "approval_version": "factorforge_main_agent_council_synthesis_approval_v1",
            "report_id": REPORT_ID,
            "approval_source": "explicit_smoke_reviewer",
            "synthesis_sha256": sha256_file(paths["root_synthesis"]),
        },
    )

    final_report = validate_protocol_bundle(
        root=root,
        report_id=REPORT_ID,
        stage="final",
        iteration_path=iteration_path,
    )
    cases["valid_final_bundle_passes"] = {
        "ok": final_report["verdict"] == "PASS",
        "report": final_report,
    }

    valid_summary = json.loads(
        paths["council_summary"].read_text(encoding="utf-8")
    )
    valid_synthesis = json.loads(
        paths["root_synthesis"].read_text(encoding="utf-8")
    )
    attacked_summary = deepcopy(valid_summary)
    attacked_synthesis = deepcopy(valid_synthesis)
    attacked_route = attacked_summary["research_route_summary"][0]
    attacked_result_path = root / attacked_route["source_result_path"]
    valid_result_payload = json.loads(
        attacked_result_path.read_text(encoding="utf-8")
    )
    valid_result_text = attacked_result_path.read_text(encoding="utf-8")
    old_result_hash = attacked_route["source_result_sha256"]
    attacked_result_payload = deepcopy(valid_result_payload)
    attacked_result_payload["task_id"] = "forged_task_identity"
    write_json(attacked_result_path, attacked_result_payload)
    attacked_hash = sha256_file(attacked_result_path)
    attacked_route["source_result_sha256"] = attacked_hash
    for law in attacked_summary.get("candidate_law_index") or []:
        if law.get("source_result_sha256") == old_result_hash:
            law["source_result_sha256"] = attacked_hash
    attacked_synthesis["selected_revision"]["source_result_hashes"] = [
        attacked_hash if value == old_result_hash else value
        for value in attacked_synthesis["selected_revision"][
            "source_result_hashes"
        ]
    ]
    write_json(paths["council_summary"], attacked_summary)
    write_json(paths["root_synthesis"], attacked_synthesis)
    write_json(
        paths["root_synthesis_approval"],
        {
            "approval_version": (
                "factorforge_main_agent_council_synthesis_approval_v1"
            ),
            "report_id": REPORT_ID,
            "approval_source": "explicit_smoke_reviewer",
            "synthesis_sha256": sha256_file(paths["root_synthesis"]),
        },
    )
    forged_identity_report = validate_protocol_bundle(
        root=root,
        report_id=REPORT_ID,
        stage="final",
        iteration_path=iteration_path,
    )
    cases["hash_consistent_council_identity_forgery_blocks"] = {
        "ok": has(
            forged_identity_report.get("block_reasons") or [],
            "BLOCK_FACTORFORGE_ROOT_SYNTHESIS_SOURCE_RESULT_VALIDATION_FAILED",
        ),
        "report": forged_identity_report,
    }
    attacked_result_path.write_text(valid_result_text, encoding="utf-8")
    write_json(paths["council_summary"], valid_summary)
    write_json(paths["root_synthesis"], valid_synthesis)
    write_json(
        paths["root_synthesis_approval"],
        {
            "approval_version": (
                "factorforge_main_agent_council_synthesis_approval_v1"
            ),
            "report_id": REPORT_ID,
            "approval_source": "explicit_smoke_reviewer",
            "synthesis_sha256": sha256_file(paths["root_synthesis"]),
        },
    )

    mismatched_conjecture = deepcopy(conjecture)
    mismatched_conjecture["claim_class"] = "liquidity_rent"
    write_json(paths["conjecture"], mismatched_conjecture)
    mismatch_report = validate_protocol_bundle(
        root=root,
        report_id=REPORT_ID,
        stage="final",
        iteration_path=iteration_path,
    )
    cases["factor_proof_claim_class_must_match_conjecture"] = {
        "ok": has(
            mismatch_report.get("block_reasons") or [],
            "BLOCK_FACTORFORGE_RESEARCH_PROTOCOL_CLAIM_CLASS_MISMATCH",
        ),
        "report": mismatch_report,
    }
    write_json(paths["conjecture"], conjecture)

    write_json(
        council_dir / f"revision_council_packet__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "research_memo": {
                "revision_strategy": {"primary_failure_signature": "cost_too_high"},
                "mechanism_analysis": {"mechanism_fit": "partial"},
            },
            "metrics": {"long_side_annual_return": 0.01},
        },
    )
    taskbook_proc = run(
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py",
            "--report-id",
            REPORT_ID,
            "--executor",
            "dispatch_manifest",
            "--research-protocol",
            "required",
        ],
        root,
    )
    taskbook_path = council_dir / f"agentic_taskbook__{REPORT_ID}.json"
    taskbook = json.loads(taskbook_path.read_text(encoding="utf-8"))
    tasks = taskbook.get("agent_tasks") or []
    blind_tasks = [
        task
        for task in tasks
        if (task.get("blind_context_policy") or {}).get("blind_phase") is True
    ]
    cases["dynamic_registry_routes_and_blinding"] = {
        "ok": taskbook_proc.returncode == 0
        and taskbook.get("research_protocol_gate", {}).get("status") == "valid"
        and {task.get("route_family") for task in tasks}
        == {
            "economic_game",
            "mechanism_object_measurement",
            "null_alias_counterexample",
        }
        and len(blind_tasks) >= 2,
        "stderr": taskbook_proc.stderr,
    }

    missing_report_id = "RESEARCH_PROTOCOL_MISSING_SMOKE"
    missing_council_dir = (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / missing_report_id
    )
    write_json(
        missing_council_dir / f"revision_council_packet__{missing_report_id}.json",
        {
            "report_id": missing_report_id,
            "research_memo": {
                "revision_strategy": {
                    "primary_failure_signature": "mechanism_unclear"
                },
                "mechanism_analysis": {"mechanism_fit": "weak"},
            },
            "metrics": {"long_side_annual_return": 0.0},
        },
    )
    missing_taskbook = run(
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py",
            "--report-id",
            missing_report_id,
            "--executor",
            "dispatch_manifest",
        ],
        root,
    )
    cases["formal_taskbook_defaults_to_required_protocol"] = {
        "ok": missing_taskbook.returncode != 0
        and "BLOCK_FACTORFORGE_RESEARCH_CONJECTURE_PROTOCOL_REQUIRED" in (
            missing_taskbook.stdout + missing_taskbook.stderr
        ),
        "stdout": missing_taskbook.stdout,
        "stderr": missing_taskbook.stderr,
    }

    dispatch_proc = run(
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/build_agentic_council_dispatch_manifest.py",
            "--report-id",
            REPORT_ID,
        ],
        root,
    )
    dispatch_validate = run(
        [
            sys.executable,
            "skills/factor-forge-step6/scripts/validate_agentic_council_dispatch.py",
            "--report-id",
            REPORT_ID,
        ],
        root,
    )
    cases["blind_task_packets_validate"] = {
        "ok": dispatch_proc.returncode == 0 and dispatch_validate.returncode == 0,
        "dispatch_stderr": dispatch_proc.stderr,
        "validator_stdout": dispatch_validate.stdout,
        "validator_stderr": dispatch_validate.stderr,
    }

    failed = [name for name, item in cases.items() if not item.get("ok")]
    result = {
        "verdict": "ACCEPT" if not failed else "BLOCK",
        "failed": failed,
        "cases": cases,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if failed:
        return 1
    print("FACTORFORGE_RESEARCH_PROTOCOL_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
