from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any, Mapping, Protocol

from factor_factory.research_org.contracts import (
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
    BLOCK_MEMORY_REVIEW_INVALID,
    REVIEW_DECISIONS,
    _assert_private_root,
    _atomic_store_json,
    _contains_absolute_path,
    _ensure_private_directory,
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
