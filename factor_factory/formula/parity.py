from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from factor_factory.implementation_runtime import implementation_callable
from factor_factory.research_api import validate_factor_output

from .evaluator import evaluate_formula_frame
from .semantics import max_formula_ir_lookback


def make_operator_fixture(formula_ir: dict[str, Any] | None = None) -> pd.DataFrame:
    rows = []
    lookback = max_formula_ir_lookback(formula_ir)
    periods = max(6, lookback + 2) if formula_ir else 6
    trade_dates = [value.strftime('%Y%m%d') for value in pd.bdate_range('2026-01-01', periods=periods)]
    for day_idx, trade_date in enumerate(trade_dates):
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
                'buy_sm_amount': 80.0 + code_idx * 5.0 + day_idx * 3.0,
                'sell_sm_amount': 76.0 + code_idx * 4.0 + day_idx * 2.0,
                'buy_md_amount': 120.0 + code_idx * 8.0 + day_idx * 4.0,
                'sell_md_amount': 118.0 + code_idx * 6.0 + day_idx * 3.0,
                'buy_lg_amount': 150.0 + code_idx * 12.0 + day_idx * 5.0,
                'sell_lg_amount': 143.0 + code_idx * 10.0 + day_idx * 4.0,
                'buy_elg_amount': 60.0 + code_idx * 9.0 + day_idx * 3.0,
                'sell_elg_amount': 58.0 + code_idx * 7.0 + day_idx * 2.0,
                'net_mf_amount': (
                    (80.0 + code_idx * 5.0 + day_idx * 3.0)
                    + (120.0 + code_idx * 8.0 + day_idx * 4.0)
                    + (150.0 + code_idx * 12.0 + day_idx * 5.0)
                    + (60.0 + code_idx * 9.0 + day_idx * 3.0)
                    - (76.0 + code_idx * 4.0 + day_idx * 2.0)
                    - (118.0 + code_idx * 6.0 + day_idx * 3.0)
                    - (143.0 + code_idx * 10.0 + day_idx * 4.0)
                    - (58.0 + code_idx * 7.0 + day_idx * 2.0)
                ),
            })
    fixture = pd.DataFrame(rows)
    if formula_ir:
        fixture = _with_standard_formula_fixture_fields(formula_ir, fixture)
        fixture = _with_resolved_formula_fixture_fields(formula_ir, fixture)
    return fixture


def _adv_window(field: str) -> int | None:
    match = re.fullmatch(r'adv([1-9][0-9]*)', str(field or '').strip().lower())
    if not match:
        return None
    return int(match.group(1))


def _with_standard_formula_fixture_fields(formula_ir: dict[str, Any], fixture: pd.DataFrame) -> pd.DataFrame:
    required = {str(field).strip().lower() for field in formula_ir.get('required_fields') or []}
    adv_fields = sorted((field, _adv_window(field)) for field in required if _adv_window(field) is not None)
    if not required and not adv_fields:
        return fixture

    working = fixture.copy()
    volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
    if ('volume' in required or adv_fields or 'vwap' in required) and volume_col is None:
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: fixture missing volume/vol source')
    if 'volume' in required and 'volume' not in working.columns:
        working['volume'] = pd.to_numeric(working[volume_col], errors='coerce')
        volume_col = 'volume'

    if ('returns' in required or 'return' in required or 'ret' in required) and 'returns' not in working.columns:
        return_col = 'return' if 'return' in working.columns else 'pct_chg' if 'pct_chg' in working.columns else None
        if return_col is None:
            raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: fixture missing returns/pct_chg source')
        values = pd.to_numeric(working[return_col], errors='coerce')
        working['returns'] = values / 100.0 if return_col == 'pct_chg' else values
    if 'return' in required and 'return' not in working.columns and 'returns' in working.columns:
        working['return'] = working['returns']

    if 'vwap' in required and 'vwap' not in working.columns:
        volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
        if volume_col is None or 'amount' not in working.columns:
            raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: fixture missing vwap sources')
        volume = pd.to_numeric(working[volume_col], errors='coerce')
        amount = pd.to_numeric(working['amount'], errors='coerce')
        working['vwap'] = amount / volume.mask(volume == 0)

    missing_adv = [field for field, _window in adv_fields if field not in working.columns]
    if missing_adv:
        volume_col = 'volume' if 'volume' in working.columns else 'vol' if 'vol' in working.columns else None
        if volume_col is None:
            raise AssertionError(f'BLOCK_OPERATOR_PARITY_FAILED: fixture missing adv source {missing_adv}')
        volume = pd.to_numeric(working[volume_col], errors='coerce')
        grouped_volume = volume.groupby(working['ts_code'], sort=False)
        for field, window in adv_fields:
            if field in working.columns:
                continue
            working[field] = grouped_volume.transform(lambda s, window=window: s.rolling(window, min_periods=window).mean())
    return working


def _with_resolved_formula_fixture_fields(
    formula_ir: dict[str, Any], fixture: pd.DataFrame
) -> pd.DataFrame:
    resolved = {
        str(value).strip()
        for value in (formula_ir.get("resolved_fields") or {}).values()
        if isinstance(value, str) and value.strip()
    }

    def collect(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "field":
            value = node.get("resolved_field")
            if isinstance(value, str) and value.strip():
                resolved.add(value.strip())
        for child in node.get("args") or []:
            collect(child)

    collect(formula_ir.get("root"))
    missing = sorted(resolved - set(fixture.columns) - {"ts_code", "trade_date"})
    if not missing:
        return fixture
    working = fixture.copy()
    row_index = np.arange(len(working), dtype=float)
    for field_index, field in enumerate(missing, start=1):
        # Schema validation proves the field exists in real data. The parity
        # fixture only needs deterministic, finite variation for both engines.
        working[field] = 1.0 + field_index * 0.17 + (row_index % 13.0) * 0.031
    return working


def _load_compute(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot import generated operator artifact: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return implementation_callable(module)


def compare_outputs(reference: pd.DataFrame, generated: pd.DataFrame, *, tolerance: float = 1e-9) -> dict[str, Any]:
    # Legacy numerical fixtures use arbitrary matching key labels; only adapt
    # indexed class outputs here. Real stage inputs/outputs are validated by
    # the shared research API, not reinterpreted by the parity comparator.
    if isinstance(reference.index, pd.MultiIndex):
        reference = validate_factor_output(reference)
    if isinstance(generated.index, pd.MultiIndex):
        generated = validate_factor_output(generated)
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
    if not ref_mask.any():
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: no finite observations; empty/all-null parity is unverified')
    if not np.isfinite(ref[ref_mask]).all() or not np.isfinite(gen[gen_mask]).all():
        raise AssertionError('BLOCK_OPERATOR_PARITY_FAILED: non-finite output values')
    diffs = (ref[ref_mask] - gen[gen_mask]).abs()
    max_abs_diff = float(diffs.max())
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
    fixture = make_operator_fixture(formula_ir)
    reference = evaluate_formula_frame(formula_ir, fixture)
    compute = _load_compute(implementation_path)
    generated = compute(daily_df=fixture.copy(), minute_df=None)
    return compare_outputs(reference, generated, tolerance=tolerance)
