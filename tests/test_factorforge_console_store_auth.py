from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import sys
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest


def _request(title: str = "Overnight information diffusion"):
    from factor_factory.console.models import ResearchRequest

    return ResearchRequest(
        title=title,
        hypothesis="Information spreads after market close and is reflected in the next opening auction.",
        factor_id_hint=title,
        sample_start="2016-01-01",
        sample_end="2025-07-11",
        transaction_cost_bps=10,
    )


def _auth_seed(path: Path, *, provider: str = "deepseek", profile_type: str = "api_key") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE auth_profile_store (store_key TEXT NOT NULL PRIMARY KEY, store_json TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO auth_profile_store VALUES (?, ?, ?)",
            (
                "primary",
                json.dumps(
                    {
                        "version": 1,
                        "profiles": {
                            f"{provider}:console": {
                                "provider": provider,
                                "type": profile_type,
                                "key": "test-provider-api-key",
                            }
                        },
                    }
                ),
                1,
            ),
        )
    path.chmod(0o600)
    return path


def test_research_request_rejects_unsafe_or_oversized_values():
    from factor_factory.console.models import ResearchRequest

    with pytest.raises(ValueError, match="title is required"):
        ResearchRequest(title="", hypothesis="idea")
    with pytest.raises(ValueError, match="hypothesis is too long"):
        ResearchRequest(title="idea", hypothesis="x" * 20_001)
    with pytest.raises(ValueError, match="source_url"):
        ResearchRequest(title="idea", hypothesis="test", source_url="file:///etc/passwd")
    with pytest.raises(ValueError, match="https"):
        ResearchRequest(title="idea", hypothesis="test", source_url="http://example.com/report")
    with pytest.raises(ValueError, match="local or internal"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://metadata.google.internal/report")
    with pytest.raises(ValueError, match="private or non-global"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://127.0.0.1/report")
    with pytest.raises(ValueError, match="private or non-global"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://127.1/report")
    with pytest.raises(ValueError, match="private or non-global"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://2130706433/report")
    with pytest.raises(ValueError, match="without credentials"):
        ResearchRequest(title="idea", hypothesis="test", source_url="https://user:pass@example.com/report")
    ResearchRequest(title="idea", hypothesis="test", source_url="https://example.com/report")
    with pytest.raises(ValueError, match="between 0 and 200"):
        ResearchRequest(title="idea", hypothesis="test", transaction_cost_bps=201)


def test_research_request_rejects_dns_resolution_to_private_address(monkeypatch):
    import factor_factory.console.models as models

    monkeypatch.setattr(
        models.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (models.socket.AF_INET, models.socket.SOCK_STREAM, 6, "", ("10.2.3.4", 443))
        ],
    )

    with pytest.raises(ValueError, match="private or non-global"):
        models.ResearchRequest(
            title="idea",
            hypothesis="test",
            source_url="https://public-looking.example/report",
        )


def test_job_store_uses_external_sqlite_and_serial_claiming(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    state_root = tmp_path / "console-state"
    store = ResearchJobStore(state_root)
    first = store.create_job(_request("Factor alpha"))
    second = store.create_job(_request("Factor beta"))

    assert store.path == state_root / "console.sqlite3"
    assert first.factor_id == "FACTOR_ALPHA"
    assert first.workspace_path == ""
    assert len(store.list_jobs()) == 2

    claimed = store.claim_next_job()
    assert claimed is not None
    assert claimed.job_id == first.job_id
    assert claimed.execution_status == "ALLOCATING"
    assert store.claim_next_job() is None

    store.update_job(
        first.job_id,
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="REJECT",
        council_status="PASS",
        finished_at_utc="2026-08-01T00:00:00Z",
        result={"summary": "rejected after costs"},
    )
    claimed_second = store.claim_next_job()
    assert claimed_second is not None
    assert claimed_second.job_id == second.job_id

    public = store.get_job(first.job_id).to_dict()
    assert "worktree_path" not in public
    assert "workspace_path" not in public
    assert "agent_session_key" not in public
    assert public["factor_verdict"] == "REJECT"


def test_service_restart_pauses_inflight_job_without_duplicate_queue(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "state")
    job = store.create_job(_request())
    assert store.claim_next_job().job_id == job.job_id
    assert store.pause_interrupted_jobs() == 1
    paused = store.get_job(job.job_id)
    assert paused.execution_status == "REVIEW_REQUIRED"
    assert paused.protocol_status == "PAUSED"
    assert store.claim_next_job() is None

    resumed = store.request_resume(job.job_id)
    assert resumed.execution_status == "QUEUED"
    assert store.claim_next_job().job_id == job.job_id


def test_invite_auth_session_expiry_csrf_and_cookie_flags():
    from factor_factory.console.auth import InviteAuth, SESSION_MAX_AGE_SECONDS

    auth = InviteAuth("invite-pass", "cookie-secret", secure_cookie=True)
    assert auth.password_matches("invite-pass")
    assert not auth.password_matches("wrong")
    token = auth.issue_session(now=1_000)
    assert auth.verify_session(token, now=1_001)
    assert not auth.verify_session(token, now=1_000 + SESSION_MAX_AGE_SECONDS + 1)
    csrf = auth.csrf_token(token)
    assert auth.verify_csrf(token, csrf)
    assert not auth.verify_csrf(token, csrf + "x")
    header = auth.set_cookie_header(token)
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" in header


def test_server_side_session_registration_and_revocation(tmp_path):
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "state")
    token = "signed-session-token-for-test"
    store.register_session(token, max_age_seconds=60)
    assert store.session_is_active(token) is True
    store.revoke_session(token)
    assert store.session_is_active(token) is False


def test_runner_health_socket_binds_queue_to_exact_engine(tmp_path):
    from factor_factory.console.run_service import ResearchQueueService
    from factor_factory.console.runner_health import RunnerHealthSocket
    from factor_factory.console.store import ResearchJobStore

    with tempfile.TemporaryDirectory(prefix="ff-runner-", dir="/tmp") as socket_root:
        socket_path = Path(socket_root) / "health.sock"
        server = RunnerHealthSocket(
            socket_path,
            lambda: {"ok": True, "engine_commit": "a" * 40},
        )
        server.start()
        try:
            store = ResearchJobStore(tmp_path / "state")
            matching = ResearchQueueService(
                store=store,
                runner_health_socket=socket_path,
                expected_engine_commit="a" * 40,
            )
            mismatch = ResearchQueueService(
                store=store,
                runner_health_socket=socket_path,
                expected_engine_commit="b" * 40,
            )
            assert matching.healthcheck() is True
            assert mismatch.healthcheck() is False
        finally:
            server.stop()


def test_auth_database_rejects_sqlite_sidecars(tmp_path):
    from factor_factory.console.agent_adapter import validate_auth_database

    seed = _auth_seed(tmp_path / "seed.sqlite")
    Path(f"{seed}-wal").write_bytes(b"stale")
    with pytest.raises(RuntimeError, match="SQLite sidecars"):
        validate_auth_database(seed, provider="deepseek", label="credential seed")


def test_agent_prompt_binds_exact_workspace_and_read_only_catalog(tmp_path):
    from factor_factory.console.agent_adapter import build_agent_prompt
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.models import ResearchJob

    worktree = tmp_path / "worktree"
    workspace = worktree / "factor_research" / "FACTOR" / "research"
    catalog = tmp_path / "catalog.json"
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        data_catalogs=(catalog,),
        auth_disabled=True,
    )
    job = ResearchJob(
        job_id="job_123",
        factor_id="FACTOR",
        research_id="research",
        report_id="report",
        request=_request(),
    )
    prompt = build_agent_prompt(job, worktree=worktree, workspace=workspace, config=config, resume=False)
    assert str(workspace) in prompt
    assert str(catalog.resolve()) in prompt
    assert "run_factorforge_ultimate_loop.py" in prompt
    assert "Do not run" in prompt
    assert "Data API and catalogs are read-only" in prompt
    assert "never as a broker report" in prompt


def test_agent_readiness_requires_healthy_dedicated_profile(tmp_path, monkeypatch):
    import subprocess

    from factor_factory.console.agent_adapter import OpenClawResearchAgentAdapter
    from factor_factory.console.config import ConsoleConfig

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "health" in command:
            return subprocess.CompletedProcess(command, 0, stdout='{"ok": true, "plugins": {"errors": []}}', stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="Config valid\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_profile="factorforge-console-test",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite"),
        auth_disabled=True,
    )
    assert OpenClawResearchAgentAdapter(config).validate_ready() == "factorforge-console-test"
    assert all(command[:3] == ["openclaw", "--profile", "factorforge-console-test"] for command in calls)


def test_agent_readiness_blocks_plugin_errors(tmp_path, monkeypatch):
    import subprocess

    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE, OpenClawResearchAgentAdapter
    from factor_factory.console.config import ConsoleConfig

    def fake_run(command, **kwargs):
        output = '{"ok": true, "plugins": {"errors": [{"id": "bad"}]}}' if "health" in command else "ok"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite"),
        auth_disabled=True,
    )
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        OpenClawResearchAgentAdapter(config).validate_ready()


