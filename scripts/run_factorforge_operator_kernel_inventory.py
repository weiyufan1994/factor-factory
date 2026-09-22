#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
VERSION = 'factorforge_operator_kernel_inventory_v1'
CANONICAL_DIRS = ['objects', 'runs', 'evaluations', 'generated_code', 'archive', 'factorforge', 'data/clean']

from factor_factory.formula.kernels import DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS, DEFAULT_NUMPY_TS_OPERATORS, DEFAULT_NUMPY_TS_ROLLBACK_ENV

OPTIONAL_DEPENDENCIES = {
    'talib': ('TA-Lib technical indicator library', 'factor_indicator_library', 'TA-Lib'),
    'bottleneck': ('fast nan-aware array reductions', 'operator_kernel_candidate', 'bottleneck'),
    'numba': ('jit compiled custom rolling kernels', 'operator_kernel_candidate', 'numba'),
    'scipy': ('rankdata and statistical kernels', 'operator_kernel_candidate', 'scipy'),
    'numbagg': ('numba-backed aggregations', 'operator_kernel_candidate', 'numbagg'),
    'window_ops': ('rolling window operations', 'operator_kernel_candidate', 'window-ops'),
    'polars': ('alternate dataframe backend', 'alternate_dataframe_backend', 'polars'),
}

OPERATOR_ORDER = [
    'cs_rank',
    'ts_sum',
    'ts_mean',
    'ts_std',
    'ts_stddev',
    'ts_rank',
    'ts_min',
    'ts_max',
    'ts_argmin',
    'ts_argmax',
    'ts_delta',
    'ts_delay',
    'rolling_corr',
    'rolling_cov',
    'polars_formula_engine',
    'experimental_formula_kernel',
    'cs_scale',
    'signed_power',
]

OPERATOR_TO_KERNEL_NAMES = {
    'ts_sum': {'sum'},
    'ts_mean': {'mean'},
    'ts_std': {'std'},
    'ts_stddev': {'stddev'},
    'ts_min': {'min'},
    'ts_max': {'max'},
    'ts_delta': {'delta'},
    'ts_delay': {'delay'},
    'ts_argmin': {'argmin'},
    'ts_argmax': {'argmax'},
    'ts_rank': {'ts_rank'},
    'rolling_corr': {'correlation', 'corr'},
    'rolling_cov': {'covariance'},
}


