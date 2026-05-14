from __future__ import annotations

import json
from typing import Any


CODEGEN_VERSION = 'factorforge_pandas_formula_codegen_v1'


def generate_pandas_formula_code(*, report_id: str, factor_id: str, formula_ir: dict[str, Any]) -> str:
    formula_ir_literal = json.dumps(formula_ir, ensure_ascii=False, sort_keys=True, indent=2)
    return f'''from __future__ import annotations

import pandas as pd

from factor_factory.formula.evaluator import evaluate_formula_frame


REPORT_ID = {report_id!r}
FACTOR_ID = {factor_id!r}
FORMULA_IR = {formula_ir_literal}


METADATA = {{
    "report_id": REPORT_ID,
    "factor_id": FACTOR_ID,
    "implementation_source": "formula_ir_pandas_codegen",
    "formula_ir_version": FORMULA_IR.get("formula_ir_version"),
    "formula_hash": FORMULA_IR.get("formula_hash"),
    "operator_set": FORMULA_IR.get("operator_set") or [],
    "required_fields": FORMULA_IR.get("required_fields") or [],
    "resolved_fields": FORMULA_IR.get("resolved_fields") or {{}},
    "codegen_version": {CODEGEN_VERSION!r},
}}


def compute_factor(daily_df: pd.DataFrame, minute_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        return pd.DataFrame(columns=["ts_code", "trade_date", "factor_value"])
    return evaluate_formula_frame(FORMULA_IR, daily_df)
'''


def operator_metadata(formula_ir: dict[str, Any]) -> dict[str, Any]:
    return {
        'implementation_source': 'formula_ir_pandas_codegen',
        'formula_ir_version': formula_ir.get('formula_ir_version'),
        'formula_hash': formula_ir.get('formula_hash'),
        'operator_set': formula_ir.get('operator_set') or [],
        'required_fields': formula_ir.get('required_fields') or [],
        'resolved_fields': formula_ir.get('resolved_fields') or {},
        'field_aliases': formula_ir.get('field_aliases') or {},
        'codegen_version': CODEGEN_VERSION,
    }
