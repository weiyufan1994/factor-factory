from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import factor_factory.evo_terminal_closure as terminal
from factor_factory.evo_oos import (
    allocate_fresh_child_oos,
    consume_oos_allocation_for_release,
)
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
)
from factor_factory.research_evidence import sha256_file
from factor_factory.research_obligation_verifier import stable_hash as obligation_hash
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.research_release import stable_hash as release_hash

REPORT_ID = "EVO_TERMINAL_REPORT"
FACTOR_ID = "EVO_TERMINAL_FACTOR"
INSTALLATION_ID = "evo-terminal-test-installation"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _setup_trust(tmp_path: Path) -> tuple[Path, Path, object]:
    root = tmp_path / "workspace"
    root.mkdir()
    trust_root = tmp_path / "host-private-trust"
    trust = ensure_runtime_trust_store(
        trust_root,
        installation_id=INSTALLATION_ID,
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
    runtime_state["state_sha256"] = obligation_hash(runtime_state)
    _write_json(
        root / organization_root / "runtime/runtime_state.json",
        runtime_state,
    )
    return root, trust_root, trust


def _verifier_reference(root: Path) -> dict:
    path = root / "objects/evidence/nqc_host_verifier.json"
    payload = {
        "verifier_id": "test_nqc_host_verifier_v1",
        "verifier_status": "PASS",
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": "b" * 64,
    }
    _write_json(path, payload)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": "b" * 64,
        "verifier_id": "test_nqc_host_verifier_v1",
        "verifier_status": "PASS",
    }


def _write_signed_nqc_lifecycle(root: Path, trust: object) -> None:
    evidence_refs = [_verifier_reference(root)]
    initial = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="PREDICTIONS_FROZEN",
        evidence_refs=copy.deepcopy(evidence_refs),
    )
    _write_json(
        epistemic_evolution_lifecycle_snapshot_path(root, REPORT_ID, 1),
        initial,
    )
    receipt = trust.sign(
        "host_admission",
        {
            "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
            "report_id": REPORT_ID,
            "sequence": 2,
            "from_state": "PREDICTIONS_FROZEN",
            "to_state": "NO_QUALIFIED_CONTRADICTION",
            "lifecycle_parent_sha256": obligation_hash(initial),
            "evidence_refs_sha256": obligation_hash(evidence_refs),
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
            "authority_scope": (
                "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_SEMANTIC_AUTHORITY"
            ),
            "oos_accessed": False,
        },
    )
    receipt_path = (
        epistemic_evolution_lifecycle_path(root, REPORT_ID).parent
        / "lifecycle_transition_receipt__0002.json"
    )
    _write_json(receipt_path, receipt)
    final = build_epistemic_evolution_lifecycle(
        report_id=REPORT_ID,
        to_state="NO_QUALIFIED_CONTRADICTION",
        evidence_refs=copy.deepcopy(evidence_refs),
        existing=initial,
        actor_receipt_ref={
            "path": receipt_path.relative_to(root).as_posix(),
            "sha256": sha256_file(receipt_path),
            "receipt_id": receipt["receipt_id"],
            "trust_manifest_sha256": trust.public_manifest["manifest_sha256"],
        },
    )
    _write_json(epistemic_evolution_lifecycle_path(root, REPORT_ID), final)
    _write_json(
        epistemic_evolution_lifecycle_snapshot_path(root, REPORT_ID, 2),
        final,
    )


def _write_release(root: Path) -> Path:
    protocol = root / "objects/research_protocol"
    ledger_path = protocol / f"search_trial_ledger__{REPORT_ID}.json"
    threshold_path = protocol / f"threshold_registration__{REPORT_ID}.json"
    _write_json(ledger_path, {"report_id": REPORT_ID, "status": "FROZEN"})
    _write_json(threshold_path, {"report_id": REPORT_ID, "status": "LOCKED"})
    release_path = protocol / f"oos_release_manifest__{REPORT_ID}.json"
    payload = {
        "version": "factorforge_oos_release_manifest_v1",
        "release_status": "RELEASED",
        "report_id": REPORT_ID,
        "factor_id": FACTOR_ID,
        "release_sequence": 30,
        "search_trial_ledger_ref": ledger_path.relative_to(root).as_posix(),
        "search_trial_ledger_sha256": sha256_file(ledger_path),
        "threshold_registration_ref": threshold_path.relative_to(root).as_posix(),
        "threshold_registration_sha256": sha256_file(threshold_path),
        "dataset_snapshot_hash": "a" * 64,
        "window_hash": "c" * 64,
        "evaluation_contract_hash": "d" * 64,
        "oos_window": "2026-01-01/2026-03-31",
        "observed_start_date": "2026-01-01",
        "observed_end_date": "2026-03-31",
        "observed_period_count": 60,
        "oos_release_token_hash": "b" * 64,
    }
    payload["release_manifest_sha256"] = release_hash(payload)
    _write_json(release_path, payload)
    return release_path


