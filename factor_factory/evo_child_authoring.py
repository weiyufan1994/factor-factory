from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from factor_factory.evo_v2 import canonical_json_bytes, sha256_file, stable_json_hash
from factor_factory.research_conjecture import (
    research_protocol_paths,
    validate_approach_registry,
    validate_research_conjecture,
    validate_research_state,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_org.contracts import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    private_reasoning_paths,
)
from factor_factory.research_org.runtime import (
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
)
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)
from factor_factory.research_release import SEARCH_TRIAL_LEDGER_VERSION

EVO_CHILD_AUTHORING_ROLE_ID = "evo_child_preregistration_author"
EVO_CHILD_AUTHORING_TASK_VERSION = "factorforge_evo_child_authoring_task_v1"
EVO_CHILD_AUTHORING_BUNDLE_VERSION = "factorforge_evo_child_authoring_bundle_v1"
EVO_CHILD_AUTHORING_ADMISSION_VERSION = (
    "factorforge_evo_child_authoring_admission_v1"
)
EVO_CHILD_AUTHORING_RECEIPT_TYPE = "EVO_CHILD_AGENT_AUTHORING_ADMISSION"
EVO_CHILD_AUTHORING_STATUS = "RUNTIME_ATTESTED_AGENT_SEMANTICS_ADMITTED"
BLOCK_EVO_CHILD_AUTHORING = "BLOCK_FACTORFORGE_EVO_CHILD_AUTHORING_INVALID"
LEDGER_DERIVED_HASH_SENTINEL = "HOST_DETERMINISTIC_RECOMPUTE"
MAX_PRIVATE_OUTPUT_BYTES = 2 * 1024 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,191}\Z")
_JOB_ID = re.compile(r"job_[a-f0-9]{10}\Z")
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
_SEMANTIC_KEYS = (
    "research_state",
    "research_conjecture",
    "approach_registry",
    "base_search_trial_ledger",
    "agent_authored_child_web_research_plan",
)
_LEDGER_DERIVED_FIELDS = (
    "trial_set_sha256",
    "candidate_space_sha256",
    "selected_hypothesis_sha256",
)
_FORBIDDEN_TRIAL_RESULT_FIELDS = {
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
_FORBIDDEN_OUTPUT_RESULT_KEYS = {
    "accepted",
    "approved",
    "evaluation_results",
    "factor_values",
    "factor_verdict",
    "formal_factor_verdict",
    "observed_metrics",
    "oos_accessed",
    "oos_panel",
    "oos_release_manifest",
    "realized_metrics",
}
_PROTECTED_EVIDENCE_FIELDS = (
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
_ADAPTER_RECEIPT_FIELDS = {
    "contract_version",
    "receipt_type",
    "identity",
    "ordering",
    "bindings",
    "session",
    "outcome",
    "issuer",
    "receipt_id",
    "signature",
}
_ADAPTER_BINDING_FIELDS = {
    "plan_sha256",
    "task_sha256",
    "context_manifest_sha256",
    "dependency_admissions",
    "idempotency_key",
    "adapter_challenge",
}
_ADAPTER_ORDERING_FIELDS = {
    "scheduler_epoch",
    "dispatch_event_seq",
    "issued_at_utc",
    "started_at_utc",
    "finished_at_utc",
}
_ADAPTER_SESSION_FIELDS = {
    "session_uid",
    "runtime_handle_sha256",
    "provider_handle_sha256",
    "adapter_id",
    "adapter_build_sha256",
    "container_image_digest",
    "isolation_profile_sha256",
    "runtime",
    "parent_session_uid",
    "lease_epoch",
}
_ADAPTER_OUTCOME_FIELDS = {
    "returncode",
    "cancelled",
    "error_class",
    "private_output_sha256",
    "private_output_size_bytes",
    "termination_confirmed",
}
_RUNTIME_ATTESTATION_FIELDS = {
    "session_id",
    "runtime_instance_id",
    "provider",
    "model",
    "transport",
    "isolation_class",
    "owned_termination_supported",
    "termination_confirmed",
    "parent_session_uid",
}
_TRANSPORT_BY_ISOLATION = {
    "container_staged_context": "openclaw_disposable_container",
}
_EVO_CHILD_AUTHORING_ISOLATION_CLASSES = frozenset(_TRANSPORT_BY_ISOLATION)


class EvoChildAuthoringError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(item) for item in reasons if str(item)))
        super().__init__(";".join(self.reasons))


class EvoChildAuthoringRunner(Protocol):
    def run_research_org_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> ResearchOrgSessionOutcome: ...

    def reconcile_research_org_session(
        self,
        runtime_instance_id: str,
    ) -> Mapping[str, Any]: ...


def _token(reason: str) -> str:
    return f"{BLOCK_EVO_CHILD_AUTHORING}:{reason}"


def _raise(*reasons: str) -> None:
    raise EvoChildAuthoringError([_token(reason) for reason in reasons])


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _safe_id(value: Any) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


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


def _load_json_file(path: Path, *, label: str, canonical: bool = False) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _raise(f"missing_or_unsafe:{label}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildAuthoringError([_token(f"invalid_json:{label}")]) from exc
    if not isinstance(payload, dict):
        _raise(f"object_required:{label}")
    if canonical and raw != canonical_json_bytes(payload):
        _raise(f"noncanonical_json:{label}")
    return payload


def _file_ref(root: Path, path: Path) -> dict[str, str]:
    if (
        not _within_without_symlinks(root, path)
        or path.is_symlink()
        or not path.is_file()
    ):
        _raise(f"unsafe_ref:{path.name}")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
    }


def _expected_file_ref(
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _payload_sha256(payload),
    }


