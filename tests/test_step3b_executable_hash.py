"""Exercise real Step3B generation then the unmodified direct-code validator."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RID = "EXECUTABLE_HASH_REGRESSION"
SOURCE = '''from factor_factory.factors import PriceVolumeFactor
class Example(PriceVolumeFactor):
    name = "executable_hash_regression"
    input_columns = {"daily_df": ("ts_code", "trade_date")}
    def compute(self, inputs):
        return inputs["daily_df"][["ts_code", "trade_date"]].assign(factor_value=1.0)
FACTOR = Example()
'''
CONTROLLER = '''import pandas as pd
METADATA = {"prepared_state_projection": True, "raw_minute_access": False}
def compute_factor_partitioned(*, local_inputs, derived_state_root, daily_input_path, output_path):
    daily = pd.read_parquet(daily_input_path)
    daily[["ts_code", "trade_date"]].assign(factor_value=1.0).to_parquet(output_path, index=False)
    return output_path
'''


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def generate(tmp_path, *, real=True, parent_code_hash=True, controller_source=CONTROLLER):
    canonical, work = tmp_path / "canonical", tmp_path / "debug"
    canonical.mkdir(); work.mkdir()
    code = work / "generated_code" / RID
    code.mkdir(parents=True)
    impl = code / f"factor_impl__{RID}.py"
    if real:
        impl.write_text(controller_source)
    identity = {"report_id": RID, "factor_id": RID, "implementation_mode": "direct_code",
                "branch_id": "main", "source_type": "canonical_formula", "spec_hash": "synthetic_spec",
                "code_contract_hash": "synthetic_contract"}
    if parent_code_hash:
        identity["code_hash"] = hashlib.sha256(SOURCE.encode()).hexdigest()
    contract = {"source_code": SOURCE, "code_contract_hash": "synthetic_contract",
                "input_schema": {"daily_df": ["ts_code", "trade_date"]},
                "output_schema": {"index": ["datetime", "instrument"], "columns": ["factor_value"]}}
    spec = {"report_id": RID, "factor_id": RID, "implementation_mode": "direct_code",
            "artifact_identity": identity, "implementation_contract": {"code_contract": contract}}
    local = {}
    if real:
        days = ["20200102", "20200103"]
        sample = work / "sample"
        sample.mkdir(); (sample / "states").mkdir()
        daily = sample / "daily.parquet"
        pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"] * 2,
                      "trade_date": [days[0]] * 2 + [days[1]] * 2}).to_parquet(daily, index=False)
        inputs = {"input_mode": "derived_state_with_daily", "daily_df_parquet": str(daily),
                  "derived_state_root": str(sample / "states"), "calendar_dates": days,
                  "sample_window_actual": {"start": days[0], "end": days[-1]}}
        config = sample / "controller.json"
        write(config, {"controller": "sample", "sample_budget": {"max_calendar_days": 2},
                       "sample_calendar_dates": days, "local_inputs": inputs})
        local = {**inputs, "step3b_daily_df_parquet": str(daily),
                 "step3b_derived_state_root": str(sample / "states"), "step3b_calendar_dates": days,
                 "step3b_sample_window": inputs["sample_window_actual"],
                 "step3b_prepared_controller_config": str(config)}
    prep = {"report_id": RID, "feasibility": "ready", "local_input_paths": local}
    spec_path = work / f"objects/factor_spec_master/factor_spec_master__{RID}.json"
    write(spec_path, spec)
    write(work / f"objects/data_prep_master/data_prep_master__{RID}.json", prep)
    before = spec_path.read_bytes()
    env = {key: value for key, value in os.environ.items() if not key.startswith("FACTORFORGE_")}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", FACTORFORGE_REPO_ROOT=str(ROOT),
               FACTORFORGE_ROOT=str(canonical), FACTORFORGE_DEBUG_ROOT=str(work), FACTORFORGE_ALLOW_DIRECT_STEP="1")
    entry = os.environ.get("STEP3B_TEST_ENTRY") or str(ROOT / "skills/factor-forge-step3/scripts/run_step3b.py")
    result = subprocess.run([sys.executable, entry,
                             "--report-id", RID, "--csv-output-policy", "no_csv"],
                            cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert spec_path.read_bytes() == before
    assert not list(canonical.rglob("*.json"))
    plan = json.loads((work / f"objects/implementation_plan_master/implementation_plan_master__{RID}.json").read_text())
    qlib = json.loads((code / f"qlib_expression_draft__{RID}.json").read_text())
    hybrid = json.loads((code / f"hybrid_execution_scaffold__{RID}.json").read_text())
    handoff = json.loads((work / f"objects/handoff/handoff_to_step4__{RID}.json").read_text())
    stub = code / f"factor_impl_stub__{RID}.py"
    chosen = impl if real else stub
    module_spec = importlib.util.spec_from_file_location("executable_hash_validator", ROOT / "skills/factor-forge-step3/scripts/validate_step3b.py")
    validator = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(validator)
    validator.FF = work
    def validate():
        validator.validate_direct_code_mode(spec, plan, qlib, hybrid,
            manifest={"step_io": {"step3b": {"outputs": {"factor_impl": str(chosen)}}}},
            handoff=handoff, code_dir=code, stub=stub, real_impl=impl, prep=prep)
    return validate, validator, spec, plan, qlib, hybrid, handoff, chosen, stub


@pytest.mark.parametrize("real,parent_hash", [(True, True), (True, False), (False, True)])
def test_generated_execution_identities_match_selected_code(tmp_path, real, parent_hash):
    validate, validator, spec, plan, qlib, hybrid, handoff, chosen, stub = generate(
        tmp_path, real=real, parent_code_hash=parent_hash)
    validate()
    expected = hashlib.sha256(chosen.read_bytes()).hexdigest()
    declared = validator.collect_declared_direct_code_hashes(spec, plan, qlib, hybrid, handoff)
    assert declared and all(digest == expected for _, digest in declared)
    assert plan["code_contract"]["source_code"] == SOURCE
    assert plan["code_contract_hash"] == "synthetic_contract"
    assert SOURCE in stub.read_text()
    if real:
        assert hashlib.sha256(stub.read_bytes()).hexdigest() != expected
        assert plan["first_run_outputs"]["status"] == "ready"
        assert handoff["factor_impl_ref"].endswith(chosen.name)


def test_changed_executable_still_fails_hash_check(tmp_path):
    validate, _, _, _, _, _, _, chosen, _ = generate(tmp_path)
    chosen.write_text(chosen.read_text() + "\n# changed after generation\n")
    with pytest.raises(AssertionError, match="BLOCK_DIRECT_CODE_HASH_MISMATCH"):
        validate()


def test_matching_hash_does_not_bypass_future_data_check(tmp_path):
    source = CONTROLLER + "\ndef bad_future(frame):\n    return frame.shift(-1)\n"
    validate, *_ = generate(tmp_path, controller_source=source)
    with pytest.raises(AssertionError, match="BLOCK_DIRECT_CODE_LEAKAGE"):
        validate()


def test_matching_hash_does_not_bypass_prepared_controller_check(tmp_path):
    source = CONTROLLER.replace('"raw_minute_access": False', '"raw_minute_access": True')
    validate, *_ = generate(tmp_path, controller_source=source)
    with pytest.raises(AssertionError, match="PREPARED_CONTROLLER_RAW_MINUTE_ACCESS"):
        validate()
