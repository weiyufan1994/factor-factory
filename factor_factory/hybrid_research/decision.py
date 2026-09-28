"""Deterministic development-feedback policy candidates for hybrid research.

This module never runs a proposed action or writes a journal.  It only turns
comparable, completed development observations into a local recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal


Mode = Literal["exploit", "explore"]


@dataclass(frozen=True)
class Context:
    stage: str
    objective: str
    conditions: tuple[tuple[str, str], ...]
    evaluation_protocol: str

    def __post_init__(self) -> None:
        if not self.stage or not self.objective or not self.evaluation_protocol:
            raise ValueError("context stage, objective, and evaluation_protocol are required")
        if tuple(sorted(self.conditions)) != self.conditions:
            raise ValueError("conditions must be sorted key/value pairs")
        if len({key for key, _ in self.conditions}) != len(self.conditions):
            raise ValueError("conditions cannot repeat keys")

    @classmethod
    def from_mapping(
        cls,
        *,
        stage: str,
        objective: str,
        conditions: dict[str, str],
        evaluation_protocol: str,
    ) -> "Context":
        return cls(stage, objective, tuple(sorted(conditions.items())), evaluation_protocol)


@dataclass(frozen=True)
class Action:
    action_id: str
    family: str
    mode: Mode
    estimated_cost: float
    rationale: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id or not self.family or not self.rationale:
            raise ValueError("action_id, family, and rationale are required")
        if self.mode not in {"exploit", "explore"}:
            raise ValueError("mode must be exploit or explore")
        if not isfinite(self.estimated_cost) or self.estimated_cost < 0:
            raise ValueError("estimated_cost must be finite and non-negative")


@dataclass(frozen=True)
class Observation:
    run_id: str
    action_id: str
    context: Context
    split: str
    protocol_id: str
    metric: str
    direction: int
    baseline: float | None
    result: float | None
    scale: float | None
    actual_cost: float | None
    status: str
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.action_id or not self.protocol_id or not self.metric:
            raise ValueError("run_id, action_id, protocol_id, and metric are required")
        if self.direction not in {-1, 1}:
            raise ValueError("direction must be +1 or -1")
        if self.actual_cost is not None and (
            not isfinite(self.actual_cost) or self.actual_cost < 0
        ):
            raise ValueError("actual_cost must be finite and non-negative when known")

    def learning_increment(self) -> float | None:
        """Return a bounded comparable development delta, else ``None``.

        Failed and incomplete observations remain representable but intentionally
        do not become a reward.  Their actual cost stays available to the caller.
        """
        if self.split != "development" or self.status != "completed":
            return None
        if self.protocol_id != self.context.evaluation_protocol:
            return None
        if not isinstance(self.evidence_ref, str) or not self.evidence_ref.strip():
            return None
        values = (self.baseline, self.result, self.scale)
        if any(value is None or not isfinite(value) for value in values):
            return None
        assert self.baseline is not None and self.result is not None and self.scale is not None
        if self.scale <= 0:
            return None
        raw = self.direction * (self.result - self.baseline) / self.scale
        return max(-1.0, min(1.0, raw))


@dataclass(frozen=True)
class PolicyCandidate:
    context: Context
    family: str
    protocol_id: str
    metric: str
    direction: int
    run_ids: tuple[str, ...]
    mean_increment: float
    total_increment: float
    mean_attempt_cost: float | None
    total_attempt_cost: float | None
    attempt_count: int
    failed_attempt_count: int

    @property
    def efficiency(self) -> float | None:
        """Comparable gain per full-attempt cost, when that cost is known."""
        if self.total_attempt_cost is None or self.total_attempt_cost == 0:
            return None
        return self.total_increment / self.total_attempt_cost


@dataclass(frozen=True)
class ScheduleState:
    """Minimal journal-persisted state for deterministic action allocation."""

    episode_index: int = 0
    explore_allocations: int = 0
    exploit_allocations: int = 0

    def __post_init__(self) -> None:
        if min(self.episode_index, self.explore_allocations, self.exploit_allocations) < 0:
            raise ValueError("schedule counters must be non-negative")
        if self.explore_allocations + self.exploit_allocations != self.episode_index:
            raise ValueError("schedule allocations must equal episode_index")


@dataclass(frozen=True)
class Decision:
    action: Action | None
    reason: str
    policy_version: str = "hybrid-research-policy-v1"
    supporting_runs: tuple[str, ...] = ()
    episode_index: int = 0
    next_episode_index: int = 0
    next_schedule_state: ScheduleState = ScheduleState()


def learn_policy(
    observations: tuple[Observation, ...],
    actions: tuple[Action, ...],
) -> tuple[PolicyCandidate, ...]:
    """Aggregate only comparable development observations into local candidates.

    A repeated identical run is idempotent.  Two different records for a run id
    are ambiguous provenance and are rejected rather than selected opportunistically.
    """
    action_by_id = {action.action_id: action for action in actions}
    if len(action_by_id) != len(actions):
        raise ValueError("action ids must be unique")

    deduplicated: dict[str, Observation] = {}
    for observation in observations:
        previous = deduplicated.get(observation.run_id)
        if previous is not None and previous != observation:
            raise ValueError(f"conflicting duplicate run_id: {observation.run_id}")
        deduplicated[observation.run_id] = observation

    grouped: dict[tuple[Context, str, str, int, str], list[Observation]] = {}
    for observation in deduplicated.values():
        if observation.split != "development" or observation.protocol_id != observation.context.evaluation_protocol:
            continue
        action = action_by_id.get(observation.action_id)
        if action is None:
            if observation.status == "completed":
                raise ValueError(f"completed observation has no registered action: {observation.action_id}")
            continue
        key = (
            observation.context,
            observation.protocol_id,
            observation.metric,
            observation.direction,
            action.family,
        )
        grouped.setdefault(key, []).append(observation)

    candidates: list[PolicyCandidate] = []
    for (context, protocol_id, metric, direction, family), rows in grouped.items():
        learning_rows = [(row, row.learning_increment()) for row in rows]
        usable_rows = [(row, increment) for row, increment in learning_rows if increment is not None]
        if not usable_rows:
            continue
        increments = [increment for _, increment in usable_rows]
        costs = [row.actual_cost for row in rows]
        complete_cost = all(cost is not None for cost in costs)
        candidates.append(
            PolicyCandidate(
                context=context,
                family=family,
                protocol_id=protocol_id,
                metric=metric,
                direction=direction,
                run_ids=tuple(sorted(row.run_id for row, _ in usable_rows)),
                mean_increment=sum(increments) / len(increments),
                total_increment=sum(increments),
                mean_attempt_cost=(sum(costs) / len(costs)) if complete_cost else None,
                total_attempt_cost=sum(costs) if complete_cost else None,
                attempt_count=len(rows),
                failed_attempt_count=sum(row.status != "completed" for row in rows),
            )
        )
    return tuple(sorted(
        candidates,
        key=lambda item: (
            item.context.stage,
            item.context.objective,
            item.context.conditions,
            item.context.evaluation_protocol,
            item.metric,
            item.family,
        ),
    ))


def select_action(
    *,
    context: Context,
    actions: tuple[Action, ...],
    candidates: tuple[PolicyCandidate, ...],
    metric: str,
    direction: int,
    remaining_budget: float,
    explore_share: float = 0.0,
    episode_index: int = 0,
    schedule_state: ScheduleState | None = None,
) -> Decision:
    """Select one registered action or return an explicit legal stop."""
    if direction not in {-1, 1}:
        raise ValueError("direction must be +1 or -1")
    if not isfinite(remaining_budget) or remaining_budget < 0:
        raise ValueError("remaining_budget must be finite and non-negative")
    if not 0 <= explore_share <= 1:
        raise ValueError("explore_share must be within [0, 1]")
    if not isinstance(episode_index, int) or episode_index < 0:
        raise ValueError("episode_index must be a non-negative integer")
    if schedule_state is not None and episode_index != 0:
        raise ValueError("pass either schedule_state or a non-zero legacy episode_index")
    state = schedule_state or ScheduleState(
        episode_index=episode_index,
        explore_allocations=int(episode_index * explore_share),
        exploit_allocations=episode_index - int(episode_index * explore_share),
    )
    if len({action.action_id for action in actions}) != len(actions):
        raise ValueError("action ids must be unique")

    affordable = tuple(action for action in actions if action.estimated_cost <= remaining_budget)
    if not affordable:
        return Decision(
            None,
            "STOP: budget exhausted or no action is affordable",
            episode_index=state.episode_index,
            next_episode_index=state.episode_index,
            next_schedule_state=state,
        )

    explore = tuple(action for action in affordable if action.mode == "explore")
    exploit = tuple(action for action in affordable if action.mode == "exploit")
    desired_explore_after = int((state.episode_index + 1) * explore_share)
    explore_due = bool(explore) and (
        not exploit or state.explore_allocations < desired_explore_after
    )
    if explore_due:
        action = sorted(explore, key=lambda item: item.action_id)[state.explore_allocations % len(explore)]
        next_state = ScheduleState(
            episode_index=state.episode_index + 1,
            explore_allocations=state.explore_allocations + 1,
            exploit_allocations=state.exploit_allocations,
        )
        return Decision(
            action,
            "explore: configured deterministic opportunity",
            episode_index=state.episode_index,
            next_episode_index=next_state.episode_index,
            next_schedule_state=next_state,
        )

    compatible = {
        candidate.family: candidate
        for candidate in candidates
        if candidate.context == context
        and candidate.protocol_id == context.evaluation_protocol
        and candidate.metric == metric
        and candidate.direction == direction
    }
    scored = [(compatible[action.family], action) for action in exploit if action.family in compatible]
    if scored:
        priced = [item for item in scored if item[0].efficiency is not None]
        pool = priced or scored
        candidate, action = max(
            pool,
            key=lambda item: (
                item[0].efficiency is not None,
                item[0].efficiency if item[0].efficiency is not None else item[0].mean_increment,
                item[0].mean_increment,
                item[1].action_id,
            ),
        )
        reason = (
            "exploit: best comparable development increment per complete attempt cost"
            if priced
            else "exploit: comparable development increment with incomplete or zero cost"
        )
        return Decision(
            action,
            reason,
            supporting_runs=candidate.run_ids,
            episode_index=state.episode_index,
            next_episode_index=state.episode_index + 1,
            next_schedule_state=ScheduleState(
                episode_index=state.episode_index + 1,
                explore_allocations=state.explore_allocations,
                exploit_allocations=state.exploit_allocations + 1,
            ),
        )

    # Without evidence, round-robin means lexical order after an explicit caller
    # supplied action registry.  This is reproducible and does not claim success.
    baseline_actions = sorted(exploit or explore, key=lambda item: item.action_id)
    is_explore = baseline_actions[0].mode == "explore"
    allocation_index = state.explore_allocations if is_explore else state.exploit_allocations
    action = baseline_actions[allocation_index % len(baseline_actions)]
    next_state = ScheduleState(
        episode_index=state.episode_index + 1,
        explore_allocations=state.explore_allocations + int(is_explore),
        exploit_allocations=state.exploit_allocations + int(not is_explore),
    )
    return Decision(
        action,
        "baseline: no comparable development evidence; deterministic round-robin",
        episode_index=state.episode_index,
        next_episode_index=next_state.episode_index,
        next_schedule_state=next_state,
    )
