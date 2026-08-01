from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from factor_factory.console.agent_adapter import (
    BLOCK_AGENT_RUNTIME_FAILED,
    BLOCK_AGENT_RUNTIME_TIMEOUT,
    BLOCK_AGENT_RUNTIME_UNAVAILABLE,
    AgentRunResult,
    build_agent_prompt,
    copy_auth_database,
    redact_secrets,
    validate_auth_database,
)
from factor_factory.console.config import ConsoleConfig
from factor_factory.console.models import ResearchJob
from factor_factory.console.store import utc_now


REQUIRED_CONTAINER_TOOLS = ["read", "edit", "write", "apply_patch", "exec", "process"]
REQUIRED_PROXY_URL = "http://172.29.0.1:3128"
REQUIRED_MODEL_BROKER_URL = "http://172.29.0.1:8781"
DATA_API_BRIDGE_RELATIVE = Path("deploy/factorforge-console/data-api-bridge")


@dataclass(frozen=True)
class _AwsCredentialLease:
    access_key: str
    secret_key: str
    token: str
    expires_at: datetime
    method: str
    caller_arn: str


class ContainerizedOpenClawResearchAgentAdapter:
    """Run one OpenClaw local agent in one disposable container per factor task."""

    def __init__(self, config: ConsoleConfig) -> None:
        self.config = config
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def validate_ready(self) -> str:
        validate_auth_database(
            self.config.openclaw_auth_seed_db,
            provider=self.config.openclaw_auth_provider,
            label="credential seed",
        )
        template = self.config.openclaw_profile_template
        if template is None or template.is_symlink() or not template.is_file():
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: OpenClaw profile template is missing")
        try:
            payload = json.loads(template.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: OpenClaw profile template is invalid") from exc
        _validate_profile_policy(
            payload,
            expected_model_broker_url=self.config.container_model_broker_url,
        )
        if self.config.data_api_pythonpath is not None:
            self._data_api_package_root()
        self._run_runtime(
            [self.config.container_runtime, "image", "inspect", self.config.agent_container_image],
            timeout=30,
            label="agent container image",
        )
        network_output = self._run_runtime(
            [self.config.container_runtime, "network", "inspect", self.config.container_network],
            timeout=30,
            label="agent egress network",
        )
        try:
            network = json.loads(network_output)[0]
            subnets = {
                str(item.get("Subnet") or "")
                for item in ((network.get("IPAM") or {}).get("Config") or [])
                if isinstance(item, dict)
            }
        except (IndexError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent egress network metadata is invalid"
            ) from exc
        if (
            str(network.get("Name") or "") != self.config.container_network
            or network.get("Internal") is True
            or network.get("EnableIPv6") is True
            or self.config.container_network_subnet not in subnets
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent egress network policy is invalid"
            )
        self._reconcile_stale_containers()
        self._reconcile_orphan_credentials()
        if self.config.data_catalogs and not self.config.auth_disabled:
            _load_aws_credentials(self.config.aws_readonly_role_name)
        self._validate_egress_policy()
        if self.config.data_catalogs and not self.config.auth_disabled:
            self._validate_data_api_read_smoke()
        return f"container:{self.config.agent_container_image}"

    def stop_all(self) -> None:
        with self._lock:
            names = list(self._active)
        for name in names:
            self._stop_container(name)

    def healthcheck(self) -> bool:
        proxy = urlsplit(self.config.container_proxy_url)
        model_broker = urlsplit(self.config.container_model_broker_url)
        try:
            validate_auth_database(
                self.config.openclaw_auth_seed_db,
                provider=self.config.openclaw_auth_provider,
                label="credential seed",
            )
            assert self.config.openclaw_profile_template is not None
            _validate_profile_policy(
                json.loads(self.config.openclaw_profile_template.read_text(encoding="utf-8")),
                expected_model_broker_url=self.config.container_model_broker_url,
            )
            if self.config.data_catalogs and not self.config.auth_disabled:
                _load_aws_credentials(self.config.aws_readonly_role_name)
            with socket.create_connection((str(proxy.hostname), int(proxy.port or 0)), timeout=1):
                pass
            with socket.create_connection(
                (str(model_broker.hostname), int(model_broker.port or 0)), timeout=1
            ):
                pass
            proc = subprocess.run(
                [self.config.container_runtime, "info", "--format", "{{.ServerVersion}}"],
                text=True,
                capture_output=True,
                timeout=3,
            )
            image = subprocess.run(
                [self.config.container_runtime, "image", "inspect", self.config.agent_container_image],
                text=True,
                capture_output=True,
                timeout=3,
            )
            network = subprocess.run(
                [self.config.container_runtime, "network", "inspect", self.config.container_network],
                text=True,
                capture_output=True,
                timeout=3,
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return False
        return bool(
            proc.returncode == 0
            and proc.stdout.strip()
            and image.returncode == 0
            and network.returncode == 0
        )

    def run(self, job: ResearchJob, *, worktree: Path, workspace: Path, resume: bool) -> AgentRunResult:
        worktree = worktree.resolve(strict=True)
        workspace = workspace.resolve(strict=True)
        workspace.relative_to(worktree)
        agent_id = job.agent_id or f"factorforge-web-{job.job_id.removeprefix('job_')}"
        session_key = job.agent_session_key or f"agent:{agent_id}:{job.job_id}"
        prompt_path = workspace / "identity" / ("web_agent_resume.md" if resume else "web_agent_task.md")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            build_agent_prompt(job, worktree=worktree, workspace=workspace, config=self.config, resume=resume),
            encoding="utf-8",
        )

        runtime_root, home, agent_dir, profile_config = self._prepare_runtime(job.job_id)
        git_dir = self._prepare_git_view(
            runtime_root=runtime_root,
            worktree=worktree,
            base_commit=job.base_commit,
        )
        auth_store = agent_dir / "openclaw-agent.sqlite"
        validate_auth_database(
            auth_store,
            provider=self.config.openclaw_auth_provider,
            label="container agent credential store",
        )
        container_name = (
            f"ff-console-{self.config.installation_id[:8]}-"
            f"{job.job_id.removeprefix('job_')}"
        )
        common = self._container_prefix(
            container_name=container_name,
            job_id=job.job_id,
            worktree=worktree,
            workspace=workspace,
            runtime_root=runtime_root,
            home=home,
            git_dir=git_dir,
            aws_env_file=None,
            profile_config_readonly=None,
            auth_store_readonly=None,
        )
        model = job.request.model or self.config.openclaw_model
        add_command = [
            *common,
            self.config.openclaw_binary,
            "--profile",
            self.config.openclaw_profile,
            "agents",
            "add",
            agent_id,
            "--workspace",
            str(worktree),
            "--agent-dir",
            str(agent_dir),
            "--model",
            model,
            "--non-interactive",
            "--json",
        ]
        self._run_runtime(add_command, timeout=120, label="container agent initialization", allow_exists=True)
        self._validate_agent_binding(profile_config, agent_id, worktree, agent_dir, model)

        aws_env_file, credential_values = self._prepare_aws_environment(job.job_id)
        research_common = self._container_prefix(
            container_name=container_name,
            job_id=job.job_id,
            worktree=worktree,
            workspace=workspace,
            runtime_root=runtime_root,
            home=home,
            git_dir=git_dir,
            aws_env_file=aws_env_file,
            profile_config_readonly=profile_config,
            auth_store_readonly=auth_store,
        )
        command = [
            *research_common,
            self.config.openclaw_binary,
            "--profile",
            self.config.openclaw_profile,
            "agent",
            "--local",
            "--agent",
            agent_id,
            "--session-key",
            session_key,
            "--message-file",
            str(prompt_path),
            "--thinking",
            self.config.openclaw_thinking,
            "--timeout",
            str(self.config.agent_timeout_seconds),
            "--json",
        ]
        started = utc_now()
        with self._lock:
            self._active.add(container_name)
        try:
            proc = subprocess.run(
                command,
                cwd=worktree,
                text=True,
                capture_output=True,
                timeout=self.config.agent_timeout_seconds + 90,
            )
            returncode = proc.returncode
            stdout = redact_secrets(proc.stdout, extra_values=credential_values)
            stderr = redact_secrets(proc.stderr, extra_values=credential_values)
            error_code = "" if returncode == 0 else BLOCK_AGENT_RUNTIME_FAILED
        except FileNotFoundError as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.container_runtime}") from exc
        except subprocess.TimeoutExpired as exc:
            if not self._stop_container(container_name):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: timed-out agent container could not be removed"
                ) from exc
            stdout = redact_secrets(_as_text(exc.stdout), extra_values=credential_values)
            stderr = redact_secrets(_as_text(exc.stderr), extra_values=credential_values)
            returncode = 124
            error_code = BLOCK_AGENT_RUNTIME_TIMEOUT
        finally:
            if aws_env_file is not None:
                aws_env_file.unlink(missing_ok=True)
            with self._lock:
                self._active.discard(container_name)

        finished = utc_now()
        result_path = self.config.state_root / "jobs" / job.job_id / f"agent_run_{_stamp(finished)}.json"
        payload: dict[str, Any] = {
            "version": "factorforge_console_agent_run_v1",
            "execution_mode": "container",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "agent_id": agent_id,
            "session_key_sha256": hashlib.sha256(session_key.encode("utf-8")).hexdigest(),
            "resume": resume,
            "started_at_utc": started,
            "finished_at_utc": finished,
            "returncode": returncode,
            "error_code": error_code,
            "stdout_tail": stdout[-16_000:],
            "stderr_tail": stderr[-16_000:],
        }
        _write_private_json(result_path, payload)
        return AgentRunResult(
            returncode=returncode,
            agent_id=agent_id,
            session_key=session_key,
            started_at_utc=started,
            finished_at_utc=finished,
            stdout_tail=str(payload["stdout_tail"]),
            stderr_tail=str(payload["stderr_tail"]),
            result_path=str(result_path),
        )

    def _prepare_runtime(self, job_id: str) -> tuple[Path, Path, Path, Path]:
        runtime_root = self.config.state_root / "jobs" / job_id / "container-agent"
        home = runtime_root / "home"
        agent_dir = runtime_root / "agent"
        profile_dir = home / f".openclaw-{self.config.openclaw_profile}"
        for path in (runtime_root, home, agent_dir, profile_dir):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        profile_config = profile_dir / "openclaw.json"
        if not profile_config.exists():
            assert self.config.openclaw_profile_template is not None
            shutil.copy2(self.config.openclaw_profile_template, profile_config)
            profile_config.chmod(0o600)
        try:
            _validate_profile_policy(
                json.loads(profile_config.read_text(encoding="utf-8")),
                expected_model_broker_url=self.config.container_model_broker_url,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: per-task OpenClaw profile is invalid"
            ) from exc
        auth_store = agent_dir / "openclaw-agent.sqlite"
        if not auth_store.exists():
            assert self.config.openclaw_auth_seed_db is not None
            copy_auth_database(self.config.openclaw_auth_seed_db, auth_store)
            auth_store.chmod(0o600)
        return runtime_root, home, agent_dir, profile_config

    def _prepare_git_view(self, *, runtime_root: Path, worktree: Path, base_commit: str) -> Path:
        commit = base_commit.strip().lower()
        if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: task base commit is invalid")
        git_dir = runtime_root / "engine.git"
        if git_dir.exists():
            if git_dir.is_symlink() or not git_dir.is_dir():
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: per-task Git view is invalid"
                )
            self._validate_git_view(git_dir=git_dir, worktree=worktree, base_commit=commit)
            return git_dir

        temporary = runtime_root / f".engine.git-{uuid.uuid4().hex}"
        try:
            self._run_host_git(
                ["git", "init", "--bare", str(temporary)],
                timeout=30,
                label="per-task Git view initialization",
            )
            self._run_host_git(
                [
                    "git",
                    f"--git-dir={temporary}",
                    "fetch",
                    "--no-tags",
                    "--depth=1",
                    worktree.as_uri(),
                    commit,
                ],
                timeout=120,
                label="per-task Git view fetch",
            )
            self._run_host_git(
                [
                    "git",
                    f"--git-dir={temporary}",
                    "update-ref",
                    "--no-deref",
                    "HEAD",
                    commit,
                ],
                timeout=30,
                label="per-task Git view HEAD binding",
            )
            self._run_host_git(
                ["git", "read-tree", commit],
                timeout=30,
                label="per-task Git view index",
                env={
                    "GIT_DIR": str(temporary),
                    "GIT_WORK_TREE": str(worktree),
                    "GIT_OPTIONAL_LOCKS": "0",
                },
            )
            temporary.replace(git_dir)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        self._validate_git_view(git_dir=git_dir, worktree=worktree, base_commit=commit)
        return git_dir

    def _validate_git_view(self, *, git_dir: Path, worktree: Path, base_commit: str) -> None:
        output = self._run_host_git(
            ["git", "rev-parse", "HEAD"],
            timeout=30,
            label="per-task Git view validation",
            env={
                "GIT_DIR": str(git_dir),
                "GIT_WORK_TREE": str(worktree),
                "GIT_OPTIONAL_LOCKS": "0",
            },
        )
        if output.strip().lower() != base_commit:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: per-task Git view commit mismatch"
            )

    @staticmethod
    def _run_host_git(
        command: list[str],
        *,
        timeout: int,
        label: str,
        env: dict[str, str] | None = None,
    ) -> str:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        try:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout,
                env=process_env,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} failed") from exc
        if proc.returncode != 0:
            detail = redact_secrets(proc.stderr or proc.stdout)[-1200:]
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} failed: {detail}"
            )
        return proc.stdout

    def _container_prefix(
        self,
        *,
        container_name: str,
        job_id: str,
        worktree: Path,
        workspace: Path,
        runtime_root: Path,
        home: Path,
        git_dir: Path,
        aws_env_file: Path | None,
        profile_config_readonly: Path | None,
        auth_store_readonly: Path | None,
    ) -> list[str]:
        command = [
            self.config.container_runtime,
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            "factorforge.console=research-agent",
            "--label",
            "factorforge.console.managed=true",
            "--label",
            f"factorforge.console.job={job_id}",
            "--label",
            f"factorforge.console.installation={self.config.installation_id}",
            "--network",
            self.config.container_network,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit",
            str(self.config.container_pids_limit),
            "--memory",
            self.config.container_memory,
            "--cpus",
            str(self.config.container_cpus),
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,size={self.config.container_tmpfs_size}",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            _mount(worktree, readonly=True),
            "--mount",
            _mount(workspace, readonly=False),
            "--mount",
            _mount(runtime_root, readonly=False),
            "--mount",
            _mount(git_dir, readonly=True),
            "--env",
            f"HOME={home}",
            "--env",
            f"FACTORFORGE_ROOT={worktree}",
            "--env",
            f"FACTORFORGE_FACTOR_WORKSPACE={workspace}",
            "--env",
            f"GIT_DIR={git_dir}",
            "--env",
            f"GIT_WORK_TREE={worktree}",
            "--env",
            "GIT_OPTIONAL_LOCKS=0",
            "--env",
            "PYTHONUNBUFFERED=1",
            "--env",
            "AWS_EC2_METADATA_DISABLED=true",
            "--env",
            f"HTTP_PROXY={self.config.container_proxy_url}",
            "--env",
            f"HTTPS_PROXY={self.config.container_proxy_url}",
            "--env",
            f"http_proxy={self.config.container_proxy_url}",
            "--env",
            f"https_proxy={self.config.container_proxy_url}",
            "--env",
            f"NO_PROXY={urlsplit(self.config.container_model_broker_url).hostname}",
            "--env",
            f"no_proxy={urlsplit(self.config.container_model_broker_url).hostname}",
        ]
        if aws_env_file is not None:
            command.extend(["--env-file", str(aws_env_file)])
        if profile_config_readonly is not None:
            command.extend(["--mount", _mount(profile_config_readonly, readonly=True)])
        if auth_store_readonly is not None:
            command.extend(["--mount", _mount(auth_store_readonly, readonly=True)])
        python_paths = [str(worktree)]
        if self.config.data_api_pythonpath:
            data_api_package = self._data_api_package_root()
            bridge_root = worktree / DATA_API_BRIDGE_RELATIVE
            command.extend(["--mount", _mount(data_api_package, readonly=True)])
            command.extend(
                ["--env", f"FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT={data_api_package}"]
            )
            python_paths.insert(0, str(bridge_root))
        mounted_data_roots: set[Path] = set()
        if self.config.data_catalogs:
            command.extend(["--env", f"FACTORFORGE_STATE_CATALOG={self.config.data_catalogs[0]}"])
            command.extend(["--env", f"FACTORFORGE_DATA_CATALOG={self.config.data_catalogs[0]}"])
            for catalog in self.config.data_catalogs:
                root = catalog.parent.parent if catalog.parent.name == "catalogs" else catalog.parent
                if root not in mounted_data_roots:
                    command.extend(["--mount", _mount(root, readonly=True)])
                    mounted_data_roots.add(root)
        command.extend(["--env", f"PYTHONPATH={os.pathsep.join(python_paths)}"])
        for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
            if os.getenv(key):
                command.extend(["--env", f"{key}={os.environ[key]}"])
        command.extend(["--workdir", str(worktree), self.config.agent_container_image])
        return command

    def _data_api_package_root(self) -> Path:
        configured = self.config.data_api_pythonpath
        if configured is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API package root is missing"
            )
        package_root = configured / "factor_factory" / "data_api"
        try:
            resolved = package_root.resolve(strict=True)
            resolved.relative_to(configured.resolve(strict=True))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API package root is invalid"
            ) from exc
        if resolved.is_symlink() or not resolved.is_dir() or not (resolved / "__init__.py").is_file():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API package root is invalid"
            )
        return resolved

    def _prepare_aws_environment(self, job_id: str) -> tuple[Path | None, tuple[str, ...]]:
        try:
            credentials = _load_aws_credentials(self.config.aws_readonly_role_name)
        except RuntimeError:
            if self.config.data_catalogs and not self.config.auth_disabled:
                raise
            return None, ()
        credential_root = self.config.state_root / "credential-leases"
        credential_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        credential_root.chmod(0o700)
        env_path = credential_root / f"{job_id}.env"
        if env_path.exists() or env_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: task credential lease already exists"
            )
        lines = [
            f"AWS_ACCESS_KEY_ID={credentials.access_key}",
            f"AWS_SECRET_ACCESS_KEY={credentials.secret_key}",
            f"AWS_SESSION_TOKEN={credentials.token}",
            f"AWS_CREDENTIAL_EXPIRATION={credentials.expires_at.isoformat()}",
        ]
        descriptor = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, ("\n".join(lines) + "\n").encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return env_path, (
            credentials.access_key,
            credentials.secret_key,
            credentials.token,
        )

    def _validate_agent_binding(
        self,
        profile_config: Path,
        agent_id: str,
        worktree: Path,
        agent_dir: Path,
        model: str,
    ) -> None:
        try:
            payload = json.loads(profile_config.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent profile config is unreadable") from exc
        agents = ((payload.get("agents") or {}).get("list") or []) if isinstance(payload, dict) else []
        match = next((item for item in agents if str(item.get("id") or "") == agent_id), None)
        if not isinstance(match, dict) or len(agents) != 1:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent binding is missing")
        expected = {"workspace": worktree, "agentDir": agent_dir}
        for key, path in expected.items():
            actual = str(match.get(key) or "")
            if not actual or Path(actual).resolve() != path.resolve():
                raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent {key} binding mismatch")
        if str(match.get("model") or "") != model:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent model binding mismatch")

    def _run_runtime(
        self,
        command: list[str],
        *,
        timeout: int,
        label: str,
        allow_exists: bool = False,
    ) -> str:
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.container_runtime}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} timed out") from exc
        detail = proc.stderr or proc.stdout
        if proc.returncode != 0 and not (allow_exists and "already exists" in detail.lower()):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} failed: {redact_secrets(detail)[-1200:]}"
            )
        return proc.stdout

    def _stop_container(self, name: str) -> bool:
        try:
            stop = subprocess.run(
                [self.config.container_runtime, "stop", "--time", "10", name],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            remove = subprocess.run(
                [self.config.container_runtime, "rm", "-f", name],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            inspect = subprocess.run(
                [self.config.container_runtime, "inspect", name],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        stop_missing = "no such container" in (stop.stderr + stop.stdout).lower()
        remove_missing = "no such container" in (remove.stderr + remove.stdout).lower()
        stop_ok = stop.returncode == 0 or stop_missing
        remove_ok = remove.returncode == 0 or remove_missing
        return stop_ok and remove_ok and inspect.returncode != 0

    def _reconcile_stale_containers(self) -> None:
        output = self._run_runtime(
            [
                self.config.container_runtime,
                "ps",
                "-aq",
                "--filter",
                "label=factorforge.console.managed=true",
                "--filter",
                f"label=factorforge.console.installation={self.config.installation_id}",
            ],
            timeout=30,
            label="stale agent container inventory",
        )
        for container_id in output.splitlines():
            value = container_id.strip()
            if value and not self._stop_container(value):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: stale agent container could not be removed"
                )
        remaining = self._run_runtime(
            [
                self.config.container_runtime,
                "ps",
                "-aq",
                "--filter",
                "label=factorforge.console.managed=true",
                "--filter",
                f"label=factorforge.console.installation={self.config.installation_id}",
            ],
            timeout=30,
            label="post-reconciliation agent container inventory",
        )
        if remaining.strip():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: stale agent containers remain after reconciliation"
            )

    def _reconcile_orphan_credentials(self) -> None:
        root = self.config.state_root / "credential-leases"
        if not root.exists():
            return
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: credential lease root is unsafe"
            )
        for candidate in root.iterdir():
            if candidate.is_symlink() or not candidate.is_file() or candidate.suffix != ".env":
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: unexpected credential lease entry"
                )
            candidate.unlink()

    def _validate_egress_policy(self) -> None:
        script = r"""
import json
import sys
import urllib.error
import urllib.request

mode, url = sys.argv[1], sys.argv[2]
opener = (
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if mode in {"blocked-direct", "allowed-model"}
    else urllib.request.build_opener()
)
reached_remote = False
valid_identity = False
try:
    with opener.open(url, timeout=8) as response:
        reached_remote = 100 <= int(response.status) < 600
        headers = {key.lower(): value for key, value in response.headers.items()}
        if mode == "allowed-model":
            payload = json.loads(response.read(4096))
            valid_identity = response.status == 200 and payload.get("service") == "factorforge-model-broker"
        elif mode == "allowed-s3":
            valid_identity = bool(headers.get("x-amz-request-id") or headers.get("x-amz-id-2"))
except urllib.error.HTTPError as error:
    reached_remote = True
    headers = {key.lower(): value for key, value in error.headers.items()}
    if mode == "allowed-s3":
        valid_identity = bool(headers.get("x-amz-request-id") or headers.get("x-amz-id-2"))
except Exception:
    reached_remote = False
if mode in {"allowed-model", "allowed-s3"}:
    accepted = reached_remote and valid_identity
else:
    accepted = not reached_remote
raise SystemExit(0 if accepted else 1)
"""
        probes = (
            ("allowed-model", f"{self.config.container_model_broker_url}/healthz"),
            (
                "allowed-s3",
                "https://yufan-data-lake.s3.ap-southeast-1.amazonaws.com",
            ),
            ("blocked-proxy", "https://api.deepseek.com"),
            ("blocked-proxy", "https://example.com"),
            ("blocked-direct", "https://example.com"),
            ("blocked-direct", "http://169.254.169.254/latest/meta-data/"),
        )
        for mode, url in probes:
            self._run_runtime(
                [
                    self.config.container_runtime,
                    "run",
                    "--rm",
                    "--network",
                    self.config.container_network,
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--label",
                    "factorforge.console.managed=true",
                    "--label",
                    f"factorforge.console.installation={self.config.installation_id}",
                    "--env",
                    f"HTTP_PROXY={self.config.container_proxy_url}",
                    "--env",
                    f"HTTPS_PROXY={self.config.container_proxy_url}",
                    "--env",
                    f"NO_PROXY={urlsplit(self.config.container_model_broker_url).hostname}",
                    self.config.agent_container_image,
                    "python3",
                    "-c",
                    script,
                    mode,
                    url,
                ],
                timeout=20,
                label=f"egress policy probe {mode}",
            )

    def _validate_data_api_read_smoke(self) -> None:
        if not self.config.data_catalogs or self.config.data_api_pythonpath is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API readiness inputs are missing"
            )
        catalog = self.config.data_catalogs[0]
        data_api_package = self._data_api_package_root()
        bridge_root = self.config.source_repo / DATA_API_BRIDGE_RELATIVE
        catalog_root = catalog.parent.parent if catalog.parent.name == "catalogs" else catalog.parent
        env_file, _ = self._prepare_aws_environment("readiness")
        if env_file is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API readiness credentials are missing"
            )
        script = r"""
import json
from factor_factory.data_api.client import DataApiClient
from factor_factory.data_api.query import DataQuery

catalog_path = __import__('os').environ['FACTORFORGE_STATE_CATALOG']
client = DataApiClient.from_catalog(catalog_path)
datasets = client.list_datasets()
if 'clean_daily_bar' not in datasets:
    raise SystemExit(2)
result = client.fetch(
    DataQuery('clean_daily_bar', '20260624', '20260624', 'a_share_all', ['close'], 'daily')
)
if result.status not in {'ready', 'proxy_ready'} or len(result.frame) < 1:
    raise SystemExit(3)
print(json.dumps({'status': 'PASS', 'dataset_count': len(datasets), 'row_count': len(result.frame)}))
"""
        container_name = f"ff-console-{self.config.installation_id[:8]}-data-readiness"
        command = [
            self.config.container_runtime,
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            "factorforge.console.managed=true",
            "--label",
            f"factorforge.console.installation={self.config.installation_id}",
            "--network",
            self.config.container_network,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit",
            "256",
            "--memory",
            "2g",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=1g",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            _mount(self.config.source_repo, readonly=True),
            "--mount",
            _mount(data_api_package, readonly=True),
            "--mount",
            _mount(catalog_root, readonly=True),
            "--env-file",
            str(env_file),
            "--env",
            f"PYTHONPATH={bridge_root}{os.pathsep}{self.config.source_repo}",
            "--env",
            f"FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT={data_api_package}",
            "--env",
            f"FACTORFORGE_STATE_CATALOG={catalog}",
            "--env",
            f"FACTORFORGE_DATA_CATALOG={catalog}",
            "--env",
            "AWS_REGION=ap-southeast-1",
            "--env",
            "AWS_DEFAULT_REGION=ap-southeast-1",
            "--env",
            "AWS_EC2_METADATA_DISABLED=true",
            "--env",
            f"HTTP_PROXY={self.config.container_proxy_url}",
            "--env",
            f"HTTPS_PROXY={self.config.container_proxy_url}",
            "--env",
            f"NO_PROXY={urlsplit(self.config.container_model_broker_url).hostname}",
            "--env",
            "HOME=/tmp",
            self.config.agent_container_image,
            "python3",
            "-c",
            script,
        ]
        try:
            self._run_runtime(command, timeout=180, label="Data API container read smoke")
        finally:
            env_file.unlink(missing_ok=True)


