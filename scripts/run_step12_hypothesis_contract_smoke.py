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
from factor_factory.knowledge_reference import build_knowledge_reference_contract
from factor_factory.measurement_program import measurement_program_template
from scripts.step12_intake_common import (
    attach_agent_authored_measurement_program,
    build_canonical_formula_step1,
)

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


def enrich_step1_with_smoke_research_contract(root: Path, report_id: str) -> None:
    """Inject a test-only, researcher-authored formal contract after intake.

    Production intake deliberately remains under-specified until an agent writes
    this semantic contract; the smoke needs an explicit positive fixture to test
    Step1 -> Step2 preservation.
    """
    path = root / "objects" / "alpha_idea_master" / f"alpha_idea_master__{report_id}.json"
    aim = load_json(path)
    discipline = aim.get("research_discipline") if isinstance(aim.get("research_discipline"), dict) else {}
    math_candidates = discipline.get("math_hypothesis_candidates") or []
    primary_candidate = (
        math_candidates[0]
        if math_candidates and isinstance(math_candidates[0], dict)
        else {}
    )
    primary_family = str(
        primary_candidate.get("model_family")
        or "structural conditional-payoff model"
    )
    placeholder = "SMOKE_RESEARCHER_MUST_REPLACE"
    program = measurement_program_template(
        placeholder=placeholder,
        implementation_route="operator",
    )

    def fill(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if value == placeholder:
            return "test-only mechanism-specific auditable statement"
        return value

    program = fill(program)
    program["math_tool_selection"].update(
        {
            "candidate_tool_families": [
                primary_family,
                "mechanism-distinct structural alternative",
                "measurement-alias null model",
            ],
            "selected_tool_families": [primary_family],
            "selection_rationale": "the formula-specific economic state determines this test model; operator availability does not",
            "rejected_tool_families": [
                {
                    "tool_family": "unrelated intrinsic-value or generic diffusion template",
                    "reason": "it does not explain this formula-specific payer and observable state",
                }
            ],
        }
    )
    model_candidates = program["model_selection"]["candidate_models"]
    model_candidates[0].update(
        {
            "model_family": primary_family,
            "mathematical_object": primary_candidate.get("mathematical_object") or "formula-specific mathematical object estimated at legal time t",
            "mechanism_equation_or_functional": primary_candidate.get(
                "mechanism_equation_or_functional"
            ) or "object_t = mechanism(legal_inputs_<=t)",
            "economic_implication": primary_candidate.get("why_suitable") or "the selected object changes the next-horizon after-cost payoff",
            "identifiability_condition": "the state survives mechanism controls and component ablation",
            "decisive_test": next(
                iter(primary_candidate.get("falsification_tests") or []),
                "controlled after-cost payoff and component ablation",
            ),
        }
    )
    model_candidates[1].update(
        {
            "model_family": "mechanism-distinct permanent-state alternative",
            "mathematical_object": "persistent information state",
            "mechanism_equation_or_functional": (
                "permanent_state_t = permanent_update(legal_inputs_<=t)"
            ),
            "target_functional": "permanent-information continuation payoff",
            "market_outcome_projection": (
                "permanent state predicts continuation rather than repair"
            ),
            "observation_mapping": (
                "map legal-time innovations into a permanent-state estimator"
            ),
            "economic_implication": "the same observable predicts continuation rather than repair",
            "identifiability_condition": "continuation remains after transient-state controls",
            "decisive_test": "compare continuation and repair signatures",
        }
    )
    model_candidates[2].update(
        {
            "model_family": "measurement-alias null model",
            "mathematical_object": "known size, liquidity and reversal aliases",
            "mechanism_equation_or_functional": (
                "score_t = known_aliases_t + measurement_noise_t"
            ),
            "target_functional": "incremental payoff after known aliases",
            "market_outcome_projection": (
                "the null predicts zero incremental after-cost payoff"
            ),
            "observation_mapping": (
                "project the legal-time score on known aliases"
            ),
            "economic_implication": "the formula has no incremental mechanism-conditioned payoff",
            "identifiability_condition": "alias controls span the same score variation",
            "decisive_test": "incremental payoff is zero after alias controls",
        }
    )
    market_outcome = {
        "role": "terminal_tradeable_quantity_bridge_not_core_model_restriction",
        "projection_kind": "formula-specific state to next-horizon after-cost payoff",
        "source_math_object": model_candidates[0]["mathematical_object"],
        "traded_quantity": "next-horizon after-cost long-side equity return",
        "affected_payoff_or_distribution_terms": [
            "conditional expected return",
            "after-cost long-side payoff",
        ],
        "projection_equation_or_map": "alpha_t = Phi(X_<=t); payoff_t+1 = E[R_t+1 | alpha_t, controls] - trading_cost_t",
        "link_to_observation_equation": "the canonical formula is the legal-time estimator Phi of the selected state",
        "falsifier": "the controlled conditional payoff or component ablation does not support the selected state",
    }
    program["market_outcome_projection"] = copy.deepcopy(market_outcome)
    if primary_candidate:
        program["observation_and_estimation"].update(
            {
                "estimand": primary_candidate.get("target_functional") or program["observation_and_estimation"]["estimand"],
                "observation_map": primary_candidate.get("observable_estimator") or program["observation_and_estimation"]["observation_map"],
                "estimator": primary_candidate.get("observable_estimator") or program["observation_and_estimation"]["estimator"],
            }
        )
    model_candidates[0].update(
        {
            "target_functional": program["observation_and_estimation"][
                "estimand"
            ],
            "market_outcome_projection": program["market_outcome_projection"][
                "projection_equation_or_map"
            ],
            "observation_mapping": program["observation_and_estimation"][
                "observation_map"
            ],
        }
    )
    program["model_selection"]["selection_target"] = "formula-specific next-horizon after-cost payoff mechanism"
    program["model_selection"]["selection_argument"] = "payer, horizon and observable state favor the selected model over the alternative and null"
    program["model_selection"]["rejected_model_reason"] = "the alternative and null imply different controlled payoff signatures"
    program["applicable_audits"] = {
        "selection_rule": "select only specialized audits justified by this smoke mechanism",
        "selected": [],
        "rejected": [],
    }
    knowledge = build_knowledge_reference_contract(
        repo_root=REPO_ROOT,
        knowledge_root=REPO_ROOT / "knowledge" / "因子工厂",
        query_text=json.dumps(
            {
                "economic_hypothesis": discipline.get("economic_hypothesis"),
                "math_hypothesis_candidates": math_candidates,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        producer="step12_hypothesis_contract_smoke_researcher_fixture",
        retrieval_required=False,
    )
    aim["research_discipline"] = discipline
    enriched = attach_agent_authored_measurement_program(
        {"aim": aim},
        measurement_program=program,
        knowledge_reference_contract=knowledge,
    )
    write_json(path, enriched["aim"])


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

    commands: dict[str, dict[str, Any]] = {}
    commands["standardize_step1"] = run([sys.executable, "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py", "--report-id", RID], root)
    enrich_step1_with_smoke_research_contract(root, RID)
    commands["validate_step1"] = run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", RID], root)
    commands["run_step2_wrapper"] = run([sys.executable, "scripts/run_factorforge_ultimate.py", "--report-id", RID, "--start-step", "2", "--end-step", "2", "--council-mode", "off"], root)
    commands["alpha019_standardize_step1"] = run([sys.executable, "skills/factor-forge-step1/scripts/standardize_step1_research_fields.py", "--report-id", ALPHA019_RID], root)
    enrich_step1_with_smoke_research_contract(root, ALPHA019_RID)
    commands["alpha019_validate_step1"] = run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", ALPHA019_RID], root)
    commands["alpha019_run_step2_wrapper"] = run([sys.executable, "scripts/run_factorforge_ultimate.py", "--report-id", ALPHA019_RID, "--start-step", "2", "--end-step", "2", "--council-mode", "off"], root)
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
    alpha019_program = alpha019_master.get("mechanism_conditioned_measurement_program") or {}
    alpha019_selected_model = next(
        (
            item
            for item in ((alpha019_program.get("model_selection") or {}).get("candidate_models") or [])
            if isinstance(item, dict) and item.get("selected") is True
        ),
        {},
    )
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
    measurement_program = master.get("mechanism_conditioned_measurement_program") or {}
    selected_model = next(
        (
            item
            for item in ((measurement_program.get("model_selection") or {}).get("candidate_models") or [])
            if isinstance(item, dict) and item.get("selected") is True
        ),
        {},
    )
    after = file_snapshot()
    pollution = sorted(after - before)
    cases = {
        "step1_economic_hypothesis_present": isinstance(discipline.get("economic_hypothesis"), dict) and bool(discipline.get("economic_hypothesis")),
        "step1_math_hypothesis_candidates_present": isinstance(discipline.get("math_hypothesis_candidates"), list) and bool(discipline.get("math_hypothesis_candidates")),
        "step2_preserves_economic_hypothesis": research_contract.get("economic_hypothesis") == discipline.get("economic_hypothesis"),
        "step2_preserves_math_hypotheses": research_contract.get("math_hypothesis_candidates") == discipline.get("math_hypothesis_candidates"),
        "measurement_program_preserves_one_exact_source_model": (
            bool(measurement_program)
            and measurement_program == aim.get("mechanism_conditioned_measurement_program")
            and measurement_program == (discipline.get("mechanism_conditioned_measurement_program") or {})
            and measurement_program == ((master.get("canonical_spec") or {}).get("mechanism_conditioned_measurement_program") or {})
            and measurement_program == (handoff.get("mechanism_conditioned_measurement_program") or {})
            and not master.get("mechanism_math_contract")
            and not master.get("mechanism_math_contract_v2")
        ),
        "wrapper_pass": proof.get("status") == "PASS",
        "alpha019_like_formula_specific_modelling_pass": (
            (((alpha019_econ.get("second_layer") or {}).get("subtype") or "").find("slow_winner") >= 0)
            and any("short" in item.lower() or "threshold" in item.lower() or "reversal" in item.lower() for item in [
                (alpha019_econ.get("second_layer") or {}).get("subtype", ""),
                (alpha019_econ.get("second_layer") or {}).get("why_they_may_pay", ""),
            ])
            and bool(alpha019_math)
            and alpha019_math[0].get("model_family") == "stochastic_process"
            and alpha019_selected_model.get("model_family") == "stochastic_process"
            and alpha019_understanding.get("interaction_structure") == "slow_state_x_short_horizon_threshold"
            and all(
                token in json.dumps(alpha019_program, ensure_ascii=False).lower()
                for token in ["slow", "short", "threshold"]
            )
            and alpha019_program == alpha019_aim.get("mechanism_conditioned_measurement_program")
            and not alpha019_master.get("mechanism_math_contract")
            and not alpha019_master.get("mechanism_math_contract_v2")
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
            and isinstance(alpha019_discipline.get("market_outcome_projection"), dict)
            and isinstance(alpha019_discipline.get("mechanism_conditioned_measurement_program"), dict)
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

    under_specified = copy.deepcopy(original_aim)
    under_specified.pop("mechanism_conditioned_measurement_program", None)
    under_discipline = under_specified.get("research_discipline") or {}
    if isinstance(under_discipline, dict):
        under_discipline.pop("mechanism_conditioned_measurement_program", None)
        under_discipline.pop("market_outcome_projection", None)
    write_json(aim_path, under_specified)
    proc = run([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", RID], root)
    output = proc["stdout_tail"] + proc["stderr_tail"]
    mutation_cases["unenriched_intake_blocks_before_formal_step2"] = {
        "rc": proc["rc"],
        "token_present": "BLOCK_FACTORFORGE_MEASUREMENT_PROGRAM_INVALID" in output,
        "ok": proc["rc"] == 1
        and "BLOCK_FACTORFORGE_MEASUREMENT_PROGRAM_INVALID" in output,
    }
    write_json(aim_path, original_aim)

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
        mutated_program = copy.deepcopy(mutated_master.get("mechanism_conditioned_measurement_program") or {})
        mutated_program.setdefault("model_selection", {})["selection_argument"] = "tampered after Step2"
        mutated_master["mechanism_conditioned_measurement_program"] = mutated_program
        refresh_step2_identity_hashes(mutated_master, mutated_handoff)
        write_json(master_path, mutated_master)
        write_json(handoff_path, mutated_handoff)
        proc = run([sys.executable, "skills/factor-forge-step2/scripts/validate_step2.py", "--report-id", RID], root)
        output = proc["stdout_tail"] + proc["stderr_tail"]
        token_present = "MEASUREMENT_PROGRAM" in output or "measurement_program" in output
        mutation_cases["measurement_program_copy_mismatch_blocks_step2"] = {
            "rc": proc["rc"],
            "token_present": token_present,
            "ok": proc["rc"] == 1 and token_present,
        }
        write_json(master_path, original_master)
        write_json(handoff_path, original_handoff)
    else:
        mutation_cases["measurement_program_copy_mismatch_blocks_step2"] = {"ok": False, "skipped": "positive Step2 wrapper failed"}

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
        "mechanism_model_family": selected_model.get("model_family"),
        "runtime_context_guard": {
            "rid_runtime_context_exists": rid_runtime_context.exists(),
            "alpha019_runtime_context_exists": alpha019_runtime_context.exists(),
        },
        "alpha019_formula_specific_modelling": {
            "headline_blob": alpha019_headline_blob,
            "step1_economic_hypothesis": alpha019_econ,
            "formula_understanding": alpha019_understanding,
            "math_hypothesis_candidates": alpha019_math,
            "mechanism_model_family": alpha019_selected_model.get("model_family"),
            "mathematical_object": alpha019_selected_model.get("mathematical_object"),
            "observation_and_estimation": alpha019_program.get("observation_and_estimation") or {},
            "legacy_contract_synthesized": bool(
                alpha019_master.get("mechanism_math_contract")
                or alpha019_master.get("mechanism_math_contract_v2")
            ),
        },
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
    }
    write_json(root / "step12_hypothesis_contract_smoke_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
