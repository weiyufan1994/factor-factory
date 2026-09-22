from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.extension_registry import EXTENSION_OPERATORS
from factor_factory.formula.pandas_codegen import generate_pandas_formula_code
from factor_factory.formula.parity import make_operator_fixture, run_operator_parity
from factor_factory.formula.parser import parse_formula
from factor_factory.formula.qlib_codegen import to_qlib_expression
from factor_factory.formula.registry import SUPPORTED_OPERATORS
from factor_factory.formula.semantics import max_formula_ir_lookback, requires_cross_sectional_sample


def _time(values):
    return pd.DataFrame({
        "ts_code": ["A"] * len(values),
        "trade_date": pd.bdate_range("2024-01-02", periods=len(values)).strftime("%Y%m%d"),
        "x": values,
    })


def _cross(values, groups=None):
    frame = pd.DataFrame({"ts_code": [f"S{i:03d}" for i in range(len(values))], "trade_date": "20240102", "x": values})
    if groups is not None:
        frame["g"] = groups
    return frame


def _run(expression, frame, engine="optimized"):
    ir = parse_formula(expression, available_columns=list(frame.columns), raise_on_error=True)
    result = evaluate_formula_frame(ir, frame, engine=engine)
    keys = pd.MultiIndex.from_frame(frame[["ts_code", "trade_date"]])
    return result.set_index(["ts_code", "trade_date"]).reindex(keys)["factor_value"].to_numpy()


@pytest.mark.parametrize("engine", ["reference", "optimized"])
@pytest.mark.parametrize(("expression", "expected"), [
    ("minimum(x,2)", [-3, 2, np.nan, 2]),
    ("maximum(2,x)", [2, 4, np.nan, np.inf]),
    ("sqrt_nonnegative(x)", [np.nan, 2, np.nan, np.inf]),
    ("clip(x,-2,3)", [-2, 3, np.nan, 3]),
    ("lt(x,2)", [1, 0, 0, 0]),
    ("where(lt(x,2),-1,x)", [-1, 4, np.nan, np.inf]),
    ("where(x,10,20)", [10, 10, 20, 10]),
])
def test_elementwise_hand_calculated(expression, expected, engine):
    frame = _time([-3, 4, np.nan, np.inf])
    before = frame.copy(deep=True)
    np.testing.assert_allclose(_run(expression, frame, engine), expected, equal_nan=True)
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize(("expression", "values", "expected"), [
    ("cs_demean(x)", [1, 3, np.nan, np.inf], [-1, 1, np.nan, np.nan]),
    ("cs_fillmean(x)", [1, 3, np.nan, np.inf], [1, 3, 2, np.inf]),
    ("cs_winsor_quantile(x,0.25,0.75)", [0, 2, 4, 100, np.nan, np.inf], [1.5, 2, 4, 28, np.nan, 28]),
    ("cs_winsor_mad(x,1)", [0, 2, 4, 100, np.nan, np.inf], [1, 2, 4, 5, np.nan, 5]),
    ("cs_winsor_std(x,1)", [0, 2, 4, 6], [3-np.sqrt(5), 2, 4, 3+np.sqrt(5)]),
    ("cs_winsor_mad(x,3)", [2, 2, 2, 100, np.nan], [2, 2, 2, 100, np.nan]),
    ("cs_winsor_std(x,3)", [2, np.nan, np.inf], [2, np.nan, np.inf]),
    ("cs_fillmean(x)", [np.nan, np.inf], [np.nan, np.inf]),
])
def test_cross_sectional_statistics_and_degenerate_cases(expression, values, expected):
    np.testing.assert_allclose(_run(expression, _cross(values)), expected, equal_nan=True)


@pytest.mark.parametrize(("expression", "expected"), [
    ("cs_rank_group(x,g)", [1/3, 2/3, 1, np.nan, np.nan, 1, 1]),
    ("ind_demean(x,g)", [-1, 1, np.nan, np.nan, np.nan, np.nan, np.nan]),
    ("ind_fillmean(x,g)", [1, 3, 10, 10, 99, np.inf, 5]),
])
def test_group_isolation_missing_group_and_singleton(expression, expected):
    frame = _cross([1, 3, 10, np.nan, 99, np.inf, 5], [1, 1, 2, 2, np.nan, 1, 3])
    np.testing.assert_allclose(_run(expression, frame), expected, equal_nan=True)


