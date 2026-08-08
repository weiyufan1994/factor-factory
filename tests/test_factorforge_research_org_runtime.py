from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest

import factor_factory.research_org.director as director_module
import factor_factory.research_org.runtime as runtime_module
from factor_factory.research_org import (
    AGENT_RESULT_CONTRACT_VERSION,
    ResearchOrganizationError,
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
    admit_agent_result,
    load_research_organization_plan,
    request_research_organization_cancel,
    run_research_organization_runtime,
    validate_research_organization_runtime,
    write_research_organization_bundle,
)
from factor_factory.research_org.contracts import (
    BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    with_content_hash,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
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
from factor_factory.research_workspace import (
    build_workspace_manifest,
    write_workspace_manifest,
)
from scripts.run_factorforge_ultimate import (
    resolve_research_organization_runtime_gate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path: Path) -> Path:
    runtime = tmp_path / "factorforge"
    workspace = runtime / "factor_research" / "RUNTIME_FACTOR" / "runtime_research"
    manifest = build_workspace_manifest(
        repo_root=PROJECT_ROOT,
        factorforge_root=runtime,
        factor_id="RUNTIME_FACTOR",
        research_id="runtime_research",
        root_report_id="RUNTIME_REPORT",
        implementation_mode="hybrid",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    identity = workspace / "identity"
    (identity / "web_research_request.json").write_text("{}\n", encoding="utf-8")
    (identity / "web_research_authoring_contract.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (identity / "factor_knowledge_summary.json").write_text("{}\n", encoding="utf-8")
    (identity / "data_catalog_summary.json").write_text("{}\n", encoding="utf-8")
    write_research_organization_bundle(
        workspace=workspace,
        request={
            "job_id": "job_runtime_001",
            "factor_id": "RUNTIME_FACTOR",
            "research_id": "runtime_research",
            "report_id": "RUNTIME_REPORT",
            "title": "Intraday pressure",
            "hypothesis": (
                "Minute price-volume imbalance and order-flow pressure reveal a "
                "liquidity-constrained reversal mechanism."
            ),
            "input_kind": "hypothesis",
            "conversation_snapshot": {
                "messages": [
                    {
                        "sequence_no": 1,
                        "role": "user",
                        "content_kind": "hypothesis",
                        "content": "Minute price-volume imbalance reveals liquidity pressure.",
                    }
                ]
            },
        },
    )
    return workspace


def _task(workspace: Path, role_id: str) -> dict:
    plan = load_research_organization_plan(workspace)
    dispatch = json.loads(
        (workspace / plan["workspace_policy"]["dispatch_manifest_path"]).read_text(
            encoding="utf-8"
        )
    )
    reference = next(item for item in dispatch["tasks"] if item["role_id"] == role_id)
    return json.loads((workspace / reference["path"]).read_text(encoding="utf-8"))


def _domain_record(task: dict) -> dict:
    role_id = task["role_id"]
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
            "domain_fit": {"fit": "interface", "reason": "Catalog snapshot resolved."},
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
            "domain_fit": {"fit": "primary", "reason": "Mechanism aligned."},
            "public_research_record": {
                "public_derivation_summary": ["Define object, projection, and falsifier."]
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
        "executive_summary": f"Public result from {role_id}.",
        "claims": [
            {
                "claim_type": "DESIGN_REQUIREMENT",
                "statement": "The role-specific obligation was evaluated.",
                "falsifier": "The bound evidence contradicts the claim.",
                "evidence_refs": [],
            }
        ],
        "artifact_refs": [],
        "handoff": {"status": "ready_for_host_review"},
    }
    if role_id in PREFORMAL_ROLE_CHECK_IDS:
        checks = [
            {
                "check_id": check_id,
                "claim_type": "DESIGN_REQUIREMENT",
                "status": "PASS",
                "finding_code": PREFORMAL_FINDING_CODES["PASS"],
                "falsifier_code": PREFORMAL_FALSIFIER_CODES[check_id],
                "evidence_refs": [],
            }
            for check_id in PREFORMAL_ROLE_CHECK_IDS[role_id]
        ]
        record["executive_summary"] = PREFORMAL_EXECUTIVE_SUMMARIES[
            PREFORMAL_CLEAR_DECISION
        ]
        record["claims"] = [dict(check) for check in checks]
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


def _private_output(task: dict) -> dict:
    payload = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": _domain_record(task),
    }
    if task["role_id"] == "independent_council":
        payload["independence_attestation"] = {
            "independence_satisfied": True,
            "reviewed_role_ids": task["required_review_role_ids"],
        }
        payload["formal_independent_verdict"] = {
            "contract_version": PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
            "stage": "pre_formal_research_design",
            "claim_scope": PREFORMAL_CLAIM_SCOPE,
            "decision": PREFORMAL_CLEAR_DECISION,
            "reviewed_role_ids": task["required_review_role_ids"],
            "blocking_findings": [],
            "empirical_factor_verdict": "NOT_ISSUED",
        }
    return payload


class FakeSessionRunner:
    def __init__(
        self,
        workspace: Path,
        *,
        fail_once_roles: set[str] | None = None,
        cancel_on_role: str | None = None,
        cancel_after_output_role: str | None = None,
        mutate_context_on_role: str | None = None,
        hardlink_output_role: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.fail_once_roles = set(fail_once_roles or set())
        self.cancel_on_role = cancel_on_role
        self.cancel_after_output_role = cancel_after_output_role
        self.mutate_context_on_role = mutate_context_on_role
        self.hardlink_output_role = hardlink_output_role
        self.calls: list[ResearchOrgSessionInvocation] = []
        self.cancelled_instances: list[str] = []
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def run_research_org_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> ResearchOrgSessionOutcome:
        with self._lock:
            self.calls.append(invocation)
            count = self._counts.get(invocation.role_id, 0) + 1
            self._counts[invocation.role_id] = count
        task = json.loads(
            (
                invocation.context_root
                / f"objects/research_organization/RUNTIME_REPORT/tasks/{invocation.task_id}.json"
            ).read_text(encoding="utf-8")
        )
        if self.cancel_on_role == invocation.role_id:
            request_research_organization_cancel(
                workspace=self.workspace,
                requested_by="test",
                reason="bounded cancellation test",
            )
            return self._outcome(invocation, returncode=130, cancelled=True)
        if self.mutate_context_on_role == invocation.role_id and count == 1:
            source = next(
                path
                for path in invocation.context_root.rglob("*.json")
                if path.name != "runtime_context.json"
            )
            source.chmod(0o600)
            source.write_text("{}\n", encoding="utf-8")
        if invocation.role_id in self.fail_once_roles and count == 1:
            return self._outcome(invocation, returncode=1)
        invocation.private_output_path.write_text(
            json.dumps(_private_output(task), ensure_ascii=False),
            encoding="utf-8",
        )
        if self.hardlink_output_role == invocation.role_id:
            os.link(
                invocation.private_output_path,
                invocation.private_output_path.with_name("agent_result_alias.json"),
            )
        if self.cancel_after_output_role == invocation.role_id:
            request_research_organization_cancel(
                workspace=self.workspace,
                requested_by="test",
                reason="cancel immediately before Host admission",
            )
        return self._outcome(invocation, returncode=0)

    def cancel_research_org_session(self, runtime_instance_id: str) -> bool:
        self.cancelled_instances.append(runtime_instance_id)
        return True

    @staticmethod
    def _outcome(
        invocation: ResearchOrgSessionInvocation,
        *,
        returncode: int,
        cancelled: bool = False,
    ) -> ResearchOrgSessionOutcome:
        return ResearchOrgSessionOutcome(
            returncode=returncode,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc="2026-08-08T00:00:00Z",
            finished_at_utc="2026-08-08T00:00:01Z",
            provider="test",
            model="test-model",
            transport="test_isolated_session",
            isolation_class="container_staged_context",
            owned_termination_supported=True,
            cancelled=cancelled,
        )


class SignedFakeSessionRunner(FakeSessionRunner):
    def __init__(
        self,
        workspace: Path,
        *,
        trust_root: Path,
        installation_id: str,
        tamper_signature: bool = False,
        fixed_provider_handle_sha256: str | None = None,
        container_image_digest: str | None = None,
    ) -> None:
        super().__init__(workspace)
        self.trust_store = ensure_runtime_trust_store(
            trust_root,
            installation_id=installation_id,
        )
        self.installation_id = installation_id
        self.tamper_signature = tamper_signature
        self.fixed_provider_handle_sha256 = fixed_provider_handle_sha256
        self.container_image_digest = container_image_digest or f"sha256:{'b' * 64}"

    def run_research_org_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> ResearchOrgSessionOutcome:
        outcome = super().run_research_org_session(invocation)
        output_bytes = invocation.private_output_path.read_bytes()
        provider_handle = self.fixed_provider_handle_sha256 or hashlib.sha256(
            f"signed-provider:{invocation.session_id}".encode()
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
                    "issued_at_utc": outcome.finished_at_utc,
                    "started_at_utc": outcome.started_at_utc,
                    "finished_at_utc": outcome.finished_at_utc,
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
                    "adapter_build_sha256": "a" * 64,
                    "container_image_digest": self.container_image_digest,
                    "isolation_profile_sha256": "c" * 64,
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
        if self.tamper_signature:
            receipt["bindings"]["task_sha256"] = "0" * 64
        return ResearchOrgSessionOutcome(
            returncode=outcome.returncode,
            session_id=outcome.session_id,
            runtime_instance_id=outcome.runtime_instance_id,
            started_at_utc=outcome.started_at_utc,
            finished_at_utc=outcome.finished_at_utc,
            provider=outcome.provider,
            model=outcome.model,
            transport=outcome.transport,
            isolation_class=outcome.isolation_class,
            owned_termination_supported=outcome.owned_termination_supported,
            cancelled=outcome.cancelled,
            stdout_tail=outcome.stdout_tail,
            stderr_tail=outcome.stderr_tail,
            provider_session_handle_sha256=provider_handle,
            adapter_receipt=receipt,
        )


def _admit_host_director(workspace: Path) -> None:
    task = _task(workspace, "research_director")
    record = _domain_record(task)
    reviewed_results = []
    for role_id in task["depends_on_roles"]:
        dependency_task = _task(workspace, role_id)
        result_relative = dependency_task["expected_result_path"]
        dependency_result = json.loads(
            (workspace / result_relative).read_text(encoding="utf-8")
        )
        reviewed_results.append(
            {
                "role_id": role_id,
                "path": result_relative,
                "result_sha256": dependency_result["result_sha256"],
            }
        )
    source_relative = "identity/web_research_director_record.json"
    source_path = workspace / source_relative
    source_path.write_text(
        json.dumps(
            {
                "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
                "reviewed_specialist_results": reviewed_results,
                "mechanism_decision": "Retain the constrained-liquidity reversal mechanism.",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    source_ref = {
        "path": source_relative,
        "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }
    record["artifact_refs"] = [
        source_ref
    ]
    record["director_synthesis"] = {
        "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
        "stage": "pre_formal_research_design",
        "mechanism_decision": "Retain the constrained-liquidity reversal mechanism.",
        "selected_measurement_object": "Signed price-volume pressure followed by reversal.",
        "rejected_alternatives": ["Reject an unconditional momentum interpretation."],
        "unresolved_risks": ["Auction effects may confound the pressure state."],
        "falsifiers": ["The signal predicts continuation after timing controls."],
        "reviewed_specialist_results": reviewed_results,
        "source_record_ref": source_ref,
        "handoff_status": "ready_for_specialist_verification",
    }
    payload = with_content_hash(
        {
            "contract_version": AGENT_RESULT_CONTRACT_VERSION,
            "task_ref": {"task_id": task["task_id"], "sha256": task["task_sha256"]},
            "identity": task["identity"],
            "role_id": task["role_id"],
            "status": "PASS",
            "producer_mode": "real_agent",
            "session_id": "host_research_director_session",
            "public_research_record": record,
        },
        hash_field="result_sha256",
    )
    admit_agent_result(workspace=workspace, result=payload, role_id="research_director")


def test_runtime_dispatches_distinct_sessions_and_resumes_after_host_result(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(workspace)
    first = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    assert first["lifecycle"] == "WAITING_HOST_RESULT"
    assert first["receipt_count"] == 3
    assert first["role_states"]["research_director"] == "WAITING_HOST"
    assert len({call.session_id for call in runner.calls}) == 3

    _admit_host_director(workspace)
    completed = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    assert completed["lifecycle"] == "COMPLETE"
    assert completed["result_count"] == 7
    assert completed["receipt_count"] == 6
    assert completed["session_count"] == 6
    assert completed["runtime_assurance"] == (
        "transactional_runtime_unverified_sessions"
    )
    assert completed["formal_independence_verified"] is False
    for role_id in ("quant_implementation", "validation_evidence", "independent_council"):
        invocation = next(call for call in runner.calls if call.role_id == role_id)
        context_manifest = json.loads(
            (invocation.context_root / "runtime_context.json").read_text(
                encoding="utf-8"
            )
        )
        request_relative = (
            "objects/research_organization/RUNTIME_REPORT/inputs/"
            "web_research_request.json"
        )
        assert request_relative in {
            item["path"] for item in context_manifest["files"]
        }
        assert (invocation.context_root / request_relative).is_file()
        assert (
            invocation.context_root
            / "objects"
            / "research_organization"
            / "RUNTIME_REPORT"
            / "results"
            / "research_director.json"
        ).is_file()
    assert validate_research_organization_runtime(
        workspace=workspace,
        require_complete=True,
    )["verdict"] == "PASS"


def test_host_materializes_liaison_request_and_stages_it_transitively(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    liaison_task = _task(workspace, "data_liaison")
    request_id = "intraday_pressure_state_v1"
    request_relative = (
        "objects/research_organization/RUNTIME_REPORT/data_requests/"
        f"{request_id}.json"
    )
    record = _domain_record(liaison_task)
    record["proposal_status"] = "awaiting_data"
    record["catalog_resolution"]["generated_data_requests"] = [
        {
            "request_id": request_id,
            "path": request_relative,
            "request_payload": {
                "contract_version": "factorforge_data_request_v1",
                "request_id": request_id,
                "request_type": "derived_state",
                "dataset_id": "intraday_pressure_state_v1",
                "required_fields": ["signed_pressure", "liquidity_capacity"],
                "required_coverage": {
                    "start": "2016-01-01",
                    "end": "2025-07-11",
                },
                "parameters": {"bar_frequency": "1min"},
                "lookahead_policy_required": True,
                "qa_required": True,
                "consumer": {
                    "factor_id": liaison_task["identity"]["factor_id"],
                    "research_id": liaison_task["identity"]["research_id"],
                    "report_id": liaison_task["identity"]["report_id"],
                },
                "status": "requested",
                "production_execution_allowed": False,
            },
        }
    ]
    payload = with_content_hash(
        {
            "contract_version": AGENT_RESULT_CONTRACT_VERSION,
            "task_ref": {
                "task_id": liaison_task["task_id"],
                "sha256": liaison_task["task_sha256"],
            },
            "identity": liaison_task["identity"],
            "role_id": "data_liaison",
            "status": "NEEDS_DATA",
            "producer_mode": "real_agent",
            "session_id": "liaison-materialization-session",
            "public_research_record": record,
        },
        hash_field="result_sha256",
    )

    admit_agent_result(workspace=workspace, result=payload, role_id="data_liaison")

    admitted = json.loads(
        (workspace / liaison_task["expected_result_path"]).read_text(
            encoding="utf-8"
        )
    )
    request_ref = admitted["public_research_record"]["catalog_resolution"][
        "generated_data_requests"
    ][0]
    assert set(request_ref) == {"request_id", "path", "sha256"}
    assert request_ref["path"] == request_relative
    assert (workspace / request_relative).is_file()
    tasks_by_role = {
        role_id: _task(workspace, role_id)
        for role_id in (
            "knowledge_librarian",
            "data_liaison",
            "price_volume_researcher",
            "research_director",
            "quant_implementation",
        )
    }
    staged = runtime_module._context_source_paths(
        workspace,
        tasks_by_role["quant_implementation"],
        tasks_by_role,
    )
    assert request_relative in staged


def test_host_admission_rolls_back_result_and_request_on_final_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    liaison_task = _task(workspace, "data_liaison")
    request_id = "atomic_rollback_pressure_state_v1"
    request_relative = (
        "objects/research_organization/RUNTIME_REPORT/data_requests/"
        f"{request_id}.json"
    )
    record = _domain_record(liaison_task)
    record["proposal_status"] = "awaiting_data"
    record["catalog_resolution"]["generated_data_requests"] = [
        {
            "request_id": request_id,
            "path": request_relative,
            "request_payload": {
                "contract_version": "factorforge_data_request_v1",
                "request_id": request_id,
                "request_type": "derived_state",
                "dataset_id": request_id,
                "required_fields": ["signed_pressure"],
                "required_coverage": {"sample": "frozen"},
                "parameters": {},
                "lookahead_policy_required": True,
                "qa_required": True,
                "consumer": {
                    "factor_id": liaison_task["identity"]["factor_id"],
                    "research_id": liaison_task["identity"]["research_id"],
                    "report_id": liaison_task["identity"]["report_id"],
                },
                "status": "requested",
                "production_execution_allowed": False,
            },
        }
    ]
    payload = with_content_hash(
        {
            "contract_version": AGENT_RESULT_CONTRACT_VERSION,
            "task_ref": {
                "task_id": liaison_task["task_id"],
                "sha256": liaison_task["task_sha256"],
            },
            "identity": liaison_task["identity"],
            "role_id": "data_liaison",
            "status": "NEEDS_DATA",
            "producer_mode": "real_agent",
            "session_id": "liaison-atomic-rollback-session",
            "public_research_record": record,
        },
        hash_field="result_sha256",
    )
    original_validate = director_module.validate_research_organization_bundle
    validation_calls = 0

    def fail_final_validation(*args, **kwargs):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 2:
            raise RuntimeError("injected final bundle validation failure")
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(
        director_module,
        "validate_research_organization_bundle",
        fail_final_validation,
    )

    with pytest.raises(RuntimeError, match="injected final bundle validation failure"):
        admit_agent_result(
            workspace=workspace,
            result=payload,
            role_id="data_liaison",
        )

    assert validation_calls == 2
    assert not (workspace / liaison_task["expected_result_path"]).exists()
    assert not (workspace / request_relative).exists()
    assert original_validate(workspace=workspace)["result_count"] == 0


def test_liaison_materialization_rolls_back_when_runtime_ledger_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    request_id = "rollback_pressure_state_v1"
    request_relative = (
        "objects/research_organization/RUNTIME_REPORT/data_requests/"
        f"{request_id}.json"
    )

    class DataRequestRunner(FakeSessionRunner):
        def run_research_org_session(
            self,
            invocation: ResearchOrgSessionInvocation,
        ) -> ResearchOrgSessionOutcome:
            outcome = super().run_research_org_session(invocation)
            if invocation.role_id != "data_liaison":
                return outcome
            task = json.loads(
                (
                    invocation.context_root
                    / "objects/research_organization/RUNTIME_REPORT/tasks"
                    / f"{invocation.task_id}.json"
                ).read_text(encoding="utf-8")
            )
            record = _domain_record(task)
            record["proposal_status"] = "awaiting_data"
            record["catalog_resolution"]["generated_data_requests"] = [
                {
                    "request_id": request_id,
                    "path": request_relative,
                    "request_payload": {
                        "contract_version": "factorforge_data_request_v1",
                        "request_id": request_id,
                        "request_type": "derived_state",
                        "dataset_id": "rollback_pressure_state_v1",
                        "required_fields": ["signed_pressure"],
                        "required_coverage": {"sample": "frozen"},
                        "parameters": {},
                        "lookahead_policy_required": True,
                        "qa_required": True,
                        "consumer": {
                            "factor_id": task["identity"]["factor_id"],
                            "research_id": task["identity"]["research_id"],
                            "report_id": task["identity"]["report_id"],
                        },
                        "status": "requested",
                        "production_execution_allowed": False,
                    },
                }
            ]
            invocation.private_output_path.write_text(
                json.dumps(
                    {
                        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
                        "status": "NEEDS_DATA",
                        "public_research_record": record,
                    }
                ),
                encoding="utf-8",
            )
            return outcome

    original_complete = runtime_module.ResearchOrgRuntimeLedger.complete_attempt

    def fail_liaison_commit(self, *args, canonical_result=None, **kwargs):
        if (
            isinstance(canonical_result, dict)
            and canonical_result.get("role_id") == "data_liaison"
        ):
            raise OSError("injected ledger commit failure")
        return original_complete(
            self,
            *args,
            canonical_result=canonical_result,
            **kwargs,
        )

    monkeypatch.setattr(
        runtime_module.ResearchOrgRuntimeLedger,
        "complete_attempt",
        fail_liaison_commit,
    )
    with pytest.raises(OSError, match="injected ledger commit failure"):
        run_research_organization_runtime(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            private_root=tmp_path / "private-runtime",
            runner=DataRequestRunner(workspace),
            allow_unverified_test_runner=True,
            max_concurrency=1,
            max_attempts=2,
            timeout_seconds=60,
        )

    assert not (workspace / request_relative).exists()


def test_runtime_retries_with_a_distinct_session(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(workspace, fail_once_roles={"knowledge_librarian"})
    summary = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    knowledge_calls = [
        call for call in runner.calls if call.role_id == "knowledge_librarian"
    ]
    assert summary["lifecycle"] == "WAITING_HOST_RESULT"
    assert len(knowledge_calls) == 2
    assert knowledge_calls[0].session_id != knowledge_calls[1].session_id
    assert summary["receipt_count"] == 4


def test_runtime_context_tampering_never_admits_first_attempt(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(
        workspace,
        mutate_context_on_role="price_volume_researcher",
    )
    summary = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    price_calls = [
        call for call in runner.calls if call.role_id == "price_volume_researcher"
    ]
    assert len(price_calls) == 1
    assert summary["role_states"]["price_volume_researcher"] == "RETRY_EXHAUSTED"


def test_private_output_hardlink_is_never_admitted(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(
        workspace,
        hardlink_output_role="knowledge_librarian",
    )
    summary = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=1,
        max_attempts=1,
        timeout_seconds=60,
    )
    task = _task(workspace, "knowledge_librarian")
    assert summary["role_states"]["knowledge_librarian"] == "RETRY_EXHAUSTED"
    assert not (workspace / task["expected_result_path"]).exists()


def test_runtime_cancel_request_stops_remaining_roles(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(workspace, cancel_on_role="knowledge_librarian")
    summary = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=1,
        max_attempts=2,
        timeout_seconds=60,
    )
    assert summary["lifecycle"] == "CANCELLED"
    assert summary["role_states"]["knowledge_librarian"] == "CANCELLED"
    assert len(runner.calls) == 1


def test_cancel_wins_race_before_host_admission(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(
        workspace,
        cancel_after_output_role="knowledge_librarian",
    )
    summary = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=1,
        max_attempts=2,
        timeout_seconds=60,
    )
    task = _task(workspace, "knowledge_librarian")
    assert summary["lifecycle"] == "CANCELLED"
    assert not (workspace / task["expected_result_path"]).exists()


def test_runtime_receipt_tampering_blocks_validation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    runner = FakeSessionRunner(workspace)
    run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    receipt_path = next(
        (
            workspace
            / "objects/research_organization/RUNTIME_REPORT/runtime/attempts"
        ).glob("*/*/session_receipt.json")
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["session_id"] = "forged_session"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
    ):
        validate_research_organization_runtime(workspace=workspace)


def test_signed_runtime_is_required_for_formal_independence(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    installation_id = "signed-runtime-test-001"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    first = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    assert first["formal_independence_verified"] is False

    _admit_host_director(workspace)
    completed = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    assert completed["lifecycle"] == "COMPLETE"
    assert completed["formal_independence_verified"] is True
    assert completed["runtime_assurance"] == (
        "signed_specialist_runtime_complete_host_director_external"
    )
    ultimate_gate = resolve_research_organization_runtime_gate(
        args=argparse.Namespace(
            research_org_runtime_mode="formal-complete",
            research_org_runtime_private_root=str(tmp_path / "private-runtime"),
            research_org_runtime_trust_root=str(trust_root),
            research_org_runtime_installation_id=installation_id,
        ),
        factor_workspace=workspace,
    )
    assert ultimate_gate["status"] == "validated"
    assert ultimate_gate["formal_independence_verified"] is True


def test_non_hex_image_digest_cannot_satisfy_formal_runtime(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    installation_id = "signed-runtime-test-unpinned"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
        container_image_digest=f"sha256:{'z' * 64}",
    )
    run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    _admit_host_director(workspace)
    completed = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=tmp_path / "private-runtime",
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )

    assert completed["lifecycle"] == "COMPLETE"
    assert completed["formal_independence_verified"] is False
    with pytest.raises(
        ResearchOrganizationError,
        match="formal_signed_runtime_not_satisfied",
    ):
        validate_research_organization_runtime(
            workspace=workspace,
            private_root=tmp_path / "private-runtime",
            trust_root=trust_root,
            installation_id=installation_id,
            require_formal=True,
        )


def test_ultimate_if_present_rejects_unsafe_runtime_entry(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plan = load_research_organization_plan(workspace)
    runtime_state = (
        workspace
        / str(plan["workspace_policy"]["organization_root"])
        / "runtime"
        / "runtime_state.json"
    )
    runtime_state.mkdir(parents=True)

    with pytest.raises(
        ResearchOrganizationError,
        match="runtime_state_unsafe",
    ):
        resolve_research_organization_runtime_gate(
            args=argparse.Namespace(
                research_org_runtime_mode="if-present",
                research_org_runtime_private_root=None,
                research_org_runtime_trust_root=None,
                research_org_runtime_installation_id=None,
            ),
            factor_workspace=workspace,
        )


def test_tampered_adapter_signature_blocks_before_admission(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    installation_id = "signed-runtime-test-002"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
        tamper_signature=True,
    )
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
    ):
        run_research_organization_runtime(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            private_root=tmp_path / "private-runtime",
            trust_root=trust_root,
            installation_id=installation_id,
            runner=runner,
            max_concurrency=1,
            max_attempts=2,
            timeout_seconds=60,
        )
    task = _task(workspace, "knowledge_librarian")
    assert not (workspace / task["expected_result_path"]).exists()


def test_signed_runtime_rejects_reused_provider_session_handle(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    installation_id = "signed-runtime-test-reused-provider"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
        fixed_provider_handle_sha256="d" * 64,
    )
    with pytest.raises(
        ResearchOrganizationError,
        match="adapter_session_or_receipt_reused",
    ):
        run_research_organization_runtime(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            private_root=tmp_path / "private-runtime",
            trust_root=trust_root,
            installation_id=installation_id,
            runner=runner,
            max_concurrency=3,
            max_attempts=2,
            timeout_seconds=60,
        )


def test_rehashed_workspace_projection_cannot_override_private_ledger(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    private_root = tmp_path / "private-runtime"
    installation_id = "signed-runtime-test-003"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    receipt_path = next(
        (
            workspace
            / "objects/research_organization/RUNTIME_REPORT/runtime/attempts"
        ).glob("*/*/session_receipt.json")
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["provider"] = "forged-provider"
    receipt = with_content_hash(receipt, hash_field="receipt_sha256")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(
        ResearchOrganizationError,
        match="ledger_projection_hash",
    ):
        validate_research_organization_runtime(
            workspace=workspace,
            private_root=private_root,
            trust_root=trust_root,
            installation_id=installation_id,
        )


def test_private_ledger_receipt_tampering_fails_signature_validation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    private_root = tmp_path / "private-runtime"
    installation_id = "signed-runtime-test-004"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    result = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    _admit_host_director(workspace)
    result = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    ledger_path = private_root / result["runtime_id"] / "runtime_ledger.sqlite3"
    with sqlite3.connect(ledger_path) as connection:
        row = connection.execute(
            """
            SELECT receipt_id, payload_json FROM receipts
            WHERE issuer_kind='runtime_adapter' LIMIT 1
            """
        ).fetchone()
        payload = json.loads(row[1])
        payload["session"]["adapter_build_sha256"] = "0" * 64
        connection.execute(
            "UPDATE receipts SET payload_json=? WHERE receipt_id=?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )
    with pytest.raises(
        ResearchOrganizationError,
        match="signed_receipt",
    ):
        validate_research_organization_runtime(
            workspace=workspace,
            private_root=private_root,
            trust_root=trust_root,
            installation_id=installation_id,
        )


def test_private_ledger_dependency_snapshot_tampering_blocks_validation(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    trust_root = tmp_path / "trust"
    private_root = tmp_path / "private-runtime"
    installation_id = "signed-runtime-test-dependency-binding"
    runner = SignedFakeSessionRunner(
        workspace,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    result = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    _admit_host_director(workspace)
    result = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        runner=runner,
        max_concurrency=3,
        max_attempts=2,
        timeout_seconds=60,
    )
    ledger_path = private_root / result["runtime_id"] / "runtime_ledger.sqlite3"
    with sqlite3.connect(ledger_path) as connection:
        row = connection.execute(
            """
            SELECT attempt_id, dependency_admissions_json FROM attempts
            WHERE dependency_admissions_json <> '[]' LIMIT 1
            """
        ).fetchone()
        dependencies = json.loads(row[1])
        dependencies[0]["result_sha256"] = "0" * 64
        connection.execute(
            "UPDATE attempts SET dependency_admissions_json=? WHERE attempt_id=?",
            (json.dumps(dependencies, sort_keys=True), row[0]),
        )
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
    ):
        validate_research_organization_runtime(
            workspace=workspace,
            private_root=private_root,
            trust_root=trust_root,
            installation_id=installation_id,
        )


def test_private_ledger_hardlink_blocks_validation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    private_root = tmp_path / "private-runtime"
    runner = FakeSessionRunner(workspace)
    result = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=1,
        max_attempts=2,
        timeout_seconds=60,
    )
    ledger_path = private_root / result["runtime_id"] / "runtime_ledger.sqlite3"
    os.link(ledger_path, tmp_path / "ledger-alias.sqlite3")
    with pytest.raises(
        ResearchOrganizationError,
        match="unsafe_private_runtime_ledger",
    ):
        validate_research_organization_runtime(
            workspace=workspace,
            private_root=private_root,
        )


def test_runtime_validation_does_not_recreate_missing_private_ledger(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    private_root = tmp_path / "private-runtime"
    runner = FakeSessionRunner(workspace)
    result = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=1,
        max_attempts=2,
        timeout_seconds=60,
    )
    ledger_path = private_root / result["runtime_id"] / "runtime_ledger.sqlite3"
    ledger_path.unlink()
    with pytest.raises(ResearchOrganizationError, match="host_private_runtime_ledger"):
        validate_research_organization_runtime(
            workspace=workspace,
            private_root=private_root,
        )
    assert not ledger_path.exists()


def test_crash_after_ledger_dispatch_recovers_projection_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _workspace(tmp_path)
    private_root = tmp_path / "private-runtime"
    runner = FakeSessionRunner(workspace)
    original_write_once = runtime_module.write_workspace_json_once
    injected = False

    def fail_before_attempt_projection(
        workspace: Path,
        relative_path: str,
        payload: dict,
    ) -> Path:
        nonlocal injected
        if relative_path.endswith("/context_manifest.json") and not injected:
            injected = True
            raise OSError("injected host crash after ledger dispatch")
        return original_write_once(workspace, relative_path, payload)

    monkeypatch.setattr(
        runtime_module,
        "write_workspace_json_once",
        fail_before_attempt_projection,
    )
    with pytest.raises(OSError, match="injected host crash"):
        run_research_organization_runtime(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            private_root=private_root,
            runner=runner,
            allow_unverified_test_runner=True,
            max_concurrency=1,
            max_attempts=2,
            timeout_seconds=60,
        )
    monkeypatch.setattr(
        runtime_module,
        "write_workspace_json_once",
        original_write_once,
    )
    recovered = run_research_organization_runtime(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        private_root=private_root,
        runner=runner,
        allow_unverified_test_runner=True,
        max_concurrency=1,
        max_attempts=2,
        timeout_seconds=60,
    )
    assert recovered["lifecycle"] == "WAITING_HOST_RESULT"
    assert runner.cancelled_instances
    assert recovered["receipt_count"] == 4
