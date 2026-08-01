from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
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
        _validate_profile_policy(payload, expected_proxy_url=self.config.container_proxy_url)
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
        if self.config.data_catalogs and not self.config.auth_disabled:
            credentials = _load_aws_credentials()
            if credentials is None:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: scoped AWS credentials are unavailable"
                )
        self._reconcile_stale_containers()
        self._validate_egress_policy()
        return f"container:{self.config.agent_container_image}"

    def stop_all(self) -> None:
        with self._lock:
            names = list(self._active)
        for name in names:
            self._stop_container(name)

    def healthcheck(self) -> bool:
        proxy = urlsplit(self.config.container_proxy_url)
        try:
            with socket.create_connection((str(proxy.hostname), int(proxy.port or 0)), timeout=1):
                pass
            proc = subprocess.run(
                [self.config.container_runtime, "info", "--format", "{{.ServerVersion}}"],
                text=True,
                capture_output=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0 and bool(proc.stdout.strip())

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
        auth_store = agent_dir / "openclaw-agent.sqlite"
        validate_auth_database(
            auth_store,
            provider=self.config.openclaw_auth_provider,
            label="container agent credential store",
        )
        container_name = f"ff-console-{job.job_id.removeprefix('job_')}"
        common = self._container_prefix(
            container_name=container_name,
            job_id=job.job_id,
            worktree=worktree,
            workspace=workspace,
            runtime_root=runtime_root,
            home=home,
            aws_env_file=None,
            profile_config_readonly=None,
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

        aws_env_file, credential_values = self._prepare_aws_environment(runtime_root)
        research_common = self._container_prefix(
            container_name=container_name,
            job_id=job.job_id,
            worktree=worktree,
            workspace=workspace,
            runtime_root=runtime_root,
            home=home,
            aws_env_file=aws_env_file,
            profile_config_readonly=profile_config,
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
            self._stop_container(container_name)
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
                expected_proxy_url=self.config.container_proxy_url,
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

    def _container_prefix(
        self,
        *,
        container_name: str,
        job_id: str,
        worktree: Path,
        workspace: Path,
        runtime_root: Path,
        home: Path,
        aws_env_file: Path | None,
        profile_config_readonly: Path | None,
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
            f"factorforge.console.job={job_id}",
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
            "--env",
            f"HOME={home}",
            "--env",
            f"FACTORFORGE_ROOT={worktree}",
            "--env",
            f"FACTORFORGE_FACTOR_WORKSPACE={workspace}",
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
            "NO_PROXY=",
            "--env",
            "no_proxy=",
        ]
        if aws_env_file is not None:
            command.extend(["--env-file", str(aws_env_file)])
        if profile_config_readonly is not None:
            command.extend(["--mount", _mount(profile_config_readonly, readonly=True)])
        python_paths = [str(worktree)]
        if self.config.data_api_pythonpath:
            command.extend(["--mount", _mount(self.config.data_api_pythonpath, readonly=True)])
            python_paths.insert(0, str(self.config.data_api_pythonpath))
        mounted_data_roots: set[Path] = set()
        if self.config.data_catalogs:
            command.extend(["--env", f"FACTORFORGE_STATE_CATALOG={self.config.data_catalogs[0]}"])
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

    def _prepare_aws_environment(self, runtime_root: Path) -> tuple[Path | None, tuple[str, ...]]:
        credentials = _load_aws_credentials()
        if credentials is None:
            if self.config.data_catalogs and not self.config.auth_disabled:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: scoped AWS credentials are unavailable"
                )
            return None, ()
        access_key, secret_key, token = credentials
        env_path = runtime_root / ".aws-readonly.env"
        lines = [
            f"AWS_ACCESS_KEY_ID={access_key}",
            f"AWS_SECRET_ACCESS_KEY={secret_key}",
        ]
        if token:
            lines.append(f"AWS_SESSION_TOKEN={token}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env_path.chmod(0o600)
        return env_path, tuple(value for value in (access_key, secret_key, token) if value)

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

    def _stop_container(self, name: str) -> None:
        try:
            subprocess.run(
                [self.config.container_runtime, "stop", "--time", "10", name],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
            subprocess.run(
                [self.config.container_runtime, "rm", "-f", name],
                text=True,
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return

    def _reconcile_stale_containers(self) -> None:
        output = self._run_runtime(
            [
                self.config.container_runtime,
                "ps",
                "-aq",
                "--filter",
                "label=factorforge.console=research-agent",
            ],
            timeout=30,
            label="stale agent container inventory",
        )
        for container_id in output.splitlines():
            value = container_id.strip()
            if value:
                self._stop_container(value)

    def _validate_egress_policy(self) -> None:
        script = r"""
import sys
import urllib.error
import urllib.request

mode, url = sys.argv[1], sys.argv[2]
opener = (
    urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if mode == "blocked-direct"
    else urllib.request.build_opener()
)
try:
    with opener.open(url, timeout=8) as response:
        reached_remote = 100 <= int(response.status) < 600
except urllib.error.HTTPError:
    reached_remote = True
except Exception:
    reached_remote = False
expected = mode == "allowed-proxy"
raise SystemExit(0 if reached_remote is expected else 1)
"""
        probes = (
            ("allowed-proxy", "https://api.deepseek.com"),
            (
                "allowed-proxy",
                "https://yufan-data-lake.s3.ap-southeast-1.amazonaws.com",
            ),
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
                    "--env",
                    f"HTTP_PROXY={self.config.container_proxy_url}",
                    "--env",
                    f"HTTPS_PROXY={self.config.container_proxy_url}",
                    "--env",
                    "NO_PROXY=",
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


def _load_aws_credentials() -> tuple[str, str, str] | None:
    try:
        import botocore.session

        credentials = botocore.session.get_session().get_credentials()
        if credentials is None:
            return None
        frozen = credentials.get_frozen_credentials()
    except Exception:
        return None
    access_key = str(frozen.access_key or "")
    secret_key = str(frozen.secret_key or "")
    token = str(frozen.token or "")
    if not access_key or not secret_key:
        return None
    return access_key, secret_key, token


def _validate_profile_policy(
    payload: object,
    *,
    expected_proxy_url: str = REQUIRED_PROXY_URL,
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
    if deepseek.get("baseUrl") != "https://api.deepseek.com":
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container model endpoint is invalid")
    proxy = ((deepseek.get("request") or {}).get("proxy") or {})
    if proxy != {"mode": "explicit-proxy", "url": expected_proxy_url}:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container model proxy is invalid")
