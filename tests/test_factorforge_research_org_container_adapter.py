from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.container_agent_adapter import (
    ContainerizedOpenClawResearchAgentAdapter,
)
from factor_factory.research_org import (
    ResearchOrganizationError,
    ResearchOrgSessionInvocation,
)
from factor_factory.research_org.runtime_ledger import ResearchOrgRuntimeLedger
from factor_factory.research_org.runtime_trust import (
    ensure_runtime_trust_store,
    load_runtime_trust_store,
)


class _CompletedProcess:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakePopen:
    command: ClassVar[list[str]] = []

    def __init__(self, command, **_kwargs) -> None:
        type(self).command = list(command)
        self.returncode = 0

    def poll(self) -> int:
        return 0

    def communicate(self, timeout=None):
        del timeout
        return "agent completed", ""


class _RunningPopen(_FakePopen):
    def __init__(self, command, **_kwargs) -> None:
        type(self).command = list(command)
        self.returncode = None

    def poll(self):
        return None


class _FailedPopen(_FakePopen):
    def __init__(self, command, **_kwargs) -> None:
        type(self).command = list(command)
        self.returncode = 7


def _termination_proof(
    config: ConsoleConfig,
    runtime_instance_id: str,
    *,
    confirmed: bool,
) -> dict:
    store = ensure_runtime_trust_store(
        config.state_root / "research-org-trust",
        installation_id=config.installation_id,
    )
    return store.sign(
        "runtime_adapter",
        {
            "receipt_type": "RESEARCH_ORG_CONTAINER_TERMINATION",
            "identity": {
                "runtime_instance_id": runtime_instance_id,
                "runtime_handle_sha256": hashlib.sha256(
                    runtime_instance_id.encode("utf-8")
                ).hexdigest(),
                "adapter_id": config.installation_id,
            },
            "ordering": {"issued_at_utc": "2026-08-13T00:00:00Z"},
            "termination": {
                "initial_state": "ABSENT" if confirmed else "OWNED_PRESENT",
                "ownership_labels_verified": not confirmed,
                "remove_attempted": not confirmed,
                "inspect_not_found": confirmed,
                "final_state": "ABSENT" if confirmed else "UNCONFIRMED",
                "termination_confirmed": confirmed,
            },
            "authority": {
                "scope": "OWNED_CONTAINER_TERMINATION_ONLY",
                "retry_authorized": False,
                "factor_verdict": "NOT_ISSUED",
            },
        },
    )


def _config(tmp_path: Path) -> ConsoleConfig:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    profile = tmp_path / "openclaw.json"
    profile.write_text("{}\n", encoding="utf-8")
    seed = tmp_path / "seed.sqlite"
    seed.write_bytes(b"seed")
    return ConsoleConfig(
        source_repo=worktree,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_profile_template=profile,
        openclaw_auth_seed_db=seed,
        auth_disabled=True,
    )


