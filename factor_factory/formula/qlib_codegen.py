from __future__ import annotations

from .registry import operator_meta


def _emit(node: dict) -> str:
    typ = node.get('type')
    if typ == 'field':
        return f'${node["resolved_field"]}'
    if typ == 'constant':
        return str(node['value'])
    if typ != 'operator':
        raise ValueError(f'BLOCK_UNSUPPORTED_IR_NODE: {typ}')
    op = node['operator']
    meta = operator_meta(op)
    args = [_emit(arg) for arg in node.get('args') or []]
    if op == 'delay':
        return f'Ref({args[0]}, {args[1]})'
    if op == 'delta':
        return f'({args[0]} - Ref({args[0]}, {args[1]}))'
    if op == 'negate':
        return f'(-1 * {args[0]})'
    if op in {'plus', 'minus', 'multiply', 'divide'}:
        symbol = {'plus': '+', 'minus': '-', 'multiply': '*', 'divide': '/'}[op]
        return f'({args[0]} {symbol} {args[1]})'
    qlib = meta.get('qlib_name')
    if not meta.get('supports_qlib') or qlib is None:
        raise ValueError(f'BLOCK_UNSUPPORTED_QLIB_OPERATOR: {op}')
    return f'{qlib}({", ".join(args)})'


def to_qlib_expression(formula_ir: dict) -> dict:
    if formula_ir.get('parse_status') != 'success':
        return {
            'status': 'unsupported',
            'qlib_supported': False,
            'unsupported_operators': [],
            'fallback_allowed': False,
            'reason': f'formula parse failed: {formula_ir.get("parse_errors")}',
        }
    try:
        return {
            'status': 'supported',
            'qlib_supported': True,
            'unsupported_operators': [],
            'fallback_allowed': False,
            'expression': _emit(formula_ir['root']),
        }
    except ValueError as exc:
        reason = str(exc)
        unsupported = []
        if 'BLOCK_UNSUPPORTED_QLIB_OPERATOR:' in reason:
            unsupported.append(reason.split('BLOCK_UNSUPPORTED_QLIB_OPERATOR:', 1)[1].strip())
        return {
            'status': 'unsupported',
            'qlib_supported': False,
            'unsupported_operators': unsupported,
            'fallback_allowed': False,
            'reason': reason,
        }
