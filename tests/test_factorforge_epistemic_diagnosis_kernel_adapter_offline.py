from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import factor_factory.epistemic_diagnosis_kernel_adapter_offline as adapter
from factor_factory.epistemic_diagnosis_kernel_adapter_offline import (
    ADAPTER_DOMAIN,
    DiagnosisKernelAdapterError,
    compile_diagnosis_kernel_candidate,
    validate_diagnosis_kernel_candidate,
)
from factor_factory.epistemic_failure_diagnosis_offline import (
    INTAKE_DOMAIN,
    STAGE2_PACKET_DOMAIN,
    compile_distinguishing_test_registry_candidate,
    compile_exploit_explore_dirac_advisory_candidate,
    compile_hypothesis_mismatch_candidate,
    compile_layer_assessment_plan_candidate,
    compile_material_rival_registry_candidate,
    compile_partition_independence_plan_candidate,
    compile_planner_terminal_candidate,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


FIXTURE_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-20260829/diagnosis-fixture.json"
)
ASSERTION_DAG_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-r3-20260829/"
    "assertion-dependency-dag.json"
)
STAGE2_MANIFEST = Path(
    "/Users/researcher/projects/"
    "factor-forge-phase-safe-retrieval-standalone-prototype-r3-20260829/"
    "packet_manifest.json"
)
SOURCE_SESSION_SHA256 = "a" * 64


def _payload(path: Path) -> tuple[bytes, dict]:
    raw = path.read_bytes()
    return raw, json.loads(raw)


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _rehash(payload: dict, *, domain: str) -> dict:
    core = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = framed_sha256(domain, core)
    return payload


def _candidate(
    *,
    fixture: dict | None = None,
    stage2_raw: bytes | None = None,
    session_id: str = "offline-demo-session",
    source_session_content_sha256: str = SOURCE_SESSION_SHA256,
) -> tuple[dict, bytes, bytes, bytes]:
    fixture_raw, _ = _payload(FIXTURE_PATH)
    if fixture is not None:
        fixture_raw = _json_bytes(fixture)
    dag_raw = ASSERTION_DAG_PATH.read_bytes()
    if stage2_raw is None:
        stage2_raw = STAGE2_MANIFEST.read_bytes()
    candidate = compile_diagnosis_kernel_candidate(
        session_id=session_id,
        source_session_content_sha256=source_session_content_sha256,
        stage2_manifest_raw_bytes=stage2_raw,
        fixture_raw_bytes=fixture_raw,
        assertion_dependency_raw_bytes=dag_raw,
    )
    return candidate, stage2_raw, fixture_raw, dag_raw


def test_compiles_replayable_step4_step5_agent_projection() -> None:
    candidate, stage2_raw, fixture_raw, dag_raw = _candidate()
    projection = candidate["agent_visible_projection"]

    assert projection["projection_kind"] == "STEP4_STEP5_FAILURE_DIAGNOSIS_PLAN_ADVISORY"
    assert len(projection["material_rivals"]) == 3
    assert {row["role"] for row in projection["material_rivals"]} == {
        "PREFERRED_MECHANISM",
        "MECHANISM_DISTINCT_ALTERNATIVE",
        "NULL_OR_ALIAS",
    }
    assert [row["layer_id"] for row in projection["layers"]] == [
        f"L{ordinal}" for ordinal in range(10)
    ]
    assert projection["controlled_or_localized_can_substitute_for_cleared"] is False
    assert projection["terminal"]["cause_identified"] is False
    assert projection["terminal"]["qualification_allowed"] is False
    validate_diagnosis_kernel_candidate(
        candidate,
        session_id="offline-demo-session",
        source_session_content_sha256=SOURCE_SESSION_SHA256,
        stage2_manifest_raw_bytes=stage2_raw,
        fixture_raw_bytes=fixture_raw,
        assertion_dependency_raw_bytes=dag_raw,
    )


