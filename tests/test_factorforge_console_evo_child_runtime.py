from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import factor_factory.console.evo_child_runtime as runtime
from factor_factory.console import run_service
from factor_factory.console.run_service import ResearchRunService
from factor_factory.console.private_job_root import (
    ensure_host_private_job_subdirectory,
)
from factor_factory.evo_child_materialization_admission import (
    child_materialization_admission_path,
    materialize_evo_child_materialization_admission,
    validate_evo_child_materialization_admission,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.oos_exposure_incident import (
    build_oos_exposure_incident,
    oos_exposure_incident_path,
    register_oos_exposure_incident_host_private,
    write_oos_exposure_incident_create_only,
)
from tests.test_factorforge_evo_child_materialization_admission import (
    _materialized_fixture,
)
from tests.test_factorforge_pre_oos_human_bridge import (
    CHILD_ID as FORMAL_CHILD,
    INSTALLATION_ID as FORMAL_INSTALLATION,
    REPORT_ID as FORMAL_PARENT,
    _host_trust_root as formal_host_trust_root,
)

PARENT = "RUNTIME_PARENT"
CHILD = "RUNTIME_PARENT__EVO_CHILD_001"
INSTALLATION = "runtime-test-host"
JOB = "job_runtime_001"


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    patch_materialization_validator: bool = True,
) -> dict:
    tree = tmp_path / "worktree"
    workspace = tree / "factor_research/factor/research"
    workspace.mkdir(parents=True)
    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    trust = state / "research-org-trust"
    store = ensure_runtime_trust_store(trust, installation_id=INSTALLATION)
    pin = store.public_manifest["manifest_sha256"]
    counter = tree / "counter.txt"
    argv_log = tree / "argv.json"
    ultimate = tree / "fake_ultimate.py"
    ultimate.write_text(
        """#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser(add_help=False)
p.add_argument('--report-id'); p.add_argument('--start-step')
p.add_argument('--factor-workspace'); args,_=p.parse_known_args()
workspace=Path(args.factor_workspace)
counter=workspace.parents[2]/'counter.txt'
attempt=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(attempt))
(workspace.parents[2]/'argv.json').write_text(json.dumps({'report_id':args.report_id,'start_step':args.start_step}))
proof=workspace/'objects/runtime_context'/f'ultimate_run_report__{args.report_id}.json'
proof.parent.mkdir(parents=True,exist_ok=True)
requested={'3b':['3b','4','5','6'],'4':['4','5','6'],'5':['5','6'],'6':['6']}[args.start_step]
terminal=(workspace.parents[2]/'terminal_mode').exists()
proof.write_text(json.dumps({'report_id':args.report_id,'status':'PAUSED','factor_verdict':'NOT_ISSUED','attempt':attempt,'requested_steps':requested,'commands':[{'name':'run_step4','returncode':0}],'proof_semantics':'awaiting_evo_v2_non_revision_terminal_closure' if terminal else 'purged_is_checkpoint_only_awaiting_host_qualification','final_outcome':'awaiting_evo_v2_non_revision_terminal_closure' if terminal else 'awaiting_evo_v2_host_qualification','evo_v2_execution_gate':{'enabled':True,'current_state':'NO_QUALIFIED_CONTRADICTION' if terminal else 'PREDICTIONS_FROZEN','action':'RELEASE_ORIGINAL_CANDIDATE_OOS' if terminal else 'AWAIT_HOST_QUALIFICATION','oos_release_allowed':terminal,'oos_artifacts':[]}}))
""",
        encoding="utf-8",
    )
    ultimate.chmod(0o700)
    container_admission = state / "container-admission.json"
    _write(container_admission, b"admission\n")
    container_admission.chmod(0o600)
    other = workspace / "objects/research_protocol/materialization.json"
    _write(other, b"materialized\n")
    artifacts = {
        "container_admission": runtime._ref(container_admission),
        "child_materialization": runtime._ref(other),
        "ultimate_script": runtime._ref(ultimate),
    }
    argv = [
        str(ultimate),
        "--report-id",
        CHILD,
        "--start-step",
        "3b",
        "--factor-workspace",
        str(workspace),
    ]
    identity = {
        "job_id": JOB,
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_trust_manifest_sha256": pin,
    }
    core = {
        "receipt_type": "EVO_CHILD_RUNTIME_STAGE",
        "runtime_version": runtime.CHILD_RUNTIME_VERSION,
        "stage_index": 7,
        "stage": runtime.CHILD_EXECUTION_READY,
        "identity": identity,
        "trusted_parent_checkpoint": {"ultimate_proof_sha256": "a" * 64},
        "previous_stage_receipt_id": "previous",
        "artifacts": artifacts,
        "execution": {
            "argv": argv,
            "argv_sha256": runtime.stable_json_hash(argv),
            "ultimate_script_sha256": runtime._sha256(ultimate),
            "cwd": str(tree),
            "start_step": "3b",
            "credential_environment": "HOST_PREFETCH_ONLY_AGENT_STAGES_STRIPPED",
            "container_admission_sha256": runtime._sha256(
                container_admission
            ),
        },
        "authority": {
            "child_execution_allowed": True,
            "allowed_start_step": "3b",
            "oos_release_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "skill_or_policy_mutation_allowed": False,
        },
    }
    core["content_sha256"] = runtime.stable_json_hash(core)
    checkpoint = store.sign("host_admission", core)
    checkpoint_path = state / "ready.json"
    checkpoint_path.write_bytes(runtime._canonical_bytes(checkpoint))
    checkpoint_path.chmod(0o600)
    termination_path = ensure_host_private_job_subdirectory(
        state,
        JOB,
        ("evo-child-container", CHILD),
        create=True,
    ) / "termination__000001__validate_step4.json"
    termination_receipt = store.sign(
        "host_admission",
        {
            "receipt_type": "EVO_CHILD_AGENT_STAGE_CONTAINER_TERMINATION",
            "identity": {
                "installation_id": INSTALLATION,
                "job_id": JOB,
                "parent_report_id": PARENT,
                "child_report_id": CHILD,
            },
            "stage_name": "validate_step4",
            "process_tree": {"process_tree_absent": True},
        },
    )
    termination_path.write_bytes(runtime._canonical_bytes(termination_receipt))
    termination_path.chmod(0o600)
    monkeypatch.setattr(
        runtime,
        "validate_evo_child_container_admission",
        lambda **_kwargs: {"verdict": "PASS"},
    )
    monkeypatch.setattr(
        runtime,
        "reconcile_evo_child_agent_stage_containers",
        lambda **_kwargs: {
            "verdict": "PASS",
            "process_tree_absent": True,
        },
    )
    monkeypatch.setattr(
        runtime,
        "validate_latest_evo_child_agent_termination",
        lambda **_kwargs: {
            "verdict": "PASS",
            "stage_name": "validate_step4",
            "process_tree_absent": True,
            "termination_receipt_path": termination_path,
            "termination_receipt": termination_receipt,
        },
    )
    if patch_materialization_validator:
        monkeypatch.setattr(
            runtime,
            "validate_evo_child_materialization_admission",
            lambda **_kwargs: ({"verdict": "PASS"}, []),
        )
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "4")
    return {
        "tree": tree,
        "workspace": workspace,
        "state": state,
        "trust": trust,
        "store": store,
        "pin": pin,
        "checkpoint": checkpoint_path,
        "counter": counter,
        "argv_log": argv_log,
    }


def _execute(fixture: dict, *, resume: bool = False) -> dict:
    return runtime.execute_evo_child_ready(
        checkpoint_path=fixture["checkpoint"],
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["tree"],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        host_environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=60,
        resume=resume,
    )


def test_initial_execution_replays_materialization_with_current_incident_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    captured: list[dict[str, object]] = []

    def current_materialization(**kwargs):
        captured.append(dict(kwargs))
        return {"verdict": "PASS"}, []

    monkeypatch.setattr(
        runtime,
        "validate_evo_child_materialization_admission",
        current_materialization,
    )
    result = _execute(fixture)
    assert result["status"] == runtime.CHILD_RESUME_READY
    assert len(captured) == 1
    assert captured[0]["incident_trust_root"] == fixture["trust"]
    assert captured[0]["incident_installation_id"] == INSTALLATION