def _resolve_ref(
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
        _raise(f"ref_shape:{label}")
    raw_path = reference.get("path")
    if (
        not isinstance(raw_path, str)
        or "\\" in raw_path
        or not _is_sha256(reference.get("sha256"))
    ):
        _raise(f"ref_values:{label}")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != raw_path:
        _raise(f"ref_path:{label}")
    path = root.joinpath(*relative.parts)
    if (
        not _within_without_symlinks(root, path)
        or path.is_symlink()
        or not path.is_file()
        or (expected_path is not None and path.resolve() != expected_path.resolve())
        or sha256_file(path) != reference.get("sha256")
    ):
        _raise(f"ref_readback:{label}")
    payload = _load_json_file(path, label=label)
    content_sha = reference.get("content_sha256")
    if content_sha is not None:
        declared = payload.get("content_sha256")
        if declared is None:
            valid_content_binding = content_sha == stable_json_hash(payload)
        else:
            unsigned = dict(payload)
            unsigned.pop("content_sha256", None)
            valid_content_binding = (
                declared == content_sha
                and declared == stable_json_hash(unsigned)
            )
        if not valid_content_binding:
            _raise(f"ref_content_hash:{label}")
    return path, payload


def evo_child_authoring_paths(
    workspace_root: Path | str,
    child_report_id: str,
) -> dict[str, Path]:
    root = Path(workspace_root).expanduser().resolve(strict=False)
    if not _safe_id(child_report_id):
        _raise("child_report_id")
    base = root / "objects" / "runtime_context"
    return {
        "task": base / f"evo_child_authoring_task__{child_report_id}.json",
        "agent_output": base
        / f"evo_child_authoring_agent_output__{child_report_id}.json",
        "semantic_bundle": base
        / f"evo_child_authoring_bundle__{child_report_id}.json",
        "adapter_receipt": base
        / f"evo_child_authoring_adapter_receipt__{child_report_id}.json",
        "admission": base
        / f"evo_child_authoring_admission__{child_report_id}.json",
    }


def evo_child_authoring_admission_path(
    workspace_root: Path | str,
    child_report_id: str,
) -> Path:
    return evo_child_authoring_paths(workspace_root, child_report_id)["admission"]


def _authorization_material(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Resolve the signed child authorization and frozen parent contracts.

    This function intentionally imports the preregistration authority lazily:
    preregistration imports this module only at its formal admission gate.
    """

    from factor_factory.evo_child_preregistration import _authorization_context

    authorization = _authorization_context(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    ticket = authorization.get("ticket")
    handoff = authorization.get("handoff")
    parent_contracts = authorization.get("parent_contracts")
    if not all(isinstance(item, Mapping) for item in (ticket, handoff, parent_contracts)):
        _raise("authorization_context_shape")
    trust_path, trust_manifest = _resolve_ref(
        root,
        ticket.get("trust_manifest_ref"),
        label="host_trust_manifest",
    )
    if (
        validate_public_trust_manifest(trust_manifest)
        or trust_manifest.get("manifest_sha256")
        != expected_host_trust_manifest_sha256
    ):
        _raise("host_trust_manifest_pin")

    parent_protocol = research_protocol_paths(root, parent_report_id)
    parent_state_path = parent_protocol["state"]
    parent_approaches_path = parent_protocol["approaches"]
    parent_state = _load_json_file(parent_state_path, label="parent_research_state")
    parent_approaches = _load_json_file(
        parent_approaches_path,
        label="parent_approach_registry",
    )
    if validate_research_state(parent_state) or validate_approach_registry(
        parent_approaches,
        stage="pre_council",
    ):
        _raise("parent_protocol_contract")

    bindings = ticket.get("bindings")
    if not isinstance(bindings, Mapping):
        _raise("authorization_bindings")
    approval_path, approval = _resolve_ref(
        root,
        bindings.get("approval_ref"),
        label="pre_oos_human_approval",
    )
    approval_bindings = approval.get("evidence_bindings")
    if not isinstance(approval_bindings, Mapping):
        _raise("approval_evidence_bindings")
    root_synthesis_path, root_synthesis = _resolve_ref(
        root,
        approval_bindings.get("root_synthesis_ref"),
        label="pre_oos_root_synthesis",
    )
    mechanism_delta_path, mechanism_delta = _resolve_ref(
        root,
        approval_bindings.get("mechanism_delta_ref"),
        label="mechanism_delta",
    )
    backprojection_path, backprojection = _resolve_ref(
        root,
        approval_bindings.get("economic_backprojection_ref"),
        label="economic_backprojection",
    )
    orchestration_path, orchestration = _resolve_ref(
        root,
        bindings.get("formal_transfer_use_orchestration_ref"),
        label="formal_transfer_use_orchestration",
    )

    source_paths: dict[str, Path] = {
        "authorization_ticket": authorization["authorization_path"],
        "host_trust_manifest": trust_path,
        "handoff": authorization["handoff_path"],
        "pre_oos_human_approval": approval_path,
        "pre_oos_root_synthesis": root_synthesis_path,
        "mechanism_delta": mechanism_delta_path,
        "economic_backprojection": backprojection_path,
        "formal_transfer_use_orchestration": orchestration_path,
        "parent_workspace_manifest": root / "manifest.json",
        "parent_web_research_plan": parent_contracts["plan_path"],
        "parent_research_state": parent_state_path,
        "parent_research_conjecture": parent_contracts[
            "research_conjecture_path"
        ],
        "parent_approach_registry": parent_approaches_path,
        "parent_metric_verifier_spec": parent_contracts[
            "metric_verifier_spec_path"
        ],
        "parent_threshold_registration": parent_contracts[
            "threshold_registration_path"
        ],
        "parent_web_factor_proof_preregistration": parent_contracts[
            "web_preregistration_path"
        ],
    }
    source_payloads: dict[str, dict[str, Any]] = {
        "authorization_ticket": dict(ticket),
        "host_trust_manifest": dict(trust_manifest),
        "handoff": dict(handoff),
        "pre_oos_human_approval": dict(approval),
        "pre_oos_root_synthesis": dict(root_synthesis),
        "mechanism_delta": dict(mechanism_delta),
        "economic_backprojection": dict(backprojection),
        "formal_transfer_use_orchestration": dict(orchestration),
        "parent_workspace_manifest": _load_json_file(
            root / "manifest.json",
            label="parent_workspace_manifest",
        ),
        "parent_web_research_plan": dict(parent_contracts["plan"]),
        "parent_research_state": parent_state,
        "parent_research_conjecture": dict(parent_contracts["research_conjecture"]),
        "parent_approach_registry": parent_approaches,
        "parent_metric_verifier_spec": dict(
            parent_contracts["metric_verifier_spec"]
        ),
        "parent_threshold_registration": dict(
            parent_contracts["threshold_registration"]
        ),
        "parent_web_factor_proof_preregistration": dict(
            parent_contracts["web_preregistration"]
        ),
    }
    addendum_path = authorization.get("execution_addendum_path")
    addendum = authorization.get("execution_addendum")
    if isinstance(addendum_path, Path) and isinstance(addendum, Mapping):
        source_paths["execution_addendum"] = addendum_path
        source_payloads["execution_addendum"] = dict(addendum)

    for label, path in source_paths.items():
        if (
            not _within_without_symlinks(root, path)
            or path.is_symlink()
            or not path.is_file()
            or label not in source_payloads
            or sha256_file(path) != _file_ref(root, path)["sha256"]
        ):
            _raise(f"source_invalid:{label}")
    allocation = authorization.get("allocation")
    if not isinstance(allocation, Mapping):
        _raise("fresh_oos_allocation")
    return {
        "authorization": authorization,
        "trust_manifest": dict(trust_manifest),
        "trust_manifest_path": trust_path,
        "source_paths": source_paths,
        "source_payloads": source_payloads,
        "source_file_sha256s": {
            path: sha256_file(path) for path in source_paths.values()
        },
        "allocation_public_binding": {
            "allocation_id": allocation.get("allocation_id"),
            "report_id": allocation.get("report_id"),
            "parent_report_id": allocation.get("parent_report_id"),
            "dataset_snapshot_sha256": allocation.get("dataset_snapshot_sha256"),
            "oos_window": deepcopy(allocation.get("oos_window")),
            "sealed_token_sha256": allocation.get("sealed_token_sha256"),
            "sealed_carrier_sha256": allocation.get("sealed_carrier_sha256"),
            "release_state": allocation.get("release_state"),
            "consumed": allocation.get("consumed"),
        },
    }


def _selected_revision(material: Mapping[str, Any]) -> dict[str, Any]:
    handoff = material["authorization"]["handoff"]
    selected = handoff.get("selected_revision")
    if not isinstance(selected, Mapping):
        _raise("selected_revision")
    required = (
        "law_id",
        "delta_id",
        "implementation_mode",
        "child_formula",
        "child_formula_hash",
    )
    if (
        any(
            not isinstance(selected.get(field), str)
            or not selected.get(field)
            for field in required
        )
        or not _is_sha256(selected.get("child_formula_hash"))
    ):
        _raise("selected_revision_binding")
    return {
        "law_id": selected.get("law_id"),
        "delta_id": selected.get("delta_id"),
        "implementation_mode": selected.get("implementation_mode"),
        "child_formula": selected.get("child_formula"),
        "child_formula_hash": selected.get("child_formula_hash"),
        "expected_metric_signature": deepcopy(
            selected.get("expected_metric_signature")
        ),
        "falsification_tests": deepcopy(selected.get("falsification_tests")),
        "kill_criteria": deepcopy(selected.get("kill_criteria")),
        "selected_revision_sha256": stable_json_hash(dict(selected)),
    }


def _staged_file_projection(material: Mapping[str, Any]) -> list[dict[str, Any]]:
    staged: list[dict[str, Any]] = []
    for label, payload in sorted(material["source_payloads"].items()):
        raw = canonical_json_bytes(payload)
        staged.append(
            {
                "label": label,
                "path": f"inputs/{label}.json",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    allocation_raw = canonical_json_bytes(material["allocation_public_binding"])
    staged.append(
        {
            "label": "fresh_oos_allocation_public_binding",
            "path": "identity/fresh_oos_allocation_public_binding.json",
            "sha256": hashlib.sha256(allocation_raw).hexdigest(),
            "size_bytes": len(allocation_raw),
        }
    )
    return sorted(staged, key=lambda item: str(item["path"]))


def _project_authoring_task(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    material: Mapping[str, Any],
) -> dict[str, Any]:
    authorization = material["authorization"]
    parent_plan = authorization["parent_contracts"]["plan"]
    parent_identity = parent_plan.get("identity")
    parent_identity = parent_identity if isinstance(parent_identity, Mapping) else {}
    handoff_identity = authorization["handoff"].get("parent_identity")
    handoff_identity = (
        handoff_identity if isinstance(handoff_identity, Mapping) else {}
    )
    identity = {
        "job_id": parent_identity.get("job_id"),
        "factor_id": handoff_identity.get("factor_id"),
        "research_id": handoff_identity.get("research_id"),
        "report_id": child_report_id,
    }
    if (
        _JOB_ID.fullmatch(str(identity["job_id"] or "")) is None
        or any(not _safe_id(identity[field]) for field in ("factor_id", "research_id", "report_id"))
        or parent_identity.get("report_id") != parent_report_id
        or identity["factor_id"] != parent_identity.get("factor_id")
        or identity["research_id"] != parent_identity.get("research_id")
    ):
        _raise("task_identity")
    allocation = material["allocation_public_binding"]
    if (
        allocation.get("report_id") != child_report_id
        or allocation.get("parent_report_id") != parent_report_id
        or not _is_sha256(allocation.get("dataset_snapshot_sha256"))
        or not _is_sha256(allocation.get("sealed_token_sha256"))
        or not _is_sha256(allocation.get("sealed_carrier_sha256"))
        or allocation.get("release_state") != "SEALED_UNRELEASED"
        or allocation.get("consumed") is not False
    ):
        _raise("task_fresh_oos_binding")
    staged_files = _staged_file_projection(material)
    source_refs = {
        label: _file_ref(root, path)
        for label, path in sorted(material["source_paths"].items())
    }
    core = {
        "contract_version": EVO_CHILD_AUTHORING_TASK_VERSION,
        "role_id": EVO_CHILD_AUTHORING_ROLE_ID,
        "identity": identity,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "authorization_ticket_ref": _file_ref(
            root,
            authorization["authorization_path"],
        ),
        "external_host_trust_manifest_sha256": material["trust_manifest"][
            "manifest_sha256"
        ],
        "selected_revision": _selected_revision(material),
        "fresh_oos_allocation_ref": _file_ref(
            root,
            authorization["allocation_path"],
        ),
        "fresh_oos_allocation_public_binding": deepcopy(allocation),
        "parent_frozen_contract_refs": {
            key: source_refs[key]
            for key in (
                "parent_workspace_manifest",
                "parent_web_research_plan",
                "parent_research_state",
                "parent_research_conjecture",
                "parent_approach_registry",
                "parent_metric_verifier_spec",
                "parent_threshold_registration",
                "parent_web_factor_proof_preregistration",
            )
        },
        "revision_evidence_refs": {
            key: source_refs[key]
            for key in (
                "handoff",
                "pre_oos_human_approval",
                "pre_oos_root_synthesis",
                "mechanism_delta",
                "economic_backprojection",
                "formal_transfer_use_orchestration",
            )
        },
        "optional_execution_addendum_ref": source_refs.get("execution_addendum"),
        "staged_files": staged_files,
        "context_manifest_sha256": stable_json_hash(staged_files),
        "required_private_output": {
            "outer_contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
            "status": "PASS",
            "public_record_exact_keys": list(_SEMANTIC_KEYS),
            "base_ledger_derived_hash_sentinel": LEDGER_DERIVED_HASH_SENTINEL,
        },
        "closed_constraints": {
            "agent_authors_semantics": True,
            "host_semantic_generation_allowed": False,
            "host_deterministic_hash_normalization_only": True,
            "oos_bytes_available": False,
            "oos_results_available": False,
            "oos_access_allowed": False,
            "empirical_results_allowed_in_output": False,
            "skill_or_validator_mutation_allowed": False,
            "estimand_mutation_allowed": False,
            "threshold_mutation_allowed": False,
            "trial_budget_mutation_allowed": False,
            "multiplicity_policy_mutation_allowed": False,
            "human_approval_authority": False,
            "child_execution_authority": False,
            "canonical_write_authority": False,
            "factor_verdict_authority": False,
        },
    }
    return {**core, "task_sha256": stable_json_hash(core)}


def _private_write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            _raise(f"private_immutable_conflict:{path.name}")
        return
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("evo_child_authoring_private_short_write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _materialize_staged_context(
    *,
    context_root: Path,
    material: Mapping[str, Any],
    task: Mapping[str, Any],
) -> None:
    for item in task["staged_files"]:
        label = item["label"]
        payload = (
            material["allocation_public_binding"]
            if label == "fresh_oos_allocation_public_binding"
            else material["source_payloads"][label]
        )
        raw = canonical_json_bytes(payload)
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            _raise(f"staged_projection:{label}")
        _private_write_once(context_root / item["path"], raw)
    _private_write_once(
        context_root / "identity/evo_child_authoring_request.json",
        canonical_json_bytes(task),
    )


def _safe_private_root(path: Path, *, workspace: Path, worktree: Path) -> Path:
    candidate = path.expanduser()
    for protected in (workspace.resolve(), worktree.resolve()):
        resolved_candidate = candidate.resolve(strict=False)
        if (
            resolved_candidate == protected
            or resolved_candidate in protected.parents
            or protected in resolved_candidate.parents
        ):
            _raise("private_root_overlaps_workspace_or_worktree")
    if candidate.exists() or candidate.is_symlink():
        metadata = candidate.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            _raise("unsafe_private_root")
    else:
        candidate.mkdir(parents=True, mode=0o700)
    candidate.chmod(0o700)
    return candidate.resolve(strict=True)


def _private_child_scope(
    private: Path,
    *,
    namespace: str,
    child_report_id: str,
) -> Path:
    if namespace not in {"authoring", "assurance"} or not _safe_id(
        child_report_id
    ):
        _raise("private_child_scope")
    scope = (
        private
        / ".evo-child-scopes"
        / namespace
        / stable_json_hash(
            {
                "scope": "evo_child_private_scope_v1",
                "namespace": namespace,
                "child_report_id": child_report_id,
            }
        )[:32]
    )
    try:
        scope.mkdir(parents=True, mode=0o700, exist_ok=True)
        metadata = scope.lstat()
    except OSError as exc:
        raise EvoChildAuthoringError([_token("private_child_scope")]) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        _raise("private_child_scope")
    scope.chmod(0o700)
    return scope.resolve(strict=True)


def prepare_evo_child_authoring_session(
    *,
    workspace_root: Path | str,
    worktree: Path | str,
    private_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    trust_root: Path | str,
    installation_id: str,
    timeout_seconds: int = 1800,
    attempt_token: str | None = None,
    adapter_challenge: str | None = None,
    attempt_number: int = 1,
) -> tuple[ResearchOrgSessionInvocation, dict[str, Any]]:
    """Prepare one disposable, staged-context child-semantics Agent session."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    tree = Path(worktree).expanduser().resolve(strict=True)
    try:
        root.relative_to(tree)
    except ValueError as exc:
        raise EvoChildAuthoringError([_token("workspace_outside_worktree")]) from exc
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
        or not _is_sha256(expected_host_trust_manifest_sha256)
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 60 <= timeout_seconds <= 7200
        or isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or not 1 <= attempt_number <= 32
    ):
        _raise("prepare_inputs")
    material = _authorization_material(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    trust_store = load_runtime_trust_store(
        Path(trust_root),
        installation_id=installation_id,
    )
    if trust_store.public_manifest != material["trust_manifest"]:
        _raise("private_trust_store_workspace_manifest_mismatch")
    task = _project_authoring_task(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        material=material,
    )
    private = _safe_private_root(
        Path(private_root),
        workspace=root,
        worktree=tree,
    )
    token = attempt_token or uuid.uuid4().hex
    challenge = adapter_challenge or uuid.uuid4().hex
    if (
        not re.fullmatch(r"[0-9a-f]{32}", token)
        or not re.fullmatch(r"[0-9a-f]{32,64}", challenge)
    ):
        _raise("prepare_attempt_identity")
    session_root = private / f"evo-child-authoring-{token}"
    session_root.mkdir(mode=0o700, exist_ok=True)
    context_root = session_root / "context"
    context_root.mkdir(mode=0o700, exist_ok=True)
    (session_root / "output").mkdir(mode=0o700, exist_ok=True)
    _materialize_staged_context(
        context_root=context_root,
        material=material,
        task=task,
    )
    invocation = ResearchOrgSessionInvocation(
        identity=dict(task["identity"]),
        role_id=EVO_CHILD_AUTHORING_ROLE_ID,
        task_id=f"evo_child_authoring_{token[:24]}",
        task_sha256=str(task["task_sha256"]),
        attempt_id=f"attempt_evo_child_author_{token[:20]}",
        attempt_number=attempt_number,
        session_id=f"session_{token}",
        runtime_instance_id=f"fforg-evo-child-author-{token[:16]}",
        worktree=tree,
        workspace=root,
        private_attempt_root=session_root,
        context_root=context_root,
        private_output_path=session_root / "output" / "agent_result.json",
        cancel_request_path=session_root / "cancel_request.json",
        context_manifest_sha256=str(task["context_manifest_sha256"]),
        required_skills=("factor-forge-ultimate",),
        timeout_seconds=timeout_seconds,
        runtime_id=f"runtime_evo_child_author_{token[:20]}",
        plan_sha256=str(
            task["parent_frozen_contract_refs"]["parent_web_research_plan"][
                "sha256"
            ]
        ),
        scheduler_epoch=attempt_number,
        dispatch_event_seq=attempt_number,
        idempotency_key=stable_json_hash(
            {
                "task_sha256": task["task_sha256"],
                "authorization_ticket_ref": task["authorization_ticket_ref"],
                "child_report_id": child_report_id,
                "attempt_number": attempt_number,
            }
        ),
        adapter_challenge=challenge,
        dependency_admissions=(dict(task["authorization_ticket_ref"]),),
        parent_session_uid=None,
    )
    return invocation, {
        "task": task,
        "material": material,
        "session_root": session_root,
    }


def build_evo_child_authoring_prompt(
    invocation: ResearchOrgSessionInvocation,
) -> str:
    """Return the closed prompt used only by the dedicated authoring role."""

    request_path = (
        invocation.context_root / "identity/evo_child_authoring_request.json"
    )
    output_template = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": {
            "research_state": {},
            "research_conjecture": {},
            "approach_registry": {},
            "base_search_trial_ledger": {},
            "agent_authored_child_web_research_plan": {},
        },
    }
    return f"""# Factor Forge EVO child preregistration semantic author

You are one disposable Agent session. Read the exact Host-frozen request at
`{request_path}` and only the files listed under its `staged_files`. The parent
contracts, selected minimal law, human-approved authorization and fresh sealed
OOS metadata are immutable inputs. No OOS panel bytes or realized OOS results
are available or authorized.

Author the child research semantics. Return exactly five semantic objects:
`research_state`, `research_conjecture`, `approach_registry`,
`base_search_trial_ledger`, and `agent_authored_child_web_research_plan`.
The child plan must preserve the parent plan's protected structure, data plan,
IS policy, estimand, thresholds, trial budget and multiplicity policy while
binding the selected child formula, child identity, fresh OOS dates/token,
new hypotheses and mechanism-distinct routes. It must agree exactly with the
conjecture and approach registry. The base ledger contains preregistered trials
only; it must not contain results, metrics, evidence, acceptance or OOS access.

For the three derived base-ledger hash fields (`trial_set_sha256`,
`candidate_space_sha256`, `selected_hypothesis_sha256`), either compute the
exact canonical SHA-256 or write the literal
`{LEDGER_DERIVED_HASH_SENTINEL}`. The Host may recompute only those hash fields;
it may not generate or rewrite hypotheses, routes, trials, questions, economic
logic or mathematical semantics.

Do not modify skills, validators, permissions, estimand, thresholds, OOS rules,
trial budget, multiplicity policy, canonical knowledge or factor verdict. Do
not include private chain-of-thought, absolute Host paths, empirical results,
OOS bytes, Markdown or commentary.

Write exactly one JSON object to `{invocation.private_output_path}` with this
outer shape and no additional keys:

```json
{json.dumps(output_template, ensure_ascii=False, indent=2, sort_keys=True)}
```
"""


