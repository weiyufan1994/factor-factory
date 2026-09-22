from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_step4():
    path = REPO_ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("run_step4_factor_csv_policy_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_step4_factor_csv_policy_preserves_legacy_full_csv_compat(monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.delenv("FACTORFORGE_CSV_OUTPUT_POLICY", raising=False)

    policy = run_step4.step4_factor_csv_policy_from_step3b({})

    assert policy["csv_output_policy"] == "legacy_missing"
    assert policy["source"] == "legacy_missing"
    assert policy["factor_csv_write_allowed"] is True


def test_step4_factor_csv_policy_honors_env_override(monkeypatch):
    run_step4 = _load_run_step4()
    monkeypatch.setenv("FACTORFORGE_CSV_OUTPUT_POLICY", "no_csv")

    policy = run_step4.step4_factor_csv_policy_from_step3b({})

    assert policy["csv_output_policy"] == "no_csv"
    assert policy["source"] == "step4_env"
    assert policy["factor_csv_write_allowed"] is False


def test_step4_factor_csv_policy_honors_step3b_sample_contract():
    run_step4 = _load_run_step4()
    metadata = {
        "performance_profile": {
            "csv_output_profile": {"csv_output_policy": "sample_csv"}
        }
    }

    policy = run_step4.step4_factor_csv_policy_from_step3b(metadata)

    assert policy["csv_output_policy"] == "sample_csv"
    assert policy["source"] == "step3b_run_metadata"
    assert policy["factor_csv_write_allowed"] is False
