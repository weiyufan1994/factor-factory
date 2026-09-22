from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from factor_factory.evo_staging import (
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_FEEDBACK,
    STAGE_ADMIT_TRANSFER,
    STAGE_RECORD_USE,
    _lifecycle_parent_sha256,
    materialize_evo_v2_stage,
    staging_manifest_path,
    validate_evo_v2_staging_manifest,
)
from factor_factory.evo_v2 import (
    EvoV2Error,
    canonical_json_bytes,
    evo_v2_paths,
    load_json_object,
    sha256_file,
)
from factor_factory.pre_oos_human_bridge import (
    pre_oos_child_handoff_path,
    pre_oos_human_approval_path,
)
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    epistemic_evolution_lifecycle_path,
    validate_epistemic_evolution_lifecycle,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
)
from factor_factory.revision_council.pre_oos_outcome import (
    pre_oos_outcome_evidence_reference,
    validate_materialized_pre_oos_council_outcome,
)


BLOCK_PRE_OOS_ORCHESTRATION = (
    "BLOCK_FACTORFORGE_EVO_V2_PRE_OOS_OUTCOME_ORCHESTRATION_INVALID"
)
ALLOWED_OUTCOMES = {"MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"}
_DESCENDANTS = {"TRANSFER_RECORDED", "COLD_START_RECORDED"}
_SELECTED_REF_FIELDS = {"task_id", "path", "sha256"}


class PreOosOutcomeOrchestrationError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
        super().__init__(";".join(self.reasons))


def _block(reason: str) -> PreOosOutcomeOrchestrationError:
    return PreOosOutcomeOrchestrationError(
        [f"{BLOCK_PRE_OOS_ORCHESTRATION}:{reason}"]
    )


