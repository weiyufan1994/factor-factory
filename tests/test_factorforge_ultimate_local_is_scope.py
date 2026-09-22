from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from factor_factory.research_workspace import (
    build_workspace_manifest,
    default_workspace_root,
    workspace_manifest_path,
    write_workspace_manifest,
)
from scripts import run_factorforge_ultimate as ultimate
from factor_factory.code_review_handoff import CodeReviewHandoff
from datetime import datetime, timezone
import hashlib


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_ID = "LOCAL_IS_SCOPE_TEST"
HOST_ENV_KEYS = (
    ultimate.OOS_HOST_TRUST_ROOT_ENV,
    ultimate.OOS_HOST_INSTALLATION_ID_ENV,
    ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
    ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV,
)


@pytest.fixture(autouse=True)
def _no_ambient_host(monkeypatch):
    for key in HOST_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _workspace(tmp_path: Path) -> Path:
    factorforge_root = tmp_path / "factorforge-root"
    workspace = default_workspace_root(
        factorforge_root=factorforge_root,
        factor_id="local-is-factor",
        research_id="local-is-research",
    )
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=factorforge_root,
        factor_id="local-is-factor",
        research_id="local-is-research",
        root_report_id=REPORT_ID,
    )
    write_workspace_manifest(workspace_manifest_path(workspace), manifest)
    return workspace


def _args(monkeypatch: pytest.MonkeyPatch, workspace: Path, *extra: str):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_factorforge_ultimate.py",
            "--report-id",
            REPORT_ID,
            "--factor-workspace",
            str(workspace),
            "--start-step",
            "3",
            "--end-step",
            "6",
            "--council-mode",
            "off",
            "--skip-researcher-packets",
            *extra,
        ],
    )
    return ultimate.parse_args()


def _normal_recovery(*_args, **_kwargs) -> dict:
    return {
        "recovery_required": False,
        "allowed_execution": "NORMAL",
        "artifact_refs": [],
        "finalization_receipt_present": False,
    }


def _install_local_runtime_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_command: str | None = None,
    materialize_artifacts: bool = False,
) -> list[tuple[str, list[str], dict[str, str]]]:
    calls: list[tuple[str, list[str], dict[str, str]]] = []
    monkeypatch.setattr(
        ultimate,
        "resolve_research_organization_gate",
        lambda **_kwargs: {"status": "not_required"},
    )
    monkeypatch.setattr(
        ultimate,
        "resolve_research_organization_runtime_gate",
        lambda **_kwargs: {"status": "off", "formal_independence_verified": False},
    )
    monkeypatch.setattr(ultimate, "web_factor_proof_oos_recovery_state", _normal_recovery)
    monkeypatch.setattr(
        ultimate,
        "run_state_reuse_gate",
        lambda **_kwargs: {"required": False, "status": "not_applicable"},
    )
    monkeypatch.setattr(ultimate, "run_post_step5_epistemic_shadow_nonblocking", lambda **_kwargs: None)
    # These orchestration tests must never export their synthetic studies to
    # the real repo knowledge store or refresh the user's default index.
    for hook in (
        "record_research_knowledge_maintenance_nonblocking",
        "run_post_step6_knowledge_refresh_nonblocking",
    ):
        monkeypatch.setattr(ultimate, hook, lambda **_kwargs: {"status": "SKIPPED_TEST"})

    def forbidden_host_access(*_args, **_kwargs):
        raise AssertionError("local IS execution must not access a Host incident guard")

    monkeypatch.setattr(ultimate, "oos_exposure_private_registry_guard", forbidden_host_access)
    monkeypatch.setattr(ultimate, "formal_oos_incident_reasons", forbidden_host_access)

    def fake_run(name, command, *, cwd, env, dry_run=False):
        assert dry_run is False
        calls.append((name, list(command), dict(env)))
        code = 1 if name == fail_command else 0
        if materialize_artifacts and code == 0 and name in ("run_step4", "run_step5", "run_step6"):
            workspace = Path(env["FACTORFORGE_ROOT"])
            manifest = json.loads((workspace / "objects/runtime_context" / f"factorforge_runtime_manifest__{REPORT_ID}.json").read_text())
            outputs = manifest["step_io"]["step" + name[-1]]["outputs"]

            def write(path, payload):
                path = Path(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload))

            for key, raw in outputs.items():
                if key == "research_journal":
                    continue
                if key == "archive_root":
                    Path(raw).mkdir(parents=True, exist_ok=True)
                else:
                    write(raw, {"report_id": REPORT_ID, "fixture_object": key, "synthetic": True})
            if name == "run_step4":
                values = Path(manifest["runs"]["factor_values_csv"])
                values.parent.mkdir(parents=True, exist_ok=True)
                values.write_text("index,value\n0,1\n")
                write(manifest["runs"]["run_metadata"], {"synthetic": True})
                write(outputs["factor_run_master"], {"report_id": REPORT_ID, "synthetic": True,
                      "output_paths": [str(values)], "evaluation_results": {"backend_runs": [
                          {"status": "success", "payload_path": outputs["self_quant_payload"]}]}})
            elif name == "run_step5":
                archived = Path(outputs["archive_root"]) / "synthetic-evidence.json"
                write(archived, {"synthetic": True, "evidence": "minimal retained file"})
                write(outputs["factor_case_master"], {"report_id": REPORT_ID, "synthetic": True,
                                                    "evidence": {"archive_paths": [str(archived)]}})
        now = ultimate.utc_now()
        return ultimate.CommandResult(
            name=name,
            command=list(command),
            cwd=str(cwd),
            started_at_utc=now,
            finished_at_utc=now,
            returncode=code,
            stderr_tail="injected failure" if code else "",
            status="FAIL" if code else "PASS",
        )

    monkeypatch.setattr(ultimate, "run_command", fake_run)
    return calls


