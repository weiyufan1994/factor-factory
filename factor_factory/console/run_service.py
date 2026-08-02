from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from factor_factory.console.agent_adapter import AgentRunResult, ResearchAgentAdapter
from factor_factory.console.artifact_service import SafeArtifact, publish_official_artifacts
from factor_factory.console.catalog_health import catalogs_healthy, require_catalogs_healthy
from factor_factory.console.config import ConsoleConfig
from factor_factory.console.council_ingress import (
    CouncilIngressTask,
    load_council_ingress_tasks,
)
from factor_factory.console.models import (
    ResearchJob,
    ResearchRequest,
    validate_pilot_evaluation_request,
    validate_public_source_url,
)
from factor_factory.console.runner_health import probe_runner_health
from factor_factory.console.secret_safety import redact_secret_values
from factor_factory.console.store import ResearchJobStore, utc_now
from factor_factory.console.ultimate_reader import UltimateRunSummary, read_ultimate_workspace
from factor_factory.console.web_research_plan import (
    required_web_resume_start_step,
    stable_json_hash,
    validate_materialized_web_research,
    write_text_atomic,
    write_web_research_packet,
)
from factor_factory.console.worktree_allocator import (
    FactorWorktreeAllocator,
    WorktreeAllocation,
    WorktreeAllocationError,
)
from factor_factory.research_workspace import load_workspace_manifest, validate_workspace_manifest


BLOCK_ISOLATION_AUDIT_FAILED = "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED"
BLOCK_EVIDENCE_IDENTITY_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_EVIDENCE_IDENTITY_MISMATCH"
BLOCK_FORMAL_EVIDENCE_MISSING = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_EVIDENCE_MISSING"
BLOCK_CREDENTIAL_REGISTRY_INVALID = "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_REGISTRY_INVALID"
BLOCK_AGENT_WRITE_SCOPE_INVALID = "BLOCK_FACTORFORGE_CONSOLE_AGENT_WRITE_SCOPE_INVALID"
BLOCK_HOST_FORMAL_EXECUTION_FAILED = "BLOCK_FACTORFORGE_CONSOLE_HOST_FORMAL_EXECUTION_FAILED"
BLOCK_RESUME_TRUST_INVALID = "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
DATA_API_BRIDGE_RELATIVE = Path("deploy/factorforge-console/data-api-bridge")
PRIVATE_LIFECYCLE_VERSION = "factorforge_console_private_job_lifecycle_v1"
PRIVATE_LIFECYCLE_RUNNING = "RUNNING"
PRIVATE_LIFECYCLE_RESUMABLE = "RESUMABLE"
PRIVATE_LIFECYCLE_TERMINAL = "TERMINAL"
PRIVATE_LIFECYCLE_NON_RESUMABLE = "NON_RESUMABLE"

NON_RESUMABLE_SECURITY_BLOCKERS = frozenset(
    {
        BLOCK_AGENT_WRITE_SCOPE_INVALID,
        BLOCK_ISOLATION_AUDIT_FAILED,
        BLOCK_CREDENTIAL_REGISTRY_INVALID,
        BLOCK_RESUME_TRUST_INVALID,
        "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
    }
)


def _configure_host_formal_python_environment(
    env: dict[str, str],
    *,
    worktree: Path,
    data_api_pythonpath: Path | None,
) -> None:
    try:
        worktree_root = worktree.expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal worktree is invalid"
        ) from exc

    python_paths = [str(worktree_root)]
    excluded_inherited_root: Path | None = None
    env.pop("FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT", None)
    if data_api_pythonpath is not None:
        checkout_candidate = data_api_pythonpath.expanduser()
        package_candidate = checkout_candidate / "factor_factory" / "data_api"
        bridge_candidate = worktree_root / DATA_API_BRIDGE_RELATIVE
        package_entry = package_candidate / "__init__.py"
        bridge_entry = bridge_candidate / "factorforge_data_api" / "__init__.py"
        if (
            checkout_candidate.is_symlink()
            or package_candidate.is_symlink()
            or package_entry.is_symlink()
            or bridge_candidate.is_symlink()
            or bridge_entry.is_symlink()
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Data API bridge path is unsafe"
            )
        try:
            checkout = checkout_candidate.resolve(strict=True)
            package_root = package_candidate.resolve(strict=True)
            bridge_root = bridge_candidate.resolve(strict=True)
            package_root.relative_to(checkout)
            bridge_root.relative_to(worktree_root)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Data API bridge path is invalid"
            ) from exc
        if not package_entry.is_file() or not bridge_entry.is_file():
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Data API bridge package is missing"
            )
        python_paths.append(str(bridge_root))
        excluded_inherited_root = checkout
        env["FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT"] = str(package_root)

    inherited_pythonpath = env.get("PYTHONPATH", "")
    seen_python_paths = set(python_paths)
    for item in inherited_pythonpath.split(os.pathsep):
        value = item.strip()
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = worktree_root / candidate
        try:
            canonical = candidate.resolve(strict=False)
        except RuntimeError:
            continue
        if excluded_inherited_root is not None and (
            canonical == excluded_inherited_root
            or canonical.is_relative_to(excluded_inherited_root)
        ):
            continue
        canonical_value = str(canonical)
        if canonical_value not in seen_python_paths:
            python_paths.append(canonical_value)
            seen_python_paths.add(canonical_value)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["FACTORFORGE_REPO_ROOT"] = str(worktree_root)


def _require_resume_request_allowed(job: ResearchJob) -> None:
    if job.error_code in NON_RESUMABLE_SECURITY_BLOCKERS:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior security blocker is not resumable; "
            "start a new isolated research task"
        )
    if not job.worktree_path or not job.workspace_path or not job.base_commit:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: persisted workspace identity is incomplete"
        )


class ResearchQueueService:
    """Unprivileged web-side queue facade; execution lives in the runner process."""

    def __init__(
        self,
        *,
        store: ResearchJobStore,
        runner_health_socket: str | Path,
        expected_engine_commit: str = "",
        config: ConsoleConfig | None = None,
    ) -> None:
        self.store = store
        self.runner_health_socket = Path(runner_health_socket).expanduser().resolve(strict=False)
        self.expected_engine_commit = expected_engine_commit
        self.config = config

    def start(self) -> None:
        return None

    def stop(self, timeout: float = 10.0) -> None:
        return None

    def healthcheck(self) -> bool:
        payload = probe_runner_health(self.runner_health_socket)
        return bool(
            payload
            and payload.get("ok") is True
            and (self.config is None or catalogs_healthy(self.config))
            and (
                not self.expected_engine_commit
                or payload.get("engine_commit") == self.expected_engine_commit
            )
        )

    def submit(self, request: ResearchRequest) -> ResearchJob:
        validate_pilot_evaluation_request(request)
        if request.source_url:
            raise ValueError(
                "source URL ingestion is disabled until the read-only fetch broker is available"
            )
        if self.config is not None:
            require_catalogs_healthy(self.config)
        if not self.healthcheck():
            raise RuntimeError("BLOCK_FACTORFORGE_CONSOLE_RUNNER_UNAVAILABLE")
        return self.store.create_job(request)

    def request_resume(self, job_id: str) -> ResearchJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        validate_pilot_evaluation_request(job.request)
        _require_resume_request_allowed(job)
        if self.config is not None:
            require_catalogs_healthy(self.config)
        if not self.healthcheck():
            raise RuntimeError("BLOCK_FACTORFORGE_CONSOLE_RUNNER_UNAVAILABLE")
        return self.store.request_resume(job_id)

    def cancel_queued(self, job_id: str) -> ResearchJob:
        return self.store.cancel_queued(job_id)


