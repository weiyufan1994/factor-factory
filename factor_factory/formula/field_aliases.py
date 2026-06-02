from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable


FIELD_ALIASES = {
    'volume': ['volume', 'vol'],
    'vol': ['vol', 'volume'],
    'returns': ['returns', 'return', 'pct_chg'],
    'return': ['returns', 'return', 'pct_chg'],
    'ret': ['returns', 'return', 'pct_chg'],
    'market_cap': ['market_cap', 'total_mv'],
    'float_market_cap': ['float_market_cap', 'free_float_mv'],
    'amount': ['amount'],
    'open': ['open'],
    'high': ['high'],
    'low': ['low'],
    'close': ['close'],
    'vwap': ['vwap'],
    'turnover': ['turnover', 'turnover_rate'],
}

STANDARD_FORMULA_FIELDS_CONTRACT_VERSION = 'factorforge_standard_formula_fields_contract_v1'
STANDARD_OUTPUT_FIELDS = {'volume', 'returns', 'vwap'}
ADV_RE = re.compile(r'^adv([1-9][0-9]*)$', re.I)
FORMULA_FIELD_TOKEN_RE = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]*\b')


def is_adv_field(name: str) -> bool:
    return bool(ADV_RE.match(str(name).strip()))


def adv_window(name: str) -> int | None:
    m = ADV_RE.match(str(name).strip())
    return int(m.group(1)) if m else None


def is_standard_formula_field(name: str) -> bool:
    key = str(name).strip().lower()
    return key in STANDARD_OUTPUT_FIELDS or is_adv_field(key)


def standard_formula_fields_from_text(formula_text: str | None) -> list[str]:
    """Extract Alpha101 standard-field tokens directly from formula text.

    This is a producer-side safety net for malformed or incomplete upstream
    formula_ir.required_fields metadata. It intentionally only recognizes the
    formal standard fields managed by this contract.
    """
    if not formula_text:
        return []
    tokens = [match.group(0).strip().lower() for match in FORMULA_FIELD_TOKEN_RE.finditer(str(formula_text))]
    return sorted({token for token in tokens if is_standard_formula_field(token)})


def aliases_for(name: str) -> list[str]:
    key = str(name).strip().lower()
    if is_adv_field(key):
        return [key]
    if key not in FIELD_ALIASES:
        raise KeyError(f'BLOCK_MISSING_FIELD_ALIAS: {name}')
    return list(FIELD_ALIASES[key])


def resolve_field(name: str, available_columns: Iterable[str] | None = None) -> str:
    aliases = aliases_for(name)
    if available_columns is None:
        return aliases[0]
    available = {str(col): str(col) for col in available_columns}
    lower_to_actual = {str(col).lower(): str(col) for col in available_columns}
    for alias in aliases:
        if alias in available:
            return available[alias]
        if alias.lower() in lower_to_actual:
            return lower_to_actual[alias.lower()]
    raise KeyError(f'BLOCK_MISSING_FIELD_ALIAS: {name}')


def resolve_fields(required_fields: Iterable[str], available_columns: Iterable[str] | None = None) -> dict[str, str]:
    return {str(field): resolve_field(str(field), available_columns) for field in required_fields}


def field_alias_payload(required_fields: Iterable[str]) -> dict[str, list[str]]:
    return {str(field): aliases_for(str(field)) for field in required_fields}


