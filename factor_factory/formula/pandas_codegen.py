from __future__ import annotations

import pprint
from typing import Any


CODEGEN_VERSION = 'factorforge_pandas_formula_codegen_v2_class'


def render_python_literal(value: Any) -> str:
    """Render structured contracts as deterministic, importable Python literals."""
    return pprint.pformat(value, sort_dicts=True, width=100)


def generate_pandas_formula_code(*, report_id: str, factor_id: str, formula_ir: dict[str, Any], domain: str = 'price_volume') -> str:
    if domain not in {'price_volume', 'fundamental'}:
        raise ValueError('factor domain must be price_volume or fundamental')
    formula_ir_literal = render_python_literal(formula_ir)
    return f'''from __future__ import annotations

import pandas as pd

from factor_factory.factors import BaseFactor
from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.research_api import validate_factor_output


REPORT_ID = {report_id!r}
FACTOR_ID = {factor_id!r}
FORMULA_IR = {formula_ir_literal}


METADATA = {{
    "report_id": REPORT_ID,
    "factor_id": FACTOR_ID,
    "implementation_source": "formula_ir_pandas_codegen",
    "formula_ir_version": FORMULA_IR.get("formula_ir_version"),
    "formula_hash": FORMULA_IR.get("formula_hash"),
    "resolved_binding_hash": FORMULA_IR.get("resolved_binding_hash"),
    "operator_set": FORMULA_IR.get("operator_set") or [],
    "required_fields": FORMULA_IR.get("required_fields") or [],
    "resolved_fields": FORMULA_IR.get("resolved_fields") or {{}},
    "codegen_version": {CODEGEN_VERSION!r},
}}


class GeneratedFormulaFactor(BaseFactor):
    """Evaluate the reviewed IR; do not reparse or replace its field semantics."""

    name = FACTOR_ID
    domain = {domain!r}
    input_columns = {{"daily_df": ("ts_code", "trade_date")}}

    def compute(self, inputs):
        return evaluate_formula_frame(FORMULA_IR, inputs["daily_df"])


FACTOR = GeneratedFormulaFactor()


def compute_factor(daily_df: pd.DataFrame, minute_df: pd.DataFrame | None = None) -> pd.DataFrame:
    # Backward-compatible long-table boundary, not a second implementation.
    result = FACTOR({{"daily_df": daily_df, "minute_df": minute_df}})
    return validate_factor_output(result).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
'''


def operator_metadata(formula_ir: dict[str, Any]) -> dict[str, Any]:
    return {
        'implementation_source': 'formula_ir_pandas_codegen',
        'formula_ir_version': formula_ir.get('formula_ir_version'),
        'formula_hash': formula_ir.get('formula_hash'),
        'resolved_binding_hash': formula_ir.get('resolved_binding_hash'),
        'operator_set': formula_ir.get('operator_set') or [],
        'required_fields': formula_ir.get('required_fields') or [],
        'resolved_fields': formula_ir.get('resolved_fields') or {},
        'field_aliases': formula_ir.get('field_aliases') or {},
        'codegen_version': CODEGEN_VERSION,
    }
