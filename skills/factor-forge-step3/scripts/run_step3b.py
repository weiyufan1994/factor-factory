#!/usr/bin/env python3
import argparse, json, shutil, subprocess
from pathlib import Path

WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = WORKSPACE / 'factorforge'
OBJ = FF / 'objects'
CODEGEN = FF / 'generated_code'
RUNS = FF / 'runs'


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


def build_cpv_artifacts(report_id: str, prep: dict, spec: dict):
    factor_id = spec.get('factor_id', 'CPV')
    canonical = spec.get('canonical_spec', {})
    sample = prep.get('sample_window', {})

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

    python_stub = f'''"""\nAuto-generated Step 3B factor implementation stub for {factor_id}.\nThis file is intended for IDE-side editing before Step 4 execution.\n"""\n\nfrom pathlib import Path\nimport pandas as pd\nimport numpy as np\n\nREPORT_ID = {report_id!r}\nFACTOR_ID = {factor_id!r}\n\n\ndef load_inputs(minute_df: pd.DataFrame, daily_df: pd.DataFrame):\n    \"\"\"Step 3A has already resolved paths / fields / proxies.\n    Step 4 should pass normalized DataFrames into this implementation.\n    \"\"\"\n    return minute_df.copy(), daily_df.copy()\n\n\ndef compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:\n    \"\"\"CPV hybrid implementation skeleton.\n\n    To be refined in IDE before Step 4 execution.\n    Current design:\n    1. minute-level price-volume correlation\n    2. aggregate daily signals\n    3. amount-based neutralization proxy\n    4. trend signal\n    5. equal-weight merge\n    \"\"\"\n    required_minute = ['ts_code', 'trade_date', 'trade_time', 'close', 'vol', 'amount']\n    required_daily = ['ts_code', 'trade_date', 'pct_chg', 'vol', 'amount']\n    for c in required_minute:\n        if c not in minute_df.columns:\n            raise KeyError(f'missing minute column: {{c}}')\n    for c in required_daily:\n        if c not in daily_df.columns:\n            raise KeyError(f'missing daily column: {{c}}')\n\n    out = pd.DataFrame(columns=['ts_code', 'trade_date', 'cpv_factor'])\n    return out\n\n\ndef main():\n    raise SystemExit('This is a Step 3B generated stub. Edit in IDE, then invoke from Step 4 runner.')\n\n\nif __name__ == '__main__':\n    main()\n'''

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    report_id = args.report_id

    prep = load_json(OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json')
    spec = load_json(OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    factor_id = spec.get('factor_id', report_id)

    # Hard consistency rule: filename report_id and JSON internal report_id must agree.
    if spec.get('report_id') != report_id:
        raise SystemExit(f'factor_spec_master.report_id mismatch: expected {report_id}, got {spec.get("report_id")}')

    if 'CPV' in factor_id.upper():
        implementation_plan, python_stub, qlib_expression, hybrid_scaffold = build_cpv_artifacts(report_id, prep, spec)
    else:
        raise SystemExit('Only CPV sample is supported in the first Step 3B implementation pass.')

    code_dir = CODEGEN / report_id
    impl_path = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    stub_path = code_dir / f'factor_impl_stub__{report_id}.py'
    qlib_path = code_dir / f'qlib_expression_draft__{report_id}.json'
    hybrid_path = code_dir / f'hybrid_execution_scaffold__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'

    write_json(impl_path, implementation_plan)
    write_text(stub_path, python_stub)
    write_json(qlib_path, qlib_expression)
    write_json(hybrid_path, hybrid_scaffold)
    prep = load_json(OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json')
    real_impl_rel = f'generated_code/{report_id}/factor_impl__{report_id}.py'
    real_impl_abs = FF / real_impl_rel

    handoff_payload = {
        'report_id': report_id,
        'step3a_ready': True,
        'step3b_ready': True,
        'implementation_plan_master_ref': impl_path.name,
        'factor_impl_ref': real_impl_rel if real_impl_abs.exists() else None,
        'factor_impl_stub_ref': str(stub_path.relative_to(FF)),
        'qlib_expression_draft_ref': str(qlib_path.relative_to(FF)),
        'hybrid_execution_scaffold_ref': str(hybrid_path.relative_to(FF)),
        'execution_mode': implementation_plan['implementation_mode'],
        'local_input_paths': prep.get('local_input_paths', {}),
        'first_run_outputs': {
            'status': 'pending',
            'output_paths': [],
            'run_metadata_path': None,
            'producer': 'step3b'
        }
    }
    write_json(handoff_path, handoff_payload)

    # Business-acceptance upgrade: if local execution snapshots already exist and a real implementation
    # is available, Step 3B should also generate first-run factor values instead of stopping at plan/code only.
    local_inputs = prep.get('local_input_paths') or {}
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    if minute_rel and daily_rel and real_impl_abs.exists():
        run_step4 = WORKSPACE / 'skills' / 'factor-forge-step4' / 'scripts' / 'run_step4.py'
        result = subprocess.run(
            ['python3', str(run_step4), '--report-id', report_id],
            cwd=str(WORKSPACE),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, end='')
        if result.returncode != 0:
            raise SystemExit(f'Step 3B first-run factor generation failed for {report_id} with code {result.returncode}')

        factor_parquet = RUNS / report_id / f'factor_values__{report_id}.parquet'
        factor_csv = RUNS / report_id / f'factor_values__{report_id}.csv'
        run_meta = RUNS / report_id / f'run_metadata__{report_id}.json'
        outputs = [str(p.relative_to(FF)) for p in [factor_parquet, factor_csv] if p.exists()]
        implementation_plan['first_run_outputs'] = {
            'status': 'ready' if outputs and run_meta.exists() else 'partial',
            'output_paths': outputs,
            'run_metadata_path': str(run_meta.relative_to(FF)) if run_meta.exists() else None,
            'producer': 'step3b'
        }
        implementation_plan['step4_contract']['runner_entry'] = real_impl_rel
        write_json(impl_path, implementation_plan)

        handoff_payload['factor_impl_ref'] = real_impl_rel
        handoff_payload['first_run_outputs'] = implementation_plan['first_run_outputs']
        write_json(handoff_path, handoff_payload)


if __name__ == '__main__':
    main()
