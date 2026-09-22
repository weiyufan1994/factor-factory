from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from factor_factory.measurement_program import measurement_program_template, validate_measurement_program
from factor_factory.research_workspace import build_workspace_manifest, write_workspace_manifest
from skills.factor_forge_step1.modules.report_ingestion.intake.structured_intake_contract import StructuredIntake
import skills.factor_forge_step1.modules.report_ingestion.merge.merge_to_alpha_idea_master as merge_module


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_factorforge_local_step1.py"
REPORT_ID = "RPT_pdf_local_step1_test"


def load_step2_module():
    spec = importlib.util.spec_from_file_location(
        "local_step1_test_step2_runner", ROOT / "skills" / "factor-forge-step2" / "scripts" / "run_step2.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_step2_validator_module():
    spec = importlib.util.spec_from_file_location(
        "local_step1_test_step2_validator", ROOT / "skills" / "factor-forge-step2" / "scripts" / "validate_step2.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def make_workspace(tmp_path: Path) -> Path:
    factorforge_root = tmp_path / "factorforge-root"
    workspace = factorforge_root / "factor_research" / "local_step1" / "case_a"
    manifest = build_workspace_manifest(
        repo_root=ROOT,
        factorforge_root=factorforge_root,
        factor_id="local_step1",
        research_id="case_a",
        root_report_id=REPORT_ID,
    )
    write_workspace_manifest(workspace / "manifest.json", manifest)
    return workspace


def identity(role: str, agent_id: str) -> dict:
    return {
        "agent_id": agent_id,
        "role": role,
        "authorship": "agent_authored",
        "description": f"real local {role} declaration",
    }


def intake(name: str, extension: str) -> dict:
    return {
        "report_meta": {"title": "Local test report", "broker": "test", "topic": "test"},
        "section_map": [{"section_title": "method", "summary": "source-derived summary"}],
        "variables": ["close"],
        "signals": ["test_signal"],
        "subfactors": [{"name": "component", "formula_or_expression": "rank(close)"}],
        "final_factor": {
            "name": name,
            "assembly_steps": ["rank close"],
            "economic_logic": "caller-authored economic mechanism",
            "behavioral_logic": "caller-authored behavioral mechanism",
            "causal_chain": "state to payoff",
        },
        "formula_clues": [{"content": "rank(close)", "location_hint": "p1"}],
        "code_clues": [],
        "implementation_clues": [],
        "alpha_candidates": [{"name": name, "logic": "caller", "direction": "positive"}],
        "evidence_clues": [],
        "ambiguities": [],
        "agent_extension": {"preserve": extension},
    }


def valid_measurement_program() -> dict:
    placeholder = "LOCAL_STEP1_TEST_REPLACE"
    program = measurement_program_template(placeholder=placeholder, implementation_route="direct_code")

    def fill(value):
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return "authored mechanism statement" if value == placeholder else value

    result = fill(program)
    candidates = result["model_selection"]["candidate_models"]
    candidates[0].update(
        {
            "model_family": "chief-selected distinct model",
            "mechanism_equation_or_functional": "chief_object_t=chief_mechanism(inputs_t)",
            "target_functional": result["observation_and_estimation"]["estimand"],
            "market_outcome_projection": result["market_outcome_projection"]["projection_equation_or_map"],
            "observation_mapping": result["observation_and_estimation"]["observation_map"],
        }
    )
    candidates[1].update(
        {
            "model_family": "chief alternative distinct model",
            "mechanism_equation_or_functional": "alternative_t=alternative_mechanism(inputs_t)",
            "target_functional": "alternative chief estimand",
            "market_outcome_projection": "alternative chief market payoff map",
            "observation_mapping": "alternative legal observation map",
        }
    )
    candidates[2].update(
        {
            "model_family": "chief null distinct model",
            "mechanism_equation_or_functional": "null_t=alias_controls_t+noise_t",
            "target_functional": "zero incremental payoff",
            "market_outcome_projection": "null implies zero payoff",
            "observation_mapping": "legal alias projection",
        }
    )
    return result


def authored_discipline() -> dict:
    program = valid_measurement_program()
    market_thesis = {
        "custom_extension": "must remain exact",
        "economic_hypothesis": "DISTINCT_CHIEF_ECONOMIC_MECHANISM",
    }
    return {
        "step1_mathematical_object": "DISTINCT_CHIEF_MATHEMATICAL_OBJECT",
        "target_statistic_hint": "DISTINCT_CHIEF_TARGET_STATISTIC",
        "information_set_hint": "DISTINCT_CHIEF_LEGAL_INFORMATION_SET",
        "initial_return_source_hypothesis": "mixed",
        "economic_hypothesis": {"chief": "distinct economics"},
        "math_hypothesis_candidates": [{"chief": "distinct math candidate"}],
        "market_process_thesis": market_thesis,
        "expected_failure_modes": ["DISTINCT_CHIEF_FAILURE_MODE"],
        "innovative_idea_seeds": ["DISTINCT_CHIEF_INNOVATION_SEED"],
        "reuse_instruction_for_future_agents": ["DISTINCT_CHIEF_REUSE_INSTRUCTION"],
        "primary_mechanism_model_candidates": [{"chief": "distinct model candidate"}],
        "market_outcome_projection": {"chief": "distinct market projection"},
        "what_must_be_true": ["DISTINCT_CHIEF_ASSUMPTION"],
        "what_would_break_it": ["DISTINCT_CHIEF_FALSIFIER"],
        "similar_case_lessons_imported": ["DISTINCT_CHIEF_KB_LESSON"],
        "knowledge_reference_contract": {"contract_version": "caller-authored-kb-context", "custom": "DISTINCT_CHIEF_KB"},
        "factor_knowledge_context": {"nodes": [{"id": "DISTINCT_CHIEF_KB_NODE"}], "custom": "context"},
        "mechanism_conditioned_measurement_program": program,
    }


def inputs(tmp_path: Path, *, bad_primary_role: bool = False, omit_original: bool = False) -> dict[str, Path]:
    report_path = tmp_path / "inputs" / "report.pdf"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(b"%PDF-1.7\noriginal report bytes")
    original = {
        "content_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "description": "caller reviewed original local PDF bytes",
    }
    source = {
        "report_id": REPORT_ID,
        "source": {
            "source_type": "pdf",
            "source_uri": "file:///caller-supplied/report.pdf",
            "title": "Local test report",
            "local_cache_path": str(report_path),
            **({"original_source": original} if not omit_original else {}),
        },
        "reader_identity": identity("local_source_reader", "source-reader"),
        "reading_context": {"caller_note": "metadata only; not an independence claim"},
    }
    primary = {"authorship": identity("wrong_role" if bad_primary_role else "primary_reader", "primary-reader"), "intake": intake("PFVV", "primary extension")}
    challenger = {"authorship": identity("challenger_reader", "challenger-reader"), "intake": intake("PFVV", "challenger extension")}
    discipline = authored_discipline()
    code_contract = {
        "code_contract_version": "factorforge_direct_code_contract_v1",
        "function_name": "compute_factor",
        "entrypoint": "compute_factor",
        "source_code": "def compute_factor(daily_df):\n    return daily_df\n",
        "imports": ["pandas"],
        "required_fields": ["close"],
        "information_set_rules": ["close is observed at or before t"],
        "forbidden_patterns": ["future_return"],
    }
    chief = {
        "authorship": identity("chief_merge", "chief-reader"),
        "chief_merge": {
            "report_id": REPORT_ID,
            "final_factor": {
                "name": "PFVV",
                "assembly_steps": ["rank close"],
                "economic_logic": "chief economic extension",
                "behavioral_logic": "chief behavioral extension",
                "causal_chain": "chief state to payoff",
            },
            "chief_decision_summary": "caller-authored merge",
            "chief_confidence": "low",
            "chief_rationale": "preserve uncertainty",
            "market_process_thesis": deepcopy(discipline["market_process_thesis"]),
            "primary_mathematical_model": {"custom_math": "chief authored"},
            "research_discipline": discipline,
            "factor_id": "DISTINCT_CHIEF_FACTOR_ID",
            "source_type": "chief-authored-pdf-source-type",
            "research_subject_mode": "report_replication",
            "source_baseline_reference": {"reference": "DISTINCT_BASELINE"},
            "source_semantic_review": {"review": "DISTINCT_SEMANTIC_REVIEW"},
            "local_agent_spec_inputs": {"input": "DISTINCT_LOCAL_AGENT_INPUT"},
            "direct_code_spec": {"entrypoint": "DISTINCT_DIRECT_CODE"},
            "code_contract": deepcopy(code_contract),
            "direct_code_contract": deepcopy(code_contract),
            "implementation_contract": {"code_contract": deepcopy(code_contract)},
            "batch_execution_plan": {"batch": "DISTINCT_BATCH_PLAN"},
            "research_window_contract": {"window": "DISTINCT_RESEARCH_WINDOW"},
            "evaluation_contract": {"evaluation": "DISTINCT_EVALUATION_CONTRACT"},
        },
    }
    return {
        "source": write_json(tmp_path / "inputs" / "source.json", source),
        "primary": write_json(tmp_path / "inputs" / "primary.json", primary),
        "challenger": write_json(tmp_path / "inputs" / "challenger.json", challenger),
        "chief": write_json(tmp_path / "inputs" / "chief.json", chief),
    }


def invoke(workspace: Path, files: dict[str, Path]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--factor-workspace", str(workspace),
            "--report-id", REPORT_ID,
            "--source-json", str(files["source"]),
            "--primary-intake", str(files["primary"]),
            "--challenger-intake", str(files["challenger"]),
            "--chief-merge", str(files["chief"]),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def test_local_step1_imports_authored_inputs_and_preserves_extensions(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = invoke(workspace, inputs(tmp_path))
    assert result.returncode == 0, result.stderr
    alpha = json.loads((workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json").read_text())
    assert alpha["local_step1_declaration"]["provider_or_model_called"] is False
    assert alpha["local_step1_declaration"]["independent_certification"] is False
    assert alpha["agent_authored_evidence"]["primary"]["intake"]["agent_extension"]["preserve"] == "primary extension"
    assert alpha["agent_authored_evidence"]["challenger"]["intake"]["agent_extension"]["preserve"] == "challenger extension"
    assert alpha["agent_authored_evidence"]["chief"]["chief_merge"]["market_process_thesis"] == {
        "custom_extension": "must remain exact",
        "economic_hypothesis": "DISTINCT_CHIEF_ECONOMIC_MECHANISM",
    }
    assert alpha["agent_authored_evidence"]["chief"]["chief_merge"]["primary_mathematical_model"] == {"custom_math": "chief authored"}
    assert alpha["research_discipline"]["step1_mathematical_object"] == "DISTINCT_CHIEF_MATHEMATICAL_OBJECT"
    assert alpha["research_discipline"]["knowledge_reference_contract"]["custom"] == "DISTINCT_CHIEF_KB"
    assert alpha["research_discipline"]["similar_case_lessons_imported"] == ["DISTINCT_CHIEF_KB_LESSON"]
    assert alpha["factor_id"] == "DISTINCT_CHIEF_FACTOR_ID"
    assert alpha["source_baseline_reference"] == {"reference": "DISTINCT_BASELINE"}
    assert alpha["direct_code_spec"] == {"entrypoint": "DISTINCT_DIRECT_CODE"}
    assert alpha["code_contract"]["source_code"] == "def compute_factor(daily_df):\n    return daily_df\n"
    assert alpha["direct_code_contract"] == alpha["code_contract"]
    assert alpha["implementation_contract"]["code_contract"] == alpha["code_contract"]
    assert alpha["batch_execution_plan"] == {"batch": "DISTINCT_BATCH_PLAN"}
    assert alpha["research_window_contract"] == {"window": "DISTINCT_RESEARCH_WINDOW"}
    assert alpha["evaluation_contract"] == {"evaluation": "DISTINCT_EVALUATION_CONTRACT"}
    step2 = load_step2_module()
    downstream_contract = step2.explicit_direct_code_source_contract({}, alpha)
    assert downstream_contract["source_code"] == alpha["code_contract"]["source_code"]
    assert downstream_contract["source_derivation"]["not_fallback"] is True
    receipt = json.loads((workspace / "step1" / f"local_step1_ingest__{REPORT_ID}.json").read_text())
    assert receipt["status"] == "LOCAL_STEP1_INGESTED_NOT_INDEPENDENTLY_CERTIFIED"
    assert receipt["next_steps_started"] == []


def test_step2_local_authored_research_contract_never_uses_old_thesis_or_templates(monkeypatch) -> None:
    step2 = load_step2_module()
    discipline = authored_discipline()
    aim = {
        "local_agent_spec_inputs": {"declared": "only route marker for unit test"},
        "research_discipline": discipline,
        "evaluation_contract": {"evaluation": "DISTINCT_LOCAL_EVALUATION"},
    }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("local authored path must not call inference or KB retrieval")

    monkeypatch.setattr(step2, "infer_economic_mechanism", fail_if_called)
    monkeypatch.setattr(step2, "infer_expected_failure_modes", fail_if_called)
    monkeypatch.setattr(step2, "infer_innovative_idea_seeds", fail_if_called)
    monkeypatch.setattr(step2, "build_reuse_instructions", fail_if_called)
    monkeypatch.setattr(step2, "retrieve_step2_factor_knowledge_context", fail_if_called)
    contract = step2.build_step2_research_contract(
        {"raw_formula_text": "OLD_THESIS_FORMULA"},
        {"distortion_risks": ["OLD_THESIS_FAILURE"]},
        aim,
        {
            "economic_logic": "OLD_THESIS_ECONOMICS",
            "behavioral_logic": "OLD_THESIS_BEHAVIOR",
            "causal_chain": "OLD_THESIS_CHAIN",
        },
    )
    assert contract["economic_mechanism"] == "DISTINCT_CHIEF_ECONOMIC_MECHANISM"
    assert contract["expected_failure_modes"] == ["DISTINCT_CHIEF_FAILURE_MODE"]
    assert contract["innovative_idea_seeds"] == ["DISTINCT_CHIEF_INNOVATION_SEED"]
    assert contract["reuse_instruction_for_future_agents"] == ["DISTINCT_CHIEF_REUSE_INSTRUCTION"]
    assert contract["factor_knowledge_context"] == discipline["factor_knowledge_context"]
    assert contract["knowledge_reference_contract"] == discipline["knowledge_reference_contract"]
    assert step2._master_evaluation_contract({}, aim) == {"evaluation": "DISTINCT_LOCAL_EVALUATION"}

    missing = deepcopy(aim)
    missing["research_discipline"].pop("innovative_idea_seeds")
    with pytest.raises(SystemExit, match="innovative_idea_seeds"):
        step2.build_step2_research_contract({}, {}, missing, {})
    missing_evaluation = deepcopy(aim)
    missing_evaluation.pop("evaluation_contract")
    with pytest.raises(SystemExit, match="evaluation_contract"):
        step2._master_evaluation_contract({}, missing_evaluation)


def test_step2_measurement_program_accepts_explicit_carried_context_node_ids_only() -> None:
    validator = load_step2_validator_module()
    program = valid_measurement_program()
    program["implementation"]["components"][0]["knowledge_node_ids"] = ["NODE_FROM_CARRIED_CONTEXT"]
    learning = {"knowledge_reference_contract": {"contract_version": "native-no-cited-node-ids"}}
    research_contract = {
        "knowledge_reference_contract": {"contract_version": "native-no-cited-node-ids"},
        "factor_knowledge_context": {"nodes": [{"id": "NODE_FROM_CARRIED_CONTEXT"}]},
    }
    available = validator.available_knowledge_node_ids_for_measurement_program(
        learning, research_contract
    )
    assert available == {"NODE_FROM_CARRIED_CONTEXT"}
    assert validate_measurement_program(
        program, available_knowledge_node_ids=available, require_web_executable=False
    ) == []
    rejected = validate_measurement_program(
        program, available_knowledge_node_ids=set(), require_web_executable=False
    )
    assert any("knowledge_node_ids_not_in_summary" in reason for reason in rejected)


def test_local_step1_rejects_wrong_agent_identity(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = invoke(workspace, inputs(tmp_path, bad_primary_role=True))
    assert result.returncode == 1
    assert "BLOCK_LOCAL_STEP1_IDENTITY_INVALID" in result.stderr
    partial = workspace / "step1" / f"local_step1_ingest__{REPORT_ID}__partial.json"
    assert json.loads(partial.read_text())["status"] == "LOCAL_STEP1_PARTIAL_NOT_COMPLETE"


def test_local_step1_rejects_missing_chief_and_original_source(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    files = inputs(tmp_path)
    files["chief"] = tmp_path / "inputs" / "missing-chief.json"
    result = invoke(workspace, files)
    assert result.returncode == 1
    assert "BLOCK_LOCAL_STEP1_INPUT_MISSING" in result.stderr
    assert not (workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json").exists()

    missing_original_workspace = make_workspace(tmp_path / "missing-original")
    missing_original = invoke(missing_original_workspace, inputs(tmp_path / "missing-original", omit_original=True))
    assert missing_original.returncode == 1
    # Source validation is intentionally performed before any authored decision can publish.
    assert "BLOCK_LOCAL_STEP1_ORIGINAL_SOURCE_MISSING" in missing_original.stderr
    assert not (
        missing_original_workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json"
    ).exists()


def test_local_step1_rejects_duplicate_target_without_overwrite(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    files = inputs(tmp_path)
    first = invoke(workspace, files)
    assert first.returncode == 0, first.stderr
    alpha_path = workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json"
    before = alpha_path.read_bytes()
    second = invoke(workspace, files)
    assert second.returncode == 1
    assert "BLOCK_LOCAL_STEP1_OUTPUT_EXISTS" in second.stderr
    assert alpha_path.read_bytes() == before


def test_local_step1_rejects_actual_pdf_hash_mismatch_before_publication(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    files = inputs(tmp_path)
    report_path = Path(json.loads(files["source"].read_text())["source"]["local_cache_path"])
    report_path.write_bytes(b"%PDF-1.7\ntampered after caller hash declaration")
    result = invoke(workspace, files)
    assert result.returncode == 1
    assert "BLOCK_LOCAL_STEP1_ORIGINAL_SOURCE_HASH_MISMATCH" in result.stderr
    assert not (workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json").exists()


def test_local_step1_rejects_non_pdf_bytes_even_when_hash_matches(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    files = inputs(tmp_path)
    source = json.loads(files["source"].read_text())
    report_path = Path(source["source"]["local_cache_path"])
    report_path.write_bytes(b"not a PDF, despite its filename")
    source["source"]["original_source"]["content_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    write_json(files["source"], source)
    result = invoke(workspace, files)
    assert result.returncode == 1
    assert "BLOCK_LOCAL_STEP1_ORIGINAL_SOURCE_NOT_PDF" in result.stderr
    assert not (workspace / "objects" / "alpha_idea_master" / f"alpha_idea_master__{REPORT_ID}.json").exists()


def test_agent_authored_only_merge_never_calls_automatic_discipline_builder(monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("automatic discipline builder must not run")

    monkeypatch.setattr(merge_module, "attach_step1_research_discipline", fail_if_called)
    program = {"implementation": {"route": "direct_code"}, "chief": "exact"}
    discipline = {
        "step1_mathematical_object": "DISTINCT_OBJECT",
        "knowledge_reference_contract": {"custom": "DISTINCT_KB"},
        "mechanism_conditioned_measurement_program": program,
    }
    chief = {
        "final_factor": {"name": "Distinct", "assembly_steps": ["authored"]},
        "chief_decision_summary": "authored",
        "chief_confidence": "low",
        "chief_rationale": "authored",
        "research_discipline": discipline,
        "factor_id": "DISTINCT_FACTOR",
    }
    primary = StructuredIntake(report_id=REPORT_ID, report_meta={"title": "source"})
    challenger = StructuredIntake(report_id=REPORT_ID)
    alpha = merge_module.merge_to_alpha_idea_master(
        primary,
        challenger,
        {},
        {},
        chief,
        agent_authored_only=True,
    )
    assert alpha["research_discipline"] == discipline
    assert alpha["mechanism_conditioned_measurement_program"] == program
    assert alpha["factor_id"] == "DISTINCT_FACTOR"
    assert alpha["market_process_thesis_provenance"]["derivation_policy"] == "chief_authored_only_no_inference_or_knowledge_retrieval"
