from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import factor_factory.evo_terminal_closure as terminal_closure
import factor_factory.evo_transfer_use_orchestrator as transfer_orchestrator
import tests.test_factorforge_evo_transfer_use_orchestrator as transfer_fixtures

from factor_factory.console.evo_resume import (
    PAUSE_AWAIT_EXTERNAL_CHILD,
    PAUSE_AWAIT_HOST_COUNCIL_OUTCOME,
    PAUSE_AWAIT_HOST_QUALIFICATION,
    PAUSE_AWAIT_NQC_TERMINAL_CLOSURE,
    PAUSE_AWAIT_TRANSFER_USE,
    PROGRESS_CHILD_HANDOFF_AUTHORIZED,
    PROGRESS_HOST_CHECKPOINT_READY,
    PROGRESS_TERMINAL_CHECKPOINT_READY,
    PROGRESS_WAITING,
    EvoV2ExternalResumeError,
    assess_evo_v2_external_resume,
)
from factor_factory.console.run_service import (
    RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY,
    RESUME_KIND_EVO_V2_EXTERNAL_WAIT,
    RESUME_KIND_HOST_FORMAL_CHECKPOINT,
    RESUME_KIND_EVO_V2_TERMINAL_CHECKPOINT,
    _classify_resume_route,
    _workspace_evidence_tree,
)
from factor_factory.evo_staging import (
    STAGE_ADMIT_FEEDBACK,
    _lifecycle_parent_sha256,
    materialize_evo_v2_stage,
)
from factor_factory.evo_memory_runtime import protected_contract_hashes
from factor_factory.evo_v2 import (
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_paths,
    sha256_file,
    with_content_hash,
)
from factor_factory.pre_oos_human_bridge import (
    materialize_pre_oos_human_bridge as _materialize_pre_oos_human_bridge,
    pre_oos_child_handoff_path,
    pre_oos_child_intent_path,
    pre_oos_human_approval_path,
)
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
)
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import (
    ensure_runtime_trust_store,
    load_runtime_trust_store,
)
from factor_factory.researcher_memory import (
    build_evo_v2_transfer_use_change_receipt,
)
from factor_factory.researcher_memory_review import (
    build_evo_v2_memory_review_projection,
)
from tests.test_factorforge_evo_pre_oos_orchestrator import (
    _orchestrate,
    _prepare as _prepare_outcome,
)
from tests.test_factorforge_evo_terminal_closure import (
    INSTALLATION_ID as TERMINAL_INSTALLATION_ID,
    REPORT_ID as TERMINAL_REPORT_ID,
    _ready_workspace as _ready_terminal_workspace,
)
from tests.test_factorforge_evo_transfer_use_orchestrator import (
    _found_inputs as _formal_found_inputs,
    _write_execution_tests as _write_formal_execution_tests,
)
from tests.test_factorforge_evo_v2 import REPORT_ID, _as_cold_start, _build_bundle
from tests.test_factorforge_pre_oos_council_outcome import _fixture
from tests.test_factorforge_pre_oos_human_bridge import (
    CHILD_ID,
    _allocate_oos,
    _complete_transfer_use_low_level_only as _complete_transfer_use,
    _external_human_receipt,
    _prepare_minimal,
)
from tests.test_factorforge_researcher_memory_evo_v2 import (
    _completed_cold_start_search,
    _completed_review_decision,
    _transfer_use_change_receipt,
    _json_bytes as _review_json_bytes,
)


def materialize_pre_oos_human_bridge(**kwargs):
    """Console fixture reuses its attested Host trust pair for incidents."""

    kwargs.setdefault("incident_trust_root", kwargs["host_trust_root"])
    kwargs.setdefault("incident_installation_id", kwargs["installation_id"])
    return _materialize_pre_oos_human_bridge(**kwargs)


_PROOF_CONTRACTS = {
    PAUSE_AWAIT_HOST_QUALIFICATION: (
        "purged_is_checkpoint_only_awaiting_host_qualification",
        "PREDICTIONS_FROZEN",
        "AWAIT_HOST_QUALIFICATION",
    ),
    PAUSE_AWAIT_HOST_COUNCIL_OUTCOME: (
        "pre_oos_council_outcome_verified_review_only",
        "QUALIFIED_CONTRADICTION",
        "RUN_PRE_OOS_REVISION_COUNCIL",
    ),
    PAUSE_AWAIT_TRANSFER_USE: (
        "review_only_delta_awaiting_transfer_and_actual_use",
        "MINIMAL_MECHANISM_DELTA",
        "AWAIT_EVO_V2_TRANSFER_AND_USE",
    ),
    PAUSE_AWAIT_EXTERNAL_CHILD: (
        "review_only_delta_awaiting_external_approval_and_fresh_child",
        "TRANSFER_RECORDED",
        "AWAIT_EXTERNAL_APPROVAL_AND_CHILD",
    ),
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _prefix(lifecycle: dict, generation: int) -> dict:
    events = lifecycle["events"][:generation]
    payload = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": lifecycle["report_id"],
        "current_state": events[-1]["to_state"],
        "events": events,
        "host_authority": lifecycle["host_authority"],
    }
    payload["content_sha256"] = stable_hash(payload)
    return payload


def _write_snapshots(root: Path, lifecycle: dict) -> None:
    for generation in range(1, len(lifecycle["events"]) + 1):
        _write_json(
            epistemic_evolution_lifecycle_snapshot_path(
                root, REPORT_ID, generation
            ),
            _prefix(lifecycle, generation),
        )
    _write_json(epistemic_evolution_lifecycle_path(root, REPORT_ID), lifecycle)


def _proof(root: Path, pause: str) -> tuple[dict, Path]:
    semantics, state, action = _PROOF_CONTRACTS[pause]
    payload = {
        "report_id": REPORT_ID,
        "status": "PAUSED",
        "failure": None,
        "factor_verdict": "NOT_ISSUED",
        "formal_proof_eligible": False,
        "proof_semantics": semantics,
        "final_outcome": pause,
        "evo_v2_execution_gate": {
            "enabled": True,
            "current_state": state,
            "action": action,
            "oos_release_allowed": False,
            "oos_artifacts": [],
        },
    }
    path = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}.json"
    )
    _write_json(path, payload)
    return payload, path


