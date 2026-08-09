#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_org import (
    ResearchOrganizationError,
    load_research_organization_plan,
    write_research_organization_bundle,
)
from factor_factory.research_org.contracts import (
    stable_json_hash,
    with_content_hash,
    write_workspace_json_once,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)
from factor_factory.researcher_memory import (
    BLOCK_MEMORY_REVIEW_INVALID,
    BLOCK_MEMORY_ROOT_INVALID,
    ensure_researcher_memory_store,
    load_candidate_review_material,
    materialize_learning_candidates,
    promote_reviewed_candidate,
    record_candidate_review,
    record_research_outcome,
    validate_memory_candidate,
    validate_researcher_memory_store,
)
from factor_factory import researcher_memory as memory_module
from factor_factory.research_org.runtime import PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
from factor_factory.researcher_memory_review import (
    REVIEW_AGENT_RECORD_CONTRACT_VERSION,
    REVIEW_CHECKS,
)


INSTALLATION_ID = "factorforge-researcher-memory-smoke"


def _task_for_role(workspace: Path, role_id: str) -> dict:
    plan = load_research_organization_plan(workspace)
    dispatch = json.loads(
        (workspace / plan["workspace_policy"]["dispatch_manifest_path"]).read_text(
            encoding="utf-8"
        )
    )
    reference = next(
        item for item in dispatch["tasks"] if item["role_id"] == role_id
    )
    return json.loads((workspace / reference["path"]).read_text(encoding="utf-8"))