def test_generation_confirmation_overlap_is_visible_and_fail_closed() -> None:
    _, fixture = _payload(FIXTURE_PATH)
    fixture["partition_plan"]["confirmation_member_ids"][0] = fixture[
        "partition_plan"
    ]["generation_member_ids"][0]
    candidate, _, _, _ = _candidate(fixture=fixture)
    projection = candidate["agent_visible_projection"]

    assert projection["generation_confirmation_nonoverlap_candidate"] is False
    assert projection["terminal"]["disposition"] == "BLOCKED_PARTITION_INDEPENDENCE"
    assert projection["terminal"]["reasons"] == [
        "GENERATION_CONFIRMATION_MEMBER_OVERLAP"
    ]


def test_agent_projection_tamper_is_rejected() -> None:
    candidate, stage2_raw, fixture_raw, dag_raw = _candidate()
    tampered = copy.deepcopy(candidate)
    tampered["agent_visible_projection"]["terminal"]["cause_identified"] = True

    with pytest.raises(DiagnosisKernelAdapterError, match="agent_projection_mismatch"):
        validate_diagnosis_kernel_candidate(
            tampered,
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=stage2_raw,
            fixture_raw_bytes=fixture_raw,
            assertion_dependency_raw_bytes=dag_raw,
        )


def test_stage2_manifest_raw_identity_mismatch_is_rejected() -> None:
    candidate, stage2_raw, fixture_raw, dag_raw = _candidate()
    semantically_equal_different_bytes = b"\n" + stage2_raw

    with pytest.raises(DiagnosisKernelAdapterError, match="stage2_lineage_mismatch"):
        validate_diagnosis_kernel_candidate(
            candidate,
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=semantically_equal_different_bytes,
            fixture_raw_bytes=fixture_raw,
            assertion_dependency_raw_bytes=dag_raw,
        )


def test_output_has_no_metric_verdict_or_execution_authority() -> None:
    candidate, _, _, _ = _candidate()

    assert candidate["diagnostic_tests_executed"] is False
    assert candidate["cause_identified"] is False
    assert candidate["qualification_allowed"] is False
    assert candidate["canonical_or_oos_accessed"] is False
    assert candidate["authority_effect"] == "NONE"
    assert candidate["agent_visible_projection"]["metric_is_not_cause"] is True


