from __future__ import annotations

import json
from pathlib import Path
from re import sub
from typing import Any

from factor_factory.console.models import ConsoleResult, ConsoleTask


BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE = "BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE"

MINER_CAMPAIGN_STEPS = [
    "capability_inventory",
    "candidate_generation",
    "data_gap_report",
    "cheap_screen",
    "research_queue",
]

MINER_CAMPAIGN_EXPECTED_OUTPUTS = [
    "docs/miner_capability_inventory.md",
    "objects/candidates/candidate_manifest.json",
    "docs/data_gap_report.md",
    "objects/cheap_screen/cheap_screen_summary.json",
    "objects/research_queue/research_queue.json",
]

SAFE_MINER_BOUNDARIES = {
    "production_research_allowed": False,
    "worker_allowed": False,
    "formal_step3b_step4_step6_allowed": False,
    "clean_data_mutation_allowed": False,
    "repo_root_generated_data_write_allowed": False,
}


def write_console_task(root: str | Path, task: ConsoleTask) -> Path:
    return _write_manifest(Path(root), "tasks", task.task_id, task.to_dict())


def write_console_result(root: str | Path, result: ConsoleResult) -> Path:
    return _write_manifest(Path(root), "results", result.task_id, result.to_dict())


def build_miner_campaign_task(
    *,
    root: str | Path,
    campaign_id: str,
    execution_workspace: str,
    catalogs: list[str],
    screen_window: str = "2016-01-01..2025-07-11",
    universe: str = "current_data_api_catalog",
) -> ConsoleTask:
    safe_campaign = _safe_id(campaign_id)
    if not safe_campaign:
        raise ValueError("campaign_id is required")
    task_id = f"task_miner_{safe_campaign}"
    return ConsoleTask(
        contract_version="factorforge_console_task_v1",
        task_id=task_id,
        task_type="factorforge_miner_campaign",
        repo_root=str(Path(root).resolve(strict=False)),
        execution_workspace=execution_workspace,
        campaign_id=safe_campaign,
        workspace_root=f"factor_research/miner/{safe_campaign}",
        inputs={
            "catalogs": catalogs,
            "screen_window": screen_window,
            "universe": universe,
        },
        steps=list(MINER_CAMPAIGN_STEPS),
        boundaries=dict(SAFE_MINER_BOUNDARIES),
        expected_outputs=list(MINER_CAMPAIGN_EXPECTED_OUTPUTS),
    )


def create_miner_campaign_task(
    *,
    root: str | Path,
    campaign_id: str,
    execution_workspace: str,
    catalogs: list[str],
    screen_window: str = "2016-01-01..2025-07-11",
    universe: str = "current_data_api_catalog",
) -> Path:
    task = build_miner_campaign_task(
        root=root,
        campaign_id=campaign_id,
        execution_workspace=execution_workspace,
        catalogs=catalogs,
        screen_window=screen_window,
        universe=universe,
    )
    return write_console_task(root, task)


def read_console_tasks(root: str | Path) -> list[ConsoleTask]:
    tasks_root = Path(root) / "factor_research" / "console" / "tasks"
    if not tasks_root.exists():
        return []
    tasks: list[ConsoleTask] = []
    for path in sorted(tasks_root.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            payload: Any = json.load(handle)
        if isinstance(payload, dict):
            tasks.append(ConsoleTask.from_dict(payload))
    return tasks


def _write_manifest(root: Path, kind: str, manifest_id: str, payload: dict) -> Path:
    console_root = (root / "factor_research" / "console").resolve()
    if "/" in manifest_id or "\\" in manifest_id or manifest_id in {"", ".", ".."}:
        raise ValueError(BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE)
    output_dir = console_root / kind
    output_path = (output_dir / f"{manifest_id}.json").resolve()
    if not _is_relative_to(output_path, console_root):
        raise ValueError(BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def _safe_id(value: str) -> str:
    return sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
