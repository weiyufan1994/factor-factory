from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.code_review_checkpoint import validate_code_review


REPORT_ID = "REVIEW_CASE"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_factorforge_code_review.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case(tmp_path: Path) -> dict:
    workspace = tmp_path / "research"
    repo = tmp_path / "external-repo"
    spec = workspace / "objects" / "factor_spec_master" / "spec.json"
    implementation = workspace / "generated_code" / "factor.py"
    helper = repo / "factor_factory" / "helper.py"
    evidence = workspace / "logs" / "acceptance.log"
    handoff = workspace / "objects" / "handoff" / "handoff.json"
    review = workspace / "objects" / "research_journal" / f"code_review__{REPORT_ID}.json"
    _write_json(spec, {"report_id": REPORT_ID})
    _write_json(handoff, {"factor_impl_ref": "generated_code/factor.py"})
    for path, content in (
        (implementation, "raise RuntimeError('factor code must never execute during validation')\n"),
        (helper, "raise RuntimeError('helper code must never execute during validation')\n"),
        (evidence, "Deterministic acceptance: PASS\n"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    reviewed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    files = [
        {"role": "spec", "path": str(spec.relative_to(workspace)), "sha256": _sha(spec)},
        {"role": "implementation", "path": "generated_code/factor.py", "sha256": _sha(implementation)},
        {"role": "helper", "base": "repo", "path": "factor_factory/helper.py", "sha256": _sha(helper)},
    ]
    record = {
        "report_id": REPORT_ID,
        "author_id": "implementation-agent",
        "reviewer_id": "researcher-agent",
        "reviewed_at": reviewed_at.isoformat(),
        "decision": "proceed",
        "summary": "Reviewed the fixture's spec, implementation and helper; no unresolved issues.",
        "findings": [],
        "reviewed_files": files,
        "post_review_tests": {
            "status": "PASS",
            "started_at": (reviewed_at + timedelta(minutes=1)).isoformat(),
            "completed_at": (reviewed_at + timedelta(minutes=2)).isoformat(),
            "evidence": [{"path": "logs/acceptance.log", "sha256": _sha(evidence)}],
            "tested_files": deepcopy(files),
        },
    }
    _write_json(review, record)
    return {
        "root": tmp_path, "workspace": workspace, "repo": repo, "spec": spec,
        "implementation": implementation, "helper": helper, "evidence": evidence,
        "handoff": handoff, "review": review, "record": record,
    }


def _check(case: dict, *, save: bool = True) -> dict:
    if save:
        _write_json(case["review"], case["record"])
    return validate_code_review(
        workspace_root=case["workspace"], report_id=REPORT_ID,
        handoff=case["handoff"], spec=case["spec"], repo_root=case["repo"],
    )


def _blocked(result: dict, reason: str) -> None:
    assert result["status"] == "BLOCK", result
    assert any(reason in item for item in result["reasons"]), result


def test_valid_review_passes_without_importing_code_or_writing_files(case: dict) -> None:
    before = {path: path.read_bytes() for path in case["root"].rglob("*") if path.is_file()}
    result = _check(case, save=False)
    after = {path: path.read_bytes() for path in case["root"].rglob("*") if path.is_file()}
    assert result["status"] == "PASS"
    assert result["reasons"] == []
    assert result["implementation_path"] == str(case["implementation"])
    assert before == after


def test_missing_review_blocks_without_creating_one(case: dict) -> None:
    case["review"].unlink()
    _blocked(_check(case, save=False), "CODE_REVIEW_RECORD_UNREADABLE")
    assert not case["review"].exists()


@pytest.mark.parametrize("field,value,reason", [
    ("report_id", "OTHER", "REPORT_ID_MISMATCH"),
    ("author_id", " researcher-agent ", "SELF_REVIEW"),
    ("reviewer_id", "", "IDENTITIES_INVALID"),
    ("decision", "revise", "DECISION_NOT_PROCEED"),
    ("summary", "  ", "SUMMARY_MISSING"),
    ("summary", "TODO", "SUMMARY_MISSING"),
    ("findings", [{"summary": "Timing unresolved", "status": "open"}], "FINDING_OPEN"),
])
def test_incomplete_review_blocks(case: dict, field: str, value: object, reason: str) -> None:
    case["record"][field] = value
    _blocked(_check(case), reason)


@pytest.mark.parametrize("status", ["closed", "resolved"])
def test_review_can_record_addressed_findings(case: dict, status: str) -> None:
    case["record"]["findings"] = [{"summary": "Index alignment corrected and re-reviewed", "status": status}]
    assert _check(case)["status"] == "PASS"


@pytest.mark.parametrize("field", ["spec", "implementation", "helper"])
def test_any_reviewed_file_change_requires_real_rereview(case: dict, field: str) -> None:
    path = case[field]
    path.write_bytes(path.read_bytes() + b"\n")
    _blocked(_check(case), "FILE_CHANGED")


def test_new_review_snapshot_cannot_reuse_old_test_snapshot(case: dict) -> None:
    case["implementation"].write_text("# revised implementation\n", encoding="utf-8")
    case["record"]["reviewed_files"][1]["sha256"] = _sha(case["implementation"])
    _blocked(_check(case), "POST_REVIEW_TEST_FILES_MISMATCH")


@pytest.mark.parametrize("which", ["spec", "implementation"])
def test_review_must_bind_actual_spec_and_selected_implementation(case: dict, which: str) -> None:
    index = 0 if which == "spec" else 1
    decoy = case["workspace"] / f"different-{which}.py"
    decoy.write_bytes(case[which].read_bytes())
    case["record"]["reviewed_files"][index]["path"] = str(decoy)
    case["record"]["post_review_tests"]["tested_files"] = deepcopy(case["record"]["reviewed_files"])
    _blocked(_check(case), f"CODE_REVIEW_{which.upper()}_MISMATCH")


def test_tested_files_cannot_omit_a_reviewed_helper(case: dict) -> None:
    case["record"]["post_review_tests"]["tested_files"].pop()
    _blocked(_check(case), "POST_REVIEW_TEST_FILES_MISMATCH")


@pytest.mark.parametrize("minutes", [-1, 0])
def test_tests_must_start_strictly_after_review(case: dict, minutes: int) -> None:
    reviewed_at = datetime.fromisoformat(case["record"]["reviewed_at"])
    case["record"]["post_review_tests"]["started_at"] = (reviewed_at + timedelta(minutes=minutes)).isoformat()
    _blocked(_check(case), "POST_REVIEW_TESTS_NOT_AFTER_REVIEW")


def test_tests_completion_cannot_precede_start(case: dict) -> None:
    case["record"]["post_review_tests"]["completed_at"] = case["record"]["reviewed_at"]
    _blocked(_check(case), "POST_REVIEW_TESTS_INVALID_ORDER")


@pytest.mark.parametrize("field", ["reviewed_at", "started_at", "completed_at"])
def test_future_timestamps_fail_closed(case: dict, field: str) -> None:
    target = case["record"] if field == "reviewed_at" else case["record"]["post_review_tests"]
    target[field] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _blocked(_check(case), "FUTURE")


@pytest.mark.parametrize("field,value", [
    ("author_id", []), ("reviewer_id", {}), ("summary", True),
    ("reviewed_at", 123), ("reviewed_at", "2026-01-01T12:00:00"),
    ("findings", {}), ("findings", [{"summary": "x", "status": []}]),
    ("reviewed_files", {}), ("reviewed_files", [{"role": []}]),
    ("post_review_tests", []),
])
def test_bad_record_types_fail_closed(case: dict, field: str, value: object) -> None:
    case["record"][field] = value
    assert _check(case)["status"] == "BLOCK"


@pytest.mark.parametrize("field,value", [
    ("status", "FAIL"), ("started_at", None), ("completed_at", []),
    ("evidence", []), ("evidence", [42]), ("evidence", ["logs/acceptance.log"]),
    ("tested_files", []),
])
def test_bad_test_records_fail_closed(case: dict, field: str, value: object) -> None:
    case["record"]["post_review_tests"][field] = value
    assert _check(case)["status"] == "BLOCK"


@pytest.mark.parametrize("action", ["missing", "empty", "changed"])
def test_test_evidence_must_exist_and_keep_its_version(case: dict, action: str) -> None:
    if action == "missing":
        case["evidence"].unlink()
    else:
        case["evidence"].write_text("" if action == "empty" else "different result", encoding="utf-8")
    _blocked(_check(case), "POST_REVIEW_TEST_EVIDENCE")


@pytest.mark.parametrize("field", ["factor_impl_ref", "factor_impl_stub_ref", "implementation_path"])
def test_handoff_priority_and_all_supported_fields(case: dict, field: str) -> None:
    fields = ["factor_impl_ref", "factor_impl_stub_ref", "implementation_path"]
    payload = {name: "generated_code/not-selected.py" for name in fields[fields.index(field) + 1:]}
    payload[field] = "generated_code/factor.py"
    _write_json(case["handoff"], payload)
    result = _check(case)
    assert result["status"] == "PASS"
    assert result["implementation_source"] == field


def test_missing_priority_file_does_not_fall_through_to_reviewed_stub(case: dict) -> None:
    _write_json(case["handoff"], {
        "factor_impl_ref": "generated_code/not-reviewed.py",
        "factor_impl_stub_ref": "generated_code/factor.py",
    })
    _blocked(_check(case), "IMPLEMENTATION_MISMATCH")


@pytest.mark.parametrize("canonical", [True, False])
@pytest.mark.parametrize("handoff_value", [None, "TODO"])
def test_spec_implementation_fallback_matches_step4(case: dict, canonical: bool, handoff_value: str | None) -> None:
    _write_json(case["handoff"], {"factor_impl_ref": handoff_value})
    payload = {"implementation_path": "generated_code/factor.py"}
    _write_json(case["spec"], {"canonical_spec": payload} if canonical else payload)
    case["record"]["reviewed_files"][0]["sha256"] = _sha(case["spec"])
    case["record"]["post_review_tests"]["tested_files"] = deepcopy(case["record"]["reviewed_files"])
    assert _check(case)["status"] == "PASS"


@pytest.mark.parametrize("absolute", [True, False])
def test_external_implementation_is_absolute_or_workspace_parent_relative(case: dict, absolute: bool) -> None:
    path = case["root"] / "external-factor.py"
    path.write_bytes(case["implementation"].read_bytes())
    raw = str(path) if absolute else "external-factor.py"
    _write_json(case["handoff"], {"factor_impl_ref": raw})
    case["record"]["reviewed_files"][1]["path"] = raw
    case["record"]["post_review_tests"]["tested_files"] = deepcopy(case["record"]["reviewed_files"])
    assert _check(case)["status"] == "PASS"


@pytest.mark.parametrize("value", [[], {}, 1, True])
def test_bad_implementation_types_block(case: dict, value: object) -> None:
    _write_json(case["handoff"], {"factor_impl_ref": value})
    _blocked(_check(case), "IMPLEMENTATION_REFERENCE_INVALID")


def test_external_helpers_require_explicit_repo_root(case: dict) -> None:
    result = validate_code_review(
        workspace_root=case["workspace"], report_id=REPORT_ID,
        handoff=case["handoff"], spec=case["spec"],
    )
    _blocked(result, "base=repo needs helper role and repo_root")


def test_duplicate_reviewed_path_cannot_claim_two_roles(case: dict) -> None:
    item = deepcopy(case["record"]["reviewed_files"][1])
    item["role"] = "helper"
    case["record"]["reviewed_files"].append(item)
    _blocked(_check(case), "DUPLICATE_PATH")


@pytest.mark.parametrize("content", ["[]", "not-json"])
def test_invalid_json_records_block(case: dict, content: str) -> None:
    case["review"].write_text(content, encoding="utf-8")
    _blocked(_check(case, save=False), "CODE_REVIEW_RECORD")


def test_cli_is_read_only_json_and_uses_zero_or_one_exit_status(case: dict) -> None:
    command = [
        sys.executable, "-B", str(SCRIPT), "--workspace-root", str(case["workspace"]),
        "--report-id", REPORT_ID, "--handoff", "objects/handoff/handoff.json",
        "--spec", "objects/factor_spec_master/spec.json", "--repo-root", str(case["repo"]),
    ]
    before = {path: path.read_bytes() for path in case["root"].rglob("*") if path.is_file()}
    passed = subprocess.run(command, cwd=case["root"], capture_output=True, text=True, check=False)
    assert passed.returncode == 0, passed.stderr + passed.stdout
    assert json.loads(passed.stdout)["status"] == "PASS"
    after = {path: path.read_bytes() for path in case["root"].rglob("*") if path.is_file()}
    assert before == after
    case["review"].unlink()
    blocked = subprocess.run(command, cwd=case["root"], capture_output=True, text=True, check=False)
    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["status"] == "BLOCK"
    assert not case["review"].exists()


def test_cli_bad_arguments_are_json_block_with_exit_one() -> None:
    result = subprocess.run([sys.executable, "-B", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "BLOCK"


def test_synthetic_step4_bug_revise_rereview_and_retest_lifecycle(case: dict) -> None:
    """Synthetic states only: no real agent notification or research-result recomputation."""
    record = case["record"]
    initial_review_at = datetime.fromisoformat(record["reviewed_at"])
    initial = _check(case)
    assert initial["status"] == "PASS"

    # Model a Step4 bug report without running Step4 or notifying another agent.
    record["decision"] = "revise"
    record["findings"] = [{"summary": "Synthetic Step4 bug: boundary alignment needs correction", "status": "open"}]
    reported = _check(case)
    _blocked(reported, "CODE_REVIEW_DECISION_NOT_PROCEED")
    _blocked(reported, "CODE_REVIEW_FINDING_OPEN_OR_INVALID")

    case["implementation"].write_bytes(case["implementation"].read_bytes() + b"# synthetic bug correction\n")
    changed = _check(case)
    _blocked(changed, "FILE_CHANGED")

    # A new review snapshot cannot bless test snapshots/logs from the old code.
    record["reviewed_at"] = (initial_review_at + timedelta(minutes=4)).isoformat()
    record["reviewed_files"][1]["sha256"] = _sha(case["implementation"])
    stale_tests = _check(case)
    _blocked(stale_tests, "POST_REVIEW_TEST_FILES_MISMATCH")
    _blocked(stale_tests, "POST_REVIEW_TESTS_NOT_AFTER_REVIEW")

    # Advance the synthetic chronology: reviewer closes the finding, then the
    # fixture supplies NEW test declarations and evidence for the new version.
    # This is not proof of a real review, test execution, or recalculated result.
    record["decision"] = "proceed"
    record["summary"] = "Synthetic re-review: corrected boundary alignment, no remaining fixture findings."
    record["findings"][0]["status"] = "closed"
    record["reviewed_at"] = (initial_review_at + timedelta(minutes=5)).isoformat()
    tests = record["post_review_tests"]
    tests["started_at"] = (initial_review_at + timedelta(minutes=6)).isoformat()
    tests["completed_at"] = (initial_review_at + timedelta(minutes=7)).isoformat()
    tests["tested_files"] = deepcopy(record["reviewed_files"])
    case["evidence"].write_text("Synthetic fixture acceptance, revised version: PASS\n", encoding="utf-8")
    tests["evidence"][0]["sha256"] = _sha(case["evidence"])
    accepted = _check(case)
    assert accepted["status"] == "PASS"
    assert accepted["reasons"] == []
    assert [stage["status"] for stage in (initial, reported, changed, stale_tests, accepted)] == [
        "PASS", "BLOCK", "BLOCK", "BLOCK", "PASS",
    ]