def _terminal_pause_proof(root: Path) -> tuple[dict, Path]:
    payload = {
        "report_id": TERMINAL_REPORT_ID,
        "status": "PAUSED",
        "failure": None,
        "formal_proof_eligible": False,
        "proof_semantics": (
            "awaiting_evo_v2_non_revision_terminal_closure"
        ),
        "final_outcome": PAUSE_AWAIT_NQC_TERMINAL_CLOSURE,
        "evo_v2_execution_gate": {
            "enabled": True,
            "current_state": "NO_QUALIFIED_CONTRADICTION",
            "action": "RELEASE_ORIGINAL_CANDIDATE_OOS",
            "oos_release_allowed": True,
            "oos_artifacts": [],
        },
        "evo_v2_post_oos_terminal_closure": {
            "verdict": "AWAITING_HOST_SIGNATURE",
            "formal_factor_verdict": None,
            "block_reasons": [
                "formal Host trust root and installation identity required"
            ],
        },
        "revision_council": {
            "status": "not_triggered",
            "terminal_protocol_validated": False,
        },
    }
    path = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{TERMINAL_REPORT_ID}.json"
    )
    _write_json(path, payload)
    return payload, path


def _stage_feedback(root: Path) -> None:
    lifecycle_path = epistemic_evolution_lifecycle_path(root, REPORT_ID)
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    parent_sha = _lifecycle_parent_sha256(lifecycle)
    assert isinstance(parent_sha, str)
    feedback = json.loads(
        evo_v2_paths(root, REPORT_ID)["feedback_ledger"].read_text(
            encoding="utf-8"
        )
    )
    materialize_evo_v2_stage(
        workspace_root=root,
        report_id=REPORT_ID,
        stage=STAGE_ADMIT_FEEDBACK,
        expected_lifecycle_parent_sha256=parent_sha,
        expected_lifecycle_content_sha256=lifecycle["content_sha256"],
        expected_staging_content_sha256="ABSENT",
        feedback_ledger=feedback,
    )


def _assessment(
    root: Path,
    proof: dict,
    baseline: dict[str, str] | None = None,
    *,
    trust_root: Path | None = None,
    installation_id: str | None = None,
    admissions_root: Path | None = None,
):
    return assess_evo_v2_external_resume(
        workspace_root=root,
        report_id=REPORT_ID,
        proof=proof,
        attested_entries=baseline,
        trust_root=trust_root,
        installation_id=installation_id,
        admissions_root=admissions_root,
    )


def _formal_host_trust_root(root: Path) -> Path:
    """Reuse the private Host root that the shared pre-OOS fixture owns."""

    external = root.parent / f".{root.name}-host-private-trust"
    target = root.parent / f".{root.name}-formal-host-state" / "research-org-trust"
    private_inside = root / "host-private-trust"
    if not target.is_dir() and (private_inside.is_dir() or external.is_dir()):
        target.parent.mkdir(parents=True, exist_ok=True)
        (private_inside if private_inside.is_dir() else external).rename(target)
    assert target.is_dir()
    return target


def _formal_admissions_root(root: Path) -> Path:
    return _formal_host_trust_root(root).parent / "researcher-memory-evo-v2"


def _allocate_oos_with_console_host(root: Path, trust_root: Path) -> None:
    _allocate_oos(root, trust_root=trust_root)


def _attested_tree_before_external_child_actions(root: Path) -> dict[str, str]:
    """Model a pause whose human key was pinned before later signed actions."""

    entries = _workspace_evidence_tree(root)
    dynamic = {
        "identity/evo_oos_host_trust_manifest.json",
        "identity/pre_oos_external_human_receipt.json",
        "objects/research_protocol/evo_oos_allocation_registry.json",
        "objects/research_protocol/evo_oos_allocation_registry.json.lock",
        (
            "objects/research_protocol/"
            f"evo_oos_allocation__{CHILD_ID}.json"
        ),
        (
            "objects/research_protocol/"
            f"evo_oos_allocation_host_receipt__{CHILD_ID}.json"
        ),
    }
    for relative in dynamic:
        entries.pop(relative, None)
    human_trust = "identity/human_approval_trust.json"
    assert human_trust in entries
    return entries


def _merge_formal_transfer_fixture_prerequisites(
    root: Path,
    baseline: dict[str, str],
) -> None:
    """Treat the formal plan/review inputs built by the compact fixture as pre-pause."""

    evo_root = f"objects/evo_v2/{REPORT_ID}"
    host_action_outputs = {
        f"{evo_root}/lifecycle.json",
        f"{evo_root}/lifecycle_history/lifecycle__0004.json",
        f"{evo_root}/lifecycle_transition_receipt__0004.json",
        f"{evo_root}/staging_manifest.json",
        f"{evo_root}/experience_transfer_bundle.json",
        f"{evo_root}/transfer_use_receipt.json",
        f"{evo_root}/transfer_use_preflight_verifier.json",
        f"{evo_root}/transfer_use_orchestration.json",
        f"{evo_root}/execution_addendum.json",
        f"{evo_root}/.transfer_use_orchestration.lock",
        f"{evo_root}/execution_addendum.lock",
    }
    for relative, digest in _workspace_evidence_tree(root).items():
        if relative not in host_action_outputs:
            baseline[relative] = digest


