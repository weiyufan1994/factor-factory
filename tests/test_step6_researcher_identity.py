from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_builder():
    path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "factor-forge-step6-researcher"
        / "scripts"
        / "build_researcher_packet.py"
    )
    spec = importlib.util.spec_from_file_location("build_researcher_packet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packet_uses_current_identity_and_leaves_research_judgement_to_reviewer(tmp_path):
    import json
    from factor_factory.step6.packets import build_researcher_packet

    rid = "ALPHA015_SWEEP_TURNPEN_A040_20160101"
    path = tmp_path / "objects/factor_spec_master" / f"factor_spec_master__{rid}.json"
    path.parent.mkdir(parents=True)
    source = {"factor_id": "Alpha015", "canonical_spec": {"formula_text": "-sum(rank(correlation(rank(high), rank(volume), 7)), 7)"}}
    path.write_text(json.dumps(source))
    packet = build_researcher_packet(rid, workspace_root=tmp_path)
    assert packet["report_id"] == rid
    assert packet["objects"]["factor_spec_master"] == source
    assert packet["producer"] == "factor-forge-step6-researcher.build_researcher_packet"
    assert "Alpha013" not in json.dumps(packet)
    assert "researcher_decision" not in packet
    assert "knowledge_to_write_back" not in packet
    assert not Path(packet["required_researcher_output"]).exists()


def test_legacy_formula_family_template_cannot_synthesize_an_independent_memo():
    import pytest
    with pytest.raises(RuntimeError, match="does not author a researcher memo"):
        _load_builder().build_researcher_memo("CURRENT", {}, {}, {})