class ResearchRunService:
    def __init__(
        self,
        *,
        config: ConsoleConfig,
        store: ResearchJobStore,
        allocator: FactorWorktreeAllocator,
        agent_adapter: ResearchAgentAdapter,
        poll_seconds: float = 1.0,
    ) -> None:
        self.config = config
        self.store = store
        self.allocator = allocator
        self.agent_adapter = agent_adapter
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._expected_base_commit = self.allocator.validate_ready()
        self._health_lock = threading.Lock()
        self._health_checked_at = 0.0
        self._health_cached = False
        self._health_ttl_seconds = 30.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.pause_interrupted_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="factorforge-console-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        stop_all = getattr(self.agent_adapter, "stop_all", None)
        if callable(stop_all):
            stop_all()
        if self._thread:
            self._thread.join(timeout=timeout)

    def healthcheck(self) -> bool:
        if not self._thread or not self._thread.is_alive() or self._stop.is_set():
            return False
        now = time.monotonic()
        with self._health_lock:
            if now - self._health_checked_at < self._health_ttl_seconds:
                return self._health_cached
            self._health_cached = self._compute_healthcheck()
            self._health_checked_at = time.monotonic()
            return self._health_cached

    def _compute_healthcheck(self) -> bool:
        adapter_health = getattr(self.agent_adapter, "healthcheck", None)
        try:
            source_ready = self.allocator.validate_ready() == self._expected_base_commit
            runtime_ready = bool(adapter_health()) if callable(adapter_health) else True
        except (OSError, RuntimeError, ValueError):
            return False
        return bool(
            source_ready
            and runtime_ready
            and catalogs_healthy(self.config)
        )

    def submit(self, request: ResearchRequest) -> ResearchJob:
        validate_pilot_evaluation_request(request)
        if request.source_url:
            raise ValueError(
                "source URL ingestion is disabled until the read-only fetch broker is available"
            )
        require_catalogs_healthy(self.config)
        job = self.store.create_job(request)
        self._wake.set()
        return job

    def request_resume(self, job_id: str) -> ResearchJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        validate_pilot_evaluation_request(job.request)
        _require_resume_request_allowed(job)
        require_catalogs_healthy(self.config)
        self._require_private_resume_allowed(job)
        allocation = self.allocator.validate_allocation(
            factor_id=job.factor_id,
            research_id=job.research_id,
            report_id=job.report_id,
            persisted_worktree_path=job.worktree_path,
            persisted_workspace_path=job.workspace_path,
            persisted_base_commit=job.base_commit,
        )
        self._validate_trusted_resume_context(
            job,
            worktree=allocation.worktree_path,
            workspace=allocation.workspace_path,
        )
        job = self.store.request_resume(job_id)
        self._wake.set()
        return job

    def cancel_queued(self, job_id: str) -> ResearchJob:
        return self.store.cancel_queued(job_id)

    def run_once(self) -> ResearchJob | None:
        if not catalogs_healthy(self.config):
            return None
        job = self.store.claim_next_job()
        if job is None:
            return None
        self._run_job(job)
        return self.store.get_job(job.job_id)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            if not catalogs_healthy(self.config) or not self.healthcheck():
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            job = self.store.claim_next_job()
            if job is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            self._run_job(job)

    def _run_job(self, job: ResearchJob) -> None:
        denied_values: tuple[str, ...] = ()
        resume_trust: dict[str, Any] | None = None
        private_completion_status: str | None = None
        private_attestation_id = ""
        council_ingress_tasks: tuple[CouncilIngressTask, ...] = ()
        try:
            resume = bool(job.workspace_path and job.worktree_path)
            self._begin_private_execution(job, resume=resume)
            validate_public_source_url(job.request.source_url)
            if resume:
                allocation = self.allocator.validate_allocation(
                    factor_id=job.factor_id,
                    research_id=job.research_id,
                    report_id=job.report_id,
                    persisted_worktree_path=job.worktree_path,
                    persisted_workspace_path=job.workspace_path,
                    persisted_base_commit=job.base_commit,
                )
                worktree = allocation.worktree_path
                workspace = allocation.workspace_path
                resume_trust = self._validate_trusted_resume_context(
                    job,
                    worktree=worktree,
                    workspace=workspace,
                    private_execution_started=True,
                )
                council_ingress_tasks = _trusted_council_ingress_tasks(
                    workspace,
                    report_id=job.report_id,
                    trusted_resume_proof_sha256=str(
                        resume_trust["ultimate_proof_sha256"]
                    ),
                )
                self._write_request_artifacts(
                    job,
                    allocation,
                    preserve_plan=True,
                    trusted_resume_start_step=str(resume_trust["start_step"]),
                )
                self._write_resume_authorization(job, workspace)
            else:
                allocation = self.allocator.allocate(
                    factor_id=job.factor_id,
                    research_id=job.research_id,
                    report_id=job.report_id,
                    implementation_mode="operator",
                )
                worktree = allocation.worktree_path
                workspace = allocation.workspace_path
                self.store.update_job(
                    job.job_id,
                    base_commit=allocation.base_commit,
                    worktree_path=str(worktree),
                    workspace_path=str(workspace),
                    current_stage="researching",
                )
                self._write_request_artifacts(job, allocation)
                self.store.append_event(
                    job.job_id,
                    "WORKTREE_ALLOCATED",
                    "已分配固定代码版本的独立 Git worktree 和 factor workspace",
                    {"base_commit": allocation.base_commit},
                )

            agent_write_snapshot = _workspace_file_snapshot(workspace)
            allowed_agent_writes, required_agent_outputs = _allowed_agent_write_paths(
                workspace,
                report_id=job.report_id,
                resume=resume,
                trusted_resume_proof_sha256=(
                    str(resume_trust["ultimate_proof_sha256"])
                    if resume_trust is not None
                    else None
                ),
                council_ingress_tasks=council_ingress_tasks,
            )

            self.store.update_job(
                job.job_id,
                execution_status="RESEARCHING",
                protocol_status="RUNNING",
                current_stage="researching",
            )
            self.store.append_event(
                job.job_id,
                "AGENT_STARTED" if not resume else "AGENT_RESUMED",
                "隔离研究代理已启动" if not resume else "研究代理已从现有证据继续",
                {},
            )
            current_job = self.store.get_job(job.job_id) or job
            if council_ingress_tasks:
                run_council_ingress = getattr(
                    self.agent_adapter,
                    "run_council_ingress",
                    None,
                )
                if not callable(run_council_ingress):
                    raise RuntimeError(
                        "BLOCK_FACTORFORGE_CONSOLE_COUNCIL_INGRESS_UNAVAILABLE: "
                        "isolated Council ingress adapter is missing"
                    )
                agent_result = run_council_ingress(
                    current_job,
                    worktree=worktree,
                    workspace=workspace,
                    tasks=council_ingress_tasks,
                )
            else:
                agent_result = self.agent_adapter.run(
                    current_job,
                    worktree=worktree,
                    workspace=workspace,
                    resume=resume,
                )
            denied_values = _adapter_denied_values(self.agent_adapter, job.job_id)
            self.store.update_job(
                job.job_id,
                agent_id=agent_result.agent_id,
                agent_session_key=agent_result.session_key,
                execution_status="VERIFYING",
                current_stage="verifying",
            )
            self.store.append_event(
                job.job_id,
                "AGENT_FINISHED",
                "研究代理已返回，开始核验正式证据",
                {"returncode": agent_result.returncode},
            )

            _validate_agent_write_boundary(
                workspace,
                before=agent_write_snapshot,
                allowed=allowed_agent_writes,
                required=required_agent_outputs,
            )
            if agent_result.returncode != 0:
                raise RuntimeError(
                    f"BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: returncode={agent_result.returncode}"
                )

            isolation_failures = audit_factor_worktree(worktree, workspace)
            if isolation_failures:
                raise RuntimeError(f"{BLOCK_ISOLATION_AUDIT_FAILED}: {'; '.join(isolation_failures)}")
            host_data_env: dict[str, str] = {}
            prepare_host_data = getattr(
                self.agent_adapter,
                "prepare_host_data_environment",
                None,
            )
            if callable(prepare_host_data):
                host_data_env, host_denied_values = prepare_host_data(job.job_id)
                denied_values = tuple(
                    dict.fromkeys((*denied_values, *host_denied_values))
                )
            elif self.config.execution_mode == "container" and not self.config.auth_disabled:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease provider is missing"
                )
            formal_execution = self._execute_host_formal_pipeline(
                current_job,
                worktree=worktree,
                workspace=workspace,
                resume=resume,
                denied_values=denied_values,
                host_data_env=host_data_env,
                resume_trust=resume_trust,
            )
            isolation_failures = audit_factor_worktree(worktree, workspace)
            if isolation_failures:
                raise RuntimeError(f"{BLOCK_ISOLATION_AUDIT_FAILED}: {'; '.join(isolation_failures)}")
            web_materialization = validate_materialized_web_research(workspace)
            summary = read_ultimate_workspace(workspace, report_id=job.report_id)
            self._validate_summary_identity(current_job, summary)
            host_attestation_id = self._write_host_attestation(
                job=current_job,
                workspace=workspace,
                summary=summary,
                agent_result=agent_result,
                web_materialization=web_materialization,
                formal_execution=formal_execution,
            )
            publication_id, public_artifacts = publish_official_artifacts(
                workspace,
                self.config.state_root / "public" / job.job_id,
                role_artifact_ids=summary.artifact_ids,
                identity={
                    "job_id": job.job_id,
                    "report_id": job.report_id,
                    "factor_id": job.factor_id,
                    "research_id": job.research_id,
                },
                denied_values=denied_values,
            )
            result = _redact_public_payload(
                build_web_result(
                    summary,
                    publication_id=publication_id,
                    public_artifacts=public_artifacts,
                ),
                denied_values,
            )
            result["host_attestation_id"] = host_attestation_id
            execution_status = _web_execution_status(summary, agent_result.returncode)
            finished = utc_now() if execution_status in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"} else ""
            error_code = ""
            error_message = ""
            if execution_status == "FAILED":
                error_code = BLOCK_FORMAL_EVIDENCE_MISSING
                error_message = "研究代理返回后未形成可核验的正式终态或暂停态。"
            updated = self.store.update_job(
                job.job_id,
                execution_status=execution_status,
                protocol_status=_normalize_protocol(summary.protocol_status),
                factor_verdict=summary.factor_verdict,
                council_status=_normalize_council(summary.council_status),
                formal_proof_eligible=summary.formal_proof_eligible,
                current_stage=_web_stage(summary),
                result=result,
                error_code=error_code,
                error_message=error_message,
                finished_at_utc=finished,
            )
            self.store.append_event(
                job.job_id,
                "EVIDENCE_VERIFIED",
                f"证据核验完成：{updated.execution_status} / {updated.factor_verdict}",
                {
                    "protocol_status": updated.protocol_status,
                    "council_status": updated.council_status,
                    "formal_proof_eligible": updated.formal_proof_eligible,
                },
            )
            private_completion_status = (
                PRIVATE_LIFECYCLE_RESUMABLE
                if execution_status in {"REVIEW_REQUIRED", "BLOCKED", "FAILED"}
                else PRIVATE_LIFECYCLE_TERMINAL
            )
            private_attestation_id = host_attestation_id
        except (WorktreeAllocationError, FileNotFoundError, ValueError, RuntimeError) as exc:
            message = str(exc)
            registry_read_failed = False
            if not denied_values:
                try:
                    denied_values = _adapter_denied_values(self.agent_adapter, job.job_id)
                except (OSError, RuntimeError, ValueError):
                    registry_read_failed = True
            credential_state = "not_issued"
            if registry_read_failed:
                try:
                    credential_state = _adapter_credential_material_state(
                        self.agent_adapter,
                        job.job_id,
                    )
                except (OSError, RuntimeError, ValueError):
                    credential_state = "unknown"
            if registry_read_failed and credential_state != "not_issued":
                token = BLOCK_CREDENTIAL_REGISTRY_INVALID
                public_message = (
                    "临时凭证脱敏状态无法验证；任务已安全阻断，未公开原始异常详情。"
                )
            else:
                token = message.split(":", 1)[0] if message.startswith("BLOCK_") else "BLOCK_FACTORFORGE_CONSOLE_RUN_FAILED"
                public_message = _public_error_message(message, denied_values=denied_values)
            if token in NON_RESUMABLE_SECURITY_BLOCKERS:
                try:
                    self._mark_job_non_resumable(job, token=token)
                except (OSError, RuntimeError, ValueError):
                    token = BLOCK_RESUME_TRUST_INVALID
                    public_message = (
                        "任务触发安全阻断，且主机私有不可续跑标记未能可靠落盘；"
                        "当前任务已禁止续跑，请新建隔离任务。"
                    )
            self.store.update_job(
                job.job_id,
                execution_status="BLOCKED" if token.startswith("BLOCK_") else "FAILED",
                protocol_status="BLOCK" if token.startswith("BLOCK_") else "FAIL",
                factor_verdict="BLOCK" if token.startswith("BLOCK_") else "UNKNOWN",
                current_stage="blocked" if token.startswith("BLOCK_") else "failed",
                error_code=token,
                error_message=public_message,
                result=_result_without_resume_attestation(
                    self.store.get_job(job.job_id) or job
                ),
                finished_at_utc=utc_now(),
            )
            self.store.append_event(
                job.job_id,
                "RUN_BLOCKED",
                public_message,
                {"code": token},
            )
        except Exception as exc:
            token = "BLOCK_FACTORFORGE_CONSOLE_INTERNAL_ERROR"
            self.store.update_job(
                job.job_id,
                execution_status="BLOCKED",
                protocol_status="BLOCK",
                factor_verdict="BLOCK",
                current_stage="blocked",
                error_code=token,
                error_message="研究服务发生未预期错误；任务证据已保留，未自动重试。",
                result=_result_without_resume_attestation(
                    self.store.get_job(job.job_id) or job
                ),
                finished_at_utc=utc_now(),
            )
            self.store.append_event(
                job.job_id,
                "RUN_BLOCKED",
                "研究服务发生未预期错误；任务证据已保留，未自动重试。",
                {"code": token, "exception_type": type(exc).__name__},
            )
        finally:
            cleanup_succeeded = True
            release = getattr(self.agent_adapter, "deactivate_denied_secrets", None)
            if not callable(release):
                release = getattr(self.agent_adapter, "clear_denied_secrets", None)
            if callable(release):
                try:
                    release(job.job_id)
                except (OSError, RuntimeError, ValueError):
                    cleanup_succeeded = False
                    try:
                        self._mark_job_non_resumable(
                            job,
                            token="BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
                        )
                    except (OSError, RuntimeError, ValueError):
                        pass
                    self.store.update_job(
                        job.job_id,
                        execution_status="BLOCKED",
                        protocol_status="BLOCK",
                        factor_verdict="BLOCK",
                        formal_proof_eligible=False,
                        current_stage="blocked",
                        error_code="BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
                        error_message="临时凭证脱敏 registry 未能安全停用，任务已阻断。",
                        result=_result_without_resume_attestation(
                            self.store.get_job(job.job_id) or job
                        ),
                        finished_at_utc=utc_now(),
                    )
            if cleanup_succeeded and private_completion_status is not None:
                try:
                    self._finish_private_execution(
                        job,
                        status=private_completion_status,
                        attestation_id=private_attestation_id,
                    )
                except (OSError, RuntimeError, ValueError):
                    try:
                        self._mark_job_non_resumable(
                            job,
                            token=BLOCK_RESUME_TRUST_INVALID,
                        )
                    except (OSError, RuntimeError, ValueError):
                        pass
                    self.store.update_job(
                        job.job_id,
                        execution_status="BLOCKED",
                        protocol_status="BLOCK",
                        factor_verdict="BLOCK",
                        formal_proof_eligible=False,
                        current_stage="blocked",
                        error_code=BLOCK_RESUME_TRUST_INVALID,
                        error_message=(
                            "主机私有研究生命周期未能可靠完成；当前任务已禁止续跑，"
                            "请新建隔离任务。"
                        ),
                        result=_result_without_resume_attestation(
                            self.store.get_job(job.job_id) or job
                        ),
                        finished_at_utc=utc_now(),
                    )

    def _non_resumable_marker_path(self, job_id: str) -> Path:
        return (
            self.config.state_root
            / "jobs"
            / job_id
            / "security"
            / "non_resumable.json"
        )

    def _private_lifecycle_path(self, job_id: str) -> Path:
        return self.config.state_root / "jobs" / job_id / "security" / "lifecycle.json"

    @staticmethod
    def _private_lifecycle_identity(job: ResearchJob) -> dict[str, str]:
        return {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
        }

    def _read_private_lifecycle(self, job: ResearchJob) -> dict[str, Any] | None:
        path = self._private_lifecycle_path(job.job_id)
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle uses a symlink"
            )
        if not path.exists():
            return None
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.config.state_root.resolve(strict=True))
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is unreadable"
            ) from exc
        expected = self._private_lifecycle_identity(job)
        if (
            not isinstance(payload, dict)
            or payload.get("version") != PRIVATE_LIFECYCLE_VERSION
            or any(payload.get(key) != value for key, value in expected.items())
            or payload.get("status")
            not in {
                PRIVATE_LIFECYCLE_RUNNING,
                PRIVATE_LIFECYCLE_RESUMABLE,
                PRIVATE_LIFECYCLE_TERMINAL,
                PRIVATE_LIFECYCLE_NON_RESUMABLE,
            }
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle identity is invalid"
            )
        return payload

    def _write_private_lifecycle(
        self,
        job: ResearchJob,
        *,
        status: str,
        prior_status: str | None,
        attestation_id: str = "",
        blocker: str = "",
    ) -> None:
        path = self._private_lifecycle_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        _write_json_atomic(
            path,
            {
                "version": PRIVATE_LIFECYCLE_VERSION,
                **self._private_lifecycle_identity(job),
                "status": status,
                "prior_status": prior_status,
                "attestation_id": attestation_id,
                "blocker": blocker,
                "updated_at_utc": utc_now(),
            },
            root=self.config.state_root,
        )

    def _begin_private_execution(self, job: ResearchJob, *, resume: bool) -> None:
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        lifecycle = self._read_private_lifecycle(job)
        if (
            isinstance(lifecycle, dict)
            and lifecycle.get("status") == PRIVATE_LIFECYCLE_RESUMABLE
        ):
            self._write_private_lifecycle(
                job,
                status=PRIVATE_LIFECYCLE_RUNNING,
                prior_status=PRIVATE_LIFECYCLE_RESUMABLE,
            )
            if not resume:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: resumable private lifecycle cannot be reclassified as fresh"
                )
            return
        if resume:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not resumable"
            )
        if lifecycle is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: existing private lifecycle cannot be reclassified as fresh"
            )
        self._write_private_lifecycle(
            job,
            status=PRIVATE_LIFECYCLE_RUNNING,
            prior_status=None,
        )

    def _finish_private_execution(
        self,
        job: ResearchJob,
        *,
        status: str,
        attestation_id: str,
    ) -> None:
        if status not in {PRIVATE_LIFECYCLE_RESUMABLE, PRIVATE_LIFECYCLE_TERMINAL}:
            raise ValueError("private lifecycle completion status is invalid")
        lifecycle = self._read_private_lifecycle(job)
        if not isinstance(lifecycle, dict) or lifecycle.get("status") != PRIVATE_LIFECYCLE_RUNNING:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not running"
            )
        if not attestation_id:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle lacks host attestation"
            )
        self._write_private_lifecycle(
            job,
            status=status,
            prior_status=PRIVATE_LIFECYCLE_RUNNING,
            attestation_id=attestation_id,
        )

    def _mark_job_non_resumable(self, job: ResearchJob, *, token: str) -> None:
        failures: list[Exception] = []
        try:
            lifecycle = self._read_private_lifecycle(job)
            prior_status = (
                str(lifecycle.get("status")) if isinstance(lifecycle, dict) else None
            )
            self._write_private_lifecycle(
                job,
                status=PRIVATE_LIFECYCLE_NON_RESUMABLE,
                prior_status=prior_status,
                blocker=token,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(exc)
        marker_path = self._non_resumable_marker_path(job.job_id)
        try:
            if marker_path.is_symlink():
                raise RuntimeError("private non-resumable marker uses a symlink")
            if not marker_path.exists():
                marker_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                marker_path.parent.chmod(0o700)
                payload = {
                    "version": "factorforge_console_non_resumable_marker_v1",
                    "job_id": job.job_id,
                    "factor_id": job.factor_id,
                    "research_id": job.research_id,
                    "report_id": job.report_id,
                    "base_commit": job.base_commit,
                    "security_blocker": token,
                    "marked_at_utc": utc_now(),
                }
                _write_json_atomic(marker_path, payload, root=self.config.state_root)
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(exc)
        if len(failures) == 2:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private non-resumable state could not be persisted"
            ) from failures[0]

    def _require_private_resume_allowed(self, job: ResearchJob) -> None:
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        lifecycle = self._read_private_lifecycle(job)
        if not isinstance(lifecycle, dict) or lifecycle.get("status") != PRIVATE_LIFECYCLE_RESUMABLE:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not resumable"
            )

    def _validate_trusted_resume_context(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        private_execution_started: bool = False,
    ) -> dict[str, Any]:
        lifecycle = self._read_private_lifecycle(job)
        expected_private_status = (
            PRIVATE_LIFECYCLE_RUNNING
            if private_execution_started
            else PRIVATE_LIFECYCLE_RESUMABLE
        )
        if (
            not isinstance(lifecycle, dict)
            or lifecycle.get("status") != expected_private_status
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle state is invalid for resume validation"
            )
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        state_root = self.config.state_root.resolve(strict=True)
        worktree_root = worktree.resolve(strict=True)
        workspace_root = workspace.resolve(strict=True)

        def invalid(detail: str) -> RuntimeError:
            return RuntimeError(f"{BLOCK_RESUME_TRUST_INVALID}: {detail}")

        def read_host_json(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
            try:
                relative = path.relative_to(state_root)
            except ValueError as exc:
                raise invalid(f"{label} escapes host state") from exc
            current = state_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise invalid(f"{label} uses a symlink")
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(state_root)
            except (FileNotFoundError, ValueError) as exc:
                raise invalid(f"{label} is missing or outside host state") from exc
            if not resolved.is_file() or resolved.is_symlink():
                raise invalid(f"{label} is not a regular host-state file")
            try:
                payload = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise invalid(f"{label} is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise invalid(f"{label} must be a JSON object")
            return payload, _sha256(resolved)

        expected_identity = {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
        }
        if (
            Path(job.worktree_path).expanduser().resolve(strict=True) != worktree_root
            or Path(job.workspace_path).expanduser().resolve(strict=True) != workspace_root
        ):
            raise invalid("persisted allocation does not match the active workspace")

        pointer_path = state_root / "attestations" / f"{job.job_id}.current.json"
        pointer, _pointer_sha256 = read_host_json(
            pointer_path,
            label="host attestation pointer",
        )
        if (
            pointer.get("version") != "factorforge_console_host_attestation_pointer_v1"
            or pointer.get("job_id") != job.job_id
        ):
            raise invalid("host attestation pointer identity is invalid")
        attestation_id = str(pointer.get("attestation_id") or "")
        attestation_relative = Path(attestation_id)
        if (
            not attestation_id
            or attestation_relative.is_absolute()
            or ".." in attestation_relative.parts
        ):
            raise invalid("host attestation identity is unsafe")
        attestation_path = state_root / attestation_relative
        attestation, attestation_sha256 = read_host_json(
            attestation_path,
            label="host attestation",
        )
        if attestation_sha256 != str(pointer.get("attestation_sha256") or ""):
            raise invalid("host attestation hash does not match current pointer")
        if (
            attestation.get("version")
            != "factorforge_console_host_execution_attestation_v2"
            or any(attestation.get(key) != value for key, value in expected_identity.items())
            or attestation.get("host_observed_ultimate_process") is not True
            or attestation.get("host_evidence_reader_invoked") is not True
        ):
            raise invalid("host attestation identity or provenance is invalid")

        manifest_path = workspace_root / "manifest.json"
        if (
            not manifest_path.is_file()
            or manifest_path.is_symlink()
            or attestation.get("workspace_manifest_sha256") != _sha256(manifest_path)
        ):
            raise invalid("workspace manifest is not bound to the host attestation")

        materialization = attestation.get("web_materialization")
        if not isinstance(materialization, dict):
            raise invalid("web materialization provenance is missing")
        expected_plan_hash = str(materialization.get("plan_sha256") or "")
        plan_path = workspace_root / "identity" / "web_research_plan.json"
        if expected_plan_hash and (
            not plan_path.is_file()
            or plan_path.is_symlink()
            or _sha256(plan_path) != expected_plan_hash
        ):
            raise invalid("research plan no longer matches the host attestation")

        evidence_tree_id = str(attestation.get("workspace_evidence_tree_id") or "")
        evidence_tree_relative = Path(evidence_tree_id)
        if (
            not evidence_tree_id
            or evidence_tree_relative.is_absolute()
            or ".." in evidence_tree_relative.parts
        ):
            raise invalid("workspace evidence tree identity is unsafe")
        evidence_tree_path = state_root / evidence_tree_relative
        evidence_tree, evidence_tree_sha256 = read_host_json(
            evidence_tree_path,
            label="workspace evidence tree",
        )
        entries = evidence_tree.get("entries")
        if (
            evidence_tree.get("version")
            != "factorforge_console_workspace_evidence_tree_v1"
            or any(evidence_tree.get(key) != value for key, value in expected_identity.items())
            or not isinstance(entries, dict)
            or not all(
                isinstance(path, str) and isinstance(digest, str)
                for path, digest in entries.items()
            )
            or evidence_tree_sha256
            != str(attestation.get("workspace_evidence_tree_sha256") or "")
            or stable_json_hash(entries)
            != str(attestation.get("workspace_evidence_tree_root_sha256") or "")
            or evidence_tree.get("tree_sha256") != stable_json_hash(entries)
        ):
            raise invalid("workspace evidence tree provenance is invalid")
        try:
            current_entries = _workspace_evidence_tree(workspace_root)
        except RuntimeError as exc:
            raise invalid("current workspace evidence tree is unsafe") from exc
        if current_entries != entries:
            raise invalid("workspace formal evidence tree changed after host attestation")

        receipt_id = str(attestation.get("formal_execution_receipt_id") or "")
        receipt_relative = Path(receipt_id)
        if (
            not receipt_id
            or receipt_relative.is_absolute()
            or ".." in receipt_relative.parts
        ):
            raise invalid("formal execution receipt identity is unsafe")
        receipt_path = state_root / receipt_relative
        receipt, receipt_sha256 = read_host_json(
            receipt_path,
            label="formal execution receipt",
        )
        if receipt_sha256 != str(
            attestation.get("formal_execution_receipt_sha256") or ""
        ):
            raise invalid("formal execution receipt hash does not match attestation")
        if (
            receipt.get("version") != "factorforge_console_host_formal_execution_v2"
            or any(receipt.get(key) != value for key, value in expected_identity.items())
        ):
            raise invalid("formal execution receipt identity is invalid")

        commands = receipt.get("commands")
        if not isinstance(commands, list) or len(commands) != 2:
            raise invalid("formal execution receipt command chain is incomplete")
        materialize, ultimate = commands
        if not isinstance(materialize, dict) or not isinstance(ultimate, dict):
            raise invalid("formal execution receipt commands are invalid")
        materialize_argv = materialize.get("argv")
        ultimate_argv = ultimate.get("argv")
        if not isinstance(materialize_argv, list) or not isinstance(ultimate_argv, list):
            raise invalid("formal execution receipt argv is invalid")
        if (
            materialize.get("name") != "materialize_web_research"
            or materialize.get("returncode") != 0
            or materialize.get("host_observed_process") is not True
            or materialize.get("cwd") != str(worktree_root)
            or len(materialize_argv) < 2
            or str(materialize_argv[1])
            != "scripts/materialize_factorforge_web_research.py"
            or _argv_value(materialize_argv, "--workspace-root") != str(workspace_root)
            or _argv_value(materialize_argv, "--plan") != str(plan_path)
            or stable_json_hash(materialize_argv)
            != str(materialize.get("argv_sha256") or "")
        ):
            raise invalid("host materializer receipt is invalid")
        if (
            ultimate.get("name") != "run_factorforge_ultimate"
            or ultimate.get("host_observed_process") is not True
            or ultimate.get("cwd") != str(worktree_root)
            or len(ultimate_argv) < 2
            or str(ultimate_argv[1]) != "scripts/run_factorforge_ultimate.py"
            or _argv_value(ultimate_argv, "--report-id") != job.report_id
            or _argv_value(ultimate_argv, "--factor-id") != job.factor_id
            or _argv_value(ultimate_argv, "--research-id") != job.research_id
            or _argv_value(ultimate_argv, "--factorforge-root") != str(worktree_root)
            or _argv_value(ultimate_argv, "--factor-workspace") != str(workspace_root)
            or _argv_value(ultimate_argv, "--start-step") not in {"3", "4", "5", "6"}
            or _argv_value(ultimate_argv, "--end-step") != "all"
            or stable_json_hash(ultimate_argv) != str(ultimate.get("argv_sha256") or "")
            or stable_json_hash(ultimate_argv)
            != str(attestation.get("ultimate_argv_sha256") or "")
            or ultimate.get("returncode") != attestation.get("ultimate_returncode")
        ):
            raise invalid("host Ultimate receipt is invalid")
        receipt_resume = receipt.get("resume")
        receipt_start_step = _argv_value(ultimate_argv, "--start-step")
        receipt_parent = receipt.get("resume_parent")
        if receipt_resume is False:
            if receipt_start_step != "3" or receipt_parent is not None:
                raise invalid("fresh formal receipt has invalid start step or parent")
        elif receipt_resume is True:
            if not isinstance(receipt_parent, dict):
                raise invalid("resumed formal receipt is missing its trusted parent")
            required_parent_fields = {
                "start_step",
                "ultimate_proof_sha256",
                "attestation_id",
                "attestation_sha256",
                "receipt_id",
                "receipt_sha256",
            }
            if (
                set(receipt_parent) != required_parent_fields
                or receipt_parent.get("start_step") != receipt_start_step
            ):
                raise invalid("resumed formal receipt parent contract is invalid")
            parent_attestation_id = str(receipt_parent.get("attestation_id") or "")
            parent_receipt_id = str(receipt_parent.get("receipt_id") or "")
            parent_attestation_relative = Path(parent_attestation_id)
            parent_receipt_relative = Path(parent_receipt_id)
            if (
                not parent_attestation_id
                or parent_attestation_relative.is_absolute()
                or ".." in parent_attestation_relative.parts
                or not parent_receipt_id
                or parent_receipt_relative.is_absolute()
                or ".." in parent_receipt_relative.parts
            ):
                raise invalid("resumed formal receipt parent identity is unsafe")
            parent_attestation, parent_attestation_sha256 = read_host_json(
                state_root / parent_attestation_relative,
                label="parent host attestation",
            )
            parent_receipt, parent_receipt_sha256 = read_host_json(
                state_root / parent_receipt_relative,
                label="parent formal execution receipt",
            )
            parent_wrapper = (
                parent_attestation.get("evidence_hashes", {}).get("wrapper_report", {})
                if isinstance(parent_attestation.get("evidence_hashes"), dict)
                else {}
            )
            if (
                parent_attestation_sha256
                != str(receipt_parent.get("attestation_sha256") or "")
                or parent_receipt_sha256
                != str(receipt_parent.get("receipt_sha256") or "")
                or parent_attestation.get("version")
                != "factorforge_console_host_execution_attestation_v2"
                or parent_receipt.get("version")
                != "factorforge_console_host_formal_execution_v2"
                or any(
                    parent_attestation.get(key) != value
                    or parent_receipt.get(key) != value
                    for key, value in expected_identity.items()
                )
                or parent_attestation.get("formal_execution_receipt_id")
                != parent_receipt_id
                or parent_attestation.get("formal_execution_receipt_sha256")
                != parent_receipt_sha256
                or parent_receipt.get("ultimate_proof_sha256")
                != str(receipt_parent.get("ultimate_proof_sha256") or "")
                or not isinstance(parent_wrapper, dict)
                or parent_wrapper.get("sha256")
                != str(receipt_parent.get("ultimate_proof_sha256") or "")
            ):
                raise invalid("resumed formal receipt parent trust is invalid")
        else:
            raise invalid("formal receipt resume flag is invalid")

        proof_path = (
            workspace_root
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        if not proof_path.is_file() or proof_path.is_symlink():
            raise invalid("current Ultimate proof is missing or unsafe")
        proof_sha256 = _sha256(proof_path)
        wrapper_evidence = (
            attestation.get("evidence_hashes", {}).get("wrapper_report", {})
            if isinstance(attestation.get("evidence_hashes"), dict)
            else {}
        )
        if (
            receipt.get("ultimate_proof_sha256") != proof_sha256
            or not isinstance(wrapper_evidence, dict)
            or wrapper_evidence.get("artifact_id")
            != (
                "objects/runtime_context/"
                f"ultimate_run_report__{job.report_id}.json"
            )
            or wrapper_evidence.get("sha256") != proof_sha256
        ):
            raise invalid("current Ultimate proof is not bound to trusted host evidence")
        try:
            start_step = required_web_resume_start_step(workspace_root, job.report_id)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise invalid("trusted Ultimate proof is not safely resumable") from exc
        if start_step not in {"3", "4", "5", "6"}:
            raise invalid("trusted Ultimate proof has no legal resume point")
        return {
            "start_step": start_step,
            "ultimate_proof_sha256": proof_sha256,
            "attestation_id": attestation_id,
            "attestation_sha256": attestation_sha256,
            "receipt_id": receipt_id,
            "receipt_sha256": receipt_sha256,
        }

    def _execute_host_formal_pipeline(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        denied_values: tuple[str, ...],
        host_data_env: dict[str, str] | None = None,
        resume_trust: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.config.data_catalogs:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: approved data catalog is missing"
            )
        catalog = self.config.data_catalogs[0].expanduser().resolve(strict=True)
        env = os.environ.copy()
        for key in list(env):
            upper = key.upper()
            if any(
                token in upper
                for token in ("API_KEY", "PASSWORD", "SECRET", "TOKEN", "COOKIE")
            ):
                env.pop(key, None)
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_CREDENTIAL_EXPIRATION",
        ):
            env.pop(key, None)
        allowed_lease_keys = {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_CREDENTIAL_EXPIRATION",
        }
        lease_env = dict(host_data_env or {})
        if set(lease_env) - allowed_lease_keys or any(
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or "\n" in value
            or "\r" in value
            for value in lease_env.values()
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease environment is invalid"
            )
        if self.config.execution_mode == "container" and not self.config.auth_disabled:
            if set(lease_env) != allowed_lease_keys:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease environment is incomplete"
                )
        env.update(lease_env)
        env["AWS_EC2_METADATA_DISABLED"] = "true"
        env["FACTORFORGE_STATE_CATALOG"] = str(catalog)
        env["FACTORFORGE_DATA_CATALOG"] = str(catalog)
        _configure_host_formal_python_environment(
            env,
            worktree=worktree,
            data_api_pythonpath=self.config.data_api_pythonpath,
        )
        plan_path = workspace / "identity" / "web_research_plan.json"
        commands: list[dict[str, Any]] = []
        if resume:
            if not isinstance(resume_trust, dict) or resume_trust.get("start_step") not in {
                "3",
                "4",
                "5",
                "6",
            }:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: host-verified resume context is required"
                )
        elif resume_trust is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh execution cannot carry resume trust"
            )

        def run_host_command(
            name: str,
            argv: list[str],
            *,
            timeout: int,
        ) -> dict[str, Any]:
            started = utc_now()
            timed_out = False
            try:
                proc = subprocess.run(
                    argv,
                    cwd=worktree,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                )
                returncode = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                returncode = 124
                stdout = _subprocess_text(exc.stdout)
                stderr = _subprocess_text(exc.stderr)
            return {
                "name": name,
                "argv": argv,
                "argv_sha256": stable_json_hash(argv),
                "cwd": str(worktree),
                "host_observed_process": True,
                "readonly_data_lease_injected": bool(lease_env),
                "started_at_utc": started,
                "finished_at_utc": utc_now(),
                "returncode": returncode,
                "timed_out": timed_out,
                "stdout_tail": redact_secret_values(
                    stdout[-16_000:],
                    denied_values,
                    replacement="[redacted]",
                ),
                "stderr_tail": redact_secret_values(
                    stderr[-16_000:],
                    denied_values,
                    replacement="[redacted]",
                ),
            }

        materialize_argv = [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(plan_path),
        ]
        materialize = run_host_command(
            "materialize_web_research",
            materialize_argv,
            timeout=180,
        )
        commands.append(materialize)
        if materialize["returncode"] != 0:
            receipt = self._write_formal_execution_receipt(
                job,
                workspace=workspace,
                commands=commands,
                resume=resume,
                resume_trust=resume_trust,
            )
            detail = materialize["stderr_tail"] or materialize["stdout_tail"]
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: materializer returncode="
                f"{materialize['returncode']} receipt={receipt['receipt_id']} detail={detail[-1200:]}"
            )

        start_step = str(resume_trust["start_step"]) if resume_trust is not None else "3"
        ultimate_argv = [
            sys.executable,
            "scripts/run_factorforge_ultimate.py",
            "--report-id",
            job.report_id,
            "--start-step",
            start_step,
            "--end-step",
            "all",
            "--factorforge-root",
            str(worktree),
            "--factor-id",
            job.factor_id,
            "--research-id",
            job.research_id,
            "--factor-workspace",
            str(workspace),
        ]
        ultimate = run_host_command(
            "run_factorforge_ultimate",
            ultimate_argv,
            timeout=max(60, min(3000, self.config.agent_timeout_seconds)),
        )
        commands.append(ultimate)
        receipt = self._write_formal_execution_receipt(
            job,
            workspace=workspace,
            commands=commands,
            resume=resume,
            resume_trust=resume_trust,
        )
        if ultimate["timed_out"]:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Ultimate timed out; "
                f"receipt={receipt['receipt_id']}"
            )
        return receipt

    def _write_formal_execution_receipt(
        self,
        job: ResearchJob,
        *,
        workspace: Path,
        commands: list[dict[str, Any]],
        resume: bool,
        resume_trust: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if resume and not isinstance(resume_trust, dict):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resumed receipt requires a trusted parent"
            )
        if not resume and resume_trust is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh receipt cannot carry a trusted parent"
            )
        proof_path = (
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        payload = {
            "version": "factorforge_console_host_formal_execution_v2",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
            "resume": resume,
            "resume_parent": (
                {
                    "start_step": str(resume_trust["start_step"]),
                    "ultimate_proof_sha256": str(
                        resume_trust["ultimate_proof_sha256"]
                    ),
                    "attestation_id": str(resume_trust["attestation_id"]),
                    "attestation_sha256": str(resume_trust["attestation_sha256"]),
                    "receipt_id": str(resume_trust["receipt_id"]),
                    "receipt_sha256": str(resume_trust["receipt_sha256"]),
                }
                if resume_trust is not None
                else None
            ),
            "readonly_data_lease_injected": bool(
                commands
                and all(
                    command.get("readonly_data_lease_injected") is True
                    for command in commands
                )
            ),
            "commands": commands,
            "ultimate_proof_sha256": (
                _sha256(proof_path)
                if proof_path.is_file() and not proof_path.is_symlink()
                else None
            ),
            "recorded_at_utc": utc_now(),
        }
        receipt_root = self.config.state_root / "jobs" / job.job_id / "formal-execution"
        receipt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt_root.chmod(0o700)
        receipt_path = receipt_root / (
            f"receipt_{_stamp(utc_now())}_{uuid.uuid4().hex[:12]}.json"
        )
        _write_json_atomic(receipt_path, payload, root=self.config.state_root)
        return {
            "receipt_id": receipt_path.relative_to(self.config.state_root).as_posix(),
            "receipt_sha256": _sha256(receipt_path),
            "ultimate_argv_sha256": next(
                (
                    str(item.get("argv_sha256") or "")
                    for item in commands
                    if item.get("name") == "run_factorforge_ultimate"
                ),
                "",
            ),
            "ultimate_returncode": next(
                (
                    int(item.get("returncode"))
                    for item in commands
                    if item.get("name") == "run_factorforge_ultimate"
                ),
                None,
            ),
        }

    @staticmethod
    def _validate_summary_identity(job: ResearchJob, summary: UltimateRunSummary) -> None:
        expected = {
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
        }
        for key, value in expected.items():
            actual = str(getattr(summary, key) or "")
            if actual != value:
                raise RuntimeError(
                    f"{BLOCK_EVIDENCE_IDENTITY_MISMATCH}: {key} expected={value!r} actual={actual!r}"
                )

    def _write_host_attestation(
        self,
        *,
        job: ResearchJob,
        workspace: Path,
        summary: UltimateRunSummary,
        agent_result: AgentRunResult,
        web_materialization: dict[str, str],
        formal_execution: dict[str, Any],
    ) -> str:
        evidence_hashes: dict[str, dict[str, str]] = {}
        workspace_root = workspace.resolve(strict=True)
        for role, artifact_id in sorted(summary.artifact_ids.items()):
            relative_input = Path(artifact_id)
            if relative_input.is_absolute() or ".." in relative_input.parts:
                raise RuntimeError(
                    f"{BLOCK_ISOLATION_AUDIT_FAILED}: attested evidence identity is unsafe"
                )
            lexical = workspace_root / relative_input
            current = workspace_root
            for part in relative_input.parts:
                current = current / part
                if current.is_symlink():
                    raise RuntimeError(
                        f"{BLOCK_FORMAL_EVIDENCE_MISSING}: attested evidence uses a symlink"
                    )
            candidate = lexical.resolve(strict=True)
            try:
                relative = candidate.relative_to(workspace_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"{BLOCK_ISOLATION_AUDIT_FAILED}: attested evidence escapes workspace"
                ) from exc
            if not candidate.is_file() or candidate.is_symlink():
                raise RuntimeError(
                    f"{BLOCK_FORMAL_EVIDENCE_MISSING}: attested evidence is unsafe"
                )
            evidence_hashes[role] = {
                "artifact_id": relative.as_posix(),
                "sha256": _sha256(candidate),
            }

        state_root = self.config.state_root.resolve(strict=True)
        agent_result_raw = Path(agent_result.result_path).expanduser()
        if agent_result_raw.is_symlink():
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: agent result record is unsafe"
            )
        agent_result_path = agent_result_raw.resolve(strict=True)
        try:
            agent_result_relative = agent_result_path.relative_to(state_root)
        except ValueError as exc:
            raise RuntimeError(
                f"BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: agent result path is outside host state"
            ) from exc
        if not agent_result_path.is_file() or agent_result_path.is_symlink():
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: agent result record is unsafe"
            )

        receipt_id = str(formal_execution.get("receipt_id") or "")
        receipt_relative = Path(receipt_id)
        if receipt_relative.is_absolute() or ".." in receipt_relative.parts:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt identity is unsafe"
            )
        receipt_path = (state_root / receipt_relative).resolve(strict=True)
        try:
            receipt_path.relative_to(state_root)
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt escapes host state"
            ) from exc
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt is unsafe"
            )
        if _sha256(receipt_path) != str(formal_execution.get("receipt_sha256") or ""):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt hash mismatch"
            )
        formal_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected_receipt_identity = {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
        }
        if (
            formal_receipt.get("version")
            != "factorforge_console_host_formal_execution_v2"
            or any(
                formal_receipt.get(key) != value
                for key, value in expected_receipt_identity.items()
            )
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt identity mismatch"
            )
        if (
            self.config.execution_mode == "container"
            and not self.config.auth_disabled
            and formal_receipt.get("readonly_data_lease_injected") is not True
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt lacks read-only data lease"
            )
        commands = formal_receipt.get("commands")
        if not isinstance(commands, list) or len(commands) != 2:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt command count invalid"
            )
        materialize_receipt, ultimate_receipt = commands
        materialize_argv = (
            materialize_receipt.get("argv")
            if isinstance(materialize_receipt, dict)
            and isinstance(materialize_receipt.get("argv"), list)
            else []
        )
        ultimate_argv = (
            ultimate_receipt.get("argv")
            if isinstance(ultimate_receipt, dict)
            and isinstance(ultimate_receipt.get("argv"), list)
            else []
        )
        if (
            not isinstance(materialize_receipt, dict)
            or materialize_receipt.get("name") != "materialize_web_research"
            or materialize_receipt.get("returncode") != 0
            or materialize_receipt.get("host_observed_process") is not True
            or materialize_receipt.get("cwd") != str(job.worktree_path)
            or len(materialize_argv) < 2
            or materialize_argv[1]
            != "scripts/materialize_factorforge_web_research.py"
            or _argv_value(materialize_argv, "--workspace-root")
            != str(workspace_root)
            or _argv_value(materialize_argv, "--plan")
            != str(workspace_root / "identity" / "web_research_plan.json")
            or stable_json_hash(materialize_argv)
            != str(materialize_receipt.get("argv_sha256") or "")
            or not isinstance(ultimate_receipt, dict)
            or ultimate_receipt.get("name") != "run_factorforge_ultimate"
            or ultimate_receipt.get("host_observed_process") is not True
            or ultimate_receipt.get("cwd") != str(job.worktree_path)
            or len(ultimate_argv) < 2
            or ultimate_argv[1] != "scripts/run_factorforge_ultimate.py"
            or _argv_value(ultimate_argv, "--report-id") != job.report_id
            or _argv_value(ultimate_argv, "--factor-id") != job.factor_id
            or _argv_value(ultimate_argv, "--research-id") != job.research_id
            or _argv_value(ultimate_argv, "--factorforge-root")
            != str(job.worktree_path)
            or _argv_value(ultimate_argv, "--factor-workspace") != str(workspace_root)
            or _argv_value(ultimate_argv, "--end-step") != "all"
            or stable_json_hash(ultimate_argv)
            != str(ultimate_receipt.get("argv_sha256") or "")
            or stable_json_hash(ultimate_argv)
            != str(formal_execution.get("ultimate_argv_sha256") or "")
            or ultimate_receipt.get("returncode")
            != formal_execution.get("ultimate_returncode")
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal Ultimate receipt invalid"
            )
        receipt_start_step = _argv_value(ultimate_argv, "--start-step")
        receipt_parent = formal_receipt.get("resume_parent")
        if formal_receipt.get("resume") is False:
            receipt_trust_valid = receipt_start_step == "3" and receipt_parent is None
        elif formal_receipt.get("resume") is True:
            receipt_trust_valid = (
                isinstance(receipt_parent, dict)
                and receipt_parent.get("start_step") == receipt_start_step
                and set(receipt_parent)
                == {
                    "start_step",
                    "ultimate_proof_sha256",
                    "attestation_id",
                    "attestation_sha256",
                    "receipt_id",
                    "receipt_sha256",
                }
            )
        else:
            receipt_trust_valid = False
        if not receipt_trust_valid:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt resume trust invalid"
            )
        wrapper_path = (
            workspace_root
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        if (
            not wrapper_path.is_file()
            or wrapper_path.is_symlink()
            or formal_receipt.get("ultimate_proof_sha256") != _sha256(wrapper_path)
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal proof is not bound to receipt"
            )

        workspace_entries = _workspace_evidence_tree(workspace_root)
        attestation_root = state_root / "attestations"
        attestation_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        attestation_root.chmod(0o700)
        immutable_root = attestation_root / job.job_id
        immutable_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        immutable_root.chmod(0o700)
        immutable_suffix = f"{_stamp(utc_now())}_{uuid.uuid4().hex[:12]}"
        evidence_tree_path = immutable_root / f"evidence_tree_{immutable_suffix}.json"
        evidence_tree_payload = {
            "version": "factorforge_console_workspace_evidence_tree_v1",
            **expected_receipt_identity,
            "entries": workspace_entries,
            "tree_sha256": stable_json_hash(workspace_entries),
            "recorded_at_utc": utc_now(),
        }
        _write_json_atomic(
            evidence_tree_path,
            evidence_tree_payload,
            root=state_root,
        )
        evidence_tree_id = evidence_tree_path.relative_to(state_root).as_posix()
        payload = {
            "version": "factorforge_console_host_execution_attestation_v2",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
            "host_observed_agent_process": True,
            "host_observed_ultimate_process": True,
            "agent_returncode": agent_result.returncode,
            "agent_result_id": agent_result_relative.as_posix(),
            "agent_result_sha256": _sha256(agent_result_path),
            "host_evidence_reader_invoked": True,
            "host_terminal_formal_validation_status": (
                "PASS"
                if summary.formal_proof_eligible
                else "NOT_APPLICABLE"
                if summary.execution_status.upper() in {
                    "PAUSED",
                    "ITERATING",
                    "REVIEW_REQUIRED",
                    "RUNNING",
                }
                else "BLOCK"
            ),
            "summary_sha256": stable_json_hash(summary.to_dict()),
            "workspace_manifest_sha256": _sha256(workspace_root / "manifest.json"),
            "web_materialization": web_materialization,
            "formal_execution_receipt_id": receipt_id,
            "formal_execution_receipt_sha256": _sha256(receipt_path),
            "ultimate_argv_sha256": formal_execution["ultimate_argv_sha256"],
            "ultimate_returncode": formal_execution["ultimate_returncode"],
            "evidence_hashes": evidence_hashes,
            "workspace_evidence_tree_id": evidence_tree_id,
            "workspace_evidence_tree_sha256": _sha256(evidence_tree_path),
            "workspace_evidence_tree_root_sha256": stable_json_hash(workspace_entries),
            "attested_at_utc": utc_now(),
        }
        attestation_path = immutable_root / f"attestation_{immutable_suffix}.json"
        _write_json_atomic(
            attestation_path,
            payload,
            root=state_root,
        )
        attestation_id = attestation_path.relative_to(state_root).as_posix()
        pointer_path = attestation_root / f"{job.job_id}.current.json"
        _write_json_atomic(
            pointer_path,
            {
                "version": "factorforge_console_host_attestation_pointer_v1",
                "job_id": job.job_id,
                "attestation_id": attestation_id,
                "attestation_sha256": _sha256(attestation_path),
                "updated_at_utc": utc_now(),
            },
            root=state_root,
        )
        return attestation_id

    def _write_request_artifacts(
        self,
        job: ResearchJob,
        allocation: WorktreeAllocation,
        *,
        preserve_plan: bool = False,
        trusted_resume_start_step: str | None = None,
    ) -> None:
        workspace = allocation.workspace_path
        request_payload = {
            **job.request.to_dict(),
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": allocation.base_commit,
            "allocation_manifest_sha256": _sha256(allocation.manifest_path),
            "submitted_at_utc": job.created_at_utc,
            "source_type": "natural_language_hypothesis",
            "data_access": {
                "mode": "read_only",
                "catalog_count": len(self.config.data_catalogs),
            },
            "write_policy": {
                "factor_workspace_only": True,
                "repo_root_knowledge_write_allowed": False,
                "repo_root_data_write_allowed": False,
            },
        }
        _write_json_atomic(
            workspace / "identity" / "web_research_request.json",
            request_payload,
            root=workspace,
        )
        source_lines = [
            f"# {job.request.title}",
            "",
            "- Source type: natural language hypothesis",
            f"- Factor ID: {job.factor_id}",
            f"- Research ID: {job.research_id}",
            f"- Report ID: {job.report_id}",
            f"- Universe: {job.request.universe}",
            f"- Sample: {job.request.sample_start} to {job.request.sample_end}",
            f"- Forward horizon: {job.request.forward_horizon}",
            f"- Transaction cost: {job.request.transaction_cost_bps:g} bps",
            "",
            "## Hypothesis",
            "",
            job.request.hypothesis,
        ]
        if job.request.source_url:
            source_lines.extend(["", "## User Reference", "", job.request.source_url])
        source_path = workspace / "reports" / "user_hypothesis.md"
        write_text_atomic(
            source_path,
            "\n".join(source_lines) + "\n",
            root=workspace,
        )
        write_web_research_packet(
            workspace=workspace,
            worktree=allocation.worktree_path,
            request=request_payload,
            catalogs=self.config.data_catalogs,
            preserve_existing_plan=preserve_plan,
            trusted_resume_start_step=trusted_resume_start_step,
        )

    def _write_resume_authorization(self, job: ResearchJob, workspace: Path) -> None:
        payload = {
            "version": "factorforge_console_resume_authorization_v1",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "authorization_type": "web_user_resume",
            "human_approval_recorded": False,
            "automated_policy_approval": False,
            "authorized_at_utc": utc_now(),
            "scope": "resume existing workspace; do not infer promotion or revision approval",
        }
        _write_json_atomic(
            workspace / "identity" / "web_resume_authorization.json",
            payload,
            root=workspace,
        )


def _workspace_file_snapshot(workspace: Path) -> dict[str, str]:
    root = workspace.resolve(strict=True)
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = f"symlink:{os.readlink(path)}"
        elif path.is_file():
            snapshot[relative] = f"file:{_sha256(path)}"
    return snapshot


def _result_without_resume_attestation(job: ResearchJob) -> dict[str, Any]:
    result = dict(job.result) if isinstance(job.result, dict) else {}
    result.pop("host_attestation_id", None)
    return result


def _workspace_evidence_tree(workspace: Path) -> dict[str, str]:
    root = workspace.resolve(strict=True)
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: workspace evidence tree contains symlink {relative}"
            )
        if path.is_file():
            entries[relative] = _sha256(path)
        elif not path.is_dir():
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: workspace evidence tree contains non-regular entry {relative}"
            )
    return entries


