#!/usr/bin/env python3
import argparse, importlib.util, json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

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
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


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


def generate_first_run_factor_values(
    report_id: str,
    factor_id: str,
    implementation_path: Path,
    local_inputs: dict,
    step2_research_context: dict,
) -> dict:
    """Run only the factor implementation and materialize factor_values.

    This intentionally does not call Step4 or any evaluator. Step3B's proof is
    executability of the factor implementation, not IC/NAV/backtest evidence.
    """
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    input_mode = str(local_inputs.get('input_mode') or '')
    minute_required = input_mode != 'daily_only'
    minute_path = resolve_local_input_path(minute_rel)
    daily_path = resolve_local_input_path(daily_rel)

    if daily_path is None or not daily_path.exists():
        raise SystemExit(f'Step3B first-run daily input missing: {daily_path}')
    if minute_required and (minute_path is None or not minute_path.exists()):
        raise SystemExit(f'Step3B first-run minute input missing: {minute_path}')

    import pandas as pd

    module = import_module_from_path(implementation_path)
    if not hasattr(module, 'compute_factor'):
        raise SystemExit(f'Step3B implementation missing compute_factor(): {implementation_path}')

    minute_df = read_df(minute_path) if minute_path is not None else pd.DataFrame()
    daily_df = read_df(daily_path)
    result_df = module.compute_factor(minute_df, daily_df)
    if result_df is None or len(result_df) == 0:
        raise SystemExit('Step3B first-run implementation returned empty factor values')
    if not {'ts_code', 'trade_date'}.issubset(result_df.columns):
        raise SystemExit('Step3B first-run output must include ts_code and trade_date')

    signal_col = infer_signal_column(result_df, factor_id=factor_id)
    result_df = result_df[['ts_code', 'trade_date', signal_col]].copy()
    result_df['trade_date'] = normalize_trade_date_series(result_df['trade_date']).dt.strftime('%Y%m%d')
    result_df = result_df.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    run_dir = RUNS / report_id
    run_dir.mkdir(parents=True, exist_ok=True)
    factor_parquet = run_dir / f'factor_values__{report_id}.parquet'
    factor_csv = run_dir / f'factor_values__{report_id}.csv'
    run_meta = run_dir / f'run_metadata__{report_id}.json'
    result_df.to_parquet(factor_parquet, index=False)
    result_df.to_csv(factor_csv, index=False)

    metadata = {
        'report_id': report_id,
        'factor_id': factor_id,
        'producer': 'step3b_first_run',
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
            'minute': str(minute_path) if minute_path else None,
            'daily': str(daily_path),
        },
        'step2_research_context': step2_research_context,
        'created_at_utc': utc_now(),
        'boundary_note': 'Step3B first-run produced factor values only; Step4 owns IC/NAV/backtest evaluation.',
    }
    write_json(run_meta, metadata)

    return {
        'status': 'ready',
        'output_paths': [str(factor_parquet.relative_to(FF)), str(factor_csv.relative_to(FF))],
        'run_metadata_path': str(run_meta.relative_to(FF)),
        'producer': 'step3b',
        'signal_column': signal_col,
        'row_count': int(len(result_df)),
        'date_count': int(result_df['trade_date'].nunique()),
        'ticker_count': int(result_df['ts_code'].nunique()),
    }


def signal_column_name(factor_id: str | None) -> str:
    raw = re.sub(r'[^0-9a-zA-Z]+', '_', str(factor_id or '').strip().lower()).strip('_') or 'factor'
    return raw if raw.endswith('_factor') else f'{raw}_factor'


