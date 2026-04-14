from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..intake.pdf_skill_client import PdfSkillClient


class ChiefMergeClient:
    def __init__(self, pdf_skill_client: PdfSkillClient, prompt_path: str | Path):
        self.pdf_skill_client = pdf_skill_client
        self.prompt_path = Path(prompt_path)

    def build_merge_prompt(
        self,
        primary_intake: Dict[str, Any],
        challenger_intake: Dict[str, Any],
        primary_thesis: Dict[str, Any],
        challenger_thesis: Dict[str, Any],
        intake_diff: Dict[str, Any],
        thesis_diff: Dict[str, Any],
    ) -> str:
        base_prompt = self.prompt_path.read_text(encoding='utf-8')
        context = f"""
## CONTEXT FOR CHIEF MERGE

### PRIMARY INTAKE
{json.dumps(primary_intake, ensure_ascii=False, indent=2)}

### CHALLENGER INTAKE
{json.dumps(challenger_intake, ensure_ascii=False, indent=2)}

### PRIMARY THESIS
{json.dumps(primary_thesis, ensure_ascii=False, indent=2)}

### CHALLENGER THESIS
{json.dumps(challenger_thesis, ensure_ascii=False, indent=2)}

### INTAKE DIFF
{json.dumps(intake_diff, ensure_ascii=False, indent=2)}

### THESIS DIFF
{json.dumps(thesis_diff, ensure_ascii=False, indent=2)}

---

{base_prompt}
"""
        return context

    def run_merge(
        self,
        report_id: str,
        primary_intake: Dict[str, Any],
        challenger_intake: Dict[str, Any],
        primary_thesis: Dict[str, Any],
        challenger_thesis: Dict[str, Any],
        intake_diff: Dict[str, Any],
        thesis_diff: Dict[str, Any],
    ) -> Dict[str, Any]:
        prompt = self.build_merge_prompt(
            primary_intake, challenger_intake,
            primary_thesis, challenger_thesis,
            intake_diff, thesis_diff,
        )
        # Use a dummy PDF path since this is synthetic content; pdf_skill_client
        # extracts the text from response_text param not from actual PDF
        response = self.pdf_skill_client.call_skill(
            report_id=report_id,
            pdf_path=None,  # dummy - not reading a real PDF here
            prompt=prompt,
        )
        return json.loads(response)
