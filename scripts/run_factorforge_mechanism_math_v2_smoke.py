#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.mechanism_math.classifier import build_mechanism_math_contract, build_mechanism_math_contract_v2
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract
from factor_factory.revision_council.validator import validate_revision_council_proposal


def load_module(name: str, path: Path):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STEP2 = load_module("rta18_step2", REPO_ROOT / "skills/factor-forge-step2/scripts/run_step2.py")
STEP6_VALIDATE = load_module("rta18_validate_step6", REPO_ROOT / "skills/factor-forge-step6/scripts/validate_step6.py")
RUN_COUNCIL = load_module("rta18_run_revision_council", REPO_ROOT / "skills/factor-forge-step6/scripts/run_revision_council.py")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cmd(cmd: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    env["FACTORFORGE_ALLOW_DIRECT_STEP"] = "1"
    env["FACTORFORGE_DEBUG_ROOT"] = str(root)
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def valid_spec() -> dict[str, Any]:
    return {
        "report_id": "RTA18_VALID",
        "factor_id": "RTA18_VALID",
        "source_type": "paper_canonical_formula",
        "canonical_spec": {
            "formula_text": "rank(delta(close, 5))",
            "required_inputs": ["close"],
            "operators": ["rank()", "delta()"],
        },
        "research_contract": {
            "economic_mechanism": "delayed information diffusion creates continuation and reversal states in observed prices",
            "economic_hypothesis": {
                "hypothesis_version": "factorforge_step1_economic_hypothesis_v1",
                "macro_return_source": "information_advantage",
                "second_layer": {
                    "subtype": "slow_information_diffusion",
                    "expected_counterparty_or_payer": "slow information processors",
                    "why_they_may_pay": "they update beliefs later than the signal observer",
                },
                "counterparty_loss_hypothesis": "slow information processors",
            },
            "math_hypothesis_candidates": [
                {
                    "hypothesis_id": "math_delayed_belief_update",
                    "linked_economic_hypothesis": "information_advantage:slow_information_diffusion",
                    "model_family": "stochastic_process",
                    "math_tools": ["probability_theory", "statistics"],
                    "state_or_object": "latent drift continuation state",
                    "process_or_distribution_hypothesis": "returns have state-dependent drift under F_t",
                    "observable_estimator": "ranked lagged close delta",
                    "target_functional": "E[r_{t+1} | F_t, drift_state_t]",
                    "why_suitable": "the formula estimates a lag-safe price-process state",
                    "falsification_tests": ["rank IC sign fails", "long side return is non-positive"],
                }
            ],
        },
    }


def valid_v2_contract() -> dict[str, Any]:
    return build_mechanism_math_contract_v2(valid_spec())


def case_contract_validation() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    valid = valid_v2_contract()
    cases.append({"case": "valid_v2_contract_pass", "ok": not validate_mechanism_math_contract(valid), "failures": validate_mechanism_math_contract(valid)})

    mutated = json.loads(json.dumps(valid))
    mutated["primary_mechanism_model"]["selected_model_family"] = ""
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "missing_primary_model_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_MISSING_PRIMARY_MODEL" for f in failures), "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["stochastic_price_process_projection"]["affected_price_process_terms"] = []
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "empty_stochastic_projection_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_EMPTY_STOCHASTIC_PROJECTION" for f in failures), "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["formula_component_mapping"] = []
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "formula_mapping_missing_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_MISSING" for f in failures), "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["primary_mechanism_model"]["state_variables"] = []
    mutated["primary_mechanism_model"]["observable_proxies"] = []
    mutated["stochastic_price_process_projection"]["price_process_form"] = "Generic stochastic process: dS = mu S dt + sigma S dW."
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "vague_sde_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_VAGUE_SDE" for f in failures), "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["stochastic_price_process_projection"]["price_process_form"] = "Decorative generic SDE: dS = mu S dt + sigma S dW."
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "decorative_sde_with_filled_chain_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_VAGUE_SDE" for f in failures), "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["formula_component_mapping"][0]["formula_component"] = "rank(close)"
    mutated["formula_component_mapping"][0]["observable_proxy_for"] = "rank(close)"
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "formula_mapping_self_reference_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_SELF_REFERENTIAL" for f in failures), "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["formula_component_mapping"][0]["formula_component"] = "分钟收盘价"
    mutated["formula_component_mapping"][0]["observable_proxy_for"] = "orthogonalized residual signal state"
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "formula_mapping_non_ascii_component_to_state_passes", "ok": not failures, "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["formula_component_mapping"][0]["formula_component"] = "分钟收盘价"
    mutated["formula_component_mapping"][0]["observable_proxy_for"] = "latent mean-reversion state (inventory pressure)"
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "formula_mapping_parenthetical_mechanism_state_passes", "ok": not failures, "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["formula_component_mapping"][0]["formula_component"] = "分钟成交量"
    mutated["formula_component_mapping"][0]["observable_proxy_for"] = "ranked liquidity state (institutional flow imbalance)"
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "formula_mapping_ranked_language_state_passes", "ok": not failures, "failures": failures})

    mutated = json.loads(json.dumps(valid))
    mutated["formula_component_mapping"][0]["formula_component"] = "分钟收盘价"
    mutated["formula_component_mapping"][0]["observable_proxy_for"] = "mean(close, 5)"
    failures = validate_mechanism_math_contract(mutated)
    cases.append({"case": "formula_mapping_function_call_proxy_blocks", "ok": any(f["code"] == "BLOCK_MECHANISM_MATH_V2_FORMULA_MAPPING_SELF_REFERENTIAL" for f in failures), "failures": failures})

    legacy = build_mechanism_math_contract(valid_spec())
    cases.append({"case": "legacy_v1_still_accepted", "ok": not validate_mechanism_math_contract(legacy), "failures": validate_mechanism_math_contract(legacy)})
    return cases


