from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from factor_factory.console.web_research_plan import (
    BOOTSTRAP_VERSION,
    validate_materialized_web_research,
    validate_plan,
)
from factor_factory.knowledge_context import (
    BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID,
    complete_evo_v2_cold_start_search_session,
    prepare_evo_v2_cold_start_search_session,
    retrieve_evo_v2_memory_projection,
)
from factor_factory.measurement_program import (
    stable_measurement_program_hash,
    validate_measurement_program,
)
from factor_factory.research_org.contracts import (
    SAFE_ID_RE,
    SHA256_RE,
    ResearchOrganizationError,
    normalize_workspace_relative_path,
    read_workspace_json,
    sha256_file,
    stable_json_hash,
    validate_content_hash,
    with_content_hash,
    workspace_file_lock,
    write_workspace_json,
    write_workspace_json_once,
)
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
)
from factor_factory.research_conjecture import (
    validate_epistemic_evolution_lifecycle,
)
from factor_factory.researcher_memory import (
    _assert_private_root,
    _atomic_store_json,
    _ensure_private_directory,
    _read_store_json,
    _store_lock,
    load_evo_v2_memory_admissions,
)


MEMORY_RUNTIME_STATE_VERSION = "factorforge_evo_v2_memory_runtime_state_v1"
MEMORY_RUNTIME_TRANSITION_RECEIPT_TYPE = "EVO_V2_MEMORY_RUNTIME_TRANSITION"
HISTORICAL_EPISODE_CANDIDATE_VERSION = (
    "factorforge_evo_v2_historical_episode_candidate_v1"
)
HISTORICAL_EPISODE_RECEIPT_TYPE = (
    "EVO_V2_HISTORICAL_EPISODE_FACTS_CANDIDATE_ADMITTED"
)

BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID = (
    "BLOCK_FACTORFORGE_EVO_V2_MEMORY_RUNTIME_INVALID"
)
BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID = (
    "BLOCK_FACTORFORGE_EVO_V2_HISTORICAL_EPISODE_INVALID"
)

RUNTIME_STAGES = {
    "AWAITING_KNOWLEDGE_LIBRARIAN_RUNTIME",
    "AWAITING_ADMISSIBLE_SOURCE_OR_ZERO_HIT",
    "AWAITING_TRANSFER_AUTHORING_AND_REVIEW",
    "COLD_START_VERIFIED_READY",
    "TRANSFER_ADMITTED_READY",
}
READY_STAGES = {
    "COLD_START_VERIFIED_READY",
    "TRANSFER_ADMITTED_READY",
}
_ALLOWED_TRANSITIONS = {
    None: RUNTIME_STAGES,
    "AWAITING_KNOWLEDGE_LIBRARIAN_RUNTIME": {
        "AWAITING_ADMISSIBLE_SOURCE_OR_ZERO_HIT",
        "AWAITING_TRANSFER_AUTHORING_AND_REVIEW",
        "COLD_START_VERIFIED_READY",
    },
    "AWAITING_ADMISSIBLE_SOURCE_OR_ZERO_HIT": {
        "AWAITING_ADMISSIBLE_SOURCE_OR_ZERO_HIT",
        "AWAITING_TRANSFER_AUTHORING_AND_REVIEW",
        "COLD_START_VERIFIED_READY",
    },
    "AWAITING_TRANSFER_AUTHORING_AND_REVIEW": {
        "AWAITING_TRANSFER_AUTHORING_AND_REVIEW",
        "TRANSFER_ADMITTED_READY",
    },
    "COLD_START_VERIFIED_READY": {"COLD_START_VERIFIED_READY"},
    "TRANSFER_ADMITTED_READY": {"TRANSFER_ADMITTED_READY"},
}

_EPISODE_ROOT_ENTRIES = {".store.lock", "tmp", "episodes"}


def _raise(token: str, *reasons: str) -> None:
    raise ResearchOrganizationError(token, list(reasons))


def is_validated_evo_v2_memory_runtime_enabled(
    *,
    workspace: Path,
    report_id: str,
    validated_materialization: Mapping[str, Any] | None = None,
) -> bool:
    """Return true only for an explicitly EVO-enabled formal materialization.

    Absence of the two EVO bootstrap artifacts is the legacy compatibility
    signal.  Once either marker is present, the materialization and prediction
    freeze are security-sensitive and therefore fail closed instead of being
    silently treated as a legacy workspace.
    """

    workspace = Path(workspace).expanduser().resolve(strict=True)
    bootstrap_path = workspace / "identity/web_research_bootstrap_result.json"
    if not bootstrap_path.exists():
        return False
    if bootstrap_path.is_symlink() or not bootstrap_path.is_file():
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "bootstrap_path")
    try:
        bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "bootstrap_json")
        raise AssertionError("unreachable") from exc
    if not isinstance(bootstrap, Mapping):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "bootstrap_object")
    artifacts = bootstrap.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, Mapping) else {}
    freeze_marker = artifacts.get("evo_v2_prediction_freeze_verifier")
    lifecycle_marker = artifacts.get("evo_v2_lifecycle")
    if freeze_marker is None and lifecycle_marker is None:
        return False
    if not isinstance(freeze_marker, str) or not isinstance(lifecycle_marker, str):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "evo_bootstrap_markers")
    expected_freeze = (
        f"objects/evo_v2/{report_id}/prediction_freeze_verifier.json"
    )
    expected_lifecycle = f"objects/evo_v2/{report_id}/lifecycle.json"
    if (
        bootstrap.get("version") != BOOTSTRAP_VERSION
        or bootstrap.get("verdict") != "PASS"
        or bootstrap.get("report_id") != report_id
        or freeze_marker != expected_freeze
        or lifecycle_marker != expected_lifecycle
    ):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "evo_bootstrap_binding")

    validation = (
        dict(validated_materialization)
        if isinstance(validated_materialization, Mapping)
        else validate_materialized_web_research(workspace)
    )
    plan_path = workspace / "identity/web_research_plan.json"
    if (
        validation.get("plan_sha256") != sha256_file(plan_path)
        or bootstrap.get("agent_authored_plan_sha256")
        != validation.get("plan_sha256")
    ):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "validated_plan_binding")

    def read_regular(relative: str, label: str) -> dict[str, Any]:
        path = workspace / relative
        if path.is_symlink() or not path.is_file():
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, f"{label}_path")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, f"{label}_json")
            raise AssertionError("unreachable") from exc
        if not isinstance(payload, dict):
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, f"{label}_object")
        return payload

    freeze = read_regular(expected_freeze, "prediction_freeze")
    if (
        freeze.get("contract_version")
        != "factorforge_evo_v2_prediction_freeze_verifier_v1"
        or freeze.get("report_id") != report_id
        or freeze.get("verifier_id")
        != "factorforge_evo_v2_prediction_freeze_verifier_v1"
        or freeze.get("verifier_status") != "PASS"
        or freeze.get("information_set")
        != "PREREGISTRATION_ONLY_NO_EMPIRICAL_EVIDENCE"
        or freeze.get("oos_accessed") is not False
        or freeze.get("plan_sha256") != validation.get("plan_sha256")
        or freeze.get("formula_hash") != validation.get("formula_hash")
        or freeze.get("dataset_snapshot_hash")
        != validation.get("catalog_sha256")
    ):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "prediction_freeze_binding")
    lifecycle = read_regular(expected_lifecycle, "evo_lifecycle")
    lifecycle_reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=workspace,
    )
    if lifecycle_reasons:
        _raise(
            BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
            *(f"evo_lifecycle:{reason}" for reason in lifecycle_reasons),
        )
    first_event = (lifecycle.get("events") or [None])[0]
    if (
        not isinstance(first_event, Mapping)
        or first_event.get("from_state") is not None
        or first_event.get("to_state") != "PREDICTIONS_FROZEN"
        or not any(
            isinstance(reference, Mapping)
            and reference.get("path") == expected_freeze
            and reference.get("sha256")
            == sha256_file(workspace / expected_freeze)
            for reference in first_event.get("evidence_refs") or []
        )
    ):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "prediction_freeze_lifecycle")
    return True


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _identity_from_plan(plan: Mapping[str, Any]) -> dict[str, str]:
    identity = plan.get("identity")
    if not isinstance(identity, Mapping):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "plan_identity")
    output = {
        field: str(identity.get(field) or "")
        for field in ("factor_id", "report_id", "research_id")
    }
    output["branch_id"] = "main"
    output["run_id"] = f"run_{output['report_id']}"
    if any(not SAFE_ID_RE.fullmatch(value) for value in output.values()):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "artifact_identity")
    return output


