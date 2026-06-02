#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.artifact_identity import build_spec_hash
from scripts.step12_intake_common import build_canonical_formula_step1

CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
RID = "STEP12_HYPOTHESIS_SMOKE"
ALPHA019_RID = "STEP12_ALPHA019_FORMULA_MODELLING_SMOKE"


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve())
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def file_snapshot() -> set[str]:
    files: set[str] = set()
    for rel in CANONICAL_ROOTS:
        root = REPO_ROOT / rel
        if not root.exists():
            continue
        for item in root.rglob("*"):
            if item.is_file():
                files.add(str(item.relative_to(REPO_ROOT)))
    return files


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run(cmd: list[str], root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {"command": cmd, "rc": proc.returncode, "stdout_tail": proc.stdout[-12000:], "stderr_tail": proc.stderr[-12000:]}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def import_run_step3_module():
    path = REPO_ROOT / "skills" / "factor-forge-step3" / "scripts" / "run_step3.py"
    spec = importlib.util.spec_from_file_location("factorforge_step12_smoke_run_step3", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_run_step3b_module():
    path = REPO_ROOT / "skills" / "factor-forge-step3" / "scripts" / "run_step3b.py"
    spec = importlib.util.spec_from_file_location("factorforge_step12_smoke_run_step3b", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def remove_mechanism_source_fields(payload: dict[str, Any]) -> None:
    contract = payload.get("mechanism_math_contract")
    if isinstance(contract, dict):
        contract.pop("source_economic_hypothesis", None)
        contract.pop("source_math_hypothesis_candidates", None)
    canonical_contract = ((payload.get("canonical_spec") or {}).get("mechanism_math_contract"))
    if isinstance(canonical_contract, dict):
        canonical_contract.pop("source_economic_hypothesis", None)
        canonical_contract.pop("source_math_hypothesis_candidates", None)


def refresh_step2_identity_hashes(master: dict[str, Any], handoff: dict[str, Any]) -> None:
    spec_hash = build_spec_hash(master)
    master["spec_hash"] = spec_hash
    identity = master.get("artifact_identity")
    if isinstance(identity, dict):
        identity["spec_hash"] = spec_hash
    handoff_identity = handoff.get("artifact_identity")
    if isinstance(handoff_identity, dict):
        handoff_identity["spec_hash"] = spec_hash


def run_step3a_blocked_handoff_clears_execution_state_case() -> dict[str, Any]:
    module = import_run_step3_module()
    existing = {
        "report_id": "STEP12_STALE_HANDOFF",
        "step3a_ready": True,
        "step3b_ready": True,
        "first_run_outputs": {
            "status": "ready",
            "output_paths": ["runs/old/factor_values.parquet"],
            "run_metadata_path": "runs/old/metadata.json",
            "factor_values_path": "runs/old/factor_values.parquet",
        },
        "factor_impl_ref": "generated_code/old/factor.py",
        "factor_impl_stub_ref": "generated_code/old/stub.py",
        "qlib_expression_draft_ref": "objects/old/qlib.json",
        "hybrid_execution_scaffold_ref": "objects/old/hybrid.json",
        "local_input_paths": {
            "old": "kept",
            "daily_df_parquet": "runs/old/daily.parquet",
            "daily_df_csv": "runs/old/daily.csv",
            "daily_df_csv_sample": "runs/old/daily_sample.csv",
            "minute_df_parquet": "runs/old/minute.parquet",
            "minute_df_csv": "runs/old/minute.csv",
        },
    }
    merged = module.merge_handoff(existing, {
        "report_id": "STEP12_STALE_HANDOFF",
        "step3a_ready": False,
        "local_input_paths": {},
    })
    first_run = merged.get("first_run_outputs") or {}
    stale_refs_absent = all(
        key not in merged
        for key in [
            "factor_impl_ref",
            "factor_impl_stub_ref",
            "qlib_expression_draft_ref",
            "hybrid_execution_scaffold_ref",
            "step3b_sample_run_metadata_ref",
            "step3b_sample_factor_values_ref",
        ]
    )
    executable_local_input_keys = [
        "daily_df_parquet",
        "daily_df_csv",
        "daily_df_csv_sample",
        "minute_df_parquet",
        "minute_df_csv",
    ]
    local_inputs = merged.get("local_input_paths") if isinstance(merged.get("local_input_paths"), dict) else {}
    stale_local_inputs_absent = all(key not in local_inputs for key in executable_local_input_keys)
    ok = (
        merged.get("step3a_ready") is False
        and merged.get("step3b_ready") is False
        and first_run.get("status") == "blocked"
        and not first_run.get("output_paths")
        and first_run.get("factor_values_path") is None
        and stale_refs_absent
        and stale_local_inputs_absent
    )
    return {
        "ok": bool(ok),
        "step3a_ready": merged.get("step3a_ready"),
        "step3b_ready": merged.get("step3b_ready"),
        "first_run_outputs": first_run,
        "stale_refs_absent": stale_refs_absent,
        "local_input_paths": local_inputs,
        "stale_local_inputs_absent": stale_local_inputs_absent,
    }


def run_step3b_cannot_upgrade_blocked_step3a_handoff_case() -> dict[str, Any]:
    module = import_run_step3b_module()
    existing = {
        "report_id": "STEP12_BLOCKED_STEP3A",
        "step3a_ready": False,
        "step3b_ready": False,
        "first_run_outputs": {
            "status": "blocked",
            "no_first_run_reason": "step3a_feasibility_blocked",
            "output_paths": [],
            "run_metadata_path": None,
            "factor_values_path": None,
        },
        "local_input_paths": {
            "input_mode": "blocked",
            "snapshot_source": "step3a_feasibility_blocked",
        },
    }
    merged = module.merge_handoff(existing, {
        "report_id": "STEP12_BLOCKED_STEP3A",
        "step3a_ready": False,
        "step3b_ready": True,
        "first_run_outputs": {
            "status": "pending",
            "no_first_run_reason": "no_local_snapshots_available",
            "output_paths": [],
            "run_metadata_path": None,
            "factor_values_path": None,
            "producer": "step3b",
        },
        "factor_impl_stub_ref": "generated_code/STEP12_BLOCKED_STEP3A/factor_impl_stub__STEP12_BLOCKED_STEP3A.py",
    })
    first_run = merged.get("first_run_outputs") or {}
    ok = (
        merged.get("step3a_ready") is False
        and merged.get("step3b_ready") is False
        and first_run.get("status") == "blocked"
        and first_run.get("no_first_run_reason") == "step3a_feasibility_blocked"
        and "factor_impl_stub_ref" not in merged
    )
    return {
        "ok": bool(ok),
        "step3a_ready": merged.get("step3a_ready"),
        "step3b_ready": merged.get("step3b_ready"),
        "first_run_outputs": first_run,
        "factor_impl_stub_ref": merged.get("factor_impl_stub_ref"),
    }


def build_fixture(root: Path) -> None:
    objects = root / "objects"
    write_json(objects / "alpha_idea_master" / f"alpha_idea_master__{RID}.json", {
        "report_id": RID,
        "source_type": "paper_canonical_formula",
        "raw_formula": "rank(correlation(high, volume, 5))",
        "factor_id": RID,
        "final_factor": {
            "name": "price_volume_attention_pressure",
            "assembly_steps": ["rank(correlation(high, volume, 5))"],
            "economic_logic": "high price and volume co-movement may reflect crowded attention and transient order imbalance",
            "behavioral_logic": "behaviorally biased late buyers and liquidity demanders may overpay under attention pressure",
            "causal_chain": "attention pressure and order imbalance create transient impact that may later decay",
            "direction": "negative_after_sign_review",
            "key_implementation_risks": ["turnover may destroy signal"],
        },
        "assembly_path": ["rank(correlation(high, volume, 5))"],
    })
    thesis = {
        "thesis_name": "price volume attention pressure",
        "economic_logic": "price-volume co-movement identifies attention pressure",
        "behavioral_logic": "late attention buyers and liquidity demanders are possible counterparties",
        "causal_chain": "attention and order imbalance create transient impact",
        "key_variables": ["high", "volume"],
        "operators": ["rank", "correlation"],
        "signals": ["price-volume dependence"],
        "raw_formula_text": "rank(correlation(high, volume, 5))",
    }
    write_json(objects / "validation" / f"report_map_validation__{RID}__alpha_thesis.json", thesis)
    write_json(objects / "validation" / f"report_map_validation__{RID}__challenger_alpha_thesis.json", thesis)
    write_json(objects / "report_maps" / f"report_map__{RID}__primary.json", {"variables": ["high", "volume"], "operators": ["rank", "correlation"], "raw_formula": "rank(correlation(high, volume, 5))"})


def build_alpha019_formula_fixture(root: Path) -> None:
    formula = (
        "multiply("
        "negate(sign(plus(minus(close, delay(close, 7)), delta(close, 7)))), "
        "plus(1, rank(plus(1, sum(returns, 250))))"
        ")"
    )
    bundle = build_canonical_formula_step1(
        report_id=ALPHA019_RID,
        factor_id="ALPHA019_LIKE",
        source_name="Alpha019 synthetic formula modelling smoke",
        source_url="synthetic://alpha019-like",
        formula=formula,
        window_start="2016-01-01",
        window_end="2024-12-31",
    )
    objects = root / "objects"
    write_json(objects / "alpha_idea_master" / f"alpha_idea_master__{ALPHA019_RID}.json", bundle["aim"])
    write_json(objects / "validation" / f"report_map_validation__{ALPHA019_RID}__alpha_thesis.json", bundle["primary"])
    write_json(objects / "validation" / f"report_map_validation__{ALPHA019_RID}__challenger_alpha_thesis.json", bundle["challenger"])
    write_json(objects / "report_maps" / f"report_map__{ALPHA019_RID}__primary.json", bundle["report_map"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--root", default=f"/tmp/factorforge_step12_hypothesis_contract_{int(time.time())}")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    before = file_snapshot()
    build_fixture(root)
    build_alpha019_formula_fixture(root)

    commands = {
        "standardize_step1": run([sys.executable, "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py", "--report-id", RID], root),
        "validate_step1": run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", RID], root),
        "run_step2_wrapper": run([sys.executable, "scripts/run_factorforge_ultimate.py", "--report-id", RID, "--start-step", "2", "--end-step", "2", "--council-mode", "off"], root),
        "alpha019_standardize_step1": run([sys.executable, "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py", "--report-id", ALPHA019_RID], root),
        "alpha019_validate_step1": run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", ALPHA019_RID], root),
        "alpha019_run_step2_wrapper": run([sys.executable, "scripts/run_factorforge_ultimate.py", "--report-id", ALPHA019_RID, "--start-step", "2", "--end-step", "2", "--council-mode", "off"], root),
    }
    aim = json.loads((root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{RID}.json").read_text(encoding="utf-8"))
    master_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{RID}.json"
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3__{RID}.json"
    master = json.loads(master_path.read_text(encoding="utf-8")) if master_path.exists() else {}
    handoff = json.loads(handoff_path.read_text(encoding="utf-8")) if handoff_path.exists() else {}
    proof_path = root / "objects" / "runtime_context" / f"ultimate_run_report__{RID}.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.exists() else {}
    alpha019_aim_path = root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{ALPHA019_RID}.json"
    alpha019_master_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{ALPHA019_RID}.json"
    alpha019_aim = json.loads(alpha019_aim_path.read_text(encoding="utf-8")) if alpha019_aim_path.exists() else {}
    alpha019_master = json.loads(alpha019_master_path.read_text(encoding="utf-8")) if alpha019_master_path.exists() else {}
    alpha019_primary_path = root / "objects" / "validation" / f"report_map_validation__{ALPHA019_RID}__alpha_thesis.json"
    alpha019_primary = json.loads(alpha019_primary_path.read_text(encoding="utf-8")) if alpha019_primary_path.exists() else {}
    alpha019_discipline = alpha019_aim.get("research_discipline") or {}
    alpha019_understanding = alpha019_discipline.get("formula_understanding") or alpha019_aim.get("formula_understanding") or {}
    alpha019_econ = alpha019_discipline.get("economic_hypothesis") or {}
    alpha019_math = alpha019_discipline.get("math_hypothesis_candidates") or []
    alpha019_contract = alpha019_master.get("mechanism_math_contract") or {}
    rid_runtime_context = root / "objects" / "runtime_context" / f"runtime_context__{RID}.json"
    alpha019_runtime_context = root / "objects" / "runtime_context" / f"runtime_context__{ALPHA019_RID}.json"
    alpha019_headline_blob = json.dumps({
        "factor_intuition": alpha019_aim.get("factor_intuition"),
        "return_source_hypothesis": alpha019_aim.get("return_source_hypothesis"),
        "final_factor_economic_logic": (alpha019_aim.get("final_factor") or {}).get("economic_logic"),
        "report_map_validation_economic_logic": alpha019_primary.get("economic_logic"),
    }, ensure_ascii=False).lower()
    discipline = aim.get("research_discipline") or {}
    research_contract = master.get("research_contract") or {}
    mechanism_contract = master.get("mechanism_math_contract") or {}
    after = file_snapshot()
    pollution = sorted(after - before)
    cases = {
        "step1_economic_hypothesis_present": isinstance(discipline.get("economic_hypothesis"), dict) and bool(discipline.get("economic_hypothesis")),
        "step1_math_hypothesis_candidates_present": isinstance(discipline.get("math_hypothesis_candidates"), list) and bool(discipline.get("math_hypothesis_candidates")),
        "step2_preserves_economic_hypothesis": research_contract.get("economic_hypothesis") == discipline.get("economic_hypothesis"),
        "step2_preserves_math_hypotheses": research_contract.get("math_hypothesis_candidates") == discipline.get("math_hypothesis_candidates"),
        "mechanism_contract_carries_sources": bool(mechanism_contract.get("source_economic_hypothesis")) and bool(mechanism_contract.get("source_math_hypothesis_candidates")),
        "wrapper_pass": proof.get("status") == "PASS",
        "alpha019_like_formula_specific_modelling_pass": (
            (((alpha019_econ.get("second_layer") or {}).get("subtype") or "").find("slow_winner") >= 0)
            and any("short" in item.lower() or "threshold" in item.lower() or "reversal" in item.lower() for item in [
                (alpha019_econ.get("second_layer") or {}).get("subtype", ""),
                (alpha019_econ.get("second_layer") or {}).get("why_they_may_pay", ""),
            ])
            and bool(alpha019_math)
            and alpha019_math[0].get("model_family") == "stochastic_process"
            and alpha019_contract.get("model_family") == "stochastic_process"
            and alpha019_understanding.get("interaction_structure") == "slow_state_x_short_horizon_threshold"
            and all(
                token in json.dumps(alpha019_contract, ensure_ascii=False).lower()
                for token in ["slow", "short", "threshold", "rank", "sum(returns,250)"]
            )
            and alpha019_contract.get("source_economic_hypothesis") == (alpha019_master.get("research_contract") or {}).get("economic_hypothesis")
            and alpha019_contract.get("source_math_hypothesis_candidates") == (alpha019_master.get("research_contract") or {}).get("math_hypothesis_candidates")
        ),
        "alpha019_headline_formula_specific_no_generic_price_volume": (
            "slow" in alpha019_headline_blob
            and ("threshold" in alpha019_headline_blob or "short-horizon" in alpha019_headline_blob)
            and "price-volume" not in alpha019_headline_blob
        ),
        "canonical_formula_step1_v2_fields_present": (
            isinstance(alpha019_discipline.get("market_process_thesis"), dict)
            and isinstance(alpha019_discipline.get("primary_mechanism_model_candidates"), list)
            and bool(alpha019_discipline.get("primary_mechanism_model_candidates"))
            and isinstance(alpha019_discipline.get("stochastic_price_process_projection"), dict)
            and (alpha019_discipline.get("stochastic_price_process_projection") or {}).get("projection_required") is True
        ),
        "ultimate_wrapper_does_not_write_worker_runtime_context": (
            not rid_runtime_context.exists()
            and not alpha019_runtime_context.exists()
        ),
    }
    mutation_cases: dict[str, Any] = {}
    aim_path = root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{RID}.json"
    original_aim = copy.deepcopy(aim)
    original_master = copy.deepcopy(master)
    original_handoff = copy.deepcopy(handoff)

    if commands["validate_step1"]["rc"] == 0:
        mutated = copy.deepcopy(original_aim)
        second = (((mutated.get("research_discipline") or {}).get("economic_hypothesis") or {}).get("second_layer") or {})
        if isinstance(second, dict):
            second.pop("why_they_may_pay", None)
        write_json(aim_path, mutated)
        proc = run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", RID], root)
        token_present = "economic_hypothesis" in (proc["stdout_tail"] + proc["stderr_tail"])
        mutation_cases["missing_why_they_may_pay_blocks_step1"] = {
            "rc": proc["rc"],
            "token_present": token_present,
            "ok": proc["rc"] == 1 and token_present,
        }
        write_json(aim_path, original_aim)
    else:
        mutation_cases["missing_why_they_may_pay_blocks_step1"] = {"ok": False, "skipped": "positive Step1 validation failed"}

    if master_path.exists() and handoff_path.exists() and commands["run_step2_wrapper"]["rc"] == 0:
        mutated_master = copy.deepcopy(original_master)
        mutated_handoff = copy.deepcopy(original_handoff)
        remove_mechanism_source_fields(mutated_master)
        remove_mechanism_source_fields(mutated_handoff)
        refresh_step2_identity_hashes(mutated_master, mutated_handoff)
        write_json(master_path, mutated_master)
        write_json(handoff_path, mutated_handoff)
        proc = run([sys.executable, "skills/factor-forge-step2/scripts/validate_step2.py", "--report-id", RID], root)
        output = proc["stdout_tail"] + proc["stderr_tail"]
        token_present = "source_hypotheses" in output or "source_economic_hypothesis" in output
        mutation_cases["missing_mechanism_source_hypotheses_blocks_step2"] = {
            "rc": proc["rc"],
            "token_present": token_present,
            "ok": proc["rc"] == 1 and token_present,
        }
        write_json(master_path, original_master)
        write_json(handoff_path, original_handoff)
    else:
        mutation_cases["missing_mechanism_source_hypotheses_blocks_step2"] = {"ok": False, "skipped": "positive Step2 wrapper failed"}

    mutation_cases["step3a_blocked_handoff_clears_execution_state"] = run_step3a_blocked_handoff_clears_execution_state_case()
    mutation_cases["step3b_cannot_upgrade_blocked_step3a_handoff"] = run_step3b_cannot_upgrade_blocked_step3a_handoff_case()

    if commands["alpha019_run_step2_wrapper"]["rc"] == 0:
        proc = run([
            sys.executable,
            "scripts/run_factorforge_ultimate.py",
            "--report-id",
            ALPHA019_RID,
            "--start-step",
            "3",
            "--end-step",
            "3",
            "--council-mode",
            "off",
        ], root)
        output = proc["stdout_tail"] + proc["stderr_tail"]
        mutation_cases["ultimate_step3_block_does_not_write_worker_runtime_context"] = {
            "rc": proc["rc"],
            "runtime_context_exists": alpha019_runtime_context.exists(),
            "token_present": "validate_step3" in output or "BLOCK_STEP3A" in output,
            "ok": proc["rc"] != 0 and not alpha019_runtime_context.exists(),
        }
    else:
        mutation_cases["ultimate_step3_block_does_not_write_worker_runtime_context"] = {
            "ok": False,
            "skipped": "positive Alpha019 Step2 wrapper failed",
        }

    summary = {
        "verdict": "ACCEPT" if all(cases.values()) and all(item.get("ok") for item in mutation_cases.values()) and not pollution and all(item["rc"] == 0 for item in commands.values()) else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": is_tmp(root), "enforced": True},
        "commands": commands,
        "cases": cases,
        "mutation_cases": mutation_cases,
        "economic_hypothesis": discipline.get("economic_hypothesis"),
        "math_candidate_count": len(discipline.get("math_hypothesis_candidates") or []),
        "mechanism_model_family": mechanism_contract.get("model_family"),
        "runtime_context_guard": {
            "rid_runtime_context_exists": rid_runtime_context.exists(),
            "alpha019_runtime_context_exists": alpha019_runtime_context.exists(),
        },
        "alpha019_formula_specific_modelling": {
            "headline_blob": alpha019_headline_blob,
            "step1_economic_hypothesis": alpha019_econ,
            "formula_understanding": alpha019_understanding,
            "math_hypothesis_candidates": alpha019_math,
            "mechanism_model_family": alpha019_contract.get("model_family"),
            "mechanism_state_or_object": alpha019_contract.get("state_or_object"),
            "mechanism_factor_as_estimator": alpha019_contract.get("factor_as_estimator"),
            "mechanism_process_hypothesis": alpha019_contract.get("process_hypothesis"),
            "mechanism_conditional_distribution_hypothesis": alpha019_contract.get("conditional_distribution_hypothesis"),
        },
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
    }
    write_json(root / "step12_hypothesis_contract_smoke_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
