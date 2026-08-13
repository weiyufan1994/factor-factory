from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from factor_factory.evo_v2 import (
    EXPERIENCE_TRANSFER_BUNDLE_VERSION,
    TRANSFER_USE_RECEIPT_VERSION,
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_relative_paths,
    materialize_evo_v2_bundle,
    sha256_file,
)
from factor_factory.knowledge_context import (
    BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID,
    EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION,
    KnowledgeRetrievalError,
    complete_evo_v2_cold_start_search_session,
    prepare_evo_v2_cold_start_search_session,
    retrieve_evo_v2_memory_projection,
)
from factor_factory.research_org.contracts import (
    ResearchOrganizationError,
    with_content_hash,
)
from factor_factory.research_org.runtime import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
    build_research_org_session_prompt,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.researcher_memory import (
    BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
    build_evo_v2_memory_admission,
    build_evo_v2_transfer_use_change_receipt,
    ensure_researcher_memory_store,
    load_evo_v2_memory_admissions,
    persist_evo_v2_memory_admission,
    validate_evo_v2_memory_admission,
    validate_researcher_memory_store,
)
from factor_factory.researcher_memory_review import (
    EVO_V2_MEMORY_REVIEW_AGENT_RECORD_VERSION,
    EVO_V2_MEMORY_REVIEW_CHECKS,
    build_evo_v2_memory_review_projection,
    complete_evo_v2_memory_review_session,
    prepare_evo_v2_memory_review_session,
)
from tests.test_factorforge_evo_v2 import REPORT_ID, _as_cold_start, _build_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _json_bytes(payload: dict) -> bytes:
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


def _write_json_ref(workspace: Path, relative: str, payload: dict) -> dict:
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))
    return {"path": relative, "sha256": sha256_file(path)}


def _transfer_use_change_receipt(
    *,
    workspace: Path,
    artifacts: dict,
    trust_store: object,
) -> dict:
    uses = artifacts["transfer_use_receipt"]["uses"]
    before_ref = _write_json_ref(
        workspace,
        "support/evo_v2_research_plan_before.json",
        {
            "research_questions": [
                {"question_id": "question_baseline", "text": "Baseline question"}
            ],
            "registered_tests": [
                {"test_id": "test_baseline", "text": "Baseline test"}
            ],
        },
    )
    mapping_uses = []
    added_questions = []
    added_tests = []
    for index, use in enumerate(uses):
        question_id = f"question_{use['mapping_id']}"
        test_id = use["generated_test_id"]
        added_questions.append(
            {"question_id": question_id, "text": f"Question from mapping {index}"}
        )
        added_tests.append(
            {"test_id": test_id, "text": f"Test from mapping {index}"}
        )
        mapping_uses.append(
            {
                "mapping_id": use["mapping_id"],
                "research_effect": use["research_effect"],
                "generated_question_ids": [question_id],
                "generated_test_ids": [test_id],
            }
        )
    after_ref = _write_json_ref(
        workspace,
        "support/evo_v2_research_plan_after.json",
        {
            "research_questions": [
                {"question_id": "question_baseline", "text": "Baseline question"},
                *added_questions,
            ],
            "registered_tests": [
                {"test_id": "test_baseline", "text": "Baseline test"},
                *added_tests,
            ],
        },
    )
    return build_evo_v2_transfer_use_change_receipt(
        workspace=workspace,
        transfer_bundle=artifacts["experience_transfer_bundle"],
        transfer_receipt=artifacts["transfer_use_receipt"],
        before_research_plan_ref=before_ref,
        after_research_plan_ref=after_ref,
        mapping_uses=mapping_uses,
        protected_contracts={
            "skill_sha256": "8" * 64,
            "validator_sha256": "9" * 64,
            "thresholds_sha256": "a" * 64,
            "oos_policy_sha256": "b" * 64,
            "estimand_sha256": "c" * 64,
            "trial_budget_sha256": "d" * 64,
            "unchanged": True,
        },
        trust_store=trust_store,
    )


