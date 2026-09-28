"""Small causal response models with explicit measurement semantics."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite


@dataclass(frozen=True)
class ResponseSemantics:
    """Supported, frozen semantics for one bounded response fit.

    Empty index tuples mean the whole observed series. ``input_start_index``
    identifies the first response index to model; earlier inputs can seed a
    lagged response. No meaning is inferred from a floating-point rate.
    """

    observation_timing: str = "same_event"
    rate_parameterization: str = "continuous_decay"
    pre_sample_input: str = "zero"
    initial_state: str = "zero"
    intercept: str = "zero"
    direct_input: str = "zero"
    gain_mode: str = "evolved_component"
    gain_constraint: str = "unrestricted"
    memory_rate_policy: str = "legacy_ordered_terms"
    training_indexes: tuple[int, ...] = ()
    score_indexes: tuple[int, ...] = ()
    input_start_index: int = 0
    initial_state_start_index: int = 0
    initial_power_offset: int = 1

    def __post_init__(self) -> None:
        choices = {
            "observation_timing": {"same_event", "lag_one"},
            "rate_parameterization": {"continuous_decay", "retention"},
            "pre_sample_input": {"zero", "unknown"},
            "initial_state": {"zero", "profiled_component"},
            "intercept": {"zero", "profiled"},
            "direct_input": {"zero", "profiled_same_event"},
            "gain_mode": {"evolved_component", "profiled_shared", "profiled_component"},
            "gain_constraint": {"unrestricted", "nonnegative"},
            "memory_rate_policy": {"legacy_ordered_terms", "strict_increasing_unique"},
        }
        for field, allowed in choices.items():
            if getattr(self, field) not in allowed:
                raise ValueError(f"unsupported response semantics: {field}={getattr(self, field)!r}")
        if self.gain_mode == "evolved_component" and self.gain_constraint != "unrestricted":
            raise ValueError("nonnegative gain constraint requires profiled gains")
        if self.direct_input == "profiled_same_event" and self.observation_timing != "same_event":
            raise ValueError("profiled direct input requires same_event observation timing")
        if (
            self.memory_rate_policy == "strict_increasing_unique"
            and self.rate_parameterization != "retention"
        ):
            raise ValueError("strict memory rates require retention parameterization")
        for field in ("training_indexes", "score_indexes"):
            values = getattr(self, field)
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError(f"{field} must contain non-negative integers")
            if len(set(values)) != len(values):
                raise ValueError(f"{field} must not contain duplicates")
        if type(self.input_start_index) is not int or self.input_start_index < 0:
            raise ValueError("input_start_index must be a non-negative integer")
        if type(self.initial_state_start_index) is not int or self.initial_state_start_index < 0:
            raise ValueError("initial_state_start_index must be a non-negative integer")
        if type(self.initial_power_offset) is not int or self.initial_power_offset < 0:
            raise ValueError("initial_power_offset must be a non-negative integer")


def retention_from_parameter(rate: float, *, parameterization: str, step: float) -> float:
    if not isfinite(rate):
        raise ValueError("response rate must be finite")
    if not isfinite(step) or step <= 0:
        raise ValueError("step must be finite and positive")
    if parameterization == "continuous_decay":
        if rate < 0 or not isfinite(rate * step):
            raise ValueError("continuous decay rate must be finite and non-negative")
        return exp(-rate * step)
    if parameterization == "retention":
        if not 0 <= rate <= 1:
            raise ValueError("retention must be in [0, 1]")
        return rate
    raise ValueError(f"unsupported rate parameterization: {parameterization!r}")


def response_column(
    signed_impulses: tuple[float, ...],
    *,
    rate: float,
    step: float = 1.0,
    semantics: ResponseSemantics,
) -> tuple[float, ...]:
    """Evaluate one zero-initial-state causal input column."""
    _validate_values(signed_impulses)
    retention = retention_from_parameter(
        rate, parameterization=semantics.rate_parameterization, step=step
    )
    state = 0.0
    values: list[float] = []
    for index in range(len(signed_impulses)):
        if semantics.observation_timing == "same_event":
            source = signed_impulses[index] if index >= semantics.input_start_index else 0.0
        else:
            source_index = index - 1
            source = (
                signed_impulses[source_index]
                if source_index >= 0 and index >= semantics.input_start_index
                else 0.0
            )
        state = retention * state + source
        values.append(state)
    return tuple(values)


def initial_state_column(
    length: int, *, rate: float, step: float, semantics: ResponseSemantics
) -> tuple[float, ...]:
    retention = retention_from_parameter(
        rate, parameterization=semantics.rate_parameterization, step=step
    )
    return tuple(
        retention ** (index - semantics.initial_state_start_index + semantics.initial_power_offset)
        if index >= semantics.initial_state_start_index
        else 0.0
        for index in range(length)
    )


def recursive_transient_response(
    signed_impulses: tuple[float, ...],
    *,
    decay_rate: float,
    step: float = 1.0,
) -> tuple[float, ...]:
    """Evaluate a causal exponential transient response by state recursion.

    At index ``t`` an impulse is observable before the returned response.  This
    convention is part of the synthetic model, not a market-data convention.
    """
    _validate_legacy(signed_impulses, decay_rate, step)
    return response_column(
        signed_impulses, rate=decay_rate, step=step, semantics=ResponseSemantics()
    )


def closed_form_transient_oracle(
    signed_impulses: tuple[float, ...],
    *,
    decay_rate: float,
    step: float = 1.0,
) -> tuple[float, ...]:
    """Independently evaluate the same causal convolution from its definition."""
    _validate_legacy(signed_impulses, decay_rate, step)
    decay = retention_from_parameter(
        decay_rate, parameterization="continuous_decay", step=step
    )
    return tuple(
        sum(
            signed_impulses[source] * decay ** (target - source)
            for source in range(target + 1)
        )
        for target in range(len(signed_impulses))
    )


def _validate_values(values: tuple[float, ...]) -> None:
    if any(not isfinite(value) for value in values):
        raise ValueError("signed_impulses must be finite")


def _validate_legacy(values: tuple[float, ...], decay_rate: float, step: float) -> None:
    if not isfinite(decay_rate) or decay_rate < 0:
        raise ValueError("decay_rate must be finite and non-negative")
    if not isfinite(step) or step <= 0:
        raise ValueError("step must be finite and positive")
    if not isfinite(decay_rate * step):
        raise ValueError("decay_rate * step must be finite")
    _validate_values(values)
