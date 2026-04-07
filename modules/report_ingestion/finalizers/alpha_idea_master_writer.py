from __future__ import annotations

import json
from pathlib import Path

from ..writers.object_writer import ObjectWriter


class AlphaIdeaMasterWriter:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def write(self, report_id: str, alpha_idea_master: dict) -> Path:
        path = self.output_dir / f'alpha_idea_master__{report_id}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(alpha_idea_master, ensure_ascii=False, indent=2), encoding='utf-8')
        return path