def _adapter_completion_receipt(
    *,
    trust_store: object,
    artifact_identity: dict,
    role_id: str,
    session_id: str,
    runtime_instance_id: str,
    runtime_id: str,
    task_id: str,
    attempt_id: str,
    plan_sha256: str,
    task_sha256: str,
    context_manifest_sha256: str,
    output_bytes: bytes,
) -> dict:
    return trust_store.sign(
        "runtime_adapter",
        {
            "receipt_type": "COMPLETED",
            "identity": {
                **artifact_identity,
                "runtime_id": runtime_id,
                "task_id": task_id,
                "role_id": role_id,
                "attempt_id": attempt_id,
                "attempt_no": 1,
            },
            "ordering": {
                "scheduler_epoch": 1,
                "dispatch_event_seq": 1,
                "issued_at_utc": "2026-08-12T00:00:02Z",
                "started_at_utc": "2026-08-12T00:00:00Z",
                "finished_at_utc": "2026-08-12T00:00:02Z",
            },
            "bindings": {
                "plan_sha256": plan_sha256,
                "task_sha256": task_sha256,
                "context_manifest_sha256": context_manifest_sha256,
                "dependency_admissions": [],
                "idempotency_key": f"idem_{task_id}",
                "adapter_challenge": f"challenge_{task_id}",
            },
            "session": {
                "session_uid": session_id,
                "runtime_handle_sha256": hashlib.sha256(
                    runtime_instance_id.encode("utf-8")
                ).hexdigest(),
                "provider_handle_sha256": "1" * 64,
                "adapter_id": trust_store.installation_id,
                "adapter_build_sha256": "2" * 64,
                "container_image_digest": "sha256:" + "3" * 64,
                "isolation_profile_sha256": "4" * 64,
                "runtime": {
                    "provider": "deepseek",
                    "model": "deepseek/deepseek-v4-flash",
                    "transport": "openclaw_disposable_container",
                    "isolation_class": "container_staged_context",
                    "owned_termination_supported": True,
                },
                "parent_session_uid": None,
                "lease_epoch": 1,
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


def _completed_review_decision(
    *,
    tmp_path: Path,
    workspace: Path,
    projection: dict,
    artifacts: dict,
    trust_store: object,
) -> dict:
    source_output = b'{"source":"admitted_evo_v2_author"}\n'
    source_receipt = _adapter_completion_receipt(
        trust_store=trust_store,
        artifact_identity=projection["artifact_identity"],
        role_id="knowledge_librarian",
        session_id="session_evo_v2_source_author_001",
        runtime_instance_id="runtime-evo-v2-source-author-001",
        runtime_id="runtime_evo_v2_source_001",
        task_id="task_evo_v2_source_001",
        attempt_id="attempt_evo_v2_source_001",
        plan_sha256="5" * 64,
        task_sha256="6" * 64,
        context_manifest_sha256="7" * 64,
        output_bytes=source_output,
    )
    invocation, request, _review_root = prepare_evo_v2_memory_review_session(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        state_root=tmp_path,
        installation_id=trust_store.installation_id,
        host_job_id="job_123abc4567",
        host_plan_identity={
            "job_id": "job_123abc4567",
            "factor_id": projection["artifact_identity"]["factor_id"],
            "research_id": projection["artifact_identity"]["research_id"],
            "report_id": projection["artifact_identity"]["report_id"],
        },
        projection=projection,
        experience_transfer_bundle=artifacts["experience_transfer_bundle"],
        transfer_use_receipt=artifacts["transfer_use_receipt"],
        source_execution_receipts=[source_receipt],
    )
    cold_start = projection["memory_state"] == "COLD_START_NO_ADMISSIBLE_MEMORY"
    review_output = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        "public_research_record": {
            "contract_version": EVO_V2_MEMORY_REVIEW_AGENT_RECORD_VERSION,
            "artifact_identity": projection["artifact_identity"],
            "reviewer_role_id": "researcher_memory_reviewer",
            "projection_sha256": projection["projection_sha256"],
            "decision": (
                "NOT_REQUIRED_VERIFIED_COLD_START"
                if cold_start
                else "APPROVE_ADVISORY_USE"
            ),
            "rationale": (
                "The zero-hit proof is runtime-bound and review is not required."
                if cold_start
                else "The source lessons are bounded and usable for advisory transfer."
            ),
            "checks": dict(projection["review_checks"]),
            "experience_decisions": [
                {
                    "experience_id": experience_id,
                    "decision": (
                        "APPROVE_CANONICAL_SOURCE_FOR_ADVISORY_TRANSFER"
                    ),
                }
                for experience_id in projection["review_scope_experience_ids"]
            ],
        },
    }
    output_bytes = _json_bytes(review_output)
    invocation.private_output_path.write_bytes(output_bytes)
    adapter_receipt = _adapter_completion_receipt(
        trust_store=trust_store,
        artifact_identity=projection["artifact_identity"],
        role_id=invocation.role_id,
        session_id=invocation.session_id,
        runtime_instance_id=invocation.runtime_instance_id,
        runtime_id=invocation.runtime_id,
        task_id=invocation.task_id,
        attempt_id=invocation.attempt_id,
        plan_sha256=invocation.plan_sha256,
        task_sha256=invocation.task_sha256,
        context_manifest_sha256=invocation.context_manifest_sha256,
        output_bytes=output_bytes,
    )
    outcome = ResearchOrgSessionOutcome(
        returncode=0,
        session_id=invocation.session_id,
        runtime_instance_id=invocation.runtime_instance_id,
        started_at_utc="2026-08-12T00:00:00Z",
        finished_at_utc="2026-08-12T00:00:02Z",
        provider="test-runtime",
        model="test-independent-reviewer",
        transport="test_disposable_container",
        isolation_class="container_staged_context",
        owned_termination_supported=True,
        cancelled=False,
        stdout_tail="",
        stderr_tail="",
        provider_session_handle_sha256="1" * 64,
        adapter_receipt=adapter_receipt,
    )
    decision = complete_evo_v2_memory_review_session(
        invocation=invocation,
        outcome=outcome,
        state_root=tmp_path,
        installation_id=trust_store.installation_id,
    )
    assert decision["runtime_evidence"]["review_request"] == request
    return decision


def test_evo_review_uses_canonical_session_id_and_bound_host_routing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "factor_workspace"
    artifacts = _build_bundle(workspace)
    paths = materialize_evo_v2_bundle(
        artifacts,
        workspace_root=workspace,
        report_id=REPORT_ID,
    )
    relative_paths = evo_v2_relative_paths(REPORT_ID)
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )
    projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=artifacts["experience_transfer_bundle"],
        transfer_use_receipt=artifacts["transfer_use_receipt"],
        experience_transfer_bundle_ref={
            "path": relative_paths["experience_transfer_bundle"],
            "sha256": sha256_file(paths["experience_transfer_bundle"]),
        },
        transfer_use_receipt_ref={
            "path": relative_paths["transfer_use_receipt"],
            "sha256": sha256_file(paths["transfer_use_receipt"]),
        },
        trust_store=trust_store,
        source_workspace=workspace,
    )
    source_receipt = _adapter_completion_receipt(
        trust_store=trust_store,
        artifact_identity=projection["artifact_identity"],
        role_id="knowledge_librarian",
        session_id="session_0123456789abcdef0123456789abcdef",
        runtime_instance_id="fforg-source-author-01234567",
        runtime_id="runtime_evo_v2_source_001",
        task_id="task_evo_v2_source_001",
        attempt_id="attempt_evo_v2_source_001",
        plan_sha256="5" * 64,
        task_sha256="6" * 64,
        context_manifest_sha256="7" * 64,
        output_bytes=b'{"source":"runtime-author"}\n',
    )
    plan_identity = {
        "job_id": "job_123abc4567",
        "factor_id": projection["artifact_identity"]["factor_id"],
        "research_id": projection["artifact_identity"]["research_id"],
        "report_id": projection["artifact_identity"]["report_id"],
    }
    common = {
        "workspace": workspace,
        "worktree": PROJECT_ROOT,
        "state_root": tmp_path,
        "installation_id": trust_store.installation_id,
        "projection": projection,
        "experience_transfer_bundle": artifacts["experience_transfer_bundle"],
        "transfer_use_receipt": artifacts["transfer_use_receipt"],
        "source_execution_receipts": [source_receipt],
    }
    invocation, _request, _review_root = prepare_evo_v2_memory_review_session(
        **common,
        host_job_id=plan_identity["job_id"],
        host_plan_identity=plan_identity,
    )
    assert re.fullmatch(r"session_[a-f0-9]{32}", invocation.session_id)
    assert invocation.host_job_id == plan_identity["job_id"]
    assert "job_id" not in invocation.identity

    with pytest.raises(
        ResearchOrganizationError,
        match="evo_v2_review_host_job_id",
    ):
        prepare_evo_v2_memory_review_session(
            **common,
            host_job_id="",
            host_plan_identity=plan_identity,
        )
    with pytest.raises(
        ResearchOrganizationError,
        match="evo_v2_review_host_job_id",
    ):
        prepare_evo_v2_memory_review_session(
            **common,
            host_job_id=plan_identity["job_id"],
            host_plan_identity={},
        )
    with pytest.raises(
        ResearchOrganizationError,
        match="evo_v2_review_host_job_id",
    ):
        prepare_evo_v2_memory_review_session(
            **common,
            host_job_id=plan_identity["job_id"],
            host_plan_identity={**plan_identity, "branch_id": "main"},
        )
    with pytest.raises(
        ResearchOrganizationError,
        match="evo_v2_review_host_job_id",
    ):
        prepare_evo_v2_memory_review_session(
            **common,
            host_job_id="job_abcdef1234",
            host_plan_identity=plan_identity,
        )
    mismatched_identity = dict(plan_identity)
    mismatched_identity["report_id"] = "OTHER_REPORT"
    with pytest.raises(
        ResearchOrganizationError,
        match="evo_v2_review_host_job_id",
    ):
        prepare_evo_v2_memory_review_session(
            **common,
            host_job_id=plan_identity["job_id"],
            host_plan_identity=mismatched_identity,
        )