@pytest.mark.parametrize("expression", [
    "cs_demean(x)", "cs_fillmean(x)", "cs_winsor_quantile(x,0.1,0.9)",
    "cs_winsor_mad(x,2)", "cs_winsor_std(x,2)", "cs_rank_group(x,g)",
    "ind_demean(x,g)", "ind_fillmean(x,g)",
])
def test_cross_section_never_uses_other_dates(expression):
    first = _cross([1, 3, 10, np.nan], [1, 1, 2, 2])
    second = first.assign(trade_date="20240103", x=[100, -100, 50, 80])
    together = pd.concat([first, second], ignore_index=True)
    np.testing.assert_allclose(_run(expression, together)[:len(first)], _run(expression, first), equal_nan=True)


@pytest.mark.parametrize(("expression", "values", "expected"), [
    ("ts_decay_linear(x,3)", [1, 2, 3, 4], [np.nan, np.nan, 14/6, 20/6]),
    ("ts_decay_linear(x,3)", [1, np.nan, 3, 4], [np.nan, np.nan, 2.5, 18/5]),
    ("ts_decay_linear(x,3)", [1, 2, np.nan], [np.nan, np.nan, 5/3]),
    ("ts_decay_linear(x,3)", [1, np.nan, np.inf], [np.nan, np.nan, np.nan]),
    ("ts_product(x,3)", [2, 0, 4, np.nan, 3, 5, 6], [np.nan, np.nan, 0, np.nan, np.nan, np.nan, 90]),
    ("ts_product(x,3)", [-2, 3, 4], [np.nan, np.nan, -24]),
    ("ts_product(x,2)", [1e308, 1e308], [np.nan, np.nan]),
    ("ts_product(x,2)", [0, np.inf], [np.nan, np.nan]),
    ("ts_ffill(x,2)", [np.nan, 2, np.nan, np.inf, np.nan, 5, np.nan], [np.nan, 2, 2, np.inf, np.nan, 5, 5]),
    ("ts_ffill(x,0)", [1, np.nan, 2], [1, np.nan, 2]),
])
def test_temporal_hand_calculated(expression, values, expected):
    np.testing.assert_allclose(_run(expression, _time(values)), expected, equal_nan=True)


@pytest.mark.parametrize("expression", ["ts_decay_linear(x,2)", "ts_product(x,2)", "ts_ffill(x,1)"])
def test_temporal_security_boundaries_sorting_and_future_independence(expression):
    a = _time([1, np.nan, 3, 4])
    b = _time([10, 20, np.nan, 40]).assign(ts_code="B")
    combined = pd.concat([a, b], ignore_index=True).sample(frac=1, random_state=7)
    expected = pd.Series(np.concatenate([_run(expression, a), _run(expression, b)]), index=pd.MultiIndex.from_frame(pd.concat([a, b])[["ts_code", "trade_date"]]))
    actual = _run(expression, combined)
    np.testing.assert_allclose(actual, expected.reindex(pd.MultiIndex.from_frame(combined[["ts_code", "trade_date"]])).to_numpy(), equal_nan=True)
    future = _time([1e9]).assign(trade_date="20240108")
    extended = pd.concat([a, future], ignore_index=True)
    np.testing.assert_allclose(_run(expression, extended)[:len(a)], _run(expression, a), equal_nan=True)


@pytest.mark.parametrize("expression", [
    "clip(x,2,1)", "clip(x,x,1)", "cs_winsor_quantile(x,-0.1,0.9)",
    "cs_winsor_quantile(x,0.9,0.1)", "cs_winsor_quantile(x,0,2)",
    "cs_winsor_mad(x,0)", "cs_winsor_std(x,-1)", "cs_winsor_std(x,x)",
    "ts_ffill(x,-1)", "ts_ffill(x,1.5)", "ts_product(x,0)", "ts_decay_linear(x,x)",
])
def test_bad_parameters_block_before_execution(expression):
    ir = parse_formula(expression, available_columns=["x"])
    assert ir["parse_status"] == "failed"


