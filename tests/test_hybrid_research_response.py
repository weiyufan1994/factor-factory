from __future__ import annotations

import math

import pytest

from factor_factory.hybrid_research.response import closed_form_transient_oracle, recursive_transient_response


@pytest.mark.parametrize("rate", (0.0, 0.1, 1.5))
def test_recursive_candidate_matches_independent_closed_form_oracle(rate: float) -> None:
    impulses = (2.0, -1.0, 0.0, 3.0, -2.0)
    recursive = recursive_transient_response(impulses, decay_rate=rate, step=0.25)
    oracle = closed_form_transient_oracle(impulses, decay_rate=rate, step=0.25)

    assert recursive == pytest.approx(oracle)


def test_future_impulse_does_not_change_prior_causal_response() -> None:
    base = recursive_transient_response((1.0, 0.0, 0.0), decay_rate=0.4)
    perturbed = recursive_transient_response((1.0, 0.0, 99.0), decay_rate=0.4)

    assert perturbed[:2] == pytest.approx(base[:2])
    assert perturbed[2] != pytest.approx(base[2])


def test_zero_decay_preserves_cumulative_signed_impulse() -> None:
    assert recursive_transient_response((1.0, -2.0, 4.0), decay_rate=0.0) == (1.0, -1.0, 3.0)


@pytest.mark.parametrize("rate", (-0.1, math.inf))
def test_invalid_decay_is_rejected(rate: float) -> None:
    with pytest.raises(ValueError, match="decay_rate"):
        recursive_transient_response((1.0,), decay_rate=rate)


def test_overflowing_decay_exponent_is_outside_the_declared_domain() -> None:
    with pytest.raises(ValueError, match=r"decay_rate \* step"):
        closed_form_transient_oracle((1.0, 0.0), decay_rate=1e308, step=2.0)