def build_cpv_artifacts(report_id: str, prep: dict, spec: dict):
    factor_id = spec.get('factor_id', 'CPV')
    signal_col = signal_column_name(factor_id)
    canonical = spec.get('canonical_spec', {})
    sample = prep.get('sample_window', {})

    # Step 3B exports both:
    # 1) plan/schema objects consumed by downstream steps
    # 2) editable code artifacts meant for IDE-side collaboration
    implementation_plan = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'hybrid',
        'rationale': [
            '分钟级相关性计算与多段残差剥离更适合 direct_python',
            '字段组织与后续数据访问可尽量靠近 qlib 标准层',
            '因此当前最佳路径为 hybrid'
        ],
        'inputs': {
            'minute_dataset': 'tushare_minute_bars',
            'daily_dataset': 'tushare_daily_bars',
            'sample_window': sample,
            'required_fields': ['ts_code', 'trade_date', 'trade_time', 'close', 'vol', 'amount', 'pct_chg']
        },
        'proxy_rules': prep.get('proxy_rules', []),
        'calculation_steps': [
            '读取分钟级行情，按股票和交易日组织',
            '计算单日分钟 price-volume 相关系数',
            '构造 PV_corr_avg / market_corr / trend 信号',
            '对 amount 代理的规模项做中性化',
            '生成最终 CPV 因子值'
        ],
        'code_artifacts': {
            'python_stub': f'factor_impl_stub__{report_id}.py',
            'qlib_expression_draft': f'qlib_expression_draft__{report_id}.json',
            'hybrid_execution_scaffold': f'hybrid_execution_scaffold__{report_id}.json'
        },
        'step4_contract': {
            'runner_entry': f'generated_code/{report_id}/factor_impl_stub__{report_id}.py',
            'execution_mode': 'hybrid',
            'expected_outputs': [
                f'factorforge/runs/{report_id}/factor_values__{report_id}.parquet',
                f'factorforge/runs/{report_id}/factor_values__{report_id}.csv',
                f'factorforge/runs/{report_id}/run_metadata__{report_id}.json',
                f'factorforge/objects/factor_run_master/factor_run_master__{report_id}.json'
            ]
        },
        'first_run_outputs': {
            'status': 'pending',
            'output_paths': [],
            'run_metadata_path': None,
            'producer': 'step3b'
        }
    }

    python_stub = f'''"""\nAuto-generated Step 3B factor implementation stub for {factor_id}.\nThis file is intended for IDE-side editing before Step 4 execution.\n"""\n\nfrom pathlib import Path\nimport pandas as pd\nimport numpy as np\n\nREPORT_ID = {report_id!r}\nFACTOR_ID = {factor_id!r}\nSIGNAL_COLUMN = {signal_col!r}\n\n# CONTEXT:\n# - This module is generated by Step 3B and then edited in Cursor/Trae with human review.\n# - Step 4 will import compute_factor() directly, so this file is execution-critical.\n\n# CONTRACT:\n# - Input columns must follow Step 3A normalized mapping.\n# - Output schema must be: ['ts_code', 'trade_date', SIGNAL_COLUMN].\n# - Function must stay deterministic for the same input snapshot.\n\n# RISK:\n# - `amount` is currently used as a proxy for missing market_cap/turnover fields.\n# - Any proxy change must be reflected in Step 2/3 specs to keep lineage auditable.\n\n\ndef load_inputs(minute_df: pd.DataFrame, daily_df: pd.DataFrame):\n    \"\"\"Step 3A has already resolved paths / fields / proxies.\n    Step 4 should pass normalized DataFrames into this implementation.\n    \"\"\"\n    return minute_df.copy(), daily_df.copy()\n\n\ndef compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:\n    \"\"\"CPV hybrid implementation skeleton.\n\n    To be refined in IDE before Step 4 execution.\n    Current design:\n    1. minute-level price-volume correlation\n    2. aggregate daily signals\n    3. amount-based neutralization proxy\n    4. trend signal\n    5. equal-weight merge\n    \"\"\"\n    required_minute = ['ts_code', 'trade_date', 'trade_time', 'close', 'vol', 'amount']\n    required_daily = ['ts_code', 'trade_date', 'pct_chg', 'vol', 'amount']\n    for c in required_minute:\n        if c not in minute_df.columns:\n            raise KeyError(f'missing minute column: {{c}}')\n    for c in required_daily:\n        if c not in daily_df.columns:\n            raise KeyError(f'missing daily column: {{c}}')\n\n    # Keep empty-by-default output so reviewer can safely fill logic in IDE.\n    out = pd.DataFrame(columns=['ts_code', 'trade_date', SIGNAL_COLUMN])\n    return out\n\n\ndef main():\n    raise SystemExit('This is a Step 3B generated stub. Edit in IDE, then invoke from Step 4 runner.')\n\n\nif __name__ == '__main__':\n    main()\n'''

    qlib_expression = {
        'report_id': report_id,
        'factor_id': factor_id,
        'status': 'draft',
        'mode': 'hybrid_only',
        'reason': 'CPV contains minute-level correlation and residualization; qlib expression can cover field semantics but not the full logic cleanly.',
        'candidate_expression_parts': {
            'daily_return': '$ret',
            'daily_volume': '$volume',
            'daily_amount': '$amount'
        },
        'non_qlib_parts': [
            'minute-level price-volume correlation',
            'cross-step residualization chain',
            'trend merge logic'
        ]
    }

    hybrid_scaffold = {
        'report_id': report_id,
        'factor_id': factor_id,
        'execution_mode': 'hybrid',
        'data_layer': 'Step 3A qlib-normalized adapter',
        'compute_layer': {
            'python_required': [
                'minute-level corr',
                'cross-sectional neutralization',
                'trend merge'
            ],
            'qlib_compatible': [
                'field access',
                'daily feature loading',
                'future extension for expression-backed pieces'
            ]
        },
        'ide_edit_expected': True
    }

    return implementation_plan, python_stub, qlib_expression, hybrid_scaffold


