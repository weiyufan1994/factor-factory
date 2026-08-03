from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import uuid
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from factor_factory.console.agent_adapter import (
    BLOCK_AGENT_ORPHANED_WRITER,
    BLOCK_AGENT_RUNTIME_FAILED,
    BLOCK_AGENT_RUNTIME_TIMEOUT,
    BLOCK_AGENT_RUNTIME_UNAVAILABLE,
    AgentRunResult,
    AgentResumeTask,
    RESUME_MEMO_AGENT_COMPONENT_FIELDS,
    RESUME_MEMO_AGENT_DIRECT_FIELDS,
    RESUME_MEMO_AGENT_EVIDENCE_FIELDS,
    RESUME_MEMO_AGENT_OPERATOR_FIELDS,
    RESUME_MEMO_AGENT_PATCH_FIELDS,
    RESUME_MEMO_AGENT_PATCH_MAX_BYTES,
    RESUME_MEMO_MAX_BYTES,
    RESUME_PROMPT_INPUT_MAX_BYTES,
    build_agent_prompt,
    build_agent_session_key,
    copy_auth_database,
    redact_secrets,
    validate_auth_database,
)
from factor_factory.console.config import ConsoleConfig
from factor_factory.console.council_ingress import (
    CouncilIngressTask,
    build_council_task_prompt,
)
from factor_factory.console.models import ResearchJob
from factor_factory.console.model_broker import (
    ACTIVE_SECRET_REGISTRY_NAME,
    read_private_token_file,
)
from factor_factory.console.store import utc_now
from factor_factory.console.web_research_plan import write_text_atomic
from factor_factory.console.workspace_transaction import (
    workspace_transaction_lock,
    workspace_transaction_lock_held,
)


REQUIRED_CONTAINER_TOOLS = ["read", "edit", "write", "apply_patch", "exec", "process"]
REQUIRED_RESUME_CONTAINER_TOOLS = ["read"]
RESUME_TERMINAL_DELIVERY_KEYS = {"status", "memo", "ledger"}
RESUME_LEDGER_MAX_CHARACTERS = 1_600
RESUME_TERMINAL_MAX_BYTES = 32_000
RESUME_TERMINAL_PLAIN_PREFIX_MAX_BYTES = 2_048
REQUIRED_COMPACTION_POLICY = {
    "mode": "safeguard",
    "reserveTokens": 16384,
    "reserveTokensFloor": 12000,
    "keepRecentTokens": 12000,
    "recentTurnsPreserve": 1,
    "maxHistoryShare": 0.5,
    "identifierPolicy": "strict",
    "qualityGuard": {"enabled": True, "maxRetries": 1},
    "midTurnPrecheck": {"enabled": True},
    "postIndexSync": "off",
    "postCompactionSections": [],
    "truncateAfterCompaction": True,
    "maxActiveTranscriptBytes": "2mb",
    "notifyUser": False,
    "memoryFlush": {"enabled": False},
}
REQUIRED_PROXY_URL = "http://172.29.0.1:3128"
REQUIRED_MODEL_BROKER_URL = "http://172.29.0.1:8781"
DATA_API_BRIDGE_RELATIVE = Path("deploy/factorforge-console/data-api-bridge")


def _is_bounded_plain_resume_prefix(prefix: str) -> bool:
    if (
        not prefix.strip()
        or len(prefix.encode("utf-8"))
        > RESUME_TERMINAL_PLAIN_PREFIX_MAX_BYTES
        or "{" in prefix
        or "}" in prefix
        or "```" in prefix
        or "~~~" in prefix
        or any(
            character not in "\r\n\t" and not character.isprintable()
            for character in prefix
        )
    ):
        return False

    lines = [line.strip() for line in prefix.splitlines() if line.strip()]
    for line in lines:
        prose = re.sub(r"^(?:[-*]|[0-9]{1,2}[.)])\s+", "", line)
        if not prose or not prose[0].isalpha() or prose.startswith(("[", "]")):
            return False
        try:
            _json_value, parsed_end = json.JSONDecoder().raw_decode(prose)
        except json.JSONDecodeError:
            continue
        if (
            parsed_end == len(prose)
            or not (
                prose[parsed_end].isalnum()
                or prose[parsed_end] == "_"
            )
        ):
            return False
    return bool(lines)


@dataclass(frozen=True)
class _AwsCredentialLease:
    access_key: str
    secret_key: str
    token: str
    expires_at: datetime
    method: str
    caller_arn: str


