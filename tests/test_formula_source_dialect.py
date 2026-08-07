from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_factory.formula.evaluator import evaluate_formula_frame, evaluate_formula_ir
from factor_factory.formula.polars_evaluator import polars_dependency_available
from factor_factory.formula.parser import parse_formula, resolve_formula_fields_for_schema
from factor_factory.formula.qlib_codegen import to_qlib_expression
from factor_factory.formula.semantics import (
    max_formula_ir_lookback,
    requires_cross_sectional_sample,
)
from factor_factory.formula.source_dialects import (
    BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
    SourceFormulaDialectError,
    resolve_source_formula,
    valid_source_formula_contract,
)


SOURCE_FORMULA = (
    "-1 * (NORMALIZE(S_LOG_LP(TS_KURTOSIS(CLOSE,5))"
    "+TS_MAX_SKEW(VOLUME,5,3)-TS_MIN_SKEW(VOLUME,20,3)"
    "+TS_MAX_SUM(CHANGE_PCT,20,5),STANDARDIZE=1))"
)


def _choices(**overrides: str) -> dict[str, str]:
    choices = {
        "kurtosis_convention": "excess_unbiased",
        "skew_convention": "inner_window_extrema",
        "max_sum_convention": "contiguous_subwindow",
        "zscore_ddof": "0",
    }
    choices.update(overrides)
    return choices


def _source_ir(**overrides: str) -> tuple[dict, dict]:
    contract = resolve_source_formula(SOURCE_FORMULA, _choices(**overrides))
    formula_ir = parse_formula(
        contract["canonical_formula"],
        available_columns=["close", "volume", "pct_chg"],
        source_dialect_contract=contract,
        raise_on_error=True,
    )
    return contract, formula_ir


def _frame() -> pd.DataFrame:
    rows = []
    for stock_index, ts_code in enumerate(("000001.SZ", "000002.SZ", "600000.SH")):
        for day in range(1, 27):
            rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": f"2026-01-{day:02d}",
                    "close": 10.0 + stock_index * 0.7 + day * 0.03 + np.sin(day + stock_index),
                    "volume": 1000.0 + stock_index * 90.0 + day * day + (day % 4) * 17.0,
                    "pct_chg": (stock_index + 1) * 0.2 + np.cos(day) * 1.5,
                }
            )
    return pd.DataFrame(rows).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def test_source_formula_requires_explicit_semantic_resolution() -> None:
    with pytest.raises(SourceFormulaDialectError) as exc:
        resolve_source_formula(SOURCE_FORMULA, None)

    assert exc.value.token == BLOCK_SOURCE_SEMANTICS_UNRESOLVED


def test_source_formula_translation_freezes_semantics_and_true_lookback() -> None:
    contract, formula_ir = _source_ir()

    assert contract["unit_translation"] == {"CHANGE_PCT": "returns=pct_chg/100"}
    assert {
        "cs_zscore",
        "signed_log1p",
        "rolling_excess_kurtosis",
        "rolling_max_inner_skew",
        "rolling_min_inner_skew",
        "rolling_max_subwindow_sum",
    } <= set(formula_ir["operator_set"])
    assert formula_ir["resolved_fields"] == {
        "close": "close",
        "returns": "pct_chg",
        "volume": "volume",
    }
    assert max_formula_ir_lookback(formula_ir) == 20
    assert requires_cross_sectional_sample(formula_ir) is True
    assert formula_ir["operator_semantic_hash"]
    assert valid_source_formula_contract(contract) is True


def test_source_formula_contract_hash_and_semantics_are_not_forgeable() -> None:
    contract, _formula_ir = _source_ir()
    tampered = dict(contract)
    tampered["canonical_formula"] = "close"

    assert valid_source_formula_contract(tampered) is False


