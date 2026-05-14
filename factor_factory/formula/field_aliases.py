from __future__ import annotations

from typing import Iterable


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
