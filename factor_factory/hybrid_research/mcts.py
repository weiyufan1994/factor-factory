"""Bounded tree search over registered hybrid-research actions.

The search expands a tree with actual caller-supplied development observations.
It does not invent rollout rewards, execute actions by name, or turn a planning
result into research approval.  The same :class:`Action` registry and evaluator
can be passed to :func:`run_simple_scheduler` for an equal-budget comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, log, sqrt
from random import Random
from typing import Callable, Literal

from .decision import (
    Action,
    Context,
    Observation,
    PolicyCandidate,
    ScheduleState,
    learn_policy,
    select_action,
)


@dataclass(frozen=True)
class ResearchState:
    """A compact, non-authoritative view of one research branch."""

    context: Context
    hypothesis_ref: str
    prediction_refs: tuple[str, ...]
    competing_explanation_refs: tuple[str, ...]
    experiment_refs: tuple[str, ...] = ()
    completed_action_ids: tuple[str, ...] = ()
    incurred_cost: float = 0.0
    depth: int = 0
    stopped: bool = False

    def __post_init__(self) -> None:
        if not self.hypothesis_ref:
            raise ValueError("hypothesis_ref is required")
        if not self.prediction_refs:
            raise ValueError("at least one prediction_ref is required")
        if not self.competing_explanation_refs:
            raise ValueError("at least one competing_explanation_ref is required")
        if not isfinite(self.incurred_cost) or self.incurred_cost < 0:
            raise ValueError("incurred_cost must be finite and non-negative")
        if not isinstance(self.depth, int) or self.depth < 0:
            raise ValueError("depth must be a non-negative integer")
        if len(set(self.completed_action_ids)) != len(self.completed_action_ids):
            raise ValueError("completed_action_ids cannot repeat within a branch")


@dataclass(frozen=True)
class ActionResult:
    """Observed result of one real, bounded action expansion."""

    observation: Observation
    hypothesis_ref: str | None = None
    added_prediction_refs: tuple[str, ...] = ()
    added_competing_explanation_refs: tuple[str, ...] = ()
    experiment_ref: str | None = None
    terminal: bool = False


ActionEvaluator = Callable[[ResearchState, Action, int], ActionResult]
ActionAvailability = Callable[[ResearchState, Action], bool]
ActionFeedbackFamily = Callable[[Action], str]


@dataclass(frozen=True)
class ExpansionRecord:
    iteration: int
    parent_node_id: str
    node_id: str
    action_id: str
    action_mode: str
    depth: int
    evaluator_seed: int | None
    status: str
    split: str | None
    actual_cost: float | None
    learning_increment: float | None
    evidence_ref: str | None
    path_action_ids: tuple[str, ...]


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    parent_node_id: str | None
    action_id: str | None
    depth: int
    visits: int
    value_sum: float
    cost_sum: float
    mean_value: float
    evidence_efficiency: float | None
    terminal: bool
    development_evidence: bool | None
    completed_action_ids: tuple[str, ...]


@dataclass(frozen=True)
class PlannerFailure:
    kind: str
    message: str
    action_id: str
    evaluator_invoked: bool
    known_actual_cost: float | None


@dataclass(frozen=True)
class PlanningResult:
    algorithm: Literal["mcts", "simple_scheduler"]
    enabled: bool
    seed: int
    total_budget: float
    spent_cost: float
    prior_incurred_cost: float
    cumulative_known_cost: float
    expansion_count: int
    selected_action_id: str | None
    first_executed_action_id: str | None
    stop_reason: str
    trace: tuple[ExpansionRecord, ...]
    nodes: tuple[NodeRecord, ...]
    virtual_rollout_count: int = 0
    failure: PlannerFailure | None = None


class PlannerContractError(ValueError):
    """Contract rejection that retains all known progress and cost."""

    def __init__(self, message: str, partial_result: PlanningResult) -> None:
        super().__init__(message)
        self.partial_result = partial_result


@dataclass
class _Node:
    node_id: str
    state: ResearchState
    parent: "_Node | None" = None
    action: Action | None = None
    children: list["_Node"] = field(default_factory=list)
    expanded_action_ids: set[str] = field(default_factory=set)
    visits: int = 0
    value_sum: float = 0.0
    cost_sum: float = 0.0
    development_evidence: bool | None = None

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0

    @property
    def evidence_efficiency(self) -> float | None:
        return self.value_sum / self.cost_sum if self.cost_sum > 0 else None


def run_action_mcts(
    *,
    enabled: bool = False,
    initial_state: ResearchState,
    actions: tuple[Action, ...],
    evaluator: ActionEvaluator | None = None,
    metric: str,
    direction: int,
    seed: int,
    total_budget: float,
    max_expansions: int,
    max_depth: int = 3,
    exploration_weight: float = 1.0,
    explore_share: float = 0.25,
    stop_action_ids: tuple[str, ...] = (),
    prior_observations: tuple[Observation, ...] = (),
    action_available: ActionAvailability | None = None,
    max_children_per_node: int | None = None,
) -> PlanningResult:
    """Run expansion-only MCTS with actual development evidence.

    Each iteration performs tree selection, expands exactly one previously
    untried registered action, and backpropagates its eligible development
    increment using a mean-value rule.  There is deliberately no virtual
    simulation phase. ``total_budget`` caps newly reported cost for this call;
    prior branch cost is reported separately. ``estimated_cost`` is a trusted
    evaluator reservation contract. A returned cost above that bound can only
    be detected after the evaluator returns and is rejected as a violation.
    """
    _validate_initial_state(initial_state)
    _validate_planner_inputs(
        actions=actions,
        metric=metric,
        direction=direction,
        total_budget=total_budget,
        max_expansions=max_expansions,
        max_depth=max_depth,
        explore_share=explore_share,
        stop_action_ids=stop_action_ids,
    )
    if not isfinite(exploration_weight) or exploration_weight < 0:
        raise ValueError("exploration_weight must be finite and non-negative")
    if max_children_per_node is not None and max_children_per_node < 1:
        raise ValueError("max_children_per_node must be positive when set")
    prior_by_run_id = _validate_prior_observations(prior_observations)
    prior_candidates = learn_policy(prior_observations, actions)
    availability = action_available or (lambda state, action: True)
    if not enabled:
        return PlanningResult(
            algorithm="mcts",
            enabled=False,
            seed=seed,
            total_budget=total_budget,
            spent_cost=0.0,
            prior_incurred_cost=initial_state.incurred_cost,
            cumulative_known_cost=initial_state.incurred_cost,
            expansion_count=0,
            selected_action_id=None,
            first_executed_action_id=None,
            stop_reason="disabled: explicit opt-in required",
            trace=(),
            nodes=(),
        )
    if evaluator is None:
        raise ValueError("evaluator is required when MCTS is enabled")

    rng = Random(seed)
    root = _Node("n000", initial_state)
    nodes = [root]
    trace: list[ExpansionRecord] = []
    observations_by_run_id = dict(prior_by_run_id)
    spent_cost = 0.0
    stop_ids = set(stop_action_ids)
    stop_reason = "completed"
    failure: PlannerFailure | None = None

    for iteration in range(max_expansions):
        remaining_budget = total_budget - spent_cost
        selected = _select_expandable_node(
            root=root,
            actions=actions,
            remaining_budget=remaining_budget,
            max_depth=max_depth,
            exploration_weight=exploration_weight,
            rng=rng,
            action_available=availability,
            max_children_per_node=max_children_per_node,
        )
        if selected is None:
            stop_reason = "no_expandable_branch_within_budget"
            break
        available = _untried_affordable_actions(
            selected, actions, remaining_budget, availability, max_children_per_node
        )
        action = _choose_expansion_action(
            available=available,
            trace=trace,
            explore_share=explore_share,
            rng=rng,
            context=initial_state.context,
            metric=metric,
            direction=direction,
            prior_candidates=prior_candidates,
        )
        selected.expanded_action_ids.add(action.action_id)
        node_id = f"n{len(nodes):03d}"
        path = selected.state.completed_action_ids + (action.action_id,)

        if action.action_id in stop_ids:
            child_state = _advance_state(selected.state, action, None, 0.0, stopped=True)
            child = _Node(node_id, child_state, selected, action)
            selected.children.append(child)
            nodes.append(child)
            _backpropagate(child, value=0.0, cost=0.0)
            trace.append(ExpansionRecord(
                iteration, selected.node_id, node_id, action.action_id, action.mode,
                child_state.depth, None, "stopped", None, 0.0, None, None, path,
            ))
            continue

        evaluator_seed = rng.randrange(0, 2**63)
        try:
            result = evaluator(selected.state, action, evaluator_seed)
        except Exception as exc:
            failure = PlannerFailure(
                "evaluator_exception", f"{type(exc).__name__}: {exc}",
                action.action_id, True, None,
            )
            trace.append(ExpansionRecord(
                iteration, selected.node_id, node_id, action.action_id, action.mode,
                selected.state.depth + 1, evaluator_seed,
                "evaluator_exception_unknown_cost", None, None, None, None, path,
            ))
            stop_reason = "evaluator_exception_unknown_cost"
            break
        try:
            actual_cost = _validate_action_result(
                result=result,
                state=selected.state,
                action=action,
                metric=metric,
                direction=direction,
                remaining_budget=remaining_budget,
            )
        except (TypeError, ValueError) as exc:
            known_cost = _known_actual_cost(result)
            if known_cost is not None:
                spent_cost += known_cost
            failure = PlannerFailure(
                "evaluator_contract_violation", str(exc),
                action.action_id, True, known_cost,
            )
            observation = result.observation if isinstance(result, ActionResult) else None
            trace.append(ExpansionRecord(
                iteration, selected.node_id, node_id, action.action_id, action.mode,
                selected.state.depth + 1, evaluator_seed,
                "evaluator_contract_violation",
                observation.split if observation else None,
                known_cost, None,
                observation.evidence_ref if observation else None,
                path,
            ))
            partial = _partial_result(
                algorithm="mcts",
                initial_state=initial_state,
                seed=seed,
                total_budget=total_budget,
                spent_cost=spent_cost,
                stop_reason="evaluator_contract_violation",
                trace=trace,
                nodes=nodes,
                selected_action_id=_recommend_root_action(root, stop_ids),
                failure=failure,
            )
            raise PlannerContractError(str(exc), partial) from exc
        observation = result.observation
        try:
            is_new_observation = _register_observation(observation, observations_by_run_id)
        except ValueError as exc:
            spent_cost += actual_cost
            failure = PlannerFailure(
                "conflicting_run_id", str(exc),
                action.action_id, True, actual_cost,
            )
            trace.append(ExpansionRecord(
                iteration, selected.node_id, node_id, action.action_id, action.mode,
                selected.state.depth + 1, evaluator_seed,
                "conflicting_run_id_rejected", observation.split, actual_cost,
                None, observation.evidence_ref, path,
            ))
            partial = _partial_result(
                algorithm="mcts",
                initial_state=initial_state,
                seed=seed,
                total_budget=total_budget,
                spent_cost=spent_cost,
                stop_reason="conflicting_run_id_rejected",
                trace=trace,
                nodes=nodes,
                selected_action_id=_recommend_root_action(root, stop_ids),
                failure=failure,
            )
            raise PlannerContractError(str(exc), partial) from exc
        charged_cost = actual_cost if is_new_observation else 0.0
        spent_cost += charged_cost
        increment = observation.learning_increment() if is_new_observation else None
        nondevelopment = observation.split != "development"
        child_state = _advance_state(
            selected.state,
            action,
            result,
            charged_cost,
            stopped=result.terminal or nondevelopment,
        )
        child = _Node(
            node_id, child_state, selected, action,
            development_evidence=is_new_observation and not nondevelopment,
        )
        selected.children.append(child)
        nodes.append(child)
        if is_new_observation and not nondevelopment:
            _backpropagate(
                child,
                value=increment if increment is not None else 0.0,
                cost=charged_cost,
            )
        trace.append(ExpansionRecord(
            iteration=iteration,
            parent_node_id=selected.node_id,
            node_id=node_id,
            action_id=action.action_id,
            action_mode=action.mode,
            depth=child_state.depth,
            evaluator_seed=evaluator_seed,
            status=(
                "duplicate_observation_not_relearned"
                if not is_new_observation
                else "recorded_non_development_not_learned"
                if nondevelopment
                else observation.status
            ),
            split=observation.split,
            actual_cost=charged_cost,
            learning_increment=increment,
            evidence_ref=observation.evidence_ref,
            path_action_ids=path,
        ))
    else:
        stop_reason = "expansion_budget_exhausted"

    if spent_cost >= total_budget and stop_reason == "completed":
        stop_reason = "cost_budget_exhausted"
    selected_action_id = _recommend_root_action(root, stop_ids)
    first_executed_action_id = _first_executed_action_id(trace)
    return PlanningResult(
        algorithm="mcts",
        enabled=True,
        seed=seed,
        total_budget=total_budget,
        spent_cost=spent_cost,
        prior_incurred_cost=initial_state.incurred_cost,
        cumulative_known_cost=initial_state.incurred_cost + spent_cost,
        expansion_count=len(trace),
        selected_action_id=selected_action_id,
        first_executed_action_id=first_executed_action_id,
        stop_reason=stop_reason,
        trace=tuple(trace),
        nodes=tuple(_record_node(node) for node in nodes),
        failure=failure,
    )


def run_simple_scheduler(
    *,
    enabled: bool = False,
    initial_state: ResearchState,
    actions: tuple[Action, ...],
    evaluator: ActionEvaluator | None = None,
    metric: str,
    direction: int,
    seed: int,
    total_budget: float,
    max_expansions: int,
    max_depth: int = 3,
    exploration_weight: float = 0.0,
    explore_share: float = 0.25,
    stop_action_ids: tuple[str, ...] = (),
    prior_observations: tuple[Observation, ...] = (),
    action_available: ActionAvailability | None = None,
    max_children_per_node: int | None = None,
    avoid_nonpositive_families: bool = False,
    feedback_family: ActionFeedbackFamily | None = None,
) -> PlanningResult:
    """Run the W03 scheduler through the same action/evaluator/budget contract."""
    del exploration_weight, max_children_per_node  # Interface parity; simple has no tree width.
    _validate_initial_state(initial_state)
    _validate_planner_inputs(
        actions=actions,
        metric=metric,
        direction=direction,
        total_budget=total_budget,
        max_expansions=max_expansions,
        max_depth=max_depth,
        explore_share=explore_share,
        stop_action_ids=stop_action_ids,
    )
    prior_by_run_id = _validate_prior_observations(prior_observations)
    availability = action_available or (lambda state, action: True)
    feedback_family_for = feedback_family or (lambda action: action.family)
    if not enabled:
        return PlanningResult(
            algorithm="simple_scheduler",
            enabled=False,
            seed=seed,
            total_budget=total_budget,
            spent_cost=0.0,
            prior_incurred_cost=initial_state.incurred_cost,
            cumulative_known_cost=initial_state.incurred_cost,
            expansion_count=0,
            selected_action_id=None,
            first_executed_action_id=None,
            stop_reason="disabled: explicit opt-in required",
            trace=(),
            nodes=(),
        )
    if evaluator is None:
        raise ValueError("evaluator is required when scheduler is enabled")

    rng = Random(seed)
    state = initial_state
    schedule_state = ScheduleState()
    observations = list(prior_observations)
    observations_by_run_id = dict(prior_by_run_id)
    trace: list[ExpansionRecord] = []
    spent_cost = 0.0
    stop_ids = set(stop_action_ids)
    stop_reason = "completed"
    failure: PlannerFailure | None = None
    discouraged_families: set[str] = set()

    for iteration in range(max_expansions):
        if state.stopped or state.depth >= max_depth:
            stop_reason = "terminal_or_depth_limit"
            break
        remaining_budget = total_budget - spent_cost
        available = tuple(
            action for action in actions
            if action.action_id not in state.completed_action_ids
            and action.estimated_cost <= remaining_budget
            and availability(state, action)
        )
        if avoid_nonpositive_families and discouraged_families:
            alternatives = tuple(
                action for action in available
                if feedback_family_for(action) not in discouraged_families
                and action.action_id not in stop_ids
            )
            if alternatives:
                available = alternatives + tuple(
                    action for action in available if action.action_id in stop_ids
                )
            discouraged_families.clear()
        if not available:
            stop_reason = "no_action_affordable_within_budget"
            break
        candidates = learn_policy(tuple(observations), actions)
        decision = select_action(
            context=state.context,
            actions=available,
            candidates=candidates,
            metric=metric,
            direction=direction,
            remaining_budget=remaining_budget,
            explore_share=explore_share,
            schedule_state=schedule_state,
        )
        if decision.action is None:
            stop_reason = decision.reason
            break
        action = decision.action
        schedule_state = decision.next_schedule_state
        node_id = f"s{iteration + 1:03d}"
        path = state.completed_action_ids + (action.action_id,)
        if action.action_id in stop_ids:
            state = _advance_state(state, action, None, 0.0, stopped=True)
            trace.append(ExpansionRecord(
                iteration, f"s{iteration:03d}", node_id, action.action_id, action.mode,
                state.depth, None, "stopped", None, 0.0, None, None, path,
            ))
            stop_reason = "explicit_stop_action"
            break

        evaluator_seed = rng.randrange(0, 2**63)
        try:
            result = evaluator(state, action, evaluator_seed)
        except Exception as exc:
            failure = PlannerFailure(
                "evaluator_exception", f"{type(exc).__name__}: {exc}",
                action.action_id, True, None,
            )
            trace.append(ExpansionRecord(
                iteration, f"s{iteration:03d}", node_id, action.action_id, action.mode,
                state.depth + 1, evaluator_seed, "evaluator_exception_unknown_cost",
                None, None, None, None, path,
            ))
            stop_reason = "evaluator_exception_unknown_cost"
            break
        try:
            actual_cost = _validate_action_result(
                result=result,
                state=state,
                action=action,
                metric=metric,
                direction=direction,
                remaining_budget=remaining_budget,
            )
        except (TypeError, ValueError) as exc:
            known_cost = _known_actual_cost(result)
            if known_cost is not None:
                spent_cost += known_cost
            failure = PlannerFailure(
                "evaluator_contract_violation", str(exc),
                action.action_id, True, known_cost,
            )
            observation = result.observation if isinstance(result, ActionResult) else None
            trace.append(ExpansionRecord(
                iteration, f"s{iteration:03d}", node_id, action.action_id, action.mode,
                state.depth + 1, evaluator_seed, "evaluator_contract_violation",
                observation.split if observation else None, known_cost, None,
                observation.evidence_ref if observation else None, path,
            ))
            partial = _partial_result(
                algorithm="simple_scheduler",
                initial_state=initial_state,
                seed=seed,
                total_budget=total_budget,
                spent_cost=spent_cost,
                stop_reason="evaluator_contract_violation",
                trace=trace,
                nodes=(),
                selected_action_id=None,
                failure=failure,
            )
            raise PlannerContractError(str(exc), partial) from exc
        observation = result.observation
        try:
            is_new_observation = _register_observation(observation, observations_by_run_id)
        except ValueError as exc:
            spent_cost += actual_cost
            failure = PlannerFailure(
                "conflicting_run_id", str(exc),
                action.action_id, True, actual_cost,
            )
            trace.append(ExpansionRecord(
                iteration, f"s{iteration:03d}", node_id, action.action_id, action.mode,
                state.depth + 1, evaluator_seed, "conflicting_run_id_rejected",
                observation.split, actual_cost, None, observation.evidence_ref, path,
            ))
            partial = _partial_result(
                algorithm="simple_scheduler",
                initial_state=initial_state,
                seed=seed,
                total_budget=total_budget,
                spent_cost=spent_cost,
                stop_reason="conflicting_run_id_rejected",
                trace=trace,
                nodes=(),
                selected_action_id=None,
                failure=failure,
            )
            raise PlannerContractError(str(exc), partial) from exc
        charged_cost = actual_cost if is_new_observation else 0.0
        spent_cost += charged_cost
        if is_new_observation:
            observations.append(observation)
        increment = observation.learning_increment() if is_new_observation else None
        if is_new_observation and observation.split == "development":
            if increment is not None and increment <= 0:
                discouraged_families = {feedback_family_for(action)}
            elif increment is not None:
                discouraged_families.clear()
        nondevelopment = observation.split != "development"
        state = _advance_state(
            state, action, result, charged_cost,
            stopped=result.terminal or nondevelopment,
        )
        trace.append(ExpansionRecord(
            iteration, f"s{iteration:03d}", node_id, action.action_id, action.mode,
            state.depth, evaluator_seed,
            "duplicate_observation_not_relearned"
            if not is_new_observation
            else "recorded_non_development_not_learned"
            if nondevelopment
            else observation.status,
            observation.split, charged_cost, increment, observation.evidence_ref, path,
        ))
    else:
        stop_reason = "expansion_budget_exhausted"

    return PlanningResult(
        algorithm="simple_scheduler",
        enabled=True,
        seed=seed,
        total_budget=total_budget,
        spent_cost=spent_cost,
        prior_incurred_cost=initial_state.incurred_cost,
        cumulative_known_cost=initial_state.incurred_cost + spent_cost,
        expansion_count=len(trace),
        selected_action_id=None,
        first_executed_action_id=_first_executed_action_id(trace),
        stop_reason=stop_reason,
        trace=tuple(trace),
        nodes=(),
        failure=failure,
    )


def _validate_planner_inputs(
    *,
    actions: tuple[Action, ...],
    metric: str,
    direction: int,
    total_budget: float,
    max_expansions: int,
    max_depth: int,
    explore_share: float,
    stop_action_ids: tuple[str, ...],
) -> None:
    if not actions or len({action.action_id for action in actions}) != len(actions):
        raise ValueError("actions must be nonempty with unique action ids")
    if not metric:
        raise ValueError("metric is required")
    if direction not in {-1, 1}:
        raise ValueError("direction must be +1 or -1")
    if not isfinite(total_budget) or total_budget < 0:
        raise ValueError("total_budget must be finite and non-negative")
    if not isinstance(max_expansions, int) or max_expansions < 1:
        raise ValueError("max_expansions must be a positive integer")
    if not isinstance(max_depth, int) or max_depth < 1:
        raise ValueError("max_depth must be a positive integer")
    if not 0 <= explore_share <= 1:
        raise ValueError("explore_share must be within [0, 1]")
    action_by_id = {action.action_id: action for action in actions}
    if len(set(stop_action_ids)) != len(stop_action_ids):
        raise ValueError("stop_action_ids cannot repeat")
    for action_id in stop_action_ids:
        action = action_by_id.get(action_id)
        if action is None:
            raise ValueError(f"unknown stop action: {action_id}")
        if action.estimated_cost != 0:
            raise ValueError("stop actions must reserve zero cost")


def _validate_initial_state(initial_state: ResearchState) -> None:
    if initial_state.context.stage != "development":
        raise ValueError("bounded planners accept development context only")


def _validate_prior_observations(
    observations: tuple[Observation, ...],
) -> dict[str, Observation]:
    by_run_id: dict[str, Observation] = {}
    for observation in observations:
        if observation.split != "development":
            raise ValueError("prior observations must be development-only")
        _register_observation(observation, by_run_id)
    return by_run_id


def _register_observation(
    observation: Observation,
    observations_by_run_id: dict[str, Observation],
) -> bool:
    previous = observations_by_run_id.get(observation.run_id)
    if previous is None:
        observations_by_run_id[observation.run_id] = observation
        return True
    if previous != observation:
        raise ValueError(f"conflicting duplicate run_id: {observation.run_id}")
    return False


def _known_actual_cost(result: object) -> float | None:
    if not isinstance(result, ActionResult):
        return None
    cost = result.observation.actual_cost
    if cost is None or not isfinite(cost) or cost < 0:
        return None
    return cost


def _first_executed_action_id(trace: list[ExpansionRecord]) -> str | None:
    return next((row.action_id for row in trace if row.evaluator_seed is not None), None)


def _partial_result(
    *,
    algorithm: Literal["mcts", "simple_scheduler"],
    initial_state: ResearchState,
    seed: int,
    total_budget: float,
    spent_cost: float,
    stop_reason: str,
    trace: list[ExpansionRecord],
    nodes: list[_Node] | tuple[_Node, ...],
    selected_action_id: str | None,
    failure: PlannerFailure,
) -> PlanningResult:
    return PlanningResult(
        algorithm=algorithm,
        enabled=True,
        seed=seed,
        total_budget=total_budget,
        spent_cost=spent_cost,
        prior_incurred_cost=initial_state.incurred_cost,
        cumulative_known_cost=initial_state.incurred_cost + spent_cost,
        expansion_count=len(trace),
        selected_action_id=selected_action_id,
        first_executed_action_id=_first_executed_action_id(trace),
        stop_reason=stop_reason,
        trace=tuple(trace),
        nodes=tuple(_record_node(node) for node in nodes),
        failure=failure,
    )


def _untried_affordable_actions(
    node: _Node,
    actions: tuple[Action, ...],
    remaining_budget: float,
    action_available: ActionAvailability,
    max_children_per_node: int | None,
) -> tuple[Action, ...]:
    if node.state.stopped:
        return ()
    if (
        max_children_per_node is not None
        and len(node.expanded_action_ids) >= max_children_per_node
    ):
        return ()
    return tuple(
        action for action in actions
        if action.action_id not in node.state.completed_action_ids
        and action.action_id not in node.expanded_action_ids
        and action.estimated_cost <= remaining_budget
        and action_available(node.state, action)
    )


def _select_expandable_node(
    *,
    root: _Node,
    actions: tuple[Action, ...],
    remaining_budget: float,
    max_depth: int,
    exploration_weight: float,
    rng: Random,
    action_available: ActionAvailability,
    max_children_per_node: int | None,
) -> _Node | None:
    node = root
    while True:
        if node.state.depth < max_depth and _untried_affordable_actions(
            node, actions, remaining_budget, action_available, max_children_per_node
        ):
            return node
        candidates = [
            child for child in node.children
            if _has_expandable_descendant(
                child, actions, remaining_budget, max_depth, action_available,
                max_children_per_node,
            )
        ]
        if not candidates:
            return None
        parent_visits = max(1, node.visits)
        scored = []
        for child in candidates:
            exploitation = (
                child.evidence_efficiency
                if child.evidence_efficiency is not None
                else child.mean_value
            )
            exploration = exploration_weight * sqrt(log(parent_visits + 1) / max(1, child.visits))
            scored.append((exploitation + exploration, child))
        best_score = max(score for score, _ in scored)
        tied = sorted(
            (child for score, child in scored if abs(score - best_score) <= 1e-15),
            key=lambda child: child.node_id,
        )
        node = rng.choice(tied)


def _has_expandable_descendant(
    node: _Node,
    actions: tuple[Action, ...],
    remaining_budget: float,
    max_depth: int,
    action_available: ActionAvailability,
    max_children_per_node: int | None,
) -> bool:
    if node.state.stopped or node.state.depth >= max_depth:
        return False
    if _untried_affordable_actions(
        node, actions, remaining_budget, action_available, max_children_per_node
    ):
        return True
    return any(
        _has_expandable_descendant(
            child, actions, remaining_budget, max_depth, action_available,
            max_children_per_node
        )
        for child in node.children
    )


def _choose_expansion_action(
    *,
    available: tuple[Action, ...],
    trace: list[ExpansionRecord],
    explore_share: float,
    rng: Random,
    context: Context,
    metric: str,
    direction: int,
    prior_candidates: tuple[PolicyCandidate, ...],
) -> Action:
    explore = tuple(action for action in available if action.mode == "explore")
    exploit = tuple(action for action in available if action.mode == "exploit")
    previous_explore = sum(row.action_mode == "explore" for row in trace)
    desired_explore_after = int((len(trace) + 1) * explore_share)
    pool = explore if explore and (not exploit or previous_explore < desired_explore_after) else exploit
    pool = pool or explore
    compatible = {
        candidate.family: candidate
        for candidate in prior_candidates
        if candidate.context == context
        and candidate.protocol_id == context.evaluation_protocol
        and candidate.metric == metric
        and candidate.direction == direction
    }
    scored = [(compatible[action.family], action) for action in pool if action.family in compatible]
    if not scored:
        return rng.choice(tuple(sorted(pool, key=lambda action: action.action_id)))
    best_key = max(
        (
            candidate.efficiency is not None,
            candidate.efficiency if candidate.efficiency is not None else candidate.mean_increment,
            candidate.mean_increment,
        )
        for candidate, _ in scored
    )
    tied = sorted(
        (
            action for candidate, action in scored
            if (
                candidate.efficiency is not None,
                candidate.efficiency if candidate.efficiency is not None else candidate.mean_increment,
                candidate.mean_increment,
            ) == best_key
        ),
        key=lambda action: action.action_id,
    )
    return rng.choice(tied)


def _validate_action_result(
    *,
    result: ActionResult,
    state: ResearchState,
    action: Action,
    metric: str,
    direction: int,
    remaining_budget: float,
) -> float:
    if not isinstance(result, ActionResult):
        raise TypeError("evaluator must return ActionResult")
    observation = result.observation
    if observation.action_id != action.action_id:
        raise ValueError("observation action_id does not match expanded action")
    if observation.context != state.context:
        raise ValueError("observation context does not match branch context")
    if observation.protocol_id != state.context.evaluation_protocol:
        raise ValueError("observation protocol does not match branch protocol")
    if observation.metric != metric or observation.direction != direction:
        raise ValueError("observation metric or direction does not match planner protocol")
    if observation.actual_cost is None:
        raise ValueError("actual_cost is required for every attempted action")
    actual_cost = observation.actual_cost
    if actual_cost > action.estimated_cost + 1e-12:
        raise ValueError("actual_cost exceeds the action reservation cap")
    if actual_cost > remaining_budget + 1e-12:
        raise ValueError("actual_cost exceeds remaining hard budget")
    if result.experiment_ref is not None and not result.experiment_ref.strip():
        raise ValueError("experiment_ref cannot be blank")
    return actual_cost


def _advance_state(
    state: ResearchState,
    action: Action,
    result: ActionResult | None,
    actual_cost: float,
    *,
    stopped: bool,
) -> ResearchState:
    if result is None:
        hypothesis_ref = state.hypothesis_ref
        prediction_refs = state.prediction_refs
        competing_refs = state.competing_explanation_refs
        experiment_refs = state.experiment_refs
    else:
        hypothesis_ref = result.hypothesis_ref or state.hypothesis_ref
        prediction_refs = tuple(dict.fromkeys(state.prediction_refs + result.added_prediction_refs))
        competing_refs = tuple(dict.fromkeys(
            state.competing_explanation_refs + result.added_competing_explanation_refs
        ))
        experiment_ref = result.experiment_ref or result.observation.evidence_ref
        experiment_refs = state.experiment_refs + ((experiment_ref,) if experiment_ref else ())
    return ResearchState(
        context=state.context,
        hypothesis_ref=hypothesis_ref,
        prediction_refs=prediction_refs,
        competing_explanation_refs=competing_refs,
        experiment_refs=experiment_refs,
        completed_action_ids=state.completed_action_ids + (action.action_id,),
        incurred_cost=state.incurred_cost + actual_cost,
        depth=state.depth + 1,
        stopped=stopped,
    )


def _backpropagate(node: _Node, *, value: float, cost: float) -> None:
    current: _Node | None = node
    while current is not None:
        current.visits += 1
        current.value_sum += value
        current.cost_sum += cost
        current = current.parent


def _recommend_root_action(root: _Node, stop_action_ids: set[str]) -> str | None:
    candidates = [
        child for child in root.children
        if child.action is not None
        and child.action.action_id not in stop_action_ids
        and child.development_evidence is not False
    ]
    if not candidates:
        return None
    if stop_action_ids:
        # STOP is the explicit zero-utility outside option.  A failed branch has
        # zero evidence value and a negatively observed branch is below zero.
        # Registration makes this outside option available; it need not consume
        # a tree expansion before it can defeat a non-positive branch.
        candidates = [
            child for child in candidates
            if (
                child.evidence_efficiency
                if child.evidence_efficiency is not None
                else child.mean_value
            ) > 0
        ]
        if not candidates:
            return None
    chosen = max(
        candidates,
        key=lambda child: (
            child.visits,
            child.evidence_efficiency is not None,
            child.evidence_efficiency if child.evidence_efficiency is not None else child.mean_value,
            child.mean_value,
            child.action.action_id,
        ),
    )
    return chosen.action.action_id


def _record_node(node: _Node) -> NodeRecord:
    return NodeRecord(
        node_id=node.node_id,
        parent_node_id=node.parent.node_id if node.parent else None,
        action_id=node.action.action_id if node.action else None,
        depth=node.state.depth,
        visits=node.visits,
        value_sum=node.value_sum,
        cost_sum=node.cost_sum,
        mean_value=node.mean_value,
        evidence_efficiency=node.evidence_efficiency,
        terminal=node.state.stopped,
        development_evidence=node.development_evidence,
        completed_action_ids=node.state.completed_action_ids,
    )
