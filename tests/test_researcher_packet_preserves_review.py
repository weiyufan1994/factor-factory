from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _builder():
    path = Path(__file__).resolve().parents[1] / "skills/factor-forge-step6-researcher/scripts/build_researcher_packet.py"
    spec = importlib.util.spec_from_file_location("packet_preservation_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packet_preparation_preserves_authored_review(tmp_path, monkeypatch):
    module = _builder()
    monkeypatch.setattr(module, "FF", tmp_path)
    monkeypatch.setattr(module, "OBJ", tmp_path / "objects")
    monkeypatch.setattr(module, "EVAL", tmp_path / "evaluations")
    monkeypatch.setattr("sys.argv", ["builder", "--report-id", "TEST"])
    memo = tmp_path / "objects/research_iteration_master/researcher_memo__TEST.json"
    memo.parent.mkdir(parents=True)
    original = b'{"producer":"independent_researcher","researcher_decision":"reject","specific_reason":"direction lost"}\n'
    memo.write_bytes(original)
    monkeypatch.setattr(module, "build_researcher_memo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("template must not run")))
    module.main()
    assert memo.read_bytes() == original
    packet = json.loads((memo.parent / "researcher_packet__TEST.json").read_text())
    assert packet["required_researcher_output"] == str(memo)
    assert packet["source_files"]["prior_researcher_memo"]["exists"] is True


def test_packet_preparation_never_invents_a_review(tmp_path, monkeypatch):
    module = _builder()
    monkeypatch.setattr(module, "FF", tmp_path)
    monkeypatch.setattr(module, "OBJ", tmp_path / "objects")
    monkeypatch.setattr(module, "EVAL", tmp_path / "evaluations")
    monkeypatch.setattr("sys.argv", ["builder", "--report-id", "TEST"])
    module.main()
    assert (tmp_path / "objects/research_iteration_master/researcher_packet__TEST.json").is_file()
    assert not (tmp_path / "objects/research_iteration_master/researcher_memo__TEST.json").exists()
