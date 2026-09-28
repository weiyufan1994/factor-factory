"""Independent feedback-boundary tests using synthetic engineering records only."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from factor_factory.hybrid_research import journal_adapter as adapter
from factor_factory.hybrid_research.decision import ScheduleState
from factor_factory.hybrid_research.synthetic import FitData
from factor_factory.hybrid_research.variation import DerivationScope


REPORT = "independent-feedback-fixture"
RUN = "run-001"


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run(root):
    return adapter.run_hybrid_episode(
        workspace_root=root, report_id=REPORT, run_id=RUN,
        fit_data=FitData((1., 0., -1.), (.8, .3, -.6), 1.),
        scope=DerivationScope(
            "independent:feedback", "causal kernels", "finite signed impulses",
            "zero", "event", "missing is not zero", "signed J to y",
            ("causal convolution",), ("pulse has a causal tail",),
            "engineering-only unknown response", ("transient_exponential_kernel",),
            ("parameter_search",),
        ),
        schedule_state=ScheduleState(4, 1, 3), handoff_stage="step2",
        enabled=True, allowed_rates=(0.2,), allowed_scales=(1.,),
        max_evaluations=1, max_attempts=2,
    )


@pytest.fixture
def episode(tmp_path):
    for stem, payload in {
        "research_journal/research_journal": {"existing_note": "preserve"},
        "factor_spec_master/factor_spec_master": {
            "mechanism_conditioned_measurement_program": {"model_selection": {"candidate": "fixture"}},
        },
        "research_protocol/approach_registry": {"approaches": []},
        "handoff/handoff_to_step3": {"status": "engineering_only"},
    }.items():
        _write(tmp_path / "objects" / f"{stem}__{REPORT}.json", {
            "report_id": REPORT, "engineering_fixture": True, **payload,
        })
    outcome = _run(tmp_path)
    source = tmp_path / "synthetic_feedback.json"
    material_hash = sha256(Path(outcome.researcher_material_path).read_bytes()).hexdigest()
    _write(source, {
        "report_id": REPORT, "run_id": RUN,
        "input_identity": outcome.input_identity,
        "material_sha256": material_hash,
        "decision": "stop_insufficient_evidence",
        "next_research_question": "Synthetic test only: separate observation ambiguity from fit.",
        "engineering_fixture": True,
    })
    return tmp_path, outcome, source, material_hash


def _record(episode):
    root, outcome, source, digest = episode
    return adapter.record_hybrid_researcher_response(
        workspace_root=root, report_id=REPORT, run_id=RUN,
        input_identity=outcome.input_identity, material_sha256=digest,
        response_path=source, enabled=True,
    )


def test_external_identity_cannot_disagree_with_requested_run(episode):
    _, outcome, source, _ = episode
    value = json.loads(source.read_text())
    value["run_id"] = "different-study"
    _write(source, value)
    before = Path(outcome.journal_path).read_bytes()
    with pytest.raises(adapter.HybridResearchError):
        _record(episode)
    assert Path(outcome.journal_path).read_bytes() == before


def test_original_response_text_preserves_actual_raw_bytes(episode):
    _, outcome, source, _ = episode
    original = json.dumps(json.loads(source.read_text()), indent=2).replace("\n", "\r\n") + "\r\n"
    source.write_bytes(original.encode("utf-8"))
    _record(episode)
    journal = json.loads(Path(outcome.journal_path).read_text())
    record = journal["hybrid_research"]["episodes"][0]["researcher_response"]
    assert record["original_response_text"].encode("utf-8") == source.read_bytes()
    assert sha256(record["original_response_text"].encode("utf-8")).hexdigest() == record["source_sha256"]


def test_modified_recorded_decision_cannot_survive_resume(episode):
    root, outcome, _, _ = episode
    _record(episode)
    journal_path = Path(outcome.journal_path)
    journal = json.loads(journal_path.read_text())
    journal["hybrid_research"]["episodes"][0]["researcher_response"]["decision"] = "retain_for_more_development"
    _write(journal_path, journal)
    with pytest.raises(adapter.HybridResearchError):
        _run(root)


def test_valid_record_is_idempotent_and_resume_never_runs_search(episode, monkeypatch):
    root, outcome, source, _ = episode
    first = _record(episode)
    journal_path = Path(outcome.journal_path)
    before = journal_path.read_bytes()
    second = _record(episode)
    assert first.resumed is False and second.resumed is True
    assert journal_path.read_bytes() == before

    def forbidden_search(**kwargs):
        pytest.fail("feedback recovery must not perform another search")

    monkeypatch.setattr(adapter, "run_response_gp", forbidden_search)
    recovered = _run(root)
    assert recovered.status == "researcher_response_recorded"
    assert recovered.resumed is True and recovered.search_result is None
    after = json.loads(journal_path.read_text())
    assert after["existing_note"] == "preserve"
    assert len(after["hybrid_research"]["episodes"]) == 1
    assert after["hybrid_research"]["current_schedule_state"] == {
        "episode_index": 4, "explore_allocations": 1, "exploit_allocations": 3,
    }
    record = after["hybrid_research"]["episodes"][0]["researcher_response"]
    assert record["source_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert record["formal_approval"] is False
    assert record["policy_update_eligible"] is False
    assert record["knowledge_write_allowed"] is False
    assert record["next_experiment_dispatched"] is False


def test_saved_original_survives_loss_of_external_source_copy(episode, monkeypatch):
    root, _, source, _ = episode
    original = source.read_bytes()
    _record(episode)
    source.unlink()  # Only the synthetic file created by this test's tmp_path fixture.

    def forbidden_search(**kwargs):
        pytest.fail("recovering saved researcher feedback must not rerun computation")

    monkeypatch.setattr(adapter, "run_response_gp", forbidden_search)
    recovered = _run(root)
    assert recovered.status == "researcher_response_recorded"
    journal = json.loads(Path(recovered.journal_path).read_text())
    record = journal["hybrid_research"]["episodes"][0]["researcher_response"]
    assert record["original_response_text"].encode("utf-8") == original
