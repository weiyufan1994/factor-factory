#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.console.readers import read_miner_campaign  # noqa: E402


REAL_WORKSPACE = Path(
    "/tmp/factorforge-miner-workspace/factor_research/miner/current_data_api_catalog_20260626"
)
FIXTURE_ROOT = Path("/tmp/factorforge_console_smoke")
CAMPAIGN_ID = "current_data_api_catalog_20260626"


def main() -> None:
    workspace = REAL_WORKSPACE if REAL_WORKSPACE.exists() else _create_fixture()
    summary = read_miner_campaign(workspace)
    cheap_screen = _read_json(workspace / "objects" / "cheap_screen" / "cheap_screen_summary.json")

    assert summary.candidate_count == 12, summary.to_dict()
    assert summary.research_queue_count == 0, summary.to_dict()
    assert summary.data_gap_count == 46, summary.to_dict()
    assert summary.data_request_count == 1, summary.to_dict()
    assert summary.template_status_counts.get("needs_operator") == 6, summary.to_dict()
    assert summary.template_status_counts.get("partial") == 4, summary.to_dict()
    assert summary.template_status_counts.get("needs_data") == 2, summary.to_dict()
    assert summary.verdict == "BLOCK", summary.to_dict()
    assert cheap_screen.get("promotion_forbidden_until_formal") is True
    _assert_artifact_links_under_workspace(workspace, summary.artifact_paths)

    print("FACTORFORGE_CONSOLE_SMOKE PASS")


def _create_fixture() -> Path:
    workspace = FIXTURE_ROOT / "factor_research" / "miner" / CAMPAIGN_ID
    _write_json(
        workspace / "objects" / "miner_capability_inventory.json",
        {"campaign_id": CAMPAIGN_ID},
    )
    _write_json(
        workspace / "objects" / "candidates" / "candidate_manifest.json",
        {
            "campaign_id": CAMPAIGN_ID,
            "candidates": [
                {"candidate_id": f"candidate_{idx}", "cheap_screen_status": status}
                for idx, status in enumerate(
                    ["needs_operator"] * 6 + ["partial"] * 4 + ["needs_data"] * 2,
                    start=1,
                )
            ],
        },
    )
    _write_json(
        workspace / "objects" / "data_gap_report.json",
        {
            "campaign_id": CAMPAIGN_ID,
            "data_request_ids": ["data_request_intraday_value_occupation_state_v1"],
            "gaps": [{"gap_id": f"gap_{idx}"} for idx in range(46)],
        },
    )
    _write_json(
        workspace / "objects" / "cheap_screen" / "cheap_screen_summary.json",
        {
            "campaign_id": CAMPAIGN_ID,
            "promotion_forbidden_until_formal": True,
            "results": [],
        },
    )
    _write_json(
        workspace / "objects" / "research_queue" / "research_queue.json",
        {"campaign_id": CAMPAIGN_ID, "items": []},
    )
    return workspace


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_artifact_links_under_workspace(workspace: Path, artifact_paths: dict[str, str]) -> None:
    workspace_resolved = workspace.resolve()
    for rel_path in artifact_paths.values():
        path = Path(rel_path)
        assert not path.is_absolute(), rel_path
        resolved = (workspace / path).resolve()
        try:
            resolved.relative_to(workspace_resolved)
        except ValueError as exc:
            raise AssertionError(f"artifact link outside workspace: {rel_path}") from exc


if __name__ == "__main__":
    main()
