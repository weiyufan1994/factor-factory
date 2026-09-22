from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from factor_factory.evo_staging import (
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_FEEDBACK,
    STAGE_ADMIT_TRANSFER,
    STAGE_RECORD_USE,
    materialize_evo_v2_stage,
    no_derived_law_path,
    staging_manifest_path,
    validate_evo_v2_staging_manifest,
)
from factor_factory.evo_v2 import (
    BLOCK_EVO_V2_MATERIALIZATION_CONFLICT,
    EvoV2Error,
    canonical_json_bytes,
    evo_v2_paths,
)
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    epistemic_evolution_lifecycle_path,
    write_json,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from tests.test_factorforge_evo_v2 import REPORT_ID
from tests.test_revision_council_evo_v2 import (
    _no_derived_proof,
    _proposal_and_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _verifier_ref(root: Path) -> dict[str, object]:
    path = root / "support" / "lifecycle_verifier.json"
    write_json(
        path,
        {
            "verifier_id": "test_evo_staging_lifecycle_v1",
            "verifier_status": "PASS",
            "dataset_snapshot_hash": "a" * 64,
            "window_hash": "b" * 64,
        },
    )
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": "b" * 64,
        "verifier_id": "test_evo_staging_lifecycle_v1",
        "verifier_status": "PASS",
    }


def _write_lifecycle(root: Path, states: list[str]) -> tuple[str, str]:
    reference = _verifier_ref(root)
    trust = ensure_runtime_trust_store(
        root / "host-private-trust",
        installation_id="evo-staging-test-installation-001",
    )
    organization_root = f"objects/research_organization/{REPORT_ID}"
    write_json(
        root / "identity" / "research_organization_plan.json",
        {
            "identity": {"report_id": REPORT_ID},
            "workspace_policy": {"organization_root": organization_root},
        },
    )
    runtime_state = {
        "identity": {"report_id": REPORT_ID},
        "authority": {
            "signed_adapter_receipts_required": True,
            "trust_manifest": trust.public_manifest,
        },
    }
    runtime_state["state_sha256"] = stable_hash(runtime_state)
    write_json(
        root / organization_root / "runtime" / "runtime_state.json",
        runtime_state,
    )
    events = []
    previous = None
    parent_sha256 = ""
    for index, state in enumerate(states):
        actor_receipt_ref = None
        if index > 0:
            parent_payload = {
                "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
                "report_id": REPORT_ID,
                "current_state": previous,
                "events": copy.deepcopy(events),
                "host_authority": "ULTIMATE_HOST_APPEND_ONLY_CAS",
            }
            parent_payload["content_sha256"] = stable_hash(parent_payload)
            transition_parent_sha256 = stable_hash(parent_payload)
            receipt = trust.sign(
                "host_admission",
                {
                    "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
                    "report_id": REPORT_ID,
                    "sequence": index + 1,
                    "from_state": previous,
                    "to_state": state,
                    "lifecycle_parent_sha256": transition_parent_sha256,
                    "evidence_refs_sha256": stable_hash([reference]),
                    "trust_manifest_sha256": trust.public_manifest[
                        "manifest_sha256"
                    ],
                    "authority_scope": (
                        "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
                    ),
                    "oos_accessed": False,
                },
            )
            receipt_path = (
                epistemic_evolution_lifecycle_path(root, REPORT_ID).parent
                / f"lifecycle_transition_receipt__{index + 1:04d}.json"
            )
            write_json(receipt_path, receipt)
            actor_receipt_ref = {
                "path": receipt_path.relative_to(root).as_posix(),
                "sha256": sha256_file(receipt_path),
                "receipt_id": receipt["receipt_id"],
                "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
            }
            if index == len(states) - 1:
                parent_sha256 = transition_parent_sha256
        event = {
            "sequence": index + 1,
            "from_state": previous,
            "to_state": state,
            "evidence_refs": [copy.deepcopy(reference)],
            "actor": "Ultimate Host",
            "actor_receipt_ref": actor_receipt_ref,
        }
        event["event_sha256"] = stable_hash(event)
        events.append(event)
        previous = state
    payload = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": REPORT_ID,
        "current_state": states[-1],
        "events": events,
        "host_authority": "ULTIMATE_HOST_APPEND_ONLY_CAS",
    }
    payload["content_sha256"] = stable_hash(payload)
    write_json(epistemic_evolution_lifecycle_path(root, REPORT_ID), payload)
    assert parent_sha256
    return parent_sha256, payload["content_sha256"]


def _stage(
    root: Path,
    *,
    stage: str,
    lifecycle_hashes: tuple[str, str],
    staging_cas: str,
    **inputs: object,
) -> dict:
    parent, current = lifecycle_hashes
    return materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=stage,
        expected_lifecycle_parent_sha256=parent,
        expected_lifecycle_content_sha256=current,
        expected_staging_content_sha256=staging_cas,
        **inputs,
    )


