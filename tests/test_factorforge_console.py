import json
import threading
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest


CAMPAIGN_ID = "current_data_api_catalog_20260626"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def make_miner_fixture(root: Path) -> Path:
    workspace = root / "factor_research" / "miner" / CAMPAIGN_ID
    _write_json(
        workspace / "objects" / "miner_capability_inventory.json",
        {
            "campaign_id": CAMPAIGN_ID,
            "summary": {
                "data_request_count": 1,
            },
        },
    )
    _write_json(
        workspace / "objects" / "candidates" / "candidate_manifest.json",
        {
            "candidates": [
                {"candidate_id": f"candidate_{idx}", "template_status": status}
                for idx, status in enumerate(
                    ["needs_operator"] * 6 + ["partial"] * 4 + ["needs_data"] * 2,
                    start=1,
                )
            ]
        },
    )
    _write_json(
        workspace / "objects" / "data_gap_report.json",
        {
            "gaps": [{"gap_id": f"gap_{idx}"} for idx in range(46)],
            "data_requests": [{"dataset": "intraday_value_occupation_state_v1"}],
        },
    )
    _write_json(
        workspace / "objects" / "cheap_screen" / "cheap_screen_summary.json",
        {
            "promotion_forbidden_until_formal": True,
            "passed_count": 0,
        },
    )
    _write_json(
        workspace / "objects" / "research_queue" / "research_queue.json",
        {
            "queue": [],
        },
    )
    return workspace


def test_campaign_summary_round_trip():
    from factor_factory.console.models import CampaignSummary

    summary = CampaignSummary(
        campaign_id=CAMPAIGN_ID,
        workspace_root="/tmp/factorforge-miner-workspace/factor_research/miner/current_data_api_catalog_20260626",
        verdict="BLOCK",
        candidate_count=12,
        cheap_screen_passed=0,
        research_queue_count=0,
        data_gap_count=46,
        data_request_count=1,
        template_status_counts={"needs_operator": 6, "partial": 4, "needs_data": 2},
        artifact_paths={"research_queue": "objects/research_queue/research_queue.json"},
        blockers=["no ready templates"],
        next_actions=["fix catalog"],
        boundary_statement="No production research.",
    )
    payload = summary.to_dict()
    assert payload["verdict"] == "BLOCK"
    assert payload["candidate_count"] == 12
    assert CampaignSummary.from_dict(payload).template_status_counts["needs_operator"] == 6


def test_console_task_requires_contract_version():
    from factor_factory.console.models import ConsoleTask

    payload = {
        "contract_version": "wrong",
        "task_id": "task_1",
        "task_type": "factorforge_miner_campaign",
        "repo_root": "/repo",
        "execution_workspace": "/tmp/work",
        "campaign_id": "camp",
        "workspace_root": "factor_research/miner/camp",
        "inputs": {},
        "steps": [],
        "boundaries": {},
        "expected_outputs": [],
    }
    with pytest.raises(ValueError, match="factorforge_console_task_v1"):
        ConsoleTask.from_dict(payload)


def test_console_result_rejects_invalid_verdict():
    from factor_factory.console.models import ConsoleResult

    payload = {
        "contract_version": "factorforge_console_result_v1",
        "task_id": "task_1",
        "run_id": "run_1",
        "status": "completed",
        "verdict": "PROMOTE",
        "metrics": {},
        "artifact_paths": {},
        "blockers": [],
        "next_actions": [],
        "boundaries_observed": {},
    }
    with pytest.raises(ValueError, match="verdict"):
        ConsoleResult.from_dict(payload)


def test_read_miner_campaign_blocks_when_no_queue(tmp_path):
    from factor_factory.console.readers import read_miner_campaign

    workspace = make_miner_fixture(tmp_path)
    summary = read_miner_campaign(workspace)
    assert summary.verdict == "BLOCK"
    assert summary.candidate_count == 12
    assert summary.data_gap_count == 46
    assert summary.data_request_count == 1
    assert summary.research_queue_count == 0
    assert summary.template_status_counts == {
        "needs_operator": 6,
        "partial": 4,
        "needs_data": 2,
    }
    assert "production research" in summary.boundary_statement
    assert all(not Path(path).is_absolute() for path in summary.artifact_paths.values())


def test_read_miner_campaign_blocks_when_promotion_guard_missing(tmp_path):
    from factor_factory.console.readers import read_miner_campaign

    workspace = make_miner_fixture(tmp_path)
    _write_json(
        workspace / "objects" / "cheap_screen" / "cheap_screen_summary.json",
        {"promotion_forbidden_until_formal": False, "passed_count": 0},
    )
    summary = read_miner_campaign(workspace)
    assert summary.verdict == "BLOCK"
    assert any("promotion guard" in blocker for blocker in summary.blockers)


def test_discover_miner_campaigns(tmp_path):
    from factor_factory.console.discovery import discover_miner_campaigns

    workspace = make_miner_fixture(tmp_path / "root")
    data_clean = tmp_path / "root" / "data" / "clean" / "factor_research" / "miner"
    _write_json(
        data_clean / "bad" / "objects" / "miner_capability_inventory.json",
        {"campaign_id": "bad"},
    )
    found = discover_miner_campaigns([tmp_path / "root"])
    assert found == [workspace]