@dataclass(frozen=True)
class _ResumeWorkspaceView:
    root: Path
    read_only_file_sha256: tuple[tuple[str, str], ...]
    parent_tree_file_sha256: tuple[tuple[str, str], ...]
    parent_tree_directory_relatives: tuple[str, ...]
    parent_ledger_sha256: str
    parent_output_bytes: tuple[tuple[str, bytes | None], ...]
    prior_output_archive_id: str
    allowed_entry_relatives: tuple[str, ...]
    writable_relatives: tuple[str, ...]
    remove_if_empty_relatives: tuple[str, ...]


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
        self._validate_credential_state_mount_boundary()
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

    def run(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task: AgentResumeTask | None = None,
    ) -> AgentRunResult:
        worktree = worktree.resolve(strict=True)
        workspace = workspace.resolve(strict=True)
        workspace.relative_to(worktree)
        if resume and resume_task is None:
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID: typed resume task is required"
            )
        base_agent_id = f"factorforge-web-{job.job_id.removeprefix('job_')}"
        agent_id = (
            f"{base_agent_id}-r-{resume_task.attempt_id[-8:]}"
            if resume_task is not None
            else (job.agent_id or base_agent_id)
        )
        session_key = build_agent_session_key(
            job,
            agent_id,
            resume=resume,
            resume_task=resume_task,
        )
        prompt_path = workspace / "identity" / ("web_agent_resume.md" if resume else "web_agent_task.md")
        write_text_atomic(
            prompt_path,
            build_agent_prompt(
                job,
                worktree=worktree,
                workspace=workspace,
                config=self.config,
                resume=resume,
                resume_task=resume_task,
            ),
            root=workspace,
        )

        self._initialize_credential_material_state(job.job_id, resume=resume)
        first_issuance = self.credential_material_state(job.job_id) == "not_issued"
        runtime_root, home, agent_dir, profile_config = self._prepare_runtime(
            job.job_id,
            phase_id=resume_task.attempt_id if resume_task is not None else None,
        )
        resume_workspace_view = (
            self._prepare_resume_workspace_view(
                runtime_root=runtime_root,
                workspace=workspace,
                resume_task=resume_task,
            )
            if resume_task is not None
            else None
        )
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
            auth_store_path=None,
            workspace_readonly=resume_workspace_view is not None,
            workspace_mount_source=(
                resume_workspace_view.root if resume_workspace_view is not None else None
            ),
            protected_workspace_relatives=(
                tuple(relative for relative, _digest in resume_workspace_view.read_only_file_sha256)
                if resume_workspace_view is not None
                else ()
            ),
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
        self._validate_agent_binding(
            profile_config,
            agent_id,
            worktree,
            agent_dir,
            model,
            expected_tools=(
                REQUIRED_RESUME_CONTAINER_TOOLS
                if resume_task is not None
                else REQUIRED_CONTAINER_TOOLS
            ),
        )

        aws_env_file, credential_values, denied_secret_file = self._prepare_aws_environment(
            job.job_id,
            allow_missing_history=first_issuance,
            include_aws_credentials=False,
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
                auth_store_path=auth_store,
                workspace_readonly=resume_workspace_view is not None,
                workspace_mount_source=(
                    resume_workspace_view.root
                    if resume_workspace_view is not None
                    else None
                ),
                protected_workspace_relatives=(
                    tuple(
                        relative
                        for relative, _digest in resume_workspace_view.read_only_file_sha256
                    )
                    if resume_workspace_view is not None
                    else ()
                ),
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
                (
                    self.config.openclaw_resume_thinking
                    if resume
                    else self.config.openclaw_thinking
                ),
                "--timeout",
                str(self.config.agent_timeout_seconds),
                "--json",
            ]
            started = utc_now()
            raw_stdout = ""
            raw_stderr = ""
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
                raw_stdout = proc.stdout
                raw_stderr = proc.stderr
                stdout = redact_secrets(raw_stdout, extra_values=credential_values)
                stderr = redact_secrets(raw_stderr, extra_values=credential_values)
                error_code = "" if returncode == 0 else BLOCK_AGENT_RUNTIME_FAILED
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.container_runtime}"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                if not self._stop_container(container_name):
                    raise RuntimeError(
                        f"{BLOCK_AGENT_ORPHANED_WRITER}: timed-out agent container could not be removed"
                    ) from exc
                raw_stdout = _as_text(exc.stdout)
                raw_stderr = _as_text(exc.stderr)
                stdout = redact_secrets(raw_stdout, extra_values=credential_values)
                stderr = redact_secrets(raw_stderr, extra_values=credential_values)
                returncode = 124
                error_code = BLOCK_AGENT_RUNTIME_TIMEOUT
            finally:
                with self._lock:
                    self._active.discard(container_name)
        finally:
            # Keep the exact denied-value registry until the runner has
            # validated and published the task's public evidence set.
            self._cleanup_aws_environment(aws_env_file, None)

        try:
            validate_auth_database(
                auth_store,
                provider=self.config.openclaw_auth_provider,
                label="phase credential store",
                expected_key=self._broker_client_token(),
            )
        except (OSError, RuntimeError):
            returncode = 1
            error_code = BLOCK_AGENT_RUNTIME_FAILED
            stderr = (
                f"{stderr}\n{BLOCK_AGENT_RUNTIME_FAILED}: "
                "phase credential store failed post-run validation"
            ).strip()

        if resume_workspace_view is not None and returncode == 0:
            try:
                terminal_text = _validate_openclaw_terminal_status(
                    raw_stdout,
                    raw_stderr,
                )
                self._stage_resume_terminal_delivery(
                    resume_workspace_view,
                    terminal_text=terminal_text,
                    resume_task=resume_task,
                    extra_secret_values=credential_values,
                    rehydrate_immutable_fields=True,
                )
                self._promote_resume_workspace_view(
                    resume_workspace_view,
                    workspace=workspace,
                    extra_secret_values=credential_values,
                    worktree=worktree,
                    report_id=job.report_id,
                )
            except RuntimeError as exc:
                if str(exc).startswith(BLOCK_AGENT_ORPHANED_WRITER):
                    raise
                returncode = 1
                error_code = BLOCK_AGENT_RUNTIME_FAILED
                stderr = f"{stderr}\n{exc}".strip()
            except OSError as exc:
                returncode = 1
                error_code = BLOCK_AGENT_RUNTIME_FAILED
                stderr = (
                    f"{stderr}\n{BLOCK_AGENT_RUNTIME_FAILED}: "
                    f"resume promotion I/O failure:{type(exc).__name__}"
                ).strip()

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
            "resume_attempt_id": resume_task.attempt_id if resume_task is not None else "",
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

    def run_council_ingress(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        tasks: tuple[CouncilIngressTask, ...],
    ) -> AgentRunResult:
        if not tasks:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Council ingress has no tasks"
            )
        worktree = worktree.resolve(strict=True)
        workspace = workspace.resolve(strict=True)
        workspace.relative_to(worktree)
        summary_prompt = workspace / "identity" / "web_agent_resume.md"
        _ensure_workspace_parent(summary_prompt, root=workspace)
        write_text_atomic(
            summary_prompt,
            "# Council result ingress\n\n"
            f"Report: {job.report_id}\n\n"
            f"{len(tasks)} independent blind-route agents are dispatched by the Host. "
            "Each agent may write only its immutable expected result path.\n",
            root=workspace,
        )

        self._initialize_credential_material_state(job.job_id, resume=True)
        first_issuance = self.credential_material_state(job.job_id) == "not_issued"
        runtime_root, _home, _primary_agent_dir, _profile_config = (
            self._prepare_runtime(job.job_id)
        )
        council_run_root = (
            runtime_root / "council-isolated" / f"run_{uuid.uuid4().hex}"
        )
        council_run_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        council_run_root.chmod(0o700)
        model = job.request.model or self.config.openclaw_model
        per_task_timeout = max(
            180,
            min(
                self.config.agent_timeout_seconds,
                self.config.agent_timeout_seconds // len(tasks) + 120,
            ),
        )
        aws_env_file, credential_values, _denied_secret_file = (
            self._prepare_aws_environment(
                job.job_id,
                allow_missing_history=first_issuance,
                include_aws_credentials=False,
            )
        )
        started = utc_now()
        runs: list[dict[str, Any]] = []
        private_results: list[tuple[CouncilIngressTask, Path]] = []
        returncode = 0
        try:
            for index, task in enumerate(tasks, start=1):
                runtime_token = _safe_runtime_token(task.task_id)
                agent_id = (
                    f"ff-council-{job.job_id.removeprefix('job_')[:10]}-{index:02d}"
                )
                session_key = f"agent:{agent_id}:{job.job_id}:{task.task_id}"
                task_runtime_root = council_run_root / runtime_token
                home = task_runtime_root / "home"
                agent_dir = task_runtime_root / "agent"
                profile_dir = home / f".openclaw-{self.config.openclaw_profile}"
                output_root = task_runtime_root / "output"
                worktree_view = task_runtime_root / "engine-view"
                workspace_view = task_runtime_root / "workspace-view"
                for path in (
                    task_runtime_root,
                    home,
                    agent_dir,
                    profile_dir,
                    output_root,
                    worktree_view,
                    workspace_view,
                ):
                    path.mkdir(parents=True, exist_ok=False, mode=0o700)
                    path.chmod(0o700)
                workspace_mountpoint = worktree_view / workspace.relative_to(worktree)
                workspace_mountpoint.mkdir(parents=True, exist_ok=False, mode=0o700)
                packet_source = workspace / task.task_packet_path
                packet_view = workspace_view / task.task_packet_path
                packet_view.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
                shutil.copy2(packet_source, packet_view)
                packet_view.chmod(0o400)
                assert self.config.openclaw_profile_template is not None
                profile_config = profile_dir / "openclaw.json"
                shutil.copy2(self.config.openclaw_profile_template, profile_config)
                profile_config.chmod(0o600)
                _validate_profile_policy(
                    json.loads(profile_config.read_text(encoding="utf-8")),
                    expected_model_broker_url=self.config.container_model_broker_url,
                )
                auth_store = agent_dir / "openclaw-agent.sqlite"
                assert self.config.openclaw_auth_seed_db is not None
                copy_auth_database(self.config.openclaw_auth_seed_db, auth_store)
                auth_store.chmod(0o600)
                validate_auth_database(
                    auth_store,
                    provider=self.config.openclaw_auth_provider,
                    label=f"Council credential store {index}",
                    expected_key=self._broker_client_token(),
                )
                container_name = (
                    f"ff-council-{self.config.installation_id[:8]}-"
                    f"{job.job_id.removeprefix('job_')[:10]}-{index:02d}"
                )
                common = self._container_prefix(
                    container_name=container_name,
                    job_id=job.job_id,
                    worktree=worktree,
                    workspace=workspace,
                    runtime_root=task_runtime_root,
                    home=home,
                    git_dir=None,
                    aws_env_file=None,
                    profile_config_readonly=None,
                    auth_store_path=None,
                    worktree_mount_source=worktree_view,
                    workspace_readonly=True,
                    workspace_mount_source=workspace_view,
                )
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
                self._run_runtime(
                    add_command,
                    timeout=120,
                    label=f"Council agent {index} initialization",
                    allow_exists=True,
                )
                self._validate_agent_binding(
                    profile_config,
                    agent_id,
                    worktree,
                    agent_dir,
                    model,
                )
                private_result_path = output_root / "agent_result.json"
                prompt_path = task_runtime_root / "council_task.md"
                prompt_path.write_text(
                    build_council_task_prompt(
                        workspace=workspace,
                        report_id=job.report_id,
                        task=task,
                        private_output_path=private_result_path,
                    ),
                    encoding="utf-8",
                )
                prompt_path.chmod(0o600)
                research_common = self._container_prefix(
                    container_name=container_name,
                    job_id=job.job_id,
                    worktree=worktree,
                    workspace=workspace,
                    runtime_root=task_runtime_root,
                    home=home,
                    git_dir=None,
                    aws_env_file=aws_env_file,
                    profile_config_readonly=profile_config,
                    auth_store_path=auth_store,
                    worktree_mount_source=worktree_view,
                    workspace_readonly=True,
                    workspace_mount_source=workspace_view,
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
                    str(per_task_timeout),
                    "--json",
                ]
                turn_started = utc_now()
                with self._lock:
                    self._active.add(container_name)
                try:
                    proc = subprocess.run(
                        command,
                        cwd=worktree,
                        text=True,
                        capture_output=True,
                        timeout=per_task_timeout + 90,
                    )
                    turn_returncode = proc.returncode
                    stdout = redact_secrets(
                        proc.stdout,
                        extra_values=credential_values,
                    )
                    stderr = redact_secrets(
                        proc.stderr,
                        extra_values=credential_values,
                    )
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.container_runtime}"
                    ) from exc
                except subprocess.TimeoutExpired as exc:
                    if not self._stop_container(container_name):
                        raise RuntimeError(
                            f"{BLOCK_AGENT_ORPHANED_WRITER}: timed-out Council container could not be removed"
                        ) from exc
                    turn_returncode = 124
                    stdout = redact_secrets(
                        _as_text(exc.stdout),
                        extra_values=credential_values,
                    )
                    stderr = redact_secrets(
                        _as_text(exc.stderr),
                        extra_values=credential_values,
                    )
                finally:
                    with self._lock:
                        self._active.discard(container_name)
                try:
                    validate_auth_database(
                        auth_store,
                        provider=self.config.openclaw_auth_provider,
                        label=f"Council credential store {index} post-run",
                        expected_key=self._broker_client_token(),
                    )
                except (OSError, RuntimeError):
                    turn_returncode = 1
                    stderr = (
                        f"{stderr}\n{BLOCK_AGENT_RUNTIME_FAILED}: "
                        "Council credential store failed post-run validation"
                    ).strip()
                runs.append(
                    {
                        "task_id": task.task_id,
                        "agent_role": task.agent_role,
                        "expected_agent_identifier": task.expected_agent_identifier,
                        "agent_id": agent_id,
                        "session_key_sha256": hashlib.sha256(
                            session_key.encode("utf-8")
                        ).hexdigest(),
                        "expected_result_path": task.expected_result_path,
                        "private_result_path": str(private_result_path),
                        "started_at_utc": turn_started,
                        "finished_at_utc": utc_now(),
                        "returncode": turn_returncode,
                        "stdout_tail": stdout[-4_000:],
                        "stderr_tail": stderr[-4_000:],
                    }
                )
                if turn_returncode != 0:
                    returncode = turn_returncode
                    break
                private_results.append((task, private_result_path))
        finally:
            self._cleanup_aws_environment(aws_env_file, None)

        if returncode == 0:
            if len(private_results) != len(tasks):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: Council ingress result count is incomplete"
                )
            validated_results: list[tuple[CouncilIngressTask, dict[str, Any]]] = []
            for task, private_result_path in private_results:
                if (
                    private_result_path.is_symlink()
                    or not private_result_path.is_file()
                    or private_result_path.stat().st_size <= 0
                    or private_result_path.stat().st_size > 2 * 1024 * 1024
                ):
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: Council agent result is missing or unsafe"
                    )
                raw_result = private_result_path.read_text(encoding="utf-8")
                if redact_secrets(
                    raw_result,
                    extra_values=credential_values,
                ) != raw_result:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: Council agent result contains secret material"
                    )
                try:
                    result_payload = json.loads(raw_result)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: Council agent result is invalid JSON"
                    ) from exc
                if (
                    not isinstance(result_payload, dict)
                    or result_payload.get("report_id") != job.report_id
                    or result_payload.get("task_id") != task.task_id
                    or result_payload.get("agent_role") != task.agent_role
                    or result_payload.get("agent_identifier")
                    != task.expected_agent_identifier
                ):
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: Council agent result identity mismatch"
                    )
                validation_reasons = _validate_private_council_result(
                    worktree=worktree,
                    workspace=workspace,
                    report_id=job.report_id,
                    task=task,
                    payload=result_payload,
                )
                if validation_reasons:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: Council agent result failed formal validation"
                    )
                validated_results.append((task, result_payload))
            _promote_council_result_set(
                workspace=workspace,
                validated_results=validated_results,
            )
            for task, _result_payload in validated_results:
                runs_by_task = next(
                    run for run in runs if run["task_id"] == task.task_id
                )
                runs_by_task["imported_result_sha256"] = hashlib.sha256(
                    (workspace / task.expected_result_path).read_bytes()
                ).hexdigest()

        finished = utc_now()
        primary_agent_id = job.agent_id or (
            f"factorforge-web-{job.job_id.removeprefix('job_')}"
        )
        primary_session_key = job.agent_session_key or (
            f"agent:{primary_agent_id}:{job.job_id}"
        )
        result_path = (
            self.config.state_root
            / "jobs"
            / job.job_id
            / f"council_ingress_{_stamp(finished)}.json"
        )
        payload: dict[str, Any] = {
            "version": "factorforge_console_council_ingress_v1",
            "execution_mode": "container",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "agent_id": primary_agent_id,
            "independent_agent_count": len(runs),
            "required_agent_count": len(tasks),
            "resume": True,
            "started_at_utc": started,
            "finished_at_utc": finished,
            "returncode": returncode,
            "error_code": "" if returncode == 0 else BLOCK_AGENT_RUNTIME_FAILED,
            "runs": runs,
        }
        _write_private_json(result_path, payload)
        return AgentRunResult(
            returncode=returncode,
            agent_id=primary_agent_id,
            session_key=primary_session_key,
            started_at_utc=started,
            finished_at_utc=finished,
            stdout_tail=json.dumps(
                {
                    "council_agents_completed": sum(
                        1 for run in runs if run["returncode"] == 0
                    ),
                    "council_agents_required": len(tasks),
                },
                sort_keys=True,
            ),
            stderr_tail="" if returncode == 0 else "Council ingress agent failed",
            result_path=str(result_path),
        )

    def _prepare_runtime(
        self,
        job_id: str,
        *,
        phase_id: str | None = None,
    ) -> tuple[Path, Path, Path, Path]:
        runtime_root = self.config.state_root / "jobs" / job_id / "container-agent"
        if phase_id is not None:
            if not re.fullmatch(r"resume_[a-f0-9]{32}", phase_id):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume phase identity is invalid"
                )
            runtime_root = (
                self.config.state_root
                / "jobs"
                / job_id
                / "container-agent-phases"
                / phase_id
            )
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
            payload = json.loads(profile_config.read_text(encoding="utf-8"))
            expected_tools = REQUIRED_CONTAINER_TOOLS
            if phase_id is not None:
                expected_tools = REQUIRED_RESUME_CONTAINER_TOOLS
                tools = payload.get("tools") if isinstance(payload, dict) else None
                if isinstance(tools, dict) and tools.get("allow") == REQUIRED_CONTAINER_TOOLS:
                    tools["allow"] = list(REQUIRED_RESUME_CONTAINER_TOOLS)
                    write_text_atomic(
                        profile_config,
                        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
                        root=profile_config.parent,
                    )
            _validate_profile_policy(
                payload,
                expected_model_broker_url=self.config.container_model_broker_url,
                expected_tools=expected_tools,
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

    def _prepare_resume_workspace_view(
        self,
        *,
        runtime_root: Path,
        workspace: Path,
        resume_task: AgentResumeTask,
    ) -> _ResumeWorkspaceView:
        view_root = runtime_root.parent / f"{runtime_root.name}-resume-workspace-view"
        if view_root.exists() or view_root.is_symlink():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace view already exists"
            )
        view_root.mkdir(mode=0o700)
        view_root.chmod(0o700)

        prompt_relative = "identity/web_agent_resume.md"
        safe_read_relatives = tuple(
            dict.fromkeys(
                (
                    resume_task.contract_relative,
                    *resume_task.read_only_inputs,
                    prompt_relative,
                )
            )
        )
        parent_protected_relatives = tuple(
            dict.fromkeys(
                (
                    *resume_task.protected_inputs,
                    *safe_read_relatives,
                )
            )
        )
        parent_snapshots = {
            relative: _read_stable_workspace_file_bytes(
                workspace,
                relative,
                max_bytes=16 * 1024 * 1024,
            )
            for relative in parent_protected_relatives
        }
        for relative in safe_read_relatives:
            destination = _safe_view_relative_path(view_root, relative)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(parent_snapshots[relative])
            destination.chmod(0o400)

        try:
            facts = json.loads(
                parent_snapshots[resume_task.facts_relative].decode("utf-8")
            )
        except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume facts packet is invalid"
            ) from exc
        formula_facts = (
            facts.get("formula_facts")
            if isinstance(facts, dict) and isinstance(facts.get("formula_facts"), dict)
            else {}
        )
        formula = str(formula_facts.get("formula") or "").strip()
        fields = formula_facts.get("fields")
        operators = formula_facts.get("operators")
        if (
            not formula
            or not isinstance(fields, list)
            or not fields
            or not isinstance(operators, list)
            or not operators
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume formula facts are incomplete"
            )
        safe_spec_relative = (
            "objects/factor_spec_master/"
            f"factor_spec_master__{resume_task.report_id}.json"
        )
        safe_spec_path = _safe_view_relative_path(view_root, safe_spec_relative)
        safe_spec_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_spec_path.write_text(
            json.dumps(
                {
                    "report_id": resume_task.report_id,
                    "factor_id": resume_task.factor_id,
                    "canonical_spec": {
                        "formula_text": formula,
                        "required_inputs": fields,
                        "operators": operators,
                    },
                    "projection": "agent_safe_formula_facts_only",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        safe_spec_path.chmod(0o400)

        writable_relatives = tuple(
            dict.fromkeys(
                (
                    resume_task.required_output_relative,
                    "identity/web_execution_ledger.md",
                )
            )
        )
        ledger_relative = "identity/web_execution_ledger.md"
        parent_ledger = _read_stable_workspace_file_bytes(
            workspace,
            ledger_relative,
            max_bytes=2 * 1024 * 1024,
        )
        parent_output_relatives = (
            resume_task.required_output_relative,
        )
        prior_output_sha256 = dict(resume_task.prior_output_sha256)
        if (
            len(prior_output_sha256) != len(resume_task.prior_output_sha256)
            or set(prior_output_sha256)
            - {resume_task.required_output_relative}
            or any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in prior_output_sha256.values()
            )
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: prior resume output binding is invalid"
            )
        if bool(prior_output_sha256) != bool(
            resume_task.prior_output_archive_id
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: prior memo archive binding is invalid"
            )
        if resume_task.prior_output_archive_id:
            _prepare_private_resume_archive_path(
                self.config.state_root,
                resume_task,
            )
        parent_output_bytes: list[tuple[str, bytes | None]] = []
        for relative in writable_relatives:
            target = _safe_workspace_relative_file(
                workspace,
                relative,
                must_exist=False,
            )
            if relative in {
                resume_task.required_output_relative,
                resume_task.optional_output_relative,
            }:
                expected_digest = prior_output_sha256.get(relative)
                if expected_digest is None:
                    if target.exists() or target.is_symlink():
                        raise RuntimeError(
                            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume output already exists"
                        )
                    parent_output_bytes.append((relative, None))
                else:
                    baseline = _read_stable_workspace_file_bytes(
                        workspace,
                        relative,
                        max_bytes=2 * 1024 * 1024,
                    )
                    if hashlib.sha256(baseline).hexdigest() != expected_digest:
                        raise RuntimeError(
                            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: prior resume output hash mismatch:{relative}"
                        )
                    parent_output_bytes.append((relative, baseline))
            elif not target.is_file() or target.is_symlink():
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume ledger is unsafe"
                )
            view_target = _safe_view_relative_path(view_root, relative)
            view_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            view_target.touch(mode=0o600, exist_ok=False)

        read_only_relatives = tuple(
            dict.fromkeys((*safe_read_relatives, safe_spec_relative))
        )
        for directory in (
            path for path in view_root.rglob("*") if path.is_dir()
        ):
            directory.chmod(0o700)
        allowed_entry_relatives = tuple(
            sorted(
                path.relative_to(view_root).as_posix()
                for path in view_root.rglob("*")
            )
        )
        parent_tree_files, parent_tree_directories = _workspace_tree_snapshot(
            workspace,
            excluded_file_relatives=(
                ledger_relative,
                *parent_output_relatives,
            ),
        )
        parent_tree_file_map = dict(parent_tree_files)
        for relative, snapshot_bytes in parent_snapshots.items():
            if parent_tree_file_map.get(relative) != hashlib.sha256(
                snapshot_bytes
            ).hexdigest():
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: phase input and parent tree baseline diverged:{relative}"
                )
        return _ResumeWorkspaceView(
            root=view_root,
            read_only_file_sha256=tuple(
                (
                    relative,
                    hashlib.sha256(
                        _safe_workspace_relative_file(
                            view_root,
                            relative,
                            must_exist=True,
                        ).read_bytes()
                    ).hexdigest(),
                )
                for relative in read_only_relatives
            ),
            parent_tree_file_sha256=parent_tree_files,
            parent_tree_directory_relatives=parent_tree_directories,
            parent_ledger_sha256=hashlib.sha256(parent_ledger).hexdigest(),
            parent_output_bytes=tuple(parent_output_bytes),
            prior_output_archive_id=resume_task.prior_output_archive_id,
            allowed_entry_relatives=allowed_entry_relatives,
            writable_relatives=writable_relatives,
            remove_if_empty_relatives=(),
        )

    def _stage_resume_terminal_delivery(
        self,
        view: _ResumeWorkspaceView,
        *,
        terminal_text: str,
        resume_task: AgentResumeTask | None,
        extra_secret_values: tuple[str, ...] = (),
        rehydrate_immutable_fields: bool = False,
    ) -> None:
        if resume_task is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal delivery lacks task identity"
            )
        if (
            not terminal_text.strip()
            or len(terminal_text.encode("utf-8")) > RESUME_TERMINAL_MAX_BYTES
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal delivery is missing or too large"
            )
        accepted_prefix = ""
        try:
            delivery = json.loads(terminal_text)
        except json.JSONDecodeError as exc:
            # Recover only transport forms that still contain one unambiguous
            # delivery object; all trailing or structurally prefixed output blocks.
            try:
                delivery, parsed_end = json.JSONDecoder().raw_decode(terminal_text)
            except json.JSONDecodeError:
                delivery = None
                parsed_end = -1
            if parsed_end < 0 or terminal_text[parsed_end:] != '"}':
                object_start = terminal_text.find("{")
                prefix = terminal_text[:object_start] if object_start > 0 else ""
                try:
                    prefixed_delivery, object_end = json.JSONDecoder().raw_decode(
                        terminal_text,
                        object_start,
                    )
                except (json.JSONDecodeError, ValueError):
                    prefixed_delivery = None
                    object_end = -1
                if (
                    not _is_bounded_plain_resume_prefix(prefix)
                    or object_end != len(terminal_text)
                ):
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal delivery is invalid JSON"
                    ) from exc
                delivery = prefixed_delivery
                accepted_prefix = prefix
        if (
            accepted_prefix
            and redact_secrets(
                accepted_prefix,
                extra_values=extra_secret_values,
            )
            != accepted_prefix
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal prefix contains secret material"
            )
        if (
            not isinstance(delivery, dict)
            or set(delivery) != RESUME_TERMINAL_DELIVERY_KEYS
            or delivery.get("status") != "MEMO_DRAFT_COMPLETE"
            or not isinstance(delivery.get("memo"), dict)
            or not isinstance(delivery.get("ledger"), str)
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal delivery schema is invalid"
            )

        model_memo_text = json.dumps(
            delivery["memo"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        model_memo_limit = (
            RESUME_MEMO_AGENT_PATCH_MAX_BYTES
            if rehydrate_immutable_fields
            else RESUME_MEMO_MAX_BYTES
        )
        if len(model_memo_text.encode("utf-8")) > model_memo_limit:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal "
                f"{'research patch' if rehydrate_immutable_fields else 'memo'} "
                "exceeds byte budget"
            )
        if (
            redact_secrets(
                model_memo_text,
                extra_values=extra_secret_values,
            )
            != model_memo_text
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal memo contains secret material"
            )

        memo = delivery["memo"]
        if rehydrate_immutable_fields:
            memo = _rehydrate_resume_memo_immutable_fields(
                view.root,
                resume_task,
                memo,
            )
        memo_text = json.dumps(
            memo,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        ledger = delivery["ledger"].strip()
        ledger_text = f"{ledger}\n" if ledger else ""
        if len(memo_text.encode("utf-8")) > RESUME_MEMO_MAX_BYTES:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal memo exceeds byte budget"
            )
        if not ledger or len(ledger) > RESUME_LEDGER_MAX_CHARACTERS:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal ledger is missing or too large"
            )
        for label, text in (("memo", memo_text), ("ledger", ledger_text)):
            if redact_secrets(text, extra_values=extra_secret_values) != text:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal {label} contains secret material"
                )

        expected_writable = {
            resume_task.required_output_relative,
            "identity/web_execution_ledger.md",
        }
        if set(view.writable_relatives) != expected_writable:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal output boundary is invalid"
            )
        _audit_resume_workspace_view(view)
        for relative in view.writable_relatives:
            if _read_stable_workspace_file_bytes(
                view.root,
                relative,
                max_bytes=2 * 1024 * 1024,
                error_code=BLOCK_AGENT_RUNTIME_FAILED,
            ):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume phase output changed before Host staging"
                )
        _replace_text_atomic_existing(
            view.root,
            resume_task.required_output_relative,
            memo_text,
            expected_bytes=b"",
        )
        _replace_text_atomic_existing(
            view.root,
            "identity/web_execution_ledger.md",
            ledger_text,
            expected_bytes=b"",
        )

    def _promote_resume_workspace_view(
        self,
        view: _ResumeWorkspaceView,
        *,
        workspace: Path,
        extra_secret_values: tuple[str, ...] = (),
        worktree: Path | None = None,
        report_id: str | None = None,
    ) -> None:
        root = workspace
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: parent workspace root is unsafe"
            )
        optional_relatives = set(view.remove_if_empty_relatives)
        _audit_resume_workspace_view(view)
        for relative, expected_digest in view.read_only_file_sha256:
            source_bytes = _read_stable_workspace_file_bytes(
                view.root,
                relative,
                max_bytes=16 * 1024 * 1024,
            )
            if hashlib.sha256(source_bytes).hexdigest() != expected_digest:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume input changed:{relative}"
                )
        staged_outputs: dict[str, str] = {}
        for relative in view.writable_relatives:
            staged_bytes = _read_stable_workspace_file_bytes(
                view.root,
                relative,
                max_bytes=2 * 1024 * 1024,
                error_code=BLOCK_AGENT_RUNTIME_FAILED,
            )
            try:
                staged_text = staged_bytes.decode("utf-8")
            except UnicodeError as exc:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume output is not valid UTF-8"
                ) from exc
            if relative not in optional_relatives and not staged_text.strip():
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume output is empty:{relative}"
                )
            if (
                relative == "identity/web_execution_ledger.md"
                and len(staged_text) > 4_000
            ):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume execution ledger is too large"
                )
            if redact_secrets(
                staged_text,
                extra_values=extra_secret_values,
            ) != staged_text:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume output contains secret material"
                )
            if relative.endswith(".json") and staged_text.strip():
                try:
                    payload = json.loads(staged_text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: resume output is invalid JSON:{relative}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: resume JSON output must be an object:{relative}"
                    )
            staged_outputs[relative] = staged_text

        if (worktree is None) != (report_id is None):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume validator identity is incomplete"
            )
        if worktree is not None and report_id is not None:
            self._validate_resume_workspace_artifact(
                view,
                worktree=worktree,
                report_id=report_id,
            )

        if (
            view.prior_output_archive_id
            and not workspace_transaction_lock_held(self.config.state_root, root)
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: revision promotion lacks an outer workspace transaction"
            )
        with self._workspace_promotion_lock(root):
            self._promote_staged_resume_outputs(
                view,
                root=root,
                staged_outputs=staged_outputs,
                optional_relatives=optional_relatives,
            )

    def _validate_resume_workspace_artifact(
        self,
        view: _ResumeWorkspaceView,
        *,
        worktree: Path,
        report_id: str,
    ) -> None:
        validator = (
            worktree
            / "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py"
        )
        try:
            validator.resolve(strict=True).relative_to(worktree.resolve(strict=True))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: pinned resume validator is unavailable"
            ) from exc
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(validator),
                "--report-id",
                report_id,
            ],
            cwd=worktree,
            env={
                "FACTORFORGE_ROOT": str(view.root),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(worktree),
                "PYTHONUNBUFFERED": "1",
            },
            text=True,
            capture_output=True,
            timeout=120,
        )
        if (
            proc.returncode != 0
            or len(proc.stdout.encode("utf-8")) > 256 * 1024
            or len(proc.stderr.encode("utf-8")) > 256 * 1024
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Host resume validator rejected the memo:"
                f"{redact_secrets(proc.stderr)[-2_000:]}"
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Host resume validator receipt is invalid"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("result") != "PASS"
            or payload.get("failures") != []
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Host resume validator did not return PASS"
            )

    def _promote_staged_resume_outputs(
        self,
        view: _ResumeWorkspaceView,
        *,
        root: Path,
        staged_outputs: dict[str, str],
        optional_relatives: set[str],
    ) -> None:
        _require_parent_workspace_tree_unchanged(view, root)
        parent_output_bytes = dict(view.parent_output_bytes)
        if (
            len(parent_output_bytes) != len(view.parent_output_bytes)
            or set(parent_output_bytes) != {
                relative
                for relative in view.writable_relatives
                if relative != "identity/web_execution_ledger.md"
            }
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume output baseline is invalid"
            )
        for relative, baseline in parent_output_bytes.items():
            exists = _workspace_relative_entry_exists(root, relative)
            if baseline is None:
                if exists:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: resume output promotion target exists"
                    )
                continue
            if not exists or _read_stable_workspace_file_bytes(
                root,
                relative,
                max_bytes=2 * 1024 * 1024,
                error_code=BLOCK_AGENT_RUNTIME_FAILED,
            ) != baseline:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: prior resume output changed:{relative}"
                )
        parent_ledger_bytes = _read_stable_workspace_file_bytes(
            root,
            "identity/web_execution_ledger.md",
            max_bytes=2 * 1024 * 1024,
            error_code=BLOCK_AGENT_RUNTIME_FAILED,
        )
        if hashlib.sha256(parent_ledger_bytes).hexdigest() != view.parent_ledger_sha256:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: parent execution ledger changed"
            )
        try:
            parent_ledger = parent_ledger_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: parent execution ledger is invalid"
            ) from exc
        output_targets = {
            relative: root / relative for relative in parent_output_bytes
        }

        staged_ledger = staged_outputs["identity/web_execution_ledger.md"]
        separator = "" if not parent_ledger or parent_ledger.endswith("\n") else "\n"
        combined_ledger = f"{parent_ledger}{separator}{staged_ledger}"
        ledger_relative = "identity/web_execution_ledger.md"
        archive_bytes: bytes | None = None
        archive_parent_descriptor: int | None = None
        archive_name = ""
        archive_created = False
        prior_baselines = [
            baseline
            for baseline in parent_output_bytes.values()
            if baseline is not None
        ]
        if bool(view.prior_output_archive_id) != (len(prior_baselines) == 1):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: prior memo archive source is invalid"
            )
        with ExitStack() as archive_stack:
            if view.prior_output_archive_id:
                archive_bytes = prior_baselines[0]
                (
                    archive_parent_descriptor,
                    archive_name,
                ) = archive_stack.enter_context(
                    _open_private_resume_archive_parent_fd(
                        self.config.state_root,
                        view.prior_output_archive_id,
                        error_code=BLOCK_AGENT_RUNTIME_FAILED,
                        create_parents=False,
                        reject_existing_attempt=False,
                        require_file_absent=True,
                    )
                )
            try:
                if archive_bytes is not None:
                    if archive_parent_descriptor is None or not archive_name:
                        raise RuntimeError(
                            f"{BLOCK_AGENT_RUNTIME_FAILED}: prior memo archive parent is unavailable"
                        )
                    _require_private_resume_archive_parent_still_bound(
                        self.config.state_root,
                        view.prior_output_archive_id,
                        archive_parent_descriptor,
                        error_code=BLOCK_AGENT_RUNTIME_FAILED,
                    )
                    _write_private_resume_archive_at(
                        archive_parent_descriptor,
                        archive_name,
                        archive_bytes,
                        relative=view.prior_output_archive_id,
                    )
                    archive_created = True
                    _require_private_resume_archive_parent_still_bound(
                        self.config.state_root,
                        view.prior_output_archive_id,
                        archive_parent_descriptor,
                        error_code=BLOCK_AGENT_RUNTIME_FAILED,
                    )
                for relative, baseline in parent_output_bytes.items():
                    staged_text = staged_outputs[relative]
                    if relative in optional_relatives and not staged_text:
                        continue
                    if baseline is None:
                        _write_text_atomic_new(
                            output_targets[relative],
                            staged_text,
                            root=root,
                        )
                    else:
                        _replace_text_atomic_existing(
                            root,
                            relative,
                            staged_text,
                            expected_bytes=baseline,
                        )
                _replace_text_atomic_existing(
                    root,
                    ledger_relative,
                    combined_ledger,
                    expected_bytes=parent_ledger_bytes,
                )

                _require_parent_workspace_tree_unchanged(view, root)
                for relative, target in output_targets.items():
                    staged_text = staged_outputs[relative]
                    if relative in optional_relatives and not staged_text:
                        if (
                            parent_output_bytes[relative] is None
                            and _workspace_relative_entry_exists(root, relative)
                        ):
                            raise RuntimeError(
                                f"{BLOCK_AGENT_RUNTIME_FAILED}: unexpected optional output appeared"
                            )
                        continue
                    promoted = _read_stable_workspace_file_bytes(
                        root,
                        relative,
                        max_bytes=2 * 1024 * 1024,
                        error_code=BLOCK_AGENT_RUNTIME_FAILED,
                    )
                    if hashlib.sha256(promoted).hexdigest() != hashlib.sha256(
                        staged_text.encode("utf-8")
                    ).hexdigest():
                        raise RuntimeError(
                            f"{BLOCK_AGENT_RUNTIME_FAILED}: promoted output changed:{relative}"
                        )
                promoted_ledger = _read_stable_workspace_file_bytes(
                    root,
                    "identity/web_execution_ledger.md",
                    max_bytes=2 * 1024 * 1024,
                    error_code=BLOCK_AGENT_RUNTIME_FAILED,
                )
                if hashlib.sha256(promoted_ledger).hexdigest() != hashlib.sha256(
                    combined_ledger.encode("utf-8")
                ).hexdigest():
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_FAILED}: promoted execution ledger changed"
                    )
                if archive_created and archive_parent_descriptor is not None:
                    _require_private_resume_archive_parent_still_bound(
                        self.config.state_root,
                        view.prior_output_archive_id,
                        archive_parent_descriptor,
                        error_code=BLOCK_AGENT_RUNTIME_FAILED,
                    )
                archive_parent_descriptor = None
                archive_stack.close()
            except Exception as exc:
                rollback_failures: list[str] = []
                for relative, baseline in parent_output_bytes.items():
                    try:
                        exists = _workspace_relative_entry_exists(root, relative)
                        if baseline is None:
                            if not exists:
                                continue
                            _unlink_workspace_file_if_matches(
                                root,
                                relative,
                                expected_bytes=staged_outputs[relative].encode("utf-8"),
                            )
                            continue
                        if not exists:
                            rollback_failures.append(relative)
                            continue
                        current = _read_stable_workspace_file_bytes(
                            root,
                            relative,
                            max_bytes=2 * 1024 * 1024,
                            error_code=BLOCK_AGENT_ORPHANED_WRITER,
                        )
                        if current == staged_outputs[relative].encode("utf-8"):
                            _replace_text_atomic_existing(
                                root,
                                relative,
                                baseline.decode("utf-8"),
                                expected_bytes=current,
                            )
                        elif current != baseline:
                            rollback_failures.append(relative)
                    except (OSError, RuntimeError, UnicodeError):
                        rollback_failures.append(relative)
                try:
                    current_ledger = _read_stable_workspace_file_bytes(
                        root,
                        "identity/web_execution_ledger.md",
                        max_bytes=2 * 1024 * 1024,
                        error_code=BLOCK_AGENT_RUNTIME_FAILED,
                    )
                    if current_ledger == combined_ledger.encode("utf-8"):
                        _replace_text_atomic_existing(
                            root,
                            ledger_relative,
                            parent_ledger,
                            expected_bytes=current_ledger,
                        )
                    elif current_ledger != parent_ledger_bytes:
                        rollback_failures.append("identity/web_execution_ledger.md")
                except (OSError, RuntimeError):
                    rollback_failures.append("identity/web_execution_ledger.md")
                try:
                    _require_parent_workspace_tree_unchanged(view, root)
                except (OSError, RuntimeError):
                    rollback_failures.append("parent_workspace_evidence_tree")
                try:
                    rolled_back_ledger = _read_stable_workspace_file_bytes(
                        root,
                        "identity/web_execution_ledger.md",
                        max_bytes=2 * 1024 * 1024,
                        error_code=BLOCK_AGENT_ORPHANED_WRITER,
                    )
                    if rolled_back_ledger != parent_ledger_bytes:
                        rollback_failures.append("identity/web_execution_ledger.md")
                except (OSError, RuntimeError):
                    rollback_failures.append("identity/web_execution_ledger.md")
                for relative, baseline in parent_output_bytes.items():
                    try:
                        exists = _workspace_relative_entry_exists(root, relative)
                        if baseline is None and exists:
                            rollback_failures.append(relative)
                        elif baseline is not None and (
                            not exists
                            or _read_stable_workspace_file_bytes(
                                root,
                                relative,
                                max_bytes=2 * 1024 * 1024,
                                error_code=BLOCK_AGENT_ORPHANED_WRITER,
                            )
                            != baseline
                        ):
                            rollback_failures.append(relative)
                    except (OSError, RuntimeError):
                        rollback_failures.append(relative)
                if archive_created and archive_bytes is not None:
                    try:
                        if archive_parent_descriptor is not None and archive_name:
                            _unlink_private_resume_archive_at(
                                archive_parent_descriptor,
                                archive_name,
                                expected_bytes=archive_bytes,
                                relative=view.prior_output_archive_id,
                            )
                        else:
                            with _open_private_resume_archive_parent_fd(
                                self.config.state_root,
                                view.prior_output_archive_id,
                                error_code=BLOCK_AGENT_ORPHANED_WRITER,
                                create_parents=False,
                                reject_existing_attempt=False,
                                require_file_absent=False,
                            ) as (rollback_parent_descriptor, rollback_name):
                                _unlink_private_resume_archive_at(
                                    rollback_parent_descriptor,
                                    rollback_name,
                                    expected_bytes=archive_bytes,
                                    relative=view.prior_output_archive_id,
                                )
                    except (OSError, RuntimeError):
                        rollback_failures.append("prior_memo_archive")
                if rollback_failures:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_ORPHANED_WRITER}: resume promotion rollback failed:"
                        + ",".join(dict.fromkeys(rollback_failures))
                    ) from exc
                raise

    @contextmanager
    def _workspace_promotion_lock(self, workspace: Path):
        with workspace_transaction_lock(
            self.config.state_root,
            workspace,
            error_code=BLOCK_AGENT_RUNTIME_FAILED,
        ):
            yield

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
        git_dir: Path | None,
        aws_env_file: Path | None,
        profile_config_readonly: Path | None,
        auth_store_path: Path | None,
        worktree_mount_source: Path | None = None,
        workspace_readonly: bool = False,
        workspace_mount_source: Path | None = None,
        protected_workspace_relatives: tuple[str, ...] = (),
        writable_workspace_relatives: tuple[str, ...] = (),
        writable_workspace_source_root: Path | None = None,
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
            _mount(
                worktree_mount_source or worktree,
                readonly=True,
                target=worktree,
            ),
            "--mount",
            _mount(
                workspace_mount_source or workspace,
                readonly=workspace_readonly,
                target=workspace,
            ),
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
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "AWS_EC2_METADATA_DISABLED=true",
            "--env",
            f"NO_PROXY={urlsplit(self.config.container_model_broker_url).hostname}",
            "--env",
            f"no_proxy={urlsplit(self.config.container_model_broker_url).hostname}",
        ]
        if git_dir is not None:
            command.extend(
                [
                    "--mount",
                    _mount(git_dir, readonly=True),
                    "--env",
                    f"GIT_DIR={git_dir}",
                    "--env",
                    f"GIT_WORK_TREE={worktree}",
                    "--env",
                    "GIT_OPTIONAL_LOCKS=0",
                ]
            )
        protected_relatives: list[str] = []
        if workspace_mount_source is None:
            protected_relatives.extend(
                [
                    "manifest.json",
                    "identity/web_research_request.json",
                    "identity/data_catalog_summary.json",
                    "identity/factor_knowledge_summary.json",
                    "identity/web_research_authoring_contract.json",
                    "identity/web_research_runtime.md",
                    "identity/web_agent_task.md",
                    "identity/web_agent_resume.md",
                    "identity/web_agent_resume_contract.json",
                    "identity/web_main_agent_mechanism_answer_form.json",
                    "identity/web_resume_authorization.json",
                    "reports/user_hypothesis.md",
                ]
            )
        protected_relatives.extend(protected_workspace_relatives)
        protected_source_root = workspace_mount_source or workspace
        for relative in dict.fromkeys(protected_relatives):
            try:
                protected = _safe_workspace_relative_file(
                    protected_source_root,
                    relative,
                    must_exist=True,
                )
            except RuntimeError:
                if relative in protected_workspace_relatives:
                    raise
                continue
            command.extend(
                [
                    "--mount",
                    _mount(
                        protected,
                        readonly=True,
                        target=workspace / relative,
                    ),
                ]
            )
        for relative in writable_workspace_relatives:
            writable = _safe_workspace_relative_file(
                writable_workspace_source_root
                or workspace_mount_source
                or workspace,
                relative,
                must_exist=True,
            )
            command.extend(
                [
                    "--mount",
                    _mount(
                        writable,
                        readonly=False,
                        target=workspace / relative,
                    ),
                ]
            )
        if aws_env_file is not None:
            command.extend(["--env-file", str(aws_env_file)])
        if profile_config_readonly is not None:
            command.extend(["--mount", _mount(profile_config_readonly, readonly=True)])
        if auth_store_path is not None:
            command.extend(["--mount", _mount(auth_store_path, readonly=False)])
        python_paths = [str(worktree)]
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
        *,
        allow_missing_history: bool = False,
        include_aws_credentials: bool = True,
    ) -> tuple[Path | None, tuple[str, ...], Path | None]:
        scan_root = self.config.model_broker_secret_scan_root
        scan_path = scan_root / f"{self.config.installation_id}.{job_id}.secrets"
        scan_existed = scan_path.exists() or scan_path.is_symlink()
        first_issuance = False
        if re.fullmatch(r"job_[a-f0-9]{10}", job_id):
            state = self.credential_material_state(job_id)
            if state == "unknown":
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: credential material state is uninitialized"
                )
            if state == "not_issued":
                if not allow_missing_history:
                    raise RuntimeError(
                        f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: credential issuance was not armed"
                    )
                first_issuance = True
            if state == "may_have_been_issued" and not scan_existed and not allow_missing_history:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: prior denied-secret registry is missing"
                )
        credentials: _AwsCredentialLease | None = None
        if include_aws_credentials:
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
            secret_values = (
                broker_client_token,
                credentials.access_key,
                credentials.secret_key,
                credentials.token,
            )
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
            if not scan_existed:
                scan_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: model broker secret scanner registration failed"
            ) from exc
        try:
            if first_issuance and credentials is not None:
                self._mark_credential_material_may_have_been_issued(job_id)
            if credentials is not None and env_path is not None:
                lines = [
                    f"AWS_ACCESS_KEY_ID={credentials.access_key}",
                    f"AWS_SECRET_ACCESS_KEY={credentials.secret_key}",
                    f"AWS_SESSION_TOKEN={credentials.token}",
                    f"AWS_CREDENTIAL_EXPIRATION={credentials.expires_at.isoformat()}",
                ]
                descriptor = os.open(
                    env_path,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                try:
                    payload = ("\n".join(lines) + "\n").encode("utf-8")
                    offset = 0
                    while offset < len(payload):
                        offset += os.write(descriptor, payload[offset:])
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                _fsync_directory(env_path.parent)
        except (OSError, RuntimeError) as exc:
            if env_path is not None:
                env_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: task credential lease publication failed"
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

    def prepare_host_data_environment(
        self,
        job_id: str,
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        env_path, denied_values, _scan_path = self._prepare_aws_environment(
            job_id,
            allow_missing_history=(
                self.credential_material_state(job_id) == "not_issued"
            ),
        )
        if env_path is None:
            if self.config.data_catalogs and not self.config.auth_disabled:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: host data lease is unavailable"
                )
            return {}, denied_values
        try:
            metadata = env_path.lstat()
            if (
                env_path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o077
                or metadata.st_size > 16 * 1024
            ):
                raise RuntimeError("host data lease file is unsafe")
            entries: dict[str, str] = {}
            for line in env_path.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition("=")
                if not separator or key in entries or not value or "\x00" in value:
                    raise RuntimeError("host data lease file is invalid")
                entries[key] = value
            required = {
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN",
                "AWS_CREDENTIAL_EXPIRATION",
            }
            if set(entries) != required:
                raise RuntimeError("host data lease file is invalid")
            return entries, denied_values
        except (OSError, UnicodeError, RuntimeError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: host data lease publication failed"
            ) from exc
        finally:
            self._cleanup_aws_environment(env_path, None)

    def credential_material_state(self, job_id: str) -> str:
        marker_root = self._credential_material_marker_root()
        if not marker_root.exists() and not marker_root.is_symlink():
            return "unknown"
        try:
            root_metadata = marker_root.lstat()
        except OSError as exc:
            raise RuntimeError("credential material state root is unsafe") from exc
        if (
            marker_root.is_symlink()
            or not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_mode & 0o077
        ):
            raise RuntimeError("credential material state root is unsafe")
        marker = self._credential_material_marker_path(job_id)
        if not marker.exists() and not marker.is_symlink():
            return "unknown"
        try:
            descriptor = os.open(
                marker,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("credential material state marker is unsafe") from exc
        try:
            metadata = os.fstat(descriptor)
            payload = os.read(descriptor, 256).decode("utf-8")
            if os.read(descriptor, 1):
                raise RuntimeError("credential material state marker is unsafe")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("credential material state marker is unsafe") from exc
        finally:
            os.close(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise RuntimeError("credential material state marker is unsafe")
        states = {
            "factorforge_console_credential_material_not_issued_v1\n": "not_issued",
            "factorforge_console_credential_material_may_have_been_issued_v1\n": (
                "may_have_been_issued"
            ),
        }
        if payload not in states:
            raise RuntimeError("credential material state marker is unsafe")
        return states[payload]

    def deactivate_denied_secrets(self, job_id: str) -> None:
        _deactivate_denied_secret_registry(self._denied_secret_path(job_id))

    def clear_denied_secrets(self, job_id: str) -> None:
        self._cleanup_aws_environment(None, self._denied_secret_path(job_id))
        marker = self._credential_material_marker_path(job_id)
        if self.credential_material_state(job_id) != "unknown":
            marker.unlink()

    def _initialize_credential_material_state(self, job_id: str, *, resume: bool) -> None:
        if self.credential_material_state(job_id) != "unknown":
            return
        self._write_credential_material_state(
            job_id,
            "may_have_been_issued" if resume else "not_issued",
            replace=False,
        )

    def _mark_credential_material_may_have_been_issued(self, job_id: str) -> None:
        state = self.credential_material_state(job_id)
        if state == "may_have_been_issued":
            return
        if state != "not_issued":
            raise RuntimeError("credential material state marker is unsafe")
        self._write_credential_material_state(
            job_id,
            "may_have_been_issued",
            replace=True,
        )

    def _write_credential_material_state(
        self,
        job_id: str,
        state: str,
        *,
        replace: bool,
    ) -> None:
        payloads = {
            "not_issued": b"factorforge_console_credential_material_not_issued_v1\n",
            "may_have_been_issued": (
                b"factorforge_console_credential_material_may_have_been_issued_v1\n"
            ),
        }
        if state not in payloads:
            raise RuntimeError("credential material state is invalid")
        marker = self._credential_material_marker_path(job_id)
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        root_metadata = marker.parent.lstat()
        if (
            marker.parent.is_symlink()
            or not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_mode & 0o077
        ):
            raise RuntimeError("credential material state root is unsafe")
        destination = marker
        if replace:
            destination = marker.parent / f".{marker.name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            payload = payloads[state]
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if replace:
            try:
                destination.replace(marker)
            finally:
                destination.unlink(missing_ok=True)
        _fsync_directory(marker.parent)

    def _credential_material_marker_path(self, job_id: str) -> Path:
        if not re.fullmatch(r"job_[a-f0-9]{10}", job_id):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: task identity is invalid"
            )
        return self._credential_material_marker_root() / f"{job_id}.marker"

    def _credential_material_marker_root(self) -> Path:
        return self.config.state_root / "credential-states"

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
        *,
        expected_tools: list[str] = REQUIRED_CONTAINER_TOOLS,
    ) -> None:
        try:
            payload = json.loads(profile_config.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent profile config is unreadable") from exc
        _validate_profile_policy(
            payload,
            expected_model_broker_url=self.config.container_model_broker_url,
            expected_tools=expected_tools,
        )
        agents = ((payload.get("agents") or {}).get("list") or []) if isinstance(payload, dict) else []
        match = next((item for item in agents if str(item.get("id") or "") == agent_id), None)
        agent_ids = [str(item.get("id") or "") for item in agents if isinstance(item, dict)]
        if (
            not isinstance(match, dict)
            or len(agent_ids) != len(agents)
            or len(agent_ids) != len(set(agent_ids))
            or set(agent_ids) not in ({agent_id}, {"main", agent_id})
        ):
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
                    f"{BLOCK_AGENT_ORPHANED_WRITER}: stale agent container could not be removed"
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
                f"{BLOCK_AGENT_ORPHANED_WRITER}: stale agent containers remain after reconciliation"
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

    def _validate_credential_state_mount_boundary(self) -> None:
        script = r"""
import sys
from pathlib import Path

private_root = Path(sys.argv[1])
if private_root.exists():
    raise SystemExit(2)
try:
    private_root.mkdir(parents=True)
except OSError:
    raise SystemExit(0)
raise SystemExit(3)
"""
        self._run_runtime(
            [
                self.config.container_runtime,
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "128m",
                "--cpus",
                "0.25",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                self.config.agent_container_image,
                "python3",
                "-c",
                script,
                str(self._credential_material_marker_root()),
            ],
            timeout=20,
            label="credential state container mount-boundary probe",
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
            f"FACTORFORGE_S3_PROXY_URL={self.config.container_proxy_url}",
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


def _mount(
    path: Path,
    *,
    readonly: bool,
    target: Path | None = None,
) -> str:
    mode = ",readonly" if readonly else ""
    return f"type=bind,src={path},dst={target or path}{mode}"


def _validated_relative_parts(relative: str, *, error_code: str) -> tuple[str, ...]:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or relative_path == Path(".")
        or ".." in relative_path.parts
    ):
        raise RuntimeError(f"{error_code}: workspace path is unsafe:{relative}")
    return relative_path.parts


def _open_absolute_directory_fd(path: Path, *, error_code: str) -> int:
    if not path.is_absolute():
        raise RuntimeError(f"{error_code}: workspace root must be absolute")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(f"{error_code}: workspace root is not a directory")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _open_workspace_parent_fd(
    workspace: Path,
    relative: str,
    *,
    error_code: str,
):
    parts = _validated_relative_parts(relative, error_code=error_code)
    descriptor = _open_absolute_directory_fd(workspace, error_code=error_code)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        for part in parts[:-1]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def _read_stable_file_at(
    parent_descriptor: int,
    name: str,
    *,
    relative: str,
    max_bytes: int,
    error_code: str,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise RuntimeError(
            f"{error_code}: workspace file cannot be opened safely:{relative}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > max_bytes
        ):
            raise RuntimeError(
                f"{error_code}: workspace file is unsafe or too large:{relative}"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        try:
            path_after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise RuntimeError(
                f"{error_code}: workspace file changed while reading:{relative}"
            ) from exc
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        path_identity = (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_size,
            path_after.st_mtime_ns,
            path_after.st_ctime_ns,
        )
        if (
            before_identity != after_identity
            or after_identity != path_identity
            or len(payload) != before.st_size
        ):
            raise RuntimeError(
                f"{error_code}: workspace file changed while reading:{relative}"
            )
        return payload
    finally:
        os.close(descriptor)


def _hash_stable_file_at(
    parent_descriptor: int,
    name: str,
    *,
    relative: str,
    max_bytes: int,
    error_code: str,
) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > max_bytes
        ):
            raise RuntimeError(
                f"{error_code}: workspace tree file is unsafe or too large:{relative}"
            )
        digest = hashlib.sha256()
        bytes_read = 0
        while bytes_read < before.st_size:
            chunk = os.read(
                descriptor,
                min(before.st_size - bytes_read, 1024 * 1024),
            )
            if not chunk:
                break
            digest.update(chunk)
            bytes_read += len(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        identities = {
            (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
            for item in (before, after, path_after)
        }
        if len(identities) != 1 or bytes_read != before.st_size:
            raise RuntimeError(
                f"{error_code}: workspace tree file changed while reading:{relative}"
            )
        return digest.hexdigest(), bytes_read
    finally:
        os.close(descriptor)


def _workspace_tree_snapshot(
    workspace: Path,
    *,
    excluded_file_relatives: tuple[str, ...],
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    error_code = BLOCK_AGENT_RUNTIME_FAILED
    excluded = set(excluded_file_relatives)
    file_digests: list[tuple[str, str]] = []
    directories: list[str] = []
    total_bytes = 0
    file_count = 0
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    root_descriptor = _open_absolute_directory_fd(
        workspace,
        error_code=error_code,
    )
    root_identity = os.fstat(root_descriptor)

    def walk(directory_descriptor: int, prefix: str) -> None:
        nonlocal total_bytes, file_count
        with os.scandir(directory_descriptor) as iterator:
            entries = sorted(
                (
                    (entry.name, entry.stat(follow_symlinks=False))
                    for entry in iterator
                ),
                key=lambda item: item[0],
            )
        for entry_name, metadata in entries:
            relative = f"{prefix}/{entry_name}" if prefix else entry_name
            if stat.S_ISLNK(metadata.st_mode):
                raise RuntimeError(
                    f"{error_code}: parent workspace tree contains a symlink:{relative}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                child_descriptor = os.open(
                    entry_name,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                try:
                    child_metadata = os.fstat(child_descriptor)
                    if (
                        child_metadata.st_dev != metadata.st_dev
                        or child_metadata.st_ino != metadata.st_ino
                    ):
                        raise RuntimeError(
                            f"{error_code}: parent workspace directory changed:{relative}"
                        )
                    directories.append(relative)
                    walk(child_descriptor, relative)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise RuntimeError(
                    f"{error_code}: parent workspace tree contains an unsafe entry:{relative}"
                )
            file_count += 1
            if file_count > 100_000:
                raise RuntimeError(
                    f"{error_code}: parent workspace tree contains too many files"
                )
            if relative in excluded:
                continue
            digest, size = _hash_stable_file_at(
                directory_descriptor,
                entry_name,
                relative=relative,
                max_bytes=4 * 1024 * 1024 * 1024,
                error_code=error_code,
            )
            total_bytes += size
            if total_bytes > 8 * 1024 * 1024 * 1024:
                raise RuntimeError(
                    f"{error_code}: parent workspace tree is too large"
                )
            file_digests.append((relative, digest))

    try:
        walk(root_descriptor, "")
        verification_descriptor = _open_absolute_directory_fd(
            workspace,
            error_code=error_code,
        )
        try:
            verification_identity = os.fstat(verification_descriptor)
            if (
                root_identity.st_dev != verification_identity.st_dev
                or root_identity.st_ino != verification_identity.st_ino
            ):
                raise RuntimeError(
                    f"{error_code}: parent workspace root changed while scanning"
                )
        finally:
            os.close(verification_descriptor)
    finally:
        os.close(root_descriptor)
    return tuple(file_digests), tuple(directories)


def _require_parent_workspace_tree_unchanged(
    view: _ResumeWorkspaceView,
    workspace: Path,
) -> None:
    current_files, current_directories = _workspace_tree_snapshot(
        workspace,
        excluded_file_relatives=(
            "identity/web_execution_ledger.md",
            *(relative for relative, _baseline in view.parent_output_bytes),
        ),
    )
    if (
        current_files != view.parent_tree_file_sha256
        or current_directories != view.parent_tree_directory_relatives
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: parent workspace evidence tree changed"
        )


def _write_text_atomic_new(path: Path, text: str, *, root: Path) -> None:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: new output path escapes workspace"
        ) from exc
    with _open_workspace_parent_fd(
        root,
        relative,
        error_code=BLOCK_AGENT_RUNTIME_FAILED,
    ) as (parent_descriptor, name):
        try:
            os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: new output path already exists:{relative}"
            )
        temporary = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            payload = text.encode("utf-8")
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(
                temporary,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            os.fsync(parent_descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass


def _write_private_resume_archive_at(
    parent_descriptor: int,
    name: str,
    payload: bytes,
    *,
    relative: str,
) -> None:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: prior memo archive already exists"
        )
    temporary = f".{name}.{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    temporary_exists = False
    linked = False
    file_identity: tuple[int, int] | None = None
    descriptor_close_uncertain = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_exists = True
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fchmod(descriptor, 0o400)
        os.fsync(descriptor)
        written_metadata = os.fstat(descriptor)
        file_identity = (written_metadata.st_dev, written_metadata.st_ino)
        os.link(
            temporary,
            name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(temporary, dir_fd=parent_descriptor)
        temporary_exists = False
        os.fsync(parent_descriptor)
        published_metadata = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(published_metadata.st_mode)
            or published_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(published_metadata.st_mode) != 0o400
            or published_metadata.st_nlink != 1
            or file_identity
            != (published_metadata.st_dev, published_metadata.st_ino)
            or _read_stable_file_at(
                parent_descriptor,
                name,
                relative=relative,
                max_bytes=2 * 1024 * 1024,
                error_code=BLOCK_AGENT_RUNTIME_FAILED,
            )
            != payload
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: prior memo archive changed"
            )
        try:
            os.close(descriptor)
        except OSError as close_exc:
            descriptor = None
            descriptor_close_uncertain = True
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: prior memo archive descriptor close failed"
            ) from close_exc
        descriptor = None
    except Exception as exc:
        cleanup_failed = False
        if linked:
            try:
                current = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if file_identity != (current.st_dev, current.st_ino):
                    cleanup_failed = True
                else:
                    os.unlink(name, dir_fd=parent_descriptor)
                    os.fsync(parent_descriptor)
            except FileNotFoundError:
                pass
            except OSError:
                cleanup_failed = True
        if temporary_exists:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
                temporary_exists = False
                os.fsync(parent_descriptor)
            except FileNotFoundError:
                temporary_exists = False
            except OSError:
                cleanup_failed = True
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                descriptor_close_uncertain = True
            descriptor = None
        if cleanup_failed or descriptor_close_uncertain:
            if (
                isinstance(exc, RuntimeError)
                and str(exc).startswith(BLOCK_AGENT_ORPHANED_WRITER)
            ):
                raise
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: prior memo archive cleanup failed"
            ) from exc
        raise


def _require_private_resume_archive_parent_still_bound(
    state_root: Path,
    archive_relative: str,
    expected_parent_descriptor: int,
    *,
    error_code: str,
) -> None:
    expected = os.fstat(expected_parent_descriptor)
    with _open_private_resume_archive_parent_fd(
        state_root,
        archive_relative,
        error_code=error_code,
        create_parents=False,
        reject_existing_attempt=False,
        require_file_absent=False,
    ) as (current_parent_descriptor, _name):
        current = os.fstat(current_parent_descriptor)
        if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError(
                f"{error_code}: prior memo archive parent changed"
            )


def _unlink_private_resume_archive_at(
    parent_descriptor: int,
    name: str,
    *,
    expected_bytes: bytes,
    relative: str,
) -> None:
    descriptor = os.open(
        name,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_descriptor,
    )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o400
            or before.st_nlink != 1
            or before.st_size != len(expected_bytes)
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: prior memo archive is unsafe"
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        current = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            b"".join(chunks) != expected_bytes
            or (before.st_dev, before.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: prior memo archive changed"
            )
        os.unlink(name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    finally:
        os.close(descriptor)


def _replace_text_atomic_existing(
    workspace: Path,
    relative: str,
    text: str,
    *,
    expected_bytes: bytes,
) -> None:
    with _open_workspace_parent_fd(
        workspace,
        relative,
        error_code=BLOCK_AGENT_ORPHANED_WRITER,
    ) as (parent_descriptor, name):
        current = _read_stable_file_at(
            parent_descriptor,
            name,
            relative=relative,
            max_bytes=2 * 1024 * 1024,
            error_code=BLOCK_AGENT_ORPHANED_WRITER,
        )
        if current != expected_bytes:
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: existing output changed:{relative}"
            )
        temporary = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        try:
            payload = text.encode("utf-8")
            offset = 0
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            current = _read_stable_file_at(
                parent_descriptor,
                name,
                relative=relative,
                max_bytes=2 * 1024 * 1024,
                error_code=BLOCK_AGENT_ORPHANED_WRITER,
            )
            if current != expected_bytes:
                raise RuntimeError(
                    f"{BLOCK_AGENT_ORPHANED_WRITER}: existing output changed:{relative}"
                )
            os.replace(
                temporary,
                name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
            os.fsync(parent_descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass


def _unlink_workspace_file_if_matches(
    workspace: Path,
    relative: str,
    *,
    expected_bytes: bytes,
) -> None:
    with _open_workspace_parent_fd(
        workspace,
        relative,
        error_code=BLOCK_AGENT_ORPHANED_WRITER,
    ) as (parent_descriptor, name):
        current = _read_stable_file_at(
            parent_descriptor,
            name,
            relative=relative,
            max_bytes=2 * 1024 * 1024,
            error_code=BLOCK_AGENT_ORPHANED_WRITER,
        )
        if current != expected_bytes:
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: promoted output changed:{relative}"
            )
        os.unlink(name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)


def _workspace_relative_entry_exists(workspace: Path, relative: str) -> bool:
    with _open_workspace_parent_fd(
        workspace,
        relative,
        error_code=BLOCK_AGENT_RUNTIME_FAILED,
    ) as (parent_descriptor, name):
        try:
            os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True


def _validate_openclaw_terminal_status(stdout: str, stderr: str) -> str:
    if not stdout.strip() or len(stdout.encode("utf-8")) > 2 * 1024 * 1024:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal receipt is missing or too large"
        )
    try:
        receipt = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal receipt is invalid JSON"
        ) from exc
    if not isinstance(receipt, dict):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal receipt must be an object"
        )
    raw_payloads = receipt.get("payloads")
    payloads = [] if raw_payloads is None else raw_payloads
    metadata = receipt.get("meta")
    agent_metadata = metadata.get("agentMeta") if isinstance(metadata, dict) else None
    optional_final_text = (
        metadata.get("finalAssistantVisibleText")
        if isinstance(metadata, dict)
        else None
    )
    replay_invalid = metadata.get("replayInvalid") if isinstance(metadata, dict) else None
    payload_texts = (
        [
            str(item.get("text") or "").strip()
            for item in payloads
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if isinstance(payloads, list)
        else []
    )
    lifecycle_matches = re.findall(
        r"embedded run agent end:[^\n]*\bisError=(true|false)\b",
        stderr[-2 * 1024 * 1024 :],
        flags=re.IGNORECASE,
    )
    lifecycle_terminal = (
        lifecycle_matches[-1].lower() if lifecycle_matches else ""
    )
    if lifecycle_terminal == "true":
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw stderr reported a terminal agent error"
        )
    if (
        not isinstance(payloads, list)
        or any(not isinstance(item, dict) for item in payloads)
        or not isinstance(metadata, dict)
        or not isinstance(agent_metadata, dict)
        or (
            optional_final_text is not None
            and not isinstance(optional_final_text, str)
        )
        or (replay_invalid is not None and not isinstance(replay_invalid, bool))
        or not (
            payload_texts
            or (
                isinstance(optional_final_text, str)
                and optional_final_text.strip()
            )
            or lifecycle_terminal == "false"
        )
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal receipt schema is invalid"
        )
    if replay_invalid is True:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal replay is invalid"
        )
    final_text = (
        optional_final_text.strip()
        if isinstance(optional_final_text, str) and optional_final_text.strip()
        else (payload_texts[-1] if payload_texts else "")
    )
    for item in (receipt, metadata, agent_metadata, *payloads):
        if "isError" in item:
            if not isinstance(item["isError"], bool):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal receipt schema is invalid"
                )
            if item["isError"]:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw reported a terminal agent error"
                )
        for status_key in ("status", "state"):
            if status_key not in item:
                continue
            if not isinstance(item[status_key], str):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw terminal receipt schema is invalid"
                )
            status = item[status_key].strip().lower()
            if status not in {"", "ok", "success", "succeeded", "complete", "completed"}:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw reported a terminal agent error"
                )
        error = item.get("error")
        if error not in (None, "", False):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw reported a terminal agent error"
            )
    terminal_error_prefixes = (
        "Context overflow:",
        "Agent failed:",
        "Model request failed:",
        "No response from model",
        "No response generated",
        "Request failed:",
    )
    if final_text.strip().startswith(terminal_error_prefixes):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: OpenClaw reported a terminal model error"
        )
    return final_text


