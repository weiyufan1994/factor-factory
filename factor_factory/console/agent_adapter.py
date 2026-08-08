from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.model_broker import normalize_deepseek_openclaw_model
from factor_factory.console.models import ResearchJob
from factor_factory.console.secret_safety import redact_secret_values
from factor_factory.console.store import utc_now
from factor_factory.console.web_research_plan import write_text_atomic
from factor_factory.mechanism_math.main_agent_memo import (
    MAX_MECHANISM_MEMO_REVISIONS,
    formula_specific_qa_terms,
)


BLOCK_AGENT_RUNTIME_UNAVAILABLE = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE"
BLOCK_AGENT_ORPHANED_WRITER = "BLOCK_FACTORFORGE_CONSOLE_AGENT_ORPHANED_WRITER"
BLOCK_AGENT_RUNTIME_FAILED = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED"
BLOCK_AGENT_RUNTIME_TIMEOUT = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_TIMEOUT"
BLOCK_RESUME_TRUST_INVALID = "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
RESUME_MEMO_MAX_BYTES = 24_000
RESUME_MEMO_AGENT_PATCH_MAX_BYTES = 16_000
RESUME_MEMO_AGENT_PATCH_TARGET_BYTES = 14_000
# Reserve the prompt's 14 KB target for agent-authored research fields. The
# separate 16 KB patch and 24 KB reconstructed-memo gates remain hard limits.
RESUME_MEMO_COMPLETION_RESERVE_BYTES = RESUME_MEMO_AGENT_PATCH_TARGET_BYTES
RESUME_ANSWER_FORM_MAX_BYTES = (
    RESUME_MEMO_MAX_BYTES - RESUME_MEMO_COMPLETION_RESERVE_BYTES - 1
)
RESUME_PROMPT_INPUT_MAX_BYTES = 128 * 1024
RESUME_FACT_LOCK_MAX_BYTES = RESUME_ANSWER_FORM_MAX_BYTES
RESUME_FACT_LOCK_MAX_DEPTH = 8
RESUME_FACT_LOCK_MAX_NODES = 2_048
RESUME_FACT_LOCK_MAX_CONTAINER_ITEMS = 512
RESUME_FACT_LOCK_MAX_STRING_BYTES = 4_096
RESUME_FACT_LOCK_MAX_KEY_BYTES = 256
RESUME_MEMO_IMMUTABLE_FIELDS = (
    "contract_version",
    "resume_attempt_id",
    "report_id",
    "factor_id",
    "research_id",
    "source_refs",
    "formula",
    "formula_understanding",
    "canonical_write_permission",
    "execution_allowed_by_default",
)
RESUME_MEMO_COMPONENT_IDENTITY_FIELDS = (
    "component_id",
    "formula_subexpression",
    "operators",
)
RESUME_MEMO_OPERATOR_FLAG_FIELDS = (
    "formula_has_correlation_or_covariance_operator",
    "has_sign_or_threshold",
    "has_volume_ratio",
    "has_additive_rank_raw_ratio",
)
RESUME_MEMO_AGENT_DIRECT_FIELDS = (
    "producer",
    "agent_authorship",
    "mechanism_qa",
    "economic_hypothesis",
    "math_hypothesis",
    "math_model_selection",
    "payer",
    "mathematical_object_mapping",
    "expected_metric_signature",
    "falsification_tests",
    "council_questions",
)
RESUME_MEMO_AGENT_COMPONENT_FIELDS = (
    "observable_estimator",
    "economic_state",
    "mathematical_object",
    "expected_role",
    "metric_link",
)
RESUME_MEMO_AGENT_EVIDENCE_FIELDS = (
    "mechanism_supported",
    "contradictions",
    "revision_implications",
    "kill_criteria_triggered",
)
RESUME_MEMO_AGENT_OPERATOR_FIELDS = (
    "claims_correlation_or_covariance",
    "claims_dependence_without_operator_justification",
    "explicit_dependence_justification",
    "sign_threshold_discussion_present",
    "volume_ratio_participation_discussion_present",
    "additive_scale_commensurability_discussion_present",
)
RESUME_MEMO_AGENT_PATCH_FIELDS = (
    *RESUME_MEMO_AGENT_DIRECT_FIELDS,
    "formula_component_map",
    "evidence_comparison",
    "operator_claim_consistency",
)
RESUME_MEMO_LEGACY_AGENT_DIRECT_FIELDS = tuple(
    "formula_state_estimator"
    if field == "mathematical_object_mapping"
    else field
    for field in RESUME_MEMO_AGENT_DIRECT_FIELDS
)
RESUME_MEMO_LEGACY_AGENT_PATCH_FIELDS = (
    *RESUME_MEMO_LEGACY_AGENT_DIRECT_FIELDS,
    "formula_component_map",
    "evidence_comparison",
    "operator_claim_consistency",
)


@dataclass(frozen=True)
class AgentRunResult:
    returncode: int
    agent_id: str
    session_key: str
    started_at_utc: str
    finished_at_utc: str
    stdout_tail: str
    stderr_tail: str
    result_path: str
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class AgentResumeTask:
    version: str
    attempt_id: str
    job_id: str
    factor_id: str
    research_id: str
    report_id: str
    resume_start_step: str
    pause_kind: str
    pause_token: str
    session_policy: str
    ultimate_proof_sha256: str
    contract_relative: str
    status_relative: str
    questionnaire_relative: str
    questionnaire_markdown_relative: str
    facts_relative: str
    answer_form_relative: str
    required_output_relative: str
    optional_output_relative: str
    read_only_inputs: tuple[str, ...]
    protected_inputs: tuple[str, ...]
    allowed_model_families: tuple[str, ...]
    validation_command: str
    prior_output_sha256: tuple[tuple[str, str], ...] = ()
    prior_output_archive_id: str = ""


