from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
import json

import pytest

import factor_factory.hybrid_research.proposal_comparison as comparison
from factor_factory.hybrid_research.proposal_comparison import (
    ComparisonContractError,
    load_development_package,
    run_development_comparison,
    score_confirmation_after_selection,
)
from factor_factory.hybrid_research.gp_adapter import (
    KernelTerm,
    ResponseProgram,
    fit_response_program,
)
from factor_factory.hybrid_research.response import ResponseSemantics
from factor_factory.hybrid_research.synthetic import FitData


def _write_package(tmp_path, *, mutate=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    problem = tmp_path / "problem.json"
    step2 = tmp_path / "step2.json"
    problem.write_text('{"question":"bounded response"}', encoding="utf-8")
    step2.write_text('{"decision":"supported","derivation":"d"}', encoding="utf-8")
    digest = lambda path: sha256(path.read_bytes()).hexdigest()
    payload = {
        "contract_version": "hybrid_proposal_comparison_v1",
        "status": "frozen_before_results",
        "task_id": "task-1",
        "problem_binding": {"path": "problem.json", "sha256": digest(problem)},
        "step2_binding": {"path": "step2.json", "sha256": digest(step2)},
        "fit_data": {
            "signed_impulses": [1, 0, -1, 1, 0, -1, 0, 1],
            "observed_response": [1.1, 0.5, -0.8, 0.7, 0.3, -0.9, -0.4, 0.8],
            "step": 1.0,
        },
        "derivation_scope": {
            "derivation_ref": "step2.json#derivation",
            "mathematical_object": "causal kernels",
            "domain": "finite signed impulses",
            "initial_state": "profiled_component",
            "clock": "event",
            "missing_value_policy": "missing is not zero",
            "observation_map": "signed J to y",
            "allowed_transformations": ["causal convolution", "linear superposition"],
            "distinguishing_predictions": ["one versus two decay scales"],
            "current_gap": "bounded response structure is unresolved",
            "allowed_response_families": [
                "transient_exponential_kernel", "permanent_component", "two_scale_superposition"
            ],
            "allowed_research_actions": ["parameter_search", "structure_search"],
        },
        "response_semantics": {
            "observation_timing": "same_event",
            "rate_parameterization": "retention",
            "pre_sample_input": "zero",
            "initial_state": "profiled_component",
            "intercept": "profiled",
            "direct_input": "zero",
            "gain_mode": "profiled_component",
            "gain_constraint": "unrestricted",
            "memory_rate_policy": "legacy_ordered_terms",
            "training_indexes": list(range(8)),
            "score_indexes": list(range(8)),
            "input_start_index": 0,
            "initial_state_start_index": 0,
            "initial_power_offset": 1,
        },
        "comparison_config": {
            "proposers": ["simple_seeded_nonadaptive", "response_gp"],
            "proposer_seeds": [101, 211],
            "allowed_rates": [0.2, 0.6, 1.0],
            "allowed_scales": [1.0],
            "generations": 1,
            "population_size": 3,
            "max_evaluations": 6,
            "max_attempts": 8,
        },
    }
    if mutate:
        mutate(payload)
    package = tmp_path / "package.json"
    package.write_text(json.dumps(payload), encoding="utf-8")
    return package


def test_public_package_requires_real_byte_bindings_and_forbids_answers(tmp_path):
    package = load_development_package(_write_package(tmp_path))
    assert package.problem_binding["sha256"]
    assert package.step2_binding["sha256"]

    forbidden = _write_package(
        tmp_path / "forbidden",
        mutate=lambda payload: payload.update(expected_winner="response_gp"),
    )
    with pytest.raises(ComparisonContractError, match="forbidden result fields"):
        load_development_package(forbidden)

    stale_path = _write_package(tmp_path / "stale")
    (stale_path.parent / "step2.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ComparisonContractError, match="stale"):
        load_development_package(stale_path)


def test_development_arms_share_inputs_fitter_domain_and_budget(tmp_path):
    package = load_development_package(_write_package(tmp_path))
    result = run_development_comparison(package, enabled=True)
    assert result.confirmation_status == "not_loaded_not_scored"
    assert len(result.arms) == 4
    assert {(row.proposer, row.seed) for row in result.arms} == {
        ("simple_seeded_nonadaptive", 101), ("response_gp", 101),
        ("simple_seeded_nonadaptive", 211), ("response_gp", 211),
    }
    for arm in result.arms:
        assert arm.actual_fit_evaluations == arm.search.evaluated_count <= 6
        assert arm.proposal_attempts == arm.search.attempt_count <= 8
        assert arm.elapsed_ns >= 0
        assert arm.search.selected is not None
        assert arm.search.selected.fit.training_indexes == tuple(range(8))
        assert arm.search.selected.fit.score_indexes == tuple(range(8))
    assert all(
        row.operation == "simple_seeded_proposal"
        for arm in result.arms if arm.proposer == "simple_seeded_nonadaptive"
        for row in arm.search.trace
    )
    assert any(
        row.operation in {"parameter_mutation", "structure_mutation_add", "structure_crossover"}
        for arm in result.arms if arm.proposer == "response_gp"
        for row in arm.search.trace
    )


def test_confirmation_is_loaded_only_after_selection_and_cannot_change_development(tmp_path):
    package = load_development_package(_write_package(tmp_path))
    development = run_development_comparison(package, enabled=True)
    frozen = asdict(development)
    low = score_confirmation_after_selection(
        package=package,
        development=development,
        proposer="response_gp",
        seed=101,
        continuation_impulses=(0.0, 1.0),
        confirmation_observed_response=(0.0, 0.0),
    )
    high = score_confirmation_after_selection(
        package=package,
        development=development,
        proposer="response_gp",
        seed=101,
        continuation_impulses=(0.0, 1.0),
        confirmation_observed_response=(100.0, -100.0),
    )
    assert asdict(development) == frozen
    assert low.selected_candidate_id == high.selected_candidate_id
    assert low.confirmation_mse != high.confirmation_mse
    assert low.coefficients_reproduced and high.coefficients_reproduced


def test_execution_is_opt_in_and_budget_or_semantics_cannot_be_silently_coerced(tmp_path):
    package = load_development_package(_write_package(tmp_path))
    with pytest.raises(ComparisonContractError, match="enabled=True"):
        run_development_comparison(package)

    oversized = _write_package(
        tmp_path / "oversized",
        mutate=lambda payload: payload["comparison_config"].update(max_attempts=33),
    )
    with pytest.raises(ComparisonContractError, match=r"\[1, 32\]"):
        load_development_package(oversized)

    fractional = _write_package(
        tmp_path / "fractional",
        mutate=lambda payload: payload["response_semantics"].update(input_start_index=1.5),
    )
    with pytest.raises(ComparisonContractError, match="integer"):
        load_development_package(fractional)


def test_frozen_package_rejects_implicit_full_window_before_confirmation_can_append(tmp_path):
    empty = _write_package(
        tmp_path,
        mutate=lambda payload: payload["response_semantics"].update(
            training_indexes=[], score_indexes=[]
        ),
    )
    with pytest.raises(ComparisonContractError, match="explicit nonempty"):
        load_development_package(empty)


def test_common_scope_preflight_runs_before_either_proposer(tmp_path, monkeypatch):
    package = load_development_package(_write_package(tmp_path))
    invalid_scope = replace(
        package.scope,
        allowed_response_families=("transient_exponential_kernel", "two_scale_superposition"),
    )
    invalid = replace(package, scope=invalid_scope)
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("a proposer ran before common preflight")

    monkeypatch.setattr(comparison, "_run_simple", forbidden)
    with pytest.raises(ValueError, match="permanent response"):
        run_development_comparison(invalid, enabled=True)
    assert called is False


def _strict_package(tmp_path):
    package = load_development_package(_write_package(tmp_path))
    impulses = package.fit_data.signed_impulses
    state = []
    value = 0.0
    for impulse in impulses:
        value = 0.4 * value + impulse
        state.append(value)
    observed = tuple(0.2 + 0.6 * impulse - 0.3 * memory for impulse, memory in zip(impulses, state))
    semantics = ResponseSemantics(
        observation_timing="same_event",
        rate_parameterization="retention",
        pre_sample_input="zero",
        initial_state="zero",
        intercept="profiled",
        direct_input="profiled_same_event",
        gain_mode="profiled_component",
        gain_constraint="unrestricted",
        memory_rate_policy="strict_increasing_unique",
        training_indexes=tuple(range(8)),
        score_indexes=tuple(range(8)),
    )
    scope = replace(
        package.scope,
        initial_state="zero",
        allowed_response_families=(
            "transient_exponential_kernel",
            "two_scale_superposition",
            "direct_input_component",
            "zero_memory_component",
        ),
    )
    return replace(
        package,
        fit_data=FitData(impulses, observed, 1.0),
        scope=scope,
        semantics=semantics,
        allowed_rates=tuple(value / 10 for value in range(1, 10)),
        allowed_scales=(1.0,),
        budget=replace(package.budget, generations=8, population_size=6, max_evaluations=32, max_attempts=32),
    )


def test_strict_step2_mapping_profiles_independent_b_direct_and_memory_gains(tmp_path):
    package = _strict_package(tmp_path)
    k0 = fit_response_program(ResponseProgram(()), package.fit_data, package.semantics)
    k1 = fit_response_program(
        ResponseProgram((KernelTerm(1.0, 0.4),)), package.fit_data, package.semantics
    )
    assert k0.state_count == 0 and k0.linear_parameter_count == 2
    assert k1.state_count == 1 and k1.linear_parameter_count == 3
    coefficients = dict(k1.coefficients)
    assert coefficients["intercept"] == pytest.approx(0.2)
    assert coefficients["direct_input"] == pytest.approx(0.6)
    assert coefficients["component_gain_0"] == pytest.approx(-0.3)
    assert k1.training_loss == pytest.approx(0.0, abs=1e-24)


def test_strict_simple_domain_is_exactly_canonical_k0_k1_k2(tmp_path):
    package = _strict_package(tmp_path)
    programs = comparison._program_universe(package)
    assert len(programs) == 46
    assert [sum(len(row.terms) == k for row in programs) for k in (0, 1, 2)] == [1, 9, 36]
    assert all(
        tuple(term.decay_rate for term in row.terms)
        == tuple(sorted({term.decay_rate for term in row.terms}))
        for row in programs
    )


def test_strict_gp_stays_in_common_domain_and_records_structure_operations(tmp_path):
    package = _strict_package(tmp_path)
    result = run_development_comparison(replace(package, proposer_seeds=(101,)), enabled=True)
    gp = next(row for row in result.arms if row.proposer == "response_gp")
    programs = [row.program for row in gp.search.trace if row.program is not None]
    assert programs and all(0 <= len(program.terms) <= 2 for program in programs)
    assert all(
        tuple(term.decay_rate for term in program.terms)
        == tuple(sorted({term.decay_rate for term in program.terms}))
        for program in programs
    )
    operations = {row.operation for row in gp.search.trace}
    assert "structure_mutation_add" in operations
    assert "structure_mutation_remove" in operations
    assert "structure_crossover" in operations
