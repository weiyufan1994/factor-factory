"""Read-only, non-authoritative code-review completion check before local-IS Step4.

The researcher writes ``objects/research_journal/code_review__<report_id>.json``:

    {
      "report_id": "R1", "author_id": "implementer", "reviewer_id": "researcher",
      "reviewed_at": "2026-09-19T09:00:00Z", "decision": "proceed",
      "summary": "Explain what was actually reviewed and the conclusion.",
      "findings": [{"summary": "Describe an addressed issue.", "status": "resolved"}],
      "reviewed_files": [
        {"role": "spec", "path": "objects/spec.json", "sha256": "<64 hex>"},
        {"role": "implementation", "path": "generated_code/R1.py", "sha256": "<64 hex>"},
        {"role": "helper", "base": "repo", "path": "factor_factory/helper.py", "sha256": "<64 hex>"}
      ],
      "post_review_tests": {
        "status": "PASS", "started_at": "2026-09-19T09:01:00Z",
        "completed_at": "2026-09-19T09:02:00Z",
        "evidence": [{"path": "logs/R1-acceptance.log", "sha256": "<64 hex>"}],
        "tested_files": ["<same file objects as reviewed_files, not this string>"]
      }
    }

There must be exactly one spec and one implementation, plus every helper the
reviewer explicitly reviewed. Findings may be [] when summary explains the
review; nonempty findings need a summary and status ``resolved`` or ``closed``.
All dates require a timezone and must not be future dates. Tests must START
strictly after review and finish no earlier than their start. Test evidence is
one or more existing nonempty, SHA256-bound log/result files; snapshots match the
entire reviewed file set, including hashes. Changing any bound file requires
another real review and fresh post-review tests, not an edited declaration.

Handoff/spec CLI paths, spec record paths, helper paths, and evidence paths are
workspace-relative unless absolute. Only helpers may use ``base: "repo"`` with
an explicit repo_root. Implementation selection is handoff.factor_impl_ref,
then factor_impl_stub_ref, then implementation_path (first truthy value, as in
Step4); ``generated_code/`` paths are workspace-relative, other relative paths
are relative to workspace.parent. As in Step4, a missing/placeholder handoff
reference falls back to spec.canonical_spec.implementation_path, then
spec.implementation_path. A selected missing file never falls through to a
different file. Malformed path types BLOCK instead of being coerced to text.

SHA256 is only ordinary version detection, not signing or authority. This
program checks declarations and current bytes, NOT semantic independence,
review quality, helper-list completeness, or whether tests genuinely ran.
Those remain the responsible agents' work. It does not execute/import factor
code, run tests, read market data, create reviews, or authorize OOS/promotion.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_PLACEHOLDERS = {"", "TODO", "TBD", "PLACEHOLDER", "placeholder", "todo", "tbd"}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _review_text(value: Any) -> bool:
    return _text(value) and value.strip().lower() not in {"todo", "tbd", "placeholder"}


def _resolve(raw: Any, base: Path) -> Path:
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        raise ValueError("expected a nonempty path")
    path = Path(raw)
    return (path if path.is_absolute() else base / path).resolve()


def _load(path: Path, label: str, reasons: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        reasons.append(f"{label}_UNREADABLE:{path}:{type(exc).__name__}")
        return {}
    if not isinstance(value, dict):
        reasons.append(f"{label}_INVALID:expected JSON object")
        return {}
    return value


def _timestamp(value: Any, label: str, now: datetime, reasons: list[str]) -> datetime | None:
    try:
        if not _text(value):
            raise ValueError("expected timestamp string")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp requires timezone")
        parsed = parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        reasons.append(f"{label}_INVALID:expected timezone-aware ISO8601 timestamp")
        return None
    if parsed > now:
        reasons.append(f"{label}_FUTURE")
    return parsed


def _file_snapshots(
    values: Any,
    *,
    label: str,
    workspace: Path,
    repo: Path | None,
    reasons: list[str],
    check_current: bool,
) -> dict[tuple[str, str], str]:
    snapshots: dict[tuple[str, str], str] = {}
    if not isinstance(values, list) or not values:
        reasons.append(f"{label}_INVALID:expected nonempty file list")
        return snapshots
    seen_paths: set[str] = set()
    for index, item in enumerate(values):
        context = f"{label}[{index}]"
        if not isinstance(item, dict):
            reasons.append(f"{context}_INVALID:expected file object")
            continue
        role, raw, digest = item.get("role"), item.get("path"), item.get("sha256")
        if not isinstance(role, str) or role not in {"spec", "implementation", "helper"}:
            reasons.append(f"{context}_INVALID:unknown role")
            continue
        if not _text(raw) or not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            reasons.append(f"{context}_INVALID:nonempty path and SHA256 required")
            continue
        base = workspace
        path_base = item.get("base", "workspace")
        if path_base == "repo" and role == "helper" and repo is not None:
            base = repo
        elif path_base != "workspace":
            reasons.append(f"{context}_INVALID:base=repo needs helper role and repo_root")
            continue
        if role == "implementation":
            base = workspace if raw.startswith("generated_code/") else workspace.parent
        try:
            path = _resolve(raw, base)
            resolved = str(path)
            if resolved in seen_paths:
                reasons.append(f"{context}_DUPLICATE_PATH:{path}")
            seen_paths.add(resolved)
            snapshots[(role, resolved)] = digest.lower()
            if check_current:
                if not path.is_file():
                    reasons.append(f"{context}_FILE_MISSING:{path}")
                elif hashlib.sha256(path.read_bytes()).hexdigest() != digest.lower():
                    reasons.append(f"{context}_FILE_CHANGED:{path}:real re-review and new tests required")
        except (OSError, ValueError, RuntimeError) as exc:
            reasons.append(f"{context}_UNREADABLE:{type(exc).__name__}")
    return snapshots


def resolve_review_inputs(*, workspace_root: str | Path, handoff: str | Path,
                          spec: str | Path) -> dict[str, Any]:
    """Select the same actual files as Step4; never import or execute them."""
    workspace = _resolve(workspace_root, Path.cwd())
    handoff_path, spec_path = _resolve(handoff, workspace), _resolve(spec, workspace)
    reasons: list[str] = []
    result: dict[str, Any] = {"spec_path": str(spec_path), "handoff_path": str(handoff_path),
                              "reasons": reasons}
    handoff_record = _load(handoff_path, "HANDOFF", reasons)
    spec_record = _load(spec_path, "SPEC", reasons)
    implementation: Path | None = None
    # Do not fall through to a lower-priority file when the selected file
    # is missing, malformed, or unreviewed: Step4 would select this value.
    selected = next(
        ((key, handoff_record[key]) for key in (
            "factor_impl_ref", "factor_impl_stub_ref", "implementation_path"
        ) if handoff_record.get(key)),
        (None, None),
    )
    key, raw = selected
    for field in ("factor_impl_ref", "factor_impl_stub_ref", "implementation_path"):
        value = handoff_record.get(field)
        if value is not None and not isinstance(value, str):
            reasons.append(f"IMPLEMENTATION_REFERENCE_INVALID:handoff.{field}:expected string")
    if not raw or (isinstance(raw, str) and raw.strip() in _PLACEHOLDERS):
        canonical = spec_record.get("canonical_spec", {})
        if not isinstance(canonical, dict):
            reasons.append("IMPLEMENTATION_REFERENCE_INVALID:canonical_spec must be an object")
            canonical = {}
        raw = canonical.get("implementation_path") or spec_record.get("implementation_path")
        key = ("spec.canonical_spec.implementation_path" if canonical.get("implementation_path")
               else "spec.implementation_path")
    if not _text(raw) or raw.strip() in _PLACEHOLDERS:
        reasons.append("IMPLEMENTATION_REFERENCE_INVALID:no actual implementation in handoff/spec")
    else:
        base = workspace if raw.startswith("generated_code/") else workspace.parent
        implementation = _resolve(raw, base)
        result.update(implementation_path=str(implementation), implementation_source=key)
    return result


def validate_code_review(
    *,
    workspace_root: str | Path,
    report_id: str,
    handoff: str | Path,
    spec: str | Path,
    repo_root: str | Path | None = None,
    review_record: dict[str, Any] | None = None,
    require_post_review_tests: bool = True,
) -> dict[str, Any]:
    """Check declarations without writing or executing. Review-only intake is not release.

    The wrapper/CLI always require tests. The journal handoff uses an explicit
    supplied review and review-only validation before the author runs new tests.
    """
    reasons: list[str] = []
    result: dict[str, Any] = {"status": "BLOCK", "reasons": reasons, "report_id": report_id}
    now = datetime.now(timezone.utc)
    try:
        if (
            not _text(report_id)
            or report_id != report_id.strip()
            or report_id in {".", ".."}
            or any(char in report_id for char in ("/", "\\", "\x00"))
        ):
            reasons.append("REPORT_ID_INVALID")
            return result
        workspace = _resolve(workspace_root, Path.cwd())
        repo = _resolve(repo_root, Path.cwd()) if repo_root is not None else None
        handoff_path = _resolve(handoff, workspace)
        spec_path = _resolve(spec, workspace)
        review_path = workspace / "objects" / "research_journal" / f"code_review__{report_id}.json"
        result.update(review_path=str(review_path), spec_path=str(spec_path))
        record = review_record if review_record is not None else _load(review_path, "CODE_REVIEW_RECORD", reasons)
        inputs = resolve_review_inputs(workspace_root=workspace, handoff=handoff_path, spec=spec_path)
        reasons.extend(inputs.pop("reasons"))
        result.update(inputs)
        implementation = Path(inputs["implementation_path"]) if inputs.get("implementation_path") else None
        if record.get("report_id") != report_id:
            reasons.append("CODE_REVIEW_REPORT_ID_MISMATCH")
        author, reviewer = record.get("author_id"), record.get("reviewer_id")
        if not _text(author) or not _text(reviewer):
            reasons.append("CODE_REVIEW_IDENTITIES_INVALID:nonempty author_id and reviewer_id required")
        elif author.strip().casefold() == reviewer.strip().casefold():
            reasons.append("CODE_REVIEW_SELF_REVIEW:author_id and reviewer_id must differ")
        if record.get("decision") != "proceed":
            reasons.append("CODE_REVIEW_DECISION_NOT_PROCEED")
        if not _review_text(record.get("summary")):
            reasons.append("CODE_REVIEW_SUMMARY_MISSING")
        findings = record.get("findings")
        if not isinstance(findings, list):
            reasons.append("CODE_REVIEW_FINDINGS_INVALID:expected list")
        else:
            for index, finding in enumerate(findings):
                if not isinstance(finding, dict) or not _review_text(finding.get("summary")):
                    reasons.append(f"CODE_REVIEW_FINDING_INVALID:{index}")
                elif finding.get("status") not in ("closed", "resolved"):
                    reasons.append(f"CODE_REVIEW_FINDING_OPEN_OR_INVALID:{index}")
        reviewed_at = _timestamp(record.get("reviewed_at"), "CODE_REVIEW_TIME", now, reasons)
        reviewed = _file_snapshots(
            record.get("reviewed_files"), label="REVIEWED_FILES", workspace=workspace,
            repo=repo, reasons=reasons, check_current=True,
        )
        for role, expected in (("spec", spec_path), ("implementation", implementation)):
            paths = [path for item_role, path in reviewed if item_role == role]
            if expected is None or paths != [str(expected)]:
                reasons.append(f"CODE_REVIEW_{role.upper()}_MISMATCH:must bind exactly the actual {role}")
        if require_post_review_tests:
            tests = record.get("post_review_tests")
            if not isinstance(tests, dict):
                reasons.append("POST_REVIEW_TESTS_INVALID:expected object")
            else:
                if tests.get("status") != "PASS":
                    reasons.append("POST_REVIEW_TESTS_NOT_PASS")
                started = _timestamp(tests.get("started_at"), "POST_REVIEW_TEST_START", now, reasons)
                completed = _timestamp(tests.get("completed_at"), "POST_REVIEW_TEST_COMPLETION", now, reasons)
                if reviewed_at is not None and started is not None and started <= reviewed_at:
                    reasons.append("POST_REVIEW_TESTS_NOT_AFTER_REVIEW")
                if started is not None and completed is not None and completed < started:
                    reasons.append("POST_REVIEW_TESTS_INVALID_ORDER")
                tested = _file_snapshots(
                    tests.get("tested_files"), label="TESTED_FILES", workspace=workspace,
                    repo=repo, reasons=reasons, check_current=False,
                )
                if tested != reviewed:
                    reasons.append("POST_REVIEW_TEST_FILES_MISMATCH:tests must bind the entire reviewed version")
                evidence = tests.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    reasons.append("POST_REVIEW_TEST_EVIDENCE_MISSING")
                else:
                    for index, item in enumerate(evidence):
                        if not isinstance(item, dict) or not _text(item.get("path")):
                            reasons.append(f"POST_REVIEW_TEST_EVIDENCE_INVALID:{index}")
                            continue
                        digest = item.get("sha256")
                        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                            reasons.append(f"POST_REVIEW_TEST_EVIDENCE_INVALID:{index}")
                            continue
                        path = _resolve(item["path"], workspace)
                        if not path.is_file() or path.stat().st_size == 0:
                            reasons.append(f"POST_REVIEW_TEST_EVIDENCE_MISSING_OR_EMPTY:{path}")
                        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest.lower():
                            reasons.append(f"POST_REVIEW_TEST_EVIDENCE_CHANGED:{path}")
        else:
            result["check_scope"] = "review_only_not_release"
        if not reasons:
            result["status"] = "PASS"
    except (OSError, ValueError, TypeError, RuntimeError, OverflowError) as exc:
        # Malformed user-authored records and ordinary filesystem failures
        # must never become permission to enter Step4.
        reasons.append(f"CODE_REVIEW_INPUT_INVALID:{type(exc).__name__}:{exc}")
    return result
