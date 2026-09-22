from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

from factor_factory.evo_v2 import canonical_json_bytes, evo_v2_paths, with_content_hash
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    epistemic_evolution_policy_v2,
    epistemic_evolution_lifecycle_snapshot_path,
    research_protocol_paths,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.revision_council.production import (
    BLOCK_EVIDENCE_VIEW,
    BLOCK_OOS,
    build_evo_task_identity,
    formal_packet_redactions,
    load_formal_evo_packet_context,
    result_evo_outcome_summary,
    validate_formal_evo_packet,
    validate_result_evo_identity,
)
from scripts.run_factorforge_research_protocol_smoke import valid_conjecture
from tests.test_factorforge_evo_v2 import REPORT_ID, _build_bundle
from tests.test_factorforge_measurement_program_pipeline import _program
from tests.test_revision_council_evo_v2 import _proposal_and_payload


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = (
        REPO_ROOT
        / "skills"
        / "factor-forge-step6"
        / "scripts"
        / f"{name}.py"
    )
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    scripts = str(path.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec.loader.exec_module(module)
    return module


AGENTIC_VALIDATOR = _load_script("validate_agentic_council_result")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _formal_workspace(root: Path) -> tuple[dict, dict]:
    root.mkdir(parents=True, exist_ok=True)
    support_root = root / "bundle_support"
    bundle = _build_bundle(support_root)
    paths = evo_v2_paths(root, REPORT_ID)
    feedback = copy.deepcopy(bundle["feedback_ledger"])
    frozen_program_path = support_root / "support" / "frozen_measurement_program.json"
    _write_json(frozen_program_path, _program())
    feedback["frozen_authority"]["measurement_program_ref"] = {
        "path": frozen_program_path.relative_to(support_root).as_posix(),
        "sha256": sha256_file(frozen_program_path),
    }
    feedback = with_content_hash(feedback)
    support = support_root / "support"
    for ref in [
        *(item["preregistration_ref"] for item in feedback["hypothesis_predictions"]),
        *(item for row in feedback["state_history"] for item in row["evidence_refs"]),
        *feedback["contradiction"]["evidence_refs"],
        *feedback["contradiction"]["observed_signature"]["evidence_refs"],
        *(item for row in feedback["lower_layer_clearance"] for item in row["evidence_refs"]),
        feedback["artifact_authority"]["host_admission_ref"],
        *(
            feedback["frozen_authority"][field]
            for field in (
                "economic_hypothesis_ref",
                "measurement_program_ref",
                "threshold_registry_ref",
                "oos_policy_ref",
                "trial_budget_ref",
            )
        ),
    ]:
        source = support_root / ref["path"]
        target = root / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    paths["feedback_ledger"].parent.mkdir(parents=True, exist_ok=True)
    paths["feedback_ledger"].write_bytes(canonical_json_bytes(feedback))

    protocol = research_protocol_paths(root, REPORT_ID)
    conjecture = valid_conjecture()
    conjecture["report_id"] = REPORT_ID
    conjecture["epistemic_evolution"] = epistemic_evolution_policy_v2()
    _write_json(protocol["conjecture"], conjecture)

    trust = ensure_runtime_trust_store(
        root / "host-private-trust",
        installation_id="council-test-installation-001",
    )
    organization_root = f"objects/research_organization/{REPORT_ID}"
    _write_json(
        root / "identity/research_organization_plan.json",
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
    _write_json(root / organization_root / "runtime/runtime_state.json", runtime_state)

    lifecycle_evidence = root / "objects" / "evidence" / "qualified_is.json"
    lifecycle_payload = {
        "verifier_id": "qualified_is_verifier_v1",
        "verifier_status": "PASS",
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": "b" * 64,
    }
    _write_json(lifecycle_evidence, lifecycle_payload)
    evidence_ref = {
        "path": lifecycle_evidence.relative_to(root).as_posix(),
        "sha256": sha256_file(lifecycle_evidence),
        **lifecycle_payload,
    }
    initial_event = {
        "sequence": 1,
        "from_state": None,
        "to_state": "PREDICTIONS_FROZEN",
        "evidence_refs": [copy.deepcopy(evidence_ref)],
        "actor": "Ultimate Host",
        "actor_receipt_ref": None,
    }
    initial_event["event_sha256"] = stable_hash(initial_event)
    initial_lifecycle = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": REPORT_ID,
        "current_state": "PREDICTIONS_FROZEN",
        "events": [initial_event],
        "host_authority": "ULTIMATE_HOST_APPEND_ONLY_CAS",
    }
    initial_lifecycle["content_sha256"] = stable_hash(initial_lifecycle)
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": 2,
            "from_state": "PREDICTIONS_FROZEN",
            "to_state": "QUALIFIED_CONTRADICTION",
            "lifecycle_parent_sha256": stable_hash(initial_lifecycle),
            "evidence_refs_sha256": stable_hash([evidence_ref]),
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
            "authority_scope": (
                "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
            ),
            "oos_accessed": False,
        },
    )
    receipt_path = protocol["evo_lifecycle"].parent / "lifecycle_transition_receipt__0002.json"
    _write_json(receipt_path, receipt)
    qualified_event = {
        "sequence": 2,
        "from_state": "PREDICTIONS_FROZEN",
        "to_state": "QUALIFIED_CONTRADICTION",
        "evidence_refs": [copy.deepcopy(evidence_ref)],
        "actor": "Ultimate Host",
        "actor_receipt_ref": {
            "path": receipt_path.relative_to(root).as_posix(),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
        },
    }
    qualified_event["event_sha256"] = stable_hash(qualified_event)
    lifecycle = {
        **initial_lifecycle,
        "current_state": "QUALIFIED_CONTRADICTION",
        "events": [initial_event, qualified_event],
    }
    lifecycle.pop("content_sha256", None)
    lifecycle["content_sha256"] = stable_hash(lifecycle)
    _write_json(protocol["evo_lifecycle"], lifecycle)
    _write_json(
        epistemic_evolution_lifecycle_snapshot_path(root, REPORT_ID, 2),
        lifecycle,
    )
    return bundle, feedback


