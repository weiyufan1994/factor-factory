"""Exercise the real Ultimate process; optionally use a packaged release launcher.

FACTORFORGE_TEST_RELEASE_LAUNCHER selects the candidate release explicitly.
Inputs are synthetic engineering fixtures, never a market study or review.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_hybrid_research_journal_adapter import REPORT_ID, _fixture, _request


def _entry():
    launcher = os.environ.get("FACTORFORGE_TEST_RELEASE_LAUNCHER")
    if launcher:
        path = Path(launcher).resolve(strict=True)
        return [str(path)], path.parent / "factor-factory"
    repo = Path(__file__).resolve().parents[1]
    return [sys.executable, str(repo / "scripts/run_factorforge_ultimate.py")], repo


def _prepare(root):
    _fixture(root)
    _, repo = _entry()
    (root / "manifest.json").write_text(json.dumps({"repo_root": str(repo)}))
    return _request(root / "identity/request.json")


def _call(root, *arguments):
    command, _ = _entry()
    return subprocess.run(
        [*command, "--report-id", REPORT_ID, "--local-is-only", *arguments],
        cwd=root, text=True, capture_output=True, timeout=30,
    )


def _snapshot(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_real_entrypoint_workspace_target_and_idempotent_resume(tmp_path):
    request = _prepare(tmp_path)
    before = _snapshot(tmp_path)
    arguments = ["--factor-workspace", str(tmp_path), "--hybrid-research-adapter-only",
                 "--hybrid-research-request", str(request)]
    first = _call(tmp_path, *arguments)
    assert first.returncode == 0, first.stdout + first.stderr
    outcome = json.loads(first.stdout)
    assert outcome["status"] == "computed_awaiting_researcher"
    assert outcome["formal_proof_effect"] == "none"
    assert outcome["formal_approval"] is False
    assert outcome["resumed"] is False
    assert Path(outcome["journal_path"]).is_relative_to(tmp_path)
    saved = _snapshot(tmp_path)
    resumed = _call(tmp_path, *arguments)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert json.loads(resumed.stdout)["resumed"] is True
    assert _snapshot(tmp_path) == saved
    journal = json.loads(Path(outcome["journal_path"]).read_text())
    assert journal["preserved"] == {"old": True}
    assert len(journal["hybrid_research"]["episodes"]) == 1
    for name, digest in before.items():
        if "research_journal__" not in name:
            assert saved[name] == digest
    assert not list(tmp_path.rglob("ultimate_run_report__*"))
    assert not (tmp_path / "knowledge").exists()


@pytest.mark.parametrize("mode", ["adapter", "response"])
@pytest.mark.parametrize("target_arg", ["--factorforge-root", "--factor-workspace"])
def test_old_study_pin_rejected_without_writes(tmp_path, mode, target_arg):
    request = _prepare(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"repo_root": str(tmp_path / "old-release")}))
    before = _snapshot(tmp_path)
    if mode == "adapter":
        args = ["--hybrid-research-adapter-only", "--hybrid-research-request", str(request)]
    else:
        args = ["--hybrid-research-response-only", "--hybrid-research-response", str(request),
                "--hybrid-research-response-run-id", "r", "--hybrid-research-response-input-identity", "a" * 64,
                "--hybrid-research-response-material-sha256", "b" * 64]
    result = _call(tmp_path, target_arg, str(tmp_path), *args)
    assert result.returncode != 0
    assert "BLOCK_LOCAL_WORKSPACE_PIN_MISMATCH" in result.stdout + result.stderr
    assert _snapshot(tmp_path) == before


def test_conflicting_roots_rejected_without_writes(tmp_path):
    request = _prepare(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _prepare(other)
    before = _snapshot(tmp_path)
    result = _call(tmp_path, "--factor-workspace", str(tmp_path), "--factorforge-root", str(other),
                   "--hybrid-research-adapter-only", "--hybrid-research-request", str(request))
    assert result.returncode != 0
    assert "BLOCK_FACTORFORGE_HYBRID_RESEARCH_WORKSPACE" in result.stdout
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("invalid", ["dry_run", "confirmation", "nan", "conflicting_modes"])
def test_rejected_requests_do_not_create_episode(tmp_path, invalid):
    request = _prepare(tmp_path)
    payload = json.loads(request.read_text())
    extra = []
    if invalid == "confirmation":
        payload["split"] = "confirmation"
    elif invalid == "nan":
        payload["fit_data"]["observed_response"][0] = float("nan")
    elif invalid == "dry_run":
        extra.append("--dry-run")
    else:
        extra.append("--hybrid-research-response-only")
    request.write_text(json.dumps(payload))
    before = _snapshot(tmp_path)
    result = _call(tmp_path, "--factorforge-root", str(tmp_path), "--hybrid-research-adapter-only",
                   "--hybrid-research-request", str(request), *extra)
    assert result.returncode != 0
    assert "BLOCK_FACTORFORGE_HYBRID_RESEARCH" in result.stdout
    assert _snapshot(tmp_path) == before
