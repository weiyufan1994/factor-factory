from __future__ import annotations

import copy
from pathlib import Path

from factor_factory.evo_v2 import canonical_json_bytes, evo_v2_paths
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    epistemic_evolution_policy_v2,
    research_protocol_paths,
    validate_epistemic_evolution_policy,
    validate_epistemic_evolution_lifecycle,
    validate_protocol_bundle,
    write_json,
)
from scripts.run_factorforge_research_protocol_smoke import (
    REPORT_ID,
    valid_approaches,
    valid_conjecture,
    valid_state,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from tests.test_factorforge_evo_v2 import _build_bundle


def _write_protocol(
    root: Path,
    *,
    evo_enabled: bool,
    evo_state: str = "PREDICTIONS_FROZEN",
) -> None:
    paths = research_protocol_paths(root, REPORT_ID)
    conjecture = valid_conjecture()
    if evo_enabled:
        conjecture["epistemic_evolution"] = epistemic_evolution_policy_v2()
    write_json(paths["state"], valid_state())
    write_json(paths["conjecture"], conjecture)
    write_json(paths["approaches"], valid_approaches())
    if evo_enabled:
        evidence_path = root / "objects" / "evidence" / "evo_stage.json"
        write_json(
            evidence_path,
            {
                "verifier_id": "test_evo_lifecycle_verifier_v1",
                "verifier_status": "PASS",
                "dataset_snapshot_hash": "a" * 64,
                "window_hash": "b" * 64,
            },
        )
        evidence_ref = {
            "path": str(evidence_path.relative_to(root)),
            "sha256": sha256_file(evidence_path),
            "dataset_snapshot_hash": "a" * 64,
            "window_hash": "b" * 64,
            "verifier_id": "test_evo_lifecycle_verifier_v1",
            "verifier_status": "PASS",
        }
        transitions = {
            "PREDICTIONS_FROZEN": ["PREDICTIONS_FROZEN"],
            "QUALIFIED_CONTRADICTION": [
                "PREDICTIONS_FROZEN",
                "QUALIFIED_CONTRADICTION",
            ],
            "MINIMAL_MECHANISM_DELTA": [
                "PREDICTIONS_FROZEN",
                "QUALIFIED_CONTRADICTION",
                "MINIMAL_MECHANISM_DELTA",
            ],
        }[evo_state]
        events = []
        previous = None
        for index, state in enumerate(transitions):
            event = {
                "sequence": index + 1,
                "from_state": previous,
                "to_state": state,
                "evidence_refs": [copy.deepcopy(evidence_ref)],
                "actor": "Ultimate Host",
                "actor_receipt_ref": (
                    None if index == 0 else copy.deepcopy(evidence_ref)
                ),
            }
            event["event_sha256"] = stable_hash(event)
            events.append(event)
            previous = state
        lifecycle = {
            "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
            "report_id": REPORT_ID,
            "current_state": evo_state,
            "events": events,
            "host_authority": "ULTIMATE_HOST_APPEND_ONLY_CAS",
        }
        lifecycle["content_sha256"] = stable_hash(lifecycle)
        write_json(paths["evo_lifecycle"], lifecycle)


def test_evo_policy_is_closed_and_constitutional() -> None:
    policy = epistemic_evolution_policy_v2()
    assert validate_epistemic_evolution_policy(policy) == []

    mutated = copy.deepcopy(policy)
    mutated["skill_or_validator_mutation_allowed"] = True
    assert validate_epistemic_evolution_policy(mutated)

    extra = copy.deepcopy(policy)
    extra["reward"] = "sharpe"
    assert validate_epistemic_evolution_policy(extra)


def test_lifecycle_rejects_self_reported_state_or_tampered_transition(
    tmp_path: Path,
) -> None:
    _write_protocol(
        tmp_path,
        evo_enabled=True,
        evo_state="QUALIFIED_CONTRADICTION",
    )
    lifecycle_path = research_protocol_paths(tmp_path, REPORT_ID)["evo_lifecycle"]
    lifecycle = __import__("json").loads(lifecycle_path.read_text())
    assert (
        validate_epistemic_evolution_lifecycle(
            lifecycle,
            report_id=REPORT_ID,
            workspace_root=tmp_path,
        )
        == []
    )
    lifecycle["events"][-1]["actor"] = "current factor agent"
    assert validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=REPORT_ID,
        workspace_root=tmp_path,
    )