def _prepared_cold_start_search(
    *,
    tmp_path: Path,
    workspace: Path,
    transfer: dict,
    trust_store: object,
) -> tuple[ResearchOrgSessionInvocation, dict, Path]:
    role_index_ref = _write_json_ref(
        workspace,
        "support/role_memory_index_snapshot.json",
        {"records": [], "generation": 0},
    )
    role_index_ref["index_id"] = "role_memory"
    factor_index_ref = _write_json_ref(
        workspace,
        "support/factor_knowledge_index_snapshot.json",
        {"nodes": [], "generation": 0},
    )
    factor_index_ref["index_id"] = "factor_knowledge"
    invocation, request, _search_root = prepare_evo_v2_cold_start_search_session(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        state_root=tmp_path,
        installation_id=trust_store.installation_id,
        host_job_id="job_123abc4567",
        artifact_identity=transfer["artifact_identity"],
        mechanism_fingerprint=transfer["mechanism_fingerprint"],
        checked_indexes=[role_index_ref, factor_index_ref],
    )
    return invocation, request, _search_root


def _completed_cold_start_search(
    *,
    tmp_path: Path,
    workspace: Path,
    transfer: dict,
    trust_store: object,
    public_record_key: str = "public_research_record",
    tamper_index_before_completion: bool = False,
    completion_task_sha256: str | None = None,
) -> tuple[dict, dict]:
    invocation, request, _search_root = _prepared_cold_start_search(
        tmp_path=tmp_path,
        workspace=workspace,
        transfer=transfer,
        trust_store=trust_store,
    )
    if tamper_index_before_completion:
        build_research_org_session_prompt(invocation)
    search_output = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS",
        public_record_key: {
            "contract_version": EVO_V2_COLD_START_SEARCH_AGENT_RECORD_VERSION,
            "artifact_identity": transfer["artifact_identity"],
            "executor_role_id": "knowledge_librarian",
            "query_sha256": request["query"]["query_sha256"],
            "checked_indexes": request["checked_indexes"],
            "admissible_hits": [],
            "admissible_hit_count": 0,
            "memory_state": "COLD_START_NO_ADMISSIBLE_MEMORY",
        },
    }
    output_bytes = _json_bytes(search_output)
    invocation.private_output_path.write_bytes(output_bytes)
    adapter_receipt = _adapter_completion_receipt(
        trust_store=trust_store,
        artifact_identity=transfer["artifact_identity"],
        role_id=invocation.role_id,
        session_id=invocation.session_id,
        runtime_instance_id=invocation.runtime_instance_id,
        runtime_id=invocation.runtime_id,
        task_id=invocation.task_id,
        attempt_id=invocation.attempt_id,
        plan_sha256=invocation.plan_sha256,
        task_sha256=invocation.task_sha256,
        context_manifest_sha256=invocation.context_manifest_sha256,
        output_bytes=output_bytes,
    )
    outcome = ResearchOrgSessionOutcome(
        returncode=0,
        session_id=invocation.session_id,
        runtime_instance_id=invocation.runtime_instance_id,
        started_at_utc="2026-08-12T00:00:00Z",
        finished_at_utc="2026-08-12T00:00:02Z",
        provider="test-runtime",
        model="test-knowledge-librarian",
        transport="test_disposable_container",
        isolation_class="container_staged_context",
        owned_termination_supported=True,
        cancelled=False,
        stdout_tail="",
        stderr_tail="",
        provider_session_handle_sha256="1" * 64,
        adapter_receipt=adapter_receipt,
    )
    if tamper_index_before_completion:
        first_index = request["checked_indexes"][0]
        (invocation.context_root / first_index["path"]).write_bytes(
            b"tampered after runner\n"
        )
    receipt = complete_evo_v2_cold_start_search_session(
        invocation=(
            replace(invocation, task_sha256=completion_task_sha256)
            if completion_task_sha256 is not None
            else invocation
        ),
        outcome=outcome,
        state_root=tmp_path,
        installation_id=trust_store.installation_id,
    )
    return receipt, request