def build_evo_v2_mechanism_fingerprint(
    plan: Mapping[str, Any],
) -> dict[str, str]:
    """Project the blind, frozen plan into the mechanism-first retrieval key."""

    economic = plan.get("economic_mechanism")
    mathematical = plan.get("mathematical_mechanism")
    program = plan.get("measurement_program")
    if not all(isinstance(item, Mapping) for item in (economic, mathematical, program)):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "mechanism_inputs")
    knowledge_use = plan.get("knowledge_use")
    available_knowledge_node_ids = (
        knowledge_use.get("cited_node_ids") or []
        if isinstance(knowledge_use, Mapping)
        else []
    )
    program_reasons = validate_measurement_program(
        program,
        available_knowledge_node_ids=available_knowledge_node_ids,
    )
    if program_reasons:
        _raise(
            BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
            *(f"measurement_program:{reason}" for reason in program_reasons),
        )
    observation = program.get("observation_and_estimation") or {}
    estimand = str(observation.get("estimand") or "").strip()
    constraints = economic.get("participant_constraints") or []
    constraint_text = " | ".join(
        str(item.get("constraint") or "").strip()
        for item in constraints
        if isinstance(item, Mapping) and str(item.get("constraint") or "").strip()
    )
    payer_text = ", ".join(
        str(item).strip()
        for item in (economic.get("payer_candidates") or [])
        if str(item).strip()
    )
    preferred = next(
        (
            item
            for item in (plan.get("hypotheses") or [])
            if isinstance(item, Mapping) and item.get("kind") == "preferred"
        ),
        {},
    )
    failure_parts = [
        str(economic.get("failure_condition") or "").strip(),
        *(
            str(item).strip()
            for item in (preferred.get("kill_criteria") or [])
            if str(item).strip()
        ),
    ]
    boundary_parts = [
        str(economic.get("persistence_boundary") or "").strip(),
        str(economic.get("capacity_boundary") or "").strip(),
    ]
    fingerprint = {
        "economic_claim": str(economic.get("mechanism_claim") or "").strip(),
        "estimand_id": f"estimand_{stable_json_hash(estimand)[:20]}",
        "payer_or_constraint": " | ".join(
            item for item in (payer_text, constraint_text) if item
        ),
        "mathematical_object": str(
            mathematical.get("mathematical_object") or ""
        ).strip(),
        "broken_invariant_or_boundary": " | ".join(
            item for item in boundary_parts if item
        ),
        "observation_mapping": str(
            observation.get("observation_map") or ""
        ).strip(),
        "failure_signature": " | ".join(item for item in failure_parts if item),
    }
    if any(not value for value in fingerprint.values()):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "mechanism_fingerprint_empty")
    return fingerprint


def protected_contract_hashes(
    *,
    plan: Mapping[str, Any],
    worktree: Path,
) -> dict[str, Any]:
    program = plan["measurement_program"]
    evidence = plan["evidence_policy"]
    observation = program["observation_and_estimation"]
    skill = worktree / "skills/factor-forge-ultimate/SKILL.md"
    validator = worktree / "factor_factory/evo_v2.py"
    if any(path.is_symlink() or not path.is_file() for path in (skill, validator)):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "protected_source_missing")
    return {
        "skill_sha256": sha256_file(skill),
        "validator_sha256": sha256_file(validator),
        "thresholds_sha256": stable_json_hash(program["evaluation_design"]),
        "oos_policy_sha256": stable_json_hash(
            {
                key: evidence[key]
                for key in (
                    "is_start",
                    "is_end",
                    "oos_start",
                    "oos_end",
                    "purge_days",
                    "embargo_days",
                    "forward_horizon",
                    "signal_timestamp_policy",
                    "position_entry_policy",
                )
            }
        ),
        "estimand_sha256": stable_json_hash(observation["estimand"]),
        "trial_budget_sha256": stable_json_hash(
            {
                "trial_budget": evidence["trial_budget"],
                "multiple_testing_policy": evidence["multiple_testing_policy"],
                "registered_diagnostic_trials": program["search_policy"][
                    "registered_diagnostic_trials"
                ],
            }
        ),
        "unchanged": True,
    }


def _runtime_root(report_id: str) -> str:
    if not SAFE_ID_RE.fullmatch(report_id):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "report_id")
    return f"objects/evo_v2/{report_id}/memory_runtime"


def _safe_workspace_file_ref(workspace: Path, relative: str) -> dict[str, str]:
    normalized = normalize_workspace_relative_path(
        relative,
        workspace=workspace,
        label="evo_v2_memory_runtime_ref",
    )
    path = workspace / normalized
    if not path.is_file() or path.is_symlink():
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, f"missing_ref:{normalized}")
    return {"path": normalized, "sha256": sha256_file(path)}