def _audit_resume_workspace_view(view: _ResumeWorkspaceView) -> None:
    if view.root.is_symlink():
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace view root is unsafe"
        )
    root = view.root.resolve(strict=True)
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace view root is unsafe"
        )
    entries = sorted(root.rglob("*"))
    relatives = tuple(path.relative_to(root).as_posix() for path in entries)
    if relatives != view.allowed_entry_relatives or len(entries) > 64:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace view contains unexpected entries"
        )
    total_bytes = 0
    writable_relatives = set(view.writable_relatives)
    for path in entries:
        metadata = path.lstat()
        relative = path.relative_to(root).as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace view contains a symlink"
            )
        if stat.S_ISDIR(metadata.st_mode):
            if metadata.st_mode & 0o077:
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace directory permissions are too broad"
                )
            continue
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace file is unsafe"
            )
        if relative in writable_relatives:
            path.chmod(0o600)
            metadata = path.lstat()
        elif metadata.st_mode & 0o077:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace file permissions are too broad"
            )
        total_bytes += metadata.st_size
    if total_bytes > 8 * 1024 * 1024:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: resume workspace view is too large"
        )


def _read_stable_workspace_file_bytes(
    workspace: Path,
    relative: str,
    *,
    max_bytes: int,
    error_code: str = BLOCK_AGENT_RUNTIME_UNAVAILABLE,
) -> bytes:
    with _open_workspace_parent_fd(
        workspace,
        relative,
        error_code=error_code,
    ) as (parent_descriptor, name):
        return _read_stable_file_at(
            parent_descriptor,
            name,
            relative=relative,
            max_bytes=max_bytes,
            error_code=error_code,
        )