FORMULAS = [
    "minimum(close,open)", "maximum(close,open)", "sqrt_nonnegative(close)",
    "clip(close,9,16)", "lt(close,open)", "where(lt(close,open),close,open)",
    "cs_demean(close)", "cs_winsor_quantile(close,0.1,0.9)",
    "cs_winsor_mad(close,2)", "cs_winsor_std(close,2)", "cs_fillmean(close)",
    "cs_rank_group(close,sign(volume))", "ind_demean(close,sign(volume))",
    "ind_fillmean(close,sign(volume))", "ts_decay_linear(close,3)",
    "ts_product(close,3)", "ts_ffill(close,2)",
]


@pytest.mark.parametrize("formula", FORMULAS)
def test_registered_codegen_parity_reference_and_explicit_qlib_status(formula, tmp_path):
    ir = parse_formula(formula, available_columns=["close", "open", "volume"], raise_on_error=True)
    assert ir["operator_semantic_hash"]
    assert any(name in EXTENSION_OPERATORS for name in ir["operator_semantics"])
    fixture = make_operator_fixture(ir)
    pd.testing.assert_frame_equal(evaluate_formula_frame(ir, fixture, engine="reference"), evaluate_formula_frame(ir, fixture, engine="optimized"))
    implementation = tmp_path / "factor_impl.py"
    implementation.write_text(generate_pandas_formula_code(report_id="EXTENSION_CHECK", factor_id="EXTENSION_CHECK", formula_ir=ir))
    assert run_operator_parity(ir, implementation)["status"] == "PASS"
    qlib = to_qlib_expression(ir)
    assert qlib["status"] == "unsupported"
    assert qlib["fallback_allowed"] is False
    assert set(qlib["unsupported_operators"]) <= set(EXTENSION_OPERATORS)


def test_metadata_supports_step3_sampling_and_existing_semantics_are_unchanged():
    for expression, expected in [("ts_product(close,20)", 20), ("ts_decay_linear(close,15)", 15), ("ts_ffill(close,4)", 4)]:
        assert max_formula_ir_lookback(parse_formula(expression)) == expected
    assert requires_cross_sectional_sample(parse_formula("ind_demean(close,volume)"))
    assert not requires_cross_sectional_sample(parse_formula("minimum(close,open)"))
    assert all(SUPPORTED_OPERATORS[name]["supports_pandas"] for name in EXTENSION_OPERATORS)
    frame = _time([1, 2, 3, 4])
    np.testing.assert_allclose(_run("min(x,4)", frame), [np.nan, np.nan, np.nan, 1], equal_nan=True)
    assert _run("stddev(x,4)", frame)[-1] == pytest.approx(np.sqrt(5/3))
    assert _run("ts_rank(x,4)", frame)[-1] == 1
    assert _run("argmax(x,4)", frame)[-1] == 4
    assert _run("x**2", _time([-2]))[0] == -4


def test_extensions_reuse_repeated_subexpressions():
    frame = _time([1, 2, 3])
    ir = parse_formula("minimum(x,2)+minimum(x,2)", available_columns=list(frame.columns), raise_on_error=True)
    result, profile = evaluate_formula_frame(ir, frame, return_profile=True)
    np.testing.assert_allclose(result.factor_value, [2, 4, 4])
    assert profile["cache_hits"] > 0


