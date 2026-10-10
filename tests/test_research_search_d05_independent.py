"""Independent B1 checks: explicit numeric loops, not the Formula evaluator.

Synthetic engineering evidence only. The fixture is an estimator family, not
an economic/alpha claim or a reviewed market-study induction.
"""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from factor_factory.research_search.formula_bridge import compile_candidate, compute_candidate
from factor_factory.research_search.generator import (
    ExpressionCandidate, crossover_candidates, evaluate_candidate,
    generate_population, mutate_candidate,
)
from factor_factory.research_search.induction import (
    FieldSpec, ForwardInductionRecord, InductionScope, SemanticType, Unit,
)
from factor_factory.research_search.typed_ast import ASTNode


def scope():
    observed = SemanticType("panel", "numeric", Unit.dimensionless(),
                            "synthetic_session", "instrument_ts", "available_by_t")
    observation = "Synthetic x and y indexed by instrument and observation time."
    record = ForwardInductionRecord(
        record_id="independent-b1-affine", origin="synthetic_fixture",
        source_ref="synthetic://independent-b1/forward-derivation",
        assumptions=("x and y are observed by t; kernels have finite nonnegative lags.",),
        key_derivation_steps=(
            "g_t=b+sum_j sum_{k>=0} w_{j,k} x_{j,t-k} with fixed coefficients.",
            "Delay shifts k and a trailing mean convolves weights with a causal uniform kernel.",
            "Addition and constant scaling preserve affine structure on complete windows.",
            "Variable products and variable denominators are outside this derived family.",
        ),
        parent_delta=(), observation_map=observation,
        response_family="causal_affine_response_estimator", response_constraint="causal_affine",
        grammar_productions=("field", "constant", "plus", "minus", "multiply", "divide", "delay", "mean"),
        conclusions=("The estimator is causal; no return direction follows from this algebra.",),
        falsifiers=("A future perturbation changes an earlier estimator output.",),
        review_decision="proceed", data_exposure="synthetic_only",
    )
    return InductionScope(
        induction_id="independent-b1", parent_induction_id=None, induction_record=record,
        response_family=record.response_family, mathematical_object="causal affine estimator",
        observation_map=observation, allowed_fields=(FieldSpec("x", observed), FieldSpec("y", observed)),
        output_type=observed,
        allowed_operators=("plus", "minus", "multiply", "divide", "delay", "mean"),
        allowed_constants=(-1.0, 0.0, 0.5, 1.0, 2.0), allowed_windows=(1, 2, 3), max_depth=4,
        missing_value_policy="full-window warmup and missing input remain NaN",
        numeric_domain="finite inputs and nonzero scalar denominators",
        change_class="in_family_parameter",
    )


def panel():
    days = pd.bdate_range("2020-01-02", periods=9)
    rows = []
    for instrument, offset in (("000001.SZ", 0.0), ("600000.SH", -2.0)):
        for i, day in enumerate(days):
            rows.append({"ts_code": instrument, "trade_date": day,
                         "x": np.nan if i == 3 else float(i % 4) + offset,
                         "y": np.nan if i == 6 else float((i * 3) % 5) - 1.0})
    return pd.DataFrame(rows).sample(frac=1, random_state=89).reset_index(drop=True)


def hand_evaluate(node, group):
    """Recurse over syntax; time transforms use explicit separate numeric loops."""
    if node.kind == "field":
        return group[str(node.value)].to_numpy(dtype=float)
    if node.kind in {"constant", "window"}:
        return float(node.value)
    args = [hand_evaluate(child, group) for child in node.children]
    left, right = args
    if node.value == "plus":
        return left + right
    if node.value == "minus":
        return left - right
    if node.value == "multiply":
        return left * right
    if node.value == "divide":
        return left / right
    width = int(right)
    output = np.full(len(group), np.nan)
    for i in range(len(group)):
        if node.value == "delay" and i >= width:
            output[i] = left[i - width]
        elif node.value == "mean" and i >= width - 1:
            window = left[i - width + 1:i + 1]
            if not np.isnan(window).any():
                output[i] = sum(window) / width
    return output


def expected_frame(root, frame):
    rows = []
    ordered = frame.sort_values(["ts_code", "trade_date"])
    for instrument, group in ordered.groupby("ts_code", sort=False):
        values = hand_evaluate(root, group)
        rows.extend((day, instrument, value) for day, value in zip(group.trade_date, values))
    result = pd.DataFrame(rows, columns=["datetime", "instrument", "factor_value"])
    return result.set_index(["datetime", "instrument"]).sort_index().astype("float64")