def is_alpha002_spec(spec: dict) -> bool:
    factor_id = str(spec.get('factor_id') or '').upper()
    canonical = spec.get('canonical_spec') or {}
    label = str((spec.get('paper_ref') or {}).get('formula_label') or canonical.get('formula_label') or '').upper()
    formula_text = str(canonical.get('formula_text') or '').lower()
    return (
        factor_id in {'ALPHA002', 'ALPHA#2', 'ALPHA2'}
        or label in {'ALPHA#2', 'ALPHA002', 'ALPHA2'}
        or ('correlation' in formula_text and 'delta(log(volume)' in formula_text and '(close - open)' in formula_text)
    )


def build_alpha002_artifacts(report_id: str, prep: dict, spec: dict):
    factor_id = spec.get('factor_id', 'Alpha002')
    signal_col = signal_column_name(factor_id)
    sample = prep.get('sample_window', {})

    implementation_plan = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'direct_python',
        'rationale': [
            'Alpha002 is a canonical daily Alpha101 formula.',
            'The formula is directly expressible from daily open/close/volume fields.',
            'Step 3B emits a runnable implementation so Step 4 can immediately evaluate the requested window.'
        ],
        'inputs': {
            'daily_dataset': 'tushare_daily_bars',
            'sample_window': sample,
            'required_fields': ['ts_code', 'trade_date', 'open', 'close', 'vol']
        },
        'proxy_rules': prep.get('proxy_rules', []),
        'calculation_steps': [
            'compute delta(log(volume), 2) per instrument',
            'cross-sectionally rank delta(log(volume), 2) by trade_date',
            'compute intraday return (close - open) / open',
            'cross-sectionally rank intraday return by trade_date',
            'compute rolling 6-day correlation per instrument',
            'multiply by -1 to form Alpha002'
        ],
        'code_artifacts': {
            'python_stub': f'factor_impl_stub__{report_id}.py',
            'qlib_expression_draft': f'qlib_expression_draft__{report_id}.json',
            'hybrid_execution_scaffold': f'hybrid_execution_scaffold__{report_id}.json'
        },
        'step4_contract': {
            'runner_entry': f'generated_code/{report_id}/factor_impl_stub__{report_id}.py',
            'execution_mode': 'direct_python',
            'expected_outputs': [
                f'factorforge/runs/{report_id}/factor_values__{report_id}.parquet',
                f'factorforge/runs/{report_id}/factor_values__{report_id}.csv',
                f'factorforge/runs/{report_id}/run_metadata__{report_id}.json',
                f'factorforge/objects/factor_run_master/factor_run_master__{report_id}.json'
            ]
        },
        'first_run_outputs': {
            'status': 'pending',
            'output_paths': [],
            'run_metadata_path': None,
            'producer': 'step3b'
        }
    }

    python_stub = f'''"""\nAuto-generated Step 3B runnable implementation for {factor_id}.\nCanonical formula: -1 * correlation(rank(delta(log(volume), 2)), rank((close - open) / open), 6)\n"""\n\nfrom __future__ import annotations\n\nimport numpy as np\nimport pandas as pd\n\nREPORT_ID = {report_id!r}\nFACTOR_ID = {factor_id!r}\nSIGNAL_COLUMN = {signal_col!r}\n\n# CONTRACT:\n# - Step 4 calls compute_factor(minute_df, daily_df); Alpha002 is daily-only, so minute_df may be empty.\n# - Required daily columns: ['ts_code', 'trade_date', 'open', 'close', 'vol'].\n# - Output schema: ['ts_code', 'trade_date', SIGNAL_COLUMN].\n\n\ndef _cross_sectional_rank(df: pd.DataFrame, column: str) -> pd.Series:\n    return df.groupby('trade_date', sort=True)[column].rank(method='average', pct=True)\n\n\ndef _rolling_corr(group: pd.DataFrame) -> pd.Series:\n    return group['rank_delta_log_volume_2'].rolling(6, min_periods=6).corr(group['rank_intraday_return'])\n\n\ndef compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:\n    required_daily = ['ts_code', 'trade_date', 'open', 'close', 'vol']\n    for column in required_daily:\n        if column not in daily_df.columns:\n            raise KeyError(f'missing daily column: {{column}}')\n\n    out = daily_df[required_daily].copy()\n    out['trade_date'] = out['trade_date'].astype(str).str.replace('.0', '', regex=False).str.zfill(8)\n    out = out.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)\n\n    for column in ['open', 'close', 'vol']:\n        out[column] = pd.to_numeric(out[column], errors='coerce')\n\n    safe_volume = out['vol'].where(out['vol'] > 0)\n    out['log_volume'] = np.log(safe_volume)\n    out['delta_log_volume_2'] = out.groupby('ts_code', sort=False)['log_volume'].diff(2)\n\n    safe_open = out['open'].replace(0, np.nan)\n    out['intraday_return'] = (out['close'] - out['open']) / safe_open\n\n    out['rank_delta_log_volume_2'] = _cross_sectional_rank(out, 'delta_log_volume_2')\n    out['rank_intraday_return'] = _cross_sectional_rank(out, 'intraday_return')\n    out[SIGNAL_COLUMN] = -out.groupby('ts_code', sort=False, group_keys=False).apply(_rolling_corr)\n\n    return out[['ts_code', 'trade_date', SIGNAL_COLUMN]].sort_values(['ts_code', 'trade_date']).reset_index(drop=True)\n\n\ndef main():\n    raise SystemExit('This module is imported by Factor Forge runners. Do not execute it directly.')\n\n\nif __name__ == '__main__':\n    main()\n'''

    qlib_expression = {
        'report_id': report_id,
        'factor_id': factor_id,
        'status': 'draft',
        'mode': 'alpha101_daily_formula',
        'formula_text': '-1 * correlation(rank(delta(log(volume), 2)), rank((close - open) / open), 6)',
        'candidate_expression_parts': {
            'volume': '$volume',
            'open': '$open',
            'close': '$close',
            'delta_log_volume_2': 'Delta(Log($volume), 2)',
            'intraday_return': '($close - $open) / $open',
            'rolling_corr': 'Corr(Rank(delta_log_volume_2), Rank(intraday_return), 6)'
        },
        'non_qlib_parts': [
            'Exact operator spelling depends on the active qlib expression dialect; direct Python is canonical for this run.'
        ]
    }

    scaffold = {
        'report_id': report_id,
        'factor_id': factor_id,
        'execution_mode': 'direct_python',
        'data_layer': 'Step 3A daily-only local input + optional qlib feature frame',
        'compute_layer': {
            'python_required': [
                'per-instrument delta(log(volume), 2)',
                'cross-sectional ranks by trade_date',
                'per-instrument rolling 6-day correlation'
            ],
            'qlib_compatible': [
                'daily open/close/volume field access',
                'cross-sectional rank and rolling correlation expression draft'
            ]
        },
        'ide_edit_expected': False
    }

    return implementation_plan, python_stub, qlib_expression, scaffold


