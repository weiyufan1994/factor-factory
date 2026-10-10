import numpy as np
import pandas as pd

from factor_factory.research_search.formula_bridge import compile_candidate, compute_candidate
from factor_factory.research_search.generator import ExpressionCandidate
from factor_factory.research_search.generator import generate_population
from factor_factory.research_search.typed_ast import ASTNode
from tests.research_search_d05_helpers import approved_scope


def _candidate(scope, root, name="manual"):
    return ExpressionCandidate(name, root, scope.response_family, scope.scope_hash, 0, (), "manual_typed_ast", ("parameter",))


def _frame():
    dates = pd.date_range("2025-01-02", periods=4, freq="D")
    rows = []
    for code, xs, ys in [("B", [1.0, 2.0, np.nan, 4.0], [2.0, 0.0, 2.0, 2.0]),
                         ("A", [0.0, 3.0, 6.0, 9.0], [0.0, 2.0, 0.0, 2.0])]:
        rows.extend({"ts_code": code, "trade_date": day, "x": x, "y": y}
                    for day, x, y in zip(dates, xs, ys))
    return pd.DataFrame(rows).sample(frac=1, random_state=4).reset_index(drop=True)


def test_ast_compiles_through_existing_formula_parser_and_factor_contract():
    scope = approved_scope()
    root = ASTNode.operator("plus", ASTNode.field("x"),
                            ASTNode.operator("multiply", ASTNode.field("y"), ASTNode.constant(0.5)))
    compiled = compile_candidate(_candidate(scope, root), scope,
                                 available_columns=["ts_code", "trade_date", "x", "y"])
    result = compute_candidate(compiled, {"daily_df": _frame()})
    expected = _frame().assign(factor_value=lambda frame: frame.x + 0.5 * frame.y)
    expected = expected[["ts_code", "trade_date", "factor_value"]]
    expected = expected.rename(columns={"trade_date": "datetime", "ts_code": "instrument"})
    expected = expected.set_index(["datetime", "instrument"]).sort_index()
    pd.testing.assert_frame_equal(result, expected, check_freq=False)
    assert result.factor_value.dtype == np.dtype("float64")
    assert result.index.is_unique and result.index.is_monotonic_increasing
    assert result.factor_value.isna().sum() == 1
    assert (result.factor_value == 0.0).any()
    assert compiled.formula_ir["parse_status"] == "success"


def test_trailing_operators_have_warmup_and_no_future_dependence():
    scope = approved_scope()
    root = ASTNode.operator("plus",
        ASTNode.operator("delay", ASTNode.field("x"), ASTNode.window(1)),
        ASTNode.operator("mean", ASTNode.field("y"), ASTNode.window(2)))
    compiled = compile_candidate(_candidate(scope, root, "causal"), scope,
                                 available_columns=["ts_code", "trade_date", "x", "y"])
    base = _frame().sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    changed = base.copy()
    last_date = changed.trade_date.max()
    changed.loc[changed.trade_date.eq(last_date), ["x", "y"]] = 1_000_000.0
    left = compute_candidate(compiled, {"daily_df": base})
    right = compute_candidate(compiled, {"daily_df": changed})
    earlier = left.index.get_level_values("datetime") < last_date
    pd.testing.assert_series_equal(left.loc[earlier, "factor_value"], right.loc[earlier, "factor_value"])
    assert left.groupby(level="instrument").head(1).factor_value.isna().all()


def test_all_accepted_generated_trees_compile_and_compute_across_seeds():
    scope = approved_scope(max_depth=4)
    frame = _frame()
    for seed in range(5):
        generated = generate_population(scope, seed=seed, population_size=10, max_attempts=80)
        assert len(generated.candidates) == 10
        for candidate in generated.candidates:
            compiled = compile_candidate(candidate, scope, available_columns=list(frame.columns))
            values = compute_candidate(compiled, {"daily_df": frame})
            assert len(values) == len(frame)
