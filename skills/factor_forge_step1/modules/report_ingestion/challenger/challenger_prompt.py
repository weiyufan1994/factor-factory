from __future__ import annotations

from pathlib import Path


def load_challenger_prompt(prompt_root: str | Path) -> str:
    path = Path(prompt_root) / 'step1_report_intake_challenger.md'
    return path.read_text(encoding='utf-8')
