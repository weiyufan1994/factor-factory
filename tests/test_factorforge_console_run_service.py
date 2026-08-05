from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from factor_factory.console.conversation_ledger import (
    CONVERSATION_LEDGER_REFERENCE_FIELD,
)
from factor_factory.console.run_service import ResearchRunService as _ResearchRunService
from factor_factory.console.run_service import (
    _allowed_agent_write_paths,
    _capture_resume_restore_state,
    _configure_host_formal_python_environment,
    _read_agent_resume_artifact_json,
    _restore_resume_workspace,
    _validate_agent_write_boundary as _validate_agent_write_boundary_impl,
    _validate_host_conversation_ledger_binding,
    _workspace_evidence_tree,
    _workspace_file_snapshot,
)
from factor_factory.console.web_research_plan import stable_json_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_WRITE_HOST_ATTESTATION = _ResearchRunService._write_host_attestation
_ORIGINAL_EXECUTE_HOST_FORMAL_PIPELINE = (
    _ResearchRunService._execute_host_formal_pipeline
)
_ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT = (
    _ResearchRunService._validate_trusted_resume_context
)
_ORIGINAL_VALIDATE_HOST_CONVERSATION_LEDGER_BINDING = (
    _validate_host_conversation_ledger_binding
)


def _test_conversation_ledger_binding() -> dict:
    root_sha256 = "c" * 64
    return {
        "version": "factorforge_console_host_conversation_ledger_binding_v1",
        "mode": "initial",
        "request_sha256": "d" * 64,
        "current_checkpoint": {
            "version": "factorforge_console_conversation_ledger_reference_v1",
            "path": f"identity/conversation_ledger/checkpoint__000001__{root_sha256}.json",
            "sha256": "e" * 64,
            "root_sha256": root_sha256,
            "message_count": 1,
        },
        "current_root_sha256": root_sha256,
        "current_message_count": 1,
        "parent_request_sha256": "",
        "parent_checkpoint": None,
        "parent_attestation_id": "",
        "parent_attestation_sha256": "",
        "parent_receipt_id": "",
        "parent_receipt_sha256": "",
    }


@pytest.fixture(autouse=True)
def _stub_materialized_web_contract(monkeypatch):
    import factor_factory.console.run_service as module

    monkeypatch.setattr(
        module,
        "validate_materialized_web_research",
        lambda _workspace: {
            "plan_sha256": "plan-hash",
            "formula_hash": "formula-hash",
            "bootstrap_sha256": "bootstrap-hash",
            "factor_spec_sha256": "factor-spec-hash",
        },
    )
    monkeypatch.setattr(
        module.ResearchRunService,
        "_write_host_attestation",
        lambda self, **_kwargs: "attestations/unit-test.json",
    )
    monkeypatch.setattr(
        module,
        "_validate_agent_write_boundary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        module.ResearchRunService,
        "_execute_host_formal_pipeline",
        lambda self, *_args, **_kwargs: {
            "receipt_id": "jobs/unit/formal-execution/receipt.json",
            "receipt_sha256": "receipt-hash",
            "ultimate_argv_sha256": "ultimate-argv-hash",
            "ultimate_returncode": 0,
        },
    )

    def trusted_resume_stub(
        self,
        job,
        *,
        worktree,
        workspace,
        private_execution_started=False,
    ):
        proof_path = (
            Path(workspace)
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        return {
            "start_step": "6",
            "ultimate_proof_sha256": _file_sha256(proof_path),
            # Mirror the attestation returned by the host stub above. Production
            # resume validation reads this identity from the current pointer.
            "attestation_id": "attestations/unit-test.json",
            "attestation_sha256": "attestation-hash",
            "receipt_id": f"jobs/{job.job_id}/formal-execution/receipt.json",
            "receipt_sha256": "receipt-hash",
            "workspace_evidence_tree_root_sha256": stable_json_hash(
                _workspace_evidence_tree(Path(workspace))
            ),
        }

    monkeypatch.setattr(
        module.ResearchRunService,
        "_validate_trusted_resume_context",
        trusted_resume_stub,
    )
    monkeypatch.setattr(
        module,
        "_validate_host_conversation_ledger_binding",
        lambda **_kwargs: _test_conversation_ledger_binding(),
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _make_source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "factor_factory").mkdir(parents=True)
    (source / "scripts").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "factor_factory" / "__init__.py", source / "factor_factory" / "__init__.py")
    shutil.copy2(
        PROJECT_ROOT / "factor_factory" / "research_workspace.py",
        source / "factor_factory" / "research_workspace.py",
    )
    shutil.copy2(
        PROJECT_ROOT / "scripts" / "init_factor_research_workspace.py",
        source / "scripts" / "init_factor_research_workspace.py",
    )
    shutil.copy2(PROJECT_ROOT / ".gitignore", source / ".gitignore")
    for script_name in (
        "materialize_factorforge_web_research.py",
        "run_factorforge_ultimate.py",
    ):
        shutil.copy2(
            PROJECT_ROOT / "scripts" / script_name,
            source / "scripts" / script_name,
        )
    (source / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(source, "init")
    _git(source, "config", "user.name", "Factor Forge Test")
    _git(source, "config", "user.email", "factor-forge@example.invalid")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "fixture")
    return source


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _TerminalRejectAdapter:
    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        from factor_factory.console.agent_adapter import AgentRunResult

        report_id = job.report_id
        identity = {
            "report_id": report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
        }
        _write_json(
            workspace / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json",
            {
                **identity,
                "status": "PASS",
                "dry_run": False,
                "formal_proof_eligible": True,
                "requested_steps": ["3", "4", "5", "6"],
                "commands": [
                    {"name": name, "returncode": 0, "status": "PASS"}
                    for name in (
                        "run_step3",
                        "validate_step3",
                        "run_step3b",
                        "validate_step3b",
                        "run_step4",
                        "validate_step4",
                        "run_step5",
                        "validate_step5",
                        "run_step6",
                        "validate_step6",
                        "validate_research_protocol_pre_council",
                    )
                ],
                "formal_command_contract": {
                    "required_command_names": [
                        "run_step3",
                        "validate_step3",
                        "run_step3b",
                        "validate_step3b",
                        "run_step4",
                        "validate_step4",
                        "run_step5",
                        "validate_step5",
                        "run_step6",
                        "validate_step6",
                        "validate_research_protocol_pre_council",
                    ],
                    "research_protocol_verifier_required": True,
                    "research_protocol_verifier_name": "validate_research_protocol_pre_council",
                    "satisfied": True,
                },
                "revision_council": {"status": "skipped"},
            },
        )
        _write_json(
            workspace / "objects" / "research_protocol" / f"factor_proof_certificate__{report_id}.json",
            {
                **identity,
                "declared_verdict": "REJECT",
                "formal_proof_eligible": True,
                "metrics": {
                    "rank_ic": {"mean": -0.01},
                    "long_side_after_cost": {"net_return_annual": -0.08},
                    "drawdown": {"max_drawdown": -0.31, "recovery_days": 120},
                },
            },
        )
        _write_json(
            workspace / "objects" / "research_protocol" / f"factor_proof_verifier_report__{report_id}.json",
            {
                **identity,
                "verifier_contract_version": "factorforge_console_bound_factor_proof_verifier_v1",
                "verdict": "REJECT",
                "formal_proof_eligible": True,
                "block_reasons": [],
            },
        )
        council_root = workspace / "objects" / "research_iteration_master" / "revision_council" / report_id
        _write_json(
            council_root / f"revision_council_summary__{report_id}.json",
            {**identity, "status": "PASS"},
        )
        _write_json(
            council_root / f"main_agent_council_synthesis__{report_id}.json",
            {**identity, "status": "PASS", "selected_revision": "reject"},
        )
        _write_json(
            workspace / "objects" / "research_protocol" / f"research_quality_gate__{report_id}.json",
            {
                **identity,
                "status": "ready_for_pre_council_validation",
                "mechanism_claim_level": "component_validated",
                "economic_mechanism_contract": {
                    "preferred_claim": "urgent traders transfer value to patient liquidity suppliers",
                    "payer_candidates": ["urgent traders"],
                },
                "mathematical_object_contract": {
                    "random_object": "conditional opening return",
                    "target_statistic": "conditional expectation",
                    "observation_equation": "Y = h(X) + epsilon",
                },
            },
        )
        _write_json(
            workspace / "objects" / "implementation_plan_master" / f"implementation_plan_master__{report_id}.json",
            {
                **identity,
                "implementation_mode": "direct_code",
                "implementation_status": "ready",
                "entrypoint": "compute_factor",
            },
        )
        result_path = workspace / "identity" / "fake-agent-result.json"
        _write_json(result_path, {**identity, "returncode": 0})
        return AgentRunResult(
            returncode=0,
            agent_id=f"agent-{job.job_id}",
            session_key=f"session-{job.job_id}",
            started_at_utc="2026-08-01T00:00:00Z",
            finished_at_utc="2026-08-01T00:01:00Z",
            stdout_tail="complete",
            stderr_tail="",
            result_path=str(result_path),
        )


class _PausedAdapter:
    def run(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task=None,
    ):
        from factor_factory.console.agent_adapter import AgentRunResult

        report_id = job.report_id
        identity = {"report_id": report_id, "factor_id": job.factor_id, "research_id": job.research_id}
        _write_json(
            workspace / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json",
            {
                **identity,
                "status": "PAUSED",
                "formal_proof_eligible": False,
                "main_agent_mechanism_memo": {
                    "status": "awaiting_main_agent_mechanism_memo",
                    "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
                },
                "revision_council": {
                    "status": "not_reached",
                    "reason": "awaiting_main_agent_mechanism_memo",
                },
            },
        )
        rim = workspace / "objects" / "research_iteration_master"
        questionnaire = rim / f"main_agent_mechanism_questionnaire__{report_id}.json"
        questionnaire_md = rim / f"main_agent_mechanism_questionnaire__{report_id}.md"
        memo = rim / f"main_agent_mechanism_memo__{report_id}.json"
        memo_md = rim / f"main_agent_mechanism_memo__{report_id}.md"
        _write_json(
            questionnaire,
            {
                "contract_version": "factorforge_main_agent_mechanism_questionnaire_v1",
                **identity,
                "formula_facts": {
                    "formula": "divide(minus(close, open), pre_close)",
                    "fields": ["close", "open", "pre_close"],
                    "operators": ["divide", "minus"],
                },
                "metric_facts": {"rank_ic_mean": -0.01},
            },
        )
        questionnaire_md.parent.mkdir(parents=True, exist_ok=True)
        questionnaire_md.write_text("# Questionnaire\n", encoding="utf-8")
        _write_json(
            rim / f"main_agent_mechanism_memo_status__{report_id}.json",
            {
                "report_id": report_id,
                "status": "awaiting_main_agent_mechanism_memo",
                "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
                "questionnaire_ref": {
                    "contract_version": "factorforge_main_agent_mechanism_questionnaire_v1",
                    "json_path": str(questionnaire),
                    "markdown_path": str(questionnaire_md),
                },
                "expected_memo_ref": {
                    "contract_version": "factorforge_main_agent_mechanism_memo_v1",
                    "json_path": str(memo),
                    "markdown_path": str(memo_md),
                },
            },
        )
        _write_json(
            workspace
            / "objects"
            / "factor_spec_master"
            / f"factor_spec_master__{report_id}.json",
            {
                **identity,
                "canonical_spec": {
                    "formula_text": "divide(minus(close, open), pre_close)",
                    "required_inputs": ["close", "open", "pre_close"],
                    "operators": ["divide", "minus"],
                },
            },
        )
        _write_json(
            workspace
            / "objects"
            / "factor_case_master"
            / f"factor_case_master__{report_id}.json",
            {**identity, "headline_metrics": {"rank_ic_mean": -0.01}},
        )
        _write_json(
            workspace
            / "objects"
            / "validation"
            / f"factor_evaluation__{report_id}.json",
            {**identity, "headline_metrics": {"rank_ic_mean": -0.01}},
        )
        _write_json(
            workspace / "objects" / "runtime_context" / f"ultimate_loop_report__{report_id}.json",
            {
                **identity,
                "root_report_id": report_id,
                "status": "PAUSED",
                "final_outcome": "awaiting_agent_results",
            },
        )
        result_path = workspace / "identity" / "fake-agent-result.json"
        _write_json(result_path, {**identity, "returncode": 0})
        return AgentRunResult(
            0,
            f"agent-{job.job_id}",
            f"session-{job.job_id}",
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:01:00Z",
            "paused",
            "",
            str(result_path),
        )


class _EscapingAdapter(_TerminalRejectAdapter):
    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        result = super().run(job, worktree=worktree, workspace=workspace, resume=resume)
        (worktree / "outside-factor-workspace.txt").write_text("pollution\n", encoding="utf-8")
        return result


class _ForgingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        from factor_factory.console.agent_adapter import AgentRunResult

        self.calls += 1
        plan_path = workspace / "identity" / "web_research_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["forged_by_agent"] = True
        _write_json(plan_path, plan)
        (workspace / "identity" / "web_execution_ledger.md").write_text(
            "agent authoring completed\n",
            encoding="utf-8",
        )
        _write_json(
            workspace / "identity" / "web_agent_completion.json",
            {"execution_status": "AUTHORING_COMPLETE"},
        )
        _write_json(
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json",
            {
                "report_id": job.report_id,
                "factor_id": job.factor_id,
                "research_id": job.research_id,
                "status": "PAUSED",
                "failure": None,
            },
        )
        return AgentRunResult(
            returncode=0,
            agent_id=f"agent-{job.job_id}",
            session_key=f"session-{job.job_id}",
            started_at_utc="2026-08-02T00:00:00Z",
            finished_at_utc="2026-08-02T00:01:00Z",
            stdout_tail="forged",
            stderr_tail="",
            result_path=str(workspace / "identity" / "not-written-agent-result.json"),
        )


class _PausedThenForgingAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self._paused = _PausedAdapter()
        self._forging = _ForgingAdapter()

    def run(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task=None,
    ):
        self.calls += 1
        delegate = self._forging if resume else self._paused
        return delegate.run(
            job,
            worktree=worktree,
            workspace=workspace,
            resume=resume,
        )


class _PausedThenMalformedMemoAdapter:
    def __init__(self, state_root: Path, malformed: str) -> None:
        self.state_root = state_root
        self.malformed = malformed
        self.calls = 0
        self._paused = _PausedAdapter()

    def run(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task=None,
    ):
        from factor_factory.console.agent_adapter import AgentRunResult

        self.calls += 1
        if not resume:
            return self._paused.run(
                job,
                worktree=worktree,
                workspace=workspace,
                resume=False,
            )
        assert resume_task is not None
        memo_path = workspace / resume_task.required_output_relative
        memo_path.parent.mkdir(parents=True, exist_ok=True)
        memo_path.write_text(self.malformed, encoding="utf-8")
        (workspace / "identity" / "web_execution_ledger.md").write_text(
            "resume artifact authored\n",
            encoding="utf-8",
        )
        session_key = f"agent:malformed:{resume_task.attempt_id}"
        result_path = (
            self.state_root
            / "jobs"
            / job.job_id
            / f"agent_run_{resume_task.attempt_id}.json"
        )
        _write_json(
            result_path,
            {
                "version": "factorforge_console_agent_run_v1",
                "job_id": job.job_id,
                "factor_id": job.factor_id,
                "research_id": job.research_id,
                "report_id": job.report_id,
                "agent_id": "agent-malformed",
                "session_key_sha256": hashlib.sha256(
                    session_key.encode("utf-8")
                ).hexdigest(),
                "resume": True,
                "resume_attempt_id": resume_task.attempt_id,
                "returncode": 0,
            },
        )
        return AgentRunResult(
            returncode=0,
            agent_id="agent-malformed",
            session_key=session_key,
            started_at_utc="2026-08-02T00:00:00Z",
            finished_at_utc="2026-08-02T00:01:00Z",
            stdout_tail="",
            stderr_tail="",
            result_path=str(result_path),
        )


