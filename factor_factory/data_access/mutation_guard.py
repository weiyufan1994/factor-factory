from __future__ import annotations

import os
from datetime import datetime, timezone

AUTHORIZED_OPERATORS = {"codex", "codex-data-steward"}
APPROVAL_ENV = "FACTORFORGE_DATA_MUTATION_APPROVED"


def require_data_mutation_authority(operator: str | None, *, operation: str) -> dict[str, str]:
    """Gate shared data-layer mutations behind an explicit operator approval.

    Factor research agents may read shared data, but they must not rebuild or
    replace the canonical clean layer unless the user explicitly delegated that
    task to Codex. This guard makes accidental data mutation fail closed.
    """
    normalized = str(operator or "").strip().lower()
    approval = os.getenv(APPROVAL_ENV, "").strip().lower()
    if normalized not in AUTHORIZED_OPERATORS or approval not in {"1", "true", "yes", "codex-approved"}:
        raise SystemExit(
            "DATA_MUTATION_NOT_AUTHORIZED: shared data-layer writes require "
            f"--operator codex and {APPROVAL_ENV}=codex-approved "
            f"(operation={operation}). Bernard/Humphrey researcher agents must not mutate data directly."
        )
    return {
        "operator": normalized,
        "approval_env": APPROVAL_ENV,
        "operation": operation,
        "authorized_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
