from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from factor_factory.epistemic_dual_steward_review_handoff import (
    AUTHORITY_EFFECT,
    CANDIDATE_PACKET_MANIFEST_RAW_SHA256,
    PACKET_ARTIFACT_MANIFEST_DOMAIN,
    DualStewardReviewHandoffError,
    _validate_packet_against_compiled,
    compile_local_git_readback,
    validate_compiled_handoff,
    write_dual_steward_review_handoff_packet,
)
from factor_factory.research_org.contracts import strict_json_loads

PROJECTS_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-candidate-definition-generation-"
    "s1-r1-20260828/packet_manifest.json"
)
R14_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r14-20260828/packet_manifest.json"
)
R14_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-expectation-proposal-"
    "e1-r14-review-20260828/packet_manifest.json"
)
H1_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-s1-closure-readiness-"
    "h1-20260828/packet_manifest.json"
)
H1_REVIEW_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-host-bootstrap-s1-closure-readiness-"
    "h1-review-20260828/packet_manifest.json"
)
R2_HANDOFF_MANIFEST = PROJECTS_ROOT / (
    "factor-forge-epistemic-dual-steward-review-handoff-"
    "s1-r2-20260829/packet_manifest.json"
)
ONTOLOGY_REPO = PROJECTS_ROOT / "factor-forge-ontology-definitions"
REFERENCE_REPO = PROJECTS_ROOT / "factor-forge-reference-definitions"


def _load(path: Path) -> dict:
    payload = strict_json_loads(path.read_bytes(), label=str(path))
    assert isinstance(payload, dict)
    return payload


@pytest.fixture(scope="module")
def handoff_packet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("dual-steward-handoff") / "packet"
    write_dual_steward_review_handoff_packet(
        output,
        candidate_manifest_path=CANDIDATE_MANIFEST,
        r14_manifest_path=R14_MANIFEST,
        r14_review_manifest_path=R14_REVIEW_MANIFEST,
        h1_manifest_path=H1_MANIFEST,
        h1_review_manifest_path=H1_REVIEW_MANIFEST,
        revision_predecessor_manifest_path=R2_HANDOFF_MANIFEST,
        ontology_repo=ONTOLOGY_REPO,
        reference_repo=REFERENCE_REPO,
    )
    return output


def _compiled_from_packet(
    root: Path,
) -> tuple[dict, dict, list[dict], dict, dict, list[dict]]:
    manifest = _load(root / "packet_manifest.json")
    contract = _load(root / "00_unsigned_review_handoff_contract.json")
    schema = _load(root / "01_closed_exact2_unsigned_request.schema.json")
    requests = [
        _load(root / "02_ontology_steward_review_request.json"),
        _load(root / "03_reference_steward_review_request.json"),
    ]
    readback = _load(root / "04_local_git_delivery_readback.json")
    report = _load(root / "05_review_handoff_validation_report.json")
    return (
        contract,
        schema,
        requests,
        readback,
        report,
        manifest["ordered_dependencies"],
    )


def test_exact2_unsigned_requests_bind_same_target_without_authority(
    handoff_packet: Path,
) -> None:
    contract, schema, requests, readback, _, _ = _compiled_from_packet(handoff_packet)
    validate_compiled_handoff(
        contract=contract, schema=schema, requests=requests, readback=readback
    )
    assert [request["steward_role"] for request in requests] == [
        "ontology_steward",
        "reference_steward",
    ]
    assert requests[0]["review_target"] == requests[1]["review_target"]
    assert requests[0]["review_scope"] == requests[1]["review_scope"]
    assert requests[0]["review_scope"] == {
        "definition_row_count": 160,
        "candidate_fail_count": 99,
        "candidate_blocked_count": 61,
        "branch_selection_review_target_count": 10,
        "row_or_target_restatement_present": False,
    }
    validator = Draft202012Validator(schema)
    for request in requests:
        validator.validate(request)
        assert set(request["current_unbound_state"].values()) == {None}
        assert request["authority_effect"] == AUTHORITY_EFFECT
        assert request["signed"] is False
        assert request["is_steward_decision"] is False
        assert request["permissions_opened_count"] == 0