class _PausedThenResumeFailureAdapter:
    def __init__(self, token: str) -> None:
        self.token = token
        self.calls = 0
        self._paused = _PausedAdapter()

    def run(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task=None,
    ):
        self.calls += 1
        if not resume:
            return self._paused.run(
                job,
                worktree=worktree,
                workspace=workspace,
                resume=False,
            )
        raise RuntimeError(f"{self.token}: injected resume failure")


class _PausedThenNonzeroResumeAdapter:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.calls = 0
        self._paused = _PausedAdapter()

    def run(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task=None,
    ):
        from factor_factory.console.agent_adapter import AgentRunResult

        self.calls += 1
        if not resume:
            return self._paused.run(
                job,
                worktree=worktree,
                workspace=workspace,
                resume=False,
            )
        result_path = self.state_root / "jobs" / job.job_id / "nonzero_resume.json"
        _write_json(result_path, {"returncode": 1})
        return AgentRunResult(
            returncode=1,
            agent_id="agent-nonzero",
            session_key="session-nonzero",
            started_at_utc="2026-08-02T00:00:00Z",
            finished_at_utc="2026-08-02T00:01:00Z",
            stdout_tail="",
            stderr_tail="safe agent failure",
            result_path=str(result_path),
        )


class _CouncilPauseThenLeaseFailureAdapter:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self._paused = _PausedAdapter()
        self.council_ingress_completed = False

    def run(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        resume_task=None,
    ):
        assert not resume
        result = self._paused.run(
            job,
            worktree=worktree,
            workspace=workspace,
            resume=False,
        )
        proof_path = (
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["main_agent_mechanism_memo"] = {"status": "complete"}
        proof["revision_council"] = {
            "status": "awaiting_agent_results",
            "effective_mode": "agentic_dispatch_manifest",
        }
        _write_json(proof_path, proof)

        council_relative = (
            Path("objects")
            / "research_iteration_master"
            / "revision_council"
            / job.report_id
        )
        task_id = "economic_skeptic"
        task_relative = (
            council_relative
            / "agent_tasks"
            / f"task__{job.report_id}__{task_id}.json"
        )
        result_relative = (
            council_relative
            / "agent_results"
            / f"agent_result__{job.report_id}__{task_id}.json"
        )
        expected_agent_identifier = f"console_council_{task_id}"
        _write_json(
            workspace / task_relative,
            {
                "task_packet_version": "factorforge_agentic_council_task_packet_v1",
                "report_id": job.report_id,
                "task_id": task_id,
                "agent_role": "economic_skeptic",
                "expected_agent_identifier": expected_agent_identifier,
                "expected_result_path": result_relative.as_posix(),
                "canonical_write_permission": False,
                "execution_allowed_by_default": False,
                "human_approval_required": True,
            },
        )
        _write_json(
            workspace
            / council_relative
            / f"dispatch_manifest__{job.report_id}.json",
            {
                "dispatch_manifest_version": "factorforge_agentic_council_dispatch_manifest_v1",
                "report_id": job.report_id,
                "status": "awaiting_agent_results",
                "agent_task_count": 1,
                "agent_tasks": [
                    {
                        "required": True,
                        "task_id": task_id,
                        "agent_role": "economic_skeptic",
                        "expected_agent_identifier": expected_agent_identifier,
                        "task_packet_path": task_relative.as_posix(),
                        "task_packet_sha256": _file_sha256(workspace / task_relative),
                        "expected_result_path": result_relative.as_posix(),
                    }
                ],
            },
        )
        return result

    def run_council_ingress(
        self,
        job,
        *,
        worktree: Path,
        workspace: Path,
        tasks,
    ):
        from factor_factory.console.agent_adapter import AgentRunResult

        for task in tasks:
            _write_json(
                workspace / task.expected_result_path,
                {
                    "report_id": job.report_id,
                    "task_id": task.task_id,
                    "agent_role": task.agent_role,
                    "agent_identifier": task.expected_agent_identifier,
                },
            )
        self.council_ingress_completed = True
        result_path = (
            self.state_root
            / "jobs"
            / job.job_id
            / "council_ingress_test.json"
        )
        _write_json(result_path, {"returncode": 0})
        return AgentRunResult(
            returncode=0,
            agent_id=f"agent-{job.job_id}",
            session_key=f"session-{job.job_id}",
            started_at_utc="2026-08-02T00:00:00Z",
            finished_at_utc="2026-08-02T00:01:00Z",
            stdout_tail="council imported",
            stderr_tail="",
            result_path=str(result_path),
        )

    def prepare_host_data_environment(self, job_id: str):
        if self.council_ingress_completed:
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE: "
                "injected post-Council lease failure"
            )
        return {}, ()


class _CredentialEchoAdapter(_TerminalRejectAdapter):
    secret = "temporary-session-value-for-run-service-test"

    def __init__(self) -> None:
        self.cleared = False
        self.deactivated = False

    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        result = super().run(job, worktree=worktree, workspace=workspace, resume=resume)
        quality = (
            workspace
            / "objects"
            / "research_protocol"
            / f"research_quality_gate__{job.report_id}.json"
        )
        payload = json.loads(quality.read_text(encoding="utf-8"))
        payload["economic_mechanism_contract"]["ordinary_note"] = self.secret
        _write_json(quality, payload)
        return result

    def denied_secret_values(self, job_id: str):
        return (self.secret,)

    def clear_denied_secrets(self, job_id: str):
        self.cleared = True

    def deactivate_denied_secrets(self, job_id: str):
        self.deactivated = True


class _EarlyRuntimeFailureAdapter:
    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        raise RuntimeError(
            "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE: "
            "container agent initialization failed"
        )

    def denied_secret_values(self, job_id: str):
        raise RuntimeError("task denied-secret registry is missing")

    def credential_material_state(self, job_id: str):
        return "not_issued"

    def clear_denied_secrets(self, job_id: str):
        return None


class _PostCredentialRegistryLossAdapter(_EarlyRuntimeFailureAdapter):
    secret = "temporary-session-value-after-registry-loss"

    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        raise RuntimeError(
            "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: subprocess echoed "
            f"{self.secret}"
        )

    def credential_material_state(self, job_id: str):
        return "may_have_been_issued"


def _service(tmp_path: Path, adapter):
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.run_service import ResearchRunService
    from factor_factory.console.store import ResearchJobStore
    from factor_factory.console.worktree_allocator import FactorWorktreeAllocator

    source = _make_source_repo(tmp_path)
    config = ConsoleConfig(
        source_repo=source,
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "worktrees",
        auth_disabled=True,
    )
    store = ResearchJobStore(config.state_root)
    allocator = FactorWorktreeAllocator(
        source_repo=source,
        configured_root=config.worktree_root,
        run_state_root=config.state_root / "allocations",
        base_ref="HEAD",
    )
    service = ResearchRunService(
        config=config,
        store=store,
        allocator=allocator,
        agent_adapter=adapter,
        poll_seconds=0.05,
    )
    return source, store, service


def _request(title: str):
    from factor_factory.console.models import ResearchRequest

    return ResearchRequest(title=title, hypothesis="A testable economic and mathematical hypothesis.")


