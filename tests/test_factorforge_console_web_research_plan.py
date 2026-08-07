from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from factor_factory.console.conversation_ledger import (
    CONVERSATION_LEDGER_REFERENCE_FIELD,
    plan_conversation_checkpoints,
    write_planned_checkpoints,
)

from factor_factory.console.web_research_plan import (
    BLOCK_PLAN_INVALID,
    PLACEHOLDER,
    WebResearchPlanError,
    authoring_request_binding_hash,
    build_authoring_contract,
    required_web_resume_start_step,
    resolve_workspace_approved_catalog,
    sha256_file,
    stable_json_hash,
    validate_materialized_web_research,
    validate_plan,
    web_knowledge_query_text,
    write_text_atomic,
    write_web_research_packet,
)
from factor_factory.knowledge_reference import stable_hash, tokens
from factor_factory.research_workspace import build_workspace_manifest, write_workspace_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    workspace = runtime / "factor_research" / "WEB_FACTOR" / "web_research"
    manifest = build_workspace_manifest(
        repo_root=PROJECT_ROOT,
        factorforge_root=runtime,
        factor_id="WEB_FACTOR",
        research_id="web_research",
        root_report_id="WEB_REPORT",
        implementation_mode="operator",
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    return workspace


def _request() -> dict:
    request = {
        "job_id": "job_123abc4567",
        "factor_id": "WEB_FACTOR",
        "research_id": "web_research",
        "report_id": "WEB_REPORT",
        "title": "Opening pressure repair",
        "hypothesis": "An opening gap without persistent demand may reverse after constrained buyers finish.",
        "universe": "a_share_investable_core",
        "sample_start": "2020-01-01",
        "sample_end": "2025-12-31",
        "forward_horizon": "1d",
        "transaction_cost_bps": 30.0,
    }
    message = {
        "message_id": "msg_initial_hypothesis",
        "sequence_no": 1,
        "role": "user",
        "content_kind": "hypothesis",
        "content": request["hypothesis"],
        "model": "deepseek-v4-flash",
        "created_at_utc": "2026-08-05T00:00:01Z",
    }
    unsigned = {
        "contract_version": "factorforge_console_conversation_snapshot_v1",
        "job_id": request["job_id"],
        "message_count": 1,
        "total_message_count": 1,
        "omitted_message_count": 0,
        "content_truncated": False,
        "history_complete": True,
        "character_budget": 40_000,
        "included_character_count": len(message["content"]),
        "messages": [message],
    }
    snapshot = {**unsigned, "sha256": stable_json_hash(unsigned)}
    request["conversation_snapshot"] = snapshot
    request["conversation_snapshot_sha256"] = snapshot["sha256"]
    return request


def _dcf_request() -> dict:
    request = _request()
    request["title"] = "Legal-time discounted cash-flow valuation gap"
    request["hypothesis"] = (
        "Published cash-flow forecasts imply intrinsic value that converges toward "
        "market price after conservative discount-rate and terminal-growth controls."
    )
    unsigned = dict(request["conversation_snapshot"])
    unsigned.pop("sha256", None)
    unsigned["messages"] = [
        {
            **unsigned["messages"][0],
            "content": request["hypothesis"],
        }
    ]
    unsigned["included_character_count"] = len(request["hypothesis"])
    snapshot = {**unsigned, "sha256": stable_json_hash(unsigned)}
    request["conversation_snapshot"] = snapshot
    request["conversation_snapshot_sha256"] = snapshot["sha256"]
    return request


def _conversation_snapshot(
    contents: list[str],
    *,
    total_message_count: int | None = None,
    content_truncated: bool = False,
) -> dict:
    messages = [
        {
            "message_id": f"msg_{index:02d}",
            "sequence_no": index,
            "role": "user",
            "content_kind": "hypothesis" if index == 1 else "decision",
            "content": content,
            "model": "deepseek-v4-flash",
            "created_at_utc": f"2026-08-05T00:00:0{index}Z",
        }
        for index, content in enumerate(contents, start=1)
    ]
    total = len(messages) if total_message_count is None else total_message_count
    unsigned = {
        "contract_version": "factorforge_console_conversation_snapshot_v1",
        "job_id": "job_123abc4567",
        "message_count": len(messages),
        "total_message_count": total,
        "omitted_message_count": max(0, total - len(messages)),
        "content_truncated": content_truncated,
        "history_complete": total == len(messages) and not content_truncated,
        "character_budget": 40_000,
        "included_character_count": sum(len(item["content"]) for item in messages),
        "messages": messages,
    }
    return {**unsigned, "sha256": stable_json_hash(unsigned)}


def _request_with_messages(
    contents: list[str],
    *,
    total_message_count: int | None = None,
    content_truncated: bool = False,
) -> dict:
    request = _request()
    snapshot = _conversation_snapshot(
        contents,
        total_message_count=total_message_count,
        content_truncated=content_truncated,
    )
    request["conversation_snapshot"] = snapshot
    request["conversation_snapshot_sha256"] = snapshot["sha256"]
    return request


def _bind_resume_checkpoint(
    workspace: Path,
    request: dict,
    *,
    ledger_messages: list[dict] | None = None,
) -> dict:
    persisted_request = json.loads(
        (workspace / "identity" / "web_research_request.json").read_text(
            encoding="utf-8"
        )
    )
    reference, planned = plan_conversation_checkpoints(
        workspace,
        job_id=str(request["job_id"]),
        messages=ledger_messages or request["conversation_snapshot"]["messages"],
        existing_request=persisted_request,
        parent_attestation_id="attestations/job_123abc4567/attestation_test.json",
        parent_attestation_sha256="a" * 64,
    )
    write_planned_checkpoints(workspace, planned)
    bound = dict(request)
    bound[CONVERSATION_LEDGER_REFERENCE_FIELD] = reference
    return bound


def _request_with_bounded_history(
    contents: list[str],
    *,
    visible_limit: int = 40,
) -> tuple[dict, list[dict]]:
    full_snapshot = _conversation_snapshot(contents)
    all_messages = full_snapshot["messages"]
    visible_messages = all_messages[-visible_limit:]
    unsigned = {
        "contract_version": "factorforge_console_conversation_snapshot_v1",
        "job_id": "job_123abc4567",
        "message_count": len(visible_messages),
        "total_message_count": len(all_messages),
        "omitted_message_count": len(all_messages) - len(visible_messages),
        "content_truncated": False,
        "history_complete": len(visible_messages) == len(all_messages),
        "character_budget": 40_000,
        "included_character_count": sum(
            len(item["content"]) for item in visible_messages
        ),
        "messages": visible_messages,
    }
    snapshot = {**unsigned, "sha256": stable_json_hash(unsigned)}
    request = _request()
    request["conversation_snapshot"] = snapshot
    request["conversation_snapshot_sha256"] = snapshot["sha256"]
    return request, all_messages


def _write_catalog(tmp_path: Path) -> Path:
    path = tmp_path / "data_catalog.json"
    path.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "dataset_id": "clean_daily_bar",
                        "columns": [
                            "ts_code",
                            "trade_date",
                            "open",
                            "pre_close",
                            "close",
                            "forecast_fcf",
                            "wacc",
                            "terminal_growth",
                        ],
                        "metadata": {"schema_version": "daily_bar_v1", "qa_verdict": "ACCEPT"},
                        "uri": "s3://approved-read-only/clean_daily_bar",
                    },
                    {
                        "dataset_id": "raw_minute_bar",
                        "columns": ["ts_code", "trade_time", "close", "vol"],
                        "metadata": {"schema_version": "minute_bar_v1", "qa_verdict": "ACCEPT"},
                        "uri": "s3://not-projected-to-web-authoring/raw_minute_bar",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _fill_plan(workspace: Path) -> dict:
    plan_path = workspace / "identity" / "web_research_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["research_object"].update(
        {
            "formula_or_law": "-(open / pre_close - 1.0)",
            "expected_direction": "positive",
            "rebalance_frequency": "daily",
        }
    )
    knowledge_summary = json.loads(
        (workspace / "identity" / "factor_knowledge_summary.json").read_text(encoding="utf-8")
    )
    if knowledge_summary["nodes"]:
        plan["knowledge_use"].update(
            {
                "cited_node_ids": [knowledge_summary["nodes"][0]["id"]],
                "applied_lessons": ["Apply the cited case's failure controls without treating it as the same factor."],
                "cold_start": False,
            }
        )
    else:
        plan["knowledge_use"].update(
            {
                "cited_node_ids": [],
                "applied_lessons": ["Cold start: separate opening-price effects from reversal and liquidity aliases."],
                "cold_start": True,
            }
        )
    plan["data_plan"].update(
        {
            "daily_fields": ["open", "pre_close"],
            "minute_fields": [],
            "availability_lags": ["pre_close is known before t open; t open is usable only after the opening auction"],
            "missing_data_policy": "drop rows with missing or non-positive pre_close and preserve an auditable count",
            "data_gap_conditions": ["BLOCK if opening auction timestamps or pre_close identity cannot be verified"],
        }
    )
    plan["implementation"]["operators"] = ["divide()", "minus()", "negate()"]
    plan["economic_mechanism"].update(
        {
            "return_source_family": "information_advantage",
            "claim_class": "behavioral_rent",
            "market_phenomenon": "opening demand pressure can overshoot when overnight information diffusion is incomplete",
            "mechanism_claim": "patient investors receive value when opening-gap buyers finish urgent execution before fundamentals justify the price change",
            "subtype": "overnight_information_diffusion_and_temporary_opening_impact",
            "participants": ["urgent opening-gap buyers", "patient liquidity suppliers"],
            "payer_candidates": ["urgent opening-gap buyers"],
            "why_they_pay": "their deadline and delayed belief update make them accept temporary opening impact",
            "participant_constraints": [
                {
                    "actor": "urgent opening-gap buyers",
                    "constraint": "complete desired inventory near the opening auction after overnight news",
                    "why_persistent": "the information or mandate arrives while the market is closed and cannot be executed earlier",
                    "observable_proxy": "opening gap relative to the previous close",
                    "falsifier": "gap-conditioned returns do not differ after reversal and liquidity controls",
                }
            ],
            "action_to_price_path": "concentrated opening demand raises price before patient supply fully absorbs the order imbalance",
            "profit_transfer_equation": "receiver_pnl = temporary_opening_impact_repair - transaction_cost - impact_cost",
            "persistence_boundary": "the effect ends after opening inventory demand is absorbed or information is confirmed",
            "capacity_boundary": "capacity is bounded by opening-auction and early-session opposite-side liquidity",
            "failure_condition": "no positive long-side payoff remains after costs and alias controls",
            "what_must_be_true": [
                "opening gaps contain a temporary-impact component distinct from permanent information",
                "the favored low-pressure side has positive after-cost forward return",
            ],
            "what_would_break_it": [
                "the signal is fully explained by unconditional short-term reversal",
                "transaction and impact costs consume long-side payoff",
            ],
            "alternative_return_source_tests": [
                {
                    "alternative_source": "risk_premium",
                    "why_not_primary": "the proposed horizon and opening concentration point to transitory demand rather than broad systematic risk",
                    "discriminating_test": "control beta, size, volatility and liquidity, then test the residual opening-pressure signature",
                    "expected_signature_if_alternative_true": "payoff should be monotone in broad risk exposure and persist beyond opening-impact decay",
                }
            ],
        }
    )
    plan["mathematical_mechanism"].update(
        {
            "model_family": "latent temporary price impact with overnight information arrival",
            "math_tools": ["conditional_expectation", "state_space_model", "component_ablation"],
            "mathematical_object": "unabsorbed opening demand pressure net of permanent information",
            "mechanism_equation_or_functional": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t",
            "observation_equation": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t",
            "factor_estimator": "negative opening gap computed from t open and t-1 close",
            "target_functional": "E[r_i,t+1 | F_open,t, temporary_pressure_i,t]",
            "market_outcome_equation": "r_i,t+1 = -beta * temporary_pressure_i,t - cost_i,t + eta_i,t+1",
            "traded_quantity": "next-horizon after-cost equity return distribution",
            "information_set": "previous close and completed day-t market data available by close; position is formed at close t",
            "why_suitable": "the decomposition separates permanent overnight news from temporary opening demand pressure",
            "why_alternatives_are_less_suitable": ["unconditional reversal has no opening-specific state or participant deadline"],
            "alternative_models": ["unconditional reversal", "systematic overnight risk premium"],
            "component_map": [
                {
                    "implementation_component_id": "opening_gap_repair_score",
                    "formula_component": "open / pre_close - 1",
                    "model_term": "permanent_news plus temporary_pressure observation",
                    "preserved_information": "signed opening price displacement",
                    "deleted_or_aliased_information": "permanent-news and temporary-pressure decomposition",
                    "ablation_test": "compare raw gap with residual gap after news, reversal and liquidity controls",
                }
            ],
            "limiting_cases": [
                "temporary pressure equals zero implies no repair drift",
                "infinite opening liquidity implies zero temporary impact",
                "cost above expected repair implies non-positive net payoff",
            ],
            "expected_metric_signatures": [
                {"metric": "long_side_return", "direction": "positive after cost"},
                {"metric": "rank_ic", "direction": "positive for the negated gap estimator"},
            ],
        }
    )
    plan["measurement_program"]["knowledge_role"]["conflict_resolution"] = (
        "Contradictory knowledge creates a discriminating test; it cannot change the estimand."
    )
    plan["measurement_program"]["math_tool_selection"].update(
        {
            "candidate_tool_families": [
                "state-space stochastic processes",
                "signal decomposition",
                "information-theoretic dependence",
            ],
            "selected_tool_families": [
                "state-space stochastic processes",
                "signal decomposition",
            ],
            "selection_rationale": "latent-state separation and component filtering match the economic hypothesis; the list remains open to a new mathematical object",
            "rejected_tool_families": [
                {
                    "tool_family": "information-theoretic dependence",
                    "reason": "dependence alone does not identify temporary versus permanent opening pressure",
                }
            ],
        }
    )
    plan["measurement_program"]["model_selection"].update(
        {
            "selection_target": "unabsorbed opening pressure net of permanent information",
            "candidate_models": [
                {
                    "candidate_id": "preferred_mechanism",
                    "candidate_role": "primary",
                    "model_family": "latent temporary price impact with overnight information arrival",
                    "mathematical_object": "unabsorbed opening demand pressure net of permanent information",
                    "mechanism_equation_or_functional": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t; temporary_pressure_i,t+1 = rho * temporary_pressure_i,t + eta_i,t+1 with abs(rho) < 1",
                    "target_functional": "E[r_i,t+1 | F_open,t, temporary_pressure_i,t]",
                    "market_outcome_projection": "r_i,t+1 = -beta * temporary_pressure_i,t - cost_i,t + eta_i,t+1",
                    "observation_mapping": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t",
                    "economic_implication": "temporary opening impact predicts subsequent repair",
                    "identifiability_condition": "temporary impact is separable from permanent news and ordinary reversal",
                    "decisive_test": "residual opening-gap payoff survives news, reversal and liquidity controls",
                    "selected": True,
                },
                {
                    "candidate_id": "alternative_mechanism",
                    "candidate_role": "mechanism_alternative",
                    "model_family": "permanent overnight information diffusion",
                    "mathematical_object": "fundamental news innovation",
                    "mechanism_equation_or_functional": "fundamental_value_i,t = fundamental_value_i,t-1 + permanent_news_i,t and gap_i,t measures that permanent innovation",
                    "target_functional": "continuation payoff conditional on permanent overnight news",
                    "market_outcome_projection": "r_i,t+1 = beta_news * permanent_news_i,t - cost_i,t + eta_i,t+1",
                    "observation_mapping": "map legally observed news and opening displacement into a permanent-news estimator",
                    "economic_implication": "opening gap predicts continuation rather than repair",
                    "identifiability_condition": "news controls explain the gap and continuation",
                    "decisive_test": "signed forward return reverses under information-day controls",
                    "selected": False,
                },
                {
                    "candidate_id": "null_alias",
                    "candidate_role": "null_alias",
                    "model_family": "ordinary reversal and liquidity alias model",
                    "mathematical_object": "observable short-horizon reversal and liquidity controls",
                    "mechanism_equation_or_functional": "gap_i,t = gamma * reversal_i,t + delta * liquidity_i,t + residual_i,t with E[payoff_i,t+1 given residual_i,t] = 0",
                    "target_functional": "incremental payoff after reversal and liquidity aliases",
                    "market_outcome_projection": "E[r_i,t+1 | residual_i,t] = 0 after costs",
                    "observation_mapping": "project the opening displacement on legal-time reversal and liquidity controls",
                    "economic_implication": "the opening-specific state adds no information after alias controls",
                    "identifiability_condition": "alias controls span the same conditional-return variation",
                    "decisive_test": "the residual opening-pressure component has zero incremental payoff",
                    "selected": False,
                },
            ],
            "selection_argument": "the payer and finite absorption horizon imply a transient state model",
            "rejected_model_reason": "permanent information predicts continuation and a different conditional signature",
        }
    )
    plan["measurement_program"]["market_outcome_projection"].update(
        {
            "projection_kind": "conditional distribution induced by a latent-state observation model",
            "source_math_object": "unabsorbed opening demand pressure net of permanent information",
            "traded_quantity": "next-horizon after-cost equity return distribution",
            "affected_payoff_or_distribution_terms": ["conditional drift", "conditional left-tail probability"],
            "projection_equation_or_map": "r_i,t+1 = -beta * temporary_pressure_i,t - cost_i,t + eta_i,t+1",
            "link_to_observation_equation": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t",
            "falsifier": "the conditional return distribution is unchanged after temporary-pressure conditioning",
        }
    )
    plan["measurement_program"]["applicable_audits"].update(
        {
            "selection_rule": "select only audits justified by the chosen mechanism",
            "selected": [
                {
                    "audit_family": "dimensional_analysis",
                    "rationale": "the opening displacement divides two price quantities",
                    "audit_record": "(currency/share)/(currency/share)-1 is dimensionless and invariant to common rescaling",
                    "falsifier": "the signal changes under a pure common price-unit conversion",
                }
            ],
            "rejected": [],
        }
    )
    plan["measurement_program"]["observation_and_estimation"].update(
        {
            "estimand": "E[r_i,t+1 | F_open,t, temporary_pressure_i,t]",
            "observation_map": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t",
            "estimator": "negative opening gap computed from t open and t-1 close",
            "identification_assumptions": [
                "price fields share an adjustment basis and legal timestamp",
                "news, reversal and liquidity controls separate permanent and temporary components",
            ],
            "bias_variance_and_noise": "raw gap is biased by permanent news and noisy when opening liquidity is low",
            "legal_information_time": "open and pre_close are known before the close-t signal is frozen",
            "data_construction_is_hypothesis_conditioned": True,
        }
    )
    plan["measurement_program"]["public_derivation_record"].update(
        {
            "definitions": [
                "g_i,t = open_i,t / pre_close_i,t - 1 is the legal opening displacement",
                "u_i,t is temporary opening demand pressure net of permanent news",
            ],
            "assumptions": [
                "open and pre_close use the same adjustment basis",
                "news, reversal and liquidity controls can discriminate temporary pressure",
            ],
            "key_derivation_steps": [
                "decompose g_i,t into permanent news plus temporary pressure plus noise",
                "temporary pressure decays after constrained buyers complete urgent demand",
                "therefore the negated legal-time gap estimates the sign of repair drift",
            ],
            "identification_gaps": [
                "permanent news is not directly observed and requires discriminating controls"
            ],
            "approximations": [
                "the pilot uses a linear observation map over the registered horizon"
            ],
            "overclaim_guard": "this derivation identifies a falsifiable candidate, not proof of positive return",
        }
    )
    plan["measurement_program"]["implementation"].update(
        {
            "route": "operator",
            "web_execution_status": "trusted_formula_ir_execution",
            "why_this_route": "the approved ratio and sign estimator is exactly expressible in trusted Formula IR",
            "components": [
                {
                    "component_id": "opening_gap_repair_score",
                    "binding_role": "full_formula",
                    "economic_claim": "larger positive temporary opening pressure should earn lower forward return",
                    "math_term_or_functional": "negative observation of the transient pressure state",
                    "mechanism_role": "measure the signed displacement that should decay when urgent demand ends",
                    "observable_or_input": "open and pre_close",
                    "input_fields": ["open", "pre_close"],
                    "transformation_or_estimator": "negative relative opening gap",
                    "implementation_binding": "negate(minus(divide(open, pre_close), 1.0))",
                    "input_measurement_semantics": "currency per share accounting inputs",
                    "output_measurement_semantics": "dimensionless score",
                    "information_time": "available by close t before portfolio formation",
                    "preserved_information": "signed relative opening displacement",
                    "discarded_information": "absolute price level and any unobserved permanent-news decomposition",
                    "expected_metric_signature": "positive rank IC for the negated estimator and positive after-cost long side",
                    "ablation_test": "remove the negation and require the RankIC sign to reverse",
                    "falsifier": "residual payoff is non-positive after controls and costs",
                    "knowledge_node_ids": plan["knowledge_use"]["cited_node_ids"],
                }
            ],
        }
    )
    plan["measurement_program"]["deterministic_validation_plan"].update(
        {
            "schema_and_measurement_checks": [
                "open and pre_close are positive currency-per-share fields on the same adjustment basis"
            ],
            "future_mutation_invariance": "mutating rows after t must not change signal values at or before t",
            "limiting_case_oracles": [
                "open equals pre_close implies a zero raw gap estimator"
            ],
            "ablation_and_alias_tests": [
                "compare raw gap against news-, reversal- and liquidity-controlled residual gap"
            ],
            "implementation_parity": "Formula IR reference and optimized engines must agree within tolerance",
        }
    )
    plan["measurement_program"]["search_policy"].update(
        {
            "invariant_estimand": "temporary opening pressure repair drift",
            "allowed_model_or_estimator_variations": [
                "news-residualized gap and liquidity-conditioned observation models"
            ],
            "stop_rules": [
                "stop when all identified estimators fail OOS, alias and after-cost signatures"
            ],
        }
    )
    hypotheses = {item["kind"]: item for item in plan["hypotheses"]}
    hypotheses["preferred"].update(
        {
            "claim": "temporary opening demand pressure repairs after urgent buyers finish",
            "expected_signature": "the negated gap has positive rank IC and positive long-side after-cost return",
            "falsification_tests": ["no residual IC after reversal controls", "no positive long-side after-cost return"],
            "kill_criteria": ["kill if the legal long side is non-positive after costs"],
        }
    )
    hypotheses["null"].update(
        {
            "claim": "the opening gap estimator is noise or a data-alignment artifact",
            "expected_signature": "no stable endpoint, component or regime evidence",
            "falsification_tests": ["timestamp parity passes", "placebo and shuffled tests fail to reproduce the signal"],
            "kill_criteria": ["kill the null if verified residual evidence survives placebo tests"],
        }
    )
    hypotheses["alternative"].update(
        {
            "claim": "the estimator is only unconditional short-term reversal",
            "expected_signature": "incremental opening-state payoff vanishes after reversal controls",
            "falsification_tests": ["opening-state residual remains after controls", "opening interaction differs from ordinary reversal"],
            "kill_criteria": ["kill the alternative if opening-specific residual evidence remains"],
        }
    )
    plan["evidence_policy"].update(
        {
            "is_start": "2020-01-01",
            "is_end": "2024-12-31",
            "oos_start": "2025-01-01",
            "oos_end": "2025-12-31",
            "regime_plan": "bull, bear, high-volatility and low-liquidity regimes",
            "terminal_success_condition": "component, alias, long-side after-cost, regime and proof-certificate obligations all pass",
            "terminal_reject_condition": "the preferred route fails preregistered tests and no distinct route survives",
            "terminal_block_condition": "data identity, legal timing, implementation parity or required evidence is unresolved",
        }
    )
    route_text = {
        "economic_game": (
            "Does an urgent opening buyer transfer value to patient liquidity suppliers?",
            "participant deadlines create temporary opening impact",
            "identifies payer, receiver and persistence boundary",
            "payer identity and transfer equation lack executed evidence",
        ),
        "mechanism_object_measurement": (
            "Does the opening gap measure temporary pressure rather than permanent news?",
            "residual opening gap is a valid mechanism-object estimator",
            "tests observation validity and component ablation",
            "measurement and component evidence have not been executed",
        ),
        "null_alias_counterexample": (
            "Can reversal, liquidity or timestamp errors reproduce the result?",
            "the candidate is an alias or implementation artifact",
            "attacks aliases and legal-time alignment",
            "null, placebo and alias evidence have not been executed",
        ),
    }
    for route in plan["routes"]:
        question, claim, distinct, gap = route_text[route["route_family"]]
        route.update(
            {
                "research_question": question,
                "core_hypothesis": claim,
                "distinct_from_other_routes": distinct,
                "exact_gap": gap,
            }
        )
    assert PLACEHOLDER not in json.dumps(plan)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def test_unfilled_plan_blocks_with_field_level_reason(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = json.loads((workspace / "identity" / "web_research_plan.json").read_text(encoding="utf-8"))
    summary = json.loads((workspace / "identity" / "data_catalog_summary.json").read_text(encoding="utf-8"))
    assert summary["catalogs"][0]["entries"][0]["name"] == "clean_daily_bar"
    assert "open" in summary["catalogs"][0]["entries"][0]["columns"]
    assert [entry["name"] for entry in summary["catalogs"][0]["entries"]] == [
        "clean_daily_bar"
    ]
    contract = json.loads(
        (workspace / "identity" / "web_research_authoring_contract.json").read_text(
            encoding="utf-8"
        )
    )
    operator_names = {
        item["name"] for item in contract["formula_ir_contract"]["supported_operators"]
    }
    assert contract["version"] == "factorforge_web_research_authoring_contract_v2"
    assert contract["immutable_host_authored"] is True
    assert contract["host_input_binding"]["request_sha256"] == (
        authoring_request_binding_hash(_request())
    )
    assert (
        contract["host_input_binding"]["request_binding_scope"]
        == "immutable_authoring_request_v1"
    )
    knowledge_summary = json.loads(
        (workspace / "identity" / "factor_knowledge_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["host_input_binding"]["knowledge_summary_sha256"] == (
        stable_json_hash(knowledge_summary)
    )
    assert "open" in contract["daily_field_contract"]["allowed_columns"]
    assert "multiply" in operator_names
    assert "mul" not in operator_names
    assert "constraint_driven_arbitrage" in (
        contract["economic_mechanism_contract"]["return_source_family_allowed"]
    )
    assert contract["evidence_window_contract"]["required_relation"] == (
        "is_start <= is_end < oos_start <= oos_end"
    )
    guide = (workspace / "identity" / "web_research_runtime.md").read_text(
        encoding="utf-8"
    )
    assert "validate_factorforge_web_research_plan.py" in guide
    assert "python3 -B" in guide
    assert "controls and strata" in guide
    assert "`mul`, `sub` and `div` are" in guide
    assert "only datasets the Web" in guide
    assert "do not recompute, shorten or hand-copy the" in guide
    assert "contract hash" in guide

    try:
        validate_plan(plan, workspace=workspace)
    except WebResearchPlanError as exc:
        assert exc.token == BLOCK_PLAN_INVALID
        assert "unreplaced_placeholders" in exc.reasons
    else:
        raise AssertionError("unfilled web research plan must block")


def test_authoring_preflight_passes_valid_plan_and_reports_formula_contract(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    _fill_plan(workspace)

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/validate_factorforge_web_research_plan.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(workspace / "identity" / "web_research_plan.json"),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["verdict"] == "PASS"
    assert result["formal_research_started"] is False
    assert result["required_fields"] == ["open", "pre_close"]
    assert result["operator_set"] == ["divide", "minus", "negate"]


def test_full_web_plan_accepts_dcf_without_stochastic_or_dimensional_audits(
    tmp_path,
):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    request = _dcf_request()
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=request,
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["research_object"].update(
        {
            "title": request["title"],
            "hypothesis": request["hypothesis"],
            "formula_or_law": (
                "forecast_fcf / (wacc - terminal_growth) / close - 1.0"
            ),
            "expected_direction": "positive",
        }
    )
    plan["data_plan"].update(
        {
            "daily_fields": [
                "forecast_fcf",
                "wacc",
                "terminal_growth",
                "close",
            ],
            "availability_lags": [
                "forecast_fcf, wacc and terminal_growth use the latest legally published values; close is known at signal freeze"
            ],
            "missing_data_policy": "drop observations with missing inputs or wacc less than or equal to terminal_growth",
            "data_gap_conditions": [
                "BLOCK if publication timestamps, forecast vintage or accounting basis cannot be verified"
            ],
        }
    )
    plan["implementation"]["operators"] = ["divide()", "minus()"]
    plan["economic_mechanism"].update(
        {
            "return_source_family": "information_advantage",
            "claim_class": "information_rent",
            "market_phenomenon": "market price may adjust gradually to legally published cash-flow information",
            "mechanism_claim": "investors who value cash-flow timing and discount rates more consistently receive convergence payoff from stale valuation anchors",
            "subtype": "legal_time_intrinsic_value_convergence",
            "participants": ["valuation-aware patient investors", "investors using stale valuation anchors"],
            "payer_candidates": ["investors using stale valuation anchors"],
            "why_they_pay": "forecast processing costs and anchoring delay incorporation of cash-flow and discount-rate changes",
            "participant_constraints": [
                {
                    "actor": "investors using stale valuation anchors",
                    "constraint": "update intrinsic-value estimates slowly after legal disclosures",
                    "why_persistent": "cash-flow forecast reconciliation and discount-rate estimation are costly",
                    "observable_proxy": "legal-time DCF value gap",
                    "falsifier": "the DCF gap has no incremental payoff after value, quality and risk controls",
                }
            ],
            "action_to_price_path": "delayed valuation updating leaves price below conservative intrinsic value until information is absorbed",
            "profit_transfer_equation": "receiver_pnl = valuation_gap_convergence - transaction_cost - model_error_loss",
            "persistence_boundary": "the edge ends when price incorporates the cash-flow revision or the forecast is invalidated",
            "capacity_boundary": "capacity is bounded by names with reliable forecasts and sufficient tradable liquidity",
            "failure_condition": "the legal-time DCF gap has no positive controlled after-cost long-side payoff",
            "what_must_be_true": [
                "forecast cash flows and discount rates are observable without lookahead",
                "the valuation gap predicts convergence beyond known value and quality aliases",
            ],
            "what_would_break_it": [
                "terminal-value assumptions dominate the signal",
                "value, quality or distress controls fully absorb the payoff",
            ],
            "alternative_return_source_tests": [
                {
                    "alternative_source": "risk_premium",
                    "why_not_primary": "the hypothesis concerns delayed information processing rather than compensation for systematic risk",
                    "discriminating_test": "control value, quality, leverage, beta and distress before testing residual convergence",
                    "expected_signature_if_alternative_true": "payoff is explained by stable systematic risk exposure rather than forecast revision timing",
                }
            ],
        }
    )
    math = plan["mathematical_mechanism"]
    assert {
        "random_object",
        "latent_state",
        "state_space",
        "process_or_distribution_hypothesis",
        "affected_price_process_terms",
        "expected_return_distribution_change",
    }.isdisjoint(math)
    math.update(
        {
            "model_family": "discounted cash-flow valuation",
            "math_tools": [
                "discounted_cash_flow",
                "residual_income",
                "accounting_identity",
            ],
            "mathematical_object": "present value of legal-time forecast free cash flows",
            "mechanism_equation_or_functional": "V_t=FCF_next,t/(WACC_t-g_t); gap_t=V_t/P_t-1",
            "observation_equation": "published forecast_fcf, wacc, terminal_growth and close map to the legal-time perpetuity approximation",
            "factor_estimator": "forecast_fcf/(wacc-terminal_growth)/close-1",
            "target_functional": "after-cost convergence payoff conditional on the legal-time DCF gap",
            "market_outcome_equation": "V_t=FCF_next,t/(WACC_t-g_t); alpha_t=V_t/P_t-1",
            "traded_quantity": "after-cost valuation-gap convergence return",
            "why_suitable": "cash-flow timing and discount rates define intrinsic value directly",
            "why_alternatives_are_less_suitable": [
                "a generic stochastic price process does not identify intrinsic value"
            ],
            "alternative_models": [
                "residual-income valuation",
                "null accounting and style alias model",
            ],
            "component_map": [
                {
                    "implementation_component_id": "dcf_value_gap",
                    "formula_component": "forecast_fcf/(wacc-terminal_growth)/close-1",
                    "model_term": "zero-growth-adjusted perpetuity value relative to market price",
                    "preserved_information": "cash-flow level, discount-rate spread and market-price normalization",
                    "deleted_or_aliased_information": "multi-stage forecast shape and capital-structure detail",
                    "ablation_test": "remove each FCF, discount-spread and price-normalization component and require the predicted signature to weaken",
                }
            ],
            "limiting_cases": [
                "zero valuation gap implies zero predicted convergence payoff",
                "higher discount rate lowers intrinsic value holding cash flows fixed",
                "non-positive terminal spread removes terminal-value growth",
            ],
        }
    )
    program = plan["measurement_program"]
    program["math_tool_selection"].update(
        {
            "candidate_tool_families": [
                "discounted cash-flow valuation",
                "residual-income valuation",
                "null accounting alias model",
            ],
            "selected_tool_families": ["discounted cash-flow valuation"],
            "selection_rationale": "cash-flow timing and discount rates define the selected intrinsic-value object",
            "rejected_tool_families": [
                {
                    "tool_family": "generic stochastic price process",
                    "reason": "not needed for the core intrinsic-value derivation",
                }
            ],
        }
    )
    models = program["model_selection"]["candidate_models"]
    models[0].update(
        {
            "model_family": "discounted cash-flow valuation",
            "mathematical_object": "present value of legal-time forecast free cash flows",
            "mechanism_equation_or_functional": "V_t=FCF_next,t/(WACC_t-g_t)",
        }
    )
    models[1].update(
        {
            "model_family": "residual-income valuation",
            "mathematical_object": "book value plus discounted abnormal earnings",
            "mechanism_equation_or_functional": "V_t=B_t+sum_k RI_t+k/(1+r_t)^k",
            "target_functional": "residual-income intrinsic-value-to-price gap",
            "market_outcome_projection": "positive residual-income gaps predict controlled convergence payoff",
            "observation_mapping": "map legal-time book value, earnings forecasts and discount rates into residual income value",
        }
    )
    models[2].update(
        {
            "model_family": "null accounting and style alias model",
            "mathematical_object": "known accounting, size and value aliases",
            "mechanism_equation_or_functional": "dcf_gap_t=gamma*known_aliases_t+residual_t",
            "target_functional": "incremental payoff after known accounting and style aliases",
            "market_outcome_projection": "the null predicts zero residual after-cost convergence payoff",
            "observation_mapping": "project the legal-time DCF gap on accounting and style controls",
        }
    )
    program["applicable_audits"] = {
        "selection_rule": "select only audits justified by the chosen mechanism",
        "selected": [],
        "rejected": [],
    }
    program["market_outcome_projection"].update(
        {
            "projection_kind": "intrinsic value to market-price gap and convergence payoff",
            "source_math_object": "present value of legal-time forecast free cash flows",
            "traded_quantity": "after-cost valuation-gap convergence return",
            "affected_payoff_or_distribution_terms": [
                "intrinsic value",
                "valuation gap",
                "convergence payoff",
            ],
            "projection_equation_or_map": "V_t=FCF_next,t/(WACC_t-g_t); alpha_t=V_t/P_t-1",
            "link_to_observation_equation": "published forecast_fcf, wacc, terminal_growth and close map to the legal-time perpetuity approximation",
            "falsifier": "the valuation gap has no controlled after-cost convergence payoff",
        }
    )
    program["observation_and_estimation"].update(
        {
            "estimand": "after-cost convergence payoff conditional on the legal-time DCF gap",
            "observation_map": "published forecast_fcf, wacc, terminal_growth and close map to the legal-time perpetuity approximation",
            "estimator": "forecast_fcf/(wacc-terminal_growth)/close-1",
            "identification_assumptions": [
                "all fundamental inputs use legal publication timestamps and a consistent accounting basis",
                "wacc exceeds terminal growth and alias controls separate valuation from distress and quality",
            ],
            "bias_variance_and_noise": "forecast and discount-rate error can dominate the gap, especially when the discount spread is small",
            "legal_information_time": "all inputs are frozen from legally available records by the close-t signal time",
        }
    )
    models[0].update(
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
    program["public_derivation_record"].update(
        {
            "definitions": [
                "V_t=FCF_next,t/(WACC_t-g_t) is the legal-time conservative perpetuity approximation",
                "gap_t=V_t/P_t-1 is the traded intrinsic-value gap",
            ],
            "assumptions": [
                "WACC_t is greater than terminal growth g_t",
                "forecast and price inputs are on compatible per-share and publication-time bases",
            ],
            "key_derivation_steps": [
                "discount the forecast cash-flow stream using the selected valuation identity",
                "normalize intrinsic value by contemporaneous market price to obtain a comparable gap",
                "map a positive residual gap to a falsifiable after-cost convergence payoff",
            ],
            "identification_gaps": [
                "forecast error and omitted multi-stage growth can alias the inferred valuation gap"
            ],
            "approximations": [
                "the Web pilot uses a one-stage perpetuity approximation rather than a full forecast term structure"
            ],
            "overclaim_guard": "the identity defines a valuation estimator, not proof that market price will converge",
        }
    )
    program["implementation"].update(
        {
            "why_this_route": "the legal-time one-stage DCF gap is exactly expressible in trusted Formula IR",
            "components": [
                {
                    "component_id": "dcf_value_gap",
                    "binding_role": "full_formula",
                    "economic_claim": "a larger conservative intrinsic-value gap predicts stronger convergence payoff",
                    "math_term_or_functional": "FCF_next/(WACC-g)/P-1",
                    "mechanism_role": "estimate intrinsic value relative to market price",
                    "observable_or_input": "forecast_fcf, wacc, terminal_growth and close",
                    "input_fields": [
                        "forecast_fcf",
                        "wacc",
                        "terminal_growth",
                        "close",
                    ],
                    "transformation_or_estimator": "one-stage DCF value divided by close minus one",
                    "implementation_binding": "minus(divide(divide(forecast_fcf, minus(wacc, terminal_growth)), close), 1.0)",
                    "input_measurement_semantics": "legal-time per-share FCF, decimal rates and currency-per-share close",
                    "output_measurement_semantics": "dimensionless intrinsic-value gap",
                    "information_time": "legally available by the close-t signal freeze",
                    "preserved_information": "cash-flow level, discount spread and relative valuation",
                    "discarded_information": "multi-stage forecast shape and capital-structure detail",
                    "expected_metric_signature": "positive controlled RankIC and after-cost long-side return for positive gaps",
                    "ablation_test": "remove FCF, discount spread or price normalization separately",
                    "falsifier": "the residual gap has no positive after-cost convergence payoff",
                    "knowledge_node_ids": plan["knowledge_use"]["cited_node_ids"],
                }
            ],
        }
    )
    program["deterministic_validation_plan"].update(
        {
            "schema_and_measurement_checks": [
                "forecast_fcf and close share a per-share basis; wacc and terminal_growth are decimals with wacc greater than growth"
            ],
            "limiting_case_oracles": [
                "forecast_fcf equal to zero implies intrinsic value equal to zero"
            ],
            "ablation_and_alias_tests": [
                "control book-to-market, quality, leverage and distress before attributing residual payoff to valuation updating"
            ],
        }
    )
    program["search_policy"]["invariant_estimand"] = (
        "after-cost convergence payoff conditional on the legal-time DCF gap"
    )
    hypotheses = {item["kind"]: item for item in plan["hypotheses"]}
    hypotheses["preferred"].update(
        {
            "claim": "a positive legal-time DCF gap predicts after-cost price convergence",
            "expected_signature": "positive controlled RankIC and positive after-cost long-side return",
        }
    )
    hypotheses["null"].update(
        {
            "claim": "the DCF gap is only a value, quality or distress alias",
            "expected_signature": "residual payoff vanishes after alias controls",
        }
    )
    hypotheses["alternative"].update(
        {
            "claim": "the apparent payoff is compensation for systematic value risk",
            "expected_signature": "payoff follows stable risk exposure rather than forecast-update timing",
        }
    )

    validate_plan(plan, workspace=workspace)


def test_v2_authoring_contract_excludes_append_only_conversation_context(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    initial_request = _request_with_messages(["Initial economic hypothesis."])
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=initial_request,
        catalogs=[catalog],
    )
    catalog_summary = json.loads(
        (workspace / "identity" / "data_catalog_summary.json").read_text(
            encoding="utf-8"
        )
    )
    knowledge_summary = json.loads(
        (workspace / "identity" / "factor_knowledge_summary.json").read_text(
            encoding="utf-8"
        )
    )
    extended_request = _request_with_messages(
        ["Initial economic hypothesis.", "Keep the frozen evidence and revise one mechanism field."]
    )
    initial_contract = build_authoring_contract(
        initial_request,
        catalog_summary=catalog_summary,
        knowledge_summary=knowledge_summary,
    )
    extended_contract = build_authoring_contract(
        extended_request,
        catalog_summary=catalog_summary,
        knowledge_summary=knowledge_summary,
    )
    assert initial_contract == extended_contract

    mutated_request = dict(extended_request)
    mutated_request["hypothesis"] = "A different economic hypothesis."
    mutated_contract = build_authoring_contract(
        mutated_request,
        catalog_summary=catalog_summary,
        knowledge_summary=knowledge_summary,
    )
    assert mutated_contract != initial_contract


def test_resume_checkpoint_requires_job_scoped_parent_attestation(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    initial_request = _request_with_messages(["Initial economic hypothesis."])
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=initial_request,
        catalogs=[catalog],
    )
    persisted_request = json.loads(
        (workspace / "identity" / "web_research_request.json").read_text(
            encoding="utf-8"
        )
    )
    extended_request = _request_with_messages(
        ["Initial economic hypothesis.", "Append one decision."]
    )
    with pytest.raises(RuntimeError, match="CONVERSATION_LEDGER_INVALID"):
        plan_conversation_checkpoints(
            workspace,
            job_id=str(initial_request["job_id"]),
            messages=extended_request["conversation_snapshot"]["messages"],
            existing_request=persisted_request,
            parent_attestation_id=(
                "attestations/job_other/attestation_wrong_parent.json"
            ),
            parent_attestation_sha256="a" * 64,
        )


def test_checkpoint_directory_symlink_blocks_without_external_side_effect(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    outside = tmp_path / "outside-ledger"
    outside.mkdir(mode=0o755)
    identity = workspace / "identity"
    identity.mkdir(parents=True, exist_ok=True)
    (identity / "conversation_ledger").symlink_to(
        outside,
        target_is_directory=True,
    )
    mode_before = stat.S_IMODE(outside.stat().st_mode)

    with pytest.raises(RuntimeError, match="CONVERSATION_LEDGER_INVALID"):
        write_web_research_packet(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            request=_request(),
            catalogs=[catalog],
        )
    assert stat.S_IMODE(outside.stat().st_mode) == mode_before
    assert list(outside.iterdir()) == []

    write_planned_checkpoints(workspace, [])
    assert stat.S_IMODE(outside.stat().st_mode) == mode_before


def test_authoring_preflight_reports_exact_host_contract_reference(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    contract = json.loads(
        (workspace / "identity" / "web_research_authoring_contract.json").read_text(
            encoding="utf-8"
        )
    )
    expected_hash = stable_json_hash(contract)
    plan["authoring_contract"]["sha256"] = expected_hash[:-2]

    with pytest.raises(WebResearchPlanError) as invalid:
        validate_plan(plan, workspace=workspace)

    assert invalid.value.token == BLOCK_PLAN_INVALID
    assert (
        f"authoring_contract.sha256_expected:{expected_hash}"
        in invalid.value.reasons
    )


def test_authoring_preflight_blocks_v5_style_prose_aliases_and_bad_enums(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["research_object"]["formula_or_law"] = (
        "mul(abs(sub(div(open, pre_close), 1)), sign(sub(close, open)))"
    )
    plan["data_plan"]["daily_fields"] = [
        "signal fields (formula inputs): open, close, pre_close"
    ]
    plan["implementation"]["operators"] = ["div", "sub", "abs", "sign", "mul"]
    plan["economic_mechanism"]["return_source_family"] = "behavioral reversal"
    plan["economic_mechanism"]["claim_class"] = "rank predictive"
    plan["evidence_policy"]["is_end"] = plan["evidence_policy"]["oos_end"]
    plan_path = workspace / "identity" / "web_research_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/validate_factorforge_web_research_plan.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(plan_path),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 1
    result = json.loads(proc.stderr)
    assert result["verdict"] == "BLOCK"
    reasons = result["block_reasons"]
    assert any(reason.startswith("data_plan.daily_fields_not_in_clean_daily_bar") for reason in reasons)
    assert any(reason.startswith("implementation.formula_ir:") for reason in reasons)
    assert "economic_mechanism.return_source_family" in reasons
    assert "economic_mechanism.claim_class" in reasons
    assert "evidence_policy.window_order" in reasons


def test_authoring_contract_and_web_operator_subset_are_fail_closed(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["research_object"]["formula_or_law"] = "signedpower(open, 2)"
    plan["data_plan"]["daily_fields"] = ["open"]
    plan["implementation"]["operators"] = ["signedpower"]

    with pytest.raises(WebResearchPlanError) as unsupported:
        validate_plan(plan, workspace=workspace)
    assert unsupported.value.token == BLOCK_PLAN_INVALID
    assert "implementation.web_operator_unsupported:signedpower" in unsupported.value.reasons

    plan["research_object"]["formula_or_law"] = "mean(close, 2.5)"
    plan["data_plan"]["daily_fields"] = ["close"]
    plan["implementation"]["operators"] = ["mean"]
    with pytest.raises(WebResearchPlanError) as fractional_window:
        validate_plan(plan, workspace=workspace)
    assert any(
        "BLOCK_OPERATOR_WINDOW_NOT_INTEGER: mean" in reason
        for reason in fractional_window.value.reasons
    )

    plan["research_object"]["formula_or_law"] = "ts_mean(close, 5)"
    with pytest.raises(WebResearchPlanError) as alias:
        validate_plan(plan, workspace=workspace)
    assert "implementation.web_operator_alias_forbidden:ts_mean->mean" in alias.value.reasons

    for invalid_constant in ("True", "1e309"):
        plan["research_object"]["formula_or_law"] = f"close + {invalid_constant}"
        plan["implementation"]["operators"] = ["plus"]
        with pytest.raises(WebResearchPlanError) as constant:
            validate_plan(plan, workspace=workspace)
        assert any(
            "BLOCK_FORMULA_CONSTANT_INVALID" in reason
            for reason in constant.value.reasons
        )

    contract_path = workspace / "identity" / "web_research_authoring_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["daily_field_contract"]["allowed_columns"].append("invented_field")
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(WebResearchPlanError) as tampered:
        validate_plan(_fill_plan(workspace), workspace=workspace)
    assert tampered.value.token == "BLOCK_FACTORFORGE_WEB_RESEARCH_PLAN_IDENTITY_INVALID"
    assert "web research authoring contract does not match host inputs" in tampered.value.reasons


def test_constraint_driven_return_source_materializes_and_passes_step1(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["economic_mechanism"]["return_source_family"] = (
        "constraint_driven_arbitrage"
    )
    plan_path = workspace / "identity" / "web_research_plan.json"
    plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    env = {**os.environ, "FACTORFORGE_STATE_CATALOG": str(catalog)}

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(plan_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    alpha_idea = json.loads(
        (
            workspace
            / "objects"
            / "alpha_idea_master"
            / "alpha_idea_master__WEB_REPORT.json"
        ).read_text(encoding="utf-8")
    )
    discipline = alpha_idea["research_discipline"]
    assert discipline["economic_hypothesis"]["macro_return_source"] == (
        "constraint_driven_arbitrage"
    )
    assert discipline["market_process_thesis"]["return_source_family"] == (
        "constraint_driven_arbitrage"
    )


def test_agent_authored_plan_materializes_formal_step1_step2_and_protocol(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)

    env = os.environ.copy()
    env["FACTORFORGE_STATE_CATALOG"] = str(catalog)
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(workspace / "identity" / "web_research_plan.json"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout
    result = json.loads(proc.stdout)
    assert result["verdict"] == "PASS"
    assert result["semantic_projection_only"] is True
    assert result["empirical_evidence_created"] is False
    spec = json.loads(
        (workspace / "objects" / "factor_spec_master" / "factor_spec_master__WEB_REPORT.json").read_text(
            encoding="utf-8"
        )
    )
    assert spec["implementation_mode"] == "operator"
    assert spec["implementation_contract"]["code_contract"] is None
    assert spec["canonical_spec"]["formula_ir"]["parse_status"] == "success"
    assert result["trusted_codegen_only"] is True
    assert result["agent_authored_formula_hash"] == spec["canonical_spec"]["formula_ir"]["formula_hash"]
    attested = validate_materialized_web_research(workspace)
    assert attested["formula_hash"] == result["agent_authored_formula_hash"]
    assert spec["knowledge_reference_contract"]["summary_sha256"]
    assert spec["knowledge_reference_contract"]["cited_node_ids"] == plan["knowledge_use"]["cited_node_ids"]
    knowledge_summary = json.loads(
        (workspace / "identity" / "factor_knowledge_summary.json").read_text(
            encoding="utf-8"
        )
    )
    query = web_knowledge_query_text(_request())
    knowledge_contract = spec["knowledge_reference_contract"]
    assert knowledge_contract["query_hash"] == stable_hash(query)
    assert knowledge_contract["query_terms"] == sorted(tokens(query))[:40]
    assert knowledge_contract["index_paths_checked"] == knowledge_summary[
        "retrieval_provenance"
    ]["index_paths_checked"]
    assert "identity/factor_knowledge_summary.json" not in knowledge_contract[
        "index_paths_checked"
    ]
    assert {item["role"] for item in knowledge_contract["index_metadata"]} == {
        "node",
        "edge",
    }
    assert spec["evaluation_contract"] == {
        "version": "factorforge_web_evaluation_contract_v2",
        "rebalance_frequency": "daily",
        "signal_timestamp_policy": "after_close_t",
        "position_entry_policy": "close_t_plus_1",
        "availability_lags": plan["data_plan"]["availability_lags"],
        "missing_data_policy": plan["data_plan"]["missing_data_policy"],
        "forward_horizon": "1d",
        "label_policy": {
            "horizon": "one_trading_day_after_execution",
            "return_type": "simple",
            "entry_price_field": "close",
            "exit_price_field": "close",
            "execution_lag_sessions": 1,
            "holding_period_sessions": 1,
            "return_window": "close_t_plus_1_to_close_t_plus_2",
        },
        "transaction_cost_bps": 30.0,
        "cost_model_id": "factorforge_step4_turnover_30bps_v1",
        "cost_formula": "one_way_turnover * 0.003",
        "proof_control_columns": [],
    }
    conjecture = json.loads(
        (workspace / "objects" / "research_protocol" / "research_conjecture__WEB_REPORT.json").read_text(
            encoding="utf-8"
        )
    )
    assert conjecture["claim_level"] == "math_framed"
    assert {item["kind"] for item in conjecture["hypotheses"]} == {"preferred", "null", "alternative"}


def test_plan_identity_mismatch_blocks_before_materialization(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["identity"]["job_id"] = "job_0000000000"

    try:
        validate_plan(plan, workspace=workspace)
    except WebResearchPlanError as exc:
        assert exc.token == BLOCK_PLAN_INVALID
        assert "identity.job_id" in exc.reasons
    else:
        raise AssertionError("plan identity mismatch must block")


def test_coordinated_request_and_knowledge_query_tamper_blocks(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    request_path = workspace / "identity" / "web_research_request.json"
    summary_path = workspace / "identity" / "factor_knowledge_summary.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    request["title"] = "Tampered opening pressure"
    request["hypothesis"] = "Tampered coordinated hypothesis."
    query = " ".join(
        str(request.get(field) or "")
        for field in ("title", "hypothesis", "factor_id")
    ).strip()
    summary["retrieval_provenance"]["query"]["text"] = query
    summary["retrieval_provenance"]["query_hash"] = stable_hash(query)
    summary["retrieval_provenance"]["query_terms"] = sorted(tokens(query))[:40]
    plan["research_object"]["title"] = request["title"]
    plan["research_object"]["hypothesis"] = request["hypothesis"]
    plan["knowledge_use"]["summary_sha256"] = stable_json_hash(summary)
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(WebResearchPlanError) as blocked:
        validate_plan(plan, workspace=workspace)
    assert blocked.value.token == "BLOCK_FACTORFORGE_WEB_RESEARCH_PLAN_IDENTITY_INVALID"
    assert "web research authoring contract does not match host inputs" in blocked.value.reasons


def test_coordinated_knowledge_index_provenance_tamper_blocks(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    summary_path = workspace / "identity" / "factor_knowledge_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    fake_paths = ["/tmp/fake_nodes.jsonl", "/tmp/fake_edges.jsonl"]
    provenance = summary["retrieval_provenance"]
    provenance["index_paths_checked"] = fake_paths
    provenance["indexes_available"] = fake_paths
    for item, fake_path in zip(provenance["indexes"], fake_paths, strict=True):
        item.update(
            {
                "path": fake_path,
                "available": True,
                "regular_file": True,
                "sha256": "0" * 64,
            }
        )
    plan["knowledge_use"]["summary_sha256"] = stable_json_hash(summary)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(WebResearchPlanError) as blocked:
        validate_plan(plan, workspace=workspace)
    assert blocked.value.token == "BLOCK_FACTORFORGE_WEB_RESEARCH_PLAN_IDENTITY_INVALID"
    assert "web research authoring contract does not match host inputs" in blocked.value.reasons


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            lambda plan: plan["research_object"].update(
                {"rebalance_frequency": "weekly"}
            ),
            "research_object.rebalance_frequency_unsupported",
        ),
        (
            lambda plan: plan["evidence_policy"].update(
                {"forward_horizon": "5d"}
            ),
            "evidence_policy.forward_horizon_request_mismatch",
        ),
        (
            lambda plan: plan["evidence_policy"].update(
                {"transaction_cost_bps": 10.0}
            ),
            "evidence_policy.transaction_cost_bps_request_mismatch",
        ),
    ],
)
def test_plan_rejects_evaluation_contract_mismatch(
    tmp_path,
    mutation,
    expected_reason,
):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    mutation(plan)

    with pytest.raises(WebResearchPlanError) as failure:
        validate_plan(plan, workspace=workspace)

    assert expected_reason in failure.value.reasons


def test_configured_catalog_hash_mismatch_blocks_before_step1_write(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    _fill_plan(workspace)
    other_catalog = tmp_path / "other_catalog.json"
    other_catalog.write_text('{"datasets": {}}\n', encoding="utf-8")
    env = os.environ.copy()
    env["FACTORFORGE_STATE_CATALOG"] = str(other_catalog)

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(workspace / "identity" / "web_research_plan.json"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert proc.returncode == 1
    assert "BLOCK_FACTORFORGE_WEB_RESEARCH_CATALOG_INVALID" in proc.stderr
    assert not (workspace / "objects" / "alpha_idea_master" / "alpha_idea_master__WEB_REPORT.json").exists()


def test_conflicting_catalog_environment_variables_block(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    other_catalog = tmp_path / "other_catalog.json"
    other_catalog.write_text('{"datasets": []}\n', encoding="utf-8")

    try:
        resolve_workspace_approved_catalog(
            workspace,
            environ={
                "FACTORFORGE_STATE_CATALOG": str(catalog),
                "FACTORFORGE_DATA_CATALOG": str(other_catalog),
            },
        )
    except WebResearchPlanError as exc:
        assert exc.token == "BLOCK_FACTORFORGE_WEB_RESEARCH_CATALOG_INVALID"
    else:
        raise AssertionError("catalog environment override must block")


def test_web_plan_rejects_non_formula_io_syntax_without_reading_python(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["research_object"]["formula_or_law"] = "read_fwf('/proc/self/environ')"

    try:
        validate_plan(plan, workspace=workspace)
    except WebResearchPlanError as exc:
        assert any(reason.startswith("implementation.formula_ir:") for reason in exc.reasons)
    else:
        raise AssertionError("non-Formula-IR I/O syntax must block")


def test_web_plan_rejects_raw_minute_inputs_until_executor_v2(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["data_plan"]["minute_fields"] = ["close"]

    try:
        validate_plan(plan, workspace=workspace)
    except WebResearchPlanError as exc:
        assert "data_plan.minute_fields_require_web_executor_v2" in exc.reasons
    else:
        raise AssertionError("raw-minute web execution must block in v1")


def test_host_materialization_check_rejects_custom_agent_python(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    _fill_plan(workspace)
    env = os.environ.copy()
    env["FACTORFORGE_STATE_CATALOG"] = str(catalog)
    subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(workspace / "identity" / "web_research_plan.json"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    )
    (workspace / "step2" / "agent_factor.py").write_text(
        "raise RuntimeError('must never execute')\n",
        encoding="utf-8",
    )

    try:
        validate_materialized_web_research(workspace)
    except WebResearchPlanError as exc:
        assert "step2.agent_factor_custom_code_forbidden" in exc.reasons
    else:
        raise AssertionError("host materialization attestation must reject custom Python")

    wrapper = subprocess.run(
        [
            sys.executable,
            "scripts/run_factorforge_ultimate.py",
            "--report-id",
            "WEB_REPORT",
            "--start-step",
            "3",
            "--end-step",
            "all",
            "--factorforge-root",
            str(tmp_path / "runtime"),
            "--factor-id",
            "WEB_FACTOR",
            "--research-id",
            "web_research",
            "--factor-workspace",
            str(workspace),
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert wrapper.returncode == 1
    assert "step2.agent_factor_custom_code_forbidden" in wrapper.stdout


def test_host_atomic_writer_rejects_agent_symlink_destination(tmp_path):
    workspace = tmp_path / "workspace"
    identity = workspace / "identity"
    identity.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("unchanged\n", encoding="utf-8")
    destination = identity / "web_research_request.json"
    destination.symlink_to(outside)

    try:
        write_text_atomic(destination, "mutated\n", root=workspace)
    except RuntimeError as exc:
        assert "unsafe atomic-write destination" in str(exc)
    else:
        raise AssertionError("host-owned packet write must reject symlinks")
    assert outside.read_text(encoding="utf-8") == "unchanged\n"


def test_host_atomic_writer_accepts_macos_var_alias(tmp_path):
    resolved = str(tmp_path.resolve())
    if not resolved.startswith("/private/var/"):
        pytest.skip("macOS /var alias is not present")
    alias_root = Path("/var") / Path(resolved).relative_to("/private/var")
    destination = alias_root / "identity" / "packet.json"
    destination.parent.mkdir(parents=True, exist_ok=True)

    write_text_atomic(destination, "bound\n", root=alias_root)

    assert destination.read_text(encoding="utf-8") == "bound\n"


def test_plan_cannot_cite_knowledge_node_outside_operator_summary(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    plan = _fill_plan(workspace)
    plan["knowledge_use"]["cited_node_ids"] = ["invented_knowledge_node"]
    plan["knowledge_use"]["cold_start"] = False

    try:
        validate_plan(plan, workspace=workspace)
    except WebResearchPlanError as exc:
        assert exc.token == BLOCK_PLAN_INVALID
        assert any(reason.startswith("knowledge_use.") for reason in exc.reasons)
    else:
        raise AssertionError("invented knowledge provenance must block")


def test_passed_materialization_is_idempotent_and_preregistration_is_immutable(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=_request(),
        catalogs=[catalog],
    )
    _fill_plan(workspace)
    command = [
        sys.executable,
        "scripts/materialize_factorforge_web_research.py",
        "--workspace-root",
        str(workspace),
        "--plan",
        str(workspace / "identity" / "web_research_plan.json"),
    ]
    env = {**os.environ, "FACTORFORGE_STATE_CATALOG": str(catalog)}
    first = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert first.returncode == 0, first.stderr

    state_path = (
        workspace
        / "objects"
        / "research_protocol"
        / "research_state__WEB_REPORT.json"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["budget_used"]["trials_used"] = 7
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    repeated = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["idempotent_reuse"] is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["budget_used"]["trials_used"] == 7

    plan_path = workspace / "identity" / "web_research_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    next(item for item in plan["hypotheses"] if item["kind"] == "preferred")[
        "claim"
    ] = "post-evidence rewritten preferred claim"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    rewritten = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert rewritten.returncode == 1
    assert "BLOCK_FACTORFORGE_WEB_RESEARCH_IMPLEMENTATION_INVALID" in rewritten.stderr


def test_legacy_v1_resume_accepts_only_append_only_conversation_context(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    initial_request = _request_with_messages(["Initial economic hypothesis."])
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=initial_request,
        catalogs=[catalog],
    )
    _fill_plan(workspace)
    env = {**os.environ, "FACTORFORGE_STATE_CATALOG": str(catalog)}
    materialized = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(workspace / "identity" / "web_research_plan.json"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert materialized.returncode == 0, materialized.stderr

    contract_path = workspace / "identity" / "web_research_authoring_contract.json"
    plan_path = workspace / "identity" / "web_research_plan.json"
    bootstrap_path = workspace / "identity" / "web_research_bootstrap_result.json"
    request_path = workspace / "identity" / "web_research_request.json"
    legacy_request = json.loads(request_path.read_text(encoding="utf-8"))
    legacy_request.pop(CONVERSATION_LEDGER_REFERENCE_FIELD)
    request_path.write_text(
        json.dumps(legacy_request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(workspace / "identity" / "conversation_ledger")
    legacy_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    legacy_contract["version"] = "factorforge_web_research_authoring_contract_v1"
    legacy_binding = legacy_contract["host_input_binding"]
    legacy_binding.pop("request_binding_scope")
    legacy_binding["request_sha256"] = stable_json_hash(initial_request)
    contract_path.write_text(
        json.dumps(legacy_contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    legacy_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    legacy_plan["authoring_contract"] = {
        "version": legacy_contract["version"],
        "sha256": stable_json_hash(legacy_contract),
    }
    plan_path.write_text(
        json.dumps(legacy_plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    bootstrap["agent_authored_plan_sha256"] = sha256_file(plan_path)
    bootstrap["host_authoring_contract_sha256"] = sha256_file(contract_path)
    bootstrap["host_request_sha256"] = stable_json_hash(legacy_request)
    bootstrap.pop("host_request_binding_scope", None)
    bootstrap.pop("host_request_binding_sha256", None)
    bootstrap.pop("host_conversation_ledger_checkpoint", None)
    bootstrap_path.write_text(
        json.dumps(bootstrap, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    frozen_contract = contract_path.read_bytes()
    frozen_plan = plan_path.read_bytes()

    extended_request = _request_with_messages(
        ["Initial economic hypothesis.", "Keep frozen evidence; revise only the named mechanism field."]
    )
    extended_request = _bind_resume_checkpoint(workspace, extended_request)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=extended_request,
        catalogs=[catalog],
        preserve_existing_plan=True,
        trusted_resume_start_step="6",
    )
    assert contract_path.read_bytes() == frozen_contract
    assert plan_path.read_bytes() == frozen_plan
    resumed_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert validate_plan(resumed_plan, workspace=workspace)[1]["formula_hash"]

    long_contents = [
        "Initial economic hypothesis.",
        "Keep frozen evidence; revise only the named mechanism field.",
        *[f"Append-only legacy research decision {index}." for index in range(3, 51)],
    ]
    long_request, ledger_messages = _request_with_bounded_history(long_contents)
    long_request = _bind_resume_checkpoint(
        workspace,
        long_request,
        ledger_messages=ledger_messages,
    )
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=long_request,
        catalogs=[catalog],
        preserve_existing_plan=True,
        trusted_resume_start_step="6",
    )
    assert validate_plan(resumed_plan, workspace=workspace)[1]["formula_hash"]

    mutated_request = dict(long_request)
    mutated_request["hypothesis"] = "A different economic hypothesis."
    with pytest.raises(RuntimeError, match="frozen web research authoring contract changed"):
        write_web_research_packet(
            workspace=workspace,
            worktree=PROJECT_ROOT,
            request=mutated_request,
            catalogs=[catalog],
            preserve_existing_plan=True,
            trusted_resume_start_step="6",
        )


def test_resume_packet_and_ultimate_enforce_exact_formal_pause(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    request = _request_with_messages(["Initial economic hypothesis."])
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=request,
        catalogs=[catalog],
    )
    _fill_plan(workspace)
    env = {**os.environ, "FACTORFORGE_STATE_CATALOG": str(catalog)}
    materialized = subprocess.run(
        [
            sys.executable,
            "scripts/materialize_factorforge_web_research.py",
            "--workspace-root",
            str(workspace),
            "--plan",
            str(workspace / "identity" / "web_research_plan.json"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert materialized.returncode == 0, materialized.stderr
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / "ultimate_run_report__WEB_REPORT.json"
    )
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(
        json.dumps({"status": "PAUSED", "failure": None}) + "\n",
        encoding="utf-8",
    )
    assert required_web_resume_start_step(workspace, "WEB_REPORT") == "6"

    extended_request = _request_with_messages(
        ["Initial economic hypothesis.", "Revise only the paused mechanism artifact."]
    )
    extended_request = _bind_resume_checkpoint(workspace, extended_request)
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=extended_request,
        catalogs=[catalog],
        preserve_existing_plan=True,
        trusted_resume_start_step="6",
    )
    assert validate_materialized_web_research(workspace)["formula_hash"]
    request_path = workspace / "identity" / "web_research_request.json"
    valid_request_bytes = request_path.read_bytes()
    plan = json.loads(
        (workspace / "identity" / "web_research_plan.json").read_text(
            encoding="utf-8"
        )
    )

    current_reference = extended_request[CONVERSATION_LEDGER_REFERENCE_FIELD]
    current_checkpoint = workspace / current_reference["path"]
    branch_checkpoint = current_checkpoint.with_name(
        f"checkpoint__000003__{current_reference['root_sha256']}.json"
    )
    shutil.copyfile(current_checkpoint, branch_checkpoint)
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_plan(plan, workspace=workspace)
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_materialized_web_research(workspace)
    branch_checkpoint.unlink()

    current_checkpoint_payload = json.loads(
        current_checkpoint.read_text(encoding="utf-8")
    )
    ancestor_checkpoint = workspace / current_checkpoint_payload["parent_checkpoint"][
        "path"
    ]
    ancestor_backup = workspace / "identity" / "conversation_ancestor.backup"
    ancestor_checkpoint.rename(ancestor_backup)
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_materialized_web_research(workspace)
    ancestor_backup.rename(ancestor_checkpoint)

    renamed_checkpoint = current_checkpoint.with_name(
        f"checkpoint__000003__{current_reference['root_sha256']}.json"
    )
    current_checkpoint.rename(renamed_checkpoint)
    renamed_reference_request = json.loads(valid_request_bytes)
    renamed_reference_request[CONVERSATION_LEDGER_REFERENCE_FIELD] = {
        **current_reference,
        "path": renamed_checkpoint.relative_to(workspace).as_posix(),
    }
    request_path.write_text(
        json.dumps(renamed_reference_request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_materialized_web_research(workspace)
    renamed_checkpoint.rename(current_checkpoint)
    request_path.write_bytes(valid_request_bytes)

    divergent_request = _request_with_messages(
        ["Initial economic hypothesis.", "Replacement decision that was never appended."]
    )
    divergent_request[CONVERSATION_LEDGER_REFERENCE_FIELD] = extended_request[
        CONVERSATION_LEDGER_REFERENCE_FIELD
    ]
    request_path.write_text(
        json.dumps(divergent_request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_plan(plan, workspace=workspace)
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_materialized_web_research(workspace)

    missing_history_request = dict(divergent_request)
    missing_history_request.pop("conversation_snapshot")
    missing_history_request.pop("conversation_snapshot_sha256")
    missing_history_request.pop(CONVERSATION_LEDGER_REFERENCE_FIELD)
    request_path.write_text(
        json.dumps(missing_history_request, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_plan(plan, workspace=workspace)
    with pytest.raises(WebResearchPlanError, match="CONVERSATION_LEDGER_INVALID"):
        validate_materialized_web_research(workspace)
    request_path.write_bytes(valid_request_bytes)

    full_contents = [
        "Initial economic hypothesis.",
        "Revise only the paused mechanism artifact.",
        *[f"Append-only research decision {index}." for index in range(3, 51)],
    ]
    bounded_request, ledger_messages = _request_with_bounded_history(full_contents)
    bounded_request = _bind_resume_checkpoint(
        workspace,
        bounded_request,
        ledger_messages=ledger_messages,
    )
    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=bounded_request,
        catalogs=[catalog],
        preserve_existing_plan=True,
        trusted_resume_start_step="6",
    )
    assert validate_materialized_web_research(workspace)["formula_hash"]
    bootstrap = json.loads(
        (
            workspace / "identity" / "web_research_bootstrap_result.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        bootstrap["host_request_binding_scope"]
        == "immutable_authoring_request_v1"
    )
    assert bootstrap["host_request_binding_sha256"]

    guide = (workspace / "identity" / "web_research_runtime.md").read_text(
        encoding="utf-8"
    )
    assert "host_resume_start_step: 6" in guide
    assert "host_resume_start_step: 3" not in guide
    assert "Do not invoke the materializer" in guide

    wrong_resume = subprocess.run(
        [
            sys.executable,
            "scripts/run_factorforge_ultimate.py",
            "--report-id",
            "WEB_REPORT",
            "--start-step",
            "3",
            "--end-step",
            "all",
            "--factorforge-root",
            str(tmp_path / "runtime"),
            "--factor-id",
            "WEB_FACTOR",
            "--research-id",
            "web_research",
            "--factor-workspace",
            str(workspace),
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert wrong_resume.returncode == 1
    assert "BLOCK_FACTORFORGE_WEB_RESEARCH_RESUME_POINT_INVALID" in wrong_resume.stdout

    correct_command = list(wrong_resume.args)
    correct_command[correct_command.index("3")] = "6"
    correct_resume = subprocess.run(
        correct_command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert correct_resume.returncode == 0, correct_resume.stderr or correct_resume.stdout
    archives = list(
        proof_path.parent.glob("ultimate_run_report__WEB_REPORT__prior_*.json")
    )
    assert len(archives) == 1
    assert json.loads(archives[0].read_text(encoding="utf-8"))["status"] == "PAUSED"


@pytest.mark.parametrize(
    ("status", "command", "expected_step"),
    [
        ("BLOCK_DATA_REQUEST_PENDING", "run_step3", "3"),
        ("BLOCK_DATA_REQUEST_PENDING", "run_step4", "4"),
        ("FAIL", "validate_research_protocol_pre_council", "3"),
        ("FAIL", "finalize_web_factor_proof", "4"),
        ("FAIL", "run_step5", "5"),
    ],
)
def test_resume_mapping_preserves_actual_failed_stage(
    tmp_path,
    status,
    command,
    expected_step,
):
    workspace = _workspace(tmp_path)
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / "ultimate_run_report__WEB_REPORT.json"
    )
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(
        json.dumps(
            {
                "status": status,
                "failure": {"command": command, "returncode": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert required_web_resume_start_step(workspace, "WEB_REPORT") == expected_step
