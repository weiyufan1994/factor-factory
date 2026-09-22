from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_builder():
    path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "factor-forge-step6-researcher"
        / "scripts"
        / "build_researcher_packet.py"
    )
    spec = importlib.util.spec_from_file_location("build_researcher_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_researcher_memo_uses_current_factor_identity_not_alpha013_template():
    builder = _load_builder()
    memo = builder.build_researcher_memo(
        "ALPHA015_SWEEP_TURNPEN_A040_20160101",
        paths={},
        objects={
            "factor_spec_master": {
                "factor_id": "Alpha015",
                "canonical_spec": {
                    "formula_text": "(-1 * sum(rank(correlation(rank(high), rank(volume), 7)), 7))",
                    "formula_ir": {
                        "operator_set": ["rank", "correlation", "sum"],
                        "required_fields": ["high", "volume"],
                    },
                },
            },
            "factor_run_master": {"factor_id": "Alpha015"},
            "factor_case_master": {"factor_id": "Alpha015"},
            "factor_evaluation": {},
        },
        backend_payloads={},
    )

    current_attempt_fields = [
        memo["executive_summary"],
        memo["experience_chain"]["current_attempt_summary"],
        *memo["experience_chain"]["failed_branches_to_preserve"],
        *memo["experience_chain"]["what_future_agents_should_retrieve"],
        *memo["revision_taxonomy"]["macro_revision_options"],
        *memo["knowledge_to_write_back"]["success_lessons"],
    ]
    assert any("Alpha015" in field for field in current_attempt_fields)
    assert all("Alpha013" not in field for field in current_attempt_fields)
