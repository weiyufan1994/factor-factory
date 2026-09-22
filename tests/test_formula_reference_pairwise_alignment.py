import pandas as pd

from factor_factory.formula.evaluator import evaluate_formula_frame


def _alpha015_like_formula_ir():
    return {
        "parse_status": "success",
        "formula_ir_version": "factorforge_formula_ir_v1",
        "required_fields": ["high", "volume"],
        "root": {
            "type": "operator",
            "operator": "sum",
            "args": [
                {
                    "type": "operator",
                    "operator": "rank",
                    "args": [
                        {
                            "type": "operator",
                            "operator": "correlation",
                            "args": [
                                {
                                    "type": "operator",
                                    "operator": "rank",
                                    "args": [{"type": "field", "name": "high", "resolved_field": "high"}],
                                },
                                {
                                    "type": "operator",
                                    "operator": "rank",
                                    "args": [{"type": "field", "name": "volume", "resolved_field": "volume"}],
                                },
                                {"type": "constant", "value": 3},
                            ],
                        }
                    ],
                },
                {"type": "constant", "value": 3},
            ],
        },
    }


def test_reference_pairwise_operator_keeps_row_aligned_index_for_nested_ts_sum():
    frame = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"] * 8,
            "trade_date": [f"202001{day:02d}" for day in range(1, 9)],
            "high": [10.0, 10.2, 10.1, 10.4, 10.3, 10.5, 10.7, 10.6],
            "volume": [100.0, 120.0, 110.0, 150.0, 140.0, 160.0, 180.0, 170.0],
        }
    )

    result = evaluate_formula_frame(_alpha015_like_formula_ir(), frame, engine="reference")

    assert len(result) == len(frame)
    assert result[["ts_code", "trade_date"]].equals(frame[["ts_code", "trade_date"]])
    assert "factor_value" in result.columns