def _patch_research_session_dependencies(
    *,
    module,
    adapter: ContainerizedOpenClawResearchAgentAdapter,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        module, "_validate_profile_policy", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        module,
        "copy_auth_database",
        lambda _source, destination: destination.write_bytes(b"auth"),
    )
    monkeypatch.setattr(
        module, "validate_auth_database", lambda *_args, **_kwargs: "ok"
    )
    monkeypatch.setattr(
        adapter, "_broker_client_token", lambda: "broker-secret-token"
    )
    monkeypatch.setattr(
        adapter,
        "_initialize_credential_material_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter, "credential_material_state", lambda _job_id: "not_issued"
    )
    monkeypatch.setattr(
        adapter,
        "_prepare_aws_environment",
        lambda *_args, **_kwargs: (
            None,
            ("broker-secret-token",),
            None,
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_cleanup_aws_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter, "_validate_agent_binding", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        adapter, "_run_runtime", lambda *_args, **_kwargs: "{}"
    )


def _invocation(tmp_path: Path, config: ConsoleConfig) -> ResearchOrgSessionInvocation:
    worktree = config.source_repo
    for relative in ("data", "knowledge"):
        (worktree / relative).mkdir()
    workspace = worktree / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    private_root = tmp_path / "private" / "attempt"
    context_root = private_root / "context"
    output = private_root / "output" / "agent_result.json"
    context_root.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    (context_root / "runtime_context.json").write_text("{}\n", encoding="utf-8")
    output.write_text(
        json.dumps(
            {
                "contract_version": "factorforge_agent_private_output_v1",
                "status": "PASS",
                "public_research_record": {},
            }
        ),
        encoding="utf-8",
    )
    return ResearchOrgSessionInvocation(
        identity={
            "job_id": "job_1234567890",
            "factor_id": "FACTOR",
            "research_id": "research",
            "report_id": "REPORT",
        },
        role_id="price_volume_researcher",
        task_id="task_01_price_volume_researcher",
        task_sha256="a" * 64,
        attempt_id="attempt_01_1234567890abcdef",
        attempt_number=1,
        session_id="session_1234567890abcdef1234567890abcdef",
        runtime_instance_id="fforg-job12345678-price-volume-1234abcd",
        worktree=worktree,
        workspace=workspace,
        private_attempt_root=private_root,
        context_root=context_root,
        private_output_path=output,
        cancel_request_path=workspace / "cancel_request.json",
        context_manifest_sha256="b" * 64,
        required_skills=(),
        timeout_seconds=60,
    )


def _adapter_outcome_with_ledger(
    tmp_path: Path,
    monkeypatch,
) -> tuple[
    ResearchOrgRuntimeLedger,
    ResearchOrgSessionInvocation,
    object,
]:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    initial_invocation = _invocation(tmp_path, config)
    task = {
        "task_id": initial_invocation.task_id,
        "role_id": initial_invocation.role_id,
        "task_sha256": initial_invocation.task_sha256,
        "depends_on_roles": [],
        "session_policy": {"requirement": "isolated_session"},
    }
    plan_sha256 = "d" * 64
    trust_store = ensure_runtime_trust_store(
        config.state_root / "research-org-trust",
        installation_id=config.installation_id,
    )
    ledger = ResearchOrgRuntimeLedger(
        private_root=tmp_path / "ledger-private",
        runtime_id="runtime_container_adapter_cross_layer",
        identity=initial_invocation.identity,
        plan_sha256=plan_sha256,
        tasks=[task],
        policy={"max_attempts_per_role": 1},
        trust_store=trust_store,
    )
    scheduler_epoch = ledger.start_scheduler()
    dependencies, idempotency_key = ledger.dispatch_material(
        role_id=initial_invocation.role_id,
        attempt_no=1,
        scheduler_epoch=scheduler_epoch,
    )
    lease = ledger.begin_attempt(
        role_id=initial_invocation.role_id,
        attempt_id=initial_invocation.attempt_id,
        attempt_no=1,
        session_uid=initial_invocation.session_id,
        runtime_handle=initial_invocation.runtime_instance_id,
        context_manifest_sha256=initial_invocation.context_manifest_sha256,
        idempotency_key=idempotency_key,
        dependency_admissions=dependencies,
        adapter_challenge="challenge_container_adapter_cross_layer",
        parent_session_uid=None,
        scheduler_epoch=scheduler_epoch,
    )
    invocation = replace(
        initial_invocation,
        runtime_id=ledger.runtime_id,
        plan_sha256=plan_sha256,
        scheduler_epoch=lease.scheduler_epoch,
        dispatch_event_seq=lease.dispatch_event_seq,
        idempotency_key=lease.idempotency_key,
        adapter_challenge="challenge_container_adapter_cross_layer",
        dependency_admissions=lease.dependency_admissions,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    _patch_research_session_dependencies(
        module=module,
        adapter=adapter,
        monkeypatch=monkeypatch,
    )
    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)

    def owned_then_absent(command, **_kwargs):
        if "--format" in command:
            return _CompletedProcess(
                0,
                stdout=json.dumps(
                    {
                        "factorforge.console.managed": "true",
                        "factorforge.console.installation": config.installation_id,
                        "factorforge.research-org.session": "true",
                        "factorforge.research-org.runtime": (
                            invocation.runtime_instance_id
                        ),
                    }
                ),
            )
        return _CompletedProcess(
            1,
            stderr=f"Error: No such object: {invocation.runtime_instance_id}",
        )

    monkeypatch.setattr(module.subprocess, "run", owned_then_absent)
    monkeypatch.setattr(adapter, "_stop_container", lambda _runtime_id: True)
    outcome = adapter.run_research_org_session(invocation)
    return ledger, invocation, outcome


@pytest.mark.parametrize("runtime_fails", [False, True])
def test_memory_reviewer_always_deactivates_owned_secret_registry(
    tmp_path: Path,
    monkeypatch,
    runtime_fails: bool,
) -> None:
    import factor_factory.researcher_memory_review as review_module

    config = _config(tmp_path)
    invocation = replace(
        _invocation(tmp_path, config),
        role_id="researcher_memory_reviewer",
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    cleanup_calls: list[str] = []

    if runtime_fails:
        monkeypatch.setattr(
            adapter,
            "run_research_org_session",
            lambda _invocation: (_ for _ in ()).throw(RuntimeError("failed")),
        )
    else:
        outcome = object()
        monkeypatch.setattr(
            adapter,
            "run_research_org_session",
            lambda _invocation: outcome,
        )
        monkeypatch.setattr(
            review_module,
            "sign_completed_reviewer_session",
            lambda **_kwargs: {"status": "signed"},
        )
    monkeypatch.setattr(
        adapter,
        "deactivate_denied_secrets",
        lambda job_id: cleanup_calls.append(job_id),
    )

    if runtime_fails:
        with pytest.raises(RuntimeError, match="failed"):
            adapter.run_researcher_memory_review_session(invocation)
    else:
        assert adapter.run_researcher_memory_review_session(invocation) == {
            "status": "signed"
        }
    assert cleanup_calls == [invocation.identity["job_id"]]


def test_container_research_org_session_uses_staged_read_only_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    invocation = _invocation(tmp_path, config)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    add_commands: list[list[str]] = []

    monkeypatch.setattr(module, "_validate_profile_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "copy_auth_database",
        lambda _source, destination: destination.write_bytes(b"auth"),
    )
    monkeypatch.setattr(module, "validate_auth_database", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(adapter, "_broker_client_token", lambda: "broker-secret-token")
    monkeypatch.setattr(
        adapter,
        "_initialize_credential_material_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "credential_material_state", lambda _job_id: "not_issued")
    monkeypatch.setattr(
        adapter,
        "_prepare_aws_environment",
        lambda *_args, **_kwargs: (None, ("broker-secret-token",), None),
    )
    monkeypatch.setattr(
        adapter,
        "_cleanup_aws_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "_validate_agent_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        adapter,
        "_run_runtime",
        lambda command, **_kwargs: add_commands.append(list(command)) or "{}",
    )
    monkeypatch.setattr(
        adapter,
        "reconcile_research_org_session",
        lambda runtime_id: _termination_proof(
            config, runtime_id, confirmed=True
        ),
    )

    outcome = adapter.run_research_org_session(invocation)

    assert outcome.returncode == 0
    assert outcome.session_id == invocation.session_id
    assert outcome.isolation_class == "container_staged_context"
    assert outcome.owned_termination_supported is True
    assert invocation.private_output_path.is_file()
    assert not (invocation.private_attempt_root / "agent").exists()
    assert not (invocation.private_attempt_root / "home").exists()
    assert add_commands
    joined_add = " ".join(add_commands[0])
    joined_run = " ".join(_FakePopen.command)
    mount_specs = [
        _FakePopen.command[index + 1]
        for index, item in enumerate(_FakePopen.command[:-1])
        if item == "--mount"
    ]
    assert "factorforge.research-org.session=true" in joined_add
    assert "factorforge.research-org.session=true" in joined_run
    assert str(invocation.context_root) in joined_run
    assert f"dst={invocation.workspace}" in joined_run
    for hidden_root in ("factor_research", "knowledge", "data"):
        assert f"dst={invocation.worktree / hidden_root}" in joined_run
    assert f"dst={invocation.worktree / 'runs'}" not in joined_run
    assert joined_run.index(
        f"dst={invocation.worktree / 'factor_research'}"
    ) < joined_run.index(f"dst={invocation.workspace}")
    private_root_mount = next(
        item
        for item in mount_specs
        if f"dst={invocation.private_attempt_root}" in item
    )
    output_mount = next(
        item
        for item in mount_specs
        if f"dst={invocation.private_output_path.parent}" in item
    )
    assert private_root_mount.endswith(",readonly")
    assert not output_mount.endswith(",readonly")
    assert "readonly" in joined_run
    assert "AWS_ACCESS_KEY_ID" not in joined_run
    nested_workspace_mountpoint = (
        invocation.private_attempt_root
        / "repo_masks"
        / "factor_research"
        / "FACTOR"
        / "research"
    )
    assert nested_workspace_mountpoint.is_dir()
    assert nested_workspace_mountpoint.stat().st_mode & 0o777 == 0o500


def test_container_research_org_session_signs_initialization_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    invocation = _invocation(tmp_path, config)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    monkeypatch.setattr(module, "_validate_profile_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "copy_auth_database",
        lambda _source, destination: destination.write_bytes(b"auth"),
    )
    monkeypatch.setattr(module, "validate_auth_database", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(adapter, "_broker_client_token", lambda: "broker-secret-token")
    monkeypatch.setattr(
        adapter,
        "_initialize_credential_material_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "credential_material_state", lambda _job_id: "not_issued")
    monkeypatch.setattr(
        adapter,
        "_prepare_aws_environment",
        lambda *_args, **_kwargs: (None, ("broker-secret-token",), None),
    )
    monkeypatch.setattr(
        adapter,
        "_cleanup_aws_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        adapter,
        "_run_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE: init failed")
        ),
    )
    monkeypatch.setattr(
        adapter,
        "reconcile_research_org_session",
        lambda runtime_id: _termination_proof(
            config, runtime_id, confirmed=True
        ),
    )

    outcome = adapter.run_research_org_session(invocation)

    assert outcome.returncode == 1
    assert outcome.adapter_receipt is not None
    assert outcome.adapter_receipt["receipt_type"] == "FAILED"
    assert outcome.adapter_receipt["outcome"]["termination_confirmed"] is True
    assert "init failed" in outcome.stderr_tail
    trust_store = load_runtime_trust_store(
        config.state_root / "research-org-trust",
        installation_id=config.installation_id,
    )
    assert trust_store.verify(
        outcome.adapter_receipt,
        expected_issuer="runtime_adapter",
    ) == []
    assert not invocation.private_output_path.exists()
    assert not (invocation.private_attempt_root / "agent").exists()
    assert not (invocation.private_attempt_root / "home").exists()
    assert not (invocation.private_attempt_root / "research_org_task.md").exists()


def test_container_research_org_session_preserves_mounts_for_unconfirmed_orphan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    invocation = _invocation(tmp_path, config)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    invocation.cancel_request_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "_validate_profile_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "copy_auth_database",
        lambda _source, destination: destination.write_bytes(b"auth"),
    )
    monkeypatch.setattr(module, "validate_auth_database", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(module.subprocess, "Popen", _RunningPopen)
    monkeypatch.setattr(adapter, "_broker_client_token", lambda: "broker-secret-token")
    monkeypatch.setattr(
        adapter,
        "_initialize_credential_material_state",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "credential_material_state", lambda _job_id: "not_issued")
    monkeypatch.setattr(
        adapter,
        "_prepare_aws_environment",
        lambda *_args, **_kwargs: (None, ("broker-secret-token",), None),
    )
    monkeypatch.setattr(
        adapter,
        "_cleanup_aws_environment",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(adapter, "_validate_agent_binding", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(adapter, "_run_runtime", lambda *_args, **_kwargs: "{}")
    monkeypatch.setattr(
        adapter,
        "reconcile_research_org_session",
        lambda runtime_id: _termination_proof(
            config, runtime_id, confirmed=False
        ),
    )

    outcome = adapter.run_research_org_session(invocation)

    assert outcome.adapter_receipt is not None
    assert outcome.adapter_receipt["outcome"]["termination_confirmed"] is False
    assert "BLOCK_FACTORFORGE_CONSOLE_AGENT_ORPHANED_WRITER" in outcome.stderr_tail
    assert (invocation.private_attempt_root / "home").is_dir()
    assert (invocation.private_attempt_root / "agent").is_dir()
    assert (invocation.private_attempt_root / "research_org_task.md").is_file()
    assert invocation.private_output_path.is_file()
    assert invocation.runtime_instance_id in adapter._active


def test_targeted_cancel_refuses_unowned_container(tmp_path: Path, monkeypatch) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_id = "fforg-job12345678-price-volume-1234abcd"
    stop_calls: list[str] = []

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: _CompletedProcess(
            0,
            stdout=json.dumps(
                {
                    "factorforge.console.managed": "true",
                    "factorforge.console.installation": "another-installation",
                    "factorforge.research-org.session": "true",
                    "factorforge.research-org.runtime": runtime_id,
                }
            ),
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_stop_container",
        lambda name: stop_calls.append(name) or True,
    )

    assert adapter.cancel_research_org_session(runtime_id) is False
    adapter._active.add(runtime_id)
    adapter.stop_all()
    assert stop_calls == []


def test_targeted_cancel_does_not_treat_no_such_host_as_absent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_id = "fforg-job12345678-price-volume-1234abcd"
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: _CompletedProcess(
            1,
            stderr="lookup docker.internal: no such host",
        ),
    )

    assert adapter.cancel_research_org_session(runtime_id) is False
    assert adapter._confirm_research_org_session_terminated(runtime_id) is False


def test_targeted_cancel_accepts_exact_container_absence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_id = "fforg-job12345678-price-volume-1234abcd"
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: _CompletedProcess(
            1,
            stderr=f"Error: No such object: {runtime_id}",
        ),
    )
    monkeypatch.setattr(
        adapter,
        "_stop_container",
        lambda runtime_id: (_ for _ in ()).throw(
            AssertionError(f"must not remove after exact absence:{runtime_id}")
        ),
    )

    assert adapter.cancel_research_org_session(runtime_id) is True
    assert adapter._confirm_research_org_session_terminated(runtime_id) is True


def test_targeted_cancel_permission_error_is_unconfirmed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_id = "fforg-job12345678-price-volume-1234abcd"
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PermissionError("docker socket denied")
        ),
    )

    assert adapter.cancel_research_org_session(runtime_id) is False
    assert adapter._confirm_research_org_session_terminated(runtime_id) is False


def test_targeted_cancel_stops_only_bound_runtime(tmp_path: Path, monkeypatch) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_id = "fforg-job12345678-price-volume-1234abcd"
    stop_calls: list[str] = []

    def inspect_then_absent(command, **_kwargs):
        if "--format" in command:
            return _CompletedProcess(
                0,
                stdout=json.dumps(
                    {
                        "factorforge.console.managed": "true",
                        "factorforge.console.installation": config.installation_id,
                        "factorforge.research-org.session": "true",
                        "factorforge.research-org.runtime": runtime_id,
                    }
                ),
            )
        return _CompletedProcess(
            1, stderr=f"Error: No such object: {runtime_id}"
        )

    monkeypatch.setattr(module.subprocess, "run", inspect_then_absent)
    monkeypatch.setattr(
        adapter,
        "_stop_container",
        lambda name: stop_calls.append(name) or True,
    )

    assert adapter.cancel_research_org_session(runtime_id) is True
    assert stop_calls == [runtime_id]


@pytest.mark.parametrize(
    ("popen_type", "expected_returncode", "expected_receipt_type"),
    [
        (_FakePopen, 0, "COMPLETED"),
        (_FailedPopen, 7, "FAILED"),
    ],
)
def test_completed_and_failed_runs_both_remove_then_inspect_not_found(
    tmp_path: Path,
    monkeypatch,
    popen_type,
    expected_returncode: int,
    expected_receipt_type: str,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    invocation = _invocation(tmp_path, config)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    _patch_research_session_dependencies(
        module=module, adapter=adapter, monkeypatch=monkeypatch
    )
    monkeypatch.setattr(module.subprocess, "Popen", popen_type)
    stop_calls: list[str] = []

    def owned_then_absent(command, **_kwargs):
        if "--format" in command:
            return _CompletedProcess(
                0,
                stdout=json.dumps(
                    {
                        "factorforge.console.managed": "true",
                        "factorforge.console.installation": config.installation_id,
                        "factorforge.research-org.session": "true",
                        "factorforge.research-org.runtime": (
                            invocation.runtime_instance_id
                        ),
                    }
                ),
            )
        return _CompletedProcess(
            1,
            stderr=(
                "Error: No such object: "
                + invocation.runtime_instance_id
            ),
        )

    monkeypatch.setattr(module.subprocess, "run", owned_then_absent)
    monkeypatch.setattr(
        adapter,
        "_stop_container",
        lambda runtime_id: stop_calls.append(runtime_id) or True,
    )

    outcome = adapter.run_research_org_session(invocation)

    assert outcome.returncode == expected_returncode
    assert outcome.adapter_receipt["receipt_type"] == expected_receipt_type
    assert outcome.adapter_receipt["outcome"]["termination_confirmed"] is True
    assert stop_calls == [invocation.runtime_instance_id]
    proof_path = (
        invocation.private_attempt_root
        / "container_termination_receipt.json"
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["termination"]["inspect_not_found"] is True
    assert proof["termination"]["termination_confirmed"] is True
    trust_store = load_runtime_trust_store(
        config.state_root / "research-org-trust",
        installation_id=config.installation_id,
    )
    assert trust_store.verify(
        proof, expected_issuer="runtime_adapter"
    ) == []
    assert outcome.adapter_receipt["session"][
        "isolation_profile_sha256"
    ] == module.stable_json_hash(
        {
            "class": "container_staged_context",
            "network": config.container_network,
            "workspace_readonly": True,
            "aws_credentials": False,
            "installation_id": config.installation_id,
            "termination_receipt_id": proof["receipt_id"],
            "termination_runtime_handle_sha256": hashlib.sha256(
                invocation.runtime_instance_id.encode("utf-8")
            ).hexdigest(),
        }
    )


def test_real_container_adapter_receipt_is_admitted_by_runtime_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ledger, invocation, outcome = _adapter_outcome_with_ledger(
        tmp_path,
        monkeypatch,
    )
    output_bytes = invocation.private_output_path.read_bytes()
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    canonical_result = {
        "status": "PASS",
        "result_sha256": hashlib.sha256(b"canonical-result").hexdigest(),
    }

    host_receipt = ledger.complete_attempt(
        attempt_id=invocation.attempt_id,
        adapter_receipt=outcome.adapter_receipt,
        canonical_result=canonical_result,
        error_class=None,
        retryable=False,
        allow_unverified_test_runner=False,
        observed_private_output_sha256=output_sha256,
        observed_private_output_size_bytes=len(output_bytes),
    )

    assert host_receipt is not None
    assert host_receipt["receipt_type"] == "RESULT_ADMITTED"
    assert host_receipt["bindings"]["adapter_receipt_id"] == (
        outcome.adapter_receipt["receipt_id"]
    )
    assert outcome.adapter_receipt["session"]["runtime"] == {
        "provider": "deepseek",
        "model": "deepseek/deepseek-v4-flash",
        "transport": "openclaw_disposable_container",
        "isolation_class": "container_staged_context",
        "owned_termination_supported": True,
    }


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("provider", "other", "adapter_receipt.runtime"),
        ("model", "deepseek/other", "adapter_receipt.runtime"),
        ("transport", "shared_gateway", "adapter_receipt.runtime"),
        ("isolation_class", "shared_process", "adapter_receipt.runtime"),
        ("owned_termination_supported", False, "adapter_receipt.runtime"),
    ],
)
def test_runtime_ledger_rejects_signed_but_invalid_container_runtime_semantics(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: object,
    expected_reason: str,
) -> None:
    ledger, invocation, outcome = _adapter_outcome_with_ledger(
        tmp_path,
        monkeypatch,
    )
    tampered = deepcopy(outcome.adapter_receipt)
    tampered["session"]["runtime"][field] = value
    trust_store = load_runtime_trust_store(
        tmp_path / "state" / "research-org-trust",
        installation_id=outcome.adapter_receipt["session"]["adapter_id"],
    )
    tampered = trust_store.sign("runtime_adapter", tampered)
    output_bytes = invocation.private_output_path.read_bytes()

    with pytest.raises(ResearchOrganizationError) as captured:
        ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=tampered,
            canonical_result={
                "status": "PASS",
                "result_sha256": hashlib.sha256(b"canonical-result").hexdigest(),
            },
            error_class=None,
            retryable=False,
            allow_unverified_test_runner=False,
            observed_private_output_sha256=hashlib.sha256(output_bytes).hexdigest(),
            observed_private_output_size_bytes=len(output_bytes),
        )

    assert expected_reason in captured.value.reasons


def test_runtime_ledger_rejects_codex_for_formal_strong_isolation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ledger, invocation, outcome = _adapter_outcome_with_ledger(
        tmp_path,
        monkeypatch,
    )
    codex = deepcopy(outcome.adapter_receipt)
    codex["session"]["runtime"] = {
        "provider": "codex",
        "model": "gpt-5.6-codex",
        "transport": "codex_exec_ephemeral",
        "isolation_class": "codex_subagent_isolated",
        "owned_termination_supported": True,
    }
    trust_store = load_runtime_trust_store(
        tmp_path / "state" / "research-org-trust",
        installation_id=outcome.adapter_receipt["session"]["adapter_id"],
    )
    codex = trust_store.sign("runtime_adapter", codex)
    output_bytes = invocation.private_output_path.read_bytes()

    with pytest.raises(ResearchOrganizationError) as captured:
        ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=codex,
            canonical_result={
                "status": "PASS",
                "result_sha256": hashlib.sha256(b"canonical-result").hexdigest(),
            },
            error_class=None,
            retryable=False,
            allow_unverified_test_runner=False,
            observed_private_output_sha256=hashlib.sha256(output_bytes).hexdigest(),
            observed_private_output_size_bytes=len(output_bytes),
        )

    assert "adapter_receipt.runtime_strong_isolation" in captured.value.reasons


