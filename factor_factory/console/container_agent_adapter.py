from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import stat
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
from factor_factory.console.model_broker import (
    ACTIVE_SECRET_REGISTRY_NAME,
    read_private_token_file,
)
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
        broker_client_token = self._broker_client_token()
        validate_auth_database(
            self.config.openclaw_auth_seed_db,
            provider=self.config.openclaw_auth_provider,
            label="credential seed",
            expected_key=broker_client_token,
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
            _load_aws_credentials(
                self.config.aws_readonly_role_name,
                self.config.aws_host_role_name,
                self.config.aws_account_id,
            )
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
                expected_key=self._broker_client_token(),
            )
            assert self.config.openclaw_profile_template is not None
            _validate_profile_policy(
                json.loads(self.config.openclaw_profile_template.read_text(encoding="utf-8")),
                expected_model_broker_url=self.config.container_model_broker_url,
            )
            if self.config.data_api_pythonpath is not None:
                self._data_api_package_root()
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
            expected_key=self._broker_client_token(),
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

        aws_env_file, credential_values, denied_secret_file = self._prepare_aws_environment(
            job.job_id
        )
        try:
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
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.container_runtime}"
                ) from exc
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
                with self._lock:
                    self._active.discard(container_name)
        finally:
            # Keep the exact denied-value registry until the runner has
            # validated and published the task's public evidence set.
            self._cleanup_aws_environment(aws_env_file, None)

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

    def _broker_client_token(self) -> str:
        try:
            return read_private_token_file(
                self.config.model_broker_client_token_file,
                label="model broker client token",
                require_owner=False,
            )
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: model broker client token is unavailable"
            ) from exc

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
            "--dns",
            "127.0.0.1",
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
        if self.config.data_api_commit:
            checkout = configured.resolve(strict=True)
            try:
                head = self._run_host_git(
                    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                    timeout=30,
                    label="Data API commit validation",
                ).strip().lower()
                top = Path(
                    self._run_host_git(
                        ["git", "-C", str(checkout), "rev-parse", "--show-toplevel"],
                        timeout=30,
                        label="Data API checkout validation",
                    ).strip()
                ).resolve(strict=True)
                dirty = self._run_host_git(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "status",
                        "--porcelain=v1",
                        "--untracked-files=all",
                    ],
                    timeout=30,
                    label="Data API cleanliness validation",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API checkout cannot be verified"
                ) from exc
            if top != checkout or head != self.config.data_api_commit or dirty.strip():
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API checkout is not the pinned clean commit"
                )
        return resolved

    def _prepare_aws_environment(
        self,
        job_id: str,
    ) -> tuple[Path | None, tuple[str, ...], Path | None]:
        credentials: _AwsCredentialLease | None = None
        try:
            credentials = _load_aws_credentials(
                self.config.aws_readonly_role_name,
                self.config.aws_host_role_name,
                self.config.aws_account_id,
            )
        except RuntimeError:
            if self.config.data_catalogs and not self.config.auth_disabled:
                raise
        broker_client_token = self._broker_client_token()
        env_path: Path | None = None
        secret_values = (broker_client_token,)
        if credentials is not None:
            if credentials.expires_at <= datetime.now(timezone.utc) + timedelta(
                seconds=self.config.agent_timeout_seconds + 120
            ):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: AWS lease is too short for the task timeout"
                )
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
            secret_values = (
                broker_client_token,
                credentials.access_key,
                credentials.secret_key,
                credentials.token,
            )
        scan_root = self.config.model_broker_secret_scan_root
        scan_path = scan_root / f"{self.config.installation_id}.{job_id}.secrets"
        scan_existed = scan_path.exists() or scan_path.is_symlink()
        try:
            if (
                scan_root.is_symlink()
                or not scan_root.is_dir()
                or scan_root.stat().st_mode & 0o007
            ):
                raise RuntimeError("model broker denied-secret root is unsafe")
            existing_values = _read_denied_secret_file(scan_path) if scan_existed else ()
            merged_values = tuple(dict.fromkeys((*existing_values, *secret_values)))
            values_to_write = tuple(value for value in merged_values if value not in existing_values)
            payload = (
                ("\n".join(values_to_write) + "\n").encode("utf-8")
                if values_to_write
                else b""
            )
            existing_size = scan_path.stat().st_size if scan_existed else 0
            if existing_size + len(payload) > 64 * 1024:
                raise RuntimeError("model broker denied-secret registry is too large")
            flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
            if scan_existed:
                flags |= os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
            else:
                flags |= os.O_CREAT | os.O_EXCL
            scan_descriptor = os.open(scan_path, flags, 0o640)
            try:
                offset = 0
                while offset < len(payload):
                    offset += os.write(scan_descriptor, payload[offset:])
                os.fsync(scan_descriptor)
            finally:
                os.close(scan_descriptor)
            scan_path.chmod(0o640)
            _activate_denied_secret_registry(scan_path)
        except (OSError, RuntimeError) as exc:
            if env_path is not None:
                env_path.unlink(missing_ok=True)
            if not scan_existed:
                scan_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: model broker secret scanner registration failed"
            ) from exc
        return env_path, merged_values, scan_path

    @staticmethod
    def _cleanup_aws_environment(env_path: Path | None, scan_path: Path | None) -> None:
        if env_path is not None:
            env_path.unlink(missing_ok=True)
        if scan_path is not None:
            _deactivate_denied_secret_registry(scan_path)
            scan_path.unlink(missing_ok=True)

    def denied_secret_values(self, job_id: str) -> tuple[str, ...]:
        scan_path = self._denied_secret_path(job_id)
        return _read_denied_secret_file(scan_path)

    def clear_denied_secrets(self, job_id: str) -> None:
        self._cleanup_aws_environment(None, self._denied_secret_path(job_id))

    def _denied_secret_path(self, job_id: str) -> Path:
        if not re.fullmatch(r"job_[a-f0-9]{10}", job_id):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: task identity is invalid"
            )
        return (
            self.config.model_broker_secret_scan_root
            / f"{self.config.installation_id}.{job_id}.secrets"
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
        lease_root = self.config.state_root / "credential-leases"
        if lease_root.exists():
            if lease_root.is_symlink() or not lease_root.is_dir() or lease_root.stat().st_mode & 0o007:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: credential lease root is unsafe"
                )
            for candidate in lease_root.iterdir():
                if candidate.is_symlink() or not candidate.is_file() or candidate.suffix != ".env":
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: unexpected credential lease entry"
                    )
                candidate.unlink()

        scan_root = self.config.model_broker_secret_scan_root
        if not scan_root.exists():
            if self.config.data_catalogs and not self.config.auth_disabled:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: model broker denied-secret root is missing"
                )
            return
        if scan_root.is_symlink() or not scan_root.is_dir() or scan_root.stat().st_mode & 0o007:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: model broker denied-secret root is unsafe"
            )
        job_registry = re.compile(
            rf"{re.escape(self.config.installation_id)}\.job_[a-f0-9]{{10}}\.secrets"
        )
        readiness_name = f"{self.config.installation_id}.readiness.secrets"
        active_path = scan_root / ACTIVE_SECRET_REGISTRY_NAME
        active_name = (
            _read_active_denied_secret_registry(active_path)
            if active_path.exists() or active_path.is_symlink()
            else ""
        )
        for candidate in scan_root.iterdir():
            if candidate.name == ACTIVE_SECRET_REGISTRY_NAME:
                continue
            _read_denied_secret_file(candidate)
            if candidate.name == readiness_name:
                if active_name != readiness_name:
                    candidate.unlink()
            elif job_registry.fullmatch(candidate.name) is None:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: unexpected model broker denied-secret entry"
                )
        if active_name:
            if active_name == readiness_name:
                _deactivate_denied_secret_registry(scan_root / readiness_name)
                (scan_root / readiness_name).unlink(missing_ok=True)
            elif job_registry.fullmatch(active_name) is None:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: active model broker registry is invalid"
                )
            else:
                _read_denied_secret_file(scan_root / active_name)

    def _validate_egress_policy(self) -> None:
        script = r"""
import json
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

mode, url, token_path = sys.argv[1], sys.argv[2], sys.argv[3]
if mode == "blocked-dns":
    try:
        socket.getaddrinfo(url, 443)
    except socket.gaierror:
        raise SystemExit(0)
    raise SystemExit(1)
opener = (
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if mode in {"blocked-direct", "allowed-model"}
    else urllib.request.build_opener()
)
reached_remote = False
valid_identity = False
try:
    request = urllib.request.Request(url)
    if mode == "allowed-model":
        request.add_header("Authorization", f"Bearer {Path(token_path).read_text().strip()}")
    with opener.open(request, timeout=8) as response:
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
            (
                "blocked-direct",
                f"http://{urlsplit(self.config.container_model_broker_url).hostname}:22/",
            ),
            ("blocked-dns", "factorforge-console-egress-probe.example.com"),
        )
        readiness_env, _, readiness_registry = self._prepare_aws_environment("readiness")
        try:
            for mode, url in probes:
                self._run_runtime(
                    [
                        self.config.container_runtime,
                        "run",
                        "--rm",
                        "--network",
                        self.config.container_network,
                        "--dns",
                        "127.0.0.1",
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
                        "--mount",
                        _mount(self.config.model_broker_client_token_file, readonly=True),
                        self.config.agent_container_image,
                        "python3",
                        "-c",
                        script,
                        mode,
                        url,
                        str(self.config.model_broker_client_token_file),
                    ],
                    timeout=20,
                    label=f"egress policy probe {mode}",
                )
        finally:
            self._cleanup_aws_environment(readiness_env, readiness_registry)

    def _validate_data_api_read_smoke(self) -> None:
        if not self.config.data_catalogs or self.config.data_api_pythonpath is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API readiness inputs are missing"
            )
        catalog = self.config.data_catalogs[0]
        data_api_package = self._data_api_package_root()
        bridge_root = self.config.source_repo / DATA_API_BRIDGE_RELATIVE
        catalog_root = catalog.parent.parent if catalog.parent.name == "catalogs" else catalog.parent
        env_file, _, denied_secret_file = self._prepare_aws_environment("readiness")
        if env_file is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Data API readiness credentials are missing"
            )
        script = r"""
