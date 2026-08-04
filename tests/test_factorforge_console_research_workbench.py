from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


REPORT_ID = "WEB_RESEARCH_WORKBENCH_001"


def test_math_renderer_emits_sanitized_mathml(monkeypatch) -> None:
    from factor_factory.console import math_render

    class FakeConverter:
        @staticmethod
        def convert(_expression: str) -> str:
            return (
                '<math xmlns="http://www.w3.org/1998/Math/MathML" onclick="bad()">'
                '<semantics><mrow><mi style="color:red" href="bad">x</mi>'
                '<mo>=</mo><msup><mi>y</mi><mn>2</mn></msup></mrow>'
                '<annotation encoding="application/x-tex">x=y^2</annotation>'
                '</semantics></math>'
            )

    monkeypatch.setattr(math_render, "_latex_converter", FakeConverter())
    rendered = math_render.render_latex_math(r"x=y^2")

    assert "<math" in rendered
    assert "<msup>" in rendered
    assert "annotation" not in rendered
    assert "onclick" not in rendered
    assert "style=" not in rendered
    assert "href=" not in rendered


def test_math_renderer_fallback_escapes_unparsed_source(monkeypatch) -> None:
    from factor_factory.console import math_render

    monkeypatch.setattr(math_render, "_latex_converter", None)
    rendered = math_render.render_latex_math(r"<script>alert(1)</script> + \lambda_t")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_research_messages_persist_in_order_and_are_idempotent(tmp_path: Path) -> None:
    from factor_factory.console.models import ResearchRequest
    from factor_factory.console.store import ResearchJobStore

    state_root = tmp_path / "state"
    store = ResearchJobStore(state_root)
    job = store.create_job(
        ResearchRequest(
            title="Crowding state",
            hypothesis="Crowded liquidity demand may create a transient payoff.",
            model="deepseek-v4-flash",
        )
    )
    first = store.list_messages(job.job_id)
    assert [item.sequence_no for item in first] == [1]
    assert first[0].content_kind == "hypothesis"

    message = store.add_message(
        job.job_id,
        content_kind="formula",
        content=r"E[R_{t+1} | F_t, C_t]",
        model="deepseek-v4-flash",
        idempotency_key="browser-request-1",
    )
    duplicate = store.add_message(
        job.job_id,
        content_kind="formula",
        content=r"E[R_{t+1} | F_t, C_t]",
        model="deepseek-v4-flash",
        idempotency_key="browser-request-1",
    )
    assert duplicate.message_id == message.message_id
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        store.add_message(
            job.job_id,
            content_kind="formula",
            content="a conflicting retry must not be discarded silently",
            model="deepseek-v4-flash",
            idempotency_key="browser-request-1",
        )

    reopened = ResearchJobStore(state_root)
    messages = reopened.list_messages(job.job_id)
    assert [item.sequence_no for item in messages] == [1, 2]
    assert messages[1].content == r"E[R_{t+1} | F_t, C_t]"
    from factor_factory.console.run_service import _conversation_snapshot
    from factor_factory.console.web_research_plan import stable_json_hash

    snapshot = _conversation_snapshot(reopened, job)
    unsigned = {key: value for key, value in snapshot.items() if key != "sha256"}
    assert snapshot["sha256"] == stable_json_hash(unsigned)
    assert [item["sequence_no"] for item in snapshot["messages"]] == [1, 2]
    assert "idempotency_key" not in snapshot["messages"][0]

    with pytest.raises(ValueError, match="must not contain"):
        reopened.add_message(
            job.job_id,
            content_kind="code",
            content="api_key=sk-secretvalue123456789",
            idempotency_key="browser-request-2",
        )


def test_existing_job_request_is_backfilled_into_chatbox(tmp_path: Path) -> None:
    from factor_factory.console.models import ResearchRequest
    from factor_factory.console.store import ResearchJobStore

    state_root = tmp_path / "state"
    store = ResearchJobStore(state_root)
    job = store.create_job(
        ResearchRequest(
            title="Legacy request",
            hypothesis="Original hypothesis survives the workbench migration.",
            model="deepseek-v4-flash",
        )
    )
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM research_messages WHERE job_id=?", (job.job_id,))

    migrated_store = ResearchJobStore(state_root)
    messages = migrated_store.list_messages(job.job_id)

    assert len(messages) == 1
    assert messages[0].content == "Original hypothesis survives the workbench migration."
    assert messages[0].idempotency_key == f"initial:{job.job_id}"


def test_conversation_snapshot_declares_truncated_history(tmp_path: Path) -> None:
    from factor_factory.console.models import ResearchRequest
    from factor_factory.console.run_service import _conversation_snapshot
    from factor_factory.console.store import ResearchJobStore

    store = ResearchJobStore(tmp_path / "state")
    job = store.create_job(
        ResearchRequest(title="Long history", hypothesis="initial hypothesis")
    )
    for index, content in enumerate(("a" * 20_000, "b" * 20_000, "latest")):
        store.add_message(
            job.job_id,
            content_kind="decision",
            content=content,
            idempotency_key=f"long-history-{index}",
        )

    snapshot = _conversation_snapshot(store, job)
    total_count, latest_messages = store.snapshot_messages(job.job_id, limit=2)

    assert snapshot["total_message_count"] == 4
    assert snapshot["message_count"] == 3
    assert snapshot["omitted_message_count"] == 1
    assert snapshot["content_truncated"] is True
    assert snapshot["history_complete"] is False
    assert snapshot["included_character_count"] == 40_000
    assert total_count == 4
    assert [message.sequence_no for message in latest_messages] == [3, 4]


