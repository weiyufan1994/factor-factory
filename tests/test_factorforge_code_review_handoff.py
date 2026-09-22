"""Offline state/consumer tests. Messages here are synthetic, not real reviews."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.code_review_handoff import CodeReviewHandoff, HandoffError
from factor_factory.code_review_checkpoint import validate_code_review


REPORT = "HANDOFF_TEST"
REPO = Path(__file__).resolve().parents[1]


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def flow_case(tmp_path):
    workspace = tmp_path / "study"
    workspace.mkdir()
    spec = workspace / "spec.json"
    handoff = workspace / "handoff.json"
    code = workspace / "code.py"
    helper = workspace / "helper.py"
    source = workspace / "source.md"
    oracle = workspace / "test_oracle.py"
    _write(spec, {"report_id": REPORT})
    _write(handoff, {"factor_impl_ref": str(code)})
    prep = workspace / "data-prep.json"
    _write(prep, {"scope": "synthetic input metadata"})
    stage4 = {k: str(workspace / f"{k}.json") for k in
              ("factor_run_master", "factor_run_diagnostics", "handoff_to_step5")}
    stage5 = {k: str(workspace / f"{k}.json") for k in
              ("factor_case_master", "factor_evaluation", "handoff_to_step6")}
    manifest = {"step_io": {
        "step4": {"inputs": {"factor_spec_master": str(spec), "data_prep_master": str(prep), "handoff_to_step4": str(handoff)}, "outputs": stage4},
        "step5": {"inputs": {k: stage4[k] for k in ("factor_run_master", "handoff_to_step5")}, "outputs": stage5},
    }}
    # Nothing in handoff/checkpoint may import these files or execute commands.
    code.write_text("raise RuntimeError('must never import implementation')\n")
    helper.write_text("raise RuntimeError('must never import helper')\n")
    source.write_text("Synthetic hypothesis; no financial data.\n")
    oracle.write_text("raise RuntimeError('test plan is not a command to execute')\n")
    request = {"issue_id": "timing-check", "summary": "Check source-to-code timing",
               "author_id": "author", "reviewer_id": "reviewer", "origin_step": "3b",
               "materials_note": "One invoked helper and an independently specified oracle",
               "spec": str(spec), "handoff": str(handoff), "helpers": [{"path": str(helper)}],
               "context_files": [{"role": "source", "path": str(source)}, {"role": "test", "path": str(oracle)}],
               "resume": {"start_step": "4", "end_step": "5", "reason": "Steps2/3 are complete"}}
    return {"workspace": workspace, "spec": spec, "handoff": handoff, "code": code, "helper": helper,
            "source": source, "oracle": oracle, "request": request, "manifest": manifest, "prep": prep}


def _flow(case):
    return CodeReviewHandoff(case["workspace"], REPORT, REPO)


def _prepare(case):
    return _flow(case).prepare(case["request"])["request_id"]


def _send(case, request_id):
    assert _flow(case).delivery(request_id, "begin", "synthetic test intent")["send_allowed"]
    _flow(case).delivery(request_id, "sent", "synthetic test outcome; not a real message")


def _review(case, request_id, decision="proceed", *, edits=None):
    record = {"report_id": REPORT, "request_id": request_id, "author_id": "author", "reviewer_id": "reviewer",
              "reviewed_at": _now(), "decision": decision, "summary": "Synthetic fixture review of exact source/code/helper",
              "findings": [] if decision == "proceed" else [{"summary": "Boundary violates the frozen definition", "status": "open"}],
              "reviewed_files": _flow(case).status()["request"]["reviewed_files"]}
    if edits:
        edits(record)
    path = case["workspace"] / f"review-{request_id}.json"
    _write(path, record)
    return path


def _tests(case, request_id, status="PASS"):
    entry = _flow(case).status()["request"]
    log = case["workspace"] / f"tests-{status}.log"
    log.write_text(f"Synthetic fixture evidence {status}\n")
    record = {"status": status, "started_at": _now(), "completed_at": _now(),
              "tested_files": deepcopy(entry["reviewed_files"]),
              "evidence": [{"path": str(log), "sha256": hashlib.sha256(log.read_bytes()).hexdigest()}],
              "command": "This text is data; no shell execution is permitted"}
    path = case["workspace"] / f"test-record-{status}.json"
    _write(path, record)
    return path


def _ready(case):
    request_id = _prepare(case)
    _send(case, request_id)
    _flow(case).receive_review(request_id, _review(case, request_id))
    result = _flow(case).record_tests(request_id, _tests(case, request_id))
    assert result["status"] == "READY", result
    return request_id


def test_prepare_is_idempotent_and_preserves_existing_journal(flow_case):
    flow = _flow(flow_case)
    original = {"report_id": REPORT, "source_understanding": {"unknown": "kept"}, "revision_history": [{"prior": 1}]}
    _write(flow.path, original)
    first = _flow(flow_case).prepare(flow_case["request"])
    before = flow.path.read_bytes()
    flow_case["request"]["summary"] = "Rephrasing the same question must not send it again"
    second = _flow(flow_case).prepare(flow_case["request"])
    assert first["request_id"] == second["request_id"]
    assert not second["created"] and flow.path.read_bytes() == before
    saved = json.loads(before)
    assert saved["source_understanding"] == original["source_understanding"]
    assert saved["revision_history"] == original["revision_history"]
    assert not flow.review_path.exists()


def test_status_of_unmanaged_study_is_read_only(flow_case):
    flow = _flow(flow_case)
    assert flow.status()["status"] == "NOT_MANAGED"
    assert not flow.path.exists()


def test_unknown_send_cannot_be_retried_or_replaced(flow_case):
    request_id = _prepare(flow_case)
    assert _flow(flow_case).delivery(request_id, "begin", "tool-call intent")["send_allowed"]
    assert not _flow(flow_case).delivery(request_id, "begin", "duplicate intent")["send_allowed"]
    _flow(flow_case).delivery(request_id, "unknown", "connection dropped after request")
    assert not _flow(flow_case).delivery(request_id, "begin", "automatic retry forbidden")["send_allowed"]
    flow_case["code"].write_text("changed code\n")
    with pytest.raises(HandoffError, match="outcome unknown"):
        _prepare(flow_case)
    _flow(flow_case).delivery(request_id, "failed", "Tool inspection established non-delivery")
    newer = _prepare(flow_case)
    assert newer != request_id


def test_known_send_failure_requires_explicit_retry_reason(flow_case):
    request_id = _prepare(flow_case)
    _flow(flow_case).delivery(request_id, "begin", "attempt to contact reviewer")
    _flow(flow_case).delivery(request_id, "failed", "No reviewer/channel available; nothing sent")
    saved = _flow(flow_case).status()
    assert saved["status"] == "BLOCK" and saved["state"] == "delivery_failed"
    assert saved["owner"] == "Ultimate" and saved["resume"] is None
    with pytest.raises(HandoffError, match="retry reason"):
        _flow(flow_case).delivery(request_id, "begin", "retry")
    assert _flow(flow_case).delivery(request_id, "begin", "retry", retry_reason="Channel is now available")["send_allowed"]


def test_review_requires_actual_dispatch_declaration(flow_case):
    request_id = _prepare(flow_case)
    with pytest.raises(HandoffError, match="confirmed dispatch"):
        _flow(flow_case).receive_review(request_id, _review(flow_case, request_id))
    assert not _flow(flow_case).review_path.exists()


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(request_id="old-request"),
    lambda r: r.update(reviewer_id="author"),
    lambda r: r.update(reviewed_at="2000-01-01T00:00:00+00:00"),
    lambda r: r.update(reviewed_files=[f for f in r["reviewed_files"] if f["role"] != "helper"]),
    lambda r: r.update(post_review_tests={"status": "PASS"}),
])
def test_invalid_intake_is_preserved_without_creating_approval(flow_case, mutation):
    request_id = _prepare(flow_case)
    _send(flow_case, request_id)
    with pytest.raises(HandoffError):
        _flow(flow_case).receive_review(request_id, _review(flow_case, request_id, edits=mutation))
    saved = _flow(flow_case).status()
    assert saved["state"] == "review_invalid" and saved["request"]["intake_failures"]
    assert not _flow(flow_case).review_path.exists()


def test_findings_fix_rereview_tests_and_resume_preserve_history(flow_case):
    first = _prepare(flow_case)
    _send(flow_case, first)
    result = _flow(flow_case).receive_review(first, _review(flow_case, first, "revise"))
    assert result["state"] == "changes_requested" and result["owner"] == "author"
    with pytest.raises(HandoffError, match="proceed"):
        _flow(flow_case).record_tests(first, _tests(flow_case, first))
    flow_case["helper"].write_text("# corrected numerical boundary\n")
    second = _prepare(flow_case)
    assert second != first
    with pytest.raises(HandoffError, match="Stale request_id"):
        _flow(flow_case).receive_review(first, _review(flow_case, first))
    _send(flow_case, second)
    result = _flow(flow_case).receive_review(second, _review(flow_case, second))
    assert result["state"] == "awaiting_tests" and result["resume"] is None
    result = _flow(flow_case).record_tests(second, _tests(flow_case, second))
    assert result["status"] == "READY" and result["remaining_steps"] == ["4", "5"]
    assert result["resume"]["start_step"] == "4"
    history = _flow(flow_case).state["requests"]
    assert history[0]["review"]["findings"][0]["status"] == "open"
    assert history[1]["previous_request_id"] == first


@pytest.mark.parametrize("changed", ["spec", "code", "helper", "source", "oracle", "handoff"])
def test_changed_material_invalidates_review_tests_and_release(flow_case, changed):
    request_id = _ready(flow_case)
    path = flow_case[changed]
    path.write_bytes(path.read_bytes() + b"\n ")
    result = _flow(flow_case).status()
    assert result["state"] == "stale_materials" and result["resume"] is None
    with pytest.raises(HandoffError):
        _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    with pytest.raises(HandoffError):
        _flow(flow_case).record_tests(request_id, _tests(flow_case, request_id))


def test_failed_tests_remain_visible_and_success_needs_new_evidence(flow_case):
    request_id = _prepare(flow_case)
    _send(flow_case, request_id)
    _flow(flow_case).receive_review(request_id, _review(flow_case, request_id))
    failed = _flow(flow_case).record_tests(request_id, _tests(flow_case, request_id, "FAIL"))
    assert failed["state"] == "tests_failed" and failed["resume"] is None
    passed = _flow(flow_case).record_tests(request_id, _tests(flow_case, request_id))
    assert passed["status"] == "READY" and len(passed["request"]["test_runs"]) == 2
    assert passed["request"]["test_runs"][0]["tests"]["status"] == "FAIL"


def test_pre_review_tests_and_rewritten_review_do_not_release(flow_case):
    request_id = _prepare(flow_case)
    old_tests = _tests(flow_case, request_id)
    _send(flow_case, request_id)
    _flow(flow_case).receive_review(request_id, _review(flow_case, request_id))
    assert _flow(flow_case).record_tests(request_id, old_tests)["status"] == "BLOCK"
    _flow(flow_case).record_tests(request_id, _tests(flow_case, request_id))
    path = _flow(flow_case).review_path
    record = json.loads(path.read_text())
    record["summary"] = "Edited after acceptance"
    _write(path, record)
    assert "ACCEPTED_REVIEW_CHANGED" in _flow(flow_case).status()["reasons"]


def test_invalid_new_test_evidence_does_not_leave_old_ready_state(flow_case):
    request_id = _ready(flow_case)
    invalid = flow_case["workspace"] / "broken-test-result.json"
    invalid.write_text("truncated output")
    with pytest.raises(HandoffError):
        _flow(flow_case).record_tests(request_id, invalid)
    result = _flow(flow_case).status()
    assert result["state"] == "tests_invalid" and result["resume"] is None
    assert result["request"]["test_intake_failures"]


def _command_result(name, returncode=0):
    return {"name": name, "command": ["not executed by state test"], "cwd": str(REPO),
            "started_at_utc": _now(), "finished_at_utc": _now(), "returncode": returncode,
            "stdout_tail": "synthetic command result", "stderr_tail": "failure" if returncode else "",
            "status": "FAIL" if returncode else "PASS"}


def _command_context(case):
    return {"command": ["not executed by state test"], "cwd": str(REPO), "manifest": deepcopy(case["manifest"])}


def _stage_outputs(case, step="4"):
    """Create real minimal files for a synthetic command declaration."""
    outputs = case["manifest"]["step_io"]["step" + step]["outputs"]
    for key, raw in outputs.items():
        _write(Path(raw), {"report_id": REPORT, "synthetic_object": key})
    if step == "4":
        result = case["workspace"] / "synthetic-values.csv"
        result.write_text("index,value\n0,1\n")
        payload = case["workspace"] / "synthetic-backend.json"
        metric = case["workspace"] / "synthetic-metric.csv"
        metric.write_text("metric,value\nfixture,1\n")
        _write(payload, {"artifacts": {"metric": str(metric)}})
        _write(Path(outputs["factor_run_master"]), {"output_paths": [str(result)], "evaluation_results": {
            "backend_runs": [{"status": "success", "payload_path": str(payload)}]}})
    if step == "5":
        archived = case["workspace"] / "archived-evidence.json"
        _write(archived, {"synthetic": "archived evidence"})
        _write(Path(outputs["factor_case_master"]), {"evidence": {"archive_paths": [str(archived)]}})


def _complete_stage4(case):
    _ready(case)
    flow = _flow(case)
    flow.before_command("run_step4", end_step="5", execution_context=_command_context(case))
    _stage_outputs(case)
    flow.record_command(_command_result("run_step4"))
    flow = _flow(case)
    flow.before_command("validate_step4", end_step="5", execution_context=_command_context(case))
    flow.record_command(_command_result("validate_step4"))


@pytest.mark.parametrize("filename", ["factor_run_master.json", "factor_run_diagnostics.json", "handoff_to_step5.json",
                                     "data-prep.json", "synthetic-values.csv", "synthetic-backend.json", "synthetic-metric.csv"])
@pytest.mark.parametrize("change", ["modify", "delete"])
def test_completed_artifact_changes_block_status_and_cached_validator(flow_case, filename, change):
    _complete_stage4(flow_case)
    path = flow_case["workspace"] / filename
    if change == "delete":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\n ")
    saved_before = _flow(flow_case).path.read_bytes()
    result = _flow(flow_case).status()
    assert result["status"] == "BLOCK" and result["resume"] is None
    assert result["artifact_recovery"]["step"] == "4"
    assert result["remaining_steps"] == ["4", "5"]
    assert any(str(path) in r for r in result["reasons"])
    with pytest.raises(HandoffError, match="stage_artifacts_blocked"):
        _flow(flow_case).before_command("validate_step4", end_step="5", execution_context=_command_context(flow_case))
    assert _flow(flow_case).path.read_bytes() == saved_before


def test_success_without_outputs_cannot_establish_completion(flow_case):
    _ready(flow_case)
    _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    with pytest.raises(HandoffError, match="artifacts cannot establish completion"):
        _flow(flow_case).record_command(_command_result("run_step4"))
    result = _flow(flow_case).status()
    assert result["status"] == "BLOCK" and result["artifact_recovery"]["step"] == "4"
    assert result["request"]["execution"]["4"]["run_step4"]["returncode"] == 0


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_changed_step5_archive_blocks_at_step5_and_restored_json_can_resume(flow_case, change):
    _complete_stage4(flow_case)
    _flow(flow_case).before_command("run_step5", end_step="5", execution_context=_command_context(flow_case))
    _stage_outputs(flow_case, "5")
    _flow(flow_case).record_command(_command_result("run_step5"))
    _flow(flow_case).before_command("validate_step5", end_step="5", execution_context=_command_context(flow_case))
    _flow(flow_case).record_command(_command_result("validate_step5"))
    assert _flow(flow_case).status()["remaining_steps"] == []
    path = flow_case["workspace"] / "archived-evidence.json"
    original = path.read_bytes()
    if change == "delete":
        path.unlink()
    else:
        path.write_bytes(original + b"\n ")
    blocked = _flow(flow_case).status()
    assert blocked["status"] == "BLOCK" and blocked["resume"] is None
    assert blocked["artifact_recovery"]["step"] == "5" and blocked["remaining_steps"] == ["5"]
    with pytest.raises(HandoffError, match="stage_artifacts_blocked"):
        _flow(flow_case).before_command("validate_step5", end_step="5", execution_context=_command_context(flow_case))
    path.write_bytes(original)
    assert _flow(flow_case).status()["status"] == "READY"
    assert _flow(flow_case).before_command("validate_step5", end_step="5", execution_context=_command_context(flow_case))["status"] == "REUSE"


def test_input_changed_while_command_was_pending_does_not_become_validated(flow_case):
    _ready(flow_case)
    _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    _stage_outputs(flow_case)
    _write(flow_case["prep"], {"different": "input metadata"})
    with pytest.raises(HandoffError, match="ARTIFACT_CHANGED"):
        _flow(flow_case).record_command(_command_result("run_step4"))
    assert _flow(flow_case).status()["status"] == "BLOCK"


@pytest.mark.parametrize("mismatch", ["argv", "cwd"])
def test_wrong_process_result_leaves_pending_until_matching_result_arrives(flow_case, mismatch):
    _ready(flow_case)
    _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    _stage_outputs(flow_case)
    wrong = _command_result("run_step4")
    if mismatch == "argv":
        wrong["command"] = ["different-stage4", "--manifest", "other.json"]
    else:
        wrong["cwd"] = str(flow_case["workspace"])
    with pytest.raises(HandoffError, match="COMMAND_(ARGV|CWD)_MISMATCH"):
        _flow(flow_case).record_command(wrong)
    pending = _flow(flow_case).status()
    execution = pending["request"]["execution"]["4"]
    assert pending["status"] == "BLOCK" and execution["status"] == "running"
    assert "run_step4" not in execution and execution["result_rejections"]
    _flow(flow_case).record_command(_command_result("run_step4"))
    assert _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "REUSE"


def test_same_request_rereview_retains_findings_path_disposition_and_idempotence(flow_case):
    request_id = _prepare(flow_case)
    _send(flow_case, request_id)
    first_record = json.loads(_review(flow_case, request_id, "revise").read_text())
    first = flow_case["workspace"] / "first-review.json"
    _write(first, first_record)
    _flow(flow_case).receive_review(request_id, first)
    later = _review(flow_case, request_id, edits=lambda r: r.update(
        summary="The prior boundary concern was a misunderstanding clarified against the unchanged source; no code change required."))
    _flow(flow_case).receive_review(request_id, later)
    entry = _flow(flow_case).status()["request"]
    assert len(entry["review_history"]) == 2
    assert entry["review_history"][0]["review"] == first_record
    assert entry["review_history"][0]["result_path"] == str(first)
    assert entry["review_history"][1]["disposition"] == entry["review"]["summary"]
    assert entry["review_history"][1]["supersedes_review_number"] == 1
    before = _flow(flow_case).path.read_bytes()
    _flow(flow_case).receive_review(request_id, first)
    _flow(flow_case).receive_review(request_id, later)
    assert _flow(flow_case).path.read_bytes() == before
    first.unlink()
    assert first_record["findings"][0]["summary"] in _flow(flow_case).path.read_text()


def test_material_rollback_creates_new_round_without_reusing_old_tests_or_execution(flow_case):
    _complete_stage4(flow_case)
    first = _flow(flow_case).status()["request_id"]
    original = flow_case["helper"].read_bytes()
    flow_case["helper"].write_bytes(original + b"# version B\n")
    second = _prepare(flow_case)
    flow_case["helper"].write_bytes(original)
    returned = _flow(flow_case).prepare(flow_case["request"])
    assert returned["created"] and returned["request_id"] not in (first, second)
    entry = returned["request"]
    assert entry["previous_request_id"] == second and entry["reuses_materials_from"] == first
    assert entry["test_runs"] == [] and entry["execution"] == {} and entry["review_history"] == []
    assert returned["state"] == "prepared" and returned["owner"] == "Ultimate"
    assert _flow(flow_case).state["requests"][0]["execution"]["4"]["status"] == "complete"
    assert not _flow(flow_case).prepare(flow_case["request"])["created"]
    _send(flow_case, returned["request_id"])
    assert _flow(flow_case).status()["state"] == "awaiting_review"


def test_resume_reuses_completed_commands_and_advances_only_after_validation(flow_case):
    _ready(flow_case)
    flow = _flow(flow_case)
    assert flow.before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "RUN"
    _stage_outputs(flow_case)
    flow.record_command(_command_result("run_step4"))
    assert _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "REUSE"
    assert _flow(flow_case).status()["remaining_steps"] == ["4", "5"]
    flow = _flow(flow_case)
    assert flow.before_command("validate_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "RUN"
    flow.record_command(_command_result("validate_step4"))
    assert _flow(flow_case).status()["resume"]["start_step"] == "5"
    assert _flow(flow_case).before_command("validate_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "REUSE"
    with pytest.raises(HandoffError, match="scope"):
        _flow(flow_case).before_command("run_step5", end_step="6")


@pytest.mark.parametrize("old_step6_status", ["complete", "running", "failed", "artifacts_blocked"])
def test_step6_handoff_preserves_but_never_reuses_legacy_step6_cache(flow_case, old_step6_status):
    flow_case["request"]["resume"]["end_step"] = "6"
    _complete_stage4(flow_case)
    _flow(flow_case).before_command("run_step5", end_step="6", execution_context=_command_context(flow_case))
    _stage_outputs(flow_case, "5")
    _flow(flow_case).record_command(_command_result("run_step5"))
    _flow(flow_case).before_command("validate_step5", end_step="6", execution_context=_command_context(flow_case))
    _flow(flow_case).record_command(_command_result("validate_step5"))
    flow = _flow(flow_case)
    journal = json.loads(flow.path.read_text())
    # Simulate a journal produced before Step6 caching was removed. Retain its
    # old result/errors verbatim, without treating them as native Step6 state.
    journal["code_review_coordination"]["requests"][-1]["execution"]["6"] = {
        "status": old_step6_status, "artifact_issues": ["obsolete provisional handoff snapshot"],
        "run_step6": {"status": "PASS", "synthetic": "old cached result"},
    }
    _write(flow.path, journal)
    original = flow.path.read_bytes()
    state = _flow(flow_case).status()
    assert state["status"] == "READY" and state["remaining_steps"] == ["6"]
    assert state["resume"]["start_step"] == "6" and state["step6_followup"]
    assert state["cached_execution_steps"] == ["4", "5"]
    for name in ("run_step6", "validate_step6"):
        assert _flow(flow_case).before_command(name, end_step="6")["status"] == "NATIVE_STEP6"
        with pytest.raises(HandoffError, match="Step6 uses its native lifecycle"):
            _flow(flow_case).record_command(_command_result(name))
    assert flow.path.read_bytes() == original


def test_unknown_execution_does_not_retry_and_actual_failure_is_preserved(flow_case):
    _ready(flow_case)
    _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    with pytest.raises(HandoffError, match="UNKNOWN"):
        _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    flow_case["request"]["issue_id"] = "do-not-replace-unknown-execution"
    with pytest.raises(HandoffError, match="outcome unknown"):
        _prepare(flow_case)
    with pytest.raises(HandoffError, match="matching pending"):
        _flow(flow_case).record_command(_command_result("validate_step4"))
    _flow(flow_case).record_command(_command_result("run_step4", 1))
    result = _flow(flow_case).status()
    assert result["status"] == "BLOCK"
    assert result["request"]["execution"]["4"]["run_step4"]["stderr_tail"] == "failure"
    with pytest.raises(HandoffError, match="TRIAGE"):
        _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))


def test_wrapper_manifest_must_select_the_reviewed_paths(flow_case):
    _ready(flow_case)
    with pytest.raises(HandoffError, match="manifest"):
        _flow(flow_case).before_command("run_step4", end_step="5", spec="another-spec.json")


def test_changed_runtime_context_cannot_reuse_completed_command(flow_case):
    _ready(flow_case)
    flow = _flow(flow_case)
    original = _command_context(flow_case)
    flow.before_command("run_step4", end_step="5", execution_context=original)
    _stage_outputs(flow_case)
    flow.record_command(_command_result("run_step4"))
    assert _flow(flow_case).before_command("run_step4", end_step="5", execution_context=original)["status"] == "REUSE"
    changed = deepcopy(original)
    changed["manifest"]["runs_root"] = "different-run"
    with pytest.raises(HandoffError, match="manifest differs"):
        _flow(flow_case).before_command("run_step4", end_step="5", execution_context=changed)


def test_cli_reconciles_a_known_pending_result_without_rerunning_it(flow_case):
    request_id = _ready(flow_case)
    _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))
    _stage_outputs(flow_case)
    path = flow_case["workspace"] / "known-command-result.json"
    _write(path, _command_result("run_step4"))
    cp = subprocess.run([sys.executable, "-B", str(REPO / "scripts/manage_factorforge_code_review.py"),
                         "command-result", "--workspace-root", str(flow_case["workspace"]),
                         "--report-id", REPORT, "--request-id", request_id,
                         "--record", path.name, "--reference", "Synthetic recovered tool output, not a live process"],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert json.loads(cp.stdout)["status"] == "READY"
    assert _flow(flow_case).before_command("run_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "REUSE"
    assert _flow(flow_case).before_command("validate_step4", end_step="5", execution_context=_command_context(flow_case))["status"] == "RUN"


def test_cli_status_is_read_only_and_never_runs_embedded_commands(flow_case):
    _ready(flow_case)
    before = {p: p.read_bytes() for p in flow_case["workspace"].rglob("*") if p.is_file()}
    cp = subprocess.run([sys.executable, "-B", str(REPO / "scripts/manage_factorforge_code_review.py"),
                         "status", "--workspace-root", str(flow_case["workspace"]), "--report-id", REPORT],
                        capture_output=True, text=True)
    assert cp.returncode == 0 and json.loads(cp.stdout)["status"] == "READY"
    assert before == {p: p.read_bytes() for p in flow_case["workspace"].rglob("*") if p.is_file()}
    # The unchanged formal checkpoint still requires the full post-review tests.
    assert validate_code_review(workspace_root=flow_case["workspace"], report_id=REPORT,
                                handoff=flow_case["handoff"], spec=flow_case["spec"], repo_root=REPO)["status"] == "PASS"
