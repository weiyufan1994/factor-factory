from __future__ import annotations

import json
from pathlib import Path

from factor_factory.console.models import ConsoleResult, ConsoleTask


BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE = "BLOCK_FACTORFORGE_CONSOLE_OUTPUT_OUTSIDE_WORKSPACE"


def write_console_task(root: str | Path, task: ConsoleTask) -> Path:
    return _write_manifest(Path(root), "tasks", task.task_id, task.to_dict())


def write_console_result(root: str | Path, result: ConsoleResult) -> Path:
    return _write_manifest(Path(root), "results", result.task_id, result.to_dict())


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


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