def _mount(path: Path, *, readonly: bool) -> str:
    mode = ",readonly" if readonly else ""
    return f"type=bind,src={path},dst={path}{mode}"


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _stamp(value: str) -> str:
    return value.replace(":", "").replace("-", "")


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


def _load_aws_credentials(expected_role_name: str) -> _AwsCredentialLease:
    try:
        import botocore.session

        session = botocore.session.get_session()
        credentials = session.get_credentials()
        if credentials is None:
            raise RuntimeError("credentials unavailable")
        frozen = credentials.get_frozen_credentials()
        expiry = getattr(credentials, "_expiry_time", None)
        method = str(getattr(credentials, "method", "") or "")
        identity = session.create_client("sts").get_caller_identity()
    except Exception as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: scoped AWS credentials are unavailable"
        ) from exc
    access_key = str(frozen.access_key or "")
    secret_key = str(frozen.secret_key or "")
    token = str(frozen.token or "")
    caller_arn = str(identity.get("Arn") or "") if isinstance(identity, dict) else ""
    if isinstance(expiry, str):
        try:
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            expiry = None
    if isinstance(expiry, datetime) and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    expected_arn_token = f":assumed-role/{expected_role_name}/"
    if (
        not access_key
        or not secret_key
        or not token
        or not isinstance(expiry, datetime)
        or expiry <= now + timedelta(minutes=5)
        or expiry > now + timedelta(hours=12, minutes=5)
        or method not in {"iam-role", "container-role"}
        or not expected_role_name
        or expected_arn_token not in caller_arn
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: AWS credentials are not a pinned temporary role lease"
        )
    return _AwsCredentialLease(
        access_key=access_key,
        secret_key=secret_key,
        token=token,
        expires_at=expiry,
        method=method,
        caller_arn=caller_arn,
    )


