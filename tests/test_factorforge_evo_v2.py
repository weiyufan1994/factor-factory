from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from factor_factory.evo_v2 import (
    ECONOMIC_BACKPROJECTION_VERSION,
    EXPERIENCE_TRANSFER_BUNDLE_VERSION,
    FEEDBACK_LEDGER_VERSION,
    MECHANISM_DELTA_VERSION,
    PROTECTED_FIELDS,
    QUALIFICATION_STATES,
    TRANSFER_USE_RECEIPT_VERSION,
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_relative_paths,
    sha256_file,
    stable_json_hash,
    validate_economic_backprojection,
    validate_evo_v2_bundle,
    validate_experience_transfer_bundle,
    validate_feedback_ledger,
    validate_mechanism_delta,
    validate_transfer_use_receipt,
    with_content_hash,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = "EVO2_CASE"


def _write_support(root: Path, name: str, payload: dict | None = None) -> dict[str, str]:
    path = root / "support" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload or {"record": name}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def _authority_guard() -> dict:
    return {
        "policy": "constitutional_invariance_epistemic_evolution_only",
        "knowledge_authority": "advisory_only",
        "evo_scope": "questions_tests_public_derivations_and_transfer_mappings_only",
        "protected_fields": list(PROTECTED_FIELDS),
        "mutation_permissions": {field: False for field in PROTECTED_FIELDS},
        "canonical_write_allowed": False,
        "factor_verdict_authority": False,
        "child_execution_allowed": False,
    }


def _artifact_authority(
    producer_role: str,
    authority_class: str,
    review_status: str,
    host_ref: dict[str, str],
) -> dict:
    return {
        "producer_role": producer_role,
        "authority_class": authority_class,
        "host_admission_status": "HOST_ADMITTED",
        "host_admission_ref": copy.deepcopy(host_ref),
        "independent_review_status": review_status,
    }


def _build_bundle(root: Path) -> dict[str, dict]:
    root.mkdir(parents=True, exist_ok=True)
    host_ref = _write_support(root, "host_admission")
    reviewer_ref = _write_support(root, "independent_reviewer")
    evidence_ref = _write_support(root, "is_evidence")
    prereg_ref = _write_support(root, "preregistration")
    source_ref = _write_support(root, "source_experience")
    frozen_ref = _write_support(root, "frozen_authority")
    paths = evo_v2_relative_paths(REPORT_ID)
    identity = {
        "factor_id": "negative_pv_shape",
        "report_id": REPORT_ID,
        "research_id": "research_001",
        "branch_id": "main",
        "run_id": "run_001",
    }
    mechanism_fingerprint = {
        "economic_claim": "constraint-driven tail-state execution pressure",
        "estimand_id": "next_day_cross_sectional_ordering",
        "payer_or_constraint": "constrained_funds | mandate-driven forced execution",
        "mathematical_object": "joint empirical path distribution of return and signed activity",
        "broken_invariant_or_boundary": "additivity across tail and ordinary path states",
        "observation_mapping": "H(M_t)=legal close and volume path through t",
        "failure_signature": "qualified positive tail interaction after all lower-layer controls",
    }
    retrieval_ref = _write_support(
        root,
        "memory_retrieval",
        {
            "query": {
                "mechanism_fingerprint_sha256": stable_json_hash(
                    mechanism_fingerprint
                ),
            },
            "checked_indexes": ["role_memory", "factor_knowledge"],
            "admissible_hit_count": 3,
        },
    )

    predictions = [
        {
            "prediction_id": "pred_primary",
            "model_id": "model_primary",
            "model_role": "primary",
            "expected_signature": {
                "metric_id": "rank_ic",
                "direction": "positive",
                "shape": "monotone_top_tail",
                "horizon": "t_plus_1",
                "conditioning_set": ["purged_is", "eligible_universe"],
                "materiality_floor": "absolute_rank_ic_at_least_0.01",
                "unique_against_model_ids": ["model_null"],
            },
            "falsifier": "rank IC is zero after the alias control",
            "preregistration_ref": copy.deepcopy(prereg_ref),
            "uses_oos": False,
        },
        {
            "prediction_id": "pred_alternative",
            "model_id": "model_alternative",
            "model_role": "mechanism_alternative",
            "expected_signature": {
                "metric_id": "component_interaction",
                "direction": "zero",
                "shape": "additive_only",
                "horizon": "t_plus_1",
                "conditioning_set": ["purged_is", "component_ablation"],
                "materiality_floor": "interaction_delta_below_0.001",
                "unique_against_model_ids": ["model_primary"],
            },
            "falsifier": "the interaction remains material after ablation",
            "preregistration_ref": copy.deepcopy(prereg_ref),
            "uses_oos": False,
        },
        {
            "prediction_id": "pred_null",
            "model_id": "model_null",
            "model_role": "null_alias",
            "expected_signature": {
                "metric_id": "alias_residual_ic",
                "direction": "zero",
                "shape": "flat",
                "horizon": "t_plus_1",
                "conditioning_set": ["purged_is", "alias_residual"],
                "materiality_floor": "absolute_rank_ic_below_0.002",
                "unique_against_model_ids": ["model_primary"],
            },
            "falsifier": "residual IC survives the alias control",
            "preregistration_ref": copy.deepcopy(prereg_ref),
            "uses_oos": False,
        },
    ]
    feedback = with_content_hash(
        {
            "contract_version": FEEDBACK_LEDGER_VERSION,
            "artifact_identity": copy.deepcopy(identity),
            "authority_guard": _authority_guard(),
            "artifact_authority": _artifact_authority(
                "Validation & Evidence",
                "qualified_contradiction_advisory_only",
                "NOT_REQUIRED_PRE_MEMORY",
                host_ref,
            ),
            "frozen_authority": {
                "economic_hypothesis_ref": copy.deepcopy(frozen_ref),
                "measurement_program_ref": copy.deepcopy(frozen_ref),
                "estimand_id": "next_day_cross_sectional_ordering",
                "estimand_sha256": "1" * 64,
                "threshold_registry_ref": copy.deepcopy(frozen_ref),
                "oos_policy_ref": copy.deepcopy(frozen_ref),
                "trial_budget_ref": copy.deepcopy(frozen_ref),
                "immutable_values_sha256": "2" * 64,
            },
            "state_history": [
                {
                    "sequence": index + 1,
                    "state": state,
                    "actor_role": "Host Research Director" if index in {0, 4} else "Validation & Evidence",
                    "evidence_refs": [copy.deepcopy(evidence_ref)],
                }
                for index, state in enumerate(QUALIFICATION_STATES)
            ],
            "current_state": "QUALIFIED_CONTRADICTION",
            "hypothesis_predictions": predictions,
            "contradiction": {
                "contradiction_id": "contradiction_interaction",
                "source_prediction_ids": ["pred_primary", "pred_alternative"],
                "observed_signature": {
                    "metric_id": "component_interaction",
                    "direction": "positive",
                    "shape": "threshold_interaction",
                    "horizon": "t_plus_1",
                    "conditioning_set": ["purged_is", "component_ablation"],
                    "evidence_refs": [copy.deepcopy(evidence_ref)],
                },
                "mismatch_kind": "interaction",
                "materiality_assessment": "interaction delta exceeds the frozen IS floor",
                "competing_explanations": [
                    {
                        "explanation_id": "explain_missing_interaction",
                        "failed_layer": "primary_math_mechanism",
                        "claim": "the baseline omits a path-state interaction",
                        "distinguishing_evidence_needed": "interaction disappears when the path state is removed",
                    },
                    {
                        "explanation_id": "explain_projection_alias",
                        "failed_layer": "market_outcome_projection",
                        "claim": "the observed interaction is a projection alias",
                        "distinguishing_evidence_needed": "the interaction vanishes after the frozen alias residualization",
                    },
                ],
                "discriminating_test": "compare preregistered state interaction against frozen alias residual",
                "evidence_refs": [copy.deepcopy(evidence_ref)],
                "is_large_residual_only": False,
                "uses_oos": False,
            },
            "lower_layer_clearance": [
                {
                    "layer_id": layer,
                    "status": "CLEARED",
                    "finding": f"{layer} passed its frozen deterministic and IS audit",
                    "evidence_refs": [copy.deepcopy(evidence_ref)],
                }
                for layer in [
                    "implementation",
                    "data_integrity",
                    "information_set",
                    "measurement",
                    "alias_and_control",
                ]
            ],
            "qualification": {
                "decision": "QUALIFIED",
                "legal_information_set": True,
                "preregistered_prediction": True,
                "within_frozen_trial_budget": True,
                "multiplicity_controlled": True,
                "replicated_in_purged_is": True,
                "materiality_pass": True,
                "discriminates_models": True,
                "lower_layers_cleared": True,
                "oos_reused": False,
                "authority_scope": "research_scheduling_only",
                "factor_verdict_authority": False,
                "branch_execution_authority": False,
            },
            "oos_control": {
                "search_use": "SEALED_NOT_ACCESSED",
                "oos_accessed": False,
                "oos_used_for_contradiction": False,
                "oos_used_for_revision": False,
            },
        }
    )

    delta = with_content_hash(
        {
            "contract_version": MECHANISM_DELTA_VERSION,
            "artifact_identity": copy.deepcopy(identity),
            "authority_guard": _authority_guard(),
            "artifact_authority": _artifact_authority(
                "symbolic_law_discovery",
                "dirac_minimal_extension_advisory_only",
                "NOT_CANONICAL_PENDING_INDEPENDENT_REVIEW",
                host_ref,
            ),
            "feedback_ref": {
                "path": paths["feedback_ledger"],
                "sha256": artifact_sha256(feedback),
            },
            "contradiction_id": "contradiction_interaction",
            "baseline_model": {
                "model_id": "model_primary",
                "mathematical_object": "joint empirical path distribution of return and signed activity",
                "mechanism_equation_or_functional": "K(M)=Cov_M(return,signed_activity)=0",
                "target_functional": "next-day cross-sectional ordering",
                "market_outcome_projection": "Q_t=P(K(M_t),constraints,costs)",
                "observation_mapping": "H(M_t)=legal close and volume path through t",
                "estimand_id": "next_day_cross_sectional_ordering",
            },
            "minimal_extension": {
                "delta_id": "delta_path_interaction",
                "extension_kind": "minimal_interaction_term",
                "baseline_equation": "K(M)=Cov_M(return,signed_activity)=0",
                "extended_equation": "K_prime(M,Z)=K(M)+lambda*G(M,Z)=0",
                "missing_term": "G(M,Z)=Cov_M(return,signed_activity*tail_state)",
                "lambda_symbol": "lambda",
                "recovery_limit": "lim lambda to 0 gives K_prime=K",
                "recovery_check": {
                    "parameter": "lambda",
                    "limit_value": 0,
                    "recovers_baseline": True,
                },
                "broken_invariant_or_boundary": "additivity across tail and ordinary path states",
                "added_mathematical_object": "tail-conditioned occupation interaction",
                "preserved_invariants": ["frozen estimand", "legal information set", "payoff horizon"],
                "information_preserved": "path ordering and tail-state co-occurrence",
                "information_discarded": "security labels and future observations",
                "complexity_delta": 1,
                "minimality_argument": "one interaction term explains the qualified mismatch without a new estimand",
                "minimality_evidence": {
                    "term_necessity_test": "removing G must restore the preregistered contradiction",
                    "removal_recovers_contradiction": True,
                    "no_estimand_change": True,
                    "no_threshold_change": True,
                    "no_trial_budget_change": True,
                },
                "rejected_larger_extensions": ["hidden Markov state was rejected as unnecessary complexity"],
            },
            "distinctive_predictions": [
                {
                    "prediction_id": "delta_pred_tail_interaction",
                    "target_model_ids": ["model_primary", "model_null"],
                    "predicted_signature": "residual ordering appears only when tail occupation and signed activity coincide",
                    "unique_to_extension": True,
                    "discriminating_test": "preregistered two-way ablation of tail occupation and signed activity",
                    "falsifier": "the joint ablation is no different from either standalone component",
                    "legal_information_time": "all state inputs are observed by close at t",
                    "uses_oos": False,
                }
            ],
            "public_derivation_record": {
                "definitions": ["M is the legal path empirical measure", "Z is the tail occupation state"],
                "assumptions": ["the frozen estimand and payoff horizon remain unchanged"],
                "key_derivation_steps": [
                    "localize the mismatch to the interaction component",
                    "add the smallest interaction term and derive its ablation signature",
                ],
                "limiting_cases": [
                    "lambda=0 recovers the baseline",
                    "constant Z makes the interaction observationally redundant",
                ],
                "overclaim_guard": "the extension is a review-only hypothesis until preregistered IS confirmation",
                "private_chain_of_thought_included": False,
            },
            "status": "DERIVED_REVIEW_ONLY",
            "oos_control": {
                "search_use": "SEALED_NOT_ACCESSED",
                "oos_accessed": False,
                "oos_used_for_contradiction": False,
                "oos_used_for_revision": False,
            },
        }
    )

    backprojection = with_content_hash(
        {
            "contract_version": ECONOMIC_BACKPROJECTION_VERSION,
            "artifact_identity": copy.deepcopy(identity),
            "authority_guard": _authority_guard(),
            "artifact_authority": _artifact_authority(
                "economic_mechanism",
                "economic_backprojection_hypothesis_advisory_only",
                "NOT_CANONICAL_PENDING_INDEPENDENT_REVIEW",
                host_ref,
            ),
            "mechanism_delta_ref": {
                "path": paths["mechanism_delta"],
                "sha256": artifact_sha256(delta),
            },
            "delta_id": "delta_path_interaction",
            "economic_mapping": {
                "mapping_id": "econ_map_forced_execution",
                "missing_term_id": "tail_activity_interaction",
                "actor": "mandate-constrained funds",
                "receiver": "liquidity suppliers able to wait",
                "payer": "constrained_funds",
                "binding_constraint": "mandate-driven forced execution",
                "action": "execute in a crowded tail state despite adverse price pressure",
                "payoff_or_profit_transfer_equation": "receiver payoff equals constrained price concession net of costs",
                "persistence_mechanism": "mandate and redemption constraints recur and cannot be instantaneously arbitraged away",
                "capacity_boundary": "the concession disappears when patient liquidity exceeds constrained flow",
                "disappearance_condition": "no forced flow or ample opposing liquidity",
                "observable_proxy": "legal signed activity interacted with tail occupation",
                "proxy_information_time": "observable through market close at t",
                "counterfactual": "without the constraint the interaction coefficient is zero",
                "no_story_without_proxy": True,
            },
            "competing_economic_explanations": [
                {
                    "explanation_id": "econ_forced_execution",
                    "economic_mechanism": "objective mandates create forced tail-state trades",
                    "payer": "constrained funds",
                    "distinguishing_test": "interaction strengthens with independently measured constrained flow",
                    "falsifier": "no relation to any legal constrained-flow proxy",
                },
                {
                    "explanation_id": "econ_attention_alias",
                    "economic_mechanism": "the interaction only aliases public attention",
                    "payer": "none identified",
                    "distinguishing_test": "attention control absorbs the interaction while constrained flow does not",
                    "falsifier": "interaction survives attention control and tracks constrained flow",
                },
            ],
            "predicted_economic_signatures": [
                {
                    "signature_id": "econ_signature_constraint",
                    "mechanism_prediction_id": "delta_pred_tail_interaction",
                    "economic_signature": "the interaction rises when mandate pressure binds and vanishes with ample liquidity",
                    "observable_proxy": "constrained-flow proxy crossed with tail occupation",
                    "discriminating_test": "pre-registered proxy interaction and attention placebo",
                    "falsifier": "attention explains the effect but constrained flow does not",
                    "unique_against_explanation_ids": ["econ_attention_alias"],
                }
            ],
            "qualification": {
                "claim_level": "HYPOTHESIS_ONLY_UNTIL_VALIDATED",
                "payer_validated": False,
                "current_factor_proof": False,
                "branch_authority": False,
            },
            "status": "CAUSAL_MAPPING_REVIEW_ONLY",
            "oos_control": {
                "search_use": "SEALED_NOT_ACCESSED",
                "oos_accessed": False,
                "oos_used_for_contradiction": False,
                "oos_used_for_revision": False,
            },
        }
    )

    experiences = [
        {
            "experience_id": "exp_structural",
            "layer": "structural_lesson",
            "source_ref": copy.deepcopy(source_ref),
            "source_factor_id": "prior_factor_structural",
            "source_report_id": "PRIOR_STRUCTURAL",
            "source_outcome": "REJECT",
            "host_admission_ref": copy.deepcopy(host_ref),
            "review_authority": {
                "required": True,
                "status": "APPROVE_CANONICAL",
                "independent_session": True,
                "reviewer_receipt_ref": copy.deepcopy(reviewer_ref),
            },
            "lesson": {
                "mechanism_pattern": "ordering information and tradable payer proof are separate obligations",
                "payer_or_constraint": "forced execution under persistent mandate constraints",
                "estimand": "cross-sectional ordering",
                "mathematical_object": "path empirical measure",
                "invariant_or_boundary": "legal information time and frozen payoff horizon",
                "observation_mapping": "legal path statistics through t",
                "expected_signature": "interaction only when the objective constraint binds",
                "falsifier": "effect persists without the constraint proxy",
                "counterexample": "positive IC with no after-cost long payoff",
                "reuse_boundary": "use to propose tests, never as current-factor evidence",
                "historical_context": "source episode is retained but not used as the retrieval key",
            },
        },
        {
            "experience_id": "exp_conditional",
            "layer": "conditional_realization",
            "source_ref": copy.deepcopy(source_ref),
            "source_factor_id": "prior_factor_conditional",
            "source_report_id": "PRIOR_CONDITIONAL",
            "source_outcome": "REJECT",
            "host_admission_ref": copy.deepcopy(host_ref),
            "review_authority": {
                "required": True,
                "status": "APPROVE_CANONICAL",
                "independent_session": True,
                "reviewer_receipt_ref": copy.deepcopy(reviewer_ref),
            },
            "lesson": {
                "structural_lesson_id": "exp_structural",
                "condition_kind": "cost_recovery_boundary",
                "causal_condition": "signal half-life is shorter than cost recovery time",
                "measurable_diagnostic": "half-life crossed with frozen cost model",
                "expected_interaction_signature": "gross information survives while net long payoff vanishes",
                "enabling_or_suppressing": "suppressing",
                "condition_falsifier": "net payoff survives despite half-life below cost recovery",
                "reuse_boundary": "condition a falsifier only when the current mechanism preregisters this boundary",
                "historical_context": "the source market state is descriptive, not routing authority",
            },
        },
        {
            "experience_id": "exp_episode",
            "layer": "historical_episode",
            "source_ref": copy.deepcopy(source_ref),
            "source_factor_id": "prior_factor_episode",
            "source_report_id": "PRIOR_EPISODE",
            "source_outcome": "REJECT",
            "host_admission_ref": copy.deepcopy(host_ref),
            "review_authority": {
                "required": False,
                "status": "HOST_SIGNED_EPISODE_NO_STRUCTURAL_AUTHORITY",
                "independent_session": False,
                "reviewer_receipt_ref": None,
            },
            "lesson": {
                "window": "2024-01-01 through 2025-03-31",
                "assets": "eligible A-share universe",
                "institutional_rules": "T+1 and frozen eligibility rules",
                "participant_structure": "mandate-constrained and patient liquidity providers",
                "event_timeline": ["constraint proxy rose", "tail interaction appeared", "cost erased net payoff"],
                "state_variables": ["constraint_proxy", "tail_occupation", "liquidity"],
                "predicted_vs_observed": "ordering matched but net long payoff failed",
                "layered_verdict": "information survived; payer and tradability did not validate",
                "causal_role": "challenger",
            },
        },
    ]
    mappings = [
        {
            "mapping_id": "map_structural",
            "source_experience_id": "exp_structural",
            "source_layer": "structural_lesson",
            "target_delta_id": "delta_path_interaction",
            "source_to_target": {
                "payer_or_constraint": "forced execution maps to mandate-driven tail activity",
                "estimand": "cross-sectional ordering maps without change",
                "mathematical_object": "path empirical measure maps to tail-conditioned occupation interaction",
                "invariant_or_boundary": "legal information time and horizon remain frozen",
                "observation_mapping": "legal path statistics map to signed activity and tail occupation",
            },
            "preserved_invariants": ["estimand", "information time", "payoff horizon"],
            "broken_assumptions": ["baseline additivity"],
            "boundary_review": "current payer proxy remains unvalidated and cannot be inherited",
            "transferred_prediction": "the new term must vanish when the constraint proxy is absent",
            "distinguishing_test": "constraint interaction against public-attention placebo",
            "disposition": "adopted_for_test_only",
            "use_limit": "may alter questions and tests only",
            "performance_score_used_for_ranking": False,
            "regime_match_required": False,
            "current_factor_evidence": False,
        },
        {
            "mapping_id": "map_conditional",
            "source_experience_id": "exp_conditional",
            "source_layer": "conditional_realization",
            "target_delta_id": "delta_path_interaction",
            "source_to_target": {
                "payer_or_constraint": "cost recovery boundary maps to the frozen current cost model",
                "estimand": "ordering remains separate from monetization",
                "mathematical_object": "half-life diagnostic maps to the extension response kernel",
                "invariant_or_boundary": "frozen cost and horizon policies remain fixed",
                "observation_mapping": "IS response decay maps to legal lag diagnostics",
            },
            "preserved_invariants": ["cost model", "estimand"],
            "broken_assumptions": ["information persistence exceeds cost recovery"],
            "boundary_review": "apply only if the current extension predicts decay dependence",
            "transferred_prediction": "gross ordering can survive while net long payoff fails",
            "distinguishing_test": "preregistered half-life versus frozen cost recovery diagnostic",
            "disposition": "challenge_only",
            "use_limit": "cannot choose a branch or change the budget",
            "performance_score_used_for_ranking": False,
            "regime_match_required": False,
            "current_factor_evidence": False,
        },
        {
            "mapping_id": "map_episode",
            "source_experience_id": "exp_episode",
            "source_layer": "historical_episode",
            "target_delta_id": "delta_path_interaction",
            "source_to_target": {
                "payer_or_constraint": "historical constrained flow is only an episode comparison",
                "estimand": "historical ordering metric is not current proof",
                "mathematical_object": "episode path statistics are context only",
                "invariant_or_boundary": "institutional rules are recorded as provenance",
                "observation_mapping": "historical proxy definitions must be revalidated",
            },
            "preserved_invariants": ["provenance", "layered verdict semantics"],
            "broken_assumptions": ["market participants and rules may differ"],
            "boundary_review": "no regime label can authorize a current transfer",
            "transferred_prediction": "none; episode supplies a counterexample context",
            "distinguishing_test": "compare current predicted signature without conditioning on a regime label",
            "disposition": "context_only",
            "use_limit": "historical context cannot select or reject the current mechanism",
            "performance_score_used_for_ranking": False,
            "regime_match_required": False,
            "current_factor_evidence": False,
        },
    ]
    transfer = with_content_hash(
        {
            "contract_version": EXPERIENCE_TRANSFER_BUNDLE_VERSION,
            "artifact_identity": copy.deepcopy(identity),
            "authority_guard": _authority_guard(),
            "artifact_authority": _artifact_authority(
                "Knowledge Librarian",
                "mechanism_first_advisory_transfer_only",
                "SOURCE_AUTHORITY_VERIFIED",
                host_ref,
            ),
            "mechanism_delta_ref": {
                "path": paths["mechanism_delta"],
                "sha256": artifact_sha256(delta),
            },
            "economic_backprojection_ref": {
                "path": paths["economic_backprojection"],
                "sha256": artifact_sha256(backprojection),
            },
            "retrieval_policy": {
                "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
                "blind_derivation_completed": True,
                "primary_retrieval_key": "mechanism_fingerprint",
                "retrieval_lanes": [
                    "structural_isomorph",
                    "cross_math_analogy",
                    "near_miss_failure",
                    "direct_counterexample",
                    "historical_episode_context",
                ],
                "market_regime_role": "historical_context_or_preregistered_boundary_only",
                "regime_shortcut_allowed": False,
                "historical_score_used_for_ranking": False,
                "current_factor_proof_authority": False,
                "memory_state": "ADMISSIBLE_MEMORY_FOUND",
                "cold_start_reason": None,
                "retrieval_evidence_refs": [copy.deepcopy(retrieval_ref)],
            },
            "mechanism_fingerprint": copy.deepcopy(mechanism_fingerprint),
            "experiences": experiences,
            "transfer_mappings": mappings,
            "status": "ADVISORY_TRANSFER_REVIEWED",
        }
    )

    uses = []
    for mapping in mappings:
        disposition = mapping["disposition"]
        effect = {
            "adopted_for_test_only": "test_order_changed",
            "challenge_only": "counterexample_added",
            "context_only": "historical_context_recorded",
            "mapping_rejected": "mapping_rejected",
        }[disposition]
        uses.append(
            {
                "mapping_id": mapping["mapping_id"],
                "disposition": disposition,
                "research_effect": effect,
                "generated_test_id": f"test_{mapping['mapping_id']}",
                "preregistration_ref": copy.deepcopy(prereg_ref),
                "changed_research_question_or_test": disposition != "mapping_rejected",
                "current_factor_evidence": False,
                "threshold_change": False,
                "estimand_change": False,
                "trial_budget_change": False,
                "oos_access": False,
                "skill_or_validator_change": False,
            }
        )
    receipt = with_content_hash(
        {
            "contract_version": TRANSFER_USE_RECEIPT_VERSION,
            "artifact_identity": copy.deepcopy(identity),
            "authority_guard": _authority_guard(),
            "artifact_authority": _artifact_authority(
                "Host Research Director",
                "host_recorded_advisory_use_no_factor_authority",
                "INDEPENDENT_REVIEW_APPROVED",
                host_ref,
            ),
            "transfer_bundle_ref": {
                "path": paths["experience_transfer_bundle"],
                "sha256": artifact_sha256(transfer),
            },
            "mechanism_delta_ref": {
                "path": paths["mechanism_delta"],
                "sha256": artifact_sha256(delta),
            },
            "receipt_id": "transfer_receipt_001",
            "transfer_mode": "MAPPINGS_USED",
            "host_action": {
                "actor_role": "Host Research Director",
                "action": "RECORDED_ADVISORY_USE",
                "host_receipt_ref": copy.deepcopy(host_ref),
            },
            "reviewer_action": {
                "decision": "APPROVE_ADVISORY_USE",
                "independent_session": True,
                "reviewer_receipt_ref": copy.deepcopy(reviewer_ref),
            },
            "uses": uses,
            "outcome_recording": {
                "status": "CURRENT_FACTOR_OUTCOME_NOT_INFERRED",
                "factor_verdict": "NOT_ISSUED",
                "promotion_authority": False,
                "canonical_memory_write": False,
            },
            "status": "HOST_RECORDED_REVIEWED_ADVISORY_USE",
        }
    )
    return {
        "feedback_ledger": feedback,
        "mechanism_delta": delta,
        "economic_backprojection": backprojection,
        "experience_transfer_bundle": transfer,
        "transfer_use_receipt": receipt,
    }


def _refresh(payload: dict) -> dict:
    payload.pop("content_sha256", None)
    payload.update(with_content_hash(payload))
    return payload


def _as_cold_start(
    artifacts: dict[str, dict], root: Path | None = None
) -> dict[str, dict]:
    result = copy.deepcopy(artifacts)
    transfer = result["experience_transfer_bundle"]
    transfer["artifact_authority"][
        "independent_review_status"
    ] = "RETRIEVAL_PROVENANCE_VERIFIED_NO_SOURCE"
    transfer["retrieval_policy"]["memory_state"] = (
        "COLD_START_NO_ADMISSIBLE_MEMORY"
    )
    transfer["retrieval_policy"]["cold_start_reason"] = (
        "the hash-bound role-memory and factor-knowledge queries returned zero "
        "admissible reviewed lessons"
    )
    if root is not None:
        retrieval_ref = transfer["retrieval_policy"]["retrieval_evidence_refs"][0]
        retrieval_path = root / retrieval_ref["path"]
        retrieval_payload = json.loads(retrieval_path.read_text(encoding="utf-8"))
        retrieval_payload["admissible_hit_count"] = 0
        retrieval_path.write_text(
            json.dumps(retrieval_payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        retrieval_ref["sha256"] = sha256_file(retrieval_path)
    transfer["experiences"] = []
    transfer["transfer_mappings"] = []
    transfer["status"] = "COLD_START_RECORDED_NO_TRANSFER"
    _refresh(transfer)

    receipt = result["transfer_use_receipt"]
    receipt["artifact_authority"][
        "independent_review_status"
    ] = "NOT_REQUIRED_VERIFIED_COLD_START"
    receipt["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    receipt["transfer_mode"] = "COLD_START_NO_TRANSFER"
    receipt["host_action"]["action"] = "RECORDED_COLD_START_NO_TRANSFER"
    receipt["reviewer_action"] = {
        "decision": "NOT_REQUIRED_COLD_START",
        "independent_session": False,
        "reviewer_receipt_ref": None,
    }
    receipt["uses"] = []
    receipt["status"] = "HOST_RECORDED_COLD_START_NO_TRANSFER"
    _refresh(receipt)
    return result


def test_complete_bundle_validates_and_cli_materializes_deterministically(tmp_path: Path) -> None:
    root = tmp_path / "factor_workspace"
    artifacts = _build_bundle(root)
    assert validate_evo_v2_bundle(
        artifacts,
        workspace_root=root,
        report_id=REPORT_ID,
    ) == []

    inputs = root / "inputs"
    inputs.mkdir()
    source_paths: dict[str, Path] = {}
    for name, payload in artifacts.items():
        path = inputs / f"{name}.json"
        path.write_bytes(canonical_json_bytes(payload))
        source_paths[name] = path
    write_command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "write_factorforge_evo_v2.py"),
        "--workspace-root",
        str(root),
        "--report-id",
        REPORT_ID,
        "--feedback-ledger",
        str(source_paths["feedback_ledger"]),
        "--mechanism-delta",
        str(source_paths["mechanism_delta"]),
        "--economic-backprojection",
        str(source_paths["economic_backprojection"]),
        "--experience-transfer-bundle",
        str(source_paths["experience_transfer_bundle"]),
        "--transfer-use-receipt",
        str(source_paths["transfer_use_receipt"]),
    ]
    first = subprocess.run(write_command, cwd=REPO_ROOT, text=True, capture_output=True)
    assert first.returncode == 0, first.stderr
    second = subprocess.run(write_command, cwd=REPO_ROOT, text=True, capture_output=True)
    assert second.returncode == 0, second.stderr
    validation = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "validate_factorforge_evo_v2.py"),
            "--workspace-root",
            str(root),
            "--report-id",
            REPORT_ID,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert validation.returncode == 0, validation.stderr
    report = json.loads(validation.stdout)
    assert report["verdict"] == "PASS"
    assert report["formal_factor_verdict"] == "NOT_ISSUED"
    assert report["canonical_write_allowed"] is False


def test_cold_start_with_hash_bound_search_proof_is_valid(tmp_path: Path) -> None:
    root = tmp_path / "cold_start_workspace"
    artifacts = _as_cold_start(_build_bundle(root), root)
    assert validate_evo_v2_bundle(
        artifacts,
        workspace_root=root,
        report_id=REPORT_ID,
    ) == []
    assert artifacts["experience_transfer_bundle"]["experiences"] == []
    assert artifacts["experience_transfer_bundle"]["transfer_mappings"] == []
    assert artifacts["transfer_use_receipt"]["uses"] == []


def test_empty_experience_lists_without_explicit_cold_start_are_invalid(
    tmp_path: Path,
) -> None:
    artifacts = _build_bundle(tmp_path)
    transfer = copy.deepcopy(artifacts["experience_transfer_bundle"])
    transfer["experiences"] = []
    transfer["transfer_mappings"] = []
    _refresh(transfer)
    reasons = validate_experience_transfer_bundle(
        transfer,
        mechanism_delta=artifacts["mechanism_delta"],
        economic_backprojection=artifacts["economic_backprojection"],
        verify_refs=False,
    )
    assert any("experiences.list_minimum_3" in reason for reason in reasons)
    assert any("transfer_mappings.list_minimum_3" in reason for reason in reasons)


def test_cold_start_without_search_proof_or_reason_is_invalid(tmp_path: Path) -> None:
    artifacts = _as_cold_start(_build_bundle(tmp_path))
    transfer = copy.deepcopy(artifacts["experience_transfer_bundle"])
    transfer["retrieval_policy"]["cold_start_reason"] = ""
    transfer["retrieval_policy"]["retrieval_evidence_refs"] = []
    _refresh(transfer)
    reasons = validate_experience_transfer_bundle(
        transfer,
        mechanism_delta=artifacts["mechanism_delta"],
        economic_backprojection=artifacts["economic_backprojection"],
        verify_refs=False,
    )
    assert any("cold_start_reason.nonempty_string_required" in reason for reason in reasons)


def test_cold_start_cannot_hide_an_admissible_memory_hit(tmp_path: Path) -> None:
    root = tmp_path / "false_cold_start"
    artifacts = _as_cold_start(_build_bundle(root))
    reasons = validate_evo_v2_bundle(
        artifacts,
        workspace_root=root,
        report_id=REPORT_ID,
    )
    assert any(
        "cold_start_requires_zero_admissible_hits" in reason
        for reason in reasons
    )


def test_closed_shape_rejects_unknown_nested_field(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    feedback = copy.deepcopy(artifacts["feedback_ledger"])
    feedback["qualification"]["agent_note"] = "unauthorized open shape"
    _refresh(feedback)
    reasons = validate_feedback_ledger(feedback, verify_refs=False)
    assert any("qualification.unexpected_fields:agent_note" in reason for reason in reasons)


def test_authority_guard_rejects_self_modifying_skill_or_threshold(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    delta = copy.deepcopy(artifacts["mechanism_delta"])
    delta["authority_guard"]["mutation_permissions"]["skill"] = True
    delta["minimal_extension"]["minimality_evidence"]["no_threshold_change"] = False
    _refresh(delta)
    reasons = validate_mechanism_delta(
        delta,
        feedback_ledger=artifacts["feedback_ledger"],
        verify_refs=False,
    )
    assert any("mutation_permissions.skill.must_be_false" in reason for reason in reasons)
    assert any("no_threshold_change.must_be_true" in reason for reason in reasons)


def test_regime_shortcut_cannot_select_experience(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    transfer = copy.deepcopy(artifacts["experience_transfer_bundle"])
    transfer["retrieval_policy"]["primary_retrieval_key"] = "market_regime"
    transfer["retrieval_policy"]["regime_shortcut_allowed"] = True
    transfer["transfer_mappings"][0]["regime_match_required"] = True
    _refresh(transfer)
    reasons = validate_experience_transfer_bundle(
        transfer,
        mechanism_delta=artifacts["mechanism_delta"],
        economic_backprojection=artifacts["economic_backprojection"],
        verify_refs=False,
    )
    assert any("primary_retrieval_key.invalid" in reason for reason in reasons)
    assert any("regime_shortcut_allowed.must_be_false" in reason for reason in reasons)
    assert any("regime_match_required.must_be_false" in reason for reason in reasons)


def test_dirac_extension_requires_unique_prediction(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    delta = copy.deepcopy(artifacts["mechanism_delta"])
    delta["distinctive_predictions"][0]["unique_to_extension"] = False
    _refresh(delta)
    reasons = validate_mechanism_delta(
        delta,
        feedback_ledger=artifacts["feedback_ledger"],
        verify_refs=False,
    )
    assert any("unique_to_extension.must_be_true" in reason for reason in reasons)


def test_unresolved_lower_layer_cannot_be_qualified(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    feedback = copy.deepcopy(artifacts["feedback_ledger"])
    feedback["lower_layer_clearance"][1]["status"] = "OPEN"
    feedback["qualification"]["lower_layers_cleared"] = False
    _refresh(feedback)
    reasons = validate_feedback_ledger(feedback, verify_refs=False)
    assert any("status.not_cleared" in reason for reason in reasons)
    assert any("lower_layers_cleared.must_be_true" in reason for reason in reasons)


def test_oos_cannot_be_reused_for_contradiction_or_transfer(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    feedback = copy.deepcopy(artifacts["feedback_ledger"])
    feedback["contradiction"]["uses_oos"] = True
    feedback["qualification"]["oos_reused"] = True
    _refresh(feedback)
    feedback_reasons = validate_feedback_ledger(feedback, verify_refs=False)
    assert any("contradiction.uses_oos.must_be_false" in reason for reason in feedback_reasons)
    assert any("qualification.oos_reused.must_be_false" in reason for reason in feedback_reasons)

    receipt = copy.deepcopy(artifacts["transfer_use_receipt"])
    receipt["uses"][0]["oos_access"] = True
    _refresh(receipt)
    receipt_reasons = validate_transfer_use_receipt(
        receipt,
        transfer_bundle=artifacts["experience_transfer_bundle"],
        mechanism_delta=artifacts["mechanism_delta"],
        verify_refs=False,
    )
    assert any("oos_access.must_be_false" in reason for reason in receipt_reasons)


def test_estimand_mutation_is_not_a_minimal_extension(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    delta = copy.deepcopy(artifacts["mechanism_delta"])
    delta["baseline_model"]["estimand_id"] = "different_estimand"
    _refresh(delta)
    reasons = validate_mechanism_delta(
        delta,
        feedback_ledger=artifacts["feedback_ledger"],
        verify_refs=False,
    )
    assert "mechanism_delta.baseline_model.estimand_changed" in reasons


def test_historical_episode_has_no_normative_transfer_authority(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    transfer = copy.deepcopy(artifacts["experience_transfer_bundle"])
    transfer["transfer_mappings"][2]["disposition"] = "adopted_for_test_only"
    _refresh(transfer)
    reasons = validate_experience_transfer_bundle(
        transfer,
        mechanism_delta=artifacts["mechanism_delta"],
        economic_backprojection=artifacts["economic_backprojection"],
        verify_refs=False,
    )
    assert any("historical_episode.cannot_authorize_adoption" in reason for reason in reasons)


def test_structural_and_conditional_lessons_require_independent_review(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    transfer = copy.deepcopy(artifacts["experience_transfer_bundle"])
    transfer["experiences"][0]["review_authority"]["independent_session"] = False
    _refresh(transfer)
    reasons = validate_experience_transfer_bundle(
        transfer,
        mechanism_delta=artifacts["mechanism_delta"],
        economic_backprojection=artifacts["economic_backprojection"],
        verify_refs=False,
    )
    assert any("review_authority.independent_session.must_be_true" in reason for reason in reasons)


def test_path_and_hash_binding_rejects_repointed_artifact(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    artifacts = _build_bundle(root)
    delta = copy.deepcopy(artifacts["mechanism_delta"])
    delta["feedback_ref"]["path"] = "support/is_evidence.json"
    delta["feedback_ref"]["sha256"] = sha256_file(root / "support" / "is_evidence.json")
    artifacts["mechanism_delta"] = _refresh(delta)
    reasons = validate_evo_v2_bundle(
        artifacts,
        workspace_root=root,
        report_id=REPORT_ID,
    )
    assert "bundle.mechanism_delta.feedback_ref.canonical_path_required" in reasons


def test_economic_backprojection_cannot_claim_payer_validation(tmp_path: Path) -> None:
    artifacts = _build_bundle(tmp_path)
    backprojection = copy.deepcopy(artifacts["economic_backprojection"])
    backprojection["qualification"]["payer_validated"] = True
    _refresh(backprojection)
    reasons = validate_economic_backprojection(
        backprojection,
        mechanism_delta=artifacts["mechanism_delta"],
        verify_refs=False,
    )
    assert any("payer_validated.must_be_false" in reason for reason in reasons)