def _proof(workspace: Path) -> dict:
    path = workspace / "objects" / "runtime_context" / f"ultimate_run_report__{REPORT_ID}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _managed_review(workspace: Path, *, ready: bool, end_step: str = "5") -> CodeReviewHandoff:
    """Synthetic state fixture; runtime commands remain explicitly mocked."""
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    spec = workspace / "objects/factor_spec_master" / f"factor_spec_master__{REPORT_ID}.json"
    handoff = workspace / "objects/handoff" / f"handoff_to_step4__{REPORT_ID}.json"
    code, source = workspace / "fixture.py", workspace / "source.md"
    code.write_text("raise RuntimeError('orchestration must never execute fixture factor')\n")
    source.write_text("Synthetic source; no market or return data.\n")
    write(spec, {"report_id": REPORT_ID})
    write(handoff, {"factor_impl_ref": str(code)})
    write(workspace / "objects/data_prep_master" / f"data_prep_master__{REPORT_ID}.json", {"synthetic": True})
    flow = CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT)
    prepared = flow.prepare({
        "issue_id": "review", "summary": "Synthetic timing review", "author_id": "author", "reviewer_id": "reviewer",
        "origin_step": "3b", "spec": str(spec), "handoff": str(handoff), "helpers": [],
        "materials_note": "Fixture code has no invoked helpers",
        "context_files": [{"role": "source", "path": str(source)}],
        "resume": {"start_step": "4", "end_step": end_step, "reason": "Continue from reviewed implementation within synthetic scope"},
    })
    if ready:
        request_id = prepared["request_id"]
        flow.delivery(request_id, "begin", "synthetic fixture intent")
        flow.delivery(request_id, "sent", "synthetic fixture receipt; not a real message")
        now = lambda: datetime.now(timezone.utc).isoformat()
        record = {"report_id": REPORT_ID, "request_id": request_id, "author_id": "author", "reviewer_id": "reviewer",
                  "reviewed_at": now(), "decision": "proceed", "summary": "Synthetic fixture approval",
                  "findings": [], "reviewed_files": prepared["request"]["reviewed_files"]}
        result_path = workspace / "review-result.json"
        write(result_path, record)
        flow.receive_review(request_id, result_path)
        log = workspace / "test.log"
        log.write_text("Synthetic fixture log; no factor test was executed\n")
        tests_path = workspace / "tests-result.json"
        write(tests_path, {"status": "PASS", "started_at": now(), "completed_at": now(),
                           "tested_files": record["reviewed_files"],
                           "evidence": [{"path": str(log), "sha256": hashlib.sha256(log.read_bytes()).hexdigest()}]})
        assert flow.record_tests(request_id, tests_path)["status"] == "READY"
    return flow


