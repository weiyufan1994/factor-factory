from __future__ import annotations

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
STANDARD_FORMULA_FIELDS = {'volume', 'returns', 'vwap'}
STANDARD_SOURCE_FIELD_CANDIDATES = {
    'volume': ['vol', 'volume'],
    'returns': ['pct_chg', 'return', 'returns', 'close', 'pre_close'],
    'vwap': ['amount', 'vol', 'volume'],
}
STANDARD_DERIVATION_RULES = {
    'volume': {
        'rule': 'vol or volume after catalog unit normalization',
        'source_unit': 'shares_or_lots_from_catalog',
        'output_unit': 'documented_volume_unit',
    },
    'returns': {
        'rule': 'pct_chg / 100 if pct_chg is percent; otherwise use decimal return field',
        'source_unit': 'percent_or_decimal_from_catalog',
        'output_unit': 'decimal_return',
    },
    'vwap': {
        'rule': 'amount / volume after unit normalization',
        'source_unit': 'amount_and_volume_from_catalog',
        'output_unit': 'price',
    },
    'advN': {
        'rule': 'rolling_mean(volume, N)',
        'source_unit': 'documented_volume_unit',
        'output_unit': 'documented_volume_unit',
        'include_current_day': True,
        'missing_policy': 'early windows are null until enough observations are available',
    },
}


def _adv_token(value: str) -> str | None:
    match = re.fullmatch(r'adv([1-9][0-9]*)', str(value or '').strip().lower())
    if not match:
        return None
    return f'adv{match.group(1)}'


def is_standard_formula_field(value: str) -> bool:
    token = str(value or '').strip().lower()
    return token in STANDARD_FORMULA_FIELDS or _adv_token(token) is not None


def standard_formula_fields_from_text(formula_text: str) -> list[str]:
    """Extract Alpha101 standard fields from formula text without substring matches."""
    text = str(formula_text or '').lower()
    found: list[str] = []
    for match in re.finditer(r'\b(volume|returns|return|ret|vwap|adv[1-9][0-9]*)\b', text):
        token = match.group(1)
        if token in {'return', 'ret'}:
            token = 'returns'
        adv = _adv_token(token)
        found.append(adv or token)
    return list(dict.fromkeys(found))


