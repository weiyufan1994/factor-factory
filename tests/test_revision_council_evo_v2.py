from __future__ import annotations

import copy
from pathlib import Path

import pytest

from factor_factory.evo_v2 import (
    ECONOMIC_BACKPROJECTION_VERSION,
    FEEDBACK_LEDGER_VERSION,
    MECHANISM_DELTA_VERSION,
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_relative_paths,
    with_content_hash,
)
from factor_factory.revision_council.evo_v2 import (
    COUNCIL_EVO_V2_CONTRACT_VERSION,
    NO_DERIVED_LAW_CONTRACT_VERSION,
    proposal_law_sha256,
    validate_council_evo_v2_intake,
    validate_revision_council_evo_v2,
)
from factor_factory.revision_council.validator import (
    validate_revision_council_proposal,
)
from tests.test_factorforge_evo_v2 import REPORT_ID, _build_bundle


def _refresh(payload: dict) -> None:
    payload.pop("content_sha256", None)
    payload.update(with_content_hash(payload))


def _law() -> dict:
    return {
        "revision_model_layer": "primary_math_mechanism",
        "law_statement": "add one tail-occupation interaction to the baseline",
        "expected_metric_change": [
            "the preregistered interaction appears in purged IS",
            "the alias residual stays flat",
        ],
        "falsification_tests": ["two-way component ablation"],
        "kill_criteria": ["the joint term is observationally redundant"],
    }


def _authority() -> dict:
    return {
        "mode": "review_only",
        "human_approval_required": True,
        "human_approval_status": "PENDING_EXTERNAL_HUMAN_APPROVAL",
        "execution_allowed": False,
        "canonical_write_allowed": False,
        "factor_verdict_authority": False,
        "selection_policy": "contradiction_resolution_and_model_discrimination_only",
        "score_based_selection_allowed": False,
        "majority_vote_allowed": False,
        "regime_shortcut_allowed": False,
        "consumed_oos_reuse_allowed": False,
        "constitutional_mutation_allowed": False,
        "protected_surfaces": [
            "skill",
            "validator",
            "permissions",
            "thresholds",
            "oos_policy",
            "estimand",
            "trial_budget",
        ],
    }


def _proposal_and_payload(root: Path) -> tuple[dict, dict, dict[str, dict]]:
    artifacts = _build_bundle(root)
    paths = evo_v2_relative_paths(REPORT_ID)
    law = _law()
    delta_id = artifacts["mechanism_delta"]["minimal_extension"]["delta_id"]
    proposal = {
        "report_id": REPORT_ID,
        "candidate_revision_laws": [law],
    }
    payload = {
        "contract_version": COUNCIL_EVO_V2_CONTRACT_VERSION,
        "intake_gate": {
            "contradiction_id": artifacts["feedback_ledger"]["contradiction"][
                "contradiction_id"
            ],
            "source_state": "QUALIFIED_CONTRADICTION",
            "validity_quarantine": {
                "state": "VALIDITY_QUARANTINE",
                "status": "CLEARED",
                "unresolved_blockers": [],
                "qualified_feedback_ref": {
                    "path": paths["feedback_ledger"],
                    "sha256": artifact_sha256(artifacts["feedback_ledger"]),
                },
            },
        },
        "authority": _authority(),
        "feedback_ledger": artifacts["feedback_ledger"],
        "derivation_outcome": {
            "outcome": "MINIMAL_MECHANISM_DELTA",
            "mechanism_delta": artifacts["mechanism_delta"],
            "economic_backprojection": artifacts["economic_backprojection"],
            "no_derived_law": None,
        },
        "proposal_law_binding": {
            "law_index": 0,
            "law_sha256": proposal_law_sha256(law),
            "delta_id": delta_id,
        },
    }
    proposal["evo_v2"] = payload
    return proposal, payload, artifacts