def _validate_resume_research_patch(
    answer_form: dict[str, Any],
    memo: dict[str, Any],
) -> None:
    def invalid_patch(detail: str) -> RuntimeError:
        return RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: resume terminal research patch "
            f"is invalid:{detail}"
        )

    if set(memo) != set(RESUME_MEMO_AGENT_PATCH_FIELDS):
        raise invalid_patch("top-level field set")

    def exact_object(field: str) -> dict[str, Any]:
        canonical = answer_form.get(field)
        patch = memo.get(field)
        if not isinstance(canonical, dict):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: canonical resume answer form is incomplete"
            )
        if not isinstance(patch, dict) or set(patch) != set(canonical):
            raise invalid_patch(f"{field} field set")
        return patch

    def require_string_map(field: str) -> dict[str, Any]:
        patch = exact_object(field)
        if any(
            not isinstance(value, str) or not value.strip()
            for value in patch.values()
        ):
            raise invalid_patch(f"{field} value type")
        return patch

    def require_string_list(field: str, *, minimum: int = 0) -> list[str]:
        value = memo.get(field)
        if (
            not isinstance(value, list)
            or len(value) < minimum
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            raise invalid_patch(f"{field} value type")
        return value

    if memo.get("producer") != "current_main_agent":
        raise invalid_patch("producer")
    authorship = exact_object("agent_authorship")
    if (
        authorship.get("authoring_mode") != "current_agent_freeform"
        or authorship.get("agent_role") != "main_agent"
        or authorship.get("answered_without_deterministic_template") is not True
    ):
        raise invalid_patch("agent_authorship value")

    require_string_map("mechanism_qa")
    require_string_map("economic_hypothesis")
    require_string_map("math_model_selection")
    require_string_map("payer")

    math_hypothesis = exact_object("math_hypothesis")
    math_signature = math_hypothesis.get("expected_metric_signature")
    canonical_math = answer_form["math_hypothesis"]
    canonical_math_signature = canonical_math.get("expected_metric_signature")
    if (
        not isinstance(math_signature, dict)
        or not isinstance(canonical_math_signature, dict)
        or set(math_signature) != set(canonical_math_signature)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in math_signature.values()
        )
        or any(
            not isinstance(value, str) or not value.strip()
            for key, value in math_hypothesis.items()
            if key != "expected_metric_signature"
        )
    ):
        raise invalid_patch("math_hypothesis value type")

    require_string_map("expected_metric_signature")
    require_string_list("falsification_tests", minimum=2)
    require_string_list("council_questions")

    canonical_components = answer_form.get("formula_component_map")
    patch_components = memo.get("formula_component_map")
    if (
        not isinstance(canonical_components, list)
        or not canonical_components
        or not isinstance(patch_components, list)
        or len(canonical_components) != len(patch_components)
    ):
        raise invalid_patch("component count")
    component_ids: list[str] = []
    for canonical_component, patch_component in zip(
        canonical_components,
        patch_components,
    ):
        component_id = (
            canonical_component.get("component_id")
            if isinstance(canonical_component, dict)
            else None
        )
        if not isinstance(component_id, str) or not component_id.strip():
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: canonical resume answer form is incomplete"
            )
        component_ids.append(component_id)
        if (
            not isinstance(patch_component, dict)
            or set(patch_component) != set(RESUME_MEMO_AGENT_COMPONENT_FIELDS)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in patch_component.values()
            )
        ):
            raise invalid_patch("component field")

    state_estimator = exact_object("formula_state_estimator")
    component_links = state_estimator.get("component_links")
    if (
        any(
            not isinstance(state_estimator.get(field), str)
            or not str(state_estimator.get(field)).strip()
            for field in ("latent_state", "observable_mapping")
        )
        or not isinstance(component_links, list)
        or not component_links
        or any(not isinstance(item, str) or not item.strip() for item in component_links)
        or len(component_links) != len(set(component_links))
        or not set(component_links).issubset(component_ids)
    ):
        raise invalid_patch("formula_state_estimator value type")

    canonical_evidence = answer_form.get("evidence_comparison")
    evidence = memo.get("evidence_comparison")
    if (
        not isinstance(canonical_evidence, dict)
        or not isinstance(canonical_evidence.get("observed_metrics"), dict)
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: canonical resume answer form is incomplete"
        )
    if (
        not isinstance(evidence, dict)
        or set(evidence) != set(RESUME_MEMO_AGENT_EVIDENCE_FIELDS)
    ):
        raise invalid_patch("evidence_comparison field set")
    if (
        not isinstance(evidence.get("mechanism_supported"), str)
        or not evidence["mechanism_supported"].strip()
    ):
        raise invalid_patch("evidence_comparison value type")
    for field in (
        "contradictions",
        "revision_implications",
        "kill_criteria_triggered",
    ):
        value = evidence.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise invalid_patch("evidence_comparison value type")

    canonical_operator_claims = answer_form.get("operator_claim_consistency")
    operator_claims = memo.get("operator_claim_consistency")
    if not isinstance(canonical_operator_claims, dict):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: canonical resume answer form is incomplete"
        )
    if (
        not isinstance(operator_claims, dict)
        or set(operator_claims) != set(RESUME_MEMO_AGENT_OPERATOR_FIELDS)
    ):
        raise invalid_patch("operator_claim_consistency field set")
    explicit_justification = operator_claims.get(
        "explicit_dependence_justification"
    )
    if (
        not isinstance(explicit_justification, str)
        or (explicit_justification != "" and not explicit_justification.strip())
        or any(
            operator_claims.get(field) not in (True, False)
            or not isinstance(operator_claims.get(field), bool)
            for field in RESUME_MEMO_AGENT_OPERATOR_FIELDS
            if field != "explicit_dependence_justification"
        )
    ):
        raise invalid_patch("operator_claim_consistency value type")


