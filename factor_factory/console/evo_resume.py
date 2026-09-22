from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from factor_factory.evo_staging import (
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_FEEDBACK,
    STAGE_ADMIT_TRANSFER,
    STAGE_RECORD_USE,
    staging_manifest_path,
    validate_evo_v2_staging_manifest,
)
from factor_factory.evo_execution_addendum import (
    ADDENDUM_STATUS,
    REGISTERED_STATUS,
    execution_addendum_path,
)
from factor_factory.evo_oos import oos_host_trust_manifest_path, oos_registry_path
from factor_factory.evo_child_materialization_ticket import (
    public_child_materialization_ticket_path,
    public_child_materialization_trust_manifest_path,
    validate_public_child_materialization_ticket,
)
from factor_factory.evo_terminal_closure import (
    terminal_closure_path,
    validate_evo_post_oos_terminal_closure,
)
from factor_factory.evo_transfer_use_orchestrator import (
    transfer_use_orchestration_path,
    validate_evo_v2_transfer_use_orchestration,
)
from factor_factory.evo_v2 import (
    evo_v2_paths,
    load_json_object,
    sha256_file,
    validate_feedback_ledger,
    validate_materialized_evo_v2,
)
from factor_factory.pre_oos_human_bridge import (
    pre_oos_child_handoff_path,
    pre_oos_child_intent_path,
    pre_oos_human_approval_path,
    validate_pre_oos_child_handoff,
)
from factor_factory.human_approval import human_approval_trust_path
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
)
from factor_factory.revision_council.pre_oos_outcome import (
    validate_materialized_pre_oos_council_outcome,
)


BLOCK_EVO_V2_EXTERNAL_RESUME = (
    "BLOCK_FACTORFORGE_CONSOLE_EVO_V2_EXTERNAL_RESUME_INVALID"
)

PAUSE_AWAIT_HOST_QUALIFICATION = "awaiting_evo_v2_host_qualification"
PAUSE_AWAIT_HOST_COUNCIL_OUTCOME = (
    "awaiting_host_lifecycle_transition_and_staged_council_outcome"
)
PAUSE_AWAIT_TRANSFER_USE = "awaiting_evo_v2_transfer_and_actual_use"
PAUSE_AWAIT_EXTERNAL_CHILD = (
    "awaiting_evo_v2_external_approval_and_fresh_child"
)
PAUSE_AWAIT_NQC_TERMINAL_CLOSURE = (
    "awaiting_evo_v2_non_revision_terminal_closure"
)

EVO_V2_EXTERNAL_PAUSES = frozenset(
    {
        PAUSE_AWAIT_HOST_QUALIFICATION,
        PAUSE_AWAIT_HOST_COUNCIL_OUTCOME,
        PAUSE_AWAIT_TRANSFER_USE,
        PAUSE_AWAIT_EXTERNAL_CHILD,
        PAUSE_AWAIT_NQC_TERMINAL_CLOSURE,
    }
)

PROGRESS_WAITING = "WAITING_EXTERNAL_CONTROL"
PROGRESS_HOST_CHECKPOINT_READY = "HOST_FORMAL_CHECKPOINT_READY"
PROGRESS_CHILD_HANDOFF_READY = "CHILD_HANDOFF_READY"
PROGRESS_CHILD_HANDOFF_AUTHORIZED = "CHILD_HANDOFF_AUTHORIZED"
PROGRESS_TERMINAL_CHECKPOINT_READY = "TERMINAL_CHECKPOINT_READY"

_PAUSE_CONTRACTS: dict[str, dict[str, Any]] = {
    PAUSE_AWAIT_HOST_QUALIFICATION: {
        "proof_semantics": "purged_is_checkpoint_only_awaiting_host_qualification",
        "paused_states": {"PREDICTIONS_FROZEN"},
        "gate_actions": {"AWAIT_HOST_QUALIFICATION"},
        "next_states": {
            "NO_QUALIFIED_CONTRADICTION",
            "QUALIFIED_CONTRADICTION",
        },
        "baseline_stage_count": 0,
    },
    PAUSE_AWAIT_HOST_COUNCIL_OUTCOME: {
        "proof_semantics": "pre_oos_council_outcome_verified_review_only",
        "paused_states": {"QUALIFIED_CONTRADICTION"},
        "gate_actions": {"RUN_PRE_OOS_REVISION_COUNCIL"},
        "next_states": {"MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"},
        "baseline_stage_count": 1,
    },
    PAUSE_AWAIT_TRANSFER_USE: {
        "proof_semantics": "review_only_delta_awaiting_transfer_and_actual_use",
        "paused_states": {"MINIMAL_MECHANISM_DELTA"},
        "gate_actions": {"AWAIT_EVO_V2_TRANSFER_AND_USE"},
        "next_states": {"TRANSFER_RECORDED", "COLD_START_RECORDED"},
        "baseline_stage_count": 2,
    },
    PAUSE_AWAIT_EXTERNAL_CHILD: {
        "proof_semantics": (
            "review_only_delta_awaiting_external_approval_and_fresh_child"
        ),
        "paused_states": {"TRANSFER_RECORDED", "COLD_START_RECORDED"},
        "gate_actions": {"AWAIT_EXTERNAL_APPROVAL_AND_CHILD"},
        "next_states": set(),
        "baseline_stage_count": 4,
    },
    PAUSE_AWAIT_NQC_TERMINAL_CLOSURE: {
        "proof_semantics": "awaiting_evo_v2_non_revision_terminal_closure",
        "paused_states": {"NO_QUALIFIED_CONTRADICTION"},
        "gate_actions": {"RELEASE_ORIGINAL_CANDIDATE_OOS"},
        "next_states": set(),
        "baseline_stage_count": 0,
        "oos_release_allowed": True,
        "terminal_closure_pause": True,
    },
}

_HEX = frozenset("0123456789abcdef")


class EvoV2ExternalResumeError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
        super().__init__(";".join(self.reasons))