def test_staged_host_cas_materializes_only_artifacts_due_at_each_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    proposal, _payload, artifacts = _proposal_and_payload(root)
    paths = evo_v2_paths(root, REPORT_ID)

    qualified = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    feedback = _stage(
        root,
        stage=STAGE_ADMIT_FEEDBACK,
        lifecycle_hashes=qualified,
        staging_cas="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    assert paths["feedback_ledger"].is_file()
    assert not paths["mechanism_delta"].exists()
    assert not paths["economic_backprojection"].exists()
    assert not paths["experience_transfer_bundle"].exists()
    assert not paths["transfer_use_receipt"].exists()

    # A retry carrying the original pre-append CAS is allowed only as an
    # exact, non-mutating replay.
    retry = _stage(
        root,
        stage=STAGE_ADMIT_FEEDBACK,
        lifecycle_hashes=qualified,
        staging_cas="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    assert retry["idempotent_replay"] is True

    minimal = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
        ],
    )
    council = _stage(
        root,
        stage=STAGE_ADMIT_COUNCIL_OUTCOME,
        lifecycle_hashes=minimal,
        staging_cas=feedback["staging_manifest"]["content_sha256"],
        council_proposal=proposal,
    )
    assert set(council["written"]) == {
        "mechanism_delta",
        "economic_backprojection",
    }
    assert paths["mechanism_delta"].is_file()
    assert paths["economic_backprojection"].is_file()
    assert not paths["experience_transfer_bundle"].exists()

    transferred = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
            "TRANSFER_RECORDED",
        ],
    )
    transfer = _stage(
        root,
        stage=STAGE_ADMIT_TRANSFER,
        lifecycle_hashes=transferred,
        staging_cas=council["staging_manifest"]["content_sha256"],
        experience_transfer_bundle=artifacts["experience_transfer_bundle"],
    )
    assert paths["experience_transfer_bundle"].is_file()
    assert not paths["transfer_use_receipt"].exists()

    use = _stage(
        root,
        stage=STAGE_RECORD_USE,
        lifecycle_hashes=transferred,
        staging_cas=transfer["staging_manifest"]["content_sha256"],
        transfer_use_receipt=artifacts["transfer_use_receipt"],
    )
    assert paths["transfer_use_receipt"].is_file()
    manifest = json.loads(staging_manifest_path(root, REPORT_ID).read_text())
    assert validate_evo_v2_staging_manifest(
        manifest,
        root=root,
        report_id=REPORT_ID,
    ) == []
    assert [event["stage"] for event in manifest["events"]] == [
        STAGE_ADMIT_FEEDBACK,
        STAGE_ADMIT_COUNCIL_OUTCOME,
        STAGE_ADMIT_TRANSFER,
        STAGE_RECORD_USE,
    ]
    assert use["staging_manifest"]["content_sha256"] == manifest["content_sha256"]


def test_staged_writer_rejects_stale_manifest_and_lifecycle_parent_cas(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    proposal, _payload, artifacts = _proposal_and_payload(root)
    qualified = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    feedback = _stage(
        root,
        stage=STAGE_ADMIT_FEEDBACK,
        lifecycle_hashes=qualified,
        staging_cas="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    minimal = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "MINIMAL_MECHANISM_DELTA",
        ],
    )
    with pytest.raises(EvoV2Error) as stale_manifest:
        _stage(
            root,
            stage=STAGE_ADMIT_COUNCIL_OUTCOME,
            lifecycle_hashes=minimal,
            staging_cas="f" * 64,
            council_proposal=proposal,
        )
    assert stale_manifest.value.token == BLOCK_EVO_V2_MATERIALIZATION_CONFLICT
    assert not evo_v2_paths(root, REPORT_ID)["mechanism_delta"].exists()

    with pytest.raises(EvoV2Error) as stale_lifecycle:
        _stage(
            root,
            stage=STAGE_ADMIT_COUNCIL_OUTCOME,
            lifecycle_hashes=("e" * 64, minimal[1]),
            staging_cas=feedback["staging_manifest"]["content_sha256"],
            council_proposal=proposal,
        )
    assert stale_lifecycle.value.token == BLOCK_EVO_V2_MATERIALIZATION_CONFLICT
    assert not evo_v2_paths(root, REPORT_ID)["mechanism_delta"].exists()