def _rehydrate_resume_memo_immutable_fields(
    workspace: Path,
    resume_task: AgentResumeTask,
    memo: dict[str, Any],
) -> dict[str, Any]:
    try:
        answer_form = json.loads(
            _read_stable_workspace_file_bytes(
                workspace,
                resume_task.answer_form_relative,
                max_bytes=RESUME_PROMPT_INPUT_MAX_BYTES,
                error_code=BLOCK_AGENT_RUNTIME_FAILED,
            ).decode("utf-8")
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: canonical resume answer form is invalid"
        ) from exc
    if not isinstance(answer_form, dict):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: canonical resume answer form is invalid"
        )

    _validate_resume_research_patch(answer_form, memo)

    rehydrated = deepcopy(answer_form)
    for field in RESUME_MEMO_AGENT_DIRECT_FIELDS:
        if field in memo:
            rehydrated[field] = deepcopy(memo[field])

    if "formula_component_map" in memo:
        canonical_components = answer_form.get("formula_component_map")
        patch_components = memo["formula_component_map"]
        if (
            not isinstance(canonical_components, list)
            or not canonical_components
            or not isinstance(patch_components, list)
            or len(canonical_components) != len(patch_components)
        ):
            raise invalid_patch("component count")
        merged_components: list[dict[str, Any]] = []
        for canonical_component, patch_component in zip(
            canonical_components,
            patch_components,
        ):
            if (
                not isinstance(canonical_component, dict)
                or not isinstance(patch_component, dict)
                or set(patch_component) != set(RESUME_MEMO_AGENT_COMPONENT_FIELDS)
            ):
                raise invalid_patch("component field")
            merged_component = deepcopy(canonical_component)
            merged_component.update(deepcopy(patch_component))
            merged_components.append(merged_component)
        rehydrated["formula_component_map"] = merged_components

    for field, allowed_fields in (
        ("evidence_comparison", RESUME_MEMO_AGENT_EVIDENCE_FIELDS),
        ("operator_claim_consistency", RESUME_MEMO_AGENT_OPERATOR_FIELDS),
    ):
        if field not in memo:
            continue
        canonical_section = answer_form.get(field)
        patch_section = memo[field]
        if (
            not isinstance(canonical_section, dict)
            or not isinstance(patch_section, dict)
            or set(patch_section) != set(allowed_fields)
        ):
            raise invalid_patch(field)
        merged_section = deepcopy(canonical_section)
        merged_section.update(deepcopy(patch_section))
        rehydrated[field] = merged_section

    return rehydrated