def _contains_forbidden_output(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(str(key) in _FORBIDDEN_OUTPUT_RESULT_KEYS for key in value):
            return True
        return any(_contains_forbidden_output(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_output(item) for item in value)
    return bool(
        isinstance(value, str)
        and re.match(
            r"^/(?:Users|home|tmp|private|var|etc|opt)/",
            value,
        )
    )


def _read_private_output(path: Path) -> tuple[dict[str, Any], bytes]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvoChildAuthoringError([_token("private_output_unreadable")]) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_PRIVATE_OUTPUT_BYTES
        ):
            _raise("private_output_unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            _raise("private_output_changed")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildAuthoringError([_token("private_output_invalid_json")]) from exc
    if not isinstance(payload, dict):
        _raise("private_output_object")
    return payload, raw


def _normalize_agent_bundle(
    *,
    private_output: Mapping[str, Any],
    task: Mapping[str, Any],
    material: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    if set(private_output) != {
        "contract_version",
        "status",
        "public_research_record",
    }:
        _raise("private_output_fields")
    if (
        private_output.get("contract_version") != PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
        or private_output.get("status") != "PASS"
        or private_reasoning_paths(private_output)
        or _contains_forbidden_output(private_output)
    ):
        _raise("private_output_contract")
    record = private_output.get("public_research_record")
    if not isinstance(record, Mapping) or set(record) != set(_SEMANTIC_KEYS):
        _raise("semantic_bundle_exact_keys")
    state = deepcopy(record["research_state"])
    conjecture = deepcopy(record["research_conjecture"])
    approaches = deepcopy(record["approach_registry"])
    base_ledger = deepcopy(record["base_search_trial_ledger"])
    child_plan = deepcopy(record["agent_authored_child_web_research_plan"])
    if not all(
        isinstance(item, dict)
        for item in (state, conjecture, approaches, base_ledger, child_plan)
    ):
        _raise("semantic_object_required")

    identity = task["identity"]
    selected = task["selected_revision"]
    allocation = task["fresh_oos_allocation_public_binding"]
    parent_conjecture = material["source_payloads"]["parent_research_conjecture"]
    parent_evidence = parent_conjecture.get("evidence_policy")
    evidence = conjecture.get("evidence_policy")
    conjecture_identity = conjecture.get("identity")
    if (
        state.get("report_id") != identity["report_id"]
        or state.get("factor_id") != identity["factor_id"]
        or state.get("research_id") != identity["research_id"]
        or conjecture.get("report_id") != identity["report_id"]
        or conjecture.get("factor_id") != identity["factor_id"]
        or approaches.get("report_id") != identity["report_id"]
        or not isinstance(conjecture_identity, Mapping)
        or conjecture_identity.get("research_id") != identity["research_id"]
        or conjecture_identity.get("formula_hash") != selected["child_formula_hash"]
        or conjecture_identity.get("workspace_manifest_sha256")
        != sha256_file(root / "manifest.json")
        or conjecture_identity.get("parent_artifact_sha256")
        != task["revision_evidence_refs"]["pre_oos_root_synthesis"]["sha256"]
        or not isinstance(parent_evidence, Mapping)
        or not isinstance(evidence, Mapping)
        or any(
            evidence.get(field) != parent_evidence.get(field)
            for field in _PROTECTED_EVIDENCE_FIELDS
            if field in parent_evidence or field in evidence
        )
        or evidence.get("oos_start") != allocation["oos_window"]["start"]
        or evidence.get("oos_end") != allocation["oos_window"]["end"]
        or evidence.get("sealed_oos_token_hash")
        != allocation["sealed_token_sha256"]
    ):
        _raise("semantic_identity_or_constitution_binding")
    state_reasons = validate_research_state(state)
    conjecture_reasons = validate_research_conjecture(conjecture)
    approach_reasons = validate_approach_registry(approaches, stage="pre_council")
    if state_reasons or conjecture_reasons or approach_reasons:
        raise EvoChildAuthoringError(
            [
                _token(f"research_state:{reason}") for reason in state_reasons
            ]
            + [
                _token(f"research_conjecture:{reason}")
                for reason in conjecture_reasons
            ]
            + [
                _token(f"approach_registry:{reason}") for reason in approach_reasons
            ]
        )

    if set(base_ledger) != _BASE_LEDGER_FIELDS:
        _raise("base_ledger_fields")
    trials = base_ledger.get("trials")
    if (
        base_ledger.get("version") != SEARCH_TRIAL_LEDGER_VERSION
        or base_ledger.get("search_status") != "FROZEN"
        or base_ledger.get("report_id") != identity["report_id"]
        or base_ledger.get("factor_id") != identity["factor_id"]
        or isinstance(base_ledger.get("freeze_sequence"), bool)
        or not isinstance(base_ledger.get("freeze_sequence"), int)
        or base_ledger.get("freeze_sequence", 0) < 1
        or not isinstance(trials, list)
        or not trials
        or any(not isinstance(item, Mapping) for item in trials)
        or base_ledger.get("trial_count") != len(trials or [])
    ):
        _raise("base_ledger_contract")
    hypothesis_ids = {
        item.get("hypothesis_id")
        for item in conjecture.get("hypotheses") or []
        if isinstance(item, Mapping)
    }
    trial_ids = [item.get("trial_id") for item in trials]
    if (
        len(trial_ids) != len(set(trial_ids))
        or any(not _safe_id(trial_id) for trial_id in trial_ids)
        or any(
            item.get("status")
            not in {"REGISTERED_NOT_EVALUATED", "REGISTERED_DIAGNOSTIC_NOT_EVALUATED"}
            or item.get("hypothesis_id") not in hypothesis_ids
            or bool(set(item) & _FORBIDDEN_TRIAL_RESULT_FIELDS)
            for item in trials
        )
    ):
        _raise("base_ledger_trials")
    trial_budget = evidence.get("trial_budget")
    if (
        isinstance(trial_budget, bool)
        or not isinstance(trial_budget, int)
        or len(trials) > trial_budget
    ):
        _raise("base_ledger_trial_budget")
    from factor_factory.evo_child_preregistration import (
        project_evo_child_search_identities,
    )

    search_identity = project_evo_child_search_identities(conjecture)
    expected_derived = {
        "trial_set_sha256": stable_json_hash(trials),
        "candidate_space_sha256": search_identity["candidate_space_sha256"],
        "selected_hypothesis_sha256": search_identity[
            "selected_hypothesis_sha256"
        ],
    }
    for field, expected in expected_derived.items():
        supplied = base_ledger.get(field)
        if supplied not in {expected, LEDGER_DERIVED_HASH_SENTINEL}:
            _raise(f"base_ledger_derived_field:{field}")
        base_ledger[field] = expected

    from factor_factory.console.web_research_plan import (
        WebResearchPlanError,
        validate_authorized_evo_child_web_research_plan,
    )

    try:
        validate_authorized_evo_child_web_research_plan(
            workspace=root,
            parent_plan=material["source_payloads"]["parent_web_research_plan"],
            child_plan=child_plan,
            parent_report_id=str(task["parent_report_id"]),
            child_report_id=str(task["child_report_id"]),
            research_conjecture=conjecture,
            approach_registry=approaches,
            fresh_oos_allocation=dict(allocation),
            selected_formula=str(selected["child_formula"]),
            selected_formula_hash=str(selected["child_formula_hash"]),
        )
    except WebResearchPlanError as exc:
        raise EvoChildAuthoringError(
            [_token(f"child_web_plan:{reason}") for reason in exc.reasons]
        ) from exc
    return {
        "research_state": state,
        "research_conjecture": conjecture,
        "approach_registry": approaches,
        "base_search_trial_ledger": base_ledger,
        "agent_authored_child_web_research_plan": child_plan,
    }


def _adapter_completion_reasons(
    *,
    receipt: Any,
    invocation: ResearchOrgSessionInvocation,
    outcome: ResearchOrgSessionOutcome,
    trust_manifest: Mapping[str, Any],
    installation_id: str,
    output_sha256: str,
    output_size_bytes: int,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["adapter_receipt_object"]
    if set(receipt) != _ADAPTER_RECEIPT_FIELDS:
        reasons.append("adapter_receipt_fields")
    reasons.extend(
        f"adapter_receipt_signature:{reason}"
        for reason in verify_signed_receipt_with_manifest(
            receipt,
            trust_manifest=trust_manifest,
            expected_issuer="runtime_adapter",
        )
    )
    expected_identity = {
        **dict(invocation.identity),
        "runtime_id": invocation.runtime_id,
        "task_id": invocation.task_id,
        "role_id": invocation.role_id,
        "attempt_id": invocation.attempt_id,
        "attempt_no": invocation.attempt_number,
    }
    bindings = receipt.get("bindings")
    ordering = receipt.get("ordering")
    session = receipt.get("session")
    receipt_outcome = receipt.get("outcome")
    signed_runtime = (
        session.get("runtime") if isinstance(session, Mapping) else None
    )
    if receipt.get("receipt_type") != "COMPLETED" or receipt.get("identity") != expected_identity:
        reasons.append("adapter_receipt_identity")
    expected_bindings = {
        "plan_sha256": invocation.plan_sha256,
        "task_sha256": invocation.task_sha256,
        "context_manifest_sha256": invocation.context_manifest_sha256,
        "dependency_admissions": [
            dict(item) for item in invocation.dependency_admissions
        ],
        "idempotency_key": invocation.idempotency_key,
        "adapter_challenge": invocation.adapter_challenge,
    }
    if bindings != expected_bindings:
        reasons.append("adapter_receipt_bindings")
    expected_ordering = {
        "scheduler_epoch": invocation.scheduler_epoch,
        "dispatch_event_seq": invocation.dispatch_event_seq,
        "issued_at_utc": outcome.finished_at_utc,
        "started_at_utc": outcome.started_at_utc,
        "finished_at_utc": outcome.finished_at_utc,
    }
    if ordering != expected_ordering:
        reasons.append("adapter_receipt_ordering")
    if (
        not isinstance(session, Mapping)
        or set(session) != _ADAPTER_SESSION_FIELDS
        or session.get("session_uid") != invocation.session_id
        or session.get("runtime_handle_sha256")
        != hashlib.sha256(invocation.runtime_instance_id.encode("utf-8")).hexdigest()
        or session.get("adapter_id") != installation_id
        or session.get("parent_session_uid") is not None
        or session.get("lease_epoch") != invocation.scheduler_epoch
        or not _is_sha256(session.get("provider_handle_sha256"))
        or not _is_sha256(session.get("adapter_build_sha256"))
        or not _is_sha256(session.get("isolation_profile_sha256"))
        or not isinstance(session.get("container_image_digest"), str)
        or not session.get("container_image_digest")
    ):
        reasons.append("adapter_receipt_session")
    if signed_runtime != {
        "provider": outcome.provider,
        "model": outcome.model,
        "transport": outcome.transport,
        "isolation_class": outcome.isolation_class,
        "owned_termination_supported": outcome.owned_termination_supported,
    }:
        reasons.append("adapter_receipt_runtime")
    if (
        not isinstance(receipt_outcome, Mapping)
        or set(receipt_outcome) != _ADAPTER_OUTCOME_FIELDS
        or receipt_outcome.get("returncode") != 0
        or receipt_outcome.get("cancelled") is not False
        or receipt_outcome.get("error_class") is not None
        or receipt_outcome.get("private_output_sha256") != output_sha256
        or receipt_outcome.get("private_output_size_bytes") != output_size_bytes
        or receipt_outcome.get("termination_confirmed") is not True
    ):
        reasons.append("adapter_receipt_outcome")
    if (
        outcome.returncode != 0
        or outcome.cancelled
        or not outcome.owned_termination_supported
        or outcome.session_id != invocation.session_id
        or outcome.runtime_instance_id != invocation.runtime_instance_id
        or outcome.isolation_class not in _EVO_CHILD_AUTHORING_ISOLATION_CLASSES
        or _TRANSPORT_BY_ISOLATION.get(outcome.isolation_class)
        != outcome.transport
        or not isinstance(outcome.provider, str)
        or not outcome.provider
        or not isinstance(outcome.model, str)
        or not outcome.model
        or outcome.provider_session_handle_sha256
        != (
            session.get("provider_handle_sha256")
            if isinstance(session, Mapping)
            else None
        )
    ):
        reasons.append("runtime_outcome")
    return list(dict.fromkeys(reasons))


def _source_binding_reasons(material: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for raw_path, expected in material.get("source_file_sha256s", {}).items():
        path = raw_path if isinstance(raw_path, Path) else Path(str(raw_path))
        if (
            not _is_sha256(expected)
            or path.is_symlink()
            or not path.is_file()
            or sha256_file(path) != expected
        ):
            reasons.append(f"source_changed:{path.name}")
    return reasons


def _safe_public_parent(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise EvoChildAuthoringError([_token("public_output_outside_workspace")]) from exc
    current = root
    for part in relative.parent.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            _raise("public_output_parent_unsafe")
        try:
            current.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise EvoChildAuthoringError([_token("public_output_parent_unsafe")]) from exc


def _write_public_once(root: Path, path: Path, raw: bytes) -> bool:
    _safe_public_parent(root, path)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            _raise(f"immutable_output_conflict:{path.name}")
        return False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    os.fchmod(descriptor, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("evo_child_authoring_public_short_write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
                _raise(f"immutable_output_conflict:{path.name}")
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


@contextmanager
def _authoring_lock(private: Path, child_report_id: str):
    """Hold one private child lease across scan, Agent run, and admission."""

    if not _safe_id(child_report_id):
        _raise("authoring_lock_child")
    lock_root = private / ".evo-child-locks"
    try:
        lock_root.mkdir(mode=0o700, exist_ok=True)
        lock_metadata = lock_root.lstat()
    except OSError as exc:
        raise EvoChildAuthoringError([_token("authoring_lock")]) from exc
    if (
        stat.S_ISLNK(lock_metadata.st_mode)
        or not stat.S_ISDIR(lock_metadata.st_mode)
        or lock_metadata.st_uid != os.geteuid()
        or lock_metadata.st_mode & 0o077
    ):
        _raise("authoring_lock")
    path = lock_root / (
        "authoring__"
        + stable_json_hash(
            {
                "scope": "evo_child_authoring_lock_v1",
                "child_report_id": child_report_id,
            }
        )[:32]
        + ".lock"
    )
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
            _raise("authoring_lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def admit_completed_evo_child_authoring(
    *,
    invocation: ResearchOrgSessionInvocation,
    outcome: ResearchOrgSessionOutcome,
    prepared: Mapping[str, Any],
    trust_root: Path | str,
    installation_id: str,
    _lock_held: bool = False,
) -> dict[str, Any]:
    """Validate the real Agent completion and Host-countersign its exact bundle."""

    task = prepared.get("task")
    material = prepared.get("material")
    if not isinstance(task, Mapping) or not isinstance(material, Mapping):
        _raise("prepared_material")
    root = invocation.workspace.resolve(strict=True)
    if (
        invocation.role_id != EVO_CHILD_AUTHORING_ROLE_ID
        or invocation.task_sha256 != task.get("task_sha256")
        or invocation.identity != task.get("identity")
        or invocation.parent_session_uid is not None
    ):
        _raise("invocation_binding")
    expected_task = _project_authoring_task(
        root=root,
        parent_report_id=str(task.get("parent_report_id") or ""),
        child_report_id=str(task.get("child_report_id") or ""),
        material=material,
    )
    if dict(task) != expected_task:
        _raise("task_projection_changed")
    source_reasons = _source_binding_reasons(material)
    if source_reasons:
        raise EvoChildAuthoringError([_token(reason) for reason in source_reasons])
    private_output, private_raw = _read_private_output(invocation.private_output_path)
    private_sha = hashlib.sha256(private_raw).hexdigest()
    adapter_reasons = _adapter_completion_reasons(
        receipt=outcome.adapter_receipt,
        invocation=invocation,
        outcome=outcome,
        trust_manifest=material["trust_manifest"],
        installation_id=installation_id,
        output_sha256=private_sha,
        output_size_bytes=len(private_raw),
    )
    if adapter_reasons:
        raise EvoChildAuthoringError(
            [_token(f"adapter_completion:{reason}") for reason in adapter_reasons]
        )
    bundle = _normalize_agent_bundle(
        private_output=private_output,
        task=task,
        material=material,
        root=root,
    )
    trust_store = load_runtime_trust_store(
        Path(trust_root),
        installation_id=installation_id,
    )
    if trust_store.public_manifest != material["trust_manifest"]:
        _raise("host_trust_store_manifest")
    paths = evo_child_authoring_paths(root, str(task["child_report_id"]))
    lock_context = (
        nullcontext()
        if _lock_held
        else _authoring_lock(
            invocation.private_attempt_root.parent.resolve(strict=True),
            str(task["child_report_id"]),
        )
    )
    with lock_context:
        source_reasons = _source_binding_reasons(material)
        if source_reasons:
            raise EvoChildAuthoringError(
                [_token(reason) for reason in source_reasons]
            )
        written = {
            "task": _write_public_once(
                root,
                paths["task"],
                canonical_json_bytes(task),
            ),
            "agent_output": _write_public_once(
                root,
                paths["agent_output"],
                private_raw,
            ),
            "semantic_bundle": _write_public_once(
                root,
                paths["semantic_bundle"],
                canonical_json_bytes(bundle),
            ),
            "adapter_receipt": _write_public_once(
                root,
                paths["adapter_receipt"],
                canonical_json_bytes(dict(outcome.adapter_receipt or {})),
            ),
        }
        runtime_attestation = {
            "session_id": invocation.session_id,
            "runtime_instance_id": invocation.runtime_instance_id,
            "provider": outcome.provider,
            "model": outcome.model,
            "transport": outcome.transport,
            "isolation_class": outcome.isolation_class,
            "owned_termination_supported": outcome.owned_termination_supported,
            "termination_confirmed": (
                (outcome.adapter_receipt or {}).get("outcome", {}).get(
                    "termination_confirmed"
                )
            ),
            "parent_session_uid": None,
        }
        core = {
            "receipt_type": EVO_CHILD_AUTHORING_RECEIPT_TYPE,
            "admission_contract_version": EVO_CHILD_AUTHORING_ADMISSION_VERSION,
            "status": EVO_CHILD_AUTHORING_STATUS,
            "identity": dict(task["identity"]),
            "parent_report_id": task["parent_report_id"],
            "child_report_id": task["child_report_id"],
            "role_id": EVO_CHILD_AUTHORING_ROLE_ID,
            "trust_manifest_sha256": material["trust_manifest"][
                "manifest_sha256"
            ],
            "trust_manifest_ref": _file_ref(
                root,
                material["trust_manifest_path"],
            ),
            "authorization_ticket_ref": dict(task["authorization_ticket_ref"]),
            "task_ref": _file_ref(root, paths["task"]),
            "agent_private_output_ref": _file_ref(root, paths["agent_output"]),
            "semantic_bundle_contract_version": (
                EVO_CHILD_AUTHORING_BUNDLE_VERSION
            ),
            "semantic_bundle_ref": _file_ref(root, paths["semantic_bundle"]),
            "adapter_completion_receipt_ref": _file_ref(
                root,
                paths["adapter_receipt"],
            ),
            "adapter_completion_receipt_id": outcome.adapter_receipt["receipt_id"],
            "runtime_attestation": runtime_attestation,
            "deterministic_normalization": {
                "allowed": True,
                "object": "base_search_trial_ledger",
                "fields": list(_LEDGER_DERIVED_FIELDS),
                "semantic_generation_allowed": False,
            },
            "authority": {
                "scope": "AGENT_SEMANTIC_AUTHORSHIP_ADMISSION_ONLY",
                "agent_semantics_admitted": True,
                "host_semantic_generation_allowed": False,
                "child_preregistration_materialization_allowed": True,
                "child_execution_allowed": False,
                "oos_release_allowed": False,
                "oos_accessed": False,
                "factor_verdict": "NOT_ISSUED",
                "canonical_memory_write_allowed": False,
                "skill_or_policy_mutation_allowed": False,
            },
        }
        admission = trust_store.sign("host_admission", core)
        written["admission"] = _write_public_once(
            root,
            paths["admission"],
            canonical_json_bytes(admission),
        )
    validated = validate_evo_child_authoring_admission(
        workspace_root=root,
        parent_report_id=str(task["parent_report_id"]),
        child_report_id=str(task["child_report_id"]),
        agent_authoring_admission=paths["admission"],
        expected_host_trust_manifest_sha256=str(
            material["trust_manifest"]["manifest_sha256"]
        ),
    )
    return {
        "verdict": "PASS",
        "status": EVO_CHILD_AUTHORING_STATUS,
        "admission": validated["admission"],
        "admission_ref": _file_ref(root, paths["admission"]),
        "semantic_bundle": validated["semantic_bundle"],
        "semantic_bundle_ref": _file_ref(root, paths["semantic_bundle"]),
        "written": written,
        "idempotent_replay": False,
        "authority": dict(validated["admission"]["authority"]),
    }


def _authoring_attempt_digest(
    *,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    generation: int,
) -> str:
    return stable_json_hash(
        {
            "scope": "evo_child_authoring_attempt_v2",
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
            "expected_host_trust_manifest_sha256": (
                expected_host_trust_manifest_sha256
            ),
            "generation": generation,
        }
    )


def _termination_proof_reasons(
    proof: Any,
    *,
    runtime_instance_id: str,
    trust_store: Any,
    installation_id: str,
) -> list[str]:
    if not isinstance(proof, Mapping):
        return ["termination_proof_object"]
    reasons = [
        f"termination_proof_signature:{reason}"
        for reason in trust_store.verify(
            proof, expected_issuer="runtime_adapter"
        )
    ]
    identity = proof.get("identity")
    ordering = proof.get("ordering")
    termination = proof.get("termination")
    authority = proof.get("authority")
    if set(proof) != {
        "contract_version",
        "receipt_type",
        "identity",
        "ordering",
        "termination",
        "authority",
        "issuer",
        "receipt_id",
        "signature",
    }:
        reasons.append("termination_proof_fields")
    if proof.get("receipt_type") != "RESEARCH_ORG_CONTAINER_TERMINATION":
        reasons.append("termination_proof_type")
    if identity != {
        "runtime_instance_id": runtime_instance_id,
        "runtime_handle_sha256": hashlib.sha256(
            runtime_instance_id.encode("utf-8")
        ).hexdigest(),
        "adapter_id": installation_id,
    }:
        reasons.append("termination_proof_identity")
    if (
        not isinstance(ordering, Mapping)
        or set(ordering) != {"issued_at_utc"}
        or not isinstance(ordering.get("issued_at_utc"), str)
        or not ordering.get("issued_at_utc")
    ):
        reasons.append("termination_proof_ordering")
    if (
        not isinstance(termination, Mapping)
        or set(termination)
        != {
            "initial_state",
            "ownership_labels_verified",
            "remove_attempted",
            "inspect_not_found",
            "final_state",
            "termination_confirmed",
        }
        or termination.get("initial_state")
        not in {"ABSENT", "OWNED_PRESENT"}
        or type(termination.get("ownership_labels_verified")) is not bool
        or type(termination.get("remove_attempted")) is not bool
        or termination.get("inspect_not_found") is not True
        or termination.get("final_state") != "ABSENT"
        or termination.get("termination_confirmed") is not True
        or (
            termination.get("initial_state") == "OWNED_PRESENT"
            and (
                termination.get("ownership_labels_verified") is not True
                or termination.get("remove_attempted") is not True
            )
        )
    ):
        reasons.append("termination_proof_outcome")
    if authority != {
        "scope": "OWNED_CONTAINER_TERMINATION_ONLY",
        "retry_authorized": False,
        "factor_verdict": "NOT_ISSUED",
    }:
        reasons.append("termination_proof_authority")
    return list(dict.fromkeys(reasons))


def _targeted_reconcile_launch(
    *,
    runner: EvoChildAuthoringRunner,
    invocation: ResearchOrgSessionInvocation,
    trust_store: Any,
    installation_id: str,
) -> Mapping[str, Any]:
    reconcile = getattr(runner, "reconcile_research_org_session", None)
    if not callable(reconcile):
        _raise("targeted_reconcile_unavailable")
    try:
        proof = reconcile(invocation.runtime_instance_id)
    except Exception as exc:  # noqa: BLE001 - closed recovery boundary.
        raise EvoChildAuthoringError(
            [_token(f"targeted_reconcile_failed:{type(exc).__name__}")]
        ) from exc
    reasons = _termination_proof_reasons(
        proof,
        runtime_instance_id=invocation.runtime_instance_id,
        trust_store=trust_store,
        installation_id=installation_id,
    )
    if reasons:
        raise EvoChildAuthoringError(
            [_token(f"targeted_reconcile:{reason}") for reason in reasons]
        )
    return proof


def _run_and_admit_evo_child_authoring_locked(
    *,
    runner: EvoChildAuthoringRunner,
    workspace_root: Path | str,
    worktree: Path | str,
    private_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    trust_root: Path | str,
    installation_id: str,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    root = Path(workspace_root).expanduser().resolve(strict=True)
    tree = Path(worktree).expanduser().resolve(strict=True)
    private = _safe_private_root(
        Path(private_root), workspace=root, worktree=tree
    )
    trust_store = load_runtime_trust_store(
        Path(trust_root), installation_id=installation_id
    )
    existing_path = evo_child_authoring_admission_path(root, child_report_id)
    if existing_path.exists() or existing_path.is_symlink():
        validated = validate_evo_child_authoring_admission(
            workspace_root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            agent_authoring_admission=existing_path,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        return {
            "verdict": "PASS",
            "status": EVO_CHILD_AUTHORING_STATUS,
            "admission": validated["admission"],
            "admission_ref": _file_ref(root, existing_path),
            "semantic_bundle": validated["semantic_bundle"],
            "semantic_bundle_ref": _file_ref(
                root, validated["semantic_bundle_path"]
            ),
            "written": {
                "task": False,
                "agent_output": False,
                "semantic_bundle": False,
                "adapter_receipt": False,
                "admission": False,
            },
            "idempotent_replay": True,
            "authority": dict(validated["authority"]),
        }
    paths = evo_child_authoring_paths(root, child_report_id)
    partial_public = [
        path
        for name, path in paths.items()
        if name != "admission" and (path.exists() or path.is_symlink())
    ]
    completion_journals = sorted(
        private.glob("evo-child-authoring-*/completion_journal.json")
    )
    launch_journals = sorted(
        private.glob("evo-child-authoring-*/launch_journal.json")
    )
    if completion_journals:
        if len(completion_journals) != 1:
            _raise("completion_journal_count")
        journal_path = completion_journals[0]
        journal = _load_json_file(
            journal_path, label="completion_journal", canonical=True
        )
        signature_reasons = trust_store.verify(
            journal, expected_issuer="host_admission"
        )
        invocation_raw = journal.get("invocation")
        outcome_raw = journal.get("outcome")
        if (
            signature_reasons
            or journal.get("receipt_type")
            != "EVO_CHILD_AUTHORING_COMPLETION_JOURNAL"
            or journal.get("parent_report_id") != parent_report_id
            or journal.get("child_report_id") != child_report_id
            or journal.get("expected_host_trust_manifest_sha256")
            != expected_host_trust_manifest_sha256
            or not isinstance(invocation_raw, Mapping)
            or not isinstance(outcome_raw, Mapping)
        ):
            _raise("completion_journal_invalid")
        invocation = _deserialize_authoring_invocation(
            dict(invocation_raw), root=root, tree=tree, private=private
        )
        outcome = _deserialize_authoring_outcome(dict(outcome_raw))
        material = _authorization_material(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        task = _project_authoring_task(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            material=material,
        )
        if (
            invocation.task_sha256 != task.get("task_sha256")
            or journal.get("task_sha256") != task.get("task_sha256")
        ):
            _raise("completion_journal_task")
        return admit_completed_evo_child_authoring(
            invocation=invocation,
            outcome=outcome,
            prepared={"task": task, "material": material},
            trust_root=trust_root,
            installation_id=installation_id,
            _lock_held=True,
        )
    if partial_public:
        _raise("partial_public_without_completion_journal")
    generation = 1
    launches: list[
        tuple[int, Path, dict[str, Any], ResearchOrgSessionInvocation]
    ] = []
    for launch_path in launch_journals:
        launch_payload = _load_json_file(
            launch_path, label="launch_journal", canonical=True
        )
        generation_raw = launch_payload.get("generation")
        invocation_raw = launch_payload.get("invocation")
        if (
            trust_store.verify(
                launch_payload, expected_issuer="host_admission"
            )
            or launch_payload.get("receipt_type")
            != "EVO_CHILD_AUTHORING_LAUNCH_JOURNAL"
            or launch_payload.get("parent_report_id") != parent_report_id
            or launch_payload.get("child_report_id") != child_report_id
            or launch_payload.get("expected_host_trust_manifest_sha256")
            != expected_host_trust_manifest_sha256
            or isinstance(generation_raw, bool)
            or not isinstance(generation_raw, int)
            or not 1 <= generation_raw <= 32
            or not isinstance(invocation_raw, Mapping)
        ):
            _raise("launch_journal_invalid")
        expected_attempt = _authoring_attempt_digest(
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            generation=generation_raw,
        )
        invocation = _deserialize_authoring_invocation(
            dict(invocation_raw),
            root=root,
            tree=tree,
            private=private,
            require_output=False,
        )
        if (
            launch_payload.get("attempt_seed_sha256") != expected_attempt
            or invocation.attempt_number != generation_raw
            or invocation.scheduler_epoch != generation_raw
            or invocation.dispatch_event_seq != generation_raw
            or invocation.private_attempt_root
            != private / f"evo-child-authoring-{expected_attempt[:32]}"
            or launch_path.parent != invocation.private_attempt_root
        ):
            _raise("launch_journal_attempt")
        launches.append(
            (generation_raw, launch_path, launch_payload, invocation)
        )
    launches.sort(key=lambda item: item[0])
    if [item[0] for item in launches] != list(range(1, len(launches) + 1)):
        _raise("launch_generation_sequence")
    for index, (
        launch_generation,
        launch_path,
        launch_payload,
        launch_invocation,
    ) in enumerate(launches):
        abandoned_path = launch_path.parent / "abandoned_journal.json"
        retry_path = launch_path.parent / "retry_authorized_journal.json"
        abandoned = (
            _load_json_file(
                abandoned_path,
                label="abandoned_journal",
                canonical=True,
            )
            if abandoned_path.exists() or abandoned_path.is_symlink()
            else None
        )
        retry = (
            _load_json_file(
                retry_path,
                label="retry_authorized_journal",
                canonical=True,
            )
            if retry_path.exists() or retry_path.is_symlink()
            else None
        )
        if retry is not None and abandoned is None:
            _raise("retry_without_abandonment")
        if abandoned is None:
            if index != len(launches) - 1:
                _raise("unclosed_historical_launch")
            termination_proof = _targeted_reconcile_launch(
                runner=runner,
                invocation=launch_invocation,
                trust_store=trust_store,
                installation_id=installation_id,
            )
            abandoned = trust_store.sign(
                "host_admission",
                {
                    "receipt_type": "EVO_CHILD_AUTHORING_ABANDONED",
                    "parent_report_id": parent_report_id,
                    "child_report_id": child_report_id,
                    "generation": launch_generation,
                    "launch_receipt_id": launch_payload["receipt_id"],
                    "runtime_instance_id": (
                        launch_invocation.runtime_instance_id
                    ),
                    "termination_proof": dict(termination_proof),
                    "authority": {
                        "launch_abandoned": True,
                        "retry_authorized": False,
                        "child_execution_allowed": False,
                        "factor_verdict": "NOT_ISSUED",
                    },
                },
            )
            _private_write_once(
                abandoned_path, canonical_json_bytes(abandoned)
            )
        termination_proof = abandoned.get("termination_proof")
        if (
            trust_store.verify(abandoned, expected_issuer="host_admission")
            or abandoned.get("receipt_type")
            != "EVO_CHILD_AUTHORING_ABANDONED"
            or abandoned.get("parent_report_id") != parent_report_id
            or abandoned.get("child_report_id") != child_report_id
            or abandoned.get("generation") != launch_generation
            or abandoned.get("launch_receipt_id")
            != launch_payload.get("receipt_id")
            or abandoned.get("runtime_instance_id")
            != launch_invocation.runtime_instance_id
            or abandoned.get("authority")
            != {
                "launch_abandoned": True,
                "retry_authorized": False,
                "child_execution_allowed": False,
                "factor_verdict": "NOT_ISSUED",
            }
            or _termination_proof_reasons(
                termination_proof,
                runtime_instance_id=launch_invocation.runtime_instance_id,
                trust_store=trust_store,
                installation_id=installation_id,
            )
        ):
            _raise("abandoned_journal_invalid")
        if retry is None:
            retry = trust_store.sign(
                "host_admission",
                {
                    "receipt_type": "EVO_CHILD_AUTHORING_RETRY_AUTHORIZED",
                    "parent_report_id": parent_report_id,
                    "child_report_id": child_report_id,
                    "abandoned_receipt_id": abandoned["receipt_id"],
                    "prior_generation": launch_generation,
                    "next_generation": launch_generation + 1,
                    "authority": {
                        "new_agent_attempt_allowed": True,
                        "semantic_authority_granted": False,
                        "child_execution_allowed": False,
                        "factor_verdict": "NOT_ISSUED",
                    },
                },
            )
            _private_write_once(retry_path, canonical_json_bytes(retry))
        if (
            trust_store.verify(retry, expected_issuer="host_admission")
            or retry.get("receipt_type")
            != "EVO_CHILD_AUTHORING_RETRY_AUTHORIZED"
            or retry.get("parent_report_id") != parent_report_id
            or retry.get("child_report_id") != child_report_id
            or retry.get("abandoned_receipt_id")
            != abandoned.get("receipt_id")
            or retry.get("prior_generation") != launch_generation
            or retry.get("next_generation") != launch_generation + 1
            or retry.get("authority")
            != {
                "new_agent_attempt_allowed": True,
                "semantic_authority_granted": False,
                "child_execution_allowed": False,
                "factor_verdict": "NOT_ISSUED",
            }
        ):
            _raise("retry_authorization_invalid")
    generation = len(launches) + 1
    if generation > 32:
        _raise("authoring_retry_limit")
    deterministic_attempt = _authoring_attempt_digest(
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        generation=generation,
    )
    invocation, prepared = prepare_evo_child_authoring_session(
        workspace_root=root,
        worktree=tree,
        private_root=private,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        trust_root=trust_root,
        installation_id=installation_id,
        timeout_seconds=timeout_seconds,
        attempt_token=deterministic_attempt[:32],
        attempt_number=generation,
        adapter_challenge=stable_json_hash(
            {
                "scope": "evo_child_authoring_adapter_challenge_v2",
                "attempt_sha256": deterministic_attempt,
                "generation": generation,
            }
        ),
    )
    launch = trust_store.sign(
        "host_admission",
        {
            "receipt_type": "EVO_CHILD_AUTHORING_LAUNCH_JOURNAL",
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
            "expected_host_trust_manifest_sha256": (
                expected_host_trust_manifest_sha256
            ),
            "generation": generation,
            "attempt_seed_sha256": deterministic_attempt,
            "task_sha256": invocation.task_sha256,
            "invocation": _serialize_authoring_invocation(invocation),
            "authority": {
                "authoring_inflight_only": True,
                "rerun_after_unknown_crash_allowed": False,
                "child_execution_allowed": False,
            },
        },
    )
    _private_write_once(
        invocation.private_attempt_root / "launch_journal.json",
        canonical_json_bytes(launch),
    )
    outcome = runner.run_research_org_session(invocation)
    completion = trust_store.sign(
        "host_admission",
        {
            "receipt_type": "EVO_CHILD_AUTHORING_COMPLETION_JOURNAL",
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
            "expected_host_trust_manifest_sha256": (
                expected_host_trust_manifest_sha256
            ),
            "task_sha256": invocation.task_sha256,
            "invocation": _serialize_authoring_invocation(invocation),
            "outcome": _serialize_authoring_outcome(outcome),
            "authority": {
                "host_observed_agent_completion": True,
                "public_admission_pending": True,
                "child_execution_allowed": False,
            },
        },
    )
    _private_write_once(
        invocation.private_attempt_root / "completion_journal.json",
        canonical_json_bytes(completion),
    )
    return admit_completed_evo_child_authoring(
        invocation=invocation,
        outcome=outcome,
        prepared=prepared,
        trust_root=trust_root,
        installation_id=installation_id,
        _lock_held=True,
    )


def run_and_admit_evo_child_authoring(
    *,
    runner: EvoChildAuthoringRunner,
    workspace_root: Path | str,
    worktree: Path | str,
    private_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    trust_root: Path | str,
    installation_id: str,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Serialize one child's full authoring lifecycle under a private lease."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    tree = Path(worktree).expanduser().resolve(strict=True)
    private = _safe_private_root(
        Path(private_root), workspace=root, worktree=tree
    )
    child_private = _private_child_scope(
        private,
        namespace="authoring",
        child_report_id=child_report_id,
    )
    with _authoring_lock(child_private, child_report_id):
        return _run_and_admit_evo_child_authoring_locked(
            runner=runner,
            workspace_root=root,
            worktree=tree,
            private_root=child_private,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            trust_root=trust_root,
            installation_id=installation_id,
            timeout_seconds=timeout_seconds,
        )


def _serialize_authoring_invocation(
    invocation: ResearchOrgSessionInvocation,
) -> dict[str, Any]:
    return {
        "identity": dict(invocation.identity),
        "role_id": invocation.role_id,
        "task_id": invocation.task_id,
        "task_sha256": invocation.task_sha256,
        "attempt_id": invocation.attempt_id,
        "attempt_number": invocation.attempt_number,
        "session_id": invocation.session_id,
        "runtime_instance_id": invocation.runtime_instance_id,
        "worktree": str(invocation.worktree),
        "workspace": str(invocation.workspace),
        "private_attempt_root": str(invocation.private_attempt_root),
        "context_root": str(invocation.context_root),
        "private_output_path": str(invocation.private_output_path),
        "cancel_request_path": str(invocation.cancel_request_path),
        "context_manifest_sha256": invocation.context_manifest_sha256,
        "required_skills": list(invocation.required_skills),
        "timeout_seconds": invocation.timeout_seconds,
        "runtime_id": invocation.runtime_id,
        "plan_sha256": invocation.plan_sha256,
        "scheduler_epoch": invocation.scheduler_epoch,
        "dispatch_event_seq": invocation.dispatch_event_seq,
        "idempotency_key": invocation.idempotency_key,
        "adapter_challenge": invocation.adapter_challenge,
        "dependency_admissions": [
            dict(item) for item in invocation.dependency_admissions
        ],
        "parent_session_uid": invocation.parent_session_uid,
    }


def _deserialize_authoring_invocation(
    payload: dict[str, Any],
    *,
    root: Path,
    tree: Path,
    private: Path,
    require_output: bool = True,
) -> ResearchOrgSessionInvocation:
    try:
        invocation = ResearchOrgSessionInvocation(
            **{
                **payload,
                "worktree": Path(payload["worktree"]),
                "workspace": Path(payload["workspace"]),
                "private_attempt_root": Path(payload["private_attempt_root"]),
                "context_root": Path(payload["context_root"]),
                "private_output_path": Path(payload["private_output_path"]),
                "cancel_request_path": Path(payload["cancel_request_path"]),
                "required_skills": tuple(payload["required_skills"]),
                "dependency_admissions": tuple(payload["dependency_admissions"]),
            }
        )
        invocation.private_attempt_root.resolve(strict=True).relative_to(private)
        invocation.context_root.resolve(strict=True).relative_to(
            invocation.private_attempt_root.resolve(strict=True)
        )
        invocation.private_output_path.parent.resolve(strict=True).relative_to(
            invocation.private_attempt_root.resolve(strict=True)
        )
        if require_output:
            invocation.private_output_path.resolve(strict=True).relative_to(
                invocation.private_attempt_root.resolve(strict=True)
            )
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise EvoChildAuthoringError(
            [_token("completion_journal_invocation")]
        ) from exc
    if invocation.workspace.resolve() != root or invocation.worktree.resolve() != tree:
        _raise("completion_journal_workspace")
    return invocation


def _serialize_authoring_outcome(
    outcome: ResearchOrgSessionOutcome,
) -> dict[str, Any]:
    return {
        "returncode": outcome.returncode,
        "session_id": outcome.session_id,
        "runtime_instance_id": outcome.runtime_instance_id,
        "started_at_utc": outcome.started_at_utc,
        "finished_at_utc": outcome.finished_at_utc,
        "provider": outcome.provider,
        "model": outcome.model,
        "transport": outcome.transport,
        "isolation_class": outcome.isolation_class,
        "owned_termination_supported": outcome.owned_termination_supported,
        "cancelled": outcome.cancelled,
        "stdout_tail": outcome.stdout_tail,
        "stderr_tail": outcome.stderr_tail,
        "provider_session_handle_sha256": (
            outcome.provider_session_handle_sha256
        ),
        "adapter_receipt": dict(outcome.adapter_receipt or {}),
    }


def _deserialize_authoring_outcome(payload: dict[str, Any]) -> ResearchOrgSessionOutcome:
    try:
        return ResearchOrgSessionOutcome(**payload)
    except TypeError as exc:
        raise EvoChildAuthoringError(
            [_token("completion_journal_outcome")]
        ) from exc


def _public_read_ref(
    root: Path,
    reference: Any,
    *,
    expected_path: Path,
    label: str,
    canonical: bool = True,
) -> tuple[Path, dict[str, Any], bytes]:
    if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}:
        _raise(f"public_ref_shape:{label}")
    raw_path = reference.get("path")
    if (
        not isinstance(raw_path, str)
        or "\\" in raw_path
        or not _is_sha256(reference.get("sha256"))
    ):
        _raise(f"public_ref_values:{label}")
    relative = PurePosixPath(raw_path)
    path = root.joinpath(*relative.parts)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != raw_path
        or path.resolve(strict=False) != expected_path.resolve(strict=False)
        or not _within_without_symlinks(root, path)
        or path.is_symlink()
        or not path.is_file()
    ):
        _raise(f"public_ref_path:{label}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
        _raise(f"public_ref_hash:{label}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildAuthoringError([_token(f"public_ref_json:{label}")]) from exc
    if not isinstance(payload, dict):
        _raise(f"public_ref_object:{label}")
    if canonical and raw != canonical_json_bytes(payload):
        _raise(f"public_ref_noncanonical:{label}")
    return path, payload, raw


def _public_adapter_reasons(
    *,
    receipt: Mapping[str, Any],
    admission: Mapping[str, Any],
    task: Mapping[str, Any],
    output_raw: bytes,
    trust_manifest: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if set(receipt) != _ADAPTER_RECEIPT_FIELDS:
        reasons.append("adapter_receipt_fields")
    reasons.extend(
        f"adapter_signature:{reason}"
        for reason in verify_signed_receipt_with_manifest(
            receipt,
            trust_manifest=trust_manifest,
            expected_issuer="runtime_adapter",
        )
    )
    attestation = admission.get("runtime_attestation")
    if (
        not isinstance(attestation, Mapping)
        or set(attestation) != _RUNTIME_ATTESTATION_FIELDS
    ):
        return [*reasons, "runtime_attestation"]
    expected_identity = {
        **dict(task["identity"]),
        "runtime_id": receipt.get("identity", {}).get("runtime_id"),
        "task_id": receipt.get("identity", {}).get("task_id"),
        "role_id": EVO_CHILD_AUTHORING_ROLE_ID,
        "attempt_id": receipt.get("identity", {}).get("attempt_id"),
        "attempt_no": receipt.get("identity", {}).get("attempt_no"),
    }
    identity = receipt.get("identity")
    bindings = receipt.get("bindings")
    ordering = receipt.get("ordering")
    session = receipt.get("session")
    outcome = receipt.get("outcome")
    signed_runtime = (
        session.get("runtime") if isinstance(session, Mapping) else None
    )
    if (
        receipt.get("receipt_type") != "COMPLETED"
        or identity != expected_identity
        or not all(
            _safe_id((identity or {}).get(field))
            for field in ("runtime_id", "task_id", "attempt_id")
        )
        or isinstance((identity or {}).get("attempt_no"), bool)
        or not isinstance((identity or {}).get("attempt_no"), int)
        or not 1 <= int((identity or {}).get("attempt_no") or 0) <= 32
    ):
        reasons.append("adapter_identity")
    if (
        not isinstance(bindings, Mapping)
        or set(bindings) != _ADAPTER_BINDING_FIELDS
        or bindings.get("task_sha256") != task.get("task_sha256")
        or bindings.get("plan_sha256")
        != task["parent_frozen_contract_refs"]["parent_web_research_plan"][
            "sha256"
        ]
        or bindings.get("context_manifest_sha256")
        != task.get("context_manifest_sha256")
        or bindings.get("dependency_admissions")
        != [dict(task["authorization_ticket_ref"])]
        or not isinstance(bindings.get("idempotency_key"), str)
        or not bindings.get("idempotency_key")
        or not isinstance(bindings.get("adapter_challenge"), str)
        or not bindings.get("adapter_challenge")
    ):
        reasons.append("adapter_bindings")
    lease_epoch = session.get("lease_epoch") if isinstance(session, Mapping) else None
    if (
        not isinstance(ordering, Mapping)
        or set(ordering) != _ADAPTER_ORDERING_FIELDS
        or ordering.get("scheduler_epoch") != lease_epoch
        or ordering.get("issued_at_utc") != ordering.get("finished_at_utc")
        or any(
            not isinstance(ordering.get(field), str)
            or not ordering.get(field)
            for field in ("issued_at_utc", "started_at_utc", "finished_at_utc")
        )
    ):
        reasons.append("adapter_ordering")
    output_sha = hashlib.sha256(output_raw).hexdigest()
    if (
        not isinstance(session, Mapping)
        or set(session) != _ADAPTER_SESSION_FIELDS
        or session.get("session_uid") != attestation.get("session_id")
        or session.get("runtime_handle_sha256")
        != hashlib.sha256(
            str(attestation.get("runtime_instance_id") or "").encode("utf-8")
        ).hexdigest()
        or session.get("adapter_id") != trust_manifest.get("installation_id")
        or session.get("parent_session_uid") is not None
        or not _is_sha256(session.get("provider_handle_sha256"))
        or not _is_sha256(session.get("adapter_build_sha256"))
        or not _is_sha256(session.get("isolation_profile_sha256"))
        or not isinstance(session.get("container_image_digest"), str)
        or not session.get("container_image_digest")
    ):
        reasons.append("adapter_session")
    if signed_runtime != {
        "provider": attestation.get("provider"),
        "model": attestation.get("model"),
        "transport": attestation.get("transport"),
        "isolation_class": attestation.get("isolation_class"),
        "owned_termination_supported": attestation.get(
            "owned_termination_supported"
        ),
    }:
        reasons.append("adapter_runtime")
    if (
        not isinstance(outcome, Mapping)
        or set(outcome) != _ADAPTER_OUTCOME_FIELDS
        or outcome.get("returncode") != 0
        or outcome.get("cancelled") is not False
        or outcome.get("error_class") is not None
        or outcome.get("private_output_sha256") != output_sha
        or outcome.get("private_output_size_bytes") != len(output_raw)
        or outcome.get("termination_confirmed") is not True
    ):
        reasons.append("adapter_outcome")
    isolation = attestation.get("isolation_class")
    if (
        isolation not in _EVO_CHILD_AUTHORING_ISOLATION_CLASSES
        or _TRANSPORT_BY_ISOLATION.get(str(isolation))
        != attestation.get("transport")
        or not isinstance(attestation.get("provider"), str)
        or not attestation.get("provider")
        or not isinstance(attestation.get("model"), str)
        or not attestation.get("model")
        or attestation.get("owned_termination_supported") is not True
        or attestation.get("termination_confirmed") is not True
        or attestation.get("parent_session_uid") is not None
    ):
        reasons.append("runtime_attestation")
    return list(dict.fromkeys(reasons))


def validate_evo_child_authoring_admission(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    agent_authoring_admission: Path | str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    """Public, exact-replay validator for Agent authorship plus Host admission."""

    root = Path(workspace_root).expanduser().resolve(strict=True)
    paths = evo_child_authoring_paths(root, child_report_id)
    supplied_path = Path(agent_authoring_admission).expanduser()
    if not supplied_path.is_absolute():
        supplied_path = root / supplied_path
    if (
        not _safe_id(parent_report_id)
        or not _safe_id(child_report_id)
        or parent_report_id == child_report_id
        or not _is_sha256(expected_host_trust_manifest_sha256)
        or supplied_path.resolve(strict=False) != paths["admission"].resolve(strict=False)
    ):
        _raise("admission_inputs")
    admission = _load_json_file(
        paths["admission"],
        label="authoring_admission",
        canonical=True,
    )
    manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
    if (
        not isinstance(manifest, Mapping)
        or validate_public_trust_manifest(manifest)
        or manifest.get("manifest_sha256")
        != expected_host_trust_manifest_sha256
    ):
        _raise("workspace_public_trust_manifest")
    signature_reasons = verify_signed_receipt_with_manifest(
        admission,
        trust_manifest=manifest,
        expected_issuer="host_admission",
    )
    if signature_reasons:
        raise EvoChildAuthoringError(
            [_token(f"host_admission_signature:{reason}") for reason in signature_reasons]
        )
    expected_fields = {
        "contract_version",
        "issuer",
        "receipt_type",
        "admission_contract_version",
        "status",
        "identity",
        "parent_report_id",
        "child_report_id",
        "role_id",
        "trust_manifest_sha256",
        "trust_manifest_ref",
        "authorization_ticket_ref",
        "task_ref",
        "agent_private_output_ref",
        "semantic_bundle_contract_version",
        "semantic_bundle_ref",
        "adapter_completion_receipt_ref",
        "adapter_completion_receipt_id",
        "runtime_attestation",
        "deterministic_normalization",
        "authority",
        "receipt_id",
        "signature",
    }
    if (
        set(admission) != expected_fields
        or admission.get("receipt_type") != EVO_CHILD_AUTHORING_RECEIPT_TYPE
        or admission.get("admission_contract_version")
        != EVO_CHILD_AUTHORING_ADMISSION_VERSION
        or admission.get("status") != EVO_CHILD_AUTHORING_STATUS
        or admission.get("parent_report_id") != parent_report_id
        or admission.get("child_report_id") != child_report_id
        or admission.get("role_id") != EVO_CHILD_AUTHORING_ROLE_ID
        or admission.get("semantic_bundle_contract_version")
        != EVO_CHILD_AUTHORING_BUNDLE_VERSION
        or admission.get("trust_manifest_sha256") != manifest.get("manifest_sha256")
    ):
        _raise("admission_shape_or_identity")
    material = _authorization_material(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    expected_task = _project_authoring_task(
        root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        material=material,
    )
    _task_path, task, _task_raw = _public_read_ref(
        root,
        admission.get("task_ref"),
        expected_path=paths["task"],
        label="authoring_task",
    )
    if task != expected_task:
        _raise("task_exact_projection")
    _output_path, private_output, private_raw = _public_read_ref(
        root,
        admission.get("agent_private_output_ref"),
        expected_path=paths["agent_output"],
        label="agent_private_output",
        canonical=False,
    )
    _bundle_path, semantic_bundle, _bundle_raw = _public_read_ref(
        root,
        admission.get("semantic_bundle_ref"),
        expected_path=paths["semantic_bundle"],
        label="semantic_bundle",
    )
    _adapter_path, adapter_receipt, _adapter_raw = _public_read_ref(
        root,
        admission.get("adapter_completion_receipt_ref"),
        expected_path=paths["adapter_receipt"],
        label="adapter_completion_receipt",
    )
    if admission.get("adapter_completion_receipt_id") != adapter_receipt.get(
        "receipt_id"
    ):
        _raise("adapter_receipt_id")
    adapter_reasons = _public_adapter_reasons(
        receipt=adapter_receipt,
        admission=admission,
        task=task,
        output_raw=private_raw,
        trust_manifest=manifest,
    )
    if adapter_reasons:
        raise EvoChildAuthoringError(
            [_token(f"adapter_completion:{reason}") for reason in adapter_reasons]
        )
    expected_bundle = _normalize_agent_bundle(
        private_output=private_output,
        task=task,
        material=material,
        root=root,
    )
    if semantic_bundle != expected_bundle or set(semantic_bundle) != set(
        _SEMANTIC_KEYS
    ):
        _raise("semantic_bundle_exact_readback")
    expected_normalization = {
        "allowed": True,
        "object": "base_search_trial_ledger",
        "fields": list(_LEDGER_DERIVED_FIELDS),
        "semantic_generation_allowed": False,
    }
    expected_authority = {
        "scope": "AGENT_SEMANTIC_AUTHORSHIP_ADMISSION_ONLY",
        "agent_semantics_admitted": True,
        "host_semantic_generation_allowed": False,
        "child_preregistration_materialization_allowed": True,
        "child_execution_allowed": False,
        "oos_release_allowed": False,
        "oos_accessed": False,
        "factor_verdict": "NOT_ISSUED",
        "canonical_memory_write_allowed": False,
        "skill_or_policy_mutation_allowed": False,
    }
    if (
        admission.get("identity") != task.get("identity")
        or admission.get("authorization_ticket_ref")
        != task.get("authorization_ticket_ref")
        or admission.get("trust_manifest_ref")
        != _file_ref(root, material["trust_manifest_path"])
        or admission.get("deterministic_normalization") != expected_normalization
        or admission.get("authority") != expected_authority
    ):
        _raise("admission_exact_binding")
    source_reasons = _source_binding_reasons(material)
    if source_reasons:
        raise EvoChildAuthoringError([_token(reason) for reason in source_reasons])
    return {
        "verdict": "PASS",
        "status": EVO_CHILD_AUTHORING_STATUS,
        "admission": admission,
        "admission_path": paths["admission"],
        "semantic_bundle": semantic_bundle,
        "semantic_bundle_path": paths["semantic_bundle"],
        "task": task,
        "task_path": paths["task"],
        "adapter_completion_receipt": adapter_receipt,
        "adapter_completion_receipt_path": paths["adapter_receipt"],
        "agent_private_output": private_output,
        "agent_private_output_path": paths["agent_output"],
        "source_file_sha256s": {
            path: sha256_file(path)
            for path in paths.values()
            if path.is_file()
        },
        "writes_performed": False,
        "authority": expected_authority,
    }


__all__ = [
    "BLOCK_EVO_CHILD_AUTHORING",
    "EVO_CHILD_AUTHORING_ADMISSION_VERSION",
    "EVO_CHILD_AUTHORING_BUNDLE_VERSION",
    "EVO_CHILD_AUTHORING_RECEIPT_TYPE",
    "EVO_CHILD_AUTHORING_ROLE_ID",
    "EVO_CHILD_AUTHORING_STATUS",
    "EVO_CHILD_AUTHORING_TASK_VERSION",
    "LEDGER_DERIVED_HASH_SENTINEL",
    "EvoChildAuthoringError",
    "EvoChildAuthoringRunner",
    "admit_completed_evo_child_authoring",
    "build_evo_child_authoring_prompt",
    "evo_child_authoring_admission_path",
    "evo_child_authoring_paths",
    "prepare_evo_child_authoring_session",
    "run_and_admit_evo_child_authoring",
    "validate_evo_child_authoring_admission",
]
