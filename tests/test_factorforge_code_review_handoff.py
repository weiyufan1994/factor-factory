"""Offline state/consumer tests. Messages here are synthetic, not real reviews."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.code_review_handoff import CodeReviewHandoff, HandoffError
import factor_factory.code_review_handoff as handoff_module
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


def test_real_metadata_maintenance_argv_uses_new_step5_request_then_fresh_validator(flow_case):
    """Real maintenance subprocess; synthetic research/review and validator only."""
    from factor_factory.information_set_review import ILLEGAL
    case = flow_case
    outputs = case['manifest']['step_io']['step5']['outputs']
    case['manifest']['objects'] = {**outputs, 'factor_spec_master': str(case['spec'])}
    _write(case['spec'], {'report_id': REPORT, 'canonical_spec': {
        'formula_text': '-e*z', 'cross_sectional_steps': ['Independent of future labels.']}})
    _complete_stage4(case)
    _flow(case).before_command('run_step5', end_step='5', execution_context=_command_context(case))
    _stage_outputs(case, '5')
    case_path, handoff_path = (Path(outputs[k]) for k in ('factor_case_master', 'handoff_to_step6'))
    obj = json.loads(case_path.read_text())
    obj.update(report_id=REPORT, factor_id='SYNTHETIC', math_discipline_review={'information_set_legality': ILLEGAL})
    _write(case_path, obj)
    _write(handoff_path, obj)
    _flow(case).record_command(_command_result('run_step5'))
    _flow(case).before_command('validate_step5', end_step='5', execution_context=_command_context(case))
    _flow(case).record_command(_command_result('validate_step5', 1))
    prior = deepcopy(_flow(case)._active())
    unchanged = {p: p.read_bytes() for p in [case['spec'], Path(outputs['factor_evaluation']),
                    case['workspace'] / 'archived-evidence.json',
                    Path(case['manifest']['step_io']['step4']['outputs']['factor_run_master'])]}
    manifest = case['workspace'] / 'manifest.json'
    _write(manifest, case['manifest'])
    command = [sys.executable, '-B', str(REPO / 'scripts/repair_step5_information_set.py'),
               '--manifest', str(manifest), '--evidence-dir', str(case['workspace'] / 'preserved'), '--apply']
    for name, path in [('manifest', manifest), ('spec', case['spec']), ('case', case_path), ('handoff', handoff_path)]:
        command += [f'--expected-{name}-sha256', hashlib.sha256(path.read_bytes()).hexdigest()]
    case['request'].update(issue_id='narrative-classifier-maintenance', origin_step='5',
        resume={'start_step': '5', 'end_step': '6', 'reason': 'Only metadata repair; original native Step6 remains required'})
    case['request']['helpers'] += [{'path': str(REPO / 'scripts/repair_step5_information_set.py')},
                                  {'path': str(REPO / 'factor_factory/information_set_review.py')}]
    _ready(case)
    assert _flow(case).status()['remaining_steps'] == ['5', '6']
    with pytest.raises(HandoffError, match='scope'):
        _flow(case).before_command('run_step4', end_step='6')
    context = {**_command_context(case), 'command': command}
    assert _flow(case).before_command('run_step5', end_step='6', execution_context=context)['status'] == 'RUN'
    started = _now()
    actual = subprocess.run(command, cwd=REPO, text=True, capture_output=True)
    finished = _now()
    assert actual.returncode == 0, actual.stdout + actual.stderr
    _flow(case).record_command({'name': 'run_step5', 'command': command, 'cwd': str(REPO),
        'started_at_utc': started, 'finished_at_utc': finished, 'returncode': actual.returncode,
        'status': 'PASS', 'stdout_tail': actual.stdout, 'stderr_tail': actual.stderr})
    assert _flow(case)._active()['execution']['5']['status'] == 'computed'
    assert _flow(case).before_command('run_step5', end_step='6', execution_context=context)['status'] == 'REUSE'
    with pytest.raises(HandoffError, match='unfinished'):
        _flow(case).before_command('run_step6', end_step='6')
    # This fixture validates only the repaired classification, not native Step5.
    validator = [sys.executable, '-c',
        "import json,sys; assert json.load(open(sys.argv[1]))['math_discipline_review']['information_set_legality']=='requires_researcher_confirmation_no_forward_leakage'", str(case_path)]
    context = {**_command_context(case), 'command': validator}
    assert _flow(case).before_command('validate_step5', end_step='6', execution_context=context)['status'] == 'RUN'
    started = _now()
    actual = subprocess.run(validator, cwd=REPO, text=True, capture_output=True)
    finished = _now()
    assert actual.returncode == 0, actual.stderr
    _flow(case).record_command({'name': 'validate_step5', 'command': validator, 'cwd': str(REPO),
        'started_at_utc': started, 'finished_at_utc': finished, 'returncode': actual.returncode,
        'status': 'PASS', 'stdout_tail': actual.stdout, 'stderr_tail': actual.stderr})
    assert _flow(case).before_command('run_step6', end_step='6')['status'] == 'NATIVE_STEP6'
    assert _flow(case).state['requests'][0] == prior
    assert {p: p.read_bytes() for p in unchanged} == unchanged
    assert _flow(case)._active()['execution']['5']['run_step5']['command'] == command
    case_path.write_bytes(case_path.read_bytes() + b' ')
    assert _flow(case).status()['status'] == 'BLOCK'


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


def _many_archive_files(case, count=592):
    _stage_outputs(case, "5")
    paths = []
    for index in range(count):
        path = case["workspace"] / "archive" / f"checkpoint-{index}.{'json' if index % 5 == 0 else 'parquet'}"
        path.parent.mkdir(exist_ok=True)
        # A leaf JSON is terminal even when it contains strings resembling
        # further artifact references. No historical/recursive discovery.
        path.write_text(json.dumps({"artifacts": {"unrelated": "missing-history.parquet"}})
                        if path.suffix == ".json" else "synthetic bulk bytes, not real market data")
        paths.append(str(path))
    _write(Path(case["manifest"]["step_io"]["step5"]["outputs"]["factor_case_master"]),
           {"evidence": {"archive_paths": paths + [paths[0]]}})
    return paths


@pytest.mark.parametrize("change", ["modify", "delete"])
@pytest.mark.parametrize("archive_count", [592, 5600])
def test_large_finite_archive_binds_every_leaf_and_blocks_late_changes(flow_case, monkeypatch, change, archive_count):
    _complete_stage4(flow_case)
    _flow(flow_case).before_command("run_step5", end_step="5", execution_context=_command_context(flow_case))
    paths = _many_archive_files(flow_case, count=archive_count)
    real_read = Path.read_bytes

    def no_bulk_reads(path):
        assert path.suffix not in (".parquet", ".csv"), "Artifact capture must not read bulk data"
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", no_bulk_reads)
    _flow(flow_case).record_command(_command_result("run_step5"))
    versions = _flow(flow_case).status()["request"]["execution"]["5"]["artifacts"]
    assert set(paths) <= set(versions) and len(set(paths)) == archive_count
    assert len(versions) < archive_count + 28  # Duplicate refs deduplicate; leaf JSON does not expand.
    _flow(flow_case).before_command("validate_step5", end_step="5", execution_context=_command_context(flow_case))
    _flow(flow_case).record_command(_command_result("validate_step5"))
    path = Path(paths[-1])
    if change == "modify":
        path.write_text("changed after validation")
    else:
        path.unlink()
    assert any(str(path) in issue for issue in _flow(flow_case).status()["reasons"])
    with pytest.raises(HandoffError, match="stage_artifacts_blocked"):
        _flow(flow_case).before_command("run_step5", end_step="5", execution_context=_command_context(flow_case))


def _reference_limit_failure(case, monkeypatch, *, archive_count=270, reference_limit=256):
    """An old-version failure with synthetic native-shaped process evidence."""
    _complete_stage4(case)
    flow = _flow(case)
    request_id = flow.status()["request_id"]
    flow.before_command("run_step5", end_step="5", execution_context=_command_context(case))
    paths = _many_archive_files(case, count=archive_count)
    result = _command_result("run_step5")
    with monkeypatch.context() as old:
        old.setattr(handoff_module, "_MAX_ARTIFACT_REFS", reference_limit)
        with pytest.raises(HandoffError, match="ARTIFACT_REFERENCE_LIMIT"):
            flow.record_command(result)
    manifest_file = case["workspace"] / "runtime-manifest.json"
    _write(manifest_file, case["manifest"])
    proof = case["workspace"] / "original-wrapper-failure.json"
    _write(proof, {"report_id": REPORT, "status": "FAIL", "manifest_path": str(manifest_file),
                   "commands": [result], "failure": {
                       "command": "save_code_review_continuation", "actual_command": "run_step5",
                       "detail": "Actual command returned zero but its artifacts cannot establish completion: "
                                 + handoff_module._ARTIFACT_REFERENCE_LIMIT}})
    return request_id, proof, paths


@pytest.mark.parametrize("reference_limit,archive_count", [(256, 270), (4096, 5600)])
def test_explicit_capture_recovery_preserves_execution_and_requires_native_validation(flow_case, monkeypatch, reference_limit, archive_count):
    request_id, proof, paths = _reference_limit_failure(
        flow_case, monkeypatch, archive_count=archive_count, reference_limit=reference_limit)
    old = deepcopy(_flow(flow_case)._active()["execution"])
    recovered = _flow(flow_case).recover_artifacts(request_id, "5", proof_path=proof, reference="Synthetic tool result")
    current = recovered["request"]["execution"]
    assert current["4"] == old["4"]
    for key in ("run_step5", "run_step5_binding", "pending_invocation", "pending_artifacts", "started_at"):
        assert current["5"][key] == old["5"][key]
    assert current["5"]["status"] == "computed" and recovered["remaining_steps"] == ["5"]
    assert set(paths) <= set(current["5"]["artifacts"])
    history = current["5"]["artifact_recovery_history"][-1]
    assert history["artifact_issues"] == old["5"]["artifact_issues"]
    assert history["computation_reexecuted"] is False and history["native_validation_required"] is True
    assert history["recovery_tool"]["sha256"] == hashlib.sha256(Path(handoff_module.__file__).read_bytes()).hexdigest()
    assert _flow(flow_case).before_command("run_step5", end_step="5", execution_context=_command_context(flow_case))["command_result"] == old["5"]["run_step5"]
    with pytest.raises(HandoffError, match="reference-limit-only"):
        _flow(flow_case).recover_artifacts(request_id, "5", proof_path=proof, reference="Never replay a recovered writer")
    assert _flow(flow_case).before_command("validate_step5", end_step="5", execution_context=_command_context(flow_case))["status"] == "RUN"
    _flow(flow_case).record_command(_command_result("validate_step5"))
    assert _flow(flow_case).status()["remaining_steps"] == []


def test_real_8192_file_limit_includes_case_and_rejects_next_unique_leaf(flow_case):
    # Actual files and the production cap: no small-cap monkeypatch. The case
    # itself counts, and a duplicate leaf must not consume another slot.
    assert handoff_module._MAX_ARTIFACT_REFS == 8192
    flow = _flow(flow_case)
    case_path = Path(flow_case["manifest"]["step_io"]["step5"]["outputs"]["factor_case_master"])
    paths = _many_archive_files(flow_case, count=8191)
    contract = {"step": "5", "paths": [{"path": str(case_path), "direction": "outputs",
                                          "key": "factor_case_master", "required": True}]}
    versions = flow._capture_artifacts(contract)
    assert len(versions) == 8192 and set(paths) <= set(versions)
    # The first 8192 bindings still exist when the next explicit leaf exceeds
    # capacity. Capture must fail, never silently truncate the returned set.
    extra = case_path.parent / "one-more-declared-leaf.parquet"
    extra.write_text("synthetic bulk bytes")
    _write(case_path, {"evidence": {"archive_paths": paths + [paths[0], str(extra)]}})
    with pytest.raises(HandoffError, match="ARTIFACT_REFERENCE_LIMIT"):
        flow._capture_artifacts(contract)


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_5600_leaf_recovery_rejects_late_evidence_without_writing_journal(flow_case, monkeypatch, change):
    request_id, proof, paths = _reference_limit_failure(
        flow_case, monkeypatch, archive_count=5600, reference_limit=4096)
    original_journal = _flow(flow_case).path.read_bytes()
    last = Path(paths[-1])
    if change == "delete":
        last.unlink()
    else:
        last.write_text("changed after the successful writer")
    with pytest.raises(HandoffError, match="ARTIFACT_(MISSING|CHANGED_AFTER_COMMAND)"):
        _flow(flow_case).recover_artifacts(request_id, "5", proof_path=proof, reference="Synthetic actual result")
    assert _flow(flow_case).path.read_bytes() == original_journal


@pytest.mark.parametrize("corruption", [
    "wrong_request", "missing_result", "failed_result", "pending_unknown", "other_issue",
    "argv", "cwd", "time", "proof", "manifest", "material", "checkpoint", "input",
    "late_json", "late_bulk", "restored_bytes_backdated_mtime", "missing_leaf", "directory", "oversized_json",
])
def test_capture_recovery_refuses_unsafe_cases_without_journal_writes(flow_case, monkeypatch, corruption):
    request_id, proof, paths = _reference_limit_failure(flow_case, monkeypatch)
    flow = _flow(flow_case)
    entry = flow._active()
    execution = entry["execution"]["5"]
    if corruption == "wrong_request":
        request_id = "stale-id"
    elif corruption == "missing_result":
        del execution["run_step5"]
    elif corruption == "failed_result":
        execution["run_step5"].update(returncode=1, status="FAIL")
    elif corruption == "pending_unknown":
        execution["status"] = "running"
    elif corruption == "other_issue":
        execution["artifact_issues"].append("ARTIFACT_MISSING:other")
    elif corruption == "argv":
        execution["run_step5"]["command"] = ["different command"]
    elif corruption == "cwd":
        execution["run_step5"]["cwd"] = str(flow_case["workspace"])
    elif corruption == "time":
        execution["run_step5"]["finished_at_utc"] = "2000-01-01T00:00:00Z"
    elif corruption == "proof":
        obj = json.loads(proof.read_text())
        obj["commands"][0]["stdout_tail"] = "invented result"
        _write(proof, obj)
    elif corruption == "manifest":
        _write(flow_case["workspace"] / "runtime-manifest.json", {**flow_case["manifest"], "extra": "changed context"})
    elif corruption == "material":
        flow_case["helper"].write_text("changed helper")
    elif corruption == "checkpoint":
        record = json.loads(flow.review_path.read_text())
        record["decision"] = "revise"
        _write(flow.review_path, record)
    elif corruption == "input":
        (flow_case["workspace"] / "synthetic-metric.csv").write_text("changed input")
    elif corruption == "late_json":
        Path(paths[-5]).write_text('{"changed": true}')
    elif corruption == "late_bulk":
        Path(paths[-1]).write_text("changed bulk")
    elif corruption == "restored_bytes_backdated_mtime":
        path = Path(paths[-5])
        stat, original = path.stat(), path.read_bytes()
        path.write_bytes(original)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif corruption == "missing_leaf":
        Path(paths[-1]).unlink()
    elif corruption == "directory":
        Path(paths[-1]).unlink()
        Path(paths[-1]).mkdir()
    elif corruption == "oversized_json":
        Path(paths[-5]).write_bytes(b" " * (8 * 1024 * 1024 + 1))
    flow._save()  # Test-only corrupt fixture; production recovery must not write.
    original_journal = flow.path.read_bytes()
    with pytest.raises(HandoffError):
        _flow(flow_case).recover_artifacts(request_id, "5", proof_path=proof, reference="Synthetic result")
    assert flow.path.read_bytes() == original_journal


def test_capture_recovery_still_refuses_a_set_above_the_finite_cap(flow_case, monkeypatch):
    request_id, proof, _ = _reference_limit_failure(flow_case, monkeypatch)
    original = _flow(flow_case).path.read_bytes()
    monkeypatch.setattr(handoff_module, "_MAX_ARTIFACT_REFS", 260)
    with pytest.raises(HandoffError, match="ARTIFACT_REFERENCE_LIMIT"):
        _flow(flow_case).recover_artifacts(request_id, "5", proof_path=proof, reference="Synthetic result")
    assert _flow(flow_case).path.read_bytes() == original


def test_cli_capture_recovery_uses_stored_result_and_requires_real_reference(flow_case, monkeypatch):
    request_id, proof, _ = _reference_limit_failure(flow_case, monkeypatch)
    cmd = [sys.executable, "-B", str(REPO / "scripts/manage_factorforge_code_review.py"),
           "recover-artifacts", "--workspace-root", str(flow_case["workspace"]), "--report-id", REPORT,
           "--request-id", request_id, "--step", "5", "--proof", str(proof)]
    before = _flow(flow_case).path.read_bytes()
    cp = subprocess.run(cmd, capture_output=True, text=True)
    assert cp.returncode == 1 and "--reference" in cp.stdout
    assert _flow(flow_case).path.read_bytes() == before
    cp = subprocess.run(cmd + ["--reference", "Synthetic original process result"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert json.loads(cp.stdout)["request"]["execution"]["5"]["status"] == "computed"
