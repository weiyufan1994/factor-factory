from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from factor_factory.epistemic_host_bootstrap import load_frozen_bootstrap_contracts
from factor_factory.epistemic_host_bootstrap_expectation_proposal import (
    B0B1_R2_MANIFEST_SHA256,
    EXPECTED_CANDIDATE_COUNTS,
    EXPECTED_GLOBAL_RANGES,
    PROPOSAL_STATUS,
    EpistemicExpectationProposalError,
    build_expectation_proposal_inventory,
    build_expectation_proposal_report,
    compile_candidate_definition_generation_target,
    compile_closed_steward_review_schema_bundle,
    compile_dual_git_review_handoff,
    compile_expectation_assignment_proposal,
    compile_expectation_semantic_derivation_registry,
    require_expectation_activation,
    validate_e1_r10_predecessor_packet,
    validate_e1_r10_review_dependency_packet,
    validate_e1_r11_predecessor_packet,
    validate_e1_r11_review_dependency_packet,
    validate_e1_r12_predecessor_packet,
    validate_e1_r12_review_dependency_packet,
    validate_e1_r13_predecessor_packet,
    validate_e1_r13_review_dependency_packet,
    validate_e1_r9_predecessor_packet,
    validate_e1_r9_review_dependency_packet,
    validate_expectation_assignment_proposal,
    validate_closed_steward_review_schema_bundle,
    validate_expectation_semantic_derivation_registry,
    write_expectation_proposal_packet,
)
from factor_factory.research_org.rfc8785_canonical import canonicalize, framed_sha256


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_ROOT = REPO_ROOT.parent
R2_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-graph-v2-p1a-authorization-binding-"
    "successor-r2-20260827/packet_manifest.json"
)
O0_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-graph-v2-p1a-operating-prefix-handoff-"
    "o0-20260827/packet_manifest.json"
)
O0_PRIME_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-graph-v2-p1a-operating-prefix-handoff-"
    "o0-prime-review-20260828/packet_manifest.json"
)
B0B1_R2_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-b0b-scaffold-r2-"
    "20260828/packet_manifest.json"
)
E1_R3_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r3-20260828/packet_manifest.json"
)
E1_R4_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r4-20260828/packet_manifest.json"
)
E1_R5_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r5-20260828/packet_manifest.json"
)
E1_R6_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r6-20260828/packet_manifest.json"
)
E1_R7_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r7-20260828/packet_manifest.json"
)
E1_R8_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r8-20260828/packet_manifest.json"
)
E1_R9_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r9-20260828/packet_manifest.json"
)
E1_R9_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r9-review-20260828/packet_manifest.json"
)
E1_R10_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r10-20260828/packet_manifest.json"
)
E1_R10_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r10-review-20260828/packet_manifest.json"
)
E1_R11_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r11-20260828/packet_manifest.json"
)
E1_R11_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r11-review-20260828/packet_manifest.json"
)
E1_R12_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r12-20260828/packet_manifest.json"
)
E1_R12_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r12-review-20260828/packet_manifest.json"
)
E1_R13_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r13-20260828/packet_manifest.json"
)
E1_R13_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r13-review-20260828/packet_manifest.json"
)


def _frozen_contracts():
    required = (
        R2_MANIFEST,
        O0_MANIFEST,
        O0_PRIME_MANIFEST,
        B0B1_R2_MANIFEST,
        E1_R3_MANIFEST,
        E1_R4_MANIFEST,
        E1_R5_MANIFEST,
        E1_R6_MANIFEST,
        E1_R7_MANIFEST,
        E1_R8_MANIFEST,
        E1_R9_MANIFEST,
        E1_R9_REVIEW_MANIFEST,
        E1_R10_MANIFEST,
        E1_R10_REVIEW_MANIFEST,
        E1_R11_MANIFEST,
        E1_R11_REVIEW_MANIFEST,
        E1_R12_MANIFEST,
        E1_R12_REVIEW_MANIFEST,
        E1_R13_MANIFEST,
        E1_R13_REVIEW_MANIFEST,
    )
    if not all(path.is_file() for path in required):
        pytest.skip("manifest-bound expectation-proposal lineage is not staged")
    assert hashlib.sha256(B0B1_R2_MANIFEST.read_bytes()).hexdigest() == (
        B0B1_R2_MANIFEST_SHA256
    )
    return load_frozen_bootstrap_contracts(
        stage1b_repo_root=REPO_ROOT,
        r2_manifest_path=R2_MANIFEST,
        o0_manifest_path=O0_MANIFEST,
        o0_prime_manifest_path=O0_PRIME_MANIFEST,
    )


@functools.lru_cache(maxsize=1)
def _compile_all():
    contracts = _frozen_contracts()
    semantic_registry = compile_expectation_semantic_derivation_registry(
        contracts,
        b0b1_r2_manifest_path=B0B1_R2_MANIFEST,
        e1_r3_manifest_path=E1_R3_MANIFEST,
        e1_r4_manifest_path=E1_R4_MANIFEST,
        e1_r5_manifest_path=E1_R5_MANIFEST,
        e1_r6_manifest_path=E1_R6_MANIFEST,
        e1_r7_manifest_path=E1_R7_MANIFEST,
        e1_r8_manifest_path=E1_R8_MANIFEST,
        e1_r9_manifest_path=E1_R9_MANIFEST,
        e1_r9_review_manifest_path=E1_R9_REVIEW_MANIFEST,
        e1_r10_manifest_path=E1_R10_MANIFEST,
        e1_r10_review_manifest_path=E1_R10_REVIEW_MANIFEST,
        e1_r11_manifest_path=E1_R11_MANIFEST,
        e1_r11_review_manifest_path=E1_R11_REVIEW_MANIFEST,
        e1_r12_manifest_path=E1_R12_MANIFEST,
        e1_r12_review_manifest_path=E1_R12_REVIEW_MANIFEST,
        e1_r13_manifest_path=E1_R13_MANIFEST,
        e1_r13_review_manifest_path=E1_R13_REVIEW_MANIFEST,
    )
    proposal = compile_expectation_assignment_proposal(
        contracts,
        b0b1_r2_manifest_path=B0B1_R2_MANIFEST,
        e1_r3_manifest_path=E1_R3_MANIFEST,
        e1_r4_manifest_path=E1_R4_MANIFEST,
        e1_r5_manifest_path=E1_R5_MANIFEST,
        e1_r6_manifest_path=E1_R6_MANIFEST,
        e1_r7_manifest_path=E1_R7_MANIFEST,
        e1_r8_manifest_path=E1_R8_MANIFEST,
        e1_r9_manifest_path=E1_R9_MANIFEST,
        e1_r9_review_manifest_path=E1_R9_REVIEW_MANIFEST,
        e1_r10_manifest_path=E1_R10_MANIFEST,
        e1_r10_review_manifest_path=E1_R10_REVIEW_MANIFEST,
        e1_r11_manifest_path=E1_R11_MANIFEST,
        e1_r11_review_manifest_path=E1_R11_REVIEW_MANIFEST,
        e1_r12_manifest_path=E1_R12_MANIFEST,
        e1_r12_review_manifest_path=E1_R12_REVIEW_MANIFEST,
        e1_r13_manifest_path=E1_R13_MANIFEST,
        e1_r13_review_manifest_path=E1_R13_REVIEW_MANIFEST,
        semantic_registry=semantic_registry,
    )
    definition_target = compile_candidate_definition_generation_target(
        semantic_registry=semantic_registry,
        proposal=proposal,
    )
    schema_bundle = compile_closed_steward_review_schema_bundle(
        semantic_registry=semantic_registry,
        proposal=proposal,
        definition_target=definition_target,
    )
    handoff = compile_dual_git_review_handoff(
        proposal,
        semantic_registry=semantic_registry,
        definition_target=definition_target,
        schema_bundle=schema_bundle,
    )
    inventory = build_expectation_proposal_inventory(REPO_ROOT)
    report = build_expectation_proposal_report(
        contracts=contracts,
        b0b1_r2_manifest_path=B0B1_R2_MANIFEST,
        e1_r3_manifest_path=E1_R3_MANIFEST,
        e1_r4_manifest_path=E1_R4_MANIFEST,
        e1_r5_manifest_path=E1_R5_MANIFEST,
        e1_r6_manifest_path=E1_R6_MANIFEST,
        e1_r7_manifest_path=E1_R7_MANIFEST,
        e1_r8_manifest_path=E1_R8_MANIFEST,
        e1_r9_manifest_path=E1_R9_MANIFEST,
        e1_r9_review_manifest_path=E1_R9_REVIEW_MANIFEST,
        e1_r10_manifest_path=E1_R10_MANIFEST,
        e1_r10_review_manifest_path=E1_R10_REVIEW_MANIFEST,
        e1_r11_manifest_path=E1_R11_MANIFEST,
        e1_r11_review_manifest_path=E1_R11_REVIEW_MANIFEST,
        e1_r12_manifest_path=E1_R12_MANIFEST,
        e1_r12_review_manifest_path=E1_R12_REVIEW_MANIFEST,
        e1_r13_manifest_path=E1_R13_MANIFEST,
        e1_r13_review_manifest_path=E1_R13_REVIEW_MANIFEST,
        semantic_registry=semantic_registry,
        proposal=proposal,
        definition_target=definition_target,
        schema_bundle=schema_bundle,
        handoff=handoff,
        inventory=inventory,
    )
    return (
        contracts,
        semantic_registry,
        proposal,
        definition_target,
        schema_bundle,
        handoff,
        inventory,
        report,
    )


def _assert_object_schemas_closed(node) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
        for value in node.values():
            _assert_object_schemas_closed(value)
    elif isinstance(node, list):
        for value in node:
            _assert_object_schemas_closed(value)


def test_exact160_candidate_assignments_and_exact170_branches() -> None:
    _, semantic_registry, proposal, _, _, _, _, _ = _compile_all()
    proposal_rows = proposal["candidate_assignment_rows"]
    semantic_rows = semantic_registry["semantic_derivation_rows"]
    assert proposal["proposal_status"] == PROPOSAL_STATUS
    assert len(proposal_rows) == len(semantic_rows) == 160
    assert [row["proposal_ordinal"] for row in proposal_rows] == list(range(160))
    assert [row["global_obligation_ordinal"] for row in proposal_rows] == list(
        range(10, 170)
    )
    assert proposal["candidate_fail_count"] == 99
    assert proposal["candidate_blocked_count"] == 61
    assert proposal["branch_selection_review_required_count"] == 10
    assert proposal["input_availability_sensitive_row_count"] == 11
    assert sum(row["closed_branch_count"] for row in semantic_rows) == 170
    assert {
        source: sum(
            row["closed_branch_count"]
            for row in semantic_rows
            if row["source_contract_ordinal"] == source
        )
        for source in range(1, 5)
    } == {1: 42, 2: 50, 3: 43, 4: 35}
    for source, (lower, upper) in EXPECTED_GLOBAL_RANGES.items():
        rows = [
            row
            for row in proposal_rows
            if row["source_contract_ordinal"] == source
        ]
        assert [row["global_obligation_ordinal"] for row in rows] == list(
            range(lower, upper + 1)
        )
        assert sum(row["candidate_verdict"] == "FAIL" for row in rows) == (
            EXPECTED_CANDIDATE_COUNTS[source]["FAIL"]
        )
        assert sum(row["candidate_verdict"] == "BLOCKED" for row in rows) == (
            EXPECTED_CANDIDATE_COUNTS[source]["BLOCKED"]
        )
        assert sum(
            row["branch_selection_review_state"] == "REVIEW_REQUIRED"
            for row in rows
        ) == EXPECTED_CANDIDATE_COUNTS[source][
            "BRANCH_SELECTION_REVIEW_REQUIRED"
        ]


def test_exact10_branch_selection_and_exact11_input_sensitivity() -> None:
    _, semantic_registry, proposal, _, _, _, _, _ = _compile_all()
    semantic_rows = semantic_registry["semantic_derivation_rows"]
    review_coordinates = {
        (row["source_contract_ordinal"], row["source_vector_ordinal"])
        for row in semantic_rows
        if row["branch_selection_review_state"] == "REVIEW_REQUIRED"
    }
    assert review_coordinates == {
        (1, 0),
        (1, 17),
        (1, 18),
        (1, 21),
        (1, 22),
        (1, 35),
        (4, 3),
        (4, 10),
        (4, 14),
        (4, 15),
    }
    sensitive_coordinates = {
        (row["source_contract_ordinal"], row["source_vector_ordinal"])
        for row in semantic_rows
        if row["input_availability_sensitivity"]
        == "REVIEW_NOTE__NOT_A_BRANCH_ALTERNATIVE"
    }
    assert sensitive_coordinates == {
        (2, 9),
        (2, 12),
        (2, 13),
        (2, 15),
        (2, 22),
        (2, 25),
        (2, 27),
        (2, 28),
        (2, 34),
        (2, 41),
        (2, 49),
    }
    assert all(
        row["closed_branch_count"] == 1
        and row["branch_selection_review_state"] == "NOT_REQUIRED"
        for row in semantic_rows
        if row["input_availability_sensitivity"]
        == "REVIEW_NOTE__NOT_A_BRANCH_ALTERNATIVE"
    )
    assert sum(
        row["branch_selection_review_state"] == "REVIEW_REQUIRED"
        for row in proposal["candidate_assignment_rows"]
    ) == 10


def test_materialization_designs_are_row_specific_and_nonauthorizing() -> None:
    _, semantic_registry, _, _, _, _, _, _ = _compile_all()
    designs = [
        branch["materialization_design"]
        for row in semantic_registry["semantic_derivation_rows"]
        for branch in row["closed_branch_universe"]
    ]
    assert len(designs) == 170
    assert len({design["design_id"] for design in designs}) == 170
    for design in designs:
        core = copy.deepcopy(design)
        expected_sha256 = core.pop("content_sha256")
        assert framed_sha256("FF_E1_MATERIALIZATION_DESIGN_V1", core) == (
            expected_sha256
        )
        locator = design["target_locator"]
        assert locator["contract_law_pointer"] == design["contract_law_pointer"]
        assert locator["vector_pointer"].startswith("/")
        assert locator["vector_name_const"]
        assert locator["zero_or_multiple_match_result"] == "BLOCKED"
        assert locator["caller_override_allowed"] is False
        assert design["exact_delta_count"] == 1
        assert design["delta"]["operator_arity"] == 2
        evidence = design["expanded_evidence_profile"]
        assert set(evidence["required_evidence"]).isdisjoint(
            evidence["forbidden_evidence"]
        )
        assert design["materialized"] is False
        assert design["executed"] is False
        assert design["materialization_ready"] is False
        assert design["authority_effect"] == "NONE"
    recomputed_manifest = hashlib.sha256(
        b"FF_E1_MATERIALIZATION_DESIGN_MANIFEST_V1\x00"
        + b"".join(bytes.fromhex(design["content_sha256"]) for design in designs)
    ).hexdigest()
    assert recomputed_manifest == semantic_registry[
        "closed_materialization_design_manifest_sha256"
    ]