def test_initial_execution_passes_current_incident_context_to_real_materialization_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(
        tmp_path,
        monkeypatch,
        patch_materialization_validator=False,
    )
    pin, _report, _targets = _materialized_fixture(
        fixture["workspace"], monkeypatch
    )
    trust = formal_host_trust_root(fixture["workspace"])
    materialize_evo_child_materialization_admission(
        workspace_root=fixture["workspace"],
        parent_report_id=FORMAL_PARENT,
        child_report_id=FORMAL_CHILD,
        trust_root=trust,
        installation_id=FORMAL_INSTALLATION,
        expected_host_trust_manifest_sha256=pin,
    )
    assert (
        runtime.validate_evo_child_materialization_admission
        is validate_evo_child_materialization_admission
    )

    source = json.loads(fixture["checkpoint"].read_text(encoding="utf-8"))
    core = {
        key: value
        for key, value in source.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    core["identity"] = {
        "job_id": JOB,
        "parent_report_id": FORMAL_PARENT,
        "child_report_id": FORMAL_CHILD,
        "expected_host_trust_manifest_sha256": pin,
    }
    core["artifacts"]["child_materialization"] = runtime._ref(
        child_materialization_admission_path(
            fixture["workspace"], FORMAL_CHILD
        )
    )
    argv = runtime._replace_argv_value(
        list(core["execution"]["argv"]), "--report-id", FORMAL_CHILD
    )
    argv = runtime._replace_argv_value(
        argv, "--factor-workspace", str(fixture["workspace"])
    )
    core["execution"]["argv"] = argv
    core["execution"]["argv_sha256"] = runtime.stable_json_hash(argv)
    core.pop("content_sha256", None)
    core["content_sha256"] = runtime.stable_json_hash(core)
    store = ensure_runtime_trust_store(
        trust, installation_id=FORMAL_INSTALLATION
    )
    checkpoint = store.sign("host_admission", core)
    checkpoint_path = fixture["state"] / "formal-ready.json"
    checkpoint_path.write_bytes(runtime._canonical_bytes(checkpoint))
    checkpoint_path.chmod(0o600)

    result = runtime.execute_evo_child_ready(
        checkpoint_path=checkpoint_path,
        state_root=fixture["state"],
        trust_root=trust,
        installation_id=FORMAL_INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["tree"],
        parent_report_id=FORMAL_PARENT,
        child_report_id=FORMAL_CHILD,
        expected_host_trust_manifest_sha256=pin,
        host_environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=60,
    )
    assert result["status"] == runtime.CHILD_RESUME_READY
    assert fixture["counter"].read_text(encoding="utf-8") == "1"


def test_execution_ready_replay_blocks_private_incident_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    evidence = fixture["workspace"] / "incident-evidence"
    evidence.mkdir()
    refs = []
    for name in ("source.csv", "panel.parquet", "metrics.json", "runner.py"):
        path = evidence / name
        path.write_text(name, encoding="utf-8")
        refs.append(path)
    payload = build_oos_exposure_incident(
        workspace_root=fixture["workspace"],
        report_id=CHILD,
        factor_id="RUNTIME_FACTOR",
        frozen_oos_start="2026-01-01",
        frozen_oos_end="2026-03-31",
        frozen_oos_release_token_sha256="a" * 64,
        exposed_overlap_start="2026-01-01",
        exposed_overlap_end="2026-01-31",
        exposed_row_count=1,
        exposed_period_count=1,
        source_path=refs[0],
        panel_path=refs[1],
        metrics_path=refs[2],
        runner_path=refs[3],
        incident_at="2026-08-13T09:00:00Z",
    )
    write_oos_exposure_incident_create_only(
        workspace_root=fixture["workspace"],
        payload=payload,
    )
    register_oos_exposure_incident_host_private(
        workspace_root=fixture["workspace"],
        report_id=CHILD,
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
    )
    oos_exposure_incident_path(fixture["workspace"], CHILD).unlink()
    with pytest.raises(runtime.EvoChildRuntimeError, match="private_registry_incident"):
        _execute(fixture)
    assert not fixture["counter"].exists()


def _phase_inflight(
    fixture: dict,
    execution: dict,
    *,
    phase: str,
    expected_paths: tuple[str, ...],
) -> dict:
    return runtime.materialize_evo_child_phase_inflight(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=execution["execution_receipt_path"],
        workspace_root=fixture["workspace"],
        phase=phase,
        expected_workspace_paths=expected_paths,
        operation_binding={
            "operation_kind": f"test_{phase.lower()}",
            "trusted_proof_sha256": execution["proof_sha256"],
        },
        require_pristine_baseline=True,
    )


def test_host_observed_child_execution_maps_pause_to_signed_step4_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    result = _execute(fixture)
    assert result["status"] == runtime.CHILD_RESUME_READY
    assert result["resume_start_step"] == "4"
    assert fixture["counter"].read_text() == "1"
    assert json.loads(fixture["argv_log"].read_text()) == {
        "report_id": CHILD,
        "start_step": "3b",
    }
    receipt = json.loads(Path(result["execution_receipt_path"]).read_text())
    store = ensure_runtime_trust_store(
        fixture["trust"], installation_id=INSTALLATION
    )
    assert store.verify(receipt, expected_issuer="host_admission") == []
    assert receipt["authority"]["parent_execution_allowed"] is False
    assert receipt["authority"]["allowed_child_start_step"] == "4"


def test_crash_retry_replays_receipt_without_reexecuting_or_reauthoring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    first = _execute(fixture)
    second = _execute(fixture)
    assert first["execution_receipt_sha256"] == second["execution_receipt_sha256"]
    assert second["idempotent_replay"] is True
    assert fixture["counter"].read_text() == "1"


def test_next_resume_targets_child_and_signed_step_not_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _execute(fixture)
    resumed = _execute(fixture, resume=True)
    assert resumed["status"] == runtime.CHILD_RESUME_READY
    assert fixture["counter"].read_text() == "2"
    assert json.loads(fixture["argv_log"].read_text()) == {
        "report_id": CHILD,
        "start_step": "4",
    }
    validated = runtime.validate_evo_child_execution_state(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=resumed["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )
    assert validated["child_report_id"] == CHILD
    assert validated["resume_start_step"] == "4"


def test_resume_uses_signed_execution_baseline_not_obsolete_step3b_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    calls = 0

    def seed_admission(**_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("obsolete Step3B seed admission was replayed")
        return {"verdict": "PASS"}, []

    monkeypatch.setattr(
        runtime,
        "validate_evo_child_materialization_admission",
        seed_admission,
    )
    first = _execute(fixture)
    assert first["status"] == runtime.CHILD_RESUME_READY
    second = _execute(fixture, resume=True)
    assert second["status"] == runtime.CHILD_RESUME_READY
    assert calls == 1


def test_signed_child_nqc_terminal_checkpoint_closes_without_wrapper_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    (fixture["tree"] / "terminal_mode").write_text("1", encoding="utf-8")
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    paused = _execute(fixture)
    assert paused["status"] == runtime.CHILD_RESUME_READY
    assert paused["resume_start_step"] == "6"
    closure = (
        fixture["workspace"]
        / "objects/evo_v2"
        / CHILD
        / "post_oos_terminal_closure.json"
    )
    _write(closure, b'{"terminal":"host-signed-fixture"}\n')
    assessment_payload = {
        "report_id": CHILD,
        "pause_outcome": "awaiting_evo_v2_non_revision_terminal_closure",
        "status": runtime.PROGRESS_TERMINAL_CHECKPOINT_READY,
        "start_step": None,
        "terminal_factor_verdict": "REJECT",
        "terminal_decision": "reject",
        "terminal_closure_path": closure.relative_to(
            fixture["workspace"]
        ).as_posix(),
        "terminal_closure_sha256": runtime._sha256(closure),
        "reason": "signed_non_revision_terminal_closure_verified",
    }
    assessment = SimpleNamespace(
        **assessment_payload,
        to_dict=lambda: dict(assessment_payload),
    )
    monkeypatch.setattr(
        runtime,
        "assess_evo_v2_external_resume",
        lambda **_kwargs: assessment,
    )
    terminal = runtime.materialize_evo_child_terminal_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=paused["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )
    assert terminal["status"] == runtime.CHILD_TERMINAL
    assert terminal["scientific_factor_verdict"] == "REJECT"
    assert terminal["terminal_checkpoint"] is True
    assert fixture["counter"].read_text() == "1"

    closure.write_text('{"terminal":"tampered"}\n', encoding="utf-8")
    with pytest.raises(runtime.EvoChildRuntimeError, match="terminal_closure"):
        runtime.validate_evo_child_terminal_checkpoint(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            terminal_receipt_path=terminal["execution_receipt_path"],
            workspace_root=fixture["workspace"],
        )


def test_service_step6_resume_loads_signed_baseline_before_semantic_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    paused = _execute(fixture)
    assert paused["resume_start_step"] == "6"
    lifecycle = (
        fixture["workspace"] / "objects/evo_v2" / CHILD / "lifecycle.json"
    )
    _write(lifecycle, b'{"host_signed_delta":"pending_semantic_rebaseline"}\n')
    service = SimpleNamespace(
        config=SimpleNamespace(
            state_root=fixture["state"],
            installation_id=INSTALLATION,
        )
    )
    job = SimpleNamespace(
        job_id=JOB,
        report_id=PARENT,
        workspace_path=str(fixture["workspace"]),
        result={
            "evo_v2_child_runtime": {
                "execution": {
                    "child_report_id": CHILD,
                    "execution_receipt_path": paused["execution_receipt_path"],
                }
            }
        },
    )
    baseline = ResearchRunService._validate_evo_v2_child_runtime_resume(
        service, job
    )
    assert baseline["status"] == runtime.CHILD_RESUME_READY
    assert baseline["resume_start_step"] == "6"
    # Exact tree replay still rejects the same unadmitted delta; only the
    # subsequent qualification/phase controller may admit it.
    with pytest.raises(runtime.EvoChildRuntimeError):
        runtime.validate_evo_child_execution_state(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            execution_receipt_path=paused["execution_receipt_path"],
            workspace_root=fixture["workspace"],
        )


def test_service_private_receipt_chain_wins_if_job_store_update_crashed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    first = _execute(fixture)
    second = _execute(fixture, resume=True)
    assert first["execution_receipt_path"] != second["execution_receipt_path"]
    service = SimpleNamespace(
        config=SimpleNamespace(
            state_root=fixture["state"],
            installation_id=INSTALLATION,
        )
    )
    # Simulate durable receipt write followed by a Console DB crash: the job
    # row still points at attempt 1, while Host-private state contains attempt 2.
    job = SimpleNamespace(
        job_id=JOB,
        report_id=PARENT,
        workspace_path=str(fixture["workspace"]),
        result={
            "evo_v2_child_runtime": {
                "execution": {
                    "child_report_id": CHILD,
                    "execution_receipt_path": first["execution_receipt_path"],
                }
            }
        },
    )
    recovered = ResearchRunService._validate_evo_v2_child_runtime_resume(
        service, job
    )
    assert recovered["execution_receipt_path"] == second[
        "execution_receipt_path"
    ]
    assert recovered["execution_receipt_sha256"] == second[
        "execution_receipt_sha256"
    ]


@pytest.mark.parametrize("attack", ["tamper", "delete", "add"])
def test_resume_evidence_tree_rejects_workspace_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    result = _execute(fixture)
    proof = Path(result["proof_path"])
    if attack == "tamper":
        proof.write_text("{}", encoding="utf-8")
    elif attack == "delete":
        proof.unlink()
    else:
        extra = fixture["workspace"] / "objects/untrusted.json"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("{}", encoding="utf-8")
    with pytest.raises(runtime.EvoChildRuntimeError):
        runtime.validate_evo_child_execution_state(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            execution_receipt_path=result["execution_receipt_path"],
            workspace_root=fixture["workspace"],
        )


def test_checkpoint_or_bound_artifact_tamper_blocks_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    payload = json.loads(fixture["checkpoint"].read_text())
    payload["execution"]["argv"][2] = PARENT
    fixture["checkpoint"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["checkpoint"].chmod(0o600)
    with pytest.raises(runtime.EvoChildRuntimeError, match="signature"):
        _execute(fixture)
    assert not fixture["counter"].exists()


class _ReadyQualificationAssessment:
    status = runtime.PROGRESS_HOST_CHECKPOINT_READY
    start_step = "6"
    reason = "signed_no_qualified_contradiction_transition_verified"
    current_lifecycle_state = "NO_QUALIFIED_CONTRADICTION"

    def to_dict(self) -> dict:
        return {
            "report_id": CHILD,
            "status": self.status,
            "start_step": self.start_step,
            "reason": self.reason,
            "current_lifecycle_state": self.current_lifecycle_state,
        }


def _qualification_ready(
    fixture: dict,
    monkeypatch: pytest.MonkeyPatch,
    execution: dict,
) -> dict:
    lifecycle = (
        fixture["workspace"]
        / "objects"
        / "evo_v2"
        / CHILD
        / "lifecycle.json"
    )
    _write(lifecycle, b'{"current_state":"NO_QUALIFIED_CONTRADICTION"}\n')
    monkeypatch.setattr(
        runtime,
        "_validate_child_is_checkpoint",
        lambda **_kwargs: {
            "contract_version": "test",
            "status": "PASS",
            "report_id": CHILD,
            "uses_oos": False,
        },
    )
    monkeypatch.setattr(
        runtime,
        "assess_evo_v2_external_resume",
        lambda **_kwargs: _ReadyQualificationAssessment(),
    )
    return runtime.materialize_evo_child_qualification_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=execution["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )


def test_step6_resume_requires_signed_closed_qualification_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    first = _execute(fixture)
    assert first["resume_start_step"] == "6"
    with pytest.raises(
        runtime.EvoChildRuntimeError,
        match="child_step6_host_qualification_required",
    ):
        _execute(fixture, resume=True)
    assert fixture["counter"].read_text() == "1"

    qualification = _qualification_ready(fixture, monkeypatch, first)
    assert qualification["status"] == runtime.CHILD_QUALIFICATION_READY
    resumed = runtime.execute_evo_child_ready(
        checkpoint_path=fixture["checkpoint"],
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["tree"],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        host_environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=60,
        resume=True,
        qualification_checkpoint_path=qualification[
            "qualification_receipt_path"
        ],
    )
    assert resumed["status"] == runtime.CHILD_RESUME_READY
    assert json.loads(fixture["argv_log"].read_text())["start_step"] == "6"


def test_qualification_rebaseline_rejects_added_workspace_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    first = _execute(fixture)
    qualification = _qualification_ready(fixture, monkeypatch, first)
    extra = fixture["workspace"] / "objects" / "post_qualification_tamper.json"
    _write(extra, b"{}\n")
    with pytest.raises(runtime.EvoChildRuntimeError, match="qualification_evidence_tree"):
        runtime.validate_evo_child_qualification_checkpoint(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            qualification_receipt_path=qualification[
                "qualification_receipt_path"
            ],
            workspace_root=fixture["workspace"],
        )


def test_partial_oos_recovery_precedes_stale_proof_and_is_resumable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    first = _execute(fixture)
    assert first["resume_start_step"] == "4"
    monkeypatch.setattr(
        runtime,
        "web_factor_proof_oos_recovery_state",
        lambda *_args: {
            "recovery_required": True,
            "allowed_execution": "FINALIZER_ONLY",
        },
    )
    monkeypatch.setattr(
        runtime,
        "_run_owned_process_group",
        lambda argv, **_kwargs: runtime.subprocess.CompletedProcess(
            argv, 9, stdout="", stderr="crash"
        ),
    )
    recovery = _execute(fixture, resume=True)
    assert recovery["status"] == runtime.CHILD_RECOVERY_READY
    # A partial-OOS classifier may retain a fresh proof for forensics, but the
    # receipt authority remains finalizer-only and does not trust that proof as
    # a completed execution.
    validated = runtime.validate_evo_child_execution_state(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=recovery["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )
    assert validated["status"] == runtime.CHILD_RECOVERY_READY


def test_protocol_fail_does_not_issue_scientific_reject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    ultimate = fixture["tree"] / "fake_ultimate.py"
    source = ultimate.read_text(encoding="utf-8")
    ultimate.write_text(
        source.replace("'status':'PAUSED'", "'status':'FAIL'"),
        encoding="utf-8",
    )
    payload = json.loads(fixture["checkpoint"].read_text(encoding="utf-8"))
    # Reissue the private ready checkpoint because its code ref is immutable.
    payload["artifacts"]["ultimate_script"] = runtime._ref(ultimate)
    payload["execution"]["ultimate_script_sha256"] = runtime._sha256(ultimate)
    unsigned = {
        key: value
        for key, value in payload.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    unsigned.pop("content_sha256")
    unsigned["content_sha256"] = runtime.stable_json_hash(unsigned)
    store = ensure_runtime_trust_store(
        fixture["trust"], installation_id=INSTALLATION
    )
    replacement = store.sign("host_admission", unsigned)
    fixture["checkpoint"].write_bytes(runtime._canonical_bytes(replacement))
    result = _execute(fixture)
    assert result["status"] == runtime.CHILD_TERMINAL
    receipt = json.loads(Path(result["execution_receipt_path"]).read_text())
    assert receipt["authority"]["factor_verdict"] == "NOT_ISSUED"
    assert receipt["authority"]["scientific_verdict_issued"] is False


def test_child_council_phase_checkpoint_closes_delta_and_rebaselines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    first = _execute(fixture)
    result_path = (
        fixture["workspace"]
        / "objects/research_iteration_master/revision_council"
        / CHILD
        / "agent_results/agent_result.json"
    )
    relative = result_path.relative_to(fixture["workspace"]).as_posix()
    inflight = _phase_inflight(
        fixture,
        first,
        phase="COUNCIL_RESULTS",
        expected_paths=(relative,),
    )
    _write(result_path, b'{"status":"final"}\n')
    checkpoint = runtime.materialize_evo_child_phase_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=first["execution_receipt_path"],
        workspace_root=fixture["workspace"],
        phase="COUNCIL_RESULTS",
        allowed_workspace_delta={relative: runtime._sha256(result_path)},
        phase_evidence={"council_result": runtime._ref(result_path)},
        phase_inflight_path=inflight["phase_inflight_path"],
    )
    assert checkpoint["status"] == runtime.CHILD_PHASE_READY
    resumed = runtime.execute_evo_child_ready(
        checkpoint_path=fixture["checkpoint"],
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["tree"],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        host_environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=60,
        resume=True,
        phase_checkpoint_path=checkpoint["phase_receipt_path"],
    )
    assert resumed["status"] == runtime.CHILD_RESUME_READY
    assert json.loads(fixture["argv_log"].read_text())["start_step"] == "6"


def test_child_phase_checkpoint_rejects_unlisted_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    first = _execute(fixture)
    allowed = fixture["workspace"] / "objects/allowed.json"
    unlisted = fixture["workspace"] / "objects/unlisted.json"
    relative = allowed.relative_to(fixture["workspace"]).as_posix()
    inflight = _phase_inflight(
        fixture,
        first,
        phase="COUNCIL_RESULTS",
        expected_paths=(relative,),
    )
    _write(allowed, b"{}\n")
    _write(unlisted, b"{}\n")
    with pytest.raises(runtime.EvoChildRuntimeError, match="child_phase_workspace_delta"):
        runtime.materialize_evo_child_phase_checkpoint(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            execution_receipt_path=first["execution_receipt_path"],
            workspace_root=fixture["workspace"],
            phase="COUNCIL_RESULTS",
            allowed_workspace_delta={
                relative: runtime._sha256(allowed)
            },
            phase_evidence={"allowed": runtime._ref(allowed)},
            phase_inflight_path=inflight["phase_inflight_path"],
        )


def test_qualified_child_survives_multiple_step6_phase_restarts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    first = _execute(fixture)
    qualification = _qualification_ready(fixture, monkeypatch, first)

    def resume_with(admission: dict, *, kind: str) -> dict:
        kwargs = {
            "qualification_checkpoint_path": admission.get(
                "qualification_receipt_path"
            ),
            "phase_checkpoint_path": admission.get("phase_receipt_path"),
        }
        result = runtime.execute_evo_child_ready(
            checkpoint_path=fixture["checkpoint"],
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            workspace_root=fixture["workspace"],
            worktree=fixture["tree"],
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            host_environment={"PATH": "/usr/bin:/bin"},
            timeout_seconds=60,
            resume=True,
            **kwargs,
        )
        assert result["status"] == runtime.CHILD_RESUME_READY, kind
        return result

    prior = resume_with(qualification, kind="qualification")
    for phase, name in (
        ("COUNCIL_RESULTS", "council_result.json"),
        ("ROOT_SYNTHESIS", "root_synthesis.json"),
        ("HOST_COUNCIL_OUTCOME", "host_outcome.json"),
    ):
        artifact = fixture["workspace"] / "objects" / name
        relative = artifact.relative_to(fixture["workspace"]).as_posix()
        inflight = _phase_inflight(
            fixture,
            prior,
            phase=phase,
            expected_paths=(relative,),
        )
        _write(artifact, json.dumps({"phase": phase}).encode() + b"\n")
        admission = runtime.materialize_evo_child_phase_checkpoint(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            execution_receipt_path=prior["execution_receipt_path"],
            workspace_root=fixture["workspace"],
            phase=phase,
            allowed_workspace_delta={relative: runtime._sha256(artifact)},
            phase_evidence={phase.lower(): runtime._ref(artifact)},
            phase_inflight_path=inflight["phase_inflight_path"],
        )
        prior = resume_with(admission, kind=phase)
    assert fixture["counter"].read_text() == "5"


@pytest.mark.parametrize(
    "phase",
    ["COUNCIL_RESULTS", "ROOT_SYNTHESIS", "HOST_COUNCIL_OUTCOME"],
)
def test_signed_phase_inflight_recovers_output_boundary_and_replays_stale_job_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    prior = _execute(fixture)
    artifact = fixture["workspace"] / "objects" / f"{phase.lower()}.json"
    relative = artifact.relative_to(fixture["workspace"]).as_posix()
    inflight = _phase_inflight(
        fixture,
        prior,
        phase=phase,
        expected_paths=(relative,),
    )

    # Canonical output exists, but the Host phase receipt and Console job row do
    # not: this is the exact kill boundary the durable inflight must classify.
    _write(artifact, json.dumps({"phase": phase}).encode() + b"\n")
    pending = runtime.load_pending_evo_child_phase_inflight(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=prior["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )
    assert pending is not None
    assert pending["phase_attempt_id"] == inflight["phase_attempt_id"]
    assert pending["phase_receipt_exists"] is False

    checkpoint = runtime.materialize_evo_child_phase_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=prior["execution_receipt_path"],
        workspace_root=fixture["workspace"],
        phase=phase,
        allowed_workspace_delta={relative: runtime._sha256(artifact)},
        phase_evidence={phase.lower(): runtime._ref(artifact)},
        phase_inflight_path=pending["phase_inflight_path"],
    )
    assert checkpoint["status"] == runtime.CHILD_PHASE_READY

    # Simulate a second crash after the private phase receipt was durable but
    # before the Console job row was updated. Replaying the same signed inputs
    # must return the identical receipt and must not create a new attempt.
    stale = runtime.load_pending_evo_child_phase_inflight(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=prior["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )
    assert stale is not None
    assert stale["phase_receipt_exists"] is True
    replayed = runtime.validate_evo_child_phase_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        phase_receipt_path=stale["phase_receipt_candidate_path"],
        workspace_root=fixture["workspace"],
    )
    assert replayed["phase_receipt_path"] == checkpoint["phase_receipt_path"]
    assert replayed["receipt"]["receipt_id"] == checkpoint["receipt"]["receipt_id"]


def test_service_resume_recognizes_only_signed_phase_inflight_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    prior = _execute(fixture)
    artifact = fixture["workspace"] / "objects/council_result.json"
    relative = artifact.relative_to(fixture["workspace"]).as_posix()
    inflight = _phase_inflight(
        fixture,
        prior,
        phase="COUNCIL_RESULTS",
        expected_paths=(relative,),
    )
    _write(artifact, b'{"status":"final"}\n')
    service = SimpleNamespace(
        config=SimpleNamespace(
            state_root=fixture["state"], installation_id=INSTALLATION
        )
    )
    job = SimpleNamespace(
        job_id=JOB,
        report_id=PARENT,
        workspace_path=str(fixture["workspace"]),
        result={
            "evo_v2_child_runtime": {
                "execution": {
                    "child_report_id": CHILD,
                    "parent_report_id": PARENT,
                    "execution_receipt_path": prior["execution_receipt_path"],
                }
            }
        },
    )
    admitted = ResearchRunService._validate_evo_v2_child_runtime_resume(service, job)
    assert admitted["phase_recovery"]["phase"] == "COUNCIL_RESULTS"
    assert admitted["phase_recovery"]["phase_inflight_path"] == inflight[
        "phase_inflight_path"
    ]

    # A same-turn mutation outside the signed output set is never laundered as
    # a semantic phase delta.
    _write(fixture["workspace"] / "objects/unlisted.json", b"{}\n")
    with pytest.raises(runtime.EvoChildRuntimeError, match="phase_inflight_workspace_delta"):
        ResearchRunService._validate_evo_v2_child_runtime_resume(service, job)


def test_historical_phase_replay_allows_descendant_delta_but_not_receipt_evidence_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    prior = _execute(fixture)
    artifact = fixture["workspace"] / "objects/council_result.json"
    relative = artifact.relative_to(fixture["workspace"]).as_posix()
    inflight = _phase_inflight(
        fixture,
        prior,
        phase="COUNCIL_RESULTS",
        expected_paths=(relative,),
    )
    _write(artifact, b'{"status":"final"}\n')
    checkpoint = runtime.materialize_evo_child_phase_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=prior["execution_receipt_path"],
        workspace_root=fixture["workspace"],
        phase="COUNCIL_RESULTS",
        allowed_workspace_delta={relative: runtime._sha256(artifact)},
        phase_evidence={"council_result": runtime._ref(artifact)},
        phase_inflight_path=inflight["phase_inflight_path"],
    )
    descendant = fixture["workspace"] / "objects/descendant_state.json"
    _write(descendant, b"{}\n")
    with pytest.raises(runtime.EvoChildRuntimeError, match="child_phase_"):
        runtime.validate_evo_child_phase_checkpoint(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            phase_receipt_path=checkpoint["phase_receipt_path"],
            workspace_root=fixture["workspace"],
        )
    historical = runtime.validate_evo_child_phase_checkpoint(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        phase_receipt_path=checkpoint["phase_receipt_path"],
        workspace_root=fixture["workspace"],
        verify_workspace_exact=False,
    )
    assert historical["receipt"]["receipt_id"] == checkpoint["receipt"]["receipt_id"]
    artifact.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(runtime.EvoChildRuntimeError, match="child_phase_evidence"):
        runtime.validate_evo_child_phase_checkpoint(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=fixture["pin"],
            phase_receipt_path=checkpoint["phase_receipt_path"],
            workspace_root=fixture["workspace"],
            verify_workspace_exact=False,
        )


def test_council_output_boundary_recovers_private_receipt_without_agent_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    prior = _execute(fixture)
    result_relative = (
        f"objects/research_iteration_master/revision_council/{CHILD}/"
        f"agent_results/agent_result__{CHILD}__economic_skeptic.json"
    )
    task = run_service.CouncilIngressTask(
        task_id="economic_skeptic",
        agent_role="economic_skeptic",
        expected_agent_identifier="console_council_economic_skeptic",
        task_packet_path=(
            f"objects/research_iteration_master/revision_council/{CHILD}/"
            f"agent_tasks/task__{CHILD}__economic_skeptic.json"
        ),
        task_packet_sha256="b" * 64,
        expected_result_path=result_relative,
    )
    prompt_relative = "identity/web_agent_resume.md"
    operation_binding = {
        "operation_kind": "isolated_council_ingress",
        "trusted_proof_sha256": prior["proof_sha256"],
        "tasks": [
            {
                "task_id": task.task_id,
                "agent_role": task.agent_role,
                "expected_agent_identifier": task.expected_agent_identifier,
                "task_packet_path": task.task_packet_path,
                "task_packet_sha256": task.task_packet_sha256,
                "expected_result_path": task.expected_result_path,
            }
        ],
    }
    inflight = runtime.materialize_evo_child_phase_inflight(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=prior["execution_receipt_path"],
        workspace_root=fixture["workspace"],
        phase="COUNCIL_RESULTS",
        expected_workspace_paths=(prompt_relative, result_relative),
        operation_binding=operation_binding,
        require_pristine_baseline=True,
    )
    result_path = fixture["workspace"] / result_relative
    _write(result_path, b'{"status":"final"}\n')
    _write(fixture["workspace"] / prompt_relative, b"resume\n")
    agent_id = "agent-council-recovery"
    session_key = "session-council-recovery"
    private_receipt = fixture["state"] / "jobs" / JOB / "council_ingress_crash.json"
    _write(
        private_receipt,
        json.dumps(
            {
                "version": "factorforge_console_council_ingress_v1",
                "job_id": JOB,
                "factor_id": "factor-child",
                "research_id": "research-child",
                "report_id": CHILD,
                "agent_id": agent_id,
                "session_key_sha256": hashlib.sha256(
                    session_key.encode("utf-8")
                ).hexdigest(),
                "resume": True,
                "research_base_commit": "base-commit",
                "engine_commit": "engine-commit",
                "returncode": 0,
                "error_code": "",
                "runs": [
                    {
                        "task_id": task.task_id,
                        "agent_role": task.agent_role,
                        "expected_agent_identifier": task.expected_agent_identifier,
                        "expected_result_path": task.expected_result_path,
                        "returncode": 0,
                        "error_code": "",
                        "imported_result_sha256": runtime._sha256(result_path),
                    }
                ],
            },
            sort_keys=True,
        ).encode()
        + b"\n",
    )

    class NoRerunAdapter:
        def run_council_ingress(self, *_args, **_kwargs):
            raise AssertionError("Council Agent must not rerun after exact output import")

    service = SimpleNamespace(
        config=SimpleNamespace(
            state_root=fixture["state"], installation_id=INSTALLATION
        ),
        agent_adapter=NoRerunAdapter(),
        _expected_base_commit="engine-commit",
        _validate_council_ingress_receipt=lambda *_args, **_kwargs: SimpleNamespace(
            receipt_id=private_receipt.relative_to(fixture["state"]).as_posix(),
            receipt_sha256=runtime._sha256(private_receipt),
        ),
    )
    monkeypatch.setattr(run_service, "EVO_V2_EXTERNAL_PAUSES", frozenset())
    monkeypatch.setattr(
        run_service,
        "_classify_resume_route",
        lambda *_args, **_kwargs: SimpleNamespace(
            kind=run_service.RESUME_KIND_COUNCIL_INGRESS
        ),
    )
    monkeypatch.setattr(
        run_service,
        "_trusted_council_ingress_tasks",
        lambda *_args, **_kwargs: (task,),
    )
    child_plan_replays: list[dict[str, object]] = []

    def replay_child_plan(**kwargs):
        child_plan_replays.append(dict(kwargs))
        return {
            "raw_plan": {
                "identity": {
                    "factor_id": "factor-child",
                    "research_id": "research-child",
                }
            }
        }

    monkeypatch.setattr(
        run_service,
        "validate_and_resolve_evo_child_web_research_plan",
        replay_child_plan,
    )
    child_job = SimpleNamespace(
        job_id=JOB,
        report_id=PARENT,
        factor_id="factor-parent",
        research_id="research-parent",
        base_commit="base-commit",
        agent_id=agent_id,
        agent_session_key=session_key,
    )
    recovered = ResearchRunService._evo_child_phase_checkpoint(
        service,
        child_job,
        worktree=fixture["tree"],
        workspace=fixture["workspace"],
        child_report_id=CHILD,
        prior_execution=prior,
        trust_root=fixture["trust"],
        expected_host_pin=fixture["pin"],
        parent_report_id=PARENT,
    )
    assert recovered["status"] == runtime.CHILD_PHASE_READY
    assert recovered["phase"] == "COUNCIL_RESULTS"
    assert recovered["phase_inflight_path"] == inflight["phase_inflight_path"]
    assert child_plan_replays
    assert child_plan_replays[0]["incident_trust_root"] == fixture["trust"]
    assert child_plan_replays[0]["incident_installation_id"] == INSTALLATION

    # A second call models a private phase receipt that beat the Console job-row
    # update. It must replay immediately and still never invoke the Agent.
    replayed = ResearchRunService._evo_child_phase_checkpoint(
        service,
        child_job,
        worktree=fixture["tree"],
        workspace=fixture["workspace"],
        child_report_id=CHILD,
        prior_execution=prior,
        trust_root=fixture["trust"],
        expected_host_pin=fixture["pin"],
        parent_report_id=PARENT,
    )
    assert replayed["receipt"]["receipt_id"] == recovered["receipt"]["receipt_id"]


def test_root_synthesis_output_boundary_recovers_private_receipt_without_agent_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "required_web_resume_start_step", lambda *_args: "6")
    prior = _execute(fixture)
    task_relative = f"identity/web_pre_oos_root_synthesis_task__{CHILD}.json"
    output_relative = run_service._pre_oos_root_synthesis_relative(CHILD)
    operation_binding = {
        "operation_kind": "isolated_pre_oos_root_synthesis",
        "trusted_proof_sha256": prior["proof_sha256"],
        "task_packet_path": task_relative,
        "expected_output_path": output_relative,
    }
    inflight = runtime.materialize_evo_child_phase_inflight(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=prior["execution_receipt_path"],
        workspace_root=fixture["workspace"],
        phase="ROOT_SYNTHESIS",
        expected_workspace_paths=(task_relative, output_relative),
        operation_binding=operation_binding,
        require_pristine_baseline=True,
    )
    proof_relative = Path(prior["proof_path"]).relative_to(
        fixture["workspace"]
    ).as_posix()
    task_payload = {
        "version": run_service.PRE_OOS_ROOT_SYNTHESIS_TASK_VERSION,
        "attempt_id": inflight["phase_attempt_id"],
        "identity": {
            "job_id": JOB,
            "factor_id": "factor-child",
            "research_id": "research-child",
            "report_id": CHILD,
        },
        "read_only_inputs": [
            {"path": proof_relative, "sha256": prior["proof_sha256"]}
        ],
        "required_output": {"path": output_relative},
    }
    task_payload["content_sha256"] = runtime.stable_json_hash(task_payload)
    task_path = fixture["workspace"] / task_relative
    _write(task_path, runtime._canonical_bytes(task_payload))
    output_path = fixture["workspace"] / output_relative
    _write(output_path, b'{"decision":"continue"}\n')
    agent_id = (
        f"ff-root-{JOB.removeprefix('job_')[:10]}-"
        f"{inflight['phase_attempt_id'][-8:]}"
    )
    session_key = f"agent:{agent_id}:{JOB}:{inflight['phase_attempt_id']}"
    private_receipt = (
        fixture["state"] / "jobs" / JOB / "pre_oos_root_synthesis_crash.json"
    )
    _write(
        private_receipt,
        json.dumps(
            {
                "version": "factorforge_console_pre_oos_root_synthesis_run_v1",
                "job_id": JOB,
                "factor_id": "factor-child",
                "research_id": "research-child",
                "report_id": CHILD,
                "agent_id": agent_id,
                "session_key_sha256": hashlib.sha256(
                    session_key.encode("utf-8")
                ).hexdigest(),
                "attempt_id": inflight["phase_attempt_id"],
                "trusted_proof_sha256": prior["proof_sha256"],
                "task_packet_sha256": runtime._sha256(task_path),
                "expected_output_path": output_relative,
                "imported_output_sha256": runtime._sha256(output_path),
                "returncode": 0,
                "error_code": "",
            },
            sort_keys=True,
        ).encode()
        + b"\n",
    )

    class NoRerunAdapter:
        def run_pre_oos_root_synthesis(self, *_args, **_kwargs):
            raise AssertionError("root-synthesis Agent must not rerun after exact output")

    service = SimpleNamespace(
        config=SimpleNamespace(
            state_root=fixture["state"], installation_id=INSTALLATION
        ),
        agent_adapter=NoRerunAdapter(),
        _expected_base_commit="engine-commit",
        _validate_pre_oos_root_synthesis_receipt=(
            lambda *_args, **_kwargs: SimpleNamespace(
                receipt_id=private_receipt.relative_to(fixture["state"]).as_posix(),
                receipt_sha256=runtime._sha256(private_receipt),
            )
        ),
    )
    monkeypatch.setattr(run_service, "EVO_V2_EXTERNAL_PAUSES", frozenset())
    monkeypatch.setattr(
        run_service,
        "_classify_resume_route",
        lambda *_args, **_kwargs: SimpleNamespace(
            kind=run_service.RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS
        ),
    )
    monkeypatch.setattr(
        run_service,
        "validate_and_resolve_evo_child_web_research_plan",
        lambda **_kwargs: {
            "raw_plan": {
                "identity": {
                    "factor_id": "factor-child",
                    "research_id": "research-child",
                }
            }
        },
    )
    child_job = SimpleNamespace(
        job_id=JOB,
        report_id=PARENT,
        factor_id="factor-parent",
        research_id="research-parent",
        base_commit="base-commit",
        agent_id="unused",
        agent_session_key="unused",
    )
    recovered = ResearchRunService._evo_child_phase_checkpoint(
        service,
        child_job,
        worktree=fixture["tree"],
        workspace=fixture["workspace"],
        child_report_id=CHILD,
        prior_execution=prior,
        trust_root=fixture["trust"],
        expected_host_pin=fixture["pin"],
        parent_report_id=PARENT,
    )
    assert recovered["status"] == runtime.CHILD_PHASE_READY
    assert recovered["phase"] == "ROOT_SYNTHESIS"
    assert recovered["phase_inflight_path"] == inflight["phase_inflight_path"]
    replayed = ResearchRunService._evo_child_phase_checkpoint(
        service,
        child_job,
        worktree=fixture["tree"],
        workspace=fixture["workspace"],
        child_report_id=CHILD,
        prior_execution=prior,
        trust_root=fixture["trust"],
        expected_host_pin=fixture["pin"],
        parent_report_id=PARENT,
    )
    assert replayed["receipt"]["receipt_id"] == recovered["receipt"]["receipt_id"]


def test_two_level_recursive_lineage_is_root_to_active_and_every_edge_is_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_1 = "ROOT__EVO_CHILD_001"
    child_2 = f"{child_1}__EVO_CHILD_001"
    child_3 = f"{child_2}__EVO_CHILD_001"
    receipts: dict[str, tuple[Path, str, str, str]] = {}
    for index, (parent, child) in enumerate(((child_1, child_2), (child_2, child_3)), 1):
        path = (
            tmp_path
            / "jobs"
            / JOB
            / "evo-child-runtime"
            / parent
            / f"handoff_{index}.json"
        )
        _write(path, json.dumps({"parent": parent, "child": child}).encode() + b"\n")
        receipts[parent] = (
            path,
            runtime._sha256(path),
            f"receipt_{index}",
            child,
        )

    replayed: list[str] = []

    def replay(**kwargs):
        parent = kwargs["child_report_id"]
        path, digest, receipt_id, child = receipts[parent]
        assert kwargs["phase_receipt_path"] == path
        assert kwargs["verify_workspace_exact"] is False
        replayed.append(parent)
        return {
            "phase": "HOST_CHILD_HANDOFF",
            "phase_receipt_sha256": digest,
            "receipt": {
                "receipt_id": receipt_id,
                "phase_context": {
                    "external_resume_assessment": {
                        "report_id": parent,
                        "child_report_id": child,
                    }
                },
            },
        }

    monkeypatch.setattr(run_service, "validate_evo_child_phase_checkpoint", replay)
    edges = [
        {
            "root_report_id": "ROOT",
            "phase_owner_parent_report_id": "ROOT",
            "parent_report_id": child_1,
            "child_report_id": child_2,
            "parent_phase_receipt": {
                "path": str(receipts[child_1][0]),
                "sha256": receipts[child_1][1],
                "receipt_id": receipts[child_1][2],
            },
        },
        {
            "root_report_id": "ROOT",
            "phase_owner_parent_report_id": child_1,
            "parent_report_id": child_2,
            "child_report_id": child_3,
            "parent_phase_receipt": {
                "path": str(receipts[child_2][0]),
                "sha256": receipts[child_2][1],
                "receipt_id": receipts[child_2][2],
            },
        },
    ]
    deepest_lineage = run_service._extend_evo_child_lineage(
        root_report_id="ROOT",
        phase_owner_parent_report_id=child_1,
        parent_report_id=child_2,
        child_report_id=child_3,
        phase_checkpoint={
            "status": runtime.CHILD_PHASE_READY,
            "phase": "HOST_CHILD_HANDOFF",
            "phase_receipt_path": str(receipts[child_2][0]),
            "phase_receipt_sha256": receipts[child_2][1],
            "receipt": {"receipt_id": receipts[child_2][2]},
        },
        descendant_runtime={},
    )
    lineage = run_service._extend_evo_child_lineage(
        root_report_id="ROOT",
        phase_owner_parent_report_id="ROOT",
        parent_report_id=child_1,
        child_report_id=child_2,
        phase_checkpoint={
            "status": runtime.CHILD_PHASE_READY,
            "phase": "HOST_CHILD_HANDOFF",
            "phase_receipt_path": str(receipts[child_1][0]),
            "phase_receipt_sha256": receipts[child_1][1],
            "receipt": {"receipt_id": receipts[child_1][2]},
        },
        descendant_runtime={"lineage": deepest_lineage},
    )
    assert lineage["parent_report_id"] == child_2
    assert lineage["child_report_id"] == child_3
    assert lineage["ancestry"] == edges
    normalized = run_service._validate_evo_child_active_lineage(
        lineage=lineage,
        signed_execution={"parent_report_id": child_2, "child_report_id": child_3},
        trusted_parent_checkpoint={
            "parent_phase_receipt_path": str(receipts[child_2][0]),
            "parent_phase_receipt_sha256": receipts[child_2][1],
            "parent_phase_receipt_id": receipts[child_2][2],
        },
        state_root=tmp_path,
        trust_root=tmp_path,
        installation_id=INSTALLATION,
        job_id=JOB,
        expected_host_pin="a" * 64,
        workspace_root=tmp_path,
        replay_phase_receipts=True,
    )
    assert replayed == [child_1, child_2]
    assert [edge["child_report_id"] for edge in normalized["ancestry"]] == [
        child_2,
        child_3,
    ]

    with pytest.raises(RuntimeError, match="lineage identity"):
        run_service._validate_evo_child_active_lineage(
            lineage=lineage,
            signed_execution={"parent_report_id": "ROOT", "child_report_id": child_3},
            trusted_parent_checkpoint={
                "parent_phase_receipt_path": str(receipts[child_2][0]),
                "parent_phase_receipt_sha256": receipts[child_2][1],
                "parent_phase_receipt_id": receipts[child_2][2],
            },
            state_root=tmp_path,
            trust_root=tmp_path,
            installation_id=INSTALLATION,
            job_id=JOB,
            expected_host_pin="a" * 64,
            workspace_root=tmp_path,
            replay_phase_receipts=False,
        )

    # Edge substitution cannot turn the root job into the active parent.
    substituted = {**lineage, "ancestry": [edges[1], edges[0]]}
    with pytest.raises(RuntimeError, match="ancestry edge binding"):
        run_service._validate_evo_child_active_lineage(
            lineage=substituted,
            signed_execution={"parent_report_id": child_2, "child_report_id": child_3},
            trusted_parent_checkpoint={
                "parent_phase_receipt_path": str(receipts[child_2][0]),
                "parent_phase_receipt_sha256": receipts[child_2][1],
                "parent_phase_receipt_id": receipts[child_2][2],
            },
            state_root=tmp_path,
            trust_root=tmp_path,
            installation_id=INSTALLATION,
            job_id=JOB,
            expected_host_pin="a" * 64,
            workspace_root=tmp_path,
            replay_phase_receipts=False,
        )

    receipts[child_1][0].write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="ancestry receipt changed"):
        run_service._validate_evo_child_active_lineage(
            lineage=lineage,
            signed_execution={"parent_report_id": child_2, "child_report_id": child_3},
            trusted_parent_checkpoint={
                "parent_phase_receipt_path": str(receipts[child_2][0]),
                "parent_phase_receipt_sha256": receipts[child_2][1],
                "parent_phase_receipt_id": receipts[child_2][2],
            },
            state_root=tmp_path,
            trust_root=tmp_path,
            installation_id=INSTALLATION,
            job_id=JOB,
            expected_host_pin="a" * 64,
            workspace_root=tmp_path,
            replay_phase_receipts=False,
        )


def test_crash_after_fresh_proof_recovers_signed_inflight_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    system_run = runtime._run_owned_process_group

    def crash_after_wrapper(*args, **kwargs):
        system_run(*args, **kwargs)
        raise KeyboardInterrupt("host crash after child proof")

    monkeypatch.setattr(runtime, "_run_owned_process_group", crash_after_wrapper)
    with pytest.raises(KeyboardInterrupt):
        _execute(fixture)
    assert fixture["counter"].read_text() == "1"
    monkeypatch.setattr(runtime, "_run_owned_process_group", system_run)
    recovered = _execute(fixture)
    assert recovered["status"] == runtime.CHILD_RESUME_READY
    assert fixture["counter"].read_text() == "1"
    receipt = json.loads(Path(recovered["execution_receipt_path"]).read_text())
    assert receipt["recovered_from_inflight"] is True
    assert receipt["inflight_attempt"]["sha256"]


def test_crash_after_validate_step4_before_finalizer_recovers_without_agent_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    termination = next(
        (
            fixture["state"]
            / "jobs"
            / JOB
            / "evo-child-container"
            / CHILD
        ).glob("termination__*.json")
    )
    termination_raw = termination.read_bytes()
    termination.unlink()
    proof = (
        fixture["workspace"]
        / "objects/runtime_context"
        / f"ultimate_run_report__{CHILD}.json"
    )
    prefetch_receipt = (
        fixture["workspace"]
        / "runs"
        / CHILD
        / f"evo_pre_release_data_receipt__{CHILD}.json"
    )
    prefetch_core = {
        "contract_version": "factorforge_evo_pre_release_data_receipt_v1",
        "report_id": CHILD,
        "authority": "ULTIMATE_HOST_TRUSTED_FETCH_ONLY_NO_FACTOR_EXECUTION",
        "full_contract_input": True,
        "artifacts": [{"sha256": "a" * 64}],
    }
    _write(
        prefetch_receipt,
        runtime._canonical_bytes(
            {
                **prefetch_core,
                "content_sha256": runtime.stable_json_hash(prefetch_core),
            }
        ),
    )

    def crash_after_validate_step4(*_args, **_kwargs):
        fixture["counter"].write_text("1", encoding="utf-8")
        termination.write_bytes(termination_raw)
        termination.chmod(0o600)
        _write(
            proof,
            json.dumps(
                {
                    "report_id": CHILD,
                    "status": "RUNNING",
                    "requested_steps": ["3b", "4", "5", "6"],
                    "commands": [
                        {
                            "name": "validate_step4",
                            "returncode": 0,
                            "status": "PASS",
                        }
                    ],
                }
            ).encode("utf-8"),
        )
        raise KeyboardInterrupt("host crash before finalizer")

    monkeypatch.setattr(
        runtime, "_run_owned_process_group", crash_after_validate_step4
    )
    with pytest.raises(KeyboardInterrupt):
        _execute(fixture)
    assert fixture["counter"].read_text() == "1"

    monkeypatch.setattr(
        runtime,
        "_run_owned_process_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Agent wrapper must not rerun after validate_step4")
        ),
    )
    recovered = _execute(fixture)
    assert recovered["status"] == runtime.CHILD_RECOVERY_READY
    assert recovered["resume_start_step"] == "6"
    assert fixture["counter"].read_text() == "1"
    receipt = json.loads(Path(recovered["execution_receipt_path"]).read_text())
    assert receipt["container_termination"]["stage_name"] == "validate_step4"
    assert receipt["recovered_from_inflight"] is True

    observed: dict[str, list[str]] = {}

    def finalizer_only_wrapper(argv, **_kwargs):
        observed["argv"] = list(argv)
        assert "--evo-child-finalizer-recovery-admission" in argv
        recovery_path = Path(
            argv[argv.index("--evo-child-finalizer-recovery-admission") + 1]
        )
        assert recovery_path == Path(recovered["execution_receipt_path"])
        _write(
            proof,
            json.dumps(
                {
                    "report_id": CHILD,
                    "status": "PASS",
                    "requested_steps": ["6"],
                    "commands": [
                        {"name": "finalize_web_factor_proof", "returncode": 0}
                    ],
                }
            ).encode("utf-8"),
        )
        return runtime.subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(runtime, "_run_owned_process_group", finalizer_only_wrapper)
    finalized = _execute(fixture, resume=True)
    assert finalized["status"] == runtime.CHILD_TERMINAL
    assert fixture["counter"].read_text() == "1"
    assert observed["argv"]


@pytest.mark.parametrize(
    ("completed_names", "prefetched", "expected_start", "repeat_names"),
    [
        (["run_step3b"], False, "3b", None),
        (["run_step3b", "validate_step3b"], False, "4", None),
        (
            [
                "run_step3b",
                "validate_step3b",
                "materialize_evo_pre_release_data",
            ],
            True,
            "4",
            None,
        ),
        (
            [
                "run_step3b",
                "validate_step3b",
                "materialize_evo_pre_release_data",
            ],
            True,
            "4",
            ["materialize_evo_pre_release_data"],
        ),
        (
            ["materialize_evo_pre_release_data"],
            True,
            "4",
            [],
        ),
        (
            [
                "run_step3b",
                "validate_step3b",
                "materialize_evo_pre_release_data",
            ],
            True,
            "4",
            "MISSING_AFTER_ARCHIVE",
        ),
        (
            [
                "run_step3b",
                "validate_step3b",
                "materialize_evo_pre_release_data",
                "run_step4",
            ],
            True,
            "4",
            None,
        ),
    ],
)
def test_closed_command_boundaries_resume_at_the_exact_next_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completed_names: list[str],
    prefetched: bool,
    expected_start: str,
    repeat_names: list[str] | str | None,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    owned_run = runtime._run_owned_process_group
    termination = next(
        (
            fixture["state"]
            / "jobs"
            / JOB
            / "evo-child-container"
            / CHILD
        ).glob("termination__*.json")
    )
    termination_raw = termination.read_bytes()
    termination.unlink()
    proof = (
        fixture["workspace"]
        / "objects/runtime_context"
        / f"ultimate_run_report__{CHILD}.json"
    )
    receipt_path = (
        fixture["workspace"]
        / "runs"
        / CHILD
        / f"evo_pre_release_data_receipt__{CHILD}.json"
    )

    def crash_after_prefetch(*_args, **_kwargs):
        prefetch_core = {
            "contract_version": "factorforge_evo_pre_release_data_receipt_v1",
            "report_id": CHILD,
            "authority": "ULTIMATE_HOST_TRUSTED_FETCH_ONLY_NO_FACTOR_EXECUTION",
            "full_contract_input": True,
            "artifacts": [{"sha256": "a" * 64}],
        }
        if prefetched:
            _write(
                receipt_path,
                runtime._canonical_bytes(
                    {
                        **prefetch_core,
                        "content_sha256": runtime.stable_json_hash(prefetch_core),
                    }
                ),
            )
        termination.write_bytes(termination_raw)
        termination.chmod(0o600)
        _write(
            proof,
            json.dumps(
                {
                    "report_id": CHILD,
                    "status": "RUNNING",
                    "commands": [
                        {"name": name, "returncode": 0, "status": "PASS"}
                        for name in completed_names
                    ],
                }
            ).encode("utf-8"),
        )
        raise KeyboardInterrupt("host crash after prefetch")

    monkeypatch.setattr(runtime, "_run_owned_process_group", crash_after_prefetch)
    with pytest.raises(KeyboardInterrupt):
        _execute(fixture)
    assert not fixture["counter"].exists()

    required: list[str] = []
    expected_termination = {
        "run_step3b": "run_step3b",
        "validate_step3b": "validate_step3b",
        "materialize_evo_pre_release_data": "validate_step3b",
        "run_step4": "run_step4",
    }[completed_names[-1]]
    latest_stage = {"value": expected_termination}
    stage_terminations: dict[str, tuple[Path, dict]] = {}

    def signed_stage_termination(stage: str) -> tuple[Path, dict]:
        existing = stage_terminations.get(stage)
        if existing is not None:
            return existing
        path = termination.with_name(f"termination__mock__{stage}.json")
        signed = fixture["store"].sign(
            "host_admission",
            {
                "receipt_type": "EVO_CHILD_AGENT_STAGE_CONTAINER_TERMINATION",
                "identity": {
                    "installation_id": INSTALLATION,
                    "job_id": JOB,
                    "parent_report_id": PARENT,
                    "child_report_id": CHILD,
                },
                "stage_name": stage,
                "process_tree": {"process_tree_absent": True},
            },
        )
        path.write_bytes(runtime._canonical_bytes(signed))
        path.chmod(0o600)
        stage_terminations[stage] = (path, signed)
        return path, signed

    def validate_termination(**kwargs):
        required.append(str(kwargs.get("required_stage") or ""))
        required_stage = kwargs.get("required_stage")
        if required_stage is not None:
            assert required_stage == latest_stage["value"]
        stage_termination, signed_termination = signed_stage_termination(
            latest_stage["value"]
        )
        return {
            "verdict": "PASS",
            "stage_name": latest_stage["value"],
            "process_tree_absent": True,
            "termination_receipt_path": stage_termination,
            "termination_receipt": signed_termination,
        }

    monkeypatch.setattr(
        runtime,
        "validate_latest_evo_child_agent_termination",
        validate_termination,
    )
    if repeat_names is not None:
        def crash_before_exact_next_command(*_args, **_kwargs):
            if repeat_names == "MISSING_AFTER_ARCHIVE":
                proof.unlink()
            else:
                assert isinstance(repeat_names, list)
                _write(
                    proof,
                    json.dumps(
                        {
                            "report_id": CHILD,
                            "status": "RUNNING",
                            "commands": [
                                {
                                    "name": name,
                                    "returncode": 0,
                                    "status": "PASS",
                                }
                                for name in repeat_names
                            ],
                        }
                    ).encode("utf-8"),
                )
            raise KeyboardInterrupt("second host crash before admitted command")

        monkeypatch.setattr(
            runtime,
            "_run_owned_process_group",
            crash_before_exact_next_command,
        )
        with pytest.raises(KeyboardInterrupt):
            _execute(fixture)
        assert not fixture["counter"].exists()

    def completed_wrapper(*args, **kwargs):
        result = owned_run(*args, **kwargs)
        if not receipt_path.exists():
            completed_prefetch_core = {
                "contract_version": "factorforge_evo_pre_release_data_receipt_v1",
                "report_id": CHILD,
                "authority": "ULTIMATE_HOST_TRUSTED_FETCH_ONLY_NO_FACTOR_EXECUTION",
                "full_contract_input": True,
                "artifacts": [{"sha256": "a" * 64}],
            }
            _write(
                receipt_path,
                runtime._canonical_bytes(
                    {
                        **completed_prefetch_core,
                        "content_sha256": runtime.stable_json_hash(
                            completed_prefetch_core
                        ),
                    }
                ),
            )
        latest_stage["value"] = "validate_step4"
        signed_stage_termination("validate_step4")
        return result

    monkeypatch.setattr(runtime, "_run_owned_process_group", completed_wrapper)
    recovered = _execute(fixture)
    assert recovered["status"] == runtime.CHILD_RESUME_READY
    assert fixture["counter"].read_text() == "1"
    assert (
        json.loads(fixture["argv_log"].read_text())["start_step"]
        == expected_start
    )
    assert required[0] == ""
    assert expected_termination in required
    assert required[-1] == "validate_step4"
    receipt = json.loads(Path(recovered["execution_receipt_path"]).read_text())
    recovery = receipt["command_recovery"]
    effective_names = (
        repeat_names
        if isinstance(repeat_names, list) and repeat_names
        else completed_names
    )
    assert recovery["boundary"] == f"{effective_names[-1].upper()}_COMPLETE"
    assert bool(recovery["prefetch_receipt"]) is prefetched
    assert recovery["recovery_admission"]["sha256"]
    validated = runtime.validate_evo_child_execution_state(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=fixture["pin"],
        execution_receipt_path=recovered["execution_receipt_path"],
        workspace_root=fixture["workspace"],
    )
    assert validated["status"] == runtime.CHILD_RESUME_READY


def test_unknown_inflight_never_reruns_start3b(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runtime,
        "_run_owned_process_group",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            KeyboardInterrupt("host crash before proof")
        ),
    )
    with pytest.raises(KeyboardInterrupt):
        _execute(fixture)
    assert not fixture["counter"].exists()
    with pytest.raises(
        runtime.EvoChildRuntimeError,
        match="child_inflight_unclassified_no_rerun",
    ):
        _execute(fixture)
    assert not fixture["counter"].exists()
    proof = (
        fixture["workspace"]
        / "objects/runtime_context"
        / f"ultimate_run_report__{CHILD}.json"
    )
    _write(
        proof,
        json.dumps(
            {
                "report_id": CHILD,
                "status": "RUNNING",
                "commands": [
                    {"name": "unknown_command", "returncode": 0, "status": "PASS"}
                ],
            }
        ).encode("utf-8"),
    )
    with pytest.raises(
        runtime.EvoChildRuntimeError,
        match="child_inflight_proof_unknown_command_prefix",
    ):
        _execute(fixture)
    assert not fixture["counter"].exists()


def test_missing_proof_recovery_rejects_multiple_or_stale_signed_admissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    runtime_root = runtime._runtime_root(fixture["state"], JOB, CHILD)
    inflight = runtime_root / "inflight__0001.json"
    runtime._write_once(inflight, b'{"signed":"inflight-one"}\n')
    stale_inflight = runtime_root / "inflight__0002.json"
    runtime._write_once(stale_inflight, b'{"signed":"inflight-two"}\n')
    proof = (
        fixture["workspace"]
        / "objects/runtime_context"
        / f"ultimate_run_report__{CHILD}.json"
    )
    proof_payload = {
        "report_id": CHILD,
        "status": "RUNNING",
        "commands": [
            {
                "name": "materialize_evo_pre_release_data",
                "returncode": 0,
                "status": "PASS",
            }
        ],
    }
    _write(proof, json.dumps(proof_payload).encode("utf-8"))
    prefetch = (
        fixture["workspace"]
        / "runs"
        / CHILD
        / f"evo_pre_release_data_receipt__{CHILD}.json"
    )
    prefetch_core = {
        "contract_version": "factorforge_evo_pre_release_data_receipt_v1",
        "report_id": CHILD,
        "authority": "ULTIMATE_HOST_TRUSTED_FETCH_ONLY_NO_FACTOR_EXECUTION",
        "full_contract_input": True,
        "artifacts": [{"sha256": "a" * 64}],
    }
    _write(
        prefetch,
        runtime._canonical_bytes(
            {
                **prefetch_core,
                "content_sha256": runtime.stable_json_hash(prefetch_core),
            }
        ),
    )
    termination = (
        fixture["state"]
        / "jobs"
        / JOB
        / "evo-child-container"
        / CHILD
        / "termination__signed__validate_step3b.json"
    )
    signed_termination = fixture["store"].sign(
        "host_admission",
        {
            "receipt_type": "EVO_CHILD_AGENT_STAGE_CONTAINER_TERMINATION",
            "identity": {
                "installation_id": INSTALLATION,
                "job_id": JOB,
                "parent_report_id": PARENT,
                "child_report_id": CHILD,
            },
            "stage_name": "validate_step3b",
            "process_tree": {"process_tree_absent": True},
        },
    )
    termination.write_bytes(runtime._canonical_bytes(signed_termination))
    termination.chmod(0o600)
    boundary = runtime._validated_command_crash_boundary(
        workspace=fixture["workspace"],
        child_report_id=CHILD,
        proof=proof_payload,
    )
    assert boundary is not None
    identity = {
        "job_id": JOB,
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_trust_manifest_sha256": fixture["pin"],
    }
    admission = runtime._materialize_command_recovery_admission(
        runtime_root=runtime_root,
        store=fixture["store"],
        identity=identity,
        inflight_path=inflight,
        proof_path=proof,
        termination_path=termination,
        boundary=boundary,
        workspace=fixture["workspace"],
        trust=fixture["trust"],
        installation_id=INSTALLATION,
        child_report_id=CHILD,
    )
    proof.unlink()
    resolve_kwargs = {
        "state": fixture["state"],
        "trust": fixture["trust"],
        "installation_id": INSTALLATION,
        "job_id": JOB,
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_trust_manifest_sha256": fixture["pin"],
        "workspace": fixture["workspace"],
        "proof": None,
    }
    assert runtime._resolve_replayable_command_recovery(
        **resolve_kwargs, inflight_path=inflight
    ) is not None
    assert runtime._resolve_replayable_command_recovery(
        **resolve_kwargs, inflight_path=stale_inflight
    ) is None

    duplicate = runtime_root / "command_recovery__duplicate__run_step4.json"
    duplicate.write_bytes(Path(admission["path"]).read_bytes())
    duplicate.chmod(0o600)
    assert runtime._resolve_replayable_command_recovery(
        **resolve_kwargs, inflight_path=inflight
    ) is None


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_owned_wrapper_timeout_terminates_descendant_process_tree(
    tmp_path: Path,
) -> None:
    child_pid_path = tmp_path / "child.pid"
    script = tmp_path / "spawn_descendant.py"
    script.write_text(
        "import subprocess,sys,time\n"
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])\n"
        "open(sys.argv[1],'w').write(str(p.pid))\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    with pytest.raises(runtime.subprocess.TimeoutExpired):
        runtime._run_owned_process_group(
            [sys.executable, str(script), str(child_pid_path)],
            cwd=tmp_path,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            timeout_seconds=1,
        )
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while True:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        if time.monotonic() >= deadline:
            pytest.fail("owned descendant survived Host wrapper timeout")
        time.sleep(0.05)
