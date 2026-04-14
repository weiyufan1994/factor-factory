from __future__ import annotations

from ..intake.pdf_skill_client import PdfSkillClient
from ..intake.structured_intake_contract import StructuredIntake


class ChallengerRunner:
    def __init__(self, pdf_skill_client: PdfSkillClient):
        self.pdf_skill_client = pdf_skill_client

    def parse_challenger_response(self, report_id: str, response_text: str) -> StructuredIntake:
        return self.pdf_skill_client.parse_response(report_id, response_text)