def test_resume_request_artifact_failure_restores_parent_conversation_state(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module

    _source, store, service = _service(tmp_path, _TerminalRejectAdapter())
    job = service.submit(_request("Resume request transaction"))
    allocation = service.allocator.allocate(
        factor_id=job.factor_id,
        research_id=job.research_id,
        report_id=job.report_id,
        implementation_mode="operator",
    )
    service._write_request_artifacts(job, allocation)
    workspace = allocation.workspace_path
    request_path = workspace / "identity" / "web_research_request.json"
    guide_path = workspace / "identity" / "web_research_runtime.md"
    request_before = request_path.read_bytes()
    guide_before = guide_path.read_bytes()
    checkpoints_before = {
        path.name
        for path in (workspace / "identity" / "conversation_ledger").iterdir()
    }
    store.add_message(
        job.job_id,
        content_kind="decision",
        content="Append one bounded revision decision.",
        model=job.request.model,
        idempotency_key="resume-transaction-test",
    )

    def fail_after_partial_packet_write(**kwargs):
        request_path.write_text(
            json.dumps(kwargs["request"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        guide_path.write_text("partial runtime guide\n", encoding="utf-8")
        raise RuntimeError("injected packet write failure")

    monkeypatch.setattr(
        module,
        "write_web_research_packet",
        fail_after_partial_packet_write,
    )
    with pytest.raises(RuntimeError, match="injected packet write failure"):
        service._write_request_artifacts(
            job,
            allocation,
            preserve_plan=True,
            trusted_resume_start_step="6",
            trusted_resume_context={
                "attestation_id": (
                    f"attestations/{job.job_id}/attestation_transaction_test.json"
                ),
                "attestation_sha256": "a" * 64,
            },
        )

    assert request_path.read_bytes() == request_before
    assert guide_path.read_bytes() == guide_before
    assert {
        path.name
        for path in (workspace / "identity" / "conversation_ledger").iterdir()
    } == checkpoints_before


def test_host_conversation_binding_requires_real_parent_attestation(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module

    _source, store, service = _service(tmp_path, _TerminalRejectAdapter())
    job = service.submit(_request("Host conversation provenance"))
    allocation = service.allocator.allocate(
        factor_id=job.factor_id,
        research_id=job.research_id,
        report_id=job.report_id,
        implementation_mode="operator",
    )
    job = store.update_job(
        job.job_id,
        base_commit=allocation.base_commit,
        worktree_path=str(allocation.worktree_path),
        workspace_path=str(allocation.workspace_path),
    )
    service._write_request_artifacts(job, allocation)
    workspace = allocation.workspace_path
    parent_request = json.loads(
        (workspace / "identity" / "web_research_request.json").read_text(
            encoding="utf-8"
        )
    )
    receipt_id = f"jobs/{job.job_id}/formal-execution/receipt_parent.json"
    receipt_path = service.config.state_root / receipt_id
    identity = {
        "job_id": job.job_id,
        "factor_id": job.factor_id,
        "research_id": job.research_id,
        "report_id": job.report_id,
        "base_commit": job.base_commit,
    }
    _write_json(
        receipt_path,
        {
            "version": "factorforge_console_host_formal_execution_v2",
            **identity,
        },
    )
    receipt_sha256 = _file_sha256(receipt_path)
    attestation_id = (
        f"attestations/{job.job_id}/attestation_conversation_parent.json"
    )
    attestation_path = service.config.state_root / attestation_id
    _write_json(
        attestation_path,
        {
            "version": "factorforge_console_host_execution_attestation_v2",
            **identity,
            "formal_execution_receipt_id": receipt_id,
            "formal_execution_receipt_sha256": receipt_sha256,
        },
    )
    attestation_sha256 = _file_sha256(attestation_path)
    trusted_parent = {
        "attestation_id": attestation_id,
        "attestation_sha256": attestation_sha256,
        "receipt_id": receipt_id,
        "receipt_sha256": receipt_sha256,
        "conversation_request_sha256": stable_json_hash(parent_request),
        "conversation_ledger_checkpoint": parent_request[
            CONVERSATION_LEDGER_REFERENCE_FIELD
        ],
    }
    store.add_message(
        job.job_id,
        content_kind="decision",
        content="Append one host-attested decision.",
        model=job.request.model,
        idempotency_key="host-provenance-test",
    )
    service._write_request_artifacts(
        job,
        allocation,
        preserve_plan=True,
        trusted_resume_start_step="6",
        trusted_resume_context=trusted_parent,
    )

    binding = _ORIGINAL_VALIDATE_HOST_CONVERSATION_LEDGER_BINDING(
        workspace=workspace,
        state_root=service.config.state_root,
        job=job,
        resume=True,
        resume_trust=trusted_parent,
    )
    assert binding["mode"] == "append"
    assert binding["parent_attestation_id"] == attestation_id
    assert binding["parent_attestation_sha256"] == attestation_sha256

    wrong_sha_parent = {**trusted_parent, "attestation_sha256": "b" * 64}
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _ORIGINAL_VALIDATE_HOST_CONVERSATION_LEDGER_BINDING(
            workspace=workspace,
            state_root=service.config.state_root,
            job=job,
            resume=True,
            resume_trust=wrong_sha_parent,
        )
    nonexistent_parent = {
        **trusted_parent,
        "attestation_id": (
            f"attestations/{job.job_id}/attestation_forged_nonexistent.json"
        ),
        "attestation_sha256": "b" * 64,
    }
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _ORIGINAL_VALIDATE_HOST_CONVERSATION_LEDGER_BINDING(
            workspace=workspace,
            state_root=service.config.state_root,
            job=job,
            resume=True,
            resume_trust=nonexistent_parent,
        )

    catalog = tmp_path / "catalog.json"
    _write_json(catalog, {"datasets": []})
    service.config = replace(service.config, data_catalogs=(catalog,))
    monkeypatch.setattr(
        module,
        "_validate_host_conversation_ledger_binding",
        _ORIGINAL_VALIDATE_HOST_CONVERSATION_LEDGER_BINDING,
    )

    def subprocess_must_not_run(*_args, **_kwargs):
        raise AssertionError("formal subprocess started before provenance validation")

    monkeypatch.setattr(module.subprocess, "run", subprocess_must_not_run)
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _ORIGINAL_EXECUTE_HOST_FORMAL_PIPELINE(
            service,
            job,
            worktree=allocation.worktree_path,
            workspace=workspace,
            resume=True,
            resume_trust={
                **nonexistent_parent,
                "start_step": "6",
                "ultimate_proof_sha256": "f" * 64,
            },
            denied_values=(),
            host_data_env={},
        )


def test_service_runs_two_factors_in_separate_worktrees_and_preserves_reject(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.ultimate_reader as reader

    monkeypatch.setattr(
        reader,
        "validate_factor_proof_certificate",
        lambda *args, **kwargs: {"verdict": "REJECT", "block_reasons": []},
    )
    monkeypatch.setattr(
        reader,
        "validate_protocol_bundle",
        lambda *args, **kwargs: {"verdict": "PASS", "block_reasons": []},
    )
    source, store, service = _service(tmp_path, _TerminalRejectAdapter())
    first = service.submit(_request("Factor alpha"))
    second = service.submit(_request("Factor beta"))

    service.run_once()
    service.run_once()
    first_done = store.get_job(first.job_id)
    second_done = store.get_job(second.job_id)

    assert first_done.execution_status == "COMPLETED"
    assert first_done.protocol_status == "PASS"
    assert first_done.factor_verdict == "REJECT"
    assert first_done.formal_proof_eligible is True
    assert first_done.result["metrics"]["rank_ic"]["mean"] == -0.01
    assert first_done.worktree_path != second_done.worktree_path
    assert first_done.workspace_path != second_done.workspace_path
    assert Path(first_done.workspace_path).is_relative_to(Path(first_done.worktree_path))
    assert Path(second_done.workspace_path).is_relative_to(Path(second_done.worktree_path))
    first_identity = Path(first_done.workspace_path) / "identity"
    assert (first_identity / "web_research_runtime.md").is_file()
    assert (first_identity / "web_research_plan.json").is_file()
    assert (first_identity / "data_catalog_summary.json").is_file()
    assert (first_identity / "factor_knowledge_summary.json").is_file()
    plan = json.loads((first_identity / "web_research_plan.json").read_text(encoding="utf-8"))
    assert plan["identity"]["factor_id"] == first_done.factor_id
    assert _git(source, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_wrapper_pass_with_council_pause_becomes_review_required(tmp_path):
    _source, store, service = _service(tmp_path, _PausedAdapter())
    job = service.submit(_request("Paused factor"))
    service.run_once()
    paused = store.get_job(job.job_id)

    assert paused.execution_status == "REVIEW_REQUIRED"
    assert paused.protocol_status == "PAUSED"
    assert paused.council_status == "PAUSED"
    assert paused.formal_proof_eligible is False


def test_nonzero_agent_returncode_cannot_publish_stale_terminal_or_pause_status():
    from types import SimpleNamespace

    from factor_factory.console.run_service import _web_execution_status

    assert _web_execution_status(
        SimpleNamespace(execution_status="PAUSED"),
        124,
    ) == "FAILED"
    assert _web_execution_status(
        SimpleNamespace(execution_status="COMPLETED"),
        1,
    ) == "FAILED"


def test_fresh_allocation_attestation_receives_persisted_base_commit(tmp_path):
    _source, store, service = _service(tmp_path, _TerminalRejectAdapter())
    captured = {}

    def capture_attestation(**kwargs):
        captured["base_commit"] = kwargs["job"].base_commit
        return "attestations/unit-test.json"

    service._write_host_attestation = capture_attestation
    job = service.submit(_request("Attested base commit"))
    service.run_once()

    persisted = store.get_job(job.job_id)
    assert captured["base_commit"]
    assert captured["base_commit"] == persisted.base_commit


def test_resume_refreshes_read_only_packet_without_overwriting_agent_plan(tmp_path):
    _source, store, service = _service(tmp_path, _PausedAdapter())
    job = service.submit(_request("Resume packet factor"))
    service.run_once()
    paused = store.get_job(job.job_id)
    plan_path = Path(paused.workspace_path) / "identity" / "web_research_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["research_object"]["formula_or_law"] = "agent-authored-preserved-law"
    _write_json(plan_path, plan)

    service.request_resume(job.job_id)
    service.run_once()

    resumed_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert resumed_plan["research_object"]["formula_or_law"] == "agent-authored-preserved-law"
    assert (Path(paused.workspace_path) / "identity" / "web_resume_authorization.json").is_file()


def test_mechanism_pause_writes_exact_agent_resume_contract_and_answer_form(tmp_path, monkeypatch):
    from dataclasses import replace

    from factor_factory.console.agent_adapter import AgentRunResult, build_agent_prompt
    from factor_factory.console.models import ResearchJob

    source, _store, service = _service(tmp_path, _PausedAdapter())
    workspace = source / "factor_research" / "FACTOR" / "research"
    (workspace / "identity").mkdir(parents=True)
    job = ResearchJob(
        job_id="job_1234567890",
        factor_id="FACTOR",
        research_id="research",
        report_id="REPORT",
        request=_request("Mechanism pause factor"),
    )
    proof_relative = "objects/runtime_context/ultimate_run_report__REPORT.json"
    proof_path = workspace / proof_relative
    _write_json(
        proof_path,
        {
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
            },
        },
    )
    _write_json(
        workspace
        / "objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.json",
        {
            "contract_version": "factorforge_main_agent_mechanism_questionnaire_v1",
            "report_id": "REPORT",
            "source_refs": {
                "factor_spec_master": "objects/factor_spec_master/factor_spec_master__REPORT.json",
                "factor_case_master": "objects/factor_case_master/factor_case_master__REPORT.json",
                "evaluation_summary": "objects/validation/factor_evaluation__REPORT.json",
            },
            "formula_facts": {
                "formula": "divide(minus(close, open), pre_close)",
                "fields": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
                "profile_flags": {"has_open_close_position": True},
            },
            "metric_facts": {
                "rank_ic_mean": -0.0078,
                "cost_adjusted_annual_return": -0.12,
            },
            "upstream_hypothesis_context": {
                "decision": "iterate",
                "mechanism_analysis": {
                    "deterministic_component_interpretation": (
                        "DO_NOT_LEAK_QUESTIONNAIRE_INTERPRETATION"
                    )
                },
            },
        },
    )
    (
        workspace
        / "objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.md"
    ).write_text("# Questionnaire\n", encoding="utf-8")
    _write_json(
        workspace
        / "objects/research_iteration_master/main_agent_mechanism_memo_status__REPORT.json",
        {
            "report_id": "REPORT",
            "status": "awaiting_main_agent_mechanism_memo",
            "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
            "questionnaire_ref": {
                "contract_version": "factorforge_main_agent_mechanism_questionnaire_v1",
                "json_path": str(
                    workspace
                    / "objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.json"
                ),
                "markdown_path": str(
                    workspace
                    / "objects/research_iteration_master/main_agent_mechanism_questionnaire__REPORT.md"
                ),
            },
            "expected_memo_ref": {
                "contract_version": "factorforge_main_agent_mechanism_memo_v1",
                "json_path": str(
                    workspace
                    / "objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json"
                ),
                "markdown_path": str(
                    workspace
                    / "objects/research_iteration_master/main_agent_mechanism_memo__REPORT.md"
                ),
            },
        },
    )
    _write_json(
        workspace / "objects/factor_spec_master/factor_spec_master__REPORT.json",
        {
            "factor_id": "FACTOR",
            "canonical_spec": {
                "formula_text": "divide(minus(close, open), pre_close)",
                "required_inputs": ["close", "open", "pre_close"],
                "operators": ["divide", "minus"],
            },
        },
    )
    _write_json(
        workspace / "objects/factor_case_master/factor_case_master__REPORT.json",
        {
            "factor_id": "FACTOR",
            "headline_metrics": {
                "rank_ic_mean": -0.0078,
                "long_side_turnover_mean_daily": 0.8724,
            },
        },
    )
    _write_json(
        workspace / "objects/validation/factor_evaluation__REPORT.json",
        {
            "report_id": "REPORT",
            "coverage_summary": {
                "row_count": 8034990,
                "date_count": 2313,
                "ticker_count": 5004,
            },
            "backend_summary": [
                {
                    "backend": "self_quant",
                    "status": "PASS",
                    "key_metrics": {
                        "rank_ic_mean": -0.0078,
                        "rank_ic_ir": -0.1225,
                        "pearson_ic_mean": 0.0056,
                        "pearson_ic_ir": 0.1257,
                        "long_side_annual_volatility": 0.2631,
                        "long_side_sharpe": 0.0482,
                        "long_side_max_drawdown": -0.5943,
                        "long_side_recovery_days": 3474,
                        "long_side_turnover_mean_daily": 0.8724,
                        "trading_cogs_annual": 0.6596,
                        "cost_adjusted_annual_return": -0.12,
                        "cost_adjusted_long_side_sharpe": -2.4582,
                        "cost_adjusted_long_side_max_drawdown": -0.9983,
                        "cost_adjusted_long_side_recovery_days": 3474,
                    },
                }
            ],
        },
    )
    service._write_resume_authorization(job, workspace)
    _write_json(workspace / "identity/web_research_request.json", {"report_id": "REPORT"})
    _write_json(workspace / "identity/factor_knowledge_summary.json", {"cold_start": True})
    resume_task = service._write_agent_resume_contract(
        job,
        workspace,
        resume_trust={
            "start_step": "6",
            "ultimate_proof_sha256": _file_sha256(proof_path),
        },
        attempt_id=f"resume_{'a' * 32}",
    )

    contract_path = workspace / "identity/web_agent_resume_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    answer_form_path = workspace / contract["answer_form"]
    answer_form = json.loads(answer_form_path.read_text(encoding="utf-8"))
    assert contract["pause_kind"] == "main_agent_mechanism_memo"
    assert contract["resume_start_step"] == "6"
    assert contract["prior_output_sha256"] == {}
    assert contract["required_output"].endswith(
        "main_agent_mechanism_memo__REPORT.json"
    )
    assert contract["input_sha256"][contract["answer_form"]] == _file_sha256(
        answer_form_path
    )
    facts = json.loads((workspace / contract["facts"]).read_text(encoding="utf-8"))
    assert "DO_NOT_LEAK_QUESTIONNAIRE_INTERPRETATION" not in json.dumps(facts)
    assert facts["observed_metrics"]["rank_ic_ir"] == -0.1225
    assert facts["observed_metrics"]["pearson_ic_ir"] == 0.1257
    assert facts["observed_metrics"]["trading_cogs_annual"] == 0.6596
    assert facts["metric_availability"]["missing_core_metric_keys"] == []
    assert facts["revision_context"] == {
        "mode": "initial",
        "revision_number": 0,
        "failures": [],
    }
    assert contract["facts"] in contract["agent_read_only_inputs"]
    assert not any("questionnaire" in item for item in contract["agent_read_only_inputs"])
    assert answer_form["producer"] == ""
    assert answer_form["resume_attempt_id"] == f"resume_{'a' * 32}"
    assert answer_form["mechanism_qa"] == {
        field: "" for field in contract["required_qa_fields"]
    }
    expected_signature_keys = {
        "rank_ic",
        "long_side",
        "cost_adjusted",
        "monotonicity",
        "turnover",
    }
    assert set(answer_form["math_hypothesis"]["expected_metric_signature"]) == expected_signature_keys
    assert set(answer_form["expected_metric_signature"]) == expected_signature_keys
    assert answer_form["formula_component_map"][0]["economic_state"] == ""
    assert "stochastic_process" in contract["allowed_model_families"]
    assert answer_form["evidence_comparison"]["observed_metrics"]

    prompt = build_agent_prompt(
        job,
        worktree=source,
        workspace=workspace,
        config=service.config,
        resume=True,
        resume_task=resume_task,
    )
    assert prompt.startswith("# Factor Forge Step6 Mechanism Resume Task")
    assert "AWAITING_MAIN_AGENT_MECHANISM_MEMO" in prompt
    assert contract["required_output"] in prompt
    assert contract["facts"] in prompt
    assert "main_agent_mechanism_questionnaire__REPORT.json" not in prompt
    assert "DO_NOT_LEAK_QUESTIONNAIRE_INTERPRETATION" not in prompt
    assert contract["answer_form"] in prompt
    assert contract["validation_command"] not in prompt
    assert "## Host-pinned fact lock" in prompt
    assert '"formula":"divide(minus(close, open), pre_close)"' in prompt
    assert '"rank_ic_mean":-0.0078' in prompt
    assert '"has_additive_rank_raw_ratio":false' in prompt
    assert (
        "authoritative even when the title or submitted hypothesis suggests a richer"
        in prompt
    )
    assert "identify that implementation mismatch\nexplicitly" in prompt
    assert "never invent the\nmissing component" in prompt
    assert "Host starts from the hash-bound\nanswer form" in prompt
    assert "does not alter or fill any research claim" in prompt
    assert "pinned formal validator after your\n   clean exit" in prompt
    assert "MEMO_DRAFT_COMPLETE" in prompt
    assert "phase\n   workspace is read-only" in prompt
    assert "Return exactly one minified JSON object" in prompt
    assert "Build the research-field patch" in prompt
    assert "Do not copy machine-owned values into the patch" in prompt
    assert "Host alone reconstructs identity,\n   source refs" in prompt
    assert "Never include machine-owned fields" in prompt
    assert "performs the only\n   permitted artifact write" in prompt
    assert "Do not call\n   a write or edit tool" in prompt
    assert "the patch at 16,000 bytes and the memo at 24,000 bytes" in prompt
    assert "knowledge, or any file. Do not run" in prompt
    assert (
        "E[close_{i,t+2}/close_{i,t+1}-1 | F_t, formula_state_{i,t}], entry"
        in prompt
    )
    assert "identical JSON objects" in prompt
    assert "top-level `falsification_tests` as a JSON list with at least two" in prompt
    assert "Every list item must be one\n     non-empty plain JSON string" in prompt
    assert "objects, dictionaries, arrays, or structured\n     test records are invalid" in prompt
    assert "does not satisfy this required\n     top-level field" in prompt
    assert "any Step script or\n   validator" in prompt
    assert "exact validator above" not in prompt
    assert "RankIC and\n   PearsonIC are evaluation statistics" in prompt
    assert "must not describe IC" in prompt
    assert "do not write any of those" in prompt
    assert "Select the same economic model family in both model-family fields" in prompt
    assert "select `transient_impact` even though its representation" in prompt
    assert "regime models may still use\n   `stochastic_process`" in prompt
    assert "semicolon-delimited equations and include an equation" in prompt
    assert "observable state to the model components" in prompt
    assert "whether the branch is\n   economically active and discontinuous" in prompt
    assert "exact zero/tie convention" in prompt
    assert "branches are equivalent or continuous" in prompt
    assert "bucket or rank instability" in prompt
    assert "numerator, denominator, and window" in prompt
    assert "a non-negative scale, a signed\n   estimator" in prompt
    assert "Do not infer its sign role\n   from the Host flag alone" in prompt
    assert "Required Authoring Preflight" not in prompt
    assert "six packet files" not in prompt
    assert "Fill the task-local web research plan" not in prompt

    shared_gateway_prompt = build_agent_prompt(
        job,
        worktree=source,
        workspace=workspace,
        config=replace(service.config, execution_mode="shared_gateway"),
        resume=True,
        resume_task=resume_task,
    )
    assert f"Copy `{answer_form_path}` to" in shared_gateway_prompt
    assert "use exactly one write call for\n   the memo" in shared_gateway_prompt
    assert "Return exactly\n   `MEMO_DRAFT_COMPLETE`" in shared_gateway_prompt
    assert "Return exactly one minified JSON object" not in shared_gateway_prompt
    assert "workspace is read-only" not in shared_gateway_prompt
    assert "knowledge, or any file outside the required memo" in shared_gateway_prompt
    assert "knowledge, or any file. Do not run" not in shared_gateway_prompt
    assert "Host rehydrates machine-owned" not in shared_gateway_prompt
    assert "shared-gateway development path does not\nrehydrate" in shared_gateway_prompt
    assert "research-field patch" not in shared_gateway_prompt
    assert "Do not copy machine-owned values into the patch" not in shared_gateway_prompt
    assert "Host alone reconstructs identity" not in shared_gateway_prompt
    assert "Keep the completed memo below 22,000 UTF-8 bytes" in shared_gateway_prompt
    assert "answer form is the sole\n   source of truth" in shared_gateway_prompt

    revision_probe_paths = (
        proof_path,
        workspace / resume_task.status_relative,
        contract_path,
        workspace / resume_task.facts_relative,
        answer_form_path,
    )
    revision_probe_baseline = {
        path: path.read_bytes() for path in revision_probe_paths
    }
    prior_memo_path = workspace / resume_task.required_output_relative
    _write_json(prior_memo_path, {"prior": "rejected memo"})
    revision_prewrite_path = (
        workspace / "objects/validation/step6_prewrite_block__REPORT.json"
    )
    _write_json(
        revision_prewrite_path,
        {"prewrite_blocked": True, "report_id": "REPORT"},
    )
    revision_failure = (
        "formula_specific_derivation_invalid:"
        "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC"
    )
    revision_status = json.loads(
        (workspace / resume_task.status_relative).read_text(encoding="utf-8")
    )
    revision_status.update(
        {
            "status": "awaiting_main_agent_mechanism_memo_revision",
            "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO_REVISION",
            "revision_number": 1,
            "revision_failures": [revision_failure],
            "prior_memo_sha256": _file_sha256(prior_memo_path),
            "questionnaire_sha256": _file_sha256(
                workspace / resume_task.questionnaire_relative
            ),
            "prewrite_block_ref": (
                "objects/validation/step6_prewrite_block__REPORT.json"
            ),
            "prewrite_block_sha256": _file_sha256(revision_prewrite_path),
        }
    )
    _write_json(workspace / resume_task.status_relative, revision_status)
    revision_proof = json.loads(proof_path.read_text(encoding="utf-8"))
    revision_proof["main_agent_mechanism_memo"]["status"] = (
        "awaiting_main_agent_mechanism_memo_revision"
    )
    revision_proof["main_agent_mechanism_memo"]["token"] = (
        "AWAITING_MAIN_AGENT_MECHANISM_MEMO_REVISION"
    )
    _write_json(proof_path, revision_proof)
    revision_task = service._write_agent_resume_contract(
        job,
        workspace,
        resume_trust={
            "start_step": "6",
            "ultimate_proof_sha256": _file_sha256(proof_path),
        },
        attempt_id=f"resume_{'c' * 32}",
    )
    assert dict(revision_task.prior_output_sha256) == {
        revision_task.required_output_relative: _file_sha256(prior_memo_path)
    }
    revision_contract = json.loads(
        (workspace / revision_task.contract_relative).read_text(encoding="utf-8")
    )
    assert revision_contract["prior_output_sha256"] == dict(
        revision_task.prior_output_sha256
    )
    revision_facts = json.loads(
        (workspace / revision_task.facts_relative).read_text(encoding="utf-8")
    )
    assert revision_facts["revision_context"] == {
        "mode": "revision",
        "revision_number": 1,
        "failures": [revision_failure],
    }
    revision_prompt = build_agent_prompt(
        job,
        worktree=source,
        workspace=workspace,
        config=service.config,
        resume=True,
        resume_task=revision_task,
    )
    assert "every listed failure is a hard\nrejection" in revision_prompt
    assert "BLOCK_MECHANISM_PROFIT_PAYER_DERIVATION_GENERIC" in revision_prompt
    prior_memo_path.unlink()
    revision_prewrite_path.unlink()
    for path, content in revision_probe_baseline.items():
        path.write_bytes(content)

    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        build_agent_prompt(
            job,
            worktree=source,
            workspace=workspace,
            config=service.config,
            resume=True,
            resume_task=replace(
                resume_task,
                answer_form_relative="../outside-answer-form.json",
            ),
        )

    memo_path = workspace / contract["required_output"]
    memo = json.loads(answer_form_path.read_text(encoding="utf-8"))
    memo["report_id"] = "WRONG_REPORT"
    _write_json(memo_path, memo)
    monkeypatch.setattr(
        "factor_factory.console.run_service.validate_main_agent_mechanism_memo",
        lambda _memo, _spec: [],
    )
    agent_session_key = "agent:resume:test"
    result_path = (
        service.config.state_root
        / "jobs"
        / job.job_id
        / "agent_run_test.json"
    )
    _write_json(
        result_path,
        {
            "version": "factorforge_console_agent_run_v1",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "agent_id": "agent-resume-test",
            "session_key_sha256": hashlib.sha256(
                agent_session_key.encode("utf-8")
            ).hexdigest(),
            "resume": True,
            "resume_attempt_id": resume_task.attempt_id,
            "returncode": 0,
        },
    )
    agent_result = AgentRunResult(
        returncode=0,
        agent_id="agent-resume-test",
        session_key=agent_session_key,
        started_at_utc="2026-08-02T00:00:00Z",
        finished_at_utc="2026-08-02T00:01:00Z",
        stdout_tail="",
        stderr_tail="",
        result_path=str(result_path),
    )
    with pytest.raises(
        RuntimeError,
        match="BLOCK_FACTORFORGE_CONSOLE_AGENT_RESUME_ARTIFACT_INVALID:.*report_id",
    ):
        service._validate_agent_resume_artifact(
            job,
            workspace,
            resume_trust={
                "start_step": "6",
                "ultimate_proof_sha256": _file_sha256(proof_path),
            },
            resume_task=resume_task,
            agent_result=agent_result,
        )

    memo = json.loads(answer_form_path.read_text(encoding="utf-8"))
    memo["producer"] = "step6_main_agent"
    memo["agent_authorship"] = {
        "authoring_mode": "current_agent_freeform",
        "agent_role": "main_agent",
        "answered_without_deterministic_template": True,
    }
    _write_json(memo_path, memo)
    with pytest.raises(RuntimeError, match="producer_not_current_main_agent"):
        service._validate_agent_resume_artifact(
            job,
            workspace,
            resume_trust={
                "start_step": "6",
                "ultimate_proof_sha256": _file_sha256(proof_path),
            },
            resume_task=resume_task,
            agent_result=agent_result,
        )

    memo["producer"] = "current_main_agent"
    _write_json(memo_path, memo)
    memo["formula_component_map"].append(
        {
            "component_id": "invented_gap_component",
            "formula_subexpression": "divide(open, pre_close)",
            "operators": ["divide"],
        }
    )
    _write_json(memo_path, memo)
    with pytest.raises(
        RuntimeError,
        match="formula_component_map.required_components",
    ):
        service._validate_agent_resume_artifact(
            job,
            workspace,
            resume_trust={
                "start_step": "6",
                "ultimate_proof_sha256": _file_sha256(proof_path),
            },
            resume_task=resume_task,
            agent_result=agent_result,
        )
    memo["formula_component_map"].pop()
    _write_json(memo_path, memo)
    validation = service._validate_agent_resume_artifact(
        job,
        workspace,
        resume_trust={
            "start_step": "6",
            "ultimate_proof_sha256": _file_sha256(proof_path),
        },
        resume_task=resume_task,
        agent_result=agent_result,
    )

    from factor_factory.console.run_service import (
        _formal_owned_resume_relatives,
        _require_validated_resume_artifacts_unchanged,
        _validate_formal_owned_artifact_transitions,
        _workspace_evidence_tree,
    )

    formal_owned = _formal_owned_resume_relatives(resume_task)
    formal_owned_baseline = {
        relative: (workspace / relative).read_bytes()
        for relative in formal_owned
    }
    for relative in formal_owned:
        (workspace / relative).write_text(
            f"formal host rewrite:{relative}\n",
            encoding="utf-8",
        )
    with pytest.raises(RuntimeError, match="validated resume artifact changed"):
        _require_validated_resume_artifacts_unchanged(
            workspace,
            state_root=service.config.state_root,
            resume_task=resume_task,
            validation=validation,
        )
    _require_validated_resume_artifacts_unchanged(
        workspace,
        state_root=service.config.state_root,
        resume_task=resume_task,
        validation=validation,
        allowed_workspace_changes=formal_owned,
    )
    validated_hashes = dict(validation.workspace_file_sha256)
    formal_receipt = {
        "formal_owned_artifact_transitions": {
            relative: {
                "before_sha256": validated_hashes[relative],
                "after_sha256": _file_sha256(workspace / relative),
                "changed": True,
                "producer": "host_formal_pipeline",
            }
            for relative in formal_owned
        }
    }
    snapshot_entries = _workspace_evidence_tree(workspace)
    transitions = _validate_formal_owned_artifact_transitions(
        formal_receipt=formal_receipt,
        workspace_entries=snapshot_entries,
        resume_task=resume_task,
        validation=validation,
    )
    assert set(transitions) == formal_owned
    non_boolean_receipt = json.loads(json.dumps(formal_receipt))
    non_boolean_receipt["formal_owned_artifact_transitions"][
        resume_task.status_relative
    ]["changed"] = 1
    with pytest.raises(RuntimeError, match="formal mutation receipt hash mismatch"):
        _validate_formal_owned_artifact_transitions(
            formal_receipt=non_boolean_receipt,
            workspace_entries=snapshot_entries,
            resume_task=resume_task,
            validation=validation,
        )
    raced_relative = resume_task.status_relative
    (workspace / raced_relative).write_text("raced after receipt\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="formal mutation receipt hash mismatch"):
        _validate_formal_owned_artifact_transitions(
            formal_receipt=formal_receipt,
            workspace_entries=_workspace_evidence_tree(workspace),
            resume_task=resume_task,
            validation=validation,
        )
    (workspace / raced_relative).write_text(
        f"formal host rewrite:{raced_relative}\n",
        encoding="utf-8",
    )
    for relative, content in formal_owned_baseline.items():
        (workspace / relative).write_bytes(content)

    memo["council_questions"] = ["late replacement"]
    _write_json(memo_path, memo)
    with pytest.raises(RuntimeError, match="validated resume artifact changed"):
        _require_validated_resume_artifacts_unchanged(
            workspace,
            state_root=service.config.state_root,
            resume_task=resume_task,
            validation=validation,
        )
    memo["council_questions"] = []
    _write_json(memo_path, memo)

    agent_run = json.loads(result_path.read_text(encoding="utf-8"))
    agent_run["resume_attempt_id"] = f"resume_{'b' * 32}"
    _write_json(result_path, agent_run)
    with pytest.raises(RuntimeError, match="validated agent receipt changed"):
        _require_validated_resume_artifacts_unchanged(
            workspace,
            state_root=service.config.state_root,
            resume_task=resume_task,
            validation=validation,
        )
    with pytest.raises(RuntimeError, match="agent_run_receipt_binding_invalid"):
        service._validate_agent_resume_artifact(
            job,
            workspace,
            resume_trust={
                "start_step": "6",
                "ultimate_proof_sha256": _file_sha256(proof_path),
            },
            resume_task=resume_task,
            agent_result=agent_result,
        )


def _metric_signature_failures(
    values: dict[str, str],
    *,
    top: dict[str, str] | None = None,
) -> list[str]:
    from factor_factory.mechanism_math.main_agent_memo import (
        validate_main_agent_mechanism_memo,
    )

    return validate_main_agent_mechanism_memo(
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "math_hypothesis": {"expected_metric_signature": values},
            "expected_metric_signature": dict(values) if top is None else top,
        }
    )


def test_main_agent_memo_metric_signature_blank_values_block():
    blank = {
        "rank_ic": "",
        "long_side": "",
        "cost_adjusted": "",
        "monotonicity": "",
        "turnover": "",
    }
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXPECTED_METRIC_SIGNATURE_MISSING"
        in _metric_signature_failures(blank)
    )


def test_main_agent_memo_metric_signature_divergence_blocks():
    signature = {
        "rank_ic": "expected positive rank IC; observed sign is contradictory",
        "long_side": "expected positive long-side return; observed return is negative",
        "cost_adjusted": "expected positive net return; observed costs erase the payoff",
        "monotonicity": "expected ordered buckets; observed ordering is non-monotonic",
        "turnover": "expected moderate turnover; observed turnover is excessive",
    }
    divergent = dict(signature)
    divergent["turnover"] = "different top-level turnover claim"
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXPECTED_METRIC_SIGNATURE_MISSING"
        in _metric_signature_failures(signature, top=divergent)
    )


def test_main_agent_memo_metric_signature_filled_and_identical_passes_signature_gate():
    signature = {
        "rank_ic": "expected positive rank IC; observed sign is contradictory",
        "long_side": "expected positive long-side return; observed return is negative",
        "cost_adjusted": "expected positive net return; observed costs erase the payoff",
        "monotonicity": "expected ordered buckets; observed ordering is non-monotonic",
        "turnover": "expected moderate turnover; observed turnover is excessive",
    }
    assert (
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_EXPECTED_METRIC_SIGNATURE_MISSING"
        not in _metric_signature_failures(signature)
    )


def _model_family_failures(selected: str, selection: str) -> list[str]:
    from factor_factory.mechanism_math.main_agent_memo import (
        validate_main_agent_mechanism_memo,
    )

    signature = {
        "rank_ic": "expected sign compared with observed evidence",
        "long_side": "expected long-side return compared with observed evidence",
        "cost_adjusted": "expected net return compared with observed evidence",
        "monotonicity": "expected ordering compared with observed evidence",
        "turnover": "expected turnover compared with observed evidence",
    }
    return validate_main_agent_mechanism_memo(
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "math_hypothesis": {
                "selected_model_family": selected,
                "expected_metric_signature": signature,
            },
            "math_model_selection": {
                "model_family": selection,
                "baseline_model": "state equation",
                "model_mutation": "formula-specific observation equation",
            },
            "expected_metric_signature": dict(signature),
        }
    )


def test_main_agent_memo_model_family_mismatch_blocks():
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" in (
        _model_family_failures("transient_impact", "stochastic_process")
    )


def test_main_agent_memo_model_family_aliases_normalize_before_comparison():
    failures = _model_family_failures(
        "price_volume_microstructure",
        "transient_impact",
    )
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID" not in failures
    assert "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_MISMATCH" not in failures


def test_failed_mechanism_resume_restores_exact_parent_evidence_tree(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "identity").mkdir(parents=True)
    (workspace / "reports").mkdir()
    (workspace / "objects/research_iteration_master").mkdir(parents=True)
    (workspace / "identity/web_research_runtime.md").write_text(
        "parent runtime\n", encoding="utf-8"
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "parent ledger\n", encoding="utf-8"
    )
    (workspace / "reports/user_hypothesis.md").write_text(
        "parent hypothesis\n", encoding="utf-8"
    )
    parent_tree_hash = stable_json_hash(_workspace_evidence_tree(workspace))
    restore_state = _capture_resume_restore_state(
        workspace,
        report_id="REPORT",
    )

    (workspace / "identity/web_research_runtime.md").write_text(
        "resume runtime\n", encoding="utf-8"
    )
    (workspace / "identity/web_execution_ledger.md").write_text(
        "failed resume ledger\n", encoding="utf-8"
    )
    (workspace / "identity/web_agent_resume_contract.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (workspace / "objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json").write_text(
        "{}\n", encoding="utf-8"
    )

    _restore_resume_workspace(
        workspace,
        restore_state,
        report_id="REPORT",
        expected_tree_sha256=parent_tree_hash,
    )

    assert stable_json_hash(_workspace_evidence_tree(workspace)) == parent_tree_hash
    assert (workspace / "identity/web_research_runtime.md").read_text(encoding="utf-8") == "parent runtime\n"
    assert (workspace / "identity/web_execution_ledger.md").read_text(encoding="utf-8") == "parent ledger\n"
    assert not (workspace / "identity/web_agent_resume_contract.json").exists()
    assert not (
        workspace
        / "objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json"
    ).exists()


def test_mechanism_metric_projection_preserves_backend_conflicts_and_step5_fields():
    from factor_factory.console.run_service import (
        _complete_mechanism_metric_facts,
        _questionnaire_metric_matches_projection,
    )

    metrics, availability = _complete_mechanism_metric_facts(
        {},
        {
            "coverage_summary": {"coverage_ratio": 1.0},
            "backend_summary": [
                {
                    "backend": "self_quant",
                    "status": "PASS",
                    "key_metrics": {
                        "rank_ic_mean": 0.03,
                        "top_decile_mean_return": 0.0012,
                        "bottom_decile_mean_return": -0.0008,
                        "coverage_ratio": 0.94,
                        "annualization_factor": 252,
                        "long_side_mean_return_daily": 0.0004,
                    },
                },
                {
                    "backend": "qlib",
                    "status": "PASS",
                    "key_metrics": {
                        "rank_ic_mean": -0.01,
                        "top_decile_mean_return": 0.0007,
                        "bottom_decile_mean_return": -0.0003,
                        "coverage_ratio": 0.91,
                        "final_account": 1000123.45,
                        "nonzero_turnover_rows": 1234,
                    },
                },
            ]
        },
    )

    assert metrics["rank_ic_mean"]["status"] == "backend_conflict"
    assert metrics["coverage_ratio"]["status"] == "backend_conflict"
    assert metrics["coverage_ratio"]["reported_aggregate"] == 1.0
    assert {
        item["value"]
        for item in metrics["rank_ic_mean"]["backend_observations"]
    } == {0.03, -0.01}
    assert "top_decile_mean_return" in metrics["backend_metric_conflicts"]
    assert "bottom_decile_mean_return" in metrics["backend_metric_conflicts"]
    assert "coverage_ratio" in metrics["backend_metric_conflicts"]
    assert metrics["backend_metrics"][0]["metrics"]["coverage_ratio"] == 0.94
    assert metrics["backend_metrics"][0]["metrics"]["annualization_factor"] == 252
    assert (
        metrics["backend_metrics"][0]["metrics"]["long_side_mean_return_daily"]
        == 0.0004
    )
    assert metrics["backend_metrics"][1]["metrics"]["final_account"] == 1000123.45
    assert metrics["backend_metrics"][1]["metrics"]["nonzero_turnover_rows"] == 1234
    assert "annualization_factor" not in metrics["backend_metrics"][0][
        "promoted_metric_keys"
    ]
    assert availability["backends"][1]["metrics"]["rank_ic_mean"] == -0.01
    assert _questionnaire_metric_matches_projection(metrics, "rank_ic_mean", -0.01)
    assert not _questionnaire_metric_matches_projection(metrics, "rank_ic_mean", 0.5)


def test_mechanism_metric_projection_never_treats_disputed_aggregate_as_authoritative():
    from factor_factory.console.run_service import (
        _complete_mechanism_metric_facts,
        _questionnaire_metric_matches_projection,
    )

    metrics, _availability = _complete_mechanism_metric_facts(
        {"headline_metrics": {"rank_ic_mean": 0.02}},
        {
            "backend_summary": [
                {
                    "backend": "self_quant",
                    "status": "PASS",
                    "key_metrics": {"rank_ic_mean": 0.03},
                },
                {
                    "backend": "qlib",
                    "status": "PASS",
                    "key_metrics": {"rank_ic_mean": -0.01},
                },
            ]
        },
    )

    assert metrics["rank_ic_mean"]["status"] == "backend_conflict"
    assert metrics["rank_ic_mean"]["reported_aggregate"] == 0.02
    assert _questionnaire_metric_matches_projection(metrics, "rank_ic_mean", 0.03)
    assert _questionnaire_metric_matches_projection(metrics, "rank_ic_mean", -0.01)
    assert not _questionnaire_metric_matches_projection(metrics, "rank_ic_mean", 0.02)


@pytest.mark.parametrize(
    "key_metrics",
    [
        {f"metric_{index}": index for index in range(101)},
        {"rank_ic_mean": float("nan")},
    ],
)
def test_mechanism_metric_projection_rejects_unbounded_or_nonfinite_backend_metrics(
    key_metrics,
):
    from factor_factory.console.run_service import _complete_mechanism_metric_facts

    with pytest.raises(RuntimeError, match="backend metric facts rejected bounds"):
        _complete_mechanism_metric_facts(
            {},
            {
                "backend_summary": [
                    {
                        "backend": "unsafe_backend",
                        "status": "PASS",
                        "key_metrics": key_metrics,
                    }
                ]
            },
        )


def test_mechanism_metric_projection_rejects_excessive_nesting_without_recursion_error():
    from factor_factory.console.run_service import _complete_mechanism_metric_facts

    nested = 1
    for _index in range(1200):
        nested = {"nested": nested}

    with pytest.raises(RuntimeError, match="backend metric facts rejected bounds"):
        _complete_mechanism_metric_facts(
            {},
            {
                "backend_summary": [
                    {
                        "backend": "deep_backend",
                        "status": "PASS",
                        "key_metrics": {"rank_ic_mean": nested},
                    }
                ]
            },
        )


@pytest.mark.parametrize("malformed", ["{not-json", "[]"])
def test_malformed_mechanism_memo_is_retryable_and_restores_parent_tree(
    tmp_path,
    monkeypatch,
    malformed,
):
    adapter = _PausedThenMalformedMemoAdapter(tmp_path / "state", malformed)
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Malformed mechanism memo"))
    service.run_once()
    paused = store.get_job(job.job_id)
    workspace = Path(paused.workspace_path)
    parent_tree_sha256 = stable_json_hash(_workspace_evidence_tree(workspace))

    monkeypatch.setattr(
        "factor_factory.console.run_service._validate_agent_write_boundary",
        _validate_agent_write_boundary_impl,
    )
    service.request_resume(job.job_id)
    service.run_once()

    blocked = store.get_job(job.job_id)
    assert blocked.execution_status == "BLOCKED"
    assert (
        blocked.error_code
        == "BLOCK_FACTORFORGE_CONSOLE_AGENT_RESUME_ARTIFACT_INVALID"
    )
    assert blocked.result["host_attestation_id"] == paused.result[
        "host_attestation_id"
    ]
    assert stable_json_hash(_workspace_evidence_tree(workspace)) == parent_tree_sha256
    assert not (
        workspace
        / "objects"
        / "research_iteration_master"
        / f"main_agent_mechanism_memo__{job.report_id}.json"
    ).exists()
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "RESUMABLE"
    assert adapter.calls == 2


def test_resume_prelaunch_unavailable_restores_and_remains_resumable(tmp_path):
    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE

    adapter = _PausedThenResumeFailureAdapter(BLOCK_AGENT_RUNTIME_UNAVAILABLE)
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Resume prelaunch unavailable"))
    service.run_once()
    paused = store.get_job(job.job_id)
    workspace = Path(paused.workspace_path)
    parent_tree_sha256 = stable_json_hash(_workspace_evidence_tree(workspace))

    service.request_resume(job.job_id)
    service.run_once()

    blocked = store.get_job(job.job_id)
    assert blocked.error_code == BLOCK_AGENT_RUNTIME_UNAVAILABLE
    assert blocked.result["host_attestation_id"] == paused.result[
        "host_attestation_id"
    ]
    assert stable_json_hash(_workspace_evidence_tree(workspace)) == parent_tree_sha256
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "RESUMABLE"
    assert adapter.calls == 2


def test_nonzero_resume_restores_parent_tree_and_remains_resumable(tmp_path):
    adapter = _PausedThenNonzeroResumeAdapter(tmp_path / "state")
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Nonzero mechanism resume"))
    service.run_once()
    paused = store.get_job(job.job_id)
    workspace = Path(paused.workspace_path)
    parent_tree_sha256 = stable_json_hash(_workspace_evidence_tree(workspace))

    service.request_resume(job.job_id)
    service.run_once()

    blocked = store.get_job(job.job_id)
    assert (
        blocked.error_code
        == "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED"
    )
    assert blocked.result["host_attestation_id"] == paused.result[
        "host_attestation_id"
    ]
    assert stable_json_hash(_workspace_evidence_tree(workspace)) == parent_tree_sha256
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "RESUMABLE"
    assert adapter.calls == 2


def test_post_council_runtime_failure_restores_parent_tree_and_result_root(tmp_path):
    from factor_factory.console.agent_adapter import BLOCK_AGENT_RUNTIME_UNAVAILABLE

    adapter = _CouncilPauseThenLeaseFailureAdapter(tmp_path / "state")
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Council result restore"))
    service.run_once()
    paused = store.get_job(job.job_id)
    workspace = Path(paused.workspace_path)
    parent_tree_sha256 = stable_json_hash(_workspace_evidence_tree(workspace))
    result_root = (
        workspace
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / job.report_id
        / "agent_results"
    )
    assert not result_root.exists()

    service.request_resume(job.job_id)
    service.run_once()

    blocked = store.get_job(job.job_id)
    assert adapter.council_ingress_completed is True
    assert blocked.error_code == BLOCK_AGENT_RUNTIME_UNAVAILABLE
    assert blocked.result["host_attestation_id"] == paused.result[
        "host_attestation_id"
    ]
    assert not result_root.exists()
    assert stable_json_hash(_workspace_evidence_tree(workspace)) == parent_tree_sha256
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "RESUMABLE"


def test_possible_orphaned_resume_writer_is_non_resumable(tmp_path):
    from factor_factory.console.agent_adapter import BLOCK_AGENT_ORPHANED_WRITER

    adapter = _PausedThenResumeFailureAdapter(BLOCK_AGENT_ORPHANED_WRITER)
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Orphaned resume writer"))
    service.run_once()
    service.request_resume(job.job_id)
    service.run_once()

    blocked = store.get_job(job.job_id)
    assert blocked.error_code == BLOCK_AGENT_ORPHANED_WRITER
    assert (
        service.config.state_root
        / "jobs"
        / job.job_id
        / "security"
        / "non_resumable.json"
    ).is_file()
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "NON_RESUMABLE"
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        service.request_resume(job.job_id)
    assert adapter.calls == 2


def test_resume_classifier_distinguishes_all_known_resume_states(tmp_path):
    from factor_factory.console.run_service import (
        RESUME_KIND_COUNCIL_INGRESS,
        RESUME_KIND_HOST_FORMAL_CHECKPOINT,
        RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS,
        RESUME_KIND_HUMAN_NEXT_DERIVATION,
        RESUME_KIND_MECHANISM_AGENT,
        _apply_execution_mode_resume_policy,
        _classify_resume_route,
    )

    workspace = tmp_path / "workspace"
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / "ultimate_run_report__REPORT.json"
    )

    def classify(payload, *, start_step="6"):
        _write_json(proof_path, payload)
        return _classify_resume_route(
            workspace,
            "REPORT",
            start_step=start_step,
            trusted_proof_sha256=_file_sha256(proof_path),
        )

    assert classify(
        {"status": "FAIL", "failure": {"command": "run_step4"}},
        start_step="4",
    ).kind == RESUME_KIND_HOST_FORMAL_CHECKPOINT
    assert classify(
        {
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "status": "awaiting_main_agent_mechanism_memo",
                "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
            },
        }
    ).kind == RESUME_KIND_MECHANISM_AGENT
    revision_route = classify(
        {
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "status": "awaiting_main_agent_mechanism_memo_revision",
                "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO_REVISION",
            },
        }
    )
    assert revision_route.kind == RESUME_KIND_MECHANISM_AGENT
    assert (
        revision_route.pause_state
        == "awaiting_main_agent_mechanism_memo_revision"
    )
    assert (
        _apply_execution_mode_resume_policy(
            revision_route,
            execution_mode="container",
        ).kind
        == RESUME_KIND_MECHANISM_AGENT
    )
    assert (
        _apply_execution_mode_resume_policy(
            revision_route,
            execution_mode="shared_gateway",
        ).kind
        == RESUME_KIND_HUMAN_NEXT_DERIVATION
    )
    manual_route = classify(
        {
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "status": "awaiting_main_agent_mechanism_manual_review",
                "token": "AWAITING_MAIN_AGENT_MECHANISM_MANUAL_REVIEW",
            },
        }
    )
    assert manual_route.kind == RESUME_KIND_HUMAN_NEXT_DERIVATION
    assert classify(
        {
            "status": "PAUSED",
            "revision_council": {
                "status": "awaiting_agent_results",
                "effective_mode": "agentic_dispatch_manifest",
            },
        }
    ).kind == RESUME_KIND_COUNCIL_INGRESS
    assert classify(
        {
            "status": "PAUSED",
            "final_outcome": "awaiting_main_agent_council_synthesis",
        }
    ).kind == RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS
    assert classify(
        {
            "status": "PAUSED",
            "final_outcome": "awaiting_next_derivation",
        }
    ).kind == RESUME_KIND_HUMAN_NEXT_DERIVATION
    with pytest.raises(RuntimeError, match="unknown or unsupported paused resume state"):
        classify({"status": "PAUSED"})