def test_formal_lifecycle_rejects_dummy_pass_receipt_and_accepts_host_signature(
    tmp_path: Path,
) -> None:
    _write_protocol(
        tmp_path,
        evo_enabled=True,
        evo_state="QUALIFIED_CONTRADICTION",
    )
    paths = research_protocol_paths(tmp_path, REPORT_ID)
    lifecycle = __import__("json").loads(paths["evo_lifecycle"].read_text())
    trust = ensure_runtime_trust_store(
        tmp_path / "host-private-trust",
        installation_id="protocol-test-installation-001",
    )
    organization_root = f"objects/research_organization/{REPORT_ID}"
    write_json(
        tmp_path / "identity/research_organization_plan.json",
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
        tmp_path / organization_root / "runtime/runtime_state.json", runtime_state
    )
    dummy_reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=REPORT_ID,
        workspace_root=tmp_path,
        require_signed_host_receipts=True,
    )
    assert any("actor_receipt:REFERENCE_INVALID" in reason for reason in dummy_reasons)

    initial_event = copy.deepcopy(lifecycle["events"][0])
    initial_lifecycle = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": REPORT_ID,
        "current_state": "PREDICTIONS_FROZEN",
        "events": [initial_event],
        "host_authority": "ULTIMATE_HOST_APPEND_ONLY_CAS",
    }
    initial_lifecycle["content_sha256"] = stable_hash(initial_lifecycle)
    evidence_refs = copy.deepcopy(lifecycle["events"][1]["evidence_refs"])
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": 2,
            "from_state": "PREDICTIONS_FROZEN",
            "to_state": "QUALIFIED_CONTRADICTION",
            "lifecycle_parent_sha256": stable_hash(initial_lifecycle),
            "evidence_refs_sha256": stable_hash(evidence_refs),
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
            "authority_scope": (
                "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
            ),
            "oos_accessed": False,
        },
    )
    receipt_path = paths["evo_lifecycle"].parent / "transition_receipt.json"
    write_json(receipt_path, receipt)
    second = {
        "sequence": 2,
        "from_state": "PREDICTIONS_FROZEN",
        "to_state": "QUALIFIED_CONTRADICTION",
        "evidence_refs": evidence_refs,
        "actor": "Ultimate Host",
        "actor_receipt_ref": {
            "path": receipt_path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
        },
    }
    second["event_sha256"] = stable_hash(second)
    signed = {
        **initial_lifecycle,
        "current_state": "QUALIFIED_CONTRADICTION",
        "events": [initial_event, second],
    }
    signed.pop("content_sha256", None)
    signed["content_sha256"] = stable_hash(signed)
    assert validate_epistemic_evolution_lifecycle(
        signed,
        report_id=REPORT_ID,
        workspace_root=tmp_path,
        require_signed_host_receipts=True,
    ) == []

    signed["events"][1]["to_state"] = "NO_QUALIFIED_CONTRADICTION"
    signed["events"][1]["event_sha256"] = stable_hash(signed["events"][1])
    signed.pop("content_sha256", None)
    signed["content_sha256"] = stable_hash(signed)
    mutation_reasons = validate_epistemic_evolution_lifecycle(
        signed,
        report_id=REPORT_ID,
        workspace_root=tmp_path,
        require_signed_host_receipts=True,
    )
    assert mutation_reasons


