from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
        return AgentRunResult(
            returncode=0,
            agent_id=f"agent-{job.job_id}",
            session_key=f"session-{job.job_id}",
            started_at_utc="2026-08-01T00:00:00Z",
            finished_at_utc="2026-08-01T00:01:00Z",
            stdout_tail="complete",
            stderr_tail="",
            result_path=str(workspace / "identity" / "fake-agent-result.json"),
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
        return AgentRunResult(
            0,
            f"agent-{job.job_id}",
            f"session-{job.job_id}",
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:01:00Z",
            "paused",
            "",
            str(workspace / "identity" / "fake-agent-result.json"),
        )


class _EscapingAdapter(_TerminalRejectAdapter):
    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        result = super().run(job, worktree=worktree, workspace=workspace, resume=resume)
        (worktree / "outside-factor-workspace.txt").write_text("pollution\n", encoding="utf-8")
        return result


class _CredentialEchoAdapter(_TerminalRejectAdapter):
    secret = "temporary-session-value-for-run-service-test"

    def __init__(self) -> None:
        self.cleared = False

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


class _EarlyRuntimeFailureAdapter:
    def run(self, job, *, worktree: Path, workspace: Path, resume: bool):
        raise RuntimeError(
            "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_UNAVAILABLE: "
            "container agent initialization failed"
        )

    def denied_secret_values(self, job_id: str):
        raise RuntimeError("task denied-secret registry is missing")

    def clear_denied_secrets(self, job_id: str):
        return None


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


def test_write_outside_factor_workspace_blocks_even_with_formal_reject(tmp_path):
    _source, store, service = _service(tmp_path, _EscapingAdapter())
    job = service.submit(_request("Escaping factor"))
    service.run_once()
    blocked = store.get_job(job.job_id)

    assert blocked.execution_status == "BLOCKED"
    assert blocked.factor_verdict == "BLOCK"
    assert blocked.error_code == "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED"


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


def test_service_redacts_exact_temporary_credentials_and_clears_registry(
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
    assert adapter.cleared is True
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