@dataclass(frozen=True)
class EvoV2ExternalResumeAssessment:
    report_id: str
    pause_outcome: str
    status: str
    start_step: str | None
    paused_lifecycle_state: str
    paused_lifecycle_generation: int
    paused_lifecycle_snapshot_path: str
    paused_lifecycle_snapshot_sha256: str
    current_lifecycle_state: str
    current_lifecycle_generation: int
    current_lifecycle_sha256: str
    staging_event_count: int
    child_report_id: str | None
    terminal_factor_verdict: str | None
    terminal_decision: str | None
    terminal_closure_path: str | None
    terminal_closure_sha256: str | None
    transfer_use_orchestration_path: str | None
    transfer_use_orchestration_sha256: str | None
    transfer_use_orchestration_content_sha256: str | None
    transfer_memory_state: str | None
    execution_addendum_path: str | None
    execution_addendum_sha256: str | None
    execution_addendum_status: str | None
    execution_addendum_state: str | None
    transfer_test_execution_completed: bool | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _block(reason: str) -> EvoV2ExternalResumeError:
    return EvoV2ExternalResumeError([f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:{reason}"])


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise _block(f"{label}_missing_or_unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _block(f"{label}_invalid_json") from exc
    if not isinstance(payload, dict):
        raise _block(f"{label}_object_required")
    return payload


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError as exc:
        raise _block("path_escape") from exc


def _resolve_relative(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise _block("reference_path_invalid")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw:
        raise _block("reference_path_invalid")
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise _block("reference_symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise _block("reference_readback") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise _block("reference_not_regular")
    return resolved


def _workspace_tree(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise _block(f"workspace_symlink:{relative}")
        if path.is_file():
            entries[relative] = sha256_file(path)
        elif not path.is_dir():
            raise _block(f"workspace_non_regular:{relative}")
    return entries


def _add_allowed_file(
    root: Path,
    allowed: dict[str, str],
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> None:
    relative = _relative(root, path)
    resolved = _resolve_relative(root, relative)
    digest = sha256_file(resolved)
    if expected_sha256 is not None and digest != expected_sha256:
        raise _block(f"allowed_file_sha256:{relative}")
    prior = allowed.get(relative)
    if prior is not None and prior != digest:
        raise _block(f"allowed_file_binding_conflict:{relative}")
    allowed[relative] = digest


def _add_empty_lock_if_present(
    root: Path,
    allowed: dict[str, str],
    path: Path,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    _add_allowed_file(root, allowed, path)
    if path.stat().st_size != 0:
        raise _block(f"lock_file_not_empty:{_relative(root, path)}")


def _collect_hash_bound_refs(
    root: Path,
    allowed: dict[str, str],
    value: Any,
    *,
    _seen: set[str] | None = None,
) -> None:
    """Close only refs that bind actual file bytes, never semantic digests."""

    seen = _seen if _seen is not None else set()
    if isinstance(value, Mapping):
        raw_path = value.get("path")
        digest = value.get("sha256")
        historical_lifecycle_binding = bool(
            isinstance(raw_path, str)
            and raw_path.endswith("/lifecycle.json")
            and {
                "path",
                "sha256",
                "parent_sha256",
                "content_sha256",
                "current_state",
            }.issubset(value)
        )
        if (
            isinstance(raw_path, str)
            and _is_sha256(digest)
            and not historical_lifecycle_binding
        ):
            try:
                referenced = _resolve_relative(root, raw_path)
            except EvoV2ExternalResumeError as exc:
                if any(
                    reason.endswith(
                        (":reference_readback", ":reference_path_invalid")
                    )
                    for reason in exc.reasons
                ):
                    referenced = None
                else:
                    raise
            # Some contracts deliberately use ``sha256`` for a canonical
            # payload/semantic digest rather than the file-byte digest.  Such
            # fields remain validated by their owning formal validator, but
            # cannot extend this workspace-delta allowlist.
            if referenced is None or sha256_file(referenced) != str(digest):
                for child in value.values():
                    _collect_hash_bound_refs(root, allowed, child, _seen=seen)
                return
            _add_allowed_file(
                root,
                allowed,
                referenced,
                expected_sha256=str(digest),
            )
            relative = _relative(root, referenced)
            if relative not in seen and referenced.suffix.lower() == ".json":
                seen.add(relative)
                try:
                    referenced_payload = json.loads(
                        referenced.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise _block("hash_bound_reference_invalid_json") from exc
                if not isinstance(referenced_payload, (Mapping, list)):
                    raise _block("hash_bound_reference_container_required")
                _collect_hash_bound_refs(
                    root,
                    allowed,
                    referenced_payload,
                    _seen=seen,
                )
        trust_path = value.get("trust_manifest_ref")
        trust_digest = value.get("trust_manifest_sha256")
        if isinstance(trust_path, str) and _is_sha256(trust_digest):
            referenced = _resolve_relative(root, trust_path)
            trust_manifest = _read_json(
                referenced,
                label="hash_bound_trust_manifest",
            )
            if (
                validate_public_trust_manifest(trust_manifest)
                or trust_manifest.get("manifest_sha256") != trust_digest
            ):
                raise _block("hash_bound_trust_manifest_invalid")
            # OOS receipts bind the signed manifest's semantic digest, not
            # the pretty-printed file-byte digest.  The OOS validator above
            # has already checked the signature and exact reference binding;
            # record the actual file digest for workspace-delta closure.
            _add_allowed_file(root, allowed, referenced)
        for child in value.values():
            _collect_hash_bound_refs(root, allowed, child, _seen=seen)
    elif isinstance(value, list):
        for child in value:
            _collect_hash_bound_refs(root, allowed, child, _seen=seen)


def is_evo_v2_external_pause(proof: Any) -> bool:
    return bool(
        isinstance(proof, Mapping)
        and str(proof.get("status") or "").upper() == "PAUSED"
        and str(proof.get("final_outcome") or "") in EVO_V2_EXTERNAL_PAUSES
    )


def _validate_pause_proof(
    proof: Mapping[str, Any],
    *,
    report_id: str,
) -> tuple[str, dict[str, Any]]:
    pause = str(proof.get("final_outcome") or "")
    contract = _PAUSE_CONTRACTS.get(pause)
    if contract is None:
        raise _block("unsupported_pause")
    gate = proof.get("evo_v2_execution_gate")
    terminal_pause = contract.get("terminal_closure_pause") is True
    closure_wait = proof.get("evo_v2_post_oos_terminal_closure")
    council = proof.get("revision_council")
    if (
        str(proof.get("status") or "").upper() != "PAUSED"
        or proof.get("report_id") != report_id
        or proof.get("failure") is not None
        or (
            proof.get("factor_verdict") != "NOT_ISSUED"
            if not terminal_pause
            else proof.get("factor_verdict") not in {None, "NOT_ISSUED"}
        )
        or proof.get("formal_proof_eligible") is not False
        or proof.get("proof_semantics") != contract["proof_semantics"]
        or not isinstance(gate, Mapping)
        or gate.get("enabled") is not True
        or gate.get("current_state") not in contract["paused_states"]
        or gate.get("action") not in contract["gate_actions"]
        or gate.get("oos_release_allowed")
        is not bool(contract.get("oos_release_allowed", False))
        or bool(gate.get("oos_artifacts"))
        or (
            terminal_pause
            and (
                not isinstance(closure_wait, Mapping)
                or closure_wait.get("verdict") != "AWAITING_HOST_SIGNATURE"
                or closure_wait.get("formal_factor_verdict") is not None
                or not isinstance(closure_wait.get("block_reasons"), list)
                or not closure_wait.get("block_reasons")
                or not isinstance(council, Mapping)
                or council.get("terminal_protocol_validated") is not False
            )
        )
    ):
        raise _block("pause_proof_binding")
    return pause, contract


def _lifecycle_prefix(
    lifecycle: Mapping[str, Any],
    generation: int,
) -> dict[str, Any]:
    events = lifecycle.get("events")
    if not isinstance(events, list) or generation < 1 or generation > len(events):
        raise _block("lifecycle_prefix_generation")
    prefix: dict[str, Any] = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": lifecycle.get("report_id"),
        "current_state": events[generation - 1].get("to_state"),
        "events": [dict(event) for event in events[:generation]],
        "host_authority": lifecycle.get("host_authority"),
    }
    prefix["content_sha256"] = stable_hash(prefix)
    return prefix


def _load_lifecycle_chain(
    *,
    root: Path,
    report_id: str,
    paused_states: set[str],
    attested_entries: Mapping[str, str] | None,
    allowed: dict[str, str],
    trust_manifest: Mapping[str, Any] | None = None,
    require_signed_host_receipts: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], int, Path]:
    lifecycle_path = epistemic_evolution_lifecycle_path(root, report_id)
    lifecycle = _read_json(lifecycle_path, label="lifecycle")
    reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        trust_manifest=trust_manifest,
        require_signed_host_receipts=require_signed_host_receipts,
    )
    if reasons:
        raise EvoV2ExternalResumeError(
            [f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:lifecycle:{reason}" for reason in reasons]
        )
    events = lifecycle.get("events")
    if not isinstance(events, list):
        raise _block("lifecycle_events")
    matches = [
        index + 1
        for index, event in enumerate(events)
        if isinstance(event, Mapping) and event.get("to_state") in paused_states
    ]
    if len(matches) != 1:
        raise _block("paused_lifecycle_state_not_unique")
    generation = matches[0]
    prefix = _lifecycle_prefix(lifecycle, generation)
    snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
        root, report_id, generation
    )
    snapshot = _read_json(snapshot_path, label="paused_lifecycle_snapshot")
    snapshot_reasons = validate_epistemic_evolution_lifecycle(
        snapshot,
        report_id=report_id,
        workspace_root=root,
        trust_manifest=trust_manifest,
        require_signed_host_receipts=require_signed_host_receipts,
    )
    if snapshot_reasons:
        raise EvoV2ExternalResumeError(
            [
                f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:paused_snapshot:{reason}"
                for reason in snapshot_reasons
            ]
        )
    if snapshot != prefix:
        raise _block("paused_lifecycle_snapshot_not_ancestor")
    snapshot_relative = _relative(root, snapshot_path)
    lifecycle_relative = _relative(root, lifecycle_path)
    snapshot_digest = sha256_file(snapshot_path)
    if attested_entries is not None:
        if (
            attested_entries.get(lifecycle_relative) != snapshot_digest
            or attested_entries.get(snapshot_relative) != snapshot_digest
        ):
            raise _block("attested_pause_not_bound_to_generation_snapshot")

    _add_allowed_file(root, allowed, lifecycle_path)
    current_generation = len(events)
    current_snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
        root, report_id, current_generation
    )
    current_snapshot = _read_json(
        current_snapshot_path, label="current_lifecycle_snapshot"
    )
    if current_snapshot != lifecycle or current_snapshot_path.read_bytes() != lifecycle_path.read_bytes():
        raise _block("current_lifecycle_snapshot_mismatch")
    for item_generation in range(generation + 1, current_generation + 1):
        item_path = epistemic_evolution_lifecycle_snapshot_path(
            root, report_id, item_generation
        )
        item = _read_json(item_path, label="lifecycle_snapshot")
        if item != _lifecycle_prefix(lifecycle, item_generation):
            raise _block("lifecycle_snapshot_chain_mismatch")
        _add_allowed_file(root, allowed, item_path)
    for event in events[generation:]:
        if not isinstance(event, Mapping):
            raise _block("lifecycle_event_shape")
        _collect_hash_bound_refs(root, allowed, event.get("actor_receipt_ref"))
        _collect_hash_bound_refs(root, allowed, event.get("evidence_refs"))
    _add_empty_lock_if_present(
        root, allowed, lifecycle_path.with_suffix(".lock")
    )
    return lifecycle, snapshot, generation, snapshot_path


def _staging(
    *,
    root: Path,
    report_id: str,
    allowed: dict[str, str],
    required: bool,
) -> dict[str, Any] | None:
    path = staging_manifest_path(root, report_id)
    if not path.exists() and not path.is_symlink():
        if required:
            raise _block("staging_manifest_missing")
        return None
    manifest = _read_json(path, label="staging_manifest")
    reasons = validate_evo_v2_staging_manifest(
        manifest,
        root=root,
        report_id=report_id,
        verify_readback=True,
    )
    if reasons:
        raise EvoV2ExternalResumeError(
            [f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:staging:{reason}" for reason in reasons]
        )
    lifecycle = _read_json(
        epistemic_evolution_lifecycle_path(root, report_id),
        label="staging_lifecycle_head",
    )
    lifecycle_events = lifecycle.get("events")
    if not isinstance(lifecycle_events, list):
        raise _block("staging_lifecycle_events")
    for index, event in enumerate(manifest.get("events") or []):
        binding = event.get("lifecycle_binding") if isinstance(event, Mapping) else None
        if not isinstance(binding, Mapping):
            raise _block(f"staging_lifecycle_binding:{index}")
        state = binding.get("current_state")
        generations = [
            generation
            for generation, lifecycle_event in enumerate(lifecycle_events, start=1)
            if isinstance(lifecycle_event, Mapping)
            and lifecycle_event.get("to_state") == state
        ]
        if len(generations) != 1:
            raise _block(f"staging_lifecycle_generation:{index}")
        snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
            root, report_id, generations[0]
        )
        snapshot = _read_json(snapshot_path, label="staging_lifecycle_snapshot")
        if (
            snapshot.get("content_sha256") != binding.get("content_sha256")
            or sha256_file(snapshot_path) != binding.get("sha256")
            or _relative(root, epistemic_evolution_lifecycle_path(root, report_id))
            != binding.get("path")
        ):
            raise _block(f"staging_lifecycle_snapshot_binding:{index}")
        _add_allowed_file(root, allowed, snapshot_path)
    _add_allowed_file(root, allowed, path)
    _collect_hash_bound_refs(root, allowed, manifest)
    _add_empty_lock_if_present(root, allowed, path.parent / ".staging.lock")
    return manifest


def _validate_feedback(root: Path, report_id: str) -> None:
    path = evo_v2_paths(root, report_id)["feedback_ledger"]
    feedback = load_json_object(path)
    reasons = validate_feedback_ledger(
        feedback,
        workspace_root=root,
        verify_refs=True,
    )
    if reasons:
        raise EvoV2ExternalResumeError(
            [f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:feedback:{reason}" for reason in reasons]
        )


def _require_stage_sequence(
    manifest: Mapping[str, Any] | None,
    expected: Sequence[str],
) -> int:
    events = manifest.get("events") if isinstance(manifest, Mapping) else []
    if not isinstance(events, list):
        raise _block("staging_events")
    observed = [
        str(event.get("stage") or "") if isinstance(event, Mapping) else ""
        for event in events
    ]
    if observed != list(expected):
        raise _block("staging_exact_sequence")
    return len(events)


def _validate_outcome_materialization(
    *,
    root: Path,
    report_id: str,
    outcome: str,
) -> None:
    report, reasons = validate_materialized_pre_oos_council_outcome(
        workspace_root=root,
        report_id=report_id,
        expected_transition_state=outcome,
    )
    if report is None or reasons:
        raise EvoV2ExternalResumeError(
            [
                f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:pre_oos_outcome:{reason}"
                for reason in reasons
            ]
            or [f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:pre_oos_outcome_missing"]
        )


def _validate_complete_transfer(root: Path, report_id: str) -> None:
    artifacts, reasons = validate_materialized_evo_v2(root, report_id)
    if reasons:
        raise EvoV2ExternalResumeError(
            [f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:evo_bundle:{reason}" for reason in reasons]
        )
    if not isinstance(artifacts, Mapping):
        raise _block("evo_bundle_missing")


def _validate_external_child_trust_anchors(
    *,
    root: Path,
    attested_entries: Mapping[str, str] | None,
    trust_root: Path | None,
    installation_id: str | None,
    allowed: dict[str, str],
) -> None:
    """Bind human and fresh-OOS signatures to authorities fixed before approval."""

    if attested_entries is None:
        raise _block("external_child_attested_tree_required")
    human_path = human_approval_trust_path(root)
    human_relative = _relative(root, human_path)
    human_digest = attested_entries.get(human_relative)
    if not _is_sha256(human_digest):
        raise _block("human_trust_not_attested_before_external_approval")
    _add_allowed_file(
        root,
        allowed,
        human_path,
        expected_sha256=str(human_digest),
    )

    if (
        trust_root is None
        or not isinstance(installation_id, str)
        or not installation_id
    ):
        raise _block("oos_host_trust_anchor_required")
    try:
        expected_manifest = load_runtime_trust_store(
            Path(trust_root),
            installation_id=installation_id,
        ).public_manifest
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        raise _block(f"oos_host_trust_anchor_invalid:{exc}") from exc
    oos_trust_path = oos_host_trust_manifest_path(root)
    observed_manifest = _read_json(
        oos_trust_path,
        label="oos_host_trust_manifest",
    )
    if observed_manifest != expected_manifest:
        raise _block("oos_host_trust_not_console_host")
    _add_allowed_file(root, allowed, oos_trust_path)


def _validate_formal_transfer_use_orchestration(
    *,
    root: Path,
    report_id: str,
    lifecycle: Mapping[str, Any],
    manifest: Mapping[str, Any],
    trust_root: Path | None,
    installation_id: str | None,
    admissions_root: Path | None,
    allowed: dict[str, str],
) -> dict[str, Any]:
    """Require the signed Host orchestration, not merely its four low-level writes."""

    if trust_root is None or not isinstance(installation_id, str) or not installation_id:
        raise _block("formal_transfer_use_host_trust_required")
    lifecycle_events = lifecycle.get("events")
    if not isinstance(lifecycle_events, list):
        raise _block("formal_transfer_use_lifecycle_events")
    minimal_generations = [
        index + 1
        for index, event in enumerate(lifecycle_events)
        if isinstance(event, Mapping)
        and event.get("to_state") == "MINIMAL_MECHANISM_DELTA"
    ]
    if len(minimal_generations) != 1:
        raise _block("formal_transfer_use_minimal_generation")
    minimal_lifecycle = _lifecycle_prefix(
        lifecycle,
        minimal_generations[0],
    )
    staging_events = manifest.get("events")
    if not isinstance(staging_events, list) or len(staging_events) < 2:
        raise _block("formal_transfer_use_staging_prefix")
    minimal_staging = {
        "contract_version": manifest.get("contract_version"),
        "report_id": report_id,
        "host_authority": manifest.get("host_authority"),
        "events": [dict(event) for event in staging_events[:2]],
    }
    try:
        effective_admissions_root = (
            Path(admissions_root)
            if lifecycle.get("current_state") == "TRANSFER_RECORDED"
            and admissions_root is not None
            else None
        )
        validation = validate_evo_v2_transfer_use_orchestration(
            workspace_root=root,
            report_id=report_id,
            expected_minimal_lifecycle_sha256=stable_hash(minimal_lifecycle),
            expected_staging_content_sha256=stable_hash(minimal_staging),
            trust_root=Path(trust_root),
            installation_id=installation_id,
            admissions_root=effective_admissions_root,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _block(f"formal_transfer_use_orchestration:{exc}") from exc

    current_state = str(lifecycle.get("current_state") or "")
    expected_memory_state = {
        "TRANSFER_RECORDED": "ADMISSIBLE_MEMORY_FOUND",
        "COLD_START_RECORDED": "COLD_START_NO_ADMISSIBLE_MEMORY",
    }.get(current_state)
    orchestration_path = transfer_use_orchestration_path(root, report_id)
    orchestration = _read_json(
        orchestration_path,
        label="formal_transfer_use_orchestration",
    )
    orchestration_ref = validation.get("orchestration_ref")
    authority = validation.get("authority")
    if (
        validation.get("verdict") != "PASS"
        or validation.get("status") != "IDEMPOTENT_VERIFIED"
        or validation.get("report_id") != report_id
        or validation.get("memory_state") != expected_memory_state
        or validation.get("lifecycle_state") != current_state
        or validation.get("staging_event_count") != 4
        or not isinstance(orchestration_ref, Mapping)
        or orchestration_ref.get("path") != _relative(root, orchestration_path)
        or orchestration_ref.get("sha256") != sha256_file(orchestration_path)
        or orchestration_ref.get("content_sha256")
        != orchestration.get("content_sha256")
        or not isinstance(authority, Mapping)
        or authority.get("four_stage_events_exact_readback") is not True
        or authority.get("transfer_test_execution_completed") is not False
        or authority.get("human_approval_granted") is not False
        or authority.get("oos_accessed") is not False
        or authority.get("child_execution_allowed") is not False
        or authority.get("factor_verdict") != "NOT_ISSUED"
        or authority.get("canonical_memory_write_allowed") is not False
        or authority.get("canonical_factor_write_allowed") is not False
        or authority.get("skill_or_policy_mutation_allowed") is not False
    ):
        raise _block("formal_transfer_use_orchestration_projection")

    gate_evidence = orchestration.get("gate_evidence")
    if not isinstance(gate_evidence, Mapping):
        raise _block("formal_transfer_use_gate_evidence")
    addendum_path: Path | None = None
    addendum: dict[str, Any] | None = None
    addendum_ref: Mapping[str, Any] | None = None
    if expected_memory_state == "ADMISSIBLE_MEMORY_FOUND":
        addendum_path = execution_addendum_path(root, report_id)
        addendum = _read_json(
            addendum_path,
            label="formal_transfer_use_execution_addendum",
        )
        candidate_addendum_ref = gate_evidence.get("execution_addendum_ref")
        addendum_ref = (
            candidate_addendum_ref
            if isinstance(candidate_addendum_ref, Mapping)
            else None
        )
        binding = addendum.get("execution_binding")
        addendum_authority = addendum.get("authority")
        if (
            authority.get("preregistered_transfer_tests_bound") is not True
            or authority.get("cold_start_zero_hit_verified") is not False
            or authority.get("transfer_execution_state")
            != "PREREGISTERED_AND_BOUND_NOT_EXECUTED"
            or addendum_ref is None
            or addendum_ref.get("path") != _relative(root, addendum_path)
            or addendum_ref.get("sha256") != sha256_file(addendum_path)
            or addendum_ref.get("content_sha256")
            != addendum.get("content_sha256")
            or gate_evidence.get("execution_addendum_status") != ADDENDUM_STATUS
            or addendum.get("status") != ADDENDUM_STATUS
            or not isinstance(binding, Mapping)
            or binding.get("state") != REGISTERED_STATUS
            or binding.get("execution_completed") is not False
            or not isinstance(addendum_authority, Mapping)
            or addendum_authority.get("execution_completed") is not False
        ):
            raise _block("formal_transfer_use_execution_addendum_projection")
    elif (
        authority.get("preregistered_transfer_tests_bound") is not False
        or authority.get("cold_start_zero_hit_verified") is not True
        or authority.get("transfer_execution_state") != "NOT_APPLICABLE_COLD_START"
        or gate_evidence.get("execution_addendum_ref") is not None
        or gate_evidence.get("execution_addendum_status") is not None
        or execution_addendum_path(root, report_id).exists()
        or execution_addendum_path(root, report_id).is_symlink()
    ):
        raise _block("formal_cold_start_zero_hit_projection")

    _add_allowed_file(root, allowed, orchestration_path)
    _collect_hash_bound_refs(root, allowed, orchestration)
    _add_empty_lock_if_present(
        root,
        allowed,
        orchestration_path.parent / ".transfer_use_orchestration.lock",
    )
    if addendum_path is not None and addendum is not None:
        _add_allowed_file(root, allowed, addendum_path)
        _collect_hash_bound_refs(root, allowed, addendum)
        _add_empty_lock_if_present(
            root,
            allowed,
            addendum_path.with_suffix(".lock"),
        )
    return {
        "orchestration_path": _relative(root, orchestration_path),
        "orchestration_sha256": sha256_file(orchestration_path),
        "orchestration_content_sha256": str(
            orchestration.get("content_sha256") or ""
        ),
        "orchestration_ref": dict(orchestration_ref),
        "memory_state": expected_memory_state,
        "execution_addendum_ref": (
            dict(addendum_ref) if addendum_ref is not None else None
        ),
        "execution_addendum_path": (
            _relative(root, addendum_path) if addendum_path is not None else None
        ),
        "execution_addendum_sha256": (
            sha256_file(addendum_path) if addendum_path is not None else None
        ),
        "execution_addendum_status": (
            str(addendum.get("status") or "") if addendum is not None else None
        ),
        "execution_addendum_state": (
            str(addendum.get("execution_binding", {}).get("state") or "")
            if addendum is not None
            else None
        ),
        "transfer_test_execution_completed": False,
    }


def _validate_workspace_delta(
    *,
    root: Path,
    attested_entries: Mapping[str, str] | None,
    allowed: Mapping[str, str],
) -> None:
    if attested_entries is None:
        return
    if not all(isinstance(path, str) and _is_sha256(digest) for path, digest in attested_entries.items()):
        raise _block("attested_evidence_tree_shape")
    current = _workspace_tree(root)
    changed = {
        path
        for path in set(attested_entries) | set(current)
        if attested_entries.get(path) != current.get(path)
    }
    unexpected = sorted(changed - set(allowed))
    if unexpected:
        raise _block("untrusted_workspace_delta:" + ",".join(unexpected[:12]))
    for path in changed:
        if current.get(path) != allowed.get(path):
            raise _block(f"allowed_workspace_delta_changed:{path}")


def assess_evo_v2_external_resume(
    *,
    workspace_root: Path,
    report_id: str,
    proof: Mapping[str, Any],
    attested_entries: Mapping[str, str] | None = None,
    trust_root: Path | None = None,
    installation_id: str | None = None,
    admissions_root: Path | None = None,
    trusted_lifecycle_manifest: Mapping[str, Any] | None = None,
    require_signed_lifecycle_genesis: bool = True,
) -> EvoV2ExternalResumeAssessment:
    """Replay one EVO external pause without granting external actors runner authority.

    The prior proof is anchored to the immutable lifecycle generation that was
    current when the Host attested it.  A mutable ``lifecycle.json`` is never
    accepted as that historical anchor.  Only validator-explained, hash-bound
    workspace deltas may appear after the attestation.
    """

    root = workspace_root.expanduser().resolve(strict=True)
    pause, contract = _validate_pause_proof(proof, report_id=report_id)
    allowed: dict[str, str] = {}
    lifecycle, paused_snapshot, paused_generation, paused_snapshot_path = (
        _load_lifecycle_chain(
            root=root,
            report_id=report_id,
            paused_states=set(contract["paused_states"]),
            attested_entries=attested_entries,
            allowed=allowed,
            trust_manifest=trusted_lifecycle_manifest,
            require_signed_host_receipts=require_signed_lifecycle_genesis,
        )
    )
    events = lifecycle["events"]
    current_state = str(lifecycle.get("current_state") or "")
    current_generation = len(events)
    paused_state = str(paused_snapshot.get("current_state") or "")
    gate = proof.get("evo_v2_execution_gate")
    if not isinstance(gate, Mapping) or gate.get("current_state") != paused_state:
        raise _block("pause_gate_lifecycle_state_mismatch")
    generation_delta = current_generation - paused_generation
    if generation_delta < 0 or generation_delta > 1:
        raise _block("lifecycle_state_jump")
    if generation_delta == 0 and current_state != paused_state:
        raise _block("lifecycle_generation_state_mismatch")
    if generation_delta == 1 and current_state not in contract["next_states"]:
        raise _block("lifecycle_transition_not_authorized_for_pause")

    staging_required = int(contract["baseline_stage_count"]) > 0
    if pause == PAUSE_AWAIT_HOST_QUALIFICATION and current_state == "QUALIFIED_CONTRADICTION":
        staging_required = False
    manifest = _staging(
        root=root,
        report_id=report_id,
        allowed=allowed,
        required=staging_required,
    )
    staging_events = (
        list(manifest.get("events") or []) if isinstance(manifest, Mapping) else []
    )
    staging_count = len(staging_events)
    child_report_id: str | None = None
    terminal_factor_verdict: str | None = None
    terminal_decision: str | None = None
    terminal_path_relative: str | None = None
    terminal_sha256: str | None = None
    formal_transfer: dict[str, Any] | None = None
    status = PROGRESS_WAITING
    reason = "external_host_action_not_completed"

    if pause == PAUSE_AWAIT_NQC_TERMINAL_CLOSURE:
        if generation_delta != 0:
            raise _block("terminal_closure_cannot_advance_lifecycle")
        if manifest is not None:
            raise _block("terminal_closure_has_evo_staging")
        closure_path = terminal_closure_path(root, report_id)
        if closure_path.exists() or closure_path.is_symlink():
            validation = validate_evo_post_oos_terminal_closure(
                workspace_root=root,
                report_id=report_id,
                trust_root=trust_root,
                installation_id=installation_id,
            )
            if (
                validation.get("verdict") != "PASS"
                or validation.get("report_id") != report_id
                or validation.get("formal_factor_verdict")
                not in {"ACCEPT", "REJECT"}
                or validation.get("terminal_decision")
                not in {"promote_official", "reject"}
                or validation.get("closure_path")
                != _relative(root, closure_path)
                or validation.get("closure_sha256")
                != sha256_file(closure_path)
                or validation.get("block_reasons")
            ):
                reasons = validation.get("block_reasons")
                raise EvoV2ExternalResumeError(
                    [
                        f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:terminal_closure:{item}"
                        for item in (
                            reasons if isinstance(reasons, list) else []
                        )
                    ]
                    or [
                        f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:terminal_closure_invalid"
                    ]
                )
            closure = _read_json(
                closure_path,
                label="evo_v2_terminal_closure",
            )
            authority = closure.get("authority_guard")
            if (
                not isinstance(authority, Mapping)
                or not authority
                or any(value is not False for value in authority.values())
            ):
                raise _block("terminal_closure_authority_guard")
            terminal_factor_verdict = str(
                validation["formal_factor_verdict"]
            )
            terminal_decision = str(validation["terminal_decision"])
            if terminal_decision != {
                "ACCEPT": "promote_official",
                "REJECT": "reject",
            }[terminal_factor_verdict]:
                raise _block("terminal_closure_verdict_decision_mismatch")
            _add_allowed_file(root, allowed, closure_path)
            _collect_hash_bound_refs(root, allowed, closure)
            _add_empty_lock_if_present(
                root,
                allowed,
                closure_path.with_suffix(closure_path.suffix + ".lock"),
            )
            terminal_path_relative = _relative(root, closure_path)
            terminal_sha256 = sha256_file(closure_path)
            status = PROGRESS_TERMINAL_CHECKPOINT_READY
            reason = "signed_non_revision_terminal_closure_verified"
        else:
            reason = "non_revision_terminal_closure_waiting_host_signature"

    elif pause == PAUSE_AWAIT_HOST_QUALIFICATION:
        if generation_delta == 0:
            if manifest is not None:
                raise _block("qualification_staging_precedes_host_transition")
        elif current_state == "NO_QUALIFIED_CONTRADICTION":
            if manifest is not None:
                raise _block("no_contradiction_branch_has_staging")
            status = PROGRESS_HOST_CHECKPOINT_READY
            reason = "signed_no_qualified_contradiction_transition_verified"
        else:
            if manifest is None:
                reason = "qualified_transition_waiting_feedback_staging"
            else:
                _require_stage_sequence(manifest, [STAGE_ADMIT_FEEDBACK])
                _validate_feedback(root, report_id)
                status = PROGRESS_HOST_CHECKPOINT_READY
                reason = "signed_qualified_contradiction_and_feedback_stage_verified"

    elif pause == PAUSE_AWAIT_HOST_COUNCIL_OUTCOME:
        if generation_delta == 0:
            _require_stage_sequence(manifest, [STAGE_ADMIT_FEEDBACK])
            _validate_feedback(root, report_id)
        else:
            expected_sequence = [STAGE_ADMIT_FEEDBACK, STAGE_ADMIT_COUNCIL_OUTCOME]
            if staging_count == 1:
                _require_stage_sequence(manifest, expected_sequence[:1])
                reason = "signed_outcome_transition_waiting_council_staging"
            elif staging_count == 2:
                _require_stage_sequence(manifest, expected_sequence)
                _validate_outcome_materialization(
                    root=root,
                    report_id=report_id,
                    outcome=current_state,
                )
                status = PROGRESS_HOST_CHECKPOINT_READY
                reason = "signed_council_outcome_transition_and_staging_verified"
            else:
                raise _block("council_outcome_stage_count")

    elif pause == PAUSE_AWAIT_TRANSFER_USE:
        _validate_outcome_materialization(
            root=root,
            report_id=report_id,
            outcome="MINIMAL_MECHANISM_DELTA",
        )
        if generation_delta == 0:
            _require_stage_sequence(
                manifest, [STAGE_ADMIT_FEEDBACK, STAGE_ADMIT_COUNCIL_OUTCOME]
            )
        else:
            exact = [
                STAGE_ADMIT_FEEDBACK,
                STAGE_ADMIT_COUNCIL_OUTCOME,
                STAGE_ADMIT_TRANSFER,
                STAGE_RECORD_USE,
            ]
            if staging_count not in {2, 3, 4}:
                raise _block("transfer_use_stage_count")
            _require_stage_sequence(manifest, exact[:staging_count])
            if staging_count == 4:
                _validate_complete_transfer(root, report_id)
                formal_transfer = _validate_formal_transfer_use_orchestration(
                    root=root,
                    report_id=report_id,
                    lifecycle=lifecycle,
                    manifest=manifest,
                    trust_root=trust_root,
                    installation_id=installation_id,
                    admissions_root=(
                        admissions_root
                        if current_state == "TRANSFER_RECORDED"
                        else None
                    ),
                    allowed=allowed,
                )
                status = PROGRESS_HOST_CHECKPOINT_READY
                reason = "signed_formal_transfer_use_orchestration_verified"
            else:
                reason = "signed_transfer_transition_waiting_exact_use_staging"

    else:
        if generation_delta != 0:
            raise _block("external_approval_cannot_advance_parent_lifecycle")
        _require_stage_sequence(
            manifest,
            [
                STAGE_ADMIT_FEEDBACK,
                STAGE_ADMIT_COUNCIL_OUTCOME,
                STAGE_ADMIT_TRANSFER,
                STAGE_RECORD_USE,
            ],
        )
        _validate_complete_transfer(root, report_id)
        formal_transfer = _validate_formal_transfer_use_orchestration(
            root=root,
            report_id=report_id,
            lifecycle=lifecycle,
            manifest=manifest,
            trust_root=trust_root,
            installation_id=installation_id,
            admissions_root=(
                admissions_root
                if current_state == "TRANSFER_RECORDED"
                else None
            ),
            allowed=allowed,
        )
        handoff_path = pre_oos_child_handoff_path(root, report_id)
        if handoff_path.exists() or handoff_path.is_symlink():
            _validate_external_child_trust_anchors(
                root=root,
                attested_entries=attested_entries,
                trust_root=trust_root,
                installation_id=installation_id,
                allowed=allowed,
            )
            handoff, reasons = validate_pre_oos_child_handoff(
                workspace_root=root,
                parent_report_id=report_id,
                # This assessment is the production entry into Agent child
                # authoring/preregistration. Requiring READY here is circular:
                # READY can only be Host-signed after that preregistration.
                require_materialization_ready=False,
                host_trust_root=trust_root,
                installation_id=installation_id,
                incident_trust_root=trust_root,
                incident_installation_id=installation_id,
                admissions_root=(
                    admissions_root
                    if current_state == "TRANSFER_RECORDED"
                    else None
                ),
            )
            if handoff is None or reasons:
                raise EvoV2ExternalResumeError(
                    [
                        f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:child_handoff:{item}"
                        for item in reasons
                    ]
                    or [f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:child_handoff_invalid"]
                )
            child_report_id = str(handoff.get("child_report_id") or "")
            if not child_report_id or child_report_id == report_id:
                raise _block("child_report_identity")
            if (
                handoff.get("formal_transfer_use_orchestration_ref")
                != formal_transfer.get("orchestration_ref")
                or handoff.get("execution_addendum_ref")
                != formal_transfer.get("execution_addendum_ref")
            ):
                raise _block("child_handoff_formal_transfer_binding")
            expected_host_pin = load_runtime_trust_store(
                Path(trust_root),
                installation_id=str(installation_id),
            ).public_manifest["manifest_sha256"]
            authorization_path = public_child_materialization_ticket_path(
                root,
                child_report_id,
                materialization_ready=False,
            )
            authorization, authorization_reasons = (
                validate_public_child_materialization_ticket(
                    workspace_root=root,
                    parent_report_id=report_id,
                    child_report_id=child_report_id,
                    require_materialization_ready=False,
                    exact_ticket_path=authorization_path,
                    handoff=handoff,
                    expected_host_trust_manifest_sha256=expected_host_pin,
                )
            )
            if authorization is None or authorization_reasons:
                raise EvoV2ExternalResumeError(
                    [
                        f"{BLOCK_EVO_V2_EXTERNAL_RESUME}:child_authorization:{item}"
                        for item in authorization_reasons
                    ]
                    or [_block("child_authorization_missing").reasons[0]]
                )
            approval_path = pre_oos_human_approval_path(root, report_id)
            intent_path = pre_oos_child_intent_path(root, child_report_id)
            for path in (
                approval_path,
                handoff_path,
                intent_path,
                authorization_path,
                public_child_materialization_trust_manifest_path(root),
            ):
                _add_allowed_file(root, allowed, path)
                _collect_hash_bound_refs(
                    root,
                    allowed,
                    _read_json(path, label="pre_oos_child_bridge"),
                )
            _add_allowed_file(root, allowed, oos_registry_path(root))
            _add_empty_lock_if_present(
                root, allowed, approval_path.with_suffix(".lock")
            )
            _add_empty_lock_if_present(
                root, allowed, authorization_path.with_suffix(".lock")
            )
            registry_lock = (
                root
                / "objects"
                / "research_protocol"
                / "evo_oos_allocation_registry.json.lock"
            )
            _add_empty_lock_if_present(root, allowed, registry_lock)
            status = PROGRESS_CHILD_HANDOFF_AUTHORIZED
            reason = (
                "external_human_signature_fresh_child_oos_and_public_"
                "authorization_ticket_verified"
            )
        else:
            reason = "external_human_approval_and_fresh_child_not_completed"

    # Every admitted EVO artifact is already an exact path/hash-bound output
    # (or prior-artifact) reference in the validated staging chain.  Following
    # only that closed reference graph avoids blessing an unstaged sibling file
    # merely because it happens to have a canonical EVO filename.
    _add_empty_lock_if_present(
        root,
        allowed,
        evo_v2_paths(root, report_id)["feedback_ledger"].parent
        / ".pre_oos_outcome_orchestration.lock",
    )

    _validate_workspace_delta(
        root=root,
        attested_entries=attested_entries,
        allowed=allowed,
    )
    return EvoV2ExternalResumeAssessment(
        report_id=report_id,
        pause_outcome=pause,
        status=status,
        start_step=("6" if status == PROGRESS_HOST_CHECKPOINT_READY else None),
        paused_lifecycle_state=paused_state,
        paused_lifecycle_generation=paused_generation,
        paused_lifecycle_snapshot_path=_relative(root, paused_snapshot_path),
        paused_lifecycle_snapshot_sha256=sha256_file(paused_snapshot_path),
        current_lifecycle_state=current_state,
        current_lifecycle_generation=current_generation,
        current_lifecycle_sha256=sha256_file(
            epistemic_evolution_lifecycle_path(root, report_id)
        ),
        staging_event_count=staging_count,
        child_report_id=child_report_id,
        terminal_factor_verdict=terminal_factor_verdict,
        terminal_decision=terminal_decision,
        terminal_closure_path=terminal_path_relative,
        terminal_closure_sha256=terminal_sha256,
        transfer_use_orchestration_path=(
            formal_transfer.get("orchestration_path")
            if formal_transfer is not None
            else None
        ),
        transfer_use_orchestration_sha256=(
            formal_transfer.get("orchestration_sha256")
            if formal_transfer is not None
            else None
        ),
        transfer_use_orchestration_content_sha256=(
            formal_transfer.get("orchestration_content_sha256")
            if formal_transfer is not None
            else None
        ),
        transfer_memory_state=(
            formal_transfer.get("memory_state")
            if formal_transfer is not None
            else None
        ),
        execution_addendum_path=(
            formal_transfer.get("execution_addendum_path")
            if formal_transfer is not None
            else None
        ),
        execution_addendum_sha256=(
            formal_transfer.get("execution_addendum_sha256")
            if formal_transfer is not None
            else None
        ),
        execution_addendum_status=(
            formal_transfer.get("execution_addendum_status")
            if formal_transfer is not None
            else None
        ),
        execution_addendum_state=(
            formal_transfer.get("execution_addendum_state")
            if formal_transfer is not None
            else None
        ),
        transfer_test_execution_completed=(
            formal_transfer.get("transfer_test_execution_completed")
            if formal_transfer is not None
            else None
        ),
        reason=reason,
    )


__all__ = [
    "BLOCK_EVO_V2_EXTERNAL_RESUME",
    "EVO_V2_EXTERNAL_PAUSES",
    "EvoV2ExternalResumeAssessment",
    "EvoV2ExternalResumeError",
    "PAUSE_AWAIT_EXTERNAL_CHILD",
    "PAUSE_AWAIT_HOST_COUNCIL_OUTCOME",
    "PAUSE_AWAIT_HOST_QUALIFICATION",
    "PAUSE_AWAIT_NQC_TERMINAL_CLOSURE",
    "PAUSE_AWAIT_TRANSFER_USE",
    "PROGRESS_CHILD_HANDOFF_READY",
    "PROGRESS_CHILD_HANDOFF_AUTHORIZED",
    "PROGRESS_HOST_CHECKPOINT_READY",
    "PROGRESS_TERMINAL_CHECKPOINT_READY",
    "PROGRESS_WAITING",
    "assess_evo_v2_external_resume",
    "is_evo_v2_external_pause",
]
