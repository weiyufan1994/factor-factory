from __future__ import annotations

from typing import Any

from .base import FAMILY_PLUGIN_PRODUCER, FamilyPluginContract, plugin_identity_fields, signal_column_name


class PriceVolumePlugin:
    contract = FamilyPluginContract(
        family_id='price_volume',
        plugin_id='price_volume_v1',
        plugin_version='v1',
        implementation_mode='direct_code',
        allowed_factor_ids=(),
        allowed_source_types=('pdf_report', 'natural_language_hypothesis'),
    )

    def generate(self, report_id: str, prep: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
        factor_id = spec.get('factor_id') or f'{report_id}_price_volume'
        signal_col = signal_column_name(factor_id)
        plugin_fields = plugin_identity_fields(self.contract)
        plan = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_mode': self.contract.implementation_mode,
            'producer': FAMILY_PLUGIN_PRODUCER,
            **plugin_fields,
            'rationale': [
                'Explicit price_volume_v1 family plugin selected by Step2 contract.',
                'This path is not a generic fallback and cannot be triggered by free-text price-volume tokens alone.',
            ],
            'inputs': {
                'minute_dataset': 'tushare_minute_bars',
                'daily_dataset': 'tushare_daily_bars',
                'sample_window': prep.get('sample_window', {}),
                'required_fields': ['ts_code', 'trade_date', 'open', 'close', 'vol'],
            },
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
Explicit price_volume_v1 family plugin scaffold for {factor_id}.
This file is not a generic fallback. It is valid only when Step2 declares
factor_family=price_volume and family_plugin_allowed=true.
"""

from __future__ import annotations

import pandas as pd

REPORT_ID = {report_id!r}
FACTOR_ID = {factor_id!r}
SIGNAL_COLUMN = {signal_col!r}
FAMILY_PLUGIN = {self.contract.plugin_id!r}
NOT_GENERIC_FALLBACK = True


def compute_factor(daily_df: pd.DataFrame, minute_df=None) -> pd.DataFrame:
    required = ['ts_code', 'trade_date', 'open', 'close', 'vol']
    for column in required:
        if column not in daily_df.columns:
            raise KeyError(f'missing daily column: {{column}}')
    out = daily_df[['ts_code', 'trade_date']].copy()
    safe_open = daily_df['open'].replace(0, pd.NA)
    intraday_return = (daily_df['close'] - daily_df['open']) / safe_open
    volume = pd.to_numeric(daily_df['vol'], errors='coerce')
    date_median_volume = volume.groupby(daily_df['trade_date']).transform('median').replace(0, pd.NA)
    relative_participation = volume / date_median_volume
    out[SIGNAL_COLUMN] = intraday_return * relative_participation
    return out
'''
        qlib = {
            'report_id': report_id,
            'factor_id': factor_id,
            'producer': FAMILY_PLUGIN_PRODUCER,
            **plugin_fields,
            'status': 'family_plugin_scaffold',
            'mode': 'price_volume_family',
            'non_qlib_parts': ['audited price-volume decomposition belongs to explicit plugin logic'],
        }
        scaffold = {
            'report_id': report_id,
            'factor_id': factor_id,
            'producer': FAMILY_PLUGIN_PRODUCER,
            **plugin_fields,
            'execution_mode': self.contract.implementation_mode,
            'data_layer': 'Step3A normalized daily/minute inputs',
            'ide_edit_expected': True,
        }
        return plan, stub, qlib, scaffold


PLUGIN = PriceVolumePlugin()