def _validate_profile_policy(
    payload: object,
    *,
    expected_model_broker_url: str = REQUIRED_MODEL_BROKER_URL,
) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container profile is not an object")
    defaults = ((payload.get("agents") or {}).get("defaults") or {})
    tools = payload.get("tools") or {}
    plugins = payload.get("plugins") or {}
    providers = ((payload.get("models") or {}).get("providers") or {})
    if defaults.get("skipBootstrap") is not True or defaults.get("skills") != []:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container profile must skip bootstrap and global skills"
        )
    if tools.get("allow") != REQUIRED_CONTAINER_TOOLS:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container tool allowlist is invalid")
    if (
        (tools.get("fs") or {}).get("workspaceOnly") is not True
        or (tools.get("exec") or {}).get("mode") != "full"
        or ((tools.get("exec") or {}).get("applyPatch") or {}).get("workspaceOnly") is not True
        or (tools.get("elevated") or {}).get("enabled") is not False
        or (tools.get("agentToAgent") or {}).get("enabled") is not False
        or (tools.get("sessions") or {}).get("visibility") != "self"
    ):
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container tool policy is invalid")
    if plugins.get("allow") != []:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container plugin policy is invalid")
    if set(providers) != {"deepseek"}:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container model provider policy is invalid")
    deepseek = providers.get("deepseek") or {}
    if deepseek.get("baseUrl") != expected_model_broker_url:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container model endpoint is invalid")
    if deepseek.get("request") not in (None, {}):
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container model request policy is invalid")
