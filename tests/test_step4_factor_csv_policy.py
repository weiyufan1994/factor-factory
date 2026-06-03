from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_step4():
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("run_step4_factor_csv_policy_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_step4_factor_csv_policy_defaults_to_sample_csv(monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.delenv("FACTORFORGE_STEP4_FACTOR_CSV_POLICY", raising=False)
    monkeypatch.delenv("FACTORFORGE_FACTOR_CSV_OUTPUT_POLICY", raising=False)
    monkeypatch.delenv("FACTORFORGE_CSV_OUTPUT_POLICY", raising=False)

    policy = run_step4.step4_factor_csv_policy_from_step3b({})

    assert policy["csv_output_policy"] == "sample_csv"
    assert policy["source"] == "step4_default_sample_csv"
    assert policy["factor_csv_write_allowed"] is False


def test_step4_factor_csv_policy_honors_env_override(monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.setenv("FACTORFORGE_STEP4_FACTOR_CSV_POLICY", "no_csv")

    policy = run_step4.step4_factor_csv_policy_from_step3b({})

    assert policy["csv_output_policy"] == "no_csv"
    assert policy["source"] == "FACTORFORGE_STEP4_FACTOR_CSV_POLICY"
    assert policy["factor_csv_write_allowed"] is False


def test_step4_factor_csv_sample_is_head_tail():
    run_step4 = _load_run_step4()
    frame = pd.DataFrame({"value": range(20_000)})

    sample = run_step4.deterministic_factor_csv_sample(frame, max_rows=10_000)

    assert len(sample) == 10_000
    assert sample["value"].iloc[0] == 0
    assert sample["value"].iloc[4_999] == 4_999
    assert sample["value"].iloc[5_000] == 15_000
    assert sample["value"].iloc[-1] == 19_999
