from __future__ import annotations

import importlib.util
from pathlib import Path

IDENTITY = {
    "branch_id": "main",
    "run_id": "run_1",
    "spec_hash": "spec_a",
    "implementation_mode": "direct_code",
    "formula_hash": "formula_a",
    "code_hash": "code_a",
}


def _module():
    path = Path(__file__).resolve().parents[1] / "skills/factor-forge-step6/scripts/run_step6.py"
    spec = importlib.util.spec_from_file_location("local_terminal_rejection_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(monkeypatch):
    module = _module()
    journal = {"report_id": "R", "factor_id": "F", "producer": "factor-forge-researcher",
               "reflection": {"current_decision": "reject"}, "provenance": dict(IDENTITY)}
    review = {"report_id": "R", "factor_id": "F", "producer": "independent_researcher",
              "researcher_decision": "reject", "executive_summary": "Actual mechanism and net evidence reject this realization.",
              "formula_review": {"direction_loss": True}, "metric_review": {"net_return": -0.04},
              "revision_brief_to_step3b": {"should_modify": False}, "provenance": dict(IDENTITY)}
    monkeypatch.setenv("FACTORFORGE_LOCAL_IS_ONLY", "1")
    monkeypatch.setattr(module, "load_researcher_journal", lambda r: journal)
    monkeypatch.setattr(module, "load_researcher_agent_memo", lambda r: review)
    return module, journal, review


def test_concordant_local_rejection_can_end_metric_proposed_iteration(monkeypatch):
    module, _, _ = _inputs(monkeypatch)
    assert module.local_reviewers_agree_to_reject("R", "F", IDENTITY)


def test_hosted_path_unchanged(monkeypatch):
    module, _, _ = _inputs(monkeypatch)
    monkeypatch.delenv("FACTORFORGE_LOCAL_IS_ONLY")
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)


def test_disagreement_or_promotion_cannot_take_terminal_route(monkeypatch):
    module, journal, review = _inputs(monkeypatch)
    journal["reflection"]["current_decision"] = "promote_official"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    journal["reflection"]["current_decision"] = "reject"
    review["researcher_decision"] = "promote_official"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)


def test_foreign_template_or_arbitrary_authorship_cannot_take_terminal_route(monkeypatch):
    module, journal, review = _inputs(monkeypatch)
    review["report_id"] = "FOREIGN"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    review["report_id"] = "R"
    review["producer"] = "factor-forge-step6-researcher.build_researcher_packet"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    review["producer"] = "real_independent_researcher"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    review["producer"] = "independent_researcher"
    journal["producer"] = "arbitrary_local_writer"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)


def test_stale_journal_or_review_is_not_current_evidence(monkeypatch):
    module, journal, review = _inputs(monkeypatch)
    journal["provenance"]["run_id"] = "old_run"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    journal["provenance"]["run_id"] = IDENTITY["run_id"]
    journal["provenance"]["formula_hash"] = "old_formula"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    journal["provenance"]["formula_hash"] = IDENTITY["formula_hash"]
    review["provenance"]["run_id"] = "old_run"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    review["provenance"]["run_id"] = IDENTITY["run_id"]
    review["provenance"]["code_hash"] = "old_code"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)


def test_malformed_journal_review_or_identity_cannot_take_terminal_route(monkeypatch):
    module, journal, review = _inputs(monkeypatch)
    del journal["provenance"]
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    journal["provenance"] = dict(IDENTITY)
    journal["provenance"] = []
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    journal["provenance"] = dict(IDENTITY)
    review["provenance"] = "not-a-provenance-object"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    review["provenance"] = dict(IDENTITY)
    journal["reflection"] = "reject"
    assert not module.local_reviewers_agree_to_reject("R", "F", IDENTITY)
    journal["reflection"] = {"current_decision": "reject"}
    assert not module.local_reviewers_agree_to_reject("R", "F", {"branch_id": "main"})


