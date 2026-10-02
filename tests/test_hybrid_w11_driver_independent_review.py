"""Independent publication/order checks; never execute the real W11 preset."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import factor_factory.hybrid_research.proposal_comparison as comparison
import factor_factory.hybrid_research.w11_locked_driver as driver
from test_hybrid_w11_locked_driver_author import _small_plan


def _objects_below(root):
    def objects(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from objects(child)
    for path in root.rglob("*.json"):
        yield from objects(json.loads(path.read_text()))


def test_completed_simple_arm_is_retained_when_the_next_gp_arm_fails(tmp_path, monkeypatch):
    plan = _small_plan(tmp_path)
    calls = []

    def fail_gp(*args, **kwargs):
        calls.append("gp")
        raise RuntimeError("independent injected GP failure")

    monkeypatch.setattr(comparison, "_run_gp", fail_gp)
    root = tmp_path / "partial-arm"
    with pytest.raises(RuntimeError, match="injected GP failure"):
        driver.execute_plan_once(plan, root, enforce_locked=False)
    state = json.loads((root / "run_state.json").read_text())
    assert state["status"] == "failed_partial_preserved"
    assert state["confirmation_loaded"] is False
    assert calls == ["gp"]
    saved = [
        obj for obj in _objects_below(root)
        if obj.get("proposer") == "simple_seeded_nonadaptive" and "search" in obj
    ]
    assert saved, "completed simple-arm trace was lost with the failing sibling"
    assert saved[0]["search"]["selected_id"]
    assert saved[0]["actual_fit_evaluations"] > 0


def test_confirmation_exposure_and_completed_scores_survive_a_later_failure(tmp_path, monkeypatch):
    plan = _small_plan(tmp_path)
    score = driver.score_confirmation_after_selection
    calls = []

    def fail_second(**kwargs):
        calls.append(kwargs["proposer"])
        if len(calls) == 2:
            raise RuntimeError("independent injected second-score failure")
        return score(**kwargs)

    monkeypatch.setattr(driver, "score_confirmation_after_selection", fail_second)
    root = tmp_path / "partial-score"
    with pytest.raises(RuntimeError, match="second-score failure"):
        driver.execute_plan_once(plan, root, enforce_locked=False)
    state = json.loads((root / "run_state.json").read_text())
    assert state["status"] == "failed_partial_preserved"
    assert state["confirmation_loaded"] is True
    assert state["development_saved"] is True
    assert len(calls) == 2
    saved = [
        obj for obj in _objects_below(root)
        if "confirmation_mse" in obj and "selected_candidate_id" in obj
    ]
    assert saved, "first completed confirmation score was lost"


@pytest.mark.parametrize("field", ["input_order", "generation_seed", "direct_gain", "binding_hash"])
def test_locked_plan_rejects_semantic_drift_before_creating_output(tmp_path, monkeypatch, field):
    # Read only the pre-generation plan. _generate_packages is prohibited below;
    # these invalid plans cannot generate W11 data or perform a proposer call.
    plan = driver.locked_plan()
    if field == "input_order":
        plan = replace(plan, development_impulses=tuple(reversed(plan.development_impulses)))
    elif field == "generation_seed":
        changed = replace(plan.tasks[0], generation_seed=plan.tasks[0].generation_seed + 1)
        plan = replace(plan, tasks=(changed, *plan.tasks[1:]))
    elif field == "direct_gain":
        changed = replace(plan.tasks[0], direct_gain=plan.tasks[0].direct_gain + 0.25)
        plan = replace(plan, tasks=(changed, *plan.tasks[1:]))
    else:
        plan = replace(plan, preset_sha256="0" * 64)

    def never_generate(*args, **kwargs):
        pytest.fail("a drifted locked plan reached the generator")

    monkeypatch.setattr(driver, "_generate_packages", never_generate)
    root = tmp_path / "must-not-create"
    with pytest.raises(driver.LockedDriverError):
        driver.execute_plan_once(plan, root)
    assert not root.exists()


def test_no_confirmation_file_is_loaded_until_all_development_arms_are_saved(tmp_path, monkeypatch):
    plan = _small_plan(tmp_path)
    original = driver._load_confirmation_after_development_saved
    checked = []

    def check(root, task_id, state):
        data = json.loads((root / "development_results.json").read_text())
        arms = [arm for result in data["results"] for arm in result["arms"]]
        assert len(arms) == 2 * len(plan.tasks) * len(plan.proposer_seeds)
        assert all(arm["search"]["selected_id"] for arm in arms)
        checked.append(task_id)
        return original(root, task_id, state)

    monkeypatch.setattr(driver, "_load_confirmation_after_development_saved", check)
    root = tmp_path / "complete"
    state = driver.execute_plan_once(plan, root, enforce_locked=False)
    assert state["status"] == "complete"
    assert checked == [plan.tasks[0].public_id]
    output = json.loads((root / "confirmation_scores.json").read_text())
    assert output["confirmation_fit_evaluations"] == 2
    with pytest.raises(driver.LockedDriverError, match="already exists"):
        driver.execute_plan_once(plan, root, enforce_locked=False)


@pytest.mark.parametrize("defect", ["no_selection", "missing_arm", "duplicate_arm"])
def test_complete_development_return_without_complete_selections_does_not_open_confirmation(tmp_path, monkeypatch, defect):
    plan = _small_plan(tmp_path)
    original = driver.run_development_comparison

    def damaged_result(*args, **kwargs):
        result = original(*args, **kwargs)
        if defect == "missing_arm":
            return replace(result, arms=result.arms[:1])
        if defect == "duplicate_arm":
            return replace(result, arms=(result.arms[0], result.arms[0]))
        bad_arm = replace(result.arms[1], search=replace(
            result.arms[1].search, selected_id=None,
            trace=(), evaluated_count=0, stop_reason="no_fittable_candidate",
        ))
        return replace(result, arms=(result.arms[0], bad_arm))

    def never_open_confirmation(*args, **kwargs):
        pytest.fail("confirmation was opened without the complete selected-arm set")

    monkeypatch.setattr(driver, "run_development_comparison", damaged_result)
    monkeypatch.setattr(driver, "_load_confirmation_after_development_saved", never_open_confirmation)
    root = tmp_path / "no-selection"
    with pytest.raises(driver.LockedDriverError):
        driver.execute_plan_once(plan, root, enforce_locked=False)
    state = json.loads((root / "run_state.json").read_text())
    assert state["phase"] == "development"
    assert state["status"] == "failed_partial_preserved"
    assert state["development_saved"] is False
    assert state["confirmation_loaded"] is False
    assert state["confirmation_load_attempted"] is False
    saved = json.loads((root / "development_results.json").read_text())
    assert saved["status"] != "all_development_selected_confirmation_not_loaded"
    assert saved["completed_arms"]


def _keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(value)
        for child in value.values():
            found.update(_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_keys(child))
    return found


_PRIVATE_PLAN_KEYS = {"generation_seed", "evaluation_id", "intercept", "direct_gain", "memory"}


def test_run_state_is_not_a_second_copy_of_the_hidden_generation_plan(tmp_path):
    plan = _small_plan(tmp_path)
    root = tmp_path / "state-projection"
    state = driver.execute_plan_once(plan, root, enforce_locked=False)
    saved = json.loads((root / "run_state.json").read_text())
    assert not (_keys(state) & _PRIVATE_PLAN_KEYS)
    assert not (_keys(saved) & _PRIVATE_PLAN_KEYS)
    assert "hidden-k1" not in json.dumps(saved)


def test_default_cli_preview_does_not_print_generation_truth_or_generate_data(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/run_w11_locked_comparison.py"
    process_environment = dict(os.environ)
    process_environment.pop("PYTHONPATH", None)
    process_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    root = tmp_path / "preview-not-created"
    result = subprocess.run(
        [sys.executable, str(script), "--output-root", str(root)],
        cwd=tmp_path, env=process_environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "validated_plan_not_generated_not_executed"
    assert not (_keys(payload) & _PRIVATE_PLAN_KEYS)
    assert not root.exists()
