from __future__ import annotations

import importlib.util
import copy
from pathlib import Path

import pytest

from factor_factory.formula.pandas_codegen import generate_pandas_formula_code
from factor_factory.formula.parity import run_operator_parity
from factor_factory.formula.parser import parse_formula


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_validate_step3b():
    path = REPO_ROOT / "skills/factor-forge-step3/scripts/validate_step3b.py"
    spec = importlib.util.spec_from_file_location("validate_step3b_parity_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pre_close_formula_ir():
    return parse_formula(
        "abs(open / pre_close - 1) * sign(close - open)",
        available_columns=["open", "close", "pre_close"],
        raise_on_error=True,
    )


def test_operator_parity_fixture_adds_schema_valid_resolved_fields(tmp_path):
    formula_ir = _pre_close_formula_ir()
    implementation = tmp_path / "factor_impl.py"
    implementation.write_text(
        generate_pandas_formula_code(
            report_id="PARITY_PRE_CLOSE",
            factor_id="PARITY_PRE_CLOSE",
            formula_ir=formula_ir,
        ),
        encoding="utf-8",
    )

    result = run_operator_parity(formula_ir, implementation)

    assert result["status"] == "PASS"
    assert result["row_count"] == 24
    assert result["non_null_count"] == 24


def test_operator_schema_gate_blocks_missing_resolved_field_before_parity():
    validate_step3b = _load_validate_step3b()

    with pytest.raises(AssertionError, match="BLOCK_MISSING_FIELD_ALIAS"):
        validate_step3b.assert_resolved_fields_in_operator_schema(
            _pre_close_formula_ir(),
            {"available_columns": ["ts_code", "trade_date", "open", "close"]},
        )


def test_operator_schema_gate_does_not_trust_default_fixture_for_pre_close():
    validate_step3b = _load_validate_step3b()

    with pytest.raises(AssertionError, match="BLOCK_MISSING_FIELD_ALIAS"):
        validate_step3b.assert_resolved_fields_in_operator_schema(_pre_close_formula_ir(), {})


def test_hybrid_path_applies_same_pre_close_schema_gate(tmp_path):
    validate_step3b = _load_validate_step3b()
    spec = {
        "implementation_contract": {
            "hybrid_contract_version": validate_step3b.HYBRID_CONTRACT_VERSION,
            "operator_subgraph": {"formula_ir": _pre_close_formula_ir()},
        }
    }

    with pytest.raises(AssertionError, match="BLOCK_MISSING_FIELD_ALIAS"):
        validate_step3b.validate_hybrid_mode(
            spec,
            {},
            {},
            {},
            handoff={},
            code_dir=tmp_path,
            stub=tmp_path / "stub.py",
            real_impl=tmp_path / "impl.py",
            prep={"available_columns": ["ts_code", "trade_date", "open", "close"]},
        )


def test_operator_schema_gate_blocks_mapping_omitted_from_formula_ir():
    validate_step3b = _load_validate_step3b()
    formula_ir = copy.deepcopy(_pre_close_formula_ir())
    formula_ir["resolved_fields"].pop("pre_close")

    with pytest.raises(AssertionError, match="BLOCK_FORMULA_FIELD_MAPPING_INCOMPLETE"):
        validate_step3b.assert_resolved_fields_in_operator_schema(
            formula_ir,
            {"available_columns": ["ts_code", "trade_date", "open", "close", "pre_close"]},
        )


def test_operator_schema_gate_blocks_tree_mapping_mismatch():
    validate_step3b = _load_validate_step3b()
    formula_ir = copy.deepcopy(_pre_close_formula_ir())

    def change_pre_close(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "field" and node.get("name") == "pre_close":
            node["resolved_field"] = "close"
        for child in node.get("args") or []:
            change_pre_close(child)

    change_pre_close(formula_ir["root"])
    with pytest.raises(AssertionError, match="BLOCK_FORMULA_FIELD_MAPPING_MISMATCH"):
        validate_step3b.assert_resolved_fields_in_operator_schema(
            formula_ir,
            {"available_columns": ["ts_code", "trade_date", "open", "close", "pre_close"]},
        )


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        ("missing_mapping", "BLOCK_FORMULA_FIELD_MAPPING_INCOMPLETE"),
        ("tree_mismatch", "BLOCK_FORMULA_FIELD_MAPPING_MISMATCH"),
    ],
)
def test_hybrid_path_blocks_formula_mapping_contract_violations(tmp_path, mutation, blocker):
    validate_step3b = _load_validate_step3b()
    formula_ir = copy.deepcopy(_pre_close_formula_ir())
    if mutation == "missing_mapping":
        formula_ir["resolved_fields"].pop("pre_close")
    else:
        pending = [formula_ir["root"]]
        while pending:
            node = pending.pop()
            if node.get("type") == "field" and node.get("name") == "pre_close":
                node["resolved_field"] = "close"
            pending.extend(node.get("args") or [])
    spec = {
        "implementation_contract": {
            "hybrid_contract_version": validate_step3b.HYBRID_CONTRACT_VERSION,
            "operator_subgraph": {"formula_ir": formula_ir},
        }
    }

    with pytest.raises(AssertionError, match=blocker):
        validate_step3b.validate_hybrid_mode(
            spec,
            {},
            {},
            {},
            handoff={},
            code_dir=tmp_path,
            stub=tmp_path / "stub.py",
            real_impl=tmp_path / "impl.py",
            prep={"available_columns": ["ts_code", "trade_date", "open", "close", "pre_close"]},
        )