def test_cold_search_completion_rejects_public_record_alias(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_alias_workspace"
    transfer = _as_cold_start(_build_bundle(workspace))[
        "experience_transfer_bundle"
    ]
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )

    with pytest.raises(
        KnowledgeRetrievalError,
        match="cold_start_search_output_fields",
    ):
        _completed_cold_start_search(
            tmp_path=tmp_path,
            workspace=workspace,
            transfer=transfer,
            trust_store=trust_store,
            public_record_key="public_record",
        )


def test_cold_search_prompt_rejects_tampered_request_hash(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_prompt_tamper_workspace"
    transfer = _as_cold_start(_build_bundle(workspace))[
        "experience_transfer_bundle"
    ]
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )
    invocation, request, _search_root = _prepared_cold_start_search(
        tmp_path=tmp_path,
        workspace=workspace,
        transfer=transfer,
        trust_store=trust_store,
    )
    tampered = copy.deepcopy(request)
    tampered["policy"]["regime_shortcut_allowed"] = True
    (
        invocation.context_root
        / "identity/evo_v2_cold_start_search_request.json"
    ).write_bytes(_json_bytes(tampered))

    with pytest.raises(KnowledgeRetrievalError, match="request_sha256"):
        build_research_org_session_prompt(invocation)


def test_cold_search_prompt_rejects_tampered_staged_index(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_prompt_index_tamper_workspace"
    transfer = _as_cold_start(_build_bundle(workspace))[
        "experience_transfer_bundle"
    ]
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )
    invocation, request, _search_root = _prepared_cold_start_search(
        tmp_path=tmp_path,
        workspace=workspace,
        transfer=transfer,
        trust_store=trust_store,
    )
    first_index = request["checked_indexes"][0]
    (invocation.context_root / first_index["path"]).write_bytes(
        b"tampered before prompt\n"
    )

    with pytest.raises(
        KnowledgeRetrievalError,
        match="cold_start_search_index_readback",
    ):
        build_research_org_session_prompt(invocation)


def test_cold_search_prompt_rejects_invocation_task_hash_drift(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_prompt_hash_drift_workspace"
    transfer = _as_cold_start(_build_bundle(workspace))[
        "experience_transfer_bundle"
    ]
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )
    invocation, _request, _search_root = _prepared_cold_start_search(
        tmp_path=tmp_path,
        workspace=workspace,
        transfer=transfer,
        trust_store=trust_store,
    )

    with pytest.raises(
        KnowledgeRetrievalError,
        match="cold_start_search_task_hash_binding",
    ):
        build_research_org_session_prompt(
            replace(invocation, task_sha256="f" * 64)
        )


