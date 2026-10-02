from dataclasses import asdict
import math
import pytest
from factor_factory.hybrid_research.gp_adapter import ResponseProgram, KernelTerm, evaluate_program, run_response_gp
from factor_factory.hybrid_research.synthetic import FitData, make_synthetic_response, hidden_recovery_mse
from factor_factory.hybrid_research.variation import DerivationScope

S=DerivationScope("d","causal kernels","finite signed impulses","zero","event","missing is not zero","signed J to y",("causal convolution","linear superposition"),("temporary response decays",),"one or two scales unknown",("transient_exponential_kernel","permanent_component","two_scale_superposition"),("parameter_search","structure_search"))
KW=dict(scope=S,allowed_rates=(0.,.2,.5,1.),allowed_scales=(.3,.7,1.),seed=7,generations=2,population_size=6)

def test_structure_evolution_lineage_selection_and_replay():
    fit,_=make_synthetic_response(seed=4,noise_scale=0)
    first=run_response_gp(fit_data=fit,**KW); second=run_response_gp(fit_data=fit,**KW)
    assert first==second
    structural=[r for r in first.trace if r.operation.startswith("structure_") and r.program]
    assert structural and any(len(r.program.terms)==2 for r in structural)
    assert any(len(r.parents)==2 for r in first.trace)
    assert {r.status for r in first.trace}>={"kept","rejected"}
    assert first.selected is not None

def test_hidden_truth_is_not_part_of_fit_interface_and_is_only_used_after_search():
    fit,truth=make_synthetic_response(seed=5)
    assert set(asdict(fit))=={"signed_impulses","observed_response","step"}
    result=run_response_gp(fit_data=fit,**KW)
    prediction=evaluate_program(result.selected.program,fit)
    assert math.isfinite(hidden_recovery_mse(prediction,truth))

def test_declared_two_scale_program_matches_independent_hidden_oracle():
    fit,truth=make_synthetic_response(seed=20260927,length=24,noise_scale=0)
    program=ResponseProgram((KernelTerm(.7,.2),KernelTerm(.3,1.)))
    assert program.structure=="linear_superposition"
    assert hidden_recovery_mse(evaluate_program(program,fit),truth)==pytest.approx(0.)

def test_scope_blocks_undeclared_structure():
    narrow=DerivationScope("d","causal kernels","finite signed impulses","zero","event","missing is not zero","signed J to y",("causal convolution",),("temporary response decays",),"number of response scales unknown",("transient_exponential_kernel",),("parameter_search",))
    fit,_=make_synthetic_response(seed=1)
    result=run_response_gp(scope=narrow,fit_data=fit,allowed_rates=(.2,.5),allowed_scales=(.5,1.),seed=1,population_size=3,generations=1)
    assert any(r.operation=="structure_mutation_add" and r.reason=="grammar_disallowed" for r in result.trace)

def test_scope_rejects_wrong_observation_map_and_nonfinite_parameter_domain():
    fit,_=make_synthetic_response(seed=1)
    wrong=DerivationScope("d","causal kernels","finite signed impulses","zero","event","missing is not zero","unsigned volume to y",("causal convolution",),("temporary response decays",),"response scales unknown",("transient_exponential_kernel",),("parameter_search",))
    with pytest.raises(ValueError,match="observation_map"):
        run_response_gp(scope=wrong,fit_data=fit,allowed_rates=(.2,),allowed_scales=(1.,),seed=1)
    with pytest.raises(ValueError,match="invalid scale"):
        run_response_gp(scope=S,fit_data=fit,allowed_rates=(.2,),allowed_scales=(math.inf,),seed=1)