def test_agent_projection_preserves_required_diagnosis_fields() -> None:
    candidate, _, _, _ = _candidate()
    projection = candidate["agent_visible_projection"]
    native = candidate["native_artifacts"]
    lineage = projection["lineage"]

    assert lineage["diagnosis_id"] == candidate["diagnosis_id"]
    assert lineage["diagnosis_identity_content_sha256"] == candidate[
        "diagnosis_identity"
    ]["diagnosis_identity_content_sha256"]
    assert lineage["source_session"] == candidate["diagnosis_identity"][
        "source_session"
    ]
    assert lineage["stage2"]["manifest_raw_sha256"] == candidate[
        "stage2_lineage"
    ]["manifest_raw_sha256"]
    assert lineage["stage2"]["derived_binding_content_sha256"] == candidate[
        "stage2_binding_content_sha256"
    ]
    assert lineage["diagnosis_inputs"] == candidate["diagnosis_identity"][
        "diagnosis_inputs"
    ]
    assert lineage["target_hashes"] == candidate["diagnosis_identity"]["target"]
    assert lineage["stage2"]["semantic_payload_accessed"] is False
    assert lineage["authority_effect"] == "NONE"

    assert len(projection["signature_comparison"]) == len(
        native["hypothesis"]["mechanical_mismatch_vector"]
    )
    assert {
        row["dimension"] for row in projection["material_mismatches"]
    } == {
        row["dimension"]
        for row in native["hypothesis"]["mechanical_mismatch_vector"]
        if row["mismatch_candidate"]
    }
    assert set(projection["material_rivals"][0]) == {
        "rival_id",
        "role",
        "target_assertion_ids",
        "target_layer_ids",
        "mechanism",
        "predicted_signature",
        "materiality_floor_candidate",
        "falsifier",
        "distinguishing_test_ids",
        "knowledge_role",
        "evidence_use",
        "synthetic_freeze_order_candidate_only",
        "formal_pre_evidence_freeze_claimed",
    }
    assert projection["rival_registry_guard"]["material_rival_count"] == len(
        projection["material_rivals"]
    )
    assert projection["rival_registry_guard"][
        "post_result_rival_addition_allowed"
    ] is False
    assert set(projection["distinguishing_tests"][0]) == {
        "test_id",
        "question",
        "target_assertion_ids",
        "rival_ids",
        "synthetic_input_roles",
        "statistic_semantics",
        "expected_signature_by_rival",
        "materiality_floor_candidate",
        "correction_law_candidate",
        "missing_data_disposition",
        "nonfinite_disposition",
        "budget_charge_candidate",
        "result_fields_structurally_absent",
        "execution_allowed",
        "same_information_set_and_formation_mask_required",
        "future_label_membership_mutation_allowed",
    }
    assert set(projection["layers"][0]) == {
        "layer_id",
        "layer_name",
        "assessment_state_candidate",
        "assertion_ids",
        "material_transitive_prerequisite_assertion_ids",
        "global_evo_hard_gate_criteria_ids",
        "planned_test_ids",
        "formal_assessment_status_present",
        "independent_clearance_receipt_present",
    }
    assert "assessment" not in projection["layers"][0]
    assert projection["partition_plan"]["reservation_order_candidate"] == native[
        "partition"
    ]["reservation_order_candidate"]
    assert projection["partition_plan"]["selection_correction_candidate"] == native[
        "partition"
    ]["selection_correction_candidate"]
    assert projection["qualification_guard"][
        "expanded_material_scope_row_count"
    ] == len(projection["qualification_guard"]["expanded_material_scope_rows"])
    assert projection["qualification_guard"][
        "latest_independent_assessment_receipts_present"
    ] is False
    assert projection["qualification_guard"]["qualification_allowed"] is False
    assert projection["test_plan_guard"]["registered_test_count"] == len(
        projection["distinguishing_tests"]
    )
    assert projection["test_plan_guard"]["applicability_complete"] is True
    assert projection["test_plan_guard"]["results_present"] is False
    assert projection["test_plan_guard"]["execution_allowed"] is False
    assert all(
        row["current_diagnosis_or_revision_writeback_allowed"] is False
        for row in projection["future_questions"]
    )
    assert projection["advisory_guard"][
        "post_result_new_rival_current_use_allowed"
    ] is False


def test_raw_bytes_are_strictly_parsed_and_exactly_bound() -> None:
    candidate, stage2_raw, fixture_raw, dag_raw = _candidate()

    with pytest.raises(DiagnosisKernelAdapterError, match="fixture_raw_bytes:invalid_json"):
        compile_diagnosis_kernel_candidate(
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=stage2_raw,
            fixture_raw_bytes=b'{"schema_id":"first","schema_id":"second"}',
            assertion_dependency_raw_bytes=dag_raw,
        )

    semantically_equal_different_bytes = b"\n" + fixture_raw
    with pytest.raises(DiagnosisKernelAdapterError, match="intake_replay_mismatch"):
        validate_diagnosis_kernel_candidate(
            candidate,
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=stage2_raw,
            fixture_raw_bytes=semantically_equal_different_bytes,
            assertion_dependency_raw_bytes=dag_raw,
        )

    _, fixture = _payload(FIXTURE_PATH)
    fixture["hidden_oos_or_canonical_payload"] = {"not_allowed": True}
    with pytest.raises(ValueError, match="closed_fields"):
        compile_diagnosis_kernel_candidate(
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=stage2_raw,
            fixture_raw_bytes=_json_bytes(fixture),
            assertion_dependency_raw_bytes=dag_raw,
        )


