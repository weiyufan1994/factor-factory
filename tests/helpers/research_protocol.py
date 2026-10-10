"""Synthetic test inputs only; never evidence of real researcher execution."""
from __future__ import annotations

from typing import Any
from factor_factory.research_conjecture import PROTOCOL_VERSION

REPORT_ID = "RESEARCH_PROTOCOL_SMOKE"
HASH_A, HASH_B, HASH_C, HASH_D = (x * 64 for x in "abcd")


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
