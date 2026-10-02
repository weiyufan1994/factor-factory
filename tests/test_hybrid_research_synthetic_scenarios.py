from dataclasses import asdict
import pytest
from factor_factory.hybrid_research.response import closed_form_transient_oracle
from factor_factory.hybrid_research.synthetic import make_observational_equivalence_pair, make_response_scenario


@pytest.mark.parametrize(
    "scenario",
    ("single_slow", "single_fast", "permanent_plus_transient", "two_scale", "common_shock"),
)
def test_scenarios_keep_hidden_mechanism_out_of_fit_data(scenario):
    fit, truth = make_response_scenario(scenario=scenario, seed=9, noise_scale=0)
    assert set(asdict(fit)) == {"signed_impulses", "observed_response", "step"}
    assert truth.model_label == scenario
    assert fit.observed_response == pytest.approx(truth.noiseless_response)


def test_noise_changes_observation_not_hidden_noiseless_truth():
    clean, clean_truth = make_response_scenario(scenario="single_slow", seed=3, noise_scale=0)
    noisy, noisy_truth = make_response_scenario(scenario="single_slow", seed=3, noise_scale=.2)
    assert clean.signed_impulses == noisy.signed_impulses
    assert clean_truth.noiseless_response == noisy_truth.noiseless_response
    assert clean.observed_response != noisy.observed_response


def test_permanent_component_does_not_decay_after_last_impulse():
    fit, truth = make_response_scenario(
        scenario="permanent_plus_transient",
        seed=4,
        noise_scale=0,
        signed_impulses=(1.0,) + (0.0,) * 15,
    )
    permanent_scale = next(scale for scale, rate in truth.terms if rate == 0)
    permanent = tuple(
        permanent_scale * value
        for value in closed_form_transient_oracle(fit.signed_impulses, decay_rate=0)
    )
    last_impulse = max(index for index, value in enumerate(fit.signed_impulses) if value)
    assert last_impulse < len(permanent) - 1
    assert permanent[last_impulse:] == (permanent[last_impulse],) * (
        len(permanent) - last_impulse
    )
    assert truth.noiseless_response == fit.observed_response


def test_common_shock_is_not_inserted_into_observable_impulse_input():
    fit, truth = make_response_scenario(scenario="common_shock", seed=7, noise_scale=0)
    assert any(truth.common_component)
    assert "common_component" not in asdict(fit)


def test_observational_equivalence_preserves_unknown_identity():
    fit, left, right = make_observational_equivalence_pair()
    assert left.model_label != right.model_label and left.terms != right.terms
    assert fit.observed_response == left.noiseless_response == right.noiseless_response