def _write_once_or_verify(
    workspace: Path,
    relative: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    path = workspace / normalize_workspace_relative_path(
        relative,
        workspace=workspace,
        label="evo_v2_memory_runtime_write",
    )
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, f"unsafe_existing:{relative}")
        observed = read_workspace_json(workspace, relative)
        if observed != payload:
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, f"immutable_drift:{relative}")
    else:
        write_workspace_json_once(workspace, relative, payload)
    return _safe_workspace_file_ref(workspace, relative)


def _snapshot_memory_indexes(
    *,
    workspace: Path,
    report_id: str,
    admissions: Sequence[Mapping[str, Any]],
    historical_episodes: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    organization_plan_path = workspace / "identity/research_organization_plan.json"
    organization_plan = (
        read_workspace_json(workspace, "identity/research_organization_plan.json")
        if organization_plan_path.is_file() and not organization_plan_path.is_symlink()
        else {}
    )
    snapshot_records: list[dict[str, Any]] = []
    memory_binding = organization_plan.get("researcher_memory")
    if isinstance(memory_binding, Mapping):
        role_refs = memory_binding.get("role_snapshot_refs") or {}
        for role_id in sorted(role_refs):
            reference = role_refs[role_id]
            if not isinstance(reference, Mapping):
                _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "role_snapshot_ref")
            relative = normalize_workspace_relative_path(
                reference.get("path"),
                workspace=workspace,
                label="role_memory_snapshot",
            )
            payload = read_workspace_json(workspace, relative)
            path = workspace / relative
            if (
                path.is_symlink()
                or not path.is_file()
                or reference.get("sha256")
                not in {
                    payload.get("snapshot_sha256"),
                    sha256_file(path),
                }
            ):
                _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "role_snapshot_readback")
            snapshot_records.append(
                {
                    "role_id": role_id,
                    "snapshot_sha256": payload.get("snapshot_sha256"),
                    "cold_start": payload.get("cold_start"),
                    "canonical_records": payload.get("canonical_records") or [],
                }
            )
    role_index = with_content_hash(
        {
            "contract_version": "factorforge_evo_v2_role_memory_index_snapshot_v1",
            "report_id": report_id,
            "v1_role_snapshots": snapshot_records,
            "evo_v2_admissions": [dict(item) for item in admissions],
            "historical_episode_candidates": [
                dict(item) for item in historical_episodes
            ],
            "authority_guard": {
                "historical_advisory_only": True,
                "performance_ranking_allowed": False,
                "current_factor_proof_authority": False,
            },
        },
        hash_field="snapshot_sha256",
    )
    knowledge_path = workspace / "identity/factor_knowledge_summary.json"
    knowledge_summary = (
        read_workspace_json(workspace, "identity/factor_knowledge_summary.json")
        if knowledge_path.is_file() and not knowledge_path.is_symlink()
        else {
            "version": "factorforge_web_knowledge_summary_v1",
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "related_edges": [],
            "cold_start_reason": "factor knowledge summary unavailable",
        }
    )
    factor_index = with_content_hash(
        {
            "contract_version": "factorforge_evo_v2_factor_knowledge_index_snapshot_v1",
            "report_id": report_id,
            "factor_knowledge_summary": knowledge_summary,
            "authority_guard": {
                "historical_advisory_only": True,
                "performance_ranking_allowed": False,
                "current_factor_proof_authority": False,
            },
        },
        hash_field="snapshot_sha256",
    )
    root = _runtime_root(report_id)
    refs: list[dict[str, str]] = []
    for index_id, name, payload in (
        ("role_memory", "role_memory_index_snapshot.json", role_index),
        ("factor_knowledge", "factor_knowledge_index_snapshot.json", factor_index),
    ):
        reference = _write_once_or_verify(
            workspace,
            f"{root}/{name}",
            payload,
        )
        refs.append({"index_id": index_id, **reference})
    return refs


def _runtime_event_reasons(
    event: Any,
    *,
    trust_store: Any,
) -> list[str]:
    if not isinstance(event, Mapping):
        return ["event_object"]
    expected = {
        "contract_version",
        "artifact_identity",
        "generation",
        "parent_event_sha256",
        "stage",
        "formal_execution_allowed",
        "bindings",
        "pause",
        "authority_guard",
        "host_transition_receipt",
        "event_sha256",
    }
    reasons: list[str] = []
    if set(event) != expected:
        reasons.append("event_fields")
    if event.get("contract_version") != MEMORY_RUNTIME_STATE_VERSION:
        reasons.append("event_contract")
    identity = event.get("artifact_identity")
    if (
        not isinstance(identity, Mapping)
        or set(identity)
        != {"factor_id", "report_id", "research_id", "branch_id", "run_id"}
        or any(not SAFE_ID_RE.fullmatch(str(value or "")) for value in identity.values())
    ):
        reasons.append("event_identity")
    generation = event.get("generation")
    if type(generation) is not int or generation < 1:
        reasons.append("event_generation")
    if generation == 1:
        if event.get("parent_event_sha256") is not None:
            reasons.append("event_parent_initial")
    elif not SHA256_RE.fullmatch(str(event.get("parent_event_sha256") or "")):
        reasons.append("event_parent")
    stage = event.get("stage")
    if stage not in RUNTIME_STAGES:
        reasons.append("event_stage")
    if event.get("formal_execution_allowed") is not (stage in READY_STAGES):
        reasons.append("event_formal_gate")
    if not isinstance(event.get("bindings"), Mapping):
        reasons.append("event_bindings")
    pause = event.get("pause")
    if not isinstance(pause, Mapping) or set(pause) != {
        "required",
        "reason",
        "resume_action",
    }:
        reasons.append("event_pause")
    elif (
        pause.get("required") is not (stage not in READY_STAGES)
        or not isinstance(pause.get("reason"), str)
        or not isinstance(pause.get("resume_action"), str)
    ):
        reasons.append("event_pause_binding")
    if event.get("authority_guard") != {
        "blind_derivation_completed": True,
        "results_or_oos_accessed": False,
        "market_regime_router_allowed": False,
        "skill_or_validator_mutation_allowed": False,
        "threshold_estimand_oos_or_budget_mutation_allowed": False,
        "current_factor_proof_authority": False,
        "canonical_memory_write_authority": False,
        "host_cas_transition_required": True,
    }:
        reasons.append("event_authority_guard")
    receipt = event.get("host_transition_receipt")
    if trust_store is None or not hasattr(trust_store, "verify"):
        reasons.append("event_trust_store")
    elif not isinstance(receipt, Mapping):
        reasons.append("event_receipt")
    else:
        reasons.extend(
            f"event_signature:{reason}"
            for reason in trust_store.verify(receipt, expected_issuer="host_admission")
        )
        transition_core = {
            key: event[key]
            for key in expected
            if key not in {"host_transition_receipt", "event_sha256"}
            and key in event
        }
        if (
            receipt.get("receipt_type")
            != MEMORY_RUNTIME_TRANSITION_RECEIPT_TYPE
            or receipt.get("identity") != identity
            or receipt.get("bindings")
            != {
                "transition_core_sha256": stable_json_hash(transition_core),
                "generation": generation,
                "parent_event_sha256": event.get("parent_event_sha256"),
                "stage": stage,
            }
            or receipt.get("outcome")
            != {
                "formal_execution_allowed": stage in READY_STAGES,
                "current_factor_proof_authority": False,
                "canonical_memory_write_authority": False,
            }
        ):
            reasons.append("event_receipt_binding")
    reasons.extend(
        validate_content_hash(
            event,
            hash_field="event_sha256",
            label="evo_v2_memory_runtime_event",
        )
    )
    return list(dict.fromkeys(reasons))


