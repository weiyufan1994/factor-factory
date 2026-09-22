from __future__ import annotations

from typing import Any, Dict

from ..intake.structured_intake_contract import StructuredIntake


def intake_to_ambiguity_review(intake: StructuredIntake) -> Dict[str, Any]:
    return {
        "report_id": intake.report_id,
        "title": intake.report_meta.get("title", intake.report_id),
        "structure_ambiguities": intake.ambiguities,
        "variable_ambiguities": intake.ambiguities,
        "signal_ambiguities": intake.ambiguities,
        "further_manual_review": intake.ambiguities,
        "evidence_clues": intake.evidence_clues,
    }