def test_no_derived_law_uses_council_closed_proof_and_ends_branch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    proposal, payload, artifacts = _proposal_and_payload(root)
    qualified = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    feedback = _stage(
        root,
        stage=STAGE_ADMIT_FEEDBACK,
        lifecycle_hashes=qualified,
        staging_cas="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    contradiction_id = artifacts["feedback_ledger"]["contradiction"][
        "contradiction_id"
    ]
    proposal["candidate_revision_laws"] = []
    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": _no_derived_proof(contradiction_id),
    }
    payload["proposal_law_binding"] = None
    no_derived = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "NO_DERIVED_LAW",
        ],
    )
    result = _stage(
        root,
        stage=STAGE_ADMIT_COUNCIL_OUTCOME,
        lifecycle_hashes=no_derived,
        staging_cas=feedback["staging_manifest"]["content_sha256"],
        council_proposal=proposal,
    )
    assert result["outcome"] == "NO_DERIVED_LAW"
    assert no_derived_law_path(root, REPORT_ID).is_file()
    paths = evo_v2_paths(root, REPORT_ID)
    assert not paths["mechanism_delta"].exists()
    assert not paths["economic_backprojection"].exists()

    with pytest.raises(EvoV2Error) as terminal:
        _stage(
            root,
            stage=STAGE_ADMIT_TRANSFER,
            lifecycle_hashes=no_derived,
            staging_cas=result["staging_manifest"]["content_sha256"],
            experience_transfer_bundle=artifacts["experience_transfer_bundle"],
        )
    assert terminal.value.token == BLOCK_EVO_V2_MATERIALIZATION_CONFLICT


def test_no_derived_hidden_law_is_rejected_before_materialization(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    proposal, payload, artifacts = _proposal_and_payload(root)
    qualified = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    feedback = _stage(
        root,
        stage=STAGE_ADMIT_FEEDBACK,
        lifecycle_hashes=qualified,
        staging_cas="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    contradiction_id = artifacts["feedback_ledger"]["contradiction"][
        "contradiction_id"
    ]
    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": _no_derived_proof(contradiction_id),
    }
    payload["proposal_law_binding"] = None
    no_derived = _write_lifecycle(
        root,
        [
            "PREDICTIONS_FROZEN",
            "QUALIFIED_CONTRADICTION",
            "NO_DERIVED_LAW",
        ],
    )
    with pytest.raises(EvoV2Error) as hidden_law:
        _stage(
            root,
            stage=STAGE_ADMIT_COUNCIL_OUTCOME,
            lifecycle_hashes=no_derived,
            staging_cas=feedback["staging_manifest"]["content_sha256"],
            council_proposal=proposal,
        )
    assert any(
        "candidate_laws_must_be_empty" in reason
        for reason in hidden_law.value.reasons
    )
    assert not no_derived_law_path(root, REPORT_ID).exists()


def test_stage_cli_reports_next_manifest_cas_without_requiring_future_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _proposal, _payload, artifacts = _proposal_and_payload(root)
    lifecycle = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    source = root / "inputs" / "feedback.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(canonical_json_bytes(artifacts["feedback_ledger"]))
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "write_factorforge_evo_v2.py"),
        "--workspace-root",
        str(root),
        "--report-id",
        REPORT_ID,
        "--stage",
        STAGE_ADMIT_FEEDBACK,
        "--feedback-ledger",
        str(source),
        "--expected-lifecycle-parent-sha256",
        lifecycle[0],
        "--expected-lifecycle-content-sha256",
        lifecycle[1],
        "--expected-staging-content-sha256",
        "ABSENT",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["verdict"] == "PASS"
    assert report["stage"] == STAGE_ADMIT_FEEDBACK
    assert len(report["staging_manifest"]["content_sha256"]) == 64
    assert not evo_v2_paths(root, REPORT_ID)["mechanism_delta"].exists()


def test_rehashed_manifest_cannot_redirect_a_canonical_output_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    _proposal, _payload, artifacts = _proposal_and_payload(root)
    qualified = _write_lifecycle(
        root, ["PREDICTIONS_FROZEN", "QUALIFIED_CONTRADICTION"]
    )
    _stage(
        root,
        stage=STAGE_ADMIT_FEEDBACK,
        lifecycle_hashes=qualified,
        staging_cas="ABSENT",
        feedback_ledger=artifacts["feedback_ledger"],
    )
    manifest = json.loads(staging_manifest_path(root, REPORT_ID).read_text())
    redirected = root / "support" / "redirected_feedback.json"
    redirected.write_bytes(canonical_json_bytes(artifacts["feedback_ledger"]))
    output_ref = manifest["events"][0]["output_artifact_refs"][0]
    output_ref["path"] = redirected.relative_to(root).as_posix()
    event = manifest["events"][0]
    event.pop("event_sha256")
    event["event_sha256"] = stable_hash(event)
    manifest.pop("content_sha256")
    manifest["content_sha256"] = stable_hash(manifest)
    reasons = validate_evo_v2_staging_manifest(
        manifest,
        root=root,
        report_id=REPORT_ID,
    )
    assert any("canonical_path_invalid" in reason for reason in reasons)
