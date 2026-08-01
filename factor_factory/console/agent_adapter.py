from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from factor_factory.console.config import ConsoleConfig
from factor_factory.console.models import ResearchJob
from factor_factory.console.store import utc_now


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


class OpenClawResearchAgentAdapter:
    def __init__(self, config: ConsoleConfig) -> None:
        self.config = config

    def validate_ready(self) -> str:
        if not self.config.openclaw_profile:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: a dedicated OpenClaw profile is required")
        self._validate_auth_database(self.config.openclaw_auth_seed_db, label="credential seed")
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

    def run(self, job: ResearchJob, *, worktree: Path, workspace: Path, resume: bool) -> AgentRunResult:
        agent_id = job.agent_id or f"factorforge-web-{job.job_id.removeprefix('job_')}"
        session_key = job.agent_session_key or f"agent:{agent_id}:{job.job_id}"
        prompt_path = workspace / "identity" / ("web_agent_resume.md" if resume else "web_agent_task.md")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(
            build_agent_prompt(job, worktree=worktree, workspace=workspace, config=self.config, resume=resume),
            encoding="utf-8",
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

    def _install_auth_seed(self, agent_state: Path) -> None:
        destination = agent_state / "openclaw-agent.sqlite"
        if destination.exists():
            self._validate_auth_database(destination, label="agent credential store")
            return
        seed = self.config.openclaw_auth_seed_db
        self._validate_auth_database(seed, label="credential seed")
        assert seed is not None
        temp = agent_state / f".openclaw-agent.sqlite.seed-{os.getpid()}"
        shutil.copy2(seed, temp)
        temp.chmod(0o600)
        temp.replace(destination)

    def _validate_auth_database(self, path: Path | None, *, label: str) -> None:
        if path is None or not path.is_file():
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} is missing")
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                row = connection.execute(
                    "SELECT store_json FROM auth_profile_store WHERE store_key = 'primary'"
                ).fetchone()
            payload = json.loads(str(row[0])) if row else {}
            profiles = payload.get("profiles") or {}
        except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} is unreadable") from exc
        if not isinstance(profiles, dict) or not profiles:
            raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has no auth profile")
        expected_provider = self.config.openclaw_auth_provider
        for profile in profiles.values():
            if not isinstance(profile, dict):
                raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has invalid auth data")
            if profile.get("provider") != expected_provider or profile.get("type") != "api_key":
                raise RuntimeError(
                    f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} must contain only portable {expected_provider} API keys"
                )
            if not isinstance(profile.get("key"), str) or len(profile["key"]) < 8:
                raise RuntimeError(f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: {label} has an invalid API key")

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
    catalogs = "\n".join(f"- {path}" for path in config.data_catalogs) or "- use the configured Data API catalog"
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

Read and follow these skills literally before acting:

- {worktree / 'skills' / 'factor-forge-ultimate' / 'SKILL.md'}
- {worktree / 'skills' / 'factor-forge-researcher' / 'SKILL.md'}
- {worktree / 'skills' / 'factor-forge-research-brain' / 'SKILL.md'}

## Submitted research object

- title: {job.request.title}
- hypothesis: {job.request.hypothesis}
- universe: {job.request.universe}
- formal sample: {job.request.sample_start} through {job.request.sample_end}
- forward horizon: {job.request.forward_horizon}
- transaction cost assumption: {job.request.transaction_cost_bps} bps
- source URL: {job.request.source_url or 'none; this is a user-authored natural-language hypothesis'}

## Read-only Data API inputs

{catalogs}

## Mandatory execution contract

1. Treat this as a natural_language_hypothesis, never as a broker report and never invent attribution.
2. All factor-specific code, notes, raw model responses, metrics, Council packets, knowledge and results must stay under the exact active factor workspace above.
3. Do not write to another factor_research directory, repo-root knowledge, repo-root data, shared clean data, another worktree, or any cloud dataset. Data API and catalogs are read-only inputs.
4. Do not run `run_factorforge_ultimate_loop.py`. Author the semantic Step1/Step2 and research-protocol artifacts as the current agent, validate them, then use only `scripts/run_factorforge_ultimate.py` for formal Step3 through Step6.
5. Never use fixtures, deterministic fallback, local mock, smoke evidence or dry-run output as formal research proof. A missing dataset must produce a precise BLOCK/data request, not invented evidence.
6. Resolve Ultimate pause states yourself where the installed skill permits: mechanism memo, independent Council role packets, Council synthesis and evidence interpretation. Do not use the unimplemented `real_agent`/`remote_api` wrapper adapters.
7. Keep preferred, null and alternative hypotheses distinct. Record economic payer, mathematical object, legal information set, falsifiers, component ablations, costs, long-side economics, IS/OOS boundary and proof-certificate status.
8. A process exit code or wrapper PASS is not a factor verdict. Finish only with formal ACCEPT, REJECT, BLOCK, or an honest REVIEW_REQUIRED pause.
9. Do not create a revision child or record human approval unless an existing artifact under `identity/` explicitly authorizes this resume. Automated action must never be labeled human approval.
10. Before finishing, verify the workspace manifest and inspect Git status. Any write outside the active workspace is a blocking failure.

Write a final machine-readable record to:

`{workspace / 'identity' / 'web_agent_completion.json'}`

It must contain `version=factorforge_web_agent_completion_v1`, all immutable identity fields, `execution_status`, `protocol_status`, `factor_verdict`, `council_status`, `formal_proof_eligible`, `summary`, `blockers`, `next_actions`, and relative artifact paths. Do not include secrets or absolute paths in that record.
"""


def redact_secrets(text: str) -> str:
    value = text or ""
    secret_values = []
    for key, raw in os.environ.items():
        upper = key.upper()
        if any(token in upper for token in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and len(raw) >= 8:
            secret_values.append(raw)
    for raw in sorted(secret_values, key=len, reverse=True):
        value = value.replace(raw, "[REDACTED]")
    patterns = (
        r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+",
        r"(?i)(api[-_]?key[\"']?\s*[:=]\s*[\"'])[^\"']+",
        r"\bsk-[A-Za-z0-9_-]{12,}\b",
    )
    for pattern in patterns:
        value = re.sub(pattern, r"\1[REDACTED]" if "(" in pattern else "[REDACTED]", value)
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
