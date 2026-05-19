from __future__ import annotations

from typing import Any

from .base import FAMILY_PLUGIN_PRODUCER, FamilyPluginContract, plugin_identity_fields, signal_column_name


class ShadowCandlestickPlugin:
    contract = FamilyPluginContract(
        family_id='shadow_candlestick',
        plugin_id='shadow_candlestick_v1',
        plugin_version='v1',
        implementation_mode='hybrid',
        allowed_factor_ids=(),
        allowed_source_types=('pdf_report', 'natural_language_hypothesis'),
    )

    def generate(self, report_id: str, prep: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
        factor_id = spec.get('factor_id') or f'{report_id}_shadow_candlestick'
        signal_col = signal_column_name(factor_id)
        sample = prep.get('sample_window', {})
        plugin_fields = plugin_identity_fields(self.contract)
        plan = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_mode': self.contract.implementation_mode,
            'producer': FAMILY_PLUGIN_PRODUCER,
            **plugin_fields,
            'rationale': [
                'Explicit shadow_candlestick family plugin selected by Step2 contract.',
                'This is not a generic fallback and cannot be triggered by text tokens or factor_id alone.',
            ],
            'inputs': {
                'daily_dataset': 'tushare_daily_bars',
                'sample_window': sample,
                'required_fields': ['ts_code', 'trade_date', 'open', 'high', 'low', 'close'],
            },
            'calculation_steps': [
                'Construct candlestick upper/lower shadow components from OHLC data.',
                'Apply family-specific rolling aggregation only under the explicit plugin contract.',
                'Expose a hybrid scaffold for downstream audited implementation.',
            ],
            'output_schema': {'columns': ['ts_code', 'trade_date', signal_col]},
            'step4_contract': {
                'runner_entry': f'generated_code/{report_id}/factor_impl_stub__{report_id}.py',
                'execution_mode': self.contract.implementation_mode,
                'expected_outputs': [],
            },
            'first_run_outputs': {
                'status': 'pending',
                'output_paths': [],
                'run_metadata_path': None,
                'producer': 'step3b',
            },
        }
        stub = f'''"""
Explicit shadow_candlestick_v1 family plugin scaffold for {factor_id}.
This file is not a generic fallback. It is valid only when Step2 declares
factor_family=shadow_candlestick and family_plugin_allowed=true.
"""

from __future__ import annotations

import pandas as pd

REPORT_ID = {report_id!r}
FACTOR_ID = {factor_id!r}
SIGNAL_COLUMN = {signal_col!r}
FAMILY_PLUGIN = {self.contract.plugin_id!r}
NOT_GENERIC_FALLBACK = True


def compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    required = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close']
    for column in required:
        if column not in daily_df.columns:
            raise KeyError(f'missing daily column: {{column}}')
    out = daily_df[required].copy()
    upper = out['high'] - out[['open', 'close']].max(axis=1)
    lower = out[['open', 'close']].min(axis=1) - out['low']
    price_range = (out['high'] - out['low']).replace(0, pd.NA)
    out[SIGNAL_COLUMN] = (lower - upper) / price_range
    return out[['ts_code', 'trade_date', SIGNAL_COLUMN]]
'''
        qlib = {
            'report_id': report_id,
            'factor_id': factor_id,
            'producer': FAMILY_PLUGIN_PRODUCER,
            **plugin_fields,
            'status': 'family_plugin_scaffold',
            'mode': 'shadow_candlestick_family',
            'non_qlib_parts': ['family-specific rolling shadow aggregation remains in audited Python/hybrid layer'],
        }
        scaffold = {
            'report_id': report_id,
            'factor_id': factor_id,
            'producer': FAMILY_PLUGIN_PRODUCER,
            **plugin_fields,
            'execution_mode': self.contract.implementation_mode,
            'boundary': {
                'operator_outputs': ['ohlc_shadow_components'],
                'custom_inputs': ['ohlc_shadow_components'],
                'custom_outputs': [signal_col],
            },
            'ide_edit_expected': True,
        }
        return plan, stub, qlib, scaffold


PLUGIN = ShadowCandlestickPlugin()
