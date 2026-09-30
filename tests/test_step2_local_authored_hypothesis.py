"""Offline intake tests, not factor research or independent-review evidence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "authored_hypothesis_step2", ROOT / "skills/factor-forge-step2/scripts/run_step2.py"
)
STEP2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STEP2)
SOURCE = "natural_language_hypothesis"
PRODUCER = "step12_hypothesis_intake"


def write_ref(root, route, payload):
    relative = f"inputs/{route}.json"
    raw = json.dumps(payload, sort_keys=True).encode()
    (root / "inputs").mkdir(exist_ok=True)
    (root / relative).write_bytes(raw)
    return {
        "relative_path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
        "role": f"local_agent_{route}_spec",
        "identity": {key: payload[key] for key in (
            "report_id", "factor_id", "route", "source_type", "producer"
        )},
    }


def inputs(root):
    primary = {
        "report_id": "AUTHORED_TEST", "factor_id": "EXACT_TEST", "route": "primary",
        "source_type": SOURCE, "producer": PRODUCER,
        "raw_formula_text": "bounded_custom_estimator(close, amount)",
        "operators": [], "required_inputs": ["close", "amount"],
        "time_series_steps": ["Use authored calendar-indexed observations."],
        "cross_sectional_steps": ["Pool current eligible observations as specified."],
        "preprocessing": ["Missing is not zero."], "normalization": [],
        "neutralization": [], "rebalance_frequency": "monthly",
        "explicit_items": ["Primary independent measurement argument."],
        "inferred_items": ["Frozen estimation assumption."], "ambiguities": [],
        "candidate_only": True, "oos_accessed": False,
    }
    challenger = deepcopy(primary)
    challenger.update(route="challenger", explicit_items=["Distinct challenger noise critique."])
    aim = {
        "report_id": "AUTHORED_TEST", "factor_id": "EXACT_TEST", "source_type": SOURCE,
        "producer": PRODUCER, "implementation_mode": "direct_code",
        "research_subject_mode": "source_extension",
        "final_factor": {"name": "EXACT_TEST"},
        "source_baseline_reference": {
            "source_construction_id": "HISTORICAL_IDEA",
            "selected_construction_id": "EXACT_TEST", "relation": "source_extension",
        },
        "local_agent_spec_inputs": {
            "primary": write_ref(root, "primary", primary),
            "challenger": write_ref(root, "challenger", challenger),
            "chief_canonical_core": {
                key: deepcopy(primary[key]) for key in STEP2.LOCAL_HYPOTHESIS_CANONICAL_CORE_FIELDS
            },
        },
        "evaluation_contract": {"rebalance_frequency": "monthly"},
        "research_discipline": {
            "target_statistic_hint": "Authored persistent statistic.",
            "step1_mathematical_object": "Authored local mean.",
            "market_process_thesis": {"economic_hypothesis": "Authored economics."},
            "expected_failure_modes": ["Authored noise identification failure."],
            "innovative_idea_seeds": ["Explicit bounded alternative."],
            "reuse_instruction_for_future_agents": ["Preserve this measurement boundary."],
            "similar_case_lessons_imported": ["Explicit prior; no empirical claim."],
            "factor_knowledge_context": {"nodes": []},
            "knowledge_reference_contract": {"retrieval_status": "unavailable"},
        },
        "implementation_contract": {"code_contract": {
            "source_code": "def compute_factor(frame):\n    return frame\n",
            "entrypoint": "compute_factor", "required_fields": ["close", "amount"],
            "source_derivation": {"not_fallback": True, "test_only": True},
        }},
    }
    return aim, primary, challenger


def load(tmp_path, monkeypatch, aim):
    monkeypatch.setenv("FACTORFORGE_LOCAL_IS_ONLY", "1")
    monkeypatch.setattr(STEP2, "FACTORFORGE", tmp_path)
    return STEP2.load_local_agent_dual_route_specs("AUTHORED_TEST", aim)


def test_exact_distinct_readings_and_empty_normalization_survive(tmp_path, monkeypatch):
    aim, primary, challenger = inputs(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / "inputs").iterdir()}
    actual = load(tmp_path, monkeypatch, aim)
    assert actual == (primary, challenger)
    assert actual[0]["explicit_items"] != actual[1]["explicit_items"]
    assert actual[0]["normalization"] == actual[0]["operators"] == []
    assert before == {p: p.read_bytes() for p in before}


def test_master_preserves_authored_core_and_research_contract(tmp_path, monkeypatch):
    aim, primary, _ = inputs(tmp_path)
    primary, challenger = load(tmp_path, monkeypatch, aim)
    # Isolate transport from measurement validator tests; not an acceptance claim.
    program = {"implementation": {"route": "direct_code"}, "transport_test_only": True}
    monkeypatch.setattr(STEP2, "validated_step1_measurement_program", lambda **kw: deepcopy(program))
    monkeypatch.setattr(STEP2, "configured_advisory_root", lambda: None)
    for name in ("infer_expected_failure_modes", "infer_innovative_idea_seeds", "build_reuse_instructions"):
        monkeypatch.setattr(STEP2, name, lambda *a: pytest.fail("must not synthesize authored research"))
    consistency = STEP2.score_consistency(primary, challenger, aim)
    master = STEP2.build_factor_spec_master("AUTHORED_TEST", aim, primary, consistency, {})
    for key in STEP2.LOCAL_HYPOTHESIS_CANONICAL_CORE_FIELDS:
        dest = "formula_text" if key == "raw_formula_text" else key
        assert master["canonical_spec"][dest] == primary[key]
    assert master["research_contract"]["expected_failure_modes"] == aim["research_discipline"]["expected_failure_modes"]
    assert master["research_contract"]["economic_mechanism"] == "Authored economics."
    assert master["producer"] == master["upstream_producer"] == PRODUCER
    assert master["canonical_spec"]["mechanism_conditioned_measurement_program"] == program


@pytest.mark.parametrize("mutation, message", [
    ("aim_producer", "AIM source/producer mismatch"),
    ("ref_source", "identity mismatch"),
    ("raw_source", "raw spec source/producer mismatch"),
    ("raw_producer", "raw spec source/producer mismatch"),
    ("hash", "sha256 mismatch"),
    ("normalization", "canonical core mismatch"),
    ("same_file", "identity mismatch"),
    ("unsupported_source", "only valid for pdf_report or natural_language_hypothesis"),
])
def test_authored_hypothesis_fail_closed(tmp_path, monkeypatch, mutation, message):
    aim, primary, challenger = inputs(tmp_path)
    refs = aim["local_agent_spec_inputs"]
    if mutation == "aim_producer":
        aim["producer"] = "step2_pdf_report"
    elif mutation == "ref_source":
        refs["primary"]["identity"]["source_type"] = "pdf_report"
    elif mutation in {"raw_source", "raw_producer"}:
        primary["source_type" if mutation == "raw_source" else "producer"] = "pdf_report"
        old_identity = refs["primary"]["identity"]
        refs["primary"] = write_ref(tmp_path, "primary", primary)
        refs["primary"]["identity"] = old_identity
    elif mutation == "hash":
        refs["primary"]["sha256"] = "0" * 64
    elif mutation == "normalization":
        challenger["normalization"] = ["rank"]
        refs["challenger"] = write_ref(tmp_path, "challenger", challenger)
    elif mutation == "same_file":
        refs["challenger"].update(relative_path=refs["primary"]["relative_path"], sha256=refs["primary"]["sha256"])
    else:
        aim["source_type"] = "paper_canonical_formula"
    with pytest.raises(SystemExit, match=message):
        load(tmp_path, monkeypatch, aim)


def test_authored_route_dry_run_never_calls_generic_or_pdf(tmp_path, monkeypatch):
    aim, expected, _ = inputs(tmp_path)
    load(tmp_path, monkeypatch, aim)
    monkeypatch.setattr(STEP2, "load_alpha_idea_master", lambda _: aim)
    for name in ("load_source_context", "build_primary_spec_from_hypothesis", "locate_pdf_path"):
        monkeypatch.setattr(STEP2, name, lambda *a: pytest.fail("authored route must bypass templates/PDF"))
    seen = {}
    monkeypatch.setattr(STEP2, "build_factor_spec_master", lambda *a, **kw: seen.update(primary=a[2]) or {})
    STEP2.run_step2("AUTHORED_TEST", dry_run=True)
    assert seen["primary"] == expected
    assert not (tmp_path / "objects").exists()


def test_pdf_original_ref_shape_remains_strict(tmp_path, monkeypatch):
    aim, primary, challenger = inputs(tmp_path)
    aim["source_type"] = "pdf_report"
    aim.pop("producer")
    refs = aim["local_agent_spec_inputs"]
    for route, raw in (("primary", primary), ("challenger", challenger)):
        raw.pop("source_type")
        raw.pop("producer")
        relative = refs[route]["relative_path"]
        data = json.dumps(raw, sort_keys=True).encode()
        (tmp_path / relative).write_bytes(data)
        refs[route]["sha256"] = hashlib.sha256(data).hexdigest()
        refs[route]["identity"].pop("source_type")
        refs[route]["identity"].pop("producer")
    refs["chief_canonical_core"] = {
        key: primary[key] for key in STEP2.LOCAL_AGENT_SPEC_CANONICAL_CORE_FIELDS
    }
    assert load(tmp_path, monkeypatch, aim) == (primary, challenger)
    primary.update(source_type=SOURCE, producer=PRODUCER)
    data = json.dumps(primary, sort_keys=True).encode()
    (tmp_path / refs["primary"]["relative_path"]).write_bytes(data)
    refs["primary"]["sha256"] = hashlib.sha256(data).hexdigest()
    with pytest.raises(SystemExit, match="raw spec source/producer mismatch"):
        load(tmp_path, monkeypatch, aim)
