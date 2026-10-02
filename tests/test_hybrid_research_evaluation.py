from __future__ import annotations

import json
import subprocess
import sys

import factor_factory.hybrid_research.evaluation as evaluation
import factor_factory.hybrid_research.evaluation_v2 as evaluation_v2


def test_protocol_freezes_three_families_three_seeds_and_separate_comparisons() -> None:
    manifest = evaluation.protocol_manifest()

    assert manifest["task_families"] == [
        "matching", "condition_change", "misleading_prior",
    ]
    assert manifest["numeric_seeds"] == [11, 29, 47]
    assert manifest["task_count"] == 9
    assert manifest["algorithm_comparison"] == "MCTS minus simple, C0 only"
    assert manifest["transfer_comparison"] == "C1 minus C0 within each algorithm"
    assert manifest["final_feedback"].startswith("forbidden")
    assert len(manifest["protocol_hash"]) == 64


def test_task_noise_is_paired_by_identity_and_independent_of_planner_rng() -> None:
    task = evaluation.locked_task_specs()[0]

    first = evaluation._score(task, "deepen-fast", phase="target-development")
    second = evaluation._score(task, "deepen-fast", phase="target-development")
    other_action = evaluation._score(task, "check-rival", phase="target-development")

    assert first == second
    assert evaluation._planner_seed(task, "mcts") != evaluation._planner_seed(
        task, "simple_scheduler"
    )
    assert isinstance(other_action, float)


def test_development_run_never_reads_held_out_scores(monkeypatch) -> None:
    original = evaluation._score

    def guarded(task, action_id, *, phase):
        if phase == "target-final":
            raise AssertionError("held-out score was read during development run")
        return original(task, action_id, phase=phase)

    monkeypatch.setattr(evaluation, "_score", guarded)
    report = evaluation.run_locked_evaluation(include_final=False)

    assert len(report.records) == 36
    assert len(report.algorithm_pairs) == 9
    assert len(report.transfer_pairs) == 18
    assert all(row.development_only and row.final_quality is None for row in report.records)
    assert report.llm_auxiliary_status == "not_executed_real_researcher_required"
    assert report.token_usage == report.api_cost == "Unknown"


def test_c0_and_c1_keep_same_target_tools_while_only_c1_pays_for_prior() -> None:
    report = evaluation.run_locked_evaluation(include_final=False)
    grouped = {}
    for row in report.records:
        grouped[(row.task_id, row.algorithm, row.arm)] = row

    for task in evaluation.locked_task_specs():
        for algorithm in ("mcts", "simple_scheduler"):
            c0 = grouped[(task.task_id, algorithm, "C0")]
            c1 = grouped[(task.task_id, algorithm, "C1")]
            assert c0.transfer_learning_cost == 0.0
            assert c1.transfer_learning_cost == 4.0
            assert c0.target_spent_cost <= evaluation.TARGET_BUDGET
            assert c1.target_spent_cost <= evaluation.TARGET_BUDGET
            assert c0.total_observed_cost == c0.target_spent_cost
            assert c1.total_observed_cost == c1.target_spent_cost + 4.0


def test_condition_change_prior_is_not_silently_transferred_across_context() -> None:
    report = evaluation.run_locked_evaluation(include_final=False)
    rows = [row for row in report.records if row.family == "condition_change"]

    for algorithm in ("mcts", "simple_scheduler"):
        for numeric_seed in evaluation.NUMERIC_SEEDS:
            pair = {
                row.arm: row for row in rows
                if row.algorithm == algorithm and row.numeric_seed == numeric_seed
            }
            assert pair["C0"].first_executed_action_id == pair["C1"].first_executed_action_id
            assert pair["C0"].development_quality == pair["C1"].development_quality


def test_protocol_cli_defaults_to_manifest_only_without_final_results() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_hybrid_research_evaluation.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["mode"] == "protocol_only"
    assert payload["final_results_read"] is False
    assert payload["protocol"]["protocol_hash"] == evaluation_v2.protocol_manifest()["protocol_hash"]
