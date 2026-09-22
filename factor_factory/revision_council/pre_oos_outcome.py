from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from factor_factory.evo_v2 import (
    canonical_json_bytes,
    sha256_file,
    stable_json_hash,
)
from factor_factory.research_conjecture import (
    research_protocol_paths,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.revision_council.evo_v2 import (
    validate_revision_council_evo_v2,
)
from factor_factory.revision_council.production import (
    CouncilEvoProductionError,
    PURGED_IS_EVIDENCE_VIEW,
    load_formal_evo_packet_context,
    result_evo_outcome_summary,
)


PRE_OOS_ROOT_SYNTHESIS_VERSION = (
    "factorforge_pre_oos_council_root_synthesis_v1"
)
PRE_OOS_OUTCOME_VERIFIER_VERSION = (
    "factorforge_pre_oos_council_outcome_verifier_v1"
)
PRE_OOS_OUTCOME_VERIFIER_ID = (
    "factorforge_pre_oos_council_outcome_verifier_v1"
)

BLOCK_PRE_OOS_OUTCOME = "BLOCK_FACTORFORGE_PRE_OOS_COUNCIL_OUTCOME_INVALID"
BLOCK_PRE_OOS_EXTERNAL_VALIDATION = (
    "BLOCK_FACTORFORGE_PRE_OOS_COUNCIL_EXISTING_VALIDATOR_FAILED"
)
BLOCK_PRE_OOS_MATERIALIZATION_CONFLICT = (
    "BLOCK_FACTORFORGE_PRE_OOS_COUNCIL_OUTCOME_MATERIALIZATION_CONFLICT"
)

_DISPATCH_VERSION = "factorforge_agentic_council_dispatch_manifest_v1"
_COLLECTION_VERSION = "factorforge_agentic_council_result_collection_v1"
_SUMMARY_VERSION = "factorforge_revision_council_summary_v1"
_APPENDIX_VERSION = "factorforge_revision_council_derivation_appendix_v1"

_SYNTHESIS_FIELDS = frozenset(
    {
        "contract_version",
        "report_id",
        "evidence_view",
        "authority",
        "evidence_bindings",
        "route_result_analysis",
        "dissent_resolution",
        "selection",
        "selected_outcome",
        "content_sha256",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {
        "status",
        "host_transition_authority",
        "human_approval_authority",
        "canonical_write_allowed",
        "execution_allowed",
        "factor_verdict",
        "oos_accessed",
        "child_execution_allowed",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "feedback_ledger_ref",
        "lifecycle_ref",
        "dispatch_manifest_ref",
        "result_collection_ref",
        "council_summary_ref",
        "derivation_appendix_json_ref",
        "derivation_appendix_markdown_ref",
        "raw_result_refs",
        "selected_proposal_ref",
    }
)
_ANALYSIS_FIELDS = frozenset(
    {
        "task_id",
        "route_id",
        "route_family",
        "agent_identifier",
        "result_ref",
        "outcome",
        "disposition",
        "exact_gap_or_closed_obligation",
        "incompatible_assumptions",
        "discriminating_evidence",
        "open_proof_obligations",
        "dissent",
    }
)
_DISSENT_FIELDS = frozenset({"status", "position", "resolution"})
_DISSENT_RESOLUTION_FIELDS = frozenset(
    {
        "policy",
        "all_result_positions_covered",
        "resolution_summary",
        "unresolved_task_ids",
    }
)
_SELECTION_FIELDS = frozenset(
    {
        "policy",
        "selected_task_id",
        "selected_result_sha256",
        "rationale",
        "decisive_evidence",
        "majority_vote_used",
        "score_or_rank_used",
        "result_aggregation_used",
    }
)
_SELECTED_OUTCOME_FIELDS = frozenset(
    {
        "outcome",
        "task_id",
        "route_id",
        "result_sha256",
        "law_id",
        "law_sha256",
        "delta_id",
        "mechanism_delta_sha256",
        "economic_backprojection_sha256",
        "no_derived_law_sha256",
    }
)
_REPORT_FIELDS = frozenset(
    {
        "contract_version",
        "verifier_id",
        "verifier_source_sha256",
        "verifier_status",
        "report_id",
        "dataset_snapshot_hash",
        "window_hash",
        "evidence_view",
        "validated_synthesis_ref",
        "evidence_bindings",
        "selected_outcome",
        "authorized_host_transition_state",
        "authority",
        "validation_counts",
        "binding_digest",
        "content_sha256",
    }
)
_REPORT_AUTHORITY = {
    "host_verification_evidence_only": True,
    "host_transition_performed": False,
    "human_approval_granted": False,
    "canonical_write_allowed": False,
    "factor_verdict": "NOT_ISSUED",
    "child_execution_allowed": False,
    "oos_accessed": False,
}
_SYNTHESIS_AUTHORITY = {
    "status": "AGENT_AUTHORED_REVIEW_ONLY",
    "host_transition_authority": False,
    "human_approval_authority": False,
    "canonical_write_allowed": False,
    "execution_allowed": False,
    "factor_verdict": "NOT_ISSUED",
    "oos_accessed": False,
    "child_execution_allowed": False,
}
_REF_FIELDS = frozenset({"path", "sha256"})
_TASK_REF_FIELDS = frozenset({"task_id", "path", "sha256"})
_HEX = frozenset("0123456789abcdef")
_FORBIDDEN_SELECTION_TEXT = re.compile(
    r"(?i)(?:\bmajority\b|\bvote(?:s|d|r|rs|ing)?\b|\bconsensus\b|"
    r"\bunanimous(?:ly)?\b|\bselection[ _-]?score\b|\branking[ _-]?score\b|"
    r"\bperformance[ _-]?score\b|\bhighest[ _-]?score\b|\bscore(?:s|d|ing)?\b|"
    r"\bbest[ _-]?perform)"
)


class PreOosCouncilOutcomeError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = _dedupe(reasons)
        super().__init__(";".join(self.reasons))


def _dedupe(reasons: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))


def _token(suffix: str) -> str:
    return f"{BLOCK_PRE_OOS_OUTCOME}:{suffix}"


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty_text(item) for item in value)
        and len(value) == len(set(value))
    )


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PreOosCouncilOutcomeError([_token(f"file_invalid:{path.name}")])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreOosCouncilOutcomeError(
            [_token(f"json_unreadable:{path.name}:{type(exc).__name__}")]
        ) from exc
    if not isinstance(payload, dict):
        raise PreOosCouncilOutcomeError([_token(f"json_object_required:{path.name}")])
    return payload