def test_cold_search_completion_rejects_post_runner_index_tamper(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_completion_index_tamper_workspace"
    transfer = _as_cold_start(_build_bundle(workspace))[
        "experience_transfer_bundle"
    ]
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )

    with pytest.raises(
        KnowledgeRetrievalError,
        match="cold_start_search_index_readback",
    ):
        _completed_cold_start_search(
            tmp_path=tmp_path,
            workspace=workspace,
            transfer=transfer,
            trust_store=trust_store,
            tamper_index_before_completion=True,
        )


def test_cold_search_completion_rejects_invocation_task_hash_drift(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_completion_hash_drift_workspace"
    transfer = _as_cold_start(_build_bundle(workspace))[
        "experience_transfer_bundle"
    ]
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )

    with pytest.raises(
        KnowledgeRetrievalError,
        match="cold_start_search_task_hash_binding",
    ):
        _completed_cold_start_search(
            tmp_path=tmp_path,
            workspace=workspace,
            transfer=transfer,
            trust_store=trust_store,
            completion_task_sha256="f" * 64,
        )


def _materialized_admission(tmp_path: Path) -> tuple[Path, dict, dict, object]:
    workspace = tmp_path / "factor_workspace"
    artifacts = _build_bundle(workspace)
    paths = materialize_evo_v2_bundle(
        artifacts,
        workspace_root=workspace,
        report_id=REPORT_ID,
    )
    relative_paths = evo_v2_relative_paths(REPORT_ID)
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )
    bundle_ref = {
        "path": relative_paths["experience_transfer_bundle"],
        "sha256": sha256_file(paths["experience_transfer_bundle"]),
    }
    receipt_ref = {
        "path": relative_paths["transfer_use_receipt"],
        "sha256": sha256_file(paths["transfer_use_receipt"]),
    }
    review_projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=artifacts["experience_transfer_bundle"],
        transfer_use_receipt=artifacts["transfer_use_receipt"],
        experience_transfer_bundle_ref=bundle_ref,
        transfer_use_receipt_ref=receipt_ref,
        trust_store=trust_store,
        source_workspace=workspace,
    )
    review_decision = _completed_review_decision(
        tmp_path=tmp_path,
        workspace=workspace,
        projection=review_projection,
        artifacts=artifacts,
        trust_store=trust_store,
    )
    use_change_receipt = _transfer_use_change_receipt(
        workspace=workspace,
        artifacts=artifacts,
        trust_store=trust_store,
    )
    admission = build_evo_v2_memory_admission(
        workspace=workspace,
        experience_transfer_bundle_ref=bundle_ref,
        transfer_use_receipt_ref=receipt_ref,
        review_decision_receipt=review_decision,
        trust_store=trust_store,
        transfer_use_change_receipt=use_change_receipt,
    )
    return workspace, artifacts, admission, trust_store