def test_source3_precas_rows_structurally_forbid_postcas_evidence() -> None:
    _, semantic_registry, _, _, _, _, _, _ = _compile_all()
    rows = [
        row
        for row in semantic_registry["semantic_derivation_rows"]
        if row["source_contract_ordinal"] == 3
        and 12 <= row["source_vector_ordinal"] <= 18
    ]
    assert len(rows) == 7
    for row in rows:
        assert row["closed_branch_count"] == 1
        design = row["closed_branch_universe"][0]["materialization_design"]
        assert design["materialization_phase"] == "PRE_CAS_ONLY"
        assert design["realized_post_cas_evidence_allowed"] is False
        assert design["operator_evaluates_schema_or_dependency_graph_only"] is True
        evidence = design["expanded_evidence_profile"]
        assert evidence["base_profile_id"] == "S3_PRECAS_STRICT"
        assert {
            "REALIZED_POST_CAS_NATIVE_RECEIPT",
            "REALIZED_POST_CAS_RESULT",
            "REALIZED_POST_CAS_REREAD",
            "REALIZED_POST_CAS_STATE",
            "REALIZED_POST_ROOT",
            "COMPLETION_RECORD",
            "VALIDATOR_SUCCESSOR_EVIDENCE",
        }.issubset(evidence["forbidden_evidence"])


def test_resolved_blocked_branches_do_not_claim_unresolved_evidence() -> None:
    _, semantic_registry, _, _, _, _, _, _ = _compile_all()
    expected = {(1, 35), (4, 3), (4, 10), (4, 14), (4, 15)}
    rows = {
        (row["source_contract_ordinal"], row["source_vector_ordinal"]): row
        for row in semantic_registry["semantic_derivation_rows"]
    }
    for coordinate in expected:
        branch = rows[coordinate]["closed_branch_universe"][0]
        assert branch["resolution_class"] == "RESOLVED_BLOCKED_STATE"
        assert branch["candidate_verdict"] == "BLOCKED"
        assert branch["evidence_availability_profile"] == (
            "ALL_REQUIRED_TYPED_INPUTS_RESOLVED_TO_BLOCKING_STATE"
        )
        design = branch["materialization_design"]
        assert design["delta"]["evaluation_operator_id"] == (
            "RESOLVED_RELATION_MUST_EVALUATE_BLOCKED"
        )
        assert design["delta"]["designed_observed_relation_state"] == (
            "RESOLVED_BLOCKING_STATE"
        )
        evidence = design["expanded_evidence_profile"]
        assert any(
            value.startswith("RESOLVED_BLOCKING_STATE_PROOF::")
            for value in evidence["required_evidence"]
        )
        assert not any(
            value.startswith("NONCALLER_RESOLUTION_NEGATIVE_PROOF::")
            for value in evidence["required_evidence"]
        )


