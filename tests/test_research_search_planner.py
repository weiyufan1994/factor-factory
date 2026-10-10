from __future__ import annotations

import copy
import math

import pytest

from factor_factory.research_search.planner import plan_next


def proposal(candidate, parent=None, cost=1.0, **extra):
    return {
        "candidate_hash": candidate,
        "parent_candidate_hash": parent,
        "estimated_cost": cost,
        **extra,
    }


def result(
    candidate,
    *,
    increment=0.5,
    score=0.5,
    status="completed",
    cost=1.0,
    **extra,
):
    if status != "completed":
        increment = score = None
    return {
        "candidate_hash": candidate,
        "status": status,
        "learning_increment": increment,
        "actual_cost": cost,
        "candidate_score": score,
        **extra,
    }


TREE = (
    proposal("root"),
    proposal("a", "root"),
    proposal("b", "root"),
    proposal("a1", "a"),
    proposal("b1", "b"),
)


def test_root_is_selected_before_any_descendant():
    decision = plan_next(TREE, (), root_candidate_hash="root", seed=7)
    assert decision["candidate_hash"] == "root"
    assert decision["path"] == ["root"]
    assert decision["selection_trace"][0]["reason"] == "root_unexecuted"


def test_untried_sibling_is_selected_before_grandchild():
    feedback = (result("root"), result("a"))
    decision = plan_next(TREE, feedback, root_candidate_hash="root", seed=7)
    assert decision["candidate_hash"] == "b"
    assert decision["path"] == ["root", "b"]
    assert decision["selection_trace"][-1]["reason"] == "fair_untried_sibling"


def test_grandchildren_are_reachable_after_siblings_expand():
    feedback = (result("root"), result("a", increment=.8), result("b", increment=-.8))
    decision = plan_next(TREE, feedback, root_candidate_hash="root", seed=3)
    assert decision["candidate_hash"] == "a1"
    assert decision["path"] == ["root", "a", "a1"]
    assert decision["selection_trace"][0]["reason"] == "uct_descend"
    assert decision["selection_trace"][1]["reason"] == "fair_untried_sibling"


def test_depth_exhausted_branch_does_not_hide_other_branch():
    proposals = TREE + (proposal("a2", "a1"),)
    feedback = (
        result("root"), result("a", increment=.9), result("b", increment=.1),
        result("a1", increment=.9),
    )
    decision = plan_next(
        proposals, feedback, root_candidate_hash="root", seed=3, max_depth=2,
    )
    assert decision["candidate_hash"] == "b1"
    assert decision["path"] == ["root", "b", "b1"]


def test_best_candidate_uses_fixed_score_not_tree_reward():
    feedback = (
        result("root", increment=.2, score=.2),
        result("a", increment=1.0, score=.1),
        result("b", increment=-1.0, score=.9),
    )
    decision = plan_next(TREE, feedback, root_candidate_hash="root", seed=3)
    assert decision["best_completed_candidate_hash"] == "b"
    uct = decision["selection_trace"][0]["uct_scores"]
    assert next(row for row in uct if row["candidate_hash"] == "a")["value_sum"] > 0
    assert next(row for row in uct if row["candidate_hash"] == "b")["value_sum"] < 0


def test_negative_or_unknown_score_does_not_create_best_candidate():
    feedback = (
        result("root", increment=-.2, score=-.1),
        result("a", status="unknown", cost=None),
        result("b", increment=0, score=0),
    )
    decision = plan_next(TREE, feedback, root_candidate_hash="root", seed=3)
    assert decision["best_completed_candidate_hash"] is None


def test_duplicate_feedback_is_rejected_instead_of_double_counted():
    feedback = (result("root"), result("root"))
    with pytest.raises(ValueError, match="duplicate feedback"):
        plan_next(TREE, feedback, root_candidate_hash="root", seed=3)


def test_replay_with_same_seed_and_inputs_has_identical_trace():
    feedback = (result("root"), result("a", increment=.4), result("b", increment=.4))
    first = plan_next(TREE, feedback, root_candidate_hash="root", seed=20261010)
    second = plan_next(copy.deepcopy(TREE), copy.deepcopy(feedback), root_candidate_hash="root", seed=20261010)
    assert first == second


def test_feedback_order_does_not_change_replayed_statistics_or_trace():
    feedback = [result("root", increment=.1), result("a", increment=.2), result("b", increment=.2)]
    first = plan_next(TREE, feedback, root_candidate_hash="root", seed=11)
    second = plan_next(TREE, tuple(reversed(feedback)), root_candidate_hash="root", seed=11)
    assert first == second


