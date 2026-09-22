import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_step6_authored_failure_projection", ROOT / "skills/factor-forge-step6/scripts/run_step6.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_authored_risk_review_failure_regimes_are_projected_verbatim():
    memo = {"failure_and_risk_analysis": {"expected_failure_regimes": []}}
    authored = {"risk_review": {"failure_regimes": ["stress", "persistent information"]}}
    result = MODULE._project_authored_failure_regimes(memo, authored)
    assert result["failure_and_risk_analysis"]["expected_failure_regimes"] == ["stress", "persistent information"]


def test_missing_or_invalid_authored_regimes_remain_missing():
    cases = ({}, {"risk_review": {}}, {"risk_review": {"failure_regimes": "stress"}}, {"risk_review": {"failure_regimes": ["", 3]}})
    for authored in cases:
        memo = {"failure_and_risk_analysis": {"expected_failure_regimes": []}}
        result = MODULE._project_authored_failure_regimes(memo, authored)
        assert result["failure_and_risk_analysis"]["expected_failure_regimes"] == []


def test_real_knowledge_reuse_projection_preserves_reviewer_failure_hypotheses():
    iteration = {
        "main_agent_mechanism_memo_ref": {"contract_version": "factorforge_main_agent_mechanism_memo_v1"},
        "research_judgment": {"decision": "reject", "research_memo": {"mechanism_analysis": {
            "formula_specific_derivation": {"mathematical_object": "PF/VV dispersion", "observation_mapping": "daily path"},
        }, "researcher_agent_memo": {"risk_review": {"failure_regimes": ["stress", "persistent information"]}}}},
        "knowledge_writeback": {},
    }
    result = MODULE._knowledge_reuse_projection(iteration)
    assert result["expected_failure_regimes"] == ["stress", "persistent information"]


def _reviewer_projection_iteration(*, authored_writeback=None):
    authored_writeback = authored_writeback or {
        "factor_family": "pfvv_dispersion",
        "success_lessons": ["success lesson from reviewer"],
        "failure_lessons": ["failure lesson from reviewer"],
        "reusable_heuristics": ["heuristic from reviewer"],
        "revision_brief": {"research_question": "test the signed payer mapping"},
    }
    writeback = {
        "success_patterns": ["generic half variance claim"],
        "failure_patterns": ["generic sign/window scaffold"],
        "modification_hypotheses": ["generic widen sample"],
        "factor_family": "price_volume_correlation",
        "monetization_model": "generic",
        "bias_type": "generic",
        "return_source_hypothesis": "generic",
        "expected_failure_regimes": [],
        "objective_constraint_dependency": "unknown",
        "constraint_sources": [],
        "crowding_risk": "unknown",
        "capacity_constraints": "unknown",
        "implementation_risk": "unknown",
        "improvement_frontier": [],
        "program_search_axes": [],
        "review_checklist": [],
        "revision_principles": [],
        "research_commentary": "generic",
        "learning_and_innovation": {},
        "experience_chain": {},
        "revision_taxonomy": {},
        "program_search_policy": {},
        "diversity_position": {},
        "research_memo": {},
    }
    return {
        "report_id": "R-PFVV",
        "factor_id": "pfvv_factor",
        "iteration_no": 1,
        "created_at_utc": "2026-09-09T00:00:00Z",
        "main_agent_mechanism_memo_ref": {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1"
        },
        "research_judgment": {
            "decision": "iterate",
            "research_memo": {
                "mechanism_analysis": {
                    "factor_family": "price_volume_correlation",
                    "formula_specific_derivation": {
                        "mathematical_object": "PF/VV dispersion",
                        "observation_mapping": "daily path",
                    },
                },
                "researcher_agent_memo": {
                    "factor_family": "authored_pfvv_family",
                    "revision_brief_to_step3b": {
                        "hypothesis": "root authored revision question",
                        "specific_changes": ["change the signed mapping"],
                        "expected_metric_movement": "not a question/result",
                        "kill_criteria": ["do not survive the payer test"],
                    },
                    "knowledge_to_write_back": authored_writeback,
                    "program_search_policy": {
                        "exploit_branches": [
                            {"hypothesis": "exploit authored edge"}
                        ],
                        "explore_branches": [
                            {"research_question": "explore authored alternative"}
                        ],
                    },
                },
            },
        },
        "knowledge_writeback": writeback,
        "source_case_identity": {},
        "evidence_identity": {},
        "implementation_mode_decision": {},
        "decision_lineage": {},
        "knowledge_provenance": {},
    }


def test_build_knowledge_record_consumes_reviewer_lessons_not_generic_projection():
    record = MODULE.build_knowledge_record(_reviewer_projection_iteration())
    assert record["success_patterns"] == ["success lesson from reviewer"]
    assert record["failure_patterns"] == ["failure lesson from reviewer"]
    assert record["reusable_heuristics"] == ["heuristic from reviewer"]
    assert record["factor_family"] == "pfvv_dispersion"
    assert record["modification_hypotheses"] == [
        "test the signed payer mapping",
        "root authored revision question",
        "change the signed mapping",
        "exploit authored edge",
        "explore authored alternative",
    ]
    assert record["modification_hypotheses_future_only"] is True
    assert "generic half variance claim" not in record["success_patterns"]
    assert "generic widen sample" not in record["modification_hypotheses"]


def test_invalid_or_missing_reviewer_lessons_do_not_fabricate_replacements():
    record = MODULE.build_knowledge_record(
        _reviewer_projection_iteration(
            authored_writeback={
                "success_lessons": ["", 3],
                "failure_lessons": "not-a-list",
                "reusable_heuristics": [],
            }
        )
    )
    assert record["success_patterns"] == []
    assert record["failure_patterns"] == []
    assert record["reusable_heuristics"] == []
    assert record["factor_family"] == "authored_pfvv_family"
    assert record["modification_hypotheses"] == [
        "root authored revision question",
        "change the signed mapping",
        "exploit authored edge",
        "explore authored alternative",
    ]