def test_managed_pending_review_blocks_actual_wrapper_command(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, materialize_artifacts=True)
    _managed_review(workspace, ready=False)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "4")
    assert ultimate._run_formal_ultimate(args) == 1
    assert "run_step4" not in [name for name, _, _ in calls]
    assert _proof(workspace)["failure"]["executed"] is False


def test_managed_wrapper_resumes_step5_without_regenerating_or_rerunning_step4(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, materialize_artifacts=True)
    _managed_review(workspace, ready=True)
    first = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "4")
    assert ultimate._run_formal_ultimate(first) == 0
    assert (workspace / "objects/factor_run_master" / f"factor_run_master__{REPORT_ID}.json").is_file()
    flow = CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT)
    assert flow.status()["resume"]["start_step"] == "5"
    calls.clear()
    second = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "5", "--end-step", "5")
    assert ultimate._run_formal_ultimate(second) == 0
    assert [name for name, _, _ in calls] == ["validate_research_protocol_pre_council", "run_step5", "validate_step5"]
    calls.clear()
    assert ultimate._run_formal_ultimate(second) == 0
    assert [name for name, _, _ in calls] == ["validate_research_protocol_pre_council"]
    results = _proof(workspace)["commands"]
    assert all(row["reused_from_code_review_journal"] for row in results if row["name"] in ("run_step5", "validate_step5"))
    assert CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).status()["resume"] is None


def test_managed_step4_failure_is_durable_and_cannot_auto_retry(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, fail_command="run_step4", materialize_artifacts=True)
    _managed_review(workspace, ready=True)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "4")
    assert ultimate._run_formal_ultimate(args) == 1
    saved = CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).status()
    assert saved["request"]["execution"]["4"]["run_step4"]["returncode"] == 1
    calls.clear()
    assert ultimate._run_formal_ultimate(args) == 1
    assert "run_step4" not in [name for name, _, _ in calls]


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_managed_wrapper_blocks_step5_after_step4_artifact_changes(tmp_path, monkeypatch, change):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, materialize_artifacts=True)
    _managed_review(workspace, ready=True)
    first = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "4")
    assert ultimate._run_formal_ultimate(first) == 0
    artifact = workspace / "objects/factor_run_master" / f"factor_run_master__{REPORT_ID}.json"
    if change == "delete":
        artifact.unlink()
    else:
        artifact.write_text('{"synthetic": "changed after validation"}')
    calls.clear()
    second = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "5", "--end-step", "5")
    assert ultimate._run_formal_ultimate(second) == 1
    assert [name for name, _, _ in calls] == ["validate_research_protocol_pre_council"]
    failure = _proof(workspace)["failure"]
    assert failure["blocked_before"] == "run_step5" and failure["executed"] is False
    assert CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).status()["artifact_recovery"]["step"] == "4"


def test_managed_wrapper_zero_return_without_artifacts_cannot_pass(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, materialize_artifacts=False)
    _managed_review(workspace, ready=True)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "4")
    assert ultimate._run_formal_ultimate(args) == 1
    assert "validate_step4" not in [name for name, _, _ in calls]
    state = CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).status()
    assert state["status"] == "BLOCK" and state["artifact_recovery"]["step"] == "4"