def _load_runtime_events(
    *,
    workspace: Path,
    report_id: str,
    trust_store: Any,
) -> list[dict[str, Any]]:
    event_root = workspace / _runtime_root(report_id) / "events"
    if not event_root.exists():
        return []
    if event_root.is_symlink() or not event_root.is_dir():
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "event_root")
    events: list[dict[str, Any]] = []
    for path in sorted(event_root.iterdir(), key=lambda item: item.name):
        if (
            path.is_symlink()
            or not path.is_file()
            or not re.fullmatch(r"event_[0-9]{6}_[0-9a-f]{12}\.json", path.name)
        ):
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "event_path")
        event = json.loads(path.read_text(encoding="utf-8"))
        reasons = _runtime_event_reasons(event, trust_store=trust_store)
        if reasons:
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, *reasons)
        expected_generation = len(events) + 1
        expected_parent = events[-1]["event_sha256"] if events else None
        if (
            event["generation"] != expected_generation
            or event["parent_event_sha256"] != expected_parent
            or (
                events
                and event["stage"]
                not in _ALLOWED_TRANSITIONS[events[-1]["stage"]]
            )
        ):
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "event_chain")
        events.append(dict(event))
    current_path = workspace / _runtime_root(report_id) / "memory_runtime_state.json"
    if events:
        if current_path.exists() or current_path.is_symlink():
            if current_path.is_symlink() or not current_path.is_file():
                _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "current_state_path")
            current = json.loads(current_path.read_text(encoding="utf-8"))
            if current != events[-1]:
                _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "current_state_drift")
    elif current_path.exists() or current_path.is_symlink():
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "orphan_current_state")
    return events


def load_evo_v2_memory_round_state(
    *,
    workspace: Path,
    state_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    """Validate and project the durable pre-result state chain for resume."""

    workspace = Path(workspace).expanduser().resolve(strict=True)
    state_root = Path(state_root).expanduser().resolve(strict=True)
    plan = read_workspace_json(workspace, "identity/web_research_plan.json")
    identity = _identity_from_plan(plan)
    trust_store = load_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id=installation_id,
    )
    events = _load_runtime_events(
        workspace=workspace,
        report_id=identity["report_id"],
        trust_store=trust_store,
    )
    if not events or any(event.get("artifact_identity") != identity for event in events):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "resume_state_chain")
    return {
        "artifact_identity": identity,
        "events": events,
        "current_state": events[-1],
    }


def _transition_runtime_state(
    *,
    workspace: Path,
    identity: Mapping[str, Any],
    stage: str,
    bindings: Mapping[str, Any],
    pause_reason: str,
    resume_action: str,
    trust_store: Any,
) -> dict[str, Any]:
    if stage not in RUNTIME_STAGES:
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "transition_stage")
    report_id = str(identity.get("report_id") or "")
    root = workspace / _runtime_root(report_id)
    if root.is_symlink():
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "runtime_root_symlink")
    root.mkdir(parents=True, exist_ok=True)
    (root / "events").mkdir(parents=True, exist_ok=True)
    lock_relative = f"{_runtime_root(report_id)}/.state.lock"
    lock_path = workspace / lock_relative
    if not lock_path.exists():
        lock_path.touch(mode=0o600, exist_ok=False)
    with workspace_file_lock(workspace, lock_relative):
        events = _load_runtime_events(
            workspace=workspace,
            report_id=report_id,
            trust_store=trust_store,
        )
        prior = events[-1] if events else None
        if prior and prior["stage"] == stage and prior["bindings"] == bindings:
            return prior
        prior_stage = prior["stage"] if prior else None
        if stage not in _ALLOWED_TRANSITIONS[prior_stage]:
            _raise(
                BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
                f"transition_forbidden:{prior_stage}->{stage}",
            )
        generation = len(events) + 1
        transition_core = {
            "contract_version": MEMORY_RUNTIME_STATE_VERSION,
            "artifact_identity": dict(identity),
            "generation": generation,
            "parent_event_sha256": prior["event_sha256"] if prior else None,
            "stage": stage,
            "formal_execution_allowed": stage in READY_STAGES,
            "bindings": dict(bindings),
            "pause": {
                "required": stage not in READY_STAGES,
                "reason": pause_reason,
                "resume_action": resume_action,
            },
            "authority_guard": {
                "blind_derivation_completed": True,
                "results_or_oos_accessed": False,
                "market_regime_router_allowed": False,
                "skill_or_validator_mutation_allowed": False,
                "threshold_estimand_oos_or_budget_mutation_allowed": False,
                "current_factor_proof_authority": False,
                "canonical_memory_write_authority": False,
                "host_cas_transition_required": True,
            },
        }
        receipt = trust_store.sign(
            "host_admission",
            {
                "receipt_type": MEMORY_RUNTIME_TRANSITION_RECEIPT_TYPE,
                "identity": dict(identity),
                "bindings": {
                    "transition_core_sha256": stable_json_hash(transition_core),
                    "generation": generation,
                    "parent_event_sha256": transition_core[
                        "parent_event_sha256"
                    ],
                    "stage": stage,
                },
                "outcome": {
                    "formal_execution_allowed": stage in READY_STAGES,
                    "current_factor_proof_authority": False,
                    "canonical_memory_write_authority": False,
                },
            },
        )
        event = with_content_hash(
            {**transition_core, "host_transition_receipt": receipt},
            hash_field="event_sha256",
        )
        reasons = _runtime_event_reasons(event, trust_store=trust_store)
        if reasons:
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, *reasons)
        event_relative = (
            f"{_runtime_root(report_id)}/events/"
            f"event_{generation:06d}_{event['event_sha256'][:12]}.json"
        )
        write_workspace_json_once(workspace, event_relative, event)
        write_workspace_json(
            workspace,
            f"{_runtime_root(report_id)}/memory_runtime_state.json",
            event,
        )
        observed = _load_runtime_events(
            workspace=workspace,
            report_id=report_id,
            trust_store=trust_store,
        )
        if not observed or observed[-1] != event:
            _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "transition_readback")
        return event