def test_agent_readiness_rejects_oauth_seed(tmp_path, monkeypatch):
    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE, OpenClawResearchAgentAdapter
    from factor_factory.console.config import ConsoleConfig

    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite", profile_type="oauth"),
        auth_disabled=True,
    )
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        OpenClawResearchAgentAdapter(config).validate_ready()


def test_auth_seed_rejects_symlink_broad_permissions_and_multiple_profiles(tmp_path):
    from factor_factory.console.agent_adapter import (
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        validate_auth_database,
    )

    broad = _auth_seed(tmp_path / "broad.sqlite")
    broad.chmod(0o644)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        validate_auth_database(broad, provider="deepseek", label="seed")

    target = _auth_seed(tmp_path / "target.sqlite")
    link = tmp_path / "linked.sqlite"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        validate_auth_database(link, provider="deepseek", label="seed")

    multiple = _auth_seed(tmp_path / "multiple.sqlite")
    with sqlite3.connect(multiple) as connection:
        row = connection.execute(
            "SELECT store_json FROM auth_profile_store WHERE store_key = 'primary'"
        ).fetchone()
        payload = json.loads(row[0])
        payload["profiles"]["deepseek:second"] = {
            "provider": "deepseek",
            "type": "api_key",
            "key": "second-test-api-key",
        }
        connection.execute(
            "UPDATE auth_profile_store SET store_json = ? WHERE store_key = 'primary'",
            (json.dumps(payload),),
        )
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        validate_auth_database(multiple, provider="deepseek", label="seed")


