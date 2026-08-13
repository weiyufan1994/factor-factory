from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from factor_factory.evo_child_execution import (
    EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND,
    expected_evo_child_execution_trials,
    execution_addendum_path,
    validate_frozen_child_execution_ledger,
    verifier_source_bundle,
)
from factor_factory.evo_oos import (
    child_control_paths,
    formal_oos_incident_reasons,
    validate_oos_allocation,
)
from factor_factory.oos_exposure_incident import (
    OOS_EXPOSURE_INSTALLATION_ID_ENV,
    OOS_EXPOSURE_TRUST_ROOT_ENV,
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.evo_v2 import (
    canonical_json_bytes,
    sha256_file,
    stable_json_hash,
)
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_enabled,
    epistemic_evolution_lifecycle_snapshot_path,
    research_protocol_paths,
    validate_approach_registry,
    validate_epistemic_evolution_lifecycle,
    validate_protocol_bundle,
    validate_research_conjecture,
    validate_research_state,
)
from factor_factory.research_release import (
    MINIMUM_FORMAL_DAILY_PERIODS,
    METRIC_VERIFIER_SPEC_VERSION,
    METRIC_THRESHOLD_REGISTRATION_VERSION,
    SEARCH_TRIAL_LEDGER_VERSION,
    evaluation_contract_hash,
    stable_hash,
    validate_threshold_decision_rules,
)


CHILD_PREREGISTRATION_VERSION = "factorforge_evo_child_preregistration_v1"
CHILD_PREDICTION_FREEZE_VERIFIER_VERSION = (
    "factorforge_evo_child_prediction_freeze_verifier_v1"
)
CHILD_PREDICTION_FREEZE_VERIFIER_ID = (
    "factorforge_evo_child_prediction_freeze_verifier_v1"
)
CHILD_PREREGISTRATION_STATUS = "CHILD_CONTROLS_FROZEN_NOT_EXECUTED"
CHILD_SEARCH_IDENTITY_VERSION = "factorforge_evo_child_search_identity_v1"
CHILD_WEB_RESEARCH_PLAN_PROJECTION_VERSION = (
    "factorforge_evo_child_web_research_plan_projection_v1"
)
BLOCK_EVO_CHILD_PREREGISTRATION = (
    "BLOCK_FACTORFORGE_EVO_CHILD_PREREGISTRATION_INVALID"
)
WAITING_EVO_CHILD_PREREGISTRATION = (
    "WAITING_FACTORFORGE_EVO_CHILD_PREREGISTRATION_AUTHORIZATION"
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,191}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BASE_LEDGER_FIELDS = {
    "version",
    "search_status",
    "report_id",
    "factor_id",
    "freeze_sequence",
    "trial_count",
    "trials",
    "trial_set_sha256",
    "candidate_space_sha256",
    "selected_hypothesis_sha256",
}
_THRESHOLD_FIELDS = {
    "version",
    "registration_status",
    "report_id",
    "factor_id",
    "claim_class",
    "verification_scope",
    "window_hash",
    "evaluation_contract_hash",
    "label_contract_hash",
    "registered_before_evaluation",
    "registration_sequence",
    "search_trial_ledger_ref",
    "search_trial_ledger_sha256",
    "decision_rules",
    "rule_set_sha256",
}
_PUBLISH_ORDER = (
    "prediction_freeze_verifier",
    "evo_lifecycle",
    "evo_lifecycle_snapshot",
    "research_state",
    "research_conjecture",
    "approach_registry",
    "search_trial_ledger",
    "metric_verifier_spec",
    "child_web_research_plan",
    "web_factor_proof_preregistration",
    # The READY-ticket validator requires this fifth control.  Publishing it
    # last makes its presence the create-only commit point for the control set.
    "threshold_registration",
)
_AUTHORITY = {
    "scope": "CHILD_PREREGISTRATION_ONLY",
    "agent_authored_semantics_preserved": True,
    "deterministic_semantic_generation_allowed": False,
    "prediction_registry_frozen": True,
    "execution_completed": False,
    "human_approval_granted_by_writer": False,
    "child_execution_allowed": False,
    "oos_release_allowed": False,
    "oos_accessed": False,
    "factor_verdict": "NOT_ISSUED",
    "canonical_memory_write_allowed": False,
    "skill_or_policy_mutation_allowed": False,
}
_BASE_TRIAL_STATUSES = {
    "REGISTERED_NOT_EVALUATED",
    "REGISTERED_DIAGNOSTIC_NOT_EVALUATED",
}
_FORBIDDEN_BASE_TRIAL_RESULT_FIELDS = {
    "accepted",
    "approved",
    "dataset_snapshot_hash",
    "evidence_refs",
    "factor_verdict",
    "metrics",
    "observed_metrics",
    "oos_accessed",
    "oos_release_manifest_ref",
    "result",
    "verdict",
}


class EvoChildPreregistrationError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(item) for item in reasons if str(item)))
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_EVO_CHILD_PREREGISTRATION}:{reason}"