def test_terminal_rejection_does_not_reopen_failed_realization():
    module = _module()
    original = {"primary_failure_signature": "cost_too_high", "revision_needed": True,
                "revision_hypotheses": [{"hypothesis": "legacy smoothing proposal"}]}
    strategy = module.terminal_local_rejection_strategy(original)
    assert strategy["revision_needed"] is False
    assert strategy["revision_hypotheses"] == []
    assert strategy["loop_authorization"] == "advisory_only"
    assert original["revision_needed"] is True
    policy = module.build_search_policy_decision("reject", {}, {}, {}, strategy, {})
    assert policy["recommended_mode"] == "kill"
    assert policy["branch_templates"] == []
    assert not module.should_write_step3b_handoff("reject", strategy, {}, policy)


def test_terminal_rejection_preserves_unresolved_evidence_quality():
    module = _module()
    for signature in ("implementation_suspect", "same_factor_identity_mismatch", "mechanism_unclear"):
        strategy = module.terminal_local_rejection_strategy({"primary_failure_signature": signature})
        assert strategy["revision_quality"] == "blocked"
        assert strategy["revision_needed"] is False


def _actual_authored_terminal_memo():
    return {
        "evidence_comparison": {
            "model_layer_review": {
                "equation_supported_by_metrics": "challenged",
                "failed_equation_component": "market_outcome_projection",
                "mechanism_fit": "contradicted",
                "return_source": "unknown",
                "interpretation": (
                    "The unsigned event statistic has no established bridge to directional future returns; "
                    "the observed loss is not a uniquely identified causal diagnosis."
                ),
            },
        },
    }


def _terminal_mechanism():
    return {
        "formula_specific_derivation": {
            "revision_implication": "Do not mutate this terminated realization automatically.",
            "mathematical_object": "event-pressure residual state",
            "formula_components": ["event_u", "robust_z"],
            "observation_mapping": "date-partitioned state to cross-sectional factor value",
        },
        "research_equation_review": {
            "reviewer_task": "research_equation_reviewer",
            "failed_equation_component": "observable_estimator",
            "revision_implication": "Legacy heuristic only.",
        },
    }


def test_authored_terminal_model_review_copies_actual_fields_and_preserves_legacy_heuristic():
    module = _module()
    mechanism = _terminal_mechanism()
    module.project_authored_terminal_model_review(
        mechanism, _actual_authored_terminal_memo()
    )
    equation = mechanism["research_equation_review"]
    assert equation["equation_supported_by_metrics"] == "challenged"
    assert equation["failed_equation_component"] == "market_outcome_projection"
    assert equation["authored_interpretation"].startswith("The unsigned event statistic")
    assert equation["causal_identification"] is False
    assert equation["legacy_metric_heuristic_not_causal_identification"] == {
        "failed_equation_component": "observable_estimator",
        "revision_implication": "Legacy heuristic only.",
    }
    assert mechanism["mechanism_fit"] == "contradicted"
    assert mechanism["return_source"] == "unknown"


def test_authored_terminal_model_review_rejects_support_or_promotion_language():
    module = _module()
    memo = _actual_authored_terminal_memo()
    memo["evidence_comparison"]["model_layer_review"]["equation_supported_by_metrics"] = "supported"
    try:
        module.project_authored_terminal_model_review(_terminal_mechanism(), memo)
    except ValueError as exc:
        assert str(exc) == "Invalid authored terminal model review"
    else:
        raise AssertionError("supportive authored review must not enter terminal rejection projection")


def test_authored_terminal_model_review_marks_program_as_unexecuted_evidence():
    module = _module()
    mechanism = _terminal_mechanism()
    module.project_authored_terminal_model_review(
        mechanism, _actual_authored_terminal_memo()
    )
    scope = mechanism["measurement_execution_scope"]
    assert scope["declared_program_is_not_execution_evidence"] is True
    assert scope["source"] == "validated_main_agent_formula_specific_derivation"
    assert scope["observed_mathematical_object"] == "event-pressure residual state"
