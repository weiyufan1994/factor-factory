from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping, Protocol

from factor_factory.research_org.contracts import (
    SAFE_ID_RE,
    SHA256_RE,
    ResearchOrganizationError,
    normalize_workspace_relative_path,
    private_reasoning_paths,
    read_workspace_bytes,
    stable_json_hash,
    strict_json_loads,
    validate_content_hash,
    with_content_hash,
)
from factor_factory.research_org.runtime import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
)
from factor_factory.research_org.runtime_trust import load_runtime_trust_store
from factor_factory.researcher_memory import (
    BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
    BLOCK_MEMORY_REVIEW_INVALID,
    REVIEW_DECISIONS,
    _assert_private_root,
    _atomic_store_json,
    _contains_absolute_path,
    _ensure_private_directory,
    _evo_v2_workspace_payload,
    _review_claim_sha256,
    _review_session_receipt_reasons,
    load_candidate_review_material,
    record_candidate_review,
)


REVIEW_REQUEST_CONTRACT_VERSION = (
    "factorforge_researcher_memory_review_request_v1"
)
REVIEW_AGENT_RECORD_CONTRACT_VERSION = (
    "factorforge_researcher_memory_review_agent_record_v1"
)
REVIEWER_ROLE_ID = "researcher_memory_reviewer"
REVIEWER_ID = "factorforge_independent_memory_reviewer"
REVIEW_SESSIONS_ROOT_NAME = "researcher-memory-review-sessions"
MAX_REVIEW_OUTPUT_BYTES = 256 * 1024

EVO_V2_MEMORY_REVIEW_PROJECTION_VERSION = (
    "factorforge_researcher_memory_evo_v2_review_projection_v1"
)
EVO_V2_MEMORY_REVIEW_DECISION_RECEIPT_TYPE = (
    "factorforge_researcher_memory_evo_v2_review_decision_v1"
)
EVO_V2_MEMORY_REVIEW_REQUEST_VERSION = (
    "factorforge_researcher_memory_evo_v2_review_request_v1"
)
EVO_V2_MEMORY_REVIEW_AGENT_RECORD_VERSION = (
    "factorforge_researcher_memory_evo_v2_review_agent_record_v1"
)
EVO_V2_REVIEW_SESSIONS_ROOT_NAME = "researcher-memory-evo-v2-review-sessions"
EVO_V2_MEMORY_REVIEW_CHECKS = (
    "single_core_semantic_authority",
    "all_experience_layers_present_or_verified_cold_start",
    "structural_and_conditional_review_scope_identified",
    "historical_episode_has_no_structural_authority",
    "mechanism_fingerprint_complete",
    "transfer_mapping_has_boundary_prediction_and_distinguishing_test",
    "falsifier_or_counterexample_present",
    "regime_shortcut_forbidden",
    "historical_performance_not_ranked",
    "transfer_use_changed_questions_or_tests_only",
    "no_current_factor_inference",
    "no_skill_policy_threshold_oos_estimand_or_budget_mutation",
    "cold_start_has_runtime_signed_zero_hit_proof",
)

REVIEW_CHECKS = (
    "source_evidence_bound",
    "terminal_outcome_bound",
    "cross_factor_reusable",
    "novel_or_nonduplicative",
    "applicability_bounded",
    "failure_conditions_bounded",
    "no_current_factor_performance_inference",
    "no_private_reasoning",
)


class ResearcherMemoryReviewRunner(Protocol):
    def run_researcher_memory_review_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> Mapping[str, Any]: ...


def _raise(*reasons: str) -> None:
    raise ResearchOrganizationError(BLOCK_MEMORY_REVIEW_INVALID, reasons)


def _private_write_bytes(root: Path, relative: str, payload: bytes) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or any(not part for part in path.parts):
        _raise(f"unsafe_review_context_path:{relative}")
    parent = root
    for part in path.parent.parts:
        parent = _ensure_private_directory(root, parent.relative_to(root).joinpath(part).as_posix())
    destination = root / path
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(destination, flags, 0o600)
    except OSError as exc:
        _raise(f"review_context_write:{relative}:{exc}")
    try:
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                _raise(f"review_context_short_write:{relative}")
            written += count
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return destination


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _task_relative(material: Mapping[str, Any]) -> str:
    candidate = material["candidate"]
    return (
        f"objects/research_organization/{candidate['identity']['report_id']}"
        f"/tasks/{candidate['source_task_ref']['task_id']}.json"
    )


def prepare_independent_review_session(
    *,
    workspace: Path,
    worktree: Path,
    memory_root: Path,
    installation_id: str,
    candidate_relative: str,
    outcome_event_id: str,
    timeout_seconds: int,
) -> tuple[ResearchOrgSessionInvocation, dict[str, Any], Path]:
    worktree = Path(worktree).expanduser().resolve(strict=True)
    workspace = Path(workspace).expanduser().resolve(strict=True)
    try:
        workspace.relative_to(worktree)
    except ValueError as exc:
        _raise("review_workspace_outside_worktree")
        raise AssertionError from exc
    material = load_candidate_review_material(
        workspace=workspace,
        candidate_relative=candidate_relative,
        root=memory_root,
        installation_id=installation_id,
        outcome_event_id=outcome_event_id,
        repo_root=worktree,
    )
    review_root = _assert_private_root(
        material["memory_root"].parent / REVIEW_SESSIONS_ROOT_NAME,
        repo_root=worktree,
        workspace=workspace,
        create=True,
    )
    token = uuid.uuid4().hex
    reviewer_session_id = f"session_{token}"
    runtime_instance_id = f"fforg-memory-review-{token[:16]}"
    session_root = _ensure_private_directory(review_root, reviewer_session_id)
    context_root = _ensure_private_directory(session_root, "context")
    _ensure_private_directory(session_root, "output")

    candidate = material["candidate"]
    staged_relatives = [
        material["candidate_ref"]["path"],
        _task_relative(material),
        candidate["source_result_ref"]["path"],
        candidate["source_memory_snapshot_ref"]["path"],
        *[reference["path"] for reference in candidate["evidence_refs"]],
    ]
    staged_files: list[dict[str, Any]] = []
    seen: set[str] = set()
    evidence_hashes = {
        str(reference["path"]): str(reference["sha256"])
        for reference in candidate["evidence_refs"]
    }
    for raw_relative in staged_relatives:
        relative = normalize_workspace_relative_path(
            raw_relative,
            workspace=workspace,
            label="researcher_memory_review_context",
        )
        if relative in seen:
            continue
        seen.add(relative)
        payload = read_workspace_bytes(workspace, relative)
        observed_sha = hashlib.sha256(payload).hexdigest()
        expected_evidence_sha = evidence_hashes.get(relative)
        if expected_evidence_sha is not None and observed_sha != expected_evidence_sha:
            _raise(f"review_evidence_changed:{relative}")
        _private_write_bytes(context_root, relative, payload)
        staged_files.append(
            {
                "path": relative,
                "sha256": observed_sha,
                "size_bytes": len(payload),
            }
        )

    outcome_relative = (
        f"objects/research_organization/{candidate['identity']['report_id']}"
        "/memory_review_context/outcome_event.json"
    )
    outcome_payload = _json_bytes(material["outcome_event"])
    _private_write_bytes(context_root, outcome_relative, outcome_payload)
    staged_files.append(
        {
            "path": outcome_relative,
            "sha256": hashlib.sha256(outcome_payload).hexdigest(),
            "size_bytes": len(outcome_payload),
        }
    )
    current_memory_relative = (
        f"objects/research_organization/{candidate['identity']['report_id']}"
        "/memory_review_context/current_role_memory_snapshot.json"
    )
    current_memory_payload = _json_bytes(material["current_memory_snapshot"])
    _private_write_bytes(
        context_root,
        current_memory_relative,
        current_memory_payload,
    )
    current_memory_ref = {
        "path": current_memory_relative,
        "sha256": str(
            material["current_memory_snapshot"]["snapshot_sha256"]
        ),
        "hash_kind": "json_content",
    }
    staged_files.append(
        {
            "path": current_memory_relative,
            "sha256": hashlib.sha256(current_memory_payload).hexdigest(),
            "size_bytes": len(current_memory_payload),
        }
    )

    request = with_content_hash(
        {
            "contract_version": REVIEW_REQUEST_CONTRACT_VERSION,
            "identity": dict(candidate["identity"]),
            "reviewer_role_id": REVIEWER_ROLE_ID,
            "candidate_ref": dict(material["candidate_ref"]),
            "outcome_event_ref": dict(material["outcome_event_ref"]),
            "source_session_id": str(candidate["source_session_id"]),
            "review_parent": dict(material["review_parent"]),
            "current_memory_snapshot_ref": current_memory_ref,
            "decision_options": sorted(REVIEW_DECISIONS),
            "review_checks": list(REVIEW_CHECKS),
            "staged_files": staged_files,
            "policy": {
                "current_factor_proof_authority": False,
                "canonical_write_authority": False,
                "private_reasoning_allowed": False,
                "reviewer_selects_decision": True,
            },
        },
        hash_field="request_sha256",
    )
    request_relative = "identity/researcher_memory_review_request.json"
    _private_write_bytes(context_root, request_relative, _json_bytes(request))
    request["request_path"] = request_relative

    attempt_id = f"attempt_memory_review_{token[:24]}"
    invocation = ResearchOrgSessionInvocation(
        identity=dict(candidate["identity"]),
        role_id=REVIEWER_ROLE_ID,
        task_id=f"memory_review_{token[:24]}",
        task_sha256=str(request["request_sha256"]),
        attempt_id=attempt_id,
        attempt_number=1,
        session_id=reviewer_session_id,
        runtime_instance_id=runtime_instance_id,
        worktree=worktree,
        workspace=workspace,
        private_attempt_root=session_root,
        context_root=context_root,
        private_output_path=session_root / "output" / "agent_result.json",
        cancel_request_path=session_root / "cancel_request.json",
        context_manifest_sha256=str(request["request_sha256"]),
        required_skills=("factor-forge-researcher-memory",),
        timeout_seconds=timeout_seconds,
        runtime_id=f"runtime_memory_review_{token[:24]}",
        plan_sha256=stable_json_hash(
            {
                "candidate_ref": material["candidate_ref"],
                "outcome_event_ref": material["outcome_event_ref"],
            }
        ),
        scheduler_epoch=1,
        dispatch_event_seq=1,
        idempotency_key=stable_json_hash(
            {
                "reviewer_session_id": reviewer_session_id,
                "candidate_ref": material["candidate_ref"],
                "outcome_event_ref": material["outcome_event_ref"],
            }
        ),
        adapter_challenge=uuid.uuid4().hex,
        dependency_admissions=(),
        parent_session_uid=None,
    )
    return invocation, material, review_root


