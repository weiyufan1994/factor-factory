#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.research_org import (
    AGENT_RESULT_CONTRACT_VERSION,
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
    admit_agent_result,
    load_research_organization_plan,
    run_research_organization_runtime,
    validate_research_organization_runtime,
    write_research_organization_bundle,
)
from factor_factory.research_org.contracts import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    with_content_hash,
)
from factor_factory.research_org.director import (
    DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
    PREFORMAL_CLAIM_SCOPE,
    PREFORMAL_CLEAR_DECISION,
    PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
    PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION,
    PREFORMAL_EXECUTIVE_SUMMARIES,
    PREFORMAL_FALSIFIER_CODES,
    PREFORMAL_FINDING_CODES,
    PREFORMAL_ROLE_CHECK_IDS,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)
from scripts.run_factorforge_ultimate import (
    resolve_research_organization_runtime_gate,
)

REPORT_ID = "ORG_RUNTIME_SMOKE_REPORT"


def public_record(
    task: dict[str, Any],
    *,
    evidence_ref: dict[str, str] | None = None,
) -> dict[str, Any]:
    role_id = str(task["role_id"])
    if role_id == "data_liaison":
        return {
            "contract_version": task["output_contract"],
            "identity": {
                "task_id": task["task_id"],
                "factor_id": task["identity"]["factor_id"],
                "research_id": task["identity"]["research_id"],
                "report_id": task["identity"]["report_id"],
                "agent_role": role_id,
            },
            "domain": "data_liaison",
            "proposal_status": "ready_for_director_review",
            "domain_fit": {"fit": "interface", "reason": "Catalog resolved."},
            "catalog_resolution": {"reuse_hits": [], "generated_data_requests": []},
            "delivery_receipt_verification": {"status": "not_required"},
            "knowledge_use": [],
            "permissions_boundary": {"data_materialization": False},
            "uncertainties": [],
            "handoff": {"status": "ready_for_host_review"},
        }
    if task["output_contract"] == "factorforge_domain_research_proposal_v1":
        return {
            "contract_version": task["output_contract"],
            "identity": {
                "task_id": task["task_id"],
                "factor_id": task["identity"]["factor_id"],
                "research_id": task["identity"]["research_id"],
                "report_id": task["identity"]["report_id"],
                "agent_role": role_id,
            },
            "domain": "price_volume",
            "proposal_status": "ready_for_director_review",
            "domain_fit": {"fit": "primary", "reason": "Smoke contract route."},
            "public_research_record": {
                "public_derivation_summary": [
                    "Contract smoke defines an object, projection, and falsifier."
                ]
            },
            "math_model_search": {"candidates": ["primary", "alternative", "null"]},
            "measurement_proposal": {"implementation_route": "direct_code"},
            "knowledge_use": [],
            "data_dependencies": [],
            "falsification_plan": {"distinguishing_tests": ["null test"]},
            "uncertainties": [],
            "artifact_refs": [],
            "handoff": {"status": "ready_for_host_review"},
        }
    record = {
        "contract_version": task["output_contract"],
        "executive_summary": f"Contract-smoke result from {role_id}.",
        "claims": [
            {
                "claim_type": "DESIGN_REQUIREMENT",
                "statement": "The role-specific contract was evaluated.",
                "falsifier": "A bound artifact contradicts the claim.",
                "evidence_refs": [],
            }
        ],
        "artifact_refs": [],
        "handoff": {"status": "ready_for_host_review"},
    }
    if role_id in PREFORMAL_ROLE_CHECK_IDS:
        evidence_refs = [evidence_ref["path"]] if evidence_ref else []
        checks = [
            {
                "check_id": check_id,
                "claim_type": "DESIGN_REQUIREMENT",
                "status": "PASS",
                "finding_code": PREFORMAL_FINDING_CODES["PASS"],
                "falsifier_code": PREFORMAL_FALSIFIER_CODES[check_id],
                "evidence_refs": evidence_refs,
            }
            for check_id in PREFORMAL_ROLE_CHECK_IDS[role_id]
        ]
        record["executive_summary"] = PREFORMAL_EXECUTIVE_SUMMARIES[
            PREFORMAL_CLEAR_DECISION
        ]
        record["claims"] = [dict(check) for check in checks]
        record["artifact_refs"] = [dict(evidence_ref)] if evidence_ref else []
        record["design_review"] = {
            "contract_version": PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION,
            "stage": "pre_formal_research_design",
            "evidence_basis": "pre_registered_design_only",
            "claim_scope": PREFORMAL_CLAIM_SCOPE,
            "empirical_factor_verdict": "NOT_ISSUED",
            "decision": PREFORMAL_CLEAR_DECISION,
            "checks": checks,
            "blockers": [],
        }
    return record


