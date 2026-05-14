from __future__ import annotations

import re
from typing import Any

FORBIDDEN_TEXT_TOKEN = "BLOCK_REVISION_COUNCIL_FORBIDDEN_CHANGE"

FORBIDDEN_PATTERNS = [
    "portfolio expression",
    "portfolio repair",
    "portfolio",
    "rebalance",
    "short leg",
    "short-leg",
    "short_side",
    "short side",
    "long-short",
    "long short",
    "decile trading",
    "buy decile",
    "sell decile",
    "shared clean data",
    "clean data mutation",
    "mutate clean data",
]

SKIP_TEXT_KEYS = {
    "report_id",
    "proposal_id",
    "block_reasons",
    "forbidden_changes_ack",
    "hard_guards",
    "forbidden_search",
    "forbidden_actions_confirmed",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def scan_forbidden_text(data: Any, *, path: str = "$") -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}"
            if key in SKIP_TEXT_KEYS:
                continue
            findings.extend(scan_forbidden_text(value, path=child_path))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            findings.extend(scan_forbidden_text(value, path=f"{path}[{idx}]"))
    elif isinstance(data, str):
        normalized = _norm(data)
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in normalized:
                findings.append({"path": path, "pattern": pattern})
    return findings
