"""Pure, replayable one-step planners for asynchronous research search.

The module does not dispatch evaluations or persist state.  It rebuilds a
candidate tree from validated JSON-like proposals and terminal development
feedback, then selects at most one not-yet-evaluated candidate.  Pending work
must be withheld by the controller and never represented as feedback here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite, log, sqrt
from numbers import Real
from typing import Any, Literal


PlannerKind = Literal["mcts", "registered_queue"]
_PLANNER_KINDS = {"mcts", "registered_queue"}
_TERMINAL_STATUSES = {
    "completed",
    "failed_known_cost",
    "failed_unknown_cost",
    "blocked",
    "unknown",
}


@dataclass(frozen=True)
class _Proposal:
    candidate_hash: str
    parent_candidate_hash: str | None
    estimated_cost: float


@dataclass(frozen=True)
class _Feedback:
    candidate_hash: str
    status: str
    learning_increment: float | None
    actual_cost: float | None
    candidate_score: float | None


@dataclass
class _Stats:
    visits: int = 0
    value_sum: float = 0.0
    cost_sum: float = 0.0

    @property
    def mean_value(self) -> float:
        return self.value_sum / self.visits if self.visits else 0.0

    @property
    def exploitation(self) -> float:
        return self.value_sum / self.cost_sum if self.cost_sum > 0 else self.mean_value


def plan_next(
    proposals: Sequence[Mapping[str, Any]],
    feedback: Sequence[Mapping[str, Any]],
    *,
    root_candidate_hash: str,
    seed: int,
    max_depth: int = 3,
    exploration_weight: float = 1.0,
    planner_kind: PlannerKind = "mcts",
) -> dict[str, Any] | None:
    """Select one eligible unevaluated candidate from terminal feedback only.

    ``candidate_score`` is never used for tree selection.  It is reported only
    as ``best_completed_candidate_hash`` after an upstream score contract has
    made scores comparable and higher-is-better.  ``learning_increment`` is the
    sole tree reward.  Missing increments remain missing and are never filled
    with zero.
    """
    _validate_scalar_inputs(
        root_candidate_hash=root_candidate_hash,
        seed=seed,
        max_depth=max_depth,
        exploration_weight=exploration_weight,
        planner_kind=planner_kind,
    )
    proposal_by_hash = _parse_proposals(proposals)
    feedback_by_hash = _parse_feedback(feedback, proposal_by_hash)
    children, depths = _validate_tree(proposal_by_hash, root_candidate_hash)
    best = _best_completed_candidate(feedback_by_hash)
    if planner_kind == "registered_queue":
        return _plan_registered_queue(
            proposal_by_hash=proposal_by_hash,
            feedback_by_hash=feedback_by_hash,
            depths=depths,
            root_candidate_hash=root_candidate_hash,
            seed=seed,
            max_depth=max_depth,
            best_completed_candidate_hash=best,
        )
    stats = _rebuild_stats(proposal_by_hash, feedback_by_hash)
    return _plan_mcts(
        proposal_by_hash=proposal_by_hash,
        feedback_by_hash=feedback_by_hash,
        children=children,
        depths=depths,
        stats=stats,
        root_candidate_hash=root_candidate_hash,
        seed=seed,
        max_depth=max_depth,
        exploration_weight=float(exploration_weight),
        best_completed_candidate_hash=best,
    )


def _validate_scalar_inputs(
    *,
    root_candidate_hash: str,
    seed: int,
    max_depth: int,
    exploration_weight: float,
    planner_kind: str,
) -> None:
    if not isinstance(root_candidate_hash, str) or not root_candidate_hash:
        raise ValueError("root_candidate_hash must be a nonempty string")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(max_depth) is not int or max_depth < 0:
        raise ValueError("max_depth must be a non-negative integer")
    if not _finite_real(exploration_weight) or exploration_weight < 0:
        raise ValueError("exploration_weight must be finite and non-negative")
    if planner_kind not in _PLANNER_KINDS:
        raise ValueError("planner_kind must be mcts or registered_queue")


def _parse_proposals(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, _Proposal]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
        raise ValueError("proposals must be a nonempty sequence")
    parsed: dict[str, _Proposal] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"proposal[{index}] must be an object")
        _require_json_value(raw, path=f"proposals[{index}]")
        candidate_hash = raw.get("candidate_hash")
        parent_hash = raw.get("parent_candidate_hash")
        estimated_cost = raw.get("estimated_cost")
        if not isinstance(candidate_hash, str) or not candidate_hash:
            raise ValueError(f"proposal[{index}].candidate_hash")
        if parent_hash is not None and (
            not isinstance(parent_hash, str) or not parent_hash
        ):
            raise ValueError(f"proposal[{index}].parent_candidate_hash")
        if not _finite_real(estimated_cost) or estimated_cost < 0:
            raise ValueError(f"proposal[{index}].estimated_cost")
        if candidate_hash in parsed:
            raise ValueError(f"duplicate proposal candidate_hash: {candidate_hash}")
        parsed[candidate_hash] = _Proposal(
            candidate_hash, parent_hash, float(estimated_cost)
        )
    return parsed


def _parse_feedback(
    rows: Sequence[Mapping[str, Any]],
    proposals: Mapping[str, _Proposal],
) -> dict[str, _Feedback]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise ValueError("feedback must be a sequence")
    parsed: dict[str, _Feedback] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError(f"feedback[{index}] must be an object")
        _require_json_value(raw, path=f"feedback[{index}]")
        split = raw.get("split", "development")
        if split != "development":
            raise ValueError(f"feedback[{index}] must be development-only")
        if any(key in raw for key in ("confirmation", "oos", "final")):
            raise ValueError(f"feedback[{index}] contains forbidden held-out fields")
        candidate_hash = raw.get("candidate_hash")
        status = raw.get("status")
        increment = raw.get("learning_increment")
        actual_cost = raw.get("actual_cost")
        candidate_score = raw.get("candidate_score")
        if not isinstance(candidate_hash, str) or not candidate_hash:
            raise ValueError(f"feedback[{index}].candidate_hash")
        if candidate_hash not in proposals:
            raise ValueError(f"feedback[{index}].candidate_hash is not registered")
        if candidate_hash in parsed:
            raise ValueError(f"duplicate feedback candidate_hash: {candidate_hash}")
        if not isinstance(status, str) or status not in _TERMINAL_STATUSES:
            raise ValueError(f"feedback[{index}].status is not terminal")
        if increment is not None and (
            not _finite_real(increment) or not -1 <= increment <= 1
        ):
            raise ValueError(f"feedback[{index}].learning_increment")
        if actual_cost is not None and (
            not _finite_real(actual_cost) or actual_cost < 0
        ):
            raise ValueError(f"feedback[{index}].actual_cost")
        if candidate_score is not None and not _finite_real(candidate_score):
            raise ValueError(f"feedback[{index}].candidate_score")
        if status != "completed" and (
            increment is not None or candidate_score is not None
        ):
            raise ValueError(
                f"feedback[{index}] non-completed status cannot carry reward or score"
            )
        if status == "failed_known_cost" and actual_cost is None:
            raise ValueError(f"feedback[{index}] failed_known_cost requires actual_cost")
        if status == "failed_unknown_cost" and actual_cost is not None:
            raise ValueError(f"feedback[{index}] failed_unknown_cost forbids actual_cost")
        parsed[candidate_hash] = _Feedback(
            candidate_hash=candidate_hash,
            status=str(status),
            learning_increment=(float(increment) if increment is not None else None),
            actual_cost=(float(actual_cost) if actual_cost is not None else None),
            candidate_score=(
                float(candidate_score) if candidate_score is not None else None
            ),
        )
    return parsed


def _validate_tree(
    proposals: Mapping[str, _Proposal],
    root_candidate_hash: str,
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    if root_candidate_hash not in proposals:
        raise ValueError("root_candidate_hash is not registered")
    if proposals[root_candidate_hash].parent_candidate_hash is not None:
        raise ValueError("root candidate must not have a parent")
    children_lists: dict[str, list[str]] = {key: [] for key in proposals}
    for candidate_hash, proposal in proposals.items():
        parent = proposal.parent_candidate_hash
        if candidate_hash == root_candidate_hash:
            continue
        if parent is None:
            continue
        if parent not in proposals:
            raise ValueError(f"missing parent for candidate: {candidate_hash}")
        children_lists[parent].append(candidate_hash)
    children = {
        key: tuple(sorted(values)) for key, values in children_lists.items()
    }
    depths: dict[str, int] = {}
    visiting: set[str] = set()

    def visit(candidate_hash: str) -> int:
        if candidate_hash in depths:
            return depths[candidate_hash]
        if candidate_hash in visiting:
            raise ValueError("candidate parent cycle")
        visiting.add(candidate_hash)
        parent = proposals[candidate_hash].parent_candidate_hash
        depth = 0 if parent is None else visit(parent) + 1
        visiting.remove(candidate_hash)
        depths[candidate_hash] = depth
        return depth

    for candidate_hash in proposals:
        visit(candidate_hash)
    unreachable = sorted(
        candidate_hash
        for candidate_hash in proposals
        if not _is_descendant_of(candidate_hash, root_candidate_hash, proposals)
    )
    if unreachable:
        raise ValueError("candidates are not reachable from root: " + ",".join(unreachable))
    return children, depths


def _is_descendant_of(
    candidate_hash: str,
    root_candidate_hash: str,
    proposals: Mapping[str, _Proposal],
) -> bool:
    current: str | None = candidate_hash
    seen: set[str] = set()
    while current is not None:
        if current == root_candidate_hash:
            return True
        if current in seen:
            return False
        seen.add(current)
        current = proposals[current].parent_candidate_hash
    return False


def _rebuild_stats(
    proposals: Mapping[str, _Proposal],
    feedback: Mapping[str, _Feedback],
) -> dict[str, _Stats]:
    stats = {candidate_hash: _Stats() for candidate_hash in proposals}
    for candidate_hash in sorted(feedback):
        row = feedback[candidate_hash]
        if row.learning_increment is None:
            continue
        current: str | None = row.candidate_hash
        while current is not None:
            state = stats[current]
            state.visits += 1
            state.value_sum += row.learning_increment
            if row.actual_cost is not None:
                state.cost_sum += row.actual_cost
            current = proposals[current].parent_candidate_hash
    return stats


def _best_completed_candidate(
    feedback: Mapping[str, _Feedback],
) -> str | None:
    eligible = [
        row for row in feedback.values()
        if row.status == "completed"
        and row.candidate_score is not None
        and row.candidate_score > 0
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda row: (-float(row.candidate_score), row.candidate_hash),
    )[0].candidate_hash


def _plan_registered_queue(
    *,
    proposal_by_hash: Mapping[str, _Proposal],
    feedback_by_hash: Mapping[str, _Feedback],
    depths: Mapping[str, int],
    root_candidate_hash: str,
    seed: int,
    max_depth: int,
    best_completed_candidate_hash: str | None,
) -> dict[str, Any] | None:
    candidates = [
        candidate_hash
        for candidate_hash in proposal_by_hash
        if candidate_hash not in feedback_by_hash
        and depths[candidate_hash] <= max_depth
        and _ancestors_resolved(
            candidate_hash, proposal_by_hash, feedback_by_hash
        )
    ]
    if not candidates:
        return None
    chosen = sorted(
        candidates,
        key=lambda item: (
            depths[item],
            proposal_by_hash[item].parent_candidate_hash or "",
            item,
        ),
    )[0]
    path = _path_to_root(chosen, proposal_by_hash)
    return {
        "planner_kind": "registered_queue",
        "candidate_hash": chosen,
        "path": path,
        "seed": seed,
        "best_completed_candidate_hash": best_completed_candidate_hash,
        "selection_trace": [
            {
                "node_candidate_hash": path[-2] if len(path) > 1 else root_candidate_hash,
                "depth": depths[chosen],
                "reason": "registered_queue",
                "untried_children": sorted(candidates),
                "expandable_children": [],
                "uct_scores": [],
                "chosen_candidate_hash": chosen,
                "estimated_cost": proposal_by_hash[chosen].estimated_cost,
            }
        ],
    }


def _plan_mcts(
    *,
    proposal_by_hash: Mapping[str, _Proposal],
    feedback_by_hash: Mapping[str, _Feedback],
    children: Mapping[str, tuple[str, ...]],
    depths: Mapping[str, int],
    stats: Mapping[str, _Stats],
    root_candidate_hash: str,
    seed: int,
    max_depth: int,
    exploration_weight: float,
    best_completed_candidate_hash: str | None,
) -> dict[str, Any] | None:
    if root_candidate_hash not in feedback_by_hash:
        return _decision(
            planner_kind="mcts",
            chosen=root_candidate_hash,
            path=[root_candidate_hash],
            seed=seed,
            best=best_completed_candidate_hash,
            trace=[{
                "node_candidate_hash": root_candidate_hash,
                "depth": 0,
                "reason": "root_unexecuted",
                "untried_children": [root_candidate_hash],
                "expandable_children": [],
                "uct_scores": [],
                "chosen_candidate_hash": root_candidate_hash,
                "estimated_cost": proposal_by_hash[root_candidate_hash].estimated_cost,
            }],
        )
    current = root_candidate_hash
    path = [current]
    trace: list[dict[str, Any]] = []
    while depths[current] < max_depth:
        direct = [
            child for child in children[current]
            if depths[child] <= max_depth
        ]
        untried = [child for child in direct if child not in feedback_by_hash]
        if untried:
            chosen = _seeded_choice(
                sorted(untried), seed=seed, path=path, stage="untried"
            )
            trace.append({
                "node_candidate_hash": current,
                "depth": depths[current],
                "reason": "fair_untried_sibling",
                "untried_children": sorted(untried),
                "expandable_children": sorted(direct),
                "uct_scores": [],
                "chosen_candidate_hash": chosen,
                "estimated_cost": proposal_by_hash[chosen].estimated_cost,
            })
            return _decision(
                planner_kind="mcts", chosen=chosen, path=path + [chosen],
                seed=seed, best=best_completed_candidate_hash, trace=trace,
            )
        expandable = [
            child for child in direct
            if _has_untried_descendant(
                child, children, feedback_by_hash, depths, max_depth
            )
        ]
        if not expandable:
            return None
        parent_visits = stats[current].visits
        scored = []
        for child in sorted(expandable):
            state = stats[child]
            exploration = exploration_weight * sqrt(
                log(parent_visits + 1) / max(1, state.visits)
            )
            total = state.exploitation + exploration
            scored.append({
                "candidate_hash": child,
                "visits": state.visits,
                "value_sum": state.value_sum,
                "cost_sum": state.cost_sum,
                "exploitation": state.exploitation,
                "exploration": exploration,
                "total": total,
            })
        best_total = max(row["total"] for row in scored)
        tied = [
            str(row["candidate_hash"])
            for row in scored
            if abs(float(row["total"]) - best_total) <= 1e-15
        ]
        chosen = _seeded_choice(
            sorted(tied), seed=seed, path=path, stage="uct"
        )
        trace.append({
            "node_candidate_hash": current,
            "depth": depths[current],
            "reason": "uct_descend",
            "untried_children": [],
            "expandable_children": sorted(expandable),
            "uct_scores": scored,
            "chosen_candidate_hash": chosen,
            "estimated_cost": proposal_by_hash[chosen].estimated_cost,
        })
        current = chosen
        path.append(current)
    return None


def _has_untried_descendant(
    candidate_hash: str,
    children: Mapping[str, tuple[str, ...]],
    feedback: Mapping[str, _Feedback],
    depths: Mapping[str, int],
    max_depth: int,
) -> bool:
    if depths[candidate_hash] >= max_depth:
        return False
    for child in children[candidate_hash]:
        if depths[child] > max_depth:
            continue
        if child not in feedback:
            return True
        if _has_untried_descendant(child, children, feedback, depths, max_depth):
            return True
    return False


def _ancestors_resolved(
    candidate_hash: str,
    proposals: Mapping[str, _Proposal],
    feedback: Mapping[str, _Feedback],
) -> bool:
    parent = proposals[candidate_hash].parent_candidate_hash
    while parent is not None:
        if parent not in feedback:
            return False
        parent = proposals[parent].parent_candidate_hash
    return True


def _path_to_root(
    candidate_hash: str,
    proposals: Mapping[str, _Proposal],
) -> list[str]:
    reverse_path = []
    current: str | None = candidate_hash
    while current is not None:
        reverse_path.append(current)
        current = proposals[current].parent_candidate_hash
    return list(reversed(reverse_path))


def _seeded_choice(
    candidates: Sequence[str],
    *,
    seed: int,
    path: Sequence[str],
    stage: str,
) -> str:
    if not candidates:
        raise ValueError("cannot choose from an empty candidate set")
    payload = "\x1f".join([str(seed), stage, *path, *candidates]).encode()
    index = int.from_bytes(sha256(payload).digest()[:8], "big") % len(candidates)
    return candidates[index]


def _decision(
    *,
    planner_kind: str,
    chosen: str,
    path: list[str],
    seed: int,
    best: str | None,
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "planner_kind": planner_kind,
        "candidate_hash": chosen,
        "path": path,
        "seed": seed,
        "best_completed_candidate_hash": best,
        "selection_trace": trace,
    }


def _finite_real(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def _require_json_value(value: object, *, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} contains a non-finite JSON number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _require_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string JSON key")
            _require_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains a non-JSON value")