def alpha_idea_master(report_id: str) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "factor_id": report_id,
        "source_type": "paper_canonical_formula",
        "producer": "step12_canonical_formula_intake",
        "raw_formula": "rank(delta(close, 5))",
        "final_factor": {"name": report_id, "assembly_steps": ["rank(delta(close, 5))"]},
        "research_discipline": {
            "step1_random_object": "A-share price-return panel",
            "target_statistic_hint": "cross-sectional rank statistic for future returns",
            "information_set_hint": "requires_researcher_confirmation_no_forward_leakage",
            "initial_return_source_hypothesis": "information_advantage",
            "economic_hypothesis": valid_spec()["research_contract"]["economic_hypothesis"],
            "math_hypothesis_candidates": valid_spec()["research_contract"]["math_hypothesis_candidates"],
            "market_process_thesis": valid_v2_contract()["market_process_thesis"],
            "primary_mechanism_model_candidates": [
                {
                    "candidate_id": "candidate_stochastic_process",
                    "rank": 1,
                    "selected_model_family": "stochastic_process",
                    "why_this_model_fits": "The formula estimates a lagged drift state.",
                    "why_alternatives_are_less_suitable": ["No explicit volume or accounting estimator is present."],
                    "state_variables": ["latent drift continuation state"],
                    "observable_proxies": ["lagged close delta rank"],
                    "target_functional": "E[r_{t+1} | F_t, drift_state_t]",
                    "preferred": True,
                }
            ],
            "stochastic_price_process_projection": valid_v2_contract()["stochastic_price_process_projection"],
            "similar_case_lessons_imported": ["cold-start prior"],
            "what_must_be_true": ["ranked close delta estimates the conditional drift state"],
            "what_would_break_it": ["rank IC and long-side return contradict the projection"],
        },
        "math_discipline_review": {
            "step1_random_object": "A-share price-return panel",
            "target_statistic": "cross-sectional rank statistic for future returns",
            "information_set_legality": "requires_researcher_confirmation_no_forward_leakage",
        },
        "learning_and_innovation": {"similar_case_lessons_imported": ["cold-start prior"]},
    }


