from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from factor_factory.evo_v2 import (
    EvoV2Error,
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_paths,
    evo_v2_relative_paths,
    sha256_file,
    stable_json_hash,
    validate_feedback_ledger,
)
from factor_factory.measurement_program import (
    stable_measurement_program_hash,
    validate_measurement_program,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_enabled,
    epistemic_evolution_lifecycle_snapshot_path,
    research_protocol_paths,
    validate_epistemic_evolution_lifecycle,
    validate_research_conjecture,
)


EVO_PACKET_CONTEXT_VERSION = (
    "factorforge_revision_council_evo_v2_packet_context_v1"
)
EVO_TASK_IDENTITY_VERSION = (
    "factorforge_revision_council_evo_v2_task_identity_v1"
)
PURGED_IS_EVIDENCE_VIEW = "PURGED_IS_ONLY"

BLOCK_PACKET = "BLOCK_COUNCIL_EVO_V2_FORMAL_PACKET_INVALID"
BLOCK_LIFECYCLE = "BLOCK_COUNCIL_EVO_V2_LIFECYCLE_NOT_QUALIFIED"
BLOCK_FEEDBACK = "BLOCK_COUNCIL_EVO_V2_CANONICAL_FEEDBACK_INVALID"
BLOCK_OOS = "BLOCK_COUNCIL_EVO_V2_CONSUMED_OOS_PRESENT"
BLOCK_EVIDENCE_VIEW = "BLOCK_COUNCIL_EVO_V2_EVIDENCE_VIEW_INVALID"
BLOCK_TASK_IDENTITY = "BLOCK_COUNCIL_EVO_V2_TASK_IDENTITY_INVALID"
BLOCK_RESULT_IDENTITY = "BLOCK_COUNCIL_EVO_V2_RESULT_TASK_IDENTITY_MISMATCH"

_REDACTED_MEMORY = {
    "contract_version": "factorforge_revision_council_purged_is_redaction_v1",
    "required_for_next_council": False,
    "withheld_reason": "EVO_V2_PURGED_IS_ONLY",
}
_OOS_REF_MARKERS = (
    "oos",
    "holdout",
    "factor_evaluation",
    "factor_proof",
    "release_manifest",
)