def test_managed_step6_native_council_pause_attach_and_resume(tmp_path, monkeypatch):
    """Real wrapper/manifest, disable, result discovery and attachment; synthetic
    producers and command validators. No agent, finance or Council acceptance.
    """
    workspace = _workspace(tmp_path)
    native_run = ultimate.run_command
    calls = _install_local_runtime_stubs(monkeypatch, materialize_artifacts=True)
    stage_stub = ultimate.run_command
    _managed_review(workspace, ready=True, end_step="6")
    rim = workspace / "objects/research_iteration_master"
    iteration = rim / f"research_iteration_master__{REPORT_ID}.json"
    council = rim / "revision_council" / REPORT_ID
    dispatch = council / f"dispatch_manifest__{REPORT_ID}.json"
    result_path = council / "agent_results" / f"agent_result__{REPORT_ID}__synthetic.json"
    provisional = workspace / "objects/handoff" / f"handoff_to_step3b__{REPORT_ID}.json"

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def native_attachment(env):
        return native_run("attach_revision_council_to_step6", [
            sys.executable, "-B", "skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py",
            "--report-id", REPORT_ID,
        ], cwd=REPO_ROOT, env=env, dry_run=False)

    def stub(name, command, *, cwd, env, dry_run=False):
        if name == "run_step6":
            # Synthetic Step6 producer, preserving the actual attachment on
            # resume. Its engine is outside this orchestration regression.
            calls.append((name, list(command), dict(env)))
            if not iteration.exists():
                write(iteration, {"report_id": REPORT_ID, "synthetic": True, "loop_research_brief": {
                    "json_path": "not-produced-in-orchestration-test.json",
                    "markdown_path": "not-produced-in-orchestration-test.md"}})
                write(provisional, {"report_id": REPORT_ID, "synthetic": "provisional handoff"})
            now = ultimate.utc_now()
            return ultimate.CommandResult(name=name, command=list(command), cwd=str(cwd),
                started_at_utc=now, finished_at_utc=now, returncode=0, status="PASS")
        result = stage_stub(name, command, cwd=cwd, env=env, dry_run=dry_run)
        if name == "build_revision_council_packet":
            write(council / f"revision_council_packet__{REPORT_ID}.json", {"report_id": REPORT_ID, "synthetic": True})
        elif name == "build_agentic_council_dispatch_manifest":
            write(dispatch, {"report_id": REPORT_ID,
                "dispatch_manifest_version": "factorforge_agentic_council_dispatch_manifest_v1",
                "agent_tasks": [{"task_id": "synthetic", "required": True, "expected_result_path": str(result_path)}]})
        elif name == "finalize_agentic_council_dispatch":
            # The enclosing Council validation commands remain explicit stubs;
            # its real attachment writer must update the iteration successfully.
            attached = native_attachment(env)
            assert attached.returncode == 0, attached.stdout_tail + attached.stderr_tail
        return result

    monkeypatch.setattr(ultimate, "run_command", stub)
    first = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "6",
                  "--council-mode", "agentic", "--agentic-council-executor", "dispatch_manifest")
    assert ultimate._run_formal_ultimate(first) == 0
    paused = _proof(workspace)
    assert paused["status"] == "PAUSED" and paused["revision_council"]["status"] == "awaiting_agent_results"
    assert paused["revision_council"]["provisional_step3b_handoff_policy"]["disabled"] is True
    assert not provisional.exists()
    assert (council / f"provisional_step3b_handoff_disabled_by_council__{REPORT_ID}.json").is_file()
    flow = CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT)
    state = flow.status()
    assert state["status"] == "READY" and state["remaining_steps"] == ["6"]
    assert state["step6_followup"] and "6" not in state["request"]["execution"]
    journal_before = flow.path.read_bytes()
    assert ultimate.agentic_dispatch_required_results_present(workspace, REPORT_ID) is False

    # Deliver a clearly synthetic result through the existing result directory.
    # This fixture does not assert semantic validity or agent independence.
    write(result_path, {"report_id": REPORT_ID, "task_id": "synthetic", "agent_role": "fixture",
                       "producer": "local_mock_agentic_contract"})
    write(council / f"revision_council_summary__{REPORT_ID}.json", {
        "report_id": REPORT_ID, "human_approval_required": True,
        "candidate_proposals": [{"proposal_id": "synthetic", "producer": "local_mock_agentic_contract"}],
    })
    assert ultimate.agentic_dispatch_required_results_present(workspace, REPORT_ID) is True
    env = next(env for name, _, env in calls if name == "run_step6")
    old_iteration = iteration.read_bytes()
    attached = native_attachment(env)
    assert attached.returncode == 0, attached.stdout_tail + attached.stderr_tail
    assert iteration.read_bytes() != old_iteration
    assert json.loads(iteration.read_text())["revision_council_ref"]["enabled"] is True
    assert CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).status()["status"] == "READY"

    calls.clear()
    resume = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "6", "--end-step", "6",
                   "--council-mode", "agentic", "--agentic-council-executor", "dispatch_manifest")
    assert ultimate._run_formal_ultimate(resume) == 0
    assert "finalize_agentic_council_dispatch" in [name for name, _, _ in calls]
    assert not any(name in ("run_step4", "run_step5", "run_step3b") for name, _, _ in calls)
    completed = _proof(workspace)
    assert completed["status"] == "PASS" and completed["revision_council"]["attached"] is True
    assert completed["revision_council"]["status"] == "completed"
    assert all(not row.get("reused_from_code_review_journal") for row in completed["commands"] if row["name"].endswith("step6"))
    assert CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).path.read_bytes() == journal_before

    # Native Step6 ownership must not bypass a changed Step5 prerequisite.
    manifest = json.loads((workspace / "objects/runtime_context" / f"factorforge_runtime_manifest__{REPORT_ID}.json").read_text())
    evaluation = Path(manifest["objects"]["factor_evaluation"])
    evaluation.write_bytes(evaluation.read_bytes() + b"\n ")
    calls.clear()
    assert ultimate._run_formal_ultimate(resume) == 1
    assert "run_step6" not in [name for name, _, _ in calls]
    assert _proof(workspace)["failure"]["blocked_before"] == "run_step6"
    assert CodeReviewHandoff(workspace, REPORT_ID, REPO_ROOT).status()["artifact_recovery"]["step"] == "5"