def test_pre_revision_cannot_remain_predictions_frozen(tmp_path: Path) -> None:
    _write_protocol(tmp_path, evo_enabled=True)
    paths = research_protocol_paths(tmp_path, REPORT_ID)
    # Pre-revision obligations are intentionally absent, but the EVO-specific
    # lifecycle closure must still be reported independently.
    report = validate_protocol_bundle(
        root=tmp_path,
        report_id=REPORT_ID,
        stage="pre_revision",
    )
    assert "BLOCK_FACTORFORGE_EPISTEMIC_EVOLUTION_DIAGNOSIS_NOT_CLOSED" in report[
        "block_reasons"
    ]


def test_legacy_protocol_remains_valid_without_evo_artifacts(tmp_path: Path) -> None:
    _write_protocol(tmp_path, evo_enabled=False)
    report = validate_protocol_bundle(
        root=tmp_path,
        report_id=REPORT_ID,
        stage="pre_council",
    )
    assert report["verdict"] == "PASS", report


def test_predictions_frozen_evo_protocol_does_not_invent_a_contradiction(
    tmp_path: Path,
) -> None:
    _write_protocol(tmp_path, evo_enabled=True)
    report = validate_protocol_bundle(
        root=tmp_path,
        report_id=REPORT_ID,
        stage="pre_council",
    )
    assert report["verdict"] == "PASS", report


def test_new_evo_protocol_fails_closed_without_feedback_ledger(tmp_path: Path) -> None:
    _write_protocol(
        tmp_path,
        evo_enabled=True,
        evo_state="QUALIFIED_CONTRADICTION",
    )
    report = validate_protocol_bundle(
        root=tmp_path,
        report_id=REPORT_ID,
        stage="pre_council",
    )
    assert report["verdict"] == "BLOCK"
    assert (
        "BLOCK_FACTORFORGE_EVO_V2_STAGE_ARTIFACT_MISSING:"
        "pre_council:feedback_ledger"
    ) in report["block_reasons"]


def test_evo_protocol_validates_artifacts_by_stage(tmp_path: Path) -> None:
    _write_protocol(
        tmp_path,
        evo_enabled=True,
        evo_state="QUALIFIED_CONTRADICTION",
    )
    bundle_root = tmp_path / "bundle_source"
    bundle = _build_bundle(bundle_root)
    # The protocol smoke uses a different report id from the core fixture.
    for artifact in bundle.values():
        artifact["artifact_identity"]["report_id"] = REPORT_ID

    target_paths = evo_v2_paths(tmp_path, REPORT_ID)
    target_paths["feedback_ledger"].parent.mkdir(parents=True, exist_ok=True)
    target_paths["feedback_ledger"].write_bytes(
        canonical_json_bytes(bundle["feedback_ledger"])
    )
    pre_council = validate_protocol_bundle(
        root=tmp_path,
        report_id=REPORT_ID,
        stage="pre_council",
    )
    # Content hashes and canonical refs were deliberately not rebuilt after
    # changing identity: the stage validator must inspect content, not merely
    # accept file presence.
    assert pre_council["verdict"] == "BLOCK"
    assert any(
        reason.startswith("BLOCK_FACTORFORGE_EVO_V2_INVALID:")
        for reason in pre_council["block_reasons"]
    )


def test_pre_revision_requires_delta_and_backprojection(tmp_path: Path) -> None:
    _write_protocol(
        tmp_path,
        evo_enabled=True,
        evo_state="MINIMAL_MECHANISM_DELTA",
    )
    report = validate_protocol_bundle(
        root=tmp_path,
        report_id=REPORT_ID,
        stage="pre_revision",
    )
    assert report["verdict"] == "BLOCK"
    assert any(
        reason.endswith(":pre_revision:mechanism_delta")
        for reason in report["block_reasons"]
    )
    assert any(
        reason.endswith(":pre_revision:economic_backprojection")
        for reason in report["block_reasons"]
    )
