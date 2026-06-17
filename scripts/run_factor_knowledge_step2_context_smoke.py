#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUN_STEP2_PATH = REPO_ROOT / "skills" / "factor-forge-step2" / "scripts" / "run_step2.py"
VALIDATE_STEP2_PATH = REPO_ROOT / "skills" / "factor-forge-step2" / "scripts" / "validate_step2.py"


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    run_step2 = load_module(RUN_STEP2_PATH, "factorforge_step2_run_for_knowledge_smoke")
    validate_step2 = load_module(VALIDATE_STEP2_PATH, "factorforge_step2_validate_for_knowledge_smoke")
    aim = {
        "final_factor": {
            "name": "moneyflow_repair_smoke",
            "economic_logic": "profit payer forced flow repaired absorption",
            "behavioral_logic": "reversal after moneyflow pressure",
            "causal_chain": "uninformed selling creates support and first-passage repair",
            "assembly_steps": ["moneyflow", "first_passage", "support"],
        },
        "research_discipline": {
            "economic_hypothesis": {
                "macro_return_source": "market_structure_arbitrage",
                "second_layer": {
                    "subtype": "profit_payer_supply",
                    "expected_counterparty_or_payer": "forced or uninformed liquidity demand",
                    "why_they_may_pay": "pressure creates temporary mispricing",
                },
                "counterparty_loss_hypothesis": "profit payers sell into informed absorption",
            },
            "math_hypothesis_candidates": [
                {
                    "hypothesis_id": "first_passage_repair",
                    "linked_economic_hypothesis": "profit_payer_supply",
                    "model_family": "stochastic_process",
                    "math_tools": ["first_passage"],
                    "state_or_object": "hidden moneyflow pressure state",
                    "process_or_distribution_hypothesis": "repair path hits upside barrier before downside break",
                    "observable_estimator": "moneyflow and support proxy",
                    "target_functional": "long-side expected payoff",
                    "why_suitable": "models path geometry rather than additive score",
                    "falsification_tests": ["no long-side edge after costs"],
                }
            ],
            "initial_return_source_hypothesis": "profit payer flow",
            "step1_random_object": "hidden moneyflow pressure state",
        },
    }
    primary = {
        "factor_id": "moneyflow_repair_smoke",
        "report_id": "SMOKE_STEP2_FACTOR_KNOWLEDGE_CONTEXT",
        "raw_formula_text": "moneyflow first_passage support repair",
    }
    thesis = {
        "signals": ["moneyflow", "first_passage", "support"],
        "key_variables": ["moneyflow", "amount", "close"],
    }
    contract = run_step2.build_step2_research_contract(primary, {}, aim, thesis)
    context = contract.get("factor_knowledge_context") or {}
    knowledge_contract = contract.get("knowledge_reference_contract") or {}
    if context.get("schema_version") != "factor_knowledge_context_v1":
        raise SystemExit("Step2 research contract missing factor_knowledge_context_v1")
    if context.get("node_count", 0) < 1:
        raise SystemExit("Step2 research contract did not retrieve graph context")
    if not validate_step2.valid_knowledge_reference_contract(knowledge_contract):
        raise SystemExit("Step2 knowledge_reference_contract failed validator")
    if not any("Graph prior" in str(item) for item in contract.get("similar_case_lessons_imported") or []):
        raise SystemExit("Step2 did not import graph prior lessons")
    print(json.dumps({
        "verdict": "ACCEPT",
        "node_count": context.get("node_count"),
        "knowledge_reference_contract": knowledge_contract,
        "first_node": (context.get("nodes") or [{}])[0].get("id"),
    }, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