def build_researcher_memory_review_prompt(
    invocation: ResearchOrgSessionInvocation,
) -> str:
    request_path = invocation.workspace / "identity/researcher_memory_review_request.json"
    output_template = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": {
            "contract_version": REVIEW_AGENT_RECORD_CONTRACT_VERSION,
            "identity": dict(invocation.identity),
            "reviewer_role_id": REVIEWER_ROLE_ID,
            "candidate_ref": {"path": "<COPY_FROM_REQUEST>", "sha256": "<COPY_FROM_REQUEST>"},
            "outcome_event_ref": {"event_id": "<COPY_FROM_REQUEST>", "sha256": "<COPY_FROM_REQUEST>"},
            "review_parent": {
                "store_id": "<COPY_FROM_REQUEST>",
                "generation": 0,
                "manifest_sha256": "<COPY_FROM_REQUEST>",
            },
            "current_memory_snapshot_ref": {
                "path": "<COPY_FROM_REQUEST>",
                "sha256": "<COPY_FROM_REQUEST>",
                "hash_kind": "json_content",
            },
            "decision": "APPROVE_CANONICAL|REJECT",
            "rationale": "<CONCISE_PUBLIC_RATIONALE>",
            "checks": {check: False for check in REVIEW_CHECKS},
        },
    }
    return f"""# Factor Forge independent researcher-memory review

You are a disposable independent reviewer session. You did not author the
candidate and you have no authority to change the factor verdict, edit the
workspace, or promote canonical memory.

Read the frozen request at `{request_path}` and every file listed in its
`staged_files`. For novelty, use the request's current-generation role-memory
snapshot, not the source task's older planning snapshot. Decide whether the
proposed lesson is evidence-bound, reusable beyond the source factor,
non-duplicative, and explicit about applicability and failure conditions.
Historical performance is not current-factor proof.

Return `APPROVE_CANONICAL` only when every required check is true. Otherwise
return `REJECT` and mark at least one check false. Write a concise public
rationale; do not include private chain-of-thought, credentials, raw logs, or
absolute Host paths.

Write exactly one JSON object to `{invocation.private_output_path}` using this
shape and no additional keys:

```json
{json.dumps(output_template, ensure_ascii=False, indent=2, sort_keys=True)}
```
"""