def test_host_formal_checkpoint_resume_does_not_call_research_agent(
    tmp_path,
    monkeypatch,
):
    adapter = _PausedThenForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Host checkpoint retry"))
    service.run_once()
    paused = store.get_job(job.job_id)
    assert paused.execution_status == "REVIEW_REQUIRED"
    assert adapter.calls == 1

    workspace = Path(paused.workspace_path)
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{job.report_id}.json"
    )
    _write_json(
        proof_path,
        {
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "status": "FAIL",
            "failure": {"command": "run_step4", "returncode": 1},
        },
    )

    def trusted_step4(
        _job,
        *,
        worktree,
        workspace,
        private_execution_started=False,
    ):
        return {
            "start_step": "4",
            "ultimate_proof_sha256": _file_sha256(proof_path),
            "attestation_id": f"attestations/{job.job_id}.json",
            "attestation_sha256": "attestation-hash",
            "receipt_id": f"jobs/{job.job_id}/formal-execution/receipt.json",
            "receipt_sha256": "receipt-hash",
            "workspace_evidence_tree_root_sha256": stable_json_hash(
                _workspace_evidence_tree(Path(workspace))
            ),
        }

    monkeypatch.setattr(service, "_validate_trusted_resume_context", trusted_step4)
    service.request_resume(job.job_id)
    service.run_once()

    assert adapter.calls == 1
    host_records = list(
        (
            service.config.state_root
            / "jobs"
            / job.job_id
            / "host-checkpoint-runs"
        ).glob("*.json")
    )
    assert len(host_records) == 1
    assert json.loads(host_records[0].read_text(encoding="utf-8"))[
        "actor_kind"
    ] == "host_formal_checkpoint"