def _relative(root: Path, path: Path) -> str:
    resolved = path.resolve(strict=True)
    return resolved.relative_to(root).as_posix()


def _file_ref(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    if path.is_symlink() or not resolved.is_file():
        raise PreOosCouncilOutcomeError([_token(f"file_invalid:{path.name}")])
    return {"path": _relative(root, resolved), "sha256": sha256_file(resolved)}


def _task_ref(root: Path, task_id: str, path: Path) -> dict[str, str]:
    return {"task_id": task_id, **_file_ref(root, path)}


def _resolve_ref(
    root: Path,
    value: Any,
    *,
    expected_fields: frozenset[str] = _REF_FIELDS,
) -> Path | None:
    if not isinstance(value, dict) or set(value) != expected_fields:
        return None
    raw_path = value.get("path")
    digest = value.get("sha256")
    if not isinstance(raw_path, str) or not _is_sha256(digest) or "\\" in raw_path:
        return None
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw_path:
        return None
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if (
        not candidate.is_file()
        or candidate.is_symlink()
        or sha256_file(candidate) != digest
    ):
        return None
    return candidate


def _council_dir(root: Path, report_id: str) -> Path:
    return (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / report_id
    )


def pre_oos_root_synthesis_path(root: Path, report_id: str) -> Path:
    return _council_dir(root, report_id) / (
        f"pre_oos_council_root_synthesis__{report_id}.json"
    )


def pre_oos_outcome_verifier_path(root: Path, report_id: str) -> Path:
    return _council_dir(root, report_id) / (
        f"pre_oos_council_outcome_verifier__{report_id}.json"
    )


def verifier_source_sha256() -> str:
    return sha256_file(Path(__file__).resolve(strict=True))


def _existing_validator_command(
    root: Path,
    report_id: str,
    script_name: str,
    extra_args: Sequence[str] = (),
) -> tuple[bool, str]:
    repo_root = Path(__file__).resolve().parents[2]
    script = (
        repo_root
        / "skills"
        / "factor-forge-step6"
        / "scripts"
        / script_name
    )
    environment = os.environ.copy()
    environment["FACTORFORGE_ROOT"] = str(root)
    completed = subprocess.run(
        [sys.executable, str(script), "--report-id", report_id, *extra_args],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
    )
    diagnostic = (completed.stdout + "\n" + completed.stderr).strip()[-2000:]
    return completed.returncode == 0, diagnostic


def _run_existing_validators(
    root: Path,
    report_id: str,
    result_paths: Sequence[Path],
) -> list[str]:
    reasons: list[str] = []
    for script in (
        "validate_agentic_council_dispatch.py",
        "validate_agentic_council_collection.py",
    ):
        ok, diagnostic = _existing_validator_command(root, report_id, script)
        if not ok:
            reasons.append(
                f"{BLOCK_PRE_OOS_EXTERNAL_VALIDATION}:{script}:{diagnostic}"
            )
    for path in result_paths:
        before = sha256_file(path)
        ok, diagnostic = _existing_validator_command(
            root,
            report_id,
            "validate_agentic_council_result.py",
            ("--result-path", str(path)),
        )
        after = sha256_file(path) if path.is_file() and not path.is_symlink() else None
        if before != after:
            reasons.append(
                f"{BLOCK_PRE_OOS_EXTERNAL_VALIDATION}:result_changed_during_validation:{path.name}"
            )
        if not ok:
            reasons.append(
                f"{BLOCK_PRE_OOS_EXTERNAL_VALIDATION}:{path.name}:{diagnostic}"
            )
    return reasons


def _summary_expected_law_index(
    result_records: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in result_records:
        outcome = record["outcome"]
        if outcome.get("outcome") != "MINIMAL_MECHANISM_DELTA":
            continue
        result = record["payload"]
        laws = result.get("candidate_revision_laws")
        if not isinstance(laws, list) or len(laws) != 1 or not isinstance(laws[0], dict):
            continue
        rows.append(
            {
                "law_id": laws[0].get("law_id"),
                "route_id": record["task"].get("route_id"),
                "source_result_sha256": record["ref"]["sha256"],
                "law_hash": outcome.get("law_sha256"),
                "evo_v2_task_identity_sha256": outcome.get(
                    "evo_v2_task_identity_sha256"
                ),
                "mechanism_delta_sha256": outcome.get(
                    "mechanism_delta_sha256"
                ),
                "economic_backprojection_sha256": outcome.get(
                    "economic_backprojection_sha256"
                ),
                "delta_id": outcome.get("delta_id"),
            }
        )
    return rows


def _expected_selected_outcome(record: Mapping[str, Any]) -> dict[str, Any]:
    result = record["payload"]
    task = record["task"]
    outcome = record["outcome"]
    laws = result.get("candidate_revision_laws")
    law = laws[0] if isinstance(laws, list) and len(laws) == 1 else None
    return {
        "outcome": outcome.get("outcome"),
        "task_id": task.get("task_id"),
        "route_id": task.get("route_id"),
        "result_sha256": record["ref"]["sha256"],
        "law_id": law.get("law_id") if isinstance(law, Mapping) else None,
        "law_sha256": outcome.get("law_sha256"),
        "delta_id": outcome.get("delta_id"),
        "mechanism_delta_sha256": outcome.get("mechanism_delta_sha256"),
        "economic_backprojection_sha256": outcome.get(
            "economic_backprojection_sha256"
        ),
        "no_derived_law_sha256": outcome.get("no_derived_law_sha256"),
    }


def _selection_text_reasons(value: Any, path: str = "selection") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            reasons.extend(_selection_text_reasons(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reasons.extend(_selection_text_reasons(item, f"{path}[{index}]"))
    elif isinstance(value, str) and _FORBIDDEN_SELECTION_TEXT.search(value):
        reasons.append(_token(f"forbidden_selection_basis:{path}"))
    return reasons


def _aggregate_evidence_hash(
    lifecycle: Mapping[str, Any],
    field: str,
    reasons: list[str],
) -> str | None:
    events = lifecycle.get("events")
    last = events[-1] if isinstance(events, list) and events else None
    refs = last.get("evidence_refs") if isinstance(last, Mapping) else None
    values = sorted(
        {
            str(reference.get(field))
            for reference in (refs or [])
            if isinstance(reference, Mapping) and _is_sha256(reference.get(field))
        }
    )
    if not values:
        reasons.append(_token(f"lifecycle_evidence_{field}_missing"))
        return None
    if len(values) == 1:
        return values[0]
    return stable_json_hash({f"component_{field}s": values})


def _validate_summary(
    summary: Mapping[str, Any],
    *,
    report_id: str,
    formal_context: Mapping[str, Any],
    result_records: Sequence[dict[str, Any]],
    root: Path,
) -> list[str]:
    reasons: list[str] = []
    if (
        summary.get("contract_version") != _SUMMARY_VERSION
        or summary.get("report_id") != report_id
        or summary.get("evo_v2") != formal_context
        or summary.get("selection_source") != "agentic_results"
        or summary.get("deterministic_fallback_used") is not False
    ):
        reasons.append(_token("council_summary_header_invalid"))
    if summary.get("blocked_agent_results") != []:
        reasons.append(_token("council_summary_blocked_results_present"))
    valid = summary.get("valid_agent_results")
    if not isinstance(valid, list) or len(valid) != len(result_records):
        reasons.append(_token("council_summary_valid_result_count_mismatch"))
        valid = []
    valid_by_task = {
        row.get("task_id"): row for row in valid if isinstance(row, dict)
    }
    routes = summary.get("research_route_summary")
    if not isinstance(routes, list) or len(routes) != len(result_records):
        reasons.append(_token("council_summary_route_count_mismatch"))
        routes = []
    route_by_task = {
        row.get("task_id"): row for row in routes if isinstance(row, dict)
    }
    for record in result_records:
        task = record["task"]
        task_id = task.get("task_id")
        row = valid_by_task.get(task_id)
        route = route_by_task.get(task_id)
        expected_path = record["path"].resolve(strict=True)
        if not isinstance(row, dict):
            reasons.append(_token(f"council_summary_result_missing:{task_id}"))
        else:
            raw_path = row.get("path")
            candidate = Path(raw_path) if isinstance(raw_path, str) else Path()
            candidate = candidate if candidate.is_absolute() else root / candidate
            if (
                candidate.resolve(strict=False) != expected_path
                or row.get("result_sha256") != record["ref"]["sha256"]
                or row.get("agent_role") != task.get("agent_role")
                or row.get("route_id") != task.get("route_id")
                or row.get("route_family") != task.get("route_family")
                or row.get("evo_v2_outcome") != record["outcome"]
            ):
                reasons.append(_token(f"council_summary_result_mismatch:{task_id}"))
        if not isinstance(route, dict):
            reasons.append(_token(f"council_summary_route_missing:{task_id}"))
        else:
            raw_path = route.get("source_result_path") or route.get("source_path")
            candidate = Path(raw_path) if isinstance(raw_path, str) else Path()
            candidate = candidate if candidate.is_absolute() else root / candidate
            if (
                candidate.resolve(strict=False) != expected_path
                or route.get("source_result_sha256") != record["ref"]["sha256"]
                or route.get("route_id") != task.get("route_id")
                or route.get("route_family") != task.get("route_family")
            ):
                reasons.append(_token(f"council_summary_route_mismatch:{task_id}"))
    if summary.get("candidate_law_index") != _summary_expected_law_index(
        result_records
    ):
        reasons.append(_token("council_summary_law_index_mismatch"))
    contract = summary.get("root_synthesis_contract")
    route_families = {
        str(record["task"].get("route_family")) for record in result_records
    }
    if not isinstance(contract, dict) or contract != {
        "required": True,
        "majority_vote_forbidden": True,
        "must_compare_every_route": True,
        "must_resolve_or_preserve_dissent": True,
        "must_list_open_proof_obligations": True,
        "route_family_count": len(route_families),
    }:
        reasons.append(_token("council_summary_root_synthesis_contract_invalid"))
    return reasons


def _validate_appendix(
    appendix: Mapping[str, Any],
    *,
    report_id: str,
    summary_path: Path,
    result_records: Sequence[dict[str, Any]],
    root: Path,
) -> list[str]:
    reasons: list[str] = []
    if (
        appendix.get("appendix_version") != _APPENDIX_VERSION
        or appendix.get("report_id") != report_id
        or appendix.get("status") != "public_derivation_appendix"
        or appendix.get("selection_source") != "agentic_results"
        or appendix.get("canonical_write_permission") is not False
        or appendix.get("execution_allowed_by_default") is not False
        or appendix.get("human_approval_required_before_step3b") is not True
        or appendix.get("missing_source_paths") != []
    ):
        reasons.append(_token("derivation_appendix_header_invalid"))
    raw_summary = appendix.get("source_summary_path")
    candidate = Path(raw_summary) if isinstance(raw_summary, str) else Path()
    candidate = candidate if candidate.is_absolute() else root / candidate
    if candidate.resolve(strict=False) != summary_path.resolve(strict=True):
        reasons.append(_token("derivation_appendix_summary_binding_mismatch"))
    expected_paths = [record["path"].resolve(strict=True) for record in result_records]
    source_paths = appendix.get("source_paths")
    observed_paths: list[Path] = []
    if isinstance(source_paths, list):
        for raw in source_paths:
            path = Path(raw) if isinstance(raw, str) else Path()
            observed_paths.append(
                (path if path.is_absolute() else root / path).resolve(strict=False)
            )
    if observed_paths != expected_paths:
        reasons.append(_token("derivation_appendix_result_set_mismatch"))
    sections = appendix.get("agent_derivations")
    if not isinstance(sections, list) or len(sections) != len(result_records):
        reasons.append(_token("derivation_appendix_section_count_mismatch"))
        sections = []
    section_by_task = {
        row.get("task_id"): row for row in sections if isinstance(row, dict)
    }
    for record in result_records:
        task = record["task"]
        result = record["payload"]
        task_id = task.get("task_id")
        row = section_by_task.get(task_id)
        if not isinstance(row, dict):
            reasons.append(_token(f"derivation_appendix_section_missing:{task_id}"))
            continue
        raw_path = row.get("source_path")
        path = Path(raw_path) if isinstance(raw_path, str) else Path()
        path = path if path.is_absolute() else root / path
        if (
            path.resolve(strict=False) != record["path"].resolve(strict=True)
            or row.get("agent_role") != task.get("agent_role")
            or row.get("producer") != result.get("producer")
            or row.get("candidate_revision_laws")
            != result.get("candidate_revision_laws")
        ):
            reasons.append(_token(f"derivation_appendix_section_mismatch:{task_id}"))
    return reasons


def validate_pre_oos_root_synthesis(
    synthesis: Any,
    *,
    workspace_root: Path | str,
    report_id: str,
    synthesis_path: Path | str | None = None,
    validator_runner: Callable[[Path, str, Sequence[Path]], list[str]] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one agent-authored pre-OOS root selection.

    The return value is ``(verifier_report, reasons)``.  No lifecycle, EVO
    artifact, human approval, child, or canonical knowledge state is written.
    ``validator_runner`` exists for bounded unit fixtures only; production CLI
    callers never expose it and always replay the existing dispatch/result
    validators.
    """

    reasons: list[str] = []
    try:
        root = Path(workspace_root).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None, [_token("workspace_root_invalid")]
    if not root.is_dir():
        return None, [_token("workspace_root_invalid")]
    if not isinstance(synthesis, dict) or set(synthesis) != _SYNTHESIS_FIELDS:
        return None, [_token("synthesis_closed_shape_invalid")]
    if (
        synthesis.get("contract_version") != PRE_OOS_ROOT_SYNTHESIS_VERSION
        or synthesis.get("report_id") != report_id
        or synthesis.get("evidence_view") != PURGED_IS_EVIDENCE_VIEW
        or synthesis.get("authority") != _SYNTHESIS_AUTHORITY
    ):
        reasons.append(_token("synthesis_header_or_authority_invalid"))
    unsigned = dict(synthesis)
    digest = unsigned.pop("content_sha256", None)
    if digest != stable_json_hash(unsigned):
        reasons.append(_token("synthesis_content_sha256_mismatch"))

    canonical_synthesis_path = pre_oos_root_synthesis_path(root, report_id)
    selected_synthesis_path = (
        Path(synthesis_path).expanduser().resolve(strict=False)
        if synthesis_path is not None
        else canonical_synthesis_path.resolve(strict=False)
    )
    if selected_synthesis_path != canonical_synthesis_path.resolve(strict=False):
        reasons.append(_token("synthesis_path_not_canonical"))
    if not selected_synthesis_path.is_file() or selected_synthesis_path.is_symlink():
        reasons.append(_token("synthesis_file_missing_or_symlink"))
    else:
        try:
            on_disk = _load_object(selected_synthesis_path)
        except PreOosCouncilOutcomeError as exc:
            reasons.extend(exc.reasons)
        else:
            if on_disk != synthesis:
                reasons.append(_token("synthesis_readback_mismatch"))

    paths = research_protocol_paths(root, report_id)
    lifecycle_path = paths["evo_lifecycle"]
    lifecycle = _load_object(lifecycle_path)
    lifecycle_reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    reasons.extend(lifecycle_reasons)
    current_state = lifecycle.get("current_state")

    council_dir = _council_dir(root, report_id)
    dispatch_path = council_dir / f"dispatch_manifest__{report_id}.json"
    dispatch_probe = _load_object(dispatch_path)
    bound_context = dispatch_probe.get("evo_v2")
    if not isinstance(bound_context, dict):
        reasons.append(_token("dispatch_evo_context_missing"))
        return None, _dedupe(reasons)
    if current_state == "QUALIFIED_CONTRADICTION":
        try:
            formal_context, feedback = load_formal_evo_packet_context(
                root,
                report_id,
                bound_context=bound_context,
            )
        except CouncilEvoProductionError as exc:
            formal_context, feedback = None, None
            reasons.extend(exc.reasons)
        if formal_context is None or feedback is None:
            reasons.append(_token("formal_evo_context_required"))
            return None, _dedupe(reasons)
    else:
        # Replaying a materialized review after the Host append requires the
        # immutable QUALIFIED lifecycle snapshot carried by the dispatch.  The
        # mutable lifecycle head must be its exact append-only descendant.
        if current_state not in {
            "MINIMAL_MECHANISM_DELTA",
            "NO_DERIVED_LAW",
            "TRANSFER_RECORDED",
            "COLD_START_RECORDED",
        }:
            reasons.append(_token("lifecycle_not_qualified_or_descendant"))
            return None, _dedupe(reasons)
        lifecycle_ref = bound_context.get("lifecycle_ref")
        snapshot_path = _resolve_ref(root, lifecycle_ref)
        if snapshot_path is None:
            reasons.append(_token("qualified_lifecycle_snapshot_invalid"))
            return None, _dedupe(reasons)
        snapshot = _load_object(snapshot_path)
        reasons.extend(
            validate_epistemic_evolution_lifecycle(
                snapshot,
                report_id=report_id,
                workspace_root=root,
                require_signed_host_receipts=True,
            )
        )
        snapshot_events = snapshot.get("events")
        current_events = lifecycle.get("events")
        if (
            snapshot.get("current_state") != "QUALIFIED_CONTRADICTION"
            or not isinstance(snapshot_events, list)
            or not isinstance(current_events, list)
            or current_events[: len(snapshot_events)] != snapshot_events
            or len(current_events) <= len(snapshot_events)
        ):
            reasons.append(_token("qualified_lifecycle_not_append_only_ancestor"))
        try:
            formal_context, feedback = load_formal_evo_packet_context(
                root,
                report_id,
                bound_context=bound_context,
            )
        except CouncilEvoProductionError as exc:
            reasons.extend(exc.reasons)
            formal_context, feedback = None, None
        if formal_context is None or feedback is None:
            return None, _dedupe(reasons)

    collection_path = council_dir / f"agentic_result_collection__{report_id}.json"
    summary_path = council_dir / f"revision_council_summary__{report_id}.json"
    appendix_json_path = council_dir / f"council_derivation_appendix__{report_id}.json"
    appendix_md_path = council_dir / f"council_derivation_appendix__{report_id}.md"
    try:
        dispatch = dispatch_probe
        collection = _load_object(collection_path)
        summary = _load_object(summary_path)
        appendix = _load_object(appendix_json_path)
    except PreOosCouncilOutcomeError as exc:
        reasons.extend(exc.reasons)
        return None, _dedupe(reasons)
    if not appendix_md_path.is_file() or appendix_md_path.is_symlink():
        reasons.append(_token("derivation_appendix_markdown_missing"))
        return None, _dedupe(reasons)

    if (
        dispatch.get("dispatch_manifest_version") != _DISPATCH_VERSION
        or dispatch.get("report_id") != report_id
        or dispatch.get("evo_v2") != formal_context
        or dispatch.get("canonical_write_permission") is not False
        or dispatch.get("execution_allowed_by_default") is not False
        or dispatch.get("human_approval_required") is not True
    ):
        reasons.append(_token("dispatch_manifest_invalid"))
    tasks = dispatch.get("agent_tasks")
    if not isinstance(tasks, list) or not tasks or not all(
        isinstance(task, dict) and task.get("required") is True for task in tasks
    ):
        reasons.append(_token("dispatch_required_tasks_invalid"))
        tasks = []
    task_ids = [task.get("task_id") for task in tasks]
    route_ids = [task.get("route_id") for task in tasks]
    if (
        any(not _nonempty_text(value) for value in [*task_ids, *route_ids])
        or len(task_ids) != len(set(task_ids))
        or len(route_ids) != len(set(route_ids))
        or dispatch.get("agent_task_count") != len(tasks)
    ):
        reasons.append(_token("dispatch_task_or_route_identity_invalid"))

    result_records: list[dict[str, Any]] = []
    expected_result_paths: list[Path] = []
    for index, task in enumerate(tasks):
        task_id = str(task.get("task_id") or "")
        raw_path = task.get("expected_result_path")
        result_path = Path(raw_path) if isinstance(raw_path, str) else Path()
        result_path = result_path if result_path.is_absolute() else root / result_path
        expected_path = (
            council_dir / "agent_results" / f"agent_result__{report_id}__{task_id}.json"
        )
        if result_path.resolve(strict=False) != expected_path.resolve(strict=False):
            reasons.append(_token(f"result_path_not_canonical:{index}"))
            continue
        try:
            payload = _load_object(result_path)
        except PreOosCouncilOutcomeError as exc:
            reasons.extend(exc.reasons)
            continue
        direct_reasons = validate_revision_council_evo_v2(
            payload,
            workspace_root=root,
            required=True,
        )
        reasons.extend(
            f"{_token(f'result_evo_invalid:{task_id}')}:{reason}"
            for reason in direct_reasons
        )
        outcome = result_evo_outcome_summary(payload)
        if not isinstance(outcome, dict) or outcome.get("outcome") not in {
            "MINIMAL_MECHANISM_DELTA",
            "NO_DERIVED_LAW",
        }:
            reasons.append(_token(f"result_outcome_invalid:{task_id}"))
            continue
        reference = _task_ref(root, task_id, result_path)
        result_records.append(
            {
                "task": task,
                "payload": payload,
                "path": result_path,
                "ref": reference,
                "outcome": outcome,
            }
        )
        expected_result_paths.append(result_path)
    actual_result_paths = sorted(
        (council_dir / "agent_results").glob(
            f"agent_result__{report_id}__*.json"
        )
    )
    if {path.resolve(strict=False) for path in actual_result_paths} != {
        path.resolve(strict=False) for path in expected_result_paths
    }:
        reasons.append(_token("unbound_or_missing_raw_result_bytes"))
    if len(result_records) != len(tasks):
        reasons.append(_token("raw_result_set_incomplete"))

    runner = validator_runner or _run_existing_validators
    if len(result_records) == len(tasks):
        reasons.extend(runner(root, report_id, expected_result_paths))

    if (
        collection.get("collection_version") != _COLLECTION_VERSION
        or collection.get("report_id") != report_id
        or collection.get("evo_v2") != formal_context
        or collection.get("status") != "complete"
        or collection.get("ready_for_finalize") is not True
        or collection.get("required_result_count") != len(tasks)
        or collection.get("present_result_count") != len(tasks)
        or collection.get("valid_result_count") != len(tasks)
        or collection.get("invalid_result_count") != 0
        or collection.get("missing_result_count") != 0
        or collection.get("invalid_results") != []
        or collection.get("missing_results") != []
        or collection.get("independence_block_reasons") != []
    ):
        reasons.append(_token("result_collection_invalid"))
    collection_rows = collection.get("valid_results")
    if not isinstance(collection_rows, list) or len(collection_rows) != len(result_records):
        reasons.append(_token("result_collection_rows_invalid"))
        collection_rows = []
    collection_by_task = {
        row.get("task_id"): row for row in collection_rows if isinstance(row, dict)
    }
    for record in result_records:
        task = record["task"]
        row = collection_by_task.get(task.get("task_id"))
        raw_path = row.get("result_path") if isinstance(row, dict) else None
        candidate = Path(raw_path) if isinstance(raw_path, str) else Path()
        candidate = candidate if candidate.is_absolute() else root / candidate
        if (
            not isinstance(row, dict)
            or candidate.resolve(strict=False) != record["path"].resolve(strict=True)
            or row.get("result_sha256") != record["ref"]["sha256"]
            or row.get("status") != "final"
            or row.get("evo_v2_task_identity")
            != record["payload"].get("evo_v2_task_identity")
            or row.get("evo_v2_outcome") != record["outcome"]
        ):
            reasons.append(
                _token(f"result_collection_binding_mismatch:{task.get('task_id')}")
            )

    reasons.extend(
        _validate_summary(
            summary,
            report_id=report_id,
            formal_context=formal_context,
            result_records=result_records,
            root=root,
        )
    )
    reasons.extend(
        _validate_appendix(
            appendix,
            report_id=report_id,
            summary_path=summary_path,
            result_records=result_records,
            root=root,
        )
    )

    expected_bindings = {
        "feedback_ledger_ref": formal_context["canonical_feedback_ref"],
        "lifecycle_ref": formal_context["lifecycle_ref"],
        "dispatch_manifest_ref": _file_ref(root, dispatch_path),
        "result_collection_ref": _file_ref(root, collection_path),
        "council_summary_ref": _file_ref(root, summary_path),
        "derivation_appendix_json_ref": _file_ref(root, appendix_json_path),
        "derivation_appendix_markdown_ref": _file_ref(root, appendix_md_path),
        "raw_result_refs": [record["ref"] for record in result_records],
        "selected_proposal_ref": None,
    }
    bindings = synthesis.get("evidence_bindings")
    if not isinstance(bindings, dict) or set(bindings) != _BINDING_FIELDS:
        reasons.append(_token("evidence_bindings_closed_shape_invalid"))
        bindings = {}
    for name, expected in expected_bindings.items():
        if name == "selected_proposal_ref":
            continue
        if bindings.get(name) != expected:
            reasons.append(_token(f"evidence_binding_mismatch:{name}"))
    for reference in (bindings.get("raw_result_refs") or []):
        if _resolve_ref(root, reference, expected_fields=_TASK_REF_FIELDS) is None:
            reasons.append(_token("raw_result_ref_readback_invalid"))

    selection = synthesis.get("selection")
    if not isinstance(selection, dict) or set(selection) != _SELECTION_FIELDS:
        reasons.append(_token("selection_closed_shape_invalid"))
        selection = {}
    if (
        selection.get("policy")
        != "EVIDENCE_BASED_EXACT_RAW_RESULT_SELECTION_NO_AGGREGATION"
        or selection.get("majority_vote_used") is not False
        or selection.get("score_or_rank_used") is not False
        or selection.get("result_aggregation_used") is not False
        or not _nonempty_text(selection.get("rationale"))
        or not _text_list(selection.get("decisive_evidence"))
    ):
        reasons.append(_token("selection_policy_invalid"))
    reasons.extend(_selection_text_reasons(selection))
    selected_task_id = selection.get("selected_task_id")
    selected_records = [
        record
        for record in result_records
        if record["task"].get("task_id") == selected_task_id
    ]
    if len(selected_records) != 1:
        reasons.append(_token("selected_result_not_unique"))
        selected_record = None
    else:
        selected_record = selected_records[0]
        if selection.get("selected_result_sha256") != selected_record["ref"]["sha256"]:
            reasons.append(_token("selected_result_sha256_mismatch"))
        expected_bindings["selected_proposal_ref"] = selected_record["ref"]
        if bindings.get("selected_proposal_ref") != selected_record["ref"]:
            reasons.append(_token("selected_proposal_ref_mismatch"))

    analyses = synthesis.get("route_result_analysis")
    if not isinstance(analyses, list) or len(analyses) != len(result_records):
        reasons.append(_token("route_result_analysis_coverage_invalid"))
        analyses = []
    analysis_by_task = {
        row.get("task_id"): row for row in analyses if isinstance(row, dict)
    }
    selected_analysis_count = 0
    unresolved_task_ids: list[str] = []
    for record in result_records:
        task = record["task"]
        result = record["payload"]
        task_id = str(task.get("task_id") or "")
        row = analysis_by_task.get(task_id)
        if not isinstance(row, dict) or set(row) != _ANALYSIS_FIELDS:
            reasons.append(_token(f"route_result_analysis_invalid:{task_id}"))
            continue
        if (
            row.get("route_id") != task.get("route_id")
            or row.get("route_family") != task.get("route_family")
            or row.get("agent_identifier") != result.get("agent_identifier")
            or row.get("result_ref") != record["ref"]
            or row.get("outcome") != record["outcome"].get("outcome")
            or row.get("disposition") not in {"selected", "not_selected"}
            or not _nonempty_text(row.get("exact_gap_or_closed_obligation"))
            or not _text_list(row.get("incompatible_assumptions"))
            or not _text_list(row.get("discriminating_evidence"))
            or not _text_list(row.get("open_proof_obligations"), allow_empty=True)
        ):
            reasons.append(_token(f"route_result_analysis_binding_invalid:{task_id}"))
        if row.get("disposition") == "selected":
            selected_analysis_count += 1
            if task_id != selected_task_id:
                reasons.append(_token("selected_analysis_task_mismatch"))
        elif task_id == selected_task_id:
            reasons.append(_token("selected_analysis_disposition_mismatch"))
        dissent = row.get("dissent")
        if not isinstance(dissent, dict) or set(dissent) != _DISSENT_FIELDS:
            reasons.append(_token(f"dissent_invalid:{task_id}"))
            continue
        allowed_status = (
            {"SELECTED_RESULT"}
            if task_id == selected_task_id
            else {"RESOLVED", "PRESERVED_OPEN"}
        )
        if (
            dissent.get("status") not in allowed_status
            or not _nonempty_text(dissent.get("position"))
            or not _nonempty_text(dissent.get("resolution"))
        ):
            reasons.append(_token(f"dissent_invalid:{task_id}"))
        if dissent.get("status") == "PRESERVED_OPEN":
            unresolved_task_ids.append(task_id)
    if selected_analysis_count != 1 or set(analysis_by_task) != set(task_ids):
        reasons.append(_token("route_result_analysis_exact_coverage_invalid"))
    reasons.extend(
        _selection_text_reasons(analyses, path="route_result_analysis")
    )

    dissent_resolution = synthesis.get("dissent_resolution")
    if (
        not isinstance(dissent_resolution, dict)
        or set(dissent_resolution) != _DISSENT_RESOLUTION_FIELDS
        or dissent_resolution.get("policy")
        != "PRESERVE_OR_RESOLVE_EACH_RESULT_DISSENT_WITH_DISCRIMINATING_EVIDENCE"
        or dissent_resolution.get("all_result_positions_covered") is not True
        or not _nonempty_text(dissent_resolution.get("resolution_summary"))
        or dissent_resolution.get("unresolved_task_ids") != unresolved_task_ids
    ):
        reasons.append(_token("dissent_resolution_invalid"))
    reasons.extend(
        _selection_text_reasons(dissent_resolution, path="dissent_resolution")
    )

    selected_outcome = synthesis.get("selected_outcome")
    if (
        not isinstance(selected_outcome, dict)
        or set(selected_outcome) != _SELECTED_OUTCOME_FIELDS
    ):
        reasons.append(_token("selected_outcome_closed_shape_invalid"))
        selected_outcome = {}
    if selected_record is not None:
        expected_selected = _expected_selected_outcome(selected_record)
        if selected_outcome != expected_selected:
            reasons.append(_token("selected_outcome_exact_tuple_mismatch"))
        if expected_selected["outcome"] == "MINIMAL_MECHANISM_DELTA":
            if not all(
                _nonempty_text(expected_selected.get(field))
                for field in (
                    "law_id",
                    "law_sha256",
                    "delta_id",
                    "mechanism_delta_sha256",
                    "economic_backprojection_sha256",
                )
            ) or expected_selected.get("no_derived_law_sha256") is not None:
                reasons.append(_token("selected_minimal_tuple_incomplete"))
        else:
            if (
                not _is_sha256(expected_selected.get("no_derived_law_sha256"))
                or any(
                    expected_selected.get(field) is not None
                    for field in (
                        "law_id",
                        "law_sha256",
                        "delta_id",
                        "mechanism_delta_sha256",
                        "economic_backprojection_sha256",
                    )
                )
            ):
                reasons.append(_token("selected_no_derived_tuple_incomplete"))

    reasons = _dedupe(reasons)
    if reasons:
        return None, reasons

    dataset_snapshot_hash = _aggregate_evidence_hash(
        lifecycle, "dataset_snapshot_hash", reasons
    )
    window_hash = _aggregate_evidence_hash(lifecycle, "window_hash", reasons)
    if reasons or dataset_snapshot_hash is None or window_hash is None:
        return None, _dedupe(reasons)
    synthesis_ref = _file_ref(root, selected_synthesis_path)
    counts = {
        "required_route_count": len(result_records),
        "validated_raw_result_count": len(result_records),
        "minimal_mechanism_delta_count": sum(
            record["outcome"].get("outcome") == "MINIMAL_MECHANISM_DELTA"
            for record in result_records
        ),
        "no_derived_law_count": sum(
            record["outcome"].get("outcome") == "NO_DERIVED_LAW"
            for record in result_records
        ),
        "preserved_open_dissent_count": len(unresolved_task_ids),
        "selected_raw_result_count": 1,
    }
    report: dict[str, Any] = {
        "contract_version": PRE_OOS_OUTCOME_VERIFIER_VERSION,
        "verifier_id": PRE_OOS_OUTCOME_VERIFIER_ID,
        "verifier_source_sha256": verifier_source_sha256(),
        "verifier_status": "PASS",
        "report_id": report_id,
        "dataset_snapshot_hash": dataset_snapshot_hash,
        "window_hash": window_hash,
        "evidence_view": PURGED_IS_EVIDENCE_VIEW,
        "validated_synthesis_ref": synthesis_ref,
        "evidence_bindings": expected_bindings,
        "selected_outcome": dict(selected_outcome),
        "authorized_host_transition_state": selected_outcome["outcome"],
        "authority": dict(_REPORT_AUTHORITY),
        "validation_counts": counts,
        "binding_digest": stable_json_hash(
            {
                "validated_synthesis_ref": synthesis_ref,
                "evidence_bindings": expected_bindings,
                "selected_outcome": selected_outcome,
            }
        ),
    }
    report["content_sha256"] = stable_json_hash(report)
    return report, []


def _report_reference(
    root: Path,
    path: Path,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **_file_ref(root, path),
        "dataset_snapshot_hash": report["dataset_snapshot_hash"],
        "window_hash": report["window_hash"],
        "verifier_id": report["verifier_id"],
        "verifier_source_sha256": report["verifier_source_sha256"],
        "verifier_status": report["verifier_status"],
        "report_id": report["report_id"],
        "authorized_transition_state": report["authorized_host_transition_state"],
        "selected_proposal_ref": report["evidence_bindings"][
            "selected_proposal_ref"
        ],
        "binding_digest": report["binding_digest"],
    }


@contextmanager
def _outcome_lock(root: Path, report_id: str) -> Iterator[None]:
    directory = _council_dir(root, report_id)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".pre_oos_council_outcome.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def materialize_pre_oos_council_outcome(
    *,
    workspace_root: Path | str,
    report_id: str,
    synthesis_path: Path | str,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    source = Path(synthesis_path).expanduser().resolve(strict=False)
    with _outcome_lock(root, report_id):
        synthesis = _load_object(source)
        report, reasons = validate_pre_oos_root_synthesis(
            synthesis,
            workspace_root=root,
            report_id=report_id,
            synthesis_path=source,
        )
        if reasons or report is None:
            raise PreOosCouncilOutcomeError(reasons or [_token("unknown_failure")])
        output = pre_oos_outcome_verifier_path(root, report_id)
        expected = canonical_json_bytes(report)
        if output.exists():
            if output.is_symlink() or not output.is_file() or output.read_bytes() != expected:
                raise PreOosCouncilOutcomeError(
                    [BLOCK_PRE_OOS_MATERIALIZATION_CONFLICT]
                )
            idempotent = True
        else:
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
            )
            os.close(descriptor)
            temporary_path = Path(temporary)
            try:
                temporary_path.write_bytes(expected)
                os.replace(temporary_path, output)
            finally:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass
            idempotent = False
        if output.read_bytes() != expected:
            raise PreOosCouncilOutcomeError(
                [BLOCK_PRE_OOS_MATERIALIZATION_CONFLICT + ":readback"]
            )
        return {
            "result": "PASS",
            "report_path": _relative(root, output),
            "idempotent_replay": idempotent,
            "selected_outcome": report["selected_outcome"],
            "authorized_host_transition_state": report[
                "authorized_host_transition_state"
            ],
            "evidence_ref": _report_reference(root, output, report),
            "authority": dict(_REPORT_AUTHORITY),
        }


def validate_materialized_pre_oos_council_outcome(
    *,
    workspace_root: Path | str,
    report_id: str,
    expected_transition_state: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    output = pre_oos_outcome_verifier_path(root, report_id)
    try:
        report = _load_object(output)
    except PreOosCouncilOutcomeError as exc:
        return None, exc.reasons
    reasons: list[str] = []
    if set(report) != _REPORT_FIELDS:
        reasons.append(_token("verifier_report_closed_shape_invalid"))
    if (
        report.get("contract_version") != PRE_OOS_OUTCOME_VERIFIER_VERSION
        or report.get("verifier_id") != PRE_OOS_OUTCOME_VERIFIER_ID
        or report.get("verifier_source_sha256") != verifier_source_sha256()
        or report.get("verifier_status") != "PASS"
        or report.get("report_id") != report_id
        or report.get("evidence_view") != PURGED_IS_EVIDENCE_VIEW
        or report.get("authority") != _REPORT_AUTHORITY
    ):
        reasons.append(_token("verifier_report_header_invalid"))
    unsigned = dict(report)
    digest = unsigned.pop("content_sha256", None)
    if digest != stable_json_hash(unsigned):
        reasons.append(_token("verifier_report_content_sha256_mismatch"))
    if output.read_bytes() != canonical_json_bytes(report):
        reasons.append(_token("verifier_report_noncanonical_json"))
    synthesis_ref = report.get("validated_synthesis_ref")
    synthesis_path = _resolve_ref(root, synthesis_ref)
    if synthesis_path is None:
        reasons.append(_token("verifier_report_synthesis_ref_invalid"))
    else:
        synthesis = _load_object(synthesis_path)
        expected, replay_reasons = validate_pre_oos_root_synthesis(
            synthesis,
            workspace_root=root,
            report_id=report_id,
            synthesis_path=synthesis_path,
        )
        reasons.extend(replay_reasons)
        if expected != report:
            reasons.append(_token("verifier_report_replay_mismatch"))
    if (
        expected_transition_state is not None
        and report.get("authorized_host_transition_state")
        != expected_transition_state
    ):
        reasons.append(_token("verifier_report_transition_state_mismatch"))
    return (report if not reasons else None), _dedupe(reasons)


def pre_oos_outcome_evidence_reference(
    *,
    workspace_root: Path | str,
    report_id: str,
    expected_transition_state: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    report, reasons = validate_materialized_pre_oos_council_outcome(
        workspace_root=root,
        report_id=report_id,
        expected_transition_state=expected_transition_state,
    )
    if report is None:
        return None, reasons
    output = pre_oos_outcome_verifier_path(root, report_id)
    return _report_reference(root, output, report), []


__all__ = [
    "BLOCK_PRE_OOS_EXTERNAL_VALIDATION",
    "BLOCK_PRE_OOS_MATERIALIZATION_CONFLICT",
    "BLOCK_PRE_OOS_OUTCOME",
    "PRE_OOS_OUTCOME_VERIFIER_ID",
    "PRE_OOS_OUTCOME_VERIFIER_VERSION",
    "PRE_OOS_ROOT_SYNTHESIS_VERSION",
    "PreOosCouncilOutcomeError",
    "materialize_pre_oos_council_outcome",
    "pre_oos_outcome_evidence_reference",
    "pre_oos_outcome_verifier_path",
    "pre_oos_root_synthesis_path",
    "validate_materialized_pre_oos_council_outcome",
    "validate_pre_oos_root_synthesis",
    "verifier_source_sha256",
]