def test_coordinated_extra_field_and_full_rehash_still_fail_intake_replay() -> None:
    candidate, stage2_raw, fixture_raw, dag_raw = _candidate()
    tampered = copy.deepcopy(candidate)
    intake = tampered["native_artifacts"]["intake"]
    intake["hidden_oos_or_canonical_payload"] = {
        "canonical_ref": "forbidden",
        "oos_metric_basis_points": 990,
    }
    intake_core = {
        key: value for key, value in intake.items() if key != "content_sha256"
    }
    intake["content_sha256"] = framed_sha256(INTAKE_DOMAIN, intake_core)

    hypothesis = compile_hypothesis_mismatch_candidate(intake)
    rivals = compile_material_rival_registry_candidate(intake, hypothesis)
    partition = compile_partition_independence_plan_candidate(intake, rivals)
    tests = compile_distinguishing_test_registry_candidate(intake, rivals, partition)
    layers = compile_layer_assessment_plan_candidate(
        intake,
        hypothesis,
        rivals,
        tests,
    )
    advisory = compile_exploit_explore_dirac_advisory_candidate(
        intake,
        hypothesis,
        rivals,
        tests,
        layers,
    )
    terminal = compile_planner_terminal_candidate(
        intake,
        hypothesis,
        partition,
        tests,
        layers,
        advisory,
    )
    artifacts = {
        "intake": intake,
        "hypothesis": hypothesis,
        "rivals": rivals,
        "partition": partition,
        "tests": tests,
        "layers": layers,
        "advisory": advisory,
        "terminal": terminal,
    }
    tampered["native_artifacts"] = artifacts
    tampered["agent_visible_projection"] = adapter._agent_projection(
        artifacts,
        diagnosis_id=tampered["diagnosis_id"],
        diagnosis_identity=tampered["diagnosis_identity"],
        stage2_lineage=tampered["stage2_lineage"],
    )
    outer_core = {
        key: value for key, value in tampered.items() if key != "content_sha256"
    }
    tampered["content_sha256"] = framed_sha256(ADAPTER_DOMAIN, outer_core)

    with pytest.raises(DiagnosisKernelAdapterError, match="intake_replay_mismatch"):
        validate_diagnosis_kernel_candidate(
            tampered,
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=stage2_raw,
            fixture_raw_bytes=fixture_raw,
            assertion_dependency_raw_bytes=dag_raw,
        )


def test_stage2_manifest_hidden_payload_is_rejected_after_coordinated_rehash() -> None:
    stage2_raw, stage2_payload = _payload(STAGE2_MANIFEST)
    fixture_raw = FIXTURE_PATH.read_bytes()
    dag_raw = ASSERTION_DAG_PATH.read_bytes()
    stage2_payload["private_full_world_sidecar"][
        "hidden_oos_or_canonical_payload"
    ] = {
        "canonical_memory_ref": "forbidden",
        "oos_result_basis_points": 990,
    }
    forged_raw = _json_bytes(_rehash(stage2_payload, domain=STAGE2_PACKET_DOMAIN))

    with pytest.raises(
        DiagnosisKernelAdapterError,
        match="stage2_manifest:closed_compiler_replay_failed",
    ):
        compile_diagnosis_kernel_candidate(
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_raw_bytes=forged_raw,
            fixture_raw_bytes=fixture_raw,
            assertion_dependency_raw_bytes=dag_raw,
        )

    with pytest.raises(TypeError, match="stage2_binding"):
        compile_diagnosis_kernel_candidate(
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_binding={"content_sha256": "0" * 64},  # type: ignore[call-arg]
            fixture_raw_bytes=fixture_raw,
            assertion_dependency_raw_bytes=dag_raw,
        )

    assert stage2_raw != forged_raw


