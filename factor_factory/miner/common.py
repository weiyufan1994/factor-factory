from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factor_factory.miner import BLOCK_OUTPUT_OUTSIDE_WORKSPACE, BLOCK_WORKSPACE_MISSING


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_workspace(workspace_root: Path, *, campaign_id: str | None = None) -> Path:
    workspace = Path(workspace_root).expanduser().resolve(strict=False)
    if not str(workspace):
        raise ValueError(BLOCK_WORKSPACE_MISSING)
    parts = workspace.parts
    valid_idx: int | None = None
    for idx, part in enumerate(parts):
        if part == "factor_research" and idx + 2 < len(parts) and parts[idx + 1] == "miner":
            valid_idx = idx
            break
    if valid_idx is None:
        raise ValueError(f"{BLOCK_WORKSPACE_MISSING}: workspace_root must be factor_research/miner/<campaign_id>: {workspace}")
    actual_campaign = parts[valid_idx + 2]
    has_nested_root = len(parts) != valid_idx + 3
    if has_nested_root:
        raise ValueError(f"{BLOCK_WORKSPACE_MISSING}: workspace_root must end at factor_research/miner/<campaign_id>: {workspace}")
    if campaign_id is not None and actual_campaign != str(campaign_id):
        raise ValueError(
            f"{BLOCK_WORKSPACE_MISSING}: campaign_id mismatch workspace_campaign={actual_campaign} campaign_id={campaign_id}"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def assert_under_workspace(path: Path, workspace_root: Path, *, label: str) -> Path:
    workspace = Path(workspace_root).expanduser().resolve(strict=False)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve(strict=False)
    if resolved != workspace and not is_relative_to(resolved, workspace):
        raise ValueError(f"{BLOCK_OUTPUT_OUTSIDE_WORKSPACE}: {label}={resolved} workspace={workspace}")
    return resolved


def workspace_path(workspace_root: Path, *parts: str, campaign_id: str | None = None) -> Path:
    workspace = require_workspace(workspace_root, campaign_id=campaign_id)
    path = assert_under_workspace(workspace.joinpath(*parts), workspace, label="/".join(parts))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def write_markdown(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return path


def normalize_catalog_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    datasets = payload.get("datasets")
    if isinstance(datasets, list):
        return [row for row in datasets if isinstance(row, dict)]
    if isinstance(datasets, dict):
        return [
            {"dataset_id": key, **value} if isinstance(value, dict) else {"dataset_id": key}
            for key, value in datasets.items()
        ]
    return []
