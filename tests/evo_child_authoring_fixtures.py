from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from factor_factory.evo_child_authoring import (
    evo_child_authoring_admission_path,
    run_and_admit_evo_child_authoring,
    validate_evo_child_authoring_admission,
)
from factor_factory.evo_v2 import canonical_json_bytes
from factor_factory.research_org.contracts import (
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
)
from factor_factory.research_org.runtime import (
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
)
from factor_factory.research_org.runtime_trust import (
    ensure_runtime_trust_store,
)


class SignedEvoChildAuthoringFakeRunner:
    """Test-only runtime double with a real runtime-adapter signature."""

    def __init__(
        self,
        *,
        semantic_bundle: Mapping[str, Any],
        trust_root: Path,
        installation_id: str,
        isolation_class: str = "container_staged_context",
        transport: str = "openclaw_disposable_container",
    ) -> None:
        self.semantic_bundle = dict(semantic_bundle)
        self.trust_store = ensure_runtime_trust_store(
            trust_root,
            installation_id=installation_id,
        )
        self.installation_id = installation_id
        self.isolation_class = isolation_class
        self.transport = transport

    def reconcile_research_org_session(
        self,
        runtime_instance_id: str,
    ) -> dict[str, Any]:
        return self.trust_store.sign(
            "runtime_adapter",
            {
                "receipt_type": "RESEARCH_ORG_CONTAINER_TERMINATION",
                "identity": {
                    "runtime_instance_id": runtime_instance_id,
                    "runtime_handle_sha256": hashlib.sha256(
                        runtime_instance_id.encode("utf-8")
                    ).hexdigest(),
                    "adapter_id": self.installation_id,
                },
                "ordering": {"issued_at_utc": "2026-08-13T00:00:00Z"},
                "termination": {
                    "initial_state": "ABSENT",
                    "ownership_labels_verified": False,
                    "remove_attempted": False,
                    "inspect_not_found": True,
                    "final_state": "ABSENT",
                    "termination_confirmed": True,
                },
                "authority": {
                    "scope": "OWNED_CONTAINER_TERMINATION_ONLY",
                    "retry_authorized": False,
                    "factor_verdict": "NOT_ISSUED",
                },
            },
        )

    def run_research_org_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> ResearchOrgSessionOutcome:
        private_output = {
            "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
            "status": "PASS",
            "public_research_record": self.semantic_bundle,
        }
        output_raw = canonical_json_bytes(private_output)
        invocation.private_output_path.write_bytes(output_raw)
        provider_handle = hashlib.sha256(
            f"test-provider:{invocation.session_id}".encode()
        ).hexdigest()
        started = "2026-08-13T00:00:00Z"
        finished = "2026-08-13T00:00:01Z"
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
                    "issued_at_utc": finished,
                    "started_at_utc": started,
                    "finished_at_utc": finished,
                },
                "bindings": {
                    "plan_sha256": invocation.plan_sha256,
                    "task_sha256": invocation.task_sha256,
                    "context_manifest_sha256": (
                        invocation.context_manifest_sha256
                    ),
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
                    "container_image_digest": "sha256:" + "b" * 64,
                    "isolation_profile_sha256": "c" * 64,
                    "runtime": {
                        "provider": "signed-test-runtime",
                        "model": "evo-child-author-test-model",
                        "transport": self.transport,
                        "isolation_class": self.isolation_class,
                        "owned_termination_supported": True,
                    },
                    "parent_session_uid": None,
                    "lease_epoch": invocation.scheduler_epoch,
                },
                "outcome": {
                    "returncode": 0,
                    "cancelled": False,
                    "error_class": None,
                    "private_output_sha256": hashlib.sha256(
                        output_raw
                    ).hexdigest(),
                    "private_output_size_bytes": len(output_raw),
                    "termination_confirmed": True,
                },
            },
        )
        return ResearchOrgSessionOutcome(
            returncode=0,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc=started,
            finished_at_utc=finished,
            provider="signed-test-runtime",
            model="evo-child-author-test-model",
            transport=self.transport,
            isolation_class=self.isolation_class,
            owned_termination_supported=True,
            provider_session_handle_sha256=provider_handle,
            adapter_receipt=receipt,
        )


def admit_signed_evo_child_authoring_fixture(
    *,
    workspace_root: Path,
    parent_report_id: str,
    child_report_id: str,
    semantic_bundle: Mapping[str, Any],
    expected_host_trust_manifest_sha256: str,
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    """Run the real admission path, or exact-replay an existing admission."""

    admission_path = evo_child_authoring_admission_path(
        workspace_root, child_report_id
    )
    if admission_path.is_file():
        validated = validate_evo_child_authoring_admission(
            workspace_root=workspace_root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            agent_authoring_admission=admission_path,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        if validated["semantic_bundle"] != dict(semantic_bundle):
            raise AssertionError("existing_authoring_admission_semantic_mismatch")
        return {
            "verdict": "PASS",
            "status": validated["status"],
            "admission": validated["admission"],
            "admission_ref": {
                "path": admission_path.relative_to(workspace_root).as_posix(),
                "sha256": hashlib.sha256(admission_path.read_bytes()).hexdigest(),
            },
            "semantic_bundle": validated["semantic_bundle"],
        }
    private_root = (
        workspace_root.parent / f".{workspace_root.name}-evo-child-authoring-private"
    )
    return run_and_admit_evo_child_authoring(
        runner=SignedEvoChildAuthoringFakeRunner(
            semantic_bundle=semantic_bundle,
            trust_root=trust_root,
            installation_id=installation_id,
        ),
        workspace_root=workspace_root,
        worktree=workspace_root,
        private_root=private_root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        trust_root=trust_root,
        installation_id=installation_id,
    )
