#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STANDARDIZE_STEP1_PATH = REPO_ROOT / "skills" / "factor-forge-step1" / "scripts" / "standardize_step1_research_fields.py"
VALIDATE_STEP1_PATH = REPO_ROOT / "skills" / "factor-forge-step1" / "scripts" / "validate_step1.py"


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    standardize = load_module(STANDARDIZE_STEP1_PATH, "factorforge_step1_standardize_for_knowledge_smoke")
    validate = load_module(VALIDATE_STEP1_PATH, "factorforge_step1_validate_for_knowledge_smoke")
    aim = {
        "report_id": "SMOKE_STEP1_FACTOR_KNOWLEDGE_CONTEXT",
        "final_factor": {
            "name": "moneyflow_repair_smoke",
            "economic_logic": "profit payer forced flow repaired absorption",
            "behavioral_logic": "reversal after moneyflow pressure",
            "causal_chain": "uninformed selling creates support and first-passage repair",
            "assembly_steps": ["moneyflow", "first_passage", "support"],
        },
        "research_discipline": {
            "similar_case_lessons_imported": ["existing Step1 prior"],
            "initial_return_source_hypothesis": "profit payer flow",
            "step1_random_object": "hidden moneyflow pressure state",
        },
    }
    enriched = standardize.attach_factor_knowledge_context(aim)
    context = (enriched.get("research_discipline") or {}).get("factor_knowledge_context") or {}
    knowledge_contract = enriched.get("knowledge_reference_contract") or {}
    lessons = (enriched.get("research_discipline") or {}).get("similar_case_lessons_imported") or []
    if context.get("schema_version") != "factor_knowledge_context_v1":
        raise SystemExit("Step1 enriched artifact missing factor_knowledge_context_v1")
    if context.get("node_count", 0) < 1:
        raise SystemExit("Step1 enrichment did not retrieve graph context")
    if not validate.valid_knowledge_reference_contract(knowledge_contract):
        raise SystemExit("Step1 knowledge_reference_contract failed validator")
    if not any("Graph prior" in str(item) for item in lessons):
        raise SystemExit("Step1 did not import graph prior lessons")
    print(json.dumps({
        "verdict": "ACCEPT",
        "node_count": context.get("node_count"),
        "first_node": (context.get("nodes") or [{}])[0].get("id"),
        "knowledge_reference_contract": knowledge_contract,
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