def test_semantic_choices_change_canonical_identity_instead_of_silently_aliasing() -> None:
    contiguous, contiguous_ir = _source_ir()
    topk, topk_ir = _source_ir(
        kurtosis_convention="pearson_unbiased",
        skew_convention="order_statistic_subset",
        max_sum_convention="topk_values",
        zscore_ddof="1",
    )

    assert contiguous["contract_sha256"] != topk["contract_sha256"]
    assert contiguous_ir["formula_hash"] != topk_ir["formula_hash"]
    assert "rolling_topk_sum" in topk_ir["operator_set"]
    assert "rolling_topk_skew" in topk_ir["operator_set"]
    assert "rolling_bottomk_skew" in topk_ir["operator_set"]
    assert "rolling_pearson_kurtosis" in topk_ir["operator_set"]


def test_source_formula_is_strictly_trailing_and_future_mutation_cannot_change_past() -> None:
    _contract, formula_ir = _source_ir()
    frame = _frame()
    baseline = evaluate_formula_ir(formula_ir, frame, engine="reference")

    mutated = frame.copy()
    future = mutated["trade_date"] == "2026-01-26"
    mutated.loc[future, ["close", "volume", "pct_chg"]] = [999.0, 9_999_999.0, 80.0]
    changed = evaluate_formula_ir(formula_ir, mutated, engine="reference")

    past = frame["trade_date"] < "2026-01-26"
    np.testing.assert_allclose(
        baseline[past].to_numpy(),
        changed[past].to_numpy(),
        rtol=1e-6,
        atol=1e-10,
        equal_nan=True,
    )
    assert baseline[future].notna().all()
    assert not np.allclose(
        baseline[future].to_numpy(),
        changed[future].to_numpy(),
        equal_nan=True,
    )


def test_returns_alias_converts_percentage_points_to_decimal_returns() -> None:
    formula_ir = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["2026-01-01", "2026-01-02"],
            "pct_chg": [1.0, -2.5],
        }
    )

    result = evaluate_formula_ir(formula_ir, frame, engine="reference")

    np.testing.assert_allclose(result.to_numpy(), np.array([0.01, -0.025]))


def test_qlib_codegen_preserves_decimal_return_unit_for_pct_chg_alias() -> None:
    formula_ir = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )

    qlib = to_qlib_expression(formula_ir)

    assert qlib["status"] == "supported"
    assert qlib["expression"] == "($pct_chg / 100.0)"


def test_schema_rebind_preserves_formula_identity_and_rehashes_execution_binding() -> None:
    original = parse_formula(
        "returns",
        available_columns=["returns"],
        raise_on_error=True,
    )
    rebound = resolve_formula_fields_for_schema(original, ["pct_chg"])
    directly_bound = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )

    assert rebound["formula_hash"] == original["formula_hash"]
    assert rebound["formula_hash"] == directly_bound["formula_hash"]
    assert rebound["resolved_binding_hash"] != original["resolved_binding_hash"]
    assert rebound["resolved_binding_hash"] == directly_bound["resolved_binding_hash"]
    assert rebound["root"] == directly_bound["root"]


@pytest.mark.skipif(
    not polars_dependency_available(),
    reason="Polars dependency is not installed",
)
def test_polars_preserves_decimal_return_unit_for_pct_chg_alias() -> None:
    formula_ir = parse_formula(
        "returns",
        available_columns=["pct_chg"],
        raise_on_error=True,
    )
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["2026-01-01", "2026-01-02"],
            "pct_chg": [1.0, -2.5],
        }
    )

    reference = evaluate_formula_frame(formula_ir, frame, engine="reference")
    optimized = evaluate_formula_frame(formula_ir, frame, engine="optimized")
    polars = evaluate_formula_frame(formula_ir, frame, engine="polars_experimental")

    expected = np.array([0.01, -0.025])
    np.testing.assert_allclose(reference["factor_value"].to_numpy(), expected)
    np.testing.assert_allclose(optimized["factor_value"].to_numpy(), expected)
    np.testing.assert_allclose(polars["factor_value"].to_numpy(), expected)
