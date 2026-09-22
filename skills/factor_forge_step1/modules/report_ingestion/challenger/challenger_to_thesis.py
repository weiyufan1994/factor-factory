from __future__ import annotations

from typing import Any, Dict

from ..intake.structured_intake_contract import StructuredIntake
from ..normalizers.intake_to_alpha_thesis import intake_to_alpha_thesis


def challenger_intake_to_thesis(intake: StructuredIntake) -> Dict[str, Any]:
    thesis = intake_to_alpha_thesis(intake)
    thesis['route_role'] = 'challenger'
    return thesis
