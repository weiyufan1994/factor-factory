from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from factor_factory.council_terminal import classify_terminal_rejection_result
from factor_factory.research_conjecture import validate_terminal_council_rejection
from factor_factory.research_evidence import sha256_file
from factor_factory.research_proof import factor_proof_certificate_path
from factor_factory.ultimate_loop.state import classify_loop_state


def _load_terminal_closer():
    path = (
        Path(__file__).resolve().parents[1]
        / "skills/factor-forge-step6/scripts/close_terminal_council_rejection.py"
    )
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(
        "close_terminal_council_rejection_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_ultimate_loop():
    path = Path(__file__).resolve().parents[1] / "scripts/run_factorforge_ultimate_loop.py"
    spec = importlib.util.spec_from_file_location(
        "run_factorforge_ultimate_loop_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_terminal_rejection_result_classification_is_shared_and_fail_closed() -> None:
    assert classify_terminal_rejection_result(
        returncode=0,
        output="",
        branch_falsification_exists=False,
    ) == "closed"
    assert classify_terminal_rejection_result(
        returncode=1,
        output="BLOCK_FACTORFORGE_TERMINAL_COUNCIL_NOT_UNANIMOUS",
        branch_falsification_exists=False,
    ) == "awaiting_main_agent_council_synthesis"
    assert classify_terminal_rejection_result(
        returncode=1,
        output="BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS",
        branch_falsification_exists=True,
    ) == "awaiting_next_derivation"
    assert classify_terminal_rejection_result(
        returncode=1,
        output="BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS",
        branch_falsification_exists=False,
    ) == "failed"


def test_terminal_closer_blocks_loop_brief_path_outside_workspace(
    tmp_path: Path,
) -> None:
    closer = _load_terminal_closer()
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"decision":"untouched"}', encoding="utf-8")

    with pytest.raises(SystemExit):
        closer.loop_brief_paths(
            root,
            {"loop_research_brief": {"json_path": str(outside)}},
        )

    assert json.loads(outside.read_text(encoding="utf-8"))["decision"] == "untouched"


def test_terminal_closer_blocks_symlinked_loop_brief_parent(
    tmp_path: Path,
) -> None:
    closer = _load_terminal_closer()
    root = tmp_path / "workspace"
    real_dir = root / "real"
    real_dir.mkdir(parents=True)
    target = real_dir / "brief.json"
    target.write_text('{"decision":"untouched"}', encoding="utf-8")
    linked_dir = root / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(SystemExit):
        closer.loop_brief_paths(
            root,
            {"loop_research_brief": {"json_path": str(linked_dir / "brief.json")}},
        )

    assert json.loads(target.read_text(encoding="utf-8"))["decision"] == "untouched"


def test_loop_inherits_only_fully_validated_raw_terminal_rejection() -> None:
    loop = _load_ultimate_loop()
    valid = {
        "status": "PASS",
        "revision_council": {
            "terminal_protocol_validated": True,
            "terminal_decision": "REJECT",
            "formal_council_status": "rejected",
        },
    }
    assert loop.terminal_protocol_validated_from_wrapper(valid) is True

    invalid = json.loads(json.dumps(valid))
    invalid["revision_council"]["formal_council_status"] = "paused"
    assert loop.terminal_protocol_validated_from_wrapper(invalid) is False


def test_loop_classifier_accepts_auditable_council_wait_state_before_formal_pass(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    report_id = "COUNCIL_WAIT_TEST"
    proof_path = (
        root
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    )
    proof_path.parent.mkdir(parents=True)
    proof_path.write_text(
        json.dumps(
            {
                "status": "PAUSED",
                "dry_run": False,
                "revision_council": {"status": "awaiting_agent_results"},
            }
        ),
        encoding="utf-8",
    )

    state = classify_loop_state(
        root,
        report_id,
        0,
        contract_smoke_mode=True,
    )

    assert state["outcome"] == "awaiting_agent_results"
    assert state["proof_status"] == "PAUSED"
    assert state["can_continue"] is False


def test_terminal_rejection_binds_council_collection_proof_and_iteration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "workspace"
    report_id = "TERMINAL_REJECT_TEST"
    council_root = (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
    )
    council_root.mkdir(parents=True)
    summary_path = council_root / f"revision_council_summary__{report_id}.json"
    collection_path = council_root / f"agentic_result_collection__{report_id}.json"
    dispatch_path = council_root / f"dispatch_manifest__{report_id}.json"
    proof_path = factor_proof_certificate_path(root, report_id)
    proof_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps({"report_id": report_id}), encoding="utf-8")
    result_specs = [("route_economic", "reject"), ("route_null", "kill")]
    result_paths: dict[str, Path] = {}
    for task_id, recommendation in result_specs:
        result_path = council_root / f"agent_result__{report_id}__{task_id}.json"
        result_path.write_text(
            json.dumps(
                {
                    "report_id": report_id,
                    "task_id": task_id,
                    "revision_or_kill_recommendation": {
                        "recommendation": recommendation,
                    },
                }
            ),
            encoding="utf-8",
        )
        result_paths[task_id] = result_path
    collection_path.write_text(
        json.dumps(
            {
                "collection_version": "factorforge_agentic_council_result_collection_v1",
                "report_id": report_id,
                "status": "complete",
                "ready_for_finalize": True,
                "required_result_count": 2,
                "present_result_count": 2,
                "valid_result_count": 2,
                "invalid_result_count": 0,
                "missing_result_count": 0,
                "valid_results": [
                    {
                        "task_id": task_id,
                        "result_path": str(result_paths[task_id]),
                        "status": "final",
                    }
                    for task_id, _recommendation in result_specs
                ],
            }
        ),
        encoding="utf-8",
    )
    dispatch_path.write_text(
        json.dumps(
            {
                "dispatch_manifest_version": (
                    "factorforge_agentic_council_dispatch_manifest_v1"
                ),
                "report_id": report_id,
                "agent_tasks": [
                    {
                        "task_id": task_id,
                        "required": True,
                        "expected_result_path": str(result_paths[task_id]),
                    }
                    for task_id, _recommendation in result_specs
                ],
            }
        ),
        encoding="utf-8",
    )
    proof_path.write_text(
        json.dumps({"report_id": report_id, "declared_verdict": "REJECT"}),
        encoding="utf-8",
    )
    rejection = {
        "terminal_rejection_version": "factorforge_terminal_council_rejection_v1",
        "report_id": report_id,
        "summary_path": str(summary_path),
        "summary_sha256": sha256_file(summary_path),
        "collection_path": str(collection_path),
        "collection_sha256": sha256_file(collection_path),
        "dispatch_manifest_path": str(dispatch_path),
        "dispatch_manifest_sha256": sha256_file(dispatch_path),
        "factor_proof_path": str(proof_path),
        "factor_proof_sha256": sha256_file(proof_path),
        "factor_proof_verdict": "REJECT",
        "iteration_decision": "reject",
        "selected_agent_result_ids": ["route_economic", "route_null"],
        "terminal_recommendations": [
            {"task_id": "route_economic", "recommendation": "reject"},
            {"task_id": "route_null", "recommendation": "kill"},
        ],
        "agent_result_paths": [str(path) for path in result_paths.values()],
        "agent_result_bindings": [
            {
                "task_id": task_id,
                "result_path": str(result_paths[task_id]),
                "result_sha256": sha256_file(result_paths[task_id]),
                "recommendation": recommendation,
            }
            for task_id, recommendation in result_specs
        ],
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
    }
    iteration = {"research_judgment": {"decision": "reject"}}
    monkeypatch.setattr(
        "factor_factory.research_conjecture.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )

    assert validate_terminal_council_rejection(
        rejection,
        root=root,
        report_id=report_id,
        council_summary_path=summary_path,
        iteration=iteration,
        factor_proof_report={"verdict": "REJECT", "block_reasons": []},
    ) == []

    invalid_recommendation = dict(rejection)
    invalid_recommendation["terminal_recommendations"] = [
        {"task_id": "route_economic", "recommendation": "do not reject; continue"},
        {"task_id": "route_null", "recommendation": "kill"},
    ]
    reasons = validate_terminal_council_rejection(
        invalid_recommendation,
        root=root,
        report_id=report_id,
        council_summary_path=summary_path,
        iteration=iteration,
        factor_proof_report={"verdict": "REJECT", "block_reasons": []},
    )
    assert any("RECOMMENDATIONS_INVALID" in reason for reason in reasons)

    result_path = result_paths["route_null"]
    original_result = result_path.read_text(encoding="utf-8")
    result_path.write_text(
        json.dumps(
            {
                "report_id": report_id,
                "task_id": "route_null",
                "revision_or_kill_recommendation": {"recommendation": "kill"},
                "tampered": True,
            }
        ),
        encoding="utf-8",
    )
    reasons = validate_terminal_council_rejection(
        rejection,
        root=root,
        report_id=report_id,
        council_summary_path=summary_path,
        iteration=iteration,
        factor_proof_report={"verdict": "REJECT", "block_reasons": []},
    )
    assert any("RESULT_HASH_MISMATCH" in reason for reason in reasons)
    result_path.write_text(original_result, encoding="utf-8")

    original_collection = collection_path.read_text(encoding="utf-8")
    collection = json.loads(original_collection)
    collection["required_result_count"] = 1
    collection_path.write_text(json.dumps(collection), encoding="utf-8")
    mismatched_collection_rejection = dict(rejection)
    mismatched_collection_rejection["collection_sha256"] = sha256_file(
        collection_path
    )
    reasons = validate_terminal_council_rejection(
        mismatched_collection_rejection,
        root=root,
        report_id=report_id,
        council_summary_path=summary_path,
        iteration=iteration,
        factor_proof_report={"verdict": "REJECT", "block_reasons": []},
    )
    assert any("COLLECTION_INVALID" in reason for reason in reasons)
    collection_path.write_text(original_collection, encoding="utf-8")

    summary_path.write_text(
        json.dumps({"report_id": report_id, "tampered": True}),
        encoding="utf-8",
    )
    reasons = validate_terminal_council_rejection(
        rejection,
        root=root,
        report_id=report_id,
        council_summary_path=summary_path,
        iteration=iteration,
        factor_proof_report={"verdict": "REJECT", "block_reasons": []},
    )
    assert any("BINDING_HASH_MISMATCH:summary_path" in reason for reason in reasons)
