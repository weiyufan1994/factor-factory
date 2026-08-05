from __future__ import annotations


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
