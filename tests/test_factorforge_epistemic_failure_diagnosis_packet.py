from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from factor_factory.epistemic_failure_diagnosis_offline import (
    FailureDiagnosisOfflineError,
    PACKET_DOMAIN,
    validate_failure_diagnosis_offline_candidate_packet,
    write_failure_diagnosis_offline_candidate_packet,
)
from factor_factory.research_org.rfc8785_canonical import framed_sha256


STAGE2_MANIFEST = Path(
    "/Users/researcher/projects/"
    "factor-forge-phase-safe-retrieval-standalone-prototype-r3-20260829/packet_manifest.json"
)
FIXTURE_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-20260829/diagnosis-fixture.json"
)
ASSERTION_DAG_PATH = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-prototype-input-r3-20260829/"
    "assertion-dependency-dag.json"
)
REVISION_PREDECESSOR_MANIFEST = Path(
    "/Users/researcher/projects/"
    "factor-forge-failure-diagnosis-standalone-prototype-r2-20260829/"
    "packet_manifest.json"
)


def _kwargs() -> dict[str, Path]:
    return {
        "phase_safe_manifest_path": STAGE2_MANIFEST,
        "diagnosis_fixture_path": FIXTURE_PATH,
        "assertion_dependency_fixture_path": ASSERTION_DAG_PATH,
        "revision_predecessor_manifest_path": REVISION_PREDECESSOR_MANIFEST,
    }


def _build(root: Path) -> dict:
    return write_failure_diagnosis_offline_candidate_packet(root, **_kwargs())


def _validate(root: Path) -> dict:
    return validate_failure_diagnosis_offline_candidate_packet(
        root / "packet_manifest.json", **_kwargs()
    )


def _clone(source: Path, target: Path) -> None:
    shutil.copytree(source, target, copy_function=shutil.copy2)