import json
import os
from pathlib import Path
from factorforge_data_api import DataApiClient, DataQuery
from factorforge_data_api.catalog import resolve_default_catalog_path

catalog_path = os.environ['FACTORFORGE_STATE_CATALOG']
if resolve_default_catalog_path().resolve() != Path(catalog_path).resolve():
    raise SystemExit(4)
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
            "--dns",
            "127.0.0.1",
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
            self._cleanup_aws_environment(env_file, denied_secret_file)


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


def _read_denied_secret_file(path: Path) -> tuple[str, ...]:
    try:
        metadata = path.stat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o007
            or metadata.st_size > 64 * 1024
        ):
            raise RuntimeError("task denied-secret registry is unsafe")
        values = tuple(
            value
            for value in path.read_text(encoding="utf-8").splitlines()
            if len(value) >= 8
        )
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("task denied-secret registry is unsafe") from exc
    if not values:
        raise RuntimeError("task denied-secret registry is empty")
    return values


def _activate_denied_secret_registry(scan_path: Path) -> None:
    if not scan_path.name.endswith(".secrets") or scan_path.parent.is_symlink():
        raise RuntimeError("task denied-secret registry identity is unsafe")
    active_path = scan_path.parent / ACTIVE_SECRET_REGISTRY_NAME
    temporary = scan_path.parent / f".{ACTIVE_SECRET_REGISTRY_NAME}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o640,
    )
    try:
        payload = f"{scan_path.name}\n".encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        temporary.replace(active_path)
        active_path.chmod(0o640)
        _fsync_directory(scan_path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read_active_denied_secret_registry(active_path: Path) -> str:
    try:
        metadata = active_path.stat()
        if (
            active_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o007
            or metadata.st_size > 256
        ):
            raise RuntimeError("active task denied-secret registry is unsafe")
        active_name = active_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("active task denied-secret registry is unsafe") from exc
    if not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{7,62}\.(?:job_[a-f0-9]{10}|readiness)\.secrets",
        active_name,
    ):
        raise RuntimeError("active task denied-secret registry is invalid")
    return active_name