def standard_formula_fields_from_required_fields(required_fields: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for raw in required_fields or []:
        token = str(raw or '').strip().lower()
        if token in {'return', 'ret'}:
            token = 'returns'
        adv = _adv_token(token)
        if token in STANDARD_FORMULA_FIELDS or adv:
            out.append(adv or token)
    return list(dict.fromkeys(out))


def _source_candidates_for(field: str) -> list[str]:
    adv = _adv_token(field)
    if adv:
        return ['volume', 'vol']
    return list(STANDARD_SOURCE_FIELD_CANDIDATES.get(field, []))


def _derivation_rule_for(field: str) -> dict[str, Any]:
    adv = _adv_token(field)
    if adv:
        window = int(adv[3:])
        rule = dict(STANDARD_DERIVATION_RULES['advN'])
        rule['lookback'] = window
        rule['lookback_window'] = window
        return rule
    return dict(STANDARD_DERIVATION_RULES.get(field, {}))


def build_standard_formula_fields_contract(
    *,
    formula_text: str = '',
    required_fields: Iterable[str] | None = None,
    available_source_fields: Iterable[str] | None = None,
) -> dict[str, Any]:
    required = list(
        dict.fromkeys(
            standard_formula_fields_from_required_fields(required_fields)
            + standard_formula_fields_from_text(formula_text)
        )
    )
    formula_fields_detected = list(dict.fromkeys(
        [str(field).strip().lower() for field in (required_fields or []) if str(field).strip()]
        + standard_formula_fields_from_text(formula_text)
    ))
    available = {str(field).strip().lower() for field in (available_source_fields or []) if str(field).strip()}
    source_candidates = {field: _source_candidates_for(field) for field in required}
    derivation_rules = {field: _derivation_rule_for(field) for field in required}
    unavailable = {
        field: candidates
        for field, candidates in source_candidates.items()
        if available and not any(candidate in available for candidate in candidates)
    }
    return {
        'version': STANDARD_FORMULA_FIELDS_CONTRACT_VERSION,
        'required_standard_formula_fields': required,
        'formula_fields_detected': formula_fields_detected,
        'source_field_candidates': source_candidates,
        'derivation_rules': derivation_rules,
        'lookback_policy': 'uses data available at factor timestamp only',
        'leakage_policy': 'no future data',
        'block_if_unavailable': True,
        'source_fields_available': sorted(available),
        'unavailable_source_fields': unavailable,
    }


def validate_standard_formula_fields_contract(
    contract: dict[str, Any] | None,
    *,
    formula_text: str = '',
    required_fields: Iterable[str] | None = None,
    available_columns: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    implied = set(
        standard_formula_fields_from_required_fields(required_fields)
        + standard_formula_fields_from_text(formula_text)
    )
    if not isinstance(contract, dict) or not contract:
        if implied:
            failures.append({
                'code': 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING',
                'message': 'standard_formula_fields_contract missing while formula requires Alpha101 standard fields',
                'evidence': {'implied': sorted(implied)},
            })
        return failures
    required = contract.get('required_standard_formula_fields')
    if not isinstance(required, list):
        failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING', 'message': 'required_standard_formula_fields must be a list'})
        required = []
    normalized_required = [(_adv_token(str(item)) or str(item).strip().lower()) for item in required]
    if not implied and not normalized_required:
        return []
    if contract.get('version') != STANDARD_FORMULA_FIELDS_CONTRACT_VERSION:
        failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING', 'message': 'invalid standard_formula_fields_contract.version'})
    missing_from_contract = sorted(implied - set(normalized_required))
    if missing_from_contract:
        failures.append({
            'code': 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING',
            'message': 'formula_text standard fields missing from contract',
            'evidence': {'missing': missing_from_contract},
        })
    if contract.get('block_if_unavailable') is not True:
        failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELDS_MISSING', 'message': 'block_if_unavailable must be true'})
    if str(contract.get('leakage_policy') or '').strip().lower() != 'no future data':
        failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELD_LEAKAGE_POLICY_MISSING', 'message': 'leakage_policy must be no future data'})
    if not str(contract.get('lookback_policy') or '').strip():
        failures.append({'code': 'BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING', 'message': 'lookback_policy missing'})
    source_candidates = contract.get('source_field_candidates') if isinstance(contract.get('source_field_candidates'), dict) else {}
    rules = contract.get('derivation_rules') if isinstance(contract.get('derivation_rules'), dict) else {}
    available = {str(col).strip().lower() for col in (available_columns or []) if str(col).strip()}
    for field in normalized_required:
        candidates = source_candidates.get(field)
        if not isinstance(candidates, list) or not candidates:
            failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING', 'message': f'{field} source candidates missing'})
        elif available and field == 'vwap' and not ('amount' in available and ('vol' in available or 'volume' in available)):
            failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING', 'message': f'{field} requires amount and volume/vol source', 'evidence': {'available': sorted(available), 'candidates': candidates}})
        elif available and not any(str(candidate).lower() in available for candidate in candidates):
            failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELD_SOURCE_MISSING', 'message': f'{field} source unavailable', 'evidence': {'available': sorted(available), 'candidates': candidates}})
        rule = rules.get(field)
        if not isinstance(rule, dict) or not rule.get('rule'):
            failures.append({'code': 'BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING', 'message': f'{field} derivation rule missing'})
            continue
        if field in {'returns', 'vwap', 'volume'} and not (rule.get('output_unit') and (rule.get('source_unit') or rule.get('source_units'))):
            failures.append({'code': 'BLOCK_STANDARD_FORMULA_FIELD_UNIT_AMBIGUOUS', 'message': f'{field} unit policy missing'})
        if _adv_token(field) and not (rule.get('lookback') or rule.get('lookback_window')):
            failures.append({'code': 'BLOCK_STANDARD_FORMULA_DERIVATION_POLICY_MISSING', 'message': f'{field} lookback policy missing'})
    return failures


def aliases_for(name: str) -> list[str]:
    key = str(name).strip().lower()
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