def _allowed_agent_write_paths(
    workspace: Path,
    *,
    report_id: str,
    resume: bool,
    trusted_resume_proof_sha256: str | None = None,
    council_ingress_tasks: tuple[CouncilIngressTask, ...] = (),
) -> tuple[set[str], set[str]]:
    prompt = "identity/web_agent_resume.md" if resume else "identity/web_agent_task.md"
    allowed = {
        prompt,
        "identity/web_execution_ledger.md",
        "identity/web_agent_completion.json",
    }
    required = {
        "identity/web_execution_ledger.md",
    }
    if not resume:
        if council_ingress_tasks:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh run cannot carry Council ingress tasks"
            )
        if trusted_resume_proof_sha256 is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh agent run cannot carry resume proof"
            )
        allowed.add("identity/web_research_plan.json")
        required.add("identity/web_research_plan.json")
        return allowed, required

    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    )
    if (
        not trusted_resume_proof_sha256
        or not proof_path.is_file()
        or proof_path.is_symlink()
        or _sha256(proof_path) != trusted_resume_proof_sha256
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: current resume proof does not match host trust"
        )
    if council_ingress_tasks:
        allowed = {prompt}
        required = set()
        for task in council_ingress_tasks:
            allowed.add(task.expected_result_path)
            required.add(task.expected_result_path)
        return allowed, required
    if proof_path.is_file() and not proof_path.is_symlink():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        pause = (
            proof.get("main_agent_mechanism_memo")
            if isinstance(proof.get("main_agent_mechanism_memo"), dict)
            else {}
        )
        if (
            str(proof.get("status") or "").upper() == "PAUSED"
            and str(pause.get("token") or "") == "AWAITING_MAIN_AGENT_MECHANISM_MEMO"
        ):
            memo_json = (
                "objects/research_iteration_master/"
                f"main_agent_mechanism_memo__{report_id}.json"
            )
            memo_md = (
                "objects/research_iteration_master/"
                f"main_agent_mechanism_memo__{report_id}.md"
            )
            allowed.update({memo_json, memo_md})
            required.add(memo_json)
    return allowed, required


