from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.container_agent_adapter import (
    ContainerizedOpenClawResearchAgentAdapter,
)
from factor_factory.research_org import ResearchOrgSessionInvocation


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


def _invocation(tmp_path: Path, config: ConsoleConfig) -> ResearchOrgSessionInvocation:
    worktree = config.source_repo
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
    assert stop_calls == []


def test_targeted_cancel_stops_only_bound_runtime(tmp_path: Path, monkeypatch) -> None:
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
                    "factorforge.console.installation": config.installation_id,
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

    assert adapter.cancel_research_org_session(runtime_id) is True
    assert stop_calls == [runtime_id]