def test_packet_exact12_closure_and_closed_replay(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    manifest = _build(root)

    assert len(list(root.iterdir())) == 12
    assert manifest["artifact_count"] == 11
    assert manifest["lineage_mode"] == "STANDALONE_OFFLINE_ALGORITHM_PROTOTYPE"
    assert manifest["factor_forge_successor"] is False
    assert manifest["direct_predecessor_manifest_raw_sha256"] is None
    assert manifest["normative_dependency_count"] == 0
    assert manifest["may_satisfy_any_factor_forge_gate"] is False
    assert manifest["packet_id"].endswith("_R3")
    assert manifest["revision_lineage"]["revision_predecessor_manifest_raw_sha256"] == (
        "335f05da19b53f202a98344d006157dcf1f59b69226745acb3a88ffd2de86362"
    )
    assert manifest["revision_lineage"]["revision_predecessor_is_factor_forge_predecessor"] is False
    assert manifest["compiler_profile"]["historical_compiler_is_recoverable_from_packet"] is True
    assert _validate(root) == manifest


def test_two_independent_builds_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _build(first)
    _build(second)

    assert {path.name for path in first.iterdir()} == {
        path.name for path in second.iterdir()
    }
    for first_path in first.iterdir():
        assert first_path.read_bytes() == (second / first_path.name).read_bytes()


def test_packet_authority_and_execution_flags_remain_closed(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    manifest = _build(root)
    terminal = json.loads((root / "08_planner_terminal_candidate.json").read_text())

    assert manifest["diagnostic_test_execution_allowed"] is False
    assert manifest["identified_cause_issuance_allowed"] is False
    assert manifest["host_qualification_or_submission_allowed"] is False
    assert manifest["formal_dirac_allowed"] is False
    assert manifest["branch_selection_or_execution_allowed"] is False
    assert manifest["host_or_canonical_memory_allowed"] is False
    assert manifest["oos_allowed"] is False
    assert manifest["skill_or_rag_runtime_allowed"] is False
    assert manifest["runtime_or_deployment_allowed"] is False
    assert manifest["authority_effect"] == "NONE"
    assert terminal["cause_identified"] is False
    assert terminal["review_eligible"] is False
    assert terminal["qualification_allowed"] is False


def test_detached_stage2_binding_is_not_predecessor_or_cross_phase_semantics(
    tmp_path: Path,
) -> None:
    root = tmp_path / "packet"
    _build(root)
    binding = json.loads((root / "00_stage2_input_binding.json").read_text())
    rivals = json.loads((root / "03_material_rival_registry.json").read_text())
    advisory = json.loads((root / "07_exploit_explore_dirac_advisory.json").read_text())

    assert binding["input_role"] == (
        "DETACHED_STAGE2_IMPLEMENTATION_PROVENANCE_ONLY__NOT_PREDECESSOR"
    )
    assert binding["prototype_dependency_not_normative_predecessor"] is True
    assert binding["cross_phase_semantic_consumption_allowed"] is False
    assert binding["semantic_payload_access_policy"] == {
        "selection_ledger_opened": False,
        "returned_rows_deserialized": False,
        "lane_score_object_or_semantic_candidate_read": False,
        "response_like_artifact_hashes_emitted": False,
        "stage2_artifact_paths_dereferenced": False,
        "changing_a0_returned_semantics_may_change_this_projection": False,
    }
    assert rivals["advisory_prior_rows"] == []
    assert rivals["stage2_a0_rows_consumed"] is False
    assert advisory["stage2_a0_cross_phase_consumption_allowed"] is False
    assert advisory["future_phase_safe_retrieval_handoff"]["required_phase_branch"] == (
        "B2_POSTRESULT_PLAN_SUPPORT"
    )


def test_extra_file_breaks_exact_closure(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    _build(root)
    (root / "unexpected.json").write_text("{}\n")

    with pytest.raises(FailureDiagnosisOfflineError, match="exact12_closure"):
        _validate(root)


def test_missing_artifact_breaks_exact_closure(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    _build(root)
    (root / "06_layer_assessment_plan.json").unlink()

    with pytest.raises(FailureDiagnosisOfflineError, match="exact12_closure"):
        _validate(root)


def test_symlink_and_hardlink_are_rejected(tmp_path: Path) -> None:
    base = tmp_path / "base"
    _build(base)

    symlink_root = tmp_path / "symlink"
    _clone(base, symlink_root)
    symlink_target = symlink_root / "06_layer_assessment_plan.json"
    symlink_target.unlink()
    os.symlink(base / "06_layer_assessment_plan.json", symlink_target)
    with pytest.raises(FailureDiagnosisOfflineError, match="packet_entry:unsafe"):
        _validate(symlink_root)

    hardlink_root = tmp_path / "hardlink"
    _clone(base, hardlink_root)
    hardlink_target = hardlink_root / "06_layer_assessment_plan.json"
    hardlink_target.unlink()
    os.link(base / "06_layer_assessment_plan.json", hardlink_target)
    with pytest.raises(FailureDiagnosisOfflineError, match="packet_entry:unsafe"):
        _validate(hardlink_root)


def test_artifact_tamper_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    _build(root)
    path = root / "08_planner_terminal_candidate.json"
    payload = json.loads(path.read_text())
    payload["qualification_allowed"] = True
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    with pytest.raises(FailureDiagnosisOfflineError):
        _validate(root)


def test_manifest_compiler_profile_tamper_cannot_be_self_reauthorized(
    tmp_path: Path,
) -> None:
    root = tmp_path / "packet"
    _build(root)
    path = root / "packet_manifest.json"
    payload = json.loads(path.read_text())
    payload["compiler_profile"]["sha256"] = "0" * 64
    core = {key: value for key, value in payload.items() if key != "content_sha256"}
    payload["content_sha256"] = framed_sha256(PACKET_DOMAIN, core)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    with pytest.raises(FailureDiagnosisOfflineError, match="closed_equality"):
        _validate(root)


def test_pinned_compiler_source_tamper_is_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "packet"
    _build(root)
    compiler = root / "10_pinned_compiler_source.py"
    compiler.write_bytes(compiler.read_bytes() + b"# tamper\n")

    with pytest.raises(FailureDiagnosisOfflineError):
        _validate(root)


def test_wrong_revision_predecessor_bytes_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    _build(root)
    wrong_revision = tmp_path / "wrong-revision.json"
    wrong_revision.write_bytes(REVISION_PREDECESSOR_MANIFEST.read_bytes() + b"\n")
    kwargs = _kwargs()
    kwargs["revision_predecessor_manifest_path"] = wrong_revision

    with pytest.raises((FailureDiagnosisOfflineError, ValueError)):
        validate_failure_diagnosis_offline_candidate_packet(
            root / "packet_manifest.json", **kwargs
        )


def test_existing_output_root_is_never_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "packet"
    _build(root)
    before = {path.name: path.read_bytes() for path in root.iterdir()}

    with pytest.raises(FailureDiagnosisOfflineError, match="output_root:exists"):
        _build(root)

    assert before == {path.name: path.read_bytes() for path in root.iterdir()}
