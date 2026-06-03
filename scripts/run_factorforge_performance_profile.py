#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import resolve_factorforge_context


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--factorforge-root', default=None)
    ap.add_argument('--write-report', action='store_true')
    args = ap.parse_args()
    ctx = resolve_factorforge_context(args.factorforge_root)
    rid = args.report_id
    run_dir = ctx.factorforge_root / 'runs' / rid
    formal_run_meta = load(run_dir / f'run_metadata__{rid}.json')
    step3b_run_meta = load(run_dir / f'step3b_sample_run_metadata__{rid}.json') or formal_run_meta
    self_quant = load(ctx.factorforge_root / 'evaluations' / rid / 'self_quant_analyzer' / 'evaluation_payload.json')
    qlib_backtest = load(ctx.factorforge_root / 'evaluations' / rid / 'qlib_backtest' / 'evaluation_payload.json')
    wrapper = load(ctx.objects_root / 'runtime_context' / f'ultimate_run_report__{rid}.json')
    formal_parquet_path = run_dir / f'factor_values__{rid}.parquet'
    formal_csv_path = run_dir / f'factor_values__{rid}.csv'
    formal_csv_sample_path = run_dir / f'factor_values_sample__{rid}.csv'
    step3b_parquet_path = run_dir / f'step3b_sample_factor_values__{rid}.parquet'
    step3b_csv_path = run_dir / f'step3b_sample_factor_values__{rid}.csv'
    step3b_csv_sample_path = run_dir / f'step3b_sample_factor_values_sample__{rid}.csv'
    if not step3b_parquet_path.exists() and not step3b_csv_path.exists():
        step3b_parquet_path = formal_parquet_path
        step3b_csv_path = formal_csv_path
        step3b_csv_sample_path = formal_csv_sample_path
    step3b_profile = step3b_run_meta.get('performance_profile') or {}
    csv_output_profile = step3b_profile.get('csv_output_profile') or {}
    formula_engine_profile = step3b_profile.get('formula_engine_profile') or {}
    operator_profile = formula_engine_profile.get('operator_profile') or {}
    parity_profile = formula_engine_profile.get('parity_profile') or {}
    kernel_profile = formula_engine_profile.get('kernel_profile') or {}
    by_operator = operator_profile.get('by_operator') or {}
    top_operator_bottlenecks = [
        {
            'operator': operator,
            'total_seconds': float(payload.get('total_seconds') or 0.0),
            'max_seconds': float(payload.get('max_seconds') or 0.0),
            'count': int(payload.get('count') or 0),
            'cache_hit_count': int(payload.get('cache_hit_count') or 0),
            'rows': int(payload.get('rows') or 0),
        }
        for operator, payload in sorted(
            by_operator.items(),
            key=lambda item: float((item[1] or {}).get('total_seconds') or 0.0),
            reverse=True,
        )[:5]
    ]
    report = {
        'report_id': rid,
        'step3b_performance_profile': step3b_profile,
        'step3b_csv_output_profile': csv_output_profile,
        'step3b_write_csv_seconds': (step3b_profile.get('phase_seconds') or {}).get('write_csv'),
        'step3b_factor_parquet_bytes': step3b_parquet_path.stat().st_size if step3b_parquet_path.exists() else 0,
        'step3b_factor_csv_bytes': step3b_csv_path.stat().st_size if step3b_csv_path.exists() else 0,
        'step3b_factor_csv_sample_bytes': step3b_csv_sample_path.stat().st_size if step3b_csv_sample_path.exists() else 0,
        'step3b_metadata_path': str(run_dir / f'step3b_sample_run_metadata__{rid}.json')
        if (run_dir / f'step3b_sample_run_metadata__{rid}.json').exists()
        else str(run_dir / f'run_metadata__{rid}.json'),
        'step4_formal_run_metadata_path': str(run_dir / f'run_metadata__{rid}.json')
        if (run_dir / f'run_metadata__{rid}.json').exists()
        else None,
        'formula_engine_profile': formula_engine_profile,
        'operator_profile': operator_profile,
        'kernel_profile': kernel_profile,
        'parity_profile': parity_profile,
        'top_operator_bottlenecks': top_operator_bottlenecks,
        'self_quant_performance_profile': self_quant.get('performance_profile'),
        'qlib_backtest_status': qlib_backtest.get('status'),
        'qlib_backtest_mode': qlib_backtest.get('mode'),
        'qlib_backtest_failure_reason': qlib_backtest.get('failure_reason'),
        'qlib_backtest_resource_guard': qlib_backtest.get('resource_guard'),
        'qlib_backtest_performance_profile': qlib_backtest.get('performance_profile'),
        'wrapper_command_timing': [
            {
                'name': c.get('name'),
                'returncode': c.get('returncode'),
                'started_at_utc': c.get('started_at_utc'),
                'finished_at_utc': c.get('finished_at_utc'),
            }
            for c in wrapper.get('commands', [])
        ],
        'artifact_sizes': {
            'factor_parquet_bytes': formal_parquet_path.stat().st_size if formal_parquet_path.exists() else 0,
            'factor_csv_bytes': formal_csv_path.stat().st_size if formal_csv_path.exists() else 0,
            'factor_csv_sample_bytes': formal_csv_sample_path.stat().st_size if formal_csv_sample_path.exists() else 0,
        },
        'step4_formal_artifact_sizes': {
            'factor_parquet_bytes': formal_parquet_path.stat().st_size if formal_parquet_path.exists() else 0,
            'factor_csv_bytes': formal_csv_path.stat().st_size if formal_csv_path.exists() else 0,
            'factor_csv_sample_bytes': formal_csv_sample_path.stat().st_size if formal_csv_sample_path.exists() else 0,
        },
    }
    if args.write_report:
        out = ctx.objects_root / 'validation' / f'performance_profile__{rid}.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(f'[WRITE] {out}')
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