def standard_formula_fields_contract(required_fields: Iterable[str], *, formula_text: str | None = None) -> dict[str, Any]:
    """Build the formal source-to-standard-field contract for Alpha101-style inputs."""
    requested = [str(field).strip().lower() for field in required_fields if str(field).strip()]
    formula_standard_fields = standard_formula_fields_from_text(formula_text)
    standard_requested = sorted(
        {field for field in requested if is_standard_formula_field(field)}
        | set(formula_standard_fields)
    )
    fields: dict[str, Any] = {}

    def add_volume(required_by: list[str]) -> None:
        fields.setdefault('volume', {
            'standard_field': 'volume',
            'materialized_field': 'volume',
            'source_candidates': ['vol', 'volume'],
            'selected_source': None,
            'derivation': 'identity',
            'required_by': sorted(set(required_by)),
            'leakage_policy': 'same_day_observable_after_close_no_future_rows',
        })

    def add_returns(required_by: list[str]) -> None:
        fields.setdefault('returns', {
            'standard_field': 'returns',
            'materialized_field': 'returns',
            'source_candidates': ['pct_chg', 'close+pre_close'],
            'selected_source': None,
            'derivation': 'pct_chg/100 or close/pre_close - 1',
            'required_by': sorted(set(required_by)),
            'leakage_policy': 'same_day_close_to_pre_close_no_future_rows',
        })

    def add_vwap(required_by: list[str]) -> None:
        add_volume(['vwap'])
        fields.setdefault('vwap', {
            'standard_field': 'vwap',
            'materialized_field': 'vwap',
            'source_candidates': ['amount+vol', 'amount+volume'],
            'selected_source': None,
            'derivation': 'amount / volume with explicit raw source unit policy',
            'required_by': sorted(set(required_by)),
            'unit_policy': {
                'amount_scale': 'raw_input_amount_units',
                'volume_scale': 'raw_input_volume_units',
                'ambiguity_policy': 'BLOCK unless selected_source and scale policy are recorded',
            },
            'leakage_policy': 'same_day_turnover_proxy_after_close_no_future_rows',
        })

    if 'volume' in standard_requested:
        add_volume(['formula'])
    if 'returns' in standard_requested:
        add_returns(['formula'])
    if 'vwap' in standard_requested:
        add_vwap(['formula'])
    for field in standard_requested:
        window = adv_window(field)
        if window:
            add_volume([field])
            fields[field] = {
                'standard_field': field,
                'materialized_field': field,
                'source_candidates': ['volume'],
                'selected_source': None,
                'derivation': f'rolling_mean(volume,{window}) grouped by ts_code',
                'window': window,
                'required_by': ['formula'],
                'window_policy': 'rolling_window_includes_current_trade_date_after_close',
                'leakage_policy': 'past_or_current_rows_only_grouped_by_ts_code',
            }

    return {
        'version': STANDARD_FORMULA_FIELDS_CONTRACT_VERSION,
        'formula_text': formula_text,
        'required_fields': requested,
        'formula_text_standard_fields': formula_standard_fields,
        'required_standard_formula_fields': standard_requested,
        'fields': fields,
        'leakage_policy': 'no future rows; derived fields are computed per ts_code in trade_date order',
        'materialization_owner': 'Step3A_or_Step4_data_contract',
    }


def validate_standard_formula_fields_contract(contract: dict[str, Any] | None) -> list[str]:
    if not contract:
        return []
    failures: list[str] = []
    if contract.get('version') != STANDARD_FORMULA_FIELDS_CONTRACT_VERSION:
        failures.append('BLOCK_STANDARD_FORMULA_FIELDS_MISSING: invalid standard_formula_fields_contract.version')
    requested = contract.get('required_standard_formula_fields')
    fields = contract.get('fields')
    if not isinstance(requested, list):
        failures.append('BLOCK_STANDARD_FORMULA_FIELDS_MISSING: required_standard_formula_fields must be a list')
        requested = []
    if not isinstance(fields, dict):
        failures.append('BLOCK_STANDARD_FORMULA_FIELDS_MISSING: fields must be a dict')
        fields = {}
    formula_standard_fields = standard_formula_fields_from_text(contract.get('formula_text'))
    if formula_standard_fields:
        missing_from_required = sorted(set(formula_standard_fields) - set(str(field).strip().lower() for field in requested))
        if missing_from_required:
            failures.append(f'BLOCK_STANDARD_FORMULA_FIELDS_MISSING: formula_text standard fields missing from contract {missing_from_required}')
    if requested and not contract.get('leakage_policy'):
        failures.append('BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING: leakage_policy missing')
    for field in requested:
        spec = fields.get(field)
        if not isinstance(spec, dict):
            failures.append(f'BLOCK_STANDARD_FORMULA_FIELDS_MISSING: {field} field contract missing')
            continue
        if not spec.get('materialized_field'):
            failures.append(f'BLOCK_STEP3A_STANDARD_FIELD_NOT_MATERIALIZED: {field} materialized_field missing')
        if not spec.get('source_candidates'):
            failures.append(f'BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING: {field} source_candidates missing')
        if not spec.get('leakage_policy'):
            failures.append(f'BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING: {field} leakage_policy missing')
        if field == 'vwap' and not isinstance(spec.get('unit_policy'), dict):
            failures.append('BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING: vwap unit_policy missing')
        if is_adv_field(field) and not isinstance(spec.get('window'), int):
            failures.append(f'BLOCK_STANDARD_FORMULA_FIELDS_MISSING: {field} window missing')
    return failures