def build_shadow_artifacts(report_id: str, prep: dict, spec: dict):
    factor_id = spec.get('factor_id', 'UBL')
    signal_col = signal_column_name(factor_id)
    sample = prep.get('sample_window', {})

    implementation_plan = {
        'report_id': report_id,
        'factor_id': factor_id,
        'implementation_mode': 'direct_python',
        'rationale': [
            'UBL is a daily-frequency shadow factor and does not require minute bars.',
            'The main implementation work is daily bar feature engineering plus cross-sectional normalization.',
            'Current best path is direct_python with optional qlib feature-frame reuse for Step 4.'
        ],
        'inputs': {
            'daily_dataset': 'tushare_daily_bars',
            'sample_window': sample,
            'required_fields': ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'pct_chg']
        },
        'proxy_rules': prep.get('proxy_rules', []),
        'calculation_steps': [
            'compute normalized candlestick upper/lower shadows',
            'compute Williams-style upper/lower shadow variants',
            'aggregate 20-day mean/std shadow features',
            'combine candle_up_std and william_down_mean into final UBL factor'
        ],
        'code_artifacts': {
            'python_stub': f'factor_impl_stub__{report_id}.py',
            'qlib_expression_draft': f'qlib_expression_draft__{report_id}.json',
            'hybrid_execution_scaffold': f'hybrid_execution_scaffold__{report_id}.json'
        },
        'step4_contract': {
            'runner_entry': f'generated_code/{report_id}/factor_impl_stub__{report_id}.py',
            'execution_mode': 'direct_python',
            'expected_outputs': [
                f'factorforge/runs/{report_id}/factor_values__{report_id}.parquet',
                f'factorforge/runs/{report_id}/factor_values__{report_id}.csv',
                f'factorforge/runs/{report_id}/run_metadata__{report_id}.json',
                f'factorforge/objects/factor_run_master/factor_run_master__{report_id}.json'
            ]
        },
        'first_run_outputs': {
            'status': 'pending',
            'output_paths': [],
            'run_metadata_path': None,
            'producer': 'step3b'
        }
    }

    python_stub = f'''"""\nAuto-generated Step 3B factor implementation stub for {factor_id}.\nThis file is intended for IDE-side editing before Step 4 execution.\n"""\n\nfrom __future__ import annotations\n\nimport numpy as np\nimport pandas as pd\n\nREPORT_ID = {report_id!r}\nFACTOR_ID = {factor_id!r}\nSIGNAL_COLUMN = {signal_col!r}\n\n# CONTEXT:\n# - This module is generated by Step 3B and then edited in Cursor/Trae with human review.\n# - {factor_id} is a daily-frequency shadow factor reconstructed from OHLC inputs.\n\n# CONTRACT:\n# - Step 4 will call compute_factor(minute_df, daily_df); minute_df may be empty for daily-only factors.\n# - Required daily columns: ['ts_code', 'trade_date', 'open', 'high', 'low', 'close'].\n# - Output schema must be: ['ts_code', 'trade_date', SIGNAL_COLUMN].\n\n# RISK:\n# - This draft approximates the paper-level UBL logic and still needs your manual review.\n# - Any added neutralization or style controls should also be reflected in Step 2 specs.\n\n\ndef _zscore_by_date(df: pd.DataFrame, value_col: str) -> pd.Series:\n    grouped = df.groupby('trade_date')[value_col]\n    mean = grouped.transform('mean')\n    std = grouped.transform('std').mask(lambda s: s == 0)\n    return (df[value_col] - mean) / std\n\n\ndef compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:\n    required_daily = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close']\n    for column in required_daily:\n        if column not in daily_df.columns:\n            raise KeyError(f'missing daily column: {{column}}')\n\n    out = daily_df[required_daily].copy()\n    out = out.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)\n\n    body_top = out[['open', 'close']].max(axis=1)\n    body_bottom = out[['open', 'close']].min(axis=1)\n    upper_shadow = out['high'] - body_top\n    lower_shadow = body_bottom - out['low']\n    price_range = (out['high'] - out['low']).replace(0, np.nan).astype(float)\n\n    out['candle_up_norm'] = upper_shadow / out.groupby('ts_code')['high'].transform(lambda s: s.rolling(5, min_periods=1).mean())\n    out['candle_down_norm'] = lower_shadow / out.groupby('ts_code')['low'].transform(lambda s: s.rolling(5, min_periods=1).mean())\n    out['williams_up'] = ((out['high'] - out['close']) / price_range).astype(float)\n    out['williams_down'] = ((out['close'] - out['low']) / price_range).astype(float)\n\n    grouped = out.groupby('ts_code', sort=False)\n    out['candle_up_std20'] = grouped['candle_up_norm'].transform(lambda s: s.rolling(20, min_periods=5).std())\n    out['williams_down_mean20'] = grouped['williams_down'].transform(lambda s: s.rolling(20, min_periods=5).mean())\n\n    out['candle_up_std20_z'] = _zscore_by_date(out, 'candle_up_std20').fillna(0.0)\n    out['williams_down_mean20_z'] = _zscore_by_date(out, 'williams_down_mean20').fillna(0.0)\n    out[SIGNAL_COLUMN] = -(out['candle_up_std20_z'] + out['williams_down_mean20_z']) / 2.0\n\n    return out[['ts_code', 'trade_date', SIGNAL_COLUMN]].sort_values(['ts_code', 'trade_date']).reset_index(drop=True)\n\n\ndef main():\n    raise SystemExit('This is a Step 3B generated stub. Edit in IDE, then invoke from Step 4 runner.')\n\n\nif __name__ == '__main__':\n    main()\n'''

    qlib_expression = {
        'report_id': report_id,
        'factor_id': factor_id,
        'status': 'draft',
        'mode': 'daily_shadow_factor',
        'reason': 'UBL is daily-frequency and can reuse qlib-style OHLC features, but the final rolling/combination logic remains clearer in Python.',
        'candidate_expression_parts': {
            'daily_open': '$open',
            'daily_high': '$high',
            'daily_low': '$low',
            'daily_close': '$close'
        },
        'non_qlib_parts': [
            '5-day shadow normalization',
            '20-day rolling mean/std aggregation',
            'UBL component combination'
        ]
    }

    scaffold = {
        'report_id': report_id,
        'factor_id': factor_id,
        'execution_mode': 'direct_python',
        'data_layer': 'Step 3A daily-only local input + optional qlib feature frame',
        'compute_layer': {
            'python_required': [
                'candlestick shadow construction',
                'Williams-style shadow construction',
                '20-day rolling aggregation'
            ],
            'qlib_compatible': [
                'daily OHLC field access',
                'cross-sectional feature framing'
            ]
        },
        'ide_edit_expected': True
    }

    return implementation_plan, python_stub, qlib_expression, scaffold


