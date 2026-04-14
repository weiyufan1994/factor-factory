from __future__ import annotations

from typing import Any, Dict

from ..intake.structured_intake_contract import StructuredIntake


def intake_to_alpha_thesis(intake: StructuredIntake) -> Dict[str, Any]:
    final_factor = intake.final_factor or {}
    return {
        "report_id": intake.report_id,
        "title": intake.report_meta.get("title", intake.report_id),
        "thesis_name": final_factor.get("name") or (intake.alpha_candidates[0]["name"] if intake.alpha_candidates else None),
        "economic_logic": final_factor.get("economic_logic"),
        "economic_logic_source": final_factor.get("economic_logic_source"),
        "behavioral_logic": final_factor.get("behavioral_logic"),
        "behavioral_logic_source": final_factor.get("behavioral_logic_source"),
        "causal_chain": final_factor.get("causal_chain"),
        "causal_chain_source": final_factor.get("causal_chain_source"),
        "direction": final_factor.get("direction") or (intake.alpha_candidates[0].get("direction") if intake.alpha_candidates else None),
        "key_variables": intake.variables,
        "signals": intake.signals,
        "subfactors": intake.subfactors,
        "final_factor": final_factor,
        "formula_clues": intake.formula_clues,
        "code_clues": intake.code_clues,
        "implementation_clues": intake.implementation_clues,
        "ambiguities": intake.ambiguities,
        "evidence_clues": intake.evidence_clues,
        "source_topic": intake.report_meta.get("topic"),
    }