def standard_field_contract_hash(contract: dict[str, Any]) -> str:
    import json

    blob = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def materialize_standard_formula_fields(frame: Any, contract: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
    """Materialize standard fields on a pandas-like frame, preserving existing columns."""
    profile: dict[str, Any] = {
        'version': 'factorforge_standard_formula_field_materialization_v1',
        'contract_version': (contract or {}).get('version') if isinstance(contract, dict) else None,
        'materialized_fields': [],
        'missing_fields': [],
        'source_fields': {},
    }
    if not contract or not hasattr(frame, 'columns'):
        return frame, profile
    requested = list(contract.get('required_standard_formula_fields') or [])
    if not requested:
        return frame, profile
    import numpy as np
    import pandas as pd

    out = frame.copy()

    def has(col: str) -> bool:
        return col in out.columns

    def note(field: str, source: str) -> None:
        if field not in profile['materialized_fields']:
            profile['materialized_fields'].append(field)
        profile['source_fields'][field] = source

    if any(field in requested or is_adv_field(field) for field in ['volume', *requested]):
        if not has('volume'):
            if has('vol'):
                out['volume'] = pd.to_numeric(out['vol'], errors='coerce')
                note('volume', 'vol')
            else:
                profile['missing_fields'].append('volume')
        else:
            note('volume', 'volume')

    if 'returns' in requested:
        if not has('returns'):
            if has('pct_chg'):
                out['returns'] = pd.to_numeric(out['pct_chg'], errors='coerce') / 100.0
                note('returns', 'pct_chg/100')
            elif has('close') and has('pre_close'):
                close = pd.to_numeric(out['close'], errors='coerce')
                pre_close = pd.to_numeric(out['pre_close'], errors='coerce')
                out['returns'] = close / pre_close.replace(0, np.nan) - 1.0
                note('returns', 'close/pre_close - 1')
            else:
                profile['missing_fields'].append('returns')
        else:
            note('returns', 'returns')

    if 'vwap' in requested:
        if not has('vwap'):
            amount_col = 'amount' if has('amount') else None
            volume_col = 'volume' if has('volume') else ('vol' if has('vol') else None)
            if amount_col and volume_col:
                amount = pd.to_numeric(out[amount_col], errors='coerce')
                volume = pd.to_numeric(out[volume_col], errors='coerce')
                out['vwap'] = amount / volume.replace(0, np.nan)
                note('vwap', f'{amount_col}/{volume_col}')
            else:
                profile['missing_fields'].append('vwap')
        else:
            note('vwap', 'vwap')

    adv_fields = [field for field in requested if is_adv_field(field)]
    if adv_fields:
        if not {'ts_code', 'trade_date', 'volume'}.issubset(out.columns):
            profile['missing_fields'].extend([field for field in adv_fields if field not in profile['missing_fields']])
        else:
            out = out.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
            volume = pd.to_numeric(out['volume'], errors='coerce')
            grouped = volume.groupby(out['ts_code'], sort=False)
            for field in adv_fields:
                window = adv_window(field)
                if window is None:
                    profile['missing_fields'].append(field)
                    continue
                if field not in out.columns:
                    out[field] = grouped.transform(lambda s, w=window: s.rolling(w, min_periods=1).mean())
                note(field, f'rolling_mean(volume,{window})')

    profile['materialized_fields'] = sorted(set(profile['materialized_fields']))
    profile['missing_fields'] = sorted(set(profile['missing_fields']))
    return out, profile
