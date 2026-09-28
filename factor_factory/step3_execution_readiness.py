"""Separate a valid blocked Step3 record from permission to continue execution."""
from __future__ import annotations

from collections.abc import Mapping


def require_execution_readiness(prep, handoff, feasibility_report, *, step3b=False):
    """Read existing native states only; never infer readiness from exit code."""
    if not isinstance(prep, Mapping) or prep.get('feasibility') not in {'ready', 'proxy_ready'}:
        raise ValueError('BLOCK_STEP3A_NOT_READY: native data feasibility is not ready/proxy_ready')
    if (
        not isinstance(feasibility_report, Mapping)
        or not prep.get('report_id')
        or feasibility_report.get('report_id') != prep.get('report_id')
        or feasibility_report.get('final_result') != prep.get('feasibility')
    ):
        raise ValueError('BLOCK_STEP3A_FEASIBILITY_REPORT_MISMATCH: missing or contradictory native report')
    if not isinstance(handoff, Mapping) or handoff.get('step3a_ready') is not True:
        raise ValueError('BLOCK_STEP3A_NOT_READY: handoff is not ready')
    if step3b and handoff.get('step3b_ready') is not True:
        raise ValueError('BLOCK_STEP3B_NOT_READY: implementation handoff is not ready')
