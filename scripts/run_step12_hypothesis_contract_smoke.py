#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
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

CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
RID = "STEP12_HYPOTHESIS_SMOKE"


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

    commands = {
        "standardize_step1": run([sys.executable, "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py", "--report-id", RID], root),
        "validate_step1": run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", RID], root),
        "run_step2_wrapper": run([sys.executable, "scripts/run_factorforge_ultimate.py", "--report-id", RID, "--start-step", "2", "--end-step", "2", "--council-mode", "off"], root),
    }
    aim = json.loads((root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{RID}.json").read_text(encoding="utf-8"))
    master_path = root / "objects" / "factor_spec_master" / f"factor_spec_master__{RID}.json"
    handoff_path = root / "objects" / "handoff" / f"handoff_to_step3__{RID}.json"
    master = json.loads(master_path.read_text(encoding="utf-8")) if master_path.exists() else {}
    handoff = json.loads(handoff_path.read_text(encoding="utf-8")) if handoff_path.exists() else {}
    proof_path = root / "objects" / "runtime_context" / f"ultimate_run_report__{RID}.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8")) if proof_path.exists() else {}
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

    summary = {
        "verdict": "ACCEPT" if all(cases.values()) and all(item.get("ok") for item in mutation_cases.values()) and not pollution and all(item["rc"] == 0 for item in commands.values()) else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": is_tmp(root), "enforced": True},
        "commands": commands,
        "cases": cases,
        "mutation_cases": mutation_cases,
        "economic_hypothesis": discipline.get("economic_hypothesis"),
        "math_candidate_count": len(discipline.get("math_hypothesis_candidates") or []),
        "mechanism_model_family": mechanism_contract.get("model_family"),
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
    }
    write_json(root / "step12_hypothesis_contract_smoke_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
