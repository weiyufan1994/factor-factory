from __future__ import annotations

from copy import deepcopy
from typing import Any


EQUATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "square_root_impact_invariance": {
        "equation_id": "square_root_impact_invariance",
        "equation_status": "empirical_invariance",
        "equation_text": "realized_impact ~= sigma * sqrt(order_size / volume)",
        "symmetry_or_constraint": "impact scales sublinearly with participation under repeated liquidity provision",
        "evidence_tier": "cross_asset_empirical_invariance",
        "audit_basis": ("Empirical microstructure literature should support the square-root impact relation.",),
        "participant_constraint_loop": {
            "payer": "liquidity demanders",
            "constraint": "urgent execution cannot wait for full liquidity replenishment",
            "repeat_mechanism": "large orders repeatedly consume displayed and hidden liquidity",
            "failure_condition": "market design or liquidity regime changes break impact scaling",
        },
        "demotion_triggers": ("liquidity_regime_change", "cross_sample_failure", "metric_signature_mismatch"),
    },
    "disposition_feedback_pressure": {
        "equation_id": "disposition_feedback_pressure",
        "equation_status": "behavioral_feedback",
        "equation_text": "delayed_selling_pressure = f(unrealized_gain_loss_distribution, breakout_state)",
        "symmetry_or_constraint": "holders repeatedly defer realization until price paths cross behavioral reference points",
        "evidence_tier": "report_specific_hypothesis",
        "audit_basis": ("Report text or cited behavioral finance evidence must support the cost-basis pressure claim.",),
        "participant_constraint_loop": {
            "payer": "anchored holders or short-horizon traders",
            "constraint": "cannot or will not immediately abandon cost-basis anchored behavior",
            "repeat_mechanism": "new trapped positions are created by prior trading waves",
            "failure_condition": "participant structure changes or trapped-position density no longer maps to selling pressure",
        },
        "demotion_triggers": ("participant_structure_change", "metric_signature_mismatch", "cross_sample_failure"),
    },
}


def equation_template(equation_id: str) -> dict[str, Any] | None:
    template = EQUATION_TEMPLATES.get(str(equation_id or ""))
    return deepcopy(template) if template else None