def is_cpv_like_spec(spec: dict) -> bool:
    factor_id = str(spec.get('factor_id') or '')
    if 'CPV' in factor_id.upper():
        return True

    canonical = spec.get('canonical_spec') or {}
    required_inputs = [str(x).lower() for x in (canonical.get('required_inputs') or [])]
    formula_text = str(canonical.get('formula_text') or '').lower()
    cross_steps = ' '.join(str(x).lower() for x in (canonical.get('cross_sectional_steps') or []))

    has_core_fields = {'close', 'vol', 'amount'}.issubset(set(required_inputs))
    has_pv_semantics = any(token in f'{formula_text} {cross_steps}' for token in ['price-volume', '价量', 'corr', '相关'])
    return has_core_fields and has_pv_semantics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    args = ap.parse_args()
    enforce_direct_step_policy(args.manifest)
    _manifest, manifest_rid = apply_runtime_manifest(args.manifest)
    report_id = args.report_id or manifest_rid
    if not report_id:
        raise SystemExit('run_step3b.py requires --report-id or --manifest')

    prep = load_json(OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json')
    spec = load_json(OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    step2_handoff = load_step2_handoff(report_id)
    step2_research_context = build_step2_research_context(report_id, spec, step2_handoff)
    factor_id = spec.get('factor_id', report_id)

    # Hard consistency rule: filename report_id and JSON internal report_id must agree.
    if spec.get('report_id') != report_id:
        raise SystemExit(f'factor_spec_master.report_id mismatch: expected {report_id}, got {spec.get("report_id")}')

    if is_cpv_like_spec(spec):
        implementation_plan, python_stub, qlib_expression, hybrid_scaffold = build_cpv_artifacts(report_id, prep, spec)
    elif is_alpha002_spec(spec):
        implementation_plan, python_stub, qlib_expression, hybrid_scaffold = build_alpha002_artifacts(report_id, prep, spec)
    else:
        implementation_plan, python_stub, qlib_expression, hybrid_scaffold = build_shadow_artifacts(report_id, prep, spec)

    attach_step2_research_context(implementation_plan, qlib_expression, hybrid_scaffold, step2_research_context)
    python_stub = annotate_python_stub_with_research_context(python_stub, step2_research_context)

    code_dir = CODEGEN / report_id
    impl_path = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    stub_path = code_dir / f'factor_impl_stub__{report_id}.py'
    qlib_path = code_dir / f'qlib_expression_draft__{report_id}.json'
    hybrid_path = code_dir / f'hybrid_execution_scaffold__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'

    prep = load_json(OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json')
    step3a_ready = prep.get('feasibility') in {'ready', 'proxy_ready'}
    real_impl_rel = f'generated_code/{report_id}/factor_impl__{report_id}.py'
    real_impl_abs = FF / real_impl_rel
    stub_impl_rel = str(stub_path.relative_to(FF))
    executable_impl_rel = real_impl_rel if real_impl_abs.exists() else stub_impl_rel
    executable_impl_abs = FF / executable_impl_rel
    if real_impl_abs.exists():
        implementation_plan['step4_contract']['runner_entry'] = real_impl_rel

    write_json(impl_path, implementation_plan)
    write_text(stub_path, python_stub)
    write_json(qlib_path, qlib_expression)
    write_json(hybrid_path, hybrid_scaffold)

    # COMMENT_POLICY: execution_handoff
    # Step 3B handoff freezes the implementation/code artifact references for Step 4.
    existing_handoff = read_existing_json(handoff_path)
    handoff_payload = merge_handoff(existing_handoff, {
        'report_id': report_id,
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
        'first_run_outputs': {
            'status': 'pending',
            'output_paths': [],
            'run_metadata_path': None,
            'producer': 'step3b'
        }
    })
    write_json(handoff_path, handoff_payload)

    # Business-acceptance upgrade: if local execution snapshots already exist and a real implementation
    # is available, Step 3B should also generate first-run factor values instead of stopping at plan/code only.
    local_inputs = prep.get('local_input_paths') or {}
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    input_mode = str(local_inputs.get('input_mode') or '')
    executable_daily_only = input_mode == 'daily_only' and daily_rel
    executable_minute_daily = minute_rel and daily_rel
    if (executable_minute_daily or executable_daily_only) and executable_impl_abs.exists():
        first_run_outputs = generate_first_run_factor_values(
            report_id=report_id,
            factor_id=factor_id,
            implementation_path=executable_impl_abs,
            local_inputs=local_inputs,
            step2_research_context=step2_research_context,
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
