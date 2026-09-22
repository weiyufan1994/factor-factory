from __future__ import annotations

from typing import Dict, Optional

from ..builders.report_map_builder import ReportMapBuilder
from ..challenger.challenger_to_thesis import challenger_intake_to_thesis
from ..intake.pdf_skill_client import PdfSkillClient
from ..normalizers.intake_to_alpha_thesis import intake_to_alpha_thesis
from ..normalizers.intake_to_ambiguity_review import intake_to_ambiguity_review
from ..registry.report_source_contract import ReportSource
from ..registry.report_registry import ReportRegistry
from ..writers.object_writer import ObjectWriter


class Step1Pipeline:
    def __init__(
        self,
        registry: ReportRegistry,
        pdf_skill_client: PdfSkillClient,
        report_map_builder: ReportMapBuilder,
        object_writer: ObjectWriter,
    ):
        self.registry = registry
        self.pdf_skill_client = pdf_skill_client
        self.report_map_builder = report_map_builder
        self.object_writer = object_writer

    def run_pdf_skill(
        self,
        source: ReportSource,
        response_text: str,
        challenger_response_text: Optional[str] = None,
    ) -> Dict[str, str]:
        self.registry.register(source)
        self.registry.update_status(source.report_id, "cached", local_cache_path=source.local_cache_path)

        intake = self.pdf_skill_client.parse_response(source.report_id, response_text)
        intake_path = self.object_writer.write_validation_result(source.report_id + "__intake", intake.to_dict())

        report_map = self.report_map_builder.build_from_intake(intake)
        report_map_path = self.object_writer.write_report_map(source.report_id, "primary", report_map)

        alpha_thesis = intake_to_alpha_thesis(intake)
        alpha_thesis_path = self.object_writer.write_validation_result(source.report_id + "__alpha_thesis", alpha_thesis)

        ambiguity_review = intake_to_ambiguity_review(intake)
        ambiguity_review_path = self.object_writer.write_validation_result(source.report_id + "__ambiguity_review", ambiguity_review)

        result = {
            "intake_path": intake_path,
            "report_map_path": report_map_path,
            "alpha_thesis_path": alpha_thesis_path,
            "ambiguity_review_path": ambiguity_review_path,
        }

        if challenger_response_text:
            challenger_intake = self.pdf_skill_client.parse_response(source.report_id, challenger_response_text)
            challenger_intake_path = self.object_writer.write_validation_result(source.report_id + "__challenger_intake", challenger_intake.to_dict())
            challenger_report_map = self.report_map_builder.build_from_intake(challenger_intake)
            challenger_report_map_path = self.object_writer.write_report_map(source.report_id, "challenger", challenger_report_map)
            challenger_thesis = challenger_intake_to_thesis(challenger_intake)
            challenger_thesis_path = self.object_writer.write_validation_result(source.report_id + "__challenger_alpha_thesis", challenger_thesis)
            result.update({
                "challenger_intake_path": challenger_intake_path,
                "challenger_report_map_path": challenger_report_map_path,
                "challenger_thesis_path": challenger_thesis_path,
            })
            self.registry.update_status(source.report_id, "dual_route_ready", **result)
        else:
            self.registry.update_status(source.report_id, "report_map_ready", **result)
        result["status"] = "dual_route_ready" if challenger_response_text else "report_map_ready"
        return result