def _waiting(reason: str) -> str:
    return f"{WAITING_EVO_CHILD_PREREGISTRATION}:{reason}"


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _within_without_symlinks(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _safe_parent(root: Path, path: Path) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise EvoChildPreregistrationError([_token("output_outside_workspace")]) from exc
    current = root
    for part in relative.parent.parts:
        candidate = current / part
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if candidate.is_symlink() or not candidate.is_dir():
            raise EvoChildPreregistrationError(
                [_token(f"unsafe_output_parent:{candidate.name}")]
            )
        try:
            candidate.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise EvoChildPreregistrationError(
                [_token(f"unsafe_output_parent:{candidate.name}")]
            ) from exc
        current = candidate
    if not _within_without_symlinks(root, path):
        raise EvoChildPreregistrationError([_token(f"unsafe_output:{path.name}")])
    return current


def _load_source_object(path: Path | str, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise EvoChildPreregistrationError([_token(f"source_missing_or_unsafe:{label}")])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildPreregistrationError([_token(f"source_invalid_json:{label}")]) from exc
    if not isinstance(payload, dict):
        raise EvoChildPreregistrationError([_token(f"source_object_required:{label}")])
    return payload


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _payload_ref(root: Path, path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _payload_sha256(payload),
    }


def _file_ref(root: Path, path: Path) -> dict[str, str]:
    if not _within_without_symlinks(root, path) or path.is_symlink() or not path.is_file():
        raise EvoChildPreregistrationError([_token(f"unsafe_ref:{path.name}")])
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def _resolve_bound_ref(
    root: Path,
    reference: Any,
    *,
    label: str,
    expected_path: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    if not isinstance(reference, Mapping) or set(reference) not in (
        {"path", "sha256"},
        {"path", "sha256", "content_sha256"},
        {"path", "sha256", "semantic_sha256"},
    ):
        raise EvoChildPreregistrationError([_token(f"{label}_ref_shape")])
    raw = reference.get("path")
    if not isinstance(raw, str) or "\\" in raw or not _is_sha256(
        reference.get("sha256")
    ):
        raise EvoChildPreregistrationError([_token(f"{label}_ref_values")])
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw:
        raise EvoChildPreregistrationError([_token(f"{label}_ref_path")])
    path = root.joinpath(*relative.parts)
    if expected_path is not None and path.resolve(strict=False) != expected_path.resolve(
        strict=False
    ):
        raise EvoChildPreregistrationError([_token(f"{label}_canonical_path")])
    if (
        not _within_without_symlinks(root, path)
        or path.is_symlink()
        or not path.is_file()
        or sha256_file(path) != reference.get("sha256")
    ):
        raise EvoChildPreregistrationError([_token(f"{label}_ref_readback")])
    payload = _load_source_object(path, label=label)
    if "content_sha256" in reference:
        declared = payload.get("content_sha256")
        if declared is None:
            valid_content_binding = (
                reference.get("content_sha256") == stable_json_hash(payload)
            )
        else:
            unsigned = dict(payload)
            unsigned.pop("content_sha256", None)
            valid_content_binding = (
                declared == reference.get("content_sha256")
                and declared == stable_json_hash(unsigned)
            )
        if not valid_content_binding:
            raise EvoChildPreregistrationError([_token(f"{label}_content_sha256")])
    if (
        "semantic_sha256" in reference
        and reference.get("semantic_sha256") != stable_json_hash(payload)
    ):
        raise EvoChildPreregistrationError([_token(f"{label}_semantic_sha256")])
    return path, payload


def child_preregistration_receipt_path(root: Path, child_report_id: str) -> Path:
    if not _safe_id(child_report_id):
        raise EvoChildPreregistrationError([_token("child_report_id")])
    return (
        root
        / "objects"
        / "runtime_context"
        / f"evo_child_preregistration__{child_report_id}.json"
    )


def child_prediction_freeze_verifier_path(root: Path, child_report_id: str) -> Path:
    if not _safe_id(child_report_id):
        raise EvoChildPreregistrationError([_token("child_report_id")])
    return (
        root
        / "objects"
        / "evo_v2"
        / child_report_id
        / "prediction_freeze_verifier.json"
    )


def child_metric_verifier_spec_path(root: Path, child_report_id: str) -> Path:
    if not _safe_id(child_report_id):
        raise EvoChildPreregistrationError([_token("child_report_id")])
    return (
        root
        / "objects"
        / "research_protocol"
        / f"metric_verifier_spec__{child_report_id}.json"
    )


def child_web_research_plan_path(root: Path, child_report_id: str) -> Path:
    """Canonical immutable report-scoped Web plan projection for a child."""

    if not _safe_id(child_report_id):
        raise EvoChildPreregistrationError([_token("child_report_id")])
    return (
        root
        / "objects"
        / "research_protocol"
        / f"web_research_plan__{child_report_id}.json"
    )


def project_evo_child_search_identities(
    research_conjecture: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the only admissible candidate-space and selected-model hashes."""

    conjecture = dict(research_conjecture)
    hypotheses = conjecture.get("hypotheses")
    identity = conjecture.get("identity")
    evidence = conjecture.get("evidence_policy")
    preferred = (
        [
            dict(item)
            for item in hypotheses
            if isinstance(item, Mapping) and item.get("kind") == "preferred"
        ]
        if isinstance(hypotheses, list)
        else []
    )
    if (
        len(preferred) != 1
        or not isinstance(identity, Mapping)
        or not isinstance(evidence, Mapping)
        or not _safe_id(conjecture.get("report_id"))
        or not _safe_id(conjecture.get("factor_id"))
        or not _is_sha256(identity.get("formula_hash"))
    ):
        raise EvoChildPreregistrationError([_token("search_identity_inputs")])
    candidate_space = {
        "projection_version": CHILD_SEARCH_IDENTITY_VERSION,
        "report_id": conjecture["report_id"],
        "factor_id": conjecture["factor_id"],
        "claim_class": conjecture.get("claim_class"),
        "formula_hash": identity["formula_hash"],
        "hypotheses": deepcopy(hypotheses),
        "trial_budget": evidence.get("trial_budget"),
        "multiple_testing_policy": evidence.get("multiple_testing_policy"),
    }
    selected = preferred[0]
    return {
        "projection_version": CHILD_SEARCH_IDENTITY_VERSION,
        "candidate_space": candidate_space,
        "candidate_space_sha256": stable_json_hash(candidate_space),
        "selected_hypothesis": selected,
        "selected_hypothesis_sha256": stable_json_hash(selected),
    }


def _parent_contract_context(
    *,
    root: Path,
    parent_report_id: str,
) -> dict[str, Any]:
    """Resolve already-frozen parent evaluation contracts.

    The child writer never treats a detached Host object as the evaluation
    authority.  The canonical parent web plan must replay its pre-Step4 proof
    preregistration exactly; only then can its spec and rules seed the
    deterministic child projection.
    """

    from factor_factory.console.web_factor_proof import (
        _trusted_calendar_snapshot,
        validate_web_factor_proof_preregistration_structural,
        web_factor_proof_paths,
    )
    from factor_factory.console.web_research_plan import build_web_evaluation_contract

    plan_path = root / "identity" / "web_research_plan.json"
    plan = _load_source_object(plan_path, label="parent_web_research_plan")
    identity = plan.get("identity")
    if not isinstance(identity, Mapping) or identity.get("report_id") != parent_report_id:
        raise EvoChildPreregistrationError([_token("parent_plan_identity")])
    try:
        replay = validate_web_factor_proof_preregistration_structural(root, plan)
        calendar = _trusted_calendar_snapshot(workspace_root=root)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EvoChildPreregistrationError(
            [_token(f"parent_protected_contract_replay:{type(exc).__name__}:{exc}")]
        ) from exc
    if replay.get("status") != "PASS":
        raise EvoChildPreregistrationError([_token("parent_protected_contract_replay")])
    paths = web_factor_proof_paths(root, parent_report_id)
    spec = _load_source_object(paths["spec"], label="parent_metric_verifier_spec")
    threshold = _load_source_object(
        paths["threshold"], label="parent_threshold_registration"
    )
    web_preregistration = _load_source_object(
        paths["preregistration"], label="parent_web_factor_proof_preregistration"
    )
    if (
        spec.get("version") != METRIC_VERIFIER_SPEC_VERSION
        or spec.get("verification_scope") != "production"
        or spec.get("report_id") != parent_report_id
        or threshold.get("version") != METRIC_THRESHOLD_REGISTRATION_VERSION
        or threshold.get("registration_status") != "LOCKED"
        or threshold.get("report_id") != parent_report_id
        or threshold.get("decision_rules") is None
    ):
        raise EvoChildPreregistrationError([_token("parent_protected_contract_shape")])
    parent_protocol = research_protocol_paths(root, parent_report_id)
    parent_conjecture_path = parent_protocol["conjecture"]
    parent_conjecture = _load_source_object(
        parent_conjecture_path, label="parent_research_conjecture"
    )
    parent_conjecture_identity = parent_conjecture.get("identity")
    parent_evidence = parent_conjecture.get("evidence_policy")
    plan_evidence = plan.get("evidence_policy")
    protected_evidence_fields = (
        "is_start",
        "is_end",
        "oos_start",
        "oos_end",
        "purge_days",
        "embargo_days",
        "trial_budget",
        "multiple_testing_policy",
        "forward_horizon",
        "transaction_cost_bps",
        "cost_model_id",
        "impact_model_id",
        "capacity_model_id",
        "universe_id",
        "investability_mask_id",
    )
    if (
        validate_research_conjecture(parent_conjecture)
        or parent_conjecture.get("report_id") != parent_report_id
        or parent_conjecture.get("factor_id") != spec.get("factor_id")
        or not isinstance(parent_conjecture_identity, Mapping)
        or parent_conjecture_identity.get("research_id") != spec.get("research_id")
        or parent_conjecture.get("claim_class") != spec.get("claim_class")
        or not _is_sha256(
            parent_conjecture_identity.get("data_catalog_snapshot_sha256")
        )
        or not isinstance(parent_evidence, Mapping)
        or not isinstance(plan_evidence, Mapping)
        or any(
            parent_evidence.get(field) != plan_evidence.get(field)
            for field in protected_evidence_fields
            if field in parent_evidence or field in plan_evidence
        )
        or parent_conjecture.get("evaluation_contract")
        != build_web_evaluation_contract(plan)
    ):
        raise EvoChildPreregistrationError(
            [_token("parent_research_conjecture_contract")]
        )
    dates = calendar.get("dates")
    if not isinstance(dates, list) or not dates or any(
        not isinstance(item, str) or not item for item in dates
    ):
        raise EvoChildPreregistrationError([_token("parent_trusted_calendar")])
    return {
        "plan": plan,
        "plan_path": plan_path,
        "metric_verifier_spec": spec,
        "metric_verifier_spec_path": paths["spec"],
        "threshold_registration": threshold,
        "threshold_registration_path": paths["threshold"],
        "web_preregistration_path": paths["preregistration"],
        "web_preregistration": web_preregistration,
        "research_conjecture": parent_conjecture,
        "research_conjecture_path": parent_conjecture_path,
        "calendar": dict(calendar),
        "calendar_dates": list(dates),
        "source_file_sha256s": {
            path: sha256_file(path)
            for path in (
                plan_path,
                parent_conjecture_path,
                paths["spec"],
                paths["threshold"],
                paths["preregistration"],
                calendar["path"],
            )
        },
    }


def _project_evo_child_search_trial_ledger(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    base_search_trial_ledger: Mapping[str, Any],
    execution_addendum: Mapping[str, Any] | None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
    ):
        raise EvoChildPreregistrationError([_token("report_identity")])
    base = dict(base_search_trial_ledger)
    if set(base) != _BASE_LEDGER_FIELDS:
        raise EvoChildPreregistrationError([_token("base_ledger_fields")])
    trials = base.get("trials")
    if (
        base.get("version") != SEARCH_TRIAL_LEDGER_VERSION
        or base.get("search_status") != "FROZEN"
        or base.get("report_id") != child_report_id
        or not _safe_id(base.get("factor_id"))
        or isinstance(base.get("freeze_sequence"), bool)
        or not isinstance(base.get("freeze_sequence"), int)
        or base.get("freeze_sequence") < 1
        or not isinstance(trials, list)
        or not trials
        or base.get("trial_count") != len(trials or [])
        or base.get("trial_set_sha256") != stable_json_hash(trials)
        or not _is_sha256(base.get("candidate_space_sha256"))
        or not _is_sha256(base.get("selected_hypothesis_sha256"))
    ):
        raise EvoChildPreregistrationError([_token("base_ledger_invalid")])
    if any(not isinstance(item, Mapping) for item in trials):
        raise EvoChildPreregistrationError([_token("base_ledger_trial_object")])
    if any(
        item.get("trial_kind") == EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
        for item in trials
    ):
        raise EvoChildPreregistrationError(
            [_token("base_ledger_evo_diagnostic_forbidden")]
        )
    ids = [item.get("trial_id") for item in trials]
    if any(not _safe_id(value) for value in ids) or len(ids) != len(set(ids)):
        raise EvoChildPreregistrationError([_token("base_ledger_trial_ids")])
    expected = expected_evo_child_execution_trials(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        execution_addendum=execution_addendum,
    )
    expected_ids = [item["trial_id"] for item in expected]
    if set(ids) & set(expected_ids):
        raise EvoChildPreregistrationError([_token("execution_trial_id_collision")])
    final_trials = [dict(item) for item in trials] + expected
    output = {
        **base,
        "trial_count": len(final_trials),
        "trials": final_trials,
        "trial_set_sha256": stable_json_hash(final_trials),
    }
    reasons = validate_frozen_child_execution_ledger(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        search_trial_ledger=output,
        execution_addendum=execution_addendum,
    )
    if reasons:
        raise EvoChildPreregistrationError(
            [_token(f"shared_ledger_validator:{reason}") for reason in reasons]
        )
    return output


def _authorization_context(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    from factor_factory.evo_child_materialization_ticket import (
        public_child_materialization_ticket_path,
        validate_public_child_materialization_ticket,
    )

    if not _is_sha256(expected_host_trust_manifest_sha256):
        raise EvoChildPreregistrationError([_token("external_host_trust_pin_required")])
    authorization_path = public_child_materialization_ticket_path(
        root, child_report_id, materialization_ready=False
    )
    if not authorization_path.is_file() or authorization_path.is_symlink():
        raise EvoChildPreregistrationError([_waiting("authorization_ticket_missing")])
    ticket, reasons = validate_public_child_materialization_ticket(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        require_materialization_ready=False,
        exact_ticket_path=authorization_path,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    if ticket is None or reasons:
        raise EvoChildPreregistrationError(
            [_token(f"authorization_ticket:{reason}") for reason in reasons]
            or [_token("authorization_ticket")]
        )
    trust_manifest_path, _trust_manifest = _resolve_bound_ref(
        root,
        ticket.get("trust_manifest_ref"),
        label="host_trust_manifest",
    )
    bindings = ticket.get("bindings")
    if not isinstance(bindings, Mapping):
        raise EvoChildPreregistrationError([_token("authorization_bindings")])
    handoff_path, handoff = _resolve_bound_ref(
        root,
        bindings.get("handoff_ref"),
        label="handoff",
    )
    allocation_path, allocation = _resolve_bound_ref(
        root,
        bindings.get("oos_allocation_ref"),
        label="oos_allocation",
    )
    memory_state = ticket.get("memory_state")
    addendum: dict[str, Any] | None = None
    addendum_path: Path | None = None
    if memory_state == "ADMISSIBLE_MEMORY_FOUND":
        addendum_path, addendum = _resolve_bound_ref(
            root,
            bindings.get("execution_addendum_ref"),
            label="execution_addendum",
            expected_path=execution_addendum_path(root, parent_report_id),
        )
    elif memory_state == "COLD_START_NO_ADMISSIBLE_MEMORY":
        if bindings.get("execution_addendum_ref") is not None or execution_addendum_path(
            root, parent_report_id
        ).exists():
            raise EvoChildPreregistrationError([_token("cold_addendum_forbidden")])
    else:
        raise EvoChildPreregistrationError([_token("authorization_memory_state")])
    parent_contracts = _parent_contract_context(
        root=root,
        parent_report_id=parent_report_id,
    )
    execution_verifier_bundle = verifier_source_bundle()
    repository_root = Path(__file__).resolve().parents[1]
    execution_verifier_source_paths = {
        repository_root / str(item["path"]): str(item["sha256"])
        for item in execution_verifier_bundle.get("source_refs") or []
        if isinstance(item, Mapping)
    }
    if (
        not execution_verifier_source_paths
        or any(
            not _is_sha256(value)
            for value in execution_verifier_source_paths.values()
        )
    ):
        raise EvoChildPreregistrationError(
            [_token("execution_verifier_source_bundle")]
        )
    if addendum is not None:
        frozen_plan_path, frozen_plan = _resolve_bound_ref(
            root,
            addendum.get("frozen_web_research_plan_ref"),
            label="addendum_frozen_web_research_plan",
            expected_path=parent_contracts["plan_path"],
        )
        if (
            frozen_plan_path != parent_contracts["plan_path"]
            or frozen_plan != parent_contracts["plan"]
        ):
            raise EvoChildPreregistrationError(
                [_token("addendum_parent_plan_binding")]
            )
    source_file_sha256s = {
        authorization_path: sha256_file(authorization_path),
        trust_manifest_path: sha256_file(trust_manifest_path),
        handoff_path: sha256_file(handoff_path),
        allocation_path: sha256_file(allocation_path),
        **dict(parent_contracts["source_file_sha256s"]),
        **execution_verifier_source_paths,
    }
    if addendum_path is not None:
        source_file_sha256s[addendum_path] = sha256_file(addendum_path)
    return {
        "ticket": ticket,
        "authorization_path": authorization_path,
        "handoff": handoff,
        "handoff_path": handoff_path,
        "allocation": allocation,
        "allocation_path": allocation_path,
        "execution_addendum": addendum,
        "execution_addendum_path": addendum_path,
        "parent_contracts": parent_contracts,
        "execution_verifier_source_bundle": execution_verifier_bundle,
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
        "source_file_sha256s": source_file_sha256s,
    }


def _project_evo_child_metric_verifier_spec(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    conjecture: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the child spec from frozen parent contracts plus Host OOS.

    The only permitted changes are the child identity, canonical child output
    references, and the Host-allocated fresh sealed OOS window/token.  Panel,
    label, portfolio, cost, claim class, horizon, estimand-facing paths and all
    other evaluation semantics remain byte-for-byte inherited.
    """

    parent_contracts = authorization.get("parent_contracts")
    if not isinstance(parent_contracts, Mapping):
        raise EvoChildPreregistrationError([_token("parent_contracts_required")])
    parent_spec = parent_contracts.get("metric_verifier_spec")
    allocation = authorization.get("allocation")
    evidence = conjecture.get("evidence_policy")
    identity = conjecture.get("identity")
    if (
        not isinstance(parent_spec, Mapping)
        or not isinstance(allocation, Mapping)
        or not isinstance(evidence, Mapping)
        or not isinstance(identity, Mapping)
    ):
        raise EvoChildPreregistrationError([_token("child_spec_projection_inputs")])
    allocation_reasons = validate_oos_allocation(
        dict(allocation), workspace_root=root
    )
    if allocation_reasons:
        raise EvoChildPreregistrationError(
            [_token(f"fresh_oos_allocation:{reason}") for reason in allocation_reasons]
        )
    allocation_window = allocation.get("oos_window")
    allocation_window = (
        allocation_window if isinstance(allocation_window, Mapping) else {}
    )
    oos_start = allocation_window.get("start")
    oos_end = allocation_window.get("end")
    calendar_dates = parent_contracts.get("calendar_dates")
    if (
        not isinstance(oos_start, str)
        or not isinstance(oos_end, str)
        or not isinstance(calendar_dates, list)
        or calendar_dates != sorted(set(calendar_dates))
    ):
        raise EvoChildPreregistrationError([_token("child_oos_calendar_projection")])
    eligible = [item for item in calendar_dates if oos_start <= item <= oos_end]
    if len(eligible) < MINIMUM_FORMAL_DAILY_PERIODS + 2:
        raise EvoChildPreregistrationError([_token("child_oos_window_too_short")])
    signal_dates = eligible[:-2]
    parent_window = parent_spec.get("window_contract")
    parent_label = parent_spec.get("label_contract")
    parent_panel = parent_spec.get("panel")
    parent_portfolio = parent_spec.get("portfolio")
    if not all(
        isinstance(item, Mapping) and item
        for item in (parent_window, parent_label, parent_panel, parent_portfolio)
    ):
        raise EvoChildPreregistrationError([_token("parent_spec_contract_shape")])
    minimum_periods = parent_window.get("minimum_periods")
    if (
        isinstance(minimum_periods, bool)
        or not isinstance(minimum_periods, int)
        or minimum_periods < MINIMUM_FORMAL_DAILY_PERIODS
        or len(eligible) < minimum_periods + 2
    ):
        raise EvoChildPreregistrationError([_token("child_oos_window_too_short")])
    expected_is_window = f"{evidence.get('is_start')}/{evidence.get('is_end')}"
    parent_research_windows = parent_spec.get("research_windows")
    parent_conjecture = parent_contracts.get("research_conjecture")
    parent_conjecture_identity = (
        parent_conjecture.get("identity")
        if isinstance(parent_conjecture, Mapping)
        else None
    )
    parent_evidence = (
        parent_conjecture.get("evidence_policy")
        if isinstance(parent_conjecture, Mapping)
        else None
    )
    protected_evidence_fields = (
        "is_start",
        "is_end",
        "purge_days",
        "embargo_days",
        "trial_budget",
        "multiple_testing_policy",
        "forward_horizon",
        "transaction_cost_bps",
        "cost_model_id",
        "impact_model_id",
        "capacity_model_id",
        "universe_id",
        "investability_mask_id",
    )
    protected_evidence_matches = isinstance(parent_evidence, Mapping) and all(
        evidence.get(field) == parent_evidence.get(field)
        for field in protected_evidence_fields
        if field in parent_evidence or field in evidence
    )
    if (
        parent_spec.get("version") != METRIC_VERIFIER_SPEC_VERSION
        or parent_spec.get("verification_scope") != "production"
        or bool(parent_spec.get("dataset_snapshot_hash"))
        or parent_spec.get("report_id") != parent_report_id
        or parent_spec.get("factor_id") != conjecture.get("factor_id")
        or parent_spec.get("research_id") != identity.get("research_id")
        or parent_spec.get("claim_class") != conjecture.get("claim_class")
        or parent_spec.get("cost_policy_id") != evidence.get("cost_model_id")
        or not isinstance(parent_conjecture_identity, Mapping)
        or identity.get("data_catalog_snapshot_sha256")
        != parent_conjecture_identity.get("data_catalog_snapshot_sha256")
        or not protected_evidence_matches
        or conjecture.get("evaluation_contract")
        != parent_conjecture.get("evaluation_contract")
        or not isinstance(parent_research_windows, Mapping)
        or parent_research_windows.get("is_window") != expected_is_window
        or parent_window.get("universe_id") != evidence.get("universe_id")
        or parent_window.get("investability_mask_id")
        != evidence.get("investability_mask_id")
        or evidence.get("oos_start") != oos_start
        or evidence.get("oos_end") != oos_end
        or evidence.get("sealed_oos_token_hash")
        != allocation.get("sealed_token_sha256")
    ):
        raise EvoChildPreregistrationError(
            [_token("parent_child_protected_contract_binding")]
        )
    output = deepcopy(dict(parent_spec))
    output.update(
        {
            "report_id": child_report_id,
            "factor_id": conjecture.get("factor_id"),
            "research_id": identity.get("research_id"),
            "threshold_registration_ref": child_metric_verifier_spec_path(
                root, child_report_id
            ).with_name(
                f"threshold_registration__{child_report_id}.json"
            ).relative_to(root).as_posix(),
        }
    )
    research_windows = deepcopy(dict(parent_research_windows))
    research_windows.update(
        {
            "is_window": expected_is_window,
            "oos_window": f"{oos_start}/{oos_end}",
        }
    )
    output["research_windows"] = research_windows
    window = deepcopy(dict(parent_window))
    window.update(
        {
            "oos_window": f"{oos_start}/{oos_end}",
            "observed_start_date": signal_dates[0],
            "observed_end_date": signal_dates[-1],
            "oos_release_token_hash": allocation.get("sealed_token_sha256"),
            "search_trial_ledger_ref": child_control_paths(
                root, child_report_id
            )["search_trial_ledger"].relative_to(root).as_posix(),
            "oos_release_manifest_ref": (
                "objects/research_protocol/"
                f"oos_release_manifest__{child_report_id}.json"
            ),
        }
    )
    output["window_contract"] = window
    output["window_hash"] = stable_hash(window)
    return output


def project_authorized_evo_child_search_trial_ledger(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    base_search_trial_ledger: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Project the final immutable ledger before the Host builds thresholds.

    The function deliberately consumes the canonical public authorization and
    canonical parent addendum instead of accepting a detached addendum from an
    Agent.  It performs no writes.
    """

    root = Path(workspace_root).expanduser().resolve(strict=True)
    base = (
        dict(base_search_trial_ledger)
        if isinstance(base_search_trial_ledger, Mapping)
        else _load_source_object(
            base_search_trial_ledger,
            label="base_search_trial_ledger",
        )
    )
    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    return _project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        base_search_trial_ledger=base,
        execution_addendum=authorization.get("execution_addendum"),
    )


def project_evo_child_search_trial_ledger(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    base_search_trial_ledger: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Public, authorization-pinned child-ledger projection."""

    return project_authorized_evo_child_search_trial_ledger(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        base_search_trial_ledger=base_search_trial_ledger,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )


def projected_evo_child_search_trial_ledger_sha256(**kwargs: Any) -> str:
    return _payload_sha256(project_evo_child_search_trial_ledger(**kwargs))


def project_evo_child_metric_verifier_spec(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    research_conjecture: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Public, authorization-pinned deterministic child-spec projection."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    conjecture = (
        dict(research_conjecture)
        if isinstance(research_conjecture, Mapping)
        else _load_source_object(research_conjecture, label="research_conjecture")
    )
    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    return _project_evo_child_metric_verifier_spec(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        authorization=authorization,
    )


def _project_evo_child_threshold_registration(
    *,
    root: Path,
    child_report_id: str,
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the unique threshold object from already-authorized contracts."""

    parent_contracts = authorization.get("parent_contracts")
    parent_threshold = (
        parent_contracts.get("threshold_registration")
        if isinstance(parent_contracts, Mapping)
        else None
    )
    parent_rules = (
        parent_threshold.get("decision_rules")
        if isinstance(parent_threshold, Mapping)
        else None
    )
    freeze_sequence = ledger.get("freeze_sequence")
    if (
        not isinstance(parent_rules, list)
        or not parent_rules
        or any(not isinstance(item, Mapping) for item in parent_rules)
        or isinstance(freeze_sequence, bool)
        or not isinstance(freeze_sequence, int)
        or freeze_sequence < 0
    ):
        raise EvoChildPreregistrationError(
            [_token("threshold_projection_inputs")]
        )
    rules = [deepcopy(dict(item)) for item in parent_rules]
    output = {
        "version": METRIC_THRESHOLD_REGISTRATION_VERSION,
        "registration_status": "LOCKED",
        "report_id": child_report_id,
        "factor_id": metric_spec.get("factor_id"),
        "claim_class": metric_spec.get("claim_class"),
        "verification_scope": "production",
        "window_hash": stable_hash(metric_spec.get("window_contract")),
        "evaluation_contract_hash": evaluation_contract_hash(dict(metric_spec)),
        "label_contract_hash": stable_hash(metric_spec.get("label_contract")),
        "registered_before_evaluation": True,
        "registration_sequence": freeze_sequence + 1,
        "search_trial_ledger_ref": child_control_paths(
            root, child_report_id
        )["search_trial_ledger"].relative_to(root).as_posix(),
        "search_trial_ledger_sha256": _payload_sha256(ledger),
        "decision_rules": rules,
        "rule_set_sha256": stable_json_hash(rules),
    }
    reasons = _threshold_reasons(
        root=root,
        child_report_id=child_report_id,
        factor_id=str(metric_spec.get("factor_id") or ""),
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=output,
        authorization=authorization,
    )
    if reasons:
        raise EvoChildPreregistrationError(reasons)
    return output


def _projected_ledger_reasons(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    conjecture: Mapping[str, Any],
    ledger: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    try:
        identity = project_evo_child_search_identities(conjecture)
    except EvoChildPreregistrationError as exc:
        reasons.extend(exc.reasons)
        identity = {}
    if (
        ledger.get("candidate_space_sha256")
        != identity.get("candidate_space_sha256")
        or ledger.get("selected_hypothesis_sha256")
        != identity.get("selected_hypothesis_sha256")
    ):
        reasons.append(_token("search_identity_projection"))
    hypothesis_ids = {
        item.get("hypothesis_id")
        for item in conjecture.get("hypotheses") or []
        if isinstance(item, Mapping) and _safe_id(item.get("hypothesis_id"))
    }
    base_trials = [
        item
        for item in ledger.get("trials") or []
        if isinstance(item, Mapping)
        and item.get("trial_kind") != EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
    ]
    if any(
        item.get("status") not in _BASE_TRIAL_STATUSES
        or item.get("hypothesis_id") not in hypothesis_ids
        or bool(set(item) & _FORBIDDEN_BASE_TRIAL_RESULT_FIELDS)
        for item in base_trials
    ):
        reasons.append(_token("base_trial_preregistration_semantics"))
    reasons.extend(
        _token(f"shared_ledger_validator:{reason}")
        for reason in validate_frozen_child_execution_ledger(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            search_trial_ledger=ledger,
            execution_addendum=authorization.get("execution_addendum"),
        )
    )
    return list(dict.fromkeys(reasons))


def project_evo_child_threshold_registration(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    research_conjecture: Mapping[str, Any] | Path | str,
    search_trial_ledger: Mapping[str, Any] | Path | str,
    metric_verifier_spec: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Project, without writing, the only admissible child threshold."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    conjecture = _supplied_object(
        research_conjecture, label="research_conjecture"
    )
    ledger = _supplied_object(search_trial_ledger, label="search_trial_ledger")
    metric_spec = _supplied_object(
        metric_verifier_spec, label="metric_verifier_spec"
    )
    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    expected_spec = _project_evo_child_metric_verifier_spec(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        authorization=authorization,
    )
    if metric_spec != expected_spec:
        raise EvoChildPreregistrationError(
            [_token("metric_verifier_spec_not_exact_projection")]
        )
    reasons = _projected_ledger_reasons(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        ledger=ledger,
        authorization=authorization,
    )
    if reasons:
        raise EvoChildPreregistrationError(reasons)
    return _project_evo_child_threshold_registration(
        root=root,
        child_report_id=child_report_id,
        ledger=ledger,
        metric_spec=metric_spec,
        authorization=authorization,
    )


def _project_evo_child_web_research_plan(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    conjecture: Mapping[str, Any],
    approaches: Mapping[str, Any],
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    agent_authored_plan: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    """Freeze an Agent-authored child plan inside a Host governance envelope."""

    parent_contracts = authorization.get("parent_contracts")
    parent_plan = (
        parent_contracts.get("plan")
        if isinstance(parent_contracts, Mapping)
        else None
    )
    parent_plan_path = (
        parent_contracts.get("plan_path")
        if isinstance(parent_contracts, Mapping)
        else None
    )
    handoff = authorization.get("handoff")
    handoff = handoff if isinstance(handoff, Mapping) else {}
    selected = handoff.get("selected_revision")
    selected = selected if isinstance(selected, Mapping) else {}
    allocation = authorization.get("allocation")
    allocation = allocation if isinstance(allocation, Mapping) else {}
    allocation_window = allocation.get("oos_window")
    allocation_window = (
        allocation_window if isinstance(allocation_window, Mapping) else {}
    )
    conjecture_identity = conjecture.get("identity")
    conjecture_identity = (
        conjecture_identity if isinstance(conjecture_identity, Mapping) else {}
    )
    child_formula = selected.get("child_formula")
    raw_plan = deepcopy(dict(agent_authored_plan))
    if (
        not isinstance(parent_plan, Mapping)
        or not isinstance(parent_plan_path, Path)
        or not isinstance(child_formula, str)
        or not child_formula.strip()
        or not _is_sha256(selected.get("child_formula_hash"))
        or selected.get("child_formula_hash")
        != conjecture_identity.get("formula_hash")
        or handoff.get("parent_report_id") != parent_report_id
        or handoff.get("child_report_id") != child_report_id
        or allocation.get("report_id") != child_report_id
        or not _is_sha256(allocation.get("dataset_snapshot_sha256"))
        or not _is_sha256(allocation.get("sealed_token_sha256"))
        or not _is_sha256(allocation.get("sealed_carrier_sha256"))
        or not isinstance(allocation_window.get("start"), str)
        or not isinstance(allocation_window.get("end"), str)
    ):
        raise EvoChildPreregistrationError(
            [_token("child_web_plan_projection_inputs")]
        )
    from factor_factory.console.web_research_plan import (
        WebResearchPlanError,
        validate_authorized_evo_child_web_research_plan,
    )

    try:
        validate_authorized_evo_child_web_research_plan(
            workspace=root,
            parent_plan=dict(parent_plan),
            child_plan=raw_plan,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            research_conjecture=dict(conjecture),
            approach_registry=dict(approaches),
            fresh_oos_allocation=dict(allocation),
            selected_formula=child_formula,
            selected_formula_hash=str(selected.get("child_formula_hash") or ""),
        )
    except WebResearchPlanError as exc:
        raise EvoChildPreregistrationError(
            [_token(f"child_web_plan:{reason}") for reason in exc.reasons]
        ) from exc

    controls = child_control_paths(root, child_report_id)
    child_bindings = {
        "research_conjecture_ref": _payload_ref(
            root, controls["research_conjecture"], conjecture
        ),
        "approach_registry_ref": _payload_ref(
            root, controls["approach_registry"], approaches
        ),
        "search_trial_ledger_ref": _payload_ref(
            root, controls["search_trial_ledger"], ledger
        ),
        "metric_verifier_spec_ref": _payload_ref(
            root,
            child_metric_verifier_spec_path(root, child_report_id),
            metric_spec,
        ),
        "threshold_registration_ref": _payload_ref(
            root, controls["threshold_registration"], threshold
        ),
        "fresh_sealed_oos_allocation_ref": _file_ref(
            root, authorization["allocation_path"]
        ),
        "fresh_sealed_oos": {
            "allocation_id": allocation.get("allocation_id"),
            "dataset_snapshot_sha256": allocation["dataset_snapshot_sha256"],
            "oos_window": deepcopy(dict(allocation_window)),
            "sealed_token_sha256": allocation["sealed_token_sha256"],
            "sealed_carrier_sha256": allocation.get(
                "sealed_carrier_sha256"
            ),
            "release_state": allocation.get("release_state"),
            "consumed": allocation.get("consumed"),
        },
        "selected_revision": {
            "law_id": selected.get("law_id"),
            "delta_id": selected.get("delta_id"),
            "implementation_mode": selected.get("implementation_mode"),
            "child_formula": child_formula,
            "child_formula_hash": selected["child_formula_hash"],
            "projection_sha256": stable_json_hash(dict(selected)),
        },
    }
    core = {
        "contract_version": CHILD_WEB_RESEARCH_PLAN_PROJECTION_VERSION,
        "status": "FROZEN_NOT_EXECUTED",
        "canonical_path": child_web_research_plan_path(
            root, child_report_id
        ).relative_to(root).as_posix(),
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "factor_id": conjecture.get("factor_id"),
        "research_id": conjecture_identity.get("research_id"),
        "parent_web_research_plan_ref": _file_ref(root, parent_plan_path),
        "child_bindings": child_bindings,
        "web_research_plan": raw_plan,
        "web_research_plan_sha256": stable_json_hash(raw_plan),
        "authority": dict(_AUTHORITY),
    }
    return {**core, "content_sha256": stable_json_hash(core)}


def _project_child_web_factor_proof_targets(
    *,
    root: Path,
    raw_plan: Mapping[str, Any],
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    authorization: Mapping[str, Any],
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
    current_authority: bool = True,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Delegate proof-control schemas to the canonical pure Web projector."""

    from factor_factory.console.web_factor_proof import (
        project_web_factor_proof_preregistration_from_frozen_controls,
    )

    parent_contracts = authorization.get("parent_contracts")
    calendar = (
        parent_contracts.get("calendar")
        if isinstance(parent_contracts, Mapping)
        else None
    )
    allocation = authorization.get("allocation")
    allocation = allocation if isinstance(allocation, Mapping) else {}
    if not isinstance(calendar, Mapping):
        raise EvoChildPreregistrationError(
            [_token("child_web_proof_calendar_projection")]
        )
    try:
        projection = project_web_factor_proof_preregistration_from_frozen_controls(
            workspace_root=root,
            plan=dict(raw_plan),
            search_trial_ledger=dict(ledger),
            metric_verifier_spec=dict(metric_spec),
            threshold_registration=dict(threshold),
            calendar=deepcopy(dict(calendar)),
            oos_release_token_hash=str(
                allocation.get("sealed_token_sha256") or ""
            ),
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
            current_authority=current_authority,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise EvoChildPreregistrationError(
            [_token(f"child_web_proof_projection:{type(exc).__name__}:{exc}")]
        ) from exc
    preregistration_path = projection.get("preregistration_path")
    preregistration = projection.get("preregistration")
    component_artifacts = projection.get("component_artifacts")
    if (
        not isinstance(preregistration_path, Path)
        or not isinstance(preregistration, Mapping)
        or not isinstance(component_artifacts, list)
    ):
        raise EvoChildPreregistrationError(
            [_token("child_web_proof_projection_shape")]
        )
    targets: dict[str, tuple[Path, dict[str, Any]]] = {
        "web_factor_proof_preregistration": (
            preregistration_path,
            dict(preregistration),
        )
    }
    for index, item in enumerate(component_artifacts):
        if not isinstance(item, Mapping):
            raise EvoChildPreregistrationError(
                [_token("child_web_proof_component_shape")]
            )
        for kind in ("spec", "threshold"):
            path = item.get(f"{kind}_path")
            payload = item.get(kind)
            if not isinstance(path, Path) or not isinstance(payload, Mapping):
                raise EvoChildPreregistrationError(
                    [_token("child_web_proof_component_shape")]
                )
            targets[f"web_component_{index:03d}_{kind}"] = (path, dict(payload))
    return targets


def project_evo_child_web_research_plan(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    research_conjecture: Mapping[str, Any] | Path | str,
    approach_registry: Mapping[str, Any] | Path | str,
    search_trial_ledger: Mapping[str, Any] | Path | str,
    metric_verifier_spec: Mapping[str, Any] | Path | str,
    threshold_registration: Mapping[str, Any] | Path | str,
    agent_authored_child_web_research_plan: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
) -> dict[str, Any]:
    """Return the exact report-scoped child plan wrapper; perform no writes."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    conjecture = _supplied_object(
        research_conjecture, label="research_conjecture"
    )
    approaches = _supplied_object(approach_registry, label="approach_registry")
    ledger = _supplied_object(search_trial_ledger, label="search_trial_ledger")
    metric_spec = _supplied_object(
        metric_verifier_spec, label="metric_verifier_spec"
    )
    threshold = _supplied_object(
        threshold_registration, label="threshold_registration"
    )
    agent_plan = _supplied_object(
        agent_authored_child_web_research_plan,
        label="agent_authored_child_web_research_plan",
    )
    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    expected_spec = _project_evo_child_metric_verifier_spec(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        authorization=authorization,
    )
    expected_threshold = _project_evo_child_threshold_registration(
        root=root,
        child_report_id=child_report_id,
        ledger=ledger,
        metric_spec=expected_spec,
        authorization=authorization,
    )
    if metric_spec != expected_spec:
        raise EvoChildPreregistrationError(
            [_token("metric_verifier_spec_not_exact_projection")]
        )
    if threshold != expected_threshold:
        raise EvoChildPreregistrationError(
            [_token("threshold_registration_not_exact_projection")]
        )
    reasons = _projected_ledger_reasons(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        ledger=ledger,
        authorization=authorization,
    )
    if reasons:
        raise EvoChildPreregistrationError(reasons)
    envelope = _project_evo_child_web_research_plan(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        agent_authored_plan=agent_plan,
        authorization=authorization,
    )
    _project_child_web_factor_proof_targets(
        root=root,
        raw_plan=envelope["web_research_plan"],
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        authorization=authorization,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
    )
    return envelope


def _identity_reasons(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    state: Mapping[str, Any],
    conjecture: Mapping[str, Any],
    approaches: Mapping[str, Any],
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    handoff = authorization["handoff"]
    ticket = authorization["ticket"]
    parent_identity = handoff.get("parent_identity")
    parent_identity = parent_identity if isinstance(parent_identity, Mapping) else {}
    selected = handoff.get("selected_revision")
    selected = selected if isinstance(selected, Mapping) else {}
    ticket_selected = ticket.get("selected_revision")
    ticket_selected = ticket_selected if isinstance(ticket_selected, Mapping) else {}
    factor_id = parent_identity.get("factor_id")
    research_id = parent_identity.get("research_id")
    selected_formula_hash = selected.get("child_formula_hash")
    if (
        handoff.get("parent_report_id") != parent_report_id
        or handoff.get("child_report_id") != child_report_id
        or not _safe_id(factor_id)
        or not _safe_id(research_id)
        or not _is_sha256(selected_formula_hash)
        or ticket_selected.get("child_formula_hash") != selected_formula_hash
    ):
        reasons.append(_token("authorized_parent_child_identity"))
    conjecture_identity = conjecture.get("identity")
    conjecture_identity = (
        conjecture_identity if isinstance(conjecture_identity, Mapping) else {}
    )
    if any(
        value != child_report_id
        for value in (
            state.get("report_id"),
            conjecture.get("report_id"),
            approaches.get("report_id"),
            ledger.get("report_id"),
            metric_spec.get("report_id"),
            threshold.get("report_id"),
        )
    ):
        reasons.append(_token("child_report_identity"))
    if any(
        value != factor_id
        for value in (
            state.get("factor_id"),
            conjecture.get("factor_id"),
            ledger.get("factor_id"),
            metric_spec.get("factor_id"),
            threshold.get("factor_id"),
        )
    ):
        reasons.append(_token("factor_identity"))
    if threshold.get("claim_class") != conjecture.get("claim_class"):
        reasons.append(_token("threshold_claim_class_binding"))
    if (
        state.get("research_id") != research_id
        or conjecture_identity.get("research_id") != research_id
        or metric_spec.get("research_id") != research_id
        or state.get("round_id") != conjecture_identity.get("round_id")
    ):
        reasons.append(_token("research_identity"))
    if conjecture_identity.get("formula_hash") != selected_formula_hash:
        reasons.append(_token("child_formula_hash"))
    manifest_path = root / "manifest.json"
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or conjecture_identity.get("workspace_manifest_sha256")
        != sha256_file(manifest_path)
    ):
        reasons.append(_token("workspace_manifest_binding"))
    synthesis_ref = handoff.get("pre_oos_root_synthesis_ref")
    if (
        not isinstance(synthesis_ref, Mapping)
        or conjecture_identity.get("parent_artifact_sha256")
        != synthesis_ref.get("sha256")
    ):
        reasons.append(_token("parent_artifact_binding"))
    allocation = authorization["allocation"]
    if (
        allocation.get("report_id") != child_report_id
        or allocation.get("parent_report_id") != parent_report_id
        or not _is_sha256(allocation.get("dataset_snapshot_sha256"))
    ):
        reasons.append(_token("fresh_oos_dataset_binding"))
    state_budget = state.get("budget_used")
    evidence_policy = conjecture.get("evidence_policy")
    if not isinstance(state_budget, Mapping) or not isinstance(
        evidence_policy, Mapping
    ):
        reasons.append(_token("trial_budget_binding"))
    else:
        trial_budget = evidence_policy.get("trial_budget")
        if (
            state_budget.get("trial_budget") != trial_budget
            or state_budget.get("trials_used") != evidence_policy.get("trials_used")
            or isinstance(trial_budget, bool)
            or not isinstance(trial_budget, int)
            or ledger.get("trial_count", 0) > trial_budget
        ):
            reasons.append(_token("trial_budget_binding"))
    return reasons


def _threshold_reasons(
    *,
    root: Path,
    child_report_id: str,
    factor_id: str,
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> list[str]:
    controls = child_control_paths(root, child_report_id)
    expected_ref = controls["search_trial_ledger"].relative_to(root).as_posix()
    expected_sha = _payload_sha256(ledger)
    expected_contract_hashes = {
        "window_hash": stable_hash(metric_spec.get("window_contract")),
        "evaluation_contract_hash": evaluation_contract_hash(dict(metric_spec)),
        "label_contract_hash": stable_hash(metric_spec.get("label_contract")),
    }
    parent_contracts = authorization.get("parent_contracts")
    parent_threshold = (
        parent_contracts.get("threshold_registration")
        if isinstance(parent_contracts, Mapping)
        else None
    )
    parent_rules = (
        parent_threshold.get("decision_rules")
        if isinstance(parent_threshold, Mapping)
        else None
    )
    rules = threshold.get("decision_rules")
    if set(threshold) != _THRESHOLD_FIELDS:
        return [_token("threshold_fields")]
    reasons: list[str] = []
    if (
        threshold.get("version") != METRIC_THRESHOLD_REGISTRATION_VERSION
        or threshold.get("registration_status") != "LOCKED"
        or threshold.get("report_id") != child_report_id
        or threshold.get("factor_id") != factor_id
        or threshold.get("verification_scope") != "production"
        or threshold.get("registered_before_evaluation") is not True
        or threshold.get("search_trial_ledger_ref") != expected_ref
        or threshold.get("search_trial_ledger_sha256") != expected_sha
        or threshold.get("claim_class") != metric_spec.get("claim_class")
    ):
        reasons.append(_token("threshold_identity_or_ledger_binding"))
    if any(
        threshold.get(field) != expected
        for field, expected in expected_contract_hashes.items()
    ):
        reasons.append(_token("threshold_contract_hash_projection"))
    if (
        isinstance(threshold.get("registration_sequence"), bool)
        or not isinstance(threshold.get("registration_sequence"), int)
        or threshold.get("registration_sequence", 0)
        <= ledger.get("freeze_sequence", 0)
    ):
        reasons.append(_token("threshold_registration_order"))
    if (
        not isinstance(rules, list)
        or not rules
        or any(not isinstance(item, Mapping) for item in rules)
        or rules != parent_rules
        or threshold.get("rule_set_sha256") != stable_json_hash(rules)
    ):
        reasons.append(_token("threshold_protected_decision_rules"))
    else:
        try:
            validate_threshold_decision_rules(
                {
                    "version": METRIC_VERIFIER_SPEC_VERSION,
                    "claim_class": threshold.get("claim_class"),
                },
                [dict(item) for item in rules],
            )
        except (TypeError, ValueError) as exc:
            reasons.append(_token(f"threshold_decision_rules:{exc}"))
    return reasons


def _validate_inputs(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    state: Mapping[str, Any],
    conjecture: Mapping[str, Any],
    approaches: Mapping[str, Any],
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(validate_research_state(dict(state)))
    reasons.extend(validate_research_conjecture(dict(conjecture)))
    reasons.extend(validate_approach_registry(dict(approaches), stage="pre_council"))
    if not epistemic_evolution_enabled(dict(conjecture)):
        reasons.append(_token("child_evo_v2_required"))
    try:
        search_identity = project_evo_child_search_identities(conjecture)
    except EvoChildPreregistrationError as exc:
        reasons.extend(exc.reasons)
        search_identity = {}
    if (
        ledger.get("candidate_space_sha256")
        != search_identity.get("candidate_space_sha256")
        or ledger.get("selected_hypothesis_sha256")
        != search_identity.get("selected_hypothesis_sha256")
    ):
        reasons.append(_token("search_identity_projection"))
    hypothesis_ids = {
        item.get("hypothesis_id")
        for item in conjecture.get("hypotheses") or []
        if isinstance(item, Mapping) and _safe_id(item.get("hypothesis_id"))
    }
    base_trials = [
        item
        for item in ledger.get("trials") or []
        if isinstance(item, Mapping)
        and item.get("trial_kind") != EVO_TRANSFER_DIAGNOSTIC_TRIAL_KIND
    ]
    if any(
        item.get("status") not in _BASE_TRIAL_STATUSES
        or item.get("hypothesis_id") not in hypothesis_ids
        or bool(set(item) & _FORBIDDEN_BASE_TRIAL_RESULT_FIELDS)
        for item in base_trials
    ):
        reasons.append(_token("base_trial_preregistration_semantics"))
    reasons.extend(
        _identity_reasons(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            state=state,
            conjecture=conjecture,
            approaches=approaches,
            ledger=ledger,
            metric_spec=metric_spec,
            threshold=threshold,
            authorization=authorization,
        )
    )
    reasons.extend(
        _threshold_reasons(
            root=root,
            child_report_id=child_report_id,
            factor_id=str(ledger.get("factor_id") or ""),
            ledger=ledger,
            metric_spec=metric_spec,
            threshold=threshold,
            authorization=authorization,
        )
    )
    reasons.extend(
        _token(f"shared_ledger_validator:{reason}")
        for reason in validate_frozen_child_execution_ledger(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            search_trial_ledger=ledger,
            execution_addendum=authorization.get("execution_addendum"),
        )
    )
    return list(dict.fromkeys(reasons))


def _freeze_payloads(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    state: Mapping[str, Any],
    conjecture: Mapping[str, Any],
    approaches: Mapping[str, Any],
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    child_web_plan: Mapping[str, Any],
    web_proof_targets: Mapping[str, tuple[Path, Mapping[str, Any]]],
    authorization: Mapping[str, Any],
    authoring: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    controls = child_control_paths(root, child_report_id)
    preregistered_refs = {
        "research_state": _payload_ref(
            root, controls["research_state"], state
        ),
        "research_conjecture": _payload_ref(
            root, controls["research_conjecture"], conjecture
        ),
        "approach_registry": _payload_ref(
            root, controls["approach_registry"], approaches
        ),
        "search_trial_ledger": _payload_ref(
            root, controls["search_trial_ledger"], ledger
        ),
        "metric_verifier_spec": _payload_ref(
            root,
            child_metric_verifier_spec_path(root, child_report_id),
            metric_spec,
        ),
        "threshold_registration": _payload_ref(
            root, controls["threshold_registration"], threshold
        ),
        "child_web_research_plan": _payload_ref(
            root,
            child_web_research_plan_path(root, child_report_id),
            child_web_plan,
        ),
        "fresh_sealed_oos_allocation": _file_ref(
            root, authorization["allocation_path"]
        ),
        "agent_authoring_admission": _file_ref(
            root, authoring["admission_path"]
        ),
    }
    for name, (path, payload) in sorted(web_proof_targets.items()):
        preregistered_refs[name] = _payload_ref(root, path, payload)
    dataset_snapshot = authorization["allocation"].get("dataset_snapshot_sha256")
    window_hash = stable_json_hash(preregistered_refs)
    parent_contracts = authorization["parent_contracts"]
    parent_protected_contract_refs = {
        "web_research_plan": _file_ref(root, parent_contracts["plan_path"]),
        "research_conjecture": _file_ref(
            root, parent_contracts["research_conjecture_path"]
        ),
        "metric_verifier_spec": _file_ref(
            root, parent_contracts["metric_verifier_spec_path"]
        ),
        "threshold_registration": _file_ref(
            root, parent_contracts["threshold_registration_path"]
        ),
        "web_factor_proof_preregistration": _file_ref(
            root, parent_contracts["web_preregistration_path"]
        ),
    }
    verifier = {
        "contract_version": CHILD_PREDICTION_FREEZE_VERIFIER_VERSION,
        "report_id": child_report_id,
        "parent_report_id": parent_report_id,
        "verifier_id": CHILD_PREDICTION_FREEZE_VERIFIER_ID,
        "verifier_status": "PASS",
        "dataset_snapshot_hash": dataset_snapshot,
        "window_hash": window_hash,
        "information_set": "PREREGISTRATION_ONLY_NO_EMPIRICAL_EVIDENCE",
        "oos_accessed": False,
        "authorization_ticket_ref": _file_ref(
            root, authorization["authorization_path"]
        ),
        "expected_host_trust_manifest_sha256": authorization[
            "expected_host_trust_manifest_sha256"
        ],
        "preregistered_artifact_refs": preregistered_refs,
        "source_parent_protected_contract_refs": parent_protected_contract_refs,
        "execution_test_count": len(
            authorization.get("execution_addendum", {}).get("execution_tests") or []
        )
        if isinstance(authorization.get("execution_addendum"), Mapping)
        else 0,
        "execution_tests_sha256": stable_json_hash(
            authorization.get("execution_addendum", {}).get("execution_tests") or []
        )
        if isinstance(authorization.get("execution_addendum"), Mapping)
        else stable_json_hash([]),
        "execution_verifier_source_bundle": dict(
            authorization["execution_verifier_source_bundle"]
        ),
        "authority": dict(_AUTHORITY),
    }
    verifier_path = child_prediction_freeze_verifier_path(root, child_report_id)
    evidence_ref = {
        "path": verifier_path.relative_to(root).as_posix(),
        "sha256": _payload_sha256(verifier),
        "dataset_snapshot_hash": dataset_snapshot,
        "window_hash": window_hash,
        "verifier_id": CHILD_PREDICTION_FREEZE_VERIFIER_ID,
        "verifier_status": "PASS",
    }
    lifecycle = build_epistemic_evolution_lifecycle(
        report_id=child_report_id,
        to_state="PREDICTIONS_FROZEN",
        evidence_refs=[evidence_ref],
    )
    return verifier, lifecycle


def _target_payloads(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    state: Mapping[str, Any],
    conjecture: Mapping[str, Any],
    approaches: Mapping[str, Any],
    ledger: Mapping[str, Any],
    metric_spec: Mapping[str, Any],
    threshold: Mapping[str, Any],
    child_web_plan: Mapping[str, Any],
    web_proof_targets: Mapping[str, tuple[Path, Mapping[str, Any]]],
    authorization: Mapping[str, Any],
    authoring: Mapping[str, Any],
) -> dict[str, tuple[Path, dict[str, Any]]]:
    controls = child_control_paths(root, child_report_id)
    protocol = research_protocol_paths(root, child_report_id)
    verifier, lifecycle = _freeze_payloads(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        state=state,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        child_web_plan=child_web_plan,
        web_proof_targets=web_proof_targets,
        authorization=authorization,
        authoring=authoring,
    )
    targets: dict[str, tuple[Path, dict[str, Any]]] = {
        "prediction_freeze_verifier": (
            child_prediction_freeze_verifier_path(root, child_report_id),
            verifier,
        ),
        "evo_lifecycle": (protocol["evo_lifecycle"], lifecycle),
        "evo_lifecycle_snapshot": (
            epistemic_evolution_lifecycle_snapshot_path(root, child_report_id, 1),
            lifecycle,
        ),
        "research_state": (controls["research_state"], dict(state)),
        "research_conjecture": (
            controls["research_conjecture"],
            dict(conjecture),
        ),
        "approach_registry": (controls["approach_registry"], dict(approaches)),
        "search_trial_ledger": (controls["search_trial_ledger"], dict(ledger)),
        "metric_verifier_spec": (
            child_metric_verifier_spec_path(root, child_report_id),
            dict(metric_spec),
        ),
        "child_web_research_plan": (
            child_web_research_plan_path(root, child_report_id),
            dict(child_web_plan),
        ),
        "threshold_registration": (
            controls["threshold_registration"],
            dict(threshold),
        ),
    }
    for name, (path, payload) in web_proof_targets.items():
        if name in targets:
            raise EvoChildPreregistrationError(
                [_token(f"duplicate_web_proof_target:{name}")]
            )
        targets[name] = (path, dict(payload))
    return targets


def _write_once(root: Path, path: Path, payload: Mapping[str, Any]) -> bool:
    expected = canonical_json_bytes(payload)
    parent = _safe_parent(root, path)
    if parent != path.parent:
        raise EvoChildPreregistrationError([_token(f"unsafe_output:{path.name}")])
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise EvoChildPreregistrationError(
                [_token(f"immutable_output_conflict:{path.name}")]
            )
        return False
    descriptor, raw = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(raw)
    os.fchmod(descriptor, 0o600)
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("child_preregistration_short_write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise EvoChildPreregistrationError(
                    [_token(f"immutable_output_conflict:{path.name}")]
                )
            return False
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _preflight_targets(
    root: Path,
    targets: Mapping[str, tuple[Path, Mapping[str, Any]]],
    receipt_path: Path,
    receipt: Mapping[str, Any],
) -> None:
    """Reject unsafe/conflicting destinations before the first artifact write."""

    seen: set[Path] = set()
    for name, (path, payload) in [
        *targets.items(),
        ("preregistration_receipt", (receipt_path, receipt)),
    ]:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            raise EvoChildPreregistrationError([_token(f"duplicate_target:{name}")])
        seen.add(resolved)
        _safe_parent(root, path)
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise EvoChildPreregistrationError(
                    [_token(f"unsafe_existing_target:{name}")]
                )
            if path.read_bytes() != canonical_json_bytes(payload):
                raise EvoChildPreregistrationError(
                    [_token(f"immutable_output_conflict:{path.name}")]
                )


def _receipt_payload(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    ledger: Mapping[str, Any],
    targets: Mapping[str, tuple[Path, Mapping[str, Any]]],
    authorization: Mapping[str, Any],
    authoring: Mapping[str, Any],
) -> dict[str, Any]:
    refs = {
        name: _payload_ref(root, path, payload)
        for name, (path, payload) in sorted(targets.items())
    }
    core = {
        "contract_version": CHILD_PREREGISTRATION_VERSION,
        "status": CHILD_PREREGISTRATION_STATUS,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "factor_id": ledger["factor_id"],
        "authorization_ticket_ref": _file_ref(
            root, authorization["authorization_path"]
        ),
        "agent_authoring_admission_ref": _file_ref(
            root, authoring["admission_path"]
        ),
        "agent_authoring_semantic_bundle_ref": _file_ref(
            root, authoring["semantic_bundle_path"]
        ),
        "expected_host_trust_manifest_sha256": authorization[
            "expected_host_trust_manifest_sha256"
        ],
        "memory_state": authorization["ticket"]["memory_state"],
        "execution_addendum_ref": (
            _file_ref(root, authorization["execution_addendum_path"])
            if authorization.get("execution_addendum_path") is not None
            else None
        ),
        "source_parent_protected_contract_refs": {
            "web_research_plan": _file_ref(
                root, authorization["parent_contracts"]["plan_path"]
            ),
            "research_conjecture": _file_ref(
                root,
                authorization["parent_contracts"]["research_conjecture_path"],
            ),
            "metric_verifier_spec": _file_ref(
                root,
                authorization["parent_contracts"]["metric_verifier_spec_path"],
            ),
            "threshold_registration": _file_ref(
                root,
                authorization["parent_contracts"]["threshold_registration_path"],
            ),
            "web_factor_proof_preregistration": _file_ref(
                root,
                authorization["parent_contracts"]["web_preregistration_path"],
            ),
        },
        "frozen_artifact_refs": refs,
        "execution_trial_count": len(
            expected_evo_child_execution_trials(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                execution_addendum=authorization.get("execution_addendum"),
            )
        ),
        "execution_verifier_source_bundle": dict(
            authorization["execution_verifier_source_bundle"]
        ),
        "ready_ticket_state": "ELIGIBLE_FOR_SEPARATE_HOST_SIGNATURE",
        "authority": dict(_AUTHORITY),
    }
    return {**core, "content_sha256": stable_json_hash(core)}


@contextmanager
def _lock(root: Path, child_report_id: str) -> Iterator[None]:
    path = child_preregistration_receipt_path(root, child_report_id).with_suffix(
        ".lock"
    )
    _safe_parent(root, path)
    descriptor = os.open(
        path,
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvoChildPreregistrationError([_token("lock_not_regular")])
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _readback_reasons(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    targets: Mapping[str, tuple[Path, Mapping[str, Any]]],
    authorization: Mapping[str, Any],
    authoring: Mapping[str, Any],
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
    current_authority: bool = True,
) -> list[str]:
    reasons: list[str] = []
    for name, (path, payload) in targets.items():
        if (
            not _within_without_symlinks(root, path)
            or path.is_symlink()
            or not path.is_file()
            or path.read_bytes() != canonical_json_bytes(payload)
        ):
            reasons.append(_token(f"readback:{name}"))
    lifecycle = targets["evo_lifecycle"][1]
    reasons.extend(
        _token(f"lifecycle:{reason}")
        for reason in validate_epistemic_evolution_lifecycle(
            dict(lifecycle),
            report_id=child_report_id,
            workspace_root=root,
        )
    )
    protocol = validate_protocol_bundle(
        root=root,
        report_id=child_report_id,
        stage="pre_council",
    )
    if protocol.get("verdict") != "PASS":
        reasons.append(_token("protocol_pre_council"))
        reasons.extend(
            _token(f"protocol:{reason}")
            for reason in protocol.get("block_reasons") or []
        )
    ledger = targets["search_trial_ledger"][1]
    reasons.extend(
        _token(f"shared_ledger_readback:{reason}")
        for reason in validate_frozen_child_execution_ledger(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            search_trial_ledger=ledger,
            execution_addendum=authorization.get("execution_addendum"),
        )
    )
    envelope = targets.get("child_web_research_plan", (None, {}))[1]
    raw_plan = (
        envelope.get("web_research_plan")
        if isinstance(envelope, Mapping)
        else None
    )
    if not isinstance(raw_plan, Mapping):
        reasons.append(_token("child_web_plan_readback"))
    else:
        try:
            projected = _project_child_web_factor_proof_targets(
                root=root,
                raw_plan=raw_plan,
                ledger=targets["search_trial_ledger"][1],
                metric_spec=targets["metric_verifier_spec"][1],
                threshold=targets["threshold_registration"][1],
                authorization=authorization,
                incident_trust_root=incident_trust_root,
                incident_installation_id=incident_installation_id,
                _incident_guard=_incident_guard,
                current_authority=current_authority,
            )
        except (EvoChildPreregistrationError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            reasons.append(
                _token(f"child_web_proof_readback:{type(exc).__name__}:{exc}")
            )
        else:
            if any(
                name not in targets
                or targets[name][0] != path
                or targets[name][1] != payload
                for name, (path, payload) in projected.items()
            ):
                reasons.append(_token("child_web_proof_readback"))
    try:
        replayed_authoring = _validated_agent_authoring(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            agent_authoring_admission=authoring["admission_path"],
            expected_host_trust_manifest_sha256=authorization[
                "expected_host_trust_manifest_sha256"
            ],
        )
    except EvoChildPreregistrationError as exc:
        reasons.extend(exc.reasons)
    else:
        if replayed_authoring.get("semantic_bundle") != authoring.get(
            "semantic_bundle"
        ):
            reasons.append(_token("agent_authoring_readback"))
    return list(dict.fromkeys(reasons))


def _supplied_object(
    value: Mapping[str, Any] | Path | str,
    *,
    label: str,
) -> dict[str, Any]:
    return (
        dict(value)
        if isinstance(value, Mapping)
        else _load_source_object(value, label=label)
    )


def _source_binding_reasons(
    authorization: Mapping[str, Any],
    authoring: Mapping[str, Any] | None = None,
) -> list[str]:
    snapshots = authorization.get("source_file_sha256s")
    if not isinstance(snapshots, Mapping) or not snapshots:
        return [_token("source_file_snapshots_required")]
    reasons: list[str] = []
    for raw_path, expected_sha256 in snapshots.items():
        path = raw_path if isinstance(raw_path, Path) else Path(str(raw_path))
        if (
            not _is_sha256(expected_sha256)
            or path.is_symlink()
            or not path.is_file()
            or sha256_file(path) != expected_sha256
        ):
            reasons.append(_token(f"source_file_changed:{path.name}"))
    expected_bundle = authorization.get("execution_verifier_source_bundle")
    try:
        observed_bundle = verifier_source_bundle()
    except (OSError, EvoChildPreregistrationError, ValueError) as exc:
        reasons.append(
            _token(f"execution_verifier_source_replay:{type(exc).__name__}")
        )
    else:
        if observed_bundle != expected_bundle:
            reasons.append(_token("execution_verifier_source_bundle_changed"))
    if isinstance(authoring, Mapping):
        authoring_snapshots = authoring.get("source_file_sha256s")
        if not isinstance(authoring_snapshots, Mapping) or not authoring_snapshots:
            reasons.append(_token("agent_authoring_source_snapshots_required"))
        else:
            for raw_path, expected_sha256 in authoring_snapshots.items():
                path = raw_path if isinstance(raw_path, Path) else Path(str(raw_path))
                if (
                    not _is_sha256(expected_sha256)
                    or path.is_symlink()
                    or not path.is_file()
                    or sha256_file(path) != expected_sha256
                ):
                    reasons.append(
                        _token(f"agent_authoring_source_changed:{path.name}")
                    )
    return reasons


def _validated_agent_authoring(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    agent_authoring_admission: Path | str | None,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    if agent_authoring_admission is None or isinstance(
        agent_authoring_admission, Mapping
    ):
        raise EvoChildPreregistrationError(
            [_token("agent_authoring_admission_canonical_path_required")]
        )
    from factor_factory.evo_child_authoring import (
        EvoChildAuthoringError,
        validate_evo_child_authoring_admission,
    )

    try:
        return validate_evo_child_authoring_admission(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            agent_authoring_admission=agent_authoring_admission,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
    except EvoChildAuthoringError as exc:
        raise EvoChildPreregistrationError(
            [_token(f"agent_authoring:{reason}") for reason in exc.reasons]
        ) from exc


def _validated_bundle(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    research_state: Mapping[str, Any] | Path | str,
    research_conjecture: Mapping[str, Any] | Path | str,
    approach_registry: Mapping[str, Any] | Path | str,
    base_search_trial_ledger: Mapping[str, Any] | Path | str,
    metric_verifier_spec: Mapping[str, Any] | Path | str,
    threshold_registration: Mapping[str, Any] | Path | str,
    agent_authored_child_web_research_plan: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
    agent_authoring_admission: Path | str | None,
    incident_trust_root: Path | str | None,
    incident_installation_id: str | None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
    ):
        raise EvoChildPreregistrationError([_token("report_identity")])
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=root,
        report_id=child_report_id,
        trust_root=(
            Path(incident_trust_root)
            if incident_trust_root is not None
            else None
        ),
        installation_id=incident_installation_id,
    )
    if incident_reasons:
        raise EvoChildPreregistrationError(incident_reasons)
    if _incident_guard is not None:
        if incident_trust_root is None or not incident_installation_id:
            raise EvoChildPreregistrationError(
                [_token("incident_host_context_incomplete")]
            )
        try:
            validate_oos_exposure_private_registry_guard(
                _incident_guard,
                trust_root=Path(incident_trust_root),
                installation_id=incident_installation_id,
            )
        except (OSError, ValueError) as exc:
            raise EvoChildPreregistrationError([str(exc)]) from exc
    state = _supplied_object(research_state, label="research_state")
    conjecture = _supplied_object(
        research_conjecture, label="research_conjecture"
    )
    approaches = _supplied_object(approach_registry, label="approach_registry")
    base_ledger = _supplied_object(
        base_search_trial_ledger, label="base_search_trial_ledger"
    )
    supplied_metric_spec = _supplied_object(
        metric_verifier_spec, label="metric_verifier_spec"
    )
    threshold = _supplied_object(
        threshold_registration, label="threshold_registration"
    )
    agent_plan = _supplied_object(
        agent_authored_child_web_research_plan,
        label="agent_authored_child_web_research_plan",
    )
    authoring = _validated_agent_authoring(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        agent_authoring_admission=agent_authoring_admission,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    ledger = _project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        base_search_trial_ledger=base_ledger,
        execution_addendum=authorization.get("execution_addendum"),
    )
    expected_metric_spec = _project_evo_child_metric_verifier_spec(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        authorization=authorization,
    )
    if supplied_metric_spec != expected_metric_spec:
        raise EvoChildPreregistrationError(
            [_token("metric_verifier_spec_not_exact_projection")]
        )
    expected_threshold = _project_evo_child_threshold_registration(
        root=root,
        child_report_id=child_report_id,
        ledger=ledger,
        metric_spec=supplied_metric_spec,
        authorization=authorization,
    )
    reasons = _validate_inputs(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        state=state,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=supplied_metric_spec,
        threshold=threshold,
        authorization=authorization,
    )
    if reasons:
        raise EvoChildPreregistrationError(reasons)
    if threshold != expected_threshold:
        raise EvoChildPreregistrationError(
            [_token("threshold_registration_not_exact_projection")]
        )
    admitted_bundle = authoring.get("semantic_bundle")
    supplied_agent_semantics = {
        "research_state": state,
        "research_conjecture": conjecture,
        "approach_registry": approaches,
        "base_search_trial_ledger": base_ledger,
        "agent_authored_child_web_research_plan": agent_plan,
    }
    if not isinstance(admitted_bundle, Mapping):
        raise EvoChildPreregistrationError(
            [_token("agent_authoring_semantic_bundle_required")]
        )
    mismatches = [
        name
        for name, payload in supplied_agent_semantics.items()
        if admitted_bundle.get(name) != payload
    ]
    if mismatches or set(admitted_bundle) != set(supplied_agent_semantics):
        raise EvoChildPreregistrationError(
            [
                _token(f"agent_authoring_bundle_mismatch:{name}")
                for name in (mismatches or ["shape"])
            ]
        )
    child_web_plan = _project_evo_child_web_research_plan(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=supplied_metric_spec,
        threshold=threshold,
        agent_authored_plan=agent_plan,
        authorization=authorization,
    )
    web_proof_targets = _project_child_web_factor_proof_targets(
        root=root,
        raw_plan=child_web_plan["web_research_plan"],
        ledger=ledger,
        metric_spec=supplied_metric_spec,
        threshold=threshold,
        authorization=authorization,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    source_reasons = _source_binding_reasons(authorization, authoring)
    if source_reasons:
        raise EvoChildPreregistrationError(source_reasons)
    return {
        "root": root,
        "state": state,
        "conjecture": conjecture,
        "approaches": approaches,
        "ledger": ledger,
        "metric_spec": supplied_metric_spec,
        "threshold": threshold,
        "child_web_plan": child_web_plan,
        "web_proof_targets": web_proof_targets,
        "authorization": authorization,
        "authoring": authoring,
    }


def validate_evo_child_preregistration_inputs(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    research_state: Mapping[str, Any] | Path | str,
    research_conjecture: Mapping[str, Any] | Path | str,
    approach_registry: Mapping[str, Any] | Path | str,
    base_search_trial_ledger: Mapping[str, Any] | Path | str,
    metric_verifier_spec: Mapping[str, Any] | Path | str,
    threshold_registration: Mapping[str, Any] | Path | str,
    agent_authored_child_web_research_plan: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
    agent_authoring_admission: Path | str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
) -> dict[str, Any]:
    """Fail-closed, read-only validation using the out-of-band trust pin."""

    bundle = _validated_bundle(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        research_state=research_state,
        research_conjecture=research_conjecture,
        approach_registry=approach_registry,
        base_search_trial_ledger=base_search_trial_ledger,
        metric_verifier_spec=metric_verifier_spec,
        threshold_registration=threshold_registration,
        agent_authored_child_web_research_plan=(
            agent_authored_child_web_research_plan
        ),
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        agent_authoring_admission=agent_authoring_admission,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
    )
    return {
        "verdict": "PASS",
        "status": "VALIDATED_NOT_MATERIALIZED",
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "projected_search_trial_ledger_sha256": _payload_sha256(bundle["ledger"]),
        "projected_metric_verifier_spec_sha256": _payload_sha256(
            bundle["metric_spec"]
        ),
        "threshold_registration_sha256": _payload_sha256(bundle["threshold"]),
        "child_web_research_plan_sha256": _payload_sha256(
            bundle["child_web_plan"]
        ),
        "writes_performed": False,
        "authority": dict(_AUTHORITY),
    }


def materialize_evo_child_preregistration(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    research_state: Mapping[str, Any] | Path | str,
    research_conjecture: Mapping[str, Any] | Path | str,
    approach_registry: Mapping[str, Any] | Path | str,
    base_search_trial_ledger: Mapping[str, Any] | Path | str,
    metric_verifier_spec: Mapping[str, Any] | Path | str,
    threshold_registration: Mapping[str, Any] | Path | str,
    agent_authored_child_web_research_plan: Mapping[str, Any] | Path | str,
    expected_host_trust_manifest_sha256: str,
    agent_authoring_admission: Path | str | None = None,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    trust_raw = (
        str(incident_trust_root)
        if incident_trust_root is not None
        else os.environ.get(OOS_EXPOSURE_TRUST_ROOT_ENV)
        or os.environ.get("FACTORFORGE_OOS_HOST_TRUST_ROOT")
    )
    resolved_installation = (
        incident_installation_id
        or os.environ.get(OOS_EXPOSURE_INSTALLATION_ID_ENV)
        or os.environ.get("FACTORFORGE_OOS_HOST_INSTALLATION_ID")
    )
    if not trust_raw or not resolved_installation:
        raise EvoChildPreregistrationError(
            [_token("incident_host_context_required")]
        )
    trust = Path(trust_raw).expanduser().resolve(strict=True)
    if _incident_guard is None:
        with oos_exposure_private_registry_guard(
            trust,
            installation_id=resolved_installation,
        ) as guard:
            return materialize_evo_child_preregistration(
                workspace_root=workspace_root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                research_state=research_state,
                research_conjecture=research_conjecture,
                approach_registry=approach_registry,
                base_search_trial_ledger=base_search_trial_ledger,
                metric_verifier_spec=metric_verifier_spec,
                threshold_registration=threshold_registration,
                agent_authored_child_web_research_plan=(
                    agent_authored_child_web_research_plan
                ),
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                agent_authoring_admission=agent_authoring_admission,
                incident_trust_root=trust,
                incident_installation_id=resolved_installation,
                _incident_guard=guard,
            )
    bundle = _validated_bundle(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        research_state=research_state,
        research_conjecture=research_conjecture,
        approach_registry=approach_registry,
        base_search_trial_ledger=base_search_trial_ledger,
        metric_verifier_spec=metric_verifier_spec,
        threshold_registration=threshold_registration,
        agent_authored_child_web_research_plan=(
            agent_authored_child_web_research_plan
        ),
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        agent_authoring_admission=agent_authoring_admission,
        incident_trust_root=trust,
        incident_installation_id=resolved_installation,
        _incident_guard=_incident_guard,
    )
    root = bundle["root"]
    state = bundle["state"]
    conjecture = bundle["conjecture"]
    approaches = bundle["approaches"]
    ledger = bundle["ledger"]
    metric_spec = bundle["metric_spec"]
    threshold = bundle["threshold"]
    child_web_plan = bundle["child_web_plan"]
    web_proof_targets = bundle["web_proof_targets"]
    authorization = bundle["authorization"]
    authoring = bundle["authoring"]
    targets = _target_payloads(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        state=state,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        child_web_plan=child_web_plan,
        web_proof_targets=web_proof_targets,
        authorization=authorization,
        authoring=authoring,
    )
    receipt_path = child_preregistration_receipt_path(root, child_report_id)
    receipt = _receipt_payload(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        ledger=ledger,
        targets=targets,
        authorization=authorization,
        authoring=authoring,
    )
    _preflight_targets(root, targets, receipt_path, receipt)
    with _lock(root, child_report_id):
        source_reasons = _source_binding_reasons(authorization, authoring)
        if source_reasons:
            raise EvoChildPreregistrationError(source_reasons)
        written: list[str] = []
        component_names = sorted(
            name for name in targets if name.startswith("web_component_")
        )
        publish_order: list[str] = []
        for name in _PUBLISH_ORDER:
            if name == "web_factor_proof_preregistration":
                publish_order.extend(component_names)
            publish_order.append(name)
        if set(publish_order) != set(targets):
            raise EvoChildPreregistrationError(
                [_token("publish_order_target_mismatch")]
            )
        for name in publish_order:
            if name == "threshold_registration":
                source_reasons = _source_binding_reasons(
                    authorization, authoring
                )
                if source_reasons:
                    raise EvoChildPreregistrationError(source_reasons)
            path, payload = targets[name]
            if _write_once(root, path, payload):
                written.append(name)
        readback = _readback_reasons(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            targets=targets,
            authorization=authorization,
            authoring=authoring,
            incident_trust_root=trust,
            incident_installation_id=resolved_installation,
            _incident_guard=_incident_guard,
        )
        if readback:
            raise EvoChildPreregistrationError(readback)
        source_reasons = _source_binding_reasons(authorization, authoring)
        if source_reasons:
            raise EvoChildPreregistrationError(source_reasons)
        receipt_written = _write_once(root, receipt_path, receipt)
        if receipt_path.read_bytes() != canonical_json_bytes(receipt):
            raise EvoChildPreregistrationError([_token("receipt_readback")])
    return {
        "verdict": "PASS",
        "status": CHILD_PREREGISTRATION_STATUS,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "receipt_ref": _file_ref(root, receipt_path),
        "written_artifacts": written,
        "receipt_written": receipt_written,
        "idempotent_replay": not written and not receipt_written,
        "next_gate": "HOST_SIGN_PUBLIC_MATERIALIZATION_READY_TICKET",
        "authority": dict(_AUTHORITY),
    }


def _replay_materialized_evo_child_preregistration(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
    current_authority: bool,
) -> dict[str, Any]:
    """Recompute every materialized byte from canonical signed authority."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
    ):
        raise EvoChildPreregistrationError([_token("report_identity")])
    if current_authority:
        if incident_trust_root is None or not incident_installation_id:
            raise EvoChildPreregistrationError(
                [_token("incident_host_context_required")]
            )
        try:
            validate_oos_exposure_private_registry_guard(
                _incident_guard,
                trust_root=Path(incident_trust_root),
                installation_id=incident_installation_id,
            )
        except (OSError, ValueError) as exc:
            raise EvoChildPreregistrationError(
                [_token(f"incident_guard:{type(exc).__name__}")]
            ) from exc
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=root,
            report_id=child_report_id,
            trust_root=Path(incident_trust_root),
            installation_id=incident_installation_id,
        )
        if incident_reasons:
            raise EvoChildPreregistrationError(incident_reasons)
    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    from factor_factory.evo_child_authoring import (
        evo_child_authoring_admission_path,
    )

    authoring = _validated_agent_authoring(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        agent_authoring_admission=evo_child_authoring_admission_path(
            root, child_report_id
        ),
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    admitted_bundle = authoring.get("semantic_bundle")
    if not isinstance(admitted_bundle, Mapping):
        raise EvoChildPreregistrationError(
            [_token("agent_authoring_semantic_bundle_required")]
        )
    controls = child_control_paths(root, child_report_id)
    state = _load_source_object(controls["research_state"], label="research_state")
    conjecture = _load_source_object(
        controls["research_conjecture"], label="research_conjecture"
    )
    approaches = _load_source_object(
        controls["approach_registry"], label="approach_registry"
    )
    ledger = _load_source_object(
        controls["search_trial_ledger"], label="search_trial_ledger"
    )
    metric_spec = _load_source_object(
        child_metric_verifier_spec_path(root, child_report_id),
        label="metric_verifier_spec",
    )
    threshold = _load_source_object(
        controls["threshold_registration"], label="threshold_registration"
    )
    plan_path = child_web_research_plan_path(root, child_report_id)
    persisted_projection = _load_source_object(
        plan_path, label="child_web_research_plan"
    )
    raw_plan = persisted_projection.get("web_research_plan")
    if not isinstance(raw_plan, Mapping):
        raise EvoChildPreregistrationError([_token("child_web_plan_readback")])

    admitted_base_ledger = admitted_bundle.get("base_search_trial_ledger")
    admitted_semantics = {
        "research_state": state,
        "research_conjecture": conjecture,
        "approach_registry": approaches,
        "agent_authored_child_web_research_plan": dict(raw_plan),
    }
    semantic_mismatches = [
        name
        for name, persisted in admitted_semantics.items()
        if admitted_bundle.get(name) != persisted
    ]
    if semantic_mismatches or not isinstance(admitted_base_ledger, Mapping):
        raise EvoChildPreregistrationError(
            [
                _token(f"agent_authoring_materialized_mismatch:{name}")
                for name in (
                    semantic_mismatches
                    or ["base_search_trial_ledger"]
                )
            ]
        )
    expected_ledger = _project_evo_child_search_trial_ledger(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        base_search_trial_ledger=dict(admitted_base_ledger),
        execution_addendum=authorization.get("execution_addendum"),
    )
    if ledger != expected_ledger:
        raise EvoChildPreregistrationError(
            [_token("search_trial_ledger_not_exact_authoring_projection")]
        )

    expected_spec = _project_evo_child_metric_verifier_spec(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        authorization=authorization,
    )
    if metric_spec != expected_spec:
        raise EvoChildPreregistrationError(
            [_token("metric_verifier_spec_not_exact_projection")]
        )
    expected_threshold = _project_evo_child_threshold_registration(
        root=root,
        child_report_id=child_report_id,
        ledger=ledger,
        metric_spec=metric_spec,
        authorization=authorization,
    )
    if threshold != expected_threshold:
        raise EvoChildPreregistrationError(
            [_token("threshold_registration_not_exact_projection")]
        )
    reasons = _validate_inputs(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        state=state,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        authorization=authorization,
    )
    if reasons:
        raise EvoChildPreregistrationError(reasons)
    expected_projection = _project_evo_child_web_research_plan(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        agent_authored_plan=dict(raw_plan),
        authorization=authorization,
    )
    if persisted_projection != expected_projection:
        raise EvoChildPreregistrationError(
            [_token("child_web_research_plan_not_exact_projection")]
        )
    web_proof_targets = _project_child_web_factor_proof_targets(
        root=root,
        raw_plan=dict(raw_plan),
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        authorization=authorization,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
        current_authority=current_authority,
    )
    targets = _target_payloads(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        state=state,
        conjecture=conjecture,
        approaches=approaches,
        ledger=ledger,
        metric_spec=metric_spec,
        threshold=threshold,
        child_web_plan=expected_projection,
        web_proof_targets=web_proof_targets,
        authorization=authorization,
        authoring=authoring,
    )
    receipt_path = child_preregistration_receipt_path(root, child_report_id)
    receipt = _load_source_object(
        receipt_path, label="child_preregistration_receipt"
    )
    expected_receipt = _receipt_payload(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        ledger=ledger,
        targets=targets,
        authorization=authorization,
        authoring=authoring,
    )
    if receipt != expected_receipt:
        raise EvoChildPreregistrationError(
            [_token("preregistration_receipt_not_exact_projection")]
        )
    readback_reasons = _readback_reasons(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        targets=targets,
        authorization=authorization,
        authoring=authoring,
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
        current_authority=current_authority,
    )
    readback_reasons.extend(_source_binding_reasons(authorization, authoring))
    if readback_reasons:
        raise EvoChildPreregistrationError(readback_reasons)
    return {
        "root": root,
        "plan_path": plan_path,
        "raw_plan": deepcopy(dict(raw_plan)),
        "projection": expected_projection,
        "allocation": deepcopy(dict(authorization["allocation"])),
        "receipt": receipt,
        "receipt_path": receipt_path,
        "targets": targets,
        "authoring": authoring,
    }


def _current_replay_materialized_evo_child_preregistration(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None,
    incident_installation_id: str | None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    if incident_trust_root is None or not incident_installation_id:
        raise EvoChildPreregistrationError(
            [_token("incident_host_context_required")]
        )
    try:
        trust = Path(incident_trust_root).expanduser().resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise EvoChildPreregistrationError(
            [_token("incident_host_context_invalid")]
        ) from exc
    if _incident_guard is None:
        with oos_exposure_private_registry_guard(
            trust,
            installation_id=incident_installation_id,
        ) as guard:
            return _current_replay_materialized_evo_child_preregistration(
                workspace_root=workspace_root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                incident_trust_root=trust,
                incident_installation_id=incident_installation_id,
                _incident_guard=guard,
            )
    try:
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=trust,
            installation_id=incident_installation_id,
        )
    except (OSError, ValueError) as exc:
        raise EvoChildPreregistrationError(
            [_token(f"incident_guard:{type(exc).__name__}")]
        ) from exc
    return _replay_materialized_evo_child_preregistration(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        incident_trust_root=trust,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
        current_authority=True,
    )


def validate_evo_child_preregistration_receipt(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    """Current Host READY-signing gate; hand-written controls cannot satisfy it."""

    replay = _current_replay_materialized_evo_child_preregistration(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    return {
        "verdict": "PASS",
        "status": CHILD_PREREGISTRATION_STATUS,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "receipt_ref": _file_ref(replay["root"], replay["receipt_path"]),
        "child_web_research_plan_ref": _file_ref(
            replay["root"], replay["plan_path"]
        ),
        "frozen_artifact_count": len(replay["targets"]),
        "ready_ticket_state": "ELIGIBLE_FOR_SEPARATE_HOST_SIGNATURE",
        "writes_performed": False,
        "authority": {
            **dict(_AUTHORITY),
            "current_formal_authority_verified": True,
        },
    }


def validate_evo_child_preregistration_receipt_structural(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Replay frozen child controls without granting present-tense authority."""

    replay = _replay_materialized_evo_child_preregistration(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        current_authority=False,
    )
    return {
        "verdict": "PASS",
        "status": CHILD_PREREGISTRATION_STATUS,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "receipt_ref": _file_ref(replay["root"], replay["receipt_path"]),
        "child_web_research_plan_ref": _file_ref(
            replay["root"], replay["plan_path"]
        ),
        "frozen_artifact_count": len(replay["targets"]),
        "ready_ticket_state": "STRUCTURAL_REPLAY_ONLY",
        "writes_performed": False,
        "authority": {
            **dict(_AUTHORITY),
            "current_formal_authority_verified": False,
        },
    }


def validate_and_resolve_evo_child_web_research_plan(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path | str | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    """Resolve raw child semantics only after the full preregistration replay."""

    replay = _current_replay_materialized_evo_child_preregistration(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
        _incident_guard=_incident_guard,
    )
    return {
        "verdict": "PASS",
        "status": "VALIDATED_CHILD_WEB_RESEARCH_PLAN",
        "plan_path": replay["plan_path"],
        "raw_plan": replay["raw_plan"],
        "projection": replay["projection"],
        "allocation": replay["allocation"],
        "receipt": replay["receipt"],
        "authority": {
            **dict(_AUTHORITY),
            "current_formal_authority_verified": True,
        },
    }


def validate_and_resolve_evo_child_web_research_plan_structural(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Resolve child plan bytes for Agent computation, never formal acceptance."""

    replay = _replay_materialized_evo_child_preregistration(
        workspace_root=workspace_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        current_authority=False,
    )
    return {
        "verdict": "PASS",
        "status": "VALIDATED_CHILD_WEB_RESEARCH_PLAN_STRUCTURAL_ONLY",
        "plan_path": replay["plan_path"],
        "raw_plan": replay["raw_plan"],
        "projection": replay["projection"],
        "allocation": replay["allocation"],
        "receipt": replay["receipt"],
        "authority": {
            **dict(_AUTHORITY),
            "current_formal_authority_verified": False,
        },
    }


__all__ = [
    "BLOCK_EVO_CHILD_PREREGISTRATION",
    "CHILD_PREREGISTRATION_STATUS",
    "CHILD_PREREGISTRATION_VERSION",
    "EvoChildPreregistrationError",
    "WAITING_EVO_CHILD_PREREGISTRATION",
    "child_metric_verifier_spec_path",
    "child_prediction_freeze_verifier_path",
    "child_preregistration_receipt_path",
    "child_web_research_plan_path",
    "materialize_evo_child_preregistration",
    "project_authorized_evo_child_search_trial_ledger",
    "project_evo_child_metric_verifier_spec",
    "project_evo_child_search_trial_ledger",
    "project_evo_child_search_identities",
    "project_evo_child_threshold_registration",
    "project_evo_child_web_research_plan",
    "projected_evo_child_search_trial_ledger_sha256",
    "validate_and_resolve_evo_child_web_research_plan",
    "validate_and_resolve_evo_child_web_research_plan_structural",
    "validate_evo_child_preregistration_inputs",
    "validate_evo_child_preregistration_receipt",
    "validate_evo_child_preregistration_receipt_structural",
]
