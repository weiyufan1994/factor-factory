"""Compatibility and semantic handoff tests for the sole Step5 implementation."""
from copy import deepcopy
import importlib
import importlib.util
from pathlib import Path

import pytest

from factor_factory.step5.case_builder import build_factor_case_master


ROOT = Path(__file__).resolve().parents[1]
METADATA_FIELDS = (
    "mechanism_math_contract",
    "mechanism_math_contract_v2",
    "mechanism_conditioned_measurement_program",
)


@pytest.mark.parametrize("package", ["factor-forge-step5", "factor_forge_step5"])
@pytest.mark.parametrize("name", ["io", "archiver", "rules", "evaluator", "validator", "case_builder"])
def test_legacy_imports_and_file_loads_forward_to_same_functions(package, name):
    canonical = importlib.import_module(f"factor_factory.step5.{name}")
    legacy = importlib.import_module(f"skills.{package}.modules.{name}")
    spec = importlib.util.spec_from_file_location(
        f"legacy_step5_{package}_{name}", ROOT / "skills" / package / "modules" / f"{name}.py"
    )
    standalone = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(standalone)
    for exported in legacy.__all__:
        assert getattr(legacy, exported) is getattr(canonical, exported)
        assert getattr(standalone, exported) is getattr(canonical, exported)


def _bundle():
    program = {
        "contract_version": "test-measurement-program",
        "model_selection": {"candidate_models": [
            {"selected": True, "model_family": "linear impact", "mathematical_object": "price impact"}
        ]},
        "math_tool_selection": {"selected_tool_families": ["linear regression"]},
        "observation_and_estimation": {"estimand": "impact per unit volume", "observation_map": "r_t / volume_t"},
        "market_outcome_projection": {"projection_equation_or_map": "conditional premium for illiquidity"},
    }
    return {
        "report_id": "STEP5_METADATA_TEST",
        "objects": {
            "factor_spec_master": {
                "canonical_spec": {"formula_text": "lag(close, 1)",
                                   "mechanism_conditioned_measurement_program": program},
                "mechanism_math_contract": {"legacy_v1": "retained verbatim"},
                "mechanism_math_contract_v2": {"legacy_v2": "retained verbatim"},
            },
            "factor_run_master": {"factor_id": "IMPACT", "run_status": "success",
                                  "research_window_contract": {"scope": "local_is_only"}},
            "data_prep_master": {},
        },
        "paths": {},
    }


def _case(bundle):
    return build_factor_case_master(bundle, {"backend_summary": []}, [], "partial", "evaluation.json")


def test_union_of_window_policy_legacy_math_and_current_program_survives():
    bundle = _bundle()
    before = deepcopy(bundle)
    case = _case(bundle)
    spec = bundle["objects"]["factor_spec_master"]
    assert bundle == before
    assert case["research_window_contract"] == {"scope": "local_is_only"}
    assert case["oos_revision_policy"]["oos_revision_fitting_allowed"] is False
    for field in METADATA_FIELDS[:2]:
        assert case[field] == spec[field]
    assert case[METADATA_FIELDS[2]] == spec["canonical_spec"][METADATA_FIELDS[2]]
    ref = case["math_discipline_review"]["mechanism_conditioned_measurement_program_ref"]
    assert ref["model_family"] == "linear impact"
    assert ref["observation_map"] == "r_t / volume_t"
    case[METADATA_FIELDS[2]]["model_selection"].clear()
    assert bundle == before


@pytest.mark.parametrize("field", METADATA_FIELDS)
def test_conflicting_authored_copies_are_not_silently_selected(field):
    bundle = _bundle()
    spec = bundle["objects"]["factor_spec_master"]
    spec[field] = {"origin": "spec"}
    spec["canonical_spec"][field] = {"origin": "canonical"}
    with pytest.raises(ValueError, match="copies disagree"):
        _case(bundle)


@pytest.mark.parametrize("value", [False, [], "text", 1])
def test_nonobject_metadata_is_not_replaced_with_empty_object(value):
    bundle = _bundle()
    bundle["objects"]["factor_spec_master"][METADATA_FIELDS[2]] = value
    with pytest.raises(ValueError, match="must be an object"):
        _case(bundle)


def test_legacy_missing_metadata_stays_unknown_and_dpm_window_is_preserved():
    bundle = _bundle()
    bundle["objects"]["factor_spec_master"] = {}
    del bundle["objects"]["factor_run_master"]["research_window_contract"]
    bundle["objects"]["data_prep_master"]["research_window_contract"] = {"window_role": "IS"}
    case = _case(bundle)
    assert case[METADATA_FIELDS[2]] == {}
    assert all(field not in case for field in METADATA_FIELDS[:2])
    ref = case["math_discipline_review"]["mechanism_conditioned_measurement_program_ref"]
    assert ref["model_family"] is None
    assert ref["estimand"] is None
    assert ref["selected_tool_families"] == []
    assert case["research_window_contract"] == {"window_role": "IS"}


def test_cli_handoff_preserves_all_merged_metadata():
    spec = importlib.util.spec_from_file_location(
        "step5_canonical_handoff_test", ROOT / "skills/factor-forge-step5/scripts/run_step5.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = _bundle()
    case = _case(bundle)
    handoff = module.build_handoff_to_step6(
        bundle, {}, case, Path("evaluation.json"), Path("case.json"), []
    )
    for field in (*METADATA_FIELDS, "research_window_contract", "oos_revision_policy", "math_discipline_review"):
        assert handoff[field] == case[field]