def test_runtime_and_termination_fields_are_covered_by_adapter_signature(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ledger, invocation, outcome = _adapter_outcome_with_ledger(
        tmp_path,
        monkeypatch,
    )
    tampered = deepcopy(outcome.adapter_receipt)
    tampered["session"]["runtime"]["provider"] = "other"
    tampered["outcome"]["termination_confirmed"] = False
    output_bytes = invocation.private_output_path.read_bytes()

    with pytest.raises(ResearchOrganizationError) as captured:
        ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=tampered,
            canonical_result={
                "status": "PASS",
                "result_sha256": hashlib.sha256(b"canonical-result").hexdigest(),
            },
            error_class=None,
            retryable=False,
            allow_unverified_test_runner=False,
            observed_private_output_sha256=hashlib.sha256(output_bytes).hexdigest(),
            observed_private_output_size_bytes=len(output_bytes),
        )

    assert "signed_receipt.receipt_id" in captured.value.reasons
    assert "signed_receipt.signature_invalid" in captured.value.reasons


def test_runtime_ledger_rejects_signed_unconfirmed_termination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ledger, invocation, outcome = _adapter_outcome_with_ledger(
        tmp_path,
        monkeypatch,
    )
    unconfirmed = deepcopy(outcome.adapter_receipt)
    unconfirmed["outcome"]["termination_confirmed"] = False
    trust_store = load_runtime_trust_store(
        tmp_path / "state" / "research-org-trust",
        installation_id=outcome.adapter_receipt["session"]["adapter_id"],
    )
    unconfirmed = trust_store.sign("runtime_adapter", unconfirmed)
    output_bytes = invocation.private_output_path.read_bytes()

    with pytest.raises(ResearchOrganizationError) as captured:
        ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=unconfirmed,
            canonical_result={
                "status": "PASS",
                "result_sha256": hashlib.sha256(b"canonical-result").hexdigest(),
            },
            error_class=None,
            retryable=False,
            allow_unverified_test_runner=False,
            observed_private_output_sha256=hashlib.sha256(output_bytes).hexdigest(),
            observed_private_output_size_bytes=len(output_bytes),
        )

    assert "adapter_receipt.outcome" in captured.value.reasons


