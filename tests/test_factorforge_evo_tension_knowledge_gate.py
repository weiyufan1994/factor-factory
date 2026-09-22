from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _step6_module():
    path = REPO_ROOT / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("factorforge_step6_tension_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iteration() -> dict:
    tension = {
        "contract_version": "factorforge_evo_transfer_tension_ledger_projection_v1",
        "diagnostic_contract_sha256": "a" * 64,
        "execution_result_ref": {
            "path": "objects/evo_v2/CHILD/evo_child_execution_result.json",
            "sha256": "b" * 64,
            "content_sha256": "c" * 64,
        },
        "tests": [
            {
                "test_id": "transfer_test_1",
                "mismatch_vector": None,
                "host_review_status": (
                    "HOST_REVIEW_REQUIRED_NOT_AUTOMATICALLY_ADJUDICATED"
                ),
            }
        ],
    }
    memo = {"mechanism_analysis": {"status": "bounded"}, "evo_transfer_tension_ledger": tension}
    return {
        "report_id": "CHILD",
        "factor_id": "factor",
        "iteration_no": 1,
        "evidence_summary": {"headline_metrics": {}},
        "research_judgment": {
            "decision": "reject",
            "strengths": [],
            "weaknesses": [],
            "risks": [],
            "factor_investing_framework": {},
            "research_memo": memo,
        },
        "knowledge_writeback": {
            "success_patterns": [],
            "failure_patterns": [],
            "modification_hypotheses": [],
            "factor_family": "test",
            "monetization_model": "test",
            "bias_type": "test",
            "return_source_hypothesis": "test",
            "expected_failure_regimes": [],
            "objective_constraint_dependency": {},
            "constraint_sources": [],
            "crowding_risk": {},
            "capacity_constraints": [],
            "implementation_risk": [],
            "improvement_frontier": [],
            "program_search_axes": [],
            "review_checklist": [],
            "revision_principles": [],
            "research_commentary": "test",
            "learning_and_innovation": {},
            "experience_chain": {},
            "revision_taxonomy": {},
            "program_search_policy": {},
            "diversity_position": {},
            "research_memo": memo,
        },
        "source_case_identity": {},
        "evidence_identity": {},
        "implementation_mode_decision": {},
        "decision_lineage": {},
        "knowledge_provenance": {},
        "created_at_utc": "2026-08-13T00:00:00Z",
    }


def test_unreviewed_evo_tension_is_not_reusable_knowledge() -> None:
    module = _step6_module()
    record = module.build_knowledge_record(_iteration())
    assert "evo_transfer_tension_ledger" not in record["research_memo"]
    gate = record["evo_transfer_tension_review_gate"]
    assert gate["status"] == "HOST_ADJUDICATION_REQUIRED_NOT_REUSABLE"
    assert gate["ordered_test_ids"] == ["transfer_test_1"]
    assert gate["reusable_as_analogy"] is False
    assert gate["canonical_memory_promotion_allowed"] is False
    assert gate["factor_acceptance_affected"] is False


def test_unreviewed_evo_tension_is_not_reusable_factor_record() -> None:
    module = _step6_module()
    record = module.build_factor_record(
        _iteration(),
        {"factor_case_master": {"final_status": "REJECT"}, "factor_run_master": {}},
    )
    assert "evo_transfer_tension_ledger" not in record["research_memo"]
    assert (
        record["evo_transfer_tension_review_gate"]["raw_tension_ledger_copied_to_knowledge"]
        is False
    )