def test_admission_is_thin_single_authority_and_preserves_core_payload(
    tmp_path: Path,
) -> None:
    workspace, artifacts, admission, trust_store = _materialized_admission(tmp_path)

    assert validate_evo_v2_memory_admission(
        admission,
        trust_store=trust_store,
        workspace=workspace,
        verify_refs=True,
    ) == []
    assert admission["authority"] == "core_evo_v2_payload_only"
    assert admission["authority_guard"]["semantic_authority"] == (
        "factor_factory.evo_v2"
    )
    assert admission["authority_guard"]["payload_mutation_allowed"] is False
    assert admission["review_gate"]["decision_receipt"]["runtime_evidence"][
        "adapter_completion_receipt"
    ]["issuer"]["kind"] == "runtime_adapter"
    assert admission["host_admission_receipt"]["issuer"]["kind"] == (
        "host_admission"
    )
    source_sessions = admission["review_gate"]["decision_receipt"]["bindings"][
        "source_session_ids"
    ]
    reviewer_session = admission["review_gate"]["decision_receipt"]["reviewer"][
        "reviewer_session_id"
    ]
    assert reviewer_session not in source_sessions
    assert admission["core_payloads"]["experience_transfer_bundle"] == (
        artifacts["experience_transfer_bundle"]
    )
    assert admission["core_payloads"]["transfer_use_receipt"] == (
        artifacts["transfer_use_receipt"]
    )
    assert (
        admission["core_payloads"]["experience_transfer_bundle"][
            "contract_version"
        ]
        == EXPERIENCE_TRANSFER_BUNDLE_VERSION
    )
    assert (
        admission["core_payloads"]["transfer_use_receipt"]["contract_version"]
        == TRANSFER_USE_RECEIPT_VERSION
    )
    assert admission["admitted_experience_ids"] == [
        "exp_structural",
        "exp_conditional",
        "exp_episode",
    ]
    assert admission["core_payloads"]["experience_transfer_bundle"][
        "experiences"
    ][2]["lesson"]["layered_verdict"] == (
        "information survived; payer and tradability did not validate"
    )

    # Core refs can still point at the upstream dummy reviewer fixture, but
    # the Host cannot admit that self-assertion without a separately signed
    # runtime review decision over the exact core payloads.
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
    ):
        build_evo_v2_memory_admission(
            workspace=workspace,
            experience_transfer_bundle_ref=admission[
                "experience_transfer_bundle_ref"
            ],
            transfer_use_receipt_ref=admission["transfer_use_receipt_ref"],
            review_decision_receipt={},
            trust_store=trust_store,
        )

    # A core receipt that merely claims generated_test_id/changed=true is not
    # enough: admission also requires exact before/after plan readback.
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
    ):
        build_evo_v2_memory_admission(
            workspace=workspace,
            experience_transfer_bundle_ref=admission[
                "experience_transfer_bundle_ref"
            ],
            transfer_use_receipt_ref=admission["transfer_use_receipt_ref"],
            review_decision_receipt=admission["review_gate"][
                "decision_receipt"
            ],
            trust_store=trust_store,
            transfer_use_change_receipt=None,
        )

    tampered = copy.deepcopy(admission)
    tampered["core_payloads"]["experience_transfer_bundle"]["experiences"][0][
        "lesson"
    ]["second_semantic_authority"] = "forbidden"
    tampered = with_content_hash(
        {
            key: value
            for key, value in tampered.items()
            if key != "admission_sha256"
        },
        hash_field="admission_sha256",
    )
    reasons = validate_evo_v2_memory_admission(
        tampered,
        trust_store=trust_store,
        workspace=workspace,
        verify_refs=True,
    )
    assert any("unexpected_fields" in reason for reason in reasons)
    assert any("payload_binding" in reason for reason in reasons)

    forged_host = copy.deepcopy(admission)
    forged_host["host_admission_receipt"]["signature"]["value_b64"] = "AAAA"
    forged_host = with_content_hash(
        {
            key: value
            for key, value in forged_host.items()
            if key != "admission_sha256"
        },
        hash_field="admission_sha256",
    )
    assert any(
        "signature_invalid" in reason
        for reason in validate_evo_v2_memory_admission(
            forged_host,
            trust_store=trust_store,
            workspace=None,
            verify_refs=False,
        )
    )

    forged_change = copy.deepcopy(admission)
    forged_change["review_gate"]["transfer_use_change_receipt"][
        "question_and_test_diff"
    ]["added_test_ids"] = []
    forged_change = with_content_hash(
        {
            key: value
            for key, value in forged_change.items()
            if key != "admission_sha256"
        },
        hash_field="admission_sha256",
    )
    assert any(
        "transfer_use_change" in reason
        for reason in validate_evo_v2_memory_admission(
            forged_change,
            trust_store=trust_store,
            workspace=workspace,
            verify_refs=True,
        )
    )

    forged_review = copy.deepcopy(admission)
    forged_review["review_gate"]["decision_receipt"]["runtime_evidence"][
        "adapter_completion_receipt"
    ]["signature"]["value_b64"] = "AAAA"
    forged_review = with_content_hash(
        {
            key: value
            for key, value in forged_review.items()
            if key != "admission_sha256"
        },
        hash_field="admission_sha256",
    )
    assert any(
        "review_decision" in reason and "signature_invalid" in reason
        for reason in validate_evo_v2_memory_admission(
            forged_review,
            trust_store=trust_store,
            workspace=None,
            verify_refs=False,
        )
    )

    same_session = copy.deepcopy(admission)
    same_session["review_gate"]["decision_receipt"]["reviewer"][
        "reviewer_session_id"
    ] = source_sessions[0]
    same_session = with_content_hash(
        {
            key: value
            for key, value in same_session.items()
            if key != "admission_sha256"
        },
        hash_field="admission_sha256",
    )
    assert any(
        "reviewer_independence" in reason
        for reason in validate_evo_v2_memory_admission(
            same_session,
            trust_store=trust_store,
            workspace=None,
            verify_refs=False,
        )
    )


def test_host_private_sidecar_persists_idempotently_without_changing_v1_store(
    tmp_path: Path,
) -> None:
    workspace, _artifacts, admission, trust_store = _materialized_admission(tmp_path)
    sidecar = tmp_path / "host-private-evo-v2"
    first = persist_evo_v2_memory_admission(
        root=sidecar,
        admission=admission,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
        trust_store=trust_store,
    )
    second = persist_evo_v2_memory_admission(
        root=sidecar,
        admission=admission,
        repo_root=PROJECT_ROOT,
        workspace=workspace,
        trust_store=trust_store,
    )
    assert first["written"] is True
    assert second["written"] is False
    assert load_evo_v2_memory_admissions(
        root=sidecar,
        repo_root=PROJECT_ROOT,
        trust_store=trust_store,
    ) == [admission]

    v1_root = tmp_path / "host-private-v1"
    v1_manifest = ensure_researcher_memory_store(
        v1_root,
        installation_id="evo-v2-v1-compatibility",
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )
    assert v1_manifest["contract_version"] == (
        "factorforge_researcher_memory_store_v1"
    )
    assert validate_researcher_memory_store(
        v1_root,
        installation_id="evo-v2-v1-compatibility",
        repo_root=PROJECT_ROOT,
        workspace=workspace,
    )["verdict"] == "PASS"


