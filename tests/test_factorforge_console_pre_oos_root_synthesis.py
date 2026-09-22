from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from factor_factory.console.agent_adapter import AgentRunResult
from factor_factory.console.container_agent_adapter import (
    _build_pre_oos_root_synthesis_prompt,
    _validate_pre_oos_root_synthesis_task,
)
from factor_factory.console.models import ResearchJob, ResearchRequest
from factor_factory.console.run_service import (
    BLOCK_AGENT_RUNTIME_UNAVAILABLE,
    BLOCK_RESUME_TRUST_INVALID,
    RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS,
    ResearchRunService,
    _allowed_agent_write_paths,
    _classify_resume_route,
    _pre_oos_root_synthesis_runner,
    _sha256,
    _validate_agent_write_boundary,
    _workspace_file_snapshot,
    _write_pre_oos_root_synthesis_task,
)
from factor_factory.console.web_research_plan import stable_json_hash
from tests.test_factorforge_pre_oos_council_outcome import (
    REPORT_ID,
    _fixture,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _root_pause(tmp_path: Path):
    workspace = tmp_path / "workspace"
    synthesis, synthesis_path = _fixture(workspace)
    synthesis_path.unlink()
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}.json"
    )
    proof = {
        "status": "PAUSED",
        "proof_semantics": "awaiting_agent_authored_pre_oos_root_synthesis",
        "final_outcome": "awaiting_pre_oos_council_root_synthesis",
        "failure": None,
        "factor_verdict": "NOT_ISSUED",
        "formal_proof_eligible": False,
        "revision_council": {
            "requested_mode": "agentic",
            "status": "awaiting_root_synthesis",
            "effective_mode": "agentic_dispatch_manifest",
            "evidence_view": "PURGED_IS_ONLY",
            "oos_state": "SEALED_NOT_ACCESSED",
            "root_synthesis_path": str(synthesis_path),
            "commands": [
                {
                    "name": "merge_revision_council",
                    "status": "PASS",
                    "returncode": 0,
                }
            ],
        },
    }
    _write_json(proof_path, proof)
    job = ResearchJob(
        job_id="job_1234567890",
        factor_id="negative_pv_shape",
        research_id="research_root_synthesis",
        report_id=REPORT_ID,
        request=ResearchRequest(title="root synthesis", hypothesis="test routes"),
        base_commit="a" * 40,
    )
    return workspace, job, proof, proof_path, synthesis, synthesis_path


def _task(tmp_path: Path):
    workspace, job, proof, proof_path, synthesis, synthesis_path = _root_pause(
        tmp_path
    )
    task = _write_pre_oos_root_synthesis_task(
        job,
        workspace,
        trusted_resume_proof_sha256=_sha256(proof_path),
        attempt_id="resume_" + "1" * 32,
    )
    return workspace, job, proof, proof_path, synthesis, synthesis_path, task


def test_root_synthesis_resume_classifier_requires_exact_wrapper_pause(tmp_path):
    workspace, _job, proof, proof_path, _synthesis, synthesis_path = _root_pause(
        tmp_path
    )

    route = _classify_resume_route(
        workspace,
        REPORT_ID,
        start_step="6",
        trusted_proof_sha256=_sha256(proof_path),
    )
    assert route.kind == RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS
    assert route.pause_state == "awaiting_root_synthesis"

    for mutate in (
        lambda payload: payload.update(
            proof_semantics="awaiting_pre_oos_revision_council_agent_results"
        ),
        lambda payload: payload["revision_council"].update(
            evidence_view="OOS_VISIBLE"
        ),
        lambda payload: payload["revision_council"].update(
            root_synthesis_path=str(synthesis_path.with_name("alias.json"))
        ),
    ):
        candidate = json.loads(json.dumps(proof))
        mutate(candidate)
        _write_json(proof_path, candidate)
        with pytest.raises(
            RuntimeError,
            match="pre-OOS root synthesis pause binding is invalid",
        ):
            _classify_resume_route(
                workspace,
                REPORT_ID,
                start_step="6",
                trusted_proof_sha256=_sha256(proof_path),
            )


def test_root_synthesis_task_binds_prompt_inputs_and_only_canonical_output(tmp_path):
    (
        workspace,
        _job,
        _proof,
        proof_path,
        synthesis,
        synthesis_path,
        task,
    ) = _task(tmp_path)
    packet_path = workspace / task.task_packet_relative
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    unsigned = dict(packet)
    digest = unsigned.pop("content_sha256")
    assert digest == stable_json_hash(unsigned)
    assert packet["trusted_pause_ref"]["sha256"] == _sha256(proof_path)
    assert packet["required_output"]["path"] == task.expected_output_relative
    assert packet["permissions"]["agent_workspace_write_paths"] == [
        task.expected_output_relative
    ]
    assert packet["permissions"]["oos_access_allowed"] is False
    assert packet["permissions"]["host_transition_allowed"] is False
    assert len(packet["route_selection_options"]) == 2
    assert {
        option["outcome"] for option in packet["route_selection_options"]
    } == {"MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"}
    assert packet["fixed_evidence_bindings"]["raw_result_refs"] == [
        option["result_ref"] for option in packet["route_selection_options"]
    ]

    before = _workspace_file_snapshot(workspace)
    allowed, required = _allowed_agent_write_paths(
        workspace,
        report_id=REPORT_ID,
        resume=True,
        trusted_resume_proof_sha256=_sha256(proof_path),
        pre_oos_root_synthesis_task=task,
    )
    assert allowed == required == {task.expected_output_relative}
    _write_json(synthesis_path, synthesis)
    _validate_agent_write_boundary(
        workspace,
        before=before,
        allowed=allowed,
        required=required,
    )

    extra = workspace / "objects" / "evo_v2" / REPORT_ID / "forged.json"
    _write_json(extra, {"forged": True})
    with pytest.raises(RuntimeError, match="AGENT_WRITE_SCOPE_INVALID"):
        _validate_agent_write_boundary(
            workspace,
            before=before,
            allowed=allowed,
            required=required,
        )


