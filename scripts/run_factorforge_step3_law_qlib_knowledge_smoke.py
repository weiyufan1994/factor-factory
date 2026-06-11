#!/usr/bin/env python3
from __future__ import annotations

import json
import importlib.util
import shutil
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_true(name: str, condition: bool, details: Any = None) -> None:
    if not condition:
        raise AssertionError(f"{name} failed: {details!r}")


def expect_system_exit(name: str, token: str, fn) -> None:
    try:
        fn()
    except SystemExit as exc:
        assert_true(name, token in str(exc), str(exc))
        return
    raise AssertionError(f"{name} did not raise {token}")


def test_law_registry() -> dict[str, Any]:
    from factor_factory.factor_laws.moneyflow.registry import (
        BLOCK_LAW_HASH_MISMATCH,
        BLOCK_LAW_MISSING,
        resolve_law,
    )

    law = resolve_law("moneyflow_registry_smoke_signed_amount_v1")
    assert_true("law has stable id", law.law_id == "moneyflow_registry_smoke_signed_amount_v1", law)
    assert_true("law has hash", len(law.code_law_hash) == 64, law.code_law_hash)
    same = resolve_law("moneyflow_registry_smoke_signed_amount_v1", expected_hash=law.code_law_hash)
    assert_true("hash verified", same.code_law_hash == law.code_law_hash, same)
    expect_system_exit(
        "law missing blocks",
        BLOCK_LAW_MISSING,
        lambda: resolve_law("unknown_moneyflow_law"),
    )
    expect_system_exit(
        "law hash mismatch blocks",
        BLOCK_LAW_HASH_MISMATCH,
        lambda: resolve_law("moneyflow_registry_smoke_signed_amount_v1", expected_hash="0" * 64),
    )
    return {"known_law_hash": law.code_law_hash}


def test_step3b_contract_resolution() -> dict[str, Any]:
    from factor_factory.factor_laws.moneyflow.registry import resolve_law

    run_step3b = import_script_module(
        "run_step3b_smoke",
        REPO_ROOT / "skills" / "factor-forge-step3" / "scripts" / "run_step3b.py",
    )
    law = resolve_law("moneyflow_registry_smoke_signed_amount_v1")
    resolved = run_step3b.resolve_direct_code_law_contract(
        {"law_id": law.law_id, "code_law_hash": law.code_law_hash}
    )
    assert_true("step3b contract law id", resolved["law_id"] == law.law_id, resolved)
    assert_true("step3b contract source", "def compute_factor" in resolved["source_code"], resolved)
    existing = {
        "report_id": "blocked_parent",
        "step3a_ready": False,
        "step3b_ready": False,
        "first_run_outputs": {
            "status": "blocked",
            "no_first_run_reason": "step3a_feasibility_blocked",
            "output_paths": [],
            "run_metadata_path": None,
            "factor_values_path": None,
        },
        "local_input_paths": {"input_mode": "blocked"},
    }
    merged = run_step3b.merge_handoff(
        existing,
        {
            "report_id": "blocked_parent",
            "step3a_ready": False,
            "step3b_ready": True,
            "factor_impl_stub_ref": "generated_code/blocked_parent/factor_impl_stub__blocked_parent.py",
            "first_run_outputs": {"status": "pending", "no_first_run_reason": "no_local_snapshots_available"},
        },
    )
    assert_true("blocked step3a not upgraded", merged.get("step3b_ready") is False, merged)
    assert_true("blocked first run preserved", (merged.get("first_run_outputs") or {}).get("status") == "blocked", merged)
    assert_true("stale generated ref cleared", "factor_impl_stub_ref" not in merged, merged)
    return {"resolved_law_id": resolved["law_id"], "blocked_handoff_guard": True}


def test_real_moneyflow_law_registry_entries() -> dict[str, Any]:
    import pandas as pd

    from factor_factory.factor_laws.moneyflow.derived_state import SUPPORTED_MILLER_DERIVED_STATE_LAWS
    from factor_factory.factor_laws.moneyflow.registry import resolve_law

    sample = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "trade_date": ["20250101", "20250101", "20250102", "20250102"],
            "signed_flow_imbalance": [1.0, -1.0, 1.5, -0.5],
            "ret_excess_kurtosis": [0.2, -0.1, 0.3, -0.2],
            "close": [10.0, 20.0, 10.2, 19.8],
            "pct_chg": [1.0, -1.0, 2.0, -0.5],
            "turnover_rate": [1.5, 1.2, 1.6, 1.1],
            "volume_ratio": [1.1, 0.9, 1.2, 0.8],
            "circ_mv": [80.0, 150.0, 82.0, 148.0],
            "total_mv": [100.0, 200.0, 101.0, 198.0],
        }
    )
    results: dict[str, Any] = {}
    for law_id in sorted(SUPPORTED_MILLER_DERIVED_STATE_LAWS):
        law = resolve_law(law_id)
        assert_true("real law hash", len(law.code_law_hash) == 64, law.code_law_hash)
        assert_true(
            "real law derived state option",
            law.adapter_options.get("supports_minute_derived_flow_state_v1") is True,
            law.adapter_options,
        )
        namespace: dict[str, Any] = {}
        exec(law.source_code, namespace)
        output = namespace["compute_factor"](daily_df=sample)
        assert_true("real law output rows", len(output) == len(sample), output)
        assert_true("real law output schema", list(output.columns) == ["ts_code", "trade_date", "factor_value"], output)
        assert_true("real law no null factor values", output["factor_value"].notna().all(), output)
        results[law_id] = {
            "code_law_hash": law.code_law_hash,
            "rows": int(len(output)),
        }
    return results


