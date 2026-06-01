#!/usr/bin/env python3
import argparse, ast, hashlib, importlib.util, inspect, json, re
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
CODE = FF / 'generated_code'
RUNS = FF / 'runs'


def _contract_excepthook(exc_type, exc, tb):
    if issubclass(exc_type, AssertionError):
        print(f'CONTRACT_FAILURE: {exc}', file=sys.stderr)
        return
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _contract_excepthook

from factor_factory.artifact_identity import assert_identity_matches_strict, stable_hash
from factor_factory.factor_families.registry import validate_family_plugin_artifacts
from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.parity import compare_outputs, make_operator_fixture, run_operator_parity
from factor_factory.formula.registry import operator_meta
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

FORBIDDEN_DIRECT_CODE_PATTERNS = [
    r"shift\s*\(\s*-\d+",
    r"\bfuture_return\b",
    r"\bnext_return\b",
    r"\bforward_return\b",
    r"\blabel\b",
    r"\btarget\b",
    r"\by_true\b",
    r"\bfuture_",
    r"\blead\s*\(",
    r"\blookahead\b",
]
MODE_DECISION_VERSION = 'factorforge_implementation_mode_decision_v1'
HYBRID_CONTRACT_VERSION = 'factorforge_hybrid_contract_v1'
HIGH_SPEED_CODE_PROFILE_VERSION = 'factorforge_high_speed_code_profile_v1'
DEFAULT_OPERATOR_SCHEMA_COLUMNS = [
    'ts_code',
    'trade_date',
    'open',
    'high',
    'low',
    'close',
    'volume',
    'vol',
    'amount',
    'pct_chg',
    'returns',
    'return',
]
HIGH_SPEED_PREFERRED_BACKENDS = ['numpy', 'polars']
HIGH_SPEED_AVOID_BY_DEFAULT = [
    'python_row_loops',
    'pandas_groupby_iteration',
    'pandas_groupby_apply',
    'pandas_row_apply',
    'nested_python_for_loop',
    'sort_values_inside_loop',
    'list_append_inside_loop',
]
LARGE_STEP3B_FIRST_RUN_ROWS = 50_000
MIN_LARGE_STEP3B_COMPUTE_ROWS_PER_SECOND = 5_000.0


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    global FF, OBJ, CODE, RUNS
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    OBJ = FF / 'objects'
    CODE = FF / 'generated_code'
    RUNS = FF / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    return manifest, manifest_report_id(manifest)


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def resolve_path(raw: str | Path | None, *, code_dir: Path | None = None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    candidates = []
    if code_dir:
        candidates.append(code_dir / path)
    candidates.extend([FF / path, FF.parent / path, REPO_ROOT / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else path


def nested_path(data: dict | None, *keys: str) -> Path | None:
    current = data or {}
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return Path(current).expanduser() if current else None


def _add_schema_value(columns: set[str], value) -> None:
    if not value:
        return
    if isinstance(value, str):
        columns.add(value)
    elif isinstance(value, dict):
        for key in ['name', 'column', 'field', 'actual_column']:
            if value.get(key):
                columns.add(str(value[key]))


def explicit_step3a_schema_columns(prep: dict) -> list[str]:
    columns: set[str] = set()
    for key in ['available_columns', 'clean_data_columns', 'daily_columns', 'daily_df_columns', 'resolved_columns']:
        value = prep.get(key)
        if isinstance(value, list):
            for item in value:
                _add_schema_value(columns, item)
    for key in ['daily_schema', 'schema', 'field_schema']:
        value = prep.get(key)
        if isinstance(value, dict):
            columns.update(str(item) for item in value.keys() if item)
        elif isinstance(value, list):
            for item in value:
                _add_schema_value(columns, item)
    for key in ['field_mappings', 'resolved_fields']:
        value = prep.get(key)
        if isinstance(value, dict):
            columns.update(str(item) for item in value.values() if item)
    return sorted(columns)


def read_snapshot_columns(path: Path) -> list[str]:
    if not path.exists():
        return []
    if path.suffix.lower() == '.parquet':
        try:
            import pyarrow.parquet as pq
            return list(pq.read_schema(path).names)
        except Exception:
            import pandas as pd
            return list(pd.read_parquet(path).head(0).columns)
    import pandas as pd
    return list(pd.read_csv(path, nrows=0).columns)


def local_snapshot_schema_columns(prep: dict) -> list[str]:
    local_inputs = prep.get('local_input_paths') or {}
    raw_paths = [
        local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv'),
        local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv'),
    ]
    columns: set[str] = set()
    for raw in raw_paths:
        path = resolve_path(raw)
        if path and path.exists():
            columns.update(read_snapshot_columns(path))
    return sorted(columns)


def infer_operator_schema(prep: dict) -> dict:
    explicit_columns = explicit_step3a_schema_columns(prep)
    if explicit_columns:
        return {'columns': explicit_columns, 'source': 'step3a_schema', 'strict': True}
    snapshot_columns = local_snapshot_schema_columns(prep)
    if snapshot_columns:
        return {'columns': snapshot_columns, 'source': 'local_snapshot_schema', 'strict': True}
    return {'columns': list(DEFAULT_OPERATOR_SCHEMA_COLUMNS), 'source': 'default_plan_schema', 'strict': False}


def assert_artifact_identity(label: str, data: dict, expected: dict | None = None, role: str | None = None) -> dict:
    identity = data.get('artifact_identity') or ((data.get('metadata') or {}).get('artifact_identity'))
    assert isinstance(identity, dict) and identity, f'{label}.artifact_identity is required'
    for key in ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'spec_hash', 'branch_id', 'artifact_role']:
        assert identity.get(key), f'{label}.artifact_identity.{key} is required'
    if role:
        assert identity.get('artifact_role') == role, (
            f'{label}.artifact_identity.artifact_role mismatch: expected {role}, got {identity.get("artifact_role")}'
        )
    if expected:
        assert_identity_matches_strict(
            expected,
            identity,
            expected_label='expected',
            actual_label=label,
            allowed_role_transitions={(expected.get('artifact_role'), role or identity.get('artifact_role'))},
        )
    return identity


def declared_mode(label: str, data: dict) -> str | None:
    return data.get('implementation_mode') or ((data.get('metadata') or {}).get('implementation_mode'))


def mode_decision_from(label: str, data: dict) -> dict:
    decision = data.get('implementation_mode_decision') or ((data.get('metadata') or {}).get('implementation_mode_decision'))
    assert isinstance(decision, dict) and decision, f'{label}.implementation_mode_decision is required'
    assert decision.get('decision_version') == MODE_DECISION_VERSION, (
        f'{label}.implementation_mode_decision.decision_version must be {MODE_DECISION_VERSION}'
    )
    return decision


def assert_mode_decision_chain(
    spec_identity: dict,
    plan: dict,
    qlib_data: dict,
    hybrid_data: dict,
    handoff: dict,
) -> dict:
    decisions = {
        'implementation_plan_master': mode_decision_from('implementation_plan_master', plan),
        'qlib_expression_draft': mode_decision_from('qlib_expression_draft', qlib_data),
        'qlib_expression_draft.metadata': mode_decision_from('qlib_expression_draft.metadata', {'metadata': qlib_data.get('metadata') or {}}),
        'hybrid_execution_scaffold': mode_decision_from('hybrid_execution_scaffold', hybrid_data),
        'hybrid_execution_scaffold.metadata': mode_decision_from('hybrid_execution_scaffold.metadata', {'metadata': hybrid_data.get('metadata') or {}}),
        'handoff_to_step4': mode_decision_from('handoff_to_step4', handoff),
    }
    base = decisions['implementation_plan_master']
    for label, decision in decisions.items():
        assert decision.get('selected_mode') == base.get('selected_mode'), (
            f'{label}.implementation_mode_decision.selected_mode mismatch: '
            f'{decision.get("selected_mode")} != {base.get("selected_mode")}'
        )
        assert decision.get('final_decision_reason') == base.get('final_decision_reason'), (
            f'{label}.implementation_mode_decision.final_decision_reason mismatch'
        )

    selected = base.get('selected_mode')
    formal_mode = spec_identity.get('implementation_mode')
    assert selected in {'operator', 'hybrid', 'direct_code', 'blocked'}, (
        f'implementation_mode_decision.selected_mode unsupported: {selected}'
    )
    assert selected == formal_mode or selected == 'blocked', (
        f'implementation_mode_decision.selected_mode must match artifact_identity.implementation_mode or blocked: '
        f'{selected} vs {formal_mode}'
    )
    if selected != 'operator':
        assert base.get('operator_attempted') or base.get('operator_failure_reason'), (
            'implementation_mode_decision must record operator attempt or explicit not_applicable reason'
        )
    if selected == 'direct_code':
        assert base.get('operator_failure_reason'), 'direct_code decision requires operator failure/not_applicable reason'
        assert base.get('hybrid_failure_reason'), 'direct_code decision requires hybrid failure/not_applicable reason'
    if selected == 'blocked':
        for label, payload in [('implementation_plan_master', plan), ('handoff_to_step4', handoff)]:
            first_run = payload.get('first_run_outputs') or {}
            assert first_run.get('status') in {'blocked', 'pending', None}, (
                f'{label}.first_run_outputs.status must not be ready/partial when implementation is blocked'
            )
            assert not first_run.get('output_paths'), (
                f'{label}.first_run_outputs.output_paths must be empty when implementation is blocked'
            )
    return base


def collect_declared_operator_code_hashes(plan: dict, qlib_data: dict, hybrid_data: dict, handoff: dict) -> list[tuple[str, str]]:
    sources = [
        ('implementation_plan_master.artifact_identity', plan.get('artifact_identity')),
        ('implementation_plan_master.metadata.artifact_identity', (plan.get('metadata') or {}).get('artifact_identity')),
        ('qlib_expression_draft.artifact_identity', qlib_data.get('artifact_identity')),
        ('qlib_expression_draft.metadata.artifact_identity', (qlib_data.get('metadata') or {}).get('artifact_identity')),
        ('hybrid_execution_scaffold.artifact_identity', hybrid_data.get('artifact_identity')),
        ('hybrid_execution_scaffold.metadata.artifact_identity', (hybrid_data.get('metadata') or {}).get('artifact_identity')),
        ('handoff_to_step4.artifact_identity', handoff.get('artifact_identity')),
        ('handoff_to_step4.metadata.artifact_identity', (handoff.get('metadata') or {}).get('artifact_identity')),
    ]
    hashes = []
    for label, identity in sources:
        if isinstance(identity, dict) and identity.get('code_hash'):
            hashes.append((label, str(identity.get('code_hash'))))
    return hashes


def candidate_operator_code_paths(*, manifest: dict | None, qlib_data: dict, handoff: dict, code_dir: Path, stub: Path, real_impl: Path) -> list[Path]:
    raw_paths = [
        nested_path(manifest, 'step_io', 'step3b', 'outputs', 'factor_impl'),
        nested_path(manifest, 'step_io', 'step3b', 'outputs', 'factor_impl_path'),
        ((qlib_data.get('metadata') or {}).get('implementation_path') if isinstance(qlib_data, dict) else None),
        handoff.get('factor_impl_ref'),
        handoff.get('factor_impl_stub_ref'),
        handoff.get('implementation_path'),
        real_impl,
        stub,
    ]
    paths: list[Path] = []
    for raw in raw_paths:
        path = raw if isinstance(raw, Path) else resolve_path(raw, code_dir=code_dir)
        if path and path not in paths:
            paths.append(path)
    return paths


def validate_operator_mode(
    spec: dict,
    plan: dict,
    qlib_data: dict,
    hybrid_data: dict,
    *,
    manifest: dict | None,
    handoff: dict,
    code_dir: Path,
    stub: Path,
    real_impl: Path,
    prep: dict,
) -> None:
    canonical = spec.get('canonical_spec') or {}
    identity = spec.get('artifact_identity') or {}
    formula_ir = qlib_data.get('formula_ir') if isinstance(qlib_data.get('formula_ir'), dict) else canonical.get('formula_ir')
    assert isinstance(formula_ir, dict) and formula_ir, 'BLOCK_UNSUPPORTED_OPERATOR_PARITY: operator mode requires formula_ir before Step3B can PASS'
    assert formula_ir.get('parse_status') == 'success', (
        f"BLOCK_UNSUPPORTED_FORMULA_SYNTAX: {formula_ir.get('parse_errors') or 'formula_ir parse_status is not success'}"
    )
    assert identity.get('formula_hash'), 'operator mode requires formula_hash'
    assert identity.get('formula_hash') == formula_ir.get('formula_hash'), 'operator formula_hash mismatch between identity and formula_ir'
    operator_set = formula_ir.get('operator_set') or canonical.get('operator_set') or canonical.get('operators')
    required_fields = formula_ir.get('required_fields') or canonical.get('required_fields') or canonical.get('required_inputs')
    resolved_fields = formula_ir.get('resolved_fields') or canonical.get('resolved_fields')
    assert operator_set, 'operator mode requires operator_set/operators'
    assert required_fields, 'operator mode requires required_fields/required_inputs'
    assert resolved_fields, 'operator mode requires resolved_fields'
    operator_schema = infer_operator_schema(prep)
    if operator_schema.get('strict'):
        available = {str(col).lower() for col in operator_schema.get('columns') or []}
        missing = [
            {'field': field, 'resolved_field': resolved}
            for field, resolved in resolved_fields.items()
            if str(resolved).lower() not in available
        ]
        assert not missing, f'BLOCK_MISSING_FIELD_ALIAS: resolved_fields not present in {operator_schema.get("source")}: {missing}'
    for operator in operator_set:
        meta = operator_meta(str(operator))
        assert meta.get('supports_pandas') is True, f'BLOCK_UNSUPPORTED_PANDAS_OPERATOR: {operator}'
    source = (qlib_data.get('metadata') or {}).get('implementation_source') or qlib_data.get('implementation_source')
    assert source == 'formula_ir_pandas_codegen', 'operator generated metadata.implementation_source must be formula_ir_pandas_codegen'
    metadata = qlib_data.get('metadata') or {}
    assert metadata.get('formula_hash') == formula_ir.get('formula_hash'), 'operator generated metadata.formula_hash mismatch'
    assert set(metadata.get('operator_set') or []) == set(operator_set), 'operator generated metadata.operator_set mismatch'
    candidates = candidate_operator_code_paths(
        manifest=manifest,
        qlib_data=qlib_data,
        handoff=handoff,
        code_dir=code_dir,
        stub=stub,
        real_impl=real_impl,
    )
    implementation_path = next((path for path in candidates if path and path.exists() and path.suffix == '.py'), None)
    assert implementation_path is not None, f'BLOCK_OPERATOR_ARTIFACT_MISSING: checked {[str(p) for p in candidates]}'
    actual_code_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    declared_hashes = collect_declared_operator_code_hashes(plan, qlib_data, hybrid_data, handoff)
    assert declared_hashes, 'BLOCK_OPERATOR_HASH_MISSING: operator generated artifacts require code_hash'
    for label, declared_hash in declared_hashes:
        assert declared_hash == actual_code_hash, (
            f'BLOCK_OPERATOR_HASH_MISMATCH: {label}={declared_hash} '
            f'actual_code_hash={actual_code_hash} path={implementation_path}'
        )
    parity = run_operator_parity(formula_ir, implementation_path)
    assert parity.get('status') == 'PASS', f"BLOCK_OPERATOR_PARITY_FAILED: {parity}"


def candidate_direct_code_paths(
    *,
    manifest: dict | None,
    qlib_data: dict,
    hybrid_data: dict,
    handoff: dict,
    code_dir: Path,
    stub: Path,
    real_impl: Path,
) -> list[Path]:
    raw_paths = [
        nested_path(manifest, 'step_io', 'step3b', 'outputs', 'factor_impl'),
        nested_path(manifest, 'step_io', 'step3b', 'outputs', 'factor_impl_path'),
        nested_path(manifest, 'step_io', 'step3b', 'outputs', 'python_implementation'),
        ((qlib_data.get('metadata') or {}).get('implementation_path') if isinstance(qlib_data, dict) else None),
        ((hybrid_data.get('metadata') or {}).get('implementation_path') if isinstance(hybrid_data, dict) else None),
        handoff.get('factor_impl_ref'),
        handoff.get('factor_impl_stub_ref'),
        handoff.get('implementation_path'),
        real_impl,
        stub,
    ]
    paths: list[Path] = []
    for raw in raw_paths:
        path = raw if isinstance(raw, Path) else resolve_path(raw, code_dir=code_dir)
        if path and path not in paths:
            paths.append(path)
    return paths


def scan_direct_code_text(text: str, extra_patterns: list[str]) -> None:
    patterns = list(dict.fromkeys(FORBIDDEN_DIRECT_CODE_PATTERNS + [str(p) for p in extra_patterns if p]))
    hits = []
    for pattern in patterns:
        try:
            regex = re.compile(pattern, flags=re.IGNORECASE)
        except re.error as exc:
            raise AssertionError(
                f'BLOCK_DIRECT_CODE_INVALID_FORBIDDEN_PATTERN: pattern={pattern!r}, error={exc}'
            ) from exc
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith('#'):
                continue
            if regex.search(line):
                hits.append({'pattern': pattern, 'line': lineno, 'text': line.strip()[:180]})
    if hits:
        raise AssertionError(f'BLOCK_DIRECT_CODE_LEAKAGE_PATTERN: {hits}')


def collect_declared_direct_code_hashes(
    spec: dict,
    plan: dict,
    qlib_data: dict,
    hybrid_data: dict,
    handoff: dict,
) -> list[tuple[str, str]]:
    identity_sources = [
        ('factor_spec_master.artifact_identity', spec.get('artifact_identity')),
        ('factor_spec_master.metadata.artifact_identity', (spec.get('metadata') or {}).get('artifact_identity')),
        ('implementation_plan_master.artifact_identity', plan.get('artifact_identity')),
        ('implementation_plan_master.metadata.artifact_identity', (plan.get('metadata') or {}).get('artifact_identity')),
        ('qlib_expression_draft.artifact_identity', qlib_data.get('artifact_identity')),
        ('qlib_expression_draft.metadata.artifact_identity', (qlib_data.get('metadata') or {}).get('artifact_identity')),
        ('hybrid_execution_scaffold.artifact_identity', hybrid_data.get('artifact_identity')),
        ('hybrid_execution_scaffold.metadata.artifact_identity', (hybrid_data.get('metadata') or {}).get('artifact_identity')),
        ('handoff_to_step4.artifact_identity', handoff.get('artifact_identity')),
        ('handoff_to_step4.metadata.artifact_identity', (handoff.get('metadata') or {}).get('artifact_identity')),
    ]
    metadata_sources = [
        ('factor_spec_master.code_hash', spec),
        ('factor_spec_master.metadata.code_hash', spec.get('metadata') or {}),
        ('implementation_plan_master.code_hash', plan),
        ('implementation_plan_master.metadata.code_hash', plan.get('metadata') or {}),
        ('qlib_expression_draft.code_hash', qlib_data),
        ('qlib_expression_draft.metadata.code_hash', qlib_data.get('metadata') or {}),
        ('hybrid_execution_scaffold.code_hash', hybrid_data),
        ('hybrid_execution_scaffold.metadata.code_hash', hybrid_data.get('metadata') or {}),
        ('handoff_to_step4.code_hash', handoff),
        ('handoff_to_step4.metadata.code_hash', handoff.get('metadata') or {}),
    ]
    hashes: list[tuple[str, str]] = []
    for label, identity in identity_sources:
        if isinstance(identity, dict) and identity.get('code_hash'):
            hashes.append((label, str(identity.get('code_hash'))))
    for label, data in metadata_sources:
        if isinstance(data, dict) and data.get('code_hash'):
            hashes.append((label, str(data.get('code_hash'))))
    return hashes


def scan_direct_code_ast(text: str) -> None:
    tree = ast.parse(text)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'shift':
            if node.args:
                arg = node.args[0]
                if (
                    isinstance(arg, ast.UnaryOp)
                    and isinstance(arg.op, ast.USub)
                    and isinstance(arg.operand, ast.Constant)
                    and isinstance(arg.operand.value, int)
                ):
                    hits.append({'pattern': 'ast.shift_negative', 'line': getattr(node, 'lineno', None)})
        if isinstance(node, ast.Subscript):
            key = None
            raw_slice = node.slice
            if isinstance(raw_slice, ast.Constant) and isinstance(raw_slice.value, str):
                key = raw_slice.value
            if key and re.search(r'(future|next|label|target|y_true|lookahead)', key, flags=re.IGNORECASE):
                hits.append({'pattern': 'ast.suspicious_column', 'line': getattr(node, 'lineno', None), 'column': key})
    if hits:
        raise AssertionError(f'BLOCK_DIRECT_CODE_LEAKAGE_PATTERN: {hits}')


def _attribute_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _call_has_keyword_value(node: ast.Call, keyword_name: str, expected: object) -> bool:
    for keyword in node.keywords or []:
        if keyword.arg != keyword_name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and value.value == expected:
            return True
    return False


def _is_groupby_apply_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != 'apply':
        return False
    return _receiver_chain_contains_call(node.func.value, 'groupby')


def _is_rolling_apply_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != 'apply':
        return False
    return _receiver_chain_contains_call(node.func.value, 'rolling')


def _receiver_chain_contains_call(node: ast.AST, call_attr: str) -> bool:
    current = node
    while True:
        if isinstance(current, ast.Subscript):
            current = current.value
            continue
        if isinstance(current, ast.Attribute):
            current = current.value
            continue
        if isinstance(current, ast.Call):
            func = current.func
            if isinstance(func, ast.Attribute) and func.attr == call_attr:
                return True
            if isinstance(func, ast.Attribute):
                current = func.value
                continue
        return False


def _call_uses_name(node: ast.Call, names: set[str]) -> bool:
    chain = _attribute_chain(node.func)
    return bool(chain and chain[0] in names)


def _is_groupby_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'groupby'
    )


def _for_iter_uses_groupby(node: ast.For, groupby_iterable_names: set[str]) -> bool:
    iter_node = node.iter
    if isinstance(iter_node, ast.Name) and iter_node.id in groupby_iterable_names:
        return True
    if _is_groupby_call(iter_node):
        return True
    if isinstance(iter_node, ast.Call) and isinstance(iter_node.func, ast.Name) and iter_node.func.id in {'iter', 'enumerate'}:
        return bool(iter_node.args and _for_iter_uses_groupby(ast.For(target=node.target, iter=iter_node.args[0], body=[], orelse=[]), groupby_iterable_names))
    return False


def _contains_call_attr(node: ast.AST, attrs: set[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr in attrs:
            return True
    return False


def _contains_list_append(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == 'append':
            return True
    return False


def build_high_speed_code_profile(text: str) -> dict:
    tree = ast.parse(text)
    import_aliases: dict[str, str] = {}
    slow_patterns: list[dict] = []
    vectorized_markers: list[dict] = []
    uses_pandas_vectorized = False
    groupby_iterable_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split('.')[0]
                import_aliases[alias.asname or root] = root
        elif isinstance(node, ast.ImportFrom):
            module_root = (node.module or '').split('.')[0]
            for alias in node.names:
                import_aliases[alias.asname or alias.name] = module_root
        elif isinstance(node, ast.Assign):
            if _is_groupby_call(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        groupby_iterable_names.add(target.id)

    numpy_names = {name for name, root in import_aliases.items() if root == 'numpy'}
    polars_names = {name for name, root in import_aliases.items() if root == 'polars'}
    pandas_names = {name for name, root in import_aliases.items() if root == 'pandas'}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr in {'iterrows', 'itertuples'}:
                    slow_patterns.append({'code': attr, 'line': getattr(node, 'lineno', None)})
                elif attr == 'apply' and _call_has_keyword_value(node, 'axis', 1):
                    slow_patterns.append({'code': 'pandas_apply_axis1', 'line': getattr(node, 'lineno', None)})
                elif _is_groupby_apply_call(node):
                    slow_patterns.append({'code': 'pandas_groupby_apply', 'line': getattr(node, 'lineno', None)})
                elif _is_rolling_apply_call(node):
                    slow_patterns.append({'code': 'pandas_rolling_apply', 'line': getattr(node, 'lineno', None)})
                elif attr in {'to_numpy', 'rank', 'shift', 'diff', 'rolling', 'transform', 'where', 'clip', 'fillna', 'assign', 'merge'}:
                    uses_pandas_vectorized = True
                    vectorized_markers.append({'code': f'pandas_{attr}', 'line': getattr(node, 'lineno', None)})
            if _call_uses_name(node, numpy_names):
                vectorized_markers.append({'code': 'numpy_call', 'line': getattr(node, 'lineno', None)})
            if _call_uses_name(node, polars_names):
                vectorized_markers.append({'code': 'polars_call', 'line': getattr(node, 'lineno', None)})
            if isinstance(node.func, ast.Name) and node.func.id == 'range' and node.args:
                first = node.args[0]
                if isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == 'len':
                    slow_patterns.append({'code': 'range_len_loop', 'line': getattr(node, 'lineno', None)})
        elif isinstance(node, ast.For):
            nested_for = any(isinstance(child, ast.For) for stmt in node.body for child in ast.walk(stmt))
            if _for_iter_uses_groupby(node, groupby_iterable_names):
                slow_patterns.append({'code': 'pandas_groupby_iteration', 'line': getattr(node, 'lineno', None)})
            if nested_for:
                slow_patterns.append({'code': 'nested_python_for_loop', 'line': getattr(node, 'lineno', None)})
            if _contains_call_attr(node, {'sort_values'}):
                slow_patterns.append({'code': 'sort_values_inside_loop', 'line': getattr(node, 'lineno', None)})
            if _contains_list_append(node):
                slow_patterns.append({'code': 'list_append_inside_loop', 'line': getattr(node, 'lineno', None)})
    deduped_slow_patterns: list[dict] = []
    seen_slow: set[tuple[str, int | None]] = set()
    for item in slow_patterns:
        key = (str(item.get('code')), item.get('line'))
        if key not in seen_slow:
            seen_slow.add(key)
            deduped_slow_patterns.append(item)

    uses_numpy = bool(numpy_names)
    uses_polars = bool(polars_names)
    uses_pandas = bool(pandas_names) or 'pd' in import_aliases
    vectorized_backend_present = bool(uses_numpy or uses_polars or uses_pandas_vectorized or vectorized_markers)
    return {
        'version': HIGH_SPEED_CODE_PROFILE_VERSION,
        'preferred_backends': HIGH_SPEED_PREFERRED_BACKENDS,
        'avoid_by_default': HIGH_SPEED_AVOID_BY_DEFAULT,
        'uses_numpy': uses_numpy,
        'uses_polars': uses_polars,
        'uses_pandas': uses_pandas,
        'uses_pandas_vectorized': bool(uses_pandas_vectorized),
        'vectorized_backend_present': vectorized_backend_present,
        'vectorized_markers': vectorized_markers[:20],
        'slow_patterns': deduped_slow_patterns,
        'requires_justification': bool(deduped_slow_patterns),
    }


def assert_high_speed_code_policy(text: str, contract: dict | None = None) -> dict:
    profile = build_high_speed_code_profile(text)
    contract = contract if isinstance(contract, dict) else {}
    policy = contract.get('high_speed_code_policy') if isinstance(contract.get('high_speed_code_policy'), dict) else {}
    justification = (
        contract.get('performance_justification')
        or contract.get('slow_pattern_justification')
        or policy.get('performance_justification')
        or policy.get('slow_pattern_justification')
    )
    allow_slow = bool(contract.get('allow_slow_patterns') is True or policy.get('allow_slow_patterns') is True)
    if profile.get('requires_justification') and not (allow_slow and str(justification or '').strip()):
        raise AssertionError(f'BLOCK_DIRECT_CODE_PERFORMANCE_RISK: {profile}')
    return profile


def assert_step3b_runtime_performance_policy(run_metadata: dict) -> dict:
    profile = run_metadata.get('performance_profile') if isinstance(run_metadata.get('performance_profile'), dict) else {}
    row_count = int(profile.get('row_count') or run_metadata.get('row_count') or 0)
    input_row_count = int(profile.get('input_row_count') or 0)
    phase_seconds = profile.get('phase_seconds') if isinstance(profile.get('phase_seconds'), dict) else {}
    compute_seconds = phase_seconds.get('compute_factor')
    rows_per_second = profile.get('rows_per_second_compute')
    rows_per_second_input = profile.get('rows_per_second_input_compute')
    if rows_per_second_input is None and input_row_count > 0 and compute_seconds:
        try:
            rows_per_second_input = float(input_row_count) / float(compute_seconds)
        except (TypeError, ValueError, ZeroDivisionError):
            rows_per_second_input = None
    policy = profile.get('runtime_performance_policy') if isinstance(profile.get('runtime_performance_policy'), dict) else {}
    allow_slow = bool(profile.get('allow_slow_runtime') is True or policy.get('allow_slow_runtime') is True)
    justification = (
        profile.get('performance_justification')
        or profile.get('slow_runtime_justification')
        or policy.get('performance_justification')
        or policy.get('slow_runtime_justification')
    )
    throughput_basis = 'input_rows' if input_row_count >= row_count and input_row_count > 0 else 'output_rows'
    gate_row_count = input_row_count if throughput_basis == 'input_rows' else row_count
    result = {
        'version': 'factorforge_step3b_runtime_performance_policy_v1',
        'large_row_threshold': LARGE_STEP3B_FIRST_RUN_ROWS,
        'min_large_compute_rows_per_second': MIN_LARGE_STEP3B_COMPUTE_ROWS_PER_SECOND,
        'row_count': row_count,
        'input_row_count': input_row_count,
        'compute_factor_seconds': compute_seconds,
        'rows_per_second_compute': rows_per_second,
        'rows_per_second_input_compute': rows_per_second_input,
        'throughput_basis': throughput_basis,
        'gate_row_count': gate_row_count,
        'rows_per_second_for_gate': rows_per_second_input if throughput_basis == 'input_rows' else rows_per_second,
        'large_first_run': gate_row_count >= LARGE_STEP3B_FIRST_RUN_ROWS,
        'allow_slow_runtime': allow_slow,
        'has_justification': bool(str(justification or '').strip()),
    }
    if gate_row_count >= LARGE_STEP3B_FIRST_RUN_ROWS:
        rows_per_second_for_gate = result.get('rows_per_second_for_gate')
        if rows_per_second_for_gate is None:
            field = 'rows_per_second_input_compute' if result.get('throughput_basis') == 'input_rows' else 'rows_per_second_compute'
            raise AssertionError(f'BLOCK_STEP3B_RUNTIME_PERFORMANCE_RISK: missing {field}: {result}')
        try:
            rps = float(rows_per_second_for_gate)
        except (TypeError, ValueError) as exc:
            field = 'rows_per_second_input_compute' if result.get('throughput_basis') == 'input_rows' else 'rows_per_second_compute'
            raise AssertionError(f'BLOCK_STEP3B_RUNTIME_PERFORMANCE_RISK: invalid {field}: {result}') from exc
        result['rows_per_second_for_gate'] = rps
        if rps < MIN_LARGE_STEP3B_COMPUTE_ROWS_PER_SECOND and not (allow_slow and str(justification or '').strip()):
            raise AssertionError(f'BLOCK_STEP3B_RUNTIME_PERFORMANCE_RISK: {result}')
    return result


def import_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot import generated direct_code artifact: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_direct_code_alias_columns(df):
    out = df.copy()
    if 'vol' in out.columns and 'volume' not in out.columns:
        out['volume'] = out['vol']
    if 'volume' in out.columns and 'vol' not in out.columns:
        out['vol'] = out['volume']
    if 'trade_time' in out.columns and 'datetime' not in out.columns:
        out['datetime'] = out['trade_time']
    if 'datetime' in out.columns and 'trade_time' not in out.columns:
        out['trade_time'] = out['datetime']
    return out


def direct_code_expects_polars(module) -> bool:
    path = Path(getattr(module, '__file__', '') or '')
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        text = ''
    polars_api_markers = [
        '.with_columns(',
        '.select(',
        '.lazy(',
        'pl.col(',
        'polars.col(',
    ]
    return any(marker in text for marker in polars_api_markers)


def maybe_polars_frame(df, use_polars: bool):
    if not use_polars:
        return df
    try:
        import polars as pl
    except ImportError as exc:
        raise AssertionError(f'BLOCK_DIRECT_CODE_FIXTURE_SMOKE_FAILED: polars dependency missing: {exc}') from exc
    return pl.from_pandas(df)


def normalize_direct_code_result(result):
    import pandas as pd

    if isinstance(result, pd.DataFrame):
        return result
    if hasattr(result, 'to_pandas') and callable(result.to_pandas):
        return result.to_pandas()
    if hasattr(result, 'to_dicts') and callable(result.to_dicts):
        return pd.DataFrame(result.to_dicts())
    return result


def run_direct_code_fixture_smoke(path: Path, output_schema: dict) -> None:
    import pandas as pd

    module = import_module_from_path(path)
    compute = getattr(module, 'compute_factor', None)
    if compute is None or not callable(compute):
        raise AssertionError('BLOCK_DIRECT_CODE_FIXTURE_SMOKE_FAILED: compute_factor missing')
    dates = [f'202601{day:02d}' for day in range(1, 12)]
    daily_rows = []
    minute_rows = []
    for stock_index, ts_code in enumerate(['000001.SZ', '000002.SZ']):
        base = 10.0 + stock_index * 10.0
        for day_index, trade_date in enumerate(dates):
            close = base + day_index * 0.05
            daily_rows.append({
                'ts_code': ts_code,
                'trade_date': trade_date,
                'open': close - 0.1,
                'close': close,
                'high': close + 0.2,
                'low': close - 0.2,
                'vol': 1000.0 + day_index * 10.0,
                'pct_chg': 0.1,
            })
            for minute_index, minute in enumerate(['09:30:00', '09:31:00', '09:32:00']):
                minute_close = close + (minute_index - 1) * 0.03
                volume = 1000.0 + stock_index * 500.0 + day_index * 20.0 + minute_index * 50.0
                minute_rows.append({
                    'ts_code': ts_code,
                    'trade_date': trade_date,
                    'trade_time': f'{trade_date} {minute}',
                    'close': minute_close,
                    'vol': volume,
                    'amount': minute_close * volume,
                })
    daily_df = add_direct_code_alias_columns(pd.DataFrame(daily_rows))
    minute_df = add_direct_code_alias_columns(pd.DataFrame(minute_rows))
    use_polars = direct_code_expects_polars(module)
    daily_input = maybe_polars_frame(daily_df, use_polars)
    minute_input = maybe_polars_frame(minute_df, use_polars)
    try:
        signature = inspect.signature(compute)
        params = list(signature.parameters.values())
    except (TypeError, ValueError) as exc:
        raise AssertionError(f'BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH: cannot inspect compute_factor signature: {exc}') from exc
    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    accepts_daily_keyword = (
        accepts_kwargs
        or 'daily_df' in signature.parameters
        or any(p.name == 'daily_df' and p.kind != inspect.Parameter.POSITIONAL_ONLY for p in params)
    )
    if not accepts_daily_keyword:
        raise AssertionError(
            'BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH: compute_factor must accept keyword argument daily_df'
        )
    try:
        result = compute(daily_df=daily_input, minute_df=minute_input)
    except TypeError as exc:
        raise AssertionError(
            f'BLOCK_STEP3B_DIRECT_CODE_SIGNATURE_MISMATCH: compute_factor keyword call failed: {exc}'
        ) from exc
    result = normalize_direct_code_result(result)
    if not isinstance(result, pd.DataFrame):
        raise AssertionError('BLOCK_DIRECT_CODE_FIXTURE_SMOKE_FAILED: compute_factor must return DataFrame')
    if len(result) <= 0:
        raise AssertionError('BLOCK_DIRECT_CODE_FIXTURE_SMOKE_FAILED: output row count must be positive')
    required = {'ts_code', 'trade_date'}
    missing = required - set(result.columns)
    if missing:
        raise AssertionError(f'BLOCK_DIRECT_CODE_FIXTURE_SMOKE_FAILED: output missing columns {sorted(missing)}')
    declared = output_schema.get('columns') if isinstance(output_schema, dict) else None
    signal_candidates = [col for col in (declared or []) if col not in {'ts_code', 'trade_date'}]
    signal_candidates.extend(['factor_value', 'signal'])
    if not any(col in result.columns for col in signal_candidates):
        raise AssertionError('BLOCK_DIRECT_CODE_FIXTURE_SMOKE_FAILED: output missing factor_value or declared signal column')
    signal_column = next((col for col in signal_candidates if col in result.columns), None)
    if signal_column and result[signal_column].isna().all():
        raise AssertionError(
            f'BLOCK_STEP3B_DIRECT_CODE_ALL_NULL_OUTPUT: output signal column {signal_column} is entirely null'
        )


def validate_direct_code_mode(
    spec: dict,
    plan: dict,
    qlib_data: dict,
    hybrid_data: dict,
    *,
    manifest: dict | None,
    handoff: dict,
    code_dir: Path,
    stub: Path,
    real_impl: Path,
) -> None:
    contract = spec.get('implementation_contract') or {}
    identity = spec.get('artifact_identity') or {}
    assert contract.get('code_contract'), 'BLOCK_UNSUPPORTED_DIRECT_CODE_VALIDATION: direct_code requires code_contract'
    assert identity.get('code_hash') or identity.get('code_contract_hash'), 'direct_code requires code_hash or code_contract_hash'
    output_schema = plan.get('output_schema') or contract.get('output_schema') or {}
    assert output_schema, 'direct_code requires declared output schema'
    candidates = candidate_direct_code_paths(
        manifest=manifest,
        qlib_data=qlib_data,
        hybrid_data=hybrid_data,
        handoff=handoff,
        code_dir=code_dir,
        stub=stub,
        real_impl=real_impl,
    )
    implementation_path = next((path for path in candidates if path and path.exists() and path.suffix == '.py'), None)
    assert implementation_path is not None, f'BLOCK_DIRECT_CODE_ARTIFACT_MISSING: checked {[str(p) for p in candidates]}'
    actual_code_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    declared_hashes = collect_declared_direct_code_hashes(spec, plan, qlib_data, hybrid_data, handoff)
    if not declared_hashes:
        raise AssertionError('BLOCK_DIRECT_CODE_HASH_MISSING: direct_code formal artifact requires code_hash')
    for label, declared_hash in declared_hashes:
        if declared_hash != actual_code_hash:
            raise AssertionError(
                f'BLOCK_DIRECT_CODE_HASH_MISMATCH: {label}={declared_hash} '
                f'actual_code_hash={actual_code_hash} path={implementation_path}'
            )

    text = implementation_path.read_text(encoding='utf-8')
    code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    extra_patterns = list(code_contract.get('forbidden_patterns') or contract.get('forbidden_patterns') or [])
    scan_direct_code_text(text, extra_patterns)
    scan_direct_code_ast(text)
    assert_high_speed_code_policy(text, code_contract or contract)
    run_direct_code_fixture_smoke(implementation_path, output_schema)


def custom_block_source(block: dict) -> str:
    return str(block.get('source_code') or block.get('code') or block.get('custom_source') or '')


def custom_block_hash(block: dict) -> str:
    source = custom_block_source(block)
    normalized = dict(block)
    normalized['source_code'] = source
    normalized.pop('custom_block_hash', None)
    return stable_hash({'source_code': source, 'contract': normalized})


def assert_hybrid_custom_source_safe(block: dict) -> None:
    source = custom_block_source(block)
    if not source.strip():
        raise AssertionError('BLOCK_INVALID_HYBRID_CONTRACT: custom block source_code missing')
    patterns = list(dict.fromkeys(FORBIDDEN_DIRECT_CODE_PATTERNS + [str(p) for p in (block.get('forbidden_patterns') or []) if p]))
    hits = []
    for pattern in patterns:
        try:
            regex = re.compile(pattern, flags=re.IGNORECASE)
        except re.error as exc:
            raise AssertionError(f'BLOCK_HYBRID_CUSTOM_BLOCK_INVALID_FORBIDDEN_PATTERN: pattern={pattern!r}, error={exc}') from exc
        for lineno, line in enumerate(source.splitlines(), start=1):
            if regex.search(line):
                hits.append({'pattern': pattern, 'line': lineno, 'text': line.strip()[:180]})
    if hits:
        raise AssertionError(f'BLOCK_HYBRID_CUSTOM_BLOCK_LEAKAGE_PATTERN: {hits}')
    try:
        scan_direct_code_ast(source)
    except AssertionError as exc:
        raise AssertionError(f'BLOCK_HYBRID_CUSTOM_BLOCK_LEAKAGE_PATTERN: {exc}') from exc
    try:
        assert_high_speed_code_policy(source, block)
    except AssertionError as exc:
        raise AssertionError(f'BLOCK_HYBRID_CUSTOM_BLOCK_PERFORMANCE_RISK: {exc}') from exc


def assert_hybrid_boundary(boundary: dict, custom_blocks: list[dict]) -> None:
    assert isinstance(boundary, dict) and boundary, 'BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING'
    operator_outputs = set(boundary.get('operator_outputs') or [])
    custom_inputs = set(boundary.get('custom_inputs') or [])
    custom_outputs = set(boundary.get('custom_outputs') or [])
    assert operator_outputs, 'BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: operator_outputs missing'
    assert operator_outputs.issubset(custom_inputs), 'BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: custom_inputs must include operator_outputs'
    assert 'factor_value' in custom_outputs, 'BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: custom_outputs must include factor_value'
    if boundary.get('allow_operator_output_overwrite') is True:
        return
    protected = set(boundary.get('protected_operator_outputs') or operator_outputs)
    for block in custom_blocks:
        source = custom_block_source(block)
        for name in protected:
            patterns = [
                rf'\[[^\\n\\]]*["\\\']{re.escape(name)}["\\\'][^\\n\\]]*\]\s*=',
                rf'\.loc\[[^\\n]*["\\\']{re.escape(name)}["\\\'][^\\n]*\]\s*=',
                rf'\.assign\([^\\n)]*{re.escape(name)}\s*=',
            ]
            if any(re.search(pattern, source) for pattern in patterns):
                raise AssertionError(f'BLOCK_HYBRID_OPERATOR_OUTPUT_OVERWRITE: {name}')


def candidate_hybrid_code_path(handoff: dict, code_dir: Path, stub: Path, real_impl: Path) -> Path | None:
    for raw in [handoff.get('factor_impl_ref'), handoff.get('factor_impl_stub_ref'), real_impl, stub]:
        path = raw if isinstance(raw, Path) else resolve_path(raw, code_dir=code_dir)
        if path and path.exists() and path.suffix == '.py':
            return path
    return None


def validate_hybrid_mode(
    spec: dict,
    plan: dict,
    qlib_data: dict,
    hybrid_data: dict,
    *,
    handoff: dict,
    code_dir: Path,
    stub: Path,
    real_impl: Path,
    prep: dict,
) -> None:
    identity = spec.get('artifact_identity') or {}
    contract = spec.get('implementation_contract') or {}
    assert contract.get('hybrid_contract_version') == HYBRID_CONTRACT_VERSION, (
        f'BLOCK_INVALID_HYBRID_CONTRACT: hybrid_contract_version must be {HYBRID_CONTRACT_VERSION}'
    )
    operator_subgraph = contract.get('operator_subgraph') or {}
    formula_ir = operator_subgraph.get('formula_ir') if isinstance(operator_subgraph.get('formula_ir'), dict) else {}
    custom_blocks = contract.get('custom_blocks') or []
    boundary = contract.get('boundary') or {}
    assert formula_ir, 'BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph.formula_ir missing'
    assert formula_ir.get('parse_status') == 'success', f"BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph formula_ir parse failed {formula_ir.get('parse_errors')}"
    assert isinstance(custom_blocks, list) and custom_blocks, 'BLOCK_INVALID_HYBRID_CONTRACT: custom_blocks missing'
    assert_hybrid_boundary(boundary, custom_blocks)
    for key in ['formula_hash', 'custom_block_hash', 'hybrid_hash']:
        assert identity.get(key) and contract.get(key), f'BLOCK_INVALID_HYBRID_CONTRACT: {key} missing'
        assert identity.get(key) == contract.get(key), f'BLOCK_HYBRID_HASH_MISMATCH: identity {key} mismatch'
        assert plan.get(key) == contract.get(key), f'BLOCK_HYBRID_HASH_MISMATCH: implementation_plan {key} mismatch'
        assert hybrid_data.get(key) == contract.get(key), f'BLOCK_HYBRID_HASH_MISMATCH: hybrid_scaffold {key} mismatch'

    operator_schema = infer_operator_schema(prep)
    resolved_fields = formula_ir.get('resolved_fields') or {}
    if operator_schema.get('strict'):
        available = {str(col).lower() for col in operator_schema.get('columns') or []}
        missing = [
            {'field': field, 'resolved_field': resolved}
            for field, resolved in resolved_fields.items()
            if str(resolved).lower() not in available
        ]
        assert not missing, f'BLOCK_MISSING_FIELD_ALIAS: resolved_fields not present in {operator_schema.get("source")}: {missing}'
    for operator in formula_ir.get('operator_set') or []:
        meta = operator_meta(str(operator))
        assert meta.get('supports_pandas') is True, f'BLOCK_UNSUPPORTED_PANDAS_OPERATOR: {operator}'
    assert formula_ir.get('formula_hash') == contract.get('formula_hash'), 'BLOCK_HYBRID_HASH_MISMATCH: formula_hash mismatch'

    block_hash_inputs = []
    for block in custom_blocks:
        assert_hybrid_custom_source_safe(block)
        actual = custom_block_hash(block)
        declared = block.get('custom_block_hash')
        assert declared == actual, f'BLOCK_HYBRID_HASH_MISMATCH: custom block {block.get("name")} hash mismatch'
        block_hash_inputs.append({'name': block.get('name'), 'custom_block_hash': declared})
    actual_custom_hash = stable_hash(block_hash_inputs)
    assert actual_custom_hash == contract.get('custom_block_hash'), 'BLOCK_HYBRID_HASH_MISMATCH: custom_block_hash mismatch'
    actual_hybrid_hash = stable_hash({
        'formula_hash': contract.get('formula_hash'),
        'custom_block_hash': contract.get('custom_block_hash'),
        'boundary': boundary,
    })
    assert actual_hybrid_hash == contract.get('hybrid_hash'), 'BLOCK_HYBRID_HASH_MISMATCH: hybrid_hash mismatch'

    implementation_path = candidate_hybrid_code_path(handoff, code_dir, stub, real_impl)
    assert implementation_path is not None, 'BLOCK_HYBRID_ARTIFACT_MISSING'
    text = implementation_path.read_text(encoding='utf-8')
    assert '<FACTORFORGE_OPERATOR_SUBGRAPH_BEGIN>' in text and '<FACTORFORGE_OPERATOR_SUBGRAPH_END>' in text, 'BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: operator section markers missing'
    assert '<FACTORFORGE_CUSTOM_BLOCK_BEGIN>' in text and '<FACTORFORGE_CUSTOM_BLOCK_END>' in text, 'BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: custom block markers missing'
    actual_code_hash = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    for label, identity_payload in [
        ('implementation_plan_master', plan.get('artifact_identity') or {}),
        ('qlib_expression_draft', qlib_data.get('artifact_identity') or {}),
        ('hybrid_execution_scaffold', hybrid_data.get('artifact_identity') or {}),
        ('handoff_to_step4', handoff.get('artifact_identity') or {}),
    ]:
        assert identity_payload.get('code_hash') == actual_code_hash, f'BLOCK_HYBRID_HASH_MISMATCH: {label}.code_hash mismatch'

    module = import_module_from_path(implementation_path)
    compute_operator = getattr(module, 'compute_operator_subgraph', None)
    compute_factor = getattr(module, 'compute_factor', None)
    assert callable(compute_operator), 'BLOCK_HYBRID_OPERATOR_PARITY_FAILED: compute_operator_subgraph missing'
    assert callable(compute_factor), 'BLOCK_HYBRID_COMBINED_SMOKE_FAILED: compute_factor missing'
    fixture = make_operator_fixture()
    fixture['is_tradable'] = [idx % 2 == 0 for idx in range(len(fixture))]
    fixture['custom_scale'] = 2.0
    fixture['universe_flag'] = [1 if idx % 3 else 0 for idx in range(len(fixture))]
    reference = evaluate_formula_frame(formula_ir, fixture).rename(columns={'factor_value': 'operator_value'})
    generated_operator = compute_operator(fixture.copy())
    if 'operator_value' not in generated_operator.columns:
        raise AssertionError('BLOCK_HYBRID_OPERATOR_PARITY_FAILED: operator output missing operator_value')
    try:
        parity = compare_outputs(
            reference.rename(columns={'operator_value': 'factor_value'}),
            generated_operator.rename(columns={'operator_value': 'factor_value'}),
        )
    except AssertionError as exc:
        detail = str(exc).replace('BLOCK_OPERATOR_PARITY_FAILED:', '').strip()
        raise AssertionError(f'BLOCK_HYBRID_OPERATOR_PARITY_FAILED: {detail}') from exc
    assert parity.get('status') == 'PASS', f'BLOCK_HYBRID_OPERATOR_PARITY_FAILED: {parity}'
    try:
        combined = compute_factor(daily_df=fixture.copy(), minute_df=None)
    except TypeError:
        combined = compute_factor(fixture.copy(), None)
    required = {'ts_code', 'trade_date', 'factor_value'}
    assert hasattr(combined, 'columns'), 'BLOCK_HYBRID_COMBINED_SMOKE_FAILED: output is not DataFrame-like'
    assert len(combined) > 0, 'BLOCK_HYBRID_COMBINED_SMOKE_FAILED: output row count must be positive'
    assert required.issubset(set(combined.columns)), f'BLOCK_HYBRID_COMBINED_SMOKE_FAILED: output missing {sorted(required - set(combined.columns))}'


def validate_mode_specific(
    spec: dict,
    plan: dict,
    qlib_data: dict,
    hybrid_data: dict,
    *,
    manifest: dict | None,
    handoff: dict,
    code_dir: Path,
    stub: Path,
    real_impl: Path,
    prep: dict,
) -> None:
    mode = (spec.get('artifact_identity') or {}).get('implementation_mode')
    if mode == 'operator':
        validate_operator_mode(
            spec,
            plan,
            qlib_data,
            hybrid_data,
            manifest=manifest,
            handoff=handoff,
            code_dir=code_dir,
            stub=stub,
            real_impl=real_impl,
            prep=prep,
        )
    elif mode == 'direct_code':
        validate_direct_code_mode(
            spec,
            plan,
            qlib_data,
            hybrid_data,
            manifest=manifest,
            handoff=handoff,
            code_dir=code_dir,
            stub=stub,
            real_impl=real_impl,
        )
    elif mode == 'hybrid':
        validate_hybrid_mode(
            spec,
            plan,
            qlib_data,
            hybrid_data,
            handoff=handoff,
            code_dir=code_dir,
            stub=stub,
            real_impl=real_impl,
            prep=prep,
        )
    else:
        raise AssertionError(f'BLOCK_UNSUPPORTED_IMPLEMENTATION_MODE: {mode}')


def assert_step2_context(label: str, ctx: dict):
    assert isinstance(ctx, dict), f'{label}.step2_research_context must be a dict'
    for key in [
        'target_statistic',
        'economic_mechanism',
        'expected_failure_modes',
        'reuse_instruction_for_future_agents',
        'implementation_invariants',
    ]:
        assert ctx.get(key), f'{label}.step2_research_context.{key} is required'
    assert isinstance(ctx.get('expected_failure_modes'), list), (
        f'{label}.step2_research_context.expected_failure_modes must be a list'
    )
    assert isinstance(ctx.get('reuse_instruction_for_future_agents'), list), (
        f'{label}.step2_research_context.reuse_instruction_for_future_agents must be a list'
    )
    for key in ['target_statistic', 'economic_mechanism']:
        assert not str(ctx.get(key)).startswith('missing_'), (
            f'{label}.step2_research_context.{key} still carries a missing_* sentinel; rerun Step2 first'
        )


def assert_no_step4_outputs_in_step3b(first_run_outputs: dict, code_dir: Path, meta: dict | None = None) -> None:
    """Step3B may prove factor-value executability, but it must not perform Step4 evaluation."""
    forbidden_tokens = [
        'evaluation_payload',
        'factor_run_master',
        'factor_run_diagnostics',
        'factor_evaluation',
        'self_quant',
        'qlib_backtest',
        'rank_ic',
        'pearson_ic',
        'quantile_nav',
        'quantile_returns',
        'long_short_nav',
        'portfolio_value',
        'benchmark_vs_strategy',
        'turnover_timeseries',
    ]
    for raw_path in first_run_outputs.get('output_paths') or []:
        text = str(raw_path)
        assert not any(token in text for token in forbidden_tokens), (
            f'Step3B first_run_outputs contains Step4-only artifact path: {text}'
        )
    if meta:
        assert meta.get('producer') in {'step3b_sample_proof', 'step3b_first_run'}, (
            f'run_metadata.producer must be step3b_sample_proof, got {meta.get("producer")}'
        )
        assert meta.get('is_formal_factor_values') is not True, (
            'Step3B metadata must not mark outputs as formal factor_values'
        )
        assert meta.get('formal_factor_values_owner') in {None, 'Step4'}, (
            'Step3B metadata must preserve Step4 ownership for formal factor_values'
        )
        note = str(meta.get('boundary_note') or '')
        assert 'Step4 owns' in note, 'run_metadata must document Step3B/Step4 boundary'

    if code_dir.exists():
        forbidden_files = [
            path for path in code_dir.iterdir()
            if path.is_file() and any(token in path.name for token in forbidden_tokens)
        ]
        assert not forbidden_files, (
            'Step3B generated_code directory contains Step4-only artifacts: '
            + ', '.join(str(path.name) for path in forbidden_files)
        )

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    a = ap.parse_args()
    _manifest, manifest_rid = apply_runtime_manifest(a.manifest)
    rid = a.report_id or manifest_rid
    if not rid:
        raise SystemExit('validate_step3b.py requires --report-id or --manifest')

    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1' and not _manifest:
        raise SystemExit('BLOCKED_MISSING_RUNTIME_MANIFEST: formal Step3B validation requires manifest_identity.')

    spec_path = (
        nested_path(_manifest, 'step_io', 'step2', 'factor_spec_master')
        or nested_path(_manifest, 'step_io', 'step3', 'inputs', 'factor_spec_master')
        or OBJ / 'factor_spec_master' / f'factor_spec_master__{rid}.json'
    )
    impl = (
        nested_path(_manifest, 'step_io', 'step3', 'outputs', 'implementation_plan_master')
        or OBJ / 'implementation_plan_master' / f'implementation_plan_master__{rid}.json'
    )
    handoff = OBJ / 'handoff' / f'handoff_to_step4__{rid}.json'
    prep_path = OBJ / 'data_prep_master' / f'data_prep_master__{rid}.json'
    manifest_code_dir = (
        (_manifest or {})
        .get('step_io', {})
        .get('step3b', {})
        .get('outputs', {})
        .get('generated_code_dir')
    )
    code_dir = Path(manifest_code_dir) if manifest_code_dir else CODE / rid
    stub = code_dir / f'factor_impl_stub__{rid}.py'
    real_impl = code_dir / f'factor_impl__{rid}.py'
    qlib = code_dir / f'qlib_expression_draft__{rid}.json'
    hybrid = code_dir / f'hybrid_execution_scaffold__{rid}.json'

    spec_data = load(spec_path) if spec_path.exists() else {}
    data = load(impl)
    h = load(handoff)
    prep = load(prep_path)
    qlib_data = load(qlib)
    hybrid_data = load(hybrid)
    spec_identity = assert_artifact_identity('factor_spec_master', spec_data, role='factor_spec_master')
    manifest_identity = (_manifest or {}).get('manifest_identity') or None
    if _manifest:
        assert manifest_identity, 'runtime manifest must carry manifest_identity'
        manifest_identity = {**manifest_identity, 'artifact_role': spec_identity.get('artifact_role'), 'producer': spec_identity.get('producer')}
        assert_identity_matches_strict(
            spec_identity,
            manifest_identity,
            expected_label='factor_spec_master',
            actual_label='manifest',
            allowed_role_transitions={(spec_identity.get('artifact_role'), spec_identity.get('artifact_role'))},
        )
    plan_identity = assert_artifact_identity('implementation_plan_master', data, expected=spec_identity, role='implementation_plan_master')
    handoff_identity = assert_artifact_identity('handoff_to_step4', h, expected=spec_identity, role='handoff_to_step4')
    qlib_identity = assert_artifact_identity('qlib_expression_draft', qlib_data, expected=spec_identity, role='generated_code')
    hybrid_identity = assert_artifact_identity('hybrid_execution_scaffold', hybrid_data, expected=spec_identity, role='generated_code')
    validate_family_plugin_artifacts(
        spec_data,
        [
            ('implementation_plan_master', data),
            ('qlib_expression_draft', qlib_data),
            ('hybrid_execution_scaffold', hybrid_data),
            ('handoff_to_step4', h),
        ],
    )
    assert plan_identity.get('implementation_mode') == handoff_identity.get('implementation_mode') == qlib_identity.get('implementation_mode') == hybrid_identity.get('implementation_mode'), 'cross-mode artifact contamination detected'
    top_modes = {
        'factor_spec_master.implementation_mode': spec_data.get('implementation_mode'),
        'implementation_plan_master.implementation_mode': data.get('implementation_mode'),
        'handoff_to_step4.implementation_mode': h.get('implementation_mode'),
        'qlib_expression_draft.implementation_mode': declared_mode('qlib_expression_draft', qlib_data),
        'hybrid_execution_scaffold.implementation_mode': declared_mode('hybrid_execution_scaffold', hybrid_data),
    }
    assert set(top_modes.values()) == {spec_identity.get('implementation_mode')}, f'top-level implementation_mode mismatch: {top_modes}'
    mode_decision = assert_mode_decision_chain(spec_identity, data, qlib_data, hybrid_data, h)
    if mode_decision.get('selected_mode') == 'blocked':
        assert h.get('step3b_ready') is False, 'blocked Step3B handoff must set step3b_ready=false'
        raise AssertionError(
            f'BLOCK_STEP3B_IMPLEMENTATION_BLOCKED: {mode_decision.get("final_decision_reason")}'
        )
    validate_mode_specific(
        spec_data,
        data,
        qlib_data,
        hybrid_data,
        manifest=_manifest,
        handoff=h,
        code_dir=code_dir,
        stub=stub,
        real_impl=real_impl,
        prep=prep,
    )
    expected_step3a_ready = prep.get('feasibility') in {'ready', 'proxy_ready'}
    assert data.get('report_id') == rid, f'implementation_plan_master.report_id mismatch: expected {rid}, got {data.get("report_id")}'
    assert h.get('report_id') == rid, f'handoff_to_step4.report_id mismatch: expected {rid}, got {h.get("report_id")}'
    assert prep.get('report_id') == rid, f'data_prep_master.report_id mismatch: expected {rid}, got {prep.get("report_id")}'
    assert data['implementation_mode'] in {'operator', 'direct_code', 'hybrid'}
    assert stub.exists()
    assert qlib.exists()
    assert hybrid.exists()
    assert handoff.exists()
    assert isinstance(h.get('local_input_paths'), dict), 'handoff_to_step4.local_input_paths must be explicit even when blocked'
    assert h.get('step3a_ready') is expected_step3a_ready, (
        f'handoff_to_step4.step3a_ready mismatch: expected {expected_step3a_ready}, '
        f"got {h.get('step3a_ready')}"
    )
    assert h.get('step3b_ready') is True, 'handoff_to_step4 must preserve step3b_ready'
    assert h.get('data_prep_master_ref'), 'handoff_to_step4 must preserve Step 3A data_prep_master reference'
    assert h.get('qlib_adapter_config_ref'), 'handoff_to_step4 must preserve Step 3A qlib_adapter_config reference'
    assert h.get('factor_spec_master_ref'), 'handoff_to_step4 must preserve factor_spec_master reference'
    if real_impl.exists():
        assert h.get('factor_impl_ref'), 'handoff_to_step4 should prefer real factor_impl when it exists'
    assert_step2_context('implementation_plan_master', data.get('step2_research_context'))
    assert_step2_context('handoff_to_step4', h.get('step2_research_context'))
    assert_step2_context('qlib_expression_draft', qlib_data.get('step2_research_context'))
    assert_step2_context('hybrid_execution_scaffold', hybrid_data.get('step2_research_context'))
    assert data.get('step2_research_context') == h.get('step2_research_context'), (
        'Step 3B must pass the same Step2 research context from plan into handoff'
    )

    txt = stub.read_text(encoding='utf-8')
    assert 'STEP2_RESEARCH_CONTEXT' in txt, 'factor implementation stub must expose Step2 research context for IDE review'
    assert 'target_statistic:' in txt, 'factor implementation stub must include Step2 target_statistic'
    for bad in ['TODO', 'TO_BE_FILLED', 'placeholder']:
        assert bad not in txt

    # Step3B executability proof: if Step3A prepared local snapshots or a Data API
    # sample contract, Step3B should emit non-formal sample outputs only.
    local_inputs = h.get('local_input_paths') or {}
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    input_mode = str(local_inputs.get('input_mode') or '')
    step4_contract = h.get('step4_data_contract') or data.get('step4_data_contract') or prep.get('step4_data_contract') or local_inputs.get('step4_data_contract') or {}
    sample_queries = step4_contract.get('sample_queries') if isinstance(step4_contract, dict) else {}
    has_sample_contract = isinstance(sample_queries, dict) and bool(sample_queries.get('clean_daily_bar'))
    if (minute_rel and daily_rel) or (input_mode == 'daily_only' and daily_rel) or has_sample_contract:
        run_dir = FF / 'runs' / rid
        factor_parquet = run_dir / f'step3b_sample_factor_values__{rid}.parquet'
        factor_csv = run_dir / f'step3b_sample_factor_values__{rid}.csv'
        meta_json = run_dir / f'step3b_sample_run_metadata__{rid}.json'
        assert factor_parquet.exists() or factor_csv.exists(), 'Step 3B requires non-formal sample factor values when sample data is available'
        assert meta_json.exists(), 'Step 3B requires sample run_metadata when sample data is available'
        assert not (run_dir / f'factor_values__{rid}.parquet').exists(), 'Step3B must not create formal factor_values parquet'
        assert not (run_dir / f'run_metadata__{rid}.json').exists(), 'Step3B must not create formal Step4 run_metadata'
        run_meta = load(meta_json)
        assert_step3b_runtime_performance_policy(run_meta)
        assert_step2_context('run_metadata', run_meta.get('step2_research_context'))
        assert_no_step4_outputs_in_step3b(data.get('first_run_outputs') or h.get('first_run_outputs') or {}, code_dir, run_meta)
        first_run_outputs = data.get('first_run_outputs') or h.get('first_run_outputs')
        assert isinstance(first_run_outputs, dict), 'Step 3B schema must expose first_run_outputs when local snapshots exist'
        assert first_run_outputs.get('status') in {'ready', 'partial', 'pending'}
        if first_run_outputs.get('status') == 'pending':
            assert first_run_outputs.get('no_first_run_reason'), 'pending first_run_outputs must carry no_first_run_reason'
        if first_run_outputs.get('status') == 'ready':
            assert first_run_outputs.get('output_paths'), 'ready first_run_outputs must carry output_paths'
            assert first_run_outputs.get('run_metadata_path'), 'ready first_run_outputs must carry run_metadata_path'
            assert first_run_outputs.get('is_formal_factor_values') is False, 'Step3B ready outputs must be explicitly non-formal'
            assert first_run_outputs.get('formal_factor_values_owner') == 'Step4', 'Step3B must preserve Step4 as formal factor_values owner'
            assert_no_step4_outputs_in_step3b(first_run_outputs, code_dir, run_meta)
    else:
        first_run_outputs = data.get('first_run_outputs') or h.get('first_run_outputs') or {}
        assert first_run_outputs.get('status') in {None, 'pending'}, 'Step 3B should stay pending when no executable local snapshots exist'
        if first_run_outputs.get('status') == 'pending':
            assert first_run_outputs.get('no_first_run_reason'), 'pending first_run_outputs must carry no_first_run_reason'

    print('RESULT: PASS')