def test_local_is_only_executes_step3_to_6_without_host_or_oos_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    for key in HOST_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    calls = _install_local_runtime_stubs(monkeypatch)

    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only")) == 0

    assert [name for name, _command, _env in calls] == [
        "validate_research_protocol_pre_council",
        "run_step3",
        "validate_step3",
        "run_step3b",
        "validate_step3b",
        "validate_step2_code_review",
        "run_step4",
        "validate_step4",
        "run_step5",
        "validate_step5",
        "run_step6",
        "validate_step6",
    ]
    for name, command, env in calls:
        assert name != "finalize_web_factor_proof"
        assert "finalize_factorforge_web_factor_proof.py" not in command
        assert all(key not in env for key in HOST_ENV_KEYS)
        assert env["FACTORFORGE_LOCAL_IS_ONLY"] == "1"
    proof = _proof(workspace)
    assert proof["status"] == "PASS"
    assert proof["proof_semantics"] == "local_is_research_execution"
    assert proof["formal_proof_eligible"] is False
    assert proof["current_formal_authority_verified"] is False
    assert proof["factor_verdict"] == "NOT_ISSUED"
    assert proof["oos_access_allowed"] is False
    assert proof["official_promotion_allowed"] is False


def test_local_is_command_failure_cannot_finish_as_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, fail_command="run_step4")

    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only")) == 1

    assert [name for name, _command, _env in calls][-1] == "run_step4"
    proof = _proof(workspace)
    assert proof["status"] == "FAIL"
    assert proof["formal_proof_eligible"] is False
    assert proof["failure"] == {"command": "run_step4", "returncode": 1}