def _formalize_human_fixture_cold_transfer(
    root: Path,
    *,
    minimal: dict,
    council_stage: dict,
) -> tuple[Path, Path]:
    installation_id = "council-test-installation-001"
    trust_root = _formal_host_trust_root(root)
    trust = load_runtime_trust_store(
        trust_root,
        installation_id=installation_id,
    )
    core_paths = evo_v2_paths(root, REPORT_ID)
    delta = json.loads(
        core_paths["mechanism_delta"].read_text(encoding="utf-8")
    )
    backprojection = json.loads(
        core_paths["economic_backprojection"].read_text(encoding="utf-8")
    )
    support_root = root / "transfer_support"
    bundle = _build_bundle(support_root)
    shutil.copytree(support_root / "support", root / "support", dirs_exist_ok=True)
    baseline_support = root / "bundle_support" / "support"
    baseline_support.mkdir(parents=True, exist_ok=True)
    for name in (
        "frozen_authority.json",
        "independent_reviewer.json",
        "is_evidence.json",
        "memory_retrieval.json",
        "preregistration.json",
        "source_experience.json",
    ):
        source = support_root / "support" / name
        if source.is_file():
            shutil.copy2(source, baseline_support / name)
    transfer = copy.deepcopy(bundle["experience_transfer_bundle"])
    transfer["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    transfer["economic_backprojection_ref"]["sha256"] = artifact_sha256(
        backprojection
    )
    transfer.pop("content_sha256", None)
    transfer = with_content_hash(transfer)
    use = copy.deepcopy(bundle["transfer_use_receipt"])
    use["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    use.pop("content_sha256", None)
    use = with_content_hash(use)
    artifacts = {
        "feedback_ledger": json.loads(
            core_paths["feedback_ledger"].read_text(encoding="utf-8")
        ),
        "mechanism_delta": delta,
        "economic_backprojection": backprojection,
        "experience_transfer_bundle": transfer,
        "transfer_use_receipt": use,
    }
    cold = _as_cold_start(artifacts, root)
    cold_receipt, _request = _completed_cold_start_search(
        tmp_path=trust_root.parent,
        workspace=root,
        transfer=cold["experience_transfer_bundle"],
        trust_store=trust,
    )
    inputs = root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    cold_receipt_path = inputs / "cold_start_search_receipt.json"
    cold_receipt_path.write_bytes(canonical_json_bytes(cold_receipt))
    transfer = cold["experience_transfer_bundle"]
    transfer["retrieval_policy"]["retrieval_evidence_refs"] = [
        {
            "path": cold_receipt_path.relative_to(root).as_posix(),
            "sha256": sha256_file(cold_receipt_path),
        }
    ]
    transfer.pop("content_sha256", None)
    transfer = with_content_hash(transfer)
    use = cold["transfer_use_receipt"]
    use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    use.pop("content_sha256", None)
    use = with_content_hash(use)
    transfer_path = inputs / "experience_transfer_bundle.json"
    use_path = inputs / "transfer_use_receipt.json"
    transfer_path.write_bytes(canonical_json_bytes(transfer))
    use_path.write_bytes(canonical_json_bytes(use))
    admissions_root = _formal_admissions_root(root)
    result = transfer_orchestrator.orchestrate_evo_v2_transfer_use(
        workspace_root=root,
        report_id=REPORT_ID,
        expected_minimal_lifecycle_sha256=stable_hash(minimal),
        expected_staging_content_sha256=(
            council_stage["staging_manifest"]["content_sha256"]
        ),
        experience_transfer_bundle_path=transfer_path,
        transfer_use_receipt_path=use_path,
        cold_start_search_receipt_path=cold_receipt_path,
        trust_root=trust_root,
        installation_id=installation_id,
        admissions_root=admissions_root,
    )
    assert result["verdict"] == "PASS"
    assert result["memory_state"] == "COLD_START_NO_ADMISSIBLE_MEMORY"
    shutil.rmtree(support_root)
    return trust_root, admissions_root


def _formalize_human_fixture_found_transfer(
    root: Path,
    *,
    minimal: dict,
    council_stage: dict,
) -> tuple[Path, Path]:
    installation_id = "council-test-installation-001"
    trust_root = _formal_host_trust_root(root)
    trust = load_runtime_trust_store(
        trust_root,
        installation_id=installation_id,
    )
    core_paths = evo_v2_paths(root, REPORT_ID)
    delta = json.loads(
        core_paths["mechanism_delta"].read_text(encoding="utf-8")
    )
    backprojection = json.loads(
        core_paths["economic_backprojection"].read_text(encoding="utf-8")
    )
    support_root = root / "transfer_support"
    bundle = _build_bundle(support_root)
    shutil.copytree(support_root / "support", root / "support", dirs_exist_ok=True)
    baseline_support = root / "bundle_support" / "support"
    baseline_support.mkdir(parents=True, exist_ok=True)
    for name in (
        "frozen_authority.json",
        "independent_reviewer.json",
        "is_evidence.json",
        "memory_retrieval.json",
        "preregistration.json",
        "source_experience.json",
    ):
        source = support_root / "support" / name
        if source.is_file():
            shutil.copy2(source, baseline_support / name)
    transfer = copy.deepcopy(bundle["experience_transfer_bundle"])
    transfer["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    transfer["economic_backprojection_ref"]["sha256"] = artifact_sha256(
        backprojection
    )
    transfer.pop("content_sha256", None)
    transfer = with_content_hash(transfer)
    use = copy.deepcopy(bundle["transfer_use_receipt"])
    use["mechanism_delta_ref"]["sha256"] = artifact_sha256(delta)
    use["transfer_bundle_ref"]["sha256"] = artifact_sha256(transfer)
    use.pop("content_sha256", None)
    use = with_content_hash(use)
    artifacts = {
        "feedback_ledger": json.loads(
            core_paths["feedback_ledger"].read_text(encoding="utf-8")
        ),
        "mechanism_delta": delta,
        "economic_backprojection": backprojection,
        "experience_transfer_bundle": transfer,
        "transfer_use_receipt": use,
    }
    review_state_root = root.parent / f".{root.name}-review-state"
    review_trust_root = review_state_root / "research-org-trust"
    review_state_root.mkdir(parents=True, exist_ok=True)
    if not review_trust_root.exists():
        shutil.copytree(trust_root, review_trust_root)
    original_installation_id = transfer_fixtures.INSTALLATION_ID
    transfer_fixtures.INSTALLATION_ID = installation_id
    try:
        transfer_path, use_path, decision_path, change_path = (
            _formal_found_inputs(root, review_trust_root, artifacts)
        )
    finally:
        transfer_fixtures.INSTALLATION_ID = original_installation_id
    tests_path = _write_formal_execution_tests(root, artifacts)
    admissions_root = _formal_admissions_root(root)
    result = transfer_orchestrator.orchestrate_evo_v2_transfer_use(
        workspace_root=root,
        report_id=REPORT_ID,
        expected_minimal_lifecycle_sha256=stable_hash(minimal),
        expected_staging_content_sha256=(
            council_stage["staging_manifest"]["content_sha256"]
        ),
        experience_transfer_bundle_path=transfer_path,
        transfer_use_receipt_path=use_path,
        review_decision_receipt_path=decision_path,
        transfer_use_change_receipt_path=change_path,
        execution_tests_path=tests_path,
        trust_root=trust_root,
        installation_id=installation_id,
        admissions_root=admissions_root,
    )
    assert result["verdict"] == "PASS"
    assert result["memory_state"] == "ADMISSIBLE_MEMORY_FOUND"
    shutil.rmtree(support_root)
    return trust_root, admissions_root


def test_waiting_external_control_never_becomes_formal_checkpoint(
    tmp_path: Path,
) -> None:
    _synthesis, _selected, lifecycle, _stage = _prepare_minimal(tmp_path)
    _write_snapshots(tmp_path, lifecycle)
    proof, proof_path = _proof(tmp_path, PAUSE_AWAIT_TRANSFER_USE)
    baseline = _workspace_evidence_tree(tmp_path)

    assessment = _assessment(tmp_path, proof, baseline)
    assert assessment.status == PROGRESS_WAITING
    assert assessment.start_step is None
    route = _classify_resume_route(
        tmp_path,
        REPORT_ID,
        start_step="6",
        trusted_proof_sha256=sha256_file(proof_path),
        evo_v2_external_progress=assessment.to_dict(),
    )
    assert route.kind == RESUME_KIND_EVO_V2_EXTERNAL_WAIT


def test_each_external_pause_remains_waiting_before_its_exact_host_action(
    tmp_path: Path,
) -> None:
    qualification_root = tmp_path / "qualification"
    _synthesis, _synthesis_path = _fixture(qualification_root)
    qualified_path = epistemic_evolution_lifecycle_path(
        qualification_root, REPORT_ID
    )
    qualified = json.loads(qualified_path.read_text(encoding="utf-8"))
    _write_snapshots(qualification_root, _prefix(qualified, 1))
    qualification_proof, _proof_path = _proof(
        qualification_root, PAUSE_AWAIT_HOST_QUALIFICATION
    )
    assert _assessment(
        qualification_root,
        qualification_proof,
        _workspace_evidence_tree(qualification_root),
    ).status == PROGRESS_WAITING

    council_root = tmp_path / "council"
    _synthesis, _synthesis_path = _fixture(council_root)
    council_lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(council_root, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(council_root, council_lifecycle)
    _stage_feedback(council_root)
    council_proof, _proof_path = _proof(
        council_root, PAUSE_AWAIT_HOST_COUNCIL_OUTCOME
    )
    assert _assessment(
        council_root,
        council_proof,
        _workspace_evidence_tree(council_root),
    ).status == PROGRESS_WAITING

    transfer_root = tmp_path / "transfer"
    _synthesis, _selected, minimal, _stage = _prepare_minimal(transfer_root)
    _write_snapshots(transfer_root, minimal)
    transfer_proof, _proof_path = _proof(
        transfer_root, PAUSE_AWAIT_TRANSFER_USE
    )
    assert _assessment(
        transfer_root,
        transfer_proof,
        _workspace_evidence_tree(transfer_root),
    ).status == PROGRESS_WAITING

    child_root = tmp_path / "child"
    _synthesis, _selected, minimal, council_stage = _prepare_minimal(
        child_root
    )
    trust_root, admissions_root = _formalize_human_fixture_found_transfer(
        child_root,
        minimal=minimal,
        council_stage=council_stage,
    )
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(child_root, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(child_root, transferred)
    child_proof, _proof_path = _proof(
        child_root, PAUSE_AWAIT_EXTERNAL_CHILD
    )
    assert _assessment(
        child_root,
        child_proof,
        _workspace_evidence_tree(child_root),
        trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=admissions_root,
    ).status == PROGRESS_WAITING


def test_external_pause_classifier_rejects_unattested_local_replay(
    tmp_path: Path,
) -> None:
    _synthesis, _selected, minimal, _stage = _prepare_minimal(tmp_path)
    _write_snapshots(tmp_path, minimal)
    _proof_payload, proof_path = _proof(tmp_path, PAUSE_AWAIT_TRANSFER_USE)

    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _classify_resume_route(
            tmp_path,
            REPORT_ID,
            start_step="6",
            trusted_proof_sha256=sha256_file(proof_path),
        )


@pytest.mark.parametrize(
    ("formal_verdict", "terminal_decision"),
    [("ACCEPT", "promote_official"), ("REJECT", "reject")],
)
def test_nqc_terminal_closure_waits_then_completes_without_parent_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    formal_verdict: str,
    terminal_decision: str,
) -> None:
    root, trust_root, _release = _ready_terminal_workspace(
        tmp_path,
        monkeypatch,
        verdict=formal_verdict,
        registered_oos=False,
    )
    proof, proof_path = _terminal_pause_proof(root)
    baseline = _workspace_evidence_tree(root)

    waiting = assess_evo_v2_external_resume(
        workspace_root=root,
        report_id=TERMINAL_REPORT_ID,
        proof=proof,
        attested_entries=baseline,
    )
    assert waiting.status == PROGRESS_WAITING
    assert waiting.start_step is None
    assert waiting.reason == (
        "non_revision_terminal_closure_waiting_host_signature"
    )

    issued = terminal_closure.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=TERMINAL_REPORT_ID,
        trust_root=trust_root,
        installation_id=TERMINAL_INSTALLATION_ID,
    )
    assert issued["verdict"] == "PASS"
    ready = assess_evo_v2_external_resume(
        workspace_root=root,
        report_id=TERMINAL_REPORT_ID,
        proof=proof,
        attested_entries=baseline,
        trust_root=trust_root,
        installation_id=TERMINAL_INSTALLATION_ID,
    )
    assert ready.status == PROGRESS_TERMINAL_CHECKPOINT_READY
    assert ready.start_step is None
    assert ready.terminal_factor_verdict == formal_verdict
    assert ready.terminal_decision == terminal_decision
    closure_path = terminal_closure.terminal_closure_path(
        root, TERMINAL_REPORT_ID
    )
    assert ready.terminal_closure_path == closure_path.relative_to(root).as_posix()
    assert ready.terminal_closure_sha256 == sha256_file(closure_path)

    route = _classify_resume_route(
        root,
        TERMINAL_REPORT_ID,
        start_step="6",
        trusted_proof_sha256=sha256_file(proof_path),
        evo_v2_external_progress=ready.to_dict(),
    )
    assert route.kind == RESUME_KIND_EVO_V2_TERMINAL_CHECKPOINT


def test_nqc_terminal_closure_forged_receipt_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _release = _ready_terminal_workspace(
        tmp_path,
        monkeypatch,
        registered_oos=False,
    )
    proof, _proof_path = _terminal_pause_proof(root)
    baseline = _workspace_evidence_tree(root)
    terminal_closure.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=TERMINAL_REPORT_ID,
        trust_root=trust_root,
        installation_id=TERMINAL_INSTALLATION_ID,
    )
    receipt_path = terminal_closure.terminal_closure_receipt_path(
        root, TERMINAL_REPORT_ID
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["signature"]["value_b64"] = "AAAA"
    _write_json(receipt_path, receipt)
    closure_path = terminal_closure.terminal_closure_path(
        root, TERMINAL_REPORT_ID
    )
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    closure["host_receipt_ref"]["sha256"] = sha256_file(receipt_path)
    closure.pop("content_sha256")
    closure["content_sha256"] = terminal_closure.stable_hash(closure)
    _write_json(closure_path, closure)

    with pytest.raises(EvoV2ExternalResumeError, match="host_receipt|signature"):
        assess_evo_v2_external_resume(
            workspace_root=root,
            report_id=TERMINAL_REPORT_ID,
            proof=proof,
            attested_entries=baseline,
            trust_root=trust_root,
            installation_id=TERMINAL_INSTALLATION_ID,
        )


def test_qualification_resume_anchors_old_generation_not_mutable_head(
    tmp_path: Path,
) -> None:
    _synthesis, _synthesis_path = _fixture(tmp_path)
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    qualified = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    frozen = _prefix(qualified, 1)
    _write_snapshots(tmp_path, frozen)
    proof, proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_QUALIFICATION)
    baseline = _workspace_evidence_tree(tmp_path)
    paused_head_sha = baseline[
        lifecycle_path.relative_to(tmp_path).as_posix()
    ]

    _write_snapshots(tmp_path, qualified)
    _stage_feedback(tmp_path)
    assert sha256_file(lifecycle_path) != paused_head_sha
    assessment = _assessment(tmp_path, proof, baseline)
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.paused_lifecycle_generation == 1
    assert assessment.current_lifecycle_generation == 2
    route = _classify_resume_route(
        tmp_path,
        REPORT_ID,
        start_step="6",
        trusted_proof_sha256=sha256_file(proof_path),
        evo_v2_external_progress=assessment.to_dict(),
    )
    assert route.kind == RESUME_KIND_HOST_FORMAL_CHECKPOINT
    assert route.start_step == "6"