def test_candidate_definition_target_and_closed_schema_bundle() -> None:
    _, semantic_registry, _, target, schema_bundle, _, _, _ = _compile_all()
    assert target["selected_branch_row_count"] == 160
    assert target["branch_selection_target_row_count"] == 10
    assert target["closed_materialization_design_count"] == 170
    assert target["future_candidate_definition_generation_id"] is None
    assert target["future_candidate_definition_generation_content_sha256"] is None
    assert target["candidate_only"] is True
    assert target["is_definition"] is False
    assert target["may_activate"] is False
    assert target["may_materialize_or_execute"] is False
    assert target["authority_effect"] == "NONE"
    assert schema_bundle["schema_count"] == 36
    for schema in schema_bundle["schemas"].values():
        Draft202012Validator.check_schema(schema)
        _assert_object_schemas_closed(schema)
    Draft202012Validator(
        schema_bundle["schemas"]["candidate_definition_target"]
    ).validate(target)
    Draft202012Validator(
        schema_bundle["schemas"]["materialization_design_registry_projection"]
    ).validate(semantic_registry)
    assert len(
        schema_bundle["schemas"]["synthetic_fixture_envelope"]["oneOf"]
    ) == 170
    assert len(
        schema_bundle["schemas"]["field_provenance_compiler_fixture"]["oneOf"]
    ) == 50
    assert len(
        schema_bundle["schemas"]["signed_steward_decision_envelope"]["oneOf"]
    ) == 2
    assert schema_bundle["candidate_steward_signature_profile_registry"][
        "profile_activated_count"
    ] == 0
    assert "candidate_definition_generation_successor" in schema_bundle["schemas"]
    assert "dual_git_definition_review_conjunction" in schema_bundle["schemas"]
    assert "fixture_validation_request" in schema_bundle["schemas"]
    assert "external_binding_subject" in schema_bundle["schemas"]
    assert "external_binding_resolution_successor" in schema_bundle["schemas"]
    assert "profile_activation_successor" in schema_bundle["schemas"]
    assert "purpose_specific_operating_authorization" in schema_bundle["schemas"]
    assert "signing_authority_binding_successor" in schema_bundle["schemas"]
    assert {
        "cas_consumption_pre_state",
        "cas_consumption_transition",
        "cas_consumption_post_state",
        "cas_consumption_receipt",
    }.issubset(schema_bundle["schemas"])
    tampered = copy.deepcopy(target)
    tampered["unexpected"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(
            schema_bundle["schemas"]["candidate_definition_target"]
        ).validate(tampered)
    assert schema_bundle["runtime_materialized"] is False
    assert schema_bundle["fixture_materialization_allowed"] is False
    assert schema_bundle["semantic_execution_allowed"] is False
    assert schema_bundle["authority_effect"] == "NONE"


def test_local_fixture_validator_profile_and_draft_report_design_are_closed() -> None:
    _, semantic_registry, _, _, schema_bundle, _, _, _ = _compile_all()
    registry = schema_bundle["candidate_fixture_validator_profile_registry"]
    assert registry["profile_count"] == 1
    assert registry["activated_profile_count"] == 0
    profile = registry["profiles"][0]
    assert profile["profile_id"] == "FF_E1_SYNTHETIC_FIXTURE_VALIDATOR_V1"
    assert profile["profile_status"] == (
        "CANDIDATE_INACTIVE__LOCAL_NONAUTHORITATIVE"
    )
    assert len(profile["ordered_validation_steps"]) == 15
    assert profile["actual_validator_principal_id"] is None
    assert profile["trusted_execution_measurement_sha256"] is None
    assert profile["validator_execution_authorization_ref"] is None
    assert profile["deployment_binding_state"] == "UNBOUND_BLOCKING"
    assert profile["profile_activated"] is False
    assert profile["network_allowed"] is False
    assert profile["canonical_memory_allowed"] is False
    assert profile["oos_allowed"] is False
    assert profile["skill_rag_runtime_allowed"] is False
    projection_schema = schema_bundle["schemas"][
        "fixture_validation_input_projection"
    ]
    report_schema = schema_bundle["schemas"][
        "local_fixture_draft_conformance_report"
    ]
    assert len(projection_schema["oneOf"]) == 170
    assert len(report_schema["oneOf"]) == 14
    assert len(profile["ordered_raw_input_fields"]) == len(
        set(profile["ordered_raw_input_fields"])
    )
    assert set(profile["ordered_raw_input_fields"]).issubset(
        projection_schema["oneOf"][0]["properties"]
    )
    design_digests = {
        branch["properties"]["materialization_design_content_sha256"]["const"]
        for branch in projection_schema["oneOf"]
    }
    assert design_digests == {
        branch["materialization_design"]["content_sha256"]
        for row in semantic_registry["semantic_derivation_rows"]
        for branch in row["closed_branch_universe"]
    }
    pass_branch = report_schema["oneOf"][0]
    assert pass_branch["properties"]["report_class"]["const"] == (
        "LOCAL_DRAFT_CONFORMANCE_REPORT__NOT_A_RECEIPT"
    )
    assert pass_branch["properties"]["overall_result"]["const"] == (
        "LOCAL_STRUCTURAL_PASS__NOT_EXECUTION"
    )
    assert pass_branch["properties"]["formal_receipt"]["const"] is False
    assert pass_branch["properties"]["admission_eligible"]["const"] is False
    assert pass_branch["properties"]["may_materialize"]["const"] is False
    assert pass_branch["properties"]["may_execute"]["const"] is False
    assert pass_branch["properties"]["authority_effect"]["const"] == "NONE"
    assert {
        branch["properties"]["first_failed_predicate_ordinal"].get("const")
        for branch in report_schema["oneOf"][1:]
    } == set(range(13))


def test_local_fixture_validation_digest_and_negative_registries_recompute() -> None:
    _, _, _, _, schema_bundle, _, _, _ = _compile_all()
    registry = schema_bundle["candidate_fixture_validator_profile_registry"]
    profile = copy.deepcopy(registry["profiles"][0])
    expected_profile_sha256 = profile.pop("profile_content_sha256")
    assert framed_sha256(
        "FF_E1_SYNTHETIC_FIXTURE_VALIDATOR_PROFILE_V1", profile
    ) == expected_profile_sha256
    assert registry["profile_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_SYNTHETIC_FIXTURE_VALIDATOR_PROFILE_MANIFEST_V1\x00"
        + bytes.fromhex(expected_profile_sha256)
    ).hexdigest()
    negative = schema_bundle[
        "candidate_fixture_validation_negative_design_registry"
    ]
    assert negative["negative_family_count"] == 86
    independent_sod_negative_families = {
        "INDEPENDENT_SOD_VALIDATOR_BINDING_MISSING",
        "INDEPENDENT_SOD_VALIDATOR_EQUALS_EXACT4_ROLE",
        "INDEPENDENT_SOD_VALIDATOR_BINDING_ALIAS",
        "INDEPENDENT_SOD_VALIDATOR_CLAIMED_DISTINCT_WITHOUT_EXACT4X7",
    }
    assert independent_sod_negative_families.issubset(
        {row["negative_family_id"] for row in negative["negative_rows"]}
    )
    assert all(
        row["target_schema_id"]
        == "factorforge_e1_r11_independent_sod_validation_receipt_v1"
        and row["expected_local_result"] == "BLOCKED"
        and row["materialized"] is False
        and row["executed"] is False
        for row in negative["negative_rows"]
        if row["negative_family_id"] in independent_sod_negative_families
    )
    cas_negative_targets = {
        row["negative_family_id"]: (
            row["target_schema_id"],
            row["target_schema_branch_ordinal"],
            row["target_instance_json_pointer"],
        )
        for row in negative["negative_rows"]
        if row["negative_family_id"].startswith("CAS_")
    }
    assert cas_negative_targets == {
        "CAS_SAME_QUAD_DIFFERENT_AUTHORIZATION_SUBJECT": (
            "factorforge_e1_external_binding_resolution_successor_v1",
            0,
            "/subject_content_sha256",
        ),
        "CAS_RAW_READBACK_ALTERNATE_RESOLVER_PROFILE": (
            "factorforge_e1_r11_cas_raw_readback_resolver_output_v1",
            0,
            "/resolver_profile_id",
        ),
        "CAS_RAW_READBACK_ALTERNATE_DIGEST_DOMAIN": (
            "factorforge_e1_r11_cas_raw_readback_resolver_output_v1",
            0,
            "/content_sha256_operand/digest_domain",
        ),
        "CAS_RAW_READBACK_ALTERNATE_SOURCE_POINTER": (
            "factorforge_e1_r11_cas_raw_readback_resolver_output_v1",
            0,
            "/source_ref_json_pointer",
        ),
    }
    cross_splice = next(
        row
        for row in negative["negative_rows"]
        if row["negative_family_id"]
        == "EVIDENCE_ASSIGNMENT_TUPLE_CROSS_ROW_SPLICE"
    )
    assert cross_splice["target_predicate_ordinal"] == 8
    assert cross_splice["target_instance_json_pointer"] == (
        "/evidence_payload/evidence_authority_assignment_tuple"
    )
    assert cross_splice["target_schema_nested_branch_path"] == [
        {
            "container_json_pointer": "/evidence_payload",
            "branch_ordinal": 0,
            "discriminator_json_pointer": "/evidence_subject_kind",
            "discriminator_const": "SYNTHETIC_POSITIVE_RESOLUTION_PROOF",
        }
    ]
    assert cross_splice["expected_local_result"] == "BLOCKED"
    within_row = next(
        row
        for row in negative["negative_rows"]
        if row["negative_family_id"]
        == "EVIDENCE_WITHIN_ROW_TARGET_FIELD_SUBSTITUTION"
    )
    assert within_row["target_predicate_ordinal"] == 8
    assert within_row["target_instance_json_pointer"] == (
        "/evidence_payload/proof_obligation_id"
    )
    assert within_row["expected_local_result"] == "BLOCKED"
    formal_uplift = next(
        row
        for row in negative["negative_rows"]
        if row["negative_family_id"]
        == "EVIDENCE_FORMAL_OR_OPERATING_FLAG_UPLIFT"
    )
    assert formal_uplift["target_instance_json_pointer"] == "/formal_evidence"
    assert formal_uplift["target_schema_nested_branch_path"] == []
    assert negative["materialized_count"] == 0
    assert negative["executed_count"] == 0
    gate_registry = schema_bundle[
        "closed_negative_first_failure_gate_registry"
    ]
    assert gate_registry["gate_count"] == 16
    assert [row["gate_ordinal"] for row in gate_registry["ordered_gate_rows"]] == list(
        range(16)
    )
    assert gate_registry["actual_first_failure_receipt_count"] == 0
    meta_registry = schema_bundle["closed_negative_meta_design_registry"]
    assert meta_registry["meta_family_count"] == 24
    assert meta_registry["materialized_count"] == 0
    assert meta_registry["executed_count"] == 0
    signature_selection = schema_bundle[
        "closed_negative_signed_derivation_signature_selection_registry"
    ]
    assert signature_selection["selection_row_count"] == 11
    assert [
        row["ordinal"] for row in signature_selection["ordered_selection_rows"]
    ] == list(range(11))
    assert all(
        row["selection_match_count"] == 1
        and row["caller_or_ambient_profile_selection_allowed"] is False
        for row in signature_selection["ordered_selection_rows"]
    )
    donor_crosswalk = schema_bundle[
        "closed_negative_donor_content_profile_crosswalk_registry"
    ]
    donor_selector_universe = {
        (
            role["donor_schema_id"],
            role["donor_branch_ordinal"],
            role["donor_generation_profile_id"],
            role["required_baseline_validation_profile_id"],
        )
        for row in negative["negative_rows"]
        for role in row["donor_plan"]["ordered_donor_roles"]
    }
    crosswalk_selector_universe = {
        (
            row["donor_schema_id"],
            row["donor_branch_ordinal"],
            row["donor_generation_profile_id"],
            row["baseline_validator_profile_id"],
        )
        for row in donor_crosswalk["ordered_crosswalk_rows"]
    }
    assert donor_selector_universe == crosswalk_selector_universe
    assert len(
        schema_bundle["schemas"][
            "negative_donor_baseline_validation_report"
        ]["oneOf"]
    ) == donor_crosswalk["crosswalk_row_count"]
    assert len(
        schema_bundle["schemas"][
            "negative_donor_content_profile_selection_receipt"
        ]["oneOf"]
    ) == donor_crosswalk["crosswalk_row_count"]
    outer_digest_authority = schema_bundle[
        "closed_digest_profile_authority_registry"
    ]
    central_authority = outer_digest_authority[
        "runtime_profile_definition_authority"
    ]
    assert central_authority["profile_id_and_definition_sha256_selection_cardinality"] == (
        "EXACTLY_ONE"
    )
    definition_by_id = {
        row["profile_id"]: (ordinal, row)
        for ordinal, row in enumerate(
            central_authority["ordered_profile_definitions"]
        )
    }
    assert central_authority["profile_definition_count"] == 59
    assert central_authority["subordinate_projection_only"] is True
    assert central_authority["normative_formula_present"] is False
    assert central_authority["formula_mirror_count"] == 0
    assert central_authority["digest_dependency_cycle_count"] == 0
    assert central_authority["back_reference_allowed"] is False
    forbidden_semantics_fields = {
        "domain",
        "digest_kind",
        "canonicalization",
        "formula",
        "hash_construction",
        "ordered_preimage_fields",
        "ordered_preimage_field_selection",
        "exclusion_rule",
        "depends_on_profile_ids",
        "ordered_child_digest_profile_ids",
    }
    for ordinal, definition in enumerate(
        central_authority["ordered_profile_definitions"]
    ):
        assert definition["ordinal"] == ordinal
        assert not forbidden_semantics_fields.intersection(definition)
        preimage = dict(definition)
        observed = preimage.pop("profile_content_sha256")
        assert observed == framed_sha256(
            "FF_E1_R13_RUNTIME_PROFILE_SELECTION_DEFINITION_V1",
            preimage,
        )
    assert central_authority["profile_definition_manifest_sha256"] == (
        hashlib.sha256(
            b"FF_E1_R13_RUNTIME_PROFILE_SELECTION_DEFINITION_MANIFEST_V1\0"
            + b"".join(
                bytes.fromhex(row["profile_content_sha256"])
                for row in central_authority["ordered_profile_definitions"]
            )
        ).hexdigest()
    )
    outer_profile_by_id = {
        row["profile_id"]: row
        for row in outer_digest_authority["ordered_profiles"]
    }
    definition_meta = outer_profile_by_id[
        "FF_E1_R13_RUNTIME_PROFILE_SELECTION_DEFINITION_V1"
    ]
    manifest_meta = outer_profile_by_id[
        "FF_E1_R13_RUNTIME_PROFILE_SELECTION_DEFINITION_MANIFEST_V1"
    ]
    assert definition_meta["exact_target_binding_count"] == 59
    assert manifest_meta["exact_target_binding_count"] == 1
    assert (
        "FF_E1_R13_RUNTIME_PROFILE_SELECTION_DEFINITION_V1"
        not in definition_by_id
    )
    assert (
        "FF_E1_R13_RUNTIME_PROFILE_SELECTION_DEFINITION_MANIFEST_V1"
        not in definition_by_id
    )
    parent_bindings = central_authority[
        "ordered_parent_profile_authority_bindings"
    ]
    assert central_authority["parent_profile_authority_binding_count"] == 59
    assert central_authority["parent_profile_match_count"] == 59
    assert len(parent_bindings) == 59
    for definition, binding in zip(
        central_authority["ordered_profile_definitions"],
        parent_bindings,
        strict=True,
    ):
        parent = outer_profile_by_id[definition["profile_id"]]
        assert binding["ordinal"] == definition["parent_authority_binding_ordinal"]
        assert binding["subordinate_profile_id"] == definition["profile_id"]
        assert binding["subordinate_profile_content_sha256"] == definition[
            "profile_content_sha256"
        ]
        assert binding["parent_central_profile_id"] == parent["profile_id"]
        assert binding["parent_central_authority_binding_row_sha256"] == parent[
            "authority_binding_row_sha256"
        ]
        assert binding["parent_semantics_exact_match"] is True
        assert binding["parent_profile_match_count"] == 1
    for row in donor_crosswalk["ordered_crosswalk_rows"]:
        ordinal, definition = definition_by_id[
            row["actual_content_digest_profile_id"]
        ]
        assert row[
            "central_digest_profile_definition_authority_registry_id"
        ] == central_authority["registry_id"]
        assert row[
            "central_digest_profile_definition_manifest_sha256"
        ] == central_authority["profile_definition_manifest_sha256"]
        assert row["central_digest_profile_definition_row_ordinal"] == ordinal
        assert row["central_digest_profile_definition_json_pointer"].endswith(
            f"/{ordinal}"
        )
        assert row[
            "actual_content_digest_profile_definition_sha256"
        ] == definition["profile_content_sha256"]
        assert row["actual_content_digest_profile_definition_kind"] == (
            "SUBORDINATE_PROFILE_ID_SELECTION_DEFINITION"
        )
        assert row[
            "actual_content_digest_profile_parent_central_profile_id"
        ] == definition["profile_id"]
        assert row["actual_content_digest_profile_parent_match_count"] == 1
        assert row[
            "central_digest_profile_definition_exact_match_count"
        ] == 1
        assert "central_digest_profile_registry_manifest_sha256" not in row
    donor_selection_negatives = schema_bundle[
        "closed_negative_donor_profile_selection_negative_design_registry"
    ]
    assert donor_selection_negatives["negative_family_count"] == 11
    assert any(
        row["negative_family_id"]
        == "DONOR_CENTRAL_PROFILE_DEFINITION_AUTHORITY_MISMATCH"
        for row in donor_selection_negatives["ordered_negative_rows"]
    )
    assert {
        row["negative_family_id"]
        for row in donor_selection_negatives["ordered_negative_rows"]
    }.issuperset(
        {
            "DONOR_RUNTIME_DEFINITION_META_PROFILE_MISSING",
            "DONOR_RUNTIME_DEFINITION_META_PROFILE_ALTERNATE",
            "DONOR_RUNTIME_DEFINITION_FORMULA_OVERRIDE_ATTEMPT",
            "DONOR_RUNTIME_DEFINITION_PARENT_BINDING_MISMATCH",
            "DONOR_RUNTIME_DEFINITION_BACK_REFERENCE_CYCLE",
        }
    )
    assert all(
        row["profile_id"]
        != "FF_E1_R11_DONOR_CONTENT_PROFILE_BY_EXACT_SCHEMA_BRANCH_V1"
        for row in schema_bundle[
            "closed_digest_profile_authority_registry"
        ]["ordered_profiles"]
    )
    evidence_signature = next(
        row
        for row in negative["negative_rows"]
        if row["negative_family_id"]
        == "EVIDENCE_SIGNATURE_PREIMAGE_AUTHORITY_OR_USE_SITE_OMISSION"
    )
    assert evidence_signature["target_stage"] == "PREFLIGHT_SIGNATURE"
    assert evidence_signature["expected_first_failure_gate_ordinal"] == 1
    assert evidence_signature["replacement_derivation_contract"][
        "derivation_class"
    ] == "INTENTIONAL_SIGNATURE_DEFECT"

    schema_by_id = {
        schema["$id"]: schema for schema in schema_bundle["schemas"].values()
    }

    def _schema_leaf_pointers(
        schema_node: dict,
        *,
        pointer: str,
        nested_branch_ordinals: dict[str, int],
    ) -> list[str]:
        if "oneOf" in schema_node:
            branch_ordinal = nested_branch_ordinals.get(pointer)
            if branch_ordinal is None:
                if len(schema_node["oneOf"]) != 1:
                    return [pointer]
                branch_ordinal = 0
            return _schema_leaf_pointers(
                schema_node["oneOf"][branch_ordinal],
                pointer=pointer,
                nested_branch_ordinals=nested_branch_ordinals,
            )
        if "properties" in schema_node:
            leaves = []
            for property_name in sorted(schema_node["properties"]):
                encoded = property_name.replace("~", "~0").replace("/", "~1")
                leaves.extend(
                    _schema_leaf_pointers(
                        schema_node["properties"][property_name],
                        pointer=f"{pointer}/{encoded}",
                        nested_branch_ordinals=nested_branch_ordinals,
                    )
                )
            return leaves
        if "prefixItems" in schema_node:
            return [
                leaf
                for item_ordinal, item_schema in enumerate(
                    schema_node["prefixItems"]
                )
                for leaf in _schema_leaf_pointers(
                    item_schema,
                    pointer=f"{pointer}/{item_ordinal}",
                    nested_branch_ordinals=nested_branch_ordinals,
                )
            ]
        if "allOf" in schema_node:
            return sorted(
                {
                    leaf
                    for child_schema in schema_node["allOf"]
                    for leaf in _schema_leaf_pointers(
                        child_schema,
                        pointer=pointer,
                        nested_branch_ordinals=nested_branch_ordinals,
                    )
                }
            )
        return [pointer]

    leaf_pointer_cache: dict[tuple, list[str]] = {}
    for row in negative["negative_rows"]:
        core = copy.deepcopy(row)
        expected_row_sha256 = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_FIXTURE_VALIDATION_NEGATIVE_DESIGN_ROW_V1", core
        ) == expected_row_sha256
        assert row["expected_local_result"] == "BLOCKED"
        assert row["atomic_fault_count"] == 1
        assert row["mutation_operator_id"]
        assert row["target_contract_pointer"].startswith("/")
        assert row["target_schema_id"]
        assert row["target_schema_branch_ordinal"] >= 0
        assert row["target_instance_json_pointer"].startswith("/")
        assert row["target_occurrence_locator"][
            "expected_match_cardinality"
        ] == "EXACTLY_ONE"
        assert row["exact_mutation_descriptor"]["exact_delta_count"] == 1
        assert row["machine_operand_relation"]["operator_arity"] == 2
        assert [
            operand["operand_ordinal"]
            for operand in row["machine_operand_relation"]["ordered_operands"]
        ] == [0, 1]
        assert row["semantic_fault_count"] == 1
        assert row["donor_plan"]["donor_role_count"] >= 1
        assert row["donor_plan"]["current_donor_resolution_count"] == 0
        assert row["donor_plan"]["current_donor_ref"] is None
        assert row["replacement_derivation_contract"][
            "caller_selected_profile_or_value_allowed"
        ] is False
        assert row["preservation_projection"][
            "forbidden_second_semantic_fault"
        ] is True
        preservation = row["preservation_projection"]
        assert preservation["materialized"] is False
        target_schema = schema_by_id[row["target_schema_id"]]
        selected_branch = (
            target_schema["oneOf"][row["target_schema_branch_ordinal"]]
            if "oneOf" in target_schema
            else target_schema
        )
        nested_branch_ordinals = {
            nested["container_json_pointer"]: nested["branch_ordinal"]
            for nested in row["target_schema_nested_branch_path"]
        }
        target_pointer = row["target_instance_json_pointer"]
        leaf_cache_key = (
            row["target_schema_id"],
            row["target_schema_branch_ordinal"],
            json.dumps(
                row["target_schema_nested_branch_path"],
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if leaf_cache_key not in leaf_pointer_cache:
            leaf_pointer_cache[leaf_cache_key] = sorted(
                set(
                    _schema_leaf_pointers(
                        selected_branch,
                        pointer="",
                        nested_branch_ordinals=nested_branch_ordinals,
                    )
                )
            )
        derived_cascade_pointers = row["preservation_projection"][
            "ordered_derived_cascade_exclusion_json_pointers"
        ]
        expected_preserved_pointers = [
            pointer
            for pointer in leaf_pointer_cache[leaf_cache_key]
            if pointer != target_pointer
            and not pointer.startswith(f"{target_pointer}/")
            and pointer not in derived_cascade_pointers
        ]
        assert preservation["ordered_preserved_sibling_json_pointers"] == (
            expected_preserved_pointers
        )
        assert preservation["preserved_sibling_pointer_count"] == len(
            expected_preserved_pointers
        )
        manifest_preimage = preservation[
            "preserved_sibling_pointer_manifest_preimage"
        ]
        assert manifest_preimage[
            "ordered_preserved_sibling_json_pointers"
        ] == expected_preserved_pointers
        assert manifest_preimage["target_exclusion_json_pointer"] == (
            target_pointer
        )
        assert manifest_preimage[
            "ordered_derived_cascade_exclusion_json_pointers"
        ] == derived_cascade_pointers
        assert preservation["preserved_sibling_pointer_manifest_sha256"] == (
            hashlib.sha256(canonicalize(manifest_preimage)).hexdigest()
        )
        expected_manifest_content_sha256 = framed_sha256(
            "FF_E1_R11_NEGATIVE_SIBLING_POINTER_MANIFEST_V1",
            manifest_preimage,
        )
        assert preservation[
            "preserved_sibling_pointer_manifest_content_sha256"
        ] == expected_manifest_content_sha256
        assert preservation["preserved_sibling_pointer_manifest_ref"] == (
            f"ffinline-negative-siblings::{expected_manifest_content_sha256}"
        )
        assert preservation["before_artifact_ref"] is None
        assert preservation["before_sibling_projection_ref"] is None
        assert preservation["after_artifact_ref"] is None
        assert preservation["after_sibling_projection_ref"] is None
        assert row["preservation_projection"]["missing_or_mismatch_result"] == (
            "BLOCKED"
        )
        assert row["future_donor_resolution_receipt_ref"] is None
        assert row["future_derivation_receipt_ref"] is None
        assert row["future_first_failure_receipt_ref"] is None
        assert row["authority_effect"] == "NONE"
    sod_collision = next(
        row
        for row in negative["negative_rows"]
        if row["negative_family_id"] == "EVIDENCE_ISSUER_SOD_COLLISION"
    )
    sod_donor = sod_collision["donor_plan"]["ordered_donor_roles"][1]
    assert sod_donor["donor_branch_selector"]["sod_role_id"] == (
        "SYNTHETIC_PROOF_RESOLVER"
    )
    assert sod_donor["donor_branch_selector"]["exact_collision_axis"] == (
        "actual_installation_id"
    )
    cas_dual = next(
        row
        for row in negative["negative_rows"]
        if row["negative_family_id"]
        == "CAS_SAME_QUAD_DIFFERENT_AUTHORIZATION_SUBJECT"
    )
    assert cas_dual["donor_plan"]["donor_role_count"] == 2
    assert cas_dual["donor_plan"]["cas_exact2_same_quad_constraints"][
        "both_donors_require_independent_full_pass"
    ] is True
    assert negative["negative_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_FIXTURE_VALIDATION_NEGATIVE_DESIGN_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in negative["negative_rows"]
        )
    ).hexdigest()
    required_profiles = {
        "raw_artifact",
        "synthetic_fixture_content",
        "fixture_validator_profile_content",
        "fixture_validator_profile_manifest",
        "fixture_validation_input_projection",
        "negative_sibling_pointer_manifest",
        "negative_sibling_projection_content",
        "fixture_evidence_binding_row",
        "fixture_evidence_binding_manifest",
        "fixture_predicate_result_row",
        "fixture_predicate_result_manifest",
        "local_fixture_draft_report_preimage",
        "local_fixture_draft_report_id",
        "local_fixture_draft_report_content",
        "fixture_predicate_semantics_row",
        "fixture_predicate_semantics_manifest",
        "evidence_resolution_plan_row",
        "evidence_resolution_plan_manifest",
        "external_signature_profile_row",
        "external_signature_profile_manifest",
    }
    assert required_profiles.issubset(schema_bundle["digest_profiles"])


def test_r11_semantics_evidence_authority_and_phase_registries_are_closed() -> None:
    contracts, semantic_registry, _, _, schema_bundle, _, _, _ = _compile_all()
    semantics = schema_bundle["closed_fixture_predicate_semantics_registry"]
    assert semantics["predicate_count"] == 13
    assert [row["ordinal"] for row in semantics["ordered_predicate_semantics_rows"]] == list(range(13))
    assert semantics["predicate_semantics_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_FIXTURE_PREDICATE_SEMANTICS_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["semantics_row_sha256"])
            for row in semantics["ordered_predicate_semantics_rows"]
        )
    ).hexdigest()
    primitive_ids = {
        row["primitive_operator_id"]
        for row in schema_bundle[
            "closed_semantic_primitive_operator_registry"
        ]["ordered_primitive_rows"]
    }
    compatibility_rows = schema_bundle[
        "closed_semantic_primitive_compatibility_registry"
    ]["ordered_compatibility_rows"]
    compatibility_by_id = {
        row["primitive_operator_id"]: row for row in compatibility_rows
    }
    assert set(compatibility_by_id) == primitive_ids
    exact12_failure_precedence = [
        "MISSING",
        "ZERO_MATCH",
        "MULTI_MATCH",
        "UNPARSEABLE",
        "UNKNOWN_PROFILE_OR_ISSUER",
        "RAW_OR_CONTENT_DIGEST_MISMATCH",
        "SIGNATURE_OR_TRUST_INVALID",
        "EXPIRED",
        "REVOKED",
        "LINEAGE_OR_SCOPE_MISMATCH",
        "MEASUREMENT_MISMATCH",
        "SEMANTIC_MISMATCH",
    ]
    source_bindings = schema_bundle[
        "closed_semantic_source_binding_registry"
    ]
    source_binding_rows = source_bindings["ordered_source_binding_rows"]
    source_binding_by_id = {
        row["source_id"]: row for row in source_binding_rows
    }
    assert source_bindings["source_binding_row_count"] == 199
    assert source_bindings["unique_source_id_count"] == 199
    assert [row["ordinal"] for row in source_binding_rows] == list(range(199))
    assert len(source_binding_by_id) == 199
    resolver_profiles = schema_bundle[
        "closed_semantic_source_resolver_profile_registry"
    ]
    assert resolver_profiles["profile_count"] == 5
    assert resolver_profiles["activated_profile_count"] == 0
    assert resolver_profiles["runtime_materialized"] is False
    assert resolver_profiles["authority_effect"] == "NONE"
    resolver_profile_validator = Draft202012Validator(
        schema_bundle["schemas"]["semantic_source_resolver_profile"]
    )
    for profile in resolver_profiles["ordered_profile_rows"]:
        resolver_profile_validator.validate(profile)
    output_bindings = schema_bundle[
        "closed_semantic_source_resolver_output_binding_registry"
    ]
    assert output_bindings["output_binding_row_count"] == 199
    assert output_bindings["output_schema_branch_count"] == 199
    assert len(
        schema_bundle["schemas"]["semantic_source_resolver_output"]["oneOf"]
    ) == 199
    assert output_bindings["output_binding_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_SEMANTIC_SOURCE_RESOLVER_OUTPUT_BINDING_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in output_bindings["ordered_output_binding_rows"]
        )
    ).hexdigest()
    for output_row, source_row in zip(
        output_bindings["ordered_output_binding_rows"],
        source_binding_rows,
        strict=True,
    ):
        assert output_row["ordinal"] == source_row["ordinal"]
        assert output_row["source_id"] == source_row["source_id"]
        assert output_row["source_binding_row_sha256"] == source_row["row_sha256"]
        assert output_row["source_locator_sha256"] == source_row[
            "source_locator"
        ]["locator_sha256"]
        assert output_row["source_resolution_recipe_content_sha256"] == (
            source_row["source_resolution_recipe"]["recipe_content_sha256"]
        )
    assert source_bindings["source_binding_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_SEMANTIC_SOURCE_BINDING_MANIFEST_V1\x00"
        + b"".join(bytes.fromhex(row["row_sha256"]) for row in source_binding_rows)
    ).hexdigest()
    for row in source_binding_rows:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_SEMANTIC_SOURCE_BINDING_ROW_V1", core
        ) == expected
        assert row["resolution_cardinality"] == "EXACTLY_ONE"
        assert row["actual_source_ref"] is None
        assert row["actual_source_raw_sha256"] is None
        assert row["actual_source_content_sha256"] is None
        assert row["actual_binding_count"] == 0
        assert row["runtime_materialized"] is False
        assert row["authority_effect"] == "NONE"
        assert row["source_schema_id"] == schema_bundle["schema_id"]
        assert row["source_json_pointer"] == (
            "/closed_semantic_source_binding_registry/"
            f"ordered_source_binding_rows/{row['ordinal']}/"
            "source_resolution_recipe"
        )
        assert "*" not in row["source_json_pointer"]
        assert row["source_locator"]["json_pointer"] == row[
            "source_json_pointer"
        ]
        assert row["source_locator"][
            "wildcard_or_recursive_descent_allowed"
        ] is False
        Draft202012Validator(
            schema_bundle["schemas"]["semantic_source_locator"]
        ).validate(row["source_locator"])
        assert row["source_resolution_recipe"]["selector_key"] == {
            key: row[key]
            for key in (
                "source_id",
                "source_role",
                "source_kind",
                "source_selector",
                "value_type",
            )
        }
        assert row["source_resolution_recipe"][
            "selector_key_content_sha256"
        ] == framed_sha256(
            "FF_E1_R11_SEMANTIC_SOURCE_SELECTOR_KEY_V1",
            row["source_resolution_recipe"]["selector_key"],
        )
        assert row["producer_output_id"]
        assert row["consumer_dag_edge_count"] == len(
            row["ordered_consumer_dag_edges"]
        )
        assert row["consumer_dag_edge_count"] >= 1
        for edge in row["ordered_consumer_dag_edges"]:
            assert edge["source_id"] == row["source_id"]
            assert edge["source_binding_row_ordinal"] == row["ordinal"]
            assert edge["producer_output_id"] == row["producer_output_id"]
            edge_core = copy.deepcopy(edge)
            edge_sha256 = edge_core.pop("edge_sha256")
            assert framed_sha256(
                "FF_E1_R11_SEMANTIC_SOURCE_DAG_EDGE_V1", edge_core
            ) == edge_sha256
        if row["binding_mode"] == "PRIOR_TYPED_PRODUCER_OUTPUT":
            assert row["producer_output_id"] == row["source_id"]
        else:
            assert row["producer_output_id"].startswith("semantic_source::")

    phase_sets = schema_bundle["closed_semantic_phase_set_registry"]
    assert phase_sets["phase_set_count"] == 4
    assert phase_sets["actual_set_binding_count"] == 0
    phase_set_by_id = {
        row["set_id"]: row
        for row in phase_sets["ordered_phase_set_rows"]
    }
    for row in phase_sets["ordered_phase_set_rows"]:
        assert row["ordered_members"] == sorted(set(row["ordered_members"]))
        assert row["member_count"] == len(row["ordered_members"])
        assert row["runtime_materialized"] is False
        assert row["authority_effect"] == "NONE"

    phase_policy = schema_bundle["closed_semantic_phase_policy_registry"]
    assert phase_policy["policy_row_count"] == 2
    assert phase_policy["actual_policy_binding_count"] == 0
    assert phase_policy["runtime_materialized"] is False
    assert phase_policy["authority_effect"] == "NONE"
    assert phase_policy["policy_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_SEMANTIC_PHASE_POLICY_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in phase_policy["ordered_policy_rows"]
        )
    ).hexdigest()
    for row in phase_policy["ordered_policy_rows"]:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_SEMANTIC_PHASE_POLICY_ROW_V1", core
        ) == expected
        assert row["actual_policy_binding_ref"] is None
        assert row["actual_policy_binding_raw_sha256"] is None
        assert row["actual_policy_binding_content_sha256"] is None
        assert row["authority_effect"] == "NONE"
        required_set = phase_set_by_id[row["required_set_id"]]
        forbidden_set = phase_set_by_id[row["forbidden_set_id"]]
        assert row["ordered_required_members"] == required_set[
            "ordered_members"
        ]
        assert row["ordered_forbidden_members"] == forbidden_set[
            "ordered_members"
        ]
        assert row["required_set_registry_json_pointer"].endswith(
            f"/{required_set['ordinal']}"
        )
        assert row["forbidden_set_registry_json_pointer"].endswith(
            f"/{forbidden_set['ordinal']}"
        )

    sealed_universe = schema_bundle[
        "closed_semantic_sealed_universe_registry"
    ]
    assert sealed_universe["universe_row_count"] == 2
    assert sealed_universe["actual_resolver_output_count"] == 0
    assert sealed_universe["runtime_materialized"] is False
    assert sealed_universe["authority_effect"] == "NONE"
    assert len(
        schema_bundle["schemas"]["semantic_sealed_member_resolver_output"][
            "oneOf"
        ]
    ) == 2
    assert sealed_universe["universe_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_SEMANTIC_SEALED_UNIVERSE_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in sealed_universe["ordered_universe_rows"]
        )
    ).hexdigest()
    for row in sealed_universe["ordered_universe_rows"]:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_SEMANTIC_SEALED_UNIVERSE_ROW_V1", core
        ) == expected
        assert row["resolution_cardinality"] == "EXACTLY_ONE"
        assert row["actual_resolver_output_ref"] is None
        assert row["actual_resolver_output_raw_sha256"] is None
        assert row["actual_resolver_output_content_sha256"] is None
        assert row["member_count"] == len(row["ordered_members"])
        assert row["ordered_members"] == sorted(set(row["ordered_members"]))
        assert row["source_ref_json_pointer"] == "/source_ref"
        assert row["member_projection_json_pointer"] == "/ordered_members"
        assert row["authority_effect"] == "NONE"

    failure_comparators = schema_bundle[
        "closed_semantic_failure_comparator_registry"
    ]
    comparator_by_state = {
        row["failure_state"]: row
        for row in failure_comparators["ordered_comparator_rows"]
    }
    assert failure_comparators["comparator_row_count"] == 12
    assert failure_comparators["actual_comparator_execution_count"] == 0
    assert failure_comparators["runtime_materialized"] is False
    assert failure_comparators["authority_effect"] == "NONE"
    assert failure_comparators["first_hit_law"][
        "later_step_observation_may_preempt_current_step"
    ] is False
    failure_observations = schema_bundle[
        "closed_semantic_failure_observation_registry"
    ]
    observation_rows = failure_observations["ordered_observation_rows"]
    observation_by_state = {
        row["failure_state"]: row for row in observation_rows
    }
    assert failure_observations["observation_row_count"] == 12
    assert failure_observations["first_hit_precedence"] == (
        exact12_failure_precedence
    )
    assert [row["first_hit_precedence_ordinal"] for row in observation_rows] == list(range(12))
    assert failure_observations["actual_observation_count"] == 0
    assert failure_observations["runtime_materialized"] is False
    assert failure_observations["authority_effect"] == "NONE"
    assert failure_observations["observation_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_SEMANTIC_FAILURE_OBSERVATION_MANIFEST_V1\x00"
        + b"".join(bytes.fromhex(row["row_sha256"]) for row in observation_rows)
    ).hexdigest()
    for row in observation_rows:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_SEMANTIC_FAILURE_OBSERVATION_ROW_V1", core
        ) == expected
        assert row["caller_supplied_observation_allowed"] is False
        assert row["comparator_row_sha256"] == comparator_by_state[
            row["failure_state"]
        ]["row_sha256"]
        assert row["observed_output_projection_json_pointer"].startswith("/")
        assert row["authority_effect"] == "NONE"

    assert {
        state
        for row in compatibility_rows
        for state in row["failure_states_in_global_precedence_order"]
    } == set(exact12_failure_precedence)
    assert all(
        row["failure_states_in_global_precedence_order"]
        == [
            state
            for state in exact12_failure_precedence
            if state in row["failure_states_in_global_precedence_order"]
        ]
        for row in compatibility_rows
    )
    for row in semantics["ordered_predicate_semantics_rows"]:
        assert row["typed_semantic_program_ast"]
        assert {
            step["primitive_operator_id"]
            for step in row["typed_semantic_program_ast"]
        }.issubset(primitive_ids)
        assert [
            step["step_ordinal"] for step in row["typed_semantic_program_ast"]
        ] == list(range(row["typed_step_count"]))
        assert all(
            "ordered_input_pointers" not in step
            and "declared_output_fields" not in step
            for step in row["typed_semantic_program_ast"]
        )
        output_ids = [
            output["output_id"]
            for step in row["typed_semantic_program_ast"]
            for output in step["ordered_typed_outputs"]
        ]
        assert len(output_ids) == len(set(output_ids))
        produced_output_ids: set[str] = set()
        for step in row["typed_semantic_program_ast"]:
            compatibility = compatibility_by_id[
                step["primitive_operator_id"]
            ]
            operand_types = {
                operand["value_type"]
                for operand in step["ordered_typed_operands"]
            }
            assert operand_types.issubset(
                compatibility["accepted_input_value_types"]
            )
            assert (
                compatibility["minimum_input_arity"]
                <= len(step["ordered_typed_operands"])
                <= compatibility["maximum_input_arity"]
            )
            assert set(compatibility["required_source_roles"]).issubset(
                {
                    operand["source_role"]
                    for operand in step["ordered_typed_operands"]
                }
            )
            assert set(step["ordered_predecessor_step_output_ids"]).issubset(
                produced_output_ids
            )
            step_failure_states = [
                failure["failure_state"]
                for failure in step["failure_map"]
            ]
            assert step_failure_states == compatibility[
                "failure_states_in_global_precedence_order"
            ]
            for operand in step["ordered_typed_operands"]:
                binding = source_binding_by_id[operand["source_id"]]
                assert operand["source_binding_row_sha256"] == binding[
                    "row_sha256"
                ]
                assert binding["source_role"] == operand["source_role"]
                assert binding["source_kind"] == operand["source_kind"]
                assert binding["value_type"] == operand["value_type"]
                assert binding["source_selector"] == operand[
                    "source_selector"
                ]
                assert operand["source_binding_json_pointer"] == binding[
                    "source_json_pointer"
                ]
                assert operand["resolved_source_producer_output_id"] == binding[
                    "producer_output_id"
                ]
            assert step["source_dag_edge_count"] == len(
                step["ordered_typed_operands"]
            )
            assert len(step["ordered_source_dag_edges"]) == len(
                step["ordered_typed_operands"]
            )
            for failure in step["failure_map"]:
                condition = failure["condition_ast"]
                observation = observation_by_state[failure["failure_state"]]
                assert condition["operator"] == (
                    "FIRST_HIT_TYPED_OBSERVATION_CONDITION"
                )
                assert condition["observation_semantics_row_sha256"] == (
                    observation["row_sha256"]
                )
                assert condition["first_hit_precedence_ordinal"] == (
                    observation["first_hit_precedence_ordinal"]
                )
                assert condition["observed_output_id"] == step[
                    "ordered_typed_outputs"
                ][0]["output_id"]
                assert condition["expected_reference_operand"] == observation[
                    "expected_reference_operand"
                ]
                assert condition["comparator_row_sha256"] == observation[
                    "comparator_row_sha256"
                ]
                assert condition["applicability"]["predicate_ordinal"] == row[
                    "ordinal"
                ]
                assert condition["applicability"]["step_ordinal"] == step[
                    "step_ordinal"
                ]
                assert condition["applicability"]["applicable"] is True
                assert condition[
                    "all_lower_applicable_conditions_must_be_false"
                ] is True
                assert condition[
                    "lower_nonapplicable_conditions_do_not_block"
                ] is True
                assert condition["later_step_condition_may_preempt"] is False
                assert condition["ordered_observation_source_ids"] == [
                    operand["source_id"]
                    for operand in step["ordered_typed_operands"]
                ]
                assert condition[
                    "ordered_observation_source_binding_row_sha256"
                ] == [
                    operand["source_binding_row_sha256"]
                    for operand in step["ordered_typed_operands"]
                ]
                assert condition[
                    "all_lower_ordinal_conditions_must_be_false"
                ] is True
                assert condition["caller_supplied_observation_allowed"] is False
            produced_output_ids.update(
                output["output_id"]
                for output in step["ordered_typed_outputs"]
            )
        assert row["forward_reference_count"] == 0
        assert row["cyclic_dependency_count"] == 0
        core = copy.deepcopy(row)
        expected = core.pop("semantics_row_sha256")
        assert framed_sha256(
            "FF_E1_R11_FIXTURE_PREDICATE_SEMANTICS_ROW_V1", core
        ) == expected

    phase_row = semantics["ordered_predicate_semantics_rows"][10]
    assert [
        step["primitive_operator_id"]
        for step in phase_row["typed_semantic_program_ast"]
    ] == [
        "POINTER_PROJECT",
        "BYTE_OR_SET_COMPARE",
        "SEALED_SET_SCAN",
        "SEALED_SET_SCAN",
        "SEALED_SET_SCAN",
    ]
    phase_steps = phase_row["typed_semantic_program_ast"]
    assert {
        operand["source_role"] for operand in phase_steps[0]["ordered_typed_operands"]
    } == {"CLOSED_SOURCE_OBJECT", "CLOSED_POINTER_SET"}
    assert any(
        output["value_type"] == "TYPED_MATERIALIZATION_PHASE"
        for output in phase_steps[0]["ordered_typed_outputs"]
    )
    assert {
        "SEALED_MEMBER_UNIVERSE",
        "REQUIRED_ID_SET",
        "FORBIDDEN_ID_SET",
        "EVIDENCE_USE_SITE_ROWS",
    }.issubset(
        {
            operand["source_role"]
            for step in phase_steps[2:]
            for operand in step["ordered_typed_operands"]
        }
    )
    assert all(
        "BOOLEAN_ASSERTION"
        not in {
            operand["value_type"]
            for operand in step["ordered_typed_operands"]
        }
        for row in semantics["ordered_predicate_semantics_rows"]
        for step in row["typed_semantic_program_ast"]
        if step["primitive_operator_id"]
        in {"SIGNATURE_TRUST_VERIFY", "CAS_TRANSITION_VERIFY", "SEALED_SET_SCAN"}
    )

    evidence = schema_bundle[
        "closed_exact858_evidence_resolution_plan_registry"
    ]
    assert evidence["plan_row_count"] == 858
    assert [row["ordinal"] for row in evidence["ordered_plan_rows"]] == list(range(858))
    assert sum(row["usage_class"] == "REQUIRED_ONLY" for row in evidence["ordered_plan_rows"]) == 794
    forbidden_rows = [
        row
        for row in evidence["ordered_plan_rows"]
        if row["usage_class"] == "FORBIDDEN_ONLY"
    ]
    assert len(forbidden_rows) == 64
    assert all(row["subject_profile_id"] is None for row in forbidden_rows)
    assert all(row["expected_schema_id"] is None for row in forbidden_rows)
    assert all(
        row["allowed_resolution_class"]
        == "MUST_BE_ABSENT_FROM_SEALED_BUNDLE"
        for row in forbidden_rows
    )
    assert sum(
        row["phase_applicability_domain"]
        == ["SYNTHETIC_OFFLINE_ONLY", "PRE_CAS_ONLY"]
        for row in evidence["ordered_plan_rows"]
    ) == 26
    assert not any(
        "POST_CAS" in row["phase_applicability_domain"]
        for row in evidence["ordered_plan_rows"]
    )

    subjects = schema_bundle[
        "candidate_external_binding_subject_profile_registry"
    ]
    resolver = schema_bundle[
        "candidate_external_binding_resolver_profile_registry"
    ]
    signing = schema_bundle["candidate_signing_authority_profile_registry"]
    signatures = schema_bundle[
        "candidate_external_signature_profile_registry"
    ]
    assert subjects["profile_count"] == 4
    assert resolver["profile_count"] == 3
    assert signing["profile_count"] == 5
    assert signatures["profile_count"] == 10
    assert subjects["activated_profile_count"] == 0
    assert resolver["activated_profile_count"] == 0
    assert signing["activated_profile_count"] == 0
    assert signatures["currently_operationally_usable_profile_count"] == 0
    assert all(
        "preimage_formula" not in row and "content_formula" not in row
        for row in signatures["profiles"]
    )
    assert len(schema_bundle["schemas"]["external_binding_subject"]["oneOf"]) == 4
    external_subject_branches = schema_bundle["schemas"]["external_binding_subject"]["oneOf"]
    frozen_payload = external_subject_branches[1]["properties"]["evidence_payload"]
    synthetic_payload_branches = external_subject_branches[2]["properties"][
        "evidence_payload"
    ]["oneOf"]
    subject_evidence_ids = set(frozen_payload["properties"]["evidence_id"]["enum"])
    subject_evidence_ids.update(
        evidence_id
        for branch in synthetic_payload_branches
        for evidence_id in branch["properties"]["evidence_id"]["enum"]
    )
    required_plan_ids = {
        row["evidence_id"]
        for row in evidence["ordered_plan_rows"]
        if row["usage_class"] == "REQUIRED_ONLY"
    }
    forbidden_plan_ids = {
        row["evidence_id"] for row in forbidden_rows
    }
    assert subject_evidence_ids == required_plan_ids
    assert subject_evidence_ids.isdisjoint(forbidden_plan_ids)
    assert len(schema_bundle["schemas"]["external_binding_resolution_successor"]["oneOf"]) == 8
    assert len(schema_bundle["schemas"]["profile_activation_successor"]["oneOf"]) == 9
    assert len(schema_bundle["schemas"]["purpose_specific_operating_authorization"]["oneOf"]) == 6
    assert len(schema_bundle["schemas"]["signing_authority_binding_successor"]["oneOf"]) == 5
    independent_receipt_signature_profile = next(
        profile
        for profile in signatures["profiles"]
        if profile["profile_id"]
        == "FF_E1_R11_INDEPENDENT_SOD_VALIDATION_RECEIPT_SIGNATURE_V1"
    )
    assert independent_receipt_signature_profile[
        "key_source_profile_id"
    ] == "FF_E1_R11_INDEPENDENT_SOD_VALIDATOR_SIGNING_AUTHORITY_PROFILE_V1"
    assert independent_receipt_signature_profile[
        "preimage_domain"
    ] == "FF_E1_R11_INDEPENDENT_SOD_VALIDATION_RECEIPT_SIGNATURE_V1::PREIMAGE_V1"
    assert independent_receipt_signature_profile[
        "currently_operationally_usable"
    ] is False
    assert independent_receipt_signature_profile["authority_effect"] == "NONE"

    assignment_registry = schema_bundle[
        "closed_evidence_authority_use_site_assignment_registry"
    ]
    assert assignment_registry["assignment_row_count"] == 1616
    assert assignment_registry["repaired_mixed_authority_use_site_count"] == 761
    assert assignment_registry["formal_evidence_eligible_count"] == 0
    assert assignment_registry["mixed_authority_class_allowed"] is False
    assignment_rows = assignment_registry["ordered_assignment_rows"]
    assert sum(
        row["branch_specific_authority_target"]["target_kind"]
        == "FROZEN_RAW_PROJECTION_TARGET"
        for row in assignment_rows
    ) == 340
    assert sum(
        row["branch_specific_authority_target"]["target_kind"]
        == "SYNTHETIC_PROOF_TARGET"
        for row in assignment_rows
    ) == 1276
    assert len(
        {
            row["branch_specific_authority_target"]["target_id"]
            for row in assignment_rows
        }
    ) == 1616
    assert all(
        row["cross_row_field_splicing_allowed"] is False
        and row["branch_specific_authority_target"][
            "caller_override_allowed"
        ]
        is False
        for row in assignment_rows
    )
    for row in assignment_rows:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_EVIDENCE_AUTHORITY_USE_SITE_ASSIGNMENT_ROW_V1",
            core,
        ) == expected
    target_profiles = schema_bundle["closed_evidence_target_profile_registry"]
    assert target_profiles["profile_count"] == 5
    assert target_profiles["activated_profile_count"] == 0
    assert target_profiles["actual_target_count"] == 0
    assert {
        profile["profile_id"] for profile in target_profiles["ordered_profiles"]
    } >= {
        "FF_E1_R11_RESOLVER_NOT_FOUND_PROOF_TARGET_V1",
        "FF_E1_R11_SIGNED_EVIDENCE_SUBJECT_RAW_READBACK_V1",
    }
    for profile in target_profiles["ordered_profiles"]:
        assert profile["undefined_input_count"] == 0
        assert profile["forward_reference_count"] == 0
        assert profile["cyclic_dependency_count"] == 0
        produced = set()
        for step in profile["closed_derivation_program_ast"]:
            assert set(step["ordered_predecessor_output_ids"]).issubset(
                produced
            )
            produced.update(
                output["output_id"]
                for output in step["ordered_typed_outputs"]
            )
    target_derivations = schema_bundle[
        "closed_exact1616_evidence_target_derivation_registry"
    ]
    assert target_derivations["derivation_row_count"] == 1616
    assert target_derivations["frozen_projection_derivation_count"] == 340
    assert target_derivations["synthetic_proof_derivation_count"] == 1276
    assert target_derivations["actual_target_count"] == 0
    assert target_derivations["runtime_materialized"] is False
    assert target_derivations[
        "caller_or_resolver_selected_target_allowed"
    ] is False
    derivation_by_target_id = {
        row["target_id"]: row
        for row in target_derivations["ordered_derivation_rows"]
    }
    assert len(derivation_by_target_id) == 1616
    assert target_derivations["derivation_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_EVIDENCE_TARGET_DERIVATION_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in target_derivations["ordered_derivation_rows"]
        )
    ).hexdigest()
    for row in target_derivations["ordered_derivation_rows"]:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_EVIDENCE_TARGET_DERIVATION_ROW_V1", core
        ) == expected
        assert row["actual_target_ref"] is None
        assert row["actual_target_raw_sha256"] is None
        assert row["actual_target_content_sha256"] is None
        assert row["runtime_materialized"] is False
        assert row["caller_selected_target_allowed"] is False
        assert row["authority_effect"] == "NONE"
    for assignment in assignment_rows:
        target = assignment["branch_specific_authority_target"]
        derivation = derivation_by_target_id[target["target_id"]]
        assert target["target_derivation_row_sha256"] == derivation[
            "row_sha256"
        ]
    crosswalk = schema_bundle[
        "closed_exact1616_evidence_target_equality_crosswalk_registry"
    ]
    assert crosswalk["crosswalk_row_count"] == 1616
    assert crosswalk["assignment_row_count"] == 1616
    assert {
        row["assignment_row_sha256"]
        for row in crosswalk["ordered_crosswalk_rows"]
    } == {row["row_sha256"] for row in assignment_rows}
    for row in crosswalk["ordered_crosswalk_rows"]:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_EVIDENCE_TARGET_EQUALITY_CROSSWALK_ROW_V1",
            core,
        ) == expected
        assert row["ordered_field_equalities"]
        assert row["independent_target_derivation"]["required"] is True
        assert row["independent_target_derivation"][
            "caller_or_resolver_selected_target_allowed"
        ] is False
        assert row["independent_target_derivation"][
            "derived_target_id"
        ] == row["assignment_target_id"]
        assert all(
            equality["operator"] == "BYTE_EQUAL"
            and equality["required"] is True
            and equality["mismatch_result"] == "BLOCKED"
            for equality in row["ordered_field_equalities"]
        )
    predicate8 = semantics["ordered_predicate_semantics_rows"][8]
    assert {
        dependency["dependency_contract_id"]
        for dependency in predicate8["required_dependency_rows"]
    } >= {
        "FF_E1_R11_EXACT858_EVIDENCE_RESOLUTION_PLAN_V1",
        "FF_E1_R11_EVIDENCE_AUTHORITY_USE_SITE_ASSIGNMENT_V1",
    }
    assert any(
        step["operation_id"]
        == "VERIFY_SUBJECT_ASSIGNMENT_EXACT_TUPLE_AND_BRANCH_SPECIFIC_TARGET_NO_CROSS_ROW_SPLICE"
        for step in predicate8["typed_semantic_program_ast"]
    )

    sod = schema_bundle[
        "candidate_evidence_actual_tuple_sod_matrix_registry"
    ]
    assert sod["role_row_count"] == 4
    assert sod["pair_row_count"] == 6
    assert sod["actual_tuple_bound_count"] == 0
    assert sod["activated_role_count"] == 0
    assert sod["purpose_specific_authorized_role_count"] == 0
    assert sod["sod_satisfied_pair_count"] == 0
    assert sod["independent_validator_pair_row_count"] == 4
    assert sod["independent_validator_actual_binding_count"] == 0
    assert sod["independent_validator_sod_satisfied_pair_count"] == 0
    assert sod["independent_validator_identity_equality_row_count"] == 19
    assert sod["independent_validator_pair_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_INDEPENDENT_SOD_VALIDATOR_PAIR_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in sod["ordered_independent_validator_pair_rows"]
        )
    ).hexdigest()
    assert sod[
        "independent_validator_identity_equality_manifest_sha256"
    ] == hashlib.sha256(
        b"FF_E1_R11_INDEPENDENT_SOD_VALIDATOR_IDENTITY_EQUALITY_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"])
            for row in sod[
                "ordered_independent_validator_identity_equality_rows"
            ]
        )
    ).hexdigest()
    assert sod["current_evaluation_state"] == "UNBOUND_BLOCKING"
    assert sod["authority_effect"] == "NONE"
    materializer = schema_bundle[
        "candidate_synthetic_fixture_materializer_profile_registry"
    ]
    assert materializer["profile_count"] == 1
    assert materializer["activated_profile_count"] == 0
    assert materializer["authorized_profile_count"] == 0
    assert materializer["actual_materializer_count"] == 0
    sod_successor = schema_bundle["schemas"][
        "evidence_actual_tuple_sod_successor"
    ]
    assert len(
        sod_successor["properties"]["ordered_actual_role_bindings"][
            "prefixItems"
        ]
    ) == 4
    assert len(
        sod_successor["properties"]["ordered_pair_results"]["prefixItems"]
    ) == 6
    assert "trust_anchor_id" in sod_successor["properties"][
        "ordered_actual_role_bindings"
    ]["prefixItems"][0]["properties"]["actual_identity"]["required"]
    independent_receipt = schema_bundle["schemas"][
        "independent_sod_validation_receipt"
    ]
    assert len(
        independent_receipt["properties"][
            "ordered_validator_role_pair_results"
        ]["prefixItems"]
    ) == 4
    assert len(
        independent_receipt["properties"][
            "ordered_identity_equality_results"
        ]["prefixItems"]
    ) == 19
    assert independent_receipt["properties"][
        "validator_identity_equal_signing_authority_binding_identity"
    ]["const"] is True
    assert independent_receipt["properties"][
        "all_exact4_validator_pairs_exact7_axes_distinct"
    ]["const"] is True
    assert independent_receipt["properties"][
        "may_authorize_materialization_or_execution"
    ]["const"] is False
    assert independent_receipt["properties"]["authority_effect"][
        "const"
    ] == "SOD_VALIDATION_EVIDENCE_ONLY"
    identity_mirror = schema_bundle["digest_profiles"][
        "resolved_identity_preimage"
    ]
    central_digest_registry = schema_bundle[
        "closed_digest_profile_authority_registry"
    ]
    identity_profile = central_digest_registry["ordered_profiles"][
        int(identity_mirror["central_profile_json_pointer"].rsplit("/", 1)[1])
    ]
    assert identity_profile["domain"] == (
        "FF_E1_R11_RESOLVED_IDENTITY_PREIMAGE_V1"
    )
    assert identity_profile["canonicalization"] == "RFC8785_INTEGER_ONLY"
    assert "/identity_preimage_sha256" in identity_profile[
        "exact_exclusion_json_pointers"
    ]
    assert any(
        "/trust_anchor_id" in binding["ordered_preimage_json_pointers"]
        for binding in identity_profile["ordered_exact_target_bindings"]
    )
    assert sod_successor["properties"][
        "may_authorize_materialization_or_execution"
    ]["const"] is False
    assert all(
        all(
            row[field] is None
            for field in (
                "actual_principal_id",
                "actual_context_id",
                "actual_capability_id",
                "actual_installation_id",
                "actual_key_id",
                "actual_measurement_sha256",
                "actual_trust_anchor_id",
                "actual_binding_successor_ref",
                "profile_activation_successor_ref",
                "purpose_specific_authorization_ref",
            )
        )
        for row in sod["ordered_role_rows"]
    )
    equality_laws = {
        law["law_id"]: law for law in schema_bundle["equality_laws"]
    }
    profile_law = equality_laws[
        "EXTERNAL_BINDING_EXACT4_AND_RESOLVER_EXACT3"
    ]
    assert profile_law["exact_subject_profile_count"] == 4
    assert profile_law["exact_resolver_profile_count"] == 3
    assert profile_law["synthetic_proof_subject_scope_count"] == 1
    assert profile_law["synthetic_proof_resolver_scope_count"] == 1
    assert not any(
        row["source_authority_class"]
        == "FROZEN_PREDECESSOR_OR_SYNTHETIC_PROOF_AUTHORITY"
        for row in evidence["ordered_plan_rows"]
    )

    cas_registry = schema_bundle[
        "closed_exact4_one_shot_cas_object_contract_registry"
    ]
    assert cas_registry["schema_root_count"] == 4
    assert cas_registry["equality_row_count"] == 97
    assert cas_registry["identity_projection_row_count"] == 4
    identity_rows = cas_registry["ordered_identity_projection_rows"]
    assert [row["ordinal"] for row in identity_rows] == list(range(4))
    assert all(
        row["resolver_profile_id"]
        == "FF_E1_R11_CAS_EXACT4_RAW_READBACK_IDENTITY_RESOLVER_V1"
        and row["resolution_cardinality"] == "EXACTLY_ONE"
        and row["caller_selected"] is False
        and row["post_cas_evidence_allowed"] is False
        and row["authority_effect"] == "NONE"
        for row in identity_rows
    )
    assert cas_registry["resolver_output_schema_id"] == (
        "factorforge_e1_r11_cas_raw_readback_resolver_output_v1"
    )
    resolver_output_profile = cas_registry["resolver_output_profile"]
    assert resolver_output_profile["profile_id"] == (
        "FF_E1_R11_CAS_EXACT4_RAW_READBACK_IDENTITY_RESOLVER_V1"
    )
    assert resolver_output_profile["exact_branch_count"] == 4
    assert resolver_output_profile[
        "serialized_equality_booleans_or_caller_digest_profile_are_sufficient"
    ] is False
    assert resolver_output_profile["current_resolver_output_instance_count"] == 0
    assert resolver_output_profile["runtime_materialized"] is False
    assert resolver_output_profile["authority_effect"] == "NONE"
    resolver_output_schema = schema_bundle["schemas"][
        "cas_raw_readback_resolver_output"
    ]
    assert len(resolver_output_schema["oneOf"]) == 4
    content_profile_ids = cas_registry[
        "ordered_content_digest_profile_ids"
    ]
    for ordinal, (row, branch, content_profile_id) in enumerate(
        zip(
            identity_rows,
            resolver_output_schema["oneOf"],
            content_profile_ids,
            strict=True,
        )
    ):
        properties = branch["properties"]
        assert properties["resolver_profile_id"]["const"] == (
            "FF_E1_R11_CAS_EXACT4_RAW_READBACK_IDENTITY_RESOLVER_V1"
        )
        assert properties["output_branch_ordinal"]["const"] == ordinal
        assert properties["resolution_cardinality"]["const"] == (
            "EXACTLY_ONE"
        )
        assert properties["caller_selected"]["const"] is False
        assert properties["post_cas_evidence_allowed"]["const"] is False
        assert properties["source_container_schema_id"]["const"] == row[
            "source_container_schema_id"
        ]
        assert properties["source_container_branch_selector"]["const"] == row[
            "source_container_branch_selector"
        ]
        assert properties["source_ref_json_pointer"]["const"] == row[
            "source_ref_json_pointer"
        ]
        assert properties["source_raw_sha256_json_pointer"]["const"] == row[
            "source_raw_sha256_json_pointer"
        ]
        assert properties["source_content_sha256_json_pointer"]["const"] == row[
            "source_content_sha256_json_pointer"
        ]
        raw_operand = properties["raw_sha256_operand"]["properties"]
        assert raw_operand["operand_kind"]["const"] == "RAW_BYTES"
        assert raw_operand["digest_profile_id"]["const"] == (
            "FF_RAW_ARTIFACT_SHA256_V1"
        )
        assert raw_operand["digest_domain"]["const"] == (
            "NONE__UNFRAMED_EXACT_RAW_BYTES"
        )
        assert raw_operand["canonicalization"]["const"] == (
            "EXACT_RAW_BYTES"
        )
        content_operand = properties["content_sha256_operand"][
            "properties"
        ]
        assert content_operand["operand_kind"]["const"] == (
            "RFC8785_CONTENT"
        )
        assert content_operand["digest_profile_id"]["const"] == (
            content_profile_id
        )
        assert content_operand["digest_domain"]["const"] == (
            content_profile_id
        )
        assert content_operand["canonicalization"]["const"] == (
            "RFC8785_INTEGER_ONLY"
        )
        assert properties["ordered_required_equalities"]["const"] == row[
            "required_equality_relations"
        ]
    for row in identity_rows:
        core = copy.deepcopy(row)
        expected = core.pop("row_sha256")
        assert framed_sha256(
            "FF_E1_R11_CAS_IDENTITY_PROJECTION_ROW_V1", core
        ) == expected
    assert cas_registry["identity_projection_manifest_sha256"] == hashlib.sha256(
        b"FF_E1_R11_CAS_IDENTITY_PROJECTION_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["row_sha256"]) for row in identity_rows
        )
    ).hexdigest()
    assert {
        "cas_identity_projection_manifest",
        "cas_equality_row",
        "cas_equality_manifest",
    }.issubset(schema_bundle["digest_profiles"])
    assert cas_registry["cas_digest_profile_count"] == 10
    cas_digest_dag = cas_registry["cas_digest_profile_dag"]
    assert [row["ordinal"] for row in cas_digest_dag] == list(range(10))
    assert {row["profile_id"] for row in cas_digest_dag} == {
        *content_profile_ids,
        "FF_E1_R11_CAS_CONSUMPTION_KEY_V1",
        "FF_E1_R11_CAS_MATERIALIZATION_ATTEMPT_ID_V1",
        "FF_E1_R11_CAS_IDENTITY_PROJECTION_ROW_V1",
        "FF_E1_R11_CAS_IDENTITY_PROJECTION_MANIFEST_V1",
        "FF_E1_R11_CAS_EQUALITY_ROW_V1",
        "FF_E1_R11_CAS_EQUALITY_MANIFEST_V1",
    }
    seen_digest_profiles = set()
    digest_profile_by_id = {
        profile["profile_id"]: profile
        for profile in schema_bundle[
            "closed_digest_profile_authority_registry"
        ]["ordered_profiles"]
    }
    for row in cas_digest_dag:
        assert set(row["depends_on_profile_ids"]).issubset(
            seen_digest_profiles
        )
        assert row["domain"] == digest_profile_by_id[
            row["profile_id"]
        ]["domain"]
        assert row["depends_on_profile_ids"] == digest_profile_by_id[
            row["profile_id"]
        ]["depends_on_profile_ids"]
        seen_digest_profiles.add(row["profile_id"])
    cas_key_profile = digest_profile_by_id[
        "FF_E1_R11_CAS_CONSUMPTION_KEY_V1"
    ]
    assert any(
        binding["ordered_preimage_json_pointers"][2:4]
        == ["/authorization_raw_sha256", "/authorization_content_sha256"]
        for binding in cas_key_profile["ordered_exact_target_bindings"]
    )
    assert all(
        not any(
            field.endswith("_preimage_sha256")
            for field in schema_bundle["schemas"][schema_name][
                "properties"
            ]
        )
        for schema_name in (
            "cas_consumption_pre_state",
            "cas_consumption_transition",
            "cas_consumption_post_state",
            "cas_consumption_receipt",
        )
    )
    equality_pairs = {
        (
            row["left_schema_id"],
            row["left_json_pointer"],
            row["right_schema_id"],
            row["right_json_pointer"],
        )
        for row in cas_registry["ordered_equality_rows"]
    }
    schema_by_id = {
        schema["$id"]: schema
        for schema in schema_bundle["schemas"].values()
    }

    def _resolve_schema_instance_pointer(
        schema_id: str,
        branch_ordinal: int | None,
        instance_pointer: str,
    ) -> dict:
        node = schema_by_id[schema_id]
        if branch_ordinal is not None:
            node = node["oneOf"][branch_ordinal]
        for encoded_token in instance_pointer.split("/")[1:]:
            token = encoded_token.replace("~1", "/").replace("~0", "~")
            node = node["properties"][token]
        return node

    for row in cas_registry["ordered_equality_rows"]:
        _resolve_schema_instance_pointer(
            row["left_schema_id"],
            row["left_schema_branch_ordinal"],
            row["left_json_pointer"],
        )
        _resolve_schema_instance_pointer(
            row["right_schema_id"],
            row["right_schema_branch_ordinal"],
            row["right_json_pointer"],
        )
    pre, transition, post, receipt = cas_registry["ordered_schema_ids"]
    assert {
        (
            "factorforge_e1_external_binding_resolution_successor_v1",
            "/subject_ref",
            pre,
            "/authorization_ref",
        ),
        (
            "factorforge_e1_external_binding_resolution_successor_v1",
            "/subject_raw_sha256",
            pre,
            "/authorization_raw_sha256",
        ),
        (
            "factorforge_e1_external_binding_resolution_successor_v1",
            "/subject_content_sha256",
            pre,
            "/authorization_content_sha256",
        ),
        (transition, "/pre_state_ref", post, "/previous_pre_state_ref"),
        (transition, "/pre_state_raw_sha256", post, "/previous_pre_state_raw_sha256"),
        (transition, "/pre_state_content_sha256", post, "/previous_pre_state_content_sha256"),
        (post, "/transition_ref", receipt, "/transition_ref"),
        (post, "/transition_raw_sha256", receipt, "/transition_raw_sha256"),
        (post, "/transition_content_sha256", receipt, "/transition_content_sha256"),
        (post, "/content_sha256", receipt, "/post_state_content_sha256"),
        (pre, "/authorization_ref", transition, "/authorization_ref"),
        (pre, "/authorization_raw_sha256", transition, "/authorization_raw_sha256"),
        (pre, "/authorization_content_sha256", transition, "/authorization_content_sha256"),
        (transition, "/authorization_ref", post, "/authorization_ref"),
        (transition, "/authorization_raw_sha256", post, "/authorization_raw_sha256"),
        (transition, "/authorization_content_sha256", post, "/authorization_content_sha256"),
        (post, "/authorization_ref", receipt, "/authorization_ref"),
        (post, "/authorization_raw_sha256", receipt, "/authorization_raw_sha256"),
        (post, "/authorization_content_sha256", receipt, "/authorization_content_sha256"),
    }.issubset(equality_pairs)
    assert sum(
        row["left_schema_id"]
        == "factorforge_e1_r11_cas_raw_readback_resolver_output_v1"
        or row["right_schema_id"]
        == "factorforge_e1_r11_cas_raw_readback_resolver_output_v1"
        for row in cas_registry["ordered_equality_rows"]
    ) == 32
    assert cas_registry["runtime_materialized"] is False

    designs = [
        branch["materialization_design"]
        for row in semantic_registry["semantic_derivation_rows"]
        for branch in row["closed_branch_universe"]
    ]
    assert sum(
        design["materialization_phase"] == "SYNTHETIC_OFFLINE_ONLY"
        for design in designs
    ) == 163
    assert sum(
        design["materialization_phase"] == "PRE_CAS_ONLY"
        for design in designs
    ) == 7
    assert all(
        design["realized_post_cas_evidence_allowed"] is False
        for design in designs
    )
    permissions = schema_bundle["current_permission_matrix"]
    assert permissions["permissions_opened_count"] == 0
    assert permissions["authority_effect"] == "NONE"
    assert not any(
        value
        for key, value in permissions.items()
        if key.endswith("_allowed")
    )
    digest_registry = schema_bundle["closed_digest_profile_authority_registry"]
    digest_profiles = {
        row["profile_id"]: row
        for row in digest_registry["ordered_profiles"]
    }
    assert digest_registry["profile_count"] == len(digest_profiles)
    assert digest_registry["profile_id_unique_count"] == len(digest_profiles)
    assert digest_registry["single_normative_formula_authority"] is True
    assert digest_registry[
        "formula_mirrors_outside_this_registry_are_authoritative"
    ] is False
    for required_profile_id in (
        "FF_STAGE1B_JSON_POINTER_PROJECTION_V1",
        "FF_E1_R11_EVIDENCE_ASSIGNMENT_PROJECTION_V1",
        "FF_E1_R11_EVIDENCE_ASSIGNMENT_PROJECTION_MANIFEST_V1",
        "FF_E1_R11_EVIDENCE_TARGET_FIELD_EQUALITY_ROW_V1",
        "FF_E1_R11_EVIDENCE_ASSIGNMENT_TARGET_COUPLING_ROW_V1",
        "FF_E1_R11_EVIDENCE_ASSIGNMENT_TARGET_COUPLING_MANIFEST_V1",
        "FF_E1_R11_NEGATIVE_DONOR_PLAN_V1",
        "FF_E1_R11_NEGATIVE_REPLACEMENT_DERIVATION_CONTRACT_V1",
        "FF_E1_R11_NEGATIVE_FIRST_FAILURE_GATE_ROW_V1",
        "FF_E1_FIXTURE_VALIDATION_NEGATIVE_DESIGN_ROW_V1",
        "FF_E1_R11_NEGATIVE_DONOR_RESOLUTION_RECEIPT_PREIMAGE_V1",
        "FF_E1_R11_NEGATIVE_DONOR_RESOLUTION_RECEIPT_CONTENT_V1",
        "FF_E1_R11_NEGATIVE_DERIVATION_RECEIPT_PREIMAGE_V1",
        "FF_E1_R11_NEGATIVE_DERIVATION_RECEIPT_CONTENT_V1",
        "FF_E1_R11_NEGATIVE_FIRST_FAILURE_ISOLATION_RECEIPT_PREIMAGE_V1",
        "FF_E1_R11_NEGATIVE_FIRST_FAILURE_ISOLATION_RECEIPT_CONTENT_V1",
        "FF_E1_R11_SUBJECT_READBACK_RECEIPT_CONTENT_V1",
        "FF_E1_R11_TARGET_DERIVATION_EXECUTION_RECEIPT_CONTENT_V1",
        "FF_E1_R12_NEGATIVE_RECEIPT_SCHEMA_DEFINITION_V1",
    ):
        assert required_profile_id in digest_profiles
    schema_definition_profile = digest_profiles[
        "FF_E1_R12_NEGATIVE_RECEIPT_SCHEMA_DEFINITION_V1"
    ]
    assert schema_definition_profile["domain"] == (
        "FF_E1_R12_NEGATIVE_RECEIPT_SCHEMA_DEFINITION_V1"
    )
    assert schema_definition_profile["exact_target_binding_count"] == 3
    assert {
        binding["target_locator"]
        for binding in schema_definition_profile[
            "ordered_exact_target_bindings"
        ]
    } == {
        "/schemas/negative_donor_resolution_receipt",
        "/schemas/negative_derivation_receipt",
        "/schemas/negative_first_failure_isolation_receipt",
    }
    assert all(
        binding["ordered_preimage_json_pointers"] == [""]
        and binding["binding_kind"]
        == "EXACT_CLOSED_SCHEMA_DEFINITION_TO_GATE_DIGEST_OUTPUT"
        for binding in schema_definition_profile[
            "ordered_exact_target_bindings"
        ]
    )
    projection_profile = schema_bundle[
        "closed_frozen_json_pointer_projection_profile_registry"
    ]["profiles"][0]
    assert projection_profile["profile_id"] == (
        "FF_STAGE1B_JSON_POINTER_PROJECTION_V1"
    )
    assert projection_profile["ordered_inputs"] == [
        "source_artifact_content_sha256",
        "source_json_pointer",
        "resolved_typed_json_value",
    ]

    def _resolve(pointer: str):
        value = contracts.schema_bundle
        for encoded in pointer.split("/")[1:]:
            token = encoded.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        return value

    first_semantic_row = semantic_registry["semantic_derivation_rows"][0]
    contract_pointer = first_semantic_row["closed_branch_universe"][0][
        "materialization_design"
    ]["contract_law_pointer"]
    assert first_semantic_row["contract_law_projection_content_sha256"] == (
        framed_sha256(
            "FF_STAGE1B_JSON_POINTER_PROJECTION_V1",
            {
                "source_artifact_content_sha256": first_semantic_row[
                    "frozen_stage1b_schema_artifact_content_sha256"
                ],
                "source_json_pointer": contract_pointer,
                "resolved_typed_json_value": _resolve(contract_pointer),
            },
        )
    )
    donor_schema = schema_bundle["schemas"][
        "negative_donor_resolution_receipt"
    ]
    derivation_schema = schema_bundle["schemas"][
        "negative_derivation_receipt"
    ]
    first_failure_schema = schema_bundle["schemas"][
        "negative_first_failure_isolation_receipt"
    ]
    assert donor_schema["not"] == {}
    assert derivation_schema["not"] == {}
    assert first_failure_schema["not"] == {}
    instantiation_gates = schema_bundle[
        "closed_negative_receipt_instantiation_gate_registry"
    ]
    assert instantiation_gates["gate_row_count"] == 3
    assert instantiation_gates["current_instantiable_schema_count"] == 0
    assert instantiation_gates[
        "current_approved_separate_operating_delta_count"
    ] == 0
    schema_definition_profile_id = (
        "FF_E1_R12_NEGATIVE_RECEIPT_SCHEMA_DEFINITION_V1"
    )
    for gate_row in instantiation_gates["ordered_gate_rows"]:
        schema_payload = schema_bundle["schemas"][gate_row["schema_key"]]
        assert gate_row["schema_definition_digest_profile_id"] == (
            schema_definition_profile_id
        )
        assert gate_row["schema_definition_target_locator"] == (
            f"/schemas/{gate_row['schema_key']}"
        )
        assert gate_row["schema_definition_content_sha256"] == framed_sha256(
            schema_definition_profile_id,
            schema_payload,
        )
        assert gate_row[
            "schema_definition_recomputed_equality_required"
        ] is True
    schema_definition_negatives = schema_bundle[
        "closed_negative_receipt_schema_definition_negative_design_registry"
    ]
    assert schema_definition_negatives["negative_design_count"] == 12
    assert schema_definition_negatives["materialized_count"] == 0
    assert schema_definition_negatives["executed_count"] == 0
    assert len(donor_schema["oneOf"]) == 86
    assert len(derivation_schema["oneOf"]) == 86
    assert len(first_failure_schema["oneOf"]) == 86
    assert len(
        {
            branch["properties"]["negative_family_id"]["const"]
            for branch in donor_schema["oneOf"]
        }
    ) == 86
    cas_branch = next(
        branch
        for branch in donor_schema["oneOf"]
        if branch["properties"]["negative_family_id"]["const"]
        == "CAS_SAME_QUAD_DIFFERENT_AUTHORIZATION_SUBJECT"
    )
    assert cas_branch["properties"]["donor_resolution_count"] == {
        "const": 2
    }
    assert len(
        cas_branch["properties"]["cas_same_quad_equality_results"][
            "prefixItems"
        ]
    ) == 4
    assert len(
        cas_branch["properties"]["cas_subject_distinctness_results"][
            "prefixItems"
        ]
    ) == 3
    for receipt_schema in (
        donor_schema,
        derivation_schema,
        first_failure_schema,
    ):
        for branch in receipt_schema["oneOf"]:
            properties = branch["properties"]
            for field in (
                "formal_evidence_eligible",
                "admission_eligible",
                "promotion_eligible",
                "may_satisfy_operational_predecessor",
                "may_satisfy_host_or_operating_authority",
                "may_materialize",
                "may_execute",
                "canonical_write_allowed",
                "oos_allowed",
                "skill_rag_runtime_allowed",
            ):
                assert properties[field] == {"const": False}
    assert "subject_readback_receipt" in schema_bundle["schemas"]
    assert "target_derivation_execution_receipt" in schema_bundle["schemas"]


