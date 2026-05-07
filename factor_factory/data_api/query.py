from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from .errors import DataQueryInvalid


Universe = str | list[str] | tuple[str, ...]


def normalize_date(value: str | int | pd.Timestamp, field_name: str = 'date') -> str:
    if isinstance(value, pd.Timestamp):
        return value.strftime('%Y%m%d')
    raw = str(value).strip()
    if not raw:
        raise DataQueryInvalid(f'{field_name} is required')
    compact = raw.replace('-', '')
    if len(compact) != 8 or not compact.isdigit():
        raise DataQueryInvalid(f'{field_name} must be YYYYMMDD or YYYY-MM-DD: {value!r}')
    try:
        parsed = pd.to_datetime(compact, format='%Y%m%d')
    except Exception as exc:  # pragma: no cover - pandas message varies
        raise DataQueryInvalid(f'{field_name} is not a valid calendar date: {value!r}') from exc
    return parsed.strftime('%Y%m%d')


def normalize_universe(universe: Universe) -> str | tuple[str, ...]:
    if isinstance(universe, str):
        name = universe.strip()
        if not name:
            raise DataQueryInvalid('universe cannot be empty')
        if name == 'a_share_all':
            return name
        raise DataQueryInvalid(f'unsupported universe name: {name}')
    symbols = tuple(str(item).strip() for item in universe if str(item).strip())
    if not symbols:
        raise DataQueryInvalid('universe list cannot be empty')
    return symbols


@dataclass(frozen=True)
class DataQuery:
    dataset: str
    start_date: str | int | pd.Timestamp
    end_date: str | int | pd.Timestamp
    universe: Universe
    fields: list[str]
    frequency: str = 'daily'
    adjust: str | None = None
    calendar: str = 'a_share'
    include_suspended: bool | None = None
    allow_duplicate_keys: bool = False

    def __post_init__(self) -> None:
        dataset = str(self.dataset).strip()
        frequency = str(self.frequency).strip() or 'daily'
        calendar = str(self.calendar).strip() or 'a_share'
        fields = tuple(str(field).strip() for field in self.fields if str(field).strip())
        if not dataset:
            raise DataQueryInvalid('dataset is required')
        if not fields:
            raise DataQueryInvalid('fields must be non-empty')
        start = normalize_date(self.start_date, 'start_date')
        end = normalize_date(self.end_date, 'end_date')
        if start > end:
            raise DataQueryInvalid(f'start_date must be <= end_date: {start}>{end}')
        object.__setattr__(self, 'dataset', dataset)
        object.__setattr__(self, 'start_date', start)
        object.__setattr__(self, 'end_date', end)
        object.__setattr__(self, 'universe', normalize_universe(self.universe))
        object.__setattr__(self, 'fields', list(dict.fromkeys(fields)))
        object.__setattr__(self, 'frequency', frequency)
        object.__setattr__(self, 'calendar', calendar)

    @property
    def symbols(self) -> tuple[str, ...]:
        return () if self.universe == 'a_share_all' else tuple(self.universe)
