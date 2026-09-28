"""Synthetic response fixtures with explicit fit/oracle separation."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from random import Random
from .response import closed_form_transient_oracle

@dataclass(frozen=True)
class FitData:
    signed_impulses: tuple[float, ...]
    observed_response: tuple[float, ...]
    step: float
    def __post_init__(self) -> None:
        if not self.signed_impulses or len(self.signed_impulses) != len(self.observed_response):
            raise ValueError("fit inputs must be nonempty and aligned")
        if not isfinite(self.step) or self.step <= 0:
            raise ValueError("fit step must be finite and positive")
        if any(not isfinite(v) for v in self.signed_impulses + self.observed_response):
            raise ValueError("fit inputs and targets must be finite")

@dataclass(frozen=True)
class HiddenSyntheticTruth:
    model_label: str
    terms: tuple[tuple[float, float], ...]
    noiseless_response: tuple[float, ...]
    common_component: tuple[float, ...] = ()


def make_synthetic_response(*, seed: int, length: int = 24, noise_scale: float = .01) -> tuple[FitData, HiddenSyntheticTruth]:
    if length < 4 or not isfinite(noise_scale) or noise_scale < 0:
        raise ValueError("length >= 4 and finite non-negative noise_scale required")
    rng = Random(seed)
    impulses = tuple(rng.choice((-1., 0., 1.)) for _ in range(length))
    terms = ((.7, .2), (.3, 1.))
    cols = [closed_form_transient_oracle(impulses, decay_rate=rate) for _, rate in terms]
    noiseless = tuple(sum(scale * col[i] for (scale, _), col in zip(terms, cols)) for i in range(length))
    observed = tuple(value + rng.uniform(-noise_scale, noise_scale) for value in noiseless)
    return FitData(impulses, observed, 1.), HiddenSyntheticTruth("two_scale_causal_response", terms, noiseless)

def make_response_scenario(
    *,
    scenario: str,
    seed: int,
    length: int = 24,
    noise_scale: float = .01,
    signed_impulses: tuple[float, ...] | None = None,
) -> tuple[FitData, HiddenSyntheticTruth]:
    """Construct bounded mechanism fixtures; hidden fields never enter ``FitData``."""
    definitions = {
        "single_slow": ((1.0, .2),),
        "single_fast": ((1.0, 1.0),),
        "permanent_plus_transient": ((.35, 0.0), (.65, .5)),
        "two_scale": ((.7, .2), (.3, 1.0)),
        "common_shock": ((.7, .2),),
    }
    if scenario not in definitions:
        raise ValueError(f"unsupported synthetic scenario: {scenario}")
    if signed_impulses is not None:
        length = len(signed_impulses)
    if length < 4 or not isfinite(noise_scale) or noise_scale < 0:
        raise ValueError("length >= 4 and finite non-negative noise_scale required")
    rng = Random(seed)
    impulses = (
        tuple(float(value) for value in signed_impulses)
        if signed_impulses is not None
        else tuple(rng.choice((-1., 0., 1.)) for _ in range(length))
    )
    if any(not isfinite(value) for value in impulses):
        raise ValueError("signed_impulses must be finite")
    terms = definitions[scenario]
    columns = [closed_form_transient_oracle(impulses, decay_rate=rate) for _, rate in terms]
    response = tuple(sum(scale * column[i] for (scale, _), column in zip(terms, columns)) for i in range(length))
    common = tuple(.2 if scenario == "common_shock" and i >= length // 2 else 0. for i in range(length))
    noiseless = tuple(value + common[i] for i, value in enumerate(response))
    observed = tuple(value + rng.uniform(-noise_scale, noise_scale) for value in noiseless)
    return FitData(impulses, observed, 1.), HiddenSyntheticTruth(scenario, terms, noiseless, common)


def make_observational_equivalence_pair(*, length: int = 8) -> tuple[FitData, HiddenSyntheticTruth, HiddenSyntheticTruth]:
    """Two distinct hidden kernel labels produce identical zero-input observations."""
    if length < 1:
        raise ValueError("length must be positive")
    zeros = (0.0,) * length
    fit = FitData(zeros, zeros, 1.0)
    slow = HiddenSyntheticTruth("unexcited_slow_kernel", ((1.0, .2),), zeros)
    fast = HiddenSyntheticTruth("unexcited_fast_kernel", ((1.0, 1.0),), zeros)
    return fit, slow, fast

def hidden_recovery_mse(prediction: tuple[float, ...], truth: HiddenSyntheticTruth) -> float:
    if len(prediction) != len(truth.noiseless_response) or any(not isfinite(v) for v in prediction):
        raise ValueError("hidden evaluation prediction must be finite and aligned")
    return sum((a-b)**2 for a,b in zip(prediction, truth.noiseless_response))/len(prediction)