def test_fixture_draft_report_reference_graph_is_forward_only() -> None:
    _, _, _, _, schema_bundle, _, _, _ = _compile_all()
    fixture_schema = schema_bundle["schemas"]["synthetic_fixture_envelope"]
    for branch in fixture_schema["oneOf"]:
        properties = branch["properties"]
        assert "fixture_validation_receipt_ref" not in properties
        assert properties["future_local_draft_conformance_report_ref"] == {
            "type": "null"
        }
        preservation = properties["sibling_preservation"]["properties"]
        assert "sibling_equality_validation_receipt_ref" not in preservation
        assert "before_artifact_raw_sha256" in preservation
        assert "after_artifact_raw_sha256" in preservation
        assert "materialization_authorization" in properties
    report_schema = schema_bundle["schemas"][
        "local_fixture_draft_conformance_report"
    ]
    for branch in report_schema["oneOf"]:
        properties = branch["properties"]
        assert properties["fixture_ref"]["minLength"] == 1
        assert properties["future_formal_receipt_ref"] == {"type": "null"}
        assert properties["formal_receipt"]["const"] is False
        assert properties["validator_execution_authorization_ref"]["minLength"] == 1
        assert properties["validator_profile_activation_successor_ref"]["minLength"] == 1
    assert schema_bundle["current_local_draft_conformance_report_instance_count"] == 0


