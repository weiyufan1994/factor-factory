from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from factor_factory.console.agent_adapter import ResearchAgentAdapter
from factor_factory.console.artifact_service import list_safe_artifacts
from factor_factory.console.config import ConsoleConfig
from factor_factory.console.models import ResearchJob, ResearchRequest, validate_public_source_url
from factor_factory.console.store import ResearchJobStore, utc_now
from factor_factory.console.ultimate_reader import UltimateRunSummary, read_ultimate_workspace
from factor_factory.console.worktree_allocator import (
    FactorWorktreeAllocator,
    WorktreeAllocation,
    WorktreeAllocationError,
)
from factor_factory.research_workspace import load_workspace_manifest, validate_workspace_manifest


BLOCK_ISOLATION_AUDIT_FAILED = "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED"
BLOCK_EVIDENCE_IDENTITY_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_EVIDENCE_IDENTITY_MISMATCH"
BLOCK_FORMAL_EVIDENCE_MISSING = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_EVIDENCE_MISSING"


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
        adapter_health = getattr(self.agent_adapter, "healthcheck", None)
        try:
            source_ready = self.allocator.validate_ready() == self._expected_base_commit
            runtime_ready = bool(adapter_health()) if callable(adapter_health) else True
        except (OSError, RuntimeError, ValueError):
            return False
        return bool(
            self._thread
            and self._thread.is_alive()
            and not self._stop.is_set()
            and source_ready
            and runtime_ready
        )

    def submit(self, request: ResearchRequest) -> ResearchJob:
        if request.source_url:
            raise ValueError(
                "source URL ingestion is disabled until the read-only fetch broker is available"
            )
        job = self.store.create_job(request)
        self._wake.set()
        return job

    def request_resume(self, job_id: str) -> ResearchJob:
        job = self.store.request_resume(job_id)
        self._wake.set()
        return job

    def cancel_queued(self, job_id: str) -> ResearchJob:
        return self.store.cancel_queued(job_id)

    def run_once(self) -> ResearchJob | None:
        job = self.store.claim_next_job()
        if job is None:
            return None
        self._run_job(job)
        return self.store.get_job(job.job_id)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next_job()
            if job is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            self._run_job(job)

    def _run_job(self, job: ResearchJob) -> None:
        try:
            validate_public_source_url(job.request.source_url)
            resume = bool(job.workspace_path and job.worktree_path)
            if resume:
                worktree = Path(job.worktree_path).resolve(strict=True)
                workspace = Path(job.workspace_path).resolve(strict=True)
                allocation = None
                self._write_resume_authorization(job, workspace)
            else:
                allocation = self.allocator.allocate(
                    factor_id=job.factor_id,
                    research_id=job.research_id,
                    report_id=job.report_id,
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
            agent_result = self.agent_adapter.run(
                current_job,
                worktree=worktree,
                workspace=workspace,
                resume=resume,
            )
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

            isolation_failures = audit_factor_worktree(worktree, workspace)
            if isolation_failures:
                raise RuntimeError(f"{BLOCK_ISOLATION_AUDIT_FAILED}: {'; '.join(isolation_failures)}")
            summary = read_ultimate_workspace(workspace, report_id=job.report_id)
            self._validate_summary_identity(job, summary)
            result = build_web_result(summary, workspace)
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
        except (WorktreeAllocationError, FileNotFoundError, ValueError, RuntimeError) as exc:
            message = str(exc)
            token = message.split(":", 1)[0] if message.startswith("BLOCK_") else "BLOCK_FACTORFORGE_CONSOLE_RUN_FAILED"
            self.store.update_job(
                job.job_id,
                execution_status="BLOCKED" if token.startswith("BLOCK_") else "FAILED",
                protocol_status="BLOCK" if token.startswith("BLOCK_") else "FAIL",
                factor_verdict="BLOCK" if token.startswith("BLOCK_") else "UNKNOWN",
                current_stage="blocked" if token.startswith("BLOCK_") else "failed",
                error_code=token,
                error_message=_public_error_message(message),
                finished_at_utc=utc_now(),
            )
            self.store.append_event(job.job_id, "RUN_BLOCKED", _public_error_message(message), {"code": token})
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
                finished_at_utc=utc_now(),
            )
            self.store.append_event(
                job.job_id,
                "RUN_BLOCKED",
                "研究服务发生未预期错误；任务证据已保留，未自动重试。",
                {"code": token, "exception_type": type(exc).__name__},
            )

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

    def _write_request_artifacts(self, job: ResearchJob, allocation: WorktreeAllocation) -> None:
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
        _write_json_atomic(workspace / "identity" / "web_research_request.json", request_payload)
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
        source_path.write_text("\n".join(source_lines) + "\n", encoding="utf-8")

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
        _write_json_atomic(workspace / "identity" / "web_resume_authorization.json", payload)


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


def build_web_result(summary: UltimateRunSummary, workspace: Path) -> dict[str, Any]:
    artifacts = []
    for item in list_safe_artifacts(workspace)[:300]:
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
    status = summary.execution_status.upper()
    if status == "COMPLETED" or status == "REJECTED":
        return "COMPLETED"
    if status in {"PAUSED", "ITERATING", "REVIEW_REQUIRED", "RUNNING"}:
        return "REVIEW_REQUIRED"
    if status == "BLOCKED":
        return "BLOCKED"
    if status in {"FAILED", "DRY_RUN"}:
        return "FAILED"
    if agent_returncode != 0:
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


def _public_error_message(message: str) -> str:
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
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