def _deactivate_denied_secret_registry(scan_path: Path) -> None:
    active_path = scan_path.parent / ACTIVE_SECRET_REGISTRY_NAME
    if not active_path.exists() and not active_path.is_symlink():
        return
    if _read_active_denied_secret_registry(active_path) == scan_path.name:
        active_path.unlink()
        _fsync_directory(scan_path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_aws_credentials(
    expected_role_name: str,
    expected_host_role_name: str,
    expected_account_id: str,
) -> _AwsCredentialLease:
    try:
        import botocore.session

        session = botocore.session.get_session()
        source_credentials = session.get_credentials()
        if source_credentials is None:
            raise RuntimeError("source credentials unavailable")
        source_method = str(getattr(source_credentials, "method", "") or "")
        source_sts = session.create_client("sts")
        source_identity = source_sts.get_caller_identity()
        account_id = str(source_identity.get("Account") or "")
        source_arn = str(source_identity.get("Arn") or "")
        if (
            source_method not in {"iam-role", "container-role"}
            or account_id != expected_account_id
            or not re.fullmatch(
                rf"arn:aws:sts::{re.escape(expected_account_id)}:assumed-role/"
                rf"{re.escape(expected_host_role_name)}/[^/]+",
                source_arn,
            )
            or not expected_role_name
            or not expected_host_role_name
            or f":assumed-role/{expected_role_name}/" in source_arn
        ):
            raise RuntimeError("source credentials are not a distinct host role")
        assumed = source_sts.assume_role(
            RoleArn=f"arn:aws:iam::{expected_account_id}:role/{expected_role_name}",
            RoleSessionName=f"factorforge-console-read-{os.getpid()}-{uuid.uuid4().hex[:8]}",
            DurationSeconds=3600,
        )
        raw_credentials = assumed.get("Credentials") if isinstance(assumed, dict) else None
        if not isinstance(raw_credentials, dict):
            raise RuntimeError("assumed credentials unavailable")
        access_key = str(raw_credentials.get("AccessKeyId") or "")
        secret_key = str(raw_credentials.get("SecretAccessKey") or "")
        token = str(raw_credentials.get("SessionToken") or "")
        expiry = raw_credentials.get("Expiration")
        assumed_identity = session.create_client(
            "sts",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=token,
        ).get_caller_identity()
    except Exception as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: scoped AWS credentials are unavailable"
        ) from exc
    caller_arn = str(assumed_identity.get("Arn") or "") if isinstance(assumed_identity, dict) else ""
    if isinstance(expiry, str):
        try:
            expiry = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        except ValueError:
            expiry = None
    if isinstance(expiry, datetime) and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    expected_assumed_arn = re.compile(
        rf"arn:aws:sts::{re.escape(expected_account_id)}:assumed-role/"
        rf"{re.escape(expected_role_name)}/[^/]+"
    )
    if (
        not access_key
        or not secret_key
        or not token
        or not isinstance(expiry, datetime)
        or expiry <= now + timedelta(minutes=5)
        or expiry > now + timedelta(hours=1, minutes=5)
        or not expected_role_name
        or expected_assumed_arn.fullmatch(caller_arn) is None
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: AWS credentials are not a pinned temporary role lease"
        )
    return _AwsCredentialLease(
        access_key=access_key,
        secret_key=secret_key,
        token=token,
        expires_at=expiry,
        method="assume-role",
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
