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
BLOCK_AGENT_ORPHANED_WRITER = "BLOCK_FACTORFORGE_CONSOLE_AGENT_ORPHANED_WRITER"
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
        if resume or not job.agent_id:
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
        workspace / "identity" / "web_research_plan.json",
    ]
    packet_list = "\n".join(f"- {path}" for path in dict.fromkeys(packet_files))
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
14. Do not recursively dump documents or inspect internal schemas. After reading the six packet files, write a concise execution ledger of at most 4,000 characters to `identity/web_execution_ledger.md`, then complete the plan or pause artifact. The read-only authoring contract and preflight output are sufficient to correct plan syntax; do not inspect validator source.

The host derives authoring status from the validated plan, execution ledger and private
agent-run receipt. Do not create a separate completion-status artifact or claim that formal
research ran. On a fresh run, exit only after the plan is complete and its preflight returns
PASS; on resume, exit after the exact permitted pause artifact is complete. Do not include
secrets or absolute paths in the execution ledger.
"""


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
        or task.pause_token != "AWAITING_MAIN_AGENT_MECHANISM_MEMO"
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
    if execution_mode == "container":
        delivery_step = f"""1. Build the completed memo from
   `{workspace / task.answer_form_relative}` in reasoning only. The phase
   workspace is read-only and no research file may be written by the agent.
   Return exactly one minified JSON object, without Markdown fences or any text
   before or after it, using this envelope:
   `{{"status":"MEMO_DRAFT_COMPLETE","memo":{{...completed answer form...}},"ledger":"..."}}`.
   JSON-escape every quote, backslash, and line break inside string values.
   Serialize the top-level object exactly once: after the ledger's closing
   quote, emit one closing `}}` and stop; never repeat the final `"}}` pair.
   The Host parses the terminal envelope, validates it, and performs the only
   permitted artifact write to `{workspace / task.required_output_relative}`."""
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
        delivery_step = f"""1. Copy `{workspace / task.answer_form_relative}` to
   `{workspace / task.required_output_relative}`. Write only the required memo
   and `identity/web_execution_ledger.md`; do not probe other paths, create
   sibling temporary files, or retry a failed write more than once."""
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

## Required deliverable

{delivery_step}
2. Preserve `resume_attempt_id`, identity, source refs, formula syntax,
   observed metrics, component IDs/subexpressions/operators, and
   formula/operator-presence flags exactly. The answer form is the sole source
   of truth for every immutable value. In particular, preserve `source_refs`
   as the answer form's exact string-valued JSON object. The facts packet's
   `source_artifacts` objects and SHA256 values are provenance evidence only;
   never copy, merge, or substitute them into `source_refs`.
3. Independently fill every blank research field. Set `producer` to
   `current_main_agent`; set authoring mode to `current_agent_freeform`, role to
   `main_agent`, and `answered_without_deterministic_template` to `true`.
4. Answer all eight `mechanism_qa` questions with formula-specific reasoning.
   Derive the random object, legal information set, stochastic or structural
   model, target functional, observable estimator, payoff sign and horizon,
   concrete payer, necessary market structure, component ablations, observed
   metric reconciliation, costs, monotonicity, turnover, kill criteria, and at
   least two falsifiers. An explanation that ignores contradictory metrics is
   invalid. Name concrete counterparties and formula observables; do not use
   canned shorthand such as "investors", "market participants", "generic
   payer", "the factor captures alpha", "signed price state", "volume
   participation gate", or "liquidity or turnover shock". Keep each answer
   between 120 and 400 characters. Keep the memo below 18,000 UTF-8 bytes when
   serialized as minified JSON; the Host hard-blocks at 20,000 bytes. The
   existing answer form is already a substantial part of that budget, so use
   compact formula-specific prose and do not repeat immutable facts. Concision
   must not omit contradictory observed metrics.
5. Complete the mathematical contract with these exact structural rules:
   - `math_hypothesis.process_or_distribution` must contain an explicit model
     equation using `=` and explain the formula-specific state, process, or
     distribution. A prose restatement of operators is not a model.
   - `math_hypothesis.target_functional` must name the forward return and legal
     information set in conditional notation, for example
     `E[r_i,t+h | F_t, formula_specific_state_i,t]`, with the actual state and
     horizon substituted.
   - Fill both `math_hypothesis.expected_metric_signature` and the top-level
     `expected_metric_signature` as identical JSON objects. Preserve and fill
     every scaffolded key: `rank_ic`, `long_side`, `cost_adjusted`,
     `monotonicity`, and `turnover`. Each value must compare the model's
     expected sign or shape with the immutable observed metrics, including any
     contradiction; do not substitute differently named threshold keys.
   - Fill the top-level `falsification_tests` as a JSON list with at least two
     formula-specific, empirically decidable tests. Every list item must be one
     non-empty plain JSON string; objects, dictionaries, arrays, or structured
     test records are invalid. A discussion inside `mechanism_qa`,
     `math_hypothesis`, or another nested field does not satisfy this required
     top-level field.
6. Select both model-family fields from: {model_families}. Update the
   operator-consistency discussion flags only after the memo actually contains
   the corresponding discussion. For every `formula_component_map` item,
   `observable_estimator` must explain how that exact formula subexpression
   estimates its stated economic or latent state; it must not describe IC,
   regressions, quantile tests, costs, or the whole-factor backtest. RankIC and
   PearsonIC are evaluation statistics, not correlation/covariance operators
   in the factor formula. If the immutable operator list contains none of
   `correlation`, `covariance`, `corr`, or `cov`, do not write any of those
   words, their plurals, or their derived forms in any research field, even to
   state their absence. Set the corresponding flags to `false` and refer to
   observed `rank_ic` and `pearson_ic` metrics by those exact names instead.
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
