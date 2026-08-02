from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.models import ResearchJob
from factor_factory.console.secret_safety import redact_secret_values
from factor_factory.console.store import utc_now
from factor_factory.console.web_research_plan import write_text_atomic


BLOCK_AGENT_RUNTIME_UNAVAILABLE = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE"
BLOCK_AGENT_RUNTIME_FAILED = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED"
BLOCK_AGENT_RUNTIME_TIMEOUT = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_TIMEOUT"


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


class ResearchAgentAdapter(Protocol):
    def validate_ready(self) -> str:
        ...

    def run(self, job: ResearchJob, *, worktree: Path, workspace: Path, resume: bool) -> AgentRunResult:
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

    def run(self, job: ResearchJob, *, worktree: Path, workspace: Path, resume: bool) -> AgentRunResult:
        agent_id = job.agent_id or f"factorforge-web-{job.job_id.removeprefix('job_')}"
        session_key = job.agent_session_key or f"agent:{agent_id}:{job.job_id}"
        prompt_path = workspace / "identity" / ("web_agent_resume.md" if resume else "web_agent_task.md")
        write_text_atomic(
            prompt_path,
            build_agent_prompt(job, worktree=worktree, workspace=workspace, config=self.config, resume=resume),
            root=workspace,
        )
        started = utc_now()
        if not resume or not job.agent_id:
            self._ensure_agent(agent_id, workspace, job.request.model or self.config.openclaw_model)
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
            self.config.openclaw_thinking,
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
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
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
            finished_at_utc=str(payload["finished_at_utc"]),
            stdout_tail=str(payload["stdout_tail"]),
            stderr_tail=str(payload["stderr_tail"]),
            result_path=str(result_path),
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
) -> str:
    catalogs = "- `identity/data_catalog_summary.json` (operator-authored, read-only projection)"
    action = "Resume the existing formal run from its current verified pause." if resume else "Start a new formal run from the submitted natural-language hypothesis."
    return f"""# Factor Forge Web Research Task

You are the sole runtime researcher for one isolated Factor Forge task. {action}

## Immutable identity

- job_id: {job.job_id}
- factor_id: {job.factor_id}
- research_id: {job.research_id}
- report_id: {job.report_id}
- engine worktree: {worktree}
- active factor workspace: {workspace}

The operator has already projected the installed Ultimate, Researcher and
Research Brain contracts into this task-local runtime packet. Read only these
six files before acting:

- {workspace / 'identity' / 'web_research_runtime.md'}
- {workspace / 'identity' / 'web_research_request.json'}
- {workspace / 'identity' / 'data_catalog_summary.json'}
- {workspace / 'identity' / 'factor_knowledge_summary.json'}
- {workspace / 'identity' / 'web_research_authoring_contract.json'}
- {workspace / 'identity' / 'web_research_plan.json'}

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
4. Do not run `run_factorforge_ultimate_loop.py`, the materializer, Step scripts, or `scripts/run_factorforge_ultimate.py`. Fill the task-local web research plan with a Formula IR-compatible factor law, or on resume write only the artifact required by the named pause. Do not author or execute custom Python. On a fresh run, execute only the authoring preflight command printed in `web_research_runtime.md`, correct named plan fields until it returns PASS, and then exit. The host exclusively materializes and runs formal Step3 through Step6 after your process exits.
5. Never use fixtures, deterministic fallback, local mock, smoke evidence or dry-run output as formal research proof. A missing dataset must produce a precise BLOCK/data request, not invented evidence.
6. On resume, write only the exact named research memo permitted by the current pause. The host owns Council dispatch, synthesis, evidence interpretation, and every formal wrapper invocation. Do not use the unimplemented `real_agent`/`remote_api` wrapper adapters.
7. Keep preferred, null and alternative hypotheses distinct. Record economic payer, mathematical object, legal information set, falsifiers, component ablations, costs, long-side economics, IS/OOS boundary and proof-certificate status.
8. A process exit code or wrapper PASS is not a factor verdict. Finish only with formal ACCEPT, REJECT, BLOCK, or an honest REVIEW_REQUIRED pause.
9. Do not create a revision child or record human approval unless an existing artifact under `identity/` explicitly authorizes this resume. Automated action must never be labeled human approval.
10. Before finishing, verify the workspace manifest and inspect Git status. Any write outside the active workspace is a blocking failure.
11. Network egress is restricted to the fixed model broker. Do not attempt to reach S3, Data API, catalog storage, raw data, arbitrary websites, or any other network destination, and do not attempt to bypass the proxy.
12. The runtime has already completed operator-owned model, network, credential and Data API readiness checks. Never enumerate environment variables or credential material; never run `env`/`printenv`, read `/proc/*/environ`, query instance metadata, inspect AWS credential/config files, or inspect the OpenClaw auth database. Never print, hash, transform, persist or return any API key, access key, session token, password or broker token. If credentials appear unexpectedly, stop and record a BLOCK without reproducing them.
13. Do not replace formal execution with ad hoc environment, package-source, credential or network probes. Begin from the task-local runtime packet and stop after the research plan or named resume artifact is complete; the Host alone uses the Data API through its public interface and pinned catalog after agent authoring exits.
14. Do not recursively dump documents or inspect internal schemas. After reading the six packet files, write a concise execution ledger of at most 4,000 characters to `identity/web_execution_ledger.md`, then complete the plan or pause artifact. The read-only authoring contract and preflight output are sufficient to correct plan syntax; do not inspect validator source.

The host derives authoring status from the validated plan, execution ledger and private
agent-run receipt. Do not create a separate completion-status artifact or claim that formal
research ran. On a fresh run, exit only after the plan is complete and its preflight returns
PASS; on resume, exit after the exact permitted pause artifact is complete. Do not include
secrets or absolute paths in the execution ledger.
"""


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
