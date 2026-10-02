from __future__ import annotations

from dataclasses import asdict
import json
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.hybrid_research.decision import ScheduleState
from factor_factory.hybrid_research.journal_adapter import (
    HybridResearchError,
    record_hybrid_researcher_response,
    run_hybrid_episode,
)
from factor_factory.hybrid_research.synthetic import FitData
from factor_factory.hybrid_research.variation import DerivationScope


REPORT_ID = "engineering-case"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(root: Path, *, step6: bool = False) -> Path:
    _write(
        root / "objects/research_journal" / f"research_journal__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "preserved": {"old": True}},
    )
    _write(
        root / "objects/factor_spec_master" / f"factor_spec_master__{REPORT_ID}.json",
        {
            "report_id": REPORT_ID,
            "mechanism_conditioned_measurement_program": {
                "model_selection": {"selected_model": "causal_response"}
            },
        },
    )
    _write(
        root / "objects/research_protocol" / f"approach_registry__{REPORT_ID}.json",
        {"report_id": REPORT_ID, "approaches": [{"id": "bounded-gp"}]},
    )
    handoff_name = "handoff_to_step6" if step6 else "handoff_to_step3"
    handoff = root / "objects/handoff" / f"{handoff_name}__{REPORT_ID}.json"
    _write(handoff, {"report_id": REPORT_ID, "status": "existing_formal_handoff"})
    return handoff


def _scope() -> DerivationScope:
    return DerivationScope(
        "fixture:response-v1",
        "causal kernels",
        "finite signed impulses",
        "zero",
        "event",
        "missing is not zero",
        "signed J to y",
        ("causal convolution", "linear superposition"),
        ("temporary response decays", "two scales can separate"),
        "response scale count unknown",
        ("transient_exponential_kernel", "permanent_component", "two_scale_superposition"),
        ("parameter_search", "structure_search"),
    )


def _data() -> FitData:
    return FitData((1.0, 0.0, -1.0, 0.0), (1.0, 0.8, -0.36, -0.288), 1.0)


def _run(root: Path, **overrides):
    args = {
        "workspace_root": root,
        "report_id": REPORT_ID,
        "run_id": "run-001",
        "fit_data": _data(),
        "scope": _scope(),
        "schedule_state": ScheduleState(7, 2, 5),
        "handoff_stage": "step2",
        "enabled": True,
        "seed": 6,
        "max_evaluations": 8,
        "max_attempts": 12,
    }
    args.update(overrides)
    return run_hybrid_episode(**args)


def _request(path: Path) -> Path:
    payload = {
        "contract_version": "hybrid_research_request_v1",
        "report_id": REPORT_ID,
        "run_id": "ultimate-run-001",
        "handoff_stage": "step2",
        "split": "development",
        "fit_data": {
            "signed_impulses": list(_data().signed_impulses),
            "observed_response": list(_data().observed_response),
            "step": _data().step,
        },
        "derivation_scope": asdict(_scope()),
        "schedule_state": asdict(ScheduleState(7, 2, 5)),
        "search_config": {"seed": 6, "max_evaluations": 8, "max_attempts": 12},
    }
    _write(path, payload)
    return path


def _response(path: Path, *, decision: str = "revise_scope", question: str = "Test a held-out shock schedule.") -> Path:
    _write(
        path,
        {
            "decision": decision,
            "next_research_question": question,
            "unknowns": ["The visible fit does not identify the economic mechanism."],
            "overclaim_guard": ["No alpha or formal approval follows."],
        },
    )
    return path


def _episode_identity(outcome) -> tuple[str, str]:
    journal = json.loads(Path(outcome.journal_path).read_text(encoding="utf-8"))
    episode = journal["hybrid_research"]["episodes"][0]
    return episode["input_identity"], episode["researcher_material_sha256"]


def test_default_off_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    before = set(tmp_path.rglob("*"))
    result = _run(tmp_path, enabled=False)
    assert result.status == "disabled"
    assert set(tmp_path.rglob("*")) == before