def _no_derived_proof(contradiction_id: str) -> dict:
    return {
        "contract_version": NO_DERIVED_LAW_CONTRACT_VERSION,
        "contradiction_id": contradiction_id,
        "attempted_derivations": [
            {
                "operator_family": "minimal_interaction_extension",
                "assumption_or_boundary_tested": "baseline additivity",
                "attempted_minimal_extension": "one path-state interaction",
                "baseline_recovery_test": "lambda to zero recovers the baseline",
                "discriminating_prediction_test": "joint ablation is not unique",
                "failure_reason": "the extension is observationally aliased",
            },
            {
                "operator_family": "boundary_condition_relaxation",
                "assumption_or_boundary_tested": "constant decay boundary",
                "attempted_minimal_extension": "one state-dependent decay term",
                "baseline_recovery_test": "constant decay recovers the baseline",
                "discriminating_prediction_test": "decay signature is not identified",
                "failure_reason": "the legal observations cannot identify the boundary",
            },
        ],
        "unresolved_proof_obligations": [
            "no extension produces a prediction distinct from the alias model"
        ],
        "additional_evidence_required": [
            "a preregistered legal proxy that separates the mechanisms"
        ],
        "status": "NO_DERIVED_LAW_REVIEW_ONLY",
        "factor_verdict": "NOT_ISSUED",
        "branch_execution_allowed": False,
        "human_approval_required": True,
    }


def test_council_uses_core_contract_versions_as_single_semantic_authority(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)

    assert payload["feedback_ledger"]["contract_version"] == FEEDBACK_LEDGER_VERSION
    assert (
        payload["derivation_outcome"]["mechanism_delta"]["contract_version"]
        == MECHANISM_DELTA_VERSION
    )
    assert (
        payload["derivation_outcome"]["economic_backprojection"]["contract_version"]
        == ECONOMIC_BACKPROJECTION_VERSION
    )
    assert validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    ) == []


@pytest.mark.parametrize(
    "field",
    [
        "replicated_in_purged_is",
        "multiplicity_controlled",
        "materiality_pass",
        "discriminates_models",
        "lower_layers_cleared",
    ],
)
def test_core_qualification_flags_fail_closed(tmp_path: Path, field: str) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    feedback = payload["feedback_ledger"]
    feedback["qualification"][field] = False
    _refresh(feedback)

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert any(
        reason.startswith("BLOCK_COUNCIL_EVO_V2_CORE_ARTIFACT_INVALID:")
        and field in reason
        for reason in reasons
    )


