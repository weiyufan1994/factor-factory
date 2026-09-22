from __future__ import annotations

import importlib.util
from pathlib import Path


def _step6():
    path = Path(__file__).resolve().parents[1] / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("reviewed_failure_projection_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _iteration():
    return {
        "main_agent_mechanism_memo_ref": {"contract_version": "factorforge_main_agent_mechanism_memo_v1"},
        "research_judgment": {"decision": "reject", "research_memo": {"mechanism_analysis": {
            "formula_specific_derivation": {
                "mathematical_object": "unsigned event residue",
                "observation_mapping": "zero-atom path projection",
                "observed_metric_comparison": "Same-sample controlled association disappears.",
                "metric_feedback_to_model": "Direction-reflection leaves the score unchanged; future signed repair changes sign.",
                "revision_implication": "Close this realization without tuning; signed-state alternatives remain untested.",
            }
        }}},
        "knowledge_writeback": {"failure_patterns": ["Negative net account."]},
    }


def test_rejected_case_keeps_real_reviewed_failure_reasoning():
    result = _step6()._knowledge_reuse_projection(_iteration())
    assert len(result["failure_patterns"]) == 3
    assert result["failure_patterns"][0] == "Negative net account."
    assert "Direction-reflection" in result["failure_patterns"][2]
    assert "not causal identification or generalization" in result["failure_patterns"][2]
    assert result["modification_hypotheses_status"] == "candidate_not_verified"
    assert result["modification_hypotheses"] == [
        "Future questions only; no automatic revision: Close this realization without tuning; signed-state alternatives remain untested."
    ]


def test_missing_main_agent_derivation_does_not_upgrade_failure_interpretation():
    data = _iteration()
    data.pop("main_agent_mechanism_memo_ref")
    result = _step6()._knowledge_reuse_projection(data)
    assert "failure_patterns" not in result


def test_non_reject_is_not_reclassified_by_failure_projection():
    data = _iteration()
    data["research_judgment"]["decision"] = "needs_human_review"
    assert "failure_patterns" not in _step6()._knowledge_reuse_projection(data)


def test_authored_economics_supersedes_unverified_style_template():
    data = _iteration()
    analysis = data["research_judgment"]["research_memo"]["mechanism_analysis"]
    analysis.update({"factor_family": "liquidity_shock", "return_source": "unknown"})
    analysis["formula_specific_derivation"]["profit_payer_derivation"] = {
        "economic_hypothesis_source": "Temporary signed pressure; payer remains unidentified.",
        "factor_family": "liquidity_shock",
    }
    result = _step6()._knowledge_reuse_projection(data)
    assert result["return_source_hypothesis"] == "Temporary signed pressure; payer remains unidentified."
    assert result["factor_family"] == "liquidity_shock"
    assert result["monetization_model"] == "unknown"
    assert result["bias_type"] == "unidentified"
    assert result["expected_failure_regimes"] == []
    assert result["constraint_sources"] == []
    assert result["objective_constraint_dependency"] == "unknown"
    data.pop("main_agent_mechanism_memo_ref")
    assert "return_source_hypothesis" not in _step6()._knowledge_reuse_projection(data)


def test_explicit_variant_and_replication_status_are_projected_without_template_inference():
    data = _iteration()
    derivation = data["research_judgment"]["research_memo"]["mechanism_analysis"]["formula_specific_derivation"]
    derivation.update({
        "research_variant": "EVENT_U_DIRECT_CODE_EXTENSION",
        "paper_replication_status": "NOT_PF_VV_REPLICATION",
        "expected_failure_regimes": ["signed-state mapping fails"],
        "constraint_sources": ["observed intraday coverage"],
        "objective_constraint_dependency": "unknown",
    })
    result = _step6()._knowledge_reuse_projection(data)
    assert result["research_variant"] == "EVENT_U_DIRECT_CODE_EXTENSION"
    assert result["paper_replication_status"] == "NOT_PF_VV_REPLICATION"
    assert result["expected_failure_regimes"] == ["signed-state mapping fails"]
    assert result["constraint_sources"] == ["observed intraday coverage"]


def test_token_routing_without_authored_memo_does_not_claim_style_or_known_payer():
    bundle = {
        "factor_run_master": {"factor_id": "liquidity_probe", "report_id": "R1"},
        "factor_case_master": {"factor_id": "liquidity_probe", "report_id": "R1"},
        "factor_spec_master": {"canonical_spec": {"required_inputs": ["liquidity"]}},
    }
    framework = _step6().infer_research_framework(bundle, {}, "reject")
    assert framework["factor_family"] == "unknown"
    assert framework["monetization_model"] == "unknown"
    assert framework["bias_type"] == "unknown"
    assert framework["return_source_hypothesis"] == "unknown"
    assert framework["expected_failure_regimes"] == []
    assert framework["constraint_sources"] == []
    assert framework["crowding_risk"] == "unknown"
    assert framework["capacity_constraints"] == "unknown"