def test_opt_in_preserves_journal_and_waits_for_real_researcher(tmp_path: Path) -> None:
    _fixture(tmp_path, step6=True)
    outcome = _run(tmp_path, handoff_stage="step6")
    journal = json.loads(Path(outcome.journal_path).read_text(encoding="utf-8"))
    material = json.loads(Path(outcome.researcher_material_path).read_text(encoding="utf-8"))

    assert journal["preserved"] == {"old": True}
    assert journal["hybrid_research"]["current_schedule_state"] == {
        "episode_index": 7,
        "explore_allocations": 2,
        "exploit_allocations": 5,
    }
    assert material["status"] == "computed_awaiting_researcher"
    assert material["formal_approval"] is False
    assert material["policy_update_eligible"] is False
    assert material["used_budget"]["actual_cost"] is None
    assert material["schedule_state_before"] == material["schedule_state_after"]
    assert material["model_selection"]["selected_model"] == "causal_response"
    assert material["approach_context"]["approaches"][0]["id"] == "bounded-gp"
    assert material["source_bindings"]["handoff"]["path"].startswith(
        "objects/handoff/handoff_to_step6__"
    )
    assert "hidden_evaluation" not in material
    assert outcome.search_result is not None


@pytest.mark.parametrize("split", ("final", "confirmation"))
def test_final_and_confirmation_cannot_drive_gp_fitness(tmp_path: Path, split: str) -> None:
    _fixture(tmp_path)
    journal = tmp_path / "objects/research_journal" / f"research_journal__{REPORT_ID}.json"
    before = journal.read_bytes()
    with pytest.raises(HybridResearchError, match="development-only"):
        _run(tmp_path, split=split)
    assert journal.read_bytes() == before


def test_repeated_resume_does_not_rerun_or_double_record(tmp_path: Path) -> None:
    _fixture(tmp_path)
    first = _run(tmp_path)
    journal_path = Path(first.journal_path)
    material_path = Path(first.researcher_material_path)
    journal_bytes = journal_path.read_bytes()
    material_bytes = material_path.read_bytes()

    resumed = _run(tmp_path)

    assert resumed.resumed is True
    assert resumed.search_result is None
    assert journal_path.read_bytes() == journal_bytes
    assert material_path.read_bytes() == material_bytes
    journal = json.loads(journal_bytes)
    assert len(journal["hybrid_research"]["episodes"]) == 1


def test_same_run_id_rejects_changed_input_identity(tmp_path: Path) -> None:
    _fixture(tmp_path)
    _run(tmp_path)
    with pytest.raises(HybridResearchError, match="another input"):
        _run(tmp_path, seed=7)


def test_orphan_material_is_recovered_without_rerunning_search(tmp_path: Path) -> None:
    _fixture(tmp_path)
    first = _run(tmp_path)
    journal_path = Path(first.journal_path)
    material_path = Path(first.researcher_material_path)
    material_bytes = material_path.read_bytes()
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["hybrid_research"]["episodes"] = []
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    recovered = _run(tmp_path)

    assert recovered.resumed is True
    assert recovered.search_result is None
    assert material_path.read_bytes() == material_bytes
    repaired = json.loads(journal_path.read_text(encoding="utf-8"))
    assert len(repaired["hybrid_research"]["episodes"]) == 1


def test_cross_object_report_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    handoff = _fixture(tmp_path)
    _write(handoff, {"report_id": "another-report"})
    with pytest.raises(HybridResearchError, match="handoff report_id"):
        _run(tmp_path)