@pytest.mark.parametrize("step", ["3", "3b", "4", "5", "6"])
def test_segmented_local_run_checks_protocol_before_work(tmp_path, monkeypatch, step):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", step, "--end-step", step)
    assert ultimate._run_formal_ultimate(args) == 0
    names = [name for name, _, _ in calls]
    assert names[0] == "validate_research_protocol_pre_council"
    assert _proof(workspace)["formal_command_contract"]["research_protocol_verifier_required"] is True
    if step == "4":
        assert names.index("validate_step2_code_review") < names.index("run_step4")
    else:
        assert "validate_step2_code_review" not in names


@pytest.mark.parametrize("end", ["2", "4"])
def test_step2_can_author_records_before_later_preflight(tmp_path, monkeypatch, end):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "2", "--end-step", end)
    assert ultimate._run_formal_ultimate(args) == 0
    names = [name for name, _, _ in calls]
    assert names[:2] == ["run_step2", "validate_step2"]
    if end == "2":
        assert names == ["run_step2", "validate_step2"]
    else:
        assert names[2] == "validate_research_protocol_pre_council"
        assert names.index("validate_step2_code_review") < names.index("run_step4")


@pytest.mark.parametrize("step", ["3", "3b", "4", "5"])
def test_segmented_local_protocol_failure_stops_before_compute(tmp_path, monkeypatch, step):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, fail_command="validate_research_protocol_pre_council")
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", step, "--end-step", step)
    assert ultimate._run_formal_ultimate(args) == 1
    assert [name for name, _, _ in calls] == ["validate_research_protocol_pre_council"]
    assert _proof(workspace)["failure"]["command"] == "validate_research_protocol_pre_council"


def test_local_code_review_failure_stops_before_step4(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch, fail_command="validate_step2_code_review")
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "5")
    assert ultimate._run_formal_ultimate(args) == 1
    assert [name for name, _, _ in calls] == [
        "validate_research_protocol_pre_council", "validate_step2_code_review",
    ]
    assert _proof(workspace)["failure"]["command"] == "validate_step2_code_review"
    command = calls[-1][1]
    assert command[command.index("--workspace-root") + 1] == str(workspace)
    assert command[command.index("--repo-root") + 1] == str(REPO_ROOT)


def test_real_protocol_cli_rejects_missing_records_before_step3(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    real_run = ultimate.run_command
    calls = _install_local_runtime_stubs(monkeypatch)
    stub_run = ultimate.run_command

    def run_preflight(name, command, **kwargs):
        if name == "validate_research_protocol_pre_council":
            calls.append((name, list(command), dict(kwargs["env"])))
            return real_run(name, command, **kwargs)
        return stub_run(name, command, **kwargs)

    monkeypatch.setattr(ultimate, "run_command", run_preflight)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "3", "--end-step", "3b")
    assert ultimate._run_formal_ultimate(args) == 1
    assert [name for name, _, _ in calls] == ["validate_research_protocol_pre_council"]
    assert _proof(workspace)["failure"]["command"] == "validate_research_protocol_pre_council"


def test_real_review_cli_rejects_missing_review_before_step4(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    real_run = ultimate.run_command
    calls = _install_local_runtime_stubs(monkeypatch)
    stub_run = ultimate.run_command

    def run_review(name, command, **kwargs):
        if name == "validate_step2_code_review":
            calls.append((name, list(command), dict(kwargs["env"])))
            return real_run(name, command, **kwargs)
        return stub_run(name, command, **kwargs)

    monkeypatch.setattr(ultimate, "run_command", run_review)
    args = _args(monkeypatch, workspace, "--local-is-only", "--start-step", "4", "--end-step", "4")
    assert ultimate._run_formal_ultimate(args) == 1
    assert [name for name, _, _ in calls] == [
        "validate_research_protocol_pre_council", "validate_step2_code_review",
    ]
    proof = _proof(workspace)
    assert proof["failure"]["command"] == "validate_step2_code_review"
    assert "BLOCK" in proof["commands"][-1]["stdout_tail"]


@pytest.mark.parametrize(
    "extra, token",
    [
        (("--sealed-oos-carrier", "/private/carrier"), "BLOCK_FACTORFORGE_LOCAL_IS_HOST_OR_OOS_ARGUMENT"),
        (("--expected-host-trust-manifest-sha256", "a" * 64), "BLOCK_FACTORFORGE_LOCAL_IS_HOST_OR_OOS_ARGUMENT"),
    ],
)
def test_local_is_rejects_oos_or_host_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], extra: tuple[str, ...], token: str
) -> None:
    workspace = _workspace(tmp_path)
    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only", *extra)) == 1
    assert token in capsys.readouterr().out