def test_child_qlib_config() -> dict[str, Any]:
    materializer = import_script_module(
        "materialize_step6_child_revision_smoke",
        REPO_ROOT / "skills" / "factor-forge-step6" / "scripts" / "materialize_step6_child_revision.py",
    )

    root = Path(tempfile.mkdtemp(prefix="factorforge_qlib_child_smoke_"))
    try:
        parent = "parent_alpha"
        child = "child_alpha"
        parent_cfg = root / "objects" / "data_prep_master" / f"qlib_adapter_config__{parent}.json"
        child_handoff = root / "objects" / "handoff" / f"handoff_to_step4__{child}.json"
        write_json(parent_cfg, {"report_id": parent, "status": "ready", "provider": "qlib_native"})
        write_json(child_handoff, {"report_id": child})
        result = materializer.ensure_child_qlib_adapter_config(root, parent, child)
        child_cfg = root / "objects" / "data_prep_master" / f"qlib_adapter_config__{child}.json"
        payload = load_json(child_cfg)
        handoff = load_json(child_handoff)
        assert_true("child config copied", result["status"] == "copied_from_parent", result)
        assert_true("child config report_id", payload["report_id"] == child, payload)
        assert_true("handoff config ref", handoff.get("qlib_adapter_config_ref") == child_cfg.name, handoff)

        orphan_child = "child_no_parent_cfg"
        orphan_handoff = root / "objects" / "handoff" / f"handoff_to_step4__{orphan_child}.json"
        write_json(orphan_handoff, {"report_id": orphan_child})
        fallback = materializer.ensure_child_qlib_adapter_config(root, parent + "_missing", orphan_child)
        fallback_cfg = root / "objects" / "data_prep_master" / f"qlib_adapter_config__{orphan_child}.json"
        fallback_payload = load_json(fallback_cfg)
        assert_true("fallback status", fallback["status"] == "not_applicable_created", fallback)
        assert_true("fallback qlib status", fallback_payload["qlib_native_status"] == "not_applicable", fallback_payload)
        assert_true(
            "fallback reason",
            fallback_payload["reason"] == "direct_code_derived_state_not_supported_by_qlib",
            fallback_payload,
        )
        return {"copied_child": str(child_cfg), "fallback_child": str(fallback_cfg)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_qlib_not_applicable_backend() -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="factorforge_qlib_backend_smoke_"))
    old_root = os.environ.get("FACTORFORGE_ROOT")
    try:
        report_id = "direct_code_child"
        write_json(
            root / "objects" / "data_prep_master" / f"qlib_adapter_config__{report_id}.json",
            {
                "report_id": report_id,
                "status": "not_applicable",
                "qlib_native_status": "not_applicable",
                "reason": "direct_code_derived_state_not_supported_by_qlib",
            },
        )
        os.environ["FACTORFORGE_ROOT"] = str(root)
        qlib_adapter = import_script_module(
            "qlib_backtest_adapter_smoke",
            REPO_ROOT / "skills" / "factor-forge-step4" / "scripts" / "qlib_backtest_adapter.py",
        )
        result = qlib_adapter.run_qlib_backtest_stub(report_id)
        assert_true("qlib not applicable skipped", result["status"] == "skipped", result)
        assert_true("qlib native not applicable", result["qlib_native_status"] == "not_applicable", result)
        return result
    finally:
        if old_root is None:
            os.environ.pop("FACTORFORGE_ROOT", None)
        else:
            os.environ["FACTORFORGE_ROOT"] = old_root
        shutil.rmtree(root, ignore_errors=True)


def test_paused_note() -> dict[str, Any]:
    from scripts.run_factorforge_ultimate_loop import write_paused_research_note

    root = Path(tempfile.mkdtemp(prefix="factorforge_paused_note_smoke_"))
    try:
        report_id = "paused_alpha"
        proof = {
            "report_id": report_id,
            "final_outcome": "awaiting_main_agent_council_synthesis",
            "stop_reason": "completed_council_requires_main_agent_synthesis",
            "iterations": [
                {
                    "report_id": report_id,
                    "outcome": "awaiting_main_agent_council_synthesis",
                    "proof_status": "PAUSED",
                    "wrapper_command": {"rc": 0},
                }
            ],
        }
        result = write_paused_research_note(
            factorforge_root=root,
            report_id=report_id,
            pause_state="awaiting_main_agent_council_synthesis",
            proof=proof,
            iteration=proof["iterations"][0],
            reason="completed_council_requires_main_agent_synthesis",
        )
        note = load_json(Path(result["json_path"]))
        assert_true("paused note status", note["status"] == "paused", note)
        assert_true("paused note state", note["pause_state"] == "awaiting_main_agent_council_synthesis", note)
        assert_true("paused note questions", bool(note.get("next_questions")), note)
        assert_true("paused note md exists", Path(result["markdown_path"]).exists(), result)
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    results = {
        "law_registry": test_law_registry(),
        "step3b_contract_resolution": test_step3b_contract_resolution(),
        "real_moneyflow_law_registry_entries": test_real_moneyflow_law_registry_entries(),
        "child_qlib_config": test_child_qlib_config(),
        "qlib_not_applicable_backend": test_qlib_not_applicable_backend(),
        "paused_note": test_paused_note(),
    }
    print(json.dumps({"verdict": "ACCEPT", "results": results}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
