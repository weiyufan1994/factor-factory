from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from factor_factory.console.council_ingress import (
    build_council_task_prompt,
    load_council_ingress_tasks,
)
from factor_factory.console.run_service import (
    _allowed_agent_write_paths,
    _trusted_council_ingress_tasks,
)


REPORT_ID = "CONSOLE_COUNCIL_INGRESS_TEST"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace(tmp_path: Path) -> tuple[Path, Path, list[dict]]:
    workspace = tmp_path / "workspace"
    council_relative = (
        Path("objects")
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
    )
    council = workspace / council_relative
    tasks: list[dict] = []
    for index in (1, 2):
        task_id = f"route_{index}"
        role = f"role_{index}"
        agent_identifier = f"independent_agent_{index}"
        packet_relative = (
            council_relative
            / "agent_tasks"
            / f"task__{REPORT_ID}__{task_id}.json"
        )
        result_relative = (
            council_relative
            / "agent_results"
            / f"agent_result__{REPORT_ID}__{task_id}.json"
        )
        packet_path = workspace / packet_relative
        _write_json(
            packet_path,
            {
                "task_packet_version": "factorforge_agentic_council_task_packet_v1",
                "report_id": REPORT_ID,
                "task_id": task_id,
                "agent_role": role,
                "expected_agent_identifier": agent_identifier,
                "expected_result_path": result_relative.as_posix(),
                "canonical_write_permission": False,
                "execution_allowed_by_default": False,
                "human_approval_required": True,
                "required_outputs": ["public_derivation_record"],
            },
        )
        tasks.append(
            {
                "task_id": task_id,
                "agent_role": role,
                "expected_agent_identifier": agent_identifier,
                "task_packet_path": packet_relative.as_posix(),
                "task_packet_sha256": _sha256(packet_path),
                "expected_result_path": result_relative.as_posix(),
                "required": True,
            }
        )
    manifest_path = council / f"dispatch_manifest__{REPORT_ID}.json"
    _write_json(
        manifest_path,
        {
            "dispatch_manifest_version": "factorforge_agentic_council_dispatch_manifest_v1",
            "report_id": REPORT_ID,
            "status": "awaiting_agent_results",
            "agent_task_count": len(tasks),
            "agent_tasks": tasks,
        },
    )
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}.json"
    )
    _write_json(
        proof_path,
        {
            "report_id": REPORT_ID,
            "status": "PAUSED",
            "revision_council": {
                "status": "awaiting_agent_results",
                "effective_mode": "agentic_dispatch_manifest",
            },
        },
    )
    return workspace, proof_path, tasks


def test_trusted_council_pause_opens_only_exact_result_ingress(tmp_path):
    workspace, proof_path, raw_tasks = _workspace(tmp_path)
    tasks = _trusted_council_ingress_tasks(
        workspace,
        report_id=REPORT_ID,
        trusted_resume_proof_sha256=_sha256(proof_path),
    )

    assert len(tasks) == 2
    assert {task.expected_agent_identifier for task in tasks} == {
        "independent_agent_1",
        "independent_agent_2",
    }
    allowed, required = _allowed_agent_write_paths(
        workspace,
        report_id=REPORT_ID,
        resume=True,
        trusted_resume_proof_sha256=_sha256(proof_path),
        council_ingress_tasks=tasks,
    )
    expected_results = {item["expected_result_path"] for item in raw_tasks}

    assert required == expected_results
    assert allowed == {"identity/web_agent_resume.md", *expected_results}
    assert "identity/web_execution_ledger.md" not in required
    prompt = build_council_task_prompt(
        workspace=workspace,
        report_id=REPORT_ID,
        task=tasks[0],
        private_output_path=tmp_path / "private" / "result.json",
    )
    assert str(tmp_path / "private" / "result.json") in prompt
    assert tasks[1].expected_result_path not in prompt
    assert "independent_agent_1" in prompt


def test_council_ingress_rejects_path_escape_and_existing_result(tmp_path):
    workspace, _proof_path, raw_tasks = _workspace(tmp_path)
    manifest_path = (
        workspace
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / REPORT_ID
        / f"dispatch_manifest__{REPORT_ID}.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["agent_tasks"][0]["expected_result_path"] = "../escaped.json"
    _write_json(manifest_path, manifest)
    with pytest.raises(RuntimeError, match="COUNCIL_INGRESS_INVALID"):
        load_council_ingress_tasks(workspace, REPORT_ID)

    workspace, _proof_path, raw_tasks = _workspace(tmp_path / "existing")
    _write_json(
        workspace / raw_tasks[0]["expected_result_path"],
        {"status": "untrusted"},
    )
    with pytest.raises(RuntimeError, match="already exists"):
        load_council_ingress_tasks(workspace, REPORT_ID)