def test_assignment_tamper_and_activation_fail_closed() -> None:
    contracts, semantic_registry, proposal, _, _, handoff, _, _ = _compile_all()
    tampered_registry = copy.deepcopy(semantic_registry)
    design = tampered_registry["semantic_derivation_rows"][0][
        "closed_branch_universe"
    ][0]["materialization_design"]
    design["contract_law_pointer"] = "/DRIFTED"
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="semantic_derivation_registry_closed_equality",
    ):
        validate_expectation_semantic_derivation_registry(
            tampered_registry,
            contracts=contracts,
            b0b1_r2_manifest_path=B0B1_R2_MANIFEST,
            e1_r3_manifest_path=E1_R3_MANIFEST,
            e1_r4_manifest_path=E1_R4_MANIFEST,
            e1_r5_manifest_path=E1_R5_MANIFEST,
            e1_r6_manifest_path=E1_R6_MANIFEST,
            e1_r7_manifest_path=E1_R7_MANIFEST,
            e1_r8_manifest_path=E1_R8_MANIFEST,
            e1_r9_manifest_path=E1_R9_MANIFEST,
            e1_r9_review_manifest_path=E1_R9_REVIEW_MANIFEST,
            e1_r10_manifest_path=E1_R10_MANIFEST,
            e1_r10_review_manifest_path=E1_R10_REVIEW_MANIFEST,
            e1_r11_manifest_path=E1_R11_MANIFEST,
            e1_r11_review_manifest_path=E1_R11_REVIEW_MANIFEST,
            e1_r12_manifest_path=E1_R12_MANIFEST,
            e1_r12_review_manifest_path=E1_R12_REVIEW_MANIFEST,
            e1_r13_manifest_path=E1_R13_MANIFEST,
            e1_r13_review_manifest_path=E1_R13_REVIEW_MANIFEST,
        )
    tampered_proposal = copy.deepcopy(proposal)
    tampered_proposal["candidate_assignment_rows"][0][
        "candidate_public_reason_code"
    ] = "DRIFTED"
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="expectation_proposal_closed_equality",
    ):
        validate_expectation_assignment_proposal(
            tampered_proposal,
            contracts=contracts,
            b0b1_r2_manifest_path=B0B1_R2_MANIFEST,
            e1_r3_manifest_path=E1_R3_MANIFEST,
            e1_r4_manifest_path=E1_R4_MANIFEST,
            e1_r5_manifest_path=E1_R5_MANIFEST,
            e1_r6_manifest_path=E1_R6_MANIFEST,
            e1_r7_manifest_path=E1_R7_MANIFEST,
            e1_r8_manifest_path=E1_R8_MANIFEST,
            e1_r9_manifest_path=E1_R9_MANIFEST,
            e1_r9_review_manifest_path=E1_R9_REVIEW_MANIFEST,
            e1_r10_manifest_path=E1_R10_MANIFEST,
            e1_r10_review_manifest_path=E1_R10_REVIEW_MANIFEST,
            e1_r11_manifest_path=E1_R11_MANIFEST,
            e1_r11_review_manifest_path=E1_R11_REVIEW_MANIFEST,
            e1_r12_manifest_path=E1_R12_MANIFEST,
            e1_r12_review_manifest_path=E1_R12_REVIEW_MANIFEST,
            e1_r13_manifest_path=E1_R13_MANIFEST,
            e1_r13_review_manifest_path=E1_R13_REVIEW_MANIFEST,
            semantic_registry=semantic_registry,
        )
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="EXPECTATION_AUTHORITY_DUAL_GIT_OS_ACTIVATION_UNBOUND",
    ):
        require_expectation_activation(proposal=proposal, handoff=handoff)