def test_reader_projects_current_agent_notebooks_and_formal_backtest_tables(
    tmp_path: Path,
) -> None:
    from factor_factory.console.ultimate_reader import read_ultimate_workspace

    workspace = tmp_path / "workspace"
    _write_json(
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "research_id": "research_001",
            "status": "RUNNING",
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_protocol"
        / f"research_quality_gate__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "economic_mechanism_contract": {"preferred_claim": "generic old contract"},
            "mathematical_object_contract": {"target_statistic": "generic statistic"},
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / f"main_agent_mechanism_memo__{REPORT_ID}.json",
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "research_id": "research_001",
            "producer": "current_main_agent",
            "agent_authorship": {
                "authoring_mode": "current_agent_freeform",
                "agent_role": "main_agent",
                "answered_without_deterministic_template": True,
            },
            "revision_number": 3,
            "formula": r"<script>alert(1)</script> + \mathbb E[R_{t+1}\mid\mathcal F_t]",
            "economic_hypothesis": {
                "return_source_class": "market_structure_arbitrage",
                "payer_or_counterparty": "forced liquidity demanders",
                "why_they_pay": "binding funding pressure makes execution inelastic",
                "necessary_market_structure": "funding deadlines cluster in event time",
            },
            "math_hypothesis": {
                "selected_model_family": "marked_point_process",
                "why_this_model": "forced trades arrive as clustered marked events",
                "random_object": "marked liquidation event process",
                "latent_state": "funding-pressure intensity",
                "process_or_distribution": r"dN_t \sim Poisson(\lambda_t dt)",
                "target_functional": r"\mathbb E[R_{t+1}\mid\mathcal F_t,\lambda_t]",
                "formula_as_estimator": "observable imbalance estimates lambda_t",
                "expected_metric_signature": {"rank_ic": "positive and regime-local"},
            },
            "math_model_selection": {
                "model_family": "marked_point_process",
                "baseline_model": r"dN_t \sim Poisson(\lambda_t dt)",
                "model_mutation": "allow self-excitation around clustered deadlines",
            },
            "formula_state_estimator": {
                "latent_state": "funding-pressure intensity",
                "observable_mapping": "signed turnover shock maps to lambda_t",
            },
            "formula_component_map": [
                {
                    "component_id": "pressure_proxy",
                    "observable_estimator": "signed turnover shock",
                    "economic_state": "forced-sale intensity",
                }
            ],
            "evidence_comparison": {
                "mechanism_supported": "partial",
                "contradictions": ["payer timing is not yet directly observed"],
            },
            "falsification_tests": ["kill if payer-aligned event windows do not strengthen"],
            "council_questions": ["Does Hawkes excitation improve the metric signature?"],
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / f"main_agent_mechanism_memo__{REPORT_ID}_foreign.json",
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "report_id": REPORT_ID,
            "factor_id": "FOREIGN_ALPHA",
            "research_id": "foreign_research",
            "producer": "current_main_agent",
            "agent_authorship": {
                "authoring_mode": "current_agent_freeform",
                "agent_role": "main_agent",
                "answered_without_deterministic_template": True,
            },
            "revision_number": 99,
            "economic_hypothesis": {
                "payer_or_counterparty": "foreign payer"
            },
            "math_hypothesis": {"selected_model_family": "foreign_model"},
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / f"main_agent_mechanism_memo__{REPORT_ID}_older.json",
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "research_id": "research_001",
            "producer": "current_main_agent",
            "revision_number": 2,
            "economic_hypothesis": {
                "payer_or_counterparty": "superseded generic payer"
            },
            "math_hypothesis": {"selected_model_family": "superseded_model"},
        },
    )
    _write_json(
        workspace
        / "objects"
        / "validation"
        / f"factor_evaluation__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "metrics": {
                "rank_ic_mean": 0.021,
                "long_side_final_nav": 1.32,
                "cost_adjusted_long_side_final_nav": 1.1025,
            },
        },
    )
    evaluation = workspace / "evaluations" / REPORT_ID / "self_quant_analyzer"
    evaluation.mkdir(parents=True)
    (evaluation / "long_side_nav.csv").write_text(
        "datetime,long_side_nav,cost_adjusted_long_side_nav\n"
        "2025-12-31,1.32,1.1025\n"
        "2024-01-02,1.0,1.0\n"
        "2024-12-31,1.1,1.05\n",
        encoding="utf-8",
    )
    for filename in (
        "long_side_nav.png",
        "cost_adjusted_long_side_nav.png",
        "quantile_nav_10groups.png",
        "rank_ic_timeseries.png",
    ):
        (evaluation / filename).write_bytes(b"formal-chart-evidence")

    summary = read_ultimate_workspace(workspace, report_id=REPORT_ID)

    assert summary.research_method["source_kind"] == "current_main_agent_memo"
    assert summary.economic_game["payer_or_counterparty"] == "forced liquidity demanders"
    assert summary.math_mechanism["selected_model_family"] == "marked_point_process"
    assert summary.research_notebook["revision_number"] == 3
    assert summary.math_notebook["equations"][0]["title"] == "Factor law"
    assert summary.backtest_center["module_status"]["gross_net_nav"] == "available"
    assert summary.backtest_center["module_status"]["annual_returns"] == "available"
    assert summary.backtest_center["annual_returns"] == [
        {"year": 2024, "gross_return": pytest.approx(0.1), "net_return": pytest.approx(0.05)},
        {"year": 2025, "gross_return": pytest.approx(0.2), "net_return": pytest.approx(0.05)},
    ]
    assert summary.backtest_center["consistency"]["status"] == "PASS"