def _load_optional_admissions(
    *,
    root: Path,
    repo_root: Path,
    trust_store: Any,
) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return load_evo_v2_memory_admissions(
        root=root,
        repo_root=repo_root,
        trust_store=trust_store,
        source_workspace=None,
    )


def prepare_evo_v2_memory_round(
    *,
    workspace: Path,
    worktree: Path,
    state_root: Path,
    installation_id: str,
    runner: Any | None,
    admissions_root: Path | None = None,
    episodes_root: Path | None = None,
) -> dict[str, Any]:
    """Run or durably pause the pre-result, mechanism-first memory gate.

    This entrypoint is idempotent.  It never fabricates a transfer.  A positive
    retrieval pauses with a hash-bound authoring task until the full independent
    review and Host-admission chain is supplied by a later orchestration stage.
    A zero-hit path becomes executable only after a real Knowledge Librarian
    session and adapter-signed completion receipt.
    """

    workspace = Path(workspace).expanduser().resolve(strict=True)
    worktree = Path(worktree).expanduser().resolve(strict=True)
    state_root = Path(state_root).expanduser().resolve(strict=True)
    plan = read_workspace_json(workspace, "identity/web_research_plan.json")
    validate_plan(dict(plan), workspace=workspace)
    identity = _identity_from_plan(plan)
    report_id = identity["report_id"]
    fingerprint = build_evo_v2_mechanism_fingerprint(plan)
    trust_store = load_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id=installation_id,
    )
    existing = _load_runtime_events(
        workspace=workspace,
        report_id=report_id,
        trust_store=trust_store,
    )
    plan_ref = _safe_workspace_file_ref(
        workspace,
        "identity/web_research_plan.json",
    )
    base_bindings = {
        "plan_ref": plan_ref,
        "plan_semantic_sha256": stable_json_hash(plan),
        "measurement_program_sha256": stable_measurement_program_hash(
            plan["measurement_program"]
        ),
        "mechanism_fingerprint": fingerprint,
        "mechanism_fingerprint_sha256": stable_json_hash(fingerprint),
        "protected_contracts": protected_contract_hashes(
            plan=plan,
            worktree=worktree,
        ),
    }
    if existing:
        latest = existing[-1]
        for field in (
            "plan_ref",
            "plan_semantic_sha256",
            "measurement_program_sha256",
            "mechanism_fingerprint",
            "mechanism_fingerprint_sha256",
            "protected_contracts",
        ):
            if latest["bindings"].get(field) != base_bindings[field]:
                _raise(
                    BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
                    f"frozen_binding_drift:{field}",
                )
        if latest["stage"] in READY_STAGES:
            return latest
        if latest["stage"] == "AWAITING_TRANSFER_AUTHORING_AND_REVIEW":
            return latest

    admissions_path = (
        Path(admissions_root)
        if admissions_root is not None
        else state_root / "researcher-memory-evo-v2"
    )
    episode_path = (
        Path(episodes_root)
        if episodes_root is not None
        else state_root / "researcher-memory-evo-v2-episodes"
    )
    admissions = _load_optional_admissions(
        root=admissions_path,
        repo_root=worktree,
        trust_store=trust_store,
    )
    historical_episodes = load_historical_episode_candidates(
        root=episode_path,
        repo_root=worktree,
        trust_store=trust_store,
    ) if episode_path.exists() else []
    index_refs = _snapshot_memory_indexes(
        workspace=workspace,
        report_id=report_id,
        admissions=admissions,
        historical_episodes=historical_episodes,
    )
    projection = retrieve_evo_v2_memory_projection(
        admissions=admissions,
        historical_episode_candidates=historical_episodes,
        target_mechanism_fingerprint=fingerprint,
        blind_derivation_completed=True,
        trust_store=trust_store,
    )
    projection_ref = _write_once_or_verify(
        workspace,
        f"{_runtime_root(report_id)}/retrieval_projection.json",
        projection,
    )
    bindings = {
        **base_bindings,
        "checked_index_refs": index_refs,
        "retrieval_projection_ref": projection_ref,
        "retrieved_experience_count": projection["retrieved_experience_count"],
        "cold_start_search_receipt_ref": None,
        "transfer_admission_ref": None,
    }
    if projection["retrieved_experience_count"] > 0:
        task = with_content_hash(
            {
                "contract_version": "factorforge_evo_v2_transfer_authoring_task_v1",
                "artifact_identity": identity,
                "mechanism_fingerprint": fingerprint,
                "retrieval_projection_ref": projection_ref,
                "requirements": {
                    "source_to_target_mapping_required": True,
                    "preregistered_before_after_question_and_test_diff_required": True,
                    "real_independent_reviewer_session_required": True,
                    "host_signed_admission_and_persistence_required": True,
                    "automatic_skill_or_policy_mutation_allowed": False,
                    "results_or_oos_access_allowed_before_completion": False,
                },
                "resume_api": "admit_evo_v2_memory_transfer_round",
            },
            hash_field="task_sha256",
        )
        task_ref = _write_once_or_verify(
            workspace,
            f"{_runtime_root(report_id)}/transfer_authoring_task.json",
            task,
        )
        bindings["transfer_authoring_task_ref"] = task_ref
        return _transition_runtime_state(
            workspace=workspace,
            identity=identity,
            stage="AWAITING_TRANSFER_AUTHORING_AND_REVIEW",
            bindings=bindings,
            pause_reason=(
                "Admissible mechanism-matched experience exists; a real author, "
                "independent reviewer, and Host admission must complete the transfer."
            ),
            resume_action="Complete the transfer authoring task and call the admission API.",
            trust_store=trust_store,
        )
    if runner is None or not callable(
        getattr(runner, "run_research_org_session", None)
    ):
        return _transition_runtime_state(
            workspace=workspace,
            identity=identity,
            stage="AWAITING_KNOWLEDGE_LIBRARIAN_RUNTIME",
            bindings=bindings,
            pause_reason=(
                "No admissible Host-side hit was found, but cold start is not valid "
                "until a real isolated Knowledge Librarian signs the zero-hit search."
            ),
            resume_action="Resume with a ResearchOrgSessionRunner and the frozen indexes.",
            trust_store=trust_store,
        )
    invocation, _request, _session_root = (
        prepare_evo_v2_cold_start_search_session(
            workspace=workspace,
            worktree=worktree,
            state_root=state_root,
            installation_id=installation_id,
            artifact_identity=identity,
            mechanism_fingerprint=fingerprint,
            checked_indexes=index_refs,
        )
    )
    try:
        outcome = runner.run_research_org_session(invocation)
        cold_receipt = complete_evo_v2_cold_start_search_session(
            invocation=invocation,
            outcome=outcome,
            state_root=state_root,
            installation_id=installation_id,
        )
    except Exception as exc:
        error_token = getattr(exc, "token", type(exc).__name__)
        bindings["retrieval_runtime_failure"] = str(error_token)
        return _transition_runtime_state(
            workspace=workspace,
            identity=identity,
            stage="AWAITING_ADMISSIBLE_SOURCE_OR_ZERO_HIT",
            bindings=bindings,
            pause_reason=(
                "The Knowledge Librarian did not produce an admissible signed zero-hit "
                "receipt. Any discovered source must be admitted before transfer."
            ),
            resume_action=(
                "Admit a discovered source or rerun the frozen zero-hit task with a real "
                "Knowledge Librarian session."
            ),
            trust_store=trust_store,
        )
    cold_ref = _write_once_or_verify(
        workspace,
        f"{_runtime_root(report_id)}/cold_start_search_receipt.json",
        cold_receipt,
    )
    bindings["cold_start_search_receipt_ref"] = cold_ref
    return _transition_runtime_state(
        workspace=workspace,
        identity=identity,
        stage="COLD_START_VERIFIED_READY",
        bindings=bindings,
        pause_reason="",
        resume_action="Proceed to formal execution without an experience transfer.",
        trust_store=trust_store,
    )