def _source_runtime_provenance(
    *,
    trust_store,
    plan: dict,
    task: dict,
    result: dict,
) -> dict:
    runtime_identity = {
        **dict(task["identity"]),
        "runtime_id": "runtime_memory_smoke",
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


def _host_attestation_ref(
    *,
    state_root: Path,
    task: dict,
    roles: list[str],
) -> dict[str, str]:
    receipt_root = state_root / "receipts" / task["identity"]["job_id"]
    receipt_root.mkdir(mode=0o700, parents=True)
    receipt_root.chmod(0o700)
    receipt_path = receipt_root / "formal.json"
    receipt_path.write_text(
        json.dumps(
            {
                "version": "factorforge_console_host_formal_execution_v2",
                **task["identity"],
                "commands": [
                    {"name": "materialize_web_research", "returncode": 0},
                    {"name": "run_factorforge_ultimate", "returncode": 0},
                ],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    attestation_root = state_root / "attestations" / task["identity"]["job_id"]
    attestation_root.mkdir(mode=0o700, parents=True)
    attestation_root.chmod(0o700)
    path = attestation_root / "attestation_memory_smoke.json"
    evidence_entries = {"objects/runtime_context/proof.json": "7" * 64}
    evidence_tree_path = attestation_root / "evidence_tree_memory_smoke.json"
    evidence_tree_path.write_text(
        json.dumps(
            {
                "version": "factorforge_console_workspace_evidence_tree_v1",
                **task["identity"],
                "entries": evidence_entries,
                "tree_sha256": stable_json_hash(evidence_entries),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_tree_path.chmod(0o600)
    path.write_text(
        json.dumps(
            {
                "version": "factorforge_console_host_execution_attestation_v2",
                **task["identity"],
                "host_observed_ultimate_process": True,
                "host_evidence_reader_invoked": True,
                "host_terminal_formal_validation_status": "PASS",
                "agent_provider": "smoke",
                "agent_model": "contract-fixture",
                "researcher_memory_outcome": {
                    "execution_status": "COMPLETED",
                    "protocol_status": "PASS",
                    "factor_verdict": "REJECT",
                    "council_status": "PASS",
                    "formal_proof_eligible": True,
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
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return {
        "id": path.relative_to(state_root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _review_session_receipt_ref(
    *,
    state_root: Path,
    trust_store,
    workspace: Path,
    candidate_ref: dict,
    outcome: dict,
    reviewer_id: str,
    reviewer_session_id: str,
    decision: str,
    rationale: str,
) -> dict[str, str]:
    candidate = json.loads(
        (workspace / candidate_ref["path"]).read_text(encoding="utf-8")
    )
    reviewer = {
        "reviewer_id": reviewer_id,
        "reviewer_session_id": reviewer_session_id,
        "runtime_instance_id": f"runtime_{reviewer_session_id}",
        "independence_class": "runtime_attested_independent_review",
    }
    public_reviewer = {
        "reviewer_id": reviewer_id,
        "reviewer_session_id": reviewer_session_id,
        "independence_class": "host_attested_independent_review",
    }
    outcome_ref = {
        "event_id": outcome["event_id"],
        "sha256": outcome["event_sha256"],
    }
    material = load_candidate_review_material(
        workspace=workspace,
        candidate_relative=candidate_ref["path"],
        root=state_root / "researcher-memory",
        installation_id=INSTALLATION_ID,
        outcome_event_id=outcome["event_id"],
        repo_root=REPO_ROOT,
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
    output_bytes = (
        json.dumps(review_output, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
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
    adapter_receipt = trust_store.sign(
        "runtime_adapter",
        {
            "receipt_type": "COMPLETED",
            "identity": {
                **dict(candidate["identity"]),
                "runtime_id": f"runtime_memory_review_{reviewer_session_id}",
                "task_id": f"memory_review_{reviewer_session_id}",
                "role_id": "researcher_memory_reviewer",
                "attempt_id": f"attempt_memory_review_{reviewer_session_id}",
                "attempt_no": 1,
            },
            "session": {
                "session_uid": reviewer_session_id,
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
                "private_output_sha256": output_sha256,
                "private_output_size_bytes": len(output_bytes),
            },
        },
    )
    receipt = trust_store.sign(
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
                "review_output_sha256": output_sha256,
                "model_execution": {
                    "provider": "smoke",
                    "model": "contract-fixture",
                    "transport": "smoke_disposable_container",
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
    receipt_root = state_root / "reviewer-session-receipts"
    receipt_root.mkdir(mode=0o700, exist_ok=True)
    receipt_root.chmod(0o700)
    path = receipt_root / f"{receipt['receipt_id']}.json"
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return {
        "id": path.relative_to(state_root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def run_smoke(root: Path) -> dict:
    factorforge_root = root / "factorforge"
    workspace = (
        factorforge_root
        / "factor_research"
        / "MEMORY_SMOKE_FACTOR"
        / "memory_smoke_research"
    )
    memory_root = root / "host-private" / "researcher-memory"
    trust_store = ensure_runtime_trust_store(
        memory_root.parent / "research-org-trust",
        installation_id=INSTALLATION_ID,
    )
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=factorforge_root,
        factor_id="MEMORY_SMOKE_FACTOR",
        research_id="memory_smoke_research",
        root_report_id="MEMORY_SMOKE_REPORT",
        implementation_mode="hybrid",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    identity_root = workspace / "identity"
    for name in (
        "web_research_request.json",
        "web_research_authoring_contract.json",
        "factor_knowledge_summary.json",
        "data_catalog_summary.json",
    ):
        (identity_root / name).write_text("{}\n", encoding="utf-8")

    try:
        ensure_researcher_memory_store(
            workspace / "invalid-memory-root",
            installation_id=INSTALLATION_ID,
            repo_root=REPO_ROOT,
            workspace=workspace,
        )
    except ResearchOrganizationError as exc:
        if exc.token != BLOCK_MEMORY_ROOT_INVALID:
            raise
    else:
        raise AssertionError("workspace-overlapping memory root was accepted")

    write_research_organization_bundle(
        workspace=workspace,
        request={
            "job_id": "job_memory_smoke",
            "factor_id": "MEMORY_SMOKE_FACTOR",
            "research_id": "memory_smoke_research",
            "report_id": "MEMORY_SMOKE_REPORT",
            "title": "Liquidity pressure falsification",
            "hypothesis": (
                "Forced liquidity demand transfers value from constrained "
                "sellers to patient buyers and reverses after pressure decays."
            ),
            "input_kind": "hypothesis",
        },
        researcher_memory_root=memory_root,
        researcher_memory_installation_id=INSTALLATION_ID,
    )
    plan = load_research_organization_plan(workspace)
    task = _task_for_role(workspace, "price_volume_researcher")
    evidence_relative = "reports/researcher_memory_smoke_evidence.json"
    evidence_path = workspace / evidence_relative
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text('{"ablation":"pressure_state_removed"}\n', encoding="utf-8")
    evidence_ref = {
        "path": evidence_relative,
        "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
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
            "session_id": "memory_smoke_source_session",
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
                "domain_fit": {
                    "fit": "primary",
                    "reason": "The mechanism is a price-volume pressure state.",
                },
                "public_research_record": {
                    "public_derivation_summary": [
                        "Define a pressure-state estimand and reject it when the "
                        "signal survives measured state decay."
                    ]
                },
                "math_model_search": {
                    "candidates": ["primary", "alternative", "null"]
                },
                "measurement_proposal": {"implementation_route": "direct_code"},
                "knowledge_use": [],
                "data_dependencies": [],
                "falsification_plan": {
                    "distinguishing_tests": ["pressure-state decay ablation"]
                },
                "uncertainties": [],
                "artifact_refs": [evidence_ref],
                "handoff": {"status": "ready_for_host_review"},
            },
        },
        hash_field="result_sha256",
    )
    write_workspace_json_once(workspace, task["expected_result_path"], result)
    candidate_ref = materialize_learning_candidates(
        workspace=workspace,
        task=task,
        result=result,
        proposals=[
            {
                "memory_kind": "falsification_pattern",
                "title": "Pressure-decay ablation",
                "lesson": (
                    "Reject a forced-liquidity mechanism when the signal remains "
                    "unchanged after the measured pressure state has decayed."
                ),
                "applicability_conditions": [
                    "The estimand explicitly represents forced liquidity demand."
                ],
                "failure_conditions": [
                    "Pressure-state ablation leaves the signal unchanged."
                ],
                "evidence_refs": [evidence_ref],
            }
        ],
        runtime_provenance=_source_runtime_provenance(
            trust_store=trust_store,
            plan=plan,
            task=task,
            result=result,
        ),
        trust_store=trust_store,
    )["candidate_refs"][0]
    candidate = json.loads(
        (workspace / candidate_ref["path"]).read_text(encoding="utf-8")
    )
    if validate_memory_candidate(candidate, task=task, result=result):
        raise AssertionError("candidate validation failed")

    roles = list(plan["role_plan"]["required_roles"])
    outcome = record_research_outcome(
        memory_root,
        installation_id=INSTALLATION_ID,
        store_id=plan["researcher_memory"]["store_id"],
        identity=task["identity"],
        role_ids=roles,
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="REJECT",
        council_status="PASS",
        formal_proof_eligible=True,
        organization_runtime_verified=True,
        host_attestation_ref=_host_attestation_ref(
            state_root=memory_root.parent,
            task=task,
            roles=roles,
        ),
        model_execution={
            "provider": "smoke",
            "model": "contract-fixture",
            "provenance": "host_pinned_agent_runtime",
        },
        repo_root=REPO_ROOT,
        workspace=workspace,
    )
    self_review_rationale = "This self-review must be rejected."
    try:
        record_candidate_review(
            workspace=workspace,
            candidate_relative=candidate_ref["path"],
            root=memory_root,
            installation_id=INSTALLATION_ID,
            decision="APPROVE_CANONICAL",
            reviewer_session_receipt_ref=_review_session_receipt_ref(
                state_root=memory_root.parent,
                trust_store=trust_store,
                workspace=workspace,
                candidate_ref=candidate_ref,
                outcome=outcome,
                reviewer_id="self_reviewer",
                reviewer_session_id=result["session_id"],
                decision="APPROVE_CANONICAL",
                rationale=self_review_rationale,
            ),
            outcome_event_id=outcome["event_id"],
            rationale=self_review_rationale,
            repo_root=REPO_ROOT,
        )
    except ResearchOrganizationError as exc:
        if exc.token != BLOCK_MEMORY_REVIEW_INVALID:
            raise
    else:
        raise AssertionError("candidate source session reviewed itself")

    review_rationale = (
        "The rejected factor still provides a reusable falsification test."
    )
    review = record_candidate_review(
        workspace=workspace,
        candidate_relative=candidate_ref["path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        decision="APPROVE_CANONICAL",
        reviewer_session_receipt_ref=_review_session_receipt_ref(
            state_root=memory_root.parent,
            trust_store=trust_store,
            workspace=workspace,
            candidate_ref=candidate_ref,
            outcome=outcome,
            reviewer_id="independent_memory_reviewer",
            reviewer_session_id="memory_smoke_review_session",
            decision="APPROVE_CANONICAL",
            rationale=review_rationale,
        ),
        outcome_event_id=outcome["event_id"],
        rationale=review_rationale,
        repo_root=REPO_ROOT,
    )
    promotion = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=REPO_ROOT,
    )
    repeated = promote_reviewed_candidate(
        workspace=workspace,
        review_relative=review["workspace_path"],
        root=memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=REPO_ROOT,
    )
    validation = validate_researcher_memory_store(
        memory_root,
        installation_id=INSTALLATION_ID,
        repo_root=REPO_ROOT,
        workspace=workspace,
    )
    if not repeated["idempotent"] or validation["canonical_record_count"] != 1:
        raise AssertionError("promotion idempotency or store count failed")
    return {
        "verdict": "PASS",
        "store_id": validation["store_id"],
        "generation": validation["generation"],
        "candidate_id": candidate["candidate_id"],
        "review_id": review["review_id"],
        "memory_id": promotion["memory_id"],
        "source_factor_verdict": "REJECT",
        "interpretation_guard": "protocol PASS is not factor ACCEPT",
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="factorforge-researcher-memory-") as raw:
        result = run_smoke(Path(raw).resolve(strict=True))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    print("FACTORFORGE_RESEARCHER_MEMORY_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