def _formal_packet(root: Path, context: dict, feedback: dict) -> dict:
    frozen_program_path = root / context["frozen_measurement_program_ref"]["path"]
    packet = {
        "report_id": REPORT_ID,
        "evo_v2": context,
        "mechanism_conditioned_measurement_program": json.loads(
            frozen_program_path.read_text(encoding="utf-8")
        ),
        **formal_packet_redactions(feedback),
        "source_paths": {
            "research_conjecture": str(
                research_protocol_paths(root, REPORT_ID)["conjecture"].resolve(
                    strict=True
                )
            ),
            "evo_lifecycle": str(
                (root / context["lifecycle_ref"]["path"]).resolve(strict=True)
            ),
            "evo_feedback_ledger": str(
                (root / context["canonical_feedback_ref"]["path"]).resolve(
                    strict=True
                )
            ),
            "frozen_measurement_program": str(
                frozen_program_path.resolve(strict=True)
            ),
        },
    }
    return packet


def test_formal_packet_requires_qualified_lifecycle_canonical_feedback_and_sealed_oos(
    tmp_path: Path,
) -> None:
    _bundle, feedback = _formal_workspace(tmp_path)
    context, loaded = load_formal_evo_packet_context(tmp_path, REPORT_ID)
    assert context is not None and loaded == feedback
    packet = _formal_packet(tmp_path, context, feedback)
    assert validate_formal_evo_packet(
        packet, workspace_root=tmp_path, report_id=REPORT_ID
    ) == []

    release = (
        tmp_path
        / "objects"
        / "research_protocol"
        / f"oos_release_manifest__{REPORT_ID}.json"
    )
    _write_json(release, {"release_status": "RELEASED"})
    reasons = validate_formal_evo_packet(
        packet, workspace_root=tmp_path, report_id=REPORT_ID
    )
    assert any(reason.startswith(BLOCK_OOS) for reason in reasons)