def test_signed_no_qualified_contradiction_resumes_oos_release_step6(
    tmp_path: Path,
) -> None:
    _synthesis, _synthesis_path = _fixture(tmp_path)
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    qualified = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    frozen = _prefix(qualified, 1)
    _write_snapshots(tmp_path, frozen)
    epistemic_evolution_lifecycle_snapshot_path(
        tmp_path, REPORT_ID, 2
    ).unlink(missing_ok=True)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_QUALIFICATION)
    baseline = _workspace_evidence_tree(tmp_path)

    trust = load_runtime_trust_store(
        tmp_path / "host-private-trust",
        installation_id="council-test-installation-001",
    )
    evidence_refs = frozen["events"][0]["evidence_refs"]
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": 2,
            "from_state": "PREDICTIONS_FROZEN",
            "to_state": "NO_QUALIFIED_CONTRADICTION",
            "lifecycle_parent_sha256": stable_hash(frozen),
            "evidence_refs_sha256": stable_hash(evidence_refs),
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
        lifecycle_path.parent
        / "lifecycle_transition_receipt__0002_nqc.json"
    )
    _write_json(receipt_path, receipt)
    no_contradiction = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="NO_QUALIFIED_CONTRADICTION",
        evidence_refs=evidence_refs,
        existing=frozen,
        actor_receipt_ref={
            "path": receipt_path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_sha256": trust.public_manifest[
                "manifest_sha256"
            ],
        },
    )
    _write_snapshots(tmp_path, no_contradiction)

    assessment = _assessment(tmp_path, proof, baseline)
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.start_step == "6"
    assert assessment.current_lifecycle_state == "NO_QUALIFIED_CONTRADICTION"
    assert assessment.staging_event_count == 0


