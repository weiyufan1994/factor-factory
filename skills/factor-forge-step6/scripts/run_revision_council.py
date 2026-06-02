#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path("/home/ubuntu/.openclaw/workspace")
FF = Path(os.getenv("FACTORFORGE_ROOT") or (LEGACY_WORKSPACE / "factorforge" if (LEGACY_WORKSPACE / "factorforge").exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.revision_council.schema import COUNCIL_AGENT_ROLES, COUNCIL_PROPOSAL_VERSION, REQUIRED_GUARDS
from factor_factory.revision_council.validator import validate_revision_council_proposal

OBJ = FF / "objects"
TOKEN_MISSING = "BLOCK_REVISION_COUNCIL_PACKET_MISSING_INPUT"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def nested(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, dict) else {}


def base_proposal(packet: dict[str, Any], role: str) -> dict[str, Any]:
    revision = nested(packet, "research_memo", "revision_strategy")
    mechanism = nested(packet, "research_memo", "mechanism_analysis")
    failure = revision.get("primary_failure_signature") or "none"
    return {
        "contract_version": COUNCIL_PROPOSAL_VERSION,
        "report_id": packet.get("report_id"),
        "agent_role": role,
        "proposal_id": role + "_001",
        "proposal_status": "proposed",
        "producer": "deterministic_scaffold",
        "research_depth": "low",
        "proposal_generation_mode": "deterministic_scaffold",
        "revision_type": "no_action",
        "revision_model_layer": "primary_mechanism_model",
        "target_failure_signature": failure,
        "selected_math_tools": [],
        "market_phenomenon": "Assess the factor expression as a research hypothesis using verified Step4/5/6 evidence.",
        "symbolic_model": {
            "state_or_object": (packet.get("mechanism_math_contract") or {}).get("state_or_object") or mechanism.get("factor_family") or "unknown state",
            "state_process": "",
            "latent_state": "",
            "target_functional": (packet.get("mechanism_math_contract") or {}).get("target_functional") or "E[next return | current information set]",
        },
        "structural_findings": [],
        "candidate_revision_laws": [],
        "return_source_hypothesis": mechanism.get("return_source") if mechanism.get("return_source") in {"risk_premium", "information_advantage", "constraint_driven_arbitrage", "mixed", "unknown"} else "unknown",
        "expression_change": "",
        "research_equation_revision": {
            "equation_component_target": "observable_estimator",
            "equation_change": "Test whether the observable estimator or expression-level state better maps to the research equation.",
            "expected_metric_signature_change": [
                "long-side cost-adjusted return should improve if the research equation component is repaired",
                "rank IC and turnover should remain consistent with the revised estimator horizon",
            ],
            "falsification_tests": [
                "Reject if the revised equation component does not improve long-side cost-adjusted metrics.",
                "Reject if improvement appears only in diagnostic spread metrics.",
            ],
        },
        "why_not_portfolio_fix": "The council is proposal-only and can only suggest expression-level or audit hypotheses; execution-wrapper changes, side-selection rescue, bucket-trading rescue, and shared-dataset mutation are forbidden.",
        "forbidden_changes_ack": list(REQUIRED_GUARDS),
        "confidence": "low",
        "risk_notes": "Proposal is not evidence and cannot promote or modify canonical artifacts.",
        "derivation_record": {},
    }


def law(statement: str, direction: str) -> dict[str, Any]:
    return {
        "law_statement": statement,
        "formula_direction": direction,
        "revision_model_layer": "observable_estimator",
        "expected_metric_change": [
            "cost-adjusted long-side return should improve if the mathematical state is persistent",
            "turnover or estimator variance should fall without losing all gross signal",
        ],
        "falsification_tests": [
            "Reject if long-side return disappears after the expression-level change.",
            "Reject if cost-adjusted Sharpe remains negative after turnover falls.",
        ],
        "kill_criteria": [
            "Kill if high-score long side remains non-positive.",
            "Kill if improvement only appears in diagnostic spread metrics rather than the high-score long side.",
        ],
    }


def build_derivation_record(packet: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    formula = str(packet.get("factor_formula") or "").strip()
    selected_math_tools = list(proposal.get("selected_math_tools") or [])
    selected_tools = selected_math_tools or ["robust_statistics"]
    symbolic_model = proposal.get("symbolic_model") or {}
    laws = proposal.get("candidate_revision_laws") or []
    first_law = laws[0] if laws and isinstance(laws[0], dict) else {}
    formula_statement = (
        "Map the observed formula structure to an advisory state-estimator hypothesis."
        if formula
        else "Map the available signal structure to an advisory state-estimator hypothesis."
    )
    formula_text = formula if formula else ""
    mathematical_objects = [
        {
            "name": "factor_value",
            "meaning": "Current factor signal produced by Step3B evidence lineage.",
            "unit_or_dimension": "dimensionless_or_unknown",
            "information_set": "available at factor timestamp",
        },
        {
            "name": str(symbolic_model.get("state_or_object") or "candidate_state"),
            "meaning": "Candidate economic or mathematical state represented by the factor expression.",
            "unit_or_dimension": "latent_or_dimensionless",
            "information_set": "current and historical observations only",
        },
    ]
    if "rank(high)" in formula.lower():
        mathematical_objects.append({
            "name": "rank(high)",
            "meaning": "Cross-sectional high-price position after rank transform.",
            "unit_or_dimension": "dimensionless_rank",
            "information_set": "current and historical high prices",
        })
    if "rank(volume)" in formula.lower() or "rank(vol)" in formula.lower():
        mathematical_objects.append({
            "name": "rank(volume)",
            "meaning": "Cross-sectional volume position after rank transform.",
            "unit_or_dimension": "dimensionless_rank",
            "information_set": "current and historical volume observations",
        })
    if "correlation" in formula.lower() or "corr" in formula.lower():
        mathematical_objects.append({
            "name": "rolling_rank_dependence",
            "meaning": "Rolling dependence estimator between transformed price and activity variables.",
            "unit_or_dimension": "dimensionless_dependence",
            "information_set": "rolling historical window ending at factor timestamp",
        })
    expected_metric_change = first_law.get("expected_metric_change") if isinstance(first_law.get("expected_metric_change"), list) else [
        "future Step4/5 evidence must improve",
        "long-side cost-adjusted metrics must remain decisive",
    ]
    falsification_tests = first_law.get("falsification_tests") if isinstance(first_law.get("falsification_tests"), list) else [
        "cost-adjusted Sharpe remains negative",
        "gross signal disappears after the expression-level hypothesis is tested",
    ]
    kill_criteria = first_law.get("kill_criteria") if isinstance(first_law.get("kill_criteria"), list) else [
        "high-score long side remains non-positive",
        "improvement only appears in diagnostic spread metrics",
    ]
    return {
        "research_question": "What mathematical or evidence-based hypothesis should be tested next?",
        "assumptions": [
            {
                "assumption": "The current Step4/5 metrics are valid inputs for advisory proposal generation.",
                "status": "hypothesis",
                "why_needed": "The deterministic scaffold does not independently re-run evidence.",
                "how_to_falsify": "If evidence identity or backend integrity is invalid, discard this proposal.",
            }
        ],
        "mathematical_objects": mathematical_objects,
        "selected_tools": [
            {
                "tool": tool,
                "why_selected": "Scaffold selects this tool to expose formula, evidence, or estimator risks.",
                "what_it_can_answer": "It can generate a falsifiable advisory hypothesis for future review.",
                "what_it_cannot_answer": "It cannot prove tradable alpha or justify promotion.",
            }
            for tool in selected_tools
        ],
        "rejected_tools": [],
        "derivation_steps": [
            {
                "step_no": 1,
                "statement": formula_statement,
                "formula": formula_text,
                "justification": "This is scaffold-level reasoning and must not be treated as proof.",
                "depends_on": [],
            },
            {
                "step_no": 2,
                "statement": "Translate the advisory state hypothesis into expected evidence implications.",
                "formula": "",
                "justification": "Metric implications are hypotheses that must be tested by future Step4/5 evidence.",
                "depends_on": [1],
            },
        ],
        "derived_implications": [
            {
                "claim": "The proposal is hypothesis-generating only.",
                "expected_metric_signature": [
                    "future Step4/5 evidence must improve",
                    "long-side cost-adjusted metrics must remain decisive",
                ],
            }
        ],
        "revision_hypotheses": [
            {
                "hypothesis": first_law.get("law_statement") or "Test the expression-level direction only after human approval.",
                "expression_direction": first_law.get("formula_direction") or proposal.get("expression_change") or "See candidate_revision_laws",
                "revision_model_layer": first_law.get("revision_model_layer") or proposal.get("revision_model_layer") or "observable_estimator",
                "expected_metric_change": expected_metric_change,
                "falsification_tests": falsification_tests,
                "kill_criteria": kill_criteria,
            }
        ],
        "confidence_and_limits": {
            "mathematical_confidence": "low",
            "empirical_confidence": "low",
            "known_gaps": [
                "deterministic scaffold is not agentic mathematical research"
            ],
            "overclaim_guard": "This derivation is scaffold-level and cannot justify promotion or canonical Step3B modification.",
        },
    }


def symbolic_law(packet: dict[str, Any]) -> dict[str, Any]:
    p = base_proposal(packet, "symbolic_law_discovery")
    formula = str(packet.get("factor_formula") or "").lower()
    metrics = packet.get("metrics") or {}
    is_price_volume = any(x in formula for x in ["volume", "vol", "amount", "turnover"]) and any(x in formula for x in ["high", "low", "close", "open"])
    p["selected_math_tools"] = [
        "dimensional_analysis",
        "scaling_law_analysis",
        "stochastic_process_modeling",
        "natural_time_clock_analysis",
    ] if is_price_volume else ["dimensional_analysis", "limiting_case_analysis", "robust_statistics"]
    p["market_phenomenon"] = "Price-volume coupling may estimate pressure, attention, or liquidity-shock state rather than stable drift."
    p["symbolic_model"].update({
        "state_or_object": "latent price-volume pressure state" if is_price_volume else p["symbolic_model"]["state_or_object"],
        "state_process": "short-horizon stochastic pressure process with transient shock and possible persistence components",
        "latent_state": "pressure persistence minus liquidity noise",
    })
    p["dimensional_scaling_review"] = {
        "raw_field_units": {"high": "price", "close": "price", "volume": "shares", "amount": "money"},
        "formula_output_dimension": "dimensionless" if any(x in formula for x in ["rank", "corr", "correlation", "zscore"]) else "unknown",
        "dimension_erasing_transforms": [x for x in ["rank", "correlation", "zscore"] if x in formula],
        "scale_invariance_claims": ["Rank/correlation transforms erase raw units but do not prove cross-sectional economic comparability."],
        "natural_time_scale": "volume_time" if is_price_volume else "trading_time",
        "dimension_risks": ["Raw volume should be normalized by float shares, ADV, or traded value before claiming cross-sectional comparability."],
        "limiting_cases": ["If volume goes to zero, price-volume dependence is ill-conditioned.", "If turnover is very high, transient shock estimates may fail after costs."],
    }
    p["structural_findings"] = [
        "Dimension-erasing transforms can hide unit pollution while preserving unstable ranking behavior.",
        "Short windows on price-volume coupling can estimate transient liquidity shocks rather than persistent expected-return state.",
    ]
    if metrics.get("cost_adjusted_annual_return") is not None and float(metrics.get("cost_adjusted_annual_return") or 0) < 0:
        p["structural_findings"].append("Cost-adjusted evidence suggests a natural-time or liquidity-pressure horizon mismatch.")
    p["candidate_revision_laws"] = [
        law(
            "A price-volume state should be persistent enough to survive trading costs before it is treated as long-side alpha.",
            "Add expression-level persistence confirmation, smoothing, or volume normalization before any approval-gated search.",
        )
    ]
    p["revision_type"] = "mechanism_challenge"
    p["expression_change"] = "Advisory only: test persistence confirmation or normalized volume-pressure state inside the factor expression."
    p["return_source_hypothesis"] = "market_structure_harvesting" if is_price_volume else p["return_source_hypothesis"]
    p["confidence"] = "medium" if is_price_volume else "low"
    return p


def role_proposal(packet: dict[str, Any], role: str) -> dict[str, Any]:
    if role == "symbolic_law_discovery":
        return symbolic_law(packet)
    p = base_proposal(packet, role)
    evidence = nested(packet, "research_memo", "evidence_audit")
    mechanism = nested(packet, "research_memo", "mechanism_analysis")
    case = nested(packet, "research_memo", "case_comparison")
    revision = nested(packet, "research_memo", "revision_strategy")
    signature = revision.get("primary_failure_signature") or "none"
    fit = mechanism.get("mechanism_fit")
    p["confidence"] = "medium"
    if role == "evidence_auditor" and (evidence.get("evidence_verdict") == "blocked" or signature in {"implementation_suspect", "same_factor_identity_mismatch"}):
        p["revision_type"] = "audit"
        p["structural_findings"] = ["Evidence or identity integrity must be repaired before expression research."]
    elif role == "economic_mechanism" and fit in {"weak", "contradicted"}:
        p["revision_type"] = "mechanism_challenge"
        p["structural_findings"] = ["Observed metric signature contradicts or weakly supports the stated return source."]
    elif role == "formula_engineer" and signature in {"cost_too_high", "non_monotonic", "long_side_negative"}:
        p["revision_type"] = "expression_revision"
        p["expression_change"] = "Advisory expression-level change: revise estimator horizon, sign/state mapping, or operator composition after human approval."
        p["candidate_revision_laws"] = [law("Expression structure must map high score to durable long-side return.", p["expression_change"])]
    elif role == "cost_turnover" and signature == "cost_too_high":
        p["revision_type"] = "expression_revision"
        p["expression_change"] = "Advisory expression-level smoothing or persistence confirmation to reduce estimator churn."
        p["candidate_revision_laws"] = [law("A costly signal needs a lower-turnover estimator kernel or more persistent state.", p["expression_change"])]
    elif role == "regime_robustness":
        p["revision_type"] = "mechanism_challenge" if signature in {"non_monotonic", "mechanism_unclear"} else "no_action"
        p["structural_findings"] = ["Check whether the formula mixes regimes, clocks, or market states before parameter search."]
    elif role == "knowledge_retrieval_critic":
        p["revision_type"] = "audit" if case.get("identity_mismatch_cases") else "no_action"
        p["structural_findings"] = [
            "Same-factor cases require identity/hash match.",
            "Similar cases are analogies only and cannot promote the current factor.",
        ]
    return p


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-id", required=True)
    args = parser.parse_args()
    rid = args.report_id
    council_dir = OBJ / "research_iteration_master" / "revision_council" / rid
    packet_path = council_dir / f"revision_council_packet__{rid}.json"
    if not packet_path.exists():
        print(TOKEN_MISSING + ": " + str(packet_path), file=sys.stderr)
        raise SystemExit(1)
    packet = load_json(packet_path)
    written = []
    for role in sorted(COUNCIL_AGENT_ROLES):
        proposal = role_proposal(packet, role)
        proposal["derivation_record"] = build_derivation_record(packet, proposal)
        reasons = validate_revision_council_proposal(proposal)
        if reasons:
            proposal["proposal_status"] = "blocked"
            proposal["block_reasons"] = reasons
        out = council_dir / f"proposal__{rid}__{role}.json"
        write_json(out, proposal)
        written.append(str(out))
    print(json.dumps({"status": "written", "report_id": rid, "proposal_paths": written}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