def test_formal_packet_rejects_oos_leak_and_flattened_evaluation_metrics(
    tmp_path: Path,
) -> None:
    _bundle, feedback = _formal_workspace(tmp_path)
    context, _loaded = load_formal_evo_packet_context(tmp_path, REPORT_ID)
    assert context is not None
    packet = _formal_packet(tmp_path, context, feedback)
    packet["metrics"]["oos_rank_ic"] = 0.1
    packet["source_paths"]["factor_evaluation"] = "/tmp/factor_evaluation.json"
    reasons = validate_formal_evo_packet(
        packet, workspace_root=tmp_path, report_id=REPORT_ID
    )
    assert f"{BLOCK_EVIDENCE_VIEW}:metrics" in reasons
    assert f"{BLOCK_EVIDENCE_VIEW}:source_paths" in reasons

    stripped = copy.deepcopy(packet)
    stripped.pop("evo_v2")
    reasons = validate_formal_evo_packet(
        stripped, workspace_root=tmp_path, report_id=REPORT_ID
    )
    assert "BLOCK_COUNCIL_EVO_V2_FORMAL_PACKET_INVALID:context_mismatch" in reasons


def test_formal_packet_rejects_mutable_measurement_program_shadow(
    tmp_path: Path,
) -> None:
    _bundle, feedback = _formal_workspace(tmp_path)
    context, _loaded = load_formal_evo_packet_context(tmp_path, REPORT_ID)
    assert context is not None
    packet = _formal_packet(tmp_path, context, feedback)

    shadow = copy.deepcopy(packet)
    shadow["mechanism_conditioned_measurement_program"]["model_selection"][
        "selection_argument"
    ] = "a different but syntactically valid post-qualification argument"

    reasons = validate_formal_evo_packet(
        shadow,
        workspace_root=tmp_path,
        report_id=REPORT_ID,
    )
    assert f"{BLOCK_EVIDENCE_VIEW}:measurement_program" in reasons

    # The canonical frozen object itself is also hash-bound by the feedback
    # ledger, so rewriting it after qualification invalidates the intake.
    frozen_path = tmp_path / context["frozen_measurement_program_ref"]["path"]
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    frozen["model_selection"]["selection_argument"] = "mutated frozen bytes"
    _write_json(frozen_path, frozen)
    try:
        load_formal_evo_packet_context(tmp_path, REPORT_ID)
    except Exception as exc:
        assert "measurement_program_ref" in str(exc)
    else:
        raise AssertionError("mutated frozen measurement program was accepted")


def test_task_identity_binds_feedback_contradiction_and_route_tuple(
    tmp_path: Path,
) -> None:
    _bundle, _feedback = _formal_workspace(tmp_path)
    context, _loaded = load_formal_evo_packet_context(tmp_path, REPORT_ID)
    assert context is not None
    identity = build_evo_task_identity(
        context,
        report_id=REPORT_ID,
        task_id="route_symbolic",
        route_id="symbolic",
        route_fingerprint="route_hash",
        blind_context_hash="blind_hash",
    )
    expected = {
        "evo_v2_required": True,
        "evo_v2_task_identity": identity,
        "evo_v2_packet_context": context,
    }
    proposal, payload, _artifacts = _proposal_and_payload(tmp_path / "proposal")
    payload["feedback_ledger"] = context["canonical_feedback_ref"]
    payload["intake_gate"]["validity_quarantine"][
        "qualified_feedback_ref"
    ] = context["canonical_feedback_ref"]
    result = {
        **proposal,
        "evo_v2": payload,
        "evo_v2_task_identity": copy.deepcopy(identity),
        "dispatch_identity": {
            "evo_v2_task_identity_sha256": identity["identity_sha256"]
        },
    }
    assert validate_result_evo_identity(result, expected) == []
    result["evo_v2_task_identity"]["contradiction_id"] = "post_hash_mutation"
    assert validate_result_evo_identity(result, expected)