def admit_evo_v2_memory_transfer_round(
    *,
    workspace: Path,
    state_root: Path,
    installation_id: str,
    repo_root: Path,
    memory_admission: Mapping[str, Any],
    persisted_admission_ref: Mapping[str, Any],
    admissions_root: Path | None = None,
) -> dict[str, Any]:
    """Advance a positive-hit pause only from a fully admitted/persisted envelope."""

    from factor_factory.researcher_memory import validate_evo_v2_memory_admission

    workspace = Path(workspace).expanduser().resolve(strict=True)
    state_root = Path(state_root).expanduser().resolve(strict=True)
    repo_root = Path(repo_root).expanduser().resolve(strict=True)
    trust_store = load_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id=installation_id,
    )
    report_id = str(
        (memory_admission.get("artifact_identity") or {}).get("report_id") or ""
    )
    events = _load_runtime_events(
        workspace=workspace,
        report_id=report_id,
        trust_store=trust_store,
    )
    if not events or events[-1]["stage"] != "AWAITING_TRANSFER_AUTHORING_AND_REVIEW":
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "transfer_pause_missing")
    latest = events[-1]
    reasons = validate_evo_v2_memory_admission(
        memory_admission,
        trust_store=trust_store,
        workspace=workspace,
        verify_refs=True,
    )
    if reasons:
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, *reasons)
    if memory_admission.get("artifact_identity") != latest["artifact_identity"]:
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "transfer_identity")
    if (
        not isinstance(persisted_admission_ref, Mapping)
        or set(persisted_admission_ref)
        != {
            "admission_id",
            "admission_sha256",
            "relative_path",
            "file_sha256",
            "written",
            "semantic_authority",
        }
        or persisted_admission_ref.get("admission_id")
        != memory_admission.get("admission_id")
        or persisted_admission_ref.get("admission_sha256")
        != memory_admission.get("admission_sha256")
        or persisted_admission_ref.get("relative_path")
        != f"admissions/{memory_admission.get('admission_id')}.json"
        or not SHA256_RE.fullmatch(
            str(persisted_admission_ref.get("file_sha256") or "")
        )
        or type(persisted_admission_ref.get("written")) is not bool
        or persisted_admission_ref.get("semantic_authority")
        != "factor_factory.evo_v2"
    ):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "persisted_admission_ref")
    admission_root = (
        Path(admissions_root)
        if admissions_root is not None
        else state_root / "researcher-memory-evo-v2"
    )
    loaded_admissions = load_evo_v2_memory_admissions(
        root=admission_root,
        repo_root=repo_root,
        trust_store=trust_store,
        source_workspace=None,
    )
    matching = [
        admission
        for admission in loaded_admissions
        if admission.get("admission_id") == memory_admission.get("admission_id")
    ]
    persisted_path = admission_root / str(persisted_admission_ref["relative_path"])
    if (
        len(matching) != 1
        or matching[0] != memory_admission
        or persisted_path.is_symlink()
        or not persisted_path.is_file()
        or sha256_file(persisted_path)
        != persisted_admission_ref.get("file_sha256")
    ):
        _raise(BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID, "persisted_admission_readback")
    bindings = dict(latest["bindings"])
    bindings["transfer_admission_ref"] = dict(persisted_admission_ref)
    return _transition_runtime_state(
        workspace=workspace,
        identity=latest["artifact_identity"],
        stage="TRANSFER_ADMITTED_READY",
        bindings=bindings,
        pause_reason="",
        resume_action="Proceed to formal execution with the admitted advisory transfer.",
        trust_store=trust_store,
    )


