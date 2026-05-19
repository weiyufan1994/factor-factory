#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

from factor_factory.mechanism_math.main_agent_memo import (
    build_main_agent_mechanism_memo,
    formula_specific_derivation_from_main_agent_memo,
    render_main_agent_mechanism_memo_markdown,
)

CANONICAL_ROOTS = ["objects", "runs", "evaluations", "generated_code", "archive", "factorforge", "data/clean"]
RID = "MAIN_AGENT_MEMO_SIGN_VOLUME_SAMPLE_SMOKE"
SIGN_VOLUME_SAMPLE_FORMULA = (
    "plus(plus(negate(rank(plus(plus(sign(delta(close,1)), "
    "sign(delta(delay(close,1),1))), sign(delta(delay(close,2),1))))), 1), "
    "multiply(1, divide(sum(volume,5), sum(volume,20))))"
)
ALT_SIGN_VOLUME_FORMULA = (
    "plus(negate(rank(plus(sign(delta(open,2)), sign(delta(delay(open,3),2))))), "
    "divide(sum(volume,3), sum(volume,30)))"
)
OPEN_CLOSE_POSITION_FORMULA = "rank(negate(signedpower(minus(1, divide(open, close)), 1)))"


def is_tmp(path: Path) -> bool:
    raw = str(path)
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = raw
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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_cmd(args: list[str], root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["FACTORFORGE_ROOT"] = str(root)
    proc = subprocess.run(args, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {
        "command": args,
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def fixture(
    root: Path,
    report_id: str = RID,
    stale_dependence_contract: bool = False,
    formula_text: str = SIGN_VOLUME_SAMPLE_FORMULA,
    required_inputs: list[str] | None = None,
    operators: list[str] | None = None,
) -> dict[str, Path]:
    objects = root / "objects"
    spec = {
        "report_id": report_id,
        "factor_id": "SIGN_VOLUME_SAMPLE_FORMULA",
        "canonical_spec": {
            "formula_text": formula_text,
            "required_inputs": required_inputs or ["close", "volume"],
            "operators": operators or ["plus", "negate", "rank", "sign", "delta", "delay", "multiply", "divide", "sum"],
        },
    }
    case = {
        "report_id": report_id,
        "factor_id": "SIGN_VOLUME_SAMPLE_FORMULA",
        "final_status": "validated",
        "headline_metrics": {
            "rank_ic_mean": 0.012,
            "long_side_annual_return": -0.08,
            "cost_adjusted_annual_return": -0.16,
            "long_side_max_drawdown": -0.42,
            "long_side_turnover_mean_daily": 0.73,
            "group_g9_mean_return": 0.003,
            "group_g10_mean_return": -0.002,
        },
    }
    evaluation = {
        "report_id": report_id,
        "backend_summary": [
            {
                "backend": "self_quant_analyzer",
                "key_metrics": case["headline_metrics"],
            }
        ],
    }
    run = {"report_id": report_id, "factor_id": "SIGN_VOLUME_SAMPLE_FORMULA", "run_status": "completed", "artifact_identity": {"report_id": report_id, "factor_id": "SIGN_VOLUME_SAMPLE_FORMULA", "artifact_role": "factor_run_master"}}
    mechanism = {
        "mechanism_fit": "weak",
        "return_source": "behavioral_microstructure",
        "factor_family": "liquidity_shock",
        "mechanism_math_contract": {
            "model_family": "price_volume_microstructure",
            "math_model_status": "specified",
            "state_or_object": "short signed price pressure plus participation intensity",
            "factor_as_estimator": "formula estimates short signed price state and relative volume participation",
            "target_functional": "E[r_i,t+1 | F_t, formula_state_i,t]",
            "process_hypothesis": "P_i,t = F_i,t + I_i,t + epsilon_i,t with transient impact decay",
            "conditional_distribution_hypothesis": "r_i,t+1 | F_t, S_i,t, V_i,t",
            "relationship_shape": "threshold and monotonicity must be tested",
            "metric_signature_match": "high score long side must be positive after costs",
            "mechanism_falsification_tests": ["ablate signed price state", "ablate volume ratio state"],
        },
    }
    if stale_dependence_contract:
        mechanism["mechanism_math_contract"].update({
            "factor_as_estimator": "rank and rolling dependence transforms estimate price-volume co-movement as an observable microstructure state",
            "process_hypothesis": "Price-volume rank dependence estimates the current impact or crowded-attention state.",
            "conditional_distribution_hypothesis": "r_i,t+1 | F_t, C_i,t where C is the price-volume dependence estimator",
        })
    iteration = {
        "report_id": report_id,
        "factor_id": "SIGN_VOLUME_SAMPLE_FORMULA",
        "iteration_no": 1,
        "research_judgment": {
            "decision": "iterate",
            "research_memo": {
                "mechanism_analysis": mechanism,
                "revision_strategy": {"primary_failure_signature": "mechanism_unclear"},
            },
        },
        "loop_research_brief": {},
    }
    paths = {
        "spec": objects / "factor_spec_master" / f"factor_spec_master__{report_id}.json",
        "case": objects / "factor_case_master" / f"factor_case_master__{report_id}.json",
        "evaluation": objects / "validation" / f"factor_evaluation__{report_id}.json",
        "run": objects / "factor_run_master" / f"factor_run_master__{report_id}.json",
        "handoff": objects / "handoff" / f"handoff_to_step6__{report_id}.json",
        "iteration": objects / "research_iteration_master" / f"research_iteration_master__{report_id}.json",
        "memo": objects / "research_iteration_master" / f"main_agent_mechanism_memo__{report_id}.json",
        "memo_md": objects / "research_iteration_master" / f"main_agent_mechanism_memo__{report_id}.md",
    }
    for key, payload in [("spec", spec), ("case", case), ("evaluation", evaluation), ("run", run), ("handoff", {"report_id": report_id}), ("iteration", iteration)]:
        write_json(paths[key], payload)
    memo = build_main_agent_mechanism_memo(report_id=report_id, factor_spec=spec, factor_case=case, evaluation_summary=evaluation, step6_iteration=iteration)
    formula_terms = (
        f"the formula uses fields {', '.join(required_inputs or ['close', 'volume'])} "
        f"and operators {', '.join(operators or ['plus', 'negate', 'rank', 'sign', 'delta', 'delay', 'multiply', 'divide', 'sum'])}"
    )
    field_text = ', '.join(required_inputs or ['close', 'volume']).lower()
    operator_text = ', '.join(operators or ['plus', 'negate', 'rank', 'sign', 'delta', 'delay', 'multiply', 'divide', 'sum']).lower()
    if 'volume' in field_text and ('close' in field_text or 'open' in field_text or 'high' in field_text):
        selected_model_family = 'transient_impact'
        process_text = 'r_i,t+1 follows a transient impact and liquidity-pressure process with imbalance decay, inventory transfer, or participation-driven state migration depending on the formula-defined state and evidence'
    else:
        selected_model_family = 'stochastic_process'
        process_text = 'r_i,t+1 follows a conditional stochastic return process with drift, reversal, impact decay, or state migration depending on the formula-defined state and evidence'
    memo['producer'] = 'current_main_agent'
    memo['agent_authorship'] = {
        'authoring_mode': 'current_agent_freeform',
        'agent_role': 'main_agent',
        'runtime': 'codex_smoke',
        'answered_without_deterministic_template': True,
    }
    memo['mechanism_qa'] = {
        'formula_state_answer': (
            f"The current main agent reads {formula_terms}. The estimated state is the observable state produced by those actual fields and operators, "
            "with the formula structure determining the latent state instead of a fixed menu label."
        ),
        'economic_hypothesis_answer': (
            "The economic hypothesis is that a constrained or delayed counterparty trades against the formula-defined state, creating a next-horizon "
            "conditional payoff through belief adjustment, liquidity demand, risk transfer, or state migration."
        ),
        'math_model_answer': (
            "The mathematical model is a conditional stochastic return process whose latent state is mutated by the exact formula components; the model "
            "must explain state dynamics, payoff sign, horizon, and falsification rather than select a canned factor-family thesis."
        ),
        'payer_answer': (
            "Likely payers are delayed updaters, liquidity demanders, risk-transfer accounts, or extrapolators whose constraints make them trade at prices "
            "that later drift, reverse, decay, or migrate conditional on the formula state."
        ),
        'payoff_answer': (
            "The payoff argument is E[r_i,t+1 | F_t, formula_state_i,t], with sign determined by the stated state direction and only accepted if long-side "
            "and cost-adjusted evidence support that direction."
        ),
        'estimator_mapping_answer': (
            f"Estimator mapping follows {formula_terms}: each component contributes an observable piece of the latent state, rank terms test ordering, "
            "arithmetic terms define direction or scale, and all inputs remain in the legal information set."
        ),
        'metric_signature_answer': (
            "The hypothesis requires aligned rank IC, positive high-score long-side return, positive cost-adjusted return, monotonic top groups, and turnover "
            "low enough that trading costs do not consume the payoff."
        ),
        'falsification_answer': (
            "Falsify if long-side cost-adjusted return is negative, if adjacent top groups invert against the claimed direction, if ablations show the formula "
            "component is not driving IC, or if no concrete payer remains."
        ),
    }
    memo['economic_hypothesis'] = {
        'return_source_class': 'mixed',
        'payer_or_counterparty': 'delayed updaters, liquidity demanders, risk-transfer accounts, or extrapolators tied to the formula-defined state',
        'why_they_pay': 'their belief adjustment, immediacy demand, or risk-transfer constraint creates conditional drift, reversal, impact decay, or state migration',
        'necessary_market_structure': 'the state must predict next-horizon returns strongly enough to survive turnover and implementation costs',
    }
    memo['math_hypothesis'] = {
        'selected_model_family': selected_model_family,
        'why_this_model': 'the formula output is modeled as a state variable in a conditional return process',
        'why_not_generic_template': 'the current agent supplied freeform answers linking formula components to payer behavior, payoff, estimator mapping, and falsification',
        'random_object': 'security-day forward return conditional on legal information set F_t and formula-defined state',
        'latent_state': 'formula-defined conditional return state from the actual fields and operators',
        'process_or_distribution': process_text,
        'target_functional': 'E[r_i,t+1 | F_t, formula_state_i,t]',
        'formula_as_estimator': memo['mechanism_qa']['estimator_mapping_answer'],
        'expected_metric_signature': {
            'rank_ic': 'rank IC sign must match the declared payoff direction',
            'long_side': 'high-score long side must be positive if the state is monetizable',
            'cost_adjusted': 'cost-adjusted return must remain positive after turnover and impact',
            'monotonicity': 'quantile ordering must match the stated direction',
            'turnover': 'turnover must not consume the expected payoff',
        },
    }
    write_json(paths["memo"], memo)
    paths["memo_md"].parent.mkdir(parents=True, exist_ok=True)
    paths["memo_md"].write_text(render_main_agent_mechanism_memo_markdown(memo), encoding="utf-8")
    return paths


def mutate_and_validate(root: Path, paths: dict[str, Path], case: str, mutate, expected_token: str | None = None) -> dict[str, Any]:
    memo = load_json(paths["memo"])
    mutate(memo)
    write_json(paths["memo"], memo)
    result = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py", "--report-id", RID], root)
    output = result["stdout_tail"] + result["stderr_tail"]
    return {
        "case": case,
        "ok": result["rc"] == 1 and (not expected_token or expected_token in output),
        "expected_token": expected_token,
        "token_present": (expected_token in output) if expected_token else None,
        "command": result,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/tmp/factorforge_main_agent_mechanism_memo_phase_o2")
    ap.add_argument("--fresh", action="store_true")
    args = ap.parse_args()
    root = Path(args.root)
    if not is_tmp(root):
        print("BLOCK_NON_TMP_FACTORFORGE_ROOT: " + str(root), file=sys.stderr)
        raise SystemExit(1)
    before = file_snapshot()
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    paths = fixture(root)
    validate = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py", "--report-id", RID], root)
    memo = load_json(paths["memo"])
    cases.append({
        "case": "sign_volume_formula_sample_main_agent_memo_pass",
        "ok": validate["rc"] == 0
        and {c.get("component_id") for c in memo.get("formula_component_map") or []} >= {"signed_price_state", "relative_volume_participation", "additive_score_combination"}
        and memo.get("evidence_comparison", {}).get("mechanism_supported") in {"no", "partial"},
        "command": validate,
    })

    paths = fixture(root, stale_dependence_contract=True)
    stale_validate = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py", "--report-id", RID], root)
    stale_memo = load_json(paths["memo"])
    stale_text = json.dumps(
        {
            "math_hypothesis": stale_memo.get("math_hypothesis"),
            "formula_component_map": stale_memo.get("formula_component_map"),
        },
        ensure_ascii=False,
    ).lower()
    cases.append({
        "case": "sign_volume_formula_ignores_stale_dependence_contract_text",
        "ok": stale_validate["rc"] == 0
        and "rolling dependence" not in stale_text
        and "covariance" not in stale_text
        and "correlation" not in stale_text
        and "co-movement" not in stale_text
        and "price-volume dependence estimator" not in stale_text,
        "command": stale_validate,
    })

    alt_paths = fixture(root, report_id=RID, formula_text=ALT_SIGN_VOLUME_FORMULA, required_inputs=["open", "volume"])
    alt_validate = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py", "--report-id", RID], root)
    alt_memo = load_json(alt_paths["memo"])
    alt_text = json.dumps(
        {
            "math_hypothesis": alt_memo.get("math_hypothesis"),
            "formula_component_map": alt_memo.get("formula_component_map"),
        },
        ensure_ascii=False,
    ).lower()
    cases.append({
        "case": "sign_volume_formula_uses_universal_rule_not_fixed_windows",
        "ok": alt_validate["rc"] == 0
        and "fields open" in alt_text
        and "operators" in alt_text
        and "sum(volume,5)" not in alt_text
        and "sum(volume,20)" not in alt_text
        and "sum(volume,3)" not in alt_text
        and "sum(volume,30)" not in alt_text,
        "command": alt_validate,
    })

    open_close_paths = fixture(
        root,
        report_id=RID,
        formula_text=OPEN_CLOSE_POSITION_FORMULA,
        required_inputs=["open", "close"],
        operators=["rank", "negate", "signedpower", "minus", "divide"],
    )
    open_close_validate = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py", "--report-id", RID], root)
    open_close_memo = load_json(open_close_paths["memo"])
    open_close_text = json.dumps(
        {
            "math_hypothesis": open_close_memo.get("math_hypothesis"),
            "formula_component_map": open_close_memo.get("formula_component_map"),
            "economic_hypothesis": open_close_memo.get("economic_hypothesis"),
        },
        ensure_ascii=False,
    ).lower()
    cases.append({
        "case": "open_close_formula_uses_intraday_position_rule",
        "ok": open_close_validate["rc"] == 0
        and "open/close" in open_close_text
        and "price-location" in open_close_text
        and "volume participation" not in open_close_text
        and "signed price state" not in open_close_text
        and "liquidity or turnover shock" not in open_close_text,
        "command": open_close_validate,
    })

    paths = fixture(root)
    model_alias_memo = load_json(paths["memo"])
    model_alias_memo.setdefault("math_hypothesis", {})["selected_model_family"] = "price_volume_microstructure"
    write_json(paths["memo"], model_alias_memo)
    model_alias_validate = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/validate_main_agent_mechanism_memo.py", "--report-id", RID], root)
    model_alias_derivation = formula_specific_derivation_from_main_agent_memo(model_alias_memo)
    cases.append({
        "case": "common_mechanism_family_normalized_for_derivation",
        "ok": model_alias_validate["rc"] == 0
        and (model_alias_derivation.get("economic_to_math_model_selection") or {}).get("baseline_model_family") == "transient_impact"
        and model_alias_derivation.get("selected_model_family") == "transient_impact",
        "command": model_alias_validate,
        "baseline_model_family": (model_alias_derivation.get("economic_to_math_model_selection") or {}).get("baseline_model_family"),
    })

    fixture(root)
    cases.append(mutate_and_validate(
        root,
        paths,
        "invalid_derivation_model_family_blocks_early",
        lambda m: m.setdefault("math_hypothesis", {}).update({"selected_model_family": "unsupported_template_family"}),
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MODEL_FAMILY_INVALID",
    ))

    paths = fixture(root)
    cases.append(mutate_and_validate(root, paths, "generic_memo_blocks", lambda m: m.setdefault("math_hypothesis", {}).update({"process_or_distribution": "rank delta sign sum divide close volume"})))
    fixture(root)
    cases.append(mutate_and_validate(root, paths, "correlation_claim_without_operator_blocks", lambda m: m.setdefault("operator_claim_consistency", {}).update({"claims_correlation_or_covariance": True, "formula_has_correlation_or_covariance_operator": False, "explicit_dependence_justification": None})))
    fixture(root)
    def text_claim_mutation(m: dict[str, Any]) -> None:
        m.setdefault("math_hypothesis", {})["formula_as_estimator"] = (
            "This is a rolling rank covariance and correlation dependence estimator between price and volume ranks."
        )
        m.setdefault("operator_claim_consistency", {}).update({
            "claims_correlation_or_covariance": False,
            "claims_dependence_without_operator_justification": False,
            "formula_has_correlation_or_covariance_operator": False,
            "explicit_dependence_justification": None,
        })

    cases.append(mutate_and_validate(
        root,
        paths,
        "operator_claim_text_contradiction_blocks",
        text_claim_mutation,
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_OPERATOR_CLAIM_CONTRADICTION",
    ))
    fixture(root)
    def text_claim_with_generated_justification_mutation(m: dict[str, Any]) -> None:
        m.setdefault("math_hypothesis", {})["formula_as_estimator"] = (
            "This is a rolling rank covariance and correlation dependence estimator between price and volume ranks."
        )
        m.setdefault("operator_claim_consistency", {}).update({
            "claims_correlation_or_covariance": False,
            "claims_dependence_without_operator_justification": False,
            "formula_has_correlation_or_covariance_operator": False,
        })

    cases.append(mutate_and_validate(
        root,
        paths,
        "operator_claim_text_with_generated_justification_blocks",
        text_claim_with_generated_justification_mutation,
        "BLOCK_MAIN_AGENT_MECHANISM_MEMO_OPERATOR_CLAIM_CONTRADICTION",
    ))
    fixture(root)
    cases.append(mutate_and_validate(root, paths, "sign_without_threshold_turnover_discussion_blocks", lambda m: m.setdefault("operator_claim_consistency", {}).update({"has_sign_or_threshold": True, "sign_threshold_discussion_present": False})))
    fixture(root)
    cases.append(mutate_and_validate(root, paths, "volume_ratio_without_participation_discussion_blocks", lambda m: m.setdefault("operator_claim_consistency", {}).update({"has_volume_ratio": True, "volume_ratio_participation_discussion_present": False})))
    fixture(root)
    cases.append(mutate_and_validate(root, paths, "additive_rank_raw_ratio_without_commensurability_discussion_blocks", lambda m: m.setdefault("operator_claim_consistency", {}).update({"has_additive_rank_raw_ratio": True, "additive_scale_commensurability_discussion_present": False})))
    fixture(root)
    cases.append(mutate_and_validate(root, paths, "canonical_write_permission_blocks", lambda m: m.update({"canonical_write_permission": True})))
    fixture(root)
    cases.append(mutate_and_validate(root, paths, "execution_allowed_by_default_blocks", lambda m: m.update({"execution_allowed_by_default": True})))

    paths = fixture(root)
    paths["memo"].unlink()
    packet_missing = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", RID], root)
    cases.append({
        "case": "memo_missing_blocks_before_council_packet",
        "ok": packet_missing["rc"] == 1 and "BLOCK_MAIN_AGENT_MECHANISM_MEMO_MISSING" in (packet_missing["stderr_tail"] + packet_missing["stdout_tail"]),
        "command": packet_missing,
    })

    paths = fixture(root)
    packet = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/build_revision_council_packet.py", "--report-id", RID], root)
    packet_path = root / "objects" / "research_iteration_master" / "revision_council" / RID / f"revision_council_packet__{RID}.json"
    packet_payload = load_json(packet_path) if packet_path.exists() else {}
    cases.append({
        "case": "council_packet_requires_memo_ref",
        "ok": packet["rc"] == 0
        and bool(packet_payload.get("main_agent_mechanism_memo_ref"))
        and bool(packet_payload.get("main_agent_formula_component_map"))
        and bool(packet_payload.get("council_required_critiques")),
        "command": packet,
    })

    taskbook = run_cmd([sys.executable, "skills/factor-forge-step6/scripts/build_agentic_council_taskbook.py", "--report-id", RID, "--executor", "dispatch_manifest"], root)
    taskbook_path = root / "objects" / "research_iteration_master" / "revision_council" / RID / f"agentic_taskbook__{RID}.json"
    taskbook_payload = load_json(taskbook_path) if taskbook_path.exists() else {}
    tasks = taskbook_payload.get("agent_tasks") or []
    cases.append({
        "case": "taskbook_requires_memo_critique",
        "ok": taskbook["rc"] == 0
        and tasks
        and all(task.get("main_agent_mechanism_memo_ref") for task in tasks)
        and all("main_agent_memo_agreement" in (task.get("required_outputs") or []) for task in tasks)
        and "main_agent_mechanism_memo_ref" in (taskbook_payload.get("shared_context") or {}),
        "command": taskbook,
    })

    non_tmp = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).relative_to(REPO_ROOT)),
            "--fresh",
            "--root",
            "/Users/humphrey/tmp_factorforge_bad",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    cases.append({
        "case": "non_tmp_root_blocks",
        "ok": non_tmp.returncode == 1 and "BLOCK_NON_TMP_FACTORFORGE_ROOT" in (non_tmp.stdout + non_tmp.stderr),
        "command": {
            "rc": non_tmp.returncode,
            "stdout_tail": non_tmp.stdout[-2000:],
            "stderr_tail": non_tmp.stderr[-2000:],
        },
    })

    after = file_snapshot()
    pollution = sorted(after - before)
    cases.append({"case": "canonical_pollution_false", "ok": not pollution, "new_files": pollution})

    summary = {
        "verdict": "ACCEPT" if all(case.get("ok") for case in cases) else "BLOCK",
        "root_policy": {"factorforge_root": str(root), "is_tmp": is_tmp(root), "enforced": True},
        "cases": cases,
        "canonical_pollution": {"polluted": bool(pollution), "new_files": pollution},
    }
    summary_path = root / "main_agent_mechanism_memo_smoke_summary.json"
    write_json(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[SUMMARY] {summary_path}")
    if summary["verdict"] != "ACCEPT":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