def test_generic_resume_preserves_explicit_human_decision_pause(tmp_path):
    adapter = _PausedThenForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Council synthesis decision"))
    service.run_once()
    paused = store.get_job(job.job_id)
    workspace = Path(paused.workspace_path)
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{job.report_id}.json"
    )
    _write_json(
        proof_path,
        {
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "status": "PAUSED",
            "final_outcome": "awaiting_main_agent_council_synthesis",
        },
    )
    service.request_resume(job.job_id)
    service.run_once()

    review = store.get_job(job.job_id)
    assert review.execution_status == "REVIEW_REQUIRED"
    assert review.protocol_status == "PAUSED"
    assert (
        review.error_code
        == "FACTORFORGE_CONSOLE_EXPLICIT_HUMAN_DECISION_REQUIRED"
    )
    assert adapter.calls == 1
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "RESUMABLE"


def test_write_outside_factor_workspace_blocks_even_with_formal_reject(tmp_path):
    _source, store, service = _service(tmp_path, _EscapingAdapter())
    job = service.submit(_request("Escaping factor"))
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.factor_verdict == "BLOCK"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED"


def test_agent_forged_pause_cannot_be_laundered_through_resume(tmp_path, monkeypatch):
    import factor_factory.console.run_service as module

    adapter = _ForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    monkeypatch.setattr(
        module,
        "_validate_agent_write_boundary",
        _validate_agent_write_boundary_impl,
    )
    job = service.submit(_request("Forged pause factor"))
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_AGENT_WRITE_SCOPE_INVALID"
    assert adapter.calls == 1
    assert (
        service.config.state_root
        / "jobs"
        / job.job_id
        / "security"
        / "non_resumable.json"
    ).is_file()
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        service.request_resume(job.job_id)

    store.request_resume(job.job_id)
    monkeypatch.setattr(
        module.ResearchRunService,
        "_validate_trusted_resume_context",
        _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT,
    )
    service.run_once()
    blocked_again = store.get_job(job.job_id)

    assert blocked_again.execution_status == "BLOCKED"
    assert blocked_again.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 1

    store.update_job(
        job.job_id,
        worktree_path="",
        workspace_path="",
        base_commit="",
    )
    store.request_resume(job.job_id)
    service.run_once()
    blocked_fresh_forgery = store.get_job(job.job_id)

    assert blocked_fresh_forgery.execution_status == "BLOCKED"
    assert blocked_fresh_forgery.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 1