def _flatten_metric_scalars(value: Any, *, prefix: str = "") -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            output.extend(_flatten_metric_scalars(value[key], prefix=path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            output.extend(_flatten_metric_scalars(item, prefix=f"{prefix}[{index}]"))
    elif value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            return output
        output.append({"metric_path": prefix, "value": value})
    return output[:256]


def build_terminal_historical_episode_candidate(
    *,
    evidence_workspace: Path,
    identity: Mapping[str, Any],
    terminal_outcome: Mapping[str, Any],
    outcome_event_ref: Mapping[str, Any],
    host_attestation_ref: Mapping[str, Any],
    state_root: Path,
    trust_store: Any,
) -> dict[str, Any]:
    """Build a Host-signed facts-only episode candidate from terminal evidence."""

    evidence_workspace = Path(evidence_workspace).expanduser().resolve(strict=True)
    plan = read_workspace_json(evidence_workspace, "identity/web_research_plan.json")
    plan_identity = plan.get("identity") or {}
    expected_identity = {
        field: str(identity.get(field) or "")
        for field in ("job_id", "factor_id", "research_id", "report_id")
    }
    if (
        any(not SAFE_ID_RE.fullmatch(value) for value in expected_identity.values())
        or any(
            plan_identity.get(field) != expected_identity[field]
            for field in ("job_id", "factor_id", "research_id", "report_id")
        )
    ):
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "identity")
    if (
        terminal_outcome.get("execution_status") != "COMPLETED"
        or terminal_outcome.get("factor_verdict") not in {"ACCEPT", "REJECT"}
        or terminal_outcome.get("organization_runtime_verified") is not True
    ):
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "terminal_outcome")
    state_root = Path(state_root).expanduser().resolve(strict=True)
    attestation_id = str(host_attestation_ref.get("id") or "")
    attestation_relative = Path(attestation_id)
    if (
        attestation_relative.is_absolute()
        or ".." in attestation_relative.parts
        or not SHA256_RE.fullmatch(str(host_attestation_ref.get("sha256") or ""))
    ):
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "attestation_ref")
    attestation_path = state_root / attestation_relative
    if (
        attestation_path.is_symlink()
        or not attestation_path.is_file()
        or sha256_file(attestation_path) != host_attestation_ref.get("sha256")
    ):
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "attestation_readback")
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    if any(
        attestation.get(field) != value
        for field, value in expected_identity.items()
    ):
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "attestation_identity")
    certificate_relative = (
        f"objects/research_protocol/factor_proof_certificate__"
        f"{expected_identity['report_id']}.json"
    )
    certificate_path = evidence_workspace / certificate_relative
    if certificate_path.is_file() and not certificate_path.is_symlink():
        certificate = read_workspace_json(evidence_workspace, certificate_relative)
        certificate_ref: dict[str, Any] | None = {
            "path": certificate_relative,
            "sha256": sha256_file(certificate_path),
        }
        metric_scalars = _flatten_metric_scalars(certificate.get("metrics") or {})
        observed_declared_verdict = certificate.get("declared_verdict")
    else:
        certificate_ref = None
        metric_scalars = []
        observed_declared_verdict = None
    evidence = plan["evidence_policy"]
    mechanism_fingerprint = build_evo_v2_mechanism_fingerprint(plan)
    plan_ref = {
        "path": "identity/web_research_plan.json",
        "sha256": sha256_file(evidence_workspace / "identity/web_research_plan.json"),
    }
    source_refs = {
        "outcome_event": {
            "event_id": str(outcome_event_ref.get("event_id") or ""),
            "event_sha256": str(outcome_event_ref.get("event_sha256") or ""),
            "path": str(outcome_event_ref.get("path") or ""),
        },
        "host_attestation": {
            "id": attestation_id,
            "sha256": str(host_attestation_ref.get("sha256") or ""),
        },
        "frozen_plan": {
            **plan_ref,
            "semantic_sha256": stable_json_hash(plan),
        },
        "factor_proof": certificate_ref,
        "workspace_evidence_tree": {
            "id": str(attestation.get("workspace_evidence_tree_id") or ""),
            "sha256": str(
                attestation.get("workspace_evidence_tree_sha256") or ""
            ),
            "root_sha256": str(
                attestation.get("workspace_evidence_tree_root_sha256") or ""
            ),
        },
    }
    facts = {
        "window": {
            key: evidence[key]
            for key in ("is_start", "is_end", "oos_start", "oos_end")
        },
        "universe_id": evidence["universe_id"],
        "mechanism_fingerprint": mechanism_fingerprint,
        "measurement_program_sha256": stable_measurement_program_hash(
            plan["measurement_program"]
        ),
        "prediction_registry_sha256": stable_json_hash(plan["hypotheses"]),
        "terminal_outcome": {
            key: terminal_outcome[key]
            for key in (
                "execution_status",
                "protocol_status",
                "factor_verdict",
                "council_status",
                "formal_proof_eligible",
                "organization_runtime_verified",
            )
        },
        "observed_signature": {
            "declared_verdict": observed_declared_verdict,
            "metric_scalars": metric_scalars,
            "metric_payload_sha256": stable_json_hash(metric_scalars),
        },
        "causal_interpretation": "NOT_INFERRED_FACTS_ONLY_CANDIDATE",
    }
    unsigned_core = {
        "state": "HOST_SIGNED_FACTUAL_CANDIDATE_ONLY",
        "authority": "historical_episode_context_only",
        "identity": expected_identity,
        "episode_layer": "historical_episode",
        "source_refs": source_refs,
        "facts": facts,
        "authority_guard": {
            "immutable_facts_only": True,
            "structural_or_conditional_lesson_generated": False,
            "causal_claim_generated": False,
            "market_regime_router_allowed": False,
            "historical_performance_ranking_allowed": False,
            "current_factor_proof_authority": False,
            "canonical_memory_write_authority": False,
            "skill_or_policy_mutation_authority": False,
        },
    }
    candidate_id = f"episode_candidate_{stable_json_hash(unsigned_core)[:24]}"
    receipt = trust_store.sign(
        "host_admission",
        {
            "receipt_type": HISTORICAL_EPISODE_RECEIPT_TYPE,
            "identity": expected_identity,
            "bindings": {
                "candidate_id": candidate_id,
                "facts_sha256": stable_json_hash(facts),
                "source_refs_sha256": stable_json_hash(source_refs),
            },
            "outcome": {
                "state": "HOST_SIGNED_FACTUAL_CANDIDATE_ONLY",
                "episode_layer": "historical_episode",
                "structural_or_conditional_lesson_generated": False,
                "canonical_memory_write_authority": False,
            },
        },
    )
    candidate = with_content_hash(
        {
            "contract_version": HISTORICAL_EPISODE_CANDIDATE_VERSION,
            "candidate_id": candidate_id,
            **unsigned_core,
            "host_admission_receipt": receipt,
        },
        hash_field="candidate_sha256",
    )
    reasons = validate_terminal_historical_episode_candidate(
        candidate,
        trust_store=trust_store,
    )
    if reasons:
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, *reasons)
    return candidate


