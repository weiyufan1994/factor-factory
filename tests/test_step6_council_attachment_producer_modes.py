from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/factor-forge-step6/scripts/attach_revision_council_to_step6.py"
SPEC = importlib.util.spec_from_file_location("step6_council_attachment_modes", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def _summary(producer: str | None) -> dict:
    return {
        "candidate_proposals": (
            [{"proposal_id": "p1", "producer": producer}] if producer else []
        ),
        "valid_agent_results": [],
        "blocked_proposals": [],
        "blocked_agent_results": [],
        "recommended_branch_templates": [],
        "human_approval_required": True,
    }


def test_attachment_mode_is_derived_from_real_producer_set():
    assert MODULE.council_producer_mode(_summary("real_agent")) == "agentic_dispatch_manifest"
    assert MODULE.council_producer_mode(_summary("local_mock_agentic_contract")) == "agentic_contract_mock"
    assert MODULE.council_producer_mode(_summary("deterministic_scaffold")) == "scaffold"
    assert MODULE.council_producer_mode(
        {
            **_summary("real_agent"),
            "valid_agent_results": [{"producer": "local_mock_agentic_contract"}],
        }
    ) == "mixed"


def test_all_three_attachment_outputs_use_the_same_mode():
    summary = _summary("real_agent")
    proposals = {"p1": {"proposal_id": "p1", "producer": "real_agent"}}
    ref = MODULE.build_revision_council_ref("R", summary, proposals)
    brief = MODULE.build_brief_council_summary("R", summary, proposals)
    markdown = MODULE.append_council_markdown("# Brief\n", summary, proposals)
    assert ref["mode"] == "agentic_dispatch_manifest"
    assert brief["mode"] == "agentic_dispatch_manifest"
    assert "- Council mode: agentic_dispatch_manifest" in markdown