def operator_policy_class(operator: str) -> tuple[str, str | None]:
    if operator in {'polars_formula_engine', 'experimental_formula_kernel'}:
        return 'opt_in_only', 'experimental_backend_requires_explicit_enable'
    kernel_names = OPERATOR_TO_KERNEL_NAMES.get(operator, {operator})
    if kernel_names & set(DEFAULT_NUMPY_TS_OPERATORS):
        return 'default_enabled', None
    if kernel_names & set(DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS):
        return 'blocked_by_edge_case', 'excluded_from_default_numpy_ts_kernel_policy'
    if operator in {'ts_sum', 'ts_mean'}:
        return 'opt_in_only', 'not_default_enabled_on_current_production_baseline'
    if operator in {'cs_rank', 'cs_scale'}:
        return 'not_reviewed', 'cross_sectional_kernel_policy_not_in_scope'
    if operator == 'signed_power':
        return 'not_applicable', 'elementwise_operator_not_time_series_kernel'
    return 'not_reviewed', 'no_default_policy_recorded'


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def is_tmp_path(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    text = str(resolved)
    return text.startswith('/tmp/') or text.startswith('/private/tmp/')


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def snapshot_canonical_files(repo_root: Path) -> set[str]:
    out: set[str] = set()
    for raw_dir in CANONICAL_DIRS:
        root = repo_root / raw_dir
        if not root.exists():
            continue
        for item in root.rglob('*'):
            if item.is_file():
                out.add(str(item.relative_to(repo_root)))
    return out


def canonical_pollution(before: set[str], after: set[str]) -> bool:
    return bool(after - before)


def read_text(repo_root: Path, relative_path: str) -> str:
    path = repo_root / relative_path
    if not path.exists():
        return ''
    return path.read_text(encoding='utf-8')


def probe_optional_dependencies() -> dict[str, dict[str, Any]]:
    probe: dict[str, dict[str, Any]] = {}
    for module, (description, role, dist_name) in OPTIONAL_DEPENDENCIES.items():
        spec = importlib.util.find_spec(module)
        version = None
        if spec is not None:
            try:
                version = importlib.metadata.version(dist_name)
            except importlib.metadata.PackageNotFoundError:
                version = None
        probe[module] = {
            'module': module,
            'description': description,
            'importable': bool(spec is not None),
            'version': version,
            'install_required_for_rta07a': False,
            'role': role,
        }
    return probe


def qlib_support_from_registry(registry_text: str) -> dict[str, bool | None]:
    support: dict[str, bool | None] = {}
    for block in re.finditer(r"'([^']+)':\s*\{([^}]+)\}", registry_text, flags=re.S):
        canonical = block.group(1)
        body = block.group(2)
        support_match = re.search(r"'supports_qlib':\s*(True|False)", body)
        if support_match:
            support[canonical] = support_match.group(1) == 'True'
        alias_match = re.search(r"'aliases':\s*\[([^\]]+)\]", body)
        if alias_match:
            for alias in re.findall(r"'([^']+)'", alias_match.group(1)):
                support[alias] = support.get(canonical)
    return support


def classify_operator(operator: str, qlib_support: dict[str, bool | None], source_text: dict[str, str]) -> dict[str, Any]:
    if operator == 'polars_formula_engine':
        policy_class, blocking_reason = operator_policy_class(operator)
        return {
            'operator': operator,
            'current_impl': 'experimental_polars_dataframe_backend',
            'qlib_bridge_supported': None,
            'performance_risk': 'medium',
            'semantic_risk': 'high',
            'reason': 'Polars formula execution is an alternate backend and remains explicit opt-in.',
            'upgrade_candidates': ['polars_experimental'],
            'default_kernel_enabled': False,
            'default_safe_to_change': False,
            'policy_class': policy_class,
            'blocking_reason': blocking_reason,
            'rollback_env': 'FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS',
            'notes': [],
        }
    if operator == 'experimental_formula_kernel':
        policy_class, blocking_reason = operator_policy_class(operator)
        return {
            'operator': operator,
            'current_impl': 'experimental_formula_kernel_engine',
            'qlib_bridge_supported': None,
            'performance_risk': 'medium',
            'semantic_risk': 'high',
            'reason': 'Broad formula-kernel engines remain explicit opt-in and cannot replace production defaults as a single switch.',
            'upgrade_candidates': ['numpy_rolling_experimental', 'numba_rolling_experimental'],
            'default_kernel_enabled': False,
            'default_safe_to_change': False,
            'policy_class': policy_class,
            'blocking_reason': blocking_reason,
            'rollback_env': 'FACTORFORGE_ENABLE_EXPERIMENTAL_FORMULA_KERNEL',
            'notes': [],
        }
    qlib_alias = {
        'cs_rank': 'rank',
        'ts_sum': 'ts_sum',
        'ts_mean': 'ts_mean',
        'ts_std': 'ts_std',
        'ts_stddev': 'stddev',
        'ts_rank': 'ts_rank',
        'ts_min': 'min',
        'ts_max': 'max',
        'ts_argmin': 'argmin',
        'ts_argmax': 'argmax',
        'ts_delta': 'delta',
        'ts_delay': 'delay',
        'rolling_corr': 'rolling_corr',
        'rolling_cov': 'rolling_cov',
        'cs_scale': 'scale',
        'signed_power': 'signed_power',
    }.get(operator, operator)
    supported = qlib_support.get(qlib_alias)
    note = None if supported is not None else 'qlib bridge support not detected from registry aliases'
    policy_class, blocking_reason = operator_policy_class(operator)
    default_kernel_enabled = policy_class == 'default_enabled'
    if operator in {'ts_argmin', 'ts_argmax'}:
        current_impl = 'pandas_groupby_rolling_apply_raw_lambda'
        performance_risk = 'high'
        semantic_risk = 'medium'
        reason = 'rolling apply lambda executes custom window logic through pandas apply'
        candidates = ['numba_per_ticker_loop', 'numpy_per_ticker_loop']
    elif operator in {'rolling_corr', 'rolling_cov'}:
        current_impl = 'pandas_groupby_apply_rolling_pairwise_stat'
        performance_risk = 'high'
        semantic_risk = 'high'
        reason = 'groupby.apply wraps pandas rolling pairwise statistics and is likely expensive on large panels'
        candidates = ['pandas_vectorized_no_groupby_apply', 'numba_per_ticker_loop', 'bottleneck_formula_candidate']
    elif operator == 'ts_rank':
        current_impl = 'pandas_groupby_rolling_rank_reference_default'
        performance_risk = 'high'
        semantic_risk = 'high'
        reason = 'pandas rolling rank semantics require careful ties and NaN parity; current default remains pandas reference'
        candidates = ['existing_numpy_sliding_window_experimental', 'pandas_rolling_rank_candidate', 'scipy_rankdata_candidate', 'numba_per_ticker_loop']
    elif operator in {'ts_sum', 'ts_mean', 'ts_std', 'ts_stddev', 'ts_min', 'ts_max'}:
        current_impl = 'pandas_groupby_transform_rolling_builtin'
        performance_risk = 'medium'
        semantic_risk = 'medium'
        reason = 'rolling reductions use pandas groupby transform; likely acceptable but worth benchmarking before replacement'
        candidates = ['existing_numpy_rolling_experimental', 'bottleneck', 'window_ops', 'numbagg']
    elif operator in {'ts_delta', 'ts_delay'}:
        current_impl = 'pandas_groupby_diff_or_shift'
        performance_risk = 'low'
        semantic_risk = 'low'
        reason = 'diff/shift are direct pandas groupby operations with narrow semantics'
        candidates = []
    elif operator == 'cs_rank':
        current_impl = 'pandas_groupby_rank_pct'
        performance_risk = 'medium'
        semantic_risk = 'medium'
        reason = 'cross-sectional rank is vectorized but can dominate wide daily panels'
        candidates = ['pandas_rank_profile', 'numpy_group_rank_candidate']
    elif operator == 'cs_scale':
        current_impl = 'pandas_groupby_abs_sum_transform'
        performance_risk = 'low'
        semantic_risk = 'medium'
        reason = 'scale uses grouped sum and division; not an urgent hotspot without profile evidence'
        candidates = ['pandas_vectorized_baseline']
    else:
        current_impl = 'numpy_or_pandas_elementwise'
        performance_risk = 'low'
        semantic_risk = 'medium'
        reason = 'elementwise semantics are simple; optimize only after higher-risk rolling operators'
        candidates = []
    if default_kernel_enabled:
        current_impl = f'default_numpy_ts_kernel_active_with_legacy_reference__{current_impl}'
        performance_risk = 'low' if operator in {'ts_delta', 'ts_delay', 'ts_sum', 'ts_mean', 'ts_min', 'ts_max'} else 'medium'
        semantic_risk = 'low' if operator in {'ts_delta', 'ts_delay', 'ts_sum', 'ts_mean', 'ts_min', 'ts_max'} else 'medium'
        reason = (
            'default pandas_optimized runtime uses a parity-proven NumPy kernel for this operator; '
            'legacy pandas implementation remains the correctness oracle and rollback path'
        )
        candidates = ['default_numpy_ts_kernel_active', 'pandas_reference_rollback']
    return {
        'operator': operator,
        'current_impl': current_impl,
        'qlib_bridge_supported': supported,
        'performance_risk': performance_risk,
        'semantic_risk': semantic_risk,
        'reason': reason,
        'upgrade_candidates': candidates,
        'default_kernel_enabled': default_kernel_enabled,
        'default_safe_to_change': default_kernel_enabled,
        'policy_class': policy_class,
        'blocking_reason': blocking_reason,
        'rollback_env': DEFAULT_NUMPY_TS_ROLLBACK_ENV if default_kernel_enabled else None,
        'notes': [note] if note else [],
    }


def build_operator_inventory(repo_root: Path) -> list[dict[str, Any]]:
    source_text = {
        'operators.py': read_text(repo_root, 'factor_factory/formula/operators.py'),
        'kernels.py': read_text(repo_root, 'factor_factory/formula/kernels.py'),
        'registry.py': read_text(repo_root, 'factor_factory/formula/registry.py'),
        'ts_rank_candidates.py': read_text(repo_root, 'factor_factory/formula/ts_rank_candidates.py'),
    }
    qlib_support = qlib_support_from_registry(source_text['registry.py'])
    return [classify_operator(operator, qlib_support, source_text) for operator in OPERATOR_ORDER]


def current_execution_model() -> dict[str, Any]:
    return {
        'step3b_factor_values_use_qlib_native': False,
        'formal_factor_engine': 'factor_forge_formula_ir_pandas_optimized_with_default_numpy_ts_kernels',
        'qlib_role': 'bridge_export_backtest_compatibility',
        'default_numpy_ts_kernel_policy': {
            'enabled': True,
            'operators': sorted(DEFAULT_NUMPY_TS_OPERATORS),
            'excluded_operators': sorted(DEFAULT_NUMPY_TS_EXCLUDED_OPERATORS),
            'rollback_env': DEFAULT_NUMPY_TS_ROLLBACK_ENV,
            'correctness_oracle': 'pandas_reference',
        },
        'custom_factor_code_policy': {
            'preferred_backends': ['numpy', 'polars'],
            'avoid_by_default': ['python_row_loops', 'pandas_groupby_apply'],
            'rule': 'direct_code and hybrid custom blocks should use vectorized NumPy/Polars where practical and must justify slower Python loops explicitly.',
        },
        'evidence_files': [
            'skills/factor-forge-step3/scripts/run_step3b.py',
            'factor_factory/formula/evaluator.py',
            'factor_factory/formula/operators.py',
            'factor_factory/formula/qlib_codegen.py',
        ],
        'notes': [
            "Current slowness should be attributed first to pandas/groupby/rolling/apply execution in Factor Forge's formal Formula-IR path, not to qlib native operator execution.",
            'A reviewed subset of Formula-IR time-series operators now defaults to NumPy kernels while pandas remains the correctness oracle and rollback path.',
        ],
    }


def library_landscape() -> list[dict[str, Any]]:
    return [
        {
            'library': 'TA-Lib',
            'best_role': 'factor_indicator_library',
            'good_for': ['RSI', 'MACD', 'ATR', 'BBANDS', 'technical_indicator_factor_family'],
            'not_safe_for': ['silent_replacement_of_formula_ir_rolling_semantics'],
            'reason': 'TA-Lib indicator warmup, NaN, price-field, and multi-input semantics differ from Alpha/Formula-IR primitive operators.',
        },
        {
            'library': 'bottleneck',
            'best_role': 'operator_kernel_candidate',
            'good_for': ['nan-aware moving reductions'],
            'not_safe_for': ['ts_rank_without_parity', 'corr_cov_without_semantic_check'],
            'reason': 'Useful only behind explicit benchmark and parity gates.',
        },
        {
            'library': 'numba',
            'best_role': 'operator_kernel_candidate',
            'good_for': ['argmin_argmax', 'ts_rank', 'corr_cov'],
            'not_safe_for': ['default_dependency_without_gate'],
            'reason': 'JIT kernels can help custom rolling operators but must remain optional and guarded.',
        },
        {
            'library': 'numbagg',
            'best_role': 'operator_kernel_candidate',
            'good_for': ['rolling_aggregations', 'grouped_reductions'],
            'not_safe_for': ['default_dependency_without_gate', 'semantic_replacement_without_parity'],
            'reason': 'Candidate acceleration layer, not a production default.',
        },
        {
            'library': 'window-ops',
            'best_role': 'operator_kernel_candidate',
            'good_for': ['rolling_window_operations'],
            'not_safe_for': ['ts_rank_without_tie_nan_parity'],
            'reason': 'Potential rolling primitive provider after exact semantic parity tests.',
        },
        {
            'library': 'scipy',
            'best_role': 'operator_kernel_candidate',
            'good_for': ['rankdata', 'statistical_kernels'],
            'not_safe_for': ['mandatory_dependency_for_default_path'],
            'reason': 'Useful for candidate comparison, not required for RTA-07A.',
        },
        {
            'library': 'polars',
            'best_role': 'alternate_dataframe_backend',
            'good_for': ['dataframe_backend_experiments'],
            'not_safe_for': ['silent_formula_ir_backend_replacement'],
            'reason': 'Backend-level experiment separate from operator-kernel default selection.',
        },
        {
            'library': 'pandas Rolling.rank',
            'best_role': 'operator_kernel_candidate',
            'good_for': ['ts_rank_reference_or_candidate'],
            'not_safe_for': ['assuming_faster_without_real_panel_benchmark'],
            'reason': 'May simplify ts_rank semantics but still requires real-panel timing and parity.',
        },
    ]


def upgrade_priority() -> list[dict[str, Any]]:
    return [
        {
            'rank': 1,
            'operators': ['ts_std', 'stddev'],
            'why': 'std/stddev remain excluded from the default NumPy TS kernel set until ddof, NaN, and edge-window semantics are proven',
            'next_phase': 'RTA-07H std semantic gate and benchmark',
        },
        {
            'rank': 2,
            'operators': ['cs_rank', 'cs_scale'],
            'why': 'cross-sectional daily operations can dominate wide panels and are not yet covered by default NumPy TS kernels',
            'next_phase': 'RTA-08 cross-sectional kernel inventory and parity',
        },
        {
            'rank': 3,
            'operators': ['direct_code', 'hybrid_custom_block'],
            'why': 'non-formula factor implementations need an explicit high-speed NumPy/Polars generation policy',
            'next_phase': 'RTA-09 direct-code vectorization policy and smoke fixtures',
        },
        {
            'rank': 4,
            'operators': ['polars_experimental_backend'],
            'why': 'Polars is available locally and promising for dataframe-level execution, but cannot silently replace Formula-IR semantics without parity contracts',
            'next_phase': 'RTA-10 Polars backend parity and performance envelope',
        },
    ]


def diagnostics() -> list[dict[str, Any]]:
    return [
        {
            'severity': 'info',
            'code': 'QLIB_NOT_FORMAL_OPERATOR_ENGINE',
            'message': 'Step3B formal factor values are produced by Factor Forge Formula-IR pandas execution, not qlib native execution.',
        },
        {
            'severity': 'warning',
            'code': 'OPERATOR_KERNEL_HOTSPOT_ROLLING_APPLY',
            'message': 'Legacy pandas rollback/reference paths for ts_rank/argmin/argmax still use rolling apply style code; default runtime uses NumPy kernels.',
        },
        {
            'severity': 'warning',
            'code': 'OPERATOR_KERNEL_HOTSPOT_GROUPBY_APPLY_CORR_COV',
            'message': 'Legacy pandas rollback/reference paths for rolling_corr/rolling_cov still use groupby.apply around rolling pairwise statistics; default runtime uses NumPy hybrid kernels.',
        },
        {
            'severity': 'info',
            'code': 'TA_LIB_FACTOR_LIBRARY_CANDIDATE',
            'message': 'TA-Lib is a candidate factor indicator library, not a silent Formula-IR primitive replacement.',
        },
        {
            'severity': 'info',
            'code': 'DEFAULT_NUMPY_TS_KERNELS_ENABLED',
            'message': 'High-confidence Formula-IR time-series kernels are default-enabled under pandas_optimized with pandas reference rollback.',
        },
    ]


def build_inventory(repo_root: Path) -> dict[str, Any]:
    before = snapshot_canonical_files(repo_root)
    payload = {
        'version': VERSION,
        'generated_at': utc_now(),
        'repo_root': str(repo_root),
        'read_only': True,
        'current_execution_model': current_execution_model(),
        'operator_inventory': build_operator_inventory(repo_root),
        'optional_dependency_probe': probe_optional_dependencies(),
        'library_landscape': library_landscape(),
        'upgrade_priority': upgrade_priority(),
        'diagnostics': diagnostics(),
    }
    after = snapshot_canonical_files(repo_root)
    payload['canonical_pollution'] = canonical_pollution(before, after)
    return payload


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', required=True)
    ap.add_argument('--allow-non-tmp-output', action='store_true')
    ap.add_argument('--repo-root', default=str(REPO_ROOT))
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    output = Path(args.output).expanduser()
    if not is_tmp_path(output) and not args.allow_non_tmp_output:
        print(f'BLOCK_OPERATOR_KERNEL_INVENTORY_NON_TMP_OUTPUT: {output}', file=sys.stderr)
        return 1
    payload = build_inventory(repo_root)
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print(f'[WRITE] {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