def test_registered_queue_is_stable_common_baseline():
    feedback = (result("root"),)
    decision = plan_next(
        TREE, feedback, root_candidate_hash="root", seed=999,
        planner_kind="registered_queue",
    )
    assert decision["candidate_hash"] == "a"
    assert decision["selection_trace"][0]["reason"] == "registered_queue"


def test_all_candidates_completed_returns_none():
    feedback = tuple(result(row["candidate_hash"]) for row in TREE)
    assert plan_next(TREE, feedback, root_candidate_hash="root", seed=1) is None


@pytest.mark.parametrize("split", ("confirmation", "final", "oos"))
def test_held_out_feedback_is_never_consumed(split):
    with pytest.raises(ValueError, match="development-only"):
        plan_next(
            TREE, (result("root", split=split),),
            root_candidate_hash="root", seed=1,
        )


def test_explicit_held_out_payload_fields_are_rejected():
    with pytest.raises(ValueError, match="forbidden held-out"):
        plan_next(
            TREE, (result("root", confirmation={"score": 1}),),
            root_candidate_hash="root", seed=1,
        )


def test_unknown_reward_is_not_filled_with_zero_or_made_best():
    feedback = (
        result("root", status="unknown", cost=None),
        result("a", status="failed_unknown_cost", cost=None),
        result("b", status="blocked", cost=2),
    )
    decision = plan_next(TREE, feedback, root_candidate_hash="root", seed=3)
    assert decision["best_completed_candidate_hash"] is None
    uct = decision["selection_trace"][0]["uct_scores"]
    assert all(row["visits"] == 0 and row["value_sum"] == 0 for row in uct)


def test_hand_calculated_backpropagation_keeps_value_and_cost_separate():
    feedback = (
        result("root", increment=.2, cost=2),
        result("a", increment=.6, cost=3),
        result("b", increment=.1, cost=4),
    )
    decision = plan_next(TREE, feedback, root_candidate_hash="root", seed=3)
    rows = {
        row["candidate_hash"]: row
        for row in decision["selection_trace"][0]["uct_scores"]
    }
    assert rows["a"]["visits"] == 1
    assert rows["a"]["value_sum"] == pytest.approx(.6)
    assert rows["a"]["cost_sum"] == pytest.approx(3)
    assert rows["a"]["exploitation"] == pytest.approx(.2)
    assert rows["b"]["visits"] == 1
    assert rows["b"]["value_sum"] == pytest.approx(.1)
    assert rows["b"]["cost_sum"] == pytest.approx(4)
    assert rows["b"]["exploitation"] == pytest.approx(.025)


def test_missing_parent_and_unreachable_root_are_rejected():
    with pytest.raises(ValueError, match="missing parent"):
        plan_next(
            (proposal("root"), proposal("x", "missing")), (),
            root_candidate_hash="root", seed=1,
        )
    with pytest.raises(ValueError, match="reachable"):
        plan_next(
            (proposal("root"), proposal("other"), proposal("x", "other")), (),
            root_candidate_hash="root", seed=1,
        )


def test_parent_cycle_is_rejected():
    proposals = (
        proposal("root"), proposal("a", "b"), proposal("b", "a"),
    )
    with pytest.raises(ValueError, match="cycle"):
        plan_next(proposals, (), root_candidate_hash="root", seed=1)


@pytest.mark.parametrize(
    ("field", "value"),
    (("learning_increment", 1.1), ("learning_increment", True),
     ("actual_cost", -1), ("candidate_score", math.inf)),
)
def test_invalid_feedback_numbers_are_rejected(field, value):
    row = result("root")
    row[field] = value
    with pytest.raises(ValueError, match=field):
        plan_next(TREE, (row,), root_candidate_hash="root", seed=1)


def test_non_json_values_are_rejected():
    bad = proposal("root", metadata={"set": {1, 2}})
    with pytest.raises(ValueError, match="non-JSON"):
        plan_next((bad,), (), root_candidate_hash="root", seed=1)


@pytest.mark.parametrize(
    "bad_feedback",
    (
        {"candidate_hash": [], "status": "completed", "learning_increment": 0,
         "actual_cost": 0, "candidate_score": 1},
        {"candidate_hash": "root", "status": {}, "learning_increment": None,
         "actual_cost": None, "candidate_score": None},
    ),
)
def test_malformed_feedback_identifiers_fail_as_contract_errors(bad_feedback):
    with pytest.raises(ValueError, match="feedback\\[0\\]"):
        plan_next(TREE, (bad_feedback,), root_candidate_hash="root", seed=1)


@pytest.mark.parametrize("bad", (True, 1.5, -1))
def test_bad_depth_is_rejected(bad):
    with pytest.raises(ValueError, match="max_depth"):
        plan_next(TREE, (), root_candidate_hash="root", seed=1, max_depth=bad)
