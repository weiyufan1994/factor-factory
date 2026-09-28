"""Independent engineering invariants, not search-quality acceptance tests."""

from dataclasses import replace
from math import exp, isfinite

import pytest

from factor_factory.hybrid_research.gp_adapter import (
    KernelTerm, ResponseProgram, evaluate_program, run_response_gp,
)
from factor_factory.hybrid_research.synthetic import FitData
from factor_factory.hybrid_research.variation import DerivationScope


def _scope():
    return DerivationScope(
        derivation_ref="independent:response-invariants",
        mathematical_object="causal kernels",
        domain="finite signed impulses",
        initial_state="zero",
        clock="event",
        missing_value_policy="missing is not zero",
        observation_map="signed J to y",
        allowed_transformations=("causal convolution", "linear superposition"),
        distinguishing_predictions=("Positive-rate modes decay; zero-rate modes persist",),
        current_gap="响应尺度尚不确定",
        allowed_response_families=(
            "transient_exponential_kernel", "permanent_component", "two_scale_superposition",
        ),
        allowed_research_actions=("parameter_search", "structure_search"),
    )


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("attempt_limit", (1, 2, 5, 13, 32))
@pytest.mark.parametrize("evaluation_limit", (1, 3, 7, 16))
def test_budget_elitism_lineage_and_replay(seed, attempt_limit, evaluation_limit):
    # Deliberately no recovery threshold or hidden model supplied to the search.
    data = FitData((1., -.5, 0., 2., 0., -1.), (.8, .1, -.1, 1.4, .3, -.7), 1.)
    kwargs = dict(
        scope=_scope(), fit_data=data, allowed_rates=(0., .01, .4, 2.),
        allowed_scales=(-.7, .3, 1.), seed=seed, generations=4,
        population_size=6, max_attempts=attempt_limit, max_evaluations=evaluation_limit,
    )
    result = run_response_gp(**kwargs)
    assert result == run_response_gp(**kwargs)
    assert len(result.trace) == result.attempt_count <= attempt_limit
    finite = [row for row in result.trace if row.loss is not None]
    assert len(finite) == result.evaluated_count <= evaluation_limit
    assert result.selected is not None
    assert result.selected.loss == min(row.loss for row in finite)
    assert all(isfinite(row.loss) for row in finite)
    seen = set()
    for row in result.trace:
        assert set(row.parents) <= seen
        assert row.candidate_id not in seen
        seen.add(row.candidate_id)
        assert row.status in {"kept", "rejected"}
        if row.program is not None:
            assert all(
                term.decay_rate in kwargs["allowed_rates"]
                and term.scale in kwargs["allowed_scales"]
                for term in row.program.terms
            )
    if result.evaluated_count == evaluation_limit:
        assert result.stop_reason == "evaluation_budget_exhausted"
    elif result.attempt_count == attempt_limit:
        assert result.stop_reason == "attempt_budget_exhausted"


@pytest.mark.parametrize("step", (.05, 1., 3.))
def test_signed_mixed_kernel_matches_explicit_convolution_and_preserves_prefix(step):
    program = ResponseProgram((KernelTerm(.7, .2), KernelTerm(-.3, 0.)))
    impulses = (1., -.5, 0., 2., 0., -1.)
    data = FitData(impulses, (0.,) * len(impulses), step)
    actual = evaluate_program(program, data)
    expected = tuple(
        sum(impulses[k] * (.7 * exp(-.2 * step * (t-k)) - .3) for k in range(t+1))
        for t in range(len(impulses))
    )
    assert actual == pytest.approx(expected, abs=1e-12)
    changed = replace(data, signed_impulses=impulses[:4] + (999., -999.))
    assert evaluate_program(program, changed)[:4] == actual[:4]
    reversed_data = replace(data, signed_impulses=tuple(-v for v in impulses))
    assert evaluate_program(program, reversed_data) == pytest.approx(tuple(-v for v in actual))
