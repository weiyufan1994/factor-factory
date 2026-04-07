from __future__ import annotations

from typing import Any, Dict


class Step1LlmRouter:
    def __init__(self, primary_client: Any = None, challenger_client: Any = None):
        self.primary_client = primary_client
        self.challenger_client = challenger_client

    def call_report_map(self, role: str, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: wire real model clients here
        return {
            "paper_id": payload["report_id"],
            "title": payload.get("title") or payload["report_id"],
            "builder_role": role,
            "prompt_name": "step1_report_ingestion.md",
            "section_map": [],
            "variables": [],
            "key_visual_elements": [],
            "notes": [f"stub llm router output for role={role}"],
        }
