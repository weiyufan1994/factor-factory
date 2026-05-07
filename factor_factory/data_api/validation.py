from __future__ import annotations

from .contracts import DataApiResult, DataValidationCheck, DataValidationReport


def validate_data_api_result(result: DataApiResult) -> DataValidationReport:
    checks: list[DataValidationCheck] = []

    def add(name: str, ok: bool, message: str = '', warn: bool = False) -> None:
        checks.append(DataValidationCheck(name, 'PASS' if ok else ('WARN' if warn else 'BLOCK'), message))

    add('status_legal', result.status in {'ready', 'proxy_ready', 'blocked'}, result.status)
    add('schema_present', bool(result.schema.columns and result.schema.date_column and result.schema.symbol_column))
    add('date_column_present', result.schema.date_column in result.schema.columns)
    add('symbol_column_present', result.schema.symbol_column in result.schema.columns)
    add('required_fields_present', not result.coverage.missing_fields, ','.join(result.coverage.missing_fields))
    row_count_ok = result.coverage.row_count > 0 or (result.status == 'blocked' and bool(result.coverage.missing_fields))
    add('row_count_nonzero_or_blocked', row_count_ok)
    duplicate_ok = result.coverage.duplicate_key_count == 0 or result.query.allow_duplicate_keys
    add('duplicate_key_count_zero_or_allowed', duplicate_ok, str(result.coverage.duplicate_key_count))
    add('alias_resolution_explicit', all(result.resolved_fields.get(field) for field in result.query.fields if field not in result.coverage.missing_fields))
    if result.status == 'proxy_ready':
        add('proxy_rules_explicit', bool(result.proxy_rules))
    else:
        add('proxy_rules_explicit', True)
    add('no_unsupported_silent_fallback', result.blocked_reason is not None if result.status == 'blocked' else True)

    final = 'PASS'
    if any(check.result == 'BLOCK' for check in checks):
        final = 'BLOCK'
    elif any(check.result == 'WARN' for check in checks):
        final = 'WARN'
    return DataValidationReport(result=final, checks=checks)
