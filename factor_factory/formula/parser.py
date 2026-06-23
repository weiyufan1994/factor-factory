from __future__ import annotations

import ast
from typing import Any

from factor_factory.artifact_identity import stable_hash
from .field_aliases import field_alias_payload, resolve_field, resolve_fields
from .ir import FORMULA_IR_VERSION
from .registry import canonical_operator_name, validate_operator_call


def _node(raw: ast.AST) -> dict[str, Any]:
    if isinstance(raw, ast.Expression):
        return _node(raw.body)
    if isinstance(raw, ast.Name):
        return {'type': 'field', 'name': raw.id, 'resolved_field': resolve_field(raw.id)}
    if isinstance(raw, ast.Constant) and isinstance(raw.value, (int, float)):
        return {'type': 'constant', 'value': raw.value}
    if isinstance(raw, ast.UnaryOp) and isinstance(raw.op, ast.USub):
        return {'type': 'operator', 'operator': 'negate', 'args': [_node(raw.operand)]}
    if isinstance(raw, ast.BinOp):
        op_map = {
            ast.Add: 'plus',
            ast.Sub: 'minus',
            ast.Mult: 'multiply',
            ast.Div: 'divide',
            ast.Pow: 'signedpower',
        }
        for klass, name in op_map.items():
            if isinstance(raw.op, klass):
                return {'type': 'operator', 'operator': name, 'args': [_node(raw.left), _node(raw.right)]}
    if isinstance(raw, ast.Call) and isinstance(raw.func, ast.Name):
        name = canonical_operator_name(raw.func.id)
        args = [_node(arg) for arg in raw.args]
        for keyword in raw.keywords:
            if keyword.arg is None:
                raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: starred keyword in {raw.func.id}')
            key = str(keyword.arg).strip().lower()
            if name == 'cs_regression' and key == 'out_type':
                args.append(_node(keyword.value))
            elif name == 'cs_regression' and key in {'with_one_col', 'fill_predict', 'dummies'}:
                # Supported by the source operator contract but not needed by the
                # current residual/predicted/beta evaluator. Defaults are enforced.
                continue
            else:
                raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_KEYWORD: {raw.func.id}.{keyword.arg}')
        if name == 'cs_regression' and len(args) == 2:
            args.append({'type': 'constant', 'value': 0})
        validate_operator_call(name, args)
        return {'type': 'operator', 'operator': name, 'args': args}
    raise ValueError(f'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: {ast.dump(raw)}')


def _walk(node: dict[str, Any], fields: set[str], operators: set[str]) -> None:
    if node.get('type') == 'field':
        fields.add(node['name'])
        return
    if node.get('type') == 'operator':
        operators.add(node['operator'])
        for arg in node.get('args') or []:
            _walk(arg, fields, operators)


def _failed_formula_ir(formula_text: str, error: str) -> dict[str, Any]:
    payload = {
        'formula_ir_version': FORMULA_IR_VERSION,
        'formula_text': formula_text,
        'formula_hash': stable_hash({'formula_text': formula_text, 'parse_status': 'failed', 'parse_errors': [error]}),
        'root': {},
        'required_fields': [],
        'resolved_fields': {},
        'field_aliases': {},
        'operator_set': [],
        'parse_status': 'failed',
        'parse_errors': [error],
    }
    return payload


def parse_formula(formula_text: str, available_columns: list[str] | None = None, *, raise_on_error: bool = False) -> dict[str, Any]:
    try:
        expr = ast.parse(formula_text, mode='eval')
        root = _node(expr)
    except Exception as exc:
        if raise_on_error:
            raise
        return _failed_formula_ir(formula_text, str(exc))
    fields: set[str] = set()
    operators: set[str] = set()
    _walk(root, fields, operators)
    try:
        resolved = resolve_fields(sorted(fields), available_columns)
        aliases = field_alias_payload(sorted(fields))
    except Exception as exc:
        if raise_on_error:
            raise
        return _failed_formula_ir(formula_text, str(exc))
    payload = {
        'formula_ir_version': FORMULA_IR_VERSION,
        'formula_text': formula_text,
        'root': root,
        'required_fields': sorted(fields),
        'resolved_fields': resolved,
        'field_aliases': aliases,
        'operator_set': sorted(operators),
        'parse_status': 'success',
        'parse_errors': [],
    }
    payload['formula_hash'] = stable_hash({
        'formula_ir_version': payload['formula_ir_version'],
        'formula_text': payload['formula_text'],
        'root': payload['root'],
        'required_fields': payload['required_fields'],
        'operator_set': payload['operator_set'],
    })
    return payload


def resolve_formula_fields_for_schema(formula_ir: dict[str, Any], available_columns: list[str]) -> dict[str, Any]:
    if formula_ir.get('parse_status') != 'success':
        raise ValueError('BLOCK_UNSUPPORTED_FORMULA_SYNTAX: formula_ir parse_status is not success')
    required = formula_ir.get('required_fields') or []
    resolved = resolve_fields(required, available_columns)
    out = dict(formula_ir)
    out['resolved_fields'] = resolved
    out['field_aliases'] = field_alias_payload(required)

    def update_node(node: dict[str, Any]) -> dict[str, Any]:
        copied = dict(node)
        if copied.get('type') == 'field':
            copied['resolved_field'] = resolved[copied['name']]
        elif copied.get('type') == 'operator':
            copied['args'] = [update_node(arg) for arg in copied.get('args') or []]
        return copied

    out['root'] = update_node(out['root'])
    return out
