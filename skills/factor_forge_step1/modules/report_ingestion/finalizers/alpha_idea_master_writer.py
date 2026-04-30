from __future__ import annotations

import json
from pathlib import Path

from ..writers.object_writer import ObjectWriter
from ..research_discipline import attach_step1_research_discipline


class AlphaIdeaMasterWriter:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def write(self, report_id: str, alpha_idea_master: dict) -> Path:
        path = self.output_dir / f'alpha_idea_master__{report_id}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        alpha_idea_master = attach_step1_research_discipline(
            alpha_idea_master,
            self.output_dir.parents[1] if len(self.output_dir.parents) > 1 else None,
        )
        path.write_text(json.dumps(alpha_idea_master, ensure_ascii=False, indent=2), encoding='utf-8')
        return path
