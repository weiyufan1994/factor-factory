"""Ordinary IS preflight: inspect local release markers without loading Host code."""
from __future__ import annotations

from factor_factory.local_is_execution import local_is_recovery_forbidden
from factor_factory.research_evidence import web_factor_proof_oos_recovery_state
from factor_factory.runtime_context import FactorForgeContext
from factor_factory.ultimate_loop.state import ExecutionMode


def prepare_local_execution(ctx: FactorForgeContext, report_id: str) -> ExecutionMode | int:
    try:
        recovery = web_factor_proof_oos_recovery_state(ctx.active_root, report_id)
    except (OSError, ValueError) as exc:
        print(f"BLOCK_FACTORFORGE_WEB_OOS_RECOVERY_STATE_INVALID: {exc}")
        return 1
    if local_is_recovery_forbidden(recovery):
        print("BLOCK_FACTORFORGE_LOCAL_IS_OOS_RECOVERY_FORBIDDEN")
        return 1
    return ExecutionMode(web_oos_recovery=recovery)