def test_reader_rejects_nonformal_main_agent_role(tmp_path: Path) -> None:
    from factor_factory.console.ultimate_reader import (
        BLOCK_EVIDENCE_LINEAGE_MISMATCH,
        read_ultimate_workspace,
    )

    workspace = tmp_path / "workspace"
    _write_json(
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "research_id": "research_001",
            "status": "RUNNING",
        },
    )
    _write_json(
        workspace
        / "objects"
        / "research_iteration_master"
        / f"main_agent_mechanism_memo__{REPORT_ID}.json",
        {
            "contract_version": "factorforge_main_agent_mechanism_memo_v1",
            "report_id": REPORT_ID,
            "factor_id": "CROWDING_ALPHA",
            "research_id": "research_001",
            "producer": "current_main_agent",
            "agent_authorship": {
                "authoring_mode": "current_agent_freeform",
                "agent_role": "current_main_agent",
                "answered_without_deterministic_template": True,
            },
            "economic_hypothesis": {"payer": "must not be published"},
        },
    )

    summary = read_ultimate_workspace(workspace, report_id=REPORT_ID)

    assert summary.research_method["source_kind"] == "deterministic_fallback"
    assert any(
        item.startswith(f"{BLOCK_EVIDENCE_LINEAGE_MISMATCH}:main_agent_mechanism_memo")
        for item in summary.evidence_errors
    )


def test_workbench_html_exposes_four_surfaces_without_control_plane_log(
    tmp_path: Path,
) -> None:
    from factor_factory.console.models import ResearchRequest
    from factor_factory.console.run_service import build_web_result
    from factor_factory.console.store import ResearchJobStore
    from factor_factory.console.ultimate_reader import UltimateRunSummary
    from factor_factory.console.web_ui import render_job

    store = ResearchJobStore(tmp_path / "state")
    job = store.create_job(
        ResearchRequest(
            title="UI workbench",
            hypothesis="Test <b>escaped</b> research input.",
            model="deepseek-v4-flash",
        )
    )
    summary = UltimateRunSummary(
        report_id=job.report_id,
        factor_id=job.factor_id,
        research_id=job.research_id,
        execution_status="PAUSED",
        protocol_status="PAUSED",
        factor_verdict="ITERATE",
        council_status="PAUSED",
        formal_proof_eligible=False,
        current_stage="awaiting_next_derivation",
        research_notebook={
            "source_label": "CURRENT MAIN AGENT",
            "revision_number": 2,
            "stages": [{"title": "Economic hypothesis", "content": {"payer": "forced seller"}}],
        },
        math_notebook={
            "evidence_class": "AGENT CLAIM",
            "definitions": {"random_object": "R"},
            "equations": [{"title": "Payoff", "expression": r"\mathbb E[R|F]"}],
            "derivation_steps": [],
        },
        backtest_center={
            "evidence_class": "FORMAL UNVERIFIED",
            "validator_verdict": "NOT_RUN",
            "metrics": {"rank_ic": {"mean": 0.02}},
            "charts": {},
            "annual_returns": [],
            "module_status": {"gross_net_nav": "not_produced"},
            "consistency": {"status": "NOT_CHECKED"},
        },
    )
    job.result = build_web_result(summary, publication_id="", public_artifacts=[])
    chart_id = "evaluations/report/self_quant_analyzer/long_side_nav.png"
    job.result["artifacts"] = [
        {"artifact_id": chart_id, "label": "Gross NAV", "kind": "image"}
    ]
    job.result["backtest_center"]["charts"] = {"gross_nav_chart": chart_id}
    job.result["backtest_center"]["consistency"] = {"status": "CONFLICT"}
    html = render_job(job, store.list_messages(job.job_id), "csrf-token")

    assert "Chatbox" in html
    assert "Research Notebook" in html
    assert ">Math<" in html
    assert "回测中心" in html
    assert "任务记录" not in html
    assert "Test &lt;b&gt;escaped&lt;/b&gt; research input." in html
    assert "\\mathbb E[R|F]" in html
    assert "页面不会用汇总指标补画这些结果" in html
    assert "EVIDENCE CONFLICT" in html
    assert "FORMAL EVIDENCE" not in html