def test_local_is_rejects_existing_oos_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    _install_local_runtime_stubs(monkeypatch)
    monkeypatch.setattr(
        ultimate,
        "web_factor_proof_oos_recovery_state",
        lambda *_args, **_kwargs: {
            "recovery_required": True,
            "allowed_execution": "FINALIZER_ONLY",
            "artifact_refs": ["objects/oos/recovery.json"],
            "finalization_receipt_present": False,
        },
    )

    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only")) == 1
    assert "BLOCK_FACTORFORGE_LOCAL_IS_OOS_RECOVERY_FORBIDDEN" in capsys.readouterr().out


def test_hosted_runs_still_require_complete_host_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    for key in HOST_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    _install_local_runtime_stubs(monkeypatch)

    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace)) == 1
    assert "BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_REQUIRED" in capsys.readouterr().out


@pytest.mark.parametrize("scope", [(), ("--local-is-only",)])
def test_partial_host_pair_remains_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], scope: tuple[str, ...]
) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setenv(ultimate.OOS_HOST_TRUST_ROOT_ENV, "/private/host-trust")
    monkeypatch.delenv(ultimate.OOS_HOST_INSTALLATION_ID_ENV, raising=False)
    monkeypatch.delenv(ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV, raising=False)
    monkeypatch.delenv(ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV, raising=False)
    _install_local_runtime_stubs(monkeypatch)

    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, *scope)) == 1
    assert "BLOCK_FACTORFORGE_WEB_OOS_HOST_FINALIZER_CREDENTIALS_PARTIAL" in capsys.readouterr().out


def test_complete_incidental_host_pair_is_not_opened_in_local_scope(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv(ultimate.OOS_HOST_TRUST_ROOT_ENV, "/does-not-exist/private-trust")
    monkeypatch.setenv(ultimate.OOS_HOST_INSTALLATION_ID_ENV, "not-a-local-dependency")
    calls = _install_local_runtime_stubs(monkeypatch)
    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only")) == 0
    assert calls
    assert all(not set(env).intersection(HOST_ENV_KEYS) for _, _, env in calls)


@pytest.mark.parametrize("as_broken_link", [False, True])
def test_hosted_workspace_is_not_reclassified_as_local(tmp_path, monkeypatch, capsys, as_broken_link):
    workspace = _workspace(tmp_path)
    marker = workspace / "identity" / "data_catalog_summary.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if as_broken_link:
        marker.symlink_to(tmp_path / "absent")
    else:
        marker.write_text("{}", encoding="utf-8")
    calls = _install_local_runtime_stubs(monkeypatch)
    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only")) == 1
    assert not calls
    assert "BLOCK_FACTORFORGE_LOCAL_IS_HOSTED_WORKSPACE" in capsys.readouterr().out


def test_complete_oos_finalization_is_not_local_research(tmp_path, monkeypatch, capsys):
    workspace = _workspace(tmp_path)
    calls = _install_local_runtime_stubs(monkeypatch)
    monkeypatch.setattr(
        ultimate, "web_factor_proof_oos_recovery_state",
        lambda *_args, **_kwargs: {**_normal_recovery(), "finalization_receipt_present": True},
    )
    assert ultimate._run_formal_ultimate(_args(monkeypatch, workspace, "--local-is-only")) == 1
    assert not calls
    assert "BLOCK_FACTORFORGE_LOCAL_IS_OOS_RECOVERY_FORBIDDEN" in capsys.readouterr().out
