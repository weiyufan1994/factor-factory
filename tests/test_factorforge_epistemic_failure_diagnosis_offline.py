from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from factor_factory.epistemic_failure_diagnosis_offline import (
    FailureDiagnosisOfflineError,
    STAGE2_PACKET_ARTIFACT_DOMAIN,
    STAGE2_PACKET_DOMAIN,
    compile_distinguishing_test_registry_candidate,
    compile_exploit_explore_dirac_advisory_candidate,
    compile_hypothesis_mismatch_candidate,
    compile_layer_assessment_plan_candidate,
    compile_material_rival_registry_candidate,
    compile_partition_independence_plan_candidate,
    compile_planner_terminal_candidate,
    compile_stage2_input_binding,
    compile_synthetic_diagnosis_intake,
    validate_failure_diagnosis_planner_bundle,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


FIXTURE_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-20260829/diagnosis-fixture.json"
)
STAGE2_MANIFEST = Path(
    "/Users/researcher/projects/"
    "factor-forge-phase-safe-retrieval-standalone-prototype-r3-20260829/packet_manifest.json"
)
ASSERTION_DAG_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-r3-20260829/"
    "assertion-dependency-dag.json"
)


def _fixture() -> tuple[dict, str]:
    raw = FIXTURE_PATH.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _assertion_dag() -> tuple[dict, str]:
    raw = ASSERTION_DAG_PATH.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def _intake(fixture: dict, raw_sha: str, *, dag: dict | None = None) -> dict:
    dependency, dependency_sha = _assertion_dag()
    if dag is not None:
        dependency = dag
        dependency_sha = hashlib.sha256(
            json.dumps(dag, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    return compile_synthetic_diagnosis_intake(
        fixture,
        fixture_raw_sha256=raw_sha,
        assertion_dependency_payload=dependency,
        assertion_dependency_raw_sha256=dependency_sha,
    )


@pytest.fixture(scope="module")
def stage2_binding() -> dict:
    return compile_stage2_input_binding(STAGE2_MANIFEST)


def _compile(fixture: dict, raw_sha: str, stage2_binding: dict) -> dict[str, dict]:
    intake = _intake(fixture, raw_sha)
    hypothesis = compile_hypothesis_mismatch_candidate(intake)
    rivals = compile_material_rival_registry_candidate(intake, hypothesis)
    partition = compile_partition_independence_plan_candidate(intake, rivals)
    tests = compile_distinguishing_test_registry_candidate(
        intake, rivals, partition
    )
    layers = compile_layer_assessment_plan_candidate(
        intake, hypothesis, rivals, tests
    )
    advisory = compile_exploit_explore_dirac_advisory_candidate(
        intake, hypothesis, rivals, tests, layers
    )
    terminal = compile_planner_terminal_candidate(
        intake, hypothesis, partition, tests, layers, advisory
    )
    return {
        "intake": intake,
        "hypothesis": hypothesis,
        "rivals": rivals,
        "partition": partition,
        "tests": tests,
        "layers": layers,
        "advisory": advisory,
        "terminal": terminal,
    }


def _validate(bundle: dict[str, dict], stage2_binding: dict) -> None:
    validate_failure_diagnosis_planner_bundle(
        stage2_binding=stage2_binding,
        intake=bundle["intake"],
        hypothesis=bundle["hypothesis"],
        rival_registry=bundle["rivals"],
        partition_plan=bundle["partition"],
        test_registry=bundle["tests"],
        layer_plan=bundle["layers"],
        advisory=bundle["advisory"],
        terminal=bundle["terminal"],
    )


def test_demo_fixture_compiles_exact_l0_l9_and_required_rival_roles(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    bundle = _compile(fixture, raw_sha, stage2_binding)

    assert [row["layer_id"] for row in bundle["layers"]["layer_rows"]] == [
        f"L{ordinal}" for ordinal in range(10)
    ]
    assert bundle["layers"]["layer_count"] == 10
    assert {row["role"] for row in bundle["rivals"]["material_rivals"]} == {
        "PREFERRED_MECHANISM",
        "MECHANISM_DISTINCT_ALTERNATIVE",
        "NULL_OR_ALIAS",
    }
    assert bundle["rivals"]["material_rival_count"] == 3
    _validate(bundle, stage2_binding)


def test_material_assertion_dag_expands_exact_transitive_and_global_scope(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    layers = _compile(fixture, raw_sha, stage2_binding)["layers"]

    assert layers["material_assertion_dependency_dag"]["edge_count"] == 6
    assert layers["material_transitive_prerequisite_pair_count"] == 6
    assert layers["global_hard_gate_requirement_count"] == 4 * 9
    assert layers["expanded_material_scope_row_count"] == 42
    assert (
        layers[
            "expanded_material_scope_is_exact_union_of_transitive_dag_and_global_hard_gates"
        ]
        is True
    )
    receipt_keys = [
        row["receipt_key_sha256"] for row in layers["expanded_material_scope_rows"]
    ]
    assert len(receipt_keys) == len(set(receipt_keys))
    payer_prerequisites = {
        row["required_prerequisite_id"]
        for row in layers["expanded_material_scope_rows"]
        if row["target_assertion_id"] == "assertion-payer-constraint"
        and row["scope_kind"] == "MATERIAL_TRANSITIVE_ASSERTION_PREREQUISITE"
    }
    assert payer_prerequisites == {
        "assertion-observation-state",
        "assertion-volatility-alias",
        "assertion-kernel-timescale",
    }
    assert all(
        row["required_status"] == "CLEARED"
        and row["receipt_selection_law"]
        == "EXACT_ONE_LATEST_NONREVOKED_INDEPENDENT_HEAD"
        and row["current_receipt_present"] is False
        and row["same_trial_control_substitution_allowed"] is False
        for row in layers["expanded_material_scope_rows"]
    )


def test_nonforward_or_cyclic_material_edge_is_rejected() -> None:
    fixture, raw_sha = _fixture()
    dag, _ = _assertion_dag()
    dag["edges"][0]["prerequisite_assertion_id"] = "assertion-payer-constraint"
    dag["edges"][0]["dependent_assertion_id"] = "assertion-observation-state"

    with pytest.raises(FailureDiagnosisOfflineError, match="nonforward_or_cyclic_edge"):
        _intake(fixture, raw_sha, dag=dag)


def test_duplicate_material_edge_pair_is_rejected() -> None:
    fixture, raw_sha = _fixture()
    dag, _ = _assertion_dag()
    duplicate = copy.deepcopy(dag["edges"][0])
    duplicate["edge_id"] = "edge-duplicate-pair"
    dag["edges"].append(duplicate)

    with pytest.raises(FailureDiagnosisOfflineError, match="duplicate_endpoint_pair"):
        _intake(fixture, raw_sha, dag=dag)


def test_tests_are_discriminating_and_cover_every_rival(stage2_binding: dict) -> None:
    fixture, raw_sha = _fixture()
    bundle = _compile(fixture, raw_sha, stage2_binding)
    registry = bundle["tests"]
    rival_ids = {row["rival_id"] for row in bundle["rivals"]["material_rivals"]}

    assert registry["applicability_complete"] is True
    assert registry["applicability_row_count"] == (
        registry["registered_test_count"] * len(rival_ids)
    )
    for test in registry["registered_tests"]:
        assert set(test["rival_ids"]) == rival_ids
        assert len(
            {row["signature"] for row in test["expected_signature_by_rival"]}
        ) >= 2
    assert registry["all_material_rivals_jointly_distinguishable_in_plan"] is True


def test_non_discriminating_test_is_rejected_at_intake() -> None:
    fixture, raw_sha = _fixture()
    for row in fixture["tests"][0]["expected_signature_by_rival"]:
        row["signature"] = "SAME_SIGNATURE"
    with pytest.raises(FailureDiagnosisOfflineError, match="not_discriminating"):
        _intake(fixture, raw_sha)


def test_missing_required_rival_role_is_rejected() -> None:
    fixture, raw_sha = _fixture()
    fixture["rivals"] = fixture["rivals"][:2]
    with pytest.raises(FailureDiagnosisOfflineError, match="min_three_material_rivals"):
        _intake(fixture, raw_sha)


def test_generation_confirmation_overlap_is_fail_closed_terminal(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    fixture["partition_plan"]["confirmation_member_ids"][0] = fixture[
        "partition_plan"
    ]["generation_member_ids"][0]
    bundle = _compile(fixture, raw_sha, stage2_binding)

    assert bundle["partition"]["synthetic_nonoverlap_candidate_pass"] is False
    assert bundle["partition"]["identified_cause_allowed"] is False
    assert bundle["terminal"]["planner_disposition"] == (
        "BLOCKED_PARTITION_INDEPENDENCE"
    )
    assert bundle["terminal"]["ordered_block_or_inconclusive_reasons"][0][
        "reason_code"
    ] == "GENERATION_CONFIRMATION_MEMBER_OVERLAP"


@pytest.mark.parametrize(
    "field", ["metric_values_present", "production_identity_present"]
)
def test_metric_and_production_fields_are_rejected(field: str) -> None:
    fixture, raw_sha = _fixture()
    fixture["validity_intake"][field] = True
    with pytest.raises(FailureDiagnosisOfflineError):
        _intake(fixture, raw_sha)


@pytest.mark.parametrize("injected", ["CONTROLLED", "IDENTIFIED"])
def test_controlled_or_identified_layer_injection_fails_closed_equality(
    stage2_binding: dict, injected: str
) -> None:
    fixture, raw_sha = _fixture()
    bundle = _compile(fixture, raw_sha, stage2_binding)
    tampered = copy.deepcopy(bundle)
    tampered["layers"]["layer_rows"][3]["assessment_state_candidate"] = injected

    with pytest.raises(FailureDiagnosisOfflineError, match="layer_plan_closed_equality"):
        _validate(tampered, stage2_binding)


def test_both_exploit_and_explore_may_abstain_without_dummy_branch(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    for lane_name in ("exploit_lane", "explore_lane"):
        fixture[lane_name] = {
            "disposition": "ABSTAINED_WITH_REASON",
            "candidates": [],
            "reason": "当前证据不足以形成不增加识别债务的候选。",
        }
    bundle = _compile(fixture, raw_sha, stage2_binding)

    assert bundle["advisory"]["both_lanes_may_abstain"] is True
    assert bundle["advisory"]["dummy_branch_required"] is False
    assert bundle["advisory"]["exploit_lane"]["candidate_count"] == 0
    assert bundle["advisory"]["explore_lane"]["candidate_count"] == 0
    assert bundle["advisory"]["branch_selection_or_execution_allowed"] is False


@pytest.mark.parametrize(
    ("lane", "field", "value"),
    [
        ("exploit_lane", "portfolio_repair", True),
        ("exploit_lane", "same_parent_hypothesis", False),
        ("explore_lane", "portfolio_repair", True),
        ("explore_lane", "reuses_parent_identity", True),
        ("explore_lane", "uses_parent_or_current_oos", True),
    ],
)
def test_portfolio_repair_parent_identity_and_oos_flags_are_rejected(
    lane: str, field: str, value: bool
) -> None:
    fixture, raw_sha = _fixture()
    fixture[lane]["candidates"][0][field] = value
    with pytest.raises(FailureDiagnosisOfflineError):
        _intake(fixture, raw_sha)


def test_stage2_a0_rows_are_not_consumed_across_phase_boundary(
    stage2_binding: dict,
    tmp_path: Path,
) -> None:
    fixture, raw_sha = _fixture()
    bundle = _compile(fixture, raw_sha, stage2_binding)
    advisory = bundle["advisory"]

    manifest_only_root = tmp_path / "manifest-only-stage2"
    manifest_only_root.mkdir()
    manifest_copy = manifest_only_root / "packet_manifest.json"
    manifest_copy.write_bytes(STAGE2_MANIFEST.read_bytes())
    assert compile_stage2_input_binding(manifest_copy) == stage2_binding

    binding_text = json.dumps(stage2_binding, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "private_sanitized_semantic_candidate",
        "score_total",
        "object_id",
        "structural_isomorph",
    ):
        assert forbidden not in binding_text
    assert stage2_binding["cross_phase_semantic_consumption_allowed"] is False
    access = stage2_binding["semantic_payload_access_policy"]
    assert access["selection_ledger_opened"] is False
    assert access["returned_rows_deserialized"] is False
    assert access["lane_score_object_or_semantic_candidate_read"] is False
    assert access["stage2_artifact_paths_dereferenced"] is False
    assert access["changing_a0_returned_semantics_may_change_this_projection"] is False
    assert stage2_binding["implementation_provenance_projection"][
        "stage2_artifact_payload_bytes_read"
    ] == 0
    assert bundle["rivals"]["advisory_prior_rows"] == []
    assert bundle["rivals"]["advisory_prior_count"] == 0
    assert bundle["rivals"]["stage2_a0_rows_consumed"] is False
    assert advisory["stage2_a0_cross_phase_consumption_allowed"] is False
    assert advisory["future_question_count"] == 1
    assert all(
        row["source_kind"] == "LOCAL_BLIND_DERIVATION_CANDIDATE"
        and row["namespace"] == "FUTURE_QUESTION_ONLY"
        and row["current_diagnosis_or_revision_writeback_allowed"] is False
        for row in advisory["future_question_namespace"]
    )
    assert advisory["post_result_new_rival_current_use_allowed"] is False
    assert advisory["future_phase_safe_retrieval_handoff"] == {
        "required_phase_branch": "B2_POSTRESULT_PLAN_SUPPORT",
        "current_prototype_invocation_status": "NOT_INVOKED_STANDALONE_PROTOTYPE",
        "may_implement_only_preexisting_rival_prediction_and_test_intents": True,
        "may_add_current_rival_prediction_or_test_intent": False,
        "post_result_new_explanation_namespace": "FUTURE_QUESTION_ONLY",
    }


def test_consistent_stage2_response_hash_changes_do_not_change_provenance_projection(
    stage2_binding: dict,
    tmp_path: Path,
) -> None:
    manifest = json.loads(STAGE2_MANIFEST.read_bytes())
    manifest["phase_projection_content_sha256"] = "a" * 64
    manifest["private_full_world_sidecar"]["corpus_content_sha256"] = "b" * 64
    manifest["private_full_world_sidecar"]["corpus_manifest_commitment_sha256"] = "c" * 64
    for ordinal in (3, 4, 5):
        manifest["ordered_artifacts"][ordinal]["sha256"] = f"{ordinal + 1:064x}"
    manifest["artifact_manifest_commitment_sha256"] = hashlib.sha256(
        STAGE2_PACKET_ARTIFACT_DOMAIN.encode("utf-8")
        + b"\x00"
        + b"".join(
            bytes.fromhex(row["sha256"]) for row in manifest["ordered_artifacts"]
        )
    ).hexdigest()
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    manifest["content_sha256"] = framed_sha256(STAGE2_PACKET_DOMAIN, core)
    path = tmp_path / "mutated-stage2-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n")

    assert compile_stage2_input_binding(path) == stage2_binding


def test_pre_dirac_remains_fixed_not_eligible(stage2_binding: dict) -> None:
    fixture, raw_sha = _fixture()
    advisory = _compile(fixture, raw_sha, stage2_binding)["advisory"]
    projection = advisory["dirac_eligibility_projection"]

    assert projection["dirac_status"] == "NOT_ELIGIBLE_STANDALONE_PROTOTYPE"
    assert projection["host_qualified_contradiction_receipt_present"] is False
    assert projection["lower_layers_all_cleared"] is False
    assert projection["formal_delta_allowed"] is False
    assert advisory["child_identity_or_handoff_allowed"] is False


def test_budget_exhaustion_has_legitimate_inconclusive_terminal(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    fixture["trial_controls"]["trial_budget"] = 2
    bundle = _compile(fixture, raw_sha, stage2_binding)

    assert bundle["tests"]["budget_plan_feasible"] is False
    assert bundle["terminal"]["planner_disposition"] == (
        "INCONCLUSIVE_NO_IDENTIFIABLE_DESIGN_WITHIN_BUDGET"
    )
    assert bundle["terminal"]["cause_identified"] is False


def test_unidentifiable_assertion_has_legitimate_inconclusive_terminal(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    assertion = fixture["assertions"][0]
    assertion["planned_partition"] = "UNIDENTIFIABLE"
    assertion["observation_identifiability"] = (
        "UNIDENTIFIABLE_FROM_CURRENT_OBSERVATION_EQUATION"
    )
    bundle = _compile(fixture, raw_sha, stage2_binding)

    assert bundle["terminal"]["planner_disposition"] == (
        "INCONCLUSIVE_UNIDENTIFIABLE_DESIGN"
    )
    assert bundle["terminal"]["cause_identified"] is False
    assert bundle["terminal"]["review_eligible"] is False


def test_unknown_fixture_field_is_rejected_by_closed_intake() -> None:
    fixture, raw_sha = _fixture()
    fixture["identified_cause"] = "caller-selected"
    with pytest.raises(FailureDiagnosisOfflineError, match="fixture:closed_fields"):
        _intake(fixture, raw_sha)


def test_tampered_derived_artifact_fails_bundle_closed_equality(
    stage2_binding: dict,
) -> None:
    fixture, raw_sha = _fixture()
    bundle = _compile(fixture, raw_sha, stage2_binding)
    tampered = copy.deepcopy(bundle)
    tampered["terminal"]["qualification_allowed"] = True

    with pytest.raises(FailureDiagnosisOfflineError, match="terminal_closed_equality"):
        _validate(tampered, stage2_binding)
