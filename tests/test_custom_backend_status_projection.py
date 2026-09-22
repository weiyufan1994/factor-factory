"""Exercise the actual custom branch with an offline subprocess boundary."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def step4(tmp_path, monkeypatch):
    source = ROOT / "skills/factor-forge-step4/scripts/run_step4.py"
    spec = importlib.util.spec_from_file_location("custom_status_step4", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter = tmp_path / "adapter.py"
    adapter.write_text("# No process or data access in this orchestration fixture.\n")
    # Resolve a real local path; only the process execution itself is stubbed.
    return module, adapter


def exercise(step4, tmp_path, monkeypatch, *, rc=0, raw=None, prior=None):
    module, adapter = step4
    path = tmp_path / "payload.json"
    if prior is not None:
        path.write_text(prior)
    calls = []

    def process(report_id, backend, script, payload_path, config, **kwargs):
        calls.append((report_id, backend, script))
        assert script == adapter
        if raw is not None:
            payload_path.write_text(raw)
        return rc, "offline boundary"

    monkeypatch.setattr(module, "run_backend_script", process)
    runs, timing = module.write_backend_payloads(
        "IT_SYNTHETIC_CUSTOM_STATUS",
        [{"backend": "study_custom", "status": "planned", "payload_path": str(path),
          "backend_config": {"script_path": str(adapter)}}],
    )
    assert len(calls) == 1
    assert runs[0]["returncode"] == rc
    assert timing["backends"]["study_custom"]["returncode"] == rc
    assert timing["backends"]["study_custom"]["status"] == runs[0]["status"]
    if raw is not None:
        assert path.read_text() == raw  # No relabeling of the actual payload.
    return runs[0], path


@pytest.mark.parametrize("status", ["success", "partial", "failed", "skipped"])
def test_zero_exit_preserves_actual_payload_status(step4, tmp_path, monkeypatch, status):
    item, _ = exercise(step4, tmp_path, monkeypatch, raw=json.dumps({"status": status, "summary": {"rows": 2}}))
    assert item["status"] == item["payload_status"] == status
    assert item["summary"] == {"rows": 2}
    assert "payload_contract_error" not in item


@pytest.mark.parametrize("status", ["success", "partial", "skipped"])
def test_nonzero_exit_with_nonfailure_payload_is_failed(step4, tmp_path, monkeypatch, status):
    item, _ = exercise(step4, tmp_path, monkeypatch, rc=2, raw=json.dumps({"status": status}))
    assert item["status"] == "failed" and item["payload_status"] == status
    assert item["payload_contract_error"] == "CUSTOM_BACKEND_PROCESS_PAYLOAD_CONTRADICTION"


def test_failed_process_and_failed_payload_remain_failed(step4, tmp_path, monkeypatch):
    item, _ = exercise(step4, tmp_path, monkeypatch, rc=2, raw='{"status":"failed"}')
    assert item["status"] == "failed" and "payload_contract_error" not in item


@pytest.mark.parametrize("rc", [0, 2])
def test_missing_payload_never_becomes_success(step4, tmp_path, monkeypatch, rc):
    item, path = exercise(step4, tmp_path, monkeypatch, rc=rc)
    assert item["status"] == "failed"
    assert item["payload_contract_error"] == "CUSTOM_BACKEND_PAYLOAD_MISSING"
    assert json.loads(path.read_text())["status"] == "failed"


@pytest.mark.parametrize("raw", ['{broken', '[]', 'null', '{}', '{"status":"ready"}', '{"status":[]}'])
def test_invalid_payload_is_retained_and_marked_failed(step4, tmp_path, monkeypatch, raw):
    item, _ = exercise(step4, tmp_path, monkeypatch, raw=raw)
    assert item["status"] == "failed"
    assert item["payload_contract_error"] in {"CUSTOM_BACKEND_PAYLOAD_INVALID", "CUSTOM_BACKEND_PAYLOAD_STATUS_INVALID"}


def test_unchanged_old_success_is_not_this_attempt_output(step4, tmp_path, monkeypatch):
    old = '{"status":"success","summary":{"old":true}}'
    item, path = exercise(step4, tmp_path, monkeypatch, prior=old)
    assert item["status"] == "failed"
    assert item["payload_contract_error"] == "CUSTOM_BACKEND_PAYLOAD_NOT_UPDATED"
    assert path.read_text() == old
