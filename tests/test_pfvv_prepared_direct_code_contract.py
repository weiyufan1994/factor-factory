"""Synthetic contract coverage for the PF/VV prepared-state direct-code entry.

This validates only the generated-code contract.  It does not materialize a
research object, read a real prepared partition, or evaluate returns.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _prepared_controller_source() -> str:
    """The AIM replacement: delegate plumbing, do not restate PF/VV math."""
    return '''\
"""PF/VV prepared-state controller entry; numerical authority stays frozen."""
from examples.mszq_intraday_momentum_pulse import pfvv_source_baseline_partitioned_v1 as _pfvv

METADATA = _pfvv.METADATA

def compute_factor_partitioned(*, local_inputs, derived_state_root, daily_input_path, output_path):
    return _pfvv.compute_factor_partitioned(
        local_inputs=local_inputs,
        derived_state_root=derived_state_root,
        daily_input_path=daily_input_path,
        output_path=output_path,
    )

def compute_factor(daily_df=None, minute_df=None):
    raise RuntimeError("prepared PF/VV controller must use compute_factor_partitioned")
'''


def test_prepared_controller_source_passes_step2_and_step3b_direct_code_contracts(tmp_path: Path) -> None:
    step2 = _load("step2_pfvv_prepared_contract_test", "skills/factor-forge-step2/scripts/run_step2.py")
    validate_step2 = _load("validate_step2_pfvv_prepared_contract_test", "skills/factor-forge-step2/scripts/validate_step2.py")
    step3b = _load("step3b_pfvv_prepared_contract_test", "skills/factor-forge-step3/scripts/run_step3b.py")
    validate_step3b = _load("validate_step3b_pfvv_prepared_contract_test", "skills/factor-forge-step3/scripts/validate_step3b.py")

    source = _prepared_controller_source()
    aim = {
        "implementation_mode": "direct_code",
        "code_contract": {
            "code_contract_version": "factorforge_direct_code_contract_v1",
            "entrypoint": "compute_factor",
            "function_name": "compute_factor",
            "source_code": source,
            "required_fields": ["ts_code", "trade_date", "pf_daily", "vv_daily"],
            "output_schema": {"columns": ["ts_code", "trade_date", "factor_value"]},
            "source_derivation": {"not_fallback": True, "derivation": "prepared_controller_delegate"},
        },
    }
    raw_contract = step2.explicit_direct_code_source_contract({}, aim)
    assert raw_contract["source_code"] == source
    assert raw_contract["code_hash"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    step2_checks = validate_step2.direct_code_contract_checks(
        {"implementation_mode": "direct_code", "implementation_contract": {"code_contract": raw_contract}}
    )
    assert not [item for item in step2_checks if item["status"] == "BLOCK"]

    spec = {
        "factor_id": "PFVV_COMPOSITE",
        "implementation_contract": {"code_contract": raw_contract},
        "artifact_identity": {"implementation_mode": "direct_code", "code_contract_hash": "synthetic"},
    }
    local_inputs = {"input_mode": "derived_state_with_daily"}
    plan, generated_source, qlib, hybrid = step3b.build_direct_code_artifacts(
        "SYNTHETIC_PFVV", local_inputs, spec, spec["artifact_identity"], None
    )
    stub = tmp_path / "factor_impl_stub__SYNTHETIC_PFVV.py"
    stub.write_text(generated_source, encoding="utf-8")
    actual_hash = hashlib.sha256(stub.read_bytes()).hexdigest()
    for payload in (plan, qlib, hybrid):
        payload["artifact_identity"] = {"code_hash": actual_hash}
        payload.setdefault("metadata", {})["code_hash"] = actual_hash

    validate_step3b.validate_direct_code_mode(
        spec,
        plan,
        qlib,
        hybrid,
        manifest=None,
        handoff={"artifact_identity": {"code_hash": actual_hash}},
        code_dir=tmp_path,
        stub=stub,
        real_impl=tmp_path / "missing_real_impl.py",
        prep={"local_input_paths": local_inputs},
    )