def test_root_synthesis_adapter_revalidates_packet_and_every_frozen_input(tmp_path):
    workspace, job, _proof, _proof_path, _synthesis, _path, task = _task(
        tmp_path
    )
    packet = _validate_pre_oos_root_synthesis_task(job, workspace, task)
    assert packet["attempt_id"] == task.attempt_id

    source_relative, _digest = task.read_only_input_sha256[0]
    source = workspace / source_relative
    source.write_text(source.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="root synthesis input changed"):
        _validate_pre_oos_root_synthesis_task(job, workspace, task)


def test_root_synthesis_prompt_uses_private_output_and_forbids_workspace_write(
    tmp_path,
):
    workspace, _job, _proof, _proof_path, _synthesis, _path, task = _task(
        tmp_path
    )
    private = tmp_path / "private" / "root.json"
    prompt = _build_pre_oos_root_synthesis_prompt(
        workspace=workspace,
        task=task,
        private_output_path=private,
    )
    assert str(private) in prompt
    assert str(workspace / task.task_packet_relative) in prompt
    assert "never write the workspace directly" in prompt
    assert "majority voting, scoring, ranking, or aggregation" in prompt


def test_missing_root_synthesis_adapter_capability_fails_closed():
    with pytest.raises(RuntimeError, match=BLOCK_AGENT_RUNTIME_UNAVAILABLE):
        _pre_oos_root_synthesis_runner(SimpleNamespace())


def test_root_synthesis_receipt_binds_prompt_inputs_and_imported_bytes(tmp_path):
    (
        workspace,
        job,
        _proof,
        _proof_path,
        synthesis,
        synthesis_path,
        task,
    ) = _task(tmp_path)
    _write_json(synthesis_path, synthesis)
    state_root = tmp_path / "state"
    receipt_path = state_root / "jobs" / job.job_id / "root_synthesis.json"
    agent_id = "root-agent"
    session_key = "root-session"
    engine_commit = "b" * 40
    receipt = {
        "version": "factorforge_console_pre_oos_root_synthesis_run_v1",
        "job_id": job.job_id,
        "factor_id": job.factor_id,
        "research_id": job.research_id,
        "report_id": job.report_id,
        "agent_id": agent_id,
        "session_key_sha256": hashlib.sha256(session_key.encode()).hexdigest(),
        "resume": True,
        "attempt_id": task.attempt_id,
        "research_base_commit": job.base_commit,
        "engine_commit": engine_commit,
        "trusted_proof_sha256": task.trusted_proof_sha256,
        "task_packet_path": task.task_packet_relative,
        "task_packet_sha256": task.task_packet_sha256,
        "read_only_inputs": [
            {"path": relative, "sha256": digest}
            for relative, digest in task.read_only_input_sha256
        ],
        "expected_output_path": task.expected_output_relative,
        "imported_output_sha256": _sha256(synthesis_path),
        "returncode": 0,
        "error_code": "",
    }
    _write_json(receipt_path, receipt)
    result = AgentRunResult(
        returncode=0,
        agent_id=agent_id,
        session_key=session_key,
        started_at_utc="2026-08-12T00:00:00Z",
        finished_at_utc="2026-08-12T00:01:00Z",
        stdout_tail="",
        stderr_tail="",
        result_path=str(receipt_path),
    )
    service = SimpleNamespace(
        config=SimpleNamespace(state_root=state_root),
        _expected_base_commit=engine_commit,
    )
    validated = ResearchRunService._validate_pre_oos_root_synthesis_receipt(
        service,
        job,
        workspace,
        task=task,
        agent_result=result,
    )
    assert validated.receipt_id == f"jobs/{job.job_id}/root_synthesis.json"
    assert validated.receipt_sha256 == _sha256(receipt_path)

    receipt["task_packet_sha256"] = "f" * 64
    _write_json(receipt_path, receipt)
    with pytest.raises(RuntimeError, match=BLOCK_RESUME_TRUST_INVALID):
        ResearchRunService._validate_pre_oos_root_synthesis_receipt(
            service,
            job,
            workspace,
            task=task,
            agent_result=result,
        )