class ResearchAgentAdapter(Protocol):
    def validate_ready(self) -> str:
        ...

    def run(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task: AgentResumeTask | None = None,
    ) -> AgentRunResult:
        ...

    def stop_all(self) -> None:
        ...

    def healthcheck(self) -> bool:
        ...

    def prepare_host_data_environment(
        self,
        job_id: str,
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        ...


class OpenClawResearchAgentAdapter:
    def __init__(self, config: ConsoleConfig) -> None:
        self.config = config

    def validate_ready(self) -> str:
        if not self.config.openclaw_profile:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: a dedicated OpenClaw profile is required")
        validate_auth_database(
            self.config.openclaw_auth_seed_db,
            provider=self.config.openclaw_auth_provider,
            label="credential seed",
        )
        self._probe(["config", "validate"], timeout=20)
        output = self._probe(["health", "--json", "--timeout", "5000"], timeout=15)
        try:
            health = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: dedicated OpenClaw gateway returned invalid health JSON"
            ) from exc
        plugin_errors = ((health.get("plugins") or {}).get("errors") or []) if isinstance(health, dict) else []
        if not isinstance(health, dict) or health.get("ok") is not True or plugin_errors:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: dedicated OpenClaw gateway is unhealthy"
            )
        return self.config.openclaw_profile

    def stop_all(self) -> None:
        return None

    def healthcheck(self) -> bool:
        return True

    def prepare_host_data_environment(
        self,
        job_id: str,
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        return {}, ()

    def run(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task: AgentResumeTask | None = None,
    ) -> AgentRunResult:
        base_agent_id = f"factorforge-web-{job.job_id.removeprefix('job_')}"
        agent_id = (
            f"{base_agent_id}-r-{resume_task.attempt_id[-8:]}"
            if resume and resume_task is not None
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
        started = utc_now()
        try:
            runtime_model = normalize_deepseek_openclaw_model(
                job.request.model or self.config.openclaw_model
            )
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent model is not pinned to DeepSeek V4 Flash"
            ) from exc
        if resume or not job.agent_id:
            self._ensure_agent(agent_id, workspace, runtime_model)
        command = [
            *self._command_prefix(),
            "agent",
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
        try:
            proc = subprocess.run(
                command,
                cwd=worktree,
                env=self._runtime_env(worktree, workspace),
                text=True,
                capture_output=True,
                timeout=self.config.agent_timeout_seconds + 90,
            )
            returncode = proc.returncode
            stdout = redact_secrets(proc.stdout)
            stderr = redact_secrets(proc.stderr)
            error_code = "" if returncode == 0 else BLOCK_AGENT_RUNTIME_FAILED
        except FileNotFoundError as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.openclaw_binary}") from exc
        except subprocess.TimeoutExpired as exc:
            stdout = redact_secrets(_as_text(exc.stdout))
            stderr = redact_secrets(_as_text(exc.stderr))
            returncode = 124
            error_code = BLOCK_AGENT_RUNTIME_TIMEOUT

        result_dir = self.config.state_root / "jobs" / job.job_id
        result_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        result_path = result_dir / f"agent_run_{utc_now().replace(':', '').replace('-', '')}.json"
        payload = {
            "version": "factorforge_console_agent_run_v1",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "agent_id": agent_id,
            "session_key_sha256": hashlib.sha256(session_key.encode("utf-8")).hexdigest(),
            "resume": resume,
            "resume_attempt_id": resume_task.attempt_id if resume_task is not None else "",
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "returncode": returncode,
            "provider": self.config.openclaw_auth_provider,
            "model": runtime_model,
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
            finished_at_utc=str(payload["finished_at_utc"]),
            stdout_tail=str(payload["stdout_tail"]),
            stderr_tail=str(payload["stderr_tail"]),
            result_path=str(result_path),
            provider=self.config.openclaw_auth_provider,
            model=runtime_model,
        )

    def _ensure_agent(self, agent_id: str, workspace: Path, model: str) -> None:
        agent_state = self.config.state_root / "agents" / agent_id
        agent_state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._install_auth_seed(agent_state)
        command = [
            *self._command_prefix(),
            "agents",
            "add",
            agent_id,
            "--workspace",
            str(workspace),
            "--agent-dir",
            str(agent_state),
            "--non-interactive",
            "--json",
        ]
        if model:
            command.extend(["--model", model])
        try:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=60)
        except FileNotFoundError as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.openclaw_binary}") from exc
        if proc.returncode != 0 and "already exists" not in (proc.stderr + proc.stdout).lower():
            detail = redact_secrets(proc.stderr or proc.stdout)[-1200:]
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {detail}")
        self._validate_agent_binding(agent_id, workspace, agent_state, model)

    def _install_auth_seed(self, agent_state: Path) -> None:
        destination = agent_state / "openclaw-agent.sqlite"
        if destination.exists():
            validate_auth_database(
                destination,
                provider=self.config.openclaw_auth_provider,
                label="agent credential store",
            )
            return
        seed = self.config.openclaw_auth_seed_db
        validate_auth_database(seed, provider=self.config.openclaw_auth_provider, label="credential seed")
        assert seed is not None
        temp = agent_state / f".openclaw-agent.sqlite.seed-{os.getpid()}"
        copy_auth_database(seed, temp)
        temp.chmod(0o600)
        temp.replace(destination)
        validate_auth_database(
            destination,
            provider=self.config.openclaw_auth_provider,
            label="copied agent credential store",
        )

    def _validate_agent_binding(self, agent_id: str, workspace: Path, agent_state: Path, model: str) -> None:
        output = self._probe(["agents", "list", "--json"], timeout=30)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: cannot verify agent binding") from exc
        agents = payload if isinstance(payload, list) else payload.get("agents", [])
        match = next((item for item in agents if str(item.get("id") or item.get("agentId")) == agent_id), None)
        expected = {
            "workspace": str(workspace.resolve()),
            "agentDir": str(agent_state.resolve()),
        }
        if not isinstance(match, dict):
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: agent binding is missing")
        for key, value in expected.items():
            actual = str(match.get(key) or "")
            if not actual or str(Path(actual).expanduser().resolve()) != value:
                raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: existing agent {key} binding mismatch")
        actual_model = str(match.get("model") or "")
        if model and actual_model != model:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: existing agent model binding mismatch")

    def _probe(self, args: list[str], *, timeout: int) -> str:
        try:
            proc = subprocess.run(
                [*self._command_prefix(), *args],
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {self.config.openclaw_binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: OpenClaw readiness probe timed out") from exc
        if proc.returncode != 0:
            detail = redact_secrets(proc.stderr or proc.stdout)[-1200:]
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {detail}")
        return proc.stdout

    def _command_prefix(self) -> list[str]:
        command = [self.config.openclaw_binary]
        if self.config.openclaw_profile:
            command.extend(["--profile", self.config.openclaw_profile])
        return command

    def _runtime_env(self, worktree: Path, workspace: Path) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "FACTORFORGE_ROOT": str(worktree),
                "FACTORFORGE_FACTOR_WORKSPACE": str(workspace),
                "PYTHONUNBUFFERED": "1",
            }
        )
        if self.config.data_catalogs:
            env["FACTORFORGE_STATE_CATALOG"] = str(self.config.data_catalogs[0])
        if self.config.data_api_pythonpath:
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = os.pathsep.join(
                part for part in (str(self.config.data_api_pythonpath), str(worktree), existing) if part
            )
        return env