def case_step1_step2(root: Path) -> list[dict[str, Any]]:
    report_id = "RTA18_STEP2_WRITES_V2"
    aim = alpha_idea_master(report_id)
    write_json(root / "objects/alpha_idea_master" / f"alpha_idea_master__{report_id}.json", aim)
    step1_proc = run_cmd([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", report_id], root=root)

    primary = STEP2.build_primary_spec_from_canonical_formula(report_id, aim, {"raw_formula_text": aim["raw_formula"]}, {})
    consistency = STEP2.score_consistency(primary, primary, aim)
    master = STEP2.build_factor_spec_master(report_id, aim, primary, consistency, {"raw_formula_text": aim["raw_formula"]})
    master_path = root / "objects/factor_spec_master" / f"factor_spec_master__{report_id}.json"
    handoff = {
        "contract_version": "factorforge_step2_source_contract_v2",
        "report_id": report_id,
        "source_type": master["source_type"],
        "implementation_mode": master["implementation_mode"],
        "artifact_identity": {**master["artifact_identity"], "artifact_role": "handoff_to_step3"},
        "spec_hash": master["spec_hash"],
        "producer": master["producer"],
        "upstream_producer": master["upstream_producer"],
        "step2_status": "factor_spec_master_ready",
        "factor_spec_master_ref": master_path.name,
        "research_contract": master["research_contract"],
        "math_discipline_review": master["math_discipline_review"],
        "mechanism_math_contract": master["mechanism_math_contract"],
        "mechanism_math_contract_v2": master["mechanism_math_contract_v2"],
        "learning_and_innovation": master["learning_and_innovation"],
    }
    write_json(master_path, master)
    write_json(root / "objects/handoff" / f"handoff_to_step3__{report_id}.json", handoff)
    step2_proc = run_cmd([sys.executable, "skills/factor-forge-step2/scripts/validate_step2.py", "--report-id", report_id], root=root)
    v2 = master.get("mechanism_math_contract_v2")
    placeholder_report_id = "RTA18_STEP1_PLACEHOLDER_V2"
    placeholder = alpha_idea_master(placeholder_report_id)
    discipline = placeholder["research_discipline"]
    discipline["market_process_thesis"] = {
        "market_phenomenon": "under_specified",
        "economic_hypothesis": "under_specified",
        "return_source_family": "mixed",
        "payer_or_counterparty": "under_specified",
        "why_they_pay": "under_specified",
        "what_must_be_true": ["under_specified"],
        "what_would_break_it": ["under_specified"],
    }
    discipline["primary_mechanism_model_candidates"] = [
        {
            "candidate_id": "placeholder",
            "rank": 1,
            "selected_model_family": "under_specified",
            "why_this_model_fits": "under_specified",
            "why_alternatives_are_less_suitable": ["under_specified"],
            "state_variables": ["under_specified"],
            "observable_proxies": ["under_specified"],
            "preferred": True,
        }
    ]
    discipline["stochastic_price_process_projection"] = {
        "projection_required": True,
        "price_process_form": "under_specified",
        "affected_price_process_terms": ["drift"],
        "conditional_distribution_claim": "under_specified",
        "formula_should_estimate": "under_specified",
        "expected_return_distribution_change": "under_specified",
    }
    write_json(root / "objects/alpha_idea_master" / f"alpha_idea_master__{placeholder_report_id}.json", placeholder)
    placeholder_proc = run_cmd([sys.executable, "skills/factor-forge-step1/scripts/validate_step1.py", "--report-id", placeholder_report_id], root=root)
    return [
        {
            "case": "validate_step1_accepts_v2_fields",
            "ok": step1_proc.returncode == 0,
            "rc": step1_proc.returncode,
            "stdout_tail": step1_proc.stdout[-1000:],
            "stderr_tail": step1_proc.stderr[-1000:],
        },
        {
            "case": "step2_writes_v2_contract_three_places",
            "ok": (
                isinstance(v2, dict)
                and v2 == master.get("canonical_spec", {}).get("mechanism_math_contract_v2")
                and v2 == handoff.get("mechanism_math_contract_v2")
                and step2_proc.returncode == 0
            ),
            "rc": step2_proc.returncode,
            "stdout_tail": step2_proc.stdout[-1000:],
            "stderr_tail": step2_proc.stderr[-1000:],
        },
        {
            "case": "step1_placeholder_v2_fields_block",
            "ok": placeholder_proc.returncode != 0,
            "rc": placeholder_proc.returncode,
            "stdout_tail": placeholder_proc.stdout[-1000:],
            "stderr_tail": placeholder_proc.stderr[-1000:],
        },
    ]


def case_step6_and_council() -> list[dict[str, Any]]:
    valid_mechanism = {
        "mechanism_projection_diagnosis": {
            "economic_hypothesis": "supported",
            "primary_mechanism_model": "supported",
            "stochastic_projection": "supported",
            "observable_estimator": "supported",
            "implementation_contract": "validated",
        },
        "metric_signature_match": {
            "economic_hypothesis": "partial",
            "primary_mechanism_model": "partial",
            "stochastic_projection": "supportive",
            "observable_estimator": "supportive",
            "implementation_contract": "validated",
        },
        "model_layer_failure_attribution": ["observable_estimator"],
        "revision_model_target": "observable_estimator",
    }
    valid_revision = {"revision_hypotheses": [{"revision_model_layer": "observable_estimator"}]}
    bad_mechanism = dict(valid_mechanism)
    bad_mechanism.pop("mechanism_projection_diagnosis")
    step6_failures = STEP6_VALIDATE.validate_step6_model_linkage(bad_mechanism, valid_revision)
    missing_metric_implementation = json.loads(json.dumps(valid_mechanism))
    missing_metric_implementation["metric_signature_match"].pop("implementation_contract", None)
    metric_implementation_failures = STEP6_VALIDATE.validate_step6_model_linkage(
        missing_metric_implementation,
        valid_revision,
    )
    placeholder_mechanism = {
        "mechanism_projection_diagnosis": {
            "economic_hypothesis": "under_specified",
            "primary_mechanism_model": "under_specified",
            "stochastic_projection": "under_specified",
            "observable_estimator": "under_specified",
            "implementation_contract": "under_specified",
        },
        "metric_signature_match": {
            "economic_hypothesis": "under_specified",
            "primary_mechanism_model": "under_specified",
            "stochastic_projection": "under_specified",
            "observable_estimator": "under_specified",
            "implementation_contract": "under_specified",
        },
        "model_layer_failure_attribution": ["observable_estimator"],
        "revision_model_target": "observable_estimator",
    }
    placeholder_step6_failures = STEP6_VALIDATE.validate_step6_model_linkage(placeholder_mechanism, valid_revision)

    packet = {
        "report_id": "RTA18_COUNCIL",
        "factor_formula": "rank(delta(close, 5))",
        "mechanism_math_contract": valid_v2_contract().get("source_mechanism_math_contract_v1", {}),
        "research_memo": {
            "revision_strategy": {"primary_failure_signature": "mechanism_unclear"},
            "mechanism_analysis": {"return_source": "mixed", "factor_family": "reversal", "mechanism_fit": "weak"},
        },
    }
    proposal = RUN_COUNCIL.symbolic_law(packet)
    proposal["derivation_record"] = RUN_COUNCIL.build_derivation_record(packet, proposal)
    valid_reasons = validate_revision_council_proposal(proposal)
    bad_proposal = json.loads(json.dumps(proposal))
    bad_proposal.pop("revision_model_layer", None)
    for law in bad_proposal.get("candidate_revision_laws") or []:
        law.pop("revision_model_layer", None)
    for item in (bad_proposal.get("derivation_record") or {}).get("revision_hypotheses") or []:
        item.pop("revision_model_layer", None)
    bad_reasons = validate_revision_council_proposal(bad_proposal)
    return [
        {
            "case": "step6_revision_without_model_layer_attribution_blocks",
            "ok": "BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL" in step6_failures,
            "failures": step6_failures,
        },
        {
            "case": "step6_placeholder_model_linkage_blocks",
            "ok": "BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL" in placeholder_step6_failures,
            "failures": placeholder_step6_failures,
        },
        {
            "case": "step6_metric_signature_missing_implementation_contract_blocks",
            "ok": "BLOCK_STEP6_METRICS_NOT_LINKED_TO_MODEL" in metric_implementation_failures,
            "failures": metric_implementation_failures,
        },
        {
            "case": "valid_council_proposal_with_model_layer_passes",
            "ok": not valid_reasons,
            "failures": valid_reasons,
        },
        {
            "case": "council_proposal_without_model_layer_mapping_blocks",
            "ok": "BLOCK_COUNCIL_REVISION_MODEL_LAYER_MISSING" in bad_reasons,
            "failures": bad_reasons,
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/tmp/factorforge_mechanism_math_v2_smoke")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not (str(root).startswith("/tmp/") or str(root).startswith("/private/tmp/")):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT")
        raise SystemExit(1)
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    cases.extend(case_contract_validation())
    cases.extend(case_step1_step2(root))
    cases.extend(case_step6_and_council())

    canonical_pollution = False
    verdict = "ACCEPT" if all(case.get("ok") for case in cases) and not canonical_pollution else "BLOCK"
    summary = {
        "summary_version": "factorforge_mechanism_math_v2_smoke_v1",
        "verdict": verdict,
        "canonical_pollution": canonical_pollution,
        "cases": cases,
    }
    out = root / "mechanism_math_v2_smoke_summary.json"
    write_json(out, summary)
    print(json.dumps({"verdict": verdict, "canonical_pollution": canonical_pollution, "summary_path": str(out)}, ensure_ascii=False, indent=2))
    if verdict != "ACCEPT":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