def _safe_workspace_relative_file(
    workspace: Path,
    relative: str,
    *,
    must_exist: bool,
) -> Path:
    root = workspace.resolve(strict=True)
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or relative_path == Path(".")
        or ".." in relative_path.parts
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace path is unsafe"
        )
    current = root
    for part in relative_path.parts[:-1]:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace parent is unavailable"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace parent is unsafe"
            )
    path = root / relative_path
    if path.is_symlink():
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace file is a symlink"
        )
    if must_exist and not path.is_file():
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace file is missing"
        )
    if path.exists() and not path.is_file():
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume workspace target is not a file"
        )
    return path


def _prepare_private_resume_archive_path(
    state_root: Path,
    task: AgentResumeTask,
) -> Path:
    expected_relative = (
        f"jobs/{task.job_id}/resume-history/"
        f"{task.attempt_id}/prior_memo.json"
    )
    if (
        task.prior_output_archive_id != expected_relative
        or re.fullmatch(r"job_[A-Za-z0-9_-]{1,64}", task.job_id) is None
        or re.fullmatch(r"resume_[a-f0-9]{32}", task.attempt_id) is None
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: prior memo archive identity is unsafe"
        )
    with _open_private_resume_archive_parent_fd(
        state_root,
        expected_relative,
        error_code=BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        create_parents=True,
        reject_existing_attempt=True,
        require_file_absent=True,
    ):
        pass
    return state_root / expected_relative


