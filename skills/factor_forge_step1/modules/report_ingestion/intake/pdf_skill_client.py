from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .pdf_skill_prompts import build_step1_report_intake_prompt
from .structured_intake_contract import StructuredIntake


class PdfSkillClient:
    def __init__(self, tool_runner: Any | None = None, model: str = "google/gemini-3.1-pro-preview"):
        self.tool_runner = tool_runner
        self.model = model

    def build_request(self, pdf_path: str | Path) -> dict:
        return {
            "pdf": str(Path(pdf_path)),
            "prompt": build_step1_report_intake_prompt(),
            "model": self.model,
        }

    def parse_response(self, report_id: str, response_text: str) -> StructuredIntake:
        payload = json.loads(response_text)
        return StructuredIntake(
            report_id=report_id,
            report_meta=payload.get("report_meta", {}),
            section_map=payload.get("section_map", []),
            variables=payload.get("variables", []),
            signals=payload.get("signals", []),
            subfactors=payload.get("subfactors", []),
            final_factor=payload.get("final_factor", {}),
            formula_clues=payload.get("formula_clues", []),
            code_clues=payload.get("code_clues", []),
            implementation_clues=payload.get("implementation_clues", []),
            alpha_candidates=payload.get("alpha_candidates", []),
            evidence_clues=payload.get("evidence_clues", []),
            ambiguities=payload.get("ambiguities", []),
            raw_response=response_text,
        )