def test_validity_quarantine_and_qualified_state_are_both_required(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    payload["intake_gate"]["validity_quarantine"]["status"] = "OPEN"
    payload["feedback_ledger"]["current_state"] = "LOWER_LAYER_QUARANTINE"
    _refresh(payload["feedback_ledger"])

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert "BLOCK_COUNCIL_EVO_V2_INTAKE_NOT_QUALIFIED" in reasons
    assert any("current_state.not_qualified" in reason for reason in reasons)


def test_validity_quarantine_clearance_binds_exact_qualified_feedback(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    payload["intake_gate"]["validity_quarantine"]["qualified_feedback_ref"][
        "sha256"
    ] = "0" * 64

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )


def test_feedback_mutation_after_quarantine_clearance_breaks_intake_binding(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    payload["feedback_ledger"]["qualification"]["materiality_pass"] = False
    _refresh(payload["feedback_ledger"])

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert (
        "BLOCK_COUNCIL_EVO_V2_INTAKE_NOT_QUALIFIED:qualified_feedback_ref"
        in reasons
    )
    assert any("materiality_pass.must_be_true" in reason for reason in reasons)

    assert (
        "BLOCK_COUNCIL_EVO_V2_INTAKE_NOT_QUALIFIED:qualified_feedback_ref"
        in reasons
    )


def test_prediction_and_evidence_ref_readback_is_not_a_self_attestation(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    feedback = payload["feedback_ledger"]
    feedback["hypothesis_predictions"][0]["preregistration_ref"]["sha256"] = "0" * 64
    _refresh(feedback)

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert any("preregistration_ref.sha256_mismatch" in reason for reason in reasons)


def test_minimal_extension_and_economic_backprojection_delegate_to_core(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    delta = payload["derivation_outcome"]["mechanism_delta"]
    delta["minimal_extension"]["recovery_check"]["recovers_baseline"] = False
    delta["minimal_extension"]["minimality_evidence"]["no_estimand_change"] = False
    _refresh(delta)
    backprojection = payload["derivation_outcome"]["economic_backprojection"]
    backprojection["economic_mapping"]["no_story_without_proxy"] = False
    backprojection["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    _refresh(backprojection)

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert any("recovers_baseline.must_be_true" in reason for reason in reasons)
    assert any("no_estimand_change.must_be_true" in reason for reason in reasons)
    assert any("no_story_without_proxy.must_be_true" in reason for reason in reasons)


def test_proposal_law_hash_and_delta_id_are_exactly_bound(tmp_path: Path) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    proposal["candidate_revision_laws"][0]["law_statement"] = "post-hash mutation"

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert "BLOCK_COUNCIL_EVO_V2_PROPOSAL_LAW_BINDING_INVALID" in reasons


def test_unbound_second_candidate_law_cannot_enter_minimal_delta_branch(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    proposal["candidate_revision_laws"].append(copy.deepcopy(_law()))

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert "BLOCK_COUNCIL_EVO_V2_PROPOSAL_LAW_BINDING_INVALID" in reasons


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("score_based_selection_allowed", True),
        ("majority_vote_allowed", True),
        ("regime_shortcut_allowed", True),
        ("consumed_oos_reuse_allowed", True),
        ("constitutional_mutation_allowed", True),
        ("human_approval_required", False),
        ("execution_allowed", True),
    ],
)
def test_council_authority_is_review_only_and_human_gated(
    tmp_path: Path, field: str, unsafe_value: object
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    payload["authority"][field] = unsafe_value

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert "BLOCK_COUNCIL_EVO_V2_AUTHORITY_INVALID" in reasons


def test_candidate_law_cannot_smuggle_score_or_majority_selection(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    proposal["candidate_revision_laws"][0]["selection_score"] = 0.99
    payload["proposal_law_binding"]["law_sha256"] = proposal_law_sha256(
        proposal["candidate_revision_laws"][0]
    )

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert any(
        reason.startswith("BLOCK_COUNCIL_EVO_V2_FORBIDDEN_SHORTCUT:")
        for reason in reasons
    )


@pytest.mark.parametrize(
    ("alias", "value"),
    [
        ("weighted_performance_score", 99),
        ("majority_result_label", "selected"),
        ("regime_routing_enabled", True),
        ("reuse_consumed_oos_for_branch", True),
        ("validator_mutation_permission", True),
    ],
)
def test_shortcut_aliases_do_not_fail_open(
    tmp_path: Path, alias: str, value: object
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    proposal["candidate_revision_laws"][0][alias] = value
    payload["proposal_law_binding"]["law_sha256"] = proposal_law_sha256(
        proposal["candidate_revision_laws"][0]
    )

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert any(
        reason.startswith("BLOCK_COUNCIL_EVO_V2_FORBIDDEN_SHORTCUT:")
        for reason in reasons
    )


def test_no_derived_law_is_a_legal_review_only_outcome(tmp_path: Path) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    contradiction_id = payload["intake_gate"]["contradiction_id"]
    proposal["candidate_revision_laws"] = []
    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": _no_derived_proof(contradiction_id),
    }
    payload["proposal_law_binding"] = None

    assert validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    ) == []


def test_no_derived_law_requires_diverse_failed_derivations(tmp_path: Path) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    contradiction_id = payload["intake_gate"]["contradiction_id"]
    proof = _no_derived_proof(contradiction_id)
    proof["attempted_derivations"][1]["operator_family"] = proof[
        "attempted_derivations"
    ][0]["operator_family"]
    proposal["candidate_revision_laws"] = []
    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": proof,
    }
    payload["proposal_law_binding"] = None

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert "BLOCK_COUNCIL_EVO_V2_NO_DERIVED_LAW_INVALID:operator_diversity" in reasons


def test_no_derived_law_cannot_carry_a_hidden_candidate_law(tmp_path: Path) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    contradiction_id = payload["intake_gate"]["contradiction_id"]
    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": _no_derived_proof(contradiction_id),
    }
    payload["proposal_law_binding"] = None

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert (
        "BLOCK_COUNCIL_EVO_V2_DERIVATION_OUTCOME_INVALID:"
        "candidate_laws_must_be_empty"
    ) in reasons


def test_core_artifacts_may_be_canonical_path_hash_refs(tmp_path: Path) -> None:
    proposal, payload, artifacts = _proposal_and_payload(tmp_path)
    paths = evo_v2_relative_paths(REPORT_ID)
    for name in ("feedback_ledger", "mechanism_delta", "economic_backprojection"):
        path = tmp_path / paths[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(artifacts[name]))
    payload["feedback_ledger"] = {
        "path": paths["feedback_ledger"],
        "sha256": artifact_sha256(artifacts["feedback_ledger"]),
    }
    payload["derivation_outcome"]["mechanism_delta"] = {
        "path": paths["mechanism_delta"],
        "sha256": artifact_sha256(artifacts["mechanism_delta"]),
    }
    payload["derivation_outcome"]["economic_backprojection"] = {
        "path": paths["economic_backprojection"],
        "sha256": artifact_sha256(artifacts["economic_backprojection"]),
    }

    assert validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    ) == []


def test_core_artifact_ref_requires_canonical_path_and_hash(tmp_path: Path) -> None:
    proposal, payload, artifacts = _proposal_and_payload(tmp_path)
    wrong_path = tmp_path / "copied_feedback.json"
    wrong_path.write_bytes(canonical_json_bytes(artifacts["feedback_ledger"]))
    payload["feedback_ledger"] = {
        "path": "copied_feedback.json",
        "sha256": artifact_sha256(artifacts["feedback_ledger"]),
    }

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert (
        "BLOCK_COUNCIL_EVO_V2_CORE_ARTIFACT_REF_INVALID:feedback_ledger:canonical_binding"
        in reasons
    )


def test_workspace_is_required_for_real_ref_readback(tmp_path: Path) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)

    reasons = validate_council_evo_v2_intake(payload, proposal=proposal)

    assert "BLOCK_COUNCIL_EVO_V2_WORKSPACE_REQUIRED" in reasons


def test_malformed_identity_and_non_json_law_fail_closed_without_exception(
    tmp_path: Path,
) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    payload["feedback_ledger"]["artifact_identity"]["report_id"] = "../escape"
    proposal["candidate_revision_laws"][0]["not_json"] = {"set"}

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert "BLOCK_COUNCIL_EVO_V2_PROPOSAL_LAW_BINDING_INVALID" in reasons
    assert any(
        reason.startswith("BLOCK_COUNCIL_EVO_V2_CORE_ARTIFACT_INVALID:")
        or reason.startswith("BLOCK_COUNCIL_EVO_V2_INTAKE_NOT_QUALIFIED:")
        for reason in reasons
    )


def test_legacy_proposal_is_optional_but_formal_council_can_require_evo_v2() -> None:
    proposal = {"report_id": REPORT_ID}

    assert validate_revision_council_evo_v2(proposal) == []
    assert validate_revision_council_evo_v2(proposal, required=True) == [
        "BLOCK_COUNCIL_EVO_V2_MISSING"
    ]
    reasons = validate_revision_council_proposal(
        proposal, evo_v2_required=True
    )
    assert "BLOCK_COUNCIL_EVO_V2_MISSING" in reasons


def test_envelope_and_no_derived_proof_are_closed_shape(tmp_path: Path) -> None:
    proposal, payload, _ = _proposal_and_payload(tmp_path)
    payload["agent_note"] = "open shapes are not authority"

    reasons = validate_council_evo_v2_intake(
        payload, proposal=proposal, workspace_root=tmp_path
    )

    assert any(
        reason.startswith("BLOCK_COUNCIL_EVO_V2_CONTRACT_INVALID:unexpected_fields")
        for reason in reasons
    )
