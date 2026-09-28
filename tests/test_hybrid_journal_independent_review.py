"""Independent recovery checks; fixtures never represent real research approval."""

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from factor_factory.hybrid_research import journal_adapter as adapter
from factor_factory.hybrid_research.decision import ScheduleState
from factor_factory.hybrid_research.synthetic import FitData
from factor_factory.hybrid_research.variation import DerivationScope


REPORT = "independent-engineering-fixture"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def workspace(tmp_path):
    payloads = {
        "research_journal/research_journal": {"existing_note": "preserve"},
        "factor_spec_master/factor_spec_master": {
            "mechanism_conditioned_measurement_program": {"model_selection": {"selected_model": "fixture"}},
        },
        "research_protocol/approach_registry": {"approaches": []},
        "handoff/handoff_to_step3": {"status": "fixture_only"},
    }
    for stem, payload in payloads.items():
        _write(tmp_path / "objects" / f"{stem}__{REPORT}.json", {
            "report_id": REPORT, "engineering_fixture": True, **payload,
        })
    return tmp_path


def _fit():
    return FitData((1., 0., -1., 0.), (.9, .4, -.7, -.3), 1.)


def _run(root, **overrides):
    scope = DerivationScope(
        "independent:journal-recovery", "causal kernels", "finite signed impulses",
        "zero", "event", "missing is not zero", "signed J to y",
        ("causal convolution", "linear superposition"),
        ("positive-rate modes decay; zero-rate modes persist",), "unknown response scales",
        ("transient_exponential_kernel", "permanent_component", "two_scale_superposition"),
        ("parameter_search", "structure_search"),
    )
    arguments = dict(
        workspace_root=root, report_id=REPORT, run_id="run-001", fit_data=_fit(),
        scope=scope, schedule_state=ScheduleState(7, 2, 5), enabled=True, seed=4,
        handoff_stage="step2",
    )
    arguments.update(overrides)
    return adapter.run_hybrid_episode(**arguments)


def test_modified_material_cannot_be_reported_as_valid_resume(workspace):
    outcome = _run(workspace)
    path = Path(outcome.researcher_material_path)
    material = json.loads(path.read_text())
    material["used_budget"]["attempts"] = 0
    _write(path, material)
    with pytest.raises(adapter.HybridResearchError):
        _run(workspace)


def test_crash_after_search_before_material_does_not_silently_reexecute(workspace, monkeypatch):
    original_search = adapter.run_response_gp
    original_write = adapter.write_json_atomic
    calls = []

    def counted_search(**kwargs):
        calls.append(kwargs)
        return original_search(**kwargs)

    def fail_material_write(path, payload):
        if Path(path).name.startswith("hybrid_research_material__"):
            raise OSError("injected interruption after search, before material publication")
        return original_write(path, payload)

    monkeypatch.setattr(adapter, "run_response_gp", counted_search)
    with monkeypatch.context() as fault:
        fault.setattr(adapter, "write_json_atomic", fail_material_write)
        with pytest.raises((OSError, adapter.HybridResearchError)):
            _run(workspace)
    try:
        resumed = _run(workspace)
    except adapter.HybridResearchError:
        resumed = None
    assert len(calls) == 1, "uncertain execution must not be silently charged/executed again"
    if resumed is not None:
        assert resumed.search_result is None
        assert resumed.status != "computed_awaiting_researcher"


def test_new_run_cannot_roll_back_existing_schedule_state(workspace):
    first = _run(workspace)
    before = Path(first.journal_path).read_bytes()
    with pytest.raises(adapter.HybridResearchError):
        _run(workspace, run_id="run-002", schedule_state=ScheduleState())
    assert Path(first.journal_path).read_bytes() == before


def test_researcher_can_inspect_visible_fit_data_not_just_a_digest(workspace):
    outcome = _run(workspace)
    material = json.loads(Path(outcome.researcher_material_path).read_text())
    visible = material.get("fit_data")
    if visible is None and isinstance(material.get("fit_data_ref"), dict):
        path = Path(material["fit_data_ref"]["path"])
        visible = json.loads((path if path.is_absolute() else workspace / path).read_text())
    expected = json.loads(json.dumps(asdict(_fit())))
    assert visible == expected
    assert not any(key.startswith("hidden") for key in visible)


def test_partial_publication_cannot_rebind_changed_fit_data(workspace, monkeypatch):
    original_write = adapter.write_json_atomic

    def fail_completed_journal(path, payload):
        rows = (payload.get("hybrid_research") or {}).get("episodes", [])
        if Path(path).name.startswith("research_journal__") and any(
            row.get("status") == "computed_awaiting_researcher" for row in rows
        ):
            raise OSError("injected interruption after material, before journal completion")
        return original_write(path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(adapter, "write_json_atomic", fail_completed_journal)
        with pytest.raises((OSError, adapter.HybridResearchError)):
            _run(workspace)
    path = workspace / "objects/research_journal" / f"hybrid_research_material__{REPORT}__run-001.json"
    material = json.loads(path.read_text())
    material["fit_data"]["observed_response"][0] += 1.
    _write(path, material)
    with pytest.raises(adapter.HybridResearchError):
        _run(workspace)


def test_unchanged_partial_publication_recovers_without_search(workspace, monkeypatch):
    original_write = adapter.write_json_atomic

    def fail_completed_journal(path, payload):
        rows = (payload.get("hybrid_research") or {}).get("episodes", [])
        if Path(path).name.startswith("research_journal__") and any(
            row.get("status") == "computed_awaiting_researcher" for row in rows
        ):
            raise OSError("injected interruption after material, before journal completion")
        return original_write(path, payload)

    with monkeypatch.context() as fault:
        fault.setattr(adapter, "write_json_atomic", fail_completed_journal)
        with pytest.raises((OSError, adapter.HybridResearchError)):
            _run(workspace)

    def forbidden_search(**kwargs):
        pytest.fail("valid completed material must resume without executing search again")

    monkeypatch.setattr(adapter, "run_response_gp", forbidden_search)
    resumed = _run(workspace)
    assert resumed.resumed is True
    assert resumed.search_result is None
    assert resumed.status == "computed_awaiting_researcher"
    journal = json.loads(Path(resumed.journal_path).read_text())
    assert len(journal["hybrid_research"]["episodes"]) == 1