def validate_terminal_historical_episode_candidate(
    candidate: Any,
    *,
    trust_store: Any,
) -> list[str]:
    if not isinstance(candidate, Mapping):
        return ["candidate_object"]
    expected = {
        "contract_version",
        "candidate_id",
        "state",
        "authority",
        "identity",
        "episode_layer",
        "source_refs",
        "facts",
        "authority_guard",
        "host_admission_receipt",
        "candidate_sha256",
    }
    reasons: list[str] = []
    if set(candidate) != expected:
        reasons.append("candidate_fields")
    if (
        candidate.get("contract_version") != HISTORICAL_EPISODE_CANDIDATE_VERSION
        or candidate.get("state") != "HOST_SIGNED_FACTUAL_CANDIDATE_ONLY"
        or candidate.get("authority") != "historical_episode_context_only"
        or candidate.get("episode_layer") != "historical_episode"
    ):
        reasons.append("candidate_type")
    identity = candidate.get("identity")
    if (
        not isinstance(identity, Mapping)
        or set(identity) != {"job_id", "factor_id", "research_id", "report_id"}
        or any(not SAFE_ID_RE.fullmatch(str(value or "")) for value in identity.values())
    ):
        reasons.append("candidate_identity")
    facts = candidate.get("facts")
    if not isinstance(facts, Mapping) or set(facts) != {
        "window",
        "universe_id",
        "mechanism_fingerprint",
        "measurement_program_sha256",
        "prediction_registry_sha256",
        "terminal_outcome",
        "observed_signature",
        "causal_interpretation",
    }:
        reasons.append("candidate_facts")
        facts = {}
    if facts.get("causal_interpretation") != "NOT_INFERRED_FACTS_ONLY_CANDIDATE":
        reasons.append("candidate_causal_guard")
    terminal = facts.get("terminal_outcome")
    if (
        not isinstance(terminal, Mapping)
        or terminal.get("execution_status") != "COMPLETED"
        or terminal.get("factor_verdict") not in {"ACCEPT", "REJECT"}
        or terminal.get("organization_runtime_verified") is not True
    ):
        reasons.append("candidate_terminal")
    fingerprint = facts.get("mechanism_fingerprint")
    if (
        not isinstance(fingerprint, Mapping)
        or set(fingerprint)
        != {
            "economic_claim",
            "estimand_id",
            "payer_or_constraint",
            "mathematical_object",
            "broken_invariant_or_boundary",
            "observation_mapping",
            "failure_signature",
        }
        or any(not str(value or "").strip() for value in fingerprint.values())
    ):
        reasons.append("candidate_fingerprint")
    if candidate.get("authority_guard") != {
        "immutable_facts_only": True,
        "structural_or_conditional_lesson_generated": False,
        "causal_claim_generated": False,
        "market_regime_router_allowed": False,
        "historical_performance_ranking_allowed": False,
        "current_factor_proof_authority": False,
        "canonical_memory_write_authority": False,
        "skill_or_policy_mutation_authority": False,
    }:
        reasons.append("candidate_authority_guard")
    source_refs = candidate.get("source_refs")
    if not isinstance(source_refs, Mapping):
        reasons.append("candidate_source_refs")
        source_refs = {}
    receipt = candidate.get("host_admission_receipt")
    if trust_store is None or not hasattr(trust_store, "verify"):
        reasons.append("candidate_trust_store")
    elif not isinstance(receipt, Mapping):
        reasons.append("candidate_receipt")
    else:
        reasons.extend(
            f"candidate_signature:{reason}"
            for reason in trust_store.verify(receipt, expected_issuer="host_admission")
        )
        if (
            receipt.get("receipt_type") != HISTORICAL_EPISODE_RECEIPT_TYPE
            or receipt.get("identity") != identity
            or receipt.get("bindings")
            != {
                "candidate_id": candidate.get("candidate_id"),
                "facts_sha256": stable_json_hash(facts),
                "source_refs_sha256": stable_json_hash(source_refs),
            }
            or receipt.get("outcome")
            != {
                "state": "HOST_SIGNED_FACTUAL_CANDIDATE_ONLY",
                "episode_layer": "historical_episode",
                "structural_or_conditional_lesson_generated": False,
                "canonical_memory_write_authority": False,
            }
        ):
            reasons.append("candidate_receipt_binding")
    # Candidate identity is intentionally derived before the Host signature;
    # verify it against that exact unsigned core instead of signature bytes.
    unsigned = {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "contract_version",
            "candidate_id",
            "host_admission_receipt",
            "candidate_sha256",
        }
    }
    if candidate.get("candidate_id") != (
        f"episode_candidate_{stable_json_hash(unsigned)[:24]}"
    ):
        reasons.append("candidate_id_binding")
    reasons.extend(
        validate_content_hash(
            candidate,
            hash_field="candidate_sha256",
            label="evo_v2_historical_episode_candidate",
        )
    )
    return list(dict.fromkeys(reasons))


def persist_historical_episode_candidate(
    *,
    root: Path,
    candidate: Mapping[str, Any],
    repo_root: Path,
    workspace: Path,
    trust_store: Any,
) -> dict[str, Any]:
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=workspace,
        create=True,
    )
    reasons = validate_terminal_historical_episode_candidate(
        candidate,
        trust_store=trust_store,
    )
    if reasons:
        _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, *reasons)
    _ensure_private_directory(resolved, "episodes")
    _ensure_private_directory(resolved, "tmp")
    relative = f"episodes/{candidate['candidate_id']}.json"
    with _store_lock(resolved):
        entries = {path.name for path in resolved.iterdir()}
        if entries != _EPISODE_ROOT_ENTRIES:
            _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "root_layout")
        path, written = _atomic_store_json(
            resolved,
            relative,
            candidate,
            replace=False,
        )
        observed = _read_store_json(resolved, relative)
        if observed != candidate:
            _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "readback")
    return {
        "candidate_id": candidate["candidate_id"],
        "candidate_sha256": candidate["candidate_sha256"],
        "relative_path": relative,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "written": written,
        "authority": "historical_episode_candidate_only",
    }


def load_historical_episode_candidates(
    *,
    root: Path,
    repo_root: Path,
    trust_store: Any,
) -> list[dict[str, Any]]:
    if not Path(root).exists():
        return []
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=None,
        create=False,
    )
    with _store_lock(resolved, create=False):
        entries = {path.name for path in resolved.iterdir()}
        if entries != _EPISODE_ROOT_ENTRIES:
            _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "root_layout")
        output: list[dict[str, Any]] = []
        episode_root = resolved / "episodes"
        for path in sorted(episode_root.iterdir(), key=lambda item: item.name):
            if (
                path.is_symlink()
                or not path.is_file()
                or not re.fullmatch(
                    r"episode_candidate_[0-9a-f]{24}\.json",
                    path.name,
                )
            ):
                _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "episode_path")
            candidate = _read_store_json(
                resolved,
                path.relative_to(resolved).as_posix(),
            )
            reasons = validate_terminal_historical_episode_candidate(
                candidate,
                trust_store=trust_store,
            )
            if reasons:
                _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, *reasons)
            if path.name != f"{candidate['candidate_id']}.json":
                _raise(BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID, "path_binding")
            output.append(candidate)
    return output


def register_terminal_historical_episode_candidate(
    *,
    root: Path,
    evidence_workspace: Path,
    repo_root: Path,
    state_root: Path,
    installation_id: str,
    identity: Mapping[str, Any],
    terminal_outcome: Mapping[str, Any],
    outcome_event_ref: Mapping[str, Any],
    host_attestation_ref: Mapping[str, Any],
) -> dict[str, Any]:
    trust_store = load_runtime_trust_store(
        Path(state_root) / "research-org-trust",
        installation_id=installation_id,
    )
    candidate = build_terminal_historical_episode_candidate(
        evidence_workspace=evidence_workspace,
        identity=identity,
        terminal_outcome=terminal_outcome,
        outcome_event_ref=outcome_event_ref,
        host_attestation_ref=host_attestation_ref,
        state_root=state_root,
        trust_store=trust_store,
    )
    persisted = persist_historical_episode_candidate(
        root=root,
        candidate=candidate,
        repo_root=repo_root,
        workspace=evidence_workspace,
        trust_store=trust_store,
    )
    return {
        **persisted,
        "episode_layer": "historical_episode",
        "structural_or_conditional_lesson_generated": False,
        "next_lesson_pipeline": (
            "materialize_learning_candidates -> real independent review -> "
            "Host CAS promotion"
        ),
    }