@contextmanager
def _open_private_resume_archive_parent_fd(
    state_root: Path,
    archive_relative: str,
    *,
    error_code: str,
    create_parents: bool,
    reject_existing_attempt: bool,
    require_file_absent: bool,
):
    parts = Path(archive_relative).parts
    if (
        len(parts) != 5
        or parts[0] != "jobs"
        or re.fullmatch(r"job_[A-Za-z0-9_-]{1,64}", parts[1]) is None
        or parts[2] != "resume-history"
        or re.fullmatch(r"resume_[a-f0-9]{32}", parts[3]) is None
        or parts[4] != "prior_memo.json"
    ):
        raise RuntimeError(
            f"{error_code}: prior memo archive identity is unsafe"
        )
    try:
        root_descriptor = _open_absolute_directory_fd(
            state_root,
            error_code=error_code,
        )
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            f"{error_code}: prior memo archive state root is unsafe"
        ) from exc
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    current_descriptor = root_descriptor
    opened_descriptors: list[int] = []
    try:
        try:
            root_metadata = os.fstat(root_descriptor)
        except OSError as exc:
            raise RuntimeError(
                f"{error_code}: prior memo archive state root is unsafe"
            ) from exc
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or root_metadata.st_uid != os.geteuid()
            or root_metadata.st_mode & 0o007
        ):
            raise RuntimeError(
                f"{error_code}: prior memo archive state root is unsafe"
            )
        trusted_group_id = root_metadata.st_gid
        try:
            for index, part in enumerate(parts[:-1]):
                leaf_attempt = index == len(parts[:-1]) - 1
                entry_preexisted = True
                try:
                    next_descriptor = os.open(
                        part,
                        directory_flags,
                        dir_fd=current_descriptor,
                    )
                except FileNotFoundError:
                    if not create_parents:
                        raise
                    entry_preexisted = False
                    os.mkdir(part, 0o700, dir_fd=current_descriptor)
                    os.fsync(current_descriptor)
                    next_descriptor = os.open(
                        part,
                        directory_flags,
                        dir_fd=current_descriptor,
                    )
                opened_descriptors.append(next_descriptor)
                if leaf_attempt and reject_existing_attempt and entry_preexisted:
                    raise RuntimeError(
                        f"{error_code}: prior memo archive attempt already exists"
                    )
                metadata = os.fstat(next_descriptor)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_mode & 0o007
                    or (
                        metadata.st_mode & 0o070
                        and metadata.st_gid != trusted_group_id
                    )
                ):
                    raise RuntimeError(
                        f"{error_code}: prior memo archive parent is unsafe"
                    )
                current_descriptor = next_descriptor
            if require_file_absent:
                try:
                    os.stat(
                        parts[-1],
                        dir_fd=current_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise RuntimeError(
                        f"{error_code}: prior memo archive already exists"
                    )
        except OSError as exc:
            raise RuntimeError(
                f"{error_code}: prior memo archive parent is unsafe"
            ) from exc
        yield current_descriptor, parts[-1]
    finally:
        active_exception = sys.exc_info()[1]
        close_failures: list[OSError] = []
        for descriptor in reversed(opened_descriptors):
            try:
                os.close(descriptor)
            except OSError as exc:
                close_failures.append(exc)
        try:
            os.close(root_descriptor)
        except OSError as exc:
            close_failures.append(exc)
        if close_failures and not (
            isinstance(active_exception, RuntimeError)
            and str(active_exception).startswith(BLOCK_AGENT_ORPHANED_WRITER)
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_ORPHANED_WRITER}: prior memo archive parent descriptor close failed"
            ) from (active_exception or close_failures[0])