def test_security_block_remains_non_resumable_when_private_marker_write_fails(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module

    adapter = _ForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    monkeypatch.setattr(
        module,
        "_validate_agent_write_boundary",
        _validate_agent_write_boundary_impl,
    )
    monkeypatch.setattr(
        service,
        "_mark_job_non_resumable",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    job = service.submit(_request("Marker failure factor"))
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert "禁止续跑" in blocked.error_message
    assert adapter.calls == 1
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        service.request_resume(job.job_id)

    store.request_resume(job.job_id)
    service.run_once()
    blocked_again = store.get_job(job.job_id)

    assert blocked_again.execution_status == "BLOCKED"
    assert blocked_again.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 1


def test_marker_failure_after_trusted_pause_cannot_be_forced_back_to_agent(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module

    adapter = _PausedThenForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Trusted pause marker failure"))
    service.run_once()
    paused = store.get_job(job.job_id)

    assert paused.execution_status == "REVIEW_REQUIRED"
    assert adapter.calls == 1

    service.request_resume(job.job_id)
    monkeypatch.setattr(
        module,
        "_validate_agent_write_boundary",
        _validate_agent_write_boundary_impl,
    )
    monkeypatch.setattr(
        service,
        "_mark_job_non_resumable",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert "host_attestation_id" not in blocked.result
    assert adapter.calls == 2

    store.request_resume(job.job_id)
    service.run_once()
    blocked_again = store.get_job(job.job_id)

    assert blocked_again.execution_status == "BLOCKED"
    assert blocked_again.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 2


def test_fresh_path_forgery_consumes_resumable_lifecycle_before_marker_failure(
    tmp_path,
    monkeypatch,
):
    adapter = _PausedThenForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Fresh-path lifecycle replay guard"))
    service.run_once()
    paused = store.get_job(job.job_id)

    assert paused.execution_status == "REVIEW_REQUIRED"
    assert adapter.calls == 1
    original_paths = {
        "worktree_path": paused.worktree_path,
        "workspace_path": paused.workspace_path,
        "base_commit": paused.base_commit,
    }
    lifecycle_path = service._private_lifecycle_path(job.job_id)
    assert json.loads(lifecycle_path.read_text(encoding="utf-8"))["status"] == "RESUMABLE"

    store.update_job(
        job.job_id,
        worktree_path="",
        workspace_path="",
        base_commit="",
    )
    store.request_resume(job.job_id)
    monkeypatch.setattr(
        service,
        "_mark_job_non_resumable",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    service.run_once()
    forged = store.get_job(job.job_id)

    assert forged.execution_status == "BLOCKED"
    assert forged.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 1
    assert json.loads(lifecycle_path.read_text(encoding="utf-8"))["status"] == "RUNNING"

    store.update_job(job.job_id, **original_paths)
    store.request_resume(job.job_id)
    service.run_once()
    replay = store.get_job(job.job_id)

    assert replay.execution_status == "BLOCKED"
    assert replay.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 1
    assert json.loads(lifecycle_path.read_text(encoding="utf-8"))["status"] == "RUNNING"


def test_evidence_event_failure_never_commits_resumable_private_state(
    tmp_path,
    monkeypatch,
):
    adapter = _PausedThenForgingAdapter()
    _source, store, service = _service(tmp_path, adapter)
    original_append_event = store.append_event

    def fail_evidence_event(job_id, event_type, message, payload):
        if event_type == "EVIDENCE_VERIFIED":
            raise OSError("ledger event unavailable")
        return original_append_event(job_id, event_type, message, payload)

    monkeypatch.setattr(store, "append_event", fail_evidence_event)
    job = service.submit(_request("Evidence event failure"))
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_INTERNAL_ERROR"
    assert "host_attestation_id" not in blocked.result
    assert adapter.calls == 1

    store.request_resume(job.job_id)
    service.run_once()
    blocked_again = store.get_job(job.job_id)

    assert blocked_again.execution_status == "BLOCKED"
    assert blocked_again.error_code == "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
    assert adapter.calls == 1


def test_service_rejects_direct_source_url_until_fetch_broker_exists(tmp_path):
    from factor_factory.console.models import ResearchRequest

    _source, store, service = _service(tmp_path, _PausedAdapter())
    request = ResearchRequest(
        title="External source factor",
        hypothesis="test hypothesis",
        source_url="https://example.com/research",
    )

    try:
        service.submit(request)
    except ValueError as exc:
        assert "source URL ingestion is disabled" in str(exc)
    else:
        raise AssertionError("source URL should be rejected before job creation")
    assert store.list_jobs() == []


def test_service_redacts_exact_temporary_credentials_and_deactivates_registry(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.ultimate_reader as reader

    monkeypatch.setattr(
        reader,
        "validate_factor_proof_certificate",
        lambda *args, **kwargs: {"verdict": "REJECT", "block_reasons": []},
    )
    monkeypatch.setattr(
        reader,
        "validate_protocol_bundle",
        lambda *args, **kwargs: {"verdict": "PASS", "block_reasons": []},
    )
    adapter = _CredentialEchoAdapter()
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Credential echo factor"))

    service.run_once()
    completed = store.get_job(job.job_id)
    serialized = json.dumps(completed.to_dict(), ensure_ascii=False)

    assert completed.execution_status == "COMPLETED"
    assert adapter.secret not in serialized
    assert adapter.deactivated is True
    assert adapter.cleared is False
    public_root = service.config.state_root / "public" / job.job_id
    assert adapter.secret.encode("utf-8") not in b"".join(
        path.read_bytes() for path in public_root.rglob("*") if path.is_file()
    )


def test_early_runtime_failure_keeps_original_block_reason_without_registry(tmp_path):
    _source, store, service = _service(tmp_path, _EarlyRuntimeFailureAdapter())
    job = service.submit(_request("Early runtime failure"))

    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE"
    assert "container agent initialization failed" in blocked.error_message
    assert "CREDENTIAL_REGISTRY_INVALID" not in blocked.error_message


def test_post_credential_registry_loss_fails_closed_without_echoing_exception(tmp_path):
    adapter = _PostCredentialRegistryLossAdapter()
    _source, store, service = _service(tmp_path, adapter)
    job = service.submit(_request("Post-credential registry loss"))

    service.run_once()
    blocked = store.get_job(job.job_id)
    serialized = json.dumps(
        {"job": blocked.to_dict(), "events": store.list_events(job.job_id)},
        ensure_ascii=False,
    )

    assert blocked.execution_status == "BLOCKED"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_REGISTRY_INVALID"
    assert "未公开原始异常详情" in blocked.error_message
    assert adapter.secret not in serialized
    assert "subprocess echoed" not in serialized


def test_web_result_redacts_exact_and_base64_temporary_credentials():
    import base64

    from factor_factory.console.run_service import _redact_public_payload

    secret = "temporary-session-value-for-result-test"
    encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
    unpadded = encoded.rstrip("=")
    escaped = "".join(f"\\u{ord(character):04x}" for character in secret)
    payload = {
        "ordinary_note": secret,
        "nested": [f"prefix:{encoded}", f"prefix:{unpadded}", escaped],
    }

    redacted = _redact_public_payload(payload, (secret,))

    serialized = json.dumps(redacted)
    assert secret not in serialized
    assert encoded not in serialized
    assert unpadded not in serialized
    assert escaped not in serialized
    assert serialized.count("[redacted]") >= 4


def test_private_receipt_snapshot_uses_validated_bytes_and_ignores_later_source_change(
    tmp_path,
):
    from factor_factory.console.run_service import _copy_immutable_regular_file

    source = tmp_path / "agent_receipt.json"
    snapshot = tmp_path / "agent_receipt.snapshot.json"
    source.write_text('{"returncode": 0}\n', encoding="utf-8")
    expected_sha256 = _file_sha256(source)

    copied_sha256 = _copy_immutable_regular_file(
        source,
        snapshot,
        root=tmp_path,
        expected_sha256=expected_sha256,
        block_token="BLOCK_TEST",
        label="agent receipt",
    )
    source.write_text('{"returncode": 1}\n', encoding="utf-8")

    assert copied_sha256 == expected_sha256
    assert _file_sha256(snapshot) == expected_sha256
    with pytest.raises(RuntimeError, match="changed during snapshot"):
        _copy_immutable_regular_file(
            source,
            tmp_path / "agent_receipt.rejected.json",
            root=tmp_path,
            expected_sha256=expected_sha256,
            block_token="BLOCK_TEST",
            label="agent receipt",
        )


def test_private_receipt_snapshot_rejects_destination_parent_swap(
    tmp_path,
    monkeypatch,
):
    from factor_factory.console.run_service import _copy_immutable_regular_file

    root = tmp_path / "state"
    source = root / "jobs/job_test/receipt.json"
    destination_parent = root / "attestations/job_test/snapshots"
    source.parent.mkdir(parents=True)
    destination_parent.mkdir(parents=True)
    source.write_text('{"returncode": 0}\n', encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    backup = destination_parent.with_name("snapshots-backup")
    original_open = os.open
    swapped = False

    def swap_after_parent_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if str(path) == "snapshots" and dir_fd is not None and not swapped:
            destination_parent.rename(backup)
            destination_parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return descriptor

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "open", swap_after_parent_open)
        with pytest.raises(RuntimeError, match="destination verification parent is unsafe"):
            _copy_immutable_regular_file(
                source,
                destination_parent / "receipt.snapshot.json",
                root=root,
                expected_sha256=_file_sha256(source),
                block_token="BLOCK_TEST",
                label="agent receipt",
            )

    assert not (outside / "receipt.snapshot.json").exists()
    assert not (backup / "receipt.snapshot.json").exists()


def test_host_execution_attestation_is_outside_agent_workspace(tmp_path, monkeypatch):
    import factor_factory.console.run_service as module
    from factor_factory.console.agent_adapter import AgentRunResult
    from factor_factory.console.run_service import ResearchRunService
    from factor_factory.console.ultimate_reader import (
        UltimateRunSummary,
        read_ultimate_workspace,
    )
    from factor_factory.console.worktree_allocator import FactorWorktreeAllocator

    source, store, service = _service(tmp_path, _TerminalRejectAdapter())
    job = service.submit(_request("Host attestation"))
    allocation = service.allocator.allocate(
        factor_id=job.factor_id,
        research_id=job.research_id,
        report_id=job.report_id,
        implementation_mode="operator",
    )
    job = store.update_job(
        job.job_id,
        base_commit=allocation.base_commit,
        worktree_path=str(allocation.worktree_path),
        workspace_path=str(allocation.workspace_path),
    )
    workspace = allocation.workspace_path
    service._write_request_artifacts(job, allocation)
    evidence = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{job.report_id}.json"
    )
    step4_evidence = (
        workspace
        / "objects"
        / "backtest_master"
        / f"backtest_master__{job.report_id}.json"
    )
    _write_json(evidence, {"report_id": job.report_id, "status": "PAUSED", "failure": None})
    _write_json(step4_evidence, {"report_id": job.report_id, "status": "PASS"})
    result_path = service.config.state_root / "jobs" / job.job_id / "agent-result.json"
    _write_json(result_path, {"returncode": 0})
    summary = UltimateRunSummary(
        report_id=job.report_id,
        factor_id=job.factor_id,
        research_id=job.research_id,
        execution_status="PAUSED",
        protocol_status="PAUSED",
        factor_verdict="ITERATE",
        council_status="PAUSED",
        formal_proof_eligible=False,
        current_stage="review_required",
        artifact_ids={
            "wrapper_report": (
                "objects/runtime_context/"
                f"ultimate_run_report__{job.report_id}.json"
            ),
            "step4_report": (
                "objects/backtest_master/"
                f"backtest_master__{job.report_id}.json"
            ),
        },
    )
    agent_result = AgentRunResult(
        returncode=0,
        agent_id="agent-test",
        session_key="session-test",
        started_at_utc="2026-08-02T00:00:00Z",
        finished_at_utc="2026-08-02T00:01:00Z",
        stdout_tail="",
        stderr_tail="",
        result_path=str(result_path),
    )
    materialize_argv = [
        sys.executable,
        "scripts/materialize_factorforge_web_research.py",
        "--workspace-root",
        str(workspace.resolve()),
        "--plan",
        str(workspace.resolve() / "identity" / "web_research_plan.json"),
    ]
    ultimate_argv = [
        sys.executable,
        "scripts/run_factorforge_ultimate.py",
        "--report-id",
        job.report_id,
        "--start-step",
        "3",
        "--end-step",
        "all",
        "--factorforge-root",
        str(allocation.worktree_path.resolve()),
        "--factor-id",
        job.factor_id,
        "--research-id",
        job.research_id,
        "--factor-workspace",
        str(workspace.resolve()),
    ]
    receipt_path = (
        service.config.state_root
        / "jobs"
        / job.job_id
        / "formal-execution"
        / "receipt.json"
    )
    _write_json(
        receipt_path,
        {
            "version": "factorforge_console_host_formal_execution_v2",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
            "resume": False,
            "resume_parent": None,
            "conversation_ledger_binding": _test_conversation_ledger_binding(),
            "formal_owned_artifact_transitions": {},
            "commands": [
                {
                    "name": "materialize_web_research",
                    "argv": materialize_argv,
                    "argv_sha256": stable_json_hash(materialize_argv),
                    "returncode": 0,
                    "host_observed_process": True,
                    "cwd": str(allocation.worktree_path.resolve()),
                },
                {
                    "name": "run_factorforge_ultimate",
                    "argv": ultimate_argv,
                    "argv_sha256": stable_json_hash(ultimate_argv),
                    "returncode": 0,
                    "host_observed_process": True,
                    "cwd": str(allocation.worktree_path.resolve()),
                },
            ],
            "ultimate_proof_sha256": _file_sha256(evidence),
        },
    )
    formal_execution = {
        "receipt_id": receipt_path.relative_to(service.config.state_root).as_posix(),
        "receipt_sha256": _file_sha256(receipt_path),
        "ultimate_argv_sha256": stable_json_hash(ultimate_argv),
        "ultimate_returncode": 0,
        "conversation_ledger_binding": _test_conversation_ledger_binding(),
    }

    service._begin_private_execution(job, resume=False)
    attested_workspace = service._snapshot_workspace_evidence(job, workspace)
    original_step4_before_attestation = step4_evidence.read_bytes()
    _write_json(step4_evidence, {"report_id": job.report_id, "status": "RACED"})
    relative = _ORIGINAL_WRITE_HOST_ATTESTATION(
        service,
        job=job,
        workspace=workspace,
        evidence_root=attested_workspace,
        summary=summary,
        agent_result=agent_result,
        web_materialization={"formula_hash": "formula-hash"},
        formal_execution=formal_execution,
    )
    step4_evidence.write_bytes(original_step4_before_attestation)
    service._finish_private_execution(
        job,
        status="RESUMABLE",
        attestation_id=relative,
    )

    attestation = service.config.state_root / relative
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    assert attestation.is_relative_to(service.config.state_root)
    assert not attestation.is_relative_to(workspace)
    assert payload["host_evidence_reader_invoked"] is True
    assert payload["host_observed_ultimate_process"] is True
    assert payload["formal_execution_receipt_sha256"] == _file_sha256(receipt_path)
    assert payload["formal_execution_receipt_source_id"] == formal_execution[
        "receipt_id"
    ]
    assert payload["conversation_ledger_binding"] == _test_conversation_ledger_binding()
    assert json.loads(receipt_path.read_text(encoding="utf-8"))[
        "conversation_ledger_binding"
    ] == payload["conversation_ledger_binding"]
    assert payload["agent_result_source_id"] == result_path.relative_to(
        service.config.state_root
    ).as_posix()
    assert payload["agent_result_id"] != payload["agent_result_source_id"]
    assert _file_sha256(
        service.config.state_root / payload["agent_result_id"]
    ) == _file_sha256(result_path)
    assert payload["evidence_hashes"]["wrapper_report"]["sha256"]
    assert payload["evidence_hashes"]["step4_report"]["sha256"] == hashlib.sha256(
        original_step4_before_attestation
    ).hexdigest()
    assert payload["workspace_snapshot_id"] == attested_workspace.relative_to(
        service.config.state_root
    ).as_posix()
    trusted = _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
        service,
        job,
        worktree=allocation.worktree_path,
        workspace=workspace,
    )
    assert trusted["start_step"] == "6"
    assert trusted["ultimate_proof_sha256"] == _file_sha256(evidence)

    prior_proof_sha256 = _file_sha256(evidence)
    archived_evidence = evidence.with_name(
        f"{evidence.stem}__prior_{prior_proof_sha256[:12]}{evidence.suffix}"
    )
    evidence.replace(archived_evidence)
    _write_json(
        evidence,
        {
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "status": "PAUSED",
            "failure": None,
            "main_agent_mechanism_memo": {
                "status": "awaiting_main_agent_mechanism_memo_revision",
            },
        },
    )
    os.utime(archived_evidence, ns=(1_000_000_000, 1_000_000_000))
    os.utime(evidence, ns=(2_000_000_000, 2_000_000_000))
    current_proof_sha256 = _file_sha256(evidence)
    assert current_proof_sha256 != prior_proof_sha256

    service._begin_private_execution(job, resume=True)
    resumed_materialize_argv = list(materialize_argv)
    resumed_materialize_argv[1] = str(
        service.config.source_repo
        / "scripts"
        / "materialize_factorforge_web_research.py"
    )
    resumed_ultimate_argv = list(ultimate_argv)
    resumed_ultimate_argv[1] = str(
        service.config.source_repo / "scripts" / "run_factorforge_ultimate.py"
    )
    resumed_ultimate_argv[resumed_ultimate_argv.index("3")] = "6"
    resumed_commands = [
        {
            "name": "materialize_web_research",
            "argv": resumed_materialize_argv,
            "argv_sha256": stable_json_hash(resumed_materialize_argv),
            "engine_script_sha256": _file_sha256(
                Path(resumed_materialize_argv[1])
            ),
            "returncode": 0,
            "host_observed_process": True,
            "cwd": str(allocation.worktree_path.resolve()),
        },
        {
            "name": "run_factorforge_ultimate",
            "argv": resumed_ultimate_argv,
            "argv_sha256": stable_json_hash(resumed_ultimate_argv),
            "engine_script_sha256": _file_sha256(Path(resumed_ultimate_argv[1])),
            "returncode": 0,
            "host_observed_process": True,
            "cwd": str(allocation.worktree_path.resolve()),
        },
    ]
    resumed_formal_execution = service._write_formal_execution_receipt(
        job,
        workspace=workspace,
        commands=resumed_commands,
        resume=True,
        resume_trust=trusted,
        conversation_ledger_binding=_test_conversation_ledger_binding(),
    )
    resumed_attested_workspace = service._snapshot_workspace_evidence(
        job,
        workspace,
    )
    snapshot_current = resumed_attested_workspace / evidence.relative_to(workspace)
    snapshot_archive = resumed_attested_workspace / archived_evidence.relative_to(
        workspace
    )
    assert snapshot_current.stat().st_mtime_ns == evidence.stat().st_mtime_ns
    assert snapshot_archive.stat().st_mtime_ns == archived_evidence.stat().st_mtime_ns
    resumed_summary = read_ultimate_workspace(
        resumed_attested_workspace,
        report_id=job.report_id,
    )
    assert resumed_summary.artifact_ids["wrapper_report"] == evidence.relative_to(
        workspace
    ).as_posix()
    with pytest.raises(
        RuntimeError,
        match="current wrapper summary binding is invalid",
    ):
        _ORIGINAL_WRITE_HOST_ATTESTATION(
            service,
            job=job,
            workspace=workspace,
            evidence_root=resumed_attested_workspace,
            summary=replace(
                resumed_summary,
                artifact_ids={
                    **resumed_summary.artifact_ids,
                    "wrapper_report": archived_evidence.relative_to(
                        workspace
                    ).as_posix(),
                },
            ),
            agent_result=agent_result,
            web_materialization={"formula_hash": "formula-hash"},
            formal_execution=resumed_formal_execution,
        )
    resumed_relative = _ORIGINAL_WRITE_HOST_ATTESTATION(
        service,
        job=job,
        workspace=workspace,
        evidence_root=resumed_attested_workspace,
        summary=resumed_summary,
        agent_result=agent_result,
        web_materialization={"formula_hash": "formula-hash"},
        formal_execution=resumed_formal_execution,
    )
    service._finish_private_execution(
        job,
        status="RESUMABLE",
        attestation_id=resumed_relative,
    )
    assert resumed_relative != relative
    assert attestation.is_file()
    resumed_attestation = json.loads(
        (service.config.state_root / resumed_relative).read_text(encoding="utf-8")
    )
    assert resumed_attestation["evidence_hashes"]["wrapper_report"] == {
        "artifact_id": evidence.relative_to(workspace).as_posix(),
        "sha256": current_proof_sha256,
    }
    service._begin_private_execution(job, resume=True)
    resumed_trusted = _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
        service,
        job,
        worktree=allocation.worktree_path,
        workspace=workspace,
        private_execution_started=True,
    )
    assert resumed_trusted["start_step"] == "6"
    assert resumed_trusted["ultimate_proof_sha256"] == current_proof_sha256
    assert resumed_trusted["attestation_id"] == resumed_relative
    service._finish_private_execution(
        job,
        status="RESUMABLE",
        attestation_id=resumed_relative,
    )

    catalog = tmp_path / "resume-catalog.json"
    _write_json(catalog, {"datasets": []})
    (source / "README.md").write_text("upgraded engine\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "upgrade formal engine")
    upgraded_engine_commit = _git(source, "rev-parse", "HEAD")
    assert upgraded_engine_commit != job.base_commit
    upgraded_config = replace(service.config, data_catalogs=(catalog,))
    upgraded_allocator = FactorWorktreeAllocator(
        source_repo=source,
        configured_root=upgraded_config.worktree_root,
        run_state_root=upgraded_config.state_root / "allocations",
        base_ref="HEAD",
    )
    upgraded_service = ResearchRunService(
        config=upgraded_config,
        store=store,
        allocator=upgraded_allocator,
        agent_adapter=_TerminalRejectAdapter(),
    )
    persisted_allocation = upgraded_allocator.validate_allocation(
        factor_id=job.factor_id,
        research_id=job.research_id,
        report_id=job.report_id,
        persisted_worktree_path=job.worktree_path,
        persisted_workspace_path=job.workspace_path,
        persisted_base_commit=job.base_commit,
    )
    assert persisted_allocation.worktree_path == allocation.worktree_path
    assert persisted_allocation.workspace_path == allocation.workspace_path
    upgraded_trust = _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
        upgraded_service,
        job,
        worktree=persisted_allocation.worktree_path,
        workspace=persisted_allocation.workspace_path,
    )
    assert upgraded_trust["attestation_id"] == resumed_relative
    assert upgraded_trust["start_step"] == "6"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0, stdout="PASS\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    cross_version_receipt = _ORIGINAL_EXECUTE_HOST_FORMAL_PIPELINE(
        upgraded_service,
        job,
        worktree=persisted_allocation.worktree_path,
        workspace=persisted_allocation.workspace_path,
        resume=True,
        resume_trust=upgraded_trust,
        denied_values=(),
        host_data_env={},
    )
    assert len(calls) == 2
    assert calls[0][1]["cwd"] == allocation.worktree_path
    assert calls[1][1]["cwd"] == allocation.worktree_path
    resumed_argv = calls[1][0]
    assert resumed_argv[1] == str(source / "scripts" / "run_factorforge_ultimate.py")
    assert resumed_argv[resumed_argv.index("--start-step") + 1] == "6"
    assert resumed_argv[resumed_argv.index("--factorforge-root") + 1] == str(
        allocation.worktree_path
    )
    assert resumed_argv[resumed_argv.index("--factor-workspace") + 1] == str(
        workspace
    )
    cross_version_payload = json.loads(
        (
            upgraded_service.config.state_root
            / cross_version_receipt["receipt_id"]
        ).read_text(encoding="utf-8")
    )
    assert cross_version_payload["resume"] is True
    assert cross_version_payload["resume_parent"]["attestation_id"] == resumed_relative
    assert cross_version_payload["base_commit"] == job.base_commit
    assert cross_version_payload["engine_commit"] == upgraded_engine_commit

    original_step4 = step4_evidence.read_bytes()
    _write_json(step4_evidence, {"report_id": job.report_id, "status": "FORGED"})
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
            service,
            job,
            worktree=allocation.worktree_path,
            workspace=workspace,
        )
    step4_evidence.write_bytes(original_step4)

    evidence.write_text(
        json.dumps({"report_id": job.report_id, "status": "PAUSED", "forged": True})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="RESUME_TRUST_INVALID"):
        _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
            service,
            job,
            worktree=allocation.worktree_path,
            workspace=workspace,
        )


