"""Local research scope, independent of the hosted OOS control plane."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path


LOCAL_IS_PROOF_SEMANTICS = "local_is_research_execution"
HOST_ONLY_ARGUMENTS = (
    "research_org_runtime_private_root",
    "research_org_runtime_trust_root",
    "research_org_runtime_installation_id",
    "evo_child_research_org_assurance",
    "expected_host_trust_manifest_sha256",
    "sealed_oos_carrier",
    "sealed_oos_private_root",
    "sealed_oos_agent_visible_root",
    "agent_execution_sandbox_profile",
    "agent_execution_sandbox_admission",
    "agent_execution_container_admission",
    "evo_child_finalizer_recovery_admission",
    "evo_child_command_recovery_admission",
    "apply_approved_revision",
)


def local_is_request_errors(args: Namespace) -> list[str]:
    """An explicit local scope cannot also request hosted/OOS operations."""
    errors = [name for name in HOST_ONLY_ARGUMENTS if getattr(args, name, None)]
    if getattr(args, "research_org_runtime_mode", "off") not in {None, "off"}:
        errors.append("research_org_runtime_mode")
    if getattr(args, "allow_legacy_research_protocol_smoke", False):
        errors.append("allow_legacy_research_protocol_smoke")
    return errors


def local_is_workspace_errors(root: Path, report_id: str) -> list[str]:
    """Do not reinterpret an existing hosted/OOS child as a local study.

    Presence checks include broken links. No private store or data is opened.
    """
    protocol = root / "objects" / "research_protocol"
    paths = (
        root / "identity" / "data_catalog_summary.json",
        protocol / f"evo_child_materialization_ticket__{report_id}__authorization.json",
        protocol / f"evo_child_materialization_ticket__{report_id}__ready.json",
        protocol / f"evo_child_intent__{report_id}.json",
        root / "objects" / "research_iteration_master" / f"executable_revision_spec__{report_id}.json",
    )
    return [str(path.relative_to(root)) for path in paths if path.exists() or path.is_symlink()]


def local_is_recovery_forbidden(recovery: dict) -> bool:
    return bool(
        recovery.get("recovery_required")
        or recovery.get("finalization_receipt_present")
        or recovery.get("allowed_execution", "NORMAL") != "NORMAL"
    )


def finish_local_is_proof(proof: dict, *, commands_passed: bool) -> None:
    """Execution evidence is real IS research, never a signed OOS certificate."""
    proof.update(
        status="PASS" if commands_passed else "FAIL",
        proof_semantics=LOCAL_IS_PROOF_SEMANTICS,
        formal_proof_eligible=False,
        current_formal_authority_verified=False,
        factor_verdict="NOT_ISSUED",
        oos_access_allowed=False,
        official_promotion_allowed=False,
        is_execution_complete=commands_passed,
        final_outcome="local_is_execution_completed" if commands_passed else "blocked",
    )
    if not commands_passed:
        proof["failure"] = {
            "command": "local_is_command_closure",
            "returncode": 1,
            "token": "BLOCK_FACTORFORGE_LOCAL_IS_COMMAND_CLOSURE",
        }
