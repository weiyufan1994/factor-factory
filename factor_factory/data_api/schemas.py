from __future__ import annotations

from .contracts import DataSchema
from .datasets import BASE_LOGICAL_FIELDS, FIELD_ALIASES


def build_schema(
    *,
    dataset: str,
    columns: list[str],
    date_column: str,
    symbol_column: str,
    qlib_field_map: dict[str, str],
    resolved_fields: dict[str, str],
) -> DataSchema:
    logical_fields = dict(BASE_LOGICAL_FIELDS)
    logical_fields.update({key: value for key, value in resolved_fields.items()})
    return DataSchema.build(
        dataset=dataset,
        columns=columns,
        date_column=date_column,
        symbol_column=symbol_column,
        qlib_field_map=qlib_field_map,
        logical_fields=logical_fields,
        field_aliases={key: list(value) for key, value in FIELD_ALIASES.items()},
    )