def test_permanent_component_and_structure_search_need_explicit_scope_labels():
    fit,_=make_synthetic_response(seed=1)
    payload=asdict(S)
    payload["allowed_response_families"]=("transient_exponential_kernel",)
    transient_only=DerivationScope(**payload)
    with pytest.raises(ValueError,match="permanent component"):
        run_response_gp(scope=transient_only,fit_data=fit,allowed_rates=(0.,.2),allowed_scales=(1.,),seed=1)
    result=run_response_gp(scope=transient_only,fit_data=fit,allowed_rates=(.2,.5),allowed_scales=(.5,1.),seed=1,population_size=3,generations=1)
    assert any(row.operation=="structure_mutation_add" and row.reason=="grammar_disallowed" for row in result.trace)

@pytest.mark.parametrize("bad",((math.nan,0.),(math.inf,0.)))
def test_nonfinite_fit_targets_are_rejected_before_search(bad):
    with pytest.raises(ValueError,match="finite"): FitData((1.,0.),bad,1.)

def test_future_impulse_does_not_change_program_history():
    program=ResponseProgram((KernelTerm(.7,.2),KernelTerm(.3,1.)))
    left=FitData((1.,0.,0.),(0.,0.,0.),1.); right=FitData((1.,0.,99.),(0.,0.,0.),1.)
    assert evaluate_program(program,left)[:2]==pytest.approx(evaluate_program(program,right)[:2])

def test_budget_exhaustion_is_recorded_not_kept():
    fit,_=make_synthetic_response(seed=2)
    result=run_response_gp(fit_data=fit,max_evaluations=2,max_attempts=5,**KW)
    assert result.evaluated_count==2
    assert result.attempt_count<=5
    assert result.stop_reason=="evaluation_budget_exhausted"
    assert result.selected is not None

def test_single_evaluation_budget_keeps_the_available_finite_elite():
    fit,_=make_synthetic_response(seed=2)
    result=run_response_gp(fit_data=fit,max_evaluations=1,max_attempts=1,**KW)
    assert result.evaluated_count==result.attempt_count==1
    assert result.selected is not None
    assert result.selected.status=="kept"

def test_global_elitism_does_not_discard_a_better_initial_parent():
    from factor_factory.hybrid_research.response import closed_form_transient_oracle
    impulses=(1.,0.,0.,-1.,0.,0.)
    fit=FitData(impulses,closed_form_transient_oracle(impulses,decay_rate=1.),1.)
    result=run_response_gp(scope=S,fit_data=fit,allowed_rates=(.2,.5,1.),allowed_scales=(.3,.7,1.),seed=0,population_size=6,generations=2)
    finite=[row for row in result.trace if row.loss is not None]
    assert result.selected.loss==min(row.loss for row in finite)

def test_extreme_finite_target_becomes_numeric_rejection_not_exception():
    fit=FitData((1.,0.,0.),(1e308,0.,0.),1.)
    result=run_response_gp(scope=S,fit_data=fit,allowed_rates=(.2,.5),allowed_scales=(.3,.7),seed=0,population_size=3,generations=1)
    assert result.selected is None
    assert result.stop_reason=="no_fittable_candidate"
    assert all(row.status=="rejected" and row.reason.startswith("numeric_invalid") for row in result.trace)

def test_candidate_output_overflow_is_rejected_without_clipping():
    fit=FitData((1e308,0.),(0.,0.),1.)
    with pytest.raises(ValueError,match="finite|overflow"):
        evaluate_program(ResponseProgram((KernelTerm(1e308,.2),)),fit)

@pytest.mark.parametrize(("field","value"),(
    ("mathematical_object","arbitrary object"),
    ("domain","unsigned impulses"),
    ("initial_state","nonzero X_0=9"),
    ("clock","calendar time"),
    ("missing_value_policy","missing is zero"),
))
def test_unsupported_scope_semantics_return_for_reformalization(field,value):
    fit,_=make_synthetic_response(seed=1)
    payload=asdict(S); payload[field]=value
    bad=DerivationScope(**payload)
    with pytest.raises(ValueError,match=field):
        run_response_gp(scope=bad,fit_data=fit,allowed_rates=(.2,),allowed_scales=(1.,),seed=1)