def _trusted_council_ingress_tasks(
    workspace: Path,
    *,
    report_id: str,
    trusted_resume_proof_sha256: str,
) -> tuple[CouncilIngressTask, ...]:
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    )
    if (
        not trusted_resume_proof_sha256
        or not proof_path.is_file()
        or proof_path.is_symlink()
        or _sha256(proof_path) != trusted_resume_proof_sha256
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress proof is not host trusted"
        )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    council = (
        proof.get("revision_council")
        if isinstance(proof.get("revision_council"), dict)
        else {}
    )
    awaiting = (
        str(proof.get("status") or "").upper() == "PAUSED"
        and str(council.get("status") or "") == "awaiting_agent_results"
        and str(council.get("effective_mode") or "")
        == "agentic_dispatch_manifest"
    )
    if not awaiting:
        return ()
    return load_council_ingress_tasks(
        workspace,
        report_id,
        require_results_absent=True,
    )


def _validate_agent_write_boundary(
    workspace: Path,
    *,
    before: dict[str, str],
    allowed: set[str],
    required: set[str],
) -> None:
    after = _workspace_file_snapshot(workspace)
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    unexpected = sorted(changed - allowed)
    if unexpected:
        raise RuntimeError(
            f"{BLOCK_AGENT_WRITE_SCOPE_INVALID}: unexpected writes="
            + ",".join(unexpected[:50])
        )
    missing = sorted(
        path
        for path in required
        if not str(after.get(path) or "").startswith("file:")
    )
    unsafe = sorted(
        path
        for path in changed & allowed
        if path in after and not after[path].startswith("file:")
    )
    if missing or unsafe:
        detail = [*(f"missing:{path}" for path in missing), *(f"unsafe:{path}" for path in unsafe)]
        raise RuntimeError(
            f"{BLOCK_AGENT_WRITE_SCOPE_INVALID}: " + ",".join(detail[:50])
        )