def test_child_preregistered_unsigned_genesis_uses_external_host_manifest_for_cas(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "objects/research_protocol/freeze_verifier.json"
    verifier_payload = {
        "verifier_status": "PASS",
        "verifier_id": "factorforge_evo_child_prediction_freeze_v1",
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": "b" * 64,
    }
    _write_json(evidence_path, verifier_payload)
    evidence_refs = [
        {
            "path": evidence_path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(evidence_path),
            "dataset_snapshot_hash": "a" * 64,
            "window_hash": "b" * 64,
            "verifier_id": verifier_payload["verifier_id"],
            "verifier_status": "PASS",
        }
    ]
    frozen = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="PREDICTIONS_FROZEN",
        evidence_refs=evidence_refs,
    )
    _write_snapshots(tmp_path, frozen)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_QUALIFICATION)
    baseline = _workspace_evidence_tree(tmp_path)
    trust = ensure_runtime_trust_store(
        tmp_path.parent / f".{tmp_path.name}-child-host-trust",
        installation_id="child-lifecycle-host",
    )
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": 2,
            "from_state": "PREDICTIONS_FROZEN",
            "to_state": "NO_QUALIFIED_CONTRADICTION",
            "lifecycle_parent_sha256": stable_hash(frozen),
            "evidence_refs_sha256": stable_hash(evidence_refs),
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
            "authority_scope": (
                "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
            ),
            "oos_accessed": False,
        },
    )
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    receipt_path = (
        lifecycle_path.parent / "lifecycle_transition_receipt__0002.json"
    )
    _write_json(receipt_path, receipt)
    transitioned = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="NO_QUALIFIED_CONTRADICTION",
        evidence_refs=evidence_refs,
        existing=frozen,
        actor_receipt_ref={
            "path": receipt_path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
        },
    )
    _write_snapshots(tmp_path, transitioned)
    assessment = assess_evo_v2_external_resume(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        proof=proof,
        attested_entries=baseline,
        trusted_lifecycle_manifest=trust.public_manifest,
        require_signed_lifecycle_genesis=False,
    )
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.start_step == "6"