def test_mechanism_first_projection_uses_core_vocabulary_and_not_regime(
    tmp_path: Path,
) -> None:
    workspace, artifacts, admission, trust_store = _materialized_admission(tmp_path)
    fingerprint = artifacts["experience_transfer_bundle"]["mechanism_fingerprint"]
    projection = retrieve_evo_v2_memory_projection(
        admissions=[admission],
        target_mechanism_fingerprint=fingerprint,
        blind_derivation_completed=True,
        trust_store=trust_store,
        top_k_per_lane=5,
    )
    assert projection["authority"] == "noncanonical_retrieval_projection_only"
    assert projection["semantic_authority"] == "factor_factory.evo_v2"
    assert projection["routing_policy"] == {
        "query_mode": "MECHANISM_FIRST_AFTER_BLIND_DERIVATION",
        "primary_retrieval_key": "mechanism_fingerprint",
        "retrieval_lanes": [
            "structural_isomorph",
            "cross_math_analogy",
            "near_miss_failure",
            "direct_counterexample",
            "historical_episode_context",
        ],
        "market_regime_role": (
            "historical_context_or_preregistered_boundary_only"
        ),
        "regime_shortcut_allowed": False,
        "historical_score_used_for_ranking": False,
        "current_factor_proof_authority": False,
    }
    assert {
        hit["experience_id"]
        for hit in projection["lanes"]["structural_isomorph"]
    } == {"exp_structural"}
    assert {
        hit["experience_id"]
        for hit in projection["lanes"]["near_miss_failure"]
    } == {"exp_conditional"}
    episode_hit = projection["lanes"]["historical_episode_context"][0]
    assert episode_hit["experience_id"] == "exp_episode"
    assert episode_hit["regime_match_required"] is False
    assert episode_hit["performance_score_used_for_ranking"] is False
    assert episode_hit["current_factor_proof_authority"] is False
    assert episode_hit["core_experience"] == (
        artifacts["experience_transfer_bundle"]["experiences"][2]
    )

    unrelated = {
        "economic_claim": "refinery inventory absorbs crude delivery shocks",
        "estimand_id": "inventory_write_down",
        "payer_or_constraint": "refinery operator | tank capacity",
        "mathematical_object": "inventory accounting identity",
        "broken_invariant_or_boundary": "tank capacity constraint",
        "observation_mapping": "legal refinery inventory report",
        "failure_signature": "inventory reconciliation fails",
    }
    no_regime_shortcut = retrieve_evo_v2_memory_projection(
        admissions=[admission],
        target_mechanism_fingerprint=unrelated,
        blind_derivation_completed=True,
        trust_store=trust_store,
    )
    assert no_regime_shortcut["retrieved_experience_count"] == 0
    assert all(not hits for hits in no_regime_shortcut["lanes"].values())

    state_label_only = {
        "economic_claim": (
            "bull-market regime around constraint-driven tail-state execution pressure"
        ),
        "estimand_id": "unrelated_state_label_estimand",
        "payer_or_constraint": "unrelated participant | unrelated constraint",
        "mathematical_object": fingerprint["mathematical_object"],
        "broken_invariant_or_boundary": fingerprint[
            "broken_invariant_or_boundary"
        ],
        "observation_mapping": fingerprint["observation_mapping"],
        "failure_signature": fingerprint["failure_signature"],
    }
    state_only_projection = retrieve_evo_v2_memory_projection(
        admissions=[admission],
        target_mechanism_fingerprint=state_label_only,
        blind_derivation_completed=True,
        trust_store=trust_store,
    )
    assert state_only_projection["retrieved_experience_count"] == 0

    with pytest.raises(
        KnowledgeRetrievalError,
        match=BLOCK_EVO_V2_MEMORY_RETRIEVAL_INVALID,
    ):
        retrieve_evo_v2_memory_projection(
            admissions=[admission],
            target_mechanism_fingerprint=fingerprint,
            blind_derivation_completed=False,
            trust_store=trust_store,
        )


def test_review_projection_checks_core_authority_without_issuing_a_decision(
    tmp_path: Path,
) -> None:
    workspace, _artifacts, admission, trust_store = _materialized_admission(tmp_path)
    projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=admission["core_payloads"][
            "experience_transfer_bundle"
        ],
        transfer_use_receipt=admission["core_payloads"][
            "transfer_use_receipt"
        ],
        experience_transfer_bundle_ref=admission[
            "experience_transfer_bundle_ref"
        ],
        transfer_use_receipt_ref=admission["transfer_use_receipt_ref"],
        trust_store=trust_store,
    )
    assert set(projection["review_checks"]) == set(EVO_V2_MEMORY_REVIEW_CHECKS)
    assert all(projection["review_checks"].values())
    assert projection["eligible_for_independent_reviewer_consideration"] is True
    assert projection["decision_issued"] is False
    assert projection["canonical_write_authority"] is False
    assert projection["current_factor_proof_authority"] is False

    mutated = copy.deepcopy(admission)
    mutated["core_payloads"]["experience_transfer_bundle"][
        "authority_guard"
    ]["mutation_permissions"]["skill"] = True
    with pytest.raises(
        ResearchOrganizationError,
        match=BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
    ):
        build_evo_v2_memory_review_projection(
            experience_transfer_bundle=mutated["core_payloads"][
                "experience_transfer_bundle"
            ],
            transfer_use_receipt=mutated["core_payloads"][
                "transfer_use_receipt"
            ],
            experience_transfer_bundle_ref=mutated[
                "experience_transfer_bundle_ref"
            ],
            transfer_use_receipt_ref=mutated["transfer_use_receipt_ref"],
            trust_store=trust_store,
            source_workspace=workspace,
        )