def test_r9_predecessor_and_revise_review_identity_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    assert validate_e1_r9_predecessor_packet(E1_R9_MANIFEST)[
        "packet_id"
    ] == "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_E1_20260828_R9"
    assert validate_e1_r9_review_dependency_packet(E1_R9_REVIEW_MANIFEST)[
        "aggregate_verdict"
    ] == "DESIGN_ONLY_REVISE"
    assert validate_e1_r10_predecessor_packet(E1_R10_MANIFEST)[
        "packet_id"
    ] == "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_E1_20260828_R10"
    r10_review = validate_e1_r10_review_dependency_packet(
        E1_R10_REVIEW_MANIFEST
    )
    assert r10_review["aggregate_verdict"] == "DESIGN_ONLY_REVISE"
    assert (r10_review["p0_count"], r10_review["p1_count"]) == (3, 3)
    assert validate_e1_r11_predecessor_packet(E1_R11_MANIFEST)[
        "packet_id"
    ] == "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_E1_20260828_R11"
    r11_review = validate_e1_r11_review_dependency_packet(
        E1_R11_REVIEW_MANIFEST
    )
    assert r11_review["aggregate_verdict"] == "DESIGN_ONLY_REVISE"
    assert (r11_review["p0_count"], r11_review["p1_count"]) == (2, 0)
    assert validate_e1_r12_predecessor_packet(E1_R12_MANIFEST)[
        "packet_id"
    ] == "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_E1_20260828_R12"
    r12_review = validate_e1_r12_review_dependency_packet(
        E1_R12_REVIEW_MANIFEST
    )
    assert r12_review["aggregate_verdict"] == "DESIGN_ONLY_REVISE"
    assert (r12_review["p0_count"], r12_review["p1_count"]) == (1, 0)
    assert validate_e1_r13_predecessor_packet(E1_R13_MANIFEST)[
        "packet_id"
    ] == "FF_B0B_EXPECTATION_ASSIGNMENT_PROPOSAL_E1_20260828_R13"
    r13_review = validate_e1_r13_review_dependency_packet(
        E1_R13_REVIEW_MANIFEST
    )
    assert r13_review["aggregate_verdict"] == "DESIGN_ONLY_REVISE"
    assert (r13_review["p0_count"], r13_review["p1_count"]) == (0, 1)

    r9_manifest_copy = tmp_path / "r9" / "packet_manifest.json"
    r9_manifest_copy.parent.mkdir()
    r9_raw = bytearray(E1_R9_MANIFEST.read_bytes())
    r9_raw[0] = ord("[")
    r9_manifest_copy.write_bytes(r9_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r9_manifest",
    ):
        validate_e1_r9_predecessor_packet(r9_manifest_copy)

    review_manifest_copy = tmp_path / "r9-review" / "packet_manifest.json"
    review_manifest_copy.parent.mkdir()
    review_raw = bytearray(E1_R9_REVIEW_MANIFEST.read_bytes())
    review_raw[0] = ord("[")
    review_manifest_copy.write_bytes(review_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r9_review_manifest",
    ):
        validate_e1_r9_review_dependency_packet(review_manifest_copy)

    r10_manifest_copy = tmp_path / "r10" / "packet_manifest.json"
    r10_manifest_copy.parent.mkdir()
    r10_raw = bytearray(E1_R10_MANIFEST.read_bytes())
    r10_raw[0] = ord("[")
    r10_manifest_copy.write_bytes(r10_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r10_manifest",
    ):
        validate_e1_r10_predecessor_packet(r10_manifest_copy)

    r10_review_manifest_copy = (
        tmp_path / "r10-review" / "packet_manifest.json"
    )
    r10_review_manifest_copy.parent.mkdir()
    r10_review_raw = bytearray(E1_R10_REVIEW_MANIFEST.read_bytes())
    r10_review_raw[0] = ord("[")
    r10_review_manifest_copy.write_bytes(r10_review_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r10_review_manifest",
    ):
        validate_e1_r10_review_dependency_packet(r10_review_manifest_copy)

    r11_manifest_copy = tmp_path / "r11" / "packet_manifest.json"
    r11_manifest_copy.parent.mkdir()
    r11_raw = bytearray(E1_R11_MANIFEST.read_bytes())
    r11_raw[0] = ord("[")
    r11_manifest_copy.write_bytes(r11_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r11_manifest",
    ):
        validate_e1_r11_predecessor_packet(r11_manifest_copy)

    r11_review_manifest_copy = (
        tmp_path / "r11-review" / "packet_manifest.json"
    )
    r11_review_manifest_copy.parent.mkdir()
    r11_review_raw = bytearray(E1_R11_REVIEW_MANIFEST.read_bytes())
    r11_review_raw[0] = ord("[")
    r11_review_manifest_copy.write_bytes(r11_review_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r11_review_manifest",
    ):
        validate_e1_r11_review_dependency_packet(r11_review_manifest_copy)

    r12_manifest_copy = tmp_path / "r12" / "packet_manifest.json"
    r12_manifest_copy.parent.mkdir()
    r12_raw = bytearray(E1_R12_MANIFEST.read_bytes())
    r12_raw[0] = ord("[")
    r12_manifest_copy.write_bytes(r12_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r12_manifest",
    ):
        validate_e1_r12_predecessor_packet(r12_manifest_copy)

    r12_review_manifest_copy = (
        tmp_path / "r12-review" / "packet_manifest.json"
    )
    r12_review_manifest_copy.parent.mkdir()
    r12_review_raw = bytearray(E1_R12_REVIEW_MANIFEST.read_bytes())
    r12_review_raw[0] = ord("[")
    r12_review_manifest_copy.write_bytes(r12_review_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r12_review_manifest",
    ):
        validate_e1_r12_review_dependency_packet(r12_review_manifest_copy)

    r13_manifest_copy = tmp_path / "r13" / "packet_manifest.json"
    r13_manifest_copy.parent.mkdir()
    r13_raw = bytearray(E1_R13_MANIFEST.read_bytes())
    r13_raw[0] = ord("[")
    r13_manifest_copy.write_bytes(r13_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r13_manifest",
    ):
        validate_e1_r13_predecessor_packet(r13_manifest_copy)

    r13_review_manifest_copy = (
        tmp_path / "r13-review" / "packet_manifest.json"
    )
    r13_review_manifest_copy.parent.mkdir()
    r13_review_raw = bytearray(E1_R13_REVIEW_MANIFEST.read_bytes())
    r13_review_raw[0] = ord("[")
    r13_review_manifest_copy.write_bytes(r13_review_raw)
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="identity_mismatch:e1_r13_review_manifest",
    ):
        validate_e1_r13_review_dependency_packet(r13_review_manifest_copy)


