from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

import factor_factory.researcher_memory as memory_module

from factor_factory.research_org import (
    ResearchOrganizationError,
    load_research_organization_plan,
    validate_research_organization_bundle,
    write_research_organization_bundle,
)
from factor_factory.research_org.contracts import (
    stable_json_hash,
    with_content_hash,
    write_workspace_json_once,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.research_org.runtime import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    ResearchOrgSessionOutcome,
    _context_source_paths,
)
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)
from factor_factory.researcher_memory import (
    BLOCK_MEMORY_PROMOTION_FORBIDDEN,
    BLOCK_MEMORY_CANDIDATE_INVALID,
    BLOCK_MEMORY_ROOT_INVALID,
    BLOCK_MEMORY_STORE_INVALID,
    build_role_memory_snapshots,
    ensure_researcher_memory_store,
    materialize_learning_candidates,
    load_candidate_review_material,
    promote_reviewed_candidate,
    record_candidate_review,
    record_research_outcome,
    validate_memory_candidate,
    validate_researcher_memory_store,
)
from factor_factory.researcher_memory_review import (
    REVIEW_AGENT_RECORD_CONTRACT_VERSION,
    REVIEW_CHECKS,
    REVIEWER_ROLE_ID,
    run_and_record_independent_review,
    sign_completed_reviewer_session,
    validate_reviewer_private_output,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLATION_ID = "researcher-memory-test-001"


def _request() -> dict:
    return {
        "job_id": "job_memory_001",
        "factor_id": "MEMORY_FACTOR",
        "research_id": "memory_research",
        "report_id": "MEMORY_REPORT",
        "title": "Liquidity pressure reversal",
        "hypothesis": (
            "Forced liquidity demand transfers value from constrained sellers "
            "to patient buyers and should reverse after the pressure decays."
        ),
        "input_kind": "hypothesis",
    }


def _workspace(
    tmp_path: Path,
    *,
    memory_enabled: bool = True,
    memory_root_override: Path | None = None,
) -> tuple[Path, Path]:
    runtime_root = tmp_path / "factorforge"
    workspace = (
        runtime_root
        / "factor_research"
        / "MEMORY_FACTOR"
        / "memory_research"
    )
    manifest = build_workspace_manifest(
        repo_root=PROJECT_ROOT,
        factorforge_root=runtime_root,
        factor_id="MEMORY_FACTOR",
        research_id="memory_research",
        root_report_id="MEMORY_REPORT",
        implementation_mode="hybrid",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    identity = workspace / "identity"
    (identity / "web_research_request.json").write_text("{}\n", encoding="utf-8")
    (identity / "web_research_authoring_contract.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (identity / "factor_knowledge_summary.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (identity / "data_catalog_summary.json").write_text("{}\n", encoding="utf-8")
    memory_root = (
        memory_root_override
        if memory_root_override is not None
        else tmp_path / "host-private-researcher-memory"
    )
    if memory_enabled:
        ensure_runtime_trust_store(
            memory_root.parent / "research-org-trust",
            installation_id=INSTALLATION_ID,
        )
    write_research_organization_bundle(
        workspace=workspace,
        request=_request(),
        researcher_memory_root=memory_root if memory_enabled else None,
        researcher_memory_installation_id=(
            INSTALLATION_ID if memory_enabled else None
        ),
    )
    return workspace, memory_root


def _tasks(workspace: Path) -> dict[str, dict]:
    plan = load_research_organization_plan(workspace)
    dispatch = json.loads(
        (workspace / plan["workspace_policy"]["dispatch_manifest_path"]).read_text(
            encoding="utf-8"
        )
    )
    return {
        reference["role_id"]: json.loads(
            (workspace / reference["path"]).read_text(encoding="utf-8")
        )
        for reference in dispatch["tasks"]
    }


def _candidate_result(workspace: Path, task: dict, *, suffix: str = "") -> dict:
    evidence_relative = f"reports/memory_evidence{suffix}.json"
    evidence_path = workspace / evidence_relative
    evidence_path.write_text('{"evidence":"bounded"}\n', encoding="utf-8")
    evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    result = with_content_hash(
        {
            "contract_version": "factorforge_agent_result_v1",
            "task_ref": {
                "task_id": task["task_id"],
                "sha256": task["task_sha256"],
            },
            "identity": dict(task["identity"]),
            "role_id": task["role_id"],
            "status": "PASS",
            "producer_mode": "real_agent",
            "session_id": f"session_source{suffix or '_001'}",
            "public_research_record": {
                "contract_version": task["output_contract"],
                "identity": {
                    "task_id": task["task_id"],
                    "factor_id": task["identity"]["factor_id"],
                    "research_id": task["identity"]["research_id"],
                    "report_id": task["identity"]["report_id"],
                    "agent_role": task["role_id"],
                },
                "domain": "price_volume",
                "proposal_status": "ready_for_director_review",
                "domain_fit": {"fit": "primary", "reason": "Mechanism aligned."},
                "public_research_record": {
                    "public_derivation_summary": [
                        "Define the pressure estimand and its falsifier."
                    ]
                },
                "math_model_search": {
                    "candidates": ["primary", "alternative", "null"]
                },
                "measurement_proposal": {"implementation_route": "direct_code"},
                "knowledge_use": [],
                "data_dependencies": [],
                "falsification_plan": {"distinguishing_tests": ["null test"]},
                "uncertainties": [],
                "artifact_refs": [
                    {"path": evidence_relative, "sha256": evidence_sha}
                ],
                "handoff": {"status": "ready_for_host_review"},
            },
        },
        hash_field="result_sha256",
    )
    write_workspace_json_once(workspace, task["expected_result_path"], result)
    return result


def _source_runtime_provenance(
    workspace: Path,
    memory_root: Path,
    task: dict,
    result: dict,
) -> dict:
    trust_store = ensure_runtime_trust_store(
        memory_root.parent / "research-org-trust",
        installation_id=INSTALLATION_ID,
    )
    plan = load_research_organization_plan(workspace)
    runtime_identity = {
        **dict(task["identity"]),
        "runtime_id": "runtime_memory_test",
        "task_id": task["task_id"],
        "role_id": task["role_id"],
        "attempt_id": f"attempt_{task['role_id']}_001",
    }
    adapter = trust_store.sign(
        "runtime_adapter",
        {
            "receipt_type": "COMPLETED",
            "identity": {**runtime_identity, "attempt_no": 1},
            "ordering": {
                "scheduler_epoch": 1,
                "dispatch_event_seq": 1,
                "issued_at_utc": "2026-08-10T00:00:00Z",
                "started_at_utc": "2026-08-10T00:00:01Z",
                "finished_at_utc": "2026-08-10T00:00:02Z",
            },
            "bindings": {
                "plan_sha256": plan["plan_sha256"],
                "task_sha256": task["task_sha256"],
                "context_manifest_sha256": "1" * 64,
                "dependency_admissions": [],
                "idempotency_key": f"idem_{task['role_id']}",
                "adapter_challenge": f"challenge_{task['role_id']}",
            },
            "session": {
                "session_uid": result["session_id"],
                "runtime_handle_sha256": "2" * 64,
                "provider_handle_sha256": "3" * 64,
                "adapter_id": INSTALLATION_ID,
                "adapter_build_sha256": "4" * 64,
                "container_image_digest": "sha256:" + "5" * 64,
                "isolation_profile_sha256": "6" * 64,
                "parent_session_uid": None,
                "lease_epoch": 1,
            },
            "outcome": {
                "returncode": 0,
                "cancelled": False,
                "error_class": None,
                "private_output_sha256": "7" * 64,
                "private_output_size_bytes": 128,
                "termination_confirmed": True,
            },
        },
    )
    host = trust_store.sign(
        "host_admission",
        {
            "receipt_type": "RESULT_ADMITTED",
            "identity": runtime_identity,
            "ordering": {
                "event_seq": 2,
                "scheduler_epoch": 1,
                "dispatch_event_seq": 1,
                "issued_at_utc": "2026-08-10T00:00:03Z",
            },
            "bindings": {
                "plan_sha256": plan["plan_sha256"],
                "task_sha256": task["task_sha256"],
                "context_manifest_sha256": "1" * 64,
                "dependency_admissions": [],
                "adapter_receipt_id": adapter["receipt_id"],
                "result_sha256": result["result_sha256"],
            },
            "outcome": {
                "result_status": result["status"],
                "evidence_class": "signed_adapter",
            },
        },
    )
    return {
        "adapter_receipt": adapter,
        "host_admission_receipt": host,
    }


def _memory_trust_store(memory_root: Path):
    return ensure_runtime_trust_store(
        memory_root.parent / "research-org-trust",
        installation_id=INSTALLATION_ID,
    )


def _host_attestation(
    memory_root: Path,
    name: str,
    *,
    identity: dict,
    roles: list[str],
    execution_status: str = "COMPLETED",
    protocol_status: str = "PASS",
    factor_verdict: str = "REJECT",
    council_status: str = "PASS",
    formal_proof_eligible: bool = True,
    provider: str = "test",
    model: str = "test-model",
) -> dict[str, str]:
    state_root = memory_root.parent
    receipt_directory = state_root / "receipts" / identity["job_id"]
    receipt_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    receipt_directory.chmod(0o700)
    receipt_path = receipt_directory / "formal.json"
    receipt_payload = {
        "version": "factorforge_console_host_formal_execution_v2",
        **identity,
        "commands": [
            {"name": "materialize_web_research", "returncode": 0},
            {"name": "run_factorforge_ultimate", "returncode": 0},
        ],
    }
    receipt_path.write_text(
        json.dumps(receipt_payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    directory = state_root / "attestations" / identity["job_id"]
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    filename = name if name.startswith("attestation_") else f"attestation_{name}"
    path = directory / filename
    evidence_tree_path = directory / f"evidence_tree_{Path(filename).stem}.json"
    evidence_entries = {"objects/runtime_context/proof.json": "7" * 64}
    evidence_tree_payload = {
        "version": "factorforge_console_workspace_evidence_tree_v1",
        **identity,
        "entries": evidence_entries,
        "tree_sha256": stable_json_hash(evidence_entries),
    }
    evidence_tree_path.write_text(
        json.dumps(evidence_tree_payload, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    evidence_tree_path.chmod(0o600)
    payload = {
        "version": "factorforge_console_host_execution_attestation_v2",
        **identity,
        "base_commit": "a" * 40,
        "host_observed_ultimate_process": True,
        "host_evidence_reader_invoked": True,
        "host_terminal_formal_validation_status": (
            "PASS" if formal_proof_eligible else "BLOCK"
        ),
        "agent_provider": provider,
        "agent_model": model,
        "researcher_memory_outcome": {
            "execution_status": execution_status,
            "protocol_status": protocol_status,
            "factor_verdict": factor_verdict,
            "council_status": council_status,
            "formal_proof_eligible": formal_proof_eligible,
            "organization_runtime_verified": True,
            "roles": roles,
        },
        "formal_execution_receipt_id": receipt_path.relative_to(
            state_root
        ).as_posix(),
        "formal_execution_receipt_sha256": hashlib.sha256(
            receipt_path.read_bytes()
        ).hexdigest(),
        "workspace_evidence_tree_id": evidence_tree_path.relative_to(
            state_root
        ).as_posix(),
        "workspace_evidence_tree_sha256": hashlib.sha256(
            evidence_tree_path.read_bytes()
        ).hexdigest(),
        "workspace_evidence_tree_root_sha256": stable_json_hash(
            evidence_entries
        ),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return {
        "id": path.relative_to(state_root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _proposal(result: dict, *, title: str = "Pressure-decay falsifier") -> dict:
    return {
        "memory_kind": "falsification_pattern",
        "title": title,
        "lesson": (
            "A pressure mechanism should be rejected when the signal survives "
            "after the constrained-liquidity state has measurably decayed."
        ),
        "applicability_conditions": [
            "The estimand explicitly represents forced liquidity demand."
        ],
        "failure_conditions": [
            "The signal is unchanged after pressure-state ablation."
        ],
        "evidence_refs": list(result["public_research_record"]["artifact_refs"]),
    }


def _prepared_candidate(
    workspace: Path,
    memory_root: Path,
    *,
    suffix: str = "",
    title: str = "Pressure-decay falsifier",
) -> tuple[dict, dict, dict]:
    task = _tasks(workspace)["price_volume_researcher"]
    result = _candidate_result(workspace, task, suffix=suffix)
    candidate_ref = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[_proposal(result, title=title)],
        runtime_provenance=_source_runtime_provenance(
            workspace,
            memory_root,
            task,
            result,
        ),
        trust_store=_memory_trust_store(memory_root),
    )["candidate_refs"][0]
    return task, result, candidate_ref


def _terminal_outcome(
    workspace: Path,
    memory_root: Path,
    task: dict,
    *,
    attestation_name: str,
    factor_verdict: str = "REJECT",
    formal_proof_eligible: bool = True,
) -> dict:
    plan = load_research_organization_plan(workspace)
    roles = list(plan["role_plan"]["required_roles"])
    return record_research_outcome(
        memory_root,
        installation_id=INSTALLATION_ID,
        store_id=plan["researcher_memory"]["store_id"],
        identity=task["identity"],
        role_ids=roles,
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict=factor_verdict,
        council_status="PASS",
        formal_proof_eligible=formal_proof_eligible,
        organization_runtime_verified=True,
        host_attestation_ref=_host_attestation(
            memory_root,
            attestation_name,
            identity=dict(task["identity"]),
            roles=roles,
            factor_verdict=factor_verdict,
            formal_proof_eligible=formal_proof_eligible,
        ),
        model_execution={
            "provider": "test",
            "model": "test-model",
            "provenance": "host_pinned_agent_runtime",
        },
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )


def _review_session_receipt_ref(
    workspace: Path,
    memory_root: Path,
    candidate_ref: dict,
    outcome: dict,
    *,
    session_id: str,
    decision: str,
    rationale: str,
    reviewer_id: str = "independent_memory_reviewer",
) -> dict[str, str]:
    candidate = json.loads(
        (workspace / candidate_ref["path"]).read_text(encoding="utf-8")
    )
    reviewer = {
        "reviewer_id": reviewer_id,
        "reviewer_session_id": session_id,
        "runtime_instance_id": f"runtime_{session_id}",
        "independence_class": "runtime_attested_independent_review",
    }
    public_reviewer = {
        "reviewer_id": reviewer["reviewer_id"],
        "reviewer_session_id": reviewer["reviewer_session_id"],
        "independence_class": "host_attested_independent_review",
    }
    outcome_ref = {
        "event_id": outcome["event_id"],
        "sha256": outcome["event_sha256"],
    }
    material = load_candidate_review_material(
        workspace=workspace,
        candidate_relative=candidate_ref["path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        outcome_event_id=outcome["event_id"],
        repo_root=PROJECT_ROOT,
    )
    review_parent = material["review_parent"]
    expected_parent_generation = int(review_parent["generation"]) + 1
    current_memory_ref = {
        "path": (
            "objects/research_organization/"
            f"{candidate['identity']['report_id']}"
            "/memory_review_context/current_role_memory_snapshot.json"
        ),
        "sha256": material["current_memory_snapshot"]["snapshot_sha256"],
        "hash_kind": "json_content",
    }
    request = with_content_hash(
        {
            "contract_version": (
                "factorforge_researcher_memory_review_request_v1"
            ),
            "identity": dict(candidate["identity"]),
            "reviewer_role_id": "researcher_memory_reviewer",
            "candidate_ref": dict(candidate_ref),
            "outcome_event_ref": outcome_ref,
            "source_session_id": candidate["source_session_id"],
            "review_parent": review_parent,
            "current_memory_snapshot_ref": current_memory_ref,
            "decision_options": ["APPROVE_CANONICAL", "REJECT"],
            "review_checks": list(REVIEW_CHECKS),
            "staged_files": [],
            "policy": {
                "current_factor_proof_authority": False,
                "canonical_write_authority": False,
                "private_reasoning_allowed": False,
                "reviewer_selects_decision": True,
            },
        },
        hash_field="request_sha256",
    )
    checks = {check: True for check in REVIEW_CHECKS}
    if decision == "REJECT":
        checks["novel_or_nonduplicative"] = False
    review_output = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": {
            "contract_version": REVIEW_AGENT_RECORD_CONTRACT_VERSION,
            "identity": dict(candidate["identity"]),
            "reviewer_role_id": "researcher_memory_reviewer",
            "candidate_ref": dict(candidate_ref),
            "outcome_event_ref": outcome_ref,
            "review_parent": review_parent,
            "current_memory_snapshot_ref": current_memory_ref,
            "decision": decision,
            "rationale": rationale,
            "checks": checks,
        },
    }
    review_output_bytes = (
        json.dumps(review_output, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    review_output_sha256 = hashlib.sha256(review_output_bytes).hexdigest()
    claim_sha256 = memory_module._review_claim_sha256(
        identity=candidate["identity"],
        candidate_ref=candidate_ref,
        outcome_event_ref=outcome_ref,
        reviewer=public_reviewer,
        source_session_id=candidate["source_session_id"],
        decision=decision,
        rationale=rationale,
        canonical_write_authorized=decision == "APPROVE_CANONICAL",
        review_parent=review_parent,
        expected_parent_generation=expected_parent_generation,
    )
    trust_store = ensure_runtime_trust_store(
        memory_root.parent / "research-org-trust",
        installation_id=INSTALLATION_ID,
    )
    adapter_receipt = trust_store.sign(
        "runtime_adapter",
        {
            "receipt_type": "COMPLETED",
            "identity": {
                **dict(candidate["identity"]),
                "runtime_id": f"runtime_memory_review_{session_id}",
                "task_id": f"memory_review_{session_id}",
                "role_id": "researcher_memory_reviewer",
                "attempt_id": f"attempt_memory_review_{session_id}",
                "attempt_no": 1,
            },
            "session": {
                "session_uid": session_id,
                "runtime_handle_sha256": hashlib.sha256(
                    reviewer["runtime_instance_id"].encode("utf-8")
                ).hexdigest(),
                "adapter_id": INSTALLATION_ID,
                "parent_session_uid": None,
            },
            "bindings": {"task_sha256": request["request_sha256"]},
            "outcome": {
                "returncode": 0,
                "cancelled": False,
                "termination_confirmed": True,
                "private_output_sha256": review_output_sha256,
                "private_output_size_bytes": len(review_output_bytes),
            },
        },
    )
    reviewer_receipt = trust_store.sign(
        "runtime_adapter",
        {
            "receipt_type": "RESEARCHER_MEMORY_REVIEW_COMPLETED",
            "identity": dict(candidate["identity"]),
            "reviewer": reviewer,
            "bindings": {
                "candidate_ref": candidate_ref,
                "outcome_event_ref": outcome_ref,
                "source_session_id": candidate["source_session_id"],
                "review_claim_sha256": claim_sha256,
                "review_parent": review_parent,
                "expected_parent_generation": expected_parent_generation,
            },
            "runtime_evidence": {
                "adapter_completion_receipt": adapter_receipt,
                "review_request": request,
                "review_output": review_output,
                "review_output_sha256": review_output_sha256,
                "model_execution": {
                    "provider": "test",
                    "model": "fixture",
                    "transport": "test_disposable_container",
                    "isolation_class": "container_staged_context",
                    "owned_termination_supported": True,
                },
            },
            "outcome": {
                "returncode": 0,
                "termination_confirmed": True,
                "secret_scan": "PASS",
            },
        },
    )
    receipt_root = memory_root.parent / "reviewer-session-receipts"
    receipt_root.mkdir(mode=0o700, exist_ok=True)
    receipt_root.chmod(0o700)
    receipt_path = receipt_root / f"{reviewer_receipt['receipt_id']}.json"
    receipt_path.write_text(
        json.dumps(reviewer_receipt, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    return {
        "id": receipt_path.relative_to(memory_root.parent).as_posix(),
        "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }


def _approved_review(
    workspace: Path,
    memory_root: Path,
    candidate_ref: dict,
    outcome: dict,
    *,
    session_id: str,
) -> dict:
    rationale = "The evidence-bound lesson is reusable outside the source factor."
    return record_candidate_review(
        workspace=workspace,
        candidate_relative=candidate_ref["path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        decision="APPROVE_CANONICAL",
        reviewer_session_receipt_ref=_review_session_receipt_ref(
            workspace,
            memory_root,
            candidate_ref,
            outcome,
            session_id=session_id,
            decision="APPROVE_CANONICAL",
            rationale=rationale,
        ),
        outcome_event_id=outcome["event_id"],
        rationale=rationale,
        repo_root=PROJECT_ROOT,
    )


class _SignedIndependentMemoryReviewRunner:
    def __init__(
        self,
        *,
        state_root: Path,
        decision: str,
    ) -> None:
        self.state_root = state_root
        self.decision = decision

    def run_researcher_memory_review_session(self, invocation):
        request = json.loads(
            (
                invocation.context_root
                / "identity/researcher_memory_review_request.json"
            ).read_text(encoding="utf-8")
        )
        checks = {check: True for check in REVIEW_CHECKS}
        rationale = "The bounded lesson is supported and reusable."
        if self.decision == "REJECT":
            checks["novel_or_nonduplicative"] = False
            rationale = "The lesson duplicates an existing role-memory pattern."
        private_output = {
            "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
            "status": "PASS",
            "public_research_record": {
                "contract_version": REVIEW_AGENT_RECORD_CONTRACT_VERSION,
                "identity": request["identity"],
                "reviewer_role_id": REVIEWER_ROLE_ID,
                "candidate_ref": request["candidate_ref"],
                "outcome_event_ref": request["outcome_event_ref"],
                "review_parent": request["review_parent"],
                "current_memory_snapshot_ref": request[
                    "current_memory_snapshot_ref"
                ],
                "decision": self.decision,
                "rationale": rationale,
                "checks": checks,
            },
        }
        output_bytes = (
            json.dumps(private_output, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        invocation.private_output_path.write_bytes(output_bytes)
        trust_store = ensure_runtime_trust_store(
            self.state_root / "research-org-trust",
            installation_id=INSTALLATION_ID,
        )
        adapter_receipt = trust_store.sign(
            "runtime_adapter",
            {
                "receipt_type": "COMPLETED",
                "identity": {
                    **dict(invocation.identity),
                    "runtime_id": invocation.runtime_id,
                    "task_id": invocation.task_id,
                    "role_id": invocation.role_id,
                    "attempt_id": invocation.attempt_id,
                    "attempt_no": invocation.attempt_number,
                },
                "ordering": {
                    "scheduler_epoch": invocation.scheduler_epoch,
                    "dispatch_event_seq": invocation.dispatch_event_seq,
                    "issued_at_utc": "2026-08-10T00:00:03Z",
                    "started_at_utc": "2026-08-10T00:00:01Z",
                    "finished_at_utc": "2026-08-10T00:00:03Z",
                },
                "bindings": {
                    "plan_sha256": invocation.plan_sha256,
                    "task_sha256": invocation.task_sha256,
                    "context_manifest_sha256": (
                        invocation.context_manifest_sha256
                    ),
                    "dependency_admissions": [],
                    "idempotency_key": invocation.idempotency_key,
                    "adapter_challenge": invocation.adapter_challenge,
                },
                "session": {
                    "session_uid": invocation.session_id,
                    "runtime_handle_sha256": hashlib.sha256(
                        invocation.runtime_instance_id.encode("utf-8")
                    ).hexdigest(),
                    "provider_handle_sha256": "3" * 64,
                    "adapter_id": INSTALLATION_ID,
                    "adapter_build_sha256": "4" * 64,
                    "container_image_digest": "sha256:" + "5" * 64,
                    "isolation_profile_sha256": "6" * 64,
                    "parent_session_uid": None,
                    "lease_epoch": invocation.scheduler_epoch,
                },
                "outcome": {
                    "returncode": 0,
                    "cancelled": False,
                    "error_class": None,
                    "private_output_sha256": hashlib.sha256(
                        output_bytes
                    ).hexdigest(),
                    "private_output_size_bytes": len(output_bytes),
                    "termination_confirmed": True,
                },
            },
        )
        outcome = ResearchOrgSessionOutcome(
            returncode=0,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc="2026-08-10T00:00:01Z",
            finished_at_utc="2026-08-10T00:00:03Z",
            provider="test",
            model="independent-reviewer-test",
            transport="signed_test_adapter",
            isolation_class="container_staged_context",
            owned_termination_supported=True,
            adapter_receipt=adapter_receipt,
        )
        return sign_completed_reviewer_session(
            invocation=invocation,
            outcome=outcome,
            state_root=self.state_root,
            installation_id=INSTALLATION_ID,
        )


def test_memory_root_must_be_disjoint_from_repo_and_workspace(tmp_path: Path) -> None:
    workspace, _memory_root = _workspace(tmp_path, memory_enabled=False)
    role = {"role_id": "price_volume_researcher"}
    with pytest.raises(ResearchOrganizationError, match=BLOCK_MEMORY_ROOT_INVALID):
        build_role_memory_snapshots(
            workspace / "memory",
            installation_id=INSTALLATION_ID,
            identity={
                "job_id": "job_memory_001",
                "factor_id": "MEMORY_FACTOR",
                "research_id": "memory_research",
                "report_id": "MEMORY_REPORT",
            },
            roles=[role],
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_bundle_freezes_one_role_scoped_snapshot_per_task(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    summary = validate_research_organization_bundle(workspace=workspace)
    assert summary["verdict"] == "PASS"
    plan = load_research_organization_plan(workspace)
    tasks = _tasks(workspace)
    binding = plan["researcher_memory"]
    assert set(binding["role_snapshot_refs"]) == set(
        plan["role_plan"]["required_roles"]
    )
    assert all("role_memory" in task for task in tasks.values())
    assert all(
        task["role_memory"]["snapshot_ref"]
        == binding["role_snapshot_refs"][role_id]
        for role_id, task in tasks.items()
    )
    assert all(
        reference not in task["input_artifacts"]
        for role_id, task in tasks.items()
        for reference in binding["role_snapshot_refs"].values()
    )
    assert validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )["verdict"] == "PASS"


def test_context_stages_only_the_current_roles_memory_snapshot(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    tasks = _tasks(workspace)
    price_task = tasks["price_volume_researcher"]
    knowledge_task = tasks["knowledge_librarian"]
    price_paths = _context_source_paths(workspace, price_task, tasks)
    knowledge_paths = _context_source_paths(workspace, knowledge_task, tasks)
    price_snapshot = price_task["role_memory"]["snapshot_ref"]["path"]
    knowledge_snapshot = knowledge_task["role_memory"]["snapshot_ref"]["path"]
    assert price_snapshot in price_paths
    assert knowledge_snapshot not in price_paths
    assert knowledge_snapshot in knowledge_paths
    assert price_snapshot not in knowledge_paths


def test_legacy_bundle_remains_memory_off_and_valid(tmp_path: Path) -> None:
    workspace, _memory_root = _workspace(tmp_path, memory_enabled=False)
    plan = load_research_organization_plan(workspace)
    assert "researcher_memory" not in plan
    assert all("role_memory" not in task for task in _tasks(workspace).values())
    assert not (
        workspace
        / "objects"
        / "research_organization"
        / "MEMORY_REPORT"
        / "memory_snapshots"
    ).exists()
    assert validate_research_organization_bundle(workspace=workspace)["verdict"] == "PASS"


def test_preserve_existing_never_refreshes_snapshot_after_store_advances(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    plan_before = (workspace / "identity/research_organization_plan.json").read_bytes()
    snapshot_paths = sorted(
        (
            workspace
            / "objects"
            / "research_organization"
            / "MEMORY_REPORT"
            / "memory_snapshots"
        ).glob("*.json")
    )
    snapshots_before = {path.name: path.read_bytes() for path in snapshot_paths}
    plan = load_research_organization_plan(workspace)
    task = _tasks(workspace)["price_volume_researcher"]
    record_research_outcome(
        memory_root,
        installation_id=INSTALLATION_ID,
        store_id=plan["researcher_memory"]["store_id"],
        identity=task["identity"],
        role_ids=plan["role_plan"]["required_roles"],
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="REJECT",
        council_status="PASS",
        formal_proof_eligible=True,
        organization_runtime_verified=True,
        host_attestation_ref=_host_attestation(
            memory_root,
            "frozen.json",
            identity=dict(task["identity"]),
            roles=list(plan["role_plan"]["required_roles"]),
            model="m",
        ),
        model_execution={
            "provider": "test",
            "model": "m",
            "provenance": "host_pinned_agent_runtime",
        },
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )

    write_research_organization_bundle(
        workspace=workspace,
        request=_request(),
        preserve_existing=True,
        researcher_memory_root=memory_root,
        researcher_memory_installation_id=INSTALLATION_ID,
    )

    assert (workspace / "identity/research_organization_plan.json").read_bytes() == plan_before
    assert {path.name: path.read_bytes() for path in snapshot_paths} == snapshots_before
    assert load_research_organization_plan(workspace)["researcher_memory"][
        "source_generation"
    ] == 0


def test_candidate_is_deterministic_separate_and_never_self_promotes(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task = _tasks(workspace)["price_volume_researcher"]
    result = _candidate_result(workspace, task)
    proposal = _proposal(result)
    runtime_provenance = _source_runtime_provenance(
        workspace,
        memory_root,
        task,
        result,
    )
    first = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[proposal],
        runtime_provenance=runtime_provenance,
        trust_store=_memory_trust_store(memory_root),
    )
    second = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[dict(reversed(list(proposal.items())))],
        runtime_provenance=runtime_provenance,
        trust_store=_memory_trust_store(memory_root),
    )
    assert first["candidate_refs"] == second["candidate_refs"]
    candidate_ref = first["candidate_refs"][0]
    candidate = json.loads(
        (workspace / candidate_ref["path"]).read_text(encoding="utf-8")
    )
    assert candidate["authority"] == "candidate_only"
    assert candidate["promotion_allowed"] is False
    assert validate_memory_candidate(candidate, task=task, result=result) == []
    assert set(result) == {
        "contract_version",
        "task_ref",
        "identity",
        "role_id",
        "status",
        "producer_mode",
        "session_id",
        "public_research_record",
        "result_sha256",
    }


def test_candidate_requires_signed_source_runtime_before_review(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task = _tasks(workspace)["price_volume_researcher"]
    result = _candidate_result(workspace, task)
    missing = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[_proposal(result)],
    )
    assert missing["candidate_refs"] == []
    assert missing["rejections"] == [
        "source_runtime_provenance_missing_or_invalid"
    ]

    forged = _source_runtime_provenance(
        workspace,
        memory_root,
        task,
        result,
    )
    forged["adapter_receipt"]["signature"]["value_b64"] = "AAAA"
    forged_materialization = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[_proposal(result, title="Forged source runtime")],
        runtime_provenance=forged,
        trust_store=_memory_trust_store(memory_root),
    )
    assert forged_materialization["candidate_refs"] == []
    assert any(
        "source_adapter_signature" in reason
        for reason in forged_materialization["rejections"]
    )


def test_rehashed_candidate_content_cannot_reuse_materialization_receipt(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, result, candidate_ref = _prepared_candidate(workspace, memory_root)
    candidate_path = workspace / candidate_ref["path"]
    tampered = json.loads(candidate_path.read_text(encoding="utf-8"))
    tampered["lesson"] = (
        "An attacker-authored replacement lesson must not inherit source admission."
    )
    candidate_core = {
        key: value
        for key, value in tampered.items()
        if key
        not in {
            "contract_version",
            "candidate_id",
            "candidate_sha256",
            "materialization_receipt",
        }
    }
    tampered["candidate_id"] = f"candidate_{stable_json_hash(candidate_core)[:24]}"
    tampered["candidate_sha256"] = stable_json_hash(
        {
            key: value
            for key, value in tampered.items()
            if key not in {"candidate_sha256", "materialization_receipt"}
        }
    )
    tampered_relative = (
        "objects/research_organization/MEMORY_REPORT/memory_candidates/"
        f"price_volume_researcher__{tampered['candidate_id']}.json"
    )
    tampered_path = workspace / tampered_relative
    tampered_path.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    candidate_path.unlink()

    reasons = validate_memory_candidate(
        tampered,
        task=task,
        result=result,
        trust_store=_memory_trust_store(memory_root),
    )
    assert any("candidate_materialization_receipt_binding" in reason for reason in reasons)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="candidate-content-tamper.json",
    )
    with pytest.raises(
        ResearchOrganizationError,
        match="research_organization_bundle_not_admitted",
    ):
        load_candidate_review_material(
            workspace=workspace,
            candidate_relative=tampered_relative,
            root=memory_root,
            installation_id=INSTALLATION_ID,
            outcome_event_id=outcome["event_id"],
            repo_root=PROJECT_ROOT,
        )


@pytest.mark.parametrize(
    ("decision", "expected_authorized"),
    [("APPROVE_CANONICAL", True), ("REJECT", False)],
)
def test_formal_reviewer_runner_selects_and_signs_decision(
    tmp_path: Path,
    decision: str,
    expected_authorized: bool,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    candidate = json.loads(
        (workspace / candidate_ref["path"]).read_text(encoding="utf-8")
    )
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name=f"formal-review-{decision.lower()}.json",
    )
    worktree = workspace.parents[2]
    result = run_and_record_independent_review(
        workspace=workspace,
        worktree=worktree,
        memory_root=memory_root,
        installation_id=INSTALLATION_ID,
        candidate_relative=candidate_ref["path"],
        outcome_event_id=outcome["event_id"],
        runner=_SignedIndependentMemoryReviewRunner(
            state_root=memory_root.parent,
            decision=decision,
        ),
        timeout_seconds=30,
    )

    assert result["decision"] == decision
    assert result["reviewer_session_id"] != candidate["source_session_id"]
    assert result["review"]["decision"] == decision
    review_payload = json.loads(
        (workspace / result["review"]["workspace_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert review_payload["canonical_write_authorized"] is expected_authorized
    assert (
        review_payload["reviewer"]["reviewer_session_id"]
        != review_payload["candidate_snapshot"]["source_session_id"]
    )
    receipt_path = (
        memory_root.parent / result["reviewer_session_receipt_ref"]["id"]
    )
    assert receipt_path.is_file()
    assert validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=worktree,
        workspace=workspace,
    )["review_count"] == 1


def test_reviewer_output_cannot_approve_with_failed_check() -> None:
    request = {
        "identity": {
            "job_id": "job_review",
            "factor_id": "FACTOR",
            "research_id": "research",
            "report_id": "REPORT",
        },
        "candidate_ref": {"path": "candidate.json", "sha256": "1" * 64},
        "outcome_event_ref": {"event_id": "outcome_1", "sha256": "2" * 64},
        "review_parent": {
            "store_id": "researcher_memory_test",
            "generation": 1,
            "manifest_sha256": "3" * 64,
        },
        "current_memory_snapshot_ref": {
            "path": "current_memory.json",
            "sha256": "4" * 64,
            "hash_kind": "json_content",
        },
    }
    checks = {check: True for check in REVIEW_CHECKS}
    checks["source_evidence_bound"] = False
    payload = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": {
            "contract_version": REVIEW_AGENT_RECORD_CONTRACT_VERSION,
            "identity": request["identity"],
            "reviewer_role_id": REVIEWER_ROLE_ID,
            "candidate_ref": request["candidate_ref"],
            "outcome_event_ref": request["outcome_event_ref"],
            "review_parent": {
                "store_id": "researcher_memory_test",
                "generation": 1,
                "manifest_sha256": "3" * 64,
            },
            "current_memory_snapshot_ref": {
                "path": "current_memory.json",
                "sha256": "4" * 64,
                "hash_kind": "json_content",
            },
            "decision": "APPROVE_CANONICAL",
            "rationale": "Unsupported approval must block.",
            "checks": checks,
        },
    }
    with pytest.raises(
        ResearchOrganizationError,
        match="review_agent_approval_checks",
    ):
        validate_reviewer_private_output(payload, request=request)


def test_formal_reviewer_cli_does_not_accept_operator_decision() -> None:
    source = (
        PROJECT_ROOT / "scripts/run_factorforge_researcher_memory_review.py"
    ).read_text(encoding="utf-8")
    assert 'parser.add_argument("--decision"' not in source
    assert 'parser.add_argument("--rationale"' not in source


def test_reviewed_promotion_advances_store_and_future_snapshot(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    plan = load_research_organization_plan(workspace)
    task = _tasks(workspace)["price_volume_researcher"]
    result = _candidate_result(workspace, task)
    candidate_ref = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[_proposal(result)],
        runtime_provenance=_source_runtime_provenance(
            workspace, memory_root, task, result
        ),
        trust_store=_memory_trust_store(memory_root),
    )["candidate_refs"][0]
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="a.json",
    )
    review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_session_001",
    )
    promoted = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )
    assert promoted["idempotent"] is False
    assert promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )["idempotent"] is True
    snapshots = build_role_memory_snapshots(
        memory_root,
        installation_id=INSTALLATION_ID,
        identity=task["identity"],
        roles=[task["role_snapshot"]],
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    snapshot = snapshots["price_volume_researcher"]
    assert snapshot["performance_scorecard"]["factor_verdict_counts"] == {
        "REJECT": 1
    }
    assert snapshot["performance_scorecard"]["protocol_status_counts"] == {
        "PASS": 1
    }
    assert snapshot["canonical_memories"][0]["source_factor_verdict"] == "REJECT"
    assert snapshot["performance_scorecard"]["interpretation_guard"] == (
        "protocol PASS is not factor ACCEPT"
    )


def test_host_blocks_duplicate_memory_even_when_reviewer_approves(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path / "first")
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="duplicate-source.json",
    )
    first_review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_duplicate_source",
    )
    promote_reviewed_candidate(
        workspace=workspace,
        review_relative=first_review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )

    second_workspace, _ = _workspace(
        tmp_path / "second",
        memory_root_override=memory_root,
    )
    second_task, _second_result, second_candidate_ref = _prepared_candidate(
        second_workspace,
        memory_root,
        suffix="_duplicate",
    )
    assert second_task["identity"] == task["identity"]
    second_review = _approved_review(
        second_workspace,
        memory_root,
        second_candidate_ref,
        outcome,
        session_id="review_duplicate_copy",
    )

    with pytest.raises(
        ResearchOrganizationError,
        match="duplicate_canonical_memory",
    ):
        promote_reviewed_candidate(
            workspace=second_workspace,
            review_relative=second_review["workspace_path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
        )


def test_self_review_and_stale_parent_generation_block(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    plan = load_research_organization_plan(workspace)
    task = _tasks(workspace)["price_volume_researcher"]
    result = _candidate_result(workspace, task, suffix="_stale")
    candidate_ref = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[_proposal(result, title="Stale-review candidate")],
        runtime_provenance=_source_runtime_provenance(
            workspace, memory_root, task, result
        ),
        trust_store=_memory_trust_store(memory_root),
    )["candidate_refs"][0]
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="b.json",
    )
    with pytest.raises(ResearchOrganizationError, match="review_session_receipt_reviewer"):
        record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="APPROVE_CANONICAL",
            reviewer_session_receipt_ref=_review_session_receipt_ref(
                workspace,
                memory_root,
                candidate_ref,
                outcome,
                session_id=result["session_id"],
                decision="APPROVE_CANONICAL",
                rationale="Self review must fail.",
                reviewer_id="self_reviewer",
            ),
            outcome_event_id=outcome["event_id"],
            rationale="Self review must fail.",
            repo_root=PROJECT_ROOT,
        )
    review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_session_stale",
    )
    record_research_outcome(
        memory_root,
        installation_id=INSTALLATION_ID,
        store_id=plan["researcher_memory"]["store_id"],
        identity={**task["identity"], "job_id": "job_memory_advance"},
        role_ids=plan["role_plan"]["required_roles"],
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="ACCEPT",
        council_status="PASS",
        formal_proof_eligible=True,
        organization_runtime_verified=True,
        host_attestation_ref=_host_attestation(
            memory_root,
            "c.json",
            identity={**task["identity"], "job_id": "job_memory_advance"},
            roles=list(plan["role_plan"]["required_roles"]),
            factor_verdict="ACCEPT",
            model="m",
        ),
        model_execution={
            "provider": "test",
            "model": "m",
            "provenance": "host_pinned_agent_runtime",
        },
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    with pytest.raises(
        ResearchOrganizationError,
        match=f"{BLOCK_MEMORY_PROMOTION_FORBIDDEN}: stale_parent_generation",
    ):
        promote_reviewed_candidate(
            workspace=workspace,
            review_relative=review["workspace_path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
        )


def test_unsigned_review_parent_rewrite_cannot_bypass_generation_cas(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    plan = load_research_organization_plan(workspace)
    task, _result, candidate_ref = _prepared_candidate(
        workspace,
        memory_root,
        suffix="_cas",
        title="CAS-bound review",
    )
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="cas-parent.json",
    )
    rationale = "The review parent must remain part of the signed runtime claim."
    receipt_ref = _review_session_receipt_ref(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_session_cas",
        decision="APPROVE_CANONICAL",
        rationale=rationale,
    )
    advanced_identity = {**task["identity"], "job_id": "job_memory_cas_advance"}
    record_research_outcome(
        memory_root,
        installation_id=INSTALLATION_ID,
        store_id=plan["researcher_memory"]["store_id"],
        identity=advanced_identity,
        role_ids=plan["role_plan"]["required_roles"],
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="REJECT",
        council_status="PASS",
        formal_proof_eligible=True,
        organization_runtime_verified=True,
        host_attestation_ref=_host_attestation(
            memory_root,
            "cas-advance.json",
            identity=advanced_identity,
            roles=list(plan["role_plan"]["required_roles"]),
        ),
        model_execution={
            "provider": "test",
            "model": "test-model",
            "provenance": "host_pinned_agent_runtime",
        },
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    current = validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    new_parent = {
        "store_id": current["store_id"],
        "generation": current["generation"],
        "manifest_sha256": current["manifest_sha256"],
    }
    receipt_path = memory_root.parent / receipt_ref["id"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["bindings"]["review_parent"] = new_parent
    receipt["bindings"]["expected_parent_generation"] = (
        current["generation"] + 1
    )
    public_reviewer = {
        "reviewer_id": receipt["reviewer"]["reviewer_id"],
        "reviewer_session_id": receipt["reviewer"]["reviewer_session_id"],
        "independence_class": "host_attested_independent_review",
    }
    receipt["bindings"]["review_claim_sha256"] = (
        memory_module._review_claim_sha256(
            identity=receipt["identity"],
            candidate_ref=candidate_ref,
            outcome_event_ref={
                "event_id": outcome["event_id"],
                "sha256": outcome["event_sha256"],
            },
            reviewer=public_reviewer,
            source_session_id=receipt["bindings"]["source_session_id"],
            decision="APPROVE_CANONICAL",
            rationale=rationale,
            canonical_write_authorized=True,
            review_parent=new_parent,
            expected_parent_generation=current["generation"] + 1,
        )
    )
    request = receipt["runtime_evidence"]["review_request"]
    request["review_parent"] = new_parent
    request = with_content_hash(
        {key: value for key, value in request.items() if key != "request_sha256"},
        hash_field="request_sha256",
    )
    receipt["runtime_evidence"]["review_request"] = request
    receipt["runtime_evidence"]["review_output"]["public_research_record"][
        "review_parent"
    ] = new_parent
    receipt["runtime_evidence"]["adapter_completion_receipt"]["bindings"][
        "task_sha256"
    ] = request["request_sha256"]
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tampered_ref = {
        "id": receipt_ref["id"],
        "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }

    with pytest.raises(ResearchOrganizationError, match="signature"):
        record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="APPROVE_CANONICAL",
            reviewer_session_receipt_ref=tampered_ref,
            outcome_event_id=outcome["event_id"],
            rationale=rationale,
            repo_root=PROJECT_ROOT,
        )


def test_store_validation_rejects_hardlinked_canonical_record(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    plan = load_research_organization_plan(workspace)
    task = _tasks(workspace)["price_volume_researcher"]
    result = _candidate_result(workspace, task, suffix="_hardlink")
    candidate_ref = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[_proposal(result, title="Hardlink test")],
        runtime_provenance=_source_runtime_provenance(
            workspace, memory_root, task, result
        ),
        trust_store=_memory_trust_store(memory_root),
    )["candidate_refs"][0]
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="d.json",
    )
    review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_session_hardlink",
    )
    promoted = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )
    source = memory_root / "canonical" / f"{promoted['memory_id']}.json"
    os.link(source, memory_root / "canonical" / "alias.json")
    with pytest.raises(ResearchOrganizationError, match=BLOCK_MEMORY_STORE_INVALID):
        validate_researcher_memory_store(
            memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_direct_researcher_memory_import_has_no_circular_import() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import factor_factory.researcher_memory"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("mode", [0o700, 0o755])
def test_init_rejects_nonempty_existing_root_without_mutation(
    tmp_path: Path,
    mode: int,
) -> None:
    root = tmp_path / f"existing-{mode:o}"
    root.mkdir(mode=mode)
    root.chmod(mode)
    sentinel = root / "sentinel.txt"
    sentinel.write_text("do-not-touch\n", encoding="utf-8")
    before_entries = sorted(path.name for path in root.iterdir())
    before_payload = sentinel.read_bytes()
    before_mode = root.stat().st_mode & 0o777

    with pytest.raises(ResearchOrganizationError, match=BLOCK_MEMORY_ROOT_INVALID):
        ensure_researcher_memory_store(
            root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
        )

    assert sorted(path.name for path in root.iterdir()) == before_entries
    assert sentinel.read_bytes() == before_payload
    assert root.stat().st_mode & 0o777 == before_mode


def test_init_cli_rejects_symlink_root_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    target.chmod(0o700)
    sentinel = target / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    symlink = tmp_path / "memory-link"
    symlink.symlink_to(target, target_is_directory=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/init_factorforge_researcher_memory.py"),
            "--memory-root",
            str(symlink),
            "--installation-id",
            INSTALLATION_ID,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert BLOCK_MEMORY_ROOT_INVALID in completed.stderr
    assert sorted(path.name for path in target.iterdir()) == ["sentinel.txt"]
    assert sentinel.read_text(encoding="utf-8") == "unchanged\n"
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("missing_source", ["result", "evidence"])
def test_review_rejects_candidate_with_missing_admitted_source(
    tmp_path: Path,
    missing_source: str,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, result, candidate_ref = _prepared_candidate(workspace, memory_root)
    missing_path = (
        workspace / task["expected_result_path"]
        if missing_source == "result"
        else workspace / result["public_research_record"]["artifact_refs"][0]["path"]
    )
    missing_path.unlink()

    with pytest.raises(ResearchOrganizationError, match=BLOCK_MEMORY_CANDIDATE_INVALID):
        record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="APPROVE_CANONICAL",
            reviewer_session_receipt_ref={
                "id": "reviewer-session-receipts/missing.json",
                "sha256": "0" * 64,
            },
            outcome_event_id="outcome_missing",
            rationale="Missing source evidence must block before review admission.",
            repo_root=PROJECT_ROOT,
        )


def test_outcome_requires_terminal_verdict_proof_and_real_attestation(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    plan = load_research_organization_plan(workspace)
    task = _tasks(workspace)["price_volume_researcher"]
    common = {
        "installation_id": INSTALLATION_ID,
        "store_id": plan["researcher_memory"]["store_id"],
        "identity": task["identity"],
        "role_ids": plan["role_plan"]["required_roles"],
        "protocol_status": "PASS",
        "council_status": "PASS",
        "organization_runtime_verified": True,
        "model_execution": {
            "provider": "test",
            "model": "test-model",
            "provenance": "host_pinned_agent_runtime",
        },
        "repo_root": PROJECT_ROOT,
        "workspace": workspace,
    }
    attestation = _host_attestation(
        memory_root,
        "outcome-guards.json",
        identity=dict(task["identity"]),
        roles=list(plan["role_plan"]["required_roles"]),
    )
    with pytest.raises(ResearchOrganizationError, match="outcome_not_terminal"):
        record_research_outcome(
            memory_root,
            execution_status="ITERATING",
            factor_verdict="ITERATE",
            formal_proof_eligible=False,
            host_attestation_ref=attestation,
            **common,
        )
    with pytest.raises(ResearchOrganizationError, match="accept_without_formal_proof"):
        record_research_outcome(
            memory_root,
            execution_status="COMPLETED",
            factor_verdict="ACCEPT",
            formal_proof_eligible=False,
            host_attestation_ref=attestation,
            **common,
        )
    with pytest.raises(ResearchOrganizationError, match="unreadable"):
        record_research_outcome(
            memory_root,
            execution_status="COMPLETED",
            factor_verdict="REJECT",
            formal_proof_eligible=False,
            host_attestation_ref={
                "id": (
                    "attestations/job_memory_001/attestation_missing.json"
                ),
                "sha256": "a" * 64,
            },
            **common,
        )
    fake_path = (
        memory_root.parent
        / "attestations"
        / task["identity"]["job_id"]
        / "attestation_fake.json"
    )
    fake_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fake_path.write_text('{"host_attested":true}\n', encoding="utf-8")
    fake_path.chmod(0o600)
    with pytest.raises(
        ResearchOrganizationError,
        match="host_attestation_contract_version",
    ):
        record_research_outcome(
            memory_root,
            execution_status="COMPLETED",
            factor_verdict="REJECT",
            formal_proof_eligible=False,
            host_attestation_ref={
                "id": fake_path.relative_to(memory_root.parent).as_posix(),
                "sha256": hashlib.sha256(fake_path.read_bytes()).hexdigest(),
            },
            **common,
        )
    nested_ref = _host_attestation(
        memory_root,
        "nested-evidence-missing.json",
        identity=dict(task["identity"]),
        roles=list(plan["role_plan"]["required_roles"]),
        formal_proof_eligible=False,
    )
    nested_path = memory_root.parent / nested_ref["id"]
    nested_payload = json.loads(nested_path.read_text(encoding="utf-8"))
    nested_payload["formal_execution_receipt_id"] = (
        "receipts/job_memory_001/nonexistent.json"
    )
    nested_payload["formal_execution_receipt_sha256"] = "a" * 64
    nested_path.write_text(
        json.dumps(nested_payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        ResearchOrganizationError,
        match="formal_execution_receipt_readback",
    ):
        record_research_outcome(
            memory_root,
            execution_status="COMPLETED",
            factor_verdict="REJECT",
            formal_proof_eligible=False,
            host_attestation_ref={
                "id": nested_ref["id"],
                "sha256": hashlib.sha256(nested_path.read_bytes()).hexdigest(),
            },
            **common,
        )
    with pytest.raises(
        ResearchOrganizationError,
        match="organization_runtime_unverified",
    ):
        record_research_outcome(
            memory_root,
            execution_status="COMPLETED",
            factor_verdict="REJECT",
            formal_proof_eligible=False,
            organization_runtime_verified=False,
            host_attestation_ref=attestation,
            **{
                key: value
                for key, value in common.items()
                if key != "organization_runtime_verified"
            },
        )
    validation = validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    assert validation["generation"] == 0
    assert validation["outcome_event_count"] == 0


def test_one_identity_cannot_record_conflicting_terminal_outcomes(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task = _tasks(workspace)["price_volume_researcher"]
    plan = load_research_organization_plan(workspace)
    roles = list(plan["role_plan"]["required_roles"])
    _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="terminal-a.json",
    )
    second_attestation = _host_attestation(
        memory_root,
        "terminal-b.json",
        identity=dict(task["identity"]),
        roles=roles,
        protocol_status="BLOCK",
    )
    with pytest.raises(
        ResearchOrganizationError,
        match="terminal_outcome_identity_conflict",
    ):
        record_research_outcome(
            memory_root,
            installation_id=INSTALLATION_ID,
            store_id=plan["researcher_memory"]["store_id"],
            identity=task["identity"],
            role_ids=roles,
            execution_status="COMPLETED",
            protocol_status="BLOCK",
            factor_verdict="REJECT",
            council_status="PASS",
            formal_proof_eligible=True,
            organization_runtime_verified=True,
            host_attestation_ref=second_attestation,
            model_execution={
                "provider": "test",
                "model": "test-model",
                "provenance": "host_pinned_agent_runtime",
            },
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_store_revalidates_outcome_attestation_bytes(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task = _tasks(workspace)["price_volume_researcher"]
    _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="durable-attestation.json",
    )
    attestation_path = (
        memory_root.parent
        / "attestations/job_memory_001/attestation_durable-attestation.json"
    )
    attestation_path.write_text('{"host_attested":false}\n', encoding="utf-8")
    attestation_path.chmod(0o600)

    with pytest.raises(
        ResearchOrganizationError,
        match="outcome_attestation_readback",
    ):
        validate_researcher_memory_store(
            memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_tampered_reviewer_signature_blocks_promotion(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="signature.json",
    )
    review_ref = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_signature",
    )
    review_path = workspace / review_ref["workspace_path"]
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviewer_attestation"]["signature"]["value_b64"] = "AAAA"
    review = with_content_hash(review, hash_field="review_sha256")
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ResearchOrganizationError,
        match="research_organization_bundle_not_admitted",
    ):
        promote_reviewed_candidate(
            workspace=workspace,
            review_relative=review_ref["workspace_path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
        )


def test_tampered_reviewer_session_receipt_blocks_review(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="review-session-signature.json",
    )
    rationale = "The reviewer receipt must bind this exact rejection rationale."
    receipt_ref = _review_session_receipt_ref(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_session_tampered",
        decision="REJECT",
        rationale=rationale,
    )
    receipt_path = memory_root.parent / receipt_ref["id"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["signature"]["value_b64"] = "AAAA"
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_ref["sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    with pytest.raises(
        ResearchOrganizationError,
        match="review_session_receipt_signature",
    ):
        record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="REJECT",
            reviewer_session_receipt_ref=receipt_ref,
            outcome_event_id=outcome["event_id"],
            rationale=rationale,
            repo_root=PROJECT_ROOT,
        )


def test_signed_review_receipt_without_runtime_evidence_is_rejected(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(
        workspace,
        memory_root,
        suffix="_runtime_evidence",
    )
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="review-runtime-evidence.json",
    )
    rationale = "A durable review must preserve the complete runtime evidence chain."
    receipt_ref = _review_session_receipt_ref(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_session_without_runtime_evidence",
        decision="REJECT",
        rationale=rationale,
    )
    receipt_path = memory_root.parent / receipt_ref["id"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt.pop("runtime_evidence")
    receipt = _memory_trust_store(memory_root).sign("runtime_adapter", receipt)
    receipt_path = receipt_path.with_name(f"{receipt['receipt_id']}.json")
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)

    with pytest.raises(ResearchOrganizationError, match="review_runtime_evidence_fields"):
        record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="REJECT",
            reviewer_session_receipt_ref={
                "id": receipt_path.relative_to(memory_root.parent).as_posix(),
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            },
            outcome_event_id=outcome["event_id"],
            rationale=rationale,
            repo_root=PROJECT_ROOT,
        )


def test_rehashed_review_and_manifest_cannot_bypass_signed_claim(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="rehash-review.json",
    )
    review_ref = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_rehash_attack",
    )
    old_review_path = memory_root / "reviews" / f"{review_ref['review_id']}.json"
    review = json.loads(old_review_path.read_text(encoding="utf-8"))
    review["rationale"] = "Attacker rewrote the rationale after the signed session."
    review_core = {
        key: value
        for key, value in review.items()
        if key not in {"contract_version", "review_id", "review_sha256"}
    }
    review["review_id"] = (
        f"review_{memory_module.stable_json_hash(review_core)[:24]}"
    )
    review = with_content_hash(
        {key: value for key, value in review.items() if key != "review_sha256"},
        hash_field="review_sha256",
    )
    new_review_path = memory_root / "reviews" / f"{review['review_id']}.json"
    old_review_path.unlink()
    new_review_path.write_text(
        json.dumps(review, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    new_review_path.chmod(0o600)

    manifest_path = memory_root / "store_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reviews"][0].update(
        {
            "review_id": review["review_id"],
            "path": f"reviews/{review['review_id']}.json",
            "sha256": review["review_sha256"],
        }
    )
    manifest = with_content_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"},
        hash_field="manifest_sha256",
    )
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ResearchOrganizationError,
        match="review_session_receipt_bindings",
    ):
        validate_researcher_memory_store(
            memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_rehashed_canonical_and_manifest_remain_bound_to_signed_review(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="rehash-canonical.json",
    )
    review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="canonical_rehash_attack",
    )
    promoted = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )
    canonical_path = memory_root / "canonical" / f"{promoted['memory_id']}.json"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical["lesson"] = "Attacker replaced the signed candidate-derived lesson."
    canonical = with_content_hash(
        {
            key: value
            for key, value in canonical.items()
            if key != "canonical_sha256"
        },
        hash_field="canonical_sha256",
    )
    canonical_path.write_text(
        json.dumps(canonical, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = memory_root / "store_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_records"][0]["sha256"] = canonical["canonical_sha256"]
    manifest = with_content_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"},
        hash_field="manifest_sha256",
    )
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ResearchOrganizationError, match="canonical_candidate_link"):
        validate_researcher_memory_store(
            memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_snapshot_freeze_rejects_payload_not_matching_manifest_reference(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="snapshot-binding.json",
    )
    review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_snapshot_binding",
    )
    promoted = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )
    canonical_path = memory_root / "canonical" / f"{promoted['memory_id']}.json"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
    canonical["title"] = "Tampered but internally rehashed title"
    canonical = with_content_hash(canonical, hash_field="canonical_sha256")
    canonical_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    canonical_path.chmod(0o600)

    with pytest.raises(ResearchOrganizationError, match=BLOCK_MEMORY_STORE_INVALID):
        build_role_memory_snapshots(
            memory_root,
            installation_id=INSTALLATION_ID,
            identity=task["identity"],
            roles=[task["role_snapshot"]],
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def test_store_validation_rejects_symlink_record_entry(tmp_path: Path) -> None:
    workspace, memory_root = _workspace(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    (memory_root / "canonical/alias.json").symlink_to(outside)

    with pytest.raises(ResearchOrganizationError, match="canonical_unsafe_entry"):
        validate_researcher_memory_store(
            memory_root,
            installation_id=INSTALLATION_ID,
            repo_root=PROJECT_ROOT,
            workspace=workspace,
        )


def _fail_next_manifest_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    original = memory_module._atomic_store_json
    failed = False

    def interrupted(root, relative, payload, *, replace):
        nonlocal failed
        if relative == "store_manifest.json" and replace and not failed:
            failed = True
            raise RuntimeError("simulated manifest interruption")
        return original(root, relative, payload, replace=replace)

    monkeypatch.setattr(memory_module, "_atomic_store_json", interrupted)


def test_orphan_atomic_temp_is_recovered_before_next_operation(
    tmp_path: Path,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    orphan = memory_root / "tmp" / f"write_999_{'a' * 32}.tmp"
    orphan.write_bytes(b"partial atomic payload")
    orphan.chmod(0o600)

    ensure_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )

    assert not orphan.exists()
    assert validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )["verdict"] == "PASS"


def test_interrupted_outcome_commit_recovers_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task = _tasks(workspace)["price_volume_researcher"]
    with monkeypatch.context() as patcher:
        _fail_next_manifest_replace(patcher)
        with pytest.raises(RuntimeError, match="simulated manifest interruption"):
            _terminal_outcome(
                workspace,
                memory_root,
                task,
                attestation_name="recover-outcome.json",
            )

    recovered = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="recover-outcome.json",
    )
    validation = validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    assert recovered["idempotent"] is True
    assert validation["generation"] == 1
    assert validation["outcome_event_count"] == 1
    assert list((memory_root / "transactions").iterdir()) == []


def test_interrupted_review_commit_recovers_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="recover-review.json",
    )
    rationale = "The evidence-bound lesson is reusable outside the source factor."
    receipt_ref = _review_session_receipt_ref(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="review_recovery",
        decision="APPROVE_CANONICAL",
        rationale=rationale,
    )

    def admit_review() -> dict:
        return record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="APPROVE_CANONICAL",
            reviewer_session_receipt_ref=receipt_ref,
            outcome_event_id=outcome["event_id"],
            rationale=rationale,
            repo_root=PROJECT_ROOT,
        )

    with monkeypatch.context() as patcher:
        _fail_next_manifest_replace(patcher)
        with pytest.raises(RuntimeError, match="simulated manifest interruption"):
            admit_review()

    recovered = admit_review()
    validation = validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    assert recovered["idempotent"] is True
    assert validation["generation"] == 2
    assert validation["review_count"] == 1
    assert list((memory_root / "transactions").iterdir()) == []


def test_interrupted_promotion_commit_recovers_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, memory_root = _workspace(tmp_path)
    task, _result, candidate_ref = _prepared_candidate(workspace, memory_root)
    outcome = _terminal_outcome(
        workspace,
        memory_root,
        task,
        attestation_name="recover-promotion.json",
    )
    review = _approved_review(
        workspace,
        memory_root,
        candidate_ref,
        outcome,
        session_id="promotion_recovery",
    )
    with monkeypatch.context() as patcher:
        _fail_next_manifest_replace(patcher)
        with pytest.raises(RuntimeError, match="simulated manifest interruption"):
            promote_reviewed_candidate(
                workspace=workspace,
                review_relative=review["workspace_path"],
                root=memory_root,
                installation_id=INSTALLATION_ID,
                repo_root=PROJECT_ROOT,
            )

    recovered = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
    )
    validation = validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    assert recovered["idempotent"] is True
    assert validation["generation"] == 3
    assert validation["canonical_record_count"] == 1
    assert list((memory_root / "transactions").iterdir()) == []