def test_host_formal_executor_records_exact_materializer_and_ultimate_processes(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module

    source, _store, service = _service(tmp_path, _TerminalRejectAdapter())
    catalog = tmp_path / "catalog.json"
    _write_json(catalog, {"datasets": []})
    service.config = replace(service.config, data_catalogs=(catalog,))
    job = service.submit(_request("Host-owned formal execution"))
    job = replace(job, base_commit="deadbeef")
    worktree = service.config.source_repo
    workspace = worktree / "factor_research" / job.factor_id / job.research_id
    (workspace / "identity").mkdir(parents=True)
    _write_json(workspace / "identity" / "web_research_plan.json", {"version": "test"})
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if Path(argv[1]).name == "run_factorforge_ultimate.py":
            _write_json(
                workspace
                / "objects"
                / "runtime_context"
                / f"ultimate_run_report__{job.report_id}.json",
                {"report_id": job.report_id, "status": "PAUSED"},
            )
        return SimpleNamespace(returncode=0, stdout="PASS\n", stderr="")

    monkeypatch.setenv("FACTORFORGE_CONSOLE_INVITE_PASSWORD", "ambient-invite-value")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ambient-model-key")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "ambient-aws-session-token")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    receipt = _ORIGINAL_EXECUTE_HOST_FORMAL_PIPELINE(
        service,
        job,
        worktree=worktree,
        workspace=workspace,
        resume=False,
        denied_values=(),
        host_data_env={
            "AWS_ACCESS_KEY_ID": "HOSTACCESSKEYFORTEST",
            "AWS_SECRET_ACCESS_KEY": "host-secret-for-test",
            "AWS_SESSION_TOKEN": "host-session-token-for-test",
            "AWS_CREDENTIAL_EXPIRATION": "2026-08-02T01:00:00+00:00",
        },
    )

    assert len(calls) == 2
    assert calls[0][0][1] == str(
        source / "scripts" / "materialize_factorforge_web_research.py"
    )
    assert calls[1][0][1] == str(source / "scripts" / "run_factorforge_ultimate.py")
    assert calls[1][0][calls[1][0].index("--start-step") + 1] == "3"
    assert calls[0][1]["env"]["AWS_ACCESS_KEY_ID"] == "HOSTACCESSKEYFORTEST"
    assert calls[0][1]["env"]["AWS_SESSION_TOKEN"] == "host-session-token-for-test"
    assert calls[0][1]["env"]["FACTORFORGE_REPO_ROOT"] == str(worktree.resolve())
    assert calls[1][1]["env"]["FACTORFORGE_REPO_ROOT"] == str(worktree.resolve())
    assert "FACTORFORGE_CONSOLE_INVITE_PASSWORD" not in calls[0][1]["env"]
    assert "DEEPSEEK_API_KEY" not in calls[0][1]["env"]
    assert calls[1][1]["env"]["AWS_EC2_METADATA_DISABLED"] == "true"
    receipt_path = service.config.state_root / receipt["receipt_id"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["version"] == "factorforge_console_host_formal_execution_v2"
    assert payload["engine_commit"] == service._expected_base_commit
    assert payload["engine_root"] == str(source)
    assert all(command["engine_script_sha256"] for command in payload["commands"])
    assert payload["resume"] is False
    assert payload["resume_parent"] is None
    assert receipt_path.is_relative_to(service.config.state_root)
    assert not receipt_path.is_relative_to(workspace)
    assert [command["host_observed_process"] for command in payload["commands"]] == [
        True,
        True,
    ]
    assert payload["ultimate_proof_sha256"]
    assert payload["readonly_data_lease_injected"] is True

    with pytest.raises(RuntimeError, match="resumed receipt requires a trusted parent"):
        service._write_formal_execution_receipt(
            job,
            workspace=workspace,
            commands=[],
            resume=True,
            resume_trust=None,
        )


def test_formal_engine_checkout_blocks_untracked_python_override(tmp_path):
    from factor_factory.console.run_service import _validate_formal_engine_checkout

    source = _make_source_repo(tmp_path)
    expected_commit = _git(source, "rev-parse", "HEAD")
    override = source / "factor_factory" / "untracked_override.py"
    override.write_text("OVERRIDE = True\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="formal engine commit changed"):
        _validate_formal_engine_checkout(source, expected_commit)


def test_host_formal_execution_uses_deployed_engine_with_pinned_research_worktree(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module
    from factor_factory.console.run_service import ResearchRunService
    from factor_factory.console.worktree_allocator import FactorWorktreeAllocator

    source, store, original_service = _service(tmp_path, _TerminalRejectAdapter())
    catalog = tmp_path / "catalog.json"
    _write_json(catalog, {"datasets": []})
    old_commit = _git(source, "rev-parse", "HEAD")
    research_worktree = tmp_path / "pinned-research-worktree"
    _git(source, "worktree", "add", "--detach", str(research_worktree), old_commit)

    (source / "README.md").write_text("upgraded engine\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "upgrade engine")
    engine_commit = _git(source, "rev-parse", "HEAD")
    assert engine_commit != old_commit

    config = replace(original_service.config, data_catalogs=(catalog,))
    allocator = FactorWorktreeAllocator(
        source_repo=source,
        configured_root=config.worktree_root,
        run_state_root=config.state_root / "allocations",
        base_ref="HEAD",
    )
    service = ResearchRunService(
        config=config,
        store=store,
        allocator=allocator,
        agent_adapter=_TerminalRejectAdapter(),
    )
    job = replace(service.submit(_request("Cross-version formal resume")), base_commit=old_commit)
    workspace = research_worktree / "factor_research" / job.factor_id / job.research_id
    (workspace / "identity").mkdir(parents=True)
    _write_json(workspace / "identity" / "web_research_plan.json", {"version": "test"})
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if Path(argv[1]).name == "run_factorforge_ultimate.py":
            _write_json(
                workspace
                / "objects"
                / "runtime_context"
                / f"ultimate_run_report__{job.report_id}.json",
                {"report_id": job.report_id, "status": "PAUSED"},
            )
        return SimpleNamespace(returncode=0, stdout="PASS\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    receipt = _ORIGINAL_EXECUTE_HOST_FORMAL_PIPELINE(
        service,
        job,
        worktree=research_worktree,
        workspace=workspace,
        resume=False,
        denied_values=(),
        host_data_env={},
    )

    assert calls[0][0][1] == str(
        source / "scripts" / "materialize_factorforge_web_research.py"
    )
    assert calls[1][0][1] == str(source / "scripts" / "run_factorforge_ultimate.py")
    assert not Path(calls[1][0][1]).is_relative_to(research_worktree)
    payload = json.loads(
        (service.config.state_root / receipt["receipt_id"]).read_text(encoding="utf-8")
    )
    assert payload["base_commit"] == old_commit
    assert payload["engine_commit"] == engine_commit


def test_host_formal_executor_preserves_trusted_ultimate_failure_checkpoint(
    tmp_path,
    monkeypatch,
):
    import factor_factory.console.run_service as module

    _source, _store, service = _service(tmp_path, _TerminalRejectAdapter())
    catalog = tmp_path / "catalog.json"
    _write_json(catalog, {"datasets": []})
    service.config = replace(service.config, data_catalogs=(catalog,))
    job = replace(service.submit(_request("Formal nonzero")), base_commit="deadbeef")
    worktree = service.config.source_repo
    workspace = worktree / "factor_research" / job.factor_id / job.research_id
    (workspace / "identity").mkdir(parents=True)
    _write_json(workspace / "identity" / "web_research_plan.json", {"version": "test"})

    def fake_run(argv, **_kwargs):
        if Path(argv[1]).name == "run_factorforge_ultimate.py":
            _write_json(
                workspace
                / "objects"
                / "runtime_context"
                / f"ultimate_run_report__{job.report_id}.json",
                {
                    "contract_version": "factorforge_ultimate_wrapper_v1",
                    "report_id": job.report_id,
                    "factor_id": job.factor_id,
                    "research_id": job.research_id,
                    "status": "FAIL",
                    "finished_at_utc": "2026-08-02T01:00:00Z",
                    "failure": {
                        "command": "finalize_web_factor_proof",
                        "returncode": 1,
                    },
                },
            )
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr=(
                    "BLOCK_FACTORFORGE_WEB_FACTOR_PROOF_FINALIZATION_FAILED: "
                    "calendar mismatch"
                ),
            )
        return SimpleNamespace(returncode=0, stdout="PASS\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    receipt = _ORIGINAL_EXECUTE_HOST_FORMAL_PIPELINE(
        service,
        job,
        worktree=worktree,
        workspace=workspace,
        resume=False,
        denied_values=(),
        host_data_env={
            "AWS_ACCESS_KEY_ID": "HOSTACCESSKEYFORTEST",
            "AWS_SECRET_ACCESS_KEY": "host-secret-for-test",
            "AWS_SESSION_TOKEN": "host-session-token-for-test",
            "AWS_CREDENTIAL_EXPIRATION": "2026-08-02T01:00:00+00:00",
        },
    )

    assert receipt["ultimate_returncode"] == 1
    receipts = sorted(
        (service.config.state_root / "jobs" / job.job_id / "formal-execution").glob(
            "receipt_*.json"
        )
    )
    assert len(receipts) == 1
    payload = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert [item["returncode"] for item in payload["commands"]] == [0, 1]
    assert payload["ultimate_proof_sha256"]


def test_host_formal_failure_checkpoint_rejects_untrusted_wrapper_state(
    tmp_path,
):
    _source, _store, service = _service(tmp_path, _TerminalRejectAdapter())
    job = service.submit(_request("Untrusted formal checkpoint"))
    workspace = service.config.source_repo / "factor_research" / job.factor_id / job.research_id
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{job.report_id}.json"
    )
    _write_json(
        proof_path,
        {
            "contract_version": "factorforge_ultimate_wrapper_v1",
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "status": "RUNNING",
            "finished_at_utc": "2026-08-02T01:00:00Z",
            "failure": {"command": "run_step4", "returncode": 1},
        },
    )

    with pytest.raises(RuntimeError, match="wrapper failure checkpoint is invalid"):
        service._validate_formal_failure_checkpoint(
            job,
            workspace=workspace,
            returncode=1,
            receipt_id=f"jobs/{job.job_id}/formal-execution/receipt.json",
        )


def test_formal_failure_checkpoint_is_attested_and_resumable(
    tmp_path,
    monkeypatch,
):
    _source, store, service = _service(tmp_path, _TerminalRejectAdapter())

    def fail_formal_checkpoint(current_job, *, workspace, **_kwargs):
        _write_json(
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{current_job.report_id}.json",
            {
                "contract_version": "factorforge_ultimate_wrapper_v1",
                "report_id": current_job.report_id,
                "factor_id": current_job.factor_id,
                "research_id": current_job.research_id,
                "status": "FAIL",
                "finished_at_utc": "2026-08-02T01:00:00Z",
                "failure": {"command": "run_step4", "returncode": 1},
            },
        )
        return {
            "receipt_id": f"jobs/{current_job.job_id}/formal-execution/receipt.json",
            "receipt_sha256": "receipt-hash",
            "ultimate_argv_sha256": "ultimate-argv-hash",
            "ultimate_returncode": 1,
        }

    monkeypatch.setattr(service, "_execute_host_formal_pipeline", fail_formal_checkpoint)
    job = service.submit(_request("Resumable formal checkpoint"))
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status in {"BLOCKED", "FAILED"}
    assert blocked.error_code != "BLOCK_FACTORFORGE_CONSOLE_INTERNAL_ERROR"
    assert blocked.result["host_attestation_id"] == "attestations/unit-test.json"
    lifecycle = json.loads(
        service._private_lifecycle_path(job.job_id).read_text(encoding="utf-8")
    )
    assert lifecycle["status"] == "RESUMABLE"

    service.request_resume(job.job_id)
    assert store.get_job(job.job_id).execution_status == "QUEUED"


def test_host_formal_python_environment_keeps_control_package_ahead_of_data_api(
    tmp_path,
):
    worktree = tmp_path / "worktree"
    control_console = worktree / "factor_factory" / "console"
    control_console.mkdir(parents=True)
    (worktree / "factor_factory" / "__init__.py").write_text("\n", encoding="utf-8")
    (control_console / "__init__.py").write_text(
        "CONTROL_MARKER = 'control'\n",
        encoding="utf-8",
    )
    bridge_source = PROJECT_ROOT / "deploy" / "factorforge-console" / "data-api-bridge"
    bridge_target = worktree / "deploy" / "factorforge-console" / "data-api-bridge"
    shutil.copytree(bridge_source, bridge_target)

    data_api_checkout = tmp_path / "data-api"
    data_api_package = data_api_checkout / "factor_factory" / "data_api"
    data_api_package.mkdir(parents=True)
    (data_api_checkout / "factor_factory" / "__init__.py").write_text(
        "DATA_API_SHADOW = True\n",
        encoding="utf-8",
    )
    (data_api_package / "__init__.py").write_text(
        "DATA_API_MARKER = 'external'\n__all__ = ['DATA_API_MARKER']\n",
        encoding="utf-8",
    )
    data_api_alias = tmp_path / "data-api-alias"
    data_api_alias.symlink_to(data_api_checkout, target_is_directory=True)
    unrelated_pythonpath = tmp_path / "unrelated-pythonpath"
    unrelated_pythonpath.mkdir()

    env = {
        "PYTHONPATH": os.pathsep.join(
            [
                f"{data_api_checkout}{os.sep}",
                f"{data_api_checkout}{os.sep}.",
                str(data_api_alias),
                str(data_api_checkout / "factor_factory"),
                str(unrelated_pythonpath),
            ]
        )
    }
    _configure_host_formal_python_environment(
        env,
        worktree=worktree,
        data_api_pythonpath=data_api_checkout,
    )

    python_paths = env["PYTHONPATH"].split(os.pathsep)
    assert python_paths[:2] == [str(worktree.resolve()), str(bridge_target.resolve())]
    assert not any(
        Path(item).is_relative_to(data_api_checkout.resolve()) for item in python_paths
    )
    assert str(unrelated_pythonpath.resolve()) in python_paths
    assert env["FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT"] == str(
        data_api_package.resolve()
    )
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["FACTORFORGE_REPO_ROOT"] == str(worktree.resolve())
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from factor_factory.console import CONTROL_MARKER; "
                "from factorforge_data_api import DATA_API_MARKER; "
                "assert CONTROL_MARKER == 'control'; "
                "assert DATA_API_MARKER == 'external'"
            ),
        ],
        cwd=tmp_path,
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
    )
    assert probe.returncode == 0, probe.stderr


