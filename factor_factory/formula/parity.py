from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .evaluator import evaluate_formula_frame


def make_operator_fixture() -> pd.DataFrame:
    rows = []
    for day_idx, trade_date in enumerate(['20260101', '20260102', '20260103', '20260104', '20260105', '20260106']):
        for code_idx, code in enumerate(['000001.SZ', '000002.SZ', '000003.SZ', '000004.SZ']):
            base = 10.0 + code_idx * 2.0 + day_idx * 0.3
            rows.append({
                'ts_code': code,
                'trade_date': trade_date,
                'open': base,
                'high': base + 0.8 + code_idx * 0.05,
                'low': base - 0.6,
                'close': base + ((-1) ** code_idx) * 0.25 + day_idx * 0.02,
                'volume': 1000.0 + code_idx * 100.0 + day_idx * 20.0,
                'vol': 1000.0 + code_idx * 100.0 + day_idx * 20.0,
                'amount': (base + 0.1) * (1000.0 + code_idx * 100.0 + day_idx * 20.0),
                'pct_chg': 0.01 * (code_idx - 1.5) + day_idx * 0.001,
                'turnover_rate': 0.4 + code_idx * 0.12 + day_idx * 0.03,
                'turnover_rate_f': 0.5 + code_idx * 0.10 + day_idx * 0.025,
                'volume_ratio': 0.8 + code_idx * 0.08 + day_idx * 0.02,
            })
    return pd.DataFrame(rows)


def _load_compute(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot import generated operator artifact: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    compute = getattr(module, 'compute_factor', None)
    if compute is None or not callable(compute):
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: compute_factor missing')
    return compute


def compare_outputs(reference: pd.DataFrame, generated: pd.DataFrame, *, tolerance: float = 1e-9) -> dict[str, Any]:
    keys = ['ts_code', 'trade_date']
    required = set(keys + ['factor_value'])
    if not required.issubset(reference.columns) or not required.issubset(generated.columns):
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: missing required output columns')
    merged = reference[keys + ['factor_value']].merge(
        generated[keys + ['factor_value']],
        on=keys,
        how='outer',
        suffixes=('_reference', '_generated'),
        indicator=True,
    )
    if not (merged['_merge'] == 'both').all():
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: output key mismatch')
    ref = pd.to_numeric(merged['factor_value_reference'], errors='coerce')
    gen = pd.to_numeric(merged['factor_value_generated'], errors='coerce')
    ref_mask = ref.notna()
    gen_mask = gen.notna()
    if not (ref_mask == gen_mask).all():
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: non-null mask mismatch')
    diffs = (ref[ref_mask] - gen[gen_mask]).abs()
    max_abs_diff = float(diffs.max()) if len(diffs) else 0.0
    if not np.isfinite(max_abs_diff) or max_abs_diff > tolerance:
        raise AssertionError(f'BLOCK_OPERATOR_PARITY_FAILED: max_abs_diff={max_abs_diff} tolerance={tolerance}')
    return {
        'status': 'PASS',
        'row_count': int(len(merged)),
        'non_null_count': int(ref_mask.sum()),
        'max_abs_diff': max_abs_diff,
        'tolerance': tolerance,
    }


def run_operator_parity(formula_ir: dict[str, Any], implementation_path: Path, *, tolerance: float = 1e-9) -> dict[str, Any]:
    fixture = make_operator_fixture()
    reference = evaluate_formula_frame(formula_ir, fixture)
    compute = _load_compute(implementation_path)
    generated = compute(daily_df=fixture.copy(), minute_df=None)
    return compare_outputs(reference, generated, tolerance=tolerance)
