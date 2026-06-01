#!/usr/bin/env python3
import argparse, ast, hashlib, importlib.util, inspect, json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Runtime root policy:
# - prefer FACTORFORGE_ROOT when explicitly configured
# - otherwise keep legacy EC2 compatibility
# - fallback to current repository root for local runs
# COMMENT_POLICY: runtime_path
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
LEGACY_REPO_ROOT = LEGACY_WORKSPACE / 'repos' / 'factor-factory'
REPO_ROOT = LEGACY_REPO_ROOT if LEGACY_REPO_ROOT.exists() else Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FF.parent
OBJ = FF / 'objects'
CODEGEN = FF / 'generated_code'
RUNS = FF / 'runs'

from factor_factory.data_access import infer_signal_column, normalize_trade_date_series
from factor_factory.data_api import fetch_data_api_dataset
from factor_factory.artifact_identity import assert_identity_matches, stable_hash
from factor_factory.factor_families.base import FAMILY_PLUGIN_PRODUCER
from factor_factory.factor_families.registry import (
    FamilyPluginContractError,
    explicit_plugin_identity_fields,
    has_family_plugin_declaration,
    resolve_family_plugin,
)
from factor_factory.formula.pandas_codegen import generate_pandas_formula_code, operator_metadata
from factor_factory.formula.parser import parse_formula, resolve_formula_fields_for_schema
from factor_factory.formula.qlib_codegen import to_qlib_expression
from factor_factory.formula.registry import operator_meta
from factor_factory.formula.evaluator import evaluate_formula_frame
from factor_factory.formula.kernels import default_kernel_profile, resolve_formula_kernel_engine
from factor_factory.formula.operators import default_ts_rank_engine_profile, resolve_ts_rank_engine as resolve_formula_ts_rank_engine
from factor_factory.formula.parity import compare_outputs, make_operator_fixture
from factor_factory.performance import PhaseTimer, safe_file_size
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

MODE_DECISION_VERSION = 'factorforge_implementation_mode_decision_v1'
HYBRID_CONTRACT_VERSION = 'factorforge_hybrid_contract_v1'
FORBIDDEN_CUSTOM_BLOCK_PATTERNS = [
    r'shift\s*\(\s*-\d+',
    r'\bfuture_return\b',
    r'\bnext_return\b',
    r'\bforward_return\b',
    r'\blabel\b',
    r'\btarget\b',
    r'\by_true\b',
    r'\bfuture_',
    r'\blead\s*\(',
    r'\blookahead\b',
]
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
CSV_POLICY_VALUES = {'full_csv', 'sample_csv', 'no_csv'}
CSV_SAMPLE_MAX_ROWS = 10_000
EXECUTABLE_REVISION_SPEC_VERSION = 'factorforge_executable_revision_spec_v1'
SORT_CONTRACT_VERSION = 'factorforge_sort_contract_v1'
HIGH_SPEED_CODE_PROFILE_VERSION = 'factorforge_high_speed_code_profile_v1'
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


def _is_groupby_apply_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != 'apply':
        return False
    return _receiver_chain_contains_call(node.func.value, 'groupby')


def _is_rolling_apply_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != 'apply':
        return False
    return _receiver_chain_contains_call(node.func.value, 'rolling')


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
        raise SystemExit(f'BLOCK_DIRECT_CODE_PERFORMANCE_RISK: {profile}')
    return profile


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def resolve_csv_policy(explicit_policy: str | None = None) -> str:
    policy = explicit_policy or os.getenv('FACTORFORGE_CSV_OUTPUT_POLICY') or 'full_csv'
    if policy not in CSV_POLICY_VALUES:
        raise SystemExit(f'BLOCK_FACTORFORGE_INVALID_CSV_OUTPUT_POLICY:{policy}')
    return policy