def audit_factor_worktree(worktree: Path, workspace: Path) -> list[str]:
    failures: list[str] = []
    worktree = worktree.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    try:
        workspace.relative_to(worktree)
    except ValueError:
        return ["workspace is outside allocated worktree"]

    manifest_path = workspace / "manifest.json"
    if not manifest_path.is_file():
        failures.append("workspace manifest missing")
    else:
        failures.extend(validate_workspace_manifest(load_workspace_manifest(manifest_path)))

    for path in workspace.rglob("*"):
        if path.is_symlink():
            failures.append(f"symlink forbidden inside workspace: {path.relative_to(workspace).as_posix()}")

    changed: set[str] = set()
    commands = (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
    )
    for args in commands:
        proc = subprocess.run(
            ["git", "-C", str(worktree), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            failures.append(f"git audit failed for {' '.join(args)}")
            continue
        changed.update(item for item in proc.stdout.split("\0") if item)
    for relative in sorted(changed):
        candidate = (worktree / relative).resolve(strict=False)
        try:
            candidate.relative_to(workspace)
        except ValueError:
            failures.append(f"write outside factor workspace: {relative}")
    return list(dict.fromkeys(failures))


def build_web_result(
    summary: UltimateRunSummary,
    *,
    publication_id: str,
    public_artifacts: list[SafeArtifact],
) -> dict[str, Any]:
    artifacts = []
    for item in public_artifacts[:300]:
        kind = "image" if item.media_type.startswith("image/") and item.content_disposition == "inline" else "document"
        artifacts.append(
            {
                "artifact_id": item.artifact_id,
                "label": _artifact_label(item.artifact_id),
                "kind": kind,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
            }
        )
    research_method = dict(summary.research_method)
    if summary.economic_game:
        research_method.setdefault("economic_mechanism", summary.economic_game)
    if summary.math_mechanism:
        research_method.setdefault("mathematical_object", summary.math_mechanism)
    data_implementation = {**summary.data_contract, **summary.implementation_contract}
    return {
        "contract_version": "factorforge_console_web_result_v1",
        "public_artifact_set_id": publication_id,
        "summary": _result_summary(summary),
        "execution_status": summary.execution_status,
        "protocol_status": summary.protocol_status,
        "factor_verdict": summary.factor_verdict,
        "council_status": summary.council_status,
        "formal_proof_eligible": summary.formal_proof_eligible,
        "current_stage": summary.current_stage,
        "research_method": research_method,
        "data_implementation": data_implementation,
        "metrics": summary.core_metrics,
        "metric_sources": summary.metric_sources,
        "blockers": summary.blockers + summary.evidence_errors,
        "next_actions": summary.next_actions,
        "timestamps": summary.timestamps,
        "evidence_artifact_ids": summary.artifact_ids,
        "stages": _stage_records(summary),
        "artifacts": artifacts,
    }


def _web_execution_status(summary: UltimateRunSummary, agent_returncode: int) -> str:
    if agent_returncode != 0:
        return "FAILED"
    status = summary.execution_status.upper()
    if status == "COMPLETED" or status == "REJECTED":
        return "COMPLETED"
    if status in {"PAUSED", "ITERATING", "REVIEW_REQUIRED", "RUNNING"}:
        return "REVIEW_REQUIRED"
    if status == "BLOCKED":
        return "BLOCKED"
    if status in {"FAILED", "DRY_RUN"}:
        return "FAILED"
    return "FAILED"


def _normalize_protocol(value: str) -> str:
    normalized = str(value or "UNKNOWN").upper()
    return {
        "BLOCKED": "BLOCK",
        "FAILED": "FAIL",
        "COMPLETED": "PASS",
    }.get(normalized, normalized if normalized in {"NOT_STARTED", "RUNNING", "PAUSED", "PASS", "BLOCK", "FAIL", "UNKNOWN"} else "UNKNOWN")


def _normalize_council(value: str) -> str:
    normalized = str(value or "UNKNOWN").upper()
    if normalized == "BLOCKED":
        return "BLOCK"
    return normalized if normalized in {"NOT_STARTED", "RUNNING", "PAUSED", "PASS", "BLOCK", "REJECTED", "NOT_REQUIRED", "UNKNOWN"} else "UNKNOWN"


def _web_stage(summary: UltimateRunSummary) -> str:
    status = summary.execution_status.upper()
    if status == "COMPLETED" or status == "REJECTED":
        return "completed"
    if status in {"PAUSED", "ITERATING", "REVIEW_REQUIRED"}:
        return "review_required"
    if status == "BLOCKED":
        return "blocked"
    return "failed"


def _stage_records(summary: UltimateRunSummary) -> list[dict[str, str]]:
    has_method = bool(summary.research_method or summary.economic_game or summary.math_mechanism)
    has_data = bool(summary.data_contract)
    has_implementation = bool(summary.implementation_contract)
    has_metrics = bool(summary.core_metrics)
    council = summary.council_status.upper()
    return [
        {"id": "mechanism", "status": "done" if has_method else "pending"},
        {"id": "data", "status": "done" if has_data else "pending"},
        {"id": "implementation", "status": "done" if has_implementation else "pending"},
        {"id": "evaluation", "status": "done" if has_metrics else "pending"},
        {
            "id": "council",
            "status": "done" if council in {"PASS", "REJECTED", "NOT_REQUIRED"} else "blocked" if council in {"BLOCK", "BLOCKED"} else "active" if council in {"RUNNING", "PAUSED"} else "pending",
        },
    ]


def _result_summary(summary: UltimateRunSummary) -> str:
    if summary.factor_verdict == "ACCEPT":
        return "研究协议与正式证明链通过，因子达到当前合同的接受条件。"
    if summary.factor_verdict == "REJECT":
        return "研究流程已完成，但因子未通过收益、成本或稳健性要求。"
    if summary.factor_verdict == "ITERATE":
        return "当前证据建议修订；需在现有 workspace 上显式继续。"
    if summary.factor_verdict == "BLOCK":
        return "研究被数据、实现或证明合同阻断，不能把现有结果当作因子结论。"
    if summary.execution_status == "PAUSED":
        return "研究处于可恢复暂停状态，尚未形成正式因子结论。"
    return "尚未形成可核验的正式因子结论。"


def _artifact_label(artifact_id: str) -> str:
    name = Path(artifact_id).stem.replace("__", " · ").replace("_", " ")
    return name[:120]


def _public_error_message(
    message: str,
    *,
    denied_values: tuple[str, ...] = (),
) -> str:
    text = str(message).replace("\n", " ")[:1200]
    text = re.sub(
        r"(?i)(?:file://\S+|s3://\S+|/(?:Users|home|srv|private|tmp|var/lib|root|etc|opt)/\S+)",
        "[internal-path]",
        text,
    )
    text = re.sub(
        r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        text,
    )
    text = _redact_public_text(text, denied_values)
    return text


def _adapter_denied_values(
    adapter: ResearchAgentAdapter,
    job_id: str,
) -> tuple[str, ...]:
    reader = getattr(adapter, "denied_secret_values", None)
    if not callable(reader):
        return ()
    values = reader(job_id)
    return tuple(str(value) for value in values if len(str(value)) >= 8)


def _adapter_credential_material_state(
    adapter: ResearchAgentAdapter,
    job_id: str,
) -> str:
    reader = getattr(adapter, "credential_material_state", None)
    if not callable(reader):
        return "unknown"
    state = str(reader(job_id))
    if state not in {"unknown", "not_issued", "may_have_been_issued"}:
        raise RuntimeError("credential material state is invalid")
    return state


def _redact_public_payload(value: Any, denied_values: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            _redact_public_text(str(key), denied_values): _redact_public_payload(
                child,
                denied_values,
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_public_payload(child, denied_values) for child in value]
    if isinstance(value, tuple):
        return [_redact_public_payload(child, denied_values) for child in value]
    if isinstance(value, str):
        return _redact_public_text(value, denied_values)
    return value


def _redact_public_text(value: str, denied_values: tuple[str, ...]) -> str:
    return redact_secret_values(value, denied_values, replacement="[redacted]")


def _subprocess_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _stamp(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", value)


def _argv_value(argv: list[Any], flag: str) -> str:
    normalized = [str(value) for value in argv]
    try:
        index = normalized.index(flag)
    except ValueError:
        return ""
    return normalized[index + 1] if index + 1 < len(normalized) else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(
    path: Path,
    payload: dict[str, Any],
    *,
    root: Path,
) -> None:
    write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        root=root,
    )