def test_local_git_readback_proves_only_local_exact7_delivery(
    handoff_packet: Path,
) -> None:
    _, _, _, readback, _, _ = _compiled_from_packet(handoff_packet)
    assert readback["receipt_kind"] == "NONAUTHORITATIVE_LOCAL_GIT_DELIVERY_READBACK"
    assert readback["repository_observation_count"] == 2
    assert readback["may_satisfy_remote_repository_binding"] is False
    assert readback["may_satisfy_steward_decision_gate"] is False
    observations = readback["ordered_repository_observations"]
    assert observations[0]["head_commit_sha"] != observations[1]["head_commit_sha"]
    assert observations[0]["head_tree_sha"] != observations[1]["head_tree_sha"]
    assert (
        observations[0]["direct_parent_commit_sha"]
        != observations[1]["direct_parent_commit_sha"]
    )
    assert all(row["clean"] and row["remote_count"] == 0 for row in observations)
    assert all(row["candidate_blob_count"] == 7 for row in observations)
    left = [
        (row["path"], row["git_blob_oid"], row["raw_sha256"])
        for row in observations[0]["ordered_candidate_blobs"]
    ]
    right = [
        (row["path"], row["git_blob_oid"], row["raw_sha256"])
        for row in observations[1]["ordered_candidate_blobs"]
    ]
    assert left == right
    assert readback["separation_matrix"]["exact7_blob_oid_and_raw_bytes_equal"] is True
    assert (
        readback["separation_matrix"]["formal_dual_git_independence_receipt_present"]
        is False
    )
    serialized = (handoff_packet / "04_local_git_delivery_readback.json").read_text()
    assert "/Users/" not in serialized


def test_packet_exact7_closure_commitments_and_closed_replay(
    handoff_packet: Path,
) -> None:
    manifest = _load(handoff_packet / "packet_manifest.json")
    assert manifest["artifact_count"] == 6
    assert manifest["dependency_count"] == 6
    assert manifest["request_count"] == 2
    assert manifest["permissions_opened_count"] == 0
    assert manifest["direct_predecessor_candidate_packet_manifest_raw_sha256"] == (
        CANDIDATE_PACKET_MANIFEST_RAW_SHA256
    )
    assert {path.name for path in handoff_packet.iterdir()} == {
        "packet_manifest.json",
        "00_unsigned_review_handoff_contract.json",
        "01_closed_exact2_unsigned_request.schema.json",
        "02_ontology_steward_review_request.json",
        "03_reference_steward_review_request.json",
        "04_local_git_delivery_readback.json",
        "05_review_handoff_validation_report.json",
    }
    rows = manifest["ordered_artifacts"]
    assert [row["ordinal"] for row in rows] == list(range(6))
    for row in rows:
        raw = (handoff_packet / row["path"]).read_bytes()
        assert len(raw) == row["bytes"]
        assert hashlib.sha256(raw).hexdigest() == row["sha256"]
    expected_commitment = hashlib.sha256(
        PACKET_ARTIFACT_MANIFEST_DOMAIN.encode()
        + b"\x00"
        + b"".join(bytes.fromhex(row["sha256"]) for row in rows)
    ).hexdigest()
    assert manifest["artifact_manifest_commitment_sha256"] == expected_commitment
    compiled = _compiled_from_packet(handoff_packet)
    assert (
        _validate_packet_against_compiled(
            handoff_packet / "packet_manifest.json",
            contract=compiled[0],
            schema=compiled[1],
            requests=compiled[2],
            readback=compiled[3],
            report=compiled[4],
            dependencies=compiled[5],
        )
        == manifest
    )


@pytest.mark.parametrize(
    ("mutation",),
    [
        (lambda item: item.__setitem__("signed", True),),
        (lambda item: item.__setitem__("submitted", True),),
        (lambda item: item.__setitem__("reviewed", True),),
        (lambda item: item.__setitem__("approved", True),),
        (lambda item: item.__setitem__("is_steward_decision", True),),
        (lambda item: item.__setitem__("permissions_opened_count", 1),),
        (
            lambda item: item["current_unbound_state"].__setitem__(
                "decision", "APPROVE_EXACT160_SELECTED_BRANCHES"
            ),
        ),
        (
            lambda item: item["current_unbound_state"].__setitem__(
                "signature", "not-null"
            ),
        ),
        (
            lambda item: item["current_unbound_state"].__setitem__(
                "submission_endpoint_ref", "ambient"
            ),
        ),
        (lambda item: item["review_scope"].__setitem__("definition_row_count", 159),),
        (
            lambda item: item["review_scope"].__setitem__(
                "branch_selection_review_target_count", 9
            ),
        ),
        (
            lambda item: item["review_target"].__setitem__(
                "candidate_definition_generation_content_sha256", "0" * 64
            ),
        ),
        (lambda item: item.__setitem__("unexpected_authority", True),),
    ],
)
def test_request_authority_and_target_tamper_fail_closed(
    handoff_packet: Path, mutation
) -> None:
    _, schema, requests, _, _, _ = _compiled_from_packet(handoff_packet)
    tampered = copy.deepcopy(requests[0])
    mutation(tampered)
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(tampered)


