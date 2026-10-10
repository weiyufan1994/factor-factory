"""Level-one research actions over substantive mechanism states.

The mature hybrid action-tree engine supplies bounded MCTS. This adapter keeps
mechanism conclusions, discriminating-test utility, and lower-level expression
scores as separate objects. A useful refutation can therefore advance research
without being treated as a negative reward.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Callable

from factor_factory.hybrid_research.decision import Action, Context, Observation
from factor_factory.hybrid_research.mcts import (
    ActionResult, PlanningResult, ResearchState as ActionTreeState, run_action_mcts,
)

from .induction import ForwardInductionRecord


@dataclass(frozen=True)
class Prediction:
    prediction_id: str
    statement: str
    discriminates_against: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.prediction_id or not self.statement or not self.discriminates_against:
            raise ValueError("prediction requires content and a competing explanation")


@dataclass(frozen=True)
class MechanismState:
    state_id: str
    mechanism: str
    response_family: str
    response_structure: str
    induction_record_hash: str
    assumptions: tuple[str, ...]
    predictions: tuple[Prediction, ...]
    competing_mechanisms: tuple[str, ...]
    unknowns: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    implementation_scores: tuple[float, ...] = ()
    mechanism_assessment: str = "unknown"
    status: str = "active"
    depth: int = 0

    def __post_init__(self) -> None:
        required = (self.state_id, self.mechanism, self.response_family,
                    self.response_structure, self.induction_record_hash)
        if not all(required) or not self.assumptions or not self.predictions or not self.competing_mechanisms:
            raise ValueError("mechanism state requires content, induction, predictions, and competitors")
        if self.status not in {"active", "stopped", "observationally_equivalent", "needs_induction"}:
            raise ValueError("unsupported mechanism state status")
        if self.mechanism_assessment not in {"unknown", "supported", "refuted", "observationally_equivalent"}:
            raise ValueError("unsupported mechanism assessment")


@dataclass(frozen=True)
class ResearchAction:
    action_id: str
    kind: str
    mode: str
    estimated_cost: float
    rationale: str
    mechanism: str | None = None
    response_family: str | None = None
    response_structure: str | None = None
    induction_record: ForwardInductionRecord | None = None
    add_assumptions: tuple[str, ...] = ()
    add_predictions: tuple[Prediction, ...] = ()
    resolve_unknowns: tuple[str, ...] = ()
    add_unknowns: tuple[str, ...] = ()
    requires_assessment: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed = {"deepen", "estimate", "derive_new_structure", "design_discriminating_experiment",
                   "check_observation", "stop"}
        if self.kind not in allowed or self.mode not in {"exploit", "explore"}:
            raise ValueError("unsupported research action")
        if not self.action_id or not self.rationale or not isfinite(self.estimated_cost) or self.estimated_cost < 0:
            raise ValueError("research action requires identity, rationale, and nonnegative cost")
        allowed_assessments = {"unknown", "supported", "refuted", "observationally_equivalent"}
        if not set(self.requires_assessment).issubset(allowed_assessments):
            raise ValueError("unsupported assessment precondition")


@dataclass(frozen=True)
class ExperimentEvidence:
    evidence_ref: str
    prediction_id: str
    protocol_id: str
    outcome: str
    comparable: bool
    discriminating: bool
    test_utility: float | None

    def __post_init__(self) -> None:
        if self.outcome not in {"supports", "refutes", "observationally_equivalent", "unknown"}:
            raise ValueError("unsupported evidence outcome")
        if not self.evidence_ref or not self.prediction_id or not self.protocol_id:
            raise ValueError("evidence requires prediction, protocol, and reference")
        if self.test_utility is not None and (
                not isfinite(self.test_utility) or not 0 <= self.test_utility <= 1):
            raise ValueError("test utility must be bounded in [0, 1]")

    def is_bound(self, state: MechanismState, expected_protocol: str) -> bool:
        return (self.prediction_id in {row.prediction_id for row in state.predictions}
                and self.protocol_id == expected_protocol and self.comparable)

    def research_reward(self, state: MechanismState, expected_protocol: str) -> float | None:
        if (not self.is_bound(state, expected_protocol) or not self.discriminating
                or self.outcome not in {"supports", "refutes"}):
            return None
        return self.test_utility


@dataclass(frozen=True)
class MechanismEvaluation:
    evidence: ExperimentEvidence
    actual_cost: float
    implementation_score: float | None = None


@dataclass(frozen=True)
class MechanismExpansion:
    path: tuple[str, ...]
    parent_state_id: str
    successor: MechanismState
    evidence: ExperimentEvidence | None
    research_reward: float | None
    implementation_score: float | None


@dataclass(frozen=True)
class MechanismSearchResult:
    planning: PlanningResult
    expansions: tuple[MechanismExpansion, ...]
    decision: str


MechanismEvaluator = Callable[[MechanismState, ResearchAction, int], MechanismEvaluation]


def apply_research_action(state: MechanismState, action: ResearchAction) -> MechanismState:
    if state.status != "active":
        raise ValueError("cannot expand a terminal mechanism state")
    if action.kind == "stop":
        return replace(state, state_id=f"{state.state_id}/{action.action_id}", status="stopped", depth=state.depth + 1)
    predictions = {row.prediction_id: row for row in state.predictions}
    for row in action.add_predictions:
        if row.prediction_id in predictions and predictions[row.prediction_id] != row:
            raise ValueError("prediction id cannot be overwritten with new content")
        predictions[row.prediction_id] = row
    changes_response = bool(
        (action.response_structure and action.response_structure != state.response_structure)
        or (action.response_family and action.response_family != state.response_family)
    )
    changes_economics = bool(
        (action.mechanism and action.mechanism != state.mechanism)
        or action.add_assumptions
    )
    requires_induction = changes_response or changes_economics
    if requires_induction and action.induction_record is None:
        return replace(state, state_id=f"{state.state_id}/{action.action_id}", status="needs_induction",
                       depth=state.depth + 1)
    if requires_induction:
        assert action.induction_record is not None
        expected_family = action.response_family or state.response_family
        if (not action.induction_record.parent_delta
                or action.induction_record.response_family != expected_family):
            raise ValueError("changed economics or response requires a matching induction delta")
    assumptions = tuple(dict.fromkeys(state.assumptions + action.add_assumptions))
    unknowns = tuple(row for row in state.unknowns if row not in set(action.resolve_unknowns))
    unknowns = tuple(dict.fromkeys(unknowns + action.add_unknowns))
    successor = MechanismState(
        state_id=f"{state.state_id}/{action.action_id}", mechanism=action.mechanism or state.mechanism,
        response_family=action.response_family or state.response_family,
        response_structure=action.response_structure or state.response_structure,
        induction_record_hash=(action.induction_record.record_hash if requires_induction else state.induction_record_hash),
        assumptions=assumptions, predictions=tuple(predictions.values()),
        competing_mechanisms=state.competing_mechanisms, unknowns=unknowns,
        evidence_refs=state.evidence_refs, implementation_scores=state.implementation_scores,
        mechanism_assessment=state.mechanism_assessment, status="active", depth=state.depth + 1,
    )
    before = (state.mechanism, state.response_structure, state.assumptions, state.predictions, state.unknowns)
    after = (successor.mechanism, successor.response_structure, successor.assumptions,
             successor.predictions, successor.unknowns)
    if before == after:
        raise ValueError("research action must create a substantive successor state")
    return successor


def run_mechanism_mcts(
    *, initial_state: MechanismState, actions: tuple[ResearchAction, ...], evaluator: MechanismEvaluator,
    protocol_id: str, seed: int, total_budget: float, max_expansions: int, max_depth: int = 3,
) -> MechanismSearchResult:
    context = Context.from_mapping(stage="development", objective=initial_state.mechanism,
                                   conditions={"research_layer": "mechanism_search",
                                               "response_structure": initial_state.response_structure},
                                   evaluation_protocol=protocol_id)
    registered = tuple(Action(row.action_id, row.kind, row.mode, row.estimated_cost, row.rationale)
                       for row in actions)
    by_id = {row.action_id: row for row in actions}
    states: dict[tuple[str, ...], MechanismState] = {(): initial_state}
    expansions: list[MechanismExpansion] = []

    def evaluate(tree_state: ActionTreeState, tree_action: Action, evaluator_seed: int) -> ActionResult:
        path = tree_state.completed_action_ids
        parent = states[path]
        action = by_id[tree_action.action_id]
        successor = apply_research_action(parent, action)
        child_path = path + (action.action_id,)
        if successor.status == "needs_induction":
            states[child_path] = successor
            expansions.append(MechanismExpansion(child_path, parent.state_id, successor, None, None, None))
            observation = Observation(
                run_id="mechanism:" + "/".join(child_path), action_id=action.action_id, context=context,
                split="development", protocol_id=protocol_id, metric="discriminating_test_utility", direction=1,
                baseline=None, result=None, scale=None, actual_cost=0.0, status="unknown", evidence_ref=None)
            return ActionResult(observation=observation, hypothesis_ref=successor.state_id, terminal=True)
        result = evaluator(parent, action, evaluator_seed)
        if not isinstance(result, MechanismEvaluation):
            raise TypeError("mechanism evaluator must return MechanismEvaluation")
        evidence = result.evidence
        bound = evidence.is_bound(successor, protocol_id)
        reward = evidence.research_reward(successor, protocol_id)
        assessment = successor.mechanism_assessment
        status = successor.status
        if bound and evidence.discriminating and evidence.outcome in {"supports", "refutes"}:
            assessment = "supported" if evidence.outcome == "supports" else "refuted"
        elif bound and evidence.outcome == "observationally_equivalent":
            assessment, status = "observationally_equivalent", "observationally_equivalent"
        successor = replace(
            successor, evidence_refs=successor.evidence_refs + (evidence.evidence_ref,),
            implementation_scores=(successor.implementation_scores
                                   + ((result.implementation_score,) if result.implementation_score is not None else ())),
            mechanism_assessment=assessment, status=status,
        )
        states[child_path] = successor
        expansions.append(MechanismExpansion(child_path, parent.state_id, successor, evidence,
                                             reward, result.implementation_score))
        observation = Observation(
            run_id="mechanism:" + "/".join(child_path), action_id=action.action_id, context=context,
            split="development", protocol_id=protocol_id, metric="discriminating_test_utility", direction=1,
            baseline=0.0 if reward is not None else None, result=reward, scale=1.0 if reward is not None else None,
            actual_cost=result.actual_cost, status="completed", evidence_ref=evidence.evidence_ref)
        return ActionResult(
            observation=observation, hypothesis_ref=successor.state_id,
            added_prediction_refs=tuple(row.prediction_id for row in action.add_predictions),
            added_competing_explanation_refs=successor.competing_mechanisms,
            experiment_ref=evidence.evidence_ref,
            terminal=successor.status != "active" or reward is None,
        )

    def available(tree_state: ActionTreeState, tree_action: Action) -> bool:
        state = states[tree_state.completed_action_ids]
        action = by_id[tree_action.action_id]
        return (state.status == "active" and tree_action.action_id not in tree_state.completed_action_ids
                and (not action.requires_assessment or state.mechanism_assessment in action.requires_assessment))

    planning = run_action_mcts(
        enabled=True,
        initial_state=ActionTreeState(context, initial_state.state_id,
                                      tuple(row.prediction_id for row in initial_state.predictions),
                                      initial_state.competing_mechanisms),
        actions=registered, evaluator=evaluate, metric="discriminating_test_utility", direction=1,
        seed=seed, total_budget=total_budget, max_expansions=max_expansions, max_depth=max_depth,
        action_available=available, stop_action_ids=tuple(row.action_id for row in actions if row.kind == "stop"),
    )
    rewarded = [row for row in expansions if row.research_reward is not None]
    needs_induction = any(row.successor.status == "needs_induction" for row in expansions)
    decision = ("needs_induction" if needs_induction else "recommend_follow_up" if planning.selected_action_id
                else "needs_discriminating_evidence" if expansions and not rewarded else "no_supported_action")
    return MechanismSearchResult(planning, tuple(expansions), decision)