def test_write_console_task_and_result_under_console_root(tmp_path):
    from factor_factory.console.models import ConsoleResult, ConsoleTask
    from factor_factory.console.task_manifest import write_console_result, write_console_task

    task = ConsoleTask(
        contract_version="factorforge_console_task_v1",
        task_id="task_1",
        task_type="factorforge_miner_campaign",
        repo_root=str(tmp_path),
        execution_workspace=str(tmp_path),
        campaign_id="camp",
        workspace_root="factor_research/miner/camp",
        inputs={},
        steps=[],
        boundaries={},
        expected_outputs=[],
    )
    result = ConsoleResult(
        contract_version="factorforge_console_result_v1",
        task_id="task_1",
        run_id="run_1",
        status="completed",
        verdict="BLOCK",
        metrics={},
        artifact_paths={},
        blockers=[],
        next_actions=[],
        boundaries_observed={},
    )

    task_path = write_console_task(tmp_path, task)
    result_path = write_console_result(tmp_path, result)

    assert task_path == tmp_path / "factor_research" / "console" / "tasks" / "task_1.json"
    assert result_path == tmp_path / "factor_research" / "console" / "results" / "task_1.json"
    assert json.loads(task_path.read_text(encoding="utf-8"))["task_id"] == "task_1"
    assert json.loads(result_path.read_text(encoding="utf-8"))["verdict"] == "BLOCK"


def test_create_miner_campaign_task_manifest(tmp_path):
    from factor_factory.console.task_manifest import create_miner_campaign_task, read_console_tasks

    path = create_miner_campaign_task(
        root=tmp_path,
        campaign_id="current data api catalog 20260629",
        execution_workspace="/tmp/factorforge-miner-workspace",
        catalogs=["/tmp/catalog.json"],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path == tmp_path / "factor_research" / "console" / "tasks" / "task_miner_current_data_api_catalog_20260629.json"
    assert payload["task_type"] == "factorforge_miner_campaign"
    assert payload["campaign_id"] == "current_data_api_catalog_20260629"
    assert payload["workspace_root"] == "factor_research/miner/current_data_api_catalog_20260629"
    assert payload["boundaries"]["production_research_allowed"] is False
    assert read_console_tasks(tmp_path)[0].task_id == "task_miner_current_data_api_catalog_20260629"


def test_reject_console_manifest_path_traversal(tmp_path):
    from factor_factory.console.models import ConsoleTask
    from factor_factory.console.task_manifest import (
        BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE,
        write_console_task,
    )

    task = ConsoleTask(
        contract_version="factorforge_console_task_v1",
        task_id="../escape",
        task_type="factorforge_miner_campaign",
        repo_root=str(tmp_path),
        execution_workspace=str(tmp_path),
        campaign_id="camp",
        workspace_root="factor_research/miner/camp",
        inputs={},
        steps=[],
        boundaries={},
        expected_outputs=[],
    )
    with pytest.raises(ValueError, match=BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE):
        write_console_task(tmp_path, task)


def test_render_dashboard_contains_campaign_metrics(tmp_path):
    from factor_factory.console.readers import read_miner_campaign
    from factor_factory.console.summary import render_dashboard

    summary = read_miner_campaign(make_miner_fixture(tmp_path))
    html = render_dashboard([summary])
    assert "Factor Forge Console" in html
    assert CAMPAIGN_ID in html
    assert "BLOCK" in html
    assert "46" in html
    assert "research queue" in html.lower()
    assert "artifact" in html.lower()
    assert "Task Launcher" in html
    assert "Create Miner Campaign Task" in html


def test_build_console_html_from_root(tmp_path):
    from factor_factory.console.static_app import build_console_html

    make_miner_fixture(tmp_path)
    html = build_console_html([tmp_path])
    assert "Factor Forge Console" in html
    assert CAMPAIGN_ID in html


def test_console_post_creates_miner_task(tmp_path):
    from factor_factory.console.static_app import build_console_server, serve_console_server

    make_miner_fixture(tmp_path)
    server = build_console_server([tmp_path], "127.0.0.1", 0)
    thread = threading.Thread(target=serve_console_server, args=(server,), daemon=True)
    thread.start()
    host, port = server.server_address
    payload = urlencode(
        {
            "campaign_id": "posted_campaign",
            "execution_workspace": "/tmp/factorforge-miner-workspace",
            "catalogs": "/tmp/catalog_a.json\n/tmp/catalog_b.json",
            "screen_window": "2016-01-01..2025-07-11",
            "universe": "current_data_api_catalog",
        }
    ).encode("utf-8")
    try:
        request = Request(f"http://{host}:{port}/tasks/miner", data=payload, method="POST")
        response = urlopen(request, timeout=3)
        assert response.status == 200
        html = response.read().decode("utf-8")
        assert "task_miner_posted_campaign" in html
        task_path = tmp_path / "factor_research" / "console" / "tasks" / "task_miner_posted_campaign.json"
        assert task_path.exists()
        task = json.loads(task_path.read_text(encoding="utf-8"))
        assert task["inputs"]["catalogs"] == ["/tmp/catalog_a.json", "/tmp/catalog_b.json"]
    finally:
        server.shutdown()
        thread.join(timeout=3)
