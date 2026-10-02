"""Independent W11 engineering checks, not research or real Step2 evidence.

The author fixture helper is reused only to serialize an explicitly synthetic
package. Its tiny source/spec stubs do NOT stand for researcher execution.
No W11 target response or comparison result is consumed here.
"""

from dataclasses import asdict, replace
import os
from pathlib import Path
from random import Random
import subprocess
import sys

import pytest

import factor_factory.hybrid_research.gp_adapter as gp
import factor_factory.hybrid_research.proposal_comparison as comparison
from test_hybrid_proposal_comparison_author import _write_package


def _package(tmp_path):
    return comparison.load_development_package(_write_package(tmp_path))


@pytest.mark.parametrize("field", ["training_indexes", "score_indexes"])
def test_public_comparison_never_accepts_an_implicit_expanding_window(tmp_path, field):
    path = _write_package(
        tmp_path,
        mutate=lambda value: value["response_semantics"].update({field: []}),
    )
    with pytest.raises(comparison.ComparisonContractError, match="explicit nonempty"):
        comparison.load_development_package(path)


@pytest.mark.parametrize("field", ["training_indexes", "score_indexes"])
def test_direct_api_cannot_reintroduce_an_expanding_window(tmp_path, monkeypatch, field):
    package = _package(tmp_path)
    package = replace(package, semantics=replace(package.semantics, **{field: ()}))

    def no_proposer(*args, **kwargs):
        pytest.fail("a proposer ran with an implicit fitting/scoring window")

    monkeypatch.setattr(comparison, "_run_simple", no_proposer)
    monkeypatch.setattr(comparison, "_run_gp", no_proposer)
    with pytest.raises(comparison.ComparisonContractError, match="explicit"):
        comparison.run_development_comparison(package, enabled=True)


@pytest.mark.parametrize(
    "change",
    [
        {"allowed_response_families": ("transient_exponential_kernel", "two_scale_superposition")},
        {"observation_map": "an unsupported observation bridge"},
        {"initial_state": "zero"},
        {"allowed_transformations": ("linear superposition",)},
        {"allowed_research_actions": ("structure_search",)},
    ],
)
def test_both_arms_reject_the_same_invalid_scope_before_fitting(tmp_path, monkeypatch, change):
    package = _package(tmp_path)
    package = replace(package, scope=replace(package.scope, **change))

    def no_fit(*args, **kwargs):
        pytest.fail("fitting began before the shared scope was accepted")

    monkeypatch.setattr(comparison, "fit_response_program", no_fit)
    monkeypatch.setattr(gp, "fit_response_program", no_fit)
    with pytest.raises(ValueError):
        comparison.run_development_comparison(package, enabled=True)


@pytest.mark.parametrize("invalid", ["training_outside", "score_outside_training", "retention_outside"])
def test_invalid_common_semantics_are_not_charged_as_candidate_failures(tmp_path, monkeypatch, invalid):
    package = _package(tmp_path)
    if invalid == "training_outside":
        package = replace(package, semantics=replace(
            package.semantics, training_indexes=tuple(range(9)), score_indexes=tuple(range(9))
        ))
    elif invalid == "score_outside_training":
        package = replace(package, semantics=replace(
            package.semantics, training_indexes=(0, 1, 2), score_indexes=(3,)
        ))
    else:
        package = replace(package, allowed_rates=(0.2, 0.6, 1.2))

    def no_fit(*args, **kwargs):
        pytest.fail("invalid common inputs reached a candidate fit")

    monkeypatch.setattr(comparison, "fit_response_program", no_fit)
    monkeypatch.setattr(gp, "fit_response_program", no_fit)
    with pytest.raises(ValueError):
        comparison.run_development_comparison(package, enabled=True)


def test_both_strategies_use_the_same_fitter_domain_and_count_real_calls(tmp_path, monkeypatch):
    package = _package(tmp_path)
    calls = {"simple_seeded_nonadaptive": [], "response_gp": []}
    fitter = gp.fit_response_program
    assert comparison.fit_response_program is fitter

    def capture(arm):
        def fit(program, data, semantics):
            assert data is package.fit_data
            assert semantics is package.semantics
            calls[arm].append(program)
            return fitter(program, data, semantics)
        return fit

    monkeypatch.setattr(comparison, "fit_response_program", capture("simple_seeded_nonadaptive"))
    monkeypatch.setattr(gp, "fit_response_program", capture("response_gp"))
    result = comparison.run_development_comparison(package, enabled=True)
    domain = set(comparison._program_universe(package))
    for name, actual in calls.items():
        matching = [arm for arm in result.arms if arm.proposer == name]
        assert len(actual) == sum(arm.actual_fit_evaluations for arm in matching)
        assert set(actual) <= domain
        for arm in matching:
            assert arm.actual_fit_evaluations <= arm.proposal_attempts <= package.budget.max_attempts
            assert arm.search.evaluated_count <= package.budget.max_evaluations
            assert arm.actual_fit_evaluations == arm.search.evaluated_count + arm.failed_attempts
            assert arm.search.selected.fit.training_indexes == package.semantics.training_indexes


