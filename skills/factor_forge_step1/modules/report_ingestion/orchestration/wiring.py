from __future__ import annotations

from pathlib import Path

from ..builders.report_map_builder import ReportMapBuilder
from ..intake.pdf_skill_client import PdfSkillClient
from ..orchestration.step1_pipeline import Step1Pipeline
from ..registry.report_registry import ReportRegistry
from ..validators.schema_validator import SchemaValidator
from ..writers.object_writer import ObjectWriter


def build_step1_pipeline(project_root: str | Path) -> Step1Pipeline:
    root = Path(project_root)
    schema_root = root / "schemas"
    if not schema_root.exists():
        schema_root = root / "skills" / "factor_forge_step1" / "schemas"
    registry = ReportRegistry(root / "data" / "report_ingestion" / "report_registry.json")
    schema_validator = SchemaValidator(schema_root)
    pdf_skill_client = PdfSkillClient()
    report_map_builder = ReportMapBuilder(schema_validator=schema_validator)
    object_writer = ObjectWriter(root / "objects")
    return Step1Pipeline(
        registry=registry,
        pdf_skill_client=pdf_skill_client,
        report_map_builder=report_map_builder,
        object_writer=object_writer,
    )