def test_signed_council_outcome_and_exact_staging_enable_only_step6_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare_outcome(
        tmp_path, monkeypatch
    )
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, lifecycle)
    _stage_feedback(tmp_path)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_COUNCIL_OUTCOME)
    baseline = _workspace_evidence_tree(tmp_path)

    result = _orchestrate(
        tmp_path, trust_root, qualified_sha, expected_state
    )
    assert result["verdict"] == "PASS"
    assessment = _assessment(tmp_path, proof, baseline)
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.start_step == "6"
    assert assessment.staging_event_count == 2


def test_signed_no_derived_law_outcome_resumes_terminal_step6_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare_outcome(
        tmp_path,
        monkeypatch,
        outcomes=("NO_DERIVED_LAW", "NO_DERIVED_LAW"),
        selected_index=1,
    )
    assert expected_state == "NO_DERIVED_LAW"
    qualified = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, qualified)
    _stage_feedback(tmp_path)
    proof, _proof_path = _proof(
        tmp_path, PAUSE_AWAIT_HOST_COUNCIL_OUTCOME
    )
    baseline = _workspace_evidence_tree(tmp_path)

    result = _orchestrate(
        tmp_path, trust_root, qualified_sha, expected_state
    )
    assert result["verdict"] == "PASS"
    assessment = _assessment(tmp_path, proof, baseline)
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.start_step == "6"
    assert assessment.current_lifecycle_state == "NO_DERIVED_LAW"
    assert assessment.staging_event_count == 2


@pytest.mark.parametrize(
    "lifecycle_state",
    ["TRANSFER_RECORDED", "COLD_START_RECORDED"],
)
def test_low_level_four_stage_transfer_cannot_bypass_formal_orchestration(
    tmp_path: Path,
    lifecycle_state: str,
) -> None:
    _synthesis, _selected, minimal, _stage = _prepare_minimal(tmp_path)
    _write_snapshots(tmp_path, minimal)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_TRANSFER_USE)
    baseline = _workspace_evidence_tree(tmp_path)

    _complete_transfer_use(
        tmp_path,
        minimal,
        lifecycle_state=lifecycle_state,
    )
    shutil.rmtree(tmp_path / "transfer_support")
    if lifecycle_state == "COLD_START_RECORDED":
        # The shared fixture creates positive-memory support before converting
        # the payload to cold-start.  Those two now-unreferenced fixture files
        # are not outputs of a real cold-start Host action.
        (tmp_path / "support" / "independent_reviewer.json").unlink()
        (tmp_path / "support" / "source_experience.json").unlink()
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, transferred)
    external_trust = _formal_host_trust_root(tmp_path)
    with pytest.raises(
        EvoV2ExternalResumeError,
        match="formal_transfer_use_orchestration|missing_or_unsafe",
    ):
        _assessment(
            tmp_path,
            proof,
            baseline,
            trust_root=external_trust,
            installation_id="council-test-installation-001",
            admissions_root=_formal_admissions_root(tmp_path),
        )


def test_formal_found_orchestration_and_addendum_enable_step6_checkpoint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "found"
    _synthesis, _selected, minimal, council_stage = _prepare_minimal(root)
    trust_root = _formal_host_trust_root(root)
    admissions_root = _formal_admissions_root(root)
    _write_snapshots(root, minimal)
    proof, _proof_path = _proof(root, PAUSE_AWAIT_TRANSFER_USE)
    baseline = _workspace_evidence_tree(root)
    observed_trust_root, observed_admissions_root = (
        _formalize_human_fixture_found_transfer(
            root,
            minimal=minimal,
            council_stage=council_stage,
        )
    )
    assert observed_trust_root == trust_root
    assert observed_admissions_root == admissions_root
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(root, transferred)
    _merge_formal_transfer_fixture_prerequisites(root, baseline)
    assessment = _assessment(
        root,
        proof,
        baseline,
        trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=admissions_root,
    )
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.start_step == "6"
    assert assessment.transfer_memory_state == "ADMISSIBLE_MEMORY_FOUND"
    assert assessment.transfer_use_orchestration_path
    assert assessment.transfer_use_orchestration_sha256
    assert assessment.execution_addendum_path
    assert assessment.execution_addendum_sha256
    assert assessment.execution_addendum_status == (
        "HOST_ATTESTED_PREREGISTERED_TRANSFER_TESTS_NOT_EXECUTED"
    )
    assert assessment.execution_addendum_state == (
        "PREREGISTERED_AND_BOUND_NOT_EVALUATED"
    )
    assert assessment.transfer_test_execution_completed is False


def test_formal_cold_zero_hit_without_addendum_enables_step6_checkpoint(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cold"
    _synthesis, _selected, minimal, council_stage = _prepare_minimal(root)
    trust_root = _formal_host_trust_root(root)
    admissions_root = _formal_admissions_root(root)
    _write_snapshots(root, minimal)
    proof, _proof_path = _proof(root, PAUSE_AWAIT_TRANSFER_USE)
    baseline = _workspace_evidence_tree(root)
    observed_trust_root, observed_admissions_root = (
        _formalize_human_fixture_cold_transfer(
            root,
            minimal=minimal,
            council_stage=council_stage,
        )
    )
    assert observed_trust_root == trust_root
    assert observed_admissions_root == admissions_root
    for name in (
        "independent_reviewer.json",
        "memory_retrieval.json",
        "source_experience.json",
    ):
        source = root / "support" / name
        baseline[f"support/{name}"] = sha256_file(source)
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(root, transferred)
    assessment = _assessment(
        root,
        proof,
        baseline,
        trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=admissions_root,
    )
    assert assessment.status == PROGRESS_HOST_CHECKPOINT_READY
    assert assessment.transfer_memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
    assert assessment.transfer_use_orchestration_path
    assert assessment.execution_addendum_path is None
    assert assessment.execution_addendum_sha256 is None
    assert assessment.execution_addendum_status is None
    assert assessment.execution_addendum_state is None
    assert assessment.transfer_test_execution_completed is False


def test_external_human_and_fresh_child_are_verified_without_parent_runner(
    tmp_path: Path,
) -> None:
    synthesis, selected, minimal, council_stage = _prepare_minimal(tmp_path)
    trust_root, admissions_root = _formalize_human_fixture_cold_transfer(
        tmp_path,
        minimal=minimal,
        council_stage=council_stage,
    )
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, transferred)
    proof, proof_path = _proof(tmp_path, PAUSE_AWAIT_EXTERNAL_CHILD)
    proof["evo_v2_execution_gate"]["current_state"] = "COLD_START_RECORDED"
    _write_json(proof_path, proof)

    _allocate_oos_with_console_host(tmp_path, trust_root)
    receipt_path, trust_sha = _external_human_receipt(
        tmp_path, synthesis, selected
    )
    baseline = _attested_tree_before_external_child_actions(tmp_path)
    bridge = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=None,
    )
    assert bridge["verdict"] == "PASS"
    assessment = _assessment(
        tmp_path,
        proof,
        baseline,
        trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=None,
    )
    assert assessment.status == PROGRESS_CHILD_HANDOFF_AUTHORIZED
    assert assessment.start_step is None
    assert assessment.child_report_id
    assert assessment.transfer_memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY"
    assert assessment.transfer_use_orchestration_path
    assert assessment.execution_addendum_path is None
    route = _classify_resume_route(
        tmp_path,
        REPORT_ID,
        start_step="6",
        trusted_proof_sha256=sha256_file(proof_path),
        evo_v2_external_progress=assessment.to_dict(),
    )
    assert route.kind == RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY


def test_external_human_new_self_signed_key_after_attestation_fails_closed(
    tmp_path: Path,
) -> None:
    synthesis, selected, minimal, council_stage = _prepare_minimal(tmp_path)
    trust_root, _admissions_root = _formalize_human_fixture_cold_transfer(
        tmp_path,
        minimal=minimal,
        council_stage=council_stage,
    )
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, transferred)
    proof, proof_path = _proof(tmp_path, PAUSE_AWAIT_EXTERNAL_CHILD)
    proof["evo_v2_execution_gate"]["current_state"] = "COLD_START_RECORDED"
    _write_json(proof_path, proof)
    _allocate_oos_with_console_host(tmp_path, trust_root)

    # The first key is the only human authority bound by the Host attestation.
    _external_human_receipt(tmp_path, synthesis, selected)
    baseline = _attested_tree_before_external_child_actions(tmp_path)
    # A workspace writer replaces it with a new key and self-signs every
    # otherwise valid approval artifact.  The bridge alone can validate this
    # internally consistent tree; console resume must reject its authority.
    forged_receipt, forged_trust_sha = _external_human_receipt(
        tmp_path, synthesis, selected
    )
    bridge = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=forged_receipt,
        human_trust_manifest_sha256=forged_trust_sha,
        host_trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=None,
    )
    assert bridge["verdict"] == "PASS"
    with pytest.raises(
        EvoV2ExternalResumeError,
        match="human_trust_not_attested_before_external_approval|allowed_file_sha256",
    ):
        _assessment(
            tmp_path,
            proof,
            baseline,
            trust_root=trust_root,
            installation_id="council-test-installation-001",
            admissions_root=None,
        )


def test_fresh_oos_new_self_signed_host_key_fails_closed(
    tmp_path: Path,
) -> None:
    synthesis, selected, minimal, council_stage = _prepare_minimal(tmp_path)
    trust_root, _admissions_root = _formalize_human_fixture_cold_transfer(
        tmp_path,
        minimal=minimal,
        council_stage=council_stage,
    )
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, transferred)
    proof, proof_path = _proof(tmp_path, PAUSE_AWAIT_EXTERNAL_CHILD)
    proof["evo_v2_execution_gate"]["current_state"] = "COLD_START_RECORDED"
    _write_json(proof_path, proof)

    # This allocator is cryptographically valid but uses an unrelated private
    # Host key rather than the console state-root Host authority.
    unrelated_trust_root = (
        tmp_path.parent / f".{tmp_path.name}-unrelated-oos-host-trust"
    )
    ensure_runtime_trust_store(
        unrelated_trust_root,
        installation_id="council-test-installation-001",
    )
    _allocate_oos(tmp_path, trust_root=unrelated_trust_root)
    receipt_path, trust_sha = _external_human_receipt(
        tmp_path, synthesis, selected
    )
    baseline = _attested_tree_before_external_child_actions(tmp_path)
    bridge = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=None,
    )
    assert bridge["verdict"] == "PASS"
    with pytest.raises(
        EvoV2ExternalResumeError,
        match="oos_host_trust_not_console_host",
    ):
        _assessment(
            tmp_path,
            proof,
            baseline,
            trust_root=trust_root,
            installation_id="council-test-installation-001",
            admissions_root=None,
        )