def test_review_handoff_and_report_are_nonauthorizing() -> None:
    _, semantic_registry, proposal, target, schemas, handoff, inventory, report = (
        _compile_all()
    )
    assert handoff["handoff_status"] == "READY_FOR_DUAL_GIT_REVIEW__NOT_APPROVED"
    assert handoff["proposal_content_sha256"] == proposal["content_sha256"]
    assert handoff["semantic_derivation_registry_content_sha256"] == (
        semantic_registry["content_sha256"]
    )
    assert handoff["definition_generation_target_content_sha256"] == (
        target["content_sha256"]
    )
    assert handoff["closed_steward_schema_bundle_content_sha256"] == (
        schemas["content_sha256"]
    )
    assert len(handoff["branch_selection_review_targets"]) == 10
    assert [row["reviewer_role"] for row in handoff["required_reviewer_roles"]] == [
        "ontology_steward",
        "reference_steward",
    ]
    assert handoff["request_contains_response_dispositions_or_approval_refs"] is False
    assert handoff["current_external_response_count"] == 0
    assert handoff["approval_conjunction_satisfied"] is False
    assert handoff["materialization_or_execution_allowed"] is False
    assert report["local_structural_verdict"] == "LOCAL_CANDIDATE_PROPOSAL_PASS"
    assert report["blocking_verdict"] == (
        "BLOCKED_POST_R14_OPERATING_AUTHORITY_AND_IMPLEMENTATION_UNBOUND"
    )
    assert report["structural_check_count"] == 25
    assert all(row["verdict"] == "PASS" for row in report["structural_checks"])
    assert report["structural_checks"][0]["predicate_id"] == (
        "FROZEN_STAGE1B_B0B1_R2_E1_R3_TO_E1_R13_AND_EXACT5_REVISE_REVIEW_LINEAGE"
    )
    assert "exact R13 direct predecessor" in report["structural_checks"][0][
        "evidence_basis"
    ]
    assert "R9, R10, R11, R12 and R13" in report["structural_checks"][0][
        "evidence_basis"
    ]
    assert report["structural_checks"][16]["predicate_id"] == (
        "ONE_SHOT_MATERIALIZATION_CONSUMPTION_CAUSALITY"
    )
    assert "exact97 equality rows" in report["structural_checks"][16][
        "evidence_basis"
    ]
    assert report["structural_checks"][17]["predicate_id"] == (
        "EXACT86_ATOMIC_NEGATIVE_DESIGNS"
    )
    assert report["structural_checks"][18]["predicate_id"] == (
        "EXACT3_NEGATIVE_RECEIPT_INSTANTIATION_GATES_CLOSED"
    )
    assert report["structural_checks"][19]["predicate_id"] == (
        "EXACT3_NEGATIVE_RECEIPT_SCHEMA_DEFINITION_DIGEST_BINDINGS"
    )
    assert report["structural_checks"][20]["predicate_id"] == (
        "EXACT13_DONOR_PROFILE_DEFINITION_AUTHORITY_BINDINGS"
    )
    assert report["structural_checks"][21]["predicate_id"] == (
        "EXACT59_SUBORDINATE_RUNTIME_PROFILE_SELECTION_DEFINITION_AUTHORITY"
    )
    assert report["negative_receipt_instantiation_allowed"] is False
    assert report["negative_operating_delta_inference_allowed"] is False
    assert report["negative_signing_allowed"] is False
    assert report["materialization_or_execution_allowed"] is False
    assert report["authority_effect"] == "NONE"
    assert inventory["fixture_materializer_present"] is False
    assert inventory["semantic_engine_present"] is False
    assert inventory["negative_receipt_instantiator_present"] is False
    assert inventory["negative_operating_delta_adapter_present"] is False
    assert inventory["negative_signer_present"] is False


