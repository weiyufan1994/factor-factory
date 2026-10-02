from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json

import pytest

import factor_factory.hybrid_research.w11_locked_driver as driver
from factor_factory.hybrid_research.w11_locked_driver import (
    GenerationTask,
    LockedDriverError,
    LockedPlan,
    _generate_series,
    execute_plan_once,
    locked_plan,
)


def _small_plan(tmp_path):
    problem = tmp_path / "problem.json"
    math = tmp_path / "math.md"
    preset = tmp_path / "preset.json"
    problem.write_text("{}", encoding="utf-8")
    math.write_text("# selected math", encoding="utf-8")
    preset.write_text("{}", encoding="utf-8")
    digest = lambda path: sha256(path.read_bytes()).hexdigest()
    return LockedPlan(
        str(problem), digest(problem), str(math), digest(math), str(preset), digest(preset),
        (1.0, 0.0, -1.0, 1.0), (0.0, -1.0), -0.01, 0.01,
        (101,), 4, 4, 1, 3,
        (GenerationTask("hidden-k1", "w11-task-01", 9001, 0.2, 0.5, ((0.4, -0.3),)),),
    )


def test_series_generator_matches_independent_state_recursion():
    impulses = (1.0, 0.0, -1.0)
    noiseless, observed = _generate_series(
        impulses=impulses, intercept=0.2, direct_gain=0.5,
        memory=((0.4, -0.3),), seed=1, noise_low=0.0, noise_high=0.0,
    )
    states = (1.0, 0.4, -0.84)
    expected = tuple(0.2 + 0.5 * u - 0.3 * x for u, x in zip(impulses, states))
    assert noiseless == pytest.approx(expected)
    assert observed == pytest.approx(expected)


def test_real_locked_plan_is_hash_and_field_validated_without_generation():
    plan = locked_plan()
    assert tuple(task.public_id for task in plan.tasks) == (
        "w11-task-01", "w11-task-02", "w11-task-03"
    )
    assert tuple(len(task.memory) for task in plan.tasks) == (0, 1, 2)
    with pytest.raises(LockedDriverError, match="differs"):
        driver._validate_locked_plan(replace(plan, max_attempts=31))


def test_small_engineering_plan_saves_all_development_before_confirmation(tmp_path, monkeypatch):
    plan = _small_plan(tmp_path)
    original = driver._load_confirmation_after_development_saved
    checks = []

    def checked(root, task_id, state):
        checks.append((state["development_saved"], (root / "development_results.json").is_file()))
        return original(root, task_id, state)

    monkeypatch.setattr(driver, "_load_confirmation_after_development_saved", checked)
    output = tmp_path / "output"
    state = execute_plan_once(plan, output, enforce_locked=False)
    assert state["status"] == "complete"
    assert checks == [(True, True)]
    public = json.loads((output / "public/w11-task-01/package.json").read_text())
    encoded = json.dumps(public)
    assert public["task_id"] == "w11-task-01"
    assert "hidden-k1" not in encoded and '"truth"' not in encoded
    development = json.loads((output / "development_results.json").read_text())
    assert len(development["results"][0]["arms"]) == 2
    confirmation = json.loads((output / "confirmation_scores.json").read_text())
    assert len(confirmation["scores"]) == 2
    assert confirmation["confirmation_fit_evaluations"] == 2
    with pytest.raises(LockedDriverError, match="already exists"):
        execute_plan_once(plan, output, enforce_locked=False)


def test_failure_is_preserved_and_not_retried(tmp_path, monkeypatch):
    plan = _small_plan(tmp_path)
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("engineered failure")

    monkeypatch.setattr(driver, "run_development_comparison", fail_once)
    output = tmp_path / "failed-output"
    with pytest.raises(RuntimeError, match="engineered failure"):
        execute_plan_once(plan, output, enforce_locked=False)
    state = json.loads((output / "run_state.json").read_text())
    assert calls == 1
    assert state["status"] == "failed_partial_preserved"
    assert state["rerun_allowed"] is False
    with pytest.raises(LockedDriverError, match="already exists"):
        execute_plan_once(plan, output, enforce_locked=False)