@pytest.mark.parametrize("seed", range(6))
def test_generated_mutated_and_crossed_trees_match_independent_numeric_oracle(seed):
    derived = scope()
    frame = panel()
    before = frame.copy(deep=True)
    result = generate_population(derived, seed=seed, population_size=10, max_attempts=80)
    assert len(result.candidates) == 10
    candidates = list(result.candidates)
    for i, parent in enumerate(result.candidates):
        mutation, _ = mutate_candidate(parent, derived, seed=i + seed, candidate_id=f"m-{seed}-{i}")
        cross, _ = crossover_candidates(parent, result.candidates[(i + 1) % 10], derived,
                                         seed=i + seed, candidate_id=f"c-{seed}-{i}")
        candidates.extend(child for child in (mutation, cross) if child is not None)
    assert len(candidates) > 10  # actual changed trees, not only the initial queue
    for candidate in candidates:
        compiled = compile_candidate(candidate, derived, available_columns=list(frame.columns))
        actual = compute_candidate(compiled, {"daily_df": frame})
        pd.testing.assert_frame_equal(actual, expected_frame(candidate.root, frame),
                                      check_freq=False, rtol=1e-12, atol=1e-12)
        assert actual.index.names == ["datetime", "instrument"]
        assert list(actual.columns) == ["factor_value"]
        pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("invalid", [
    ASTNode.operator("multiply", ASTNode.field("x"), ASTNode.field("x")),
    ASTNode.operator("divide", ASTNode.field("x"), ASTNode.field("y")),
    ASTNode.operator("divide", ASTNode.field("x"), ASTNode.constant(0.0)),
    ASTNode.operator("multiply", ASTNode.field("x"), ASTNode.window(3)),
    ASTNode.operator("mean", ASTNode.field("x"), ASTNode.window(-1)),
])
def test_invalid_math_never_reaches_even_a_tempting_fitness(invalid):
    derived = scope()
    candidate = ExpressionCandidate("bad", invalid, derived.response_family,
                                    derived.scope_hash, 0, (), "proposed", ("expression_subtree",))
    calls = []
    with pytest.raises(ValueError):
        evaluate_candidate(candidate, derived, lambda c: calls.append(c) or 1000.0)
    assert calls == []


def test_real_zero_missingness_negative_coefficient_and_future_invariance():
    derived = scope()
    frame = panel()
    # Direct independent arithmetic check: zero stays zero; 0 * NaN remains NaN.
    root = ASTNode.operator("multiply", ASTNode.field("x"), ASTNode.constant(0.0))
    candidate = ExpressionCandidate("zero", root, derived.response_family, derived.scope_hash,
                                    0, (), "manual_oracle", ("parameter",))
    compiled = compile_candidate(candidate, derived, available_columns=list(frame.columns))
    zero = compute_candidate(compiled, {"daily_df": frame}).factor_value
    assert zero.isna().sum() == 2
    assert (zero.dropna() == 0).all()
    root = ASTNode.operator("plus", ASTNode.operator("delay", ASTNode.field("x"), ASTNode.window(2)),
                            ASTNode.operator("multiply", ASTNode.field("y"), ASTNode.constant(-1.0)))
    candidate = replace(candidate, candidate_id="negative-causal", root=root)
    compiled = compile_candidate(candidate, derived, available_columns=list(frame.columns))
    actual = compute_candidate(compiled, {"daily_df": frame})
    pd.testing.assert_frame_equal(actual, expected_frame(root, frame), check_freq=False)
    cutoff = frame.trade_date.sort_values().unique()[4]
    changed = frame.copy()
    changed.loc[changed.trade_date > cutoff, ["x", "y"]] = 987654.0
    revised = compute_candidate(compiled, {"daily_df": changed})
    earlier = actual.index.get_level_values("datetime") <= cutoff
    pd.testing.assert_frame_equal(actual.loc[earlier], revised.loc[earlier])


