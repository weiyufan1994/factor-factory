from dataclasses import asdict
import json

import pytest

from factor_factory.hybrid_research.gp_adapter import (
    KernelTerm,
    ResponseProgram,
    fit_response_program,
    run_response_gp,
)
from factor_factory.hybrid_research.response import ResponseSemantics
from factor_factory.hybrid_research.synthetic import FitData
from factor_factory.hybrid_research.variation import DerivationScope
from factor_factory.hybrid_research.journal_adapter import _collect_implementation_evidence


def _scope(initial_state="profiled_component", permanent=True):
    families = ["transient_exponential_kernel", "two_scale_superposition"]
    if permanent:
        families.append("permanent_component")
    return DerivationScope(
        "d", "causal kernels", "finite signed impulses", initial_state, "event",
        "missing is not zero", "signed J to y",
        ("causal convolution", "linear superposition"), ("continuation",), "rates",
        tuple(families), ("parameter_search", "structure_search"),
    )


def test_u05_forcing_start_and_initial_anchor_are_independent():
    semantics = ResponseSemantics(
        observation_timing="lag_one", rate_parameterization="retention",
        pre_sample_input="zero", initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_shared",
        training_indexes=(1, 2, 3), input_start_index=1,
        initial_state_start_index=0, initial_power_offset=0,
    )
    data = FitData((2.0, 0.0, 0.0, 0.0), (3.0, 7.0, 5.0, 4.0), 1.0)
    fit = fit_response_program(ResponseProgram((KernelTerm(1.0, 0.5),)), data, semantics)
    assert fit.design_columns == ("shared_gain", "intercept", "initial_state_0")
    assert fit.continuation_indexes == ()
    assert fit.prediction[1:] == pytest.approx(data.observed_response[1:])


def test_training_suffix_observations_cannot_change_gp_search():
    semantics = ResponseSemantics(
        rate_parameterization="retention", initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_component",
        training_indexes=(0, 1, 2), score_indexes=(0, 1, 2),
    )
    kwargs = dict(
        scope=_scope(), allowed_rates=(0.25, 0.5), allowed_scales=(1.0,), seed=3,
        generations=2, population_size=3, response_semantics=semantics,
    )
    left = run_response_gp(fit_data=FitData((1, 0, 2, 1, 3), (2, 1, 4, 0, 0), 1), **kwargs)
    right = run_response_gp(fit_data=FitData((1, 0, 2, 1, 3), (2, 1, 4, 999, -999), 1), **kwargs)
    assert left == right


def test_unknown_lagged_presample_at_zero_retention_is_explicitly_unrepresentable():
    semantics = ResponseSemantics(
        observation_timing="lag_one", rate_parameterization="retention",
        pre_sample_input="unknown", initial_state="profiled_component",
        intercept="profiled", gain_mode="profiled_shared", training_indexes=(0, 1),
    )
    data = FitData((1, 0), (0, 0), 1)
    with pytest.raises(ValueError, match="unknown pre-sample input and retention=0"):
        fit_response_program(ResponseProgram((KernelTerm(1, 0),)), data, semantics)


def test_retention_one_requires_permanent_family_authorization():
    semantics = ResponseSemantics(
        rate_parameterization="retention", initial_state="zero",
        gain_mode="profiled_shared", training_indexes=(0, 1),
    )
    scope = _scope(initial_state="zero", permanent=False)
    data = FitData((1, 0), (1, 1), 1)
    with pytest.raises(ValueError, match="permanent response"):
        run_response_gp(
            scope=scope, fit_data=data, allowed_rates=(1.0,), allowed_scales=(1.0,),
            seed=1, response_semantics=semantics,
        )


def test_semantics_are_fully_serializable_for_material_identity():
    payload = asdict(ResponseSemantics(training_indexes=(0, 1)))
    assert payload["initial_state_start_index"] == 0
    assert payload["rate_parameterization"] == "continuous_decay"


def test_caller_reported_pass_does_not_manufacture_review_or_engine_coverage(tmp_path):
    evidence_dir = tmp_path / "objects" / "research_journal"
    evidence_dir.mkdir(parents=True)
    author = evidence_dir / "author.json"
    author.write_text(json.dumps({"status": "PASS", "tested_files": []}))
    collected = _collect_implementation_evidence(
        root=tmp_path, report_id="R", handoff_path=tmp_path / "handoff.json",
        spec_path=tmp_path / "spec.json", requested={"author_test_path": str(author)},
    )
    assert collected["author_tests"]["status"] == "artifact_available_unverified"
    assert collected["author_tests"]["tested_engine_coverage"]["status"] == "incomplete_or_stale"
    assert collected["independent_review"]["status"] == "Unknown"
    assert len(collected["executed_engine_version"]) == 2


def test_nonzero_collinear_columns_are_reported_as_structurally_unidentified():
    semantics = ResponseSemantics(
        rate_parameterization="retention", initial_state="profiled_component",
        intercept="zero", gain_mode="profiled_component", training_indexes=(0, 1, 2),
    )
    program = ResponseProgram((KernelTerm(1, 0.5), KernelTerm(1, 0.5)))
    fit = fit_response_program(program, FitData((1, 1, 0), (1, 1.5, 0.75), 1), semantics)
    assert fit.design_rank == 2
    assert set(fit.unidentified_coefficients) == {
        "component_gain_0", "component_gain_1", "initial_state_0", "initial_state_1"
    }


def test_design_rank_is_full_training_design_rank_not_active_set_rank():
    semantics = ResponseSemantics(
        rate_parameterization="retention", initial_state="zero", intercept="profiled",
        gain_mode="profiled_component", gain_constraint="nonnegative",
        training_indexes=(0, 1, 2),
    )
    fit = fit_response_program(
        ResponseProgram((KernelTerm(1, 0.5),)),
        FitData((1, 0, 0), (-1, 0, 0), 1), semantics,
    )
    assert dict(fit.coefficients)["component_gain_0"] == pytest.approx(0)
    assert fit.design_rank == 2
    assert fit.unidentified_coefficients == ()


def test_explicit_legacy_semantics_report_zero_rank_for_zero_column_design():
    fit = fit_response_program(
        ResponseProgram((KernelTerm(0.7, 0.5),)),
        FitData((1, 0, 0), (0.7, 0.35, 0.175), 1),
        ResponseSemantics(training_indexes=(0, 1, 2)),
    )
    assert fit.design_columns == ()
    assert fit.design_rank == 0
    assert fit.unidentified_coefficients == ()


def test_identifiability_diagnostic_is_invariant_to_input_units():
    semantics = ResponseSemantics(
        rate_parameterization="retention", initial_state="zero",
        gain_mode="profiled_component", training_indexes=(0, 1, 2),
    )
    program = ResponseProgram((KernelTerm(1, 0.5), KernelTerm(1, 0.5)))
    fit = fit_response_program(
        program, FitData((1e16, 1e16, 0), (1e16, 1.5e16, 0.75e16), 1), semantics
    )
    assert set(fit.unidentified_coefficients) == {"component_gain_0", "component_gain_1"}


@pytest.mark.parametrize(
    "kwargs",
    (
        {"training_indexes": (0.25, 1.75)},
        {"training_indexes": (False, 1)},
        {"input_start_index": 1.75},
        {"initial_state_start_index": True},
        {"initial_power_offset": 0.5},
    ),
)
def test_index_semantics_reject_non_integer_values_without_coercion(kwargs):
    with pytest.raises(ValueError, match="integer"):
        ResponseSemantics(**kwargs)