def _write_terminal_artifacts(
    root: Path,
    *,
    verdict: str,
    source_step6_decision: str | None = None,
) -> Path:
    release_path = _write_release(root)
    protocol = root / "objects/research_protocol"
    _write_json(
        protocol / f"factor_proof_certificate__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": FACTOR_ID,
            "declared_verdict": verdict,
            "component_obligation_bindings": [],
            "data_contract": {
                "oos_release_manifest_ref": release_path.relative_to(root).as_posix()
            },
        },
    )
    objects = root / "objects"
    simple = {
        "factor_case_master": objects
        / "factor_case_master"
        / f"factor_case_master__{REPORT_ID}.json",
        "factor_evaluation": objects
        / "validation"
        / f"factor_evaluation__{REPORT_ID}.json",
        "factor_run_master": objects
        / "factor_run_master"
        / f"factor_run_master__{REPORT_ID}.json",
        "factor_spec_master": objects
        / "factor_spec_master"
        / f"factor_spec_master__{REPORT_ID}.json",
        "handoff_to_step6": objects / "handoff" / f"handoff_to_step6__{REPORT_ID}.json",
        "factor_library_all": objects
        / "factor_library_all"
        / f"factor_record__{REPORT_ID}.json",
        "research_knowledge_base": objects
        / "research_knowledge_base"
        / f"knowledge_record__{REPORT_ID}.json",
    }
    for role, path in simple.items():
        _write_json(
            path,
            {"report_id": REPORT_ID, "factor_id": FACTOR_ID, "role": role},
        )
    decision = source_step6_decision or (
        "promote_official" if verdict == "ACCEPT" else "reject"
    )
    _write_json(
        objects
        / "research_iteration_master"
        / f"research_iteration_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": FACTOR_ID,
            "research_judgment": {
                "decision": decision,
                "research_memo": {
                    "revision_strategy": {"loop_authorization": "blocked"},
                    "final_revision_strategy": {"loop_authorization": "blocked"},
                },
            },
        },
    )
    if verdict == "ACCEPT":
        _write_json(
            objects / "factor_library_official" / f"factor_record__{REPORT_ID}.json",
            {"report_id": REPORT_ID, "factor_id": FACTOR_ID},
        )
    return release_path


def _patch_final_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_factor_proof(payload: dict, **_: object) -> dict:
        verdict = payload.get("declared_verdict")
        return {
            "verdict": verdict,
            "block_reasons": [],
            "current_formal_authority_verified": True,
        }

    def fake_step_validator(*, step: str, **_: object) -> dict:
        return {
            "validator_id": terminal._VALIDATOR_SPECS[step][0],
            "source_sha256": ("5" if step == "step5" else "6") * 64,
            "result": "PASS",
            "return_code": 0,
            "report_sha256": ("a" if step == "step5" else "b") * 64,
            "error_count": 0,
            "warning_count": 0,
        }

    monkeypatch.setattr(
        terminal, "validate_factor_proof_certificate", fake_factor_proof
    )
    monkeypatch.setattr(terminal, "_run_step_validator", fake_step_validator)