def test_agent_write_boundary_allows_plan_but_rejects_formal_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "identity").mkdir(parents=True)
    before = _workspace_file_snapshot(workspace)
    allowed, required = _allowed_agent_write_paths(
        workspace,
        report_id="REPORT",
        resume=False,
    )
    assert "identity/web_agent_completion.json" in allowed
    assert "identity/web_agent_completion.json" not in required
    _write_json(workspace / "identity" / "web_research_plan.json", {"version": "plan"})
    with pytest.raises(
        RuntimeError,
        match="BLOCK_FACTORFORGE_CONSOLE_AGENT_DELIVERABLE_MISSING:.*missing:identity/web_execution_ledger.md",
    ):
        _validate_agent_write_boundary_impl(
            workspace,
            before=before,
            allowed=allowed,
            required=required,
        )
    (workspace / "identity" / "web_execution_ledger.md").write_text(
        "authored\n",
        encoding="utf-8",
    )
    _validate_agent_write_boundary_impl(
        workspace,
        before=before,
        allowed=allowed,
        required=required,
    )

    before_optional_receipt = _workspace_file_snapshot(workspace)
    _write_json(
        workspace / "identity" / "web_agent_completion.json",
        {"execution_status": "COMPLETED", "formal_proof_eligible": True},
    )
    _validate_agent_write_boundary_impl(
        workspace,
        before=before_optional_receipt,
        allowed=allowed,
        required=required,
    )

    before_formal = _workspace_file_snapshot(workspace)
    _write_json(
        workspace
        / "objects"
        / "runtime_context"
        / "ultimate_run_report__REPORT.json",
        {"status": "PASS"},
    )
    with pytest.raises(RuntimeError, match="AGENT_WRITE_SCOPE_INVALID"):
        _validate_agent_write_boundary_impl(
            workspace,
            before=before_formal,
            allowed=allowed,
            required=required,
        )


def test_agent_write_boundary_resume_requires_ledger_not_completion(tmp_path):
    workspace = tmp_path / "workspace"
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / "ultimate_run_report__REPORT.json"
    )
    _write_json(proof_path, {"status": "PAUSED"})
    before = _workspace_file_snapshot(workspace)
    allowed, required = _allowed_agent_write_paths(
        workspace,
        report_id="REPORT",
        resume=True,
        trusted_resume_proof_sha256=_file_sha256(proof_path),
    )
    assert "identity/web_agent_completion.json" in allowed
    assert "identity/web_agent_completion.json" not in required
    with pytest.raises(
        RuntimeError,
        match="BLOCK_FACTORFORGE_CONSOLE_AGENT_DELIVERABLE_MISSING:.*missing:identity/web_execution_ledger.md",
    ):
        _validate_agent_write_boundary_impl(
            workspace,
            before=before,
            allowed=allowed,
            required=required,
        )
    (workspace / "identity").mkdir(parents=True, exist_ok=True)
    (workspace / "identity" / "web_execution_ledger.md").write_text(
        "resumed\n",
        encoding="utf-8",
    )
    _validate_agent_write_boundary_impl(
        workspace,
        before=before,
        allowed=allowed,
        required=required,
    )


def test_agent_write_boundary_mechanism_resume_still_requires_named_memo(tmp_path):
    workspace = tmp_path / "workspace"
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / "ultimate_run_report__REPORT.json"
    )
    _write_json(
        proof_path,
        {
            "status": "PAUSED",
            "main_agent_mechanism_memo": {
                "token": "AWAITING_MAIN_AGENT_MECHANISM_MEMO",
            },
        },
    )
    before = _workspace_file_snapshot(workspace)
    allowed, required = _allowed_agent_write_paths(
        workspace,
        report_id="REPORT",
        resume=True,
        trusted_resume_proof_sha256=_file_sha256(proof_path),
    )
    memo_path = (
        workspace
        / "objects"
        / "research_iteration_master"
        / "main_agent_mechanism_memo__REPORT.json"
    )
    (workspace / "identity").mkdir(parents=True, exist_ok=True)
    (workspace / "identity" / "web_execution_ledger.md").write_text(
        "mechanism memo authored\n",
        encoding="utf-8",
    )
    with pytest.raises(
        RuntimeError,
        match="BLOCK_FACTORFORGE_CONSOLE_AGENT_DELIVERABLE_MISSING:.*missing:objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json",
    ):
        _validate_agent_write_boundary_impl(
            workspace,
            before=before,
            allowed=allowed,
            required=required,
        )
    _write_json(memo_path, {"status": "ready"})
    _validate_agent_write_boundary_impl(
        workspace,
        before=before,
        allowed=allowed,
        required=required,
    )


def test_shared_gateway_resume_artifact_reader_enforces_memo_byte_limit(tmp_path):
    from factor_factory.console.agent_adapter import RESUME_MEMO_MAX_BYTES

    workspace = tmp_path / "workspace"
    relative = "objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json"
    path = workspace / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"memo": "x" * RESUME_MEMO_MAX_BYTES}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="AGENT_RESUME_ARTIFACT_INVALID: file too large"):
        _read_agent_resume_artifact_json(workspace, relative)


def test_runner_health_is_single_flight_cached_under_concurrency(tmp_path):
    class HealthAdapter:
        def __init__(self):
            self.calls = 0

        def healthcheck(self):
            self.calls += 1
            return True

        def stop_all(self):
            return None

    adapter = HealthAdapter()
    _source, _store, service = _service(tmp_path, adapter)
    allocator_calls = 0
    original_validate = service.allocator.validate_ready

    def counted_validate():
        nonlocal allocator_calls
        allocator_calls += 1
        return original_validate()

    service.allocator.validate_ready = counted_validate
    service.start()
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: service.healthcheck(), range(64)))
        assert all(results)
        assert adapter.calls == 1
        assert allocator_calls == 1
    finally:
        service.stop()