def test_console_config_rejects_unknown_thinking_level(tmp_path):
    from factor_factory.console.config import ConsoleConfig

    with pytest.raises(ValueError, match="thinking level"):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            openclaw_thinking="invented",
            auth_disabled=True,
        )


@pytest.mark.parametrize(
    ("invite", "cookie"),
    [
        ("replace-via-secrets-manager", "strong-cookie-secret-2026-with-entropy-value"),
        ("short", "strong-cookie-secret-2026-with-entropy-value"),
        ("strong-invite-secret-2026", "replace-with-random-secret"),
        ("same-secret-value-2026-with-enough-length", "same-secret-value-2026-with-enough-length"),
    ],
)
def test_console_config_rejects_weak_or_placeholder_production_secrets(
    tmp_path,
    invite,
    cookie,
):
    from factor_factory.console.config import ConsoleConfig

    with pytest.raises(ValueError):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            invite_password=invite,
            cookie_secret=cookie,
        )


def test_container_agent_uses_read_only_engine_and_one_writable_workspace(tmp_path, monkeypatch):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import ContainerizedOpenClawResearchAgentAdapter
    from factor_factory.console.models import ResearchJob

    source = tmp_path / "source"
    workspace = source / "factor_research" / "FACTOR" / "research"
    workspace.mkdir(parents=True)
    catalog_root = tmp_path / "data-runtime"
    catalog = catalog_root / "catalogs" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}\n", encoding="utf-8")
    data_api = tmp_path / "data-api"
    data_api_package = data_api / "factor_factory" / "data_api"
    data_api_package.mkdir(parents=True)
    (data_api_package / "__init__.py").write_text("\n", encoding="utf-8")
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        data_catalogs=(catalog,),
        data_api_pythonpath=data_api,
        aws_host_role_name="console-test-host-role",
        openclaw_auth_seed_db=_auth_seed(tmp_path / "seed.sqlite"),
        openclaw_profile_template=(
            Path(__file__).resolve().parents[1] / "deploy" / "factorforge-console" / "openclaw.json.example"
        ),
        container_runtime="docker-test",
        agent_container_image="factorforge-agent:test",
        auth_disabled=True,
    )
    job = ResearchJob(
        job_id="job_123abc",
        factor_id="FACTOR",
        research_id="research",
        report_id="report",
        request=_request(),
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "network" in command and "inspect" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Name": config.container_network,
                            "Internal": False,
                            "EnableIPv6": False,
                            "IPAM": {"Config": [{"Subnet": config.container_network_subnet}]},
                        }
                    ]
                ),
                stderr="",
            )
        if "ps" in command and "-aq" in command:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if "agents" in command and "add" in command:
            profile = (
                config.state_root
                / "jobs"
                / job.job_id
                / "container-agent"
                / "home"
                / ".openclaw-factorforge-console"
                / "openclaw.json"
            )
            payload = json.loads(profile.read_text(encoding="utf-8"))
            payload.setdefault("agents", {})["list"] = [
                {
                    "id": "factorforge-web-123abc",
                    "workspace": str(source.resolve()),
                    "agentDir": str(
                        (
                            config.state_root
                            / "jobs"
                            / job.job_id
                            / "container-agent"
                            / "agent"
                        ).resolve()
                    ),
                    "model": "deepseek/deepseek-reasoner",
                }
            ]
            profile.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout='{"status":"ok"}', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    git_view = config.state_root / "jobs" / job.job_id / "container-agent" / "engine.git"
    git_view.mkdir(parents=True)
    monkeypatch.setattr(adapter, "_prepare_git_view", lambda **_: git_view)
    assert adapter.validate_ready() == "container:factorforge-agent:test"
    result = adapter.run(job, worktree=source, workspace=workspace, resume=False)
    assert result.returncode == 0
    probe_commands = [
        command
        for command in calls
        if len(command) > 1 and command[1] == "run" and "python3" in command
    ]
    assert len(probe_commands) == 7
    assert any("https://example.com" in command for command in probe_commands)
    assert any("169.254.169.254" in " ".join(command) for command in probe_commands)
    assert any("factorforge-console-egress-probe.example.com" in command for command in probe_commands)
    assert all(command[command.index("--dns") + 1] == "127.0.0.1" for command in probe_commands)
    run_commands = [
        command
        for command in calls
        if len(command) > 1 and command[1] == "run" and config.openclaw_binary in command
    ]
    assert len(run_commands) == 2
    research_command = run_commands[-1]
    assert "--read-only" in research_command
    assert "--local" in research_command
    assert research_command[research_command.index("--network") + 1] == config.container_network
    assert research_command[research_command.index("--dns") + 1] == "127.0.0.1"
    assert f"HTTPS_PROXY={config.container_proxy_url}" in research_command
    assert f"NO_PROXY={urlsplit(config.container_model_broker_url).hostname}" in research_command
    assert "AWS_EC2_METADATA_DISABLED=true" in research_command
    assert f"type=bind,src={source.resolve()},dst={source.resolve()},readonly" in research_command
    assert f"type=bind,src={workspace.resolve()},dst={workspace.resolve()}" in research_command
    assert f"type=bind,src={catalog_root.resolve()},dst={catalog_root.resolve()},readonly" in research_command
    assert (
        f"type=bind,src={data_api_package.resolve()},dst={data_api_package.resolve()},readonly"
        in research_command
    )
    assert f"FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT={data_api_package.resolve()}" in research_command
    assert f"FACTORFORGE_DATA_CATALOG={catalog.resolve()}" in research_command
    python_path = next(item for item in research_command if item.startswith("PYTHONPATH="))
    assert str(data_api.resolve()) not in python_path
    assert str(source.resolve() / "deploy" / "factorforge-console" / "data-api-bridge") in python_path
    assert f"type=bind,src={git_view.resolve()},dst={git_view.resolve()},readonly" in research_command
    assert f"GIT_DIR={git_view.resolve()}" in research_command
    assert f"GIT_WORK_TREE={source.resolve()}" in research_command
    assert "GIT_OPTIONAL_LOCKS=0" in research_command
    profile_path = (
        config.state_root
        / "jobs"
        / job.job_id
        / "container-agent"
        / "home"
        / ".openclaw-factorforge-console"
        / "openclaw.json"
    )
    assert f"type=bind,src={profile_path},dst={profile_path},readonly" in research_command
    tmpfs_index = research_command.index("--tmpfs")
    assert research_command[tmpfs_index + 1].startswith("/tmp:rw,nosuid,nodev,size=")