def test_agentic_result_accepts_no_derived_zero_laws_and_rejects_hidden_law(
    tmp_path: Path,
) -> None:
    _bundle, _feedback = _formal_workspace(tmp_path)
    context, _loaded = load_formal_evo_packet_context(tmp_path, REPORT_ID)
    assert context is not None
    identity = build_evo_task_identity(
        context,
        report_id=REPORT_ID,
        task_id="route_symbolic",
        route_id="symbolic",
        route_fingerprint="route_hash",
        blind_context_hash="blind_hash",
    )
    proposal, payload, _artifacts = _proposal_and_payload(tmp_path / "proposal")
    proof = copy.deepcopy(
        payload["derivation_outcome"].get("no_derived_law")
    )
    from tests.test_revision_council_evo_v2 import _no_derived_proof

    proof = _no_derived_proof(context["contradiction_id"])
    payload["feedback_ledger"] = context["canonical_feedback_ref"]
    payload["intake_gate"]["validity_quarantine"][
        "qualified_feedback_ref"
    ] = context["canonical_feedback_ref"]
    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": proof,
    }
    payload["proposal_law_binding"] = None
    result = {
        **proposal,
        "candidate_revision_laws": [],
        "evo_v2": payload,
        "evo_v2_task_identity": identity,
        "dispatch_identity": {
            "evo_v2_task_identity_sha256": identity["identity_sha256"]
        },
    }
    expected = {
        "evo_v2_required": True,
        "evo_v2_task_identity": identity,
        "evo_v2_packet_context": context,
    }
    reasons = AGENTIC_VALIDATOR.validate_agentic_result(
        result,
        expected_task=expected,
        expected_report_id=REPORT_ID,
        workspace_root=tmp_path,
    )
    assert "BLOCK_REVISION_COUNCIL_AGENTIC_REVISION_LAWS_MISSING" not in reasons
    assert not any("NO_DERIVED_LAW_CANDIDATE" in reason for reason in reasons)

    result["candidate_revision_laws"] = [{"law_id": "hidden"}]
    reasons = AGENTIC_VALIDATOR.validate_agentic_result(
        result,
        expected_task=expected,
        expected_report_id=REPORT_ID,
        workspace_root=tmp_path,
    )
    assert (
        "BLOCK_COUNCIL_EVO_V2_NO_DERIVED_LAW_CANDIDATE_LAWS_NOT_EMPTY"
        in reasons
    )


def test_outcome_summary_preserves_bound_tuple_and_indexes_no_no_derived_law(
    tmp_path: Path,
) -> None:
    proposal, payload, _artifacts = _proposal_and_payload(tmp_path)
    proposal["evo_v2"] = payload
    proposal["evo_v2_task_identity"] = {"identity_sha256": "a" * 64}
    summary = result_evo_outcome_summary(proposal)
    assert summary is not None
    assert summary["outcome"] == "MINIMAL_MECHANISM_DELTA"
    assert summary["law_sha256"] == payload["proposal_law_binding"]["law_sha256"]
    assert summary["delta_id"] == payload["proposal_law_binding"]["delta_id"]

    payload["derivation_outcome"] = {
        "outcome": "NO_DERIVED_LAW",
        "mechanism_delta": None,
        "economic_backprojection": None,
        "no_derived_law": {"proof": "not indexed as a law"},
    }
    payload["proposal_law_binding"] = None
    proposal["candidate_revision_laws"] = []
    summary = result_evo_outcome_summary(proposal)
    assert summary is not None
    assert summary["outcome"] == "NO_DERIVED_LAW"
    assert summary["candidate_law_count"] == 0
    assert "law_sha256" not in summary
