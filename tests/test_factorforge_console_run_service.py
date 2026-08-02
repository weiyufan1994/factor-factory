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

from factor_factory.console.run_service import ResearchRunService as _ResearchRunService
from factor_factory.console.run_service import (
    _allowed_agent_write_paths,
    _configure_host_formal_python_environment,
    _validate_agent_write_boundary as _validate_agent_write_boundary_impl,
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
            "attestation_id": f"attestations/{job.job_id}.json",
            "attestation_sha256": "attestation-hash",
            "receipt_id": f"jobs/{job.job_id}/formal-execution/receipt.json",
            "receipt_sha256": "receipt-hash",
        }

    monkeypatch.setattr(
        module.ResearchRunService,
        "_validate_trusted_resume_context",
        trusted_resume_stub,
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
    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        from factor_factory.console.agent_adapter import AgentRunResult

        report_id = job.report_id
        identity = {"report_id": report_id, "factor_id": job.factor_id, "research_id": job.research_id}
        _write_json(
            workspace / "objects" / "runtime_context" / f"ultimate_run_report__{report_id}.json",
            {
                **identity,
                "status": "PASS",
                "formal_proof_eligible": False,
                "revision_council": {"status": "awaiting_agent_results"},
            },
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

    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        self.calls += 1
        delegate = self._forging if resume else self._paused
        return delegate.run(
            job,
            worktree=worktree,
            workspace=workspace,
            resume=resume,
        )


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


def test_host_execution_attestation_is_outside_agent_workspace(tmp_path):
    from factor_factory.console.agent_adapter import AgentRunResult
    from factor_factory.console.ultimate_reader import UltimateRunSummary

    _source, store, service = _service(tmp_path, _TerminalRejectAdapter())
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
    }

    service._begin_private_execution(job, resume=False)
    relative = _ORIGINAL_WRITE_HOST_ATTESTATION(
        service,
        job=job,
        workspace=workspace,
        summary=summary,
        agent_result=agent_result,
        web_materialization={"formula_hash": "formula-hash"},
        formal_execution=formal_execution,
    )
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
    assert payload["evidence_hashes"]["wrapper_report"]["sha256"]
    trusted = _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
        service,
        job,
        worktree=allocation.worktree_path,
        workspace=workspace,
    )
    assert trusted["start_step"] == "6"
    assert trusted["ultimate_proof_sha256"] == _file_sha256(evidence)

    resumed_ultimate_argv = list(ultimate_argv)
    resumed_ultimate_argv[resumed_ultimate_argv.index("3")] = "6"
    resumed_commands = [
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
            "argv": resumed_ultimate_argv,
            "argv_sha256": stable_json_hash(resumed_ultimate_argv),
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
    )
    resumed_relative = _ORIGINAL_WRITE_HOST_ATTESTATION(
        service,
        job=job,
        workspace=workspace,
        summary=summary,
        agent_result=agent_result,
        web_materialization={"formula_hash": "formula-hash"},
        formal_execution=resumed_formal_execution,
    )
    assert resumed_relative != relative
    assert attestation.is_file()
    resumed_trusted = _ORIGINAL_VALIDATE_TRUSTED_RESUME_CONTEXT(
        service,
        job,
        worktree=allocation.worktree_path,
        workspace=workspace,
    )
    assert resumed_trusted["start_step"] == "6"

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

    _source, _store, service = _service(tmp_path, _TerminalRejectAdapter())
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
        if argv[1] == "scripts/run_factorforge_ultimate.py":
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
    assert calls[0][0][1] == "scripts/materialize_factorforge_web_research.py"
    assert calls[1][0][1] == "scripts/run_factorforge_ultimate.py"
    assert calls[1][0][calls[1][0].index("--start-step") + 1] == "3"
    assert calls[0][1]["env"]["AWS_ACCESS_KEY_ID"] == "HOSTACCESSKEYFORTEST"
    assert calls[0][1]["env"]["AWS_SESSION_TOKEN"] == "host-session-token-for-test"
    assert "FACTORFORGE_CONSOLE_INVITE_PASSWORD" not in calls[0][1]["env"]
    assert "DEEPSEEK_API_KEY" not in calls[0][1]["env"]
    assert calls[1][1]["env"]["AWS_EC2_METADATA_DISABLED"] == "true"
    receipt_path = service.config.state_root / receipt["receipt_id"]
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["version"] == "factorforge_console_host_formal_execution_v2"
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
        match="missing:identity/web_execution_ledger.md",
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
        match="missing:identity/web_execution_ledger.md",
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
        match="missing:objects/research_iteration_master/main_agent_mechanism_memo__REPORT.json",
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