def test_simple_proposal_order_does_not_adapt_to_the_observed_response(tmp_path):
    package = _package(tmp_path)
    changed = replace(package, fit_data=replace(
        package.fit_data, observed_response=tuple(-10.0 * y + 7.0 for y in package.fit_data.observed_response)
    ))
    first = comparison._run_simple(package, 101)
    second = comparison._run_simple(changed, 101)
    assert [row.program for row in first.search.trace] == [row.program for row in second.search.trace]
    assert first.proposal_attempts == second.proposal_attempts


def test_confirmation_never_reaches_training_rows_or_changes_selection(tmp_path, monkeypatch):
    package = _package(tmp_path)
    result = comparison.run_development_comparison(package, enabled=True)
    before = asdict(result)
    original = comparison.fit_response_program
    fits = []
    development_size = len(package.fit_data.observed_response)

    def inspect(program, data, semantics):
        assert semantics.training_indexes
        assert max(semantics.training_indexes) < development_size
        assert max(semantics.score_indexes) < development_size
        fit = original(program, data, semantics)
        fits.append(fit)
        return fit

    monkeypatch.setattr(comparison, "fit_response_program", inspect)
    for observed in [(0.0, 0.0), (1234.0, -4321.0)]:
        comparison.score_confirmation_after_selection(
            package=package, development=result,
            proposer="response_gp", seed=101,
            continuation_impulses=(-1.0, 1.0), confirmation_observed_response=observed,
        )
    assert fits[0].coefficients == fits[1].coefficients
    assert fits[0].prediction == fits[1].prediction
    assert asdict(result) == before


def test_mismatched_development_identity_cannot_be_scored(tmp_path, monkeypatch):
    package = _package(tmp_path)
    result = comparison.run_development_comparison(package, enabled=True)
    wrong = replace(result, package_hash="not-the-selected-package")

    def no_fit(*args, **kwargs):
        pytest.fail("a mismatched selection reached confirmation fitting")

    monkeypatch.setattr(comparison, "fit_response_program", no_fit)
    with pytest.raises(comparison.ComparisonContractError, match="does not bind"):
        comparison.score_confirmation_after_selection(
            package=package, development=wrong, proposer="response_gp", seed=101,
            continuation_impulses=(0.0,), confirmation_observed_response=(0.0,),
        )


def _strict_package(tmp_path):
    package = _package(tmp_path)
    semantics = replace(
        package.semantics,
        initial_state="zero", direct_input="profiled_same_event",
        memory_rate_policy="strict_increasing_unique",
    )
    scope = replace(
        package.scope, initial_state="zero",
        allowed_response_families=(
            "transient_exponential_kernel", "two_scale_superposition",
            "direct_input_component", "zero_memory_component",
        ),
    )
    return replace(
        package, semantics=semantics, scope=scope,
        allowed_rates=tuple(index / 10 for index in range(1, 10)),
    )


def _closed_response(inputs, rates, gains, *, intercept, direct):
    """Definition-based oracle; no production recursive helper is used."""
    return tuple(
        intercept + direct * inputs[t] + sum(
            gain * sum(inputs[s] * rate ** (t - s) for s in range(t + 1))
            for gain, rate in zip(gains, rates)
        )
        for t in range(len(inputs))
    )


@pytest.mark.parametrize("rates,gains", [((), ()), ((0.2,), (1.25,)), ((0.2, 0.8), (1.25, -0.75))])
def test_k0_k1_k2_fit_the_independent_math_with_a_separate_direct_channel(tmp_path, rates, gains):
    package = _strict_package(tmp_path)
    expected = _closed_response(
        package.fit_data.signed_impulses, rates, gains, intercept=0.75, direct=-0.5
    )
    data = replace(package.fit_data, observed_response=expected)
    program = gp.ResponseProgram(tuple(gp.KernelTerm(1.0, rate) for rate in rates))
    fit = gp.fit_response_program(program, data, package.semantics)
    assert fit.prediction == pytest.approx(expected, abs=1e-11)
    coefficients = dict(fit.coefficients)
    assert coefficients["intercept"] == pytest.approx(0.75, abs=1e-11)
    assert coefficients["direct_input"] == pytest.approx(-0.5, abs=1e-11)
    for index, gain in enumerate(gains):
        assert coefficients[f"component_gain_{index}"] == pytest.approx(gain, abs=1e-11)
    assert fit.design_rank == len(rates) + 2
    assert len(fit.design_columns) == len(rates) + 2
    assert not fit.unidentified_coefficients