def build_agent_prompt(
    job: ResearchJob,
    *,
    worktree: Path,
    workspace: Path,
    config: ConsoleConfig,
    resume: bool,
    resume_task: AgentResumeTask | None = None,
) -> str:
    if resume:
        if resume_task is None:
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID: typed resume task is required"
            )
        return _build_agent_resume_prompt(
            job,
            worktree=worktree,
            workspace=workspace,
            task=resume_task,
            execution_mode=config.execution_mode,
        )
    if resume_task is not None:
        raise RuntimeError(
            "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID: fresh authoring cannot carry a resume task"
        )
    catalogs = "- `identity/data_catalog_summary.json` (operator-authored, read-only projection)"
    action = "Start a new formal run from the submitted natural-language hypothesis."
    packet_files = [
        workspace / "identity" / "web_research_runtime.md",
        workspace / "identity" / "web_research_request.json",
        workspace / "identity" / "data_catalog_summary.json",
        workspace / "identity" / "factor_knowledge_summary.json",
        workspace / "identity" / "web_research_authoring_contract.json",
        workspace / "identity" / "research_organization_plan.json",
        workspace / "identity" / "web_research_plan.json",
    ]
    packet_list = "\n".join(f"- {path}" for path in dict.fromkeys(packet_files))
    return f"""# Factor Forge Web Research Task

You are the initial authoring agent for one isolated Factor Forge task. {action}
The Host-owned research-organization plan defines the wider specialist roles;
this authoring session does not impersonate those roles or an independent Council.

## Immutable identity

- job_id: {job.job_id}
- factor_id: {job.factor_id}
- research_id: {job.research_id}
- report_id: {job.report_id}
- engine worktree: {worktree}
- active factor workspace: {workspace}

The operator has already projected the installed Ultimate, Researcher and
Research Brain contracts into this task-local runtime packet. Read only these
Host-named files before acting:

{packet_list}

The formal validators and `scripts/run_factorforge_ultimate.py` remain the
source of truth. Do not read whole skill files or validator/wrapper source.

## Submitted research object

- title: {job.request.title}
- hypothesis: {job.request.hypothesis}
- universe: {job.request.universe}
- formal sample: {job.request.sample_start} through {job.request.sample_end}
- forward horizon: {job.request.forward_horizon}
- transaction cost assumption: {job.request.transaction_cost_bps} bps
- source material: user-authored natural-language hypothesis only; external URL ingestion is disabled

## Read-only Data API inputs

{catalogs}

The agent receives no Data API package, catalog file, S3 credential, or raw dataset mount.
Use only the operator-authored catalog summary to design the legal information set and Formula
IR field requirements. After authoring exits, the host obtains a separate short-lived read-only
lease and the formal Step3/4 scripts consume the pinned catalog and Data API.

## Mandatory execution contract

1. Treat this as a natural_language_hypothesis, never as a broker report and never invent attribution.
2. All factor-specific code, notes, raw model responses, metrics, Council packets, knowledge and results must stay under the exact active factor workspace above.
3. Do not write to another factor_research directory, repo-root knowledge, repo-root data, shared clean data, another worktree, or any cloud dataset. The task-local catalog summary is descriptive only; the agent has no Data API, catalog-file, S3, or raw-data access.
4. Do not run `run_factorforge_ultimate_loop.py`, the materializer, Step scripts, or `scripts/run_factorforge_ultimate.py`. Fill the task-local web research plan with a Formula IR-compatible factor law, but preserve its Host-filled `identity` and `authoring_contract` objects exactly; never recompute or hand-copy the contract hash. On resume write only the artifact required by the named pause. Do not author or execute custom Python. On a fresh run, execute only the authoring preflight command printed in `web_research_runtime.md`, correct named plan fields until it returns PASS, and then exit. The host exclusively materializes and runs formal Step3 through Step6 after your process exits.
5. Never use fixtures, deterministic fallback, local mock, smoke evidence or dry-run output as formal research proof. A missing dataset must produce a precise BLOCK/data request, not invented evidence.
6. On resume, write only the exact named research memo permitted by the current pause. The host owns Council dispatch, synthesis, evidence interpretation, and every formal wrapper invocation. Do not use the unimplemented `real_agent`/`remote_api` wrapper adapters.
7. Keep preferred, null and alternative hypotheses distinct. Record economic payer, mathematical object, legal information set, falsifiers, component ablations, costs, long-side economics, IS/OOS boundary and proof-certificate status.
8. A process exit code or wrapper PASS is not a factor verdict. Finish only with formal ACCEPT, REJECT, BLOCK, or an honest REVIEW_REQUIRED pause.
9. Do not create a revision child or record human approval unless an existing artifact under `identity/` explicitly authorizes this resume. Automated action must never be labeled human approval.
10. Before finishing, verify the workspace manifest and inspect Git status. Any write outside the active workspace is a blocking failure.
11. Network egress is restricted to the fixed model broker. Do not attempt to reach S3, Data API, catalog storage, raw data, arbitrary websites, or any other network destination, and do not attempt to bypass the proxy.
12. The runtime has already completed operator-owned model, network, credential and Data API readiness checks. Never enumerate environment variables or credential material; never run `env`/`printenv`, read `/proc/*/environ`, query instance metadata, inspect AWS credential/config files, or inspect the OpenClaw auth database. Never print, hash, transform, persist or return any API key, access key, session token, password or broker token. If credentials appear unexpectedly, stop and record a BLOCK without reproducing them.
13. Do not replace formal execution with ad hoc environment, package-source, credential or network probes. Begin from the task-local runtime packet and stop after the research plan or named resume artifact is complete; the Host alone uses the Data API through its public interface and pinned catalog after agent authoring exits.
14. Do not recursively dump documents or inspect internal schemas. After reading the seven packet files, write a concise execution ledger of at most 4,000 characters to `identity/web_execution_ledger.md`, then complete the plan or pause artifact. The read-only authoring contract, organization plan and preflight output are sufficient to correct plan syntax; do not inspect validator source.

The host derives authoring status from the validated plan, execution ledger and private
agent-run receipt. Do not create a separate completion-status artifact or claim that formal
research ran. On a fresh run, exit only after the plan is complete and its preflight returns
PASS; on resume, exit after the exact permitted pause artifact is complete. Do not include
secrets or absolute paths in the execution ledger.
"""