def test_same_repository_cannot_satisfy_local_dual_delivery(
    handoff_packet: Path,
) -> None:
    contract, _, requests, _, _, _ = _compiled_from_packet(handoff_packet)
    with pytest.raises(DualStewardReviewHandoffError):
        compile_local_git_readback(
            ontology_repo=ONTOLOGY_REPO,
            reference_repo=ONTOLOGY_REPO,
            source_rows=contract["ordered_candidate_source_files"],
            review_target=requests[0]["review_target"],
        )


def test_dirty_repository_is_blocked(handoff_packet: Path, tmp_path: Path) -> None:
    contract, _, requests, _, _, _ = _compiled_from_packet(handoff_packet)
    dirty = tmp_path / "dirty-ontology"
    shutil.copytree(ONTOLOGY_REPO, dirty, symlinks=False)
    candidate = dirty / (
        "candidates/FF_EPISTEMIC_CANDIDATE_DEFINITION_GENERATION_S1_20260828_R1/"
        "02_candidate_definition.json"
    )
    candidate.write_bytes(candidate.read_bytes() + b"\n")
    with pytest.raises(DualStewardReviewHandoffError):
        compile_local_git_readback(
            ontology_repo=dirty,
            reference_repo=REFERENCE_REPO,
            source_rows=contract["ordered_candidate_source_files"],
            review_target=requests[0]["review_target"],
        )


@pytest.mark.parametrize(
    "poison_kind",
    [
        "shallow",
        "legacy_graft",
        "replace_parent",
        "replace_head",
        "packed_replace",
    ],
)
def test_non_raw_git_object_views_are_blocked(
    handoff_packet: Path, tmp_path: Path, poison_kind: str
) -> None:
    contract, _, requests, readback, _, _ = _compiled_from_packet(handoff_packet)
    poisoned = tmp_path / f"poisoned-{poison_kind}"
    shutil.copytree(ONTOLOGY_REPO, poisoned, symlinks=False)
    observation = readback["ordered_repository_observations"][0]
    head = observation["head_commit_sha"]
    parent = observation["direct_parent_commit_sha"]
    git_dir = poisoned / ".git"
    if poison_kind == "shallow":
        (git_dir / "shallow").write_text(parent + "\n", encoding="utf-8")
    elif poison_kind == "legacy_graft":
        (git_dir / "info" / "grafts").write_text(f"{head} {parent}\n", encoding="utf-8")
    elif poison_kind in {"replace_parent", "replace_head"}:
        replaced = parent if poison_kind == "replace_parent" else head
        replace_dir = git_dir / "refs" / "replace"
        replace_dir.mkdir(parents=True, exist_ok=True)
        (replace_dir / replaced).write_text(head + "\n", encoding="utf-8")
    else:
        (git_dir / "packed-refs").write_text(
            f"# pack-refs with: peeled fully-peeled\n{head} refs/replace/{parent}\n",
            encoding="utf-8",
        )
    with pytest.raises(DualStewardReviewHandoffError):
        compile_local_git_readback(
            ontology_repo=poisoned,
            reference_repo=REFERENCE_REPO,
            source_rows=contract["ordered_candidate_source_files"],
            review_target=requests[0]["review_target"],
        )


def test_packet_tamper_and_extra_file_fail_closed(
    handoff_packet: Path, tmp_path: Path
) -> None:
    copied = tmp_path / "tampered"
    shutil.copytree(handoff_packet, copied)
    target = copied / "05_review_handoff_validation_report.json"
    target.write_bytes(target.read_bytes() + b"\n")
    compiled = _compiled_from_packet(handoff_packet)
    with pytest.raises(DualStewardReviewHandoffError):
        _validate_packet_against_compiled(
            copied / "packet_manifest.json",
            contract=compiled[0],
            schema=compiled[1],
            requests=compiled[2],
            readback=compiled[3],
            report=compiled[4],
            dependencies=compiled[5],
        )
    copied = tmp_path / "extra"
    shutil.copytree(handoff_packet, copied)
    (copied / "unexpected.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(DualStewardReviewHandoffError):
        _validate_packet_against_compiled(
            copied / "packet_manifest.json",
            contract=compiled[0],
            schema=compiled[1],
            requests=compiled[2],
            readback=compiled[3],
            report=compiled[4],
            dependencies=compiled[5],
        )
