from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["factor-forge-step5", "factor_forge_step5"])
def evaluator(request):
    path = ROOT / "skills" / request.param / "modules/evaluator.py"
    spec = importlib.util.spec_from_file_location("step5_payloads_" + request.param, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path):
    root = tmp_path / "factorforge"
    (root / "objects").mkdir(parents=True)
    return root


def test_undeclared_old_payload_is_never_consumed(evaluator, tmp_path):
    root = _workspace(tmp_path)
    old = root / "evaluations/CURRENT/old_backend/evaluation_payload.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"status": "success", "report_id": "OTHER_RUN", "metrics": {"rank_ic_mean": .99}}))
    declared = root / "current.json"
    declared.write_text(json.dumps({"status": "success", "metrics": {"rank_ic_mean": .03}}))
    selected = evaluator.read_backend_payloads(
        [{"backend": "declared", "status": "success", "payload_path": str(declared)}],
        report_id="CURRENT", workspace_root=root,
    )
    assert len(selected) == 1
    assert selected[0]["backend"] == "declared"
    assert selected[0]["key_metrics"]["rank_ic_mean"] == .03
    assert old.exists()


@pytest.mark.parametrize("raw", ["{broken", "[]", "null", '"text"', "true"])
def test_bad_declared_payload_becomes_quality_block(evaluator, tmp_path, raw):
    root = _workspace(tmp_path)
    selected = root / "bad.json"
    selected.write_text(raw)
    runs = [{"backend": "self_quant_analyzer", "status": "success", "payload_path": str(selected)}]
    payloads = evaluator.read_backend_payloads(runs, report_id="CURRENT", workspace_root=root)
    assert payloads[0]["payload"] is None
    assert payloads[0]["payload_error"]
    quality = evaluator.build_step4_quality_gate(payloads, {"run_status": "success"})
    assert quality["verdict"] == "BLOCK"
    issue = next(i for i in quality["issues"] if i["code"] == "SUCCESS_BACKEND_PAYLOAD_UNREADABLE")
    assert issue["evidence"]["payload_error"] == payloads[0]["payload_error"]


def test_missing_declared_file_is_not_replaced_by_directory_discovery(evaluator, tmp_path):
    root = _workspace(tmp_path)
    old = root / "evaluations/CURRENT/self_quant_analyzer/evaluation_payload.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"status": "success", "report_id": "OLD"}))
    payloads = evaluator.read_backend_payloads(
        [{"backend": "self_quant_analyzer", "status": "success", "payload_path": str(root / "missing.json")}],
        report_id="CURRENT", workspace_root=root,
    )
    assert len(payloads) == 1 and payloads[0]["payload"] is None
    assert "FileNotFoundError" in payloads[0]["payload_error"]
    assert evaluator.build_step4_quality_gate(payloads, {"run_status": "success"})["verdict"] == "BLOCK"


def test_relative_declared_path_is_workspace_bound(evaluator, tmp_path, monkeypatch):
    root = _workspace(tmp_path)
    (root / "declared.json").write_text(json.dumps({"metrics": {"rank_ic_mean": .04}}))
    other = tmp_path / "unrelated_cwd"
    other.mkdir()
    (other / "declared.json").write_text(json.dumps({"metrics": {"rank_ic_mean": .99}}))
    monkeypatch.chdir(other)
    selected = evaluator.read_backend_payloads(
        [{"backend": "declared", "status": "success", "payload_path": "declared.json"}],
        report_id="CURRENT", workspace_root=root,
    )
    assert selected[0]["key_metrics"]["rank_ic_mean"] == .04
    assert selected[0]["payload_path"] == str(root / "declared.json")


@pytest.mark.parametrize("malformed", [
    {"standard_metric_contract": "malformed"},
    {"standard_metric_contract": {"checks": "malformed"}},
    {"standard_metric_contract": {"checks": ["malformed"]}},
    {"long_side_performance": [1]},
    {"ic_summary": "malformed"},
    {"group_backtest_summary": True},
    {"artifacts": ["not-an-object"]},
    {"artifacts": {"daily_nav": {"not": "a-path"}}},
    {"backend": ["unhashable"]},
])
def test_malformed_nested_payload_is_quality_block_not_exception(evaluator, tmp_path, malformed):
    root = _workspace(tmp_path)
    selected = root / "nested.json"
    selected.write_text(json.dumps(malformed))
    runs = [{"backend": "self_quant_analyzer", "status": "success", "payload_path": str(selected)}]
    payloads = evaluator.read_backend_payloads(runs, report_id="CURRENT", workspace_root=root)
    assert payloads[0]["payload"] is None
    assert payloads[0]["payload_error"]
    assert evaluator.build_step4_quality_gate(payloads, {"run_status": "success"})["verdict"] == "BLOCK"
    # The quality gate is also called directly by consumers with decoded JSON.
    gate = evaluator.build_step4_quality_gate([{**runs[0], "payload": malformed}], {"run_status": "success"})
    assert gate["verdict"] == "BLOCK"
    assert any(issue["code"] == "BACKEND_PAYLOAD_STRUCTURE_INVALID" for issue in gate["issues"])