def resolve_trust_step3a_sort_contract(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return str(os.getenv('FACTORFORGE_TRUST_STEP3A_SORT_CONTRACT') or '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def deterministic_csv_sample(df, *, max_rows: int = CSV_SAMPLE_MAX_ROWS):
    if len(df) <= max_rows:
        return df.copy()
    head_n = max_rows // 2
    tail_n = max_rows - head_n
    import pandas as pd

    return pd.concat([df.head(head_n), df.tail(tail_n)], ignore_index=True)


def sort_contract_key_hash(df: pd.DataFrame) -> str:
    key_frame = df[['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    return hashlib.sha256(key_frame.to_csv(index=False).encode('utf-8')).hexdigest()


def sample_keys_sorted(df: pd.DataFrame, *, max_points: int = 2048) -> bool:
    if df.empty:
        return True
    if len(df) <= max_points:
        sample = df[['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    else:
        step = max(1, len(df) // max_points)
        indices = sorted(set([0, len(df) - 1, *range(0, len(df), step)]))
        sample = df.iloc[indices][['ts_code', 'trade_date']].astype(str).reset_index(drop=True)
    expected = sample.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    return bool(sample.equals(expected))


def global_keys_sorted(df: pd.DataFrame) -> bool:
    if len(df) <= 1:
        return True
    keys = df[['ts_code', 'trade_date']].copy()
    ts_code = keys['ts_code'].astype(str).reset_index(drop=True)
    trade_date = normalize_trade_date_series(keys['trade_date']).dt.strftime('%Y%m%d').astype(str).reset_index(drop=True)
    prev_ts = ts_code.iloc[:-1].reset_index(drop=True)
    next_ts = ts_code.iloc[1:].reset_index(drop=True)
    prev_dt = trade_date.iloc[:-1].reset_index(drop=True)
    next_dt = trade_date.iloc[1:].reset_index(drop=True)
    ordered = (prev_ts < next_ts) | ((prev_ts == next_ts) & (prev_dt <= next_dt))
    return bool(ordered.all())


def default_normalize_sort_profile(*, contract_present: bool, opt_in_enabled: bool) -> dict:
    return {
        'version': 'factorforge_normalize_sort_profile_v1',
        'sort_contract_present': bool(contract_present),
        'sort_contract_trusted': False,
        'opt_in_enabled': bool(opt_in_enabled),
        'full_sort_skipped': False,
        'full_sort_skipped_reason': None,
        'fallback_reason': 'contract_missing' if not contract_present else ('opt_in_disabled' if not opt_in_enabled else None),
        'sample_sortedness_check': False,
        'global_sortedness_check': False,
        'duplicate_key_check': False,
        'row_count_validated': False,
        'key_dtype_validated': False,
        'data_hash_validated': False,
        'schema_validated': False,
        'output_key_order_validated': False,
    }


def extract_sort_contract(local_inputs: dict) -> dict:
    contract = local_inputs.get('sort_contract')
    if isinstance(contract, dict) and contract:
        return contract
    daily_contract = local_inputs.get('daily_io_contract') if isinstance(local_inputs.get('daily_io_contract'), dict) else {}
    contract = daily_contract.get('sort_contract')
    return contract if isinstance(contract, dict) else {}


def validate_sort_contract_for_skip(
    *,
    contract: dict,
    daily_df: pd.DataFrame,
    result_df: pd.DataFrame,
    opt_in_enabled: bool,
) -> dict:
    profile = default_normalize_sort_profile(contract_present=bool(contract), opt_in_enabled=opt_in_enabled)
    if not contract:
        return profile
    if not opt_in_enabled:
        return profile
    if contract.get('version') != SORT_CONTRACT_VERSION or contract.get('sorted_by') != ['ts_code', 'trade_date']:
        profile['fallback_reason'] = 'invalid_contract'
        return profile
    if int(contract.get('row_count') or -1) != len(daily_df) or len(result_df) != len(daily_df):
        profile['fallback_reason'] = 'row_count_mismatch'
        return profile
    profile['row_count_validated'] = True
    key_dtype = contract.get('key_dtype') if isinstance(contract.get('key_dtype'), dict) else {}
    if key_dtype.get('ts_code') != str(daily_df['ts_code'].dtype) or key_dtype.get('trade_date') != str(daily_df['trade_date'].dtype):
        profile['fallback_reason'] = 'key_dtype_mismatch'
        return profile
    profile['key_dtype_validated'] = True
    schema = contract.get('schema')
    if isinstance(schema, list) and not {'ts_code', 'trade_date'}.issubset(set(schema)):
        profile['fallback_reason'] = 'schema_mismatch'
        return profile
    profile['schema_validated'] = True
    if contract.get('data_hash') != sort_contract_key_hash(daily_df):
        profile['fallback_reason'] = 'data_hash_mismatch'
        return profile
    profile['data_hash_validated'] = True
    daily_duplicate = bool(daily_df[['ts_code', 'trade_date']].duplicated().any())
    result_duplicate = bool(result_df[['ts_code', 'trade_date']].duplicated().any())
    if contract.get('duplicate_key_check') is not True or daily_duplicate or result_duplicate:
        profile['fallback_reason'] = 'duplicate_key_detected'
        return profile
    profile['duplicate_key_check'] = True
    if not global_keys_sorted(daily_df) or not global_keys_sorted(result_df):
        profile['fallback_reason'] = 'global_sortedness_failed'
        return profile
    profile['sample_sortedness_check'] = contract.get('sample_sortedness_check') is True
    profile['global_sortedness_check'] = True
    daily_keys = daily_df[['ts_code', 'trade_date']].copy()
    daily_keys['trade_date'] = normalize_trade_date_series(daily_keys['trade_date']).dt.strftime('%Y%m%d')
    result_keys = result_df[['ts_code', 'trade_date']].copy()
    result_keys['trade_date'] = normalize_trade_date_series(result_keys['trade_date']).dt.strftime('%Y%m%d')
    if not result_keys.astype(str).reset_index(drop=True).equals(daily_keys.astype(str).reset_index(drop=True)):
        profile['fallback_reason'] = 'output_key_order_mismatch'
        return profile
    profile['output_key_order_validated'] = True
    profile['sort_contract_trusted'] = True
    profile['full_sort_skipped'] = True
    profile['full_sort_skipped_reason'] = 'trusted_step3a_sort_contract'
    profile['fallback_reason'] = None
    return profile


def executable_revision_spec_path(report_id: str) -> Path:
    return OBJ / 'research_iteration_master' / f'executable_revision_spec__{report_id}.json'


def is_child_revision_report(report_id: str, spec: dict) -> bool:
    if not isinstance(spec, dict):
        return False
    if report_id and '__LOOP' in report_id:
        return True
    return bool(spec.get('parent_report_id') and spec.get('parent_report_id') != report_id)


def apply_executable_revision_spec(report_id: str, spec: dict, spec_path: Path) -> tuple[dict, dict | None]:
    if not is_child_revision_report(report_id, spec):
        return spec, None
    path = executable_revision_spec_path(report_id)
    if not path.exists():
        raise SystemExit(f'BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_MISSING: {path}')
    revision_spec = load_json(path)
    if revision_spec.get('contract_version') != EXECUTABLE_REVISION_SPEC_VERSION:
        raise SystemExit('BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_INVALID: contract_version')
    if revision_spec.get('child_report_id') != report_id:
        raise SystemExit('BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_INVALID: child_report_id')
    child_formula = str(revision_spec.get('child_formula') or '').strip()
    if not child_formula:
        raise SystemExit('BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_INVALID: child_formula')
    parsed = parse_formula(child_formula)
    if parsed.get('parse_status') != 'success':
        raise SystemExit('BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_INVALID: formula_parse_failed')
    parent_hash = str(revision_spec.get('parent_formula_hash') or '')
    child_hash = str(revision_spec.get('child_formula_hash') or parsed.get('formula_hash') or '')
    if revision_spec.get('revision_type') != 'audit_rerun' and parent_hash and parent_hash == child_hash:
        raise SystemExit('BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT')
    if child_hash != parsed.get('formula_hash'):
        raise SystemExit('BLOCK_FACTORFORGE_CHILD_REVISION_SPEC_INVALID: child_formula_hash')

    updated = json.loads(json.dumps(spec))
    canonical = updated.setdefault('canonical_spec', {})
    canonical['formula_text'] = child_formula
    canonical['formula_ir'] = parsed
    canonical['formula_hash'] = parsed.get('formula_hash')
    canonical['operator_set'] = parsed.get('operator_set') or []
    canonical['operators'] = parsed.get('operator_set') or []
    canonical['required_inputs'] = parsed.get('required_fields') or []
    canonical['required_fields'] = parsed.get('required_fields') or []
    updated['formula_hash'] = parsed.get('formula_hash')
    updated['executable_revision_spec_ref'] = str(path)
    updated['revision_identity'] = {
        'contract_version': 'factorforge_child_revision_identity_v1',
        'parent_report_id': revision_spec.get('parent_report_id'),
        'child_report_id': report_id,
        'revision_spec_path': str(path),
        'parent_formula_hash': parent_hash,
        'child_formula_hash': child_hash,
        'revision_noop': parent_hash == child_hash,
        'revision_identity_status': 'audit_rerun' if revision_spec.get('revision_type') == 'audit_rerun' else 'changed',
    }
    updated.setdefault('implementation_contract', {})
    if isinstance(updated['implementation_contract'], dict):
        updated['implementation_contract']['mode'] = 'operator'
        updated['implementation_contract']['formula_ir'] = parsed
        updated['implementation_contract']['formula_hash'] = parsed.get('formula_hash')
        updated['implementation_contract']['operator_set'] = parsed.get('operator_set') or []
        updated['implementation_contract']['required_fields'] = parsed.get('required_fields') or []
    if isinstance(updated.get('artifact_identity'), dict):
        updated['artifact_identity']['formula_hash'] = parsed.get('formula_hash')
        updated['artifact_identity']['implementation_mode'] = 'operator'
    if updated != spec:
        write_json(spec_path, updated)
    return updated, revision_spec


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    """Apply the orchestrator-owned runtime manifest before Step3B resolves paths."""
    global FF, WORKSPACE, OBJ, CODEGEN, RUNS
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    CODEGEN = FF / 'generated_code'
    RUNS = FF / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    return manifest, manifest_report_id(manifest)


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FF, WORKSPACE, OBJ, CODEGEN, RUNS
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step3B execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FF.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    if manifest_path:
        manifest = load_runtime_manifest(manifest_path)
        if manifest_factorforge_root(manifest).expanduser().resolve() != debug_root:
            raise SystemExit('BLOCKED_DIRECT_STEP: direct debug manifest must point to FACTORFORGE_DEBUG_ROOT.')
    FF = debug_root
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    CODEGEN = FF / 'generated_code'
    RUNS = FF / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def resolve_step_runtime_python() -> str:
    venv_python = WORKSPACE / '.venvs' / 'quant-research' / 'bin' / 'python'
    if venv_python.exists():
        return str(venv_python)
    return 'python3'


def load_json(p: Path):
    return json.loads(p.read_text(encoding='utf-8'))


def nested_path(data: dict | None, *keys: str) -> Path | None:
    current = data or {}
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return Path(current).expanduser() if current else None


def require_formal_manifest(manifest: dict | None) -> None:
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1' and not manifest:
        raise SystemExit('BLOCKED_MISSING_RUNTIME_MANIFEST: formal Step3B requires explicit runtime manifest paths and manifest_identity.')


def load_manifest_identity(manifest: dict | None) -> dict:
    return (manifest or {}).get('manifest_identity') or {}


def assert_spec_identity_matches_manifest(spec: dict, manifest: dict | None) -> dict:
    identity = spec.get('artifact_identity') or {}
    if not identity:
        raise SystemExit('BLOCKED_MISSING_ARTIFACT_IDENTITY: factor_spec_master.artifact_identity is required.')
    manifest_identity = load_manifest_identity(manifest)
    if manifest is not None:
        if not manifest_identity:
            raise SystemExit('BLOCKED_MISSING_MANIFEST_IDENTITY: runtime manifest must carry manifest_identity.')
        try:
            assert_identity_matches(identity, manifest_identity, left_label='factor_spec_master', right_label='manifest')
        except AssertionError as exc:
            raise SystemExit(f'BLOCKED_ARTIFACT_IDENTITY_MISMATCH: {exc}') from exc
    return identity


def derive_child_identity(parent: dict, *, artifact_role: str, producer: str, code_hash: str | None = None, family_fields: dict | None = None) -> dict:
    out = dict(parent)
    out['artifact_role'] = artifact_role
    out['producer'] = producer
    if out.get('implementation_mode') == 'direct_code' and not out.get('code_hash'):
        out['code_hash'] = None
    else:
        out['code_hash'] = code_hash or out.get('code_hash')
    if family_fields:
        out.update(family_fields)
    return out


def build_mode_decision_start(spec_identity: dict, spec: dict) -> dict:
    mode = spec_identity.get('implementation_mode') or spec.get('implementation_mode')
    decision = {
        'decision_version': MODE_DECISION_VERSION,
        'selected_mode': 'blocked',
        'requested_mode': mode,
        'operator_attempted': False,
        'operator_result': 'not_applicable',
        'operator_failure_reason': None,
        'hybrid_attempted': False,
        'hybrid_result': 'not_applicable',
        'hybrid_failure_reason': None,
        'direct_code_attempted': False,
        'direct_code_result': 'not_applicable',
        'direct_code_failure_reason': None,
        'final_decision_reason': None,
        'correctness_risk': 'high',
        'human_review_required': True,
    }
    if mode == 'operator':
        decision['operator_attempted'] = True
        decision['operator_result'] = 'failed'
    elif mode == 'hybrid':
        decision['operator_attempted'] = True
        decision['operator_result'] = 'not_applicable'
        decision['operator_failure_reason'] = 'Step2 selected hybrid mode; operator-only implementation was not applicable to this contract.'
        decision['hybrid_attempted'] = True
        decision['hybrid_result'] = 'failed'
    elif mode == 'direct_code':
        decision['operator_attempted'] = True
        decision['operator_result'] = 'not_applicable'
        decision['operator_failure_reason'] = 'Step2 selected direct_code mode; operator implementation was not applicable to this contract.'
        decision['hybrid_attempted'] = True
        decision['hybrid_result'] = 'not_applicable'
        decision['hybrid_failure_reason'] = 'Step2 selected direct_code mode; hybrid implementation was not applicable to this contract.'
        decision['direct_code_attempted'] = True
        decision['direct_code_result'] = 'failed'
    else:
        decision['final_decision_reason'] = f'Unsupported implementation_mode: {mode}'
    return decision


def finalize_mode_decision_success(decision: dict, selected_mode: str, reason: str) -> dict:
    out = dict(decision)
    out['selected_mode'] = selected_mode
    out['correctness_risk'] = 'medium' if selected_mode == 'direct_code' else 'low'
    out['human_review_required'] = selected_mode in {'direct_code', 'hybrid'}
    out['final_decision_reason'] = reason
    if selected_mode == 'operator':
        out['operator_attempted'] = True
        out['operator_result'] = 'success'
        out['operator_failure_reason'] = None
    elif selected_mode == 'hybrid':
        out['hybrid_attempted'] = True
        out['hybrid_result'] = 'success'
        out['hybrid_failure_reason'] = None
    elif selected_mode == 'direct_code':
        out['direct_code_attempted'] = True
        out['direct_code_result'] = 'success'
        out['direct_code_failure_reason'] = None
    return out


def finalize_mode_decision_blocked(decision: dict, mode: str | None, reason: str) -> dict:
    out = dict(decision)
    out['selected_mode'] = 'blocked'
    out['correctness_risk'] = 'high'
    out['human_review_required'] = True
    out['final_decision_reason'] = reason
    if mode == 'operator':
        out['operator_attempted'] = True
        out['operator_result'] = 'failed'
        out['operator_failure_reason'] = reason
    elif mode == 'hybrid':
        out['hybrid_attempted'] = True
        out['hybrid_result'] = 'failed'
        out['hybrid_failure_reason'] = reason
    elif mode == 'direct_code':
        out['direct_code_attempted'] = True
        out['direct_code_result'] = 'failed'
        out['direct_code_failure_reason'] = reason
    return out


def write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {p}')


def write_text(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')
    print(f'[WRITE] {p}')


def read_existing_json(p: Path) -> dict:
    if not p.exists():
        return {}
    return load_json(p)


def merge_handoff(existing: dict, updates: dict) -> dict:
    merged = dict(existing)
    merged.update({k: v for k, v in updates.items() if v is not None})

    existing_local_inputs = existing.get('local_input_paths')
    update_local_inputs = updates.get('local_input_paths')
    if isinstance(existing_local_inputs, dict) and isinstance(update_local_inputs, dict):
        merged['local_input_paths'] = {**existing_local_inputs, **update_local_inputs}

    existing_first_run = existing.get('first_run_outputs')
    update_first_run = updates.get('first_run_outputs')
    if isinstance(existing_first_run, dict) and isinstance(update_first_run, dict):
        if update_first_run.get('status') == 'pending' and existing_first_run.get('status') in {'ready', 'partial'}:
            merged['first_run_outputs'] = existing_first_run
        else:
            merged['first_run_outputs'] = {**existing_first_run, **update_first_run}

    if 'evaluation_plan' in existing and updates.get('evaluation_plan') is None:
        merged['evaluation_plan'] = existing['evaluation_plan']

    for key in ['factor_impl_ref', 'factor_impl_stub_ref', 'qlib_expression_draft_ref', 'hybrid_execution_scaffold_ref', 'execution_mode']:
        if merged.get(key) is None and existing.get(key) is not None:
            merged[key] = existing[key]

    merged['report_id'] = updates.get('report_id') or existing.get('report_id')
    return merged


def load_step2_handoff(report_id: str) -> dict:
    path = OBJ / 'handoff' / f'handoff_to_step3__{report_id}.json'
    return load_json(path) if path.exists() else {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def build_step2_research_context(report_id: str, spec: dict, step2_handoff: dict | None = None) -> dict:
    """Carry Step2 research intent into Step3B implementation artifacts."""
    handoff = step2_handoff or {}
    thesis = spec.get('thesis') or {}
    spec_math = spec.get('math_discipline_review') or {}
    spec_learning = spec.get('learning_and_innovation') or {}
    spec_contract = spec.get('research_contract') or {}
    handoff_contract = handoff.get('research_contract') or {}
    handoff_math = handoff.get('math_discipline_review') or {}
    handoff_learning = handoff.get('learning_and_innovation') or {}

    target_statistic = (
        spec_contract.get('target_statistic')
        or thesis.get('target_prediction')
        or spec_math.get('target_statistic')
        or handoff_contract.get('target_statistic')
        or handoff_math.get('target_statistic')
    )
    economic_mechanism = (
        spec_contract.get('economic_mechanism')
        or thesis.get('economic_mechanism')
        or handoff_contract.get('economic_mechanism')
    )
    expected_failure_modes = (
        _as_list(spec_contract.get('expected_failure_modes'))
        or _as_list(spec_math.get('expected_failure_modes'))
        or _as_list(handoff_contract.get('expected_failure_modes'))
        or _as_list(handoff_math.get('expected_failure_modes'))
    )
    innovative_idea_seeds = (
        _as_list(spec_learning.get('innovative_idea_seeds'))
        or _as_list(spec_contract.get('innovative_idea_seeds'))
        or _as_list(handoff_learning.get('innovative_idea_seeds'))
        or _as_list(handoff_contract.get('innovative_idea_seeds'))
    )
    reuse_instruction = (
        _as_list(spec_learning.get('reuse_instruction_for_future_agents'))
        or _as_list(spec_contract.get('reuse_instruction_for_future_agents'))
        or _as_list(handoff_learning.get('reuse_instruction_for_future_agents'))
        or _as_list(handoff_contract.get('reuse_instruction_for_future_agents'))
    )

    return {
        'report_id': report_id,
        'factor_id': spec.get('factor_id'),
        'alpha_thesis': thesis.get('alpha_thesis'),
        'target_statistic': target_statistic or 'missing_target_statistic_from_step2',
        'economic_mechanism': economic_mechanism or 'missing_economic_mechanism_from_step2',
        'expected_failure_modes': expected_failure_modes or ['missing_expected_failure_modes_from_step2'],
        'step1_random_object': spec_math.get('step1_random_object') or handoff_math.get('step1_random_object'),
        'information_set_legality': spec_math.get('information_set_legality') or handoff_math.get('information_set_legality'),
        'similar_case_lessons_imported': (
            _as_list(spec_learning.get('similar_case_lessons_imported'))
            or _as_list(handoff_learning.get('similar_case_lessons_imported'))
        ),
        'innovative_idea_seeds': innovative_idea_seeds,
        'reuse_instruction_for_future_agents': reuse_instruction or ['missing_reuse_instruction_from_step2'],
        'implementation_invariants': [
            'Step3B implementation must preserve the Step2 target statistic and economic mechanism.',
            'Any proxy, sign flip, window change, neutralization, or operator substitution must be recorded as a research-motivated approximation.',
            'Code generation must not optimize metrics by changing the thesis silently.',
        ],
        'source_refs': {
            'factor_spec_master': f'factor_spec_master__{report_id}.json',
            'handoff_to_step3': f'handoff_to_step3__{report_id}.json' if handoff else None,
        },
        'producer': 'step3b_from_step2_research_contract',
    }


def attach_step2_research_context(
    implementation_plan: dict,
    qlib_expression: dict,
    hybrid_scaffold: dict,
    step2_research_context: dict,
) -> None:
    implementation_plan['step2_research_context'] = step2_research_context
    implementation_plan.setdefault('implementation_guardrails', [])
    implementation_plan['implementation_guardrails'] = list(dict.fromkeys(
        _as_list(implementation_plan.get('implementation_guardrails'))
        + _as_list(step2_research_context.get('implementation_invariants'))
    ))
    qlib_expression['step2_research_context'] = step2_research_context
    hybrid_scaffold['step2_research_context'] = step2_research_context


def annotate_python_stub_with_research_context(python_stub: str, step2_research_context: dict) -> str:
    """Make the generated implementation self-describing for IDE-side reviewers."""
    context_lines = [
        '# STEP2_RESEARCH_CONTEXT:',
        f"# target_statistic: {step2_research_context.get('target_statistic')}",
        f"# economic_mechanism: {step2_research_context.get('economic_mechanism')}",
        f"# expected_failure_modes: {step2_research_context.get('expected_failure_modes')}",
        '# implementation_guardrail: Preserve the Step2 thesis unless a revision loop explicitly changes it.',
    ]
    return '\n'.join(context_lines) + '\n\n' + python_stub


def patch_json_with_step2_research_context(path: Path, step2_research_context: dict) -> None:
    if not path.exists():
        return
    data = load_json(path)
    data['step2_research_context'] = step2_research_context
    write_json(path, data)


def import_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot create import spec for {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_direct_code_alias_columns(df: pd.DataFrame) -> pd.DataFrame:
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


def maybe_polars_frame(df: pd.DataFrame, use_polars: bool):
    if not use_polars:
        return df
    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit(f'BLOCK_STEP3B_DIRECT_CODE_DEPENDENCY_MISSING: polars dependency missing: {exc}') from exc
    return pl.from_pandas(df)


def normalize_direct_code_result(result) -> pd.DataFrame:
    if isinstance(result, pd.DataFrame):
        return result
    if hasattr(result, 'to_pandas') and callable(result.to_pandas):
        return result.to_pandas()
    if hasattr(result, 'to_dicts') and callable(result.to_dicts):
        return pd.DataFrame(result.to_dicts())
    return result


def compute_factor_with_contract(module, daily_df: pd.DataFrame, minute_df: pd.DataFrame) -> pd.DataFrame:
    fn = getattr(module, 'compute_factor')
    daily_input = add_direct_code_alias_columns(daily_df)
    minute_input = add_direct_code_alias_columns(minute_df)
    use_polars = direct_code_expects_polars(module)
    daily_call_input = maybe_polars_frame(daily_input, use_polars)
    minute_call_input = maybe_polars_frame(minute_input, use_polars)
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        params = []
    positional = [
        p for p in params
        if p.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if len(positional) == 1:
        first = positional[0].name.lower()
        if 'daily' in first:
            return normalize_direct_code_result(fn(daily_call_input))
        if 'minute' in first or 'intraday' in first:
            return normalize_direct_code_result(fn(minute_call_input))
        chosen = minute_call_input if not minute_input.empty else daily_call_input
        return normalize_direct_code_result(fn(chosen))

    try:
        return normalize_direct_code_result(fn(daily_df=daily_call_input, minute_df=minute_call_input))
    except TypeError:
        if positional:
            first = positional[0].name.lower()
            if 'minute' in first:
                return normalize_direct_code_result(fn(minute_call_input, daily_call_input))
        return normalize_direct_code_result(fn(daily_call_input, minute_call_input))


def resolve_local_input_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return WORKSPACE / path


def read_df(path: Path):
    import pandas as pd

    if path.suffix.lower() == '.parquet':
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _default_formula_engine_profile() -> dict:
    return {
        'engine': 'pandas_formula_ir_reference_or_unknown',
        'reference_engine': 'pandas_formula_ir_reference',
        'memoization_enabled': False,
        'cache_hits': None,
        'cache_misses': None,
        'input_presorted': None,
        'output_presorted': None,
        'ts_rank_engine': None,
        'ts_rank_fast_path_enabled': False,
        'ts_rank_fast_path_count': 0,
        'ts_rank_fallback_count': 0,
        'ts_rank_fallback_reasons': [],
        'ts_rank_engine_profile': default_ts_rank_engine_profile(),
        'kernel_profile': default_kernel_profile(),
        'parity_checked': False,
        'parity_sample_rows': 0,
        'max_abs_diff': None,
        'rank_corr': None,
        'row_count_equal': None,
        'key_order_equal': None,
        'nan_mask_equal': None,
        'polars_enabled': False,
        'polars_used': False,
        'polars_fallback_used': False,
        'polars_fallback_reason': None,
        'operator_profile': {
            'version': 'factorforge_operator_profile_v1',
            'enabled': False,
            'total_profiled_seconds': 0.0,
            'event_count': 0,
            'by_operator': {},
            'top_events': [],
            'unprofiled_compute_seconds': None,
        },
        'parity_profile': {
            'enabled': False,
            'sample_rows': 0,
            'reference_seconds': None,
            'candidate_seconds': None,
            'compare_seconds': None,
            'max_abs_diff': None,
            'rank_corr': None,
        },
        'compute_factor_seconds': None,
        'normalize_sort_seconds': None,
    }


def _sample_formula_frame(frame, max_rows: int = 5000):
    if len(frame) <= max_rows:
        return frame.copy()
    working = frame.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    step = max(1, len(working) // max_rows)
    return working.iloc[::step].head(max_rows).reset_index(drop=True)


def _rank_corr(reference, optimized) -> float | None:
    import pandas as pd

    merged = reference[['ts_code', 'trade_date', 'factor_value']].merge(
        optimized[['ts_code', 'trade_date', 'factor_value']],
        on=['ts_code', 'trade_date'],
        how='inner',
        suffixes=('_reference', '_optimized'),
    )
    ref = pd.to_numeric(merged['factor_value_reference'], errors='coerce')
    opt = pd.to_numeric(merged['factor_value_optimized'], errors='coerce')
    valid = ref.notna() & opt.notna()
    if int(valid.sum()) < 2:
        return None
    corr = ref[valid].rank(method='average').corr(opt[valid].rank(method='average'), method='pearson')
    return float(corr) if pd.notna(corr) else None


def _formula_frame_parity_fields(reference, candidate) -> dict:
    ref_values = pd.to_numeric(reference['factor_value'], errors='coerce')
    cand_values = pd.to_numeric(candidate['factor_value'], errors='coerce')
    return {
        'row_count_equal': int(len(reference)) == int(len(candidate)),
        'key_order_equal': bool(
            reference[['ts_code', 'trade_date']].reset_index(drop=True).equals(
                candidate[['ts_code', 'trade_date']].reset_index(drop=True)
            )
        ),
        'nan_mask_equal': bool(ref_values.isna().reset_index(drop=True).equals(cand_values.isna().reset_index(drop=True))),
    }


def resolve_formula_engine(formula_engine: str | None = None) -> str:
    raw = formula_engine or os.getenv('FACTORFORGE_FORMULA_ENGINE')
    if raw is None and os.getenv('FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS') == '1':
        raw = 'polars_experimental'
    engine = str(raw or 'optimized').strip()
    aliases = {
        'pandas': 'optimized',
        'pandas_optimized': 'optimized',
        'pandas_formula_ir_optimized': 'optimized',
        'polars': 'polars_experimental',
        'polars_adaptive': 'adaptive',
        'adaptive_polars': 'adaptive',
    }
    engine = aliases.get(engine, engine)
    if engine not in {'optimized', 'polars_experimental', 'adaptive'}:
        raise SystemExit(f'BLOCK_UNSUPPORTED_FORMULA_ENGINE:{engine}')
    return engine


def select_adaptive_formula_engine(
    requested_engine: str,
    *,
    daily_path: Path | None,
    daily_parquet_path: Path | None,
    metadata: dict | None,
    formula_ir: dict | None,
) -> tuple[str, dict]:
    selector = {
        'version': 'factorforge_polars_adaptive_selector_v1',
        'requested_engine': requested_engine,
        'selected_engine': requested_engine,
        'reason': 'explicit_engine',
        'polars_candidate': False,
        'requires_lazy_parquet': True,
    }
    if requested_engine != 'adaptive':
        return requested_engine, selector

    selector['selected_engine'] = 'optimized'
    if os.getenv('FACTORFORGE_DISABLE_ADAPTIVE_POLARS') == '1':
        selector['reason'] = 'adaptive_polars_disabled'
        return 'optimized', selector
    if not isinstance(metadata, dict) or metadata.get('implementation_source') != 'formula_ir_pandas_codegen' or not isinstance(formula_ir, dict):
        selector['reason'] = 'non_formula_ir_codegen'
        return 'optimized', selector
    if daily_path is None or daily_parquet_path is None or daily_path != daily_parquet_path or daily_path.suffix.lower() != '.parquet':
        selector['reason'] = 'lazy_parquet_unavailable'
        return 'optimized', selector

    try:
        from factor_factory.formula.polars_evaluator import first_unsupported_operator, polars_dependency_available
    except ModuleNotFoundError:
        selector['reason'] = 'polars_dependency_missing'
        return 'optimized', selector

    unsupported = first_unsupported_operator(formula_ir)
    if unsupported is not None:
        selector['reason'] = f'unsupported_operator:{unsupported}'
        return 'optimized', selector
    if not polars_dependency_available():
        selector['reason'] = 'polars_dependency_missing'
        return 'optimized', selector

    selector.update({
        'selected_engine': 'polars_experimental',
        'reason': 'native_polars_lazy_parquet_supported',
        'polars_candidate': True,
    })
    return 'polars_experimental', selector


def resolve_operator_profile(operator_profile: bool | None = None) -> bool:
    if operator_profile is not None:
        return bool(operator_profile)
    return os.getenv('FACTORFORGE_ENABLE_OPERATOR_PROFILE') == '1'


def _run_formula_engine_with_profile(
    module,
    daily_df,
    formula_engine: str = 'optimized',
    operator_profile: bool = False,
    ts_rank_engine_config: dict | None = None,
    formula_kernel_config: dict | None = None,
    daily_parquet_path: Path | None = None,
    formula_ir_override: dict | None = None,
):
    metadata = getattr(module, 'METADATA', {}) if module is not None else {}
    formula_ir = formula_ir_override or getattr(module, 'FORMULA_IR', None)
    if not isinstance(metadata, dict) or metadata.get('implementation_source') != 'formula_ir_pandas_codegen' or not isinstance(formula_ir, dict):
        return None, _default_formula_engine_profile()

    sample = _sample_formula_frame(daily_df)
    reference_start = time.perf_counter()
    reference_sample = evaluate_formula_frame(formula_ir, sample, engine='reference')
    reference_seconds = time.perf_counter() - reference_start
    candidate_start = time.perf_counter()
    candidate_sample = evaluate_formula_frame(
        formula_ir,
        sample,
        engine=formula_engine,
        ts_rank_engine_config=ts_rank_engine_config,
        formula_kernel_config=formula_kernel_config,
    )
    candidate_seconds = time.perf_counter() - candidate_start
    compare_start = time.perf_counter()
    try:
        parity = compare_outputs(reference_sample, candidate_sample, tolerance=1e-12)
    except AssertionError as exc:
        if (formula_kernel_config or {}).get('experimental_enabled'):
            raise AssertionError(f'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED:{exc}') from exc
        if (ts_rank_engine_config or {}).get('selected_engine') != 'pandas_reference':
            raise AssertionError(f'BLOCK_EXPERIMENTAL_TS_RANK_PARITY_FAILED:{exc}') from exc
        raise
    rank_corr = _rank_corr(reference_sample, candidate_sample)
    parity_fields = _formula_frame_parity_fields(reference_sample, candidate_sample)
    if (ts_rank_engine_config or {}).get('selected_engine') != 'pandas_reference':
        if parity_fields.get('key_order_equal') is not True or parity_fields.get('nan_mask_equal') is not True:
            raise AssertionError(f'BLOCK_EXPERIMENTAL_TS_RANK_PARITY_FAILED:{parity_fields}')
    if (formula_kernel_config or {}).get('experimental_enabled'):
        if parity_fields.get('key_order_equal') is not True or parity_fields.get('nan_mask_equal') is not True:
            raise AssertionError(f'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED:{parity_fields}')
    compare_seconds = time.perf_counter() - compare_start
    if formula_engine == 'polars_experimental' and daily_parquet_path is not None and daily_parquet_path.suffix.lower() == '.parquet':
        from factor_factory.formula.polars_evaluator import evaluate_formula_parquet_polars_experimental

        profile_frame, formula_engine_profile = evaluate_formula_parquet_polars_experimental(
            formula_ir,
            daily_parquet_path,
            return_profile=True,
        )
    else:
        profile_frame, formula_engine_profile = evaluate_formula_frame(
            formula_ir,
            daily_df,
            engine=formula_engine,
            return_profile=True,
            operator_profile_enabled=operator_profile,
            ts_rank_engine_config=ts_rank_engine_config,
            formula_kernel_config=formula_kernel_config,
        )
    ts_rank_profile = formula_engine_profile.get('ts_rank_engine_profile') or default_ts_rank_engine_profile(ts_rank_engine_config)
    ts_rank_profile.update({
        'parity_checked': bool((ts_rank_engine_config or {}).get('selected_engine') != 'pandas_reference'),
        'parity_sample_rows': int(parity.get('row_count') or len(sample)),
        'parity_max_abs_diff': float(parity.get('max_abs_diff') or 0.0),
        'parity_nan_mask_equal': parity_fields.get('nan_mask_equal'),
        'parity_key_order_equal': parity_fields.get('key_order_equal'),
    })
    kernel_profile = formula_engine_profile.get('kernel_profile') or default_kernel_profile(formula_kernel_config)
    kernel_profile.update({
        'parity_checked': bool((formula_kernel_config or {}).get('selected_engine') != 'pandas_reference'),
        'parity_sample_rows': int(parity.get('row_count') or len(sample)),
        'parity_max_abs_diff': float(parity.get('max_abs_diff') or 0.0),
        'parity_nan_mask_equal': parity_fields.get('nan_mask_equal'),
        'parity_key_order_equal': parity_fields.get('key_order_equal'),
        'safe_to_make_default': False,
    })
    formula_engine_profile = {
        **_default_formula_engine_profile(),
        **formula_engine_profile,
        'parity_checked': True,
        'parity_sample_rows': int(parity.get('row_count') or len(sample)),
        'max_abs_diff': float(parity.get('max_abs_diff') or 0.0),
        'rank_corr': rank_corr,
        **parity_fields,
        'ts_rank_engine_profile': ts_rank_profile,
        'kernel_profile': kernel_profile,
        'parity_profile': {
            'enabled': True,
            'sample_rows': int(parity.get('row_count') or len(sample)),
            'reference_seconds': float(reference_seconds),
            'candidate_seconds': float(candidate_seconds),
            'compare_seconds': float(compare_seconds),
            'max_abs_diff': float(parity.get('max_abs_diff') or 0.0),
            'rank_corr': rank_corr,
        },
    }
    return profile_frame, formula_engine_profile


def _query_payload(contract: dict, query_set: str, dataset_id: str) -> dict | None:
    queries = contract.get(query_set) if isinstance(contract, dict) else None
    if not isinstance(queries, dict):
        return None
    query = queries.get(dataset_id)
    return query if isinstance(query, dict) else None


def _fetch_data_api_frame(query: dict):
    result = fetch_data_api_dataset(
        str(query.get('dataset')),
        start=str(query.get('start_date')),
        end=str(query.get('end_date')),
        fields=list(query.get('fields') or []),
        universe=query.get('universe') or 'a_share_all',
        frequency=query.get('frequency'),
        catalog_path=query.get('catalog_path'),
    )
    if result.status not in {'ready', 'proxy_ready'}:
        raise SystemExit(f"BLOCK_STEP3B_DATA_API_SAMPLE_FETCH_FAILED: {query.get('dataset')} status={result.status} reason={result.blocked_reason}")
    return result.frame, result.to_metadata()


def _load_step3b_sample_inputs(local_inputs: dict, step4_data_contract: dict | None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_parquet_rel = local_inputs.get('daily_df_parquet')
    daily_csv_rel = local_inputs.get('daily_df_csv')
    daily_rel = daily_parquet_rel or daily_csv_rel
    input_mode = str(local_inputs.get('input_mode') or '')
    minute_required = input_mode != 'daily_only'
    minute_path = resolve_local_input_path(minute_rel)
    daily_path = resolve_local_input_path(daily_rel)
    daily_parquet_path = resolve_local_input_path(daily_parquet_rel)
    daily_csv_path = resolve_local_input_path(daily_csv_rel)

    if daily_path is not None and daily_path.exists() and (not minute_required or (minute_path is not None and minute_path.exists())):
        minute_df = read_df(minute_path) if minute_path is not None else pd.DataFrame()
        daily_df = read_df(daily_path)
        profile = {
            'source': 'step3a_local_snapshot_compat',
            'daily_selected_format': 'parquet' if daily_path.suffix.lower() == '.parquet' else 'csv',
            'daily_selected_path': str(daily_path),
            'daily_parquet_path': str(daily_parquet_path) if daily_parquet_path else None,
            'daily_csv_path': str(daily_csv_path) if daily_csv_path else None,
            'minute_selected_path': str(minute_path) if minute_path else None,
            'data_api_sample_metadata': {},
        }
        return daily_df, minute_df, profile

    contract = step4_data_contract or local_inputs.get('step4_data_contract') or {}
    daily_query = _query_payload(contract, 'sample_queries', 'clean_daily_bar')
    minute_query = _query_payload(contract, 'sample_queries', 'minute_bar')
    if not daily_query:
        raise SystemExit('BLOCK_STEP3B_SAMPLE_DATA_CONTRACT_MISSING: clean_daily_bar sample query is required')
    if contract.get('catalog_path'):
        daily_query = {**daily_query, 'catalog_path': contract.get('catalog_path')}
        if minute_query:
            minute_query = {**minute_query, 'catalog_path': contract.get('catalog_path')}
    daily_df, daily_meta = _fetch_data_api_frame(daily_query)
    if minute_required and minute_query:
        minute_df, minute_meta = _fetch_data_api_frame(minute_query)
    else:
        minute_df, minute_meta = pd.DataFrame(), None
    profile = {
        'source': 'factorforge_data_api_sample',
        'daily_selected_format': 'data_api_frame',
        'daily_selected_path': None,
        'daily_parquet_path': None,
        'daily_csv_path': None,
        'minute_selected_path': None,
        'data_api_sample_metadata': {
            'clean_daily_bar': daily_meta,
            **({'minute_bar': minute_meta} if minute_meta else {}),
        },
    }
    return daily_df, minute_df, profile


def generate_first_run_factor_values(
    report_id: str,
    factor_id: str,
    implementation_path: Path,
    local_inputs: dict,
    step2_research_context: dict,
    mode_decision: dict | None = None,
    artifact_identity: dict | None = None,
    csv_output_policy: str | None = None,
    formula_engine: str | None = None,
    operator_profile: bool | None = None,
    ts_rank_engine: str | None = None,
    formula_kernel_engine: str | None = None,
    trust_step3a_sort_contract: bool | None = None,
    step4_data_contract: dict | None = None,
) -> dict:
    """Run only a non-formal sample proof of the factor implementation.

    Step3B may prove executability and schema completeness on a small Data API
    sample. It must not create formal factor_values; Step4 owns full data
    retrieval and the formal factor_values artifact.
    """
    csv_policy = resolve_csv_policy(csv_output_policy)
    trust_sort_contract = resolve_trust_step3a_sort_contract(trust_step3a_sort_contract)
    requested_formula_engine = resolve_formula_engine(formula_engine)
    selected_formula_engine = requested_formula_engine
    adaptive_selector_profile = {
        'version': 'factorforge_polars_adaptive_selector_v1',
        'requested_engine': requested_formula_engine,
        'selected_engine': selected_formula_engine,
        'reason': 'explicit_engine',
        'polars_candidate': False,
        'requires_lazy_parquet': True,
    }
    operator_profile_enabled = resolve_operator_profile(operator_profile)
    try:
        ts_rank_engine_config = resolve_formula_ts_rank_engine(ts_rank_engine)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        formula_kernel_config = resolve_formula_kernel_engine(formula_kernel_engine)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    timer = PhaseTimer()

    module = import_module_from_path(implementation_path)
    if not hasattr(module, 'compute_factor'):
        raise SystemExit(f'Step3B implementation missing compute_factor(): {implementation_path}')
    metadata = getattr(module, 'METADATA', {}) if module is not None else {}
    source_profile = assert_high_speed_code_policy(
        implementation_path.read_text(encoding='utf-8'),
        metadata if isinstance(metadata, dict) else {},
    )
    module_formula_ir = getattr(module, 'FORMULA_IR', None)
    daily_path = None
    daily_parquet_path = None
    selected_formula_engine, adaptive_selector_profile = select_adaptive_formula_engine(
        requested_formula_engine,
        daily_path=daily_path,
        daily_parquet_path=daily_parquet_path,
        metadata=metadata if isinstance(metadata, dict) else None,
        formula_ir=module_formula_ir if isinstance(module_formula_ir, dict) else None,
    )
    use_lazy_polars_parquet = bool(
        selected_formula_engine == 'polars_experimental'
        and daily_path == daily_parquet_path
        and daily_path is not None
        and daily_path.suffix.lower() == '.parquet'
        and isinstance(metadata, dict)
        and metadata.get('implementation_source') == 'formula_ir_pandas_codegen'
        and isinstance(module_formula_ir, dict)
    )
    lazy_polars_formula_ir = None

    with timer.phase('read_inputs'):
        daily_df, minute_df, input_io_profile = _load_step3b_sample_inputs(local_inputs, step4_data_contract)
        if use_lazy_polars_parquet:
            try:
                from factor_factory.formula.polars_evaluator import read_formula_parquet_sample_for_polars_parity

                daily_parquet_path = Path(input_io_profile.get('daily_parquet_path')) if input_io_profile.get('daily_parquet_path') else None
                if daily_parquet_path is None:
                    use_lazy_polars_parquet = False
                else:
                    daily_df, lazy_polars_formula_ir = read_formula_parquet_sample_for_polars_parity(module_formula_ir, daily_parquet_path)
            except ModuleNotFoundError as exc:
                if 'BLOCK_POLARS_EXPERIMENTAL_DEPENDENCY_MISSING' in str(exc):
                    raise SystemExit('BLOCK_POLARS_EXPERIMENTAL_DEPENDENCY_MISSING') from exc
                raise
            except (KeyError, ValueError) as exc:
                message = str(exc)
                if 'BLOCK_POLARS_EXPERIMENTAL_' in message or 'BLOCK_UNSUPPORTED_FORMULA_SYNTAX' in message:
                    raise SystemExit(message) from exc
                raise
    minute_input_row_count = int(len(minute_df))
    daily_input_row_count = int(len(daily_df))
    input_row_count = int(minute_input_row_count + daily_input_row_count)

    formula_engine_profile = _default_formula_engine_profile()
    with timer.phase('compute_factor'):
        try:
            profiled_result, formula_engine_profile = _run_formula_engine_with_profile(
                module,
                daily_df,
                formula_engine=selected_formula_engine,
                operator_profile=operator_profile_enabled,
                ts_rank_engine_config=ts_rank_engine_config,
                formula_kernel_config=formula_kernel_config,
                daily_parquet_path=Path(input_io_profile['daily_parquet_path']) if input_io_profile.get('daily_parquet_path') else None,
                formula_ir_override=lazy_polars_formula_ir,
            )
            if profiled_result is not None:
                result_df = profiled_result
            else:
                result_df = compute_factor_with_contract(module, daily_df, minute_df)
        except ModuleNotFoundError as exc:
            if 'BLOCK_POLARS_EXPERIMENTAL_DEPENDENCY_MISSING' in str(exc):
                raise SystemExit('BLOCK_POLARS_EXPERIMENTAL_DEPENDENCY_MISSING') from exc
            raise
        except AssertionError as exc:
            message = str(exc)
            if 'BLOCK_POLARS_EXPERIMENTAL_PARITY_FAILED' in message:
                raise SystemExit(message) from exc
            if 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_PARITY_FAILED' in message:
                raise SystemExit(message) from exc
            if 'BLOCK_EXPERIMENTAL_TS_RANK_PARITY_FAILED' in message:
                raise SystemExit(message) from exc
            raise SystemExit(f'BLOCK_FORMULA_ENGINE_PARITY_FAILED: {exc}') from exc
        except RuntimeError as exc:
            message = str(exc)
            if 'BLOCK_EXPERIMENTAL_FORMULA_KERNEL_' in message:
                raise SystemExit(message) from exc
            if 'BLOCK_EXPERIMENTAL_TS_RANK_' in message:
                raise SystemExit(message) from exc
            raise
        except ValueError as exc:
            message = str(exc)
            if 'BLOCK_POLARS_EXPERIMENTAL_' in message or 'BLOCK_UNSUPPORTED_FORMULA_SYNTAX' in message:
                raise SystemExit(message) from exc
            raise
    formula_engine_profile['adaptive_selector'] = adaptive_selector_profile
    if result_df is None or len(result_df) == 0:
        raise SystemExit('Step3B sample implementation returned empty factor values')
    if not {'ts_code', 'trade_date'}.issubset(result_df.columns):
        raise SystemExit('Step3B sample output must include ts_code and trade_date')

    with timer.phase('normalize_sort'):
        signal_col = infer_signal_column(result_df, factor_id=factor_id)
        result_df = result_df[['ts_code', 'trade_date', signal_col]]
        result_df['trade_date'] = normalize_trade_date_series(result_df['trade_date']).dt.strftime('%Y%m%d')
        sort_contract = extract_sort_contract(local_inputs)
        normalize_sort_profile = validate_sort_contract_for_skip(
            contract=sort_contract,
            daily_df=daily_df,
            result_df=result_df,
            opt_in_enabled=trust_sort_contract,
        )
        if normalize_sort_profile.get('full_sort_skipped') is True:
            already_sorted = True
            result_df = result_df.reset_index(drop=True)
        else:
            keys = result_df[['ts_code', 'trade_date']]
            sorted_keys = keys.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
            already_sorted = bool(keys.reset_index(drop=True).equals(sorted_keys))
            if already_sorted:
                result_df = result_df.reset_index(drop=True)
            else:
                result_df = result_df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        formula_engine_profile['output_presorted'] = bool(already_sorted or formula_engine_profile.get('output_presorted') is True)

    run_dir = RUNS / report_id
    run_dir.mkdir(parents=True, exist_ok=True)
    factor_parquet = run_dir / f'step3b_sample_factor_values__{report_id}.parquet'
    factor_csv = run_dir / f'step3b_sample_factor_values__{report_id}.csv'
    factor_csv_sample = run_dir / f'step3b_sample_factor_values_sample__{report_id}.csv'
    run_meta = run_dir / f'step3b_sample_run_metadata__{report_id}.json'
    for stale_csv in [factor_csv, factor_csv_sample]:
        if stale_csv.exists() or stale_csv.is_symlink():
            stale_csv.unlink()
    with timer.phase('write_parquet'):
        result_df.to_parquet(factor_parquet, index=False)
    with timer.phase('write_csv'):
        if csv_policy == 'full_csv':
            result_df.to_csv(factor_csv, index=False)
            csv_path = factor_csv
            csv_sample_path = None
            csv_rows_written = int(len(result_df))
            csv_sample_strategy = 'full'
            full_csv_available = True
        elif csv_policy == 'sample_csv':
            sample_df = deterministic_csv_sample(result_df)
            sample_df.to_csv(factor_csv_sample, index=False)
            csv_path = None
            csv_sample_path = factor_csv_sample
            csv_rows_written = int(len(sample_df))
            csv_sample_strategy = 'head_tail'
            full_csv_available = False
        else:
            csv_path = None
            csv_sample_path = None
            csv_rows_written = 0
            csv_sample_strategy = 'none'
            full_csv_available = False
    phase_seconds = timer.finish()
    formula_engine_profile['compute_factor_seconds'] = float(phase_seconds.get('compute_factor') or 0.0)
    formula_engine_profile['normalize_sort_seconds'] = float(phase_seconds.get('normalize_sort') or 0.0)
    operator_profile_payload = formula_engine_profile.get('operator_profile')
    if isinstance(operator_profile_payload, dict):
        operator_profile_payload['unprofiled_compute_seconds'] = max(
            0.0,
            float(phase_seconds.get('compute_factor') or 0.0) - float(operator_profile_payload.get('total_profiled_seconds') or 0.0),
        )
        formula_engine_profile['operator_profile'] = operator_profile_payload
    result_columns = list(result_df.columns)
    sample_schema_parity = None
    if csv_sample_path:
        sample_schema_parity = list(pd.read_csv(csv_sample_path, nrows=0).columns) == result_columns
    elif csv_path:
        sample_schema_parity = list(pd.read_csv(csv_path, nrows=0).columns) == result_columns
    full_csv_absent_validated = csv_policy in {'sample_csv', 'no_csv'} and not factor_csv.exists()
    csv_output_profile = {
        'version': 'factorforge_csv_output_profile_v1',
        'formal_evidence_format': None,
        'sample_evidence_format': 'parquet',
        'csv_output_policy': csv_policy,
        'factor_parquet_path': str(factor_parquet),
        'factor_csv_path': str(csv_path) if csv_path else None,
        'factor_sample_csv_path': str(csv_sample_path) if csv_sample_path else None,
        'sample_schema_parity': sample_schema_parity,
        'full_csv_absent_validated': bool(full_csv_absent_validated),
        'full_csv_absence_reason': f'step3b_{csv_policy}_policy' if csv_policy in {'sample_csv', 'no_csv'} else None,
        'parquet_rows_written': int(len(result_df)),
        'csv_rows_written': int(csv_rows_written),
        'csv_sample_strategy': csv_sample_strategy,
        'full_csv_available': bool(full_csv_available),
        # Legacy aliases retained for existing Step4/profiler consumers.
        'csv_path': str(csv_path) if csv_path else None,
        'csv_sample_path': str(csv_sample_path) if csv_sample_path else None,
        'write_csv_seconds': float(phase_seconds.get('write_csv') or 0.0),
    }
    output_paths = [str(factor_parquet.relative_to(FF))]
    if csv_path:
        output_paths.append(str(csv_path.relative_to(FF)))
    if csv_sample_path:
        output_paths.append(str(csv_sample_path.relative_to(FF)))

    metadata = {
        'report_id': report_id,
        'factor_id': factor_id,
        'artifact_identity': derive_child_identity(artifact_identity or {}, artifact_role='step3b_sample_run_metadata', producer='step3b_sample_proof') if artifact_identity else None,
        'producer': 'step3b_sample_proof',
        'is_formal_factor_values': False,
        'purpose': 'step3_executability_proof',
        'formal_factor_values_owner': 'Step4',
        'implementation_path': str(implementation_path),
        'signal_column': signal_col,
        'row_count': int(len(result_df)),
        'date_count': int(result_df['trade_date'].nunique()),
        'ticker_count': int(result_df['ts_code'].nunique()),
        'actual_window': {
            'start': str(result_df['trade_date'].min()),
            'end': str(result_df['trade_date'].max()),
        },
        'input_paths': {
            'minute': input_io_profile.get('minute_selected_path'),
            'daily': input_io_profile.get('daily_selected_path'),
        },
        'step4_data_contract': step4_data_contract or local_inputs.get('step4_data_contract') or {},
        'step2_research_context': step2_research_context,
        'implementation_mode_decision': mode_decision,
        'created_at_utc': utc_now(),
        'boundary_note': 'Step3B produced only non-formal sample factor values; Step4 owns full data fetch, formal factor_values, IC/NAV/backtest evaluation.',
        'performance_profile': {
            'version': 'factorforge_step3b_performance_profile_v1',
            'row_count': int(len(result_df)),
            'phase_seconds': phase_seconds,
            'input_io_profile': {
                **input_io_profile,
            },
            'normalize_sort': {
                'already_sorted': bool(already_sorted),
                'full_sort_skipped': bool(normalize_sort_profile.get('full_sort_skipped')),
                'fallback_reason': normalize_sort_profile.get('fallback_reason'),
            },
            'normalize_sort_profile': normalize_sort_profile,
            'source_code_performance_profile': source_profile,
            'input_row_count': input_row_count,
            'minute_input_row_count': minute_input_row_count,
            'daily_input_row_count': daily_input_row_count,
            'rows_per_second_compute': float(len(result_df) / phase_seconds['compute_factor']) if phase_seconds.get('compute_factor') else None,
            'rows_per_second_input_compute': float(input_row_count / phase_seconds['compute_factor']) if phase_seconds.get('compute_factor') else None,
            'formula_engine_profile': formula_engine_profile,
            'output_bytes': {
                'parquet': safe_file_size(factor_parquet),
                'csv': safe_file_size(factor_csv),
                'csv_sample': safe_file_size(factor_csv_sample),
            },
            'csv_output_profile': csv_output_profile,
        },
    }
    write_json(run_meta, metadata)

    return {
        'status': 'ready',
        'output_paths': output_paths,
        'csv_output_profile': csv_output_profile,
        'run_metadata_path': str(run_meta.relative_to(FF)),
        'producer': 'step3b_sample_proof',
        'is_formal_factor_values': False,
        'purpose': 'step3_executability_proof',
        'formal_factor_values_owner': 'Step4',
        'signal_column': signal_col,
        'row_count': int(len(result_df)),
        'date_count': int(result_df['trade_date'].nunique()),
        'ticker_count': int(result_df['ts_code'].nunique()),
    }


def signal_column_name(factor_id: str | None) -> str:
    raw = re.sub(r'[^0-9a-zA-Z]+', '_', str(factor_id or '').strip().lower()).strip('_') or 'factor'
    return raw if raw.endswith('_factor') else f'{raw}_factor'


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
    candidate_keys = [
        'available_columns',
        'clean_data_columns',
        'daily_columns',
        'daily_df_columns',
        'resolved_columns',
    ]
    for key in candidate_keys:
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
    suffix = path.suffix.lower()
    if suffix == '.parquet':
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
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    columns: set[str] = set()
    for raw in [daily_rel, minute_rel]:
        path = resolve_local_input_path(raw)
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


def pending_first_run_outputs(reason: str) -> dict:
    return {
        'status': 'pending',
        'no_first_run_reason': reason,
        'factor_values_path': None,
        'output_paths': [],
        'run_metadata_path': None,
        'producer': 'step3b',
    }


def build_operator_artifacts(report_id: str, prep: dict, spec: dict, identity: dict):
    canonical = spec.get('canonical_spec') or {}
    factor_id = spec.get('factor_id') or report_id
    formula_ir = canonical.get('formula_ir')
    if not isinstance(formula_ir, dict):
        raise SystemExit('BLOCK_UNSUPPORTED_OPERATOR_MODE: operator Step3B requires formula_ir.')
    if formula_ir.get('parse_status') != 'success':
        raise SystemExit(
            'BLOCK_UNSUPPORTED_FORMULA_SYNTAX: '
            + '; '.join(str(item) for item in (formula_ir.get('parse_errors') or ['formula_ir parse failed']))
        )
    operator_schema = infer_operator_schema(prep)
    try:
        resolved_ir = resolve_formula_fields_for_schema(formula_ir, operator_schema['columns'])
    except Exception as exc:
        raise SystemExit(str(exc)) from exc
    for operator in resolved_ir.get('operator_set') or []:
        meta = operator_meta(str(operator))
        if meta.get('supports_pandas') is not True:
            raise SystemExit(f'BLOCK_UNSUPPORTED_PANDAS_OPERATOR: {operator}')
    if identity.get('formula_hash') and identity.get('formula_hash') != resolved_ir.get('formula_hash'):
        raise SystemExit(
            'BLOCK_OPERATOR_FORMULA_HASH_MISMATCH: '
            f"identity={identity.get('formula_hash')} formula_ir={resolved_ir.get('formula_hash')}"
        )

    qlib_expression = to_qlib_expression(resolved_ir)
    metadata = {
        **operator_metadata(resolved_ir),
        'implementation_mode': 'operator',
        'implementation_source': 'formula_ir_pandas_codegen',
        'qlib_expression': qlib_expression,
    }
    python_stub = generate_pandas_formula_code(report_id=report_id, factor_id=factor_id, formula_ir=resolved_ir)
    implementation_plan = {
        'report_id': report_id,
        'factor_id': factor_id,
        'producer': 'step3b_operator_formula_codegen',
        'implementation_mode': 'operator',
        'implementation_status': 'ready',
        'formula_ir': resolved_ir,
        'formula_hash': resolved_ir.get('formula_hash'),
        'operator_set': resolved_ir.get('operator_set') or [],
        'required_fields': resolved_ir.get('required_fields') or [],
        'resolved_fields': resolved_ir.get('resolved_fields') or {},
        'operator_schema': operator_schema,
        'qlib_expression': qlib_expression,
        'metadata': metadata,
        'output_schema': {'columns': ['ts_code', 'trade_date', 'factor_value']},
        'step4_contract': {
            'execution_mode': 'operator',
            'runner_entry': None,
            'expected_outputs': ['factor_values'],
        },
        'first_run_outputs': pending_first_run_outputs('no_local_snapshots_available'),
    }
    qlib_payload = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'operator',
        'implementation_source': 'formula_ir_pandas_codegen',
        'formula_ir': resolved_ir,
        'operator_schema': operator_schema,
        'qlib_expression': qlib_expression,
        'metadata': metadata,
    }
    hybrid_scaffold = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'operator',
        'implementation_source': 'formula_ir_pandas_codegen',
        'formula_ir': resolved_ir,
        'operator_schema': operator_schema,
        'hybrid_status': 'not_applicable_operator_only',
        'boundary': {
            'operator_outputs': ['factor_value'],
            'custom_inputs': [],
            'custom_outputs': [],
        },
        'metadata': metadata,
    }
    return implementation_plan, python_stub, qlib_payload, hybrid_scaffold


def _block_source(block: dict) -> str:
    return str(block.get('source_code') or block.get('code') or block.get('custom_source') or '')


def _custom_block_hash(block: dict) -> str:
    source_code = _block_source(block)
    normalized = dict(block)
    normalized['source_code'] = source_code
    normalized.pop('custom_block_hash', None)
    return stable_hash({'source_code': source_code, 'contract': normalized})


def _scan_custom_block_source(block: dict) -> None:
    source = _block_source(block)
    if not source.strip():
        raise SystemExit('BLOCK_INVALID_HYBRID_CONTRACT: custom block source_code missing')
    patterns = list(dict.fromkeys(FORBIDDEN_CUSTOM_BLOCK_PATTERNS + [str(p) for p in (block.get('forbidden_patterns') or []) if p]))
    hits = []
    for pattern in patterns:
        try:
            regex = re.compile(pattern, flags=re.IGNORECASE)
        except re.error as exc:
            raise SystemExit(
                f'BLOCK_HYBRID_CUSTOM_BLOCK_INVALID_FORBIDDEN_PATTERN: pattern={pattern!r}, error={exc}'
            ) from exc
        for lineno, line in enumerate(source.splitlines(), start=1):
            if regex.search(line):
                hits.append({'pattern': pattern, 'line': lineno, 'text': line.strip()[:180]})
    if hits:
        raise SystemExit(f'BLOCK_HYBRID_CUSTOM_BLOCK_LEAKAGE_PATTERN: {hits}')


def _assert_no_operator_output_overwrite(custom_blocks: list[dict], boundary: dict) -> None:
    if boundary.get('allow_operator_output_overwrite') is True:
        return
    protected = set(boundary.get('protected_operator_outputs') or boundary.get('operator_outputs') or ['operator_value'])
    for block in custom_blocks:
        source = _block_source(block)
        for name in protected:
            patterns = [
                rf'\[[^\n\]]*["\']{re.escape(name)}["\'][^\n\]]*\]\s*=',
                rf'\.loc\[[^\n]*["\']{re.escape(name)}["\'][^\n]*\]\s*=',
                rf'\.assign\([^\n)]*{re.escape(name)}\s*=',
            ]
            if any(re.search(pattern, source) for pattern in patterns):
                raise SystemExit(f'BLOCK_HYBRID_OPERATOR_OUTPUT_OVERWRITE: {name}')


def _assert_hybrid_contract(spec: dict, identity: dict) -> dict:
    contract = spec.get('implementation_contract') or {}
    if contract.get('hybrid_contract_version') != HYBRID_CONTRACT_VERSION:
        raise SystemExit(f'BLOCK_INVALID_HYBRID_CONTRACT: hybrid_contract_version must be {HYBRID_CONTRACT_VERSION}')
    operator_subgraph = contract.get('operator_subgraph') or {}
    formula_ir = operator_subgraph.get('formula_ir') if isinstance(operator_subgraph.get('formula_ir'), dict) else {}
    custom_blocks = contract.get('custom_blocks') or []
    boundary = contract.get('boundary') or {}
    if not operator_subgraph or not formula_ir:
        raise SystemExit('BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph.formula_ir missing')
    if formula_ir.get('parse_status') != 'success':
        raise SystemExit(f"BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph formula_ir parse failed {formula_ir.get('parse_errors')}")
    if not isinstance(custom_blocks, list) or not custom_blocks:
        raise SystemExit('BLOCK_INVALID_HYBRID_CONTRACT: custom_blocks missing')
    if not isinstance(boundary, dict) or not boundary:
        raise SystemExit('BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING')
    required_hashes = ['formula_hash', 'custom_block_hash', 'hybrid_hash']
    missing = [key for key in required_hashes if not contract.get(key) or not identity.get(key)]
    if missing:
        raise SystemExit(f'BLOCK_INVALID_HYBRID_CONTRACT: missing hashes {missing}')
    for key in required_hashes:
        if contract.get(key) != identity.get(key):
            raise SystemExit(f'BLOCK_HYBRID_HASH_MISMATCH: {key} identity={identity.get(key)} contract={contract.get(key)}')
    return contract


def _validate_hybrid_hashes(contract: dict, resolved_ir: dict) -> None:
    formula_hash = resolved_ir.get('formula_hash')
    if formula_hash != contract.get('formula_hash'):
        raise SystemExit(f'BLOCK_HYBRID_HASH_MISMATCH: formula_hash {formula_hash} != {contract.get("formula_hash")}')
    block_hash_inputs = []
    for block in contract.get('custom_blocks') or []:
        actual = _custom_block_hash(block)
        declared = block.get('custom_block_hash')
        if declared and actual != declared:
            raise SystemExit(f'BLOCK_HYBRID_HASH_MISMATCH: custom block {block.get("name")} hash mismatch')
        block_hash_inputs.append({'name': block.get('name'), 'custom_block_hash': declared or actual})
    actual_custom_hash = stable_hash(block_hash_inputs)
    if actual_custom_hash != contract.get('custom_block_hash'):
        raise SystemExit(f'BLOCK_HYBRID_HASH_MISMATCH: custom_block_hash {actual_custom_hash} != {contract.get("custom_block_hash")}')
    actual_hybrid_hash = stable_hash({
        'formula_hash': contract.get('formula_hash'),
        'custom_block_hash': contract.get('custom_block_hash'),
        'boundary': contract.get('boundary') or {},
    })
    if actual_hybrid_hash != contract.get('hybrid_hash'):
        raise SystemExit(f'BLOCK_HYBRID_HASH_MISMATCH: hybrid_hash {actual_hybrid_hash} != {contract.get("hybrid_hash")}')


def generate_hybrid_code(*, report_id: str, factor_id: str, formula_ir: dict, custom_block: dict, boundary: dict, contract: dict) -> str:
    formula_ir_literal = json.dumps(formula_ir, ensure_ascii=False, sort_keys=True, indent=2)
    source = _block_source(custom_block).rstrip()
    function_name = custom_block.get('function_name') or 'apply_custom_block'
    return f'''from __future__ import annotations

import pandas as pd

from factor_factory.formula.evaluator import evaluate_formula_frame


REPORT_ID = {report_id!r}
FACTOR_ID = {factor_id!r}
FORMULA_IR = {formula_ir_literal}
BOUNDARY = {boundary!r}
HYBRID_METADATA = {{'hybrid_contract_version': {contract.get('hybrid_contract_version')!r}, 'formula_hash': {contract.get('formula_hash')!r}, 'custom_block_hash': {contract.get('custom_block_hash')!r}, 'hybrid_hash': {contract.get('hybrid_hash')!r}}}


# <FACTORFORGE_OPERATOR_SUBGRAPH_BEGIN>
def compute_operator_subgraph(daily_df: pd.DataFrame) -> pd.DataFrame:
    operator_df = evaluate_formula_frame(FORMULA_IR, daily_df)
    return operator_df.rename(columns={{"factor_value": "operator_value"}})
# <FACTORFORGE_OPERATOR_SUBGRAPH_END>


# <FACTORFORGE_CUSTOM_BLOCK_BEGIN>
{source}
# <FACTORFORGE_CUSTOM_BLOCK_END>


def compute_factor(daily_df: pd.DataFrame, minute_df: pd.DataFrame | None = None) -> pd.DataFrame:
    operator_df = compute_operator_subgraph(daily_df)
    out = {function_name}(operator_df, daily_df)
    return out
'''


def _smoke_hybrid_code(python_stub: str, formula_ir: dict) -> None:
    namespace: dict = {}
    exec(compile(python_stub, '<hybrid_codegen_smoke>', 'exec'), namespace)
    compute_operator = namespace.get('compute_operator_subgraph')
    compute_factor = namespace.get('compute_factor')
    if not callable(compute_operator):
        raise SystemExit('BLOCK_HYBRID_OPERATOR_PARITY_FAILED: compute_operator_subgraph missing')
    if not callable(compute_factor):
        raise SystemExit('BLOCK_HYBRID_COMBINED_SMOKE_FAILED: compute_factor missing')
    fixture = make_operator_fixture()
    fixture['is_tradable'] = [idx % 2 == 0 for idx in range(len(fixture))]
    fixture['custom_scale'] = 2.0
    fixture['universe_flag'] = [1 if idx % 3 else 0 for idx in range(len(fixture))]
    reference = evaluate_formula_frame(formula_ir, fixture).rename(columns={'factor_value': 'operator_value'})
    generated_operator = compute_operator(fixture.copy())
    if 'operator_value' not in generated_operator.columns:
        raise SystemExit('BLOCK_HYBRID_OPERATOR_PARITY_FAILED: operator output missing operator_value')
    try:
        compare_outputs(
            reference.rename(columns={'operator_value': 'factor_value'}),
            generated_operator.rename(columns={'operator_value': 'factor_value'}),
        )
    except AssertionError as exc:
        raise SystemExit(f'BLOCK_HYBRID_OPERATOR_PARITY_FAILED: {exc}') from exc
    combined = compute_factor(daily_df=fixture.copy(), minute_df=None)
    required = {'ts_code', 'trade_date', 'factor_value'}
    if not hasattr(combined, 'columns'):
        raise SystemExit('BLOCK_HYBRID_COMBINED_SMOKE_FAILED: output is not DataFrame-like')
    if len(combined) <= 0:
        raise SystemExit('BLOCK_HYBRID_COMBINED_SMOKE_FAILED: output row count must be positive')
    missing = required - set(combined.columns)
    if missing:
        raise SystemExit(f'BLOCK_HYBRID_COMBINED_SMOKE_FAILED: output missing {sorted(missing)}')


def build_hybrid_artifacts(report_id: str, prep: dict, spec: dict, identity: dict):
    contract = _assert_hybrid_contract(spec, identity)
    operator_subgraph = contract.get('operator_subgraph') or {}
    formula_ir = operator_subgraph.get('formula_ir') or {}
    operator_schema = infer_operator_schema(prep)
    try:
        resolved_ir = resolve_formula_fields_for_schema(formula_ir, operator_schema['columns'])
    except Exception as exc:
        raise SystemExit(str(exc)) from exc
    for operator in resolved_ir.get('operator_set') or []:
        meta = operator_meta(str(operator))
        if meta.get('supports_pandas') is not True:
            raise SystemExit(f'BLOCK_UNSUPPORTED_PANDAS_OPERATOR: {operator}')
    custom_blocks = contract.get('custom_blocks') or []
    for block in custom_blocks:
        _scan_custom_block_source(block)
    boundary = contract.get('boundary') or {}
    _assert_no_operator_output_overwrite(custom_blocks, boundary)
    if not boundary.get('operator_outputs') or not boundary.get('custom_inputs') or not boundary.get('custom_outputs'):
        raise SystemExit('BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING')
    if not set(boundary.get('operator_outputs') or []).issubset(set(boundary.get('custom_inputs') or [])):
        raise SystemExit('BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: custom_inputs must include operator_outputs')
    if 'factor_value' not in set(boundary.get('custom_outputs') or []):
        raise SystemExit('BLOCK_HYBRID_BOUNDARY_SCHEMA_MISSING: custom_outputs must include factor_value')
    _validate_hybrid_hashes(contract, resolved_ir)
    factor_id = spec.get('factor_id') or report_id
    qlib_expression = to_qlib_expression(resolved_ir)
    python_stub = generate_hybrid_code(
        report_id=report_id,
        factor_id=factor_id,
        formula_ir=resolved_ir,
        custom_block=custom_blocks[0],
        boundary=boundary,
        contract=contract,
    )
    _smoke_hybrid_code(python_stub, resolved_ir)
    metadata = {
        **operator_metadata(resolved_ir),
        'implementation_mode': 'hybrid',
        'implementation_source': 'hybrid_formula_ir_custom_block_codegen',
        'operator_schema': operator_schema,
        'formula_hash': contract.get('formula_hash'),
        'custom_block_hash': contract.get('custom_block_hash'),
        'hybrid_hash': contract.get('hybrid_hash'),
        'boundary': boundary,
        'custom_blocks': custom_blocks,
        'qlib_expression': qlib_expression,
    }
    implementation_plan = {
        'report_id': report_id,
        'factor_id': factor_id,
        'producer': 'step3b_hybrid_codegen',
        'implementation_mode': 'hybrid',
        'implementation_status': 'ready',
        'hybrid_contract_version': HYBRID_CONTRACT_VERSION,
        'operator_subgraph': {**operator_subgraph, 'formula_ir': resolved_ir},
        'custom_blocks': custom_blocks,
        'boundary': boundary,
        'formula_hash': contract.get('formula_hash'),
        'custom_block_hash': contract.get('custom_block_hash'),
        'hybrid_hash': contract.get('hybrid_hash'),
        'metadata': metadata,
        'output_schema': custom_blocks[0].get('output_schema') or {'columns': ['ts_code', 'trade_date', 'factor_value']},
        'step4_contract': {
            'execution_mode': 'hybrid',
            'runner_entry': None,
            'expected_outputs': ['factor_values'],
        },
        'first_run_outputs': pending_first_run_outputs('no_local_snapshots_available'),
    }
    qlib_payload = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'hybrid',
        'implementation_source': 'hybrid_formula_ir_custom_block_codegen',
        'formula_ir': resolved_ir,
        'operator_subgraph': implementation_plan['operator_subgraph'],
        'qlib_expression': qlib_expression,
        'metadata': metadata,
    }
    hybrid_scaffold = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'hybrid',
        'implementation_source': 'hybrid_formula_ir_custom_block_codegen',
        'operator_subgraph': implementation_plan['operator_subgraph'],
        'custom_blocks': custom_blocks,
        'boundary': boundary,
        'formula_hash': contract.get('formula_hash'),
        'custom_block_hash': contract.get('custom_block_hash'),
        'hybrid_hash': contract.get('hybrid_hash'),
        'metadata': metadata,
    }
    return implementation_plan, python_stub, qlib_payload, hybrid_scaffold


def _direct_code_contract_candidates(spec: dict, plan: dict | None) -> list[dict]:
    candidates: list[dict] = []
    for source in [spec, plan or {}]:
        if not isinstance(source, dict):
            continue
        contract = source.get('implementation_contract') if isinstance(source.get('implementation_contract'), dict) else {}
        code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
        if code_contract:
            candidates.append(code_contract)
        top_contract = source.get('code_contract') if isinstance(source.get('code_contract'), dict) else {}
        if top_contract:
            candidates.append(top_contract)
    return candidates


def _merge_direct_code_contracts(spec: dict, plan: dict | None) -> dict:
    merged: dict = {}
    for candidate in _direct_code_contract_candidates(spec, plan):
        merged.update(candidate)
    return merged


def build_direct_code_artifacts(report_id: str, prep: dict, spec: dict, identity: dict, plan: dict | None = None):
    contract = spec.get('implementation_contract') or {}
    plan_contract = (plan or {}).get('implementation_contract') if isinstance((plan or {}).get('implementation_contract'), dict) else {}
    code_contract = _merge_direct_code_contracts(spec, plan)
    source_code = str(
        code_contract.get('source_code')
        or contract.get('source_code')
        or plan_contract.get('source_code')
        or (plan or {}).get('source_code')
        or (spec.get('canonical_spec') or {}).get('source_code')
        or ''
    )
    if not source_code.strip():
        raise SystemExit(
            'BLOCK_UNSUPPORTED_DIRECT_CODE_MODE: direct_code Step3B requires explicit code_contract.source_code; '
            'no fallback implementation is allowed.'
        )
    if 'def compute_factor' not in source_code:
        raise SystemExit('BLOCK_UNSUPPORTED_DIRECT_CODE_MODE: direct_code source_code must define compute_factor().')

    factor_id = spec.get('factor_id') or report_id
    code_contract_hash = code_contract.get('code_contract_hash') or (plan or {}).get('code_contract_hash') or identity.get('code_contract_hash') or stable_hash(code_contract)
    output_schema = code_contract.get('output_schema') or contract.get('output_schema') or {'columns': ['ts_code', 'trade_date', 'factor_value']}
    metadata = {
        'implementation_mode': 'direct_code',
        'implementation_source': 'direct_code_contract_codegen',
        'code_contract_version': code_contract.get('code_contract_version') or contract.get('code_contract_version'),
        'code_contract_hash': code_contract_hash,
        'output_schema': output_schema,
        'forbidden_patterns': code_contract.get('forbidden_patterns') or contract.get('forbidden_patterns') or [],
    }
    implementation_plan = {
        'report_id': report_id,
        'factor_id': factor_id,
        'producer': 'step3b_direct_code_codegen',
        'implementation_mode': 'direct_code',
        'implementation_status': 'ready',
        'code_contract': code_contract,
        'code_contract_hash': code_contract_hash,
        'metadata': metadata,
        'output_schema': output_schema,
        'step4_contract': {
            'execution_mode': 'direct_code',
            'runner_entry': None,
            'expected_outputs': ['factor_values'],
        },
        'first_run_outputs': pending_first_run_outputs('no_local_snapshots_available'),
    }
    qlib_payload = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'direct_code',
        'implementation_source': 'direct_code_contract_codegen',
        'code_contract': code_contract,
        'metadata': metadata,
    }
    hybrid_scaffold = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'direct_code',
        'implementation_source': 'direct_code_contract_codegen',
        'hybrid_status': 'not_applicable_direct_code_only',
        'code_contract': code_contract,
        'metadata': metadata,
    }
    return implementation_plan, source_code, qlib_payload, hybrid_scaffold


def dispatch_mode_codegen(report_id: str, prep: dict, spec: dict, identity: dict, plan: dict | None = None):
    mode = identity.get('implementation_mode')
    if has_family_plugin_declaration(spec):
        try:
            plugin = resolve_family_plugin(spec, mode)
        except FamilyPluginContractError as exc:
            raise SystemExit(str(exc)) from exc
        return plugin.generate(report_id, prep, spec)
    if mode == 'operator':
        return build_operator_artifacts(report_id, prep, spec, identity)
    if mode == 'direct_code':
        return build_direct_code_artifacts(report_id, prep, spec, identity, plan)
    if mode == 'hybrid':
        return build_hybrid_artifacts(report_id, prep, spec, identity)
    raise SystemExit(f'BLOCK_UNSUPPORTED_IMPLEMENTATION_MODE: {mode}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    ap.add_argument('--csv-output-policy', help='Step3B factor CSV output policy. Defaults to full_csv.')
    ap.add_argument('--formula-engine', help='Formula-IR engine. Defaults to pandas optimized; adaptive/polars_experimental are explicit opt-ins.')
    ap.add_argument('--operator-profile', action='store_true', help='Record Formula-IR operator-level timing metadata.')
    ap.add_argument('--ts-rank-engine', help='Experimental ts_rank engine. Defaults to pandas_reference.')
    ap.add_argument('--formula-kernel-engine', help='Formula-IR operator kernel engine. Experimental engines require explicit enable gate.')
    ap.add_argument('--trust-step3a-sort-contract', action='store_true', help='Experimental opt-in: trust validated Step3A sort contract to skip full normalize_sort sorting.')
    args = ap.parse_args()
    csv_policy = resolve_csv_policy(args.csv_output_policy)
    formula_engine = resolve_formula_engine(args.formula_engine)
    operator_profile = resolve_operator_profile(args.operator_profile if args.operator_profile else None)
    try:
        ts_rank_engine_config = resolve_formula_ts_rank_engine(args.ts_rank_engine)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        _formula_kernel_config = resolve_formula_kernel_engine(args.formula_kernel_engine)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    enforce_direct_step_policy(args.manifest)
    _manifest, manifest_rid = apply_runtime_manifest(args.manifest)
    require_formal_manifest(_manifest)
    report_id = args.report_id or manifest_rid
    if not report_id:
        raise SystemExit('run_step3b.py requires --report-id or --manifest')

    spec_path = (
        nested_path(_manifest, 'step_io', 'step2', 'factor_spec_master')
        or nested_path(_manifest, 'step_io', 'step3', 'inputs', 'factor_spec_master')
        or OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json'
    )
    prep_path = (
        nested_path(_manifest, 'step_io', 'step3', 'outputs', 'data_prep_master')
        or OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    )
    prep = load_json(prep_path)
    spec = load_json(spec_path)
    spec, executable_revision_spec = apply_executable_revision_spec(report_id or manifest_rid or '', spec, spec_path)
    spec_identity = assert_spec_identity_matches_manifest(spec, _manifest)
    step2_handoff = load_step2_handoff(report_id)
    step2_research_context = build_step2_research_context(report_id, spec, step2_handoff)
    factor_id = spec.get('factor_id', report_id)
    mode_decision = build_mode_decision_start(spec_identity, spec)

    # Hard consistency rule: filename report_id and JSON internal report_id must agree.
    if spec.get('report_id') != report_id:
        raise SystemExit(f'factor_spec_master.report_id mismatch: expected {report_id}, got {spec.get("report_id")}')

    code_dir = (
        nested_path(_manifest, 'step_io', 'step3b', 'outputs', 'generated_code_dir')
        or nested_path(_manifest, 'step_io', 'step3b', 'outputs', 'generated_code_output_dir')
        or CODEGEN / report_id
    )
    impl_path = (
        nested_path(_manifest, 'step_io', 'step3', 'outputs', 'implementation_plan_master')
        or OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    )
    stub_path = code_dir / f'factor_impl_stub__{report_id}.py'
    qlib_path = code_dir / f'qlib_expression_draft__{report_id}.json'
    hybrid_path = code_dir / f'hybrid_execution_scaffold__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'
    existing_implementation_plan = read_existing_json(impl_path)

    prep = load_json(prep_path)
    step3a_ready = prep.get('feasibility') in {'ready', 'proxy_ready'}
    real_impl_rel = f'generated_code/{report_id}/factor_impl__{report_id}.py'
    real_impl_abs = FF / real_impl_rel
    stub_impl_rel = str(stub_path.relative_to(FF))
    executable_impl_rel = real_impl_rel if real_impl_abs.exists() else stub_impl_rel
    executable_impl_abs = FF / executable_impl_rel

    try:
        implementation_plan, python_stub, qlib_expression, hybrid_scaffold = dispatch_mode_codegen(
            report_id,
            prep,
            spec,
            spec_identity,
            existing_implementation_plan,
        )
        artifact_producer = implementation_plan.get('producer') or 'step3b'
        family_fields = explicit_plugin_identity_fields(spec) if artifact_producer == FAMILY_PLUGIN_PRODUCER else {}
        mode_decision = finalize_mode_decision_success(
            mode_decision,
            spec_identity.get('implementation_mode'),
            'Step3B selected the mode declared by Step2 after dispatcher contract checks.',
        )
    except SystemExit as exc:
        block_reason = str(exc)
        mode_decision = finalize_mode_decision_blocked(mode_decision, spec_identity.get('implementation_mode'), block_reason)
        blocked_stub = annotate_python_stub_with_research_context(
            (
                f'"""\n'
                f'Blocked Step3B implementation placeholder for {factor_id}.\n'
                f'Reason: {block_reason}\n'
                f'No formal factor implementation or factor_values were produced.\n'
                f'"""\n\n'
                f'REPORT_ID = {report_id!r}\n'
                f'FACTOR_ID = {factor_id!r}\n'
                f'IMPLEMENTATION_BLOCKED = True\n'
            ),
            step2_research_context,
        )
        implementation_identity = derive_child_identity(spec_identity, artifact_role='implementation_plan_master', producer='step3b')
        generated_code_identity = derive_child_identity(spec_identity, artifact_role='generated_code', producer='step3b')
        handoff_identity = derive_child_identity(spec_identity, artifact_role='handoff_to_step4', producer='step3b')
        blocked_plan = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_mode': spec_identity.get('implementation_mode'),
            'implementation_status': 'blocked',
            'artifact_identity': implementation_identity,
            'implementation_mode_decision': mode_decision,
            'step2_research_context': step2_research_context,
            'step4_contract': {
                'execution_mode': spec_identity.get('implementation_mode'),
                'runner_entry': None,
                'expected_outputs': [],
            },
            'first_run_outputs': {
                'status': 'blocked',
                'output_paths': [],
                'run_metadata_path': None,
                'producer': 'step3b',
                'reason': block_reason,
            },
        }
        blocked_generated = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_mode': spec_identity.get('implementation_mode'),
            'implementation_status': 'blocked',
            'artifact_identity': generated_code_identity,
            'metadata': {
                'artifact_identity': generated_code_identity,
                'implementation_mode': spec_identity.get('implementation_mode'),
                'implementation_mode_decision': mode_decision,
                'implementation_status': 'blocked',
            },
            'implementation_mode_decision': mode_decision,
            'step2_research_context': step2_research_context,
        }
        write_json(impl_path, blocked_plan)
        write_text(stub_path, blocked_stub)
        write_json(qlib_path, blocked_generated)
        write_json(hybrid_path, blocked_generated)
        existing_handoff = read_existing_json(handoff_path)
        handoff_payload = merge_handoff(existing_handoff, {
            'report_id': report_id,
            'artifact_identity': handoff_identity,
            'implementation_mode': spec_identity.get('implementation_mode'),
            'implementation_status': 'blocked',
            'implementation_mode_decision': mode_decision,
            'source_type': spec_identity.get('source_type'),
            'spec_hash': spec_identity.get('spec_hash'),
            'branch_id': spec_identity.get('branch_id'),
            'step3a_ready': step3a_ready,
            'step3b_ready': False,
            'data_prep_master_ref': existing_handoff.get('data_prep_master_ref') or f'data_prep_master__{report_id}.json',
            'qlib_adapter_config_ref': existing_handoff.get('qlib_adapter_config_ref') or f'qlib_adapter_config__{report_id}.json',
            'factor_spec_master_ref': existing_handoff.get('factor_spec_master_ref') or f'factor_spec_master__{report_id}.json',
            'implementation_plan_master_ref': impl_path.name,
            'factor_impl_ref': None,
            'factor_impl_stub_ref': stub_impl_rel,
            'qlib_expression_draft_ref': str(qlib_path.relative_to(FF)),
            'hybrid_execution_scaffold_ref': str(hybrid_path.relative_to(FF)),
            'execution_mode': spec_identity.get('implementation_mode'),
            'local_input_paths': prep.get('local_input_paths', {}),
            'step2_research_context': step2_research_context,
            'first_run_outputs': blocked_plan['first_run_outputs'],
        })
        write_json(handoff_path, handoff_payload)
        raise SystemExit(block_reason) from exc

    attach_step2_research_context(implementation_plan, qlib_expression, hybrid_scaffold, step2_research_context)
    implementation_plan['implementation_mode_decision'] = mode_decision
    qlib_expression['implementation_mode_decision'] = mode_decision
    hybrid_scaffold['implementation_mode_decision'] = mode_decision
    python_stub = annotate_python_stub_with_research_context(python_stub, step2_research_context)

    if real_impl_abs.exists():
        implementation_plan['step4_contract']['runner_entry'] = real_impl_rel
    code_hash = hashlib.sha256(python_stub.encode('utf-8')).hexdigest()
    implementation_identity = derive_child_identity(
        spec_identity,
        artifact_role='implementation_plan_master',
        producer=artifact_producer,
        code_hash=code_hash,
        family_fields=family_fields,
    )
    generated_code_identity = derive_child_identity(
        spec_identity,
        artifact_role='generated_code',
        producer=artifact_producer,
        code_hash=code_hash,
        family_fields=family_fields,
    )
    handoff_identity = derive_child_identity(
        spec_identity,
        artifact_role='handoff_to_step4',
        producer=artifact_producer,
        code_hash=code_hash,
        family_fields=family_fields,
    )
    implementation_plan['artifact_identity'] = implementation_identity
    if executable_revision_spec:
        implementation_plan['executable_revision_spec'] = {
            'path': str(executable_revision_spec_path(report_id)),
            'parent_report_id': executable_revision_spec.get('parent_report_id'),
            'child_report_id': executable_revision_spec.get('child_report_id'),
            'parent_formula_hash': executable_revision_spec.get('parent_formula_hash'),
            'child_formula_hash': executable_revision_spec.get('child_formula_hash'),
            'revision_identity_status': 'audit_rerun' if executable_revision_spec.get('revision_type') == 'audit_rerun' else 'changed',
        }
    if family_fields:
        implementation_plan.update(family_fields)
    implementation_plan['implementation_mode'] = spec_identity.get('implementation_mode') or implementation_plan.get('implementation_mode')
    implementation_plan.setdefault('step4_contract', {})
    implementation_plan['step4_contract']['execution_mode'] = implementation_plan['implementation_mode']
    qlib_expression['artifact_identity'] = generated_code_identity
    if family_fields:
        qlib_expression.update(family_fields)
    qlib_expression['implementation_mode'] = spec_identity.get('implementation_mode')
    qlib_expression['metadata'] = {
        **(qlib_expression.get('metadata') or {}),
        'artifact_identity': generated_code_identity,
        'code_hash': code_hash,
        'implementation_mode': spec_identity.get('implementation_mode'),
        'implementation_mode_decision': mode_decision,
    }
    hybrid_scaffold['artifact_identity'] = generated_code_identity
    if family_fields:
        hybrid_scaffold.update(family_fields)
    hybrid_scaffold['implementation_mode'] = spec_identity.get('implementation_mode')
    hybrid_scaffold['metadata'] = {
        **(hybrid_scaffold.get('metadata') or {}),
        'artifact_identity': generated_code_identity,
        'code_hash': code_hash,
        'implementation_mode': spec_identity.get('implementation_mode'),
        'implementation_mode_decision': mode_decision,
    }

    write_json(impl_path, implementation_plan)
    write_text(stub_path, python_stub)
    write_json(qlib_path, qlib_expression)
    write_json(hybrid_path, hybrid_scaffold)

    # COMMENT_POLICY: execution_handoff
    # Step 3B handoff freezes the implementation/code artifact references for Step 4.
    existing_handoff = read_existing_json(handoff_path)
    handoff_payload = merge_handoff(existing_handoff, {
        'report_id': report_id,
        'artifact_identity': handoff_identity,
        'producer': artifact_producer,
        **family_fields,
        'implementation_mode': spec_identity.get('implementation_mode'),
        'source_type': spec_identity.get('source_type'),
        'spec_hash': spec_identity.get('spec_hash'),
        'branch_id': spec_identity.get('branch_id'),
        'step3a_ready': step3a_ready,
        'step3b_ready': True,
        'data_prep_master_ref': existing_handoff.get('data_prep_master_ref') or f'data_prep_master__{report_id}.json',
        'qlib_adapter_config_ref': existing_handoff.get('qlib_adapter_config_ref') or f'qlib_adapter_config__{report_id}.json',
        'factor_spec_master_ref': existing_handoff.get('factor_spec_master_ref') or f'factor_spec_master__{report_id}.json',
        'implementation_plan_master_ref': impl_path.name,
        'factor_impl_ref': real_impl_rel if real_impl_abs.exists() else None,
        'factor_impl_stub_ref': stub_impl_rel,
        'qlib_expression_draft_ref': str(qlib_path.relative_to(FF)),
        'hybrid_execution_scaffold_ref': str(hybrid_path.relative_to(FF)),
        'execution_mode': implementation_plan['implementation_mode'],
        'local_input_paths': prep.get('local_input_paths', {}),
        'step2_research_context': step2_research_context,
        'implementation_mode_decision': mode_decision,
        'executable_revision_spec': implementation_plan.get('executable_revision_spec'),
        'first_run_outputs': implementation_plan.get('first_run_outputs') or pending_first_run_outputs('no_local_snapshots_available')
    })
    write_json(handoff_path, handoff_payload)

    # Step3B may run a small non-formal sample proof when Data API sample queries
    # or legacy local snapshots are available. Formal factor_values are Step4-only.
    local_inputs = prep.get('local_input_paths') or {}
    step4_data_contract = (
        prep.get('step4_data_contract')
        or local_inputs.get('step4_data_contract')
        or existing_handoff.get('step4_data_contract')
        or {}
    )
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    input_mode = str(local_inputs.get('input_mode') or '')
    executable_daily_only = input_mode == 'daily_only' and daily_rel
    executable_minute_daily = minute_rel and daily_rel
    sample_queries = step4_data_contract.get('sample_queries') if isinstance(step4_data_contract, dict) else {}
    executable_data_api_sample = isinstance(sample_queries, dict) and bool(sample_queries.get('clean_daily_bar'))
    if (executable_minute_daily or executable_daily_only or executable_data_api_sample) and executable_impl_abs.exists():
        first_run_outputs = generate_first_run_factor_values(
            report_id=report_id,
            factor_id=factor_id,
            implementation_path=executable_impl_abs,
            local_inputs=local_inputs,
            step2_research_context=step2_research_context,
            mode_decision=mode_decision,
            artifact_identity=spec_identity,
            csv_output_policy=csv_policy,
            formula_engine=formula_engine,
            operator_profile=operator_profile,
            ts_rank_engine=args.ts_rank_engine,
            formula_kernel_engine=args.formula_kernel_engine,
            trust_step3a_sort_contract=args.trust_step3a_sort_contract if args.trust_step3a_sort_contract else None,
            step4_data_contract=step4_data_contract,
        )
        implementation_plan['first_run_outputs'] = first_run_outputs
        implementation_plan['step4_contract']['runner_entry'] = executable_impl_rel
        write_json(impl_path, implementation_plan)

        handoff_payload = merge_handoff(handoff_payload, {
            'factor_impl_ref': real_impl_rel if real_impl_abs.exists() else None,
            'factor_impl_stub_ref': stub_impl_rel,
            'step2_research_context': step2_research_context,
            'first_run_outputs': implementation_plan['first_run_outputs']
        })
        write_json(handoff_path, handoff_payload)


if __name__ == '__main__':
    main()
