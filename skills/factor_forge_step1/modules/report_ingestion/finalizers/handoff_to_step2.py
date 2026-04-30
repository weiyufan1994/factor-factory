from __future__ import annotations

import json
from pathlib import Path

from ..research_discipline import attach_step1_research_discipline


class HandoffToStep2:
    def __init__(self, handoff_dir: Path):
        self.handoff_dir = Path(handoff_dir)

    def write_handoff(self, report_id: str, alpha_idea_master: dict, metadata: dict = None) -> Path:
        path = self.handoff_dir / f'handoff__{report_id}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        alpha_idea_master = attach_step1_research_discipline(
            alpha_idea_master,
            self.handoff_dir.parents[1] if len(self.handoff_dir.parents) > 1 else None,
        )
        payload = {
            'report_id': report_id,
            'alpha_idea_master_ref': f'alpha_idea_master__{report_id}.json',
            'step1_status': 'alpha_idea_master_ready',
            'research_discipline': alpha_idea_master.get('research_discipline') or {},
            'handoff_metadata': metadata or {},
            'objects': {
                'alpha_idea_master': alpha_idea_master,
            }
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return path