def _safe_view_relative_path(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or relative_path == Path(".")
        or ".." in relative_path.parts
    ):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: resume view path is unsafe"
        )
    return root / relative_path


def _validate_private_council_result(
    *,
    worktree: Path,
    workspace: Path,
    report_id: str,
    task: CouncilIngressTask,
    payload: dict[str, Any],
) -> list[str]:
    manifest_path = (
        workspace
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"dispatch_manifest__{report_id}.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_task = next(
        (
            item
            for item in manifest.get("agent_tasks") or []
            if isinstance(item, dict) and item.get("task_id") == task.task_id
        ),
        None,
    )
    if not isinstance(expected_task, dict):
        return ["Council task is absent from dispatch manifest"]
    validator_path = (
        worktree
        / "skills"
        / "factor-forge-step6"
        / "scripts"
        / "validate_agentic_council_result.py"
    )
    spec = importlib.util.spec_from_file_location(
        f"factorforge_console_council_validator_{uuid.uuid4().hex}",
        validator_path,
    )
    if spec is None or spec.loader is None:
        return ["Council result validator is unavailable"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FF = workspace
    module.OBJ = workspace / "objects"
    reasons = module.validate_agentic_result(
        payload,
        expected_task=expected_task,
        expected_report_id=report_id,
    )
    return [str(reason) for reason in reasons]


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _stamp(value: str) -> str:
    return value.replace(":", "").replace("-", "")


def _ensure_workspace_parent(path: Path, *, root: Path) -> None:
    root_path = root.resolve(strict=True)
    destination = path.absolute()
    try:
        relative_parent = destination.parent.relative_to(root_path)
    except ValueError as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: Council ingress path escapes workspace"
        ) from exc
    current = root_path
    for part in relative_parent.parts:
        if part in {"", ".", ".."}:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Council ingress path is unsafe"
            )
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Council ingress directory is unavailable"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Council ingress directory is unsafe"
            )


def _promote_council_result_set(
    *,
    workspace: Path,
    validated_results: list[tuple[CouncilIngressTask, dict[str, Any]]],
) -> None:
    if not validated_results:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: Council result set is empty"
        )
    relative_parents = {
        Path(task.expected_result_path).parent
        for task, _payload in validated_results
    }
    if len(relative_parents) != 1:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: Council result set has multiple roots"
        )
    relative_root = next(iter(relative_parents))
    if relative_root.is_absolute() or ".." in relative_root.parts:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: Council result root is unsafe"
        )
    result_root = workspace / relative_root
    _ensure_workspace_parent(result_root, root=workspace)
    if result_root.exists() or result_root.is_symlink():
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_FAILED}: Council result root already exists"
        )
    staging_root = result_root.parent / (
        f".{result_root.name}.console-stage-{uuid.uuid4().hex}"
    )
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    try:
        expected_names: set[str] = set()
        for task, result_payload in validated_results:
            relative_result = Path(task.expected_result_path)
            if (
                relative_result.parent != relative_root
                or not relative_result.name
                or relative_result.name in expected_names
            ):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_FAILED}: Council result identity is unsafe"
                )
            expected_names.add(relative_result.name)
            write_text_atomic(
                staging_root / relative_result.name,
                json.dumps(
                    result_payload,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                root=staging_root,
            )
        staged_names = {
            item.name
            for item in staging_root.iterdir()
            if item.is_file() and not item.is_symlink()
        }
        if staged_names != expected_names:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_FAILED}: Council staged result set is incomplete"
            )
        os.replace(staging_root, result_root)
    except Exception:
        if staging_root.exists() and not staging_root.is_symlink():
            shutil.rmtree(staging_root)
        raise


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
    expected_tools: list[str] = REQUIRED_CONTAINER_TOOLS,
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
    compaction = defaults.get("compaction") or {}
    if any(compaction.get(key) != value for key, value in REQUIRED_COMPACTION_POLICY.items()):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container compaction policy is invalid"
        )
    if tools.get("allow") != expected_tools:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container tool allowlist is invalid")
    exec_policy = tools.get("exec") or {}
    if (
        (tools.get("fs") or {}).get("workspaceOnly") is not True
        or exec_policy.get("host") != "gateway"
        or exec_policy.get("mode") != "full"
        or exec_policy.get("strictInlineEval") is not False
        or "security" in exec_policy
        or "ask" in exec_policy
        or (exec_policy.get("applyPatch") or {}).get("workspaceOnly") is not True
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
    models = deepseek.get("models") or []
    if (
        not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], dict)
        or models[0].get("id") != "deepseek-reasoner"
        or models[0].get("contextWindow") != 131072
        or models[0].get("maxTokens") != 16384
    ):
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: container model budget is invalid")


def _safe_runtime_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")[:96]
    if not token:
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: Council task identity is unsafe"
        )
    return token