def test_verified_core_cold_start_is_persistable_but_retrieves_no_experience(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "cold_start_workspace"
    artifacts = _as_cold_start(_build_bundle(workspace))
    trust_store = ensure_runtime_trust_store(
        tmp_path / "research-org-trust",
        installation_id="evo-v2-memory-test",
    )
    transfer = artifacts["experience_transfer_bundle"]
    original_retrieval_ref = transfer["retrieval_policy"][
        "retrieval_evidence_refs"
    ][0]

    # The upstream core currently accepts a hash-bound file that still says
    # hit_count=3 as a declared cold start.  The memory gate must not.
    unsigned_projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=transfer,
        transfer_use_receipt=artifacts["transfer_use_receipt"],
        experience_transfer_bundle_ref={"path": "pending", "sha256": "0" * 64},
        transfer_use_receipt_ref={"path": "pending", "sha256": "0" * 64},
        trust_store=trust_store,
    )
    assert unsigned_projection["review_checks"][
        "cold_start_has_runtime_signed_zero_hit_proof"
    ] is False
    assert unsigned_projection[
        "eligible_for_independent_reviewer_consideration"
    ] is False

    search_receipt, search_request = _completed_cold_start_search(
        tmp_path=tmp_path,
        workspace=workspace,
        transfer=transfer,
        trust_store=trust_store,
    )
    assert search_receipt["inventory"]["admissible_hit_count"] == 0
    assert search_receipt["retrieval_runtime"]["search_request"] == search_request
    search_path = workspace / original_retrieval_ref["path"]
    search_path.write_bytes(canonical_json_bytes(search_receipt))
    signed_search_ref = {
        "path": original_retrieval_ref["path"],
        "sha256": sha256_file(search_path),
    }
    transfer["retrieval_policy"]["retrieval_evidence_refs"] = [
        signed_search_ref
    ]
    artifacts["experience_transfer_bundle"] = with_content_hash(
        transfer,
        hash_field="content_sha256",
    )
    artifacts["transfer_use_receipt"]["transfer_bundle_ref"]["sha256"] = (
        artifact_sha256(artifacts["experience_transfer_bundle"])
    )
    artifacts["transfer_use_receipt"] = with_content_hash(
        artifacts["transfer_use_receipt"],
        hash_field="content_sha256",
    )
    paths = materialize_evo_v2_bundle(
        artifacts,
        workspace_root=workspace,
        report_id=REPORT_ID,
    )
    relative_paths = evo_v2_relative_paths(REPORT_ID)
    bundle_ref = {
        "path": relative_paths["experience_transfer_bundle"],
        "sha256": sha256_file(paths["experience_transfer_bundle"]),
    }
    receipt_ref = {
        "path": relative_paths["transfer_use_receipt"],
        "sha256": sha256_file(paths["transfer_use_receipt"]),
    }
    review_projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=artifacts["experience_transfer_bundle"],
        transfer_use_receipt=artifacts["transfer_use_receipt"],
        experience_transfer_bundle_ref=bundle_ref,
        transfer_use_receipt_ref=receipt_ref,
        trust_store=trust_store,
        source_workspace=workspace,
        cold_start_search_receipt_ref=signed_search_ref,
        cold_start_search_receipt=search_receipt,
    )
    review_decision = _completed_review_decision(
        tmp_path=tmp_path,
        workspace=workspace,
        projection=review_projection,
        artifacts=artifacts,
        trust_store=trust_store,
    )
    admission = build_evo_v2_memory_admission(
        workspace=workspace,
        experience_transfer_bundle_ref=bundle_ref,
        transfer_use_receipt_ref=receipt_ref,
        review_decision_receipt=review_decision,
        trust_store=trust_store,
        cold_start_search_receipt_ref=signed_search_ref,
        cold_start_search_receipt=search_receipt,
    )
    assert admission["admitted_experience_ids"] == []
    review_projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=admission["core_payloads"][
            "experience_transfer_bundle"
        ],
        transfer_use_receipt=admission["core_payloads"][
            "transfer_use_receipt"
        ],
        experience_transfer_bundle_ref=admission[
            "experience_transfer_bundle_ref"
        ],
        transfer_use_receipt_ref=admission["transfer_use_receipt_ref"],
        trust_store=trust_store,
        cold_start_search_receipt_ref=admission["review_gate"][
            "cold_start_search_receipt_ref"
        ],
        cold_start_search_receipt=admission["review_gate"][
            "cold_start_search_receipt"
        ],
    )
    assert review_projection["eligible_for_independent_reviewer_consideration"]
    retrieval = retrieve_evo_v2_memory_projection(
        admissions=[admission],
        target_mechanism_fingerprint=artifacts["experience_transfer_bundle"][
            "mechanism_fingerprint"
        ],
        blind_derivation_completed=True,
        trust_store=trust_store,
    )
    assert retrieval["retrieved_experience_count"] == 0
    assert all(not hits for hits in retrieval["lanes"].values())
