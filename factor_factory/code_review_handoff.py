"""Local code-review continuation in the existing research journal.

One Ultimate agent owns journal writes. Reviewers write their own result files.
This module prepares/checks materials and records reported tool outcomes; it
never dispatches agents, executes recorded commands, or authenticates a reviewer.
The existing code_review checkpoint remains the version/test validator.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from factor_factory.code_review_checkpoint import (
    _file_snapshots, _resolve, _timestamp, resolve_review_inputs, validate_code_review,
)
from factor_factory.runtime_context import utc_now, write_json_atomic
from factor_factory.result_artifacts import repair_result_references, result_artifact_paths, validate_result_artifacts
from datetime import datetime, timezone


class HandoffError(ValueError):
    pass


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{label}: nonempty text required")
    return value.strip()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HandoffError(f"Expected JSON object: {path}")
    return value


def _snapshot(path: Path, role: str) -> dict:
    return {"role": role, "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


# Reuse the existing stage IO and the files referenced by its native artifacts.
# JSON envelopes are bounded; bulk files are only stat'ed, never loaded/scanned.
_MAX_ARTIFACT_JSON = 8 * 1024 * 1024
# Multiple diagnostic accounts can declare thousands of checkpoint leaves.
# Keep a finite ceiling and the existing concrete-file/JSON-size restrictions.
_MAX_ARTIFACT_REFS = 8192
_ARTIFACT_REFERENCE_LIMIT = "ARTIFACT_REFERENCE_LIMIT: inspect the declared finite artifact set"
# Step6 owns its Council pause/attachment/finalization lifecycle. This journal
# only guards its reviewed prerequisites; it must not cache Step6 completion.
_CACHED_STEPS = ("4", "5")
_REQUIRED_IO = {
    "4": {"inputs": ("factor_spec_master", "data_prep_master", "handoff_to_step4"),
          "outputs": ("factor_run_master", "factor_run_diagnostics", "handoff_to_step5")},
    "5": {"inputs": ("factor_run_master", "handoff_to_step5"),
          "outputs": ("factor_case_master", "factor_evaluation", "handoff_to_step6")},
}


def _artifact_version(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    if not path.is_file():
        raise HandoffError(f"ARTIFACT_FILE_REQUIRED:{path}; declare concrete files, not a directory tree")
    if path.suffix.lower() == ".json":
        if stat.st_size > _MAX_ARTIFACT_JSON:
            raise HandoffError(f"ARTIFACT_JSON_TOO_LARGE_FOR_REUSE:{path}")
        return {"exists": True, "kind": "bounded_json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {"exists": True, "kind": "file_metadata", "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
            "device": stat.st_dev, "inode": stat.st_ino}


class CodeReviewHandoff:
    """A small journal editor, not a scheduler. Do not use concurrent writers."""

    def __init__(self, workspace_root: str | Path, report_id: str, repo_root: str | Path):
        if (not isinstance(report_id, str) or not report_id.strip()
                or report_id != report_id.strip() or report_id in {".", ".."}
                or any(c in report_id for c in ("/", "\\", "\x00"))):
            raise HandoffError("Invalid report_id")
        self.workspace = Path(workspace_root).resolve()
        self.repo = Path(repo_root).resolve()
        self.report_id = report_id
        folder = self.workspace / "objects" / "research_journal"
        self.path = folder / f"research_journal__{report_id}.json"
        self.review_path = folder / f"code_review__{report_id}.json"
        self.journal = _read(self.path) if self.path.exists() else {"report_id": report_id}
        if self.journal.get("report_id") != report_id:
            raise HandoffError("Journal report_id mismatch")
        self.state = self.journal.get("code_review_coordination", {"active_request_id": None, "requests": []})
        if not isinstance(self.state, dict) or not isinstance(self.state.get("requests"), list):
            raise HandoffError("Invalid code_review_coordination; preserve and repair the journal")

    def _save(self) -> None:
        self.journal["code_review_coordination"] = self.state
        self.journal["updated_at_utc"] = utc_now()
        write_json_atomic(self.path, self.journal)

    def _active(self, request_id: str | None = None) -> dict | None:
        active = self.state.get("active_request_id")
        if request_id is not None and request_id != active:
            raise HandoffError("Stale request_id; read the active handoff before changing it")
        matches = [r for r in self.state["requests"] if r.get("request_id") == active]
        if active is not None and len(matches) != 1:
            raise HandoffError("Active handoff is missing or duplicated")
        return matches[0] if matches else None

    def _current(self, entry: dict) -> list[str]:
        reasons = []
        for item in entry["reviewed_files"] + entry["context_files"]:
            try:
                if _snapshot(Path(item["path"]), item["role"])["sha256"] != item["sha256"]:
                    reasons.append(f"MATERIAL_CHANGED:{item['path']}")
            except (OSError, ValueError):
                reasons.append(f"MATERIAL_UNREADABLE:{item['path']}")
        return reasons

    def _check(self, entry: dict, record: dict, *, tests: bool) -> dict:
        return validate_code_review(
            workspace_root=self.workspace, report_id=self.report_id, repo_root=self.repo,
            handoff=entry["handoff"], spec=entry["spec"], review_record=record,
            require_post_review_tests=tests,
        )

    def _artifact_contract(self, manifest: dict, step: str) -> dict:
        io = (manifest.get("step_io") or {}).get("step" + step)
        if not isinstance(io, dict):
            raise HandoffError(f"STAGE_IO_MISSING:step{step}")
        paths: dict[str, dict] = {}
        for direction in ("inputs", "outputs"):
            declared = io.get(direction)
            if not isinstance(declared, dict) or any(not declared.get(k) for k in _REQUIRED_IO[step][direction]):
                raise HandoffError(f"STAGE_IO_REQUIRED_PATH_MISSING:step{step}.{direction}")
            for key, raw in declared.items():
                # Aggregates are not recursively scanned. Their concrete files
                # are bound below from run/case/payload references. The journal
                # is this editor's own mutable continuation record, not a result.
                if key in ("evaluation_dir", "archive_root", "research_journal"):
                    continue
                path = str(_resolve(raw, self.workspace))
                paths[path] = {"path": path, "direction": direction, "key": key,
                               "required": key in _REQUIRED_IO[step][direction]}
        if step == "4":
            # Step4 owns these outputs even in manifests retaining legacy input
            # aliases. Do not mistake their creation for mutation of an input.
            for key in ("factor_values_parquet", "factor_values_csv", "run_metadata"):
                raw = (manifest.get("runs") or {}).get(key)
                if raw:
                    path = str(_resolve(raw, self.workspace))
                    paths[path] = {"path": path, "direction": "outputs", "key": key, "required": False}
        return {"step": step, "paths": list(paths.values())}

    def _capture_artifacts(self, contract: dict, *, inputs_only: bool = False,
                           payload_overrides: dict[str, dict] | None = None) -> dict:
        versions: dict[str, dict] = {}
        used_overrides: set[str] = set()
        expanded_roles: set[tuple[str, str]] = set()
        queue = [p for p in contract["paths"] if not inputs_only or p["direction"] == "inputs"]
        while queue:
            item = queue.pop(0)
            raw = item["path"]
            if raw in versions:
                if item["required"] and not versions[raw]["exists"]:
                    raise HandoffError(f"ARTIFACT_MISSING:{raw}")
                version = versions[raw]
            else:
                if len(versions) >= _MAX_ARTIFACT_REFS:
                    raise HandoffError(_ARTIFACT_REFERENCE_LIMIT)
                version = _artifact_version(Path(raw))
                if item["required"] and not version["exists"]:
                    raise HandoffError(f"ARTIFACT_MISSING:{raw}")
                versions[raw] = version
            path = Path(raw)
            if not version["exists"] or path.suffix.lower() != ".json":
                continue
            # These are the references consumed by existing Step4/5 validators;
            # this is not generic traversal of every string in a research JSON.
            key = item["key"]
            if key not in ("factor_run_master", "factor_case_master", "backend_payload",
                           "self_quant_payload", "qlib_backtest_payload"):
                continue
            # A file may first appear as a terminal output and later as a
            # payload. Deduplicate versions/count by path, expansion by role.
            if (raw, key) in expanded_roles:
                continue
            expanded_roles.add((raw, key))
            obj = _read(path)
            refs: list[tuple[str, str]] = []
            if key == "factor_run_master":
                refs.extend((p, "result") for p in obj.get("output_paths", []))
                refs.extend((r["payload_path"], "backend_payload")
                            for r in (obj.get("evaluation_results") or {}).get("backend_runs", [])
                            if r.get("status") in ("success", "partial") and r.get("payload_path"))
            elif key == "factor_case_master":
                refs.extend((p, "archive_file") for p in (obj.get("evidence") or {}).get("archive_paths", []))
            else:
                if raw in (payload_overrides or {}):
                    obj = payload_overrides[raw]
                    used_overrides.add(raw)
                try:
                    refs.extend((str(p), "backend_artifact") for p in result_artifact_paths(
                        obj, base_dir=self.workspace).values())
                except ValueError as exc:
                    raise HandoffError(str(exc)) from exc
            for ref, ref_key in refs:
                queue.append({"path": str(_resolve(ref, self.workspace)), "direction": item["direction"],
                              "key": ref_key, "required": True})
        if set(payload_overrides or {}) != used_overrides:
            raise HandoffError('REFERENCE_REPAIR_PAYLOAD_NOT_DECLARED_BY_STAGE')
        return versions

    @staticmethod
    def _changed_artifacts(versions: dict) -> list[str]:
        changed = []
        for raw, before in versions.items():
            try:
                if _artifact_version(Path(raw)) != before:
                    changed.append(f"ARTIFACT_CHANGED_OR_MISSING:{raw}")
            except (OSError, ValueError) as exc:
                changed.append(f"ARTIFACT_UNREADABLE:{raw}:{exc}")
        return changed

    def prepare(self, request: dict) -> dict:
        """Bind author-selected source/spec/code/helpers and a bounded resume point."""
        if not isinstance(request, dict):
            raise HandoffError("Preparation input must be a JSON object")
        keys = ("issue_id", "summary", "author_id", "reviewer_id", "materials_note")
        fields = {key: _text(request.get(key), key) for key in keys}
        if fields["author_id"].casefold() == fields["reviewer_id"].casefold():
            raise HandoffError("The Step2 reviewer must differ from the implementer")
        origin = request.get("origin_step")
        if origin not in ("3b", "4", "5"):
            raise HandoffError("origin_step must be 3b, 4 or 5; poor returns alone are not a defect")
        resume = deepcopy(request.get("resume"))
        if (not isinstance(resume, dict) or resume.get("start_step") not in ("4", "5")
                or resume.get("end_step") not in ("4", "5", "6")
                or resume["start_step"] > resume["end_step"]):
            raise HandoffError("Declare resume.start_step 4/5 and end_step 4/5/6 within existing scope")
        _text(resume.get("reason"), "resume.reason")
        if not isinstance(resume.get("unusable_evidence", []), list):
            raise HandoffError("resume.unusable_evidence must name affected outputs; do not delete them")
        selected = resolve_review_inputs(workspace_root=self.workspace,
                                         handoff=request.get("handoff"), spec=request.get("spec"))
        if selected["reasons"]:
            raise HandoffError("; ".join(selected["reasons"]))
        files = [_snapshot(Path(selected["spec_path"]), "spec"),
                 _snapshot(Path(selected["implementation_path"]), "implementation")]
        helpers = request.get("helpers")
        if not isinstance(helpers, list):
            raise HandoffError("Declare helpers explicitly (an empty list needs an honest materials_note)")
        for helper in helpers:
            if not isinstance(helper, dict) or helper.get("base", "workspace") not in ("workspace", "repo"):
                raise HandoffError("Each helper needs a path and workspace/repo base")
            base = self.repo if helper.get("base") == "repo" else self.workspace
            files.append(_snapshot(_resolve(helper.get("path"), base), "helper"))
        reasons: list[str] = []
        _file_snapshots(files, label="MATERIALS", workspace=self.workspace,
                        repo=self.repo, reasons=reasons, check_current=True)
        if reasons:
            raise HandoffError("; ".join(reasons))
        context = request.get("context_files")
        if not isinstance(context, list) or not any(isinstance(x, dict) and x.get("role") == "source" for x in context):
            raise HandoffError("context_files must include the actual source/hypothesis")
        contexts = [_snapshot(Path(selected["handoff_path"]), "handoff")]
        for item in context:
            if not isinstance(item, dict) or item.get("role") not in ("source", "notes", "test"):
                raise HandoffError("Context roles are source, notes or test; only explicit files are read")
            contexts.append(_snapshot(_resolve(item.get("path"), self.workspace), item["role"]))
        bound = {**fields, "origin_step": origin, "resume": resume,
                 "spec": selected["spec_path"], "handoff": selected["handoff_path"],
                 "reviewed_files": sorted(files, key=lambda x: (x["role"], x["path"])),
                 "context_files": sorted(contexts, key=lambda x: (x["role"], x["path"]))}
        # Prose edits cannot cause repeated dispatch for the same issue/version.
        identity = {k: v for k, v in bound.items() if k not in ("summary", "materials_note")}
        fingerprint = _digest({"report_id": self.report_id, **identity})[:24]
        active = self._active()
        if active and active.get("material_fingerprint", active["request_id"]) == fingerprint:
            return {**self.status(), "created": False, "matched_request_id": active["request_id"]}
        if active and active["delivery"]["status"] in ("dispatching", "unknown"):
            raise HandoffError("Delivery outcome unknown; reconcile the existing tool call before new work")
        if active and any(v.get("status") in ("running", "validating")
                          for s, v in active["execution"].items() if s in _CACHED_STEPS):
            raise HandoffError("Execution outcome unknown; reconcile the pending command before new work")
        prior_materials = [r for r in self.state["requests"]
                           if r.get("material_fingerprint", r["request_id"]) == fingerprint]
        round_no = len(self.state["requests"]) + 1
        request_id = _digest({"material_fingerprint": fingerprint, "round": round_no,
                              "previous_request_id": active["request_id"] if active else None})[:24]
        entry = {**bound, "request_id": request_id, "material_fingerprint": fingerprint,
                 "request_round": round_no, "reuses_materials_from": prior_materials[-1]["request_id"] if prior_materials else None,
                 "created_at": utc_now(),
                 "status": "prepared", "owner": "Ultimate", "delivery": {"status": "not_sent"},
                 "delivery_history": [], "review_history": [], "test_runs": [], "execution": {},
                 "previous_request_id": active["request_id"] if active else None}
        self.state["requests"].append(entry)
        self.state["active_request_id"] = request_id
        self._save()
        return {**self.status(), "created": True}

    def delivery(self, request_id: str, outcome: str, reference: str, *, retry_reason: str = "") -> dict:
        """Record intent BEFORE an actual tool call; record the actual outcome AFTER it."""
        entry = self._active(request_id)
        if entry is None:
            raise HandoffError("Prepare materials first")
        _text(reference, "tool reference or reason")
        old = entry["delivery"]
        if outcome == "begin":
            if self._current(entry):
                raise HandoffError("Materials changed; prepare a new version before dispatch")
            if old["status"] not in ("not_sent", "failed"):
                return {**self.status(), "send_allowed": False}
            if old["status"] == "failed":
                _text(retry_reason, "Known non-delivery needs an explicit retry reason")
            entry["delivery"] = {"status": "dispatching", "started_at": utc_now(), "reference": reference}
            entry["status"], entry["owner"] = "dispatching", "Ultimate"
        else:
            if outcome not in ("sent", "failed", "unknown"):
                raise HandoffError("Outcome must be begin, sent, failed (known non-delivery), or unknown")
            if old["status"] == outcome and old.get("reference") == reference:
                return {**self.status(), "send_allowed": False}
            if old["status"] not in ("dispatching", "unknown"):
                raise HandoffError("Record dispatch intent first; do not manufacture a sent transition")
            entry["delivery"] = {**old, "status": outcome, "recorded_at": utc_now(), "reference": reference}
            entry["status"] = "awaiting_review" if outcome == "sent" else f"delivery_{outcome}"
            entry["owner"] = entry["reviewer_id"] if outcome == "sent" else "Ultimate"
        entry["delivery_history"].append(deepcopy(entry["delivery"]))
        self._save()
        return {**self.status(), "send_allowed": outcome == "begin"}

    def receive_review(self, request_id: str, result_path: str | Path) -> dict:
        entry = self._active(request_id)
        if entry is None or entry["delivery"]["status"] != "sent":
            raise HandoffError("No confirmed dispatch for this review")
        path = _resolve(result_path, self.workspace)
        try:
            record = _read(path)
            if record == entry.get("review") or any(r["review"] == record for r in entry.get("review_history", [])):
                return self.status()
            errors = self._current(entry)
            if (record.get("request_id") != request_id or record.get("author_id") != entry["author_id"]
                    or record.get("reviewer_id") != entry["reviewer_id"]):
                errors.append("REVIEW_REQUEST_OR_ROLE_MISMATCH")
            if "post_review_tests" in record:
                errors.append("REVIEW_CANNOT_SUPPLY_POST_REVIEW_TESTS")
            reasons: list[str] = []
            reviewed = _file_snapshots(record.get("reviewed_files"), label="REVIEW", workspace=self.workspace,
                                       repo=self.repo, reasons=reasons, check_current=True)
            expected = _file_snapshots(entry["reviewed_files"], label="MATERIALS", workspace=self.workspace,
                                       repo=self.repo, reasons=reasons, check_current=False)
            errors.extend(reasons)
            if reviewed != expected:
                errors.append("REVIEW_MUST_BIND_ALL_DISPATCHED_FILES_INCLUDING_HELPERS")
            result = self._check(entry, record, tests=False)
            allowed = ("CODE_REVIEW_DECISION_NOT_PROCEED", "CODE_REVIEW_FINDING_OPEN_OR_INVALID:")
            errors.extend(r for r in result["reasons"] if not (
                record.get("decision") == "revise" and r.startswith(allowed)))
            if record.get("decision") not in ("proceed", "revise"):
                errors.append("REVIEW_DECISION_INVALID")
            for finding in record.get("findings", []):
                if not isinstance(finding, dict) or finding.get("status") not in ("open", "closed", "resolved"):
                    errors.append("REVIEW_FINDING_STATUS_INVALID")
            now = datetime.now(timezone.utc)
            reviewed_at = _timestamp(record.get("reviewed_at"), "REVIEW_TIME", now, errors)
            sent_at = _timestamp(entry["delivery"]["started_at"], "DISPATCH_TIME", now, errors)
            if reviewed_at and sent_at and reviewed_at < sent_at:
                errors.append("REVIEW_PREDATES_DISPATCH")
            if errors:
                raise HandoffError("; ".join(errors))
        except (OSError, ValueError, TypeError) as exc:
            entry.setdefault("intake_failures", []).append({"at": utc_now(), "path": str(path), "reason": str(exc)})
            entry["status"], entry["owner"] = "review_invalid", entry["reviewer_id"]
            self._save()
            raise HandoffError(str(exc)) from exc
        # Keep successive reviews even when no source/code byte changed. Seed a
        # pre-existing current review without inventing a historical receipt time.
        history = entry.setdefault("review_history", [])
        if entry.get("review") and not history:
            history.append({"review": deepcopy(entry["review"]), "result_path": entry.get("review_result_path"),
                            "received_at": None, "disposition": entry["review"]["summary"],
                            "retained_from_existing_current_review": True})
        history.append({"review": deepcopy(record), "result_path": str(path), "received_at": utc_now(),
                        "disposition": record["summary"], "supersedes_review_number": len(history) or None})
        entry["review"], entry["review_result_path"] = deepcopy(record), str(path)
        entry["status"] = "awaiting_tests" if record["decision"] == "proceed" else "changes_requested"
        entry["owner"] = entry["author_id"]
        write_json_atomic(self.review_path, record)
        self._save()
        return self.status()

    def record_tests(self, request_id: str, evidence_path: str | Path) -> dict:
        entry = self._active(request_id)
        if entry is None or entry.get("review", {}).get("decision") != "proceed":
            raise HandoffError("Actual proceed review is required before post-review tests")
        if self._current(entry):
            raise HandoffError("Materials changed; return to Step2 before recording new tests")
        try:
            tests = _read(_resolve(evidence_path, self.workspace))
        except (OSError, ValueError, TypeError) as exc:
            entry.setdefault("test_intake_failures", []).append({"at": utc_now(), "path": str(evidence_path), "reason": str(exc)})
            entry["status"], entry["owner"] = "tests_invalid", entry["author_id"]
            self._save()
            raise HandoffError(str(exc)) from exc
        if entry["test_runs"] and entry["test_runs"][-1]["tests"] == tests:
            return self.status()
        record = {**entry["review"], "post_review_tests": tests}
        check = self._check(entry, record, tests=True)
        entry["test_runs"].append({"at": utc_now(), "tests": tests, "check": check})
        entry["status"] = "ready" if check["status"] == "PASS" else "tests_failed"
        entry["owner"] = "Ultimate" if check["status"] == "PASS" else entry["author_id"]
        write_json_atomic(self.review_path, record)
        self._save()
        return self.status()

    def status(self) -> dict:
        entry = self._active()
        if entry is None:
            return {"status": "NOT_MANAGED", "journal_path": str(self.path)}
        reasons = self._current(entry)
        state, owner = entry["status"], entry["owner"]
        if reasons:
            state, owner = "stale_materials", entry["author_id"]
        if state == "ready":
            try:
                record = _read(self.review_path)
                if {k: v for k, v in record.items() if k != "post_review_tests"} != entry["review"]:
                    reasons.append("ACCEPTED_REVIEW_CHANGED")
                if record.get("post_review_tests") != entry["test_runs"][-1]["tests"]:
                    reasons.append("ACCEPTED_TEST_RECORD_CHANGED")
                reasons.extend(self._check(entry, record, tests=True)["reasons"])
            except (OSError, ValueError, KeyError, IndexError) as exc:
                reasons.append(f"ACCEPTED_CHECKPOINT_UNREADABLE:{exc}")
            if reasons:
                state, owner = "checkpoint_blocked", entry["author_id"]
        steps = [str(i) for i in range(int(entry["resume"]["start_step"]), int(entry["resume"]["end_step"]) + 1)]
        # Preserve any earlier Step6 cache as history, but never use it to
        # authorize, block or skip the native Step6 lifecycle.
        executions = {s: v for s, v in entry["execution"].items() if s in _CACHED_STEPS}
        stale_stages: dict[str, list[str]] = {}
        for step, execution in executions.items():
            if execution.get("status") in ("computed", "complete"):
                versions = execution.get("artifacts")
                issues = (self._changed_artifacts(versions) if versions else
                          [f"ARTIFACT_SNAPSHOT_MISSING:step{step}"])
            else:
                issues = execution.get("artifact_issues", [])
            if issues:
                stale_stages[step] = issues
                reasons.extend(issues)
        affected_step = min(stale_stages) if stale_stages else None
        if affected_step:
            state, owner = "stage_artifacts_blocked", "Ultimate"
        completed = [s for s, v in executions.items() if v.get("status") == "complete"
                     and (affected_step is None or s < affected_step)]
        remaining = [s for s in steps if s not in completed]
        uncertain = [s for s, v in executions.items() if v.get("status") in ("running", "validating")]
        failed = [s for s, v in executions.items() if v.get("status") == "failed"]
        if uncertain:
            reasons.append("EXECUTION_OUTCOME_UNKNOWN:" + ",".join(uncertain))
        if failed:
            reasons.append("EXECUTION_FAILED_TRIAGE_REQUIRED:" + ",".join(failed))
        ready = state == "ready" and not reasons
        return {"status": "READY" if ready else "BLOCK", "state": state, "owner": owner,
                "request_id": entry["request_id"], "journal_path": str(self.path),
                "reasons": reasons, "remaining_steps": remaining,
                "resume": ({**entry["resume"], "start_step": remaining[0]} if ready and remaining else None),
                "artifact_recovery": ({"step": affected_step, "owner": "Ultimate with Step2/Step3",
                                       "issues": stale_stages,
                                       "next_action": "Inspect/restore the bound artifacts or prepare an explicit repair issue at this step; retain failed evidence. Do not reuse the old validator PASS or replay computation automatically."}
                                      if affected_step else None),
                "delivery": deepcopy(entry["delivery"]), "request": deepcopy(entry),
                "step6_followup": ({"run_report": str(self.workspace / "objects" / "runtime_context" / f"ultimate_run_report__{self.report_id}.json"),
                                    "instruction": "Handoff only: use the native Step6/Council pause, attachment and final outcome. This journal neither caches Step6 commands nor determines Step6 completion."}
                                   if ready and remaining == ["6"] else None),
                "cached_execution_steps": list(_CACHED_STEPS),
                "independence_authenticated": False, "scope": "local code review coordination only"}

    def before_command(self, name: str, *, end_step: str,
                       spec: str | Path | None = None, handoff: str | Path | None = None,
                       execution_context: dict | None = None) -> dict:
        """Cache Step4/5 intent/results, or hand guarded prerequisites to Step6.

        It is the wrapper, not this function, that executes its own fixed argv.
        A cached command with unknown outcome is never automatically retried.
        Native Step6 owns its own pauses, command results and recovery decisions.
        """
        entry = self._active()
        if entry is None or name not in {f"{kind}_step{s}" for kind in ("run", "validate") for s in ("4", "5", "6")}:
            return {"status": "NOT_MANAGED"}
        for label, path in (("spec", spec), ("handoff", handoff)):
            if path is not None and str(_resolve(path, self.workspace)) != entry[label]:
                raise HandoffError(f"Journal {label} differs from the wrapper manifest")
        view = self.status()
        step = name[-1]
        if end_step > entry["resume"]["end_step"] or step < entry["resume"]["start_step"]:
            raise HandoffError("Resume exceeds the recorded scope or restarts unrelated completed work")
        if view["status"] != "READY":
            raise HandoffError(f"Code review handoff blocked: {view['state']}; {view['reasons']}")
        remaining = view["remaining_steps"]
        if step == "6":
            if remaining and step != remaining[0]:
                raise HandoffError("Resume skips an unfinished affected step")
            return {"status": "NATIVE_STEP6", "followup": view["step6_followup"]}
        execution = entry["execution"].setdefault(step, {})
        if not isinstance(execution_context, dict):
            raise HandoffError("Actual command, cwd and runtime manifest are required before execution")
        command, raw_cwd = execution_context.get("command"), execution_context.get("cwd")
        if (not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or not arg for arg in command)):
            raise HandoffError("Pending command must be the actual nonempty argv list")
        cwd = str(_resolve(_text(raw_cwd, "pending cwd"), self.repo))
        contract = self._artifact_contract(execution_context.get("manifest") or {}, step)
        if execution.get("artifact_contract") and execution["artifact_contract"] != contract:
            raise HandoffError("Stage artifact paths changed; reconcile instead of reusing completion")
        binding = _digest(execution_context)
        if name in execution:
            if execution.get(name + "_binding") != binding:
                raise HandoffError("Completed command/runtime manifest differs; do not reuse or automatically rerun it")
            return {"status": "REUSE", "command_result": deepcopy(execution[name])}
        if remaining and step != remaining[0]:
            raise HandoffError("Resume skips an unfinished affected step")
        if name.startswith("validate") and execution.get("status") != "computed":
            raise HandoffError("Cannot validate before a successful execution")
        before_artifacts = self._capture_artifacts(contract, inputs_only=name.startswith("run"))
        execution.update(status="validating" if name.startswith("validate") else "running", started_at=utc_now(), pending_command=name)
        execution["pending_invocation"] = {"name": name, "command": deepcopy(command), "cwd": cwd}
        execution["artifact_contract"] = contract
        execution["pending_artifacts"] = before_artifacts
        execution[name + "_binding"] = binding
        self._save()
        return {"status": "RUN"}

    def _command_result_issues(self, execution: dict, result: dict) -> list[str]:
        reasons: list[str] = []
        pending = execution.get("pending_invocation") or {}
        if result.get("command") != pending.get("command") or not pending.get("command"):
            reasons.append("COMMAND_ARGV_MISMATCH")
        try:
            result_cwd = str(_resolve(_text(result.get("cwd"), "result cwd"), self.repo))
        except (ValueError, OSError):
            result_cwd = None
        if result_cwd != pending.get("cwd") or not pending.get("cwd"):
            reasons.append("COMMAND_CWD_MISMATCH")
        now = datetime.now(timezone.utc)
        started = _timestamp(result.get("started_at_utc"), "COMMAND_START", now, reasons)
        finished = _timestamp(result.get("finished_at_utc"), "COMMAND_FINISH", now, reasons)
        intent = _timestamp(execution["started_at"], "COMMAND_INTENT", now, reasons)
        if started and finished and intent and not intent <= started <= finished:
            reasons.append("COMMAND_TIME_ORDER_INVALID")
        code = result.get("returncode")
        if type(code) is not int or result.get("status") != ("PASS" if code == 0 else "FAIL"):
            reasons.append("COMMAND_OUTCOME_INVALID")
        return reasons

    def record_command(self, result: dict) -> None:
        entry = self._active()
        name = result["name"]
        if entry is None or name not in {f"{kind}_step{s}" for kind in ("run", "validate") for s in _CACHED_STEPS}:
            raise HandoffError("Only active local Step4/5 commands can be reconciled here; Step6 uses its native lifecycle")
        step = name[-1]
        execution = entry["execution"].get(step, {})
        expected = "validating" if name.startswith("validate") else "running"
        if execution.get("status") != expected or execution.get("pending_command") != name:
            raise HandoffError("Execution result requires a matching pending wrapper command")
        reasons = self._command_result_issues(execution, result)
        if reasons:
            execution.setdefault("result_rejections", []).append({"at": utc_now(), "reasons": reasons,
                                                                  "command": result.get("command"), "cwd": result.get("cwd")})
            self._save()
            raise HandoffError("; ".join(reasons))
        execution[name] = deepcopy(result)
        if result["returncode"] == 0:
            try:
                changes = self._changed_artifacts(execution["pending_artifacts"])
                if changes:
                    raise HandoffError("; ".join(changes))
                execution["artifacts"] = self._capture_artifacts(execution["artifact_contract"])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                execution["status"], execution["artifact_issues"] = "artifacts_blocked", [str(exc)]
                entry["execution"][step] = execution
                self._save()
                raise HandoffError(f"Actual command returned zero but its artifacts cannot establish completion: {exc}") from exc
        execution["status"] = ("complete" if name.startswith("validate") else "computed") if result.get("returncode") == 0 else "failed"
        entry["execution"][step] = execution
        self._save()

    def recover_artifacts(self, request_id: str, step: str, *,
                          proof_path: str | Path, reference: str,
                          repair_path: str | Path | None = None) -> dict:
        """Bind a known successful writer after a supported reference failure.

        No producer or validator is executed. Original argv/runtime/result stay
        historical evidence; this tool's identity and later capture are separate.
        A fresh native validator is still required after recovery to computed.
        """
        reference = _text(reference, "recovery reference")
        entry = self._active(request_id)
        if entry is None or step not in _CACHED_STEPS:
            raise HandoffError("Artifact recovery requires an active Step4/5 request")
        name = "run_step" + step
        execution = entry["execution"].get(step, {})
        artifact_issues = execution.get('artifact_issues') or []
        repair_directory = (repair_path is not None and len(artifact_issues) == 1
                            and artifact_issues[0].startswith('ARTIFACT_FILE_REQUIRED:'))
        if (execution.get("status") != "artifacts_blocked"
                or execution.get("pending_command") != name
                or (not repair_directory and (repair_path is not None or artifact_issues != [_ARTIFACT_REFERENCE_LIMIT]))):
            raise HandoffError("Artifact recovery requires a reference-limit-only blocked writer or an explicit directory reference repair")
        view = self.status()
        if entry["status"] != "ready" or view["reasons"] != artifact_issues:
            raise HandoffError(f"Artifact recovery has other blockers: {view['reasons']}")
        result = execution.get(name)
        if (not isinstance(result, dict) or result.get("name") != name
                or type(result.get("returncode")) is not int or result["returncode"] != 0
                or result.get("status") != "PASS"):
            raise HandoffError("Artifact recovery requires the stored actual zero-return writer result")
        issues = self._command_result_issues(execution, result)
        if issues:
            raise HandoffError("; ".join(issues))

        proof_file = _resolve(proof_path, self.workspace)
        if proof_file.suffix.lower() != ".json":
            raise HandoffError("Recovery proof must be the original bounded JSON wrapper report")
        proof_version = _artifact_version(proof_file)
        proof = _read(proof_file)
        failure = proof.get("failure") or {}
        commands = proof.get("commands")
        if (not isinstance(failure, dict) or not isinstance(commands, list)
                or any(not isinstance(x, dict) for x in commands)
                or proof.get("report_id") != self.report_id or proof.get("status") != "FAIL"
                or failure.get("command") != "save_code_review_continuation"
                or failure.get("actual_command") != name
                or failure.get("detail") != "Actual command returned zero but its artifacts cannot establish completion: " + artifact_issues[0]
                or [x for x in commands if x.get("name") == name] != [result]):
            raise HandoffError("Original wrapper failure/result does not match the stored writer")
        manifest_file = _resolve(proof.get("manifest_path"), self.workspace)
        if manifest_file.suffix.lower() != ".json":
            raise HandoffError("Recovery manifest must be bounded JSON")
        manifest_version = _artifact_version(manifest_file)
        manifest = _read(manifest_file)
        context = {"command": result["command"], "cwd": result["cwd"],
                   "manifest": {k: v for k, v in manifest.items() if k != "created_at_utc"}}
        if (execution.get(name + "_binding") != _digest(context)
                or execution.get("artifact_contract") != self._artifact_contract(manifest, step)):
            raise HandoffError("Original command/runtime manifest binding changed")
        issues = self._changed_artifacts(execution["pending_artifacts"])
        if issues:
            raise HandoffError("; ".join(issues))
        repair = None
        if repair_directory:
            repair = self._prepare_reference_repair(execution, repair_path, artifact_issues[0])
        overrides = {repair['path']: repair['corrected']} if repair else None
        versions = self._capture_artifacts(execution["artifact_contract"], payload_overrides=overrides)
        # Legacy failures did not persist an output snapshot. Conservatively
        # reject any file changed/replaced since the actual writer finished,
        # including restored bytes or backdated mtime (ctime still changes).
        # This is ordinary filesystem change detection, not historical hashing.
        finished = datetime.fromisoformat(result["finished_at_utc"].replace("Z", "+00:00"))
        finished_ns = int(finished.timestamp() * 1_000_000_000)
        for raw, version in versions.items():
            if version["exists"]:
                stat = Path(raw).stat()
                if max(stat.st_mtime_ns, stat.st_ctime_ns) > finished_ns:
                    raise HandoffError(f"ARTIFACT_CHANGED_AFTER_COMMAND:{raw}")
        issues = self._changed_artifacts(versions)
        issues.extend(self._changed_artifacts({str(proof_file): proof_version,
                                              str(manifest_file): manifest_version}))
        if issues:
            raise HandoffError("; ".join(issues))
        repair_receipt = None
        if repair:
            repair_receipt = self._apply_reference_repair(entry, step, repair, versions)
            versions = self._capture_artifacts(execution['artifact_contract'])
            issues = self._changed_artifacts({str(proof_file): proof_version, str(manifest_file): manifest_version})
            if issues:
                raise HandoffError('; '.join(issues))
        recovered = deepcopy(execution)
        recovered.setdefault("artifact_recovery_history", []).append({
            "recorded_at": utc_now(), "reference": reference,
            "previous_status": execution["status"], "artifact_issues": deepcopy(execution["artifact_issues"]),
            "original_command_sha256": _digest(result),
            "original_wrapper_proof": {"path": str(proof_file), **proof_version},
            "recovery_tool": _snapshot(Path(__file__), "artifact_capture_recovery"),
            "artifact_count": len(versions), "max_artifact_refs": _MAX_ARTIFACT_REFS,
            "computation_reexecuted": False, "native_validation_required": True,
            **({'reference_repair': repair_receipt} if repair_receipt else {}),
        })
        recovered.update(status="computed", artifacts=versions, artifact_issues=[])
        entry["execution"][step] = recovered
        self._save()
        return self.status()

    def _prepare_reference_repair(self, execution: dict, repair_path: str | Path, original_issue: str) -> dict:
        """Dry projection only. All references must pass capture and age checks before writing."""
        request_file = _resolve(repair_path, self.workspace)
        if request_file.suffix.lower() != '.json':
            raise HandoffError('REFERENCE_REPAIR_REQUEST_MUST_BE_BOUNDED_JSON')
        request_version = _artifact_version(request_file)
        request = _read(request_file)
        path = _resolve(_text(request.get('path'), 'repair payload path'), self.workspace)
        if path.suffix.lower() != '.json' or str(path) in execution['pending_artifacts']:
            raise HandoffError('REFERENCE_REPAIR_REQUIRES_OUTPUT_PAYLOAD')
        original_version = _artifact_version(path)
        if original_version.get('sha256') != request.get('sha256'):
            raise HandoffError('REFERENCE_REPAIR_ORIGINAL_HASH_MISMATCH')
        original_bytes = path.read_bytes()
        original = json.loads(original_bytes)
        if validate_result_artifacts(original, base_dir=self.workspace) != [original_issue]:
            raise HandoffError('REFERENCE_REPAIR_ORIGINAL_FAILURE_MISMATCH')
        corrected = repair_result_references(original, request, base_dir=self.workspace)
        if len(json.dumps(corrected, ensure_ascii=False, indent=2).encode()) > _MAX_ARTIFACT_JSON:
            raise HandoffError('REFERENCE_REPAIR_PAYLOAD_TOO_LARGE')
        return {'path': str(path), 'original_bytes': original_bytes, 'corrected': corrected,
                'original_version': original_version, 'original_stat': path.stat(),
                'request_file': str(request_file), 'request_version': request_version}

    def recover_source_version(self, request_id: str, *, proof_path: str | Path,
                               release_record: str | Path, reference: str, dry_run: bool = False) -> dict:
        """Correct only an unknown source commit after the corresponding native rejection.

        Keeps the original writer and failed validator as evidence. A fresh native
        validator must run; the old writer stays cached with its original binding.
        """
        from factor_factory.source_version import verify_source_archive
        reference = _text(reference, 'recovery reference')
        entry = self._active(request_id)
        execution = (entry or {}).get('execution', {}).get('4', {})
        view = self.status()
        result = execution.get('validate_step4') or {}
        writer = execution.get('run_step4') or {}
        if (not entry or entry['status'] != 'ready' or execution.get('status') != 'failed'
                or execution.get('pending_command') != 'validate_step4'
                or view['reasons'] != ['EXECUTION_FAILED_TRIAGE_REQUIRED:4']
                or result.get('returncode') != 1 or result.get('status') != 'FAIL'
                or writer.get('returncode') != 0 or writer.get('status') != 'PASS'):
            raise HandoffError('SOURCE_RECOVERY_REQUIRES_FAILED_NATIVE_VALIDATOR_AND_SUCCESSFUL_WRITER')
        issues = self._command_result_issues(execution, result)
        versions = execution.get('artifacts') or {}
        if not versions:
            raise HandoffError('SOURCE_RECOVERY_ARTIFACT_SNAPSHOT_REQUIRED')
        issues.extend(self._changed_artifacts(versions))
        if issues:
            raise HandoffError('; '.join(issues))
        proof_file = _resolve(proof_path, self.workspace)
        if proof_file.suffix.lower() != '.json':
            raise HandoffError('SOURCE_RECOVERY_PROOF_MUST_BE_BOUNDED_JSON')
        proof_version = _artifact_version(proof_file)
        proof = _read(proof_file)
        if (proof.get('status') != 'FAIL' or proof.get('report_id') != self.report_id
                or proof.get('failure') != {'command': 'validate_step4', 'returncode': 1}
                or [x for x in proof.get('commands', []) if x.get('name') == 'validate_step4'] != [result]):
            raise HandoffError('SOURCE_RECOVERY_ORIGINAL_VALIDATOR_PROOF_MISMATCH')
        manifest_file = _resolve(proof.get('manifest_path'), self.workspace)
        manifest_version = _artifact_version(manifest_file)
        manifest = _read(manifest_file)
        if execution['artifact_contract'] != self._artifact_contract(manifest, '4'):
            raise HandoffError('SOURCE_RECOVERY_STAGE_PATHS_CHANGED')
        for name, command in (('run_step4', writer), ('validate_step4', result)):
            context = {'command': command['command'], 'cwd': command['cwd'],
                       'manifest': {k: v for k, v in manifest.items() if k != 'created_at_utc'}}
            if execution.get(name + '_binding') != _digest(context):
                raise HandoffError('SOURCE_RECOVERY_COMMAND_RUNTIME_BINDING_CHANGED')
        revision_path = self.workspace / 'objects/validation' / f'factor_run_validation_revision__{self.report_id}.json'
        revision_version = _artifact_version(revision_path)
        revision = _read(revision_path)
        errors = [x.get('code') for x in revision.get('issues', []) if x.get('severity') == 'error']
        if (revision.get('report_id') != self.report_id or revision.get('verdict') != 'FAIL'
                or errors != ['BLOCK_ACCEPTANCE_SUMMARY_REPO_IDENTITY_INVALID']):
            raise HandoffError('SOURCE_RECOVERY_REQUIRES_ONLY_UNKNOWN_REPO_VERSION_ERROR')
        finished = datetime.fromisoformat(result['finished_at_utc'].replace('Z', '+00:00')).timestamp()
        if max(revision_path.stat().st_mtime, revision_path.stat().st_ctime) > finished:
            raise HandoffError('SOURCE_RECOVERY_VALIDATION_EVIDENCE_CHANGED_AFTER_COMMAND')
        release_file = _resolve(release_record, self.repo)
        source = verify_source_archive(self.repo, release_file)
        started = datetime.fromisoformat(writer['started_at_utc'].replace('Z', '+00:00')).timestamp()
        if max(release_file.stat().st_mtime, release_file.stat().st_ctime) > started:
            raise HandoffError('SOURCE_RECOVERY_RELEASE_RECORD_POSTDATES_WRITER')
        run_path = next(Path(p['path']) for p in execution['artifact_contract']['paths']
                        if p['key'] == 'factor_run_master' and p['direction'] == 'outputs')
        original = run_path.read_bytes()
        corrected = json.loads(original)
        if (corrected.get('acceptance_summary') or {}).get('repo_sha') != 'unknown':
            raise HandoffError('SOURCE_RECOVERY_ONLY_UNKNOWN_FIELD_MAY_CHANGE')
        corrected['acceptance_summary']['repo_sha'] = source['commit']
        checks = {**versions, str(proof_file): proof_version, str(manifest_file): manifest_version,
                  str(revision_path): revision_version, str(release_file): _artifact_version(release_file)}
        issues = self._changed_artifacts(checks)
        if issues:
            raise HandoffError('; '.join(issues))
        if dry_run:
            return {'status': 'READY_FOR_METADATA_REPAIR', 'source': source,
                    'run_master': {'path': str(run_path), **versions[str(run_path)]},
                    'artifact_count': len(versions), 'computation_reexecuted': False,
                    'native_validation_required': True, 'writes_performed': False}
        audit = self.path.parent / 'artifact_recovery' / _digest({'source_version': source, 'request': request_id})[:24]
        audit.mkdir(parents=True, exist_ok=False)
        backup = audit / 'original_run_master.json'
        with backup.open('xb') as stream:
            stream.write(original)
        validation_backup = audit / 'original_validation_revision.json'
        with validation_backup.open('xb') as stream:
            stream.write(revision_path.read_bytes())
        if _artifact_version(validation_backup) != revision_version:
            raise HandoffError('SOURCE_RECOVERY_VALIDATION_EVIDENCE_CHANGED_DURING_BACKUP')
        attempt = {'recorded_at': utc_now(), 'status': 'prepared', 'reference': reference,
                   'source': source, 'preserved_original': _snapshot(backup, 'original_run_master_bytes'),
                   'original_wrapper_proof': {'path': str(proof_file), **proof_version},
                   'original_validation': {'path': str(revision_path), **revision_version},
                   'preserved_validation': _snapshot(validation_backup, 'original_validation_revision_bytes'),
                   'failed_validator': deepcopy(result), 'failed_validator_binding': execution['validate_step4_binding'],
                   'failed_pending_invocation': deepcopy(execution['pending_invocation']),
                   'failed_intent_started_at': execution['started_at'],
                   'recovery_tool': _snapshot(Path(__file__), 'source_version_recovery'),
                   'source_version_tool': _snapshot(Path(__file__).with_name('source_version.py'), 'source_version_verifier'),
                   'computation_reexecuted': False, 'native_validation_required': True}
        execution.setdefault('source_version_recovery_history', []).append(attempt)
        self._save()
        write_json_atomic(run_path, corrected)
        expected = {**versions, str(run_path): _artifact_version(run_path)}
        issues = self._changed_artifacts({**checks, str(run_path): expected[str(run_path)]})
        if issues or self._capture_artifacts(execution['artifact_contract']) != expected:
            raise HandoffError('SOURCE_RECOVERY_CONCURRENT_CHANGE: inspect prepared repair')
        attempt.update(status='applied', corrected_run_master=_snapshot(run_path, 'source_version_corrected_run_master'))
        del execution['validate_step4']
        del execution['validate_step4_binding']
        execution.update(status='computed', artifacts=expected)
        self._save()
        return self.status()

    def _apply_reference_repair(self, entry: dict, step: str, repair: dict, versions: dict) -> dict:
        """Preserve original bytes plus a prepared audit record before metadata changes.

        An interrupted repair stays blocked and visible; it cannot retry a writer.
        Single journal ownership is required, as for all other handoff operations.
        """
        path = Path(repair['path'])
        checks = {**versions, repair['request_file']: repair['request_version']}
        issues = self._changed_artifacts(checks)
        if issues or path.read_bytes() != repair['original_bytes']:
            raise HandoffError('REFERENCE_REPAIR_INPUT_CHANGED:' + '; '.join(issues))
        repair_id = _digest({'request': entry['request_id'], 'step': step,
                             'repair': repair['request_version']})[:24]
        audit_dir = self.path.parent / 'artifact_recovery' / repair_id
        audit_dir.mkdir(parents=True, exist_ok=False)
        backup = audit_dir / 'original_payload.json'
        with backup.open('xb') as stream:
            stream.write(repair['original_bytes'])
        stat = repair['original_stat']
        receipt = {
            'recorded_at': utc_now(), 'status': 'prepared',
            'request': {'path': repair['request_file'], **repair['request_version']},
            'original_payload': {'path': str(path), **repair['original_version'],
                                 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns},
            'preserved_original': _snapshot(backup, 'original_payload_bytes'),
            'reference_tool': _snapshot(Path(__file__).with_name('result_artifacts.py'), 'result_reference_repair'),
        }
        execution = entry['execution'][step]
        execution.setdefault('artifact_repair_attempts', []).append(receipt)
        self._save()
        write_json_atomic(path, repair['corrected'])
        expected = {**versions, str(path): _artifact_version(path)}
        actual = self._capture_artifacts(execution['artifact_contract'])
        issues = self._changed_artifacts(expected)
        if actual != expected or issues:
            raise HandoffError('REFERENCE_REPAIR_CONCURRENT_CHANGE: preserve backup and inspect prepared repair')
        receipt.update(status='applied', corrected_payload=_snapshot(path, 'reference_corrected_payload'))
        return deepcopy(receipt)