def test_step3_hybrid_generator_combines_new_operator_and_custom_code():
    path = Path(__file__).resolve().parents[1] / "skills/factor-forge-step3/scripts/run_step3b.py"
    spec = importlib.util.spec_from_file_location("extension_hybrid_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    frame = _time([1, 2, 3, 4])
    ir = parse_formula("ts_decay_linear(x,3)", available_columns=list(frame.columns), raise_on_error=True)
    source = module.generate_hybrid_code(
        report_id="EXTENSION_HYBRID_TEST", factor_id="EXTENSION_HYBRID_TEST",
        formula_ir=ir,
        custom_block={"source_code": (
            "def apply_custom_block(operator_df, daily_df):\n"
            "    out = operator_df.copy()\n"
            "    out['factor_value'] = 2 * out['operator_value']\n"
            "    return out[['ts_code', 'trade_date', 'factor_value']]\n"
        )},
        boundary={}, contract={"hybrid_contract_version": "factorforge_hybrid_contract_v1"},
    )
    namespace = {}
    exec(compile(source, "<extension_hybrid_test>", "exec"), namespace)
    result = namespace["compute_factor"](daily_df=frame)
    np.testing.assert_allclose(result.factor_value, [np.nan, np.nan, 14/3, 20/3], equal_nan=True)


@pytest.fixture(scope="module")
def step3_contract_modules():
    directory = Path(__file__).resolve().parents[1] / "skills/factor-forge-step3/scripts"
    modules = []
    for filename in ("run_step3", "validate_step3"):
        spec = importlib.util.spec_from_file_location(f"extension_contract_{filename}", directory / f"{filename}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def _local_operator_contract(specs):
    return {"derived_field_contract": {
        "version": "factorforge_derived_field_contract_v1",
        "report_local_only": True, "clean_data_mutation": False,
        "validation_result": "PASS", "derived_fields": specs,
    }}


@pytest.mark.parametrize("formula", FORMULAS + ["cs_demean(returns)", "delay(returns,2)", "ts_ffill(returns,0)"])
def test_step3_generated_contract_is_accepted_by_actual_validator(formula, step3_contract_modules):
    producer, validator = step3_contract_modules
    ir = parse_formula(formula, available_columns=["close", "open", "volume", "returns"], raise_on_error=True)
    local_inputs = _local_operator_contract(producer.formula_operator_contract_specs(ir))
    validator.validate_derived_field_contract(
        local_inputs, expected_operators=validator.expected_formula_operator_contracts(ir),
    )


@pytest.mark.parametrize("operator", ["ts_decay_linear", "ts_product", "ts_ffill"])
@pytest.mark.parametrize("incorrect_window", [4, None])
def test_step3_rejects_wrong_or_missing_extension_window(operator, incorrect_window, step3_contract_modules):
    producer, validator = step3_contract_modules
    ir = parse_formula(f"{operator}(close,5)", raise_on_error=True)
    specs = producer.formula_operator_contract_specs(ir)
    contract = next(spec for spec in specs.values() if spec["operator"] == operator)
    if incorrect_window is None:
        contract.pop("lookback_window")
    else:
        contract["lookback_window"] = incorrect_window
    with pytest.raises(AssertionError, match="BLOCK_STANDARD_FORMULA_OPERATOR_CONTRACT_MISMATCH"):
        validator.validate_derived_field_contract(
            _local_operator_contract(specs), expected_operators=validator.expected_formula_operator_contracts(ir),
        )


@pytest.mark.parametrize(("formula", "unit"), [
    ("lt(close,open)", "boolean_indicator"),
    ("where(lt(close,open),ts_decay_linear(close,5),clip(open,0,100))", "price"),
    ("cs_rank_group(close,volume)", "rank_score"),
    ("sqrt_nonnegative(close)", "source_unit_sqrt"),
    ("ts_product(close,5)", "source_unit_product"),
    ("cs_winsor_quantile(close,0.1,0.9)", "price"),
    ("ind_demean(close,volume)", "price"),
])
def test_step3_checks_output_unit_of_extension_compositions(formula, unit, step3_contract_modules):
    producer, validator = step3_contract_modules
    ir = parse_formula(formula, raise_on_error=True)
    specs = producer.formula_operator_contract_specs(ir)
    root_spec = list(specs.values())[-1]
    assert root_spec["output_unit"] == unit
    root_spec["output_unit"] = "incorrect_unit"
    with pytest.raises(AssertionError, match="BLOCK_STANDARD_FORMULA_OPERATOR_CONTRACT_MISMATCH"):
        validator.validate_derived_field_contract(
            _local_operator_contract(specs), expected_operators=validator.expected_formula_operator_contracts(ir),
        )