def test_expectation_proposal_packet_atomic_exact8(tmp_path: Path) -> None:
    _, semantic_registry, proposal, target, schemas, handoff, inventory, report = (
        _compile_all()
    )
    output = tmp_path / "expectation-proposal"
    manifest = write_expectation_proposal_packet(
        output,
        semantic_registry=semantic_registry,
        proposal=proposal,
        definition_target=target,
        schema_bundle=schemas,
        handoff=handoff,
        report=report,
        inventory=inventory,
    )
    assert os.fspath(output)
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert {path.name for path in output.iterdir()} == {
        "00_semantic_derivation_registry.json",
        "01_expectation_assignment_proposal.json",
        "02_candidate_definition_generation_target.json",
        "03_closed_steward_review_schema_bundle.json",
        "04_dual_git_review_handoff.json",
        "05_proposal_validation_report.json",
        "06_implementation_inventory.json",
        "packet_manifest.json",
    }
    assert manifest["artifact_count"] == 7
    assert manifest["source_contract_count"] == 18
    assert [row["role"] for row in manifest["source_contracts"]] == [
        "FROZEN_STAGE1B_SCHEMA_BUNDLE",
        "B0B1_R2_SCAFFOLD_MANIFEST",
        "E1_R3_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R4_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R5_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R6_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R7_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R8_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R9_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R9_INDEPENDENT_REVISE_REVIEW_DEPENDENCY_MANIFEST",
        "E1_R10_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R10_INDEPENDENT_REVISE_REVIEW_DEPENDENCY_MANIFEST",
        "E1_R11_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R11_INDEPENDENT_REVISE_REVIEW_DEPENDENCY_MANIFEST",
        "E1_R12_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R12_INDEPENDENT_REVISE_REVIEW_DEPENDENCY_MANIFEST",
        "E1_R13_DIRECT_FROZEN_PREDECESSOR_MANIFEST",
        "E1_R13_INDEPENDENT_REVISE_REVIEW_DEPENDENCY_MANIFEST",
    ]
    assert manifest["direct_predecessor_manifest_raw_sha256"] == (
        manifest["source_contracts"][16]["sha256"]
    )
    assert manifest["review_dependency_count"] == 5
    assert [
        row["source_contract_ordinal"]
        for row in manifest["ordered_review_dependencies"]
    ] == [9, 11, 13, 15, 17]
    assert manifest["review_dependencies_are_predecessors"] is False
    assert manifest["review_dependencies_may_authorize"] is False
    assert manifest["candidate_assignment_scope_count"] == 160
    assert manifest["closed_materialization_design_count"] == 170
    assert manifest["branch_selection_review_required_count"] == 10
    assert manifest["input_availability_sensitive_row_count"] == 11
    assert manifest["approval_conjunction_satisfied"] is False
    assert manifest["materialization_or_execution_allowed"] is False
    assert manifest["operating_review_eligible"] is False
    assert manifest["authority_effect"] == "NONE"
    assert manifest["permissions_opened_count"] == 0
    assert manifest["current_host_control_plane_root_binding_ref"] is None
    for permission_field in (
        "current_signing_allowed",
        "key_generation_allowed",
        "host_access_allowed",
        "profile_activation_allowed",
        "subject_issuance_allowed",
        "resolver_execution_allowed",
        "fixture_materialization_allowed",
        "semantic_execution_allowed",
        "admission_allowed",
        "canonical_write_allowed",
        "oos_allowed",
        "skill_rag_runtime_allowed",
        "negative_receipt_instantiation_allowed",
        "negative_operating_delta_inference_allowed",
        "negative_signing_allowed",
    ):
        assert manifest[permission_field] is False
    for path in output.iterdir():
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode)
        assert metadata.st_nlink == 1
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        json.loads(path.read_text(encoding="utf-8"))
    for row in manifest["ordered_artifacts"]:
        raw = (output / row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    loaded_semantic = json.loads(
        (output / "00_semantic_derivation_registry.json").read_text(
            encoding="utf-8"
        )
    )
    loaded_proposal = json.loads(
        (output / "01_expectation_assignment_proposal.json").read_text(
            encoding="utf-8"
        )
    )
    loaded_target = json.loads(
        (output / "02_candidate_definition_generation_target.json").read_text(
            encoding="utf-8"
        )
    )
    loaded_schemas = json.loads(
        (output / "03_closed_steward_review_schema_bundle.json").read_text(
            encoding="utf-8"
        )
    )
    validate_closed_steward_review_schema_bundle(
        loaded_schemas,
        semantic_registry=loaded_semantic,
        proposal=loaded_proposal,
        definition_target=loaded_target,
    )
    commitment = hashlib.sha256(
        b"FF_B0B_EXPECTATION_PROPOSAL_ARTIFACT_MANIFEST_V1\x00"
        + b"".join(
            bytes.fromhex(row["sha256"])
            for row in manifest["ordered_artifacts"]
        )
    ).hexdigest()
    assert commitment == manifest["artifact_manifest_commitment_sha256"]
    with pytest.raises(
        EpistemicExpectationProposalError,
        match="proposal_output_root_exists",
    ):
        write_expectation_proposal_packet(
            output,
            semantic_registry=semantic_registry,
            proposal=proposal,
            definition_target=target,
            schema_bundle=schemas,
            handoff=handoff,
            report=report,
            inventory=inventory,
        )


def test_expectation_proposal_surface_inventory_is_closed() -> None:
    inventory = build_expectation_proposal_inventory(REPO_ROOT)
    assert inventory["implementation_file_count"] == 3
    assert inventory["dependency_file_count"] == 5
    assert inventory["fixture_materializer_present"] is False
    assert inventory["semantic_engine_present"] is False
    assert inventory["live_host_adapter_present"] is False
    assert inventory["network_adapter_present"] is False
    assert all(
        row["surface_analysis"]["surface_verdict"] == "PASS"
        and not row["surface_analysis"][
            "forbidden_network_crypto_dynamic_execution_hits"
        ]
        for row in inventory["ordered_implementation_files"]
    )
