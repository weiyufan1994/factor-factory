from __future__ import annotations

import os
from pathlib import Path
from typing import Any


TERMINAL_REJECTION_CLOSED = "closed"
TERMINAL_REJECTION_NEXT_DERIVATION = "awaiting_next_derivation"
TERMINAL_REJECTION_MAIN_AGENT_SYNTHESIS = (
    "awaiting_main_agent_council_synthesis"
)
TERMINAL_REJECTION_FAILED = "failed"


def classify_terminal_rejection_result(
    *,
    returncode: int,
    output: str,
    branch_falsification_exists: bool,
) -> str:
    if returncode == 0:
        return TERMINAL_REJECTION_CLOSED
    if (
        "BLOCK_PREMATURE_TERMINAL_REJECT_BEFORE_MAX_LOOPS" in output
        and branch_falsification_exists
    ):
        return TERMINAL_REJECTION_NEXT_DERIVATION
    if any(
        token in output
        for token in (
            "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_NOT_UNANIMOUS",
            "BLOCK_FACTORFORGE_TERMINAL_COUNCIL_FACTOR_PROOF_NOT_REJECTED",
        )
    ):
        return TERMINAL_REJECTION_MAIN_AGENT_SYNTHESIS
    return TERMINAL_REJECTION_FAILED


def _nested_dict(root: dict, *keys: str) -> dict:
    cur = root
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def local_terminal_reject_without_revision(
    iteration: dict[str, Any],
    step3b_handoff_path: Path,
) -> bool:
    """Recognize the one local-IS terminal path that has no revision to prove.

    A rejected local empirical review may stop after its authored reviewers
    agree.  It is neither an iteration nor a downstream authority event, so
    requiring future revision obligations/counterexamples would manufacture a
    non-existent next round.  Keep this deliberately narrower than a generic
    ``reject``: it must be the producer's explicit local terminal shape and
    must not have emitted a Step3B handoff.
    """
    judgment = _nested_dict(iteration, 'research_judgment')
    memo = _nested_dict(judgment, 'research_memo')
    boundary = _nested_dict(memo, 'local_is_authority_boundary')
    decision_source = memo.get('decision_source')
    loop_action = _nested_dict(iteration, 'loop_action')
    return (
        judgment.get('decision') == 'reject'
        and isinstance(decision_source, dict)
        and decision_source == {
            'source': 'concordant_authored_local_researcher_and_independent_review',
            'decision': 'reject',
            'promotion_allowed': False,
            'automatic_revision_allowed': False,
        }
        and boundary == {
            'execution_status': 'step6_local_is_review_completed',
            'factor_verdict': 'NOT_ISSUED',
            'official_promotion_allowed': False,
            'oos_access_allowed': False,
            'original_quantitative_decision': 'reject',
        }
        and loop_action.get('should_modify_step3b') is False
        and loop_action.get('loop_authorization') == 'advisory_only'
        and loop_action.get('next_runner') == 'stop'
        and loop_action.get('requires_human_approval_before_code_change') is False
        and not step3b_handoff_path.exists()
    )


def local_terminal_reject_without_actions(
    iteration: dict[str, Any],
    step3b_handoff_path: Path,
    revision_strategy: dict[str, Any],
    search_policy_decision: dict[str, Any],
) -> bool:
    """Allow no approval only for an authenticated terminal local stop.

    ``advisory_only`` commonly still describes an unexecuted future proposal,
    which must retain the human gate.  This exception is only for an authored
    local rejection that has removed every revision and branch action.
    """
    loop_action = _nested_dict(iteration, 'loop_action')
    branch_templates = search_policy_decision.get('branch_templates')
    return (
        os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1'
        and local_terminal_reject_without_revision(iteration, step3b_handoff_path)
        and revision_strategy.get('revision_needed') is False
        and revision_strategy.get('revision_hypotheses') == []
        and revision_strategy.get('terminal_local_rejection') is True
        and branch_templates == []
        and loop_action.get('modification_targets') == []
        and loop_action.get('parallel_exploration_branches') == []
        and loop_action.get('search_methods') == []
    )