class SignedContractSmokeRunner:
    def __init__(
        self,
        *,
        trust_root: Path,
        installation_id: str,
    ) -> None:
        self.trust_store = ensure_runtime_trust_store(
            trust_root,
            installation_id=installation_id,
        )
        self.installation_id = installation_id
        self.adapter_build_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def run_research_org_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> ResearchOrgSessionOutcome:
        task_path = (
            invocation.context_root
            / f"objects/research_organization/{REPORT_ID}/tasks/{invocation.task_id}.json"
        )
        task = json.loads(task_path.read_text(encoding="utf-8"))
        task_relative = task_path.relative_to(invocation.context_root).as_posix()
        evidence_ref = {
            "path": task_relative,
            "sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
        }
        private_output: dict[str, Any] = {
            "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
            "status": "PASS",
            "public_research_record": public_record(
                task,
                evidence_ref=evidence_ref,
            ),
        }
        if invocation.role_id == "independent_council":
            private_output["independence_attestation"] = {
                "independence_satisfied": True,
                "reviewed_role_ids": task["required_review_role_ids"],
            }
            private_output["formal_independent_verdict"] = {
                "contract_version": PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
                "stage": "pre_formal_research_design",
                "claim_scope": PREFORMAL_CLAIM_SCOPE,
                "decision": PREFORMAL_CLEAR_DECISION,
                "reviewed_role_ids": task["required_review_role_ids"],
                "blocking_findings": [],
                "empirical_factor_verdict": "NOT_ISSUED",
            }
        output_bytes = json.dumps(
            private_output,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        invocation.private_output_path.write_bytes(output_bytes)
        started_at = "2026-08-08T00:00:00Z"
        finished_at = "2026-08-08T00:00:01Z"
        provider_handle = hashlib.sha256(
            f"contract-smoke:{invocation.session_id}".encode()
        ).hexdigest()
        receipt = self.trust_store.sign(
            "runtime_adapter",
            {
                "receipt_type": "COMPLETED",
                "identity": {
                    **invocation.identity,
                    "runtime_id": invocation.runtime_id,
                    "task_id": invocation.task_id,
                    "role_id": invocation.role_id,
                    "attempt_id": invocation.attempt_id,
                    "attempt_no": invocation.attempt_number,
                },
                "ordering": {
                    "scheduler_epoch": invocation.scheduler_epoch,
                    "dispatch_event_seq": invocation.dispatch_event_seq,
                    "issued_at_utc": finished_at,
                    "started_at_utc": started_at,
                    "finished_at_utc": finished_at,
                },
                "bindings": {
                    "plan_sha256": invocation.plan_sha256,
                    "task_sha256": invocation.task_sha256,
                    "context_manifest_sha256": invocation.context_manifest_sha256,
                    "dependency_admissions": [
                        dict(item) for item in invocation.dependency_admissions
                    ],
                    "idempotency_key": invocation.idempotency_key,
                    "adapter_challenge": invocation.adapter_challenge,
                },
                "session": {
                    "session_uid": invocation.session_id,
                    "runtime_handle_sha256": hashlib.sha256(
                        invocation.runtime_instance_id.encode("utf-8")
                    ).hexdigest(),
                    "provider_handle_sha256": provider_handle,
                    "adapter_id": self.installation_id,
                    "adapter_build_sha256": self.adapter_build_sha256,
                    "container_image_digest": f"sha256:{'a' * 64}",
                    "isolation_profile_sha256": "b" * 64,
                    "parent_session_uid": invocation.parent_session_uid,
                    "lease_epoch": invocation.scheduler_epoch,
                },
                "outcome": {
                    "returncode": 0,
                    "cancelled": False,
                    "error_class": None,
                    "private_output_sha256": hashlib.sha256(output_bytes).hexdigest(),
                    "private_output_size_bytes": len(output_bytes),
                    "termination_confirmed": True,
                },
            },
        )
        return ResearchOrgSessionOutcome(
            returncode=0,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            provider="contract-smoke",
            model="contract-smoke",
            transport="contract_smoke_signed_adapter",
            isolation_class="container_staged_context",
            owned_termination_supported=True,
            provider_session_handle_sha256=provider_handle,
            adapter_receipt=receipt,
        )

    def cancel_research_org_session(self, runtime_instance_id: str) -> bool:
        return bool(runtime_instance_id)


def main() -> int:
    root = Path("/tmp/factorforge_research_org_runtime_smoke")
    if not str(root).startswith("/tmp/"):
        raise SystemExit("refusing non-/tmp smoke root")
    shutil.rmtree(root, ignore_errors=True)
    runtime_root = root / "runtime"
    workspace = (
        runtime_root
        / "factor_research"
        / "ORG_RUNTIME_SMOKE"
        / "org_runtime_smoke"
    )
    manifest = build_workspace_manifest(
        repo_root=REPO_ROOT,
        factorforge_root=runtime_root,
        factor_id="ORG_RUNTIME_SMOKE",
        research_id="org_runtime_smoke",
        root_report_id=REPORT_ID,
        implementation_mode="hybrid",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    identity = workspace / "identity"
    request = {
        "job_id": "job_org_runtime_smoke",
        "factor_id": "ORG_RUNTIME_SMOKE",
        "research_id": "org_runtime_smoke",
        "report_id": REPORT_ID,
        "title": "Signed research organization contract smoke",
        "hypothesis": (
            "Abnormally high signed price-volume pressure reflects constrained "
            "liquidity and predicts reversal in next-day stock returns."
        ),
        "input_kind": "hypothesis",
    }
    for name, payload in (
        ("web_research_request.json", request),
        ("web_research_authoring_contract.json", {"status": "contract_smoke"}),
        ("factor_knowledge_summary.json", {"cold_start": True}),
        ("data_catalog_summary.json", {"datasets": []}),
    ):
        (identity / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    write_research_organization_bundle(workspace=workspace, request=request)
    private_root = root / "host-private"
    trust_root = root / "trust"
    installation_id = "org-runtime-smoke-001"
    runner = SignedContractSmokeRunner(
        trust_root=trust_root,
        installation_id=installation_id,
    )
    first = run_research_organization_runtime(
        workspace=workspace,
        worktree=REPO_ROOT,
        private_root=private_root,
        runner=runner,
        trust_root=trust_root,
        installation_id=installation_id,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    if first["lifecycle"] != "WAITING_HOST_RESULT":
        raise AssertionError(f"unexpected first lifecycle: {first}")
    plan = load_research_organization_plan(workspace)
    director_task_path = next(
        path
        for path in (
            workspace / f"objects/research_organization/{REPORT_ID}/tasks"
        ).glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["role_id"]
        == "research_director"
    )
    director_task = json.loads(director_task_path.read_text(encoding="utf-8"))
    reviewed_results = []
    for role_id in director_task["depends_on_roles"]:
        result_path = (
            workspace
            / f"objects/research_organization/{REPORT_ID}/results/{role_id}.json"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        reviewed_results.append(
            {
                "role_id": role_id,
                "path": result_path.relative_to(workspace).as_posix(),
                "result_sha256": result["result_sha256"],
            }
        )
    source_relative = "identity/web_research_director_record.json"
    source_path = workspace / source_relative
    source_path.write_text(
        json.dumps(
            {
                "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
                "reviewed_specialist_results": reviewed_results,
                "mechanism_decision": "Retain constrained-liquidity reversal.",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    source_ref = {
        "path": source_relative,
        "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }
    director_record = public_record(director_task)
    director_record["artifact_refs"] = [source_ref]
    director_record["director_synthesis"] = {
        "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
        "stage": "pre_formal_research_design",
        "mechanism_decision": "Retain constrained-liquidity reversal.",
        "selected_measurement_object": "Signed pressure followed by reversal.",
        "rejected_alternatives": ["Unconditional momentum."],
        "unresolved_risks": ["Auction confounding."],
        "falsifiers": ["Pressure predicts continuation after timing controls."],
        "reviewed_specialist_results": reviewed_results,
        "source_record_ref": source_ref,
        "handoff_status": "ready_for_specialist_verification",
    }
    director_result = with_content_hash(
        {
            "contract_version": AGENT_RESULT_CONTRACT_VERSION,
            "task_ref": {
                "task_id": director_task["task_id"],
                "sha256": director_task["task_sha256"],
            },
            "identity": dict(plan["identity"]),
            "role_id": "research_director",
            "status": "PASS",
            "producer_mode": "real_agent",
            "session_id": "host_research_director_contract_smoke",
            "public_research_record": director_record,
        },
        hash_field="result_sha256",
    )
    admit_agent_result(
        workspace=workspace,
        result=director_result,
        role_id="research_director",
    )
    completed = run_research_organization_runtime(
        workspace=workspace,
        worktree=REPO_ROOT,
        private_root=private_root,
        runner=runner,
        trust_root=trust_root,
        installation_id=installation_id,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    validated = validate_research_organization_runtime(
        workspace=workspace,
        require_complete=True,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        require_formal=True,
    )
    gate = resolve_research_organization_runtime_gate(
        args=argparse.Namespace(
            research_org_runtime_mode="formal-complete",
            research_org_runtime_private_root=str(private_root),
            research_org_runtime_trust_root=str(trust_root),
            research_org_runtime_installation_id=installation_id,
        ),
        factor_workspace=workspace,
    )
    if not (
        completed["lifecycle"] == "COMPLETE"
        and validated["formal_independence_verified"] is True
        and gate["formal_independence_verified"] is True
    ):
        raise AssertionError("signed runtime contract did not close")
    print(
        json.dumps(
            {
                "verdict": "PASS",
                "contract_smoke_only": True,
                "production_research_proof": False,
                "runtime_id": completed["runtime_id"],
                "session_count": completed["session_count"],
                "receipt_count": completed["receipt_count"],
                "runtime_assurance": completed["runtime_assurance"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    print("FACTORFORGE_RESEARCH_ORG_RUNTIME_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
