from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from factor_factory.console.web_research_plan import (
    BLOCK_PLAN_INVALID,
    PLACEHOLDER,
    WebResearchPlanError,
    required_web_resume_start_step,
    resolve_workspace_approved_catalog,
    stable_json_hash,
    validate_materialized_web_research,
    validate_plan,
    write_text_atomic,
    write_web_research_packet,
)
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
    return {
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


def _write_catalog(tmp_path: Path) -> Path:
    path = tmp_path / "data_catalog.json"
    path.write_text(
        json.dumps(
            {
                "datasets": [
                    {
                        "dataset_id": "clean_daily_bar",
                        "columns": ["ts_code", "trade_date", "open", "pre_close"],
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
            "random_object": "cross-sectional opening gap and subsequent legal-time forward return panel",
            "latent_state": "unabsorbed opening demand pressure net of permanent information",
            "state_space": "real-valued signed pressure with zero as the absorbed state",
            "process_or_distribution_hypothesis": "conditional forward-return drift decreases with positive transitory opening pressure",
            "observation_equation": "gap_i,t = permanent_news_i,t + temporary_pressure_i,t + epsilon_i,t",
            "factor_estimator": "negative opening gap computed from t open and t-1 close",
            "target_functional": "E[r_i,t+1 | F_open,t, temporary_pressure_i,t]",
            "return_equation": "r_i,t+1 = -beta * temporary_pressure_i,t - cost_i,t + eta_i,t+1",
            "information_set": "previous close and completed day-t market data available by close; position is formed at close t",
            "why_suitable": "the decomposition separates permanent overnight news from temporary opening demand pressure",
            "why_alternatives_are_less_suitable": ["unconditional reversal has no opening-specific state or participant deadline"],
            "alternative_models": ["unconditional reversal", "systematic overnight risk premium"],
            "component_map": [
                {
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
            "affected_price_process_terms": ["conditional drift", "opening observation equation"],
            "expected_return_distribution_change": "lower opening pressure shifts the next-period long-side return distribution upward after costs",
            "expected_metric_signatures": [
                {"metric": "long_side_return", "direction": "positive after cost"},
                {"metric": "rank_ic", "direction": "positive for the negated gap estimator"},
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
        "latent_state_measurement": (
            "Does the opening gap measure temporary pressure rather than permanent news?",
            "residual opening gap is a valid pressure-state estimator",
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
    assert contract["version"] == "factorforge_web_research_authoring_contract_v1"
    assert contract["immutable_host_authored"] is True
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


def test_resume_packet_and_ultimate_enforce_exact_formal_pause(tmp_path):
    workspace = _workspace(tmp_path)
    catalog = _write_catalog(tmp_path)
    request = _request()
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

    write_web_research_packet(
        workspace=workspace,
        worktree=PROJECT_ROOT,
        request=request,
        catalogs=[catalog],
        preserve_existing_plan=True,
        trusted_resume_start_step="6",
    )
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