def test_container_agent_git_view_is_shallow_exact_and_reusable(tmp_path):
    import subprocess

    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import ContainerizedOpenClawResearchAgentAdapter

    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "console@example.invalid"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Console Test"], cwd=source, check=True)
    (source / "engine.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "engine.py"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-m", "engine"], cwd=source, check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    runtime_root = config.state_root / "jobs" / "job_git" / "container-agent"
    runtime_root.mkdir(parents=True)

    first = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source.resolve(),
        base_commit=commit,
    )
    second = adapter._prepare_git_view(
        runtime_root=runtime_root,
        worktree=source.resolve(),
        base_commit=commit,
    )
    assert first == second
    assert subprocess.run(
        ["git", f"--git-dir={first}", "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip() == commit
    assert (first / "shallow").is_file()


def test_container_profile_policy_rejects_extra_tools_and_model_endpoint():
    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE
    from factor_factory.console.container_agent_adapter import _validate_profile_policy

    template = Path(__file__).resolve().parents[1] / "deploy" / "factorforge-console" / "openclaw.json.example"
    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["tools"]["allow"].append("browser")
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)

    payload = json.loads(template.read_text(encoding="utf-8"))
    payload["models"]["providers"]["deepseek"]["baseUrl"] = "https://127.0.0.1"
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _validate_profile_policy(payload)


def test_aws_credential_lease_file_stays_outside_container_runtime(tmp_path, monkeypatch):
    import factor_factory.console.container_agent_adapter as adapter_module
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import (
        ContainerizedOpenClawResearchAgentAdapter,
        _AwsCredentialLease,
    )

    scan_root = tmp_path / "broker-scan"
    scan_root.mkdir(mode=0o770)
    config = ConsoleConfig(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        model_broker_secret_scan_root=scan_root,
        auth_disabled=True,
    )
    monkeypatch.setattr(
        adapter_module,
        "_load_aws_credentials",
        lambda _role, _host_role: _AwsCredentialLease(
            access_key="ASIATESTACCESSKEY0000",
            secret_key="temporary-secret-for-test",
            token="temporary-session-token-for-test",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            method="iam-role",
            caller_arn="arn:aws:sts::123456789012:assumed-role/test-role/session",
        ),
    )
    adapter = ContainerizedOpenClawResearchAgentAdapter(config)
    lease_path, values, scan_path = adapter._prepare_aws_environment("job_credential")
    assert lease_path == config.state_root / "credential-leases" / "job_credential.env"
    assert scan_path == scan_root / f"{config.installation_id}.job_credential.secrets"
    assert config.state_root / "jobs" not in lease_path.parents
    assert lease_path.stat().st_mode & 0o077 == 0
    assert scan_path.stat().st_mode & 0o007 == 0
    assert "temporary-session-token-for-test" in values
    assert "temporary-session-token-for-test" in scan_path.read_text(encoding="utf-8")
    adapter._cleanup_aws_environment(lease_path, scan_path)
    assert not lease_path.exists()
    assert not scan_path.exists()


def test_aws_credentials_are_assumed_from_distinct_host_role(monkeypatch):
    from factor_factory.console.container_agent_adapter import _load_aws_credentials

    expected_role = "factorforge-console-pilot-data-read-role"

    class SourceCredentials:
        method = "iam-role"

    class FakeSts:
        def __init__(self, *, assumed: bool = False):
            self.assumed = assumed

        def get_caller_identity(self):
            role = expected_role if self.assumed else "factorforge-console-pilot-host-role"
            return {
                "Account": "123456789012",
                "Arn": f"arn:aws:sts::123456789012:assumed-role/{role}/session",
            }

        def assume_role(self, **kwargs):
            assert kwargs["RoleArn"] == f"arn:aws:iam::123456789012:role/{expected_role}"
            assert kwargs["DurationSeconds"] == 3600
            return {
                "Credentials": {
                    "AccessKeyId": "ASIATEMPORARYKEY0000",
                    "SecretAccessKey": "temporary-secret-for-assume-role-test",
                    "SessionToken": "temporary-session-token-for-assume-role-test",
                    "Expiration": datetime.now(timezone.utc) + timedelta(minutes=59),
                }
            }

    class FakeSession:
        def get_credentials(self):
            return SourceCredentials()

        def create_client(self, service, **kwargs):
            assert service == "sts"
            return FakeSts(assumed=bool(kwargs.get("aws_session_token")))

    session_module = types.ModuleType("botocore.session")
    session_module.get_session = lambda: FakeSession()
    package = types.ModuleType("botocore")
    package.session = session_module
    monkeypatch.setitem(sys.modules, "botocore", package)
    monkeypatch.setitem(sys.modules, "botocore.session", session_module)

    lease = _load_aws_credentials(expected_role, "factorforge-console-pilot-host-role")
    assert lease.method == "assume-role"
    assert lease.caller_arn.endswith(f"assumed-role/{expected_role}/session")
    assert lease.token == "temporary-session-token-for-assume-role-test"


def test_secret_redaction(monkeypatch):
    from factor_factory.console.agent_adapter import redact_secrets

    monkeypatch.setenv("TEST_API_KEY", "super-secret-provider-key")
    raw = json.dumps(
        {
            "api_key": "super-secret-provider-key",
            "authorization": "Bearer sk-example-secret-123456789",
            "aws_access_key_id": "AKIAABCDEFGHIJKLMNOP",
            "aws_secret_access_key": "aws-secret-material-for-test",
        }
    )
    redacted = redact_secrets(raw, extra_values=("aws-secret-material-for-test",))
    assert "super-secret-provider-key" not in redacted
    assert "sk-example-secret-123456789" not in redacted
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "aws-secret-material-for-test" not in redacted
    assert "[REDACTED]" in redacted
