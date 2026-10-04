#!/usr/bin/env python3
"""Thin existing Step4 custom-backend envelope for the shared monthly account."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

# Select this adapter's reviewed maintenance checkout, independent of a pinned
# study's older launcher/PYTHONPATH. No runtime imports from study directories.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from factor_factory.calendar_account_io import MonthlyMarket, WindowReader, digest
from factor_factory.calendar_month import backtest_calendar_month, calendar_month_windows, performance
from factor_factory.primary_evaluator import normalize_primary_evaluator_payload, primary_payload_missing_evidence
from factor_factory.research_api import _dates
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id, write_json_atomic
from factor_factory.source_version import current_source_commit


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class CsvSink:
    def __init__(self, path, empty_columns):
        self.path, self.empty_columns, self.written = path, empty_columns, False

    def __call__(self, frame):
        frame.to_csv(self.path, mode='a', header=not self.written, index=False)
        self.written = True

    def finish(self):
        if not self.written:
            pd.DataFrame(columns=self.empty_columns).to_csv(self.path, index=False)


def run(args):
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError('existing_payload_preserved')
    manifest = load_runtime_manifest(args.manifest)
    workspace = manifest_factorforge_root(manifest).resolve()
    factor_path = Path(args.factor_values).resolve()
    if args.report_id != manifest_report_id(manifest):
        raise ValueError('report_identity_mismatch')
    if factor_path != Path(manifest['runs']['factor_values_parquet']).resolve() or not factor_path.is_relative_to(workspace / 'runs'):
        raise ValueError('requires_runtime_selected_step4_factor_values')
    if not out.is_relative_to(workspace / 'evaluations'):
        raise ValueError('output_outside_current_evaluations')
    input_path = Path(args.prepared_inputs).resolve()
    prepared = json.loads(input_path.read_text())
    if prepared.get('report_id') != args.report_id or prepared.get('scope') != 'local_is_only':
        raise ValueError('prepared_input_identity_or_scope_mismatch')
    start, end = _dates([prepared['is_start'], prepared['is_end']], name='research window')
    basis = prepared['price_basis_id']
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError('explicit_fixed_price_basis_required')
    artifacts_dir = out.with_suffix('')
    artifacts_dir.mkdir(parents=True, exist_ok=False)
    backend = os.environ.get('STEP4_BACKEND_NAME', 'calendar_month_account')
    plan = {'primary_backend': backend, 'frequency': 'monthly', 'scope': 'local_is_only',
            'backends': [{'name': backend, 'script_path': str(Path(__file__).resolve())}]}
    source_names = ['factor_factory/calendar_account.py', 'factor_factory/calendar_account_io.py',
                    'factor_factory/calendar_month.py', 'factor_factory/research_api.py',
                    'factor_factory/research_statistics.py', str(Path(__file__).resolve().relative_to(ROOT))]
    payload = {'backend': backend, 'report_id': args.report_id, 'scope': 'local_is_only',
               'status': 'failed', 'results_computed': False, 'stage': 'inputs',
               'account_simulation': True, 'tradable_net_alpha_evidence': False,
               'accounts_completed': [], 'artifacts': {},
               'performance': {'net_valuation_complete': False, 'gross_valuation_complete': False},
               'bindings': {'prepared_inputs': str(input_path), 'prepared_inputs_sha256': digest(input_path),
                            'factor_values_path': str(factor_path), 'factor_values_sha256': digest(factor_path),
                            'runtime_manifest_sha256': digest(args.manifest),
                            'adapter_framework_commit': current_source_commit(ROOT),
                            'adapter_source_root': str(ROOT), 'adapter_source_sha256': {p: digest(ROOT / p) for p in source_names},
                            'price_basis_id': basis, 'is_start': str(start.date()), 'is_end': str(end.date()),
                            'pin_changed_by_adapter': False}}
    def checkpoint():
        write_json_atomic(out, clean(payload))
    sinks = {}
    checkpoint()
    try:
        required = {'daily': {'ts_code', 'trade_date', 'close_adj'},
                    'calendar': {'trade_date'}, 'membership': {'ts_code', 'trade_date'},
                    'execution_prices': {'ts_code', 'trade_date', 'execution_close_raw'},
                    'constraints': {'ts_code', 'trade_date', 'constraint_complete', 'st_state', 'suspension_state',
                                    'up_limit', 'down_limit', 'buy_execution_action', 'sell_execution_action',
                                    'pretrade_buy_blocked', 'pretrade_sell_blocked'}}
        files = {role: prepared['files'][role] for role in required}
        for role, columns in required.items():
            mapping = files[role]['columns']
            if not columns.issubset(mapping) or len(set(mapping.values())) != len(mapping):
                raise ValueError('missing_or_aliased_named_columns:' + role)
            if not Path(files[role]['path']).is_absolute():
                raise ValueError('prepared_input_path_must_be_absolute:' + role)
        # Outer joins must not silently suffix/override execution or valuation
        # meanings supplied under two roles. Daily selects only close_adj.
        constraint_fields = set(files['constraints']['columns']) - {'ts_code', 'trade_date'}
        execution_fields = set(files['execution_prices']['columns']) - {'ts_code', 'trade_date'}
        if (constraint_fields & execution_fields or
                {'price', 'close_adj', 'execution_price_basis'} & (constraint_fields | execution_fields)):
            raise ValueError('overlapping_market_role_columns')
        reader = WindowReader(files, start=start, end=end)
        calendar = _dates(reader.read('calendar', start, end).trade_date, name='exchange calendar')
        windows = calendar_month_windows(calendar)
        # Only the complete monthly formation cross-sections, not every daily
        # member row over the full research window, are loaded into memory.
        member_frames = [reader.read('membership', date, date) for date in windows.signal_date]
        if not member_frames:
            raise ValueError('empty_formation_calendar')
        membership = pd.concat(member_frames, ignore_index=True)
        semantics = prepared.get('membership_semantics')
        if semantics == 'explicit_pit_true_membership_flag':
            flag = membership['is_member']
            if flag.isna().any() or not flag.isin([True, False, 0, 1]).all():
                raise ValueError('unknown_membership')
            membership = membership.loc[flag.astype(bool)]
        elif semantics != 'explicit_pit_true_rows':
            raise ValueError('explicit_membership_semantics_required')
        membership = membership[['ts_code', 'trade_date']]
        native = pd.read_parquet(factor_path)
        # The canonical signal is explicit even when the native output carries
        # additional audit columns. The public API validates keys/numeric values.
        factor = native[['factor_value']] if isinstance(native.index, pd.MultiIndex) else native[['ts_code', 'trade_date', 'factor_value']]
        symbols = set(native.index.get_level_values('instrument')) if isinstance(native.index, pd.MultiIndex) else set(native.ts_code)
        market = MonthlyMarket(reader, symbols=symbols)
        for name in ('base30bp', 'stress60bp'):
            sinks[name] = {'trades': CsvSink(artifacts_dir / f'{name}_trades.csv', ['trade_date', 'ts_code', 'side', 'status', 'cost']),
                           'stale_marks': CsvSink(artifacts_dir / f'{name}_stale_marks.csv', ['trade_date', 'ts_code', 'valuation_mark', 'status'])}
        def complete(name, account):
            for sink in sinks[name].values():
                sink.finish()
            nav_path = artifacts_dir / f'{name}_daily_nav.csv'
            account['daily_nav'].drop(columns='holdings').to_csv(nav_path, index=False)
            state_path = artifacts_dir / f'{name}_state.json'
            write_json_atomic(state_path, clean({key: account[key] for key in ('initial_state', 'terminal_state', 'cost_rate', 'unit_kind', 'evidence_scope', 'gross_definition')}))
            payload['artifacts'].update({name + '_daily_nav': str(nav_path), name + '_state': str(state_path),
                                         **{name + '_' + key: str(sink.path) for key, sink in sinks[name].items()}})
            payload['accounts_completed'].append(name)
            payload['results_computed'] = True
            checkpoint()
        payload.update(stage='accounts_and_monthly_labels', results_computed=None,
                       observation_status='attempted_do_not_reset_trial')
        checkpoint()
        result = backtest_calendar_month(factor, calendar=calendar, membership=membership, market=market,
                                        price_basis_id=basis, retain_holdings=False, sinks=sinks, on_complete=complete)
        for key in ('coverage', 'monthly_ic', 'monthly_labels'):
            path = artifacts_dir / (key + '.csv')
            result[key].to_csv(path, index=False)
            payload['artifacts'][key] = str(path)
        base = result['accounts']['base30bp']
        shadow = base['daily_nav'].copy()
        shadow['nav'], shadow['daily_return'], shadow['cost_weight'] = shadow.gross_shadow_nav, shadow.gross_shadow_daily_return, 0.
        gross = performance(shadow)
        gross['return_basis'] = 'same_base30bp_units_fee_refund_idle_cash_shadow'
        payload.update(long_side_performance=base['performance'], gross_shadow_performance=gross,
                       stress60bp_performance=result['accounts']['stress60bp']['performance'],
                       stress_comparison=result['stress_comparison'], ic_summary=result['ic_summary'],
                       io_profile=reader.profile,
                       diagnostics={'label': 'observed_adjusted_close_next_monthly_entry_over_entry_minus_one',
                                    'five_groups': 'finite_formation_signal_midrank_percentile_before_labels; available_label_mean',
                                    'top_minus_bottom': 'monthly_label_diagnostic_not_short_account',
                                    'hac3': 'Bartlett calendar slots retained; observed-score sandwich; no finite-sample multiplier',
                                    'partial_rank_ic': 'separate_public_statistic_not_computed_here'})
        payload['performance'] = {'net_valuation_complete': True, 'gross_valuation_complete': True,
                                  'gross_definition': base['gross_definition'],
                                  'terminal_residual_weight': float(base['daily_nav'].terminal_residual_weight.iloc[-1])}
        path = artifacts_dir / 'performance.json'
        write_json_atomic(path, clean({key: payload[key] for key in ('long_side_performance', 'gross_shadow_performance', 'stress60bp_performance', 'performance')}))
        payload['artifacts'].update(performance=str(path), daily_nav=payload['artifacts']['base30bp_daily_nav'],
                                    trades=payload['artifacts']['base30bp_trades'])
        missing = primary_payload_missing_evidence(normalize_primary_evaluator_payload(clean(payload), plan))
        payload.update(status='partial' if missing else 'success', missing_metrics=missing, results_computed=True,
                       stage='complete', observation_status='observed_do_not_reset_trial')
        checkpoint()
        return 0
    except Exception as exc:
        # If an account failed mid-path, preserve its partial ledger as failed
        # evidence. A completed account alone does not imply the next completed.
        for name, account_sinks in sinks.items():
            for key, sink in account_sinks.items():
                if sink.path.exists():
                    payload['artifacts'][name + '_' + key] = str(sink.path)
        payload.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        checkpoint()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('report-id', 'factor-values', 'output', 'manifest', 'prepared-inputs'):
        parser.add_argument('--' + name, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