def _resume_prompt_error(detail: str) -> RuntimeError:
    return RuntimeError(f"{BLOCK_RESUME_TRUST_INVALID}: {detail}")


def _read_stable_resume_prompt_bytes(
    workspace: Path,
    relative: str,
    *,
    max_bytes: int = RESUME_PROMPT_INPUT_MAX_BYTES,
) -> bytes:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or relative_path == Path(".")
        or ".." in relative_path.parts
    ):
        raise _resume_prompt_error("resume prompt input path is invalid")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_descriptor: int | None = None
    file_descriptor: int | None = None
    try:
        root = workspace.resolve(strict=True)
        if not root.is_absolute():
            raise OSError("workspace root is not absolute")
        directory_descriptor = os.open("/", directory_flags)
        for part in root.parts[1:]:
            next_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        for part in relative_path.parts[:-1]:
            next_descriptor = os.open(
                part,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor

        name = relative_path.parts[-1]
        file_descriptor = os.open(name, file_flags, dir_fd=directory_descriptor)
        before = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > max_bytes
        ):
            raise OSError("resume prompt input is unsafe or too large")

        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(file_descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(file_descriptor)
        path_after = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        path_identity = (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_mode,
            path_after.st_nlink,
            path_after.st_size,
            path_after.st_mtime_ns,
            path_after.st_ctime_ns,
        )
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            before_identity != after_identity
            or after_identity != path_identity
            or after.st_nlink != 1
            or path_after.st_nlink != 1
            or not stat.S_ISREG(path_after.st_mode)
            or len(payload) != before.st_size
        ):
            raise OSError("resume prompt input changed while reading")
        return payload
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise _resume_prompt_error("resume prompt input is invalid") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _parse_resume_prompt_json(payload: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _resume_prompt_error("resume prompt input is invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise _resume_prompt_error("resume prompt input must be an object")
    return parsed


def _validate_resume_fact_lock_shape(value: Any) -> None:
    node_count = 0

    def visit(item: Any, *, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if (
            depth > RESUME_FACT_LOCK_MAX_DEPTH
            or node_count > RESUME_FACT_LOCK_MAX_NODES
        ):
            raise _resume_prompt_error("resume fact lock exceeds structural budget")
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, str):
            if len(item.encode("utf-8")) > RESUME_FACT_LOCK_MAX_STRING_BYTES:
                raise _resume_prompt_error("resume fact lock string is too large")
            return
        if isinstance(item, int):
            return
        if isinstance(item, float):
            if item != item or item in (float("inf"), float("-inf")):
                raise _resume_prompt_error(
                    "resume fact lock contains a non-finite number"
                )
            return
        if isinstance(item, list):
            if len(item) > RESUME_FACT_LOCK_MAX_CONTAINER_ITEMS:
                raise _resume_prompt_error("resume fact lock list is too large")
            for child in item:
                visit(child, depth=depth + 1)
            return
        if isinstance(item, dict):
            if len(item) > RESUME_FACT_LOCK_MAX_CONTAINER_ITEMS:
                raise _resume_prompt_error("resume fact lock object is too large")
            for key, child in item.items():
                if (
                    not isinstance(key, str)
                    or len(key.encode("utf-8")) > RESUME_FACT_LOCK_MAX_KEY_BYTES
                ):
                    raise _resume_prompt_error("resume fact lock key is invalid")
                visit(child, depth=depth + 1)
            return
        raise _resume_prompt_error("resume fact lock contains an unsupported value")

    visit(value, depth=0)


def _read_resume_prompt_json(workspace: Path, relative: str) -> dict[str, Any]:
    return _parse_resume_prompt_json(
        _read_stable_resume_prompt_bytes(workspace, relative)
    )


def _build_resume_prompt_fact_lock(
    workspace: Path,
    task: AgentResumeTask,
) -> dict[str, Any]:
    contract = _read_resume_prompt_json(workspace, task.contract_relative)
    expected_contract_fields = {
        "version": task.version,
        "attempt_id": task.attempt_id,
        "job_id": task.job_id,
        "factor_id": task.factor_id,
        "research_id": task.research_id,
        "report_id": task.report_id,
        "answer_form": task.answer_form_relative,
    }
    input_sha256 = contract.get("input_sha256")
    expected_answer_sha256 = (
        input_sha256.get(task.answer_form_relative)
        if isinstance(input_sha256, dict)
        else None
    )
    expected_facts_sha256 = (
        input_sha256.get(task.facts_relative)
        if isinstance(input_sha256, dict)
        else None
    )
    if (
        any(
            contract.get(field) != expected
            for field, expected in expected_contract_fields.items()
        )
        or not isinstance(expected_answer_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_answer_sha256) is None
        or not isinstance(expected_facts_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_facts_sha256) is None
    ):
        raise _resume_prompt_error("resume contract binding is invalid")
    answer_form_bytes = _read_stable_resume_prompt_bytes(
        workspace,
        task.answer_form_relative,
    )
    if not secrets.compare_digest(
        hashlib.sha256(answer_form_bytes).hexdigest(),
        expected_answer_sha256,
    ):
        raise _resume_prompt_error("resume answer form hash mismatch")
    facts_bytes = _read_stable_resume_prompt_bytes(
        workspace,
        task.facts_relative,
    )
    if not secrets.compare_digest(
        hashlib.sha256(facts_bytes).hexdigest(),
        expected_facts_sha256,
    ):
        raise _resume_prompt_error("resume facts hash mismatch")
    facts = _parse_resume_prompt_json(facts_bytes)
    revision_context = facts.get("revision_context")
    if (
        not isinstance(revision_context, dict)
        or revision_context.get("mode") not in {"initial", "revision"}
        or not isinstance(revision_context.get("revision_number"), int)
        or (
            revision_context.get("revision_number") != 0
            if revision_context.get("mode") == "initial"
            else not 1
            <= revision_context.get("revision_number")
            <= MAX_MECHANISM_MEMO_REVISIONS
        )
        or not isinstance(revision_context.get("failures"), list)
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 2_000
            for item in revision_context.get("failures") or []
        )
        or len(revision_context.get("failures") or []) > 16
    ):
        raise _resume_prompt_error("resume revision context is invalid")
    answer_form = _parse_resume_prompt_json(answer_form_bytes)
    answer_form_minified = json.dumps(
        answer_form,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(answer_form_minified) > RESUME_ANSWER_FORM_MAX_BYTES:
        raise _resume_prompt_error(
            "resume answer form leaves insufficient completion budget"
        )
    formula = answer_form.get("formula")
    formula_understanding = answer_form.get("formula_understanding")
    formula_features = (
        formula_understanding.get("formula_features")
        if isinstance(formula_understanding, dict)
        else None
    )
    source_refs = answer_form.get("source_refs")
    components = answer_form.get("formula_component_map")
    operator_claims = answer_form.get("operator_claim_consistency")
    evidence = answer_form.get("evidence_comparison")
    observed_metrics = (
        evidence.get("observed_metrics") if isinstance(evidence, dict) else None
    )
    if (
        not isinstance(formula, str)
        or not formula.strip()
        or not isinstance(formula_features, dict)
        or not isinstance(source_refs, dict)
        or not source_refs
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in source_refs.items()
        )
        or not isinstance(components, list)
        or not components
        or any(
            not isinstance(component, dict)
            or not isinstance(component.get("component_id"), str)
            or not isinstance(component.get("formula_subexpression"), str)
            or not isinstance(component.get("operators"), list)
            for component in components
        )
        or not isinstance(operator_claims, dict)
        or any(
            not isinstance(operator_claims.get(field), bool)
            for field in RESUME_MEMO_OPERATOR_FLAG_FIELDS
        )
        or not isinstance(observed_metrics, dict)
        or not observed_metrics
    ):
        raise _resume_prompt_error("resume fact lock is invalid")
    fact_lock = {
        "memo_schema": (
            "mechanism_conditioned"
            if "mathematical_object_mapping" in answer_form
            else "legacy_state_process"
        ),
        "formula": formula,
        "formula_component_identity": [
            {
                "component_id": component["component_id"],
                "formula_subexpression": component["formula_subexpression"],
                "operators": component["operators"],
            }
            for component in components
        ],
        "formula_features": formula_features,
        "observed_metrics": observed_metrics,
        "operator_presence_flags": {
            field: operator_claims[field]
            for field in RESUME_MEMO_OPERATOR_FLAG_FIELDS
        },
        "revision_context": revision_context,
        "source_refs": source_refs,
    }
    _validate_resume_fact_lock_shape(fact_lock)
    serialized = json.dumps(
        fact_lock,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(serialized) > RESUME_FACT_LOCK_MAX_BYTES:
        raise _resume_prompt_error("resume fact lock exceeds byte budget")
    return fact_lock


def _build_agent_resume_prompt(
    job: ResearchJob,
    *,
    worktree: Path,
    workspace: Path,
    task: AgentResumeTask,
    execution_mode: str,
) -> str:
    expected_identity = (
        task.job_id == job.job_id
        and task.factor_id == job.factor_id
        and task.research_id == job.research_id
        and task.report_id == job.report_id
    )
    if (
        task.version != "factorforge_console_resume_task_v1"
        or not expected_identity
        or task.pause_kind != "main_agent_mechanism_memo"
        or task.pause_token
        not in {
            "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
            "AWAITING_MAIN_AGENT_MECHANISM_MEMO_REVISION",
        }
        or task.resume_start_step != "6"
        or task.session_policy != "fresh_phase_agent"
    ):
        raise RuntimeError(
            "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID: mechanism resume task is invalid"
        )
    read_list = "\n".join(
        f"- {workspace / relative}" for relative in task.read_only_inputs
    )
    model_families = ", ".join(task.allowed_model_families)
    fact_lock = _build_resume_prompt_fact_lock(workspace, task)
    uses_mechanism_conditioned_schema = (
        fact_lock.get("memo_schema") == "mechanism_conditioned"
    )
    object_mapping_field = (
        "mathematical_object_mapping"
        if uses_mechanism_conditioned_schema
        else "formula_state_estimator"
    )
    object_qa_field = (
        "mathematical_object_answer"
        if uses_mechanism_conditioned_schema
        else "formula_state_answer"
    )
    observation_qa_field = (
        "observation_mapping_answer"
        if uses_mechanism_conditioned_schema
        else "estimator_mapping_answer"
    )
    fact_lock_json = json.dumps(
        fact_lock,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    formula_features = fact_lock["formula_features"]
    formula_specific_tokens_json = json.dumps(
        sorted(
            formula_specific_qa_terms(
                fact_lock["formula"],
                operators=formula_features.get("operators"),
                fields=formula_features.get("fields"),
            )
        ),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    if uses_mechanism_conditioned_schema:
        math_contract_rules = f"""5. Complete the mechanism-conditioned mathematical contract with these exact structural rules:
   - `math_hypothesis.mathematical_object` must name the object selected from the economic hypothesis. It may be a DCF or residual-income functional, accounting identity, stochastic/path object, spectral component, causal estimand, optimization object, or another justified construction. Do not invent a stochastic state when the hypothesis does not require one.
   - `math_hypothesis.mechanism_equation_or_functional` must contain an explicit model equation, identity, functional, structural equation, or optimization problem. A prose restatement of formula operators is not a model.
   - `math_hypothesis.target_functional` must state the mechanism's actual estimand. For a valuation hypothesis this may be intrinsic value or `V_t/P_t-1`; it is not required to be a conditional-return distribution.
   - `math_hypothesis.market_outcome_projection` must separately map that estimand to this Pilot's executable payoff and legal timing: `E[close_{{i,t+2}}/close_{{i,t+1}}-1 | F_t, measured_object_{{i,t}}]`, entry t+1 close and exit t+2 close, with the predicted sign stated explicitly. Never put future fields in the conditioning information set.
   - Put the formula or code observation equation in `math_hypothesis.observation_mapping` and `{object_mapping_field}.observation_mapping`; bind `{object_mapping_field}.mathematical_object` to the same selected object.
   - Fill both `math_hypothesis.expected_metric_signature` and the top-level `expected_metric_signature` as identical JSON objects. Preserve and fill every scaffolded key: `rank_ic`, `long_side`, `cost_adjusted`, `monotonicity`, and `turnover`. Each value must compare the model's expected sign or shape with the immutable observed metrics, including any contradiction; do not substitute differently named threshold keys.
   - Fill the top-level `falsification_tests` as a JSON list with at least two formula-specific, empirically decidable tests. Every list item must be one non-empty plain JSON string."""
    else:
        math_contract_rules = """5. Complete the legacy-compatible mathematical contract with these exact structural rules:
   - `math_hypothesis.process_or_distribution` must contain an explicit model equation using `=` and explain the formula-specific mathematical object. For valuation, accounting, causal, spectral, functional, graph, or optimization mechanisms, write the relevant identity, functional, structural equation, or optimization problem rather than inventing a stochastic process.
   - `math_hypothesis.target_functional` must use this Pilot's executable payoff and legal information-set form: `E[close_{i,t+2}/close_{i,t+1}-1 | F_t, formula_state_{i,t}], entry t+1 close, exit t+2 close`.
     The conditioning side may contain only legal current-time information; never put
     an assignment, formula expression, operator, future field, or prose inside the expectation brackets.
   - Put the formula-to-state equality in `formula_as_estimator` and `formula_state_estimator.observable_mapping`.
   - Fill both expected-metric-signature objects identically and provide at least two top-level falsification-test strings."""
    if execution_mode == "container":
        rehydration_notice = """After delivery, the Host starts from the hash-bound
answer form and overlays only the allowlisted research fields in your patch.
The Host supplies every machine-owned identity, formula, source reference,
observed metric, operator-presence flag, timestamp, and permission flag. This
does not alter or fill any research claim, and every agent-owned field remains
subject to formal validation."""
        delivery_step = f"""1. Build the research-field patch from
   `{workspace / task.answer_form_relative}` in reasoning only. The phase
   workspace is read-only and no research file may be written by the agent.
   Return exactly one minified JSON object, without Markdown fences or any text
   before or after it, using this envelope:
   `{{"status":"MEMO_DRAFT_COMPLETE","memo":{{...research-field patch...}},"ledger":"..."}}`.
   The `memo` patch may contain only these top-level fields:
   `producer`, `agent_authorship`, `mechanism_qa`, `economic_hypothesis`,
   `math_hypothesis`, `math_model_selection`, `payer`,
	   `{object_mapping_field}`, `expected_metric_signature`,
   `falsification_tests`, `council_questions`, `formula_component_map`,
   `evidence_comparison`, and `operator_claim_consistency`.
   In `formula_component_map`, include only `observable_estimator`,
   `economic_state`, `mathematical_object`, `expected_role`, and `metric_link`
   for each canonical component, in canonical order. You may additionally copy
   that component's exact canonical `component_id` as a transport anchor; the
   Host rejects any mismatch and never takes identity from the patch. In
   `evidence_comparison`,
   include only `mechanism_supported`, `contradictions`,
   `revision_implications`, and `kill_criteria_triggered`:
   `mechanism_supported` must be one non-empty string, while the other three
   fields must each be JSON arrays (possibly empty) of non-empty strings, never
   scalar strings. In
   `operator_claim_consistency`, include exactly
   `claims_correlation_or_covariance`,
   `claims_dependence_without_operator_justification`,
   `explicit_dependence_justification`, `sign_threshold_discussion_present`,
   `volume_ratio_participation_discussion_present`, and
   `additive_scale_commensurability_discussion_present`; omit all
   formula/operator-presence flags. Every listed patch field is required; do
   not omit an empty list or a false boolean. Never include machine-owned fields
   such as identity, timestamps, source refs, formula syntax, observed metrics,
   component identities/operators, permission flags, or contract version,
   except for the optional exact `component_id` transport anchor above.
	   Set `{object_mapping_field}.component_links` to a non-empty, unique JSON
   list of canonical `component_id` strings from the answer form; never use
   objects, subexpressions, operators, or invented component IDs there.
   JSON-escape every quote, backslash, and line break inside string values.
   Serialize the top-level object exactly once: after the ledger's closing
   quote, emit one closing `}}` and stop; never repeat the final `"}}` pair.
   The Host parses the terminal envelope, validates it, and performs the only
   permitted artifact write to `{workspace / task.required_output_relative}`."""
        immutable_step = """2. Do not copy machine-owned values into the patch. Use the
   Host-pinned fact lock for reasoning and cite exact metric keys and values
   only where needed in research prose. The Host alone reconstructs identity,
   source refs, formula syntax, observed metrics, component
   IDs/subexpressions/operators, and formula/operator-presence flags from the
   answer form."""
        budget_instruction = f"""Keep the research patch below {RESUME_MEMO_AGENT_PATCH_TARGET_BYTES:,} UTF-8 bytes
   and the reconstructed memo below 22,000 UTF-8 bytes; the Host hard-blocks
   the patch at 16,000 bytes and the memo at 24,000 bytes. Use compact
   formula-specific prose and never paste the observed-metrics object."""
        ledger_step = """7. Put a concise execution record under 1,600 characters in the envelope's
   `ledger` string. Do not include secrets or absolute paths."""
        exit_step = """8. Before returning, check the completed memo once in reasoning for identity,
   required fields, exact immutable metrics, operator consistency, and byte
   budget. Then return the single terminal JSON envelope and exit. Do not call
   a write or edit tool, do not attempt a correction turn, and do not run any
   command or validator. The Host runs the pinned formal validator after your
   clean exit."""
        modification_boundary = """Do not modify the contract, facts packet, answer form,
   questionnaire, factor spec/case/evaluation, Ultimate proof, plan, data,
   knowledge, or any file."""
    else:
        rehydration_notice = """The shared-gateway development path does not
rehydrate immutable fields. Preserve every locked value literally in the
written memo; any omission or change blocks formal validation."""
        delivery_step = f"""1. Copy `{workspace / task.answer_form_relative}` to
   `{workspace / task.required_output_relative}`. Write only the required memo
   and `identity/web_execution_ledger.md`; do not probe other paths, create
   sibling temporary files, or retry a failed write more than once."""
        immutable_step = """2. Preserve `resume_attempt_id`, identity, source refs,
   formula syntax, observed metrics, component IDs/subexpressions/operators,
   and formula/operator-presence flags exactly. The answer form is the sole
   source of truth for every immutable value. Preserve `source_refs` as its
   exact string-valued JSON object; never replace it with provenance objects or
   SHA256 records from the facts packet."""
        budget_instruction = """Keep the completed memo below 22,000 UTF-8 bytes;
   the Host hard-blocks it at 24,000 bytes. Use compact formula-specific prose
   and do not duplicate the observed-metrics object outside its canonical
   field."""
        ledger_step = """7. Update `identity/web_execution_ledger.md` with a concise record under
   1,600 characters. Do not include secrets or absolute paths."""
        exit_step = """8. Build the complete memo in reasoning, then use exactly one write call for
   the memo and exactly one write call for the ledger. Do not edit or read either
   generated file afterward and do not run any command or validator. The Host
   runs the pinned formal validator after your clean exit. Return exactly
   `MEMO_DRAFT_COMPLETE` with no summary or further tool call, then exit."""
        modification_boundary = """Do not modify the contract, facts packet, answer form,
   questionnaire, factor spec/case/evaluation, Ultimate proof, plan, data,
   knowledge, or any file outside the required memo and
   `identity/web_execution_ledger.md`."""
    return f"""# Factor Forge Step6 Mechanism Resume Task

You are the sole mechanism researcher for one Host-verified Step6 pause. This
is not initial idea authoring, plan generation, data preparation, backtesting,
Council dispatch, or Ultimate execution.

## Immutable resume identity

- attempt_id: {task.attempt_id}
- job_id: {task.job_id}
- factor_id: {task.factor_id}
- research_id: {task.research_id}
- report_id: {task.report_id}
- pause_token: {task.pause_token}
- host_resume_start_step: {task.resume_start_step}
- session_policy: {task.session_policy}
- engine worktree: {worktree}
- active factor workspace: {workspace}

## Research question

- title: {job.request.title}
- submitted hypothesis: {job.request.hypothesis}
- universe: {job.request.universe}
- formal sample: {job.request.sample_start} through {job.request.sample_end}
- forward horizon: {job.request.forward_horizon}
- transaction cost assumption: {job.request.transaction_cost_bps} bps

Read only the Host-authorized research inputs below:

- {workspace / task.contract_relative}
{read_list}

The mechanism facts packet contains only formula syntax, legal evaluation
semantics, coverage, and validated Step4/5 metrics. The structural answer form
contains the same immutable facts and blank research fields. Neither contains
an accepted economic or mathematical interpretation. The Host also protects
upstream audit artifacts, including the deterministic questionnaire and full
factor artifacts, but those are not authorized research inputs: do not read or
quote them.

## Host-pinned fact lock

The Host inserted the following verified JSON directly into this task. It is
authoritative even when the title or submitted hypothesis suggests a richer
formula. Do not rely on a tool call to acquire these facts, and do not add,
remove, round, reinterpret, or replace any locked value.

```json
{fact_lock_json}
```

The final memo must preserve every corresponding locked value exactly. A field,
operator, threshold, interaction, hinge, rank, or ratio absent from this lock is
not part of the implemented formula. If the submitted economic idea needs a
component absent from the exact formula, identify that implementation mismatch
explicitly and treat it as a falsifier or kill criterion; never invent the
missing component.

When `revision_context.mode` is `revision`, every listed failure is a hard
rejection from the previous formal Step6 attempt. Resolve each failure with a
materially more specific derivation. Renaming the same generic payer, repeating
formula tokens, or paraphrasing the rejected answer is another failure.

{rehydration_notice}

## Required deliverable

{delivery_step}
{immutable_step}
3. Independently fill every blank research field. Set `producer` to
   `current_main_agent`; set authoring mode to `current_agent_freeform`, role to
   `main_agent`, and `answered_without_deterministic_template` to `true`.
4. Answer all eight `mechanism_qa` questions with formula-specific reasoning.
   Derive the mechanism-specific mathematical object, legal information set,
   selected valuation, accounting, structural, stochastic, functional or other
   model, target functional, observable estimator, payoff sign and horizon,
   concrete payer, necessary market structure, component ablations, observed
   metric reconciliation, costs, monotonicity, turnover, kill criteria, and at
   least two falsifiers. An explanation that ignores contradictory metrics is
   invalid. Name concrete counterparties and formula observables; do not use
   canned shorthand such as "investors", "market participants", "generic
   payer", "the factor captures alpha", "signed price state", "volume
   participation gate", or "liquidity or turnover shock". Keep each answer
   between 100 and 260 characters. {budget_instruction} Concision must not omit
   contradictory observed metrics from the reasoning.
   For both `mechanism_qa.{object_qa_field}` and
   `mechanism_qa.{observation_qa_field}`, each answer independently must
   literally include at least one exact accepted token from this Host-derived
   JSON list: `{formula_specific_tokens_json}`. The Host lowercases each answer
   and applies a literal substring match. Aliases such as `G`, `R`, or `J` do
   not count unless the same answer also contains an exact listed token;
   satisfying one answer does not satisfy the other.
{math_contract_rules}
6. Select both coarse model-family routing fields from: {model_families}.
   These coarse labels do not constrain the open mathematical-tool selection;
   use `other` when no label faithfully represents the actual model, and write
   the actual mathematical object and equation in the mechanism fields. Update the
   operator-consistency discussion flags only after the memo actually contains
   the corresponding discussion. For every `formula_component_map` item,
   `observable_estimator` must explain how that exact formula subexpression
       estimates its stated economic or mathematical object; it must not describe IC,
   regressions, quantile tests, costs, or the whole-factor backtest. RankIC and
   PearsonIC are evaluation statistics, not correlation/covariance operators
   in the factor formula. If the immutable operator list contains none of
   `correlation`, `covariance`, `corr`, or `cov`, do not write any of those
   words, their plurals, or their derived forms in any research field, even to
   state their absence. Set the corresponding flags to `false` and refer to
   observed `rank_ic` and `pearson_ic` metrics by those exact names instead.
   Select the same economic model family in both model-family fields. When the
   economic object is temporary price impact with a stable decay equation,
   select `transient_impact` even though its representation is stochastic;
   formula-specific drift, volatility, or regime models may still use
   `stochastic_process`. Write multi-equation structural models as separate
   semicolon-delimited equations and include an equation binding the formula's
   actual observable state to the model components; a generic price equation
   alone is insufficient.
   If the Host-pinned operator facts set `has_sign_or_threshold` to `true`, the
   memo must determine from the exact expression whether the branch is
   economically active and discontinuous. State the exact zero/tie convention
   and, when the boundary is active, its bucket or rank instability and
   turnover consequences; if the branches are equivalent or continuous,
   explain why those effects are absent. Only then set
   `sign_threshold_discussion_present` to `true`. If `has_volume_ratio` is
   `true`, identify the ratio's numerator, denominator, and window, then decide
   from the exact expression whether it is a non-negative scale, a signed
   estimator, or a direction-setting interaction. Do not infer its sign role
   from the Host flag alone. Only then set
   `volume_ratio_participation_discussion_present` to `true`.
{ledger_step}
{exit_step} {modification_boundary} Do not run the materializer, any Step script or
   validator, Council, Ultimate, custom Python, data access, network probes,
   credential inspection, or environment enumeration. Never claim a factor
   verdict; the Host resumes formal Step6 and Council after your process exits.
"""


def build_agent_session_key(
    job: ResearchJob,
    agent_id: str,
    *,
    resume: bool,
    resume_task: AgentResumeTask | None = None,
) -> str:
    if resume:
        if resume_task is None or resume_task.session_policy != "fresh_phase_agent":
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID: fresh resume phase is required"
            )
        return f"agent:{agent_id}:{job.job_id}:{resume_task.attempt_id}"
    if resume_task is not None:
        raise RuntimeError(
            "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID: fresh session cannot carry resume task"
        )
    return job.agent_session_key or f"agent:{agent_id}:{job.job_id}"


def redact_secrets(text: str, *, extra_values: tuple[str, ...] = ()) -> str:
    value = text or ""
    secret_values = []
    for key, raw in os.environ.items():
        upper = key.upper()
        if any(token in upper for token in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and len(raw) >= 8:
            secret_values.append(raw)
    value = redact_secret_values(
        value,
        (*secret_values, *extra_values),
        replacement="[REDACTED]",
    )
    patterns = (
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+", r"\1[REDACTED]"),
        (
            r"(?i)((?:api[-_]?key|aws_secret_access_key|aws_session_token)[\"']?\s*[:=]\s*[\"']?)[^\s\"']+",
            r"\1[REDACTED]",
        ),
        (r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED]"),
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]"),
    )
    for pattern, replacement in patterns:
        value = re.sub(pattern, replacement, value)
    return value


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)


def validate_auth_database(
    path: Path | None,
    *,
    provider: str,
    label: str,
    expected_key: str | None = None,
) -> str:
    if path is None or path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} is missing or not a regular file")
    metadata = path.stat()
    if metadata.st_mode & 0o077 or metadata.st_uid != os.geteuid():
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} permissions are too broad")
    current = path.parent
    while current != current.parent:
        if current.is_symlink():
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has a symlink ancestor")
        current = current.parent
    for suffix in ("-wal", "-shm"):
        if Path(f"{path}{suffix}").exists() or Path(f"{path}{suffix}").is_symlink():
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has SQLite sidecars")
    try:
        with sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True) as connection:
            row = connection.execute(
                "SELECT store_json FROM auth_profile_store WHERE store_key = 'primary'"
            ).fetchone()
        payload = json.loads(str(row[0])) if row else {}
        profiles = payload.get("profiles") or {}
    except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} is unreadable") from exc
    if not isinstance(profiles, dict) or len(profiles) != 1:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} must contain exactly one auth profile")
    profile = next(iter(profiles.values()))
    if not isinstance(profile, dict):
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has invalid auth data")
    if profile.get("provider") != provider or profile.get("type") != "api_key":
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} must contain only a portable {provider} API key"
        )
    if not isinstance(profile.get("key"), str) or len(profile["key"]) < 8:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has an invalid API key")
    if expected_key is not None and not secrets.compare_digest(profile["key"], expected_key):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} is not bound to the model broker"
        )
    return profile["key"]


def copy_auth_database(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: auth copy destination already exists")
    try:
        with sqlite3.connect(f"{source.as_uri()}?mode=ro&immutable=1", uri=True) as source_db:
            with sqlite3.connect(destination) as destination_db:
                source_db.backup(destination_db)
    except sqlite3.Error as exc:
        raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: auth database copy failed") from exc