class CouncilEvoProductionError(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = list(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _relative(root: Path, path: Path) -> str:
    return path.resolve(strict=True).relative_to(root).as_posix()


def _ref(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    resolved.relative_to(root)
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"regular file required: {path}")
    return {"path": _relative(root, resolved), "sha256": sha256_file(resolved)}


def _frozen_measurement_program(
    *,
    root: Path,
    feedback: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Load the exact program frozen by the qualified feedback ledger.

    Council must never re-read a mutable copy from ``factor_spec`` after Host
    qualification.  The feedback reference is the sole program authority for
    this evidence view; both file bytes and the semantic program contract are
    replayed here.
    """

    frozen = feedback.get("frozen_authority")
    frozen = frozen if isinstance(frozen, Mapping) else {}
    reference = frozen.get("measurement_program_ref")
    if not isinstance(reference, Mapping):
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:measurement_program_ref"])
    raw_path = reference.get("path")
    expected_sha = reference.get("sha256")
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:measurement_program_ref"])
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:measurement_program_ref"])
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:measurement_program_ref"] ) from exc
    if (
        not candidate.is_file()
        or candidate.is_symlink()
        or sha256_file(candidate) != expected_sha
    ):
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:measurement_program_ref"])
    try:
        payload = _load_json(candidate)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CouncilEvoProductionError(
            [f"{BLOCK_FEEDBACK}:measurement_program_unreadable"]
        ) from exc
    failures = validate_measurement_program(
        payload,
        available_knowledge_node_ids={
            str(node_id)
            for component in ((payload.get("implementation") or {}).get("components") or [])
            if isinstance(component, Mapping)
            for node_id in (component.get("knowledge_node_ids") or [])
            if str(node_id).strip()
        },
        require_web_executable=False,
    )
    if failures:
        raise CouncilEvoProductionError(
            [f"{BLOCK_FEEDBACK}:measurement_program:{reason}" for reason in failures]
        )
    return payload, {"path": _relative(root, candidate), "sha256": sha256_file(candidate)}


def _released_oos_paths(root: Path, report_id: str) -> list[str]:
    protocol = root / "objects" / "research_protocol"
    release = protocol / f"oos_release_manifest__{report_id}.json"
    proof = research_protocol_paths(root, report_id)["factor_proof"]
    released: list[str] = []
    if release.is_file():
        try:
            payload = _load_json(release)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            released.append(str(release))
        else:
            if payload.get("release_status") == "RELEASED":
                released.append(str(release))
    if proof.is_file():
        released.append(str(proof))
    return released


def _visible_feedback_evidence(feedback: Mapping[str, Any]) -> list[dict[str, Any]]:
    contradiction = feedback.get("contradiction")
    contradiction = contradiction if isinstance(contradiction, Mapping) else {}
    observed = contradiction.get("observed_signature")
    observed = observed if isinstance(observed, Mapping) else {}
    refs: list[dict[str, Any]] = []
    for raw in [
        *(contradiction.get("evidence_refs") or []),
        *(observed.get("evidence_refs") or []),
    ]:
        if not isinstance(raw, dict):
            continue
        if raw not in refs:
            refs.append(copy.deepcopy(raw))
    return refs


def _all_feedback_evidence(feedback: Mapping[str, Any]) -> list[dict[str, Any]]:
    refs = _visible_feedback_evidence(feedback)
    for history in feedback.get("state_history") or []:
        if isinstance(history, Mapping):
            candidates = history.get("evidence_refs") or []
            for reference in candidates:
                if isinstance(reference, dict) and reference not in refs:
                    refs.append(copy.deepcopy(reference))
    # Prediction preregistration and the frozen OOS-policy reference are policy
    # inputs, not result evidence.  They remain legal while the holdout is
    # sealed; only transition/contradiction/clearance evidence is screened here.
    for clearance in feedback.get("lower_layer_clearance") or []:
        if isinstance(clearance, Mapping):
            candidates = clearance.get("evidence_refs") or []
            for reference in candidates:
                if isinstance(reference, dict) and reference not in refs:
                    refs.append(copy.deepcopy(reference))
    return refs


def _oos_reference_reasons(refs: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(refs, list) or not refs:
        return [f"{BLOCK_EVIDENCE_VIEW}:visible_evidence_refs"]
    for index, reference in enumerate(refs):
        if not isinstance(reference, dict):
            reasons.append(f"{BLOCK_EVIDENCE_VIEW}:evidence_ref:{index}")
            continue
        path = str(reference.get("path") or "").lower()
        if any(marker in path for marker in _OOS_REF_MARKERS):
            reasons.append(f"{BLOCK_OOS}:evidence_ref:{index}")
    return reasons


def qualified_is_metric_projection(feedback: Mapping[str, Any]) -> dict[str, Any]:
    contradiction = feedback.get("contradiction")
    contradiction = contradiction if isinstance(contradiction, Mapping) else {}
    observed = contradiction.get("observed_signature")
    observed = observed if isinstance(observed, Mapping) else {}
    return {
        "evidence_view": PURGED_IS_EVIDENCE_VIEW,
        "contradiction_id": contradiction.get("contradiction_id"),
        "metric_id": observed.get("metric_id"),
        "direction": observed.get("direction"),
        "shape": observed.get("shape"),
        "horizon": observed.get("horizon"),
        "conditioning_set": copy.deepcopy(observed.get("conditioning_set") or []),
        "materiality_assessment": contradiction.get("materiality_assessment"),
    }


def formal_packet_redactions(feedback: Mapping[str, Any]) -> dict[str, Any]:
    """Return the only result-bearing context allowed in an EVO Council packet."""

    return {
        "metrics": qualified_is_metric_projection(feedback),
        "chart_evidence": {},
        "research_memo": {},
        "loop_research_brief": {},
        "prior_revision_memory": copy.deepcopy(_REDACTED_MEMORY),
        "sibling_branch_memory": copy.deepcopy(_REDACTED_MEMORY),
        "main_agent_mechanism_memo_ref": None,
        "main_agent_formula_component_map": [],
        "main_agent_math_hypothesis": {},
        "main_agent_evidence_comparison": {},
        "formula_specific_derivation": {},
        "mechanism_formula_consistency": {},
        "program_search_policy": {},
        "supplemental_research_context": {
            "contract_version": "factorforge_revision_council_supplemental_context_v1",
            "lookup_tokens": [],
            "item_count": 0,
            "items": [],
            "withheld_reason": "EVO_V2_PURGED_IS_ONLY",
        },
    }


def load_formal_evo_packet_context(
    workspace_root: Path | str,
    report_id: str,
    *,
    bound_context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Load a formal Council intake, or ``(None, None)`` for a legacy report.

    EVO-enabled reports never downgrade to the legacy Council path.  They must
    be at the Host-derived qualified state, expose the canonical feedback file,
    and still have an unreleased OOS.
    """

    root = Path(workspace_root).expanduser().resolve(strict=True)
    paths = research_protocol_paths(root, report_id)
    conjecture_path = paths["conjecture"]
    if not conjecture_path.is_file():
        return None, None
    try:
        conjecture = _load_json(conjecture_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CouncilEvoProductionError([f"{BLOCK_PACKET}:conjecture:{type(exc).__name__}"]) from exc
    if not epistemic_evolution_enabled(conjecture):
        return None, None
    conjecture_reasons = validate_research_conjecture(conjecture)
    if conjecture_reasons:
        raise CouncilEvoProductionError(
            [f"{BLOCK_PACKET}:conjecture:{reason}" for reason in conjecture_reasons]
        )

    released = _released_oos_paths(root, report_id)
    if released:
        raise CouncilEvoProductionError(
            [f"{BLOCK_OOS}:{Path(path).name}" for path in released]
        )

    lifecycle_path = paths["evo_lifecycle"]
    if not lifecycle_path.is_file():
        raise CouncilEvoProductionError([f"{BLOCK_LIFECYCLE}:missing"])
    try:
        lifecycle = _load_json(lifecycle_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CouncilEvoProductionError([f"{BLOCK_LIFECYCLE}:unreadable"]) from exc
    lifecycle_reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if lifecycle_reasons:
        raise CouncilEvoProductionError(
            [f"{BLOCK_LIFECYCLE}:{reason}" for reason in lifecycle_reasons]
        )
    current_state = lifecycle.get("current_state")
    replay_context = dict(bound_context) if isinstance(bound_context, Mapping) else None
    if current_state != "QUALIFIED_CONTRADICTION" and replay_context is None:
        raise CouncilEvoProductionError([f"{BLOCK_LIFECYCLE}:{current_state}"])

    core_paths = evo_v2_paths(root, report_id)
    feedback_path = core_paths["feedback_ledger"]
    if not feedback_path.is_file() or feedback_path.is_symlink():
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:missing"])
    try:
        feedback = _load_json(feedback_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:unreadable"]) from exc
    if feedback_path.read_bytes() != canonical_json_bytes(feedback):
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:noncanonical_json"])
    expected_relative = evo_v2_relative_paths(report_id)["feedback_ledger"]
    feedback_ref = {
        "path": expected_relative,
        "sha256": artifact_sha256(feedback),
    }
    if _ref(root, feedback_path) != feedback_ref:
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:canonical_ref"])
    feedback_reasons = validate_feedback_ledger(
        feedback,
        workspace_root=root,
        known_artifacts={expected_relative: feedback},
        verify_refs=True,
    )
    if feedback_reasons:
        raise CouncilEvoProductionError(
            [f"{BLOCK_FEEDBACK}:{reason}" for reason in feedback_reasons]
        )
    measurement_program, measurement_program_ref = _frozen_measurement_program(
        root=root,
        feedback=feedback,
    )
    identity = feedback.get("artifact_identity")
    identity = identity if isinstance(identity, Mapping) else {}
    contradiction = feedback.get("contradiction")
    contradiction = contradiction if isinstance(contradiction, Mapping) else {}
    contradiction_id = contradiction.get("contradiction_id")
    if identity.get("report_id") != report_id or not isinstance(contradiction_id, str):
        raise CouncilEvoProductionError([f"{BLOCK_FEEDBACK}:identity"])
    visible_refs = _visible_feedback_evidence(feedback)
    ref_reasons = _oos_reference_reasons(_all_feedback_evidence(feedback))
    if ref_reasons:
        raise CouncilEvoProductionError(ref_reasons)

    if replay_context is None:
        lifecycle_generation = len(lifecycle.get("events") or [])
        lifecycle_snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
            root,
            report_id,
            lifecycle_generation,
        )
        if (
            not lifecycle_snapshot_path.is_file()
            or lifecycle_snapshot_path.is_symlink()
            or lifecycle_snapshot_path.read_bytes() != lifecycle_path.read_bytes()
        ):
            raise CouncilEvoProductionError(
                [f"{BLOCK_LIFECYCLE}:immutable_snapshot_missing_or_mismatch"]
            )
        lifecycle_ref = _ref(root, lifecycle_snapshot_path)
    else:
        lifecycle_ref = replay_context.get("lifecycle_ref")
        if not isinstance(lifecycle_ref, Mapping):
            raise CouncilEvoProductionError([f"{BLOCK_LIFECYCLE}:bound_ref_missing"])
        raw_path = lifecycle_ref.get("path")
        snapshot_path = (
            root / raw_path if isinstance(raw_path, str) else root / "__missing__"
        )
        if (
            not isinstance(raw_path, str)
            or snapshot_path.is_symlink()
            or not snapshot_path.is_file()
            or _ref(root, snapshot_path) != lifecycle_ref
        ):
            raise CouncilEvoProductionError([f"{BLOCK_LIFECYCLE}:bound_snapshot_invalid"])
        snapshot = _load_json(snapshot_path)
        snapshot_reasons = validate_epistemic_evolution_lifecycle(
            snapshot,
            report_id=report_id,
            workspace_root=root,
            require_signed_host_receipts=True,
        )
        current_events = lifecycle.get("events")
        snapshot_events = snapshot.get("events")
        if (
            snapshot_reasons
            or snapshot.get("current_state") != "QUALIFIED_CONTRADICTION"
            or not isinstance(snapshot_events, list)
            or not isinstance(current_events, list)
            or current_events[: len(snapshot_events)] != snapshot_events
            or len(current_events) < len(snapshot_events)
        ):
            raise CouncilEvoProductionError(
                [f"{BLOCK_LIFECYCLE}:bound_snapshot_not_ancestor"]
            )

    context = {
        "contract_version": EVO_PACKET_CONTEXT_VERSION,
        "required": True,
        "lifecycle_state": "QUALIFIED_CONTRADICTION",
        "lifecycle_ref": dict(lifecycle_ref),
        "canonical_feedback_ref": feedback_ref,
        "frozen_measurement_program_ref": measurement_program_ref,
        "frozen_measurement_program_sha256": stable_measurement_program_hash(
            measurement_program
        ),
        "contradiction_id": contradiction_id,
        "evidence_view": PURGED_IS_EVIDENCE_VIEW,
        "visible_evidence_refs": visible_refs,
        "oos_control": {
            "search_use": "SEALED_NOT_ACCESSED",
            "oos_refs_allowed": False,
            "consumed_oos_reuse_allowed": False,
        },
    }
    if replay_context is not None and context != replay_context:
        raise CouncilEvoProductionError([f"{BLOCK_PACKET}:bound_context_mismatch"])
    return context, feedback


def validate_formal_evo_packet(
    packet: Mapping[str, Any],
    *,
    workspace_root: Path | str,
    report_id: str,
) -> list[str]:
    context = packet.get("evo_v2")
    try:
        expected, feedback = load_formal_evo_packet_context(workspace_root, report_id)
    except CouncilEvoProductionError as exc:
        return exc.reasons
    if expected is None:
        return [] if context is None else [f"{BLOCK_PACKET}:unexpected_context"]
    if feedback is None or context != expected:
        return [f"{BLOCK_PACKET}:context_mismatch"]
    reasons = _oos_reference_reasons(context.get("visible_evidence_refs"))
    for field, expected_value in formal_packet_redactions(feedback).items():
        if packet.get(field) != expected_value:
            reasons.append(f"{BLOCK_EVIDENCE_VIEW}:{field}")
    frozen_program_path = (
        Path(workspace_root).resolve(strict=True)
        / expected["frozen_measurement_program_ref"]["path"]
    )
    try:
        frozen_program = _load_json(frozen_program_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        reasons.append(f"{BLOCK_EVIDENCE_VIEW}:measurement_program")
        frozen_program = None
    if (
        frozen_program is None
        or packet.get("mechanism_conditioned_measurement_program")
        != frozen_program
        or stable_measurement_program_hash(frozen_program)
        != expected.get("frozen_measurement_program_sha256")
    ):
        reasons.append(f"{BLOCK_EVIDENCE_VIEW}:measurement_program")
    source_paths = packet.get("source_paths")
    allowed_source_paths = {
        "research_conjecture": research_protocol_paths(
            Path(workspace_root).resolve(strict=True), report_id
        )["conjecture"].resolve(strict=True).as_posix(),
        "evo_lifecycle": (
            Path(workspace_root).resolve(strict=True) / context["lifecycle_ref"]["path"]
        ).resolve(strict=True).as_posix(),
        "evo_feedback_ledger": (
            Path(workspace_root).resolve(strict=True)
            / context["canonical_feedback_ref"]["path"]
        ).resolve(strict=True).as_posix(),
        "frozen_measurement_program": frozen_program_path.resolve(
            strict=True
        ).as_posix(),
    }
    if source_paths != allowed_source_paths:
        reasons.append(f"{BLOCK_EVIDENCE_VIEW}:source_paths")
    return list(dict.fromkeys(reasons))


def build_evo_task_identity(
    packet_context: Mapping[str, Any],
    *,
    report_id: str,
    task_id: str,
    route_id: Any,
    route_fingerprint: Any,
    blind_context_hash: Any,
) -> dict[str, Any]:
    payload = {
        "contract_version": EVO_TASK_IDENTITY_VERSION,
        "report_id": report_id,
        "task_id": task_id,
        "route_id": route_id,
        "route_fingerprint": route_fingerprint,
        "blind_context_hash": blind_context_hash,
        "lifecycle_state": packet_context.get("lifecycle_state"),
        "lifecycle_ref": copy.deepcopy(packet_context.get("lifecycle_ref")),
        "canonical_feedback_ref": copy.deepcopy(
            packet_context.get("canonical_feedback_ref")
        ),
        "contradiction_id": packet_context.get("contradiction_id"),
        "evidence_view": packet_context.get("evidence_view"),
        "packet_evo_context_sha256": stable_json_hash(packet_context),
    }
    payload["identity_sha256"] = stable_json_hash(payload)
    return payload


def validate_evo_task_identity(
    value: Any,
    *,
    packet_context: Mapping[str, Any] | None = None,
    report_id: str | None = None,
    task_id: str | None = None,
    route_id: Any = None,
    route_fingerprint: Any = None,
    blind_context_hash: Any = None,
) -> list[str]:
    if not isinstance(value, dict):
        return [BLOCK_TASK_IDENTITY]
    unsigned = dict(value)
    digest = unsigned.pop("identity_sha256", None)
    if digest != stable_json_hash(unsigned):
        return [f"{BLOCK_TASK_IDENTITY}:hash"]
    if value.get("contract_version") != EVO_TASK_IDENTITY_VERSION:
        return [f"{BLOCK_TASK_IDENTITY}:version"]
    if packet_context is not None:
        expected = build_evo_task_identity(
            packet_context,
            report_id=str(report_id or ""),
            task_id=str(task_id or ""),
            route_id=route_id,
            route_fingerprint=route_fingerprint,
            blind_context_hash=blind_context_hash,
        )
        if value != expected:
            return [f"{BLOCK_TASK_IDENTITY}:tuple"]
    return []


def validate_result_evo_identity(
    result: Mapping[str, Any],
    expected_task: Mapping[str, Any],
) -> list[str]:
    expected = expected_task.get("evo_v2_task_identity")
    if expected is None:
        return []
    reasons = validate_evo_task_identity(expected)
    if result.get("evo_v2_task_identity") != expected:
        reasons.append(BLOCK_RESULT_IDENTITY)
    dispatch = result.get("dispatch_identity")
    dispatch = dispatch if isinstance(dispatch, Mapping) else {}
    if dispatch.get("evo_v2_task_identity_sha256") != expected.get(
        "identity_sha256"
    ):
        reasons.append(f"{BLOCK_RESULT_IDENTITY}:dispatch_hash")
    envelope = result.get("evo_v2")
    envelope = envelope if isinstance(envelope, Mapping) else {}
    if envelope.get("feedback_ledger") != expected.get("canonical_feedback_ref"):
        reasons.append(f"{BLOCK_RESULT_IDENTITY}:feedback_ref")
    gate = envelope.get("intake_gate")
    gate = gate if isinstance(gate, Mapping) else {}
    if (
        gate.get("source_state") != expected.get("lifecycle_state")
        or gate.get("contradiction_id") != expected.get("contradiction_id")
    ):
        reasons.append(f"{BLOCK_RESULT_IDENTITY}:intake_gate")
    return list(dict.fromkeys(reasons))


def result_evo_outcome_summary(result: Mapping[str, Any]) -> dict[str, Any] | None:
    envelope = result.get("evo_v2")
    if not isinstance(envelope, Mapping):
        return None
    outcome = envelope.get("derivation_outcome")
    if not isinstance(outcome, Mapping):
        return None
    task_identity = result.get("evo_v2_task_identity")
    task_identity = task_identity if isinstance(task_identity, Mapping) else {}
    summary: dict[str, Any] = {
        "outcome": outcome.get("outcome"),
        "evo_v2_task_identity_sha256": task_identity.get("identity_sha256"),
        "canonical_feedback_ref": copy.deepcopy(envelope.get("feedback_ledger")),
    }
    if outcome.get("outcome") == "MINIMAL_MECHANISM_DELTA":
        delta = outcome.get("mechanism_delta")
        backprojection = outcome.get("economic_backprojection")
        laws = result.get("candidate_revision_laws")
        law = laws[0] if isinstance(laws, list) and len(laws) == 1 else None
        binding = envelope.get("proposal_law_binding")
        binding = binding if isinstance(binding, Mapping) else {}
        summary.update(
            {
                "mechanism_delta_sha256": (
                    artifact_sha256(delta) if isinstance(delta, Mapping) else None
                ),
                "economic_backprojection_sha256": (
                    artifact_sha256(backprojection)
                    if isinstance(backprojection, Mapping)
                    else None
                ),
                "law_sha256": (
                    stable_json_hash(law) if isinstance(law, Mapping) else None
                ),
                "delta_id": binding.get("delta_id"),
            }
        )
    elif outcome.get("outcome") == "NO_DERIVED_LAW":
        proof = outcome.get("no_derived_law")
        summary.update(
            {
                "no_derived_law_sha256": (
                    stable_json_hash(proof) if isinstance(proof, Mapping) else None
                ),
                "candidate_law_count": len(result.get("candidate_revision_laws") or []),
            }
        )
    return summary


__all__ = [
    "BLOCK_EVIDENCE_VIEW",
    "BLOCK_FEEDBACK",
    "BLOCK_LIFECYCLE",
    "BLOCK_OOS",
    "BLOCK_PACKET",
    "BLOCK_RESULT_IDENTITY",
    "BLOCK_TASK_IDENTITY",
    "CouncilEvoProductionError",
    "EVO_PACKET_CONTEXT_VERSION",
    "EVO_TASK_IDENTITY_VERSION",
    "PURGED_IS_EVIDENCE_VIEW",
    "build_evo_task_identity",
    "formal_packet_redactions",
    "load_formal_evo_packet_context",
    "qualified_is_metric_projection",
    "result_evo_outcome_summary",
    "validate_evo_task_identity",
    "validate_formal_evo_packet",
    "validate_result_evo_identity",
]