@pytest.mark.parametrize(
    ("receipt_type", "outcome_update", "expected_reason"),
    [
        (
            "COMPLETED",
            {"returncode": 1},
            "adapter_receipt.completed_semantics",
        ),
        (
            "FAILED",
            {"returncode": 0, "cancelled": False, "error_class": None},
            "adapter_receipt.failed_semantics",
        ),
        (
            "TERMINATED",
            {"returncode": 7, "cancelled": False, "error_class": "timeout"},
            "adapter_receipt.terminated_semantics",
        ),
    ],
)
def test_runtime_ledger_rejects_signed_receipt_type_outcome_contradictions(
    tmp_path: Path,
    monkeypatch,
    receipt_type: str,
    outcome_update: dict[str, object],
    expected_reason: str,
) -> None:
    ledger, invocation, outcome = _adapter_outcome_with_ledger(
        tmp_path,
        monkeypatch,
    )
    contradictory = deepcopy(outcome.adapter_receipt)
    contradictory["receipt_type"] = receipt_type
    contradictory["outcome"].update(outcome_update)
    trust_store = load_runtime_trust_store(
        tmp_path / "state" / "research-org-trust",
        installation_id=outcome.adapter_receipt["session"]["adapter_id"],
    )
    contradictory = trust_store.sign("runtime_adapter", contradictory)

    with pytest.raises(ResearchOrganizationError) as captured:
        ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=contradictory,
            canonical_result=None,
            error_class="host_failure",
            retryable=False,
            allow_unverified_test_runner=False,
            observed_private_output_sha256=None,
            observed_private_output_size_bytes=None,
        )

    assert expected_reason in captured.value.reasons


