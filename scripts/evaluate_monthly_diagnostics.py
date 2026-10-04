#!/usr/bin/env python3
"""Consume existing Step4 factor/labels and explicit raw controls; no account run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from factor_factory.calendar_account_io import WindowReader, digest
from factor_factory.calendar_month import calendar_month_windows
from factor_factory.monthly_statistics import C11_PROFILE, RAW_CONTROL_NAMES, evaluate_c11_monthly
from factor_factory.research_api import _dates, _frame, _index
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id, write_json_atomic
from factor_factory.source_version import current_source_commit


def _bound_json(path, expected_hash=None):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('input_path_must_be_absolute')
    actual = digest(path)
    if expected_hash is not None and actual != expected_hash:
        raise ValueError('input_hash_mismatch:' + str(path))
    value = json.loads(path.read_text())
    if digest(path) != actual:
        raise ValueError('input_changed_during_read')
    return value, {'path': str(path), 'sha256': actual}


def _expected(prepared):
    start, end = _dates([prepared['is_start'], prepared['is_end']], name='research window')
    files = {}
    for role, required in [('calendar', ['trade_date']), ('membership', ['trade_date', 'ts_code'])]:
        spec = dict(prepared['files'][role])
        if role == 'membership' and prepared['membership_semantics'] == 'explicit_pit_true_membership_flag':
            required.append('is_member')
        mapping = spec['columns']
        if not set(required).issubset(mapping) or len(set(mapping.values())) != len(mapping):
            raise ValueError('missing_or_aliased_named_columns:' + role)
        if not Path(spec['path']).is_absolute():
            raise ValueError('input_path_must_be_absolute:' + role)
        spec['columns'] = {key: mapping[key] for key in required}
        files[role] = spec
    reader = WindowReader(files, start=start, end=end)
    windows = calendar_month_windows(reader.read('calendar', start, end).trade_date)
    members = []
    for w in windows.itertuples(index=False):
        frame = reader.read('membership', w.signal_date, w.signal_date)
        semantics = prepared['membership_semantics']
        if semantics == 'explicit_pit_true_membership_flag':
            flag = frame.is_member
            if flag.isna().any() or not flag.isin([True, False, 0, 1]).all():
                raise ValueError('unknown_membership')
            frame = frame.loc[flag.astype(bool)]
        elif semantics != 'explicit_pit_true_rows':
            raise ValueError('explicit_membership_semantics_required')
        if frame.empty:
            raise ValueError('missing_formation_membership:' + str(w.signal_date.date()))
        members.append(pd.DataFrame({'trade_date': w.entry_date, 'ts_code': frame.ts_code}))
    if not members:
        raise ValueError('empty_formation_calendar')
    all_members = pd.concat(members, ignore_index=True)
    index = _index(pd.MultiIndex.from_arrays([all_members.trade_date, all_members.ts_code], names=['datetime', 'instrument']))
    return index, windows, reader.profile, files


def _controls(binding, windows, expected):
    frames, receipts = [], []
    references = binding['monthly_controls']
    required = ['ts_code', 'signal_date', 'entry_date', *RAW_CONTROL_NAMES]
    for w in windows.itertuples(index=False):
        key = w.signal_date.strftime('%Y%m%d')
        spec = references.get(key)
        if spec is None:
            # A missing reference is recorded as a whole missing control month;
            # it never selects an older or next-available file.
            receipts.append({'signal_date': key, 'status': 'missing_reference'})
            continue
        if spec['source_kind'] != 'full_member_attrition':
            raise ValueError('controls_require_explicit_full_member_raw_source')
        declared = _dates([spec['signal_date'], spec['entry_date']], name='control binding dates')
        if declared[0] != w.signal_date or declared[1] != w.entry_date:
            raise ValueError('control_window_mismatch:' + key)
        declared_end = spec['label_end_date']
        if (pd.isna(w.label_end_date) and declared_end is not None) or (not pd.isna(w.label_end_date)
                and (declared_end is None or _dates([declared_end], name='control label end')[0] != w.label_end_date)):
            raise ValueError('control_label_window_mismatch:' + key)
        path = Path(spec['path'])
        if not path.is_absolute() or digest(path) != spec['sha256']:
            raise ValueError('control_path_or_hash_mismatch:' + key)
        # Project raw7 plus dates/identity ONLY. Old factors, gates, support,
        # labels and already ranked controls are not read from this source.
        frame = pd.read_parquet(path, columns=required)
        if not (_dates(frame.signal_date, name='raw control formation') == w.signal_date).all():
            raise ValueError('control_row_formation_mismatch:' + key)
        if not (_dates(frame.entry_date, name='raw control entry') == w.entry_date).all():
            raise ValueError('control_row_entry_mismatch:' + key)
        normalized = _frame(frame.drop(columns=['signal_date']).rename(columns={'entry_date': 'trade_date'}), list(RAW_CONTROL_NAMES), allow_empty=True)
        outside = normalized.index.difference(expected)
        frames.append(normalized.loc[normalized.index.isin(expected)])
        if digest(path) != spec['sha256']:
            raise ValueError('control_changed_during_read:' + key)
        receipts.append({**spec, 'status': 'read_raw7_only', 'source_rows': len(normalized),
                         'outside_current_membership_rows': len(outside)})
    if not frames:
        raw = pd.DataFrame(columns=list(RAW_CONTROL_NAMES), index=expected[:0], dtype=float)
    else:
        raw = pd.concat(frames)
    return raw, receipts


def run(args):
    if args.control_profile != C11_PROFILE:
        raise ValueError('explicit_supported_control_profile_required')
    out = Path(args.output).resolve()
    if out.exists():
        raise FileExistsError('existing_diagnostic_preserved')
    manifest = load_runtime_manifest(args.manifest)
    workspace = manifest_factorforge_root(manifest).resolve()
    factor_path = Path(args.factor_values).resolve()
    if args.report_id != manifest_report_id(manifest):
        raise ValueError('report_identity_mismatch')
    if factor_path != Path(manifest['runs']['factor_values_parquet']).resolve() or not factor_path.is_relative_to(workspace/'runs'):
        raise ValueError('requires_runtime_selected_step4_factor_values')
    primary_path = Path(args.primary_payload).resolve()
    if not primary_path.is_relative_to(workspace/'evaluations') or not out.is_relative_to(workspace/'evaluations'):
        raise ValueError('evaluation_path_outside_current_workspace')
    primary, primary_ref = _bound_json(primary_path)
    if primary.get('report_id') != args.report_id or primary.get('scope') != 'local_is_only' or primary.get('status') != 'success':
        raise ValueError('requires_successful_current_local_primary_payload')
    bindings = primary['bindings']
    factor_sha = digest(factor_path)
    if Path(bindings['factor_values_path']).resolve() != factor_path or bindings['factor_values_sha256'] != factor_sha:
        raise ValueError('primary_factor_binding_mismatch')
    if primary['diagnostics']['label'] != 'observed_adjusted_close_next_monthly_entry_over_entry_minus_one':
        raise ValueError('unsupported_monthly_label_semantics')
    prepared, prepared_ref = _bound_json(bindings['prepared_inputs'], bindings['prepared_inputs_sha256'])
    if prepared['report_id'] != args.report_id or prepared['scope'] != 'local_is_only':
        raise ValueError('prepared_input_identity_or_scope_mismatch')
    if prepared['price_basis_id'] != bindings['price_basis_id']:
        raise ValueError('price_basis_mismatch')
    if list(_dates([prepared['is_start'], prepared['is_end']], name='prepared window')) != list(_dates([bindings['is_start'], bindings['is_end']], name='account window')):
        raise ValueError('prepared_account_window_mismatch')
    label_path = Path(primary['artifacts']['monthly_labels']).resolve()
    if not label_path.is_relative_to(workspace/'evaluations'):
        raise ValueError('labels_outside_current_evaluations')
    label_sha = digest(label_path)
    controls_binding, controls_ref = _bound_json(Path(args.controls_binding).resolve())
    artifacts = out.with_suffix('')
    artifacts.mkdir(parents=True, exist_ok=False)
    sources = ['factor_factory/monthly_statistics.py', 'factor_factory/research_statistics.py',
               'factor_factory/research_api.py', 'factor_factory/calendar_month.py',
               'factor_factory/calendar_account_io.py', str(Path(__file__).resolve().relative_to(ROOT))]
    result = {'report_id': args.report_id, 'scope': 'local_is_only', 'status': 'failed',
              'account_simulation': False, 'results_computed': False,
              'tradable_net_alpha_evidence': False, 'control_profile': args.control_profile,
              'bindings': {'factor_values_path': str(factor_path), 'factor_values_sha256': factor_sha,
                           'labels_path': str(label_path), 'labels_sha256': label_sha,
                           'primary_payload': primary_ref, 'prepared_inputs': prepared_ref,
                           'raw_controls_binding': controls_ref, 'runtime_manifest_sha256': digest(args.manifest),
                           'framework_commit': current_source_commit(ROOT), 'source_root': str(ROOT),
                           'source_sha256': {p: digest(ROOT/p) for p in sources}}, 'artifacts': {}}
    write_json_atomic(out, result)
    try:
        expected, windows, profile, files = _expected(prepared)
        raw, receipts = _controls(controls_binding, windows, expected)
        result['raw_control_inputs'] = receipts
        factor = pd.read_parquet(factor_path)
        factor = factor[['factor_value']] if isinstance(factor.index, pd.MultiIndex) else factor[['ts_code', 'trade_date', 'factor_value']]
        labels = pd.read_csv(label_path, dtype={'ts_code': str, 'trade_date': str},
                             usecols=['ts_code', 'trade_date', 'forward_return'], float_precision='round_trip')
        computed = evaluate_c11_monthly(factor, labels, raw, expected_index=expected, calendar_slots=windows.entry_date)
        for ref in (primary_ref, prepared_ref, controls_ref, {'path': str(factor_path), 'sha256': factor_sha},
                    {'path': str(label_path), 'sha256': label_sha}, *files.values()):
            if digest(ref['path']) != ref['sha256']:
                raise ValueError('input_changed_during_diagnostic:' + ref['path'])
        support_path, periods_path = artifacts/'support.parquet', artifacts/'monthly_statistics.csv'
        computed.pop('support').to_parquet(support_path, index=False)
        pd.DataFrame(computed['periods']).to_csv(periods_path, index=False)
        result.update(computed, io_profile=profile, results_computed=True,
                      status='partial' if any(r['partial_reason'] or r['fmb_reason'] for r in computed['periods']) else 'success',
                      artifacts={'support': str(support_path), 'monthly_statistics': str(periods_path)})
        write_json_atomic(out, result)
        return 0
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        write_json_atomic(out, result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('report-id', 'factor-values', 'primary-payload', 'controls-binding', 'control-profile', 'output', 'manifest'):
        parser.add_argument('--'+name, required=True)
    return run(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
