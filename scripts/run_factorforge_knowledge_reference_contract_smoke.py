#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.knowledge_reference import (
    BLOCK_KNOWLEDGE_RETRIEVAL_REQUIRED,
    KNOWLEDGE_REFERENCE_CONTRACT_VERSION,
    build_knowledge_reference_contract,
    build_legacy_knowledge_reference_contract,
    validate_knowledge_reference_contract,
)


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    return path


def load_step1_module():
    path = REPO_ROOT / "skills/factor_forge_step1/modules/report_ingestion/research_discipline.py"
    spec = importlib.util.spec_from_file_location("factorforge_step1_research_discipline_smoke", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path("/tmp/factorforge_knowledge_reference_contract_smoke")
    shutil.rmtree(root, ignore_errors=True)
    results = []

    index_path = write_jsonl(
        root / "knowledge" / "retrieval" / "factorforge_retrieval_index.jsonl",
        [
            {
                "id": "knowledge_record__flow_v1",
                "report_id": "prior_flow_report",
                "factor_id": "flow_pressure",
                "decision": "reject",
                "text": "flow pressure intraday smart money failed when no future intraday minutes policy was missing",
            }
        ],
    )
    contract = build_knowledge_reference_contract(
        repo_root=root,
        query_text="intraday smart money flow pressure no future minutes",
        producer="knowledge_reference_smoke",
    )
    if contract.get("contract_version") != KNOWLEDGE_REFERENCE_CONTRACT_VERSION:
        raise AssertionError(f"unexpected contract_version: {contract}")
    if contract.get("hit_count") != 1 or contract.get("retrieved_case_ids") != ["knowledge_record__flow_v1"]:
        raise AssertionError(f"expected one retrieved prior case from {index_path}: {contract}")
    failures = validate_knowledge_reference_contract(contract, retrieval_required=True)
    if failures:
        raise AssertionError(f"retrieved knowledge reference did not validate: {failures}")
    results.append({"name": "knowledge_reference_hit_smoke", "status": "PASS"})

    cold = build_knowledge_reference_contract(
        repo_root=root,
        query_text="unrelated unique token zzz",
        producer="knowledge_reference_smoke",
    )
    if cold.get("retrieval_status") != "cold_start" or cold.get("fallback_reason") != "knowledge_retrieval_cold_start_no_similar_case":
        raise AssertionError(f"expected auditable cold-start contract: {cold}")
    required_failures = validate_knowledge_reference_contract(cold, retrieval_required=True)
    if not any(BLOCK_KNOWLEDGE_RETRIEVAL_REQUIRED in item for item in required_failures):
        raise AssertionError(f"required retrieval did not block on zero hits: {required_failures}")
    results.append({"name": "knowledge_reference_required_zero_hit_blocks", "status": "PASS"})

    step1 = load_step1_module()
    aim = {
        "report_id": "knowledge_reference_report",
        "final_factor": {
            "name": "flow_pressure",
            "economic_logic": ["intraday smart money flow pressure"],
            "what_must_be_true": ["flow pressure predicts next return"],
            "what_would_break_it": ["flow pressure is pure noise"],
        },
    }
    discipline = step1.build_step1_research_discipline(aim, root)
    step1_contract = discipline.get("knowledge_reference_contract")
    if validate_knowledge_reference_contract(step1_contract or {}, retrieval_required=False):
        raise AssertionError(f"Step1 did not attach a valid knowledge_reference_contract: {step1_contract}")
    if discipline.get("similar_case_lessons_imported") != step1_contract.get("similar_case_lessons_imported"):
        raise AssertionError("Step1 similar_case_lessons_imported diverged from knowledge_reference_contract")
    results.append({"name": "step1_attaches_knowledge_reference_contract", "status": "PASS"})

    legacy = build_legacy_knowledge_reference_contract(
        similar_case_lessons=["legacy lesson retained from old Step1 artifact"],
        producer="legacy_smoke",
    )
    if validate_knowledge_reference_contract(legacy, retrieval_required=False):
        raise AssertionError(f"legacy knowledge reference fallback did not validate: {legacy}")
    if legacy.get("fallback_reason") != "legacy_artifact_missing_knowledge_reference_contract":
        raise AssertionError(f"legacy fallback reason missing: {legacy}")
    results.append({"name": "legacy_artifact_knowledge_reference_fallback", "status": "PASS"})

    step1_validator = load_module(
        REPO_ROOT / "skills/factor-forge-step1/scripts/validate_step1.py",
        "factorforge_step1_validator_legacy_smoke",
    )
    step2_validator = load_module(
        REPO_ROOT / "skills/factor-forge-step2/scripts/validate_step2.py",
        "factorforge_step2_validator_legacy_smoke",
    )
    if not step1_validator.valid_knowledge_reference_contract({}, ["legacy lesson"]):
        raise AssertionError("Step1 validator did not accept legacy lessons without knowledge_reference_contract")
    if not step2_validator.valid_knowledge_reference_contract({}, ["legacy lesson"]):
        raise AssertionError("Step2 validator did not accept legacy lessons without knowledge_reference_contract")
    results.append({"name": "legacy_validator_fallback_accepts_old_artifacts", "status": "PASS"})

    summary = {
        "verdict": "ACCEPT",
        "production_research_started": False,
        "worker_started": False,
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print("FACTORFORGE_KNOWLEDGE_REFERENCE_CONTRACT_SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