def test_external_human_found_transfer_binds_same_orchestration_and_addendum(
    tmp_path: Path,
) -> None:
    synthesis, selected, minimal, council_stage = _prepare_minimal(tmp_path)
    trust_root, admissions_root = _formalize_human_fixture_found_transfer(
        tmp_path,
        minimal=minimal,
        council_stage=council_stage,
    )
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, transferred)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_EXTERNAL_CHILD)

    _allocate_oos_with_console_host(tmp_path, trust_root)
    receipt_path, trust_sha = _external_human_receipt(
        tmp_path, synthesis, selected
    )
    baseline = _attested_tree_before_external_child_actions(tmp_path)
    bridge = materialize_pre_oos_human_bridge(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        human_approval_receipt=receipt_path,
        human_trust_manifest_sha256=trust_sha,
        host_trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=admissions_root,
    )
    assessment = _assessment(
        tmp_path,
        proof,
        baseline,
        trust_root=trust_root,
        installation_id="council-test-installation-001",
        admissions_root=admissions_root,
    )
    assert bridge["verdict"] == "PASS"
    assert assessment.status == PROGRESS_CHILD_HANDOFF_AUTHORIZED
    assert assessment.child_report_id
    assert assessment.transfer_memory_state == "ADMISSIBLE_MEMORY_FOUND"
    assert assessment.execution_addendum_path

    orchestration = json.loads(
        (tmp_path / assessment.transfer_use_orchestration_path).read_text(
            encoding="utf-8"
        )
    )
    orchestration_ref = {
        "path": assessment.transfer_use_orchestration_path,
        "sha256": assessment.transfer_use_orchestration_sha256,
        "content_sha256": assessment.transfer_use_orchestration_content_sha256,
    }
    addendum_ref = orchestration["gate_evidence"]["execution_addendum_ref"]
    handoff = json.loads(
        pre_oos_child_handoff_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    approval = json.loads(
        pre_oos_human_approval_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    child_intent = json.loads(
        pre_oos_child_intent_path(
            tmp_path, assessment.child_report_id
        ).read_text(encoding="utf-8")
    )
    assert handoff["formal_transfer_use_orchestration_ref"] == orchestration_ref
    assert handoff["execution_addendum_ref"] == addendum_ref
    assert approval["evidence_bindings"][
        "formal_transfer_use_orchestration_ref"
    ] == orchestration_ref
    assert approval["evidence_bindings"]["execution_addendum_ref"] == addendum_ref
    assert child_intent["formal_transfer_use_orchestration_ref"] == orchestration_ref
    assert child_intent["execution_addendum_ref"] == addendum_ref


def test_paused_snapshot_hash_drift_and_cross_report_proof_fail_closed(
    tmp_path: Path,
) -> None:
    _synthesis, _selected, minimal, _stage = _prepare_minimal(tmp_path)
    _write_snapshots(tmp_path, minimal)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_TRANSFER_USE)
    baseline = _workspace_evidence_tree(tmp_path)
    snapshot = epistemic_evolution_lifecycle_snapshot_path(
        tmp_path, REPORT_ID, 3
    )
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["content_sha256"] = "0" * 64
    _write_json(snapshot, payload)
    with pytest.raises(EvoV2ExternalResumeError, match="paused_snapshot|lifecycle"):
        _assessment(tmp_path, proof, baseline)

    _write_snapshots(tmp_path, minimal)
    crossed = dict(proof)
    crossed["report_id"] = "OTHER_REPORT"
    with pytest.raises(EvoV2ExternalResumeError, match="pause_proof_binding"):
        _assessment(tmp_path, crossed, baseline)


def test_valid_signed_chain_still_blocks_state_jump_from_old_pause(
    tmp_path: Path,
) -> None:
    _synthesis, _selected, minimal, _stage = _prepare_minimal(tmp_path)
    frozen = _prefix(minimal, 1)
    _write_snapshots(tmp_path, frozen)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_QUALIFICATION)
    baseline = _workspace_evidence_tree(tmp_path)
    _write_snapshots(tmp_path, minimal)

    with pytest.raises(EvoV2ExternalResumeError, match="lifecycle_state_jump"):
        _assessment(tmp_path, proof, baseline)


def test_pause_gate_state_must_equal_attested_lifecycle_generation(
    tmp_path: Path,
) -> None:
    _synthesis, _selected, minimal, _stage = _prepare_minimal(tmp_path)
    _complete_transfer_use(tmp_path, minimal)
    shutil.rmtree(tmp_path / "transfer_support")
    transferred = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    _write_snapshots(tmp_path, transferred)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_EXTERNAL_CHILD)
    baseline = _workspace_evidence_tree(tmp_path)
    proof["evo_v2_execution_gate"]["current_state"] = "COLD_START_RECORDED"

    with pytest.raises(
        EvoV2ExternalResumeError,
        match="pause_gate_lifecycle_state_mismatch",
    ):
        _assessment(tmp_path, proof, baseline)


def test_forged_host_signature_and_unexplained_file_delta_fail_closed(
    tmp_path: Path,
) -> None:
    _synthesis, _synthesis_path = _fixture(tmp_path)
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    qualified = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    frozen = _prefix(qualified, 1)
    _write_snapshots(tmp_path, frozen)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_QUALIFICATION)
    baseline = _workspace_evidence_tree(tmp_path)
    _write_snapshots(tmp_path, qualified)
    _stage_feedback(tmp_path)

    event = qualified["events"][1]
    receipt_ref = event["actor_receipt_ref"]
    receipt_path = tmp_path / receipt_ref["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["signature"]["value_b64"] = "AAAA"
    _write_json(receipt_path, receipt)
    receipt_ref["sha256"] = sha256_file(receipt_path)
    event_unsigned = dict(event)
    event_unsigned.pop("event_sha256")
    event["event_sha256"] = stable_hash(event_unsigned)
    lifecycle_unsigned = dict(qualified)
    lifecycle_unsigned.pop("content_sha256")
    qualified["content_sha256"] = stable_hash(lifecycle_unsigned)
    _write_snapshots(tmp_path, qualified)
    with pytest.raises(EvoV2ExternalResumeError, match="signature|receipt"):
        _assessment(tmp_path, proof, baseline)

    # Restore a valid signed chain, then show that a file outside every
    # validator-explained delta remains a trust failure.
    _synthesis, _synthesis_path = _fixture(tmp_path / "clean")
    clean = tmp_path / "clean"
    clean_lifecycle_path = epistemic_evolution_lifecycle_path(clean, REPORT_ID)
    clean_qualified = json.loads(clean_lifecycle_path.read_text(encoding="utf-8"))
    clean_frozen = _prefix(clean_qualified, 1)
    _write_snapshots(clean, clean_frozen)
    clean_proof, _clean_proof_path = _proof(
        clean, PAUSE_AWAIT_HOST_QUALIFICATION
    )
    clean_baseline = _workspace_evidence_tree(clean)
    _write_snapshots(clean, clean_qualified)
    _stage_feedback(clean)
    (clean / "objects" / "rogue_external_authority.json").write_text(
        "{}\n", encoding="utf-8"
    )
    with pytest.raises(EvoV2ExternalResumeError, match="untrusted_workspace_delta"):
        _assessment(clean, clean_proof, clean_baseline)


def test_unstaged_canonical_evo_sibling_does_not_gain_resume_authority(
    tmp_path: Path,
) -> None:
    _synthesis, _synthesis_path = _fixture(tmp_path)
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    qualified = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    frozen = _prefix(qualified, 1)
    _write_snapshots(tmp_path, frozen)
    proof, _proof_path = _proof(tmp_path, PAUSE_AWAIT_HOST_QUALIFICATION)
    baseline = _workspace_evidence_tree(tmp_path)

    _write_snapshots(tmp_path, qualified)
    _stage_feedback(tmp_path)
    _write_json(
        evo_v2_paths(tmp_path, REPORT_ID)["experience_transfer_bundle"],
        {"report_id": REPORT_ID, "self_declared": "HOST_ADMITTED"},
    )
    with pytest.raises(EvoV2ExternalResumeError, match="untrusted_workspace_delta"):
        _assessment(tmp_path, proof, baseline)
