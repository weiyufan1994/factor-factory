from __future__ import annotations

from typing import Any, Dict

from ..intake.structured_intake_contract import StructuredIntake
from ..normalizers.intake_to_report_map import intake_to_report_map
from ..validators.schema_validator import SchemaValidator


class ReportMapBuilder:
    def __init__(self, schema_validator: SchemaValidator):
        self.schema_validator = schema_validator

    def build_from_intake(self, intake: StructuredIntake) -> Dict[str, Any]:
        report_map = intake_to_report_map(intake)
        self.schema_validator.validate("report_map.schema.json", report_map)
        return report_map