@pytest.mark.parametrize("algorithm", ["gp", "mcts"])
def test_search_fitness_uses_real_factor_values_and_each_tree_is_evaluated_once(algorithm):
    from factor_factory.research_search.generator import run_expression_gp, run_expression_mcts

    derived = scope()
    days = pd.bdate_range("2020-01-02", periods=16)
    frame = pd.DataFrame({"ts_code": ["SYNTHETIC"] * 16, "trade_date": days,
                          "x": [float(i % 5 - 2) for i in range(16)],
                          "y": [float((i * 3) % 7 - 3) for i in range(16)]})
    target = frame.x.to_numpy() + 0.5 * frame.y.to_numpy()
    # Fixed common development window; no candidate-specific sample selection.
    # 12 warmup rows exceed any causal lag in this depth-4, max-window-3 grammar.
    calls = {}

    def loss(candidate):
        key = candidate.root.node_hash
        assert key not in calls, "same complete AST must reuse its previous result"
        compiled = compile_candidate(candidate, derived, available_columns=list(frame.columns))
        values = compute_candidate(compiled, {"daily_df": frame}).factor_value.to_numpy()
        assert np.isfinite(values[12:]).all()
        score = -float(np.mean((values[12:] - target[12:]) ** 2))
        calls[key] = score
        return score

    if algorithm == "gp":
        result = run_expression_gp(derived, evaluator=loss, seed=31, population_size=8,
                                   generations=3, max_attempts_per_generation=64)
        assert len(calls) <= 24
    else:
        result = run_expression_mcts(derived, evaluator=loss, seed=31, iterations=36)
        assert len(calls) <= 36
    assert calls and result.best_candidate is not None
    assert result.best_score == max(calls.values())
    assert result.best_score == calls[result.best_candidate.root.node_hash]
    assert all(row.score is None for row in result.trace if row.status == "rejected")
    assert all(value <= 0.0 for value in calls.values())


def test_mechanism_refutation_and_implementation_score_have_distinct_meanings():
    from factor_factory.research_search.mechanism import ExperimentEvidence, MechanismState, Prediction

    state = MechanismState(
        state_id="m0", mechanism="synthetic linear response", response_family="causal_affine_response_estimator",
        response_structure="constant-coefficient causal filter", induction_record_hash=scope().induction_record.record_hash,
        assumptions=("inputs observed by t",), predictions=(Prediction("p0", "no response before input", ("anticipation",)),),
        competing_mechanisms=("anticipation",), unknowns=(), implementation_scores=(-0.25,),
    )
    refutation = ExperimentEvidence("synthetic://refutation", "p0", "frozen-test", "refutes", True, True, 0.75)
    support = replace(refutation, evidence_ref="synthetic://support", outcome="supports")
    assert refutation.research_reward(state, "frozen-test") == support.research_reward(state, "frozen-test") == 0.75
    assert replace(refutation, protocol_id="different-test").research_reward(state, "frozen-test") is None
    assert replace(refutation, test_utility=None).research_reward(state, "frozen-test") is None
    assert state.mechanism_assessment == "unknown"  # a negative implementation score is not a refutation


@pytest.mark.parametrize("change", [
    {"mechanism": "a common cause drives x and the response"},
    {"add_assumptions": ("x is endogenous to an unobserved common shock",)},
])
def test_changed_economics_cannot_keep_old_response_label_to_skip_induction(change):
    from factor_factory.research_search.mechanism import MechanismState, Prediction, ResearchAction, run_mechanism_mcts

    derived = scope()
    state = MechanismState(
        state_id="m0", mechanism="x directly drives the response", response_family=derived.response_family,
        response_structure="affine filter", induction_record_hash=derived.induction_record.record_hash,
        assumptions=("x is exogenous",), predictions=(Prediction("p0", "no anticipation", ("common cause",)),),
        competing_mechanisms=("common cause",),
    )
    action = ResearchAction("changed-economics", "derive_new_structure", "explore", 1.0,
                            "new premise needs a new forward argument", **change)
    calls = []
    result = run_mechanism_mcts(initial_state=state, actions=(action,),
                               evaluator=lambda *args: calls.append(args),
                               protocol_id="p", seed=4, total_budget=1.0, max_expansions=1)
    assert calls == []
    assert result.decision == "needs_induction"


def test_parent_induction_with_an_old_delta_cannot_be_reused_as_a_fresh_induction():
    from factor_factory.research_search.mechanism import MechanismState, Prediction, ResearchAction, run_mechanism_mcts

    old = replace(scope().induction_record, record_id="already-used-child-record",
                  parent_delta=("the previous round expanded to a longer causal kernel",))
    state = MechanismState(
        state_id="child", mechanism="x directly drives the response", response_family=old.response_family,
        response_structure="affine filter", induction_record_hash=old.record_hash,
        assumptions=("x is exogenous",), predictions=(Prediction("p0", "no anticipation", ("common cause",)),),
        competing_mechanisms=("common cause",),
    )
    action = ResearchAction("new-cause", "derive_new_structure", "explore", 1.0,
                            "change the economic explanation, but incorrectly reuse the parent's record",
                            mechanism="a common cause drives both series", induction_record=old)
    calls = []
    run_mechanism_mcts(initial_state=state, actions=(action,), evaluator=lambda *args: calls.append(args),
                       protocol_id="p", seed=4, total_budget=1.0, max_expansions=1)
    assert calls == []