def _ready_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    verdict: str = "ACCEPT",
    registered_oos: bool = True,
    consume: bool = True,
    source_step6_decision: str | None = None,
) -> tuple[Path, Path, Path]:
    root, trust_root, trust = _setup_trust(tmp_path)
    _write_signed_nqc_lifecycle(root, trust)
    release_path = _write_terminal_artifacts(
        root,
        verdict=verdict,
        source_step6_decision=source_step6_decision,
    )
    if registered_oos:
        allocate_fresh_child_oos(
            workspace_root=root,
            allocation_id="allocation_terminal_report_001",
            report_id=REPORT_ID,
            parent_report_id="ROOT_PARENT_REPORT",
            dataset_snapshot_sha256="a" * 64,
            oos_start="2026-01-01",
            oos_end="2026-03-31",
            sealed_token_sha256="b" * 64,
            expected_registry_sha256=None,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
            legacy_test_only=True,
        )
        if consume:
            consume_oos_allocation_for_release(
                workspace_root=root,
                report_id=REPORT_ID,
                release_manifest_path=release_path,
                incident_trust_root=trust_root,
                incident_installation_id=INSTALLATION_ID,
            )
    _patch_final_validators(monkeypatch)
    return root, trust_root, release_path


def test_accept_closure_is_host_signed_non_revision_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(tmp_path, monkeypatch)
    issued = terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert issued["verdict"] == "PASS"
    assert issued["status"] == "ISSUED"
    closure = json.loads(
        terminal.terminal_closure_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert closure["formal_factor_verdict"] == "ACCEPT"
    assert closure["source_step6_decision"] == "promote_official"
    assert closure["step6_decision"] == "promote_official"
    assert closure["oos_consumption"]["mode"] == (
        "SIGNED_REGISTRY_ONE_TIME_CONSUMPTION"
    )
    assert all(value is False for value in closure["authority_guard"].values())
    assert closure["learning_disposition"]["canonical_promotion_performed"] is False

    replay = terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert replay["verdict"] == "PASS"
    assert replay["status"] == "IDEMPOTENT_REPLAY"


def test_terminal_receipt_partial_write_recovers_without_published_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(tmp_path, monkeypatch)
    receipt_path = terminal.terminal_closure_receipt_path(root, REPORT_ID)
    real_write = terminal.os.write
    calls = 0

    def interrupted_write(descriptor: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, data[:17])
        raise OSError("simulated_terminal_receipt_interrupt")

    monkeypatch.setattr(terminal.os, "write", interrupted_write)
    with pytest.raises(OSError, match="simulated_terminal_receipt_interrupt"):
        terminal.issue_evo_post_oos_terminal_closure(
            workspace_root=root,
            report_id=REPORT_ID,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
        )
    assert not receipt_path.exists()
    assert not terminal.terminal_closure_path(root, REPORT_ID).exists()

    monkeypatch.setattr(terminal.os, "write", real_write)
    recovered = terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert recovered["verdict"] == "PASS"
    assert recovered["status"] == "ISSUED"


def test_terminal_closure_partial_write_recovers_from_exact_receipt_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(tmp_path, monkeypatch)
    closure_path = terminal.terminal_closure_path(root, REPORT_ID)
    real_write = terminal.os.write
    calls = 0

    def interrupt_second_artifact(descriptor: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            return real_write(descriptor, data[:19])
        if calls == 3:
            raise OSError("simulated_terminal_closure_interrupt")
        return real_write(descriptor, data)

    monkeypatch.setattr(terminal.os, "write", interrupt_second_artifact)
    with pytest.raises(OSError, match="simulated_terminal_closure_interrupt"):
        terminal.issue_evo_post_oos_terminal_closure(
            workspace_root=root,
            report_id=REPORT_ID,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
        )
    assert terminal.terminal_closure_receipt_path(root, REPORT_ID).is_file()
    assert not closure_path.exists()

    monkeypatch.setattr(terminal.os, "write", real_write)
    recovered = terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert recovered["verdict"] == "PASS"
    assert recovered["status"] == "ISSUED"


def test_reject_closure_allows_only_kill_and_learn_historical_episode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(
        tmp_path,
        monkeypatch,
        verdict="REJECT",
        registered_oos=False,
    )
    report = terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert report["verdict"] == "PASS"
    closure = json.loads(
        terminal.terminal_closure_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert closure["formal_factor_verdict"] == "REJECT"
    assert closure["source_step6_decision"] == "reject"
    assert closure["step6_decision"] == "reject"
    assert closure["oos_consumption"]["mode"] == "IMMUTABLE_ORIGINAL_RELEASE_CHAIN"
    assert closure["learning_disposition"] == {
        "mode": "KILL_AND_LEARN_HISTORICAL_EPISODE_ONLY",
        "kill_and_learn": True,
        "historical_episode_candidate_allowed": True,
        "historical_episode_recorded": False,
        "structural_lesson_generated": False,
        "conditional_lesson_generated": False,
        "canonical_promotion_performed": False,
    }


def test_reject_closure_projects_non_authoritative_iterate_to_kill_and_learn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(
        tmp_path,
        monkeypatch,
        verdict="REJECT",
        registered_oos=False,
        source_step6_decision="iterate",
    )
    report = terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert report["verdict"] == "PASS"
    closure = json.loads(
        terminal.terminal_closure_path(root, REPORT_ID).read_text(encoding="utf-8")
    )
    assert closure["formal_factor_verdict"] == "REJECT"
    assert closure["source_step6_decision"] == "iterate"
    assert closure["step6_decision"] == "reject"
    assert closure["authority_guard"]["revision_authority"] is False
    assert closure["learning_disposition"]["kill_and_learn"] is True


def test_lifecycle_snapshot_tamper_blocks_terminal_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(tmp_path, monkeypatch)
    snapshot_path = epistemic_evolution_lifecycle_snapshot_path(root, REPORT_ID, 2)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["current_state"] = "QUALIFIED_CONTRADICTION"
    _write_json(snapshot_path, snapshot)
    with pytest.raises(ValueError, match="LIFECYCLE_INVALID|snapshot"):
        terminal.issue_evo_post_oos_terminal_closure(
            workspace_root=root,
            report_id=REPORT_ID,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
        )
    assert not terminal.terminal_closure_path(root, REPORT_ID).exists()


@pytest.mark.parametrize("active_surface", ["handoff", "iteration_authority"])
def test_active_post_oos_revision_surface_blocks_terminal_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_surface: str,
) -> None:
    root, trust_root, _ = _ready_workspace(tmp_path, monkeypatch)
    if active_surface == "handoff":
        _write_json(
            root / "objects/handoff" / f"handoff_to_step3b__{REPORT_ID}.json",
            {"loop_authorization": "approved_for_step3b_handoff"},
        )
    else:
        iteration_path = (
            root
            / "objects/research_iteration_master"
            / f"research_iteration_master__{REPORT_ID}.json"
        )
        iteration = json.loads(iteration_path.read_text(encoding="utf-8"))
        iteration["research_judgment"]["research_memo"]["revision_strategy"][
            "loop_authorization"
        ] = "approved_for_step3b_handoff"
        _write_json(iteration_path, iteration)
    with pytest.raises(ValueError, match="active_revision_or_decision"):
        terminal.issue_evo_post_oos_terminal_closure(
            workspace_root=root,
            report_id=REPORT_ID,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
        )


def test_registered_but_unconsumed_oos_blocks_terminal_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(
        tmp_path,
        monkeypatch,
        registered_oos=True,
        consume=False,
    )
    with pytest.raises(ValueError, match="release_consumption_count"):
        terminal.issue_evo_post_oos_terminal_closure(
            workspace_root=root,
            report_id=REPORT_ID,
            trust_root=trust_root,
            installation_id=INSTALLATION_ID,
        )


def test_rehashed_closure_authority_tamper_still_fails_host_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, trust_root, _ = _ready_workspace(tmp_path, monkeypatch)
    terminal.issue_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    path = terminal.terminal_closure_path(root, REPORT_ID)
    closure = json.loads(path.read_text(encoding="utf-8"))
    closure["authority_guard"]["child_execution_allowed"] = True
    unsigned = dict(closure)
    unsigned.pop("content_sha256", None)
    closure["content_sha256"] = terminal.stable_hash(unsigned)
    _write_json(path, closure)
    report = terminal.validate_evo_post_oos_terminal_closure(
        workspace_root=root,
        report_id=REPORT_ID,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )
    assert report["verdict"] == "BLOCK"
    assert any("host_receipt_binding" in reason for reason in report["block_reasons"])
