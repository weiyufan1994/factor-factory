from __future__ import annotations

from pathlib import Path


class PromptLoader:
    def __init__(self, prompt_root: str | Path):
        self.prompt_root = Path(prompt_root)

    def load(self, prompt_name: str) -> str:
        path = self.prompt_root / prompt_name
        if not path.exists():
            raise FileNotFoundError(f"prompt not found: {path}")
        return path.read_text(encoding="utf-8")