def test_the_strict_shared_domain_contains_exactly_46_canonical_programs(tmp_path):
    package = _strict_package(tmp_path)
    programs = comparison._program_universe(package)
    expected = {()}
    expected.update((rate,) for rate in package.allowed_rates)
    expected.update((a, b) for a in package.allowed_rates for b in package.allowed_rates if a < b)
    actual = [tuple(term.decay_rate for term in program.terms) for program in programs]
    assert len(actual) == len(set(actual)) == 46
    assert set(actual) == expected
    result = comparison.run_development_comparison(package, enabled=True)
    for arm in result.arms:
        for candidate in arm.search.trace:
            if candidate.program is not None:
                assert tuple(term.decay_rate for term in candidate.program.terms) in expected


@pytest.mark.parametrize("rates", [(0.8, 0.2), (0.2, 0.2), (0.0,), (1.0,)])
def test_strict_fitter_does_not_admit_reversed_duplicate_or_boundary_memory_rates(tmp_path, rates):
    package = _strict_package(tmp_path)
    program = gp.ResponseProgram(tuple(gp.KernelTerm(1.0, rate) for rate in rates))
    with pytest.raises(ValueError):
        gp.fit_response_program(program, package.fit_data, package.semantics)


def test_new_zero_memory_case_does_not_silently_become_a_legacy_program(tmp_path):
    package = _package(tmp_path)
    with pytest.raises(ValueError, match="zero-memory"):
        gp.fit_response_program(gp.ResponseProgram(()), package.fit_data, package.semantics)


def test_direct_channel_and_two_states_continue_without_refitting_confirmation(tmp_path):
    package = _strict_package(tmp_path)
    rates, gains = (0.2, 0.8), (1.25, -0.75)
    impulses = package.fit_data.signed_impulses + (-1.0, 1.0, 0.0, 0.0)
    expected = _closed_response(impulses, rates, gains, intercept=0.75, direct=-0.5)
    observed = expected[:8] + (99.0, -99.0, 77.0, -77.0)
    data = replace(package.fit_data, signed_impulses=impulses, observed_response=observed)
    fit = gp.fit_response_program(
        gp.ResponseProgram(tuple(gp.KernelTerm(1.0, rate) for rate in rates)),
        data, package.semantics,
    )
    assert fit.prediction == pytest.approx(expected, abs=1e-11)
    assert fit.training_indexes == tuple(range(8))
    assert fit.continuation_indexes == (8, 9, 10, 11)


def test_direct_channel_does_not_consume_a_memory_scale_or_force_tail_sign(tmp_path):
    package = _strict_package(tmp_path)
    impulses = (1.0,) + (0.0,) * 7
    expected = _closed_response(impulses, (0.6,), (1.0,), intercept=0.0, direct=-2.0)
    data = replace(package.fit_data, signed_impulses=impulses, observed_response=expected)
    fit = gp.fit_response_program(
        gp.ResponseProgram((gp.KernelTerm(1.0, 0.6),)), data, package.semantics
    )
    assert fit.prediction == pytest.approx((-1.0, 0.6, 0.36, 0.216, 0.1296, 0.07776, 0.046656, 0.0279936))
    assert fit.design_rank == 3  # One memory state, plus intercept and direct gain.
    assert dict(fit.coefficients)["direct_input"] == pytest.approx(-2.0)


@pytest.mark.parametrize("seed", [11, 101, 211])
def test_legacy_gp_keeps_its_frozen_sample_order_when_new_domain_is_not_selected(tmp_path, seed):
    package = _package(tmp_path)
    terms = [gp.KernelTerm(scale, rate) for scale in package.allowed_scales for rate in package.allowed_rates]
    # Independent reconstruction of the frozen pre-W11 initialization, not a
    # repeat of a historical efficacy experiment or a call to old executable code.
    order = Random(seed).sample(range(len(terms)), k=3)
    expected = [gp.ResponseProgram((terms[index],)) for index in order]
    result = gp.run_response_gp(
        scope=package.scope, fit_data=package.fit_data,
        allowed_rates=package.allowed_rates, allowed_scales=package.allowed_scales,
        seed=seed, generations=1, population_size=3,
        max_evaluations=6, max_attempts=8, response_semantics=package.semantics,
    )
    actual = [row.program for row in result.trace if row.operation == "initialize_structure"]
    assert actual == expected


@pytest.mark.parametrize("change", [
    {"training_indexes": list(range(9)), "score_indexes": list(range(9))},
    {"training_indexes": [0, 1, 2], "score_indexes": [3]},
])
def test_validation_only_load_does_not_call_an_invalid_common_window_valid(tmp_path, change):
    path = _write_package(
        tmp_path, mutate=lambda value: value["response_semantics"].update(change)
    )
    with pytest.raises(comparison.ComparisonContractError):
        comparison.load_development_package(path)


def test_cli_uses_its_selected_checkout_without_a_pythonpath_workaround(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/run_hybrid_proposal_comparison.py"
    process_environment = dict(os.environ)
    process_environment.pop("PYTHONPATH", None)
    process_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(script), "--help"], cwd=tmp_path,
        env=process_environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "--execute-development" in result.stdout
