from __future__ import annotations

from typing import Any, Dict

from ..intake.structured_intake_contract import StructuredIntake


def intake_to_report_map(intake: StructuredIntake) -> Dict[str, Any]:
    return {
        "paper_id": intake.report_id,
        "title": intake.report_meta.get("title", intake.report_id),
        "builder_role": "pdf_skill_primary",
        "prompt_name": "step1_report_intake.md",
        "section_map": intake.section_map,
        "variables": intake.variables,
        "key_visual_elements": intake.evidence_clues,
        "notes": intake.ambiguities,
        "evidence_refs": intake.evidence_clues,
        "metadata": {
            "broker": intake.report_meta.get("broker"),
            "topic": intake.report_meta.get("topic"),
            "signals": intake.signals,
            "alpha_candidates": intake.alpha_candidates,
            "subfactors": intake.subfactors,
            "final_factor": intake.final_factor,
            "formula_clues": intake.formula_clues,
            "code_clues": intake.code_clues,
            "implementation_clues": intake.implementation_clues,
        },
    }