def _read_private_review_output(path: Path) -> tuple[dict[str, Any], bytes]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _raise(f"review_private_output_unreadable:{exc}")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_REVIEW_OUTPUT_BYTES
        ):
            _raise("review_private_output_unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            _raise("review_private_output_changed")
    finally:
        os.close(descriptor)
    parsed = strict_json_loads(payload, label="researcher_memory_review_output")
    if not isinstance(parsed, dict):
        _raise("review_private_output_object")
    return parsed, payload


def validate_reviewer_private_output(
    payload: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> tuple[str, str]:
    if set(payload) != {"contract_version", "status", "public_research_record"}:
        _raise("review_private_output_fields")
    if (
        payload.get("contract_version") != PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
        or payload.get("status") != "PASS"
        or private_reasoning_paths(payload)
        or _contains_absolute_path(payload)
    ):
        _raise("review_private_output_contract")
    record = payload.get("public_research_record")
    expected_record_fields = {
        "contract_version",
        "identity",
        "reviewer_role_id",
        "candidate_ref",
        "outcome_event_ref",
        "review_parent",
        "current_memory_snapshot_ref",
        "decision",
        "rationale",
        "checks",
    }
    if not isinstance(record, Mapping) or set(record) != expected_record_fields:
        _raise("review_agent_record_fields")
    if (
        record.get("contract_version") != REVIEW_AGENT_RECORD_CONTRACT_VERSION
        or record.get("identity") != request.get("identity")
        or record.get("reviewer_role_id") != REVIEWER_ROLE_ID
        or record.get("candidate_ref") != request.get("candidate_ref")
        or record.get("outcome_event_ref") != request.get("outcome_event_ref")
        or record.get("review_parent") != request.get("review_parent")
        or record.get("current_memory_snapshot_ref")
        != request.get("current_memory_snapshot_ref")
    ):
        _raise("review_agent_record_binding")
    decision = record.get("decision")
    rationale = record.get("rationale")
    checks = record.get("checks")
    if decision not in REVIEW_DECISIONS:
        _raise("review_agent_decision")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        _raise("review_agent_rationale")
    if (
        not isinstance(checks, Mapping)
        or set(checks) != set(REVIEW_CHECKS)
        or any(type(checks.get(check)) is not bool for check in REVIEW_CHECKS)
    ):
        _raise("review_agent_checks")
    if decision == "APPROVE_CANONICAL" and not all(checks.values()):
        _raise("review_agent_approval_checks")
    if decision == "REJECT" and all(checks.values()):
        _raise("review_agent_rejection_checks")
    return str(decision), rationale.strip()


def sign_completed_reviewer_session(
    *,
    invocation: ResearchOrgSessionInvocation,
    outcome: ResearchOrgSessionOutcome,
    state_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    trust_store = load_runtime_trust_store(
        Path(state_root) / "research-org-trust",
        installation_id=installation_id,
    )
    adapter_receipt = outcome.adapter_receipt
    if (
        outcome.returncode != 0
        or outcome.cancelled
        or not outcome.owned_termination_supported
        or outcome.session_id != invocation.session_id
        or outcome.runtime_instance_id != invocation.runtime_instance_id
        or not isinstance(adapter_receipt, Mapping)
    ):
        _raise("review_runtime_outcome")
    signature_reasons = trust_store.verify(
        adapter_receipt,
        expected_issuer="runtime_adapter",
    )
    expected_adapter_identity = {
        **dict(invocation.identity),
        "runtime_id": invocation.runtime_id,
        "task_id": invocation.task_id,
        "role_id": invocation.role_id,
        "attempt_id": invocation.attempt_id,
        "attempt_no": invocation.attempt_number,
    }
    adapter_session = adapter_receipt.get("session") or {}
    adapter_outcome = adapter_receipt.get("outcome") or {}
    parsed, output_bytes = _read_private_review_output(invocation.private_output_path)
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    if (
        signature_reasons
        or adapter_receipt.get("receipt_type") != "COMPLETED"
        or adapter_receipt.get("identity") != expected_adapter_identity
        or (adapter_receipt.get("bindings") or {}).get("task_sha256")
        != invocation.task_sha256
        or adapter_session.get("session_uid") != invocation.session_id
        or adapter_session.get("runtime_handle_sha256")
        != hashlib.sha256(invocation.runtime_instance_id.encode("utf-8")).hexdigest()
        or adapter_session.get("adapter_id") != installation_id
        or adapter_session.get("parent_session_uid") is not None
        or adapter_outcome.get("returncode") != 0
        or adapter_outcome.get("cancelled") is not False
        or adapter_outcome.get("termination_confirmed") is not True
        or adapter_outcome.get("private_output_sha256") != output_sha256
        or adapter_outcome.get("private_output_size_bytes") != len(output_bytes)
    ):
        _raise("review_adapter_completion_receipt")
    request_path = invocation.context_root / "identity/researcher_memory_review_request.json"
    request = strict_json_loads(
        request_path.read_bytes(),
        label="researcher_memory_review_request",
    )
    if (
        not isinstance(request, Mapping)
        or request.get("contract_version") != REVIEW_REQUEST_CONTRACT_VERSION
        or validate_content_hash(
            request,
            hash_field="request_sha256",
            label="researcher_memory_review_request",
        )
        or request.get("request_sha256") != invocation.task_sha256
    ):
        _raise("review_request_contract")
    decision, rationale = validate_reviewer_private_output(parsed, request=request)
    reviewer = {
        "reviewer_id": REVIEWER_ID,
        "reviewer_session_id": invocation.session_id,
        "runtime_instance_id": invocation.runtime_instance_id,
        "independence_class": "runtime_attested_independent_review",
    }
    public_reviewer = {
        "reviewer_id": REVIEWER_ID,
        "reviewer_session_id": invocation.session_id,
        "independence_class": "host_attested_independent_review",
    }
    claim_sha256 = _review_claim_sha256(
        identity=request["identity"],
        candidate_ref=request["candidate_ref"],
        outcome_event_ref=request["outcome_event_ref"],
        reviewer=public_reviewer,
        source_session_id=str(request["source_session_id"]),
        decision=decision,
        rationale=rationale,
        canonical_write_authorized=decision == "APPROVE_CANONICAL",
        review_parent=request["review_parent"],
        expected_parent_generation=int(
            request["review_parent"]["generation"]
        )
        + 1,
    )
    receipt = trust_store.sign(
        "runtime_adapter",
        {
            "receipt_type": "RESEARCHER_MEMORY_REVIEW_COMPLETED",
            "identity": dict(request["identity"]),
            "reviewer": reviewer,
            "bindings": {
                "candidate_ref": dict(request["candidate_ref"]),
                "outcome_event_ref": dict(request["outcome_event_ref"]),
                "source_session_id": str(request["source_session_id"]),
                "review_claim_sha256": claim_sha256,
                "review_parent": dict(request["review_parent"]),
                "expected_parent_generation": int(
                    request["review_parent"]["generation"]
                )
                + 1,
            },
            "runtime_evidence": {
                "adapter_completion_receipt": dict(adapter_receipt),
                "review_request": dict(request),
                "review_output": dict(parsed),
                "review_output_sha256": output_sha256,
                "model_execution": {
                    "provider": outcome.provider,
                    "model": outcome.model,
                    "transport": outcome.transport,
                    "isolation_class": outcome.isolation_class,
                    "owned_termination_supported": (
                        outcome.owned_termination_supported
                    ),
                },
            },
            "outcome": {
                "returncode": 0,
                "termination_confirmed": True,
                "secret_scan": "PASS",
            },
        },
    )
    return {
        "decision": decision,
        "rationale": rationale,
        "provider": outcome.provider,
        "model": outcome.model,
        "adapter_completion_receipt_id": adapter_receipt["receipt_id"],
        "reviewer_session_receipt": receipt,
    }


def run_and_record_independent_review(
    *,
    workspace: Path,
    worktree: Path,
    memory_root: Path,
    installation_id: str,
    candidate_relative: str,
    outcome_event_id: str,
    runner: ResearcherMemoryReviewRunner,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    invocation, material, review_root = prepare_independent_review_session(
        workspace=workspace,
        worktree=worktree,
        memory_root=memory_root,
        installation_id=installation_id,
        candidate_relative=candidate_relative,
        outcome_event_id=outcome_event_id,
        timeout_seconds=timeout_seconds,
    )
    execution = runner.run_researcher_memory_review_session(invocation)
    if not isinstance(execution, Mapping):
        _raise("review_runner_result")
    decision = execution.get("decision")
    rationale = execution.get("rationale")
    receipt = execution.get("reviewer_session_receipt")
    trust_store = load_runtime_trust_store(
        material["trust_root"],
        installation_id=installation_id,
    )
    receipt_reasons = _review_session_receipt_reasons(
        receipt,
        identity=material["candidate"]["identity"],
        candidate_ref=material["candidate_ref"],
        outcome_event_ref=material["outcome_event_ref"],
        source_session_id=str(material["candidate"]["source_session_id"]),
        decision=str(decision or ""),
        rationale=str(rationale or ""),
        review_parent=material["review_parent"],
        expected_parent_generation=int(
            material["review_parent"]["generation"]
        )
        + 1,
        trust_store=trust_store,
    )
    if receipt_reasons:
        _raise(*receipt_reasons)
    receipt_relative_in_review_root = (
        f"{invocation.session_id}/reviewer_session_receipt.json"
    )
    receipt_path, _written = _atomic_store_json(
        review_root,
        receipt_relative_in_review_root,
        receipt,
        replace=False,
    )
    receipt_ref = {
        "id": (
            f"{REVIEW_SESSIONS_ROOT_NAME}/"
            f"{receipt_relative_in_review_root}"
        ),
        "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }
    review = record_candidate_review(
        workspace=workspace,
        candidate_relative=candidate_relative,
        root=memory_root,
        installation_id=installation_id,
        decision=str(decision),
        reviewer_session_receipt_ref=receipt_ref,
        outcome_event_id=outcome_event_id,
        rationale=str(rationale),
        repo_root=worktree,
    )
    return {
        "review": review,
        "decision": decision,
        "rationale": rationale,
        "reviewer_session_id": invocation.session_id,
        "runtime_instance_id": invocation.runtime_instance_id,
        "provider": execution.get("provider"),
        "model": execution.get("model"),
        "adapter_completion_receipt_id": execution.get(
            "adapter_completion_receipt_id"
        ),
        "reviewer_session_receipt_ref": receipt_ref,
    }


def build_evo_v2_memory_review_projection(
    *,
    experience_transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
    experience_transfer_bundle_ref: Mapping[str, Any],
    transfer_use_receipt_ref: Mapping[str, Any],
    trust_store: Any,
    source_workspace: Path | None = None,
    cold_start_search_receipt_ref: Mapping[str, Any] | None = None,
    cold_start_search_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic reviewer input directly from core EVO contracts.

    The projection is deliberately pre-decision.  An adapter-signed decision
    produced from it is required before the Host may admit or retrieve memory.
    """

    from factor_factory.evo_v2 import (
        EXPERIENCE_TRANSFER_BUNDLE_VERSION,
        TRANSFER_USE_RECEIPT_VERSION,
        validate_experience_transfer_bundle,
        validate_transfer_use_receipt,
    )
    from factor_factory.knowledge_context import (
        validate_evo_v2_cold_start_search_receipt,
    )

    bundle = experience_transfer_bundle
    receipt = transfer_use_receipt
    reasons: list[str] = []
    if not isinstance(bundle, Mapping):
        reasons.append("experience_transfer_bundle_object")
        bundle = {}
    if not isinstance(receipt, Mapping):
        reasons.append("transfer_use_receipt_object")
        receipt = {}
    if bundle.get("contract_version") != EXPERIENCE_TRANSFER_BUNDLE_VERSION:
        reasons.append("experience_transfer_bundle_contract")
    if receipt.get("contract_version") != TRANSFER_USE_RECEIPT_VERSION:
        reasons.append("transfer_use_receipt_contract")
    reasons.extend(
        f"core_experience_transfer_bundle:{reason}"
        for reason in validate_experience_transfer_bundle(
            bundle,
            workspace_root=source_workspace,
            verify_refs=source_workspace is not None,
        )
    )
    reasons.extend(
        f"core_transfer_use_receipt:{reason}"
        for reason in validate_transfer_use_receipt(
            receipt,
            transfer_bundle=bundle,
            workspace_root=source_workspace,
            verify_refs=source_workspace is not None,
        )
    )
    if source_workspace is not None:
        try:
            observed_bundle = _evo_v2_workspace_payload(
                workspace=source_workspace,
                reference=experience_transfer_bundle_ref,
                label="experience_transfer_bundle",
            )
            observed_receipt = _evo_v2_workspace_payload(
                workspace=source_workspace,
                reference=transfer_use_receipt_ref,
                label="transfer_use_receipt",
            )
        except ResearchOrganizationError as exc:
            reasons.extend(exc.reasons)
        else:
            if observed_bundle != bundle:
                reasons.append("experience_transfer_bundle_payload_binding")
            if observed_receipt != receipt:
                reasons.append("transfer_use_receipt_payload_binding")
    if reasons:
        raise ResearchOrganizationError(
            BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
            list(dict.fromkeys(reasons)),
        )
    retrieval = bundle["retrieval_policy"]
    cold_start = retrieval["memory_state"] == "COLD_START_NO_ADMISSIBLE_MEMORY"
    experiences = bundle["experiences"]
    mappings = bundle["transfer_mappings"]
    layers = {experience["layer"] for experience in experiences}
    structural_and_conditional = [
        experience
        for experience in experiences
        if experience["layer"] in {"structural_lesson", "conditional_realization"}
    ]
    episodes = [
        experience
        for experience in experiences
        if experience["layer"] == "historical_episode"
    ]
    structural_falsifiers = [
        experience["lesson"].get("falsifier")
        for experience in experiences
        if experience["layer"] == "structural_lesson"
    ]
    conditional_falsifiers = [
        experience["lesson"].get("condition_falsifier")
        for experience in experiences
        if experience["layer"] == "conditional_realization"
    ]
    uses = receipt["uses"]
    protected_use_fields = (
        "current_factor_evidence",
        "threshold_change",
        "estimand_change",
        "trial_budget_change",
        "oos_access",
        "skill_or_validator_change",
    )
    cold_start_proof_reasons: list[str] = []
    if cold_start:
        cold_start_proof_reasons.extend(
            validate_evo_v2_cold_start_search_receipt(
                cold_start_search_receipt,
                artifact_identity=bundle["artifact_identity"],
                mechanism_fingerprint=bundle["mechanism_fingerprint"],
                trust_store=trust_store,
            )
        )
        retrieval_refs = retrieval["retrieval_evidence_refs"]
        if (
            not isinstance(cold_start_search_receipt_ref, Mapping)
            or dict(cold_start_search_receipt_ref)
            not in [dict(item) for item in retrieval_refs]
        ):
            cold_start_proof_reasons.append("cold_start_search_ref_binding")
        if source_workspace is not None:
            try:
                observed_proof = _evo_v2_workspace_payload(
                    workspace=source_workspace,
                    reference=(
                        cold_start_search_receipt_ref
                        if isinstance(cold_start_search_receipt_ref, Mapping)
                        else {}
                    ),
                    label="cold_start_search_receipt",
                )
            except ResearchOrganizationError as exc:
                cold_start_proof_reasons.extend(exc.reasons)
            else:
                if observed_proof != cold_start_search_receipt:
                    cold_start_proof_reasons.append(
                        "cold_start_search_payload_binding"
                    )
    elif (
        cold_start_search_receipt_ref is not None
        or cold_start_search_receipt is not None
    ):
        cold_start_proof_reasons.append("cold_start_proof_for_non_cold_start")
    checks = {
        "single_core_semantic_authority": (
            bundle["contract_version"] == EXPERIENCE_TRANSFER_BUNDLE_VERSION
            and receipt["contract_version"] == TRANSFER_USE_RECEIPT_VERSION
        ),
        "all_experience_layers_present_or_verified_cold_start": (
            (cold_start and not experiences)
            or layers
            == {
                "structural_lesson",
                "conditional_realization",
                "historical_episode",
            }
        ),
        "structural_and_conditional_review_scope_identified": (
            cold_start
            or (
                bool(structural_and_conditional)
                and all(
                    item["review_authority"]["required"] is True
                    and item["review_authority"]["independent_session"] is True
                    for item in structural_and_conditional
                )
            )
        ),
        "historical_episode_has_no_structural_authority": (
            cold_start
            or (
                bool(episodes)
                and all(
                    item["review_authority"]
                    == {
                        "required": False,
                        "status": "HOST_SIGNED_EPISODE_NO_STRUCTURAL_AUTHORITY",
                        "independent_session": False,
                        "reviewer_receipt_ref": None,
                    }
                    for item in episodes
                )
            )
        ),
        "mechanism_fingerprint_complete": (
            set(bundle["mechanism_fingerprint"])
            == {
                "economic_claim",
                "estimand_id",
                "payer_or_constraint",
                "mathematical_object",
                "broken_invariant_or_boundary",
                "observation_mapping",
                "failure_signature",
            }
            and all(bundle["mechanism_fingerprint"].values())
        ),
        "transfer_mapping_has_boundary_prediction_and_distinguishing_test": (
            cold_start
            or (
                bool(mappings)
                and all(
                    mapping["boundary_review"]
                    and mapping["transferred_prediction"]
                    and mapping["distinguishing_test"]
                    for mapping in mappings
                )
            )
        ),
        "falsifier_or_counterexample_present": (
            cold_start
            or all(
                isinstance(item, str) and bool(item.strip())
                for item in [*structural_falsifiers, *conditional_falsifiers]
            )
        ),
        "regime_shortcut_forbidden": (
            retrieval["regime_shortcut_allowed"] is False
            and all(mapping["regime_match_required"] is False for mapping in mappings)
        ),
        "historical_performance_not_ranked": (
            retrieval["historical_score_used_for_ranking"] is False
            and all(
                mapping["performance_score_used_for_ranking"] is False
                for mapping in mappings
            )
        ),
        "transfer_use_changed_questions_or_tests_only": (
            cold_start
            or (
                bool(uses)
                and all(
                    use["research_effect"]
                    in {
                        "test_order_changed",
                        "question_broadened",
                        "counterexample_added",
                        "historical_context_recorded",
                        "mapping_rejected",
                    }
                    for use in uses
                )
            )
        ),
        "no_current_factor_inference": (
            retrieval["current_factor_proof_authority"] is False
            and receipt["outcome_recording"]
            == {
                "status": "CURRENT_FACTOR_OUTCOME_NOT_INFERRED",
                "factor_verdict": "NOT_ISSUED",
                "promotion_authority": False,
                "canonical_memory_write": False,
            }
        ),
        "no_skill_policy_threshold_oos_estimand_or_budget_mutation": (
            all(
                use[field] is False
                for use in uses
                for field in protected_use_fields
            )
            and all(
                value is False
                for value in bundle["authority_guard"][
                    "mutation_permissions"
                ].values()
            )
            and all(
                value is False
                for value in receipt["authority_guard"][
                    "mutation_permissions"
                ].values()
            )
        ),
        "cold_start_has_runtime_signed_zero_hit_proof": (
            not cold_start_proof_reasons
        ),
    }
    projection = with_content_hash(
        {
            "contract_version": EVO_V2_MEMORY_REVIEW_PROJECTION_VERSION,
            "authority": "independent_reviewer_input_only",
            "semantic_authority": "factor_factory.evo_v2",
            "source_contracts": {
                "experience_transfer_bundle_ref": dict(
                    experience_transfer_bundle_ref
                ),
                "experience_transfer_bundle_content_sha256": bundle[
                    "content_sha256"
                ],
                "transfer_use_receipt_ref": dict(transfer_use_receipt_ref),
                "transfer_use_receipt_content_sha256": receipt["content_sha256"],
            },
            "artifact_identity": dict(bundle["artifact_identity"]),
            "memory_state": retrieval["memory_state"],
            "review_scope_experience_ids": [
                item["experience_id"] for item in structural_and_conditional
            ],
            "cold_start_search_receipt_ref": (
                dict(cold_start_search_receipt_ref)
                if isinstance(cold_start_search_receipt_ref, Mapping)
                else None
            ),
            "cold_start_search_receipt_id": (
                cold_start_search_receipt.get("receipt_id")
                if isinstance(cold_start_search_receipt, Mapping)
                else None
            ),
            "review_checks": checks,
            "eligible_for_independent_reviewer_consideration": all(checks.values()),
            "decision_issued": False,
            "canonical_write_authority": False,
            "current_factor_proof_authority": False,
        },
        hash_field="projection_sha256",
    )
    return projection


def validate_evo_v2_memory_review_decision(
    decision_receipt: Any,
    *,
    projection: Mapping[str, Any],
    trust_store: Any,
) -> list[str]:
    """Validate a reviewer result bound to a real adapter completion receipt."""

    reasons: list[str] = []
    if not isinstance(decision_receipt, Mapping):
        return ["evo_v2_review_decision_object"]
    if (
        not isinstance(projection, Mapping)
        or projection.get("contract_version")
        != EVO_V2_MEMORY_REVIEW_PROJECTION_VERSION
        or validate_content_hash(
            projection,
            hash_field="projection_sha256",
            label="evo_v2_memory_review_projection",
        )
        or projection.get("eligible_for_independent_reviewer_consideration")
        is not True
    ):
        reasons.append("evo_v2_review_projection")
    expected_fields = {
        "contract_version",
        "authority",
        "identity",
        "reviewer",
        "bindings",
        "decision",
        "rationale",
        "checks",
        "experience_decisions",
        "runtime_evidence",
        "authority_guard",
        "decision_sha256",
    }
    if set(decision_receipt) != expected_fields:
        reasons.append("evo_v2_review_decision_fields")
    if (
        decision_receipt.get("contract_version")
        != EVO_V2_MEMORY_REVIEW_DECISION_RECEIPT_TYPE
        or decision_receipt.get("authority")
        != "runtime_attested_review_host_countersign_required"
        or decision_receipt.get("identity") != projection.get("artifact_identity")
    ):
        reasons.append("evo_v2_review_decision_identity")
    runtime_evidence = decision_receipt.get("runtime_evidence")
    if not isinstance(runtime_evidence, Mapping) or set(runtime_evidence) != {
        "adapter_completion_receipt",
        "review_request",
        "review_output",
        "review_output_sha256",
        "model_execution",
    }:
        reasons.append("evo_v2_review_runtime_evidence_fields")
        runtime_evidence = {}
    request = runtime_evidence.get("review_request")
    output = runtime_evidence.get("review_output")
    adapter_receipt = runtime_evidence.get("adapter_completion_receipt")
    request_reasons, source_sessions, source_runtime_handles = (
        _evo_v2_review_request_reasons(
            request,
            projection=projection,
            trust_store=trust_store,
        )
    )
    reasons.extend(request_reasons)
    output_decision: str | None = None
    output_rationale: str | None = None
    output_checks: Mapping[str, Any] = {}
    output_experience_decisions: list[dict[str, Any]] = []
    try:
        (
            output_decision,
            output_rationale,
            output_checks,
            output_experience_decisions,
        ) = validate_evo_v2_memory_reviewer_private_output(
            output if isinstance(output, Mapping) else {},
            request=request if isinstance(request, Mapping) else {},
        )
    except ResearchOrganizationError:
        reasons.append("evo_v2_review_output_contract")
    output_bytes = _json_bytes(output) if isinstance(output, Mapping) else b""
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    if (
        runtime_evidence.get("review_output_sha256") != output_sha256
        or decision_receipt.get("decision") != output_decision
        or decision_receipt.get("rationale") != output_rationale
        or decision_receipt.get("checks") != output_checks
        or decision_receipt.get("experience_decisions")
        != output_experience_decisions
    ):
        reasons.append("evo_v2_review_output_binding")
    reviewer = decision_receipt.get("reviewer")
    reviewer_session_id = str((reviewer or {}).get("reviewer_session_id") or "")
    reviewer_runtime_instance_id = str(
        (reviewer or {}).get("runtime_instance_id") or ""
    )
    if (
        not isinstance(reviewer, Mapping)
        or set(reviewer)
        != {
            "reviewer_id",
            "reviewer_role_id",
            "reviewer_session_id",
            "runtime_instance_id",
            "independence_class",
        }
        or reviewer.get("reviewer_id") != REVIEWER_ID
        or reviewer.get("reviewer_role_id") != REVIEWER_ROLE_ID
        or reviewer.get("independence_class")
        != "runtime_attested_independent_review"
        or not SAFE_ID_RE.fullmatch(reviewer_session_id)
        or not SAFE_ID_RE.fullmatch(reviewer_runtime_instance_id)
        or reviewer_session_id in source_sessions
        or hashlib.sha256(reviewer_runtime_instance_id.encode("utf-8")).hexdigest()
        in source_runtime_handles
    ):
        reasons.append("evo_v2_review_decision_reviewer_independence")
    expected_task_sha = (
        request.get("request_sha256") if isinstance(request, Mapping) else None
    )
    reasons.extend(
        _evo_v2_adapter_completion_reasons(
            adapter_receipt,
            artifact_identity=projection.get("artifact_identity") or {},
            trust_store=trust_store,
            expected_role_id=REVIEWER_ROLE_ID,
            expected_task_sha256=expected_task_sha,
            expected_session_id=reviewer_session_id,
            expected_runtime_instance_id=reviewer_runtime_instance_id,
            expected_output_sha256=output_sha256,
            expected_output_size_bytes=len(output_bytes),
        )
    )
    adapter_receipt_id = (
        adapter_receipt.get("receipt_id")
        if isinstance(adapter_receipt, Mapping)
        else None
    )
    expected_bindings = {
        "projection_sha256": projection.get("projection_sha256"),
        "source_contracts": projection.get("source_contracts"),
        "review_scope_experience_ids": projection.get(
            "review_scope_experience_ids"
        ),
        "cold_start_search_receipt_id": projection.get(
            "cold_start_search_receipt_id"
        ),
        "review_request_sha256": expected_task_sha,
        "adapter_completion_receipt_id": adapter_receipt_id,
        "review_output_sha256": output_sha256,
        "source_session_ids": source_sessions,
        "source_runtime_handle_sha256s": source_runtime_handles,
    }
    if decision_receipt.get("bindings") != expected_bindings:
        reasons.append("evo_v2_review_decision_binding")
    cold_start = projection.get("memory_state") == "COLD_START_NO_ADMISSIBLE_MEMORY"
    expected_decision = (
        "NOT_REQUIRED_VERIFIED_COLD_START"
        if cold_start
        else "APPROVE_ADVISORY_USE"
    )
    expected_experience_decisions = [
        {
            "experience_id": experience_id,
            "decision": "APPROVE_CANONICAL_SOURCE_FOR_ADVISORY_TRANSFER",
        }
        for experience_id in projection.get("review_scope_experience_ids") or []
    ]
    if (
        output_decision != expected_decision
        or output_checks != projection.get("review_checks")
        or not all(bool(value) for value in output_checks.values())
        or output_experience_decisions != expected_experience_decisions
    ):
        reasons.append("evo_v2_review_decision_outcome")
    model_execution = runtime_evidence.get("model_execution")
    if (
        not isinstance(model_execution, Mapping)
        or set(model_execution)
        != {
            "provider",
            "model",
            "transport",
            "isolation_class",
            "owned_termination_supported",
        }
        or any(
            not isinstance(model_execution.get(field), str)
            or not model_execution.get(field)
            for field in ("provider", "model", "transport", "isolation_class")
        )
        or model_execution.get("owned_termination_supported") is not True
    ):
        reasons.append("evo_v2_review_model_execution")
    if decision_receipt.get("authority_guard") != {
        "host_countersign_required": True,
        "canonical_memory_write_authority": False,
        "current_factor_proof_authority": False,
        "skill_or_policy_mutation_authority": False,
    }:
        reasons.append("evo_v2_review_decision_authority")
    reasons.extend(
        validate_content_hash(
            decision_receipt,
            hash_field="decision_sha256",
            label="evo_v2_memory_review_decision",
        )
    )
    if _contains_absolute_path(decision_receipt):
        reasons.append("evo_v2_review_decision_absolute_path")
    return list(dict.fromkeys(reasons))


def _evo_v2_adapter_completion_reasons(
    receipt: Any,
    *,
    artifact_identity: Mapping[str, Any],
    trust_store: Any,
    expected_role_id: str | None = None,
    forbidden_role_id: str | None = None,
    expected_task_sha256: str | None = None,
    expected_session_id: str | None = None,
    expected_runtime_instance_id: str | None = None,
    expected_output_sha256: str | None = None,
    expected_output_size_bytes: int | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["evo_v2_adapter_completion_object"]
    if set(receipt) != {
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
    }:
        reasons.append("evo_v2_adapter_completion_fields")
    if trust_store is None or not hasattr(trust_store, "verify"):
        reasons.append("evo_v2_adapter_completion_trust_store")
    else:
        reasons.extend(
            f"evo_v2_adapter_completion_signature:{reason}"
            for reason in trust_store.verify(
                receipt,
                expected_issuer="runtime_adapter",
            )
        )
    identity = receipt.get("identity")
    base_fields = set(artifact_identity)
    runtime_fields = {
        "runtime_id",
        "task_id",
        "role_id",
        "attempt_id",
        "attempt_no",
    }
    role_id = str((identity or {}).get("role_id") or "")
    if (
        receipt.get("receipt_type") != "COMPLETED"
        or not isinstance(identity, Mapping)
        or set(identity) != base_fields | runtime_fields
        or any(identity.get(field) != value for field, value in artifact_identity.items())
        or any(
            not SAFE_ID_RE.fullmatch(str(identity.get(field) or ""))
            for field in runtime_fields - {"attempt_no"}
        )
        or type(identity.get("attempt_no")) is not int
        or int(identity.get("attempt_no") or 0) < 1
        or (expected_role_id is not None and role_id != expected_role_id)
        or (forbidden_role_id is not None and role_id == forbidden_role_id)
    ):
        reasons.append("evo_v2_adapter_completion_identity")
    ordering = receipt.get("ordering")
    if (
        not isinstance(ordering, Mapping)
        or set(ordering)
        != {
            "scheduler_epoch",
            "dispatch_event_seq",
            "issued_at_utc",
            "started_at_utc",
            "finished_at_utc",
        }
        or type(ordering.get("scheduler_epoch")) is not int
        or type(ordering.get("dispatch_event_seq")) is not int
        or any(
            not isinstance(ordering.get(field), str) or not ordering.get(field)
            for field in ("issued_at_utc", "started_at_utc", "finished_at_utc")
        )
    ):
        reasons.append("evo_v2_adapter_completion_ordering")
    bindings = receipt.get("bindings")
    if (
        not isinstance(bindings, Mapping)
        or set(bindings)
        != {
            "plan_sha256",
            "task_sha256",
            "context_manifest_sha256",
            "dependency_admissions",
            "idempotency_key",
            "adapter_challenge",
        }
        or any(
            not SHA256_RE.fullmatch(str(bindings.get(field) or ""))
            for field in (
                "plan_sha256",
                "task_sha256",
                "context_manifest_sha256",
            )
        )
        or not isinstance(bindings.get("dependency_admissions"), list)
        or not isinstance(bindings.get("idempotency_key"), str)
        or not bindings.get("idempotency_key")
        or not isinstance(bindings.get("adapter_challenge"), str)
        or not bindings.get("adapter_challenge")
        or (
            expected_task_sha256 is not None
            and bindings.get("task_sha256") != expected_task_sha256
        )
    ):
        reasons.append("evo_v2_adapter_completion_bindings")
    session = receipt.get("session")
    runtime_handle = hashlib.sha256(
        str(expected_runtime_instance_id or "").encode("utf-8")
    ).hexdigest()
    if (
        not isinstance(session, Mapping)
        or set(session)
        != {
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
        or not SAFE_ID_RE.fullmatch(str(session.get("session_uid") or ""))
        or any(
            not SHA256_RE.fullmatch(str(session.get(field) or ""))
            for field in (
                "runtime_handle_sha256",
                "provider_handle_sha256",
                "adapter_build_sha256",
                "isolation_profile_sha256",
            )
        )
        or not isinstance(session.get("container_image_digest"), str)
        or not session.get("container_image_digest")
        or session.get("adapter_id") != getattr(trust_store, "installation_id", None)
        or type(session.get("lease_epoch")) is not int
        or (
            expected_session_id is not None
            and session.get("session_uid") != expected_session_id
        )
        or (
            expected_runtime_instance_id is not None
            and session.get("runtime_handle_sha256") != runtime_handle
        )
    ):
        reasons.append("evo_v2_adapter_completion_session")
    runtime = (
        session.get("runtime")
        if isinstance(session, Mapping)
        and isinstance(session.get("runtime"), Mapping)
        else {}
    )
    if runtime != {
        "provider": "deepseek",
        "model": "deepseek/deepseek-v4-flash",
        "transport": "openclaw_disposable_container",
        "isolation_class": "container_staged_context",
        "owned_termination_supported": True,
    }:
        reasons.append("evo_v2_adapter_completion_runtime")
    outcome = receipt.get("outcome")
    if (
        not isinstance(outcome, Mapping)
        or set(outcome)
        != {
            "returncode",
            "cancelled",
            "error_class",
            "private_output_sha256",
            "private_output_size_bytes",
            "termination_confirmed",
        }
        or outcome.get("returncode") != 0
        or outcome.get("cancelled") is not False
        or outcome.get("error_class") is not None
        or not SHA256_RE.fullmatch(str(outcome.get("private_output_sha256") or ""))
        or type(outcome.get("private_output_size_bytes")) is not int
        or int(outcome.get("private_output_size_bytes") or 0) <= 0
        or outcome.get("termination_confirmed") is not True
        or (
            expected_output_sha256 is not None
            and outcome.get("private_output_sha256") != expected_output_sha256
        )
        or (
            expected_output_size_bytes is not None
            and outcome.get("private_output_size_bytes")
            != expected_output_size_bytes
        )
    ):
        reasons.append("evo_v2_adapter_completion_outcome")
    return list(dict.fromkeys(reasons))


def _evo_v2_review_request_reasons(
    request: Any,
    *,
    projection: Mapping[str, Any],
    trust_store: Any,
) -> tuple[list[str], list[str], list[str]]:
    reasons: list[str] = []
    if not isinstance(request, Mapping):
        return ["evo_v2_review_request_object"], [], []
    expected_fields = {
        "contract_version",
        "artifact_identity",
        "reviewer_role_id",
        "projection",
        "staged_files",
        "source_execution_receipts",
        "source_session_ids",
        "source_runtime_handle_sha256s",
        "decision_options",
        "review_checks",
        "policy",
        "request_sha256",
    }
    if set(request) != expected_fields:
        reasons.append("evo_v2_review_request_fields")
    if (
        request.get("contract_version") != EVO_V2_MEMORY_REVIEW_REQUEST_VERSION
        or request.get("artifact_identity") != projection.get("artifact_identity")
        or request.get("reviewer_role_id") != REVIEWER_ROLE_ID
        or request.get("projection") != projection
        or validate_content_hash(
            request,
            hash_field="request_sha256",
            label="evo_v2_memory_review_request",
        )
    ):
        reasons.append("evo_v2_review_request_binding")
    staged_files = request.get("staged_files")
    expected_paths = {
        "identity/evo_v2_review_projection.json",
        "identity/evo_v2_experience_transfer_bundle.json",
        "identity/evo_v2_transfer_use_receipt.json",
    }
    observed_paths: set[str] = set()
    if not isinstance(staged_files, list) or len(staged_files) != 3:
        reasons.append("evo_v2_review_staged_files")
    else:
        for item in staged_files:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"path", "sha256", "size_bytes"}
                or not isinstance(item.get("path"), str)
                or Path(str(item.get("path"))).is_absolute()
                or ".." in Path(str(item.get("path"))).parts
                or not SHA256_RE.fullmatch(str(item.get("sha256") or ""))
                or type(item.get("size_bytes")) is not int
                or int(item.get("size_bytes") or 0) <= 0
            ):
                reasons.append("evo_v2_review_staged_file_entry")
                continue
            observed_paths.add(str(item["path"]))
    if observed_paths != expected_paths:
        reasons.append("evo_v2_review_staged_file_paths")
    source_receipts = request.get("source_execution_receipts")
    source_sessions: list[str] = []
    source_runtime_handles: list[str] = []
    if not isinstance(source_receipts, list) or not source_receipts:
        reasons.append("evo_v2_review_source_execution_receipts")
    else:
        for index, source_receipt in enumerate(source_receipts):
            source_reasons = _evo_v2_adapter_completion_reasons(
                source_receipt,
                artifact_identity=projection.get("artifact_identity") or {},
                trust_store=trust_store,
                forbidden_role_id=REVIEWER_ROLE_ID,
            )
            reasons.extend(
                f"evo_v2_review_source_{index}:{reason}"
                for reason in source_reasons
            )
            if isinstance(source_receipt, Mapping):
                session = source_receipt.get("session")
                if isinstance(session, Mapping):
                    source_sessions.append(str(session.get("session_uid") or ""))
                    source_runtime_handles.append(
                        str(session.get("runtime_handle_sha256") or "")
                    )
    if (
        len(set(source_sessions)) != len(source_sessions)
        or len(set(source_runtime_handles)) != len(source_runtime_handles)
        or request.get("source_session_ids") != source_sessions
        or request.get("source_runtime_handle_sha256s") != source_runtime_handles
    ):
        reasons.append("evo_v2_review_source_identity_binding")
    cold_start = projection.get("memory_state") == "COLD_START_NO_ADMISSIBLE_MEMORY"
    expected_decisions = (
        ["NOT_REQUIRED_VERIFIED_COLD_START", "REJECT"]
        if cold_start
        else ["APPROVE_ADVISORY_USE", "REJECT"]
    )
    if (
        request.get("decision_options") != expected_decisions
        or request.get("review_checks") != list(EVO_V2_MEMORY_REVIEW_CHECKS)
        or request.get("policy")
        != {
            "reviewer_selects_decision": True,
            "source_and_reviewer_sessions_must_differ": True,
            "current_factor_proof_authority": False,
            "canonical_memory_write_authority": False,
            "skill_or_policy_mutation_authority": False,
        }
    ):
        reasons.append("evo_v2_review_request_policy")
    if _contains_absolute_path(request):
        reasons.append("evo_v2_review_request_absolute_path")
    return list(dict.fromkeys(reasons)), source_sessions, source_runtime_handles


def prepare_evo_v2_memory_review_session(
    *,
    workspace: Path,
    worktree: Path,
    state_root: Path,
    installation_id: str,
    projection: Mapping[str, Any],
    experience_transfer_bundle: Mapping[str, Any],
    transfer_use_receipt: Mapping[str, Any],
    source_execution_receipts: list[Mapping[str, Any]],
    timeout_seconds: int = 1800,
) -> tuple[ResearchOrgSessionInvocation, dict[str, Any], Path]:
    """Prepare a disposable V2 reviewer session with staged read-only inputs."""

    worktree = Path(worktree).expanduser().resolve(strict=True)
    workspace = Path(workspace).expanduser().resolve(strict=True)
    state_root = Path(state_root).expanduser().resolve(strict=True)
    trust_store = load_runtime_trust_store(
        state_root / "research-org-trust",
        installation_id=installation_id,
    )
    if (
        not isinstance(projection, Mapping)
        or projection.get("contract_version")
        != EVO_V2_MEMORY_REVIEW_PROJECTION_VERSION
        or projection.get("eligible_for_independent_reviewer_consideration")
        is not True
        or validate_content_hash(
            projection,
            hash_field="projection_sha256",
            label="evo_v2_memory_review_projection",
        )
        or projection.get("source_contracts", {}).get(
            "experience_transfer_bundle_content_sha256"
        )
        != experience_transfer_bundle.get("content_sha256")
        or projection.get("source_contracts", {}).get(
            "transfer_use_receipt_content_sha256"
        )
        != transfer_use_receipt.get("content_sha256")
    ):
        _raise("evo_v2_review_projection_input")
    review_root = _assert_private_root(
        state_root / EVO_V2_REVIEW_SESSIONS_ROOT_NAME,
        repo_root=worktree,
        workspace=workspace,
        create=True,
    )
    token = uuid.uuid4().hex
    reviewer_session_id = f"session_evo_v2_review_{token[:24]}"
    runtime_instance_id = f"fforg-evo-v2-review-{token[:16]}"
    session_root = _ensure_private_directory(review_root, reviewer_session_id)
    context_root = _ensure_private_directory(session_root, "context")
    _ensure_private_directory(session_root, "output")
    staged_payloads = {
        "identity/evo_v2_review_projection.json": projection,
        "identity/evo_v2_experience_transfer_bundle.json": (
            experience_transfer_bundle
        ),
        "identity/evo_v2_transfer_use_receipt.json": transfer_use_receipt,
    }
    staged_files: list[dict[str, Any]] = []
    for relative, payload in staged_payloads.items():
        raw = _json_bytes(payload)
        _private_write_bytes(context_root, relative, raw)
        staged_files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    source_sessions: list[str] = []
    source_runtime_handles: list[str] = []
    for index, source_receipt in enumerate(source_execution_receipts):
        source_reasons = _evo_v2_adapter_completion_reasons(
            source_receipt,
            artifact_identity=projection["artifact_identity"],
            trust_store=trust_store,
            forbidden_role_id=REVIEWER_ROLE_ID,
        )
        if source_reasons:
            _raise(
                *(
                    f"evo_v2_source_{index}:{reason}"
                    for reason in source_reasons
                )
            )
        source_sessions.append(source_receipt["session"]["session_uid"])
        source_runtime_handles.append(
            source_receipt["session"]["runtime_handle_sha256"]
        )
    if (
        not source_sessions
        or len(set(source_sessions)) != len(source_sessions)
        or len(set(source_runtime_handles)) != len(source_runtime_handles)
        or reviewer_session_id in source_sessions
        or hashlib.sha256(runtime_instance_id.encode("utf-8")).hexdigest()
        in source_runtime_handles
    ):
        _raise("evo_v2_source_reviewer_independence")
    cold_start = projection["memory_state"] == "COLD_START_NO_ADMISSIBLE_MEMORY"
    request = with_content_hash(
        {
            "contract_version": EVO_V2_MEMORY_REVIEW_REQUEST_VERSION,
            "artifact_identity": dict(projection["artifact_identity"]),
            "reviewer_role_id": REVIEWER_ROLE_ID,
            "projection": dict(projection),
            "staged_files": staged_files,
            "source_execution_receipts": [
                dict(item) for item in source_execution_receipts
            ],
            "source_session_ids": source_sessions,
            "source_runtime_handle_sha256s": source_runtime_handles,
            "decision_options": (
                ["NOT_REQUIRED_VERIFIED_COLD_START", "REJECT"]
                if cold_start
                else ["APPROVE_ADVISORY_USE", "REJECT"]
            ),
            "review_checks": list(EVO_V2_MEMORY_REVIEW_CHECKS),
            "policy": {
                "reviewer_selects_decision": True,
                "source_and_reviewer_sessions_must_differ": True,
                "current_factor_proof_authority": False,
                "canonical_memory_write_authority": False,
                "skill_or_policy_mutation_authority": False,
            },
        },
        hash_field="request_sha256",
    )
    request_reasons, _, _ = _evo_v2_review_request_reasons(
        request,
        projection=projection,
        trust_store=trust_store,
    )
    if request_reasons:
        _raise(*request_reasons)
    _private_write_bytes(
        context_root,
        "identity/evo_v2_memory_review_request.json",
        _json_bytes(request),
    )
    invocation = ResearchOrgSessionInvocation(
        identity=dict(projection["artifact_identity"]),
        role_id=REVIEWER_ROLE_ID,
        task_id=f"evo_v2_memory_review_{token[:24]}",
        task_sha256=request["request_sha256"],
        attempt_id=f"attempt_evo_v2_memory_review_{token[:20]}",
        attempt_number=1,
        session_id=reviewer_session_id,
        runtime_instance_id=runtime_instance_id,
        worktree=worktree,
        workspace=workspace,
        private_attempt_root=session_root,
        context_root=context_root,
        private_output_path=session_root / "output" / "agent_result.json",
        cancel_request_path=session_root / "cancel_request.json",
        context_manifest_sha256=request["request_sha256"],
        required_skills=("factor-forge-researcher-memory",),
        timeout_seconds=timeout_seconds,
        runtime_id=f"runtime_evo_v2_memory_review_{token[:20]}",
        plan_sha256=stable_json_hash(
            {
                "projection_sha256": projection["projection_sha256"],
                "source_session_ids": source_sessions,
            }
        ),
        scheduler_epoch=1,
        dispatch_event_seq=1,
        idempotency_key=stable_json_hash(
            {
                "reviewer_session_id": reviewer_session_id,
                "projection_sha256": projection["projection_sha256"],
            }
        ),
        adapter_challenge=uuid.uuid4().hex,
        dependency_admissions=(),
        parent_session_uid=None,
    )
    return invocation, request, review_root


def build_evo_v2_memory_review_prompt(
    invocation: ResearchOrgSessionInvocation,
) -> str:
    request_path = (
        invocation.context_root / "identity/evo_v2_memory_review_request.json"
    )
    return f"""# Factor Forge EVO V2 independent memory review

You are a disposable independent reviewer session. You did not author the
source research. Read the frozen request at `{request_path}` and all staged
files. Decide from the evidence; do not infer approval from deterministic
checks or from an upstream APPROVE string. Market regime is context only.
You cannot modify skills, policies, thresholds, OOS rules, estimands, trial
budgets, canonical memory, or the current factor verdict.

Write exactly one private-output JSON object to
`{invocation.private_output_path}` using the request identity, projection hash,
review checks, decision options, and review-scope experience IDs. For a usable
non-cold transfer, every structural/conditional experience needs an explicit
`APPROVE_CANONICAL_SOURCE_FOR_ADVISORY_TRANSFER` decision. Otherwise choose
`REJECT`. Do not include private chain-of-thought or absolute Host paths.
"""


def validate_evo_v2_memory_reviewer_private_output(
    payload: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
) -> tuple[str, str, Mapping[str, Any], list[dict[str, Any]]]:
    if set(payload) != {"contract_version", "status", "public_research_record"}:
        _raise("evo_v2_review_private_output_fields")
    if (
        payload.get("contract_version") != PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
        or payload.get("status") != "PASS"
        or private_reasoning_paths(payload)
        or _contains_absolute_path(payload)
    ):
        _raise("evo_v2_review_private_output_contract")
    record = payload.get("public_research_record")
    if not isinstance(record, Mapping) or set(record) != {
        "contract_version",
        "artifact_identity",
        "reviewer_role_id",
        "projection_sha256",
        "decision",
        "rationale",
        "checks",
        "experience_decisions",
    }:
        _raise("evo_v2_review_agent_record_fields")
    projection = request.get("projection")
    if (
        record.get("contract_version")
        != EVO_V2_MEMORY_REVIEW_AGENT_RECORD_VERSION
        or record.get("artifact_identity") != request.get("artifact_identity")
        or record.get("reviewer_role_id") != REVIEWER_ROLE_ID
        or record.get("projection_sha256")
        != (projection or {}).get("projection_sha256")
    ):
        _raise("evo_v2_review_agent_record_binding")
    decision = record.get("decision")
    rationale = record.get("rationale")
    checks = record.get("checks")
    experience_decisions = record.get("experience_decisions")
    if decision not in (request.get("decision_options") or []):
        _raise("evo_v2_review_agent_decision")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        _raise("evo_v2_review_agent_rationale")
    if (
        not isinstance(checks, Mapping)
        or set(checks) != set(EVO_V2_MEMORY_REVIEW_CHECKS)
        or any(type(checks.get(check)) is not bool for check in EVO_V2_MEMORY_REVIEW_CHECKS)
    ):
        _raise("evo_v2_review_agent_checks")
    expected_ids = list((projection or {}).get("review_scope_experience_ids") or [])
    if not isinstance(experience_decisions, list):
        _raise("evo_v2_review_agent_experience_decisions")
    normalized: list[dict[str, Any]] = []
    for item in experience_decisions:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"experience_id", "decision"}
            or item.get("experience_id") not in expected_ids
            or item.get("decision")
            not in {
                "APPROVE_CANONICAL_SOURCE_FOR_ADVISORY_TRANSFER",
                "REJECT_SOURCE_FOR_ADVISORY_TRANSFER",
            }
        ):
            _raise("evo_v2_review_agent_experience_decision_entry")
        normalized.append(dict(item))
    if [item["experience_id"] for item in normalized] != expected_ids:
        _raise("evo_v2_review_agent_experience_decision_scope")
    expected_positive_decision = (
        "NOT_REQUIRED_VERIFIED_COLD_START"
        if (projection or {}).get("memory_state")
        == "COLD_START_NO_ADMISSIBLE_MEMORY"
        else "APPROVE_ADVISORY_USE"
    )
    if decision == expected_positive_decision:
        if (
            checks != (projection or {}).get("review_checks")
            or not all(checks.values())
            or any(
                item["decision"]
                != "APPROVE_CANONICAL_SOURCE_FOR_ADVISORY_TRANSFER"
                for item in normalized
            )
        ):
            _raise("evo_v2_review_agent_approval_checks")
    elif decision == "REJECT" and all(checks.values()) and all(
        item["decision"]
        == "APPROVE_CANONICAL_SOURCE_FOR_ADVISORY_TRANSFER"
        for item in normalized
    ):
        _raise("evo_v2_review_agent_rejection_checks")
    return str(decision), rationale.strip(), dict(checks), normalized


def complete_evo_v2_memory_review_session(
    *,
    invocation: ResearchOrgSessionInvocation,
    outcome: ResearchOrgSessionOutcome,
    state_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    """Admit a completed reviewer runtime result; never synthesize a decision."""

    trust_store = load_runtime_trust_store(
        Path(state_root) / "research-org-trust",
        installation_id=installation_id,
    )
    if (
        outcome.returncode != 0
        or outcome.cancelled
        or not outcome.owned_termination_supported
        or outcome.session_id != invocation.session_id
        or outcome.runtime_instance_id != invocation.runtime_instance_id
    ):
        _raise("evo_v2_review_runtime_outcome")
    request_path = (
        invocation.context_root / "identity/evo_v2_memory_review_request.json"
    )
    request = strict_json_loads(
        request_path.read_bytes(),
        label="evo_v2_memory_review_request",
    )
    projection = (
        request.get("projection") if isinstance(request, Mapping) else {}
    )
    request_reasons, source_sessions, source_runtime_handles = (
        _evo_v2_review_request_reasons(
            request,
            projection=projection if isinstance(projection, Mapping) else {},
            trust_store=trust_store,
        )
    )
    if (
        request_reasons
        or request.get("request_sha256") != invocation.task_sha256
        or invocation.session_id in source_sessions
        or hashlib.sha256(invocation.runtime_instance_id.encode("utf-8")).hexdigest()
        in source_runtime_handles
    ):
        _raise("evo_v2_review_request_runtime_binding", *request_reasons)
    parsed, output_bytes = _read_private_review_output(
        invocation.private_output_path
    )
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    decision, rationale, checks, experience_decisions = (
        validate_evo_v2_memory_reviewer_private_output(
            parsed,
            request=request,
        )
    )
    adapter_reasons = _evo_v2_adapter_completion_reasons(
        outcome.adapter_receipt,
        artifact_identity=projection["artifact_identity"],
        trust_store=trust_store,
        expected_role_id=REVIEWER_ROLE_ID,
        expected_task_sha256=invocation.task_sha256,
        expected_session_id=invocation.session_id,
        expected_runtime_instance_id=invocation.runtime_instance_id,
        expected_output_sha256=output_sha256,
        expected_output_size_bytes=len(output_bytes),
    )
    if adapter_reasons:
        _raise("evo_v2_review_adapter_completion", *adapter_reasons)
    adapter_receipt = dict(outcome.adapter_receipt or {})
    decision_receipt = with_content_hash(
        {
            "contract_version": EVO_V2_MEMORY_REVIEW_DECISION_RECEIPT_TYPE,
            "authority": "runtime_attested_review_host_countersign_required",
            "identity": dict(projection["artifact_identity"]),
            "reviewer": {
                "reviewer_id": REVIEWER_ID,
                "reviewer_role_id": REVIEWER_ROLE_ID,
                "reviewer_session_id": invocation.session_id,
                "runtime_instance_id": invocation.runtime_instance_id,
                "independence_class": "runtime_attested_independent_review",
            },
            "bindings": {
                "projection_sha256": projection["projection_sha256"],
                "source_contracts": dict(projection["source_contracts"]),
                "review_scope_experience_ids": list(
                    projection["review_scope_experience_ids"]
                ),
                "cold_start_search_receipt_id": projection[
                    "cold_start_search_receipt_id"
                ],
                "review_request_sha256": request["request_sha256"],
                "adapter_completion_receipt_id": adapter_receipt["receipt_id"],
                "review_output_sha256": output_sha256,
                "source_session_ids": source_sessions,
                "source_runtime_handle_sha256s": source_runtime_handles,
            },
            "decision": decision,
            "rationale": rationale,
            "checks": checks,
            "experience_decisions": experience_decisions,
            "runtime_evidence": {
                "adapter_completion_receipt": adapter_receipt,
                "review_request": dict(request),
                "review_output": dict(parsed),
                "review_output_sha256": output_sha256,
                "model_execution": {
                    "provider": outcome.provider,
                    "model": outcome.model,
                    "transport": outcome.transport,
                    "isolation_class": outcome.isolation_class,
                    "owned_termination_supported": (
                        outcome.owned_termination_supported
                    ),
                },
            },
            "authority_guard": {
                "host_countersign_required": True,
                "canonical_memory_write_authority": False,
                "current_factor_proof_authority": False,
                "skill_or_policy_mutation_authority": False,
            },
        },
        hash_field="decision_sha256",
    )
    decision_reasons = validate_evo_v2_memory_review_decision(
        decision_receipt,
        projection=projection,
        trust_store=trust_store,
    )
    if decision_reasons:
        _raise(*decision_reasons)
    return decision_receipt