def test_diagnosis_id_binds_source_stage2_fixture_dag_and_target_identities() -> None:
    base, stage2_raw, fixture_raw, dag_raw = _candidate()
    repeat, _, _, _ = _candidate()
    assert repeat["diagnosis_id"] == base["diagnosis_id"]

    source_changed, _, _, _ = _candidate(
        source_session_content_sha256="b" * 64
    )
    assert source_changed["diagnosis_id"] != base["diagnosis_id"]

    session_changed, _, _, _ = _candidate(session_id="offline-demo-session-2")
    assert session_changed["diagnosis_id"] != base["diagnosis_id"]

    stage2_raw_changed, _, _, _ = _candidate(stage2_raw=b"\n" + stage2_raw)
    assert stage2_raw_changed["diagnosis_id"] != base["diagnosis_id"]
    assert (
        stage2_raw_changed["stage2_binding_content_sha256"]
        == base["stage2_binding_content_sha256"]
    )

    _, stage2_payload = _payload(STAGE2_MANIFEST)
    stage2_payload["packet_id"] = f"{stage2_payload['packet_id']}_ALTERNATE"
    stage2_binding_changed_raw = _json_bytes(
        _rehash(stage2_payload, domain=STAGE2_PACKET_DOMAIN)
    )
    stage2_binding_changed, _, _, _ = _candidate(
        stage2_raw=stage2_binding_changed_raw
    )
    assert (
        stage2_binding_changed["stage2_binding_content_sha256"]
        != base["stage2_binding_content_sha256"]
    )
    assert stage2_binding_changed["diagnosis_id"] != base["diagnosis_id"]

    fixture_raw_changed_candidate = compile_diagnosis_kernel_candidate(
        session_id="offline-demo-session",
        source_session_content_sha256=SOURCE_SESSION_SHA256,
        stage2_manifest_raw_bytes=stage2_raw,
        fixture_raw_bytes=b"\n" + fixture_raw,
        assertion_dependency_raw_bytes=dag_raw,
    )
    assert fixture_raw_changed_candidate["diagnosis_id"] != base["diagnosis_id"]

    dag_raw_changed_candidate = compile_diagnosis_kernel_candidate(
        session_id="offline-demo-session",
        source_session_content_sha256=SOURCE_SESSION_SHA256,
        stage2_manifest_raw_bytes=stage2_raw,
        fixture_raw_bytes=fixture_raw,
        assertion_dependency_raw_bytes=b"\n" + dag_raw,
    )
    assert dag_raw_changed_candidate["diagnosis_id"] != base["diagnosis_id"]

    _, target_changed_fixture = _payload(FIXTURE_PATH)
    target_changed_fixture["target_identity_candidate"]["hypothesis_candidate_id"] += "-alternate"
    target_changed, _, _, _ = _candidate(fixture=target_changed_fixture)
    assert target_changed["diagnosis_id"] != base["diagnosis_id"]
    assert (
        target_changed["diagnosis_identity"]["target"][
            "target_identity_content_sha256"
        ]
        != base["diagnosis_identity"]["target"][
            "target_identity_content_sha256"
        ]
    )


def test_stage2_path_and_raw_bind_same_diagnosis_identity_but_expose_transport() -> None:
    raw_candidate, stage2_raw, fixture_raw, dag_raw = _candidate()
    path_candidate = compile_diagnosis_kernel_candidate(
        session_id="offline-demo-session",
        source_session_content_sha256=SOURCE_SESSION_SHA256,
        stage2_manifest_path=STAGE2_MANIFEST,
        fixture_raw_bytes=fixture_raw,
        assertion_dependency_raw_bytes=dag_raw,
    )

    assert path_candidate["diagnosis_id"] == raw_candidate["diagnosis_id"]
    assert path_candidate["diagnosis_identity"] == raw_candidate["diagnosis_identity"]
    assert path_candidate["stage2_lineage"]["input_mode"] == "STABLE_REGULAR_FILE_READ"
    assert raw_candidate["stage2_lineage"]["input_mode"] == "EXPLICIT_RAW_BYTES"
    assert path_candidate["stage2_lineage"]["manifest_raw_sha256"] == raw_candidate[
        "stage2_lineage"
    ]["manifest_raw_sha256"]

    validate_diagnosis_kernel_candidate(
        path_candidate,
        session_id="offline-demo-session",
        source_session_content_sha256=SOURCE_SESSION_SHA256,
        stage2_manifest_path=STAGE2_MANIFEST,
        fixture_raw_bytes=fixture_raw,
        assertion_dependency_raw_bytes=dag_raw,
    )

    with pytest.raises(
        DiagnosisKernelAdapterError,
        match="exactly_one_path_or_raw_source_required",
    ):
        compile_diagnosis_kernel_candidate(
            session_id="offline-demo-session",
            source_session_content_sha256=SOURCE_SESSION_SHA256,
            stage2_manifest_path=STAGE2_MANIFEST,
            stage2_manifest_raw_bytes=stage2_raw,
            fixture_raw_bytes=fixture_raw,
            assertion_dependency_raw_bytes=dag_raw,
        )