def _read_canonical(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise _block(f"missing_or_unsafe:{path.name}")
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise _block(f"invalid_json:{path.name}") from exc
    if path.read_bytes() != canonical_json_bytes(payload):
        raise _block(f"noncanonical_json:{path.name}")
    return payload


def _resolve_ref(root: Path, reference: Any, *, fields: set[str]) -> Path:
    if not isinstance(reference, dict) or set(reference) != fields:
        raise _block("reference_shape")
    raw = reference.get("path")
    if not isinstance(raw, str) or "\\" in raw:
        raise _block("reference_path")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise _block("reference_path")
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise _block("reference_escape") from exc
    if path.is_symlink() or not path.is_file():
        raise _block("reference_readback")
    if reference.get("sha256") != sha256_file(path):
        raise _block("reference_sha256")
    return path


def _selected_proposal(
    *,
    root: Path,
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    bindings = report.get("evidence_bindings")
    selected = (
        bindings.get("selected_proposal_ref")
        if isinstance(bindings, Mapping)
        else None
    )
    path = _resolve_ref(root, selected, fields=_SELECTED_REF_FIELDS)
    proposal = _read_canonical(path)
    return dict(selected), proposal


def _validated_outcome(
    *,
    root: Path,
    report_id: str,
    expected_transition_state: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if expected_transition_state not in ALLOWED_OUTCOMES:
        raise _block("expected_transition_state")
    report, reasons = validate_materialized_pre_oos_council_outcome(
        workspace_root=root,
        report_id=report_id,
        expected_transition_state=expected_transition_state,
    )
    if reasons or report is None:
        raise PreOosOutcomeOrchestrationError(
            [
                f"{BLOCK_PRE_OOS_ORCHESTRATION}:outcome_verifier:{reason}"
                for reason in reasons
            ]
            or [f"{BLOCK_PRE_OOS_ORCHESTRATION}:outcome_verifier_missing"]
        )
    reference, reference_reasons = pre_oos_outcome_evidence_reference(
        workspace_root=root,
        report_id=report_id,
        expected_transition_state=expected_transition_state,
    )
    if reference_reasons or reference is None:
        raise PreOosOutcomeOrchestrationError(
            [
                f"{BLOCK_PRE_OOS_ORCHESTRATION}:outcome_reference:{reason}"
                for reason in reference_reasons
            ]
            or [f"{BLOCK_PRE_OOS_ORCHESTRATION}:outcome_reference_missing"]
        )
    if (
        reference.get("authorized_transition_state") != expected_transition_state
        or reference.get("report_id") != report_id
        or reference.get("verifier_status") != "PASS"
        or report.get("authorized_host_transition_state")
        != expected_transition_state
    ):
        raise _block("outcome_authority_or_transition")
    selected_ref, proposal = _selected_proposal(root=root, report=report)
    if reference.get("selected_proposal_ref") != selected_ref:
        raise _block("outcome_selected_proposal_binding")
    feedback_ref = (report.get("evidence_bindings") or {}).get(
        "feedback_ledger_ref"
    )
    feedback_path = _resolve_ref(root, feedback_ref, fields={"path", "sha256"})
    canonical_feedback = evo_v2_paths(root, report_id)["feedback_ledger"]
    if feedback_path != canonical_feedback.resolve(strict=False):
        raise _block("feedback_not_canonical")
    feedback = _read_canonical(feedback_path)
    return report, dict(reference), proposal, feedback


def _load_lifecycle(root: Path, report_id: str) -> dict[str, Any]:
    path = epistemic_evolution_lifecycle_path(root, report_id)
    lifecycle = _read_canonical(path)
    reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if reasons:
        raise PreOosOutcomeOrchestrationError(
            [
                f"{BLOCK_PRE_OOS_ORCHESTRATION}:lifecycle:{reason}"
                for reason in reasons
            ]
        )
    return lifecycle


def _qualified_lifecycle_prefix(
    lifecycle: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    events = lifecycle.get("events")
    if not isinstance(events, list):
        raise _block("lifecycle_events")
    qualified_indices = [
        index
        for index, event in enumerate(events)
        if isinstance(event, Mapping)
        and event.get("to_state") == "QUALIFIED_CONTRADICTION"
    ]
    if len(qualified_indices) != 1:
        raise _block("qualified_transition_count")
    index = qualified_indices[0]
    prefix: dict[str, Any] = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": lifecycle.get("report_id"),
        "current_state": "QUALIFIED_CONTRADICTION",
        "events": [dict(event) for event in events[: index + 1]],
        "host_authority": lifecycle.get("host_authority"),
    }
    prefix["content_sha256"] = stable_hash(prefix)
    return prefix, index


def _qualified_cas(
    lifecycle: Mapping[str, Any],
    *,
    expected_qualified_lifecycle_sha256: str,
) -> tuple[dict[str, Any], int, str]:
    qualified, index = _qualified_lifecycle_prefix(lifecycle)
    digest = stable_hash(qualified)
    if digest != expected_qualified_lifecycle_sha256:
        raise _block("qualified_lifecycle_cas_mismatch")
    events = lifecycle.get("events")
    if not isinstance(events, list) or events[: index + 1] != qualified["events"]:
        raise _block("qualified_lifecycle_not_ancestor")
    return qualified, index, digest


def _transition_event(
    *,
    lifecycle: Mapping[str, Any],
    qualified_index: int,
    expected_transition_state: str,
    outcome_reference: Mapping[str, Any],
) -> dict[str, Any]:
    events = lifecycle.get("events")
    if not isinstance(events, list) or len(events) <= qualified_index + 1:
        raise _block("outcome_transition_missing")
    event = events[qualified_index + 1]
    if (
        not isinstance(event, dict)
        or event.get("from_state") != "QUALIFIED_CONTRADICTION"
        or event.get("to_state") != expected_transition_state
        or event.get("evidence_refs") != [dict(outcome_reference)]
        or event.get("actor") != "Ultimate Host"
    ):
        raise _block("outcome_transition_binding")
    matching = [
        item
        for item in events
        if isinstance(item, dict)
        and item.get("from_state") == "QUALIFIED_CONTRADICTION"
    ]
    if len(matching) != 1:
        raise _block("outcome_transition_not_unique")
    return event


def _load_staging_manifest(
    root: Path,
    report_id: str,
) -> dict[str, Any] | None:
    path = staging_manifest_path(root, report_id)
    if not path.exists():
        return None
    manifest = _read_canonical(path)
    reasons = validate_evo_v2_staging_manifest(
        manifest,
        root=root,
        report_id=report_id,
        verify_readback=True,
    )
    if reasons:
        raise PreOosOutcomeOrchestrationError(
            [
                f"{BLOCK_PRE_OOS_ORCHESTRATION}:staging:{reason}"
                for reason in reasons
            ]
        )
    return manifest


def _validate_staged_outcome(
    *,
    root: Path,
    report_id: str,
    manifest: Mapping[str, Any],
    expected_transition_state: str,
    selected_proposal: Mapping[str, Any],
) -> None:
    events = manifest.get("events")
    if not isinstance(events, list) or len(events) < 2:
        raise _block("staging_outcome_incomplete")
    feedback_event, council_event = events[0], events[1]
    if (
        not isinstance(feedback_event, Mapping)
        or feedback_event.get("sequence") != 1
        or feedback_event.get("stage") != STAGE_ADMIT_FEEDBACK
        or feedback_event.get("outcome") != "QUALIFIED_CONTRADICTION"
        or not isinstance(council_event, Mapping)
        or council_event.get("sequence") != 2
        or council_event.get("stage") != STAGE_ADMIT_COUNCIL_OUTCOME
        or council_event.get("outcome") != expected_transition_state
    ):
        raise _block("staging_outcome_order_or_binding")
    proposal_digest = hashlib.sha256(
        canonical_json_bytes(selected_proposal)
    ).hexdigest()
    if (council_event.get("input_digests") or {}).get(
        "council_proposal"
    ) != proposal_digest:
        raise _block("staging_selected_proposal_digest")
    if expected_transition_state == "NO_DERIVED_LAW" and len(events) != 2:
        raise _block("no_derived_branch_not_terminal")
    if expected_transition_state == "MINIMAL_MECHANISM_DELTA":
        allowed = [
            STAGE_ADMIT_FEEDBACK,
            STAGE_ADMIT_COUNCIL_OUTCOME,
            STAGE_ADMIT_TRANSFER,
            STAGE_RECORD_USE,
        ]
        actual = [event.get("stage") for event in events if isinstance(event, Mapping)]
        if actual != allowed[: len(actual)]:
            raise _block("minimal_branch_stage_order")


def _assert_pre_human_surface(root: Path, report_id: str) -> None:
    forbidden = [
        pre_oos_human_approval_path(root, report_id),
        pre_oos_child_handoff_path(root, report_id),
    ]
    existing = [path.name for path in forbidden if path.exists() or path.is_symlink()]
    if existing:
        raise _block("human_or_child_surface_present:" + ",".join(existing))


def _run_signed_lifecycle_transition(
    *,
    root: Path,
    report_id: str,
    transition_state: str,
    evidence_ref: Mapping[str, Any],
    expected_parent_sha256: str,
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts/record_factorforge_evo_v2_lifecycle.py"
    command = [
        sys.executable,
        str(script),
        "--workspace-root",
        str(root),
        "--report-id",
        report_id,
        "--to-state",
        transition_state,
        "--evidence-ref",
        json.dumps(
            dict(evidence_ref),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "--expected-parent-sha256",
        expected_parent_sha256,
        "--trust-root",
        str(trust_root),
        "--installation-id",
        installation_id,
    ]
    completed = subprocess.run(
        command,
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip()[-2000:]
        raise _block(
            "signed_lifecycle_transition_failed:"
            + (diagnostic or f"return_code_{completed.returncode}")
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise _block("signed_lifecycle_transition_output") from exc
    if (
        not isinstance(result, dict)
        or result.get("verdict") != "PASS"
        or result.get("current_state") != transition_state
    ):
        raise _block("signed_lifecycle_transition_result")
    return result


@contextmanager
def _orchestration_lock(root: Path, report_id: str):
    directory = evo_v2_paths(root, report_id)["feedback_ledger"].parent
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise _block("orchestration_directory_symlink")
    path = directory / ".pre_oos_outcome_orchestration.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def validate_pre_oos_council_outcome_orchestration(
    *,
    workspace_root: Path,
    report_id: str,
    expected_transition_state: str,
    expected_qualified_lifecycle_sha256: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    _assert_pre_human_surface(root, report_id)
    report, outcome_ref, proposal, _feedback = _validated_outcome(
        root=root,
        report_id=report_id,
        expected_transition_state=expected_transition_state,
    )
    lifecycle = _load_lifecycle(root, report_id)
    _qualified, qualified_index, qualified_digest = _qualified_cas(
        lifecycle,
        expected_qualified_lifecycle_sha256=expected_qualified_lifecycle_sha256,
    )
    current_state = lifecycle.get("current_state")
    allowed_states = {expected_transition_state}
    if expected_transition_state == "MINIMAL_MECHANISM_DELTA":
        allowed_states.update(_DESCENDANTS)
    if current_state not in allowed_states:
        raise _block(f"lifecycle_outcome_state:{current_state}")
    transition = _transition_event(
        lifecycle=lifecycle,
        qualified_index=qualified_index,
        expected_transition_state=expected_transition_state,
        outcome_reference=outcome_ref,
    )
    manifest = _load_staging_manifest(root, report_id)
    if manifest is None:
        raise _block("staging_manifest_missing")
    _validate_staged_outcome(
        root=root,
        report_id=report_id,
        manifest=manifest,
        expected_transition_state=expected_transition_state,
        selected_proposal=proposal,
    )
    _assert_pre_human_surface(root, report_id)
    manifest_path = staging_manifest_path(root, report_id)
    return {
        "verdict": "PASS",
        "report_id": report_id,
        "authorized_transition_state": expected_transition_state,
        "lifecycle_state": current_state,
        "qualified_lifecycle_sha256": qualified_digest,
        "outcome_evidence_ref": outcome_ref,
        "selected_proposal_ref": report["evidence_bindings"][
            "selected_proposal_ref"
        ],
        "lifecycle_transition_event_sha256": transition["event_sha256"],
        "staging_manifest": {
            "path": manifest_path.relative_to(root).as_posix(),
            "sha256": sha256_file(manifest_path),
            "content_sha256": manifest["content_sha256"],
            "stages": [event["stage"] for event in manifest["events"]],
        },
        "authority": {
            "host_transition_verified": True,
            "human_approval_granted": False,
            "child_execution_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "canonical_memory_write_allowed": False,
            "oos_accessed": False,
        },
    }


def orchestrate_pre_oos_council_outcome(
    *,
    workspace_root: Path,
    report_id: str,
    expected_transition_state: str,
    expected_qualified_lifecycle_sha256: str,
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    """Advance one verified pre-OOS Council outcome through Host-only gates."""

    root = workspace_root.expanduser().resolve(strict=True)
    private_root = trust_root.expanduser().resolve(strict=True)
    if private_root == root or root in private_root.parents:
        raise _block("trust_root_inside_workspace")
    trust_store = load_runtime_trust_store(
        private_root,
        installation_id=installation_id,
    )
    manifest = workspace_runtime_trust_manifest(root, report_id=report_id)
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest != trust_store.public_manifest
    ):
        raise _block("trust_manifest_mismatch")

    transition_performed = False
    feedback_materialized = False
    council_materialized = False
    with _orchestration_lock(root, report_id):
        _assert_pre_human_surface(root, report_id)
        report, outcome_ref, proposal, feedback = _validated_outcome(
            root=root,
            report_id=report_id,
            expected_transition_state=expected_transition_state,
        )
        lifecycle = _load_lifecycle(root, report_id)
        _qualified, qualified_index, qualified_digest = _qualified_cas(
            lifecycle,
            expected_qualified_lifecycle_sha256=(
                expected_qualified_lifecycle_sha256
            ),
        )
        current_state = lifecycle.get("current_state")
        allowed_current = {
            "QUALIFIED_CONTRADICTION",
            expected_transition_state,
        }
        if expected_transition_state == "MINIMAL_MECHANISM_DELTA":
            allowed_current.update(_DESCENDANTS)
        if current_state not in allowed_current:
            raise _block(f"lifecycle_state:{current_state}")

        staging = _load_staging_manifest(root, report_id)
        staging_events = list(staging.get("events") or []) if staging else []
        if not staging_events:
            if current_state != "QUALIFIED_CONTRADICTION":
                raise _block("feedback_requires_qualified_parent")
            parent_sha = _lifecycle_parent_sha256(lifecycle)
            if not isinstance(parent_sha, str):
                raise _block("qualified_lifecycle_parent_missing")
            feedback_result = materialize_evo_v2_stage(
                workspace_root=root,
                report_id=report_id,
                stage=STAGE_ADMIT_FEEDBACK,
                expected_lifecycle_parent_sha256=parent_sha,
                expected_lifecycle_content_sha256=lifecycle["content_sha256"],
                expected_staging_content_sha256="ABSENT",
                feedback_ledger=feedback,
            )
            feedback_materialized = not feedback_result.get("idempotent_replay")
            staging = _load_staging_manifest(root, report_id)
            staging_events = list(staging.get("events") or []) if staging else []
        if (
            not staging_events
            or staging_events[0].get("stage") != STAGE_ADMIT_FEEDBACK
            or staging_events[0].get("outcome") != "QUALIFIED_CONTRADICTION"
        ):
            raise _block("feedback_stage_invalid")

        replay_report, replay_ref, replay_proposal, replay_feedback = _validated_outcome(
            root=root,
            report_id=report_id,
            expected_transition_state=expected_transition_state,
        )
        if (
            replay_report != report
            or replay_ref != outcome_ref
            or replay_proposal != proposal
            or replay_feedback != feedback
        ):
            raise _block("outcome_changed_before_transition")

        lifecycle = _load_lifecycle(root, report_id)
        current_state = lifecycle.get("current_state")
        if current_state == "QUALIFIED_CONTRADICTION":
            if stable_hash(lifecycle) != qualified_digest:
                raise _block("qualified_lifecycle_changed_before_transition")
            _run_signed_lifecycle_transition(
                root=root,
                report_id=report_id,
                transition_state=expected_transition_state,
                evidence_ref=outcome_ref,
                expected_parent_sha256=qualified_digest,
                trust_root=private_root,
                installation_id=installation_id,
            )
            transition_performed = True
            lifecycle = _load_lifecycle(root, report_id)

        _qualified_cas(
            lifecycle,
            expected_qualified_lifecycle_sha256=qualified_digest,
        )
        _transition_event(
            lifecycle=lifecycle,
            qualified_index=qualified_index,
            expected_transition_state=expected_transition_state,
            outcome_reference=outcome_ref,
        )
        report_after, outcome_ref_after, proposal_after, _feedback_after = (
            _validated_outcome(
                root=root,
                report_id=report_id,
                expected_transition_state=expected_transition_state,
            )
        )
        if (
            report_after != report
            or outcome_ref_after != outcome_ref
            or proposal_after != proposal
        ):
            raise _block("outcome_changed_after_transition")

        staging = _load_staging_manifest(root, report_id)
        staging_events = list(staging.get("events") or []) if staging else []
        if len(staging_events) == 1:
            parent_sha = _lifecycle_parent_sha256(lifecycle)
            if not isinstance(parent_sha, str):
                raise _block("outcome_lifecycle_parent_missing")
            council_result = materialize_evo_v2_stage(
                workspace_root=root,
                report_id=report_id,
                stage=STAGE_ADMIT_COUNCIL_OUTCOME,
                expected_lifecycle_parent_sha256=parent_sha,
                expected_lifecycle_content_sha256=lifecycle["content_sha256"],
                expected_staging_content_sha256=staging["content_sha256"],
                council_proposal=proposal,
            )
            council_materialized = not council_result.get("idempotent_replay")
        elif len(staging_events) >= 2:
            _validate_staged_outcome(
                root=root,
                report_id=report_id,
                manifest=staging,
                expected_transition_state=expected_transition_state,
                selected_proposal=proposal,
            )
        else:
            raise _block("staging_feedback_missing_after_transition")
        _assert_pre_human_surface(root, report_id)

        validation = validate_pre_oos_council_outcome_orchestration(
            workspace_root=root,
            report_id=report_id,
            expected_transition_state=expected_transition_state,
            expected_qualified_lifecycle_sha256=qualified_digest,
        )
        return {
            **validation,
            "status": (
                "ORCHESTRATED"
                if transition_performed or feedback_materialized or council_materialized
                else "IDEMPOTENT_REPLAY"
            ),
            "actions": {
                "feedback_materialized": feedback_materialized,
                "host_lifecycle_transition_performed": transition_performed,
                "council_outcome_materialized": council_materialized,
            },
        }


__all__ = [
    "ALLOWED_OUTCOMES",
    "BLOCK_PRE_OOS_ORCHESTRATION",
    "PreOosOutcomeOrchestrationError",
    "orchestrate_pre_oos_council_outcome",
    "validate_pre_oos_council_outcome_orchestration",
]