def test_timeout_run_removes_then_inspects_not_found_before_signed_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    invocation = _invocation(tmp_path, config)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    _patch_research_session_dependencies(
        module=module, adapter=adapter, monkeypatch=monkeypatch
    )
    monkeypatch.setattr(module.subprocess, "Popen", _RunningPopen)
    monotonic_values = iter((0.0, 10_000.0))
    monkeypatch.setattr(
        module.time, "monotonic", lambda: next(monotonic_values)
    )

    def owned_then_absent(command, **_kwargs):
        if "--format" in command:
            return _CompletedProcess(
                0,
                stdout=json.dumps(
                    {
                        "factorforge.console.managed": "true",
                        "factorforge.console.installation": config.installation_id,
                        "factorforge.research-org.session": "true",
                        "factorforge.research-org.runtime": (
                            invocation.runtime_instance_id
                        ),
                    }
                ),
            )
        return _CompletedProcess(
            1,
            stderr=(
                "Error: No such object: "
                + invocation.runtime_instance_id
            ),
        )

    monkeypatch.setattr(module.subprocess, "run", owned_then_absent)
    monkeypatch.setattr(adapter, "_stop_container", lambda _runtime_id: True)

    outcome = adapter.run_research_org_session(invocation)

    assert outcome.returncode == 124
    assert outcome.adapter_receipt["receipt_type"] == "TERMINATED"
    assert outcome.adapter_receipt["outcome"]["error_class"] == "timeout"
    assert outcome.adapter_receipt["outcome"]["termination_confirmed"] is True