def test_search_runtime_failure_is_persisted_and_not_retried(tmp_path: Path, monkeypatch) -> None:
    _fixture(tmp_path)
    calls = []

    def fail_search(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("injected search failure")

    monkeypatch.setattr(
        "factor_factory.hybrid_research.journal_adapter.run_response_gp", fail_search
    )
    with pytest.raises(HybridResearchError, match="was recorded"):
        _run(tmp_path)
    resumed = _run(tmp_path)
    assert len(calls) == 1
    assert resumed.status == "execution_failed"
    journal = json.loads(Path(resumed.journal_path).read_text(encoding="utf-8"))
    episode = journal["hybrid_research"]["episodes"][0]
    assert episode["execution_failure"]["phase"] == "search_execution"
    assert episode["used_budget"]["attempts"] is None


def test_missing_formal_inputs_stops_without_creating_journal(tmp_path: Path) -> None:
    with pytest.raises(HybridResearchError, match="required existing Ultimate artifacts"):
        _run(tmp_path)
    assert not (tmp_path / "objects/research_journal").exists()


def test_researcher_response_default_off_has_no_side_effect(tmp_path: Path) -> None:
    result = record_hybrid_researcher_response(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        run_id="run-001",
        input_identity="a" * 64,
        material_sha256="b" * 64,
        response_path=tmp_path / "missing.json",
        enabled=False,
    )
    assert result.status == "disabled"
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize(
    "decision",
    ("retain_for_more_development", "revise_scope", "reject", "stop_insufficient_evidence"),
)
def test_real_researcher_response_is_bound_without_mutating_material_or_schedule(
    tmp_path: Path, decision: str
) -> None:
    _fixture(tmp_path)
    computed = _run(tmp_path)
    input_identity, material_sha = _episode_identity(computed)
    material_path = Path(computed.researcher_material_path)
    material_before = material_path.read_bytes()
    response = _response(tmp_path / "external/B.json", decision=decision)

    recorded = record_hybrid_researcher_response(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        run_id="run-001",
        input_identity=input_identity,
        material_sha256=material_sha,
        response_path=response,
        enabled=True,
    )

    assert recorded.status == "researcher_response_recorded"
    assert material_path.read_bytes() == material_before
    journal = json.loads(Path(recorded.journal_path).read_text(encoding="utf-8"))
    episode = journal["hybrid_research"]["episodes"][0]
    record = episode["researcher_response"]
    assert episode["status"] == "researcher_response_recorded"
    assert record["decision"] == decision
    assert record["next_research_question"] == "Test a held-out shock schedule."
    assert json.loads(record["original_response_text"])["unknowns"]
    assert record["formal_approval"] is False
    assert record["policy_update_eligible"] is False
    assert record["knowledge_write_allowed"] is False
    assert record["next_experiment_dispatched"] is False
    assert journal["hybrid_research"]["current_schedule_state"] == {
        "episode_index": 7,
        "explore_allocations": 2,
        "exploit_allocations": 5,
    }


def test_same_researcher_response_is_idempotent_and_search_resume_preserves_it(tmp_path: Path) -> None:
    _fixture(tmp_path)
    computed = _run(tmp_path)
    input_identity, material_sha = _episode_identity(computed)
    response = _response(tmp_path / "external/B.json")
    arguments = {
        "workspace_root": tmp_path,
        "report_id": REPORT_ID,
        "run_id": "run-001",
        "input_identity": input_identity,
        "material_sha256": material_sha,
        "response_path": response,
        "enabled": True,
    }
    first = record_hybrid_researcher_response(**arguments)
    journal_path = Path(first.journal_path)
    journal_bytes = journal_path.read_bytes()
    second = record_hybrid_researcher_response(**arguments)
    resumed_search = _run(tmp_path)

    assert second.resumed is True
    assert resumed_search.resumed is True
    assert resumed_search.status == "researcher_response_recorded"
    assert journal_path.read_bytes() == journal_bytes
    journal = json.loads(journal_bytes)
    assert len(journal["hybrid_research"]["episodes"]) == 1


def test_conflicting_or_misbound_researcher_response_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    computed = _run(tmp_path)
    input_identity, material_sha = _episode_identity(computed)
    response = _response(tmp_path / "external/B.json")
    base = {
        "workspace_root": tmp_path,
        "report_id": REPORT_ID,
        "run_id": "run-001",
        "input_identity": input_identity,
        "material_sha256": material_sha,
        "response_path": response,
        "enabled": True,
    }
    record_hybrid_researcher_response(**base)
    journal = Path(computed.journal_path)
    before = journal.read_bytes()

    _response(response, decision="reject", question="Stop this branch.")
    with pytest.raises(HybridResearchError, match="conflicting"):
        record_hybrid_researcher_response(**base)
    with pytest.raises(HybridResearchError, match="input_identity mismatch"):
        record_hybrid_researcher_response(**{**base, "input_identity": "c" * 64})
    with pytest.raises(HybridResearchError, match="material identity mismatch"):
        record_hybrid_researcher_response(**{**base, "material_sha256": "d" * 64})
    with pytest.raises(HybridResearchError, match="missing or duplicated"):
        record_hybrid_researcher_response(**{**base, "run_id": "missing-run"})
    assert journal.read_bytes() == before


def test_primary_B_shape_and_erratum_are_preserved_without_rewriting(tmp_path: Path) -> None:
    _fixture(tmp_path)
    computed = _run(tmp_path)
    input_identity, material_sha = _episode_identity(computed)
    material_path = Path(computed.researcher_material_path)
    response = tmp_path / "external/primary_B.json"
    payload = {
        "report_id": REPORT_ID,
        "run_id": "run-001",
        "decision": "stop_insufficient_evidence",
        "evidence_binding": {
            "material": {
                "path": str(material_path),
                "sha256": material_sha,
                "input_identity": input_identity,
            }
        },
        "next_experiment_and_kill_criterion": {
            "question": "Can randomized signed interventions separate common shocks?",
            "design": "Use positive, negative and sham arms.",
            "kill_criterion": "Stop if timing or controls are invalid.",
        },
    }
    _write(response, payload)
    original_response = response.read_text(encoding="utf-8")
    erratum = tmp_path / "external/primary_B_erratum.md"
    erratum.parent.mkdir(parents=True, exist_ok=True)
    erratum.write_text("The source-only note preceded method guidance; the full A followed it.", encoding="utf-8")

    result = record_hybrid_researcher_response(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        run_id="run-001",
        input_identity=input_identity,
        material_sha256=material_sha,
        response_path=response,
        erratum_path=erratum,
        enabled=True,
    )
    journal = json.loads(Path(result.journal_path).read_text(encoding="utf-8"))
    record = journal["hybrid_research"]["episodes"][0]["researcher_response"]
    assert record["original_response_text"] == original_response
    assert record["next_research_record"] == payload["next_experiment_and_kill_criterion"]
    assert record["next_research_question"] == payload["next_experiment_and_kill_criterion"]["question"]
    assert record["erratum"]["original_text"] == erratum.read_text(encoding="utf-8")


def test_challenger_B_shape_uses_nested_identity_and_design_question(tmp_path: Path) -> None:
    _fixture(tmp_path)
    computed = _run(tmp_path)
    input_identity, material_sha = _episode_identity(computed)
    material_path = Path(computed.researcher_material_path)
    response = tmp_path / "external/challenger_B.json"
    payload = {
        "decision": "stop_insufficient_evidence",
        "evidence_identity": {
            "report_id": REPORT_ID,
            "run_id": "run-001",
            "material_path": str(material_path),
            "input_identity": input_identity,
        },
        "next_experiment": {
            "scope": "Proposal only.",
            "design": "Randomize positive, negative and sham isolated pulses.",
            "kill_criterion": "Stop if the control cannot separate common influence.",
        },
    }
    _write(response, payload)

    result = record_hybrid_researcher_response(
        workspace_root=tmp_path,
        report_id=REPORT_ID,
        run_id="run-001",
        input_identity=input_identity,
        material_sha256=material_sha,
        response_path=response,
        enabled=True,
    )
    journal = json.loads(Path(result.journal_path).read_text(encoding="utf-8"))
    record = journal["hybrid_research"]["episodes"][0]["researcher_response"]
    assert record["next_research_record"] == payload["next_experiment"]
    assert record["next_research_question"] == payload["next_experiment"]["design"]


def test_response_evidence_binding_mismatch_is_rejected(tmp_path: Path) -> None:
    _fixture(tmp_path)
    computed = _run(tmp_path)
    input_identity, material_sha = _episode_identity(computed)
    response = tmp_path / "external/B.json"
    _write(
        response,
        {
            "report_id": REPORT_ID,
            "run_id": "wrong-run",
            "decision": "reject",
            "evidence_binding": {
                "material": {
                    "path": computed.researcher_material_path,
                    "sha256": material_sha,
                    "input_identity": input_identity,
                }
            },
            "next_experiment_and_kill_criterion": {"question": "Should this branch stop?"},
        },
    )
    with pytest.raises(HybridResearchError, match="run_id mismatch"):
        record_hybrid_researcher_response(
            workspace_root=tmp_path,
            report_id=REPORT_ID,
            run_id="run-001",
            input_identity=input_identity,
            material_sha256=material_sha,
            response_path=response,
            enabled=True,
        )


def test_engineering_cli_opt_in_then_resume(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts/run_hybrid_research_episode.py"
    command = [
        sys.executable,
        str(script),
        "--workspace-root",
        str(tmp_path),
        "--enable",
        "--bootstrap-engineering-fixture",
    ]
    first = json.loads(subprocess.run(command, check=True, text=True, capture_output=True).stdout)
    second = json.loads(subprocess.run(command, check=True, text=True, capture_output=True).stdout)

    assert first["status"] == "computed_awaiting_researcher"
    assert first["resumed"] is False
    assert second["resumed"] is True
    assert second["input_identity"] == first["input_identity"]

    assert second["engineering_hidden_evaluation_path"] == first[
        "engineering_hidden_evaluation_path"
    ]
    material = json.loads(Path(first["researcher_material_path"]).read_text(encoding="utf-8"))
    assert "hidden_model_label" not in json.dumps(material)


def test_existing_ultimate_entrypoint_helper_runs_explicit_request_and_resumes(tmp_path: Path) -> None:
    _fixture(tmp_path)
    request = _request(tmp_path / "identity/hybrid_request.json")
    script = Path(__file__).parents[1] / "scripts/run_factorforge_ultimate.py"
    spec = importlib.util.spec_from_file_location("ultimate_hybrid_entry", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)

    first = module.run_hybrid_research_opt_in_non_authoritative(
        active_root=tmp_path, report_id=REPORT_ID, request_path=request
    )
    second = module.run_hybrid_research_opt_in_non_authoritative(
        active_root=tmp_path, report_id=REPORT_ID, request_path=request
    )

    assert first["status"] == "computed_awaiting_researcher"
    assert first["formal_proof_effect"] == "none"
    assert first["resumed"] is False
    assert second["resumed"] is True
    assert second["input_identity"] == first["input_identity"]

    original_argv = sys.argv
    try:
        sys.argv = [str(script), "--report-id", REPORT_ID]
        assert module.parse_args().hybrid_research_request is None
    finally:
        sys.argv = original_argv


def test_existing_ultimate_cli_opt_in_and_resume(tmp_path: Path) -> None:
    _fixture(tmp_path)
    request = _request(tmp_path / "identity/hybrid_request.json")
    script = Path(__file__).parents[1] / "scripts/run_factorforge_ultimate.py"
    command = [
        sys.executable,
        str(script),
        "--report-id",
        REPORT_ID,
        "--factorforge-root",
        str(tmp_path),
        "--local-is-only",
        "--hybrid-research-adapter-only",
        "--hybrid-research-request",
        str(request),
    ]
    first = json.loads(subprocess.run(command, check=True, text=True, capture_output=True).stdout)
    second = json.loads(subprocess.run(command, check=True, text=True, capture_output=True).stdout)

    assert first["status"] == "computed_awaiting_researcher"
    assert first["resumed"] is False
    assert first["formal_approval"] is False
    assert first["formal_proof_effect"] == "none"
    assert second["resumed"] is True
    assert second["input_identity"] == first["input_identity"]

    journal = json.loads(Path(first["journal_path"]).read_text(encoding="utf-8"))
    episode = journal["hybrid_research"]["episodes"][0]
    response = _response(
        tmp_path / "external/B.json",
        decision="stop_insufficient_evidence",
        question="Use an independently randomized intervention and sham control.",
    )
    response_command = [
        sys.executable,
        str(script),
        "--report-id",
        REPORT_ID,
        "--factorforge-root",
        str(tmp_path),
        "--local-is-only",
        "--hybrid-research-response-only",
        "--hybrid-research-response",
        str(response),
        "--hybrid-research-response-run-id",
        episode["run_id"],
        "--hybrid-research-response-input-identity",
        episode["input_identity"],
        "--hybrid-research-response-material-sha256",
        episode["researcher_material_sha256"],
    ]
    recorded = json.loads(
        subprocess.run(response_command, check=True, text=True, capture_output=True).stdout
    )
    repeated = json.loads(
        subprocess.run(response_command, check=True, text=True, capture_output=True).stdout
    )
    assert recorded["status"] == "researcher_response_recorded"
    assert recorded["resumed"] is False
    assert recorded["formal_proof_effect"] == "none"
    assert recorded["policy_update_eligible"] is False
    assert recorded["next_experiment_dispatched"] is False
    assert repeated["resumed"] is True