def test_fake_sticky_container_blocks_completed_receipt_and_preserves_mounts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import factor_factory.console.container_agent_adapter as module

    config = _config(tmp_path)
    invocation = _invocation(tmp_path, config)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    _patch_research_session_dependencies(
        module=module, adapter=adapter, monkeypatch=monkeypatch
    )
    monkeypatch.setattr(module.subprocess, "Popen", _FakePopen)

    def sticky_inspect(command, **_kwargs):
        labels = {
            "factorforge.console.managed": "true",
            "factorforge.console.installation": config.installation_id,
            "factorforge.research-org.session": "true",
            "factorforge.research-org.runtime": invocation.runtime_instance_id,
        }
        if "--format" in command:
            return _CompletedProcess(0, stdout=json.dumps(labels))
        return _CompletedProcess(0, stdout="still-present")

    monkeypatch.setattr(module.subprocess, "run", sticky_inspect)
    monkeypatch.setattr(adapter, "_stop_container", lambda _runtime_id: True)

    outcome = adapter.run_research_org_session(invocation)

    assert outcome.returncode == 1
    assert outcome.adapter_receipt["receipt_type"] == "FAILED"
    assert outcome.adapter_receipt["outcome"]["termination_confirmed"] is False
    assert "BLOCK_FACTORFORGE_CONSOLE_AGENT_ORPHANED_WRITER" in outcome.stderr_tail
    assert (invocation.private_attempt_root / "home").is_dir()
    assert (invocation.private_attempt_root / "agent").is_dir()
    assert invocation.runtime_instance_id in adapter._active
