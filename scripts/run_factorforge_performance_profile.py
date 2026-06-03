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
    run_meta = load(ctx.factorforge_root / 'runs' / rid / f'run_metadata__{rid}.json')
    self_quant = load(ctx.factorforge_root / 'evaluations' / rid / 'self_quant_analyzer' / 'evaluation_payload.json')
    wrapper = load(ctx.objects_root / 'runtime_context' / f'ultimate_run_report__{rid}.json')
    factor_run_master = load(ctx.objects_root / 'factor_run_master' / f'factor_run_master__{rid}.json')
    acceptance_summary = factor_run_master.get('acceptance_summary') if isinstance(factor_run_master.get('acceptance_summary'), dict) else {}
    parquet_path = ctx.factorforge_root / 'runs' / rid / f'factor_values__{rid}.parquet'
    csv_path = ctx.factorforge_root / 'runs' / rid / f'factor_values__{rid}.csv'
    csv_sample_path = ctx.factorforge_root / 'runs' / rid / f'factor_values_sample__{rid}.csv'
    step3b_profile = run_meta.get('performance_profile') or {}
    step4_factor_io_profile = run_meta.get('step4_factor_io_profile') or {}
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
    phase_seconds = step3b_profile.get('phase_seconds') or {}
    diagnostics = []
    if step3b_profile.get('version') == 'factorforge_step3b_performance_profile_v1':
        diagnostics.append({'severity': 'info', 'code': 'STEP3B_PERFORMANCE_PROFILE_PRESENT', 'message': 'Step3B performance profile is present.'})
    if (kernel_profile.get('default_numpy_ts_profile') or {}).get('enabled') is True:
        diagnostics.append({'severity': 'info', 'code': 'DEFAULT_NUMPY_TS_KERNELS_ENABLED', 'message': 'Default NumPy TS kernels are enabled.'})
    if step4_factor_io_profile.get('version') == 'factorforge_step4_factor_io_profile_v1':
        diagnostics.append({'severity': 'info', 'code': 'STEP4_FACTOR_REUSE_PROFILE_PRESENT', 'message': 'Step4 factor IO/reuse profile is present.'})
    if acceptance_summary.get('version') == 'factorforge_production_acceptance_summary_v1':
        diagnostics.append({'severity': 'info', 'code': 'PRODUCTION_ACCEPTANCE_SUMMARY_PRESENT', 'message': 'Step4 production acceptance summary is present.'})
    else:
        diagnostics.append({'severity': 'warning', 'code': 'PRODUCTION_ACCEPTANCE_SUMMARY_MISSING', 'message': 'Step4 production acceptance summary is absent from factor_run_master.'})
    if step4_factor_io_profile.get('recomputed_factor') is True or step4_factor_io_profile.get('source') == 'step4_recompute_fallback':
        diagnostics.append({'severity': 'warning', 'code': 'STEP4_RECOMPUTE_FALLBACK', 'message': 'Step4 recomputed factor values.'})
    if parquet_path.exists():
        diagnostics.append({'severity': 'info', 'code': 'PARQUET_FORMAL_EVIDENCE_OK', 'message': 'Parquet factor evidence exists.'})
    if csv_output_profile.get('full_csv_absent_validated') is True or (csv_output_profile.get('csv_output_policy') in {'sample_csv', 'no_csv'} and not csv_path.exists()):
        diagnostics.append({'severity': 'info', 'code': 'FULL_CSV_ABSENT_BY_POLICY', 'message': 'Full CSV is absent by policy.'})
    compute_seconds = phase_seconds.get('compute_factor')
    normalize_seconds = phase_seconds.get('normalize_sort')
    if compute_seconds is not None and normalize_seconds is not None and float(compute_seconds or 0.0) > 0 and float(normalize_seconds) > float(compute_seconds) * 0.8:
        diagnostics.append({'severity': 'warning', 'code': 'NORMALIZE_SORT_DOMINANT', 'message': 'normalize/sort cost is high relative to compute_factor.'})
    reuse_gate = step4_factor_io_profile.get('reuse_gate') or {}
    if reuse_gate.get('decision') == 'reuse_allowed':
        diagnostics.append({'severity': 'info', 'code': 'REUSE_GATE_ALLOWED', 'message': 'Step4 reuse gate allowed artifact reuse.'})
    elif reuse_gate.get('decision') == 'recompute_required':
        diagnostics.append({'severity': 'warning', 'code': 'REUSE_GATE_RECOMPUTE_REQUIRED', 'message': 'Step4 reuse gate required recompute.'})
    elif reuse_gate.get('decision') == 'block_invalid_formal_reuse':
        diagnostics.append({'severity': 'blocker_candidate', 'code': 'REUSE_GATE_BLOCKED_INVALID_FORMAL_REUSE', 'message': 'Step4 refused to treat a sample/proof artifact as formal factor values.'})
    report = {
        'report_id': rid,
        'acceptance_summary': acceptance_summary,
        'step3b_performance_profile': step3b_profile,
        'step4_factor_io_profile': step4_factor_io_profile,
        'step3b_csv_output_profile': csv_output_profile,
        'step3b_write_csv_seconds': (step3b_profile.get('phase_seconds') or {}).get('write_csv'),
        'step3b_factor_parquet_bytes': parquet_path.stat().st_size if parquet_path.exists() else 0,
        'step3b_factor_csv_bytes': csv_path.stat().st_size if csv_path.exists() else 0,
        'step3b_factor_csv_sample_bytes': csv_sample_path.stat().st_size if csv_sample_path.exists() else 0,
        'formula_engine_profile': formula_engine_profile,
        'operator_profile': operator_profile,
        'kernel_profile': kernel_profile,
        'parity_profile': parity_profile,
        'top_operator_bottlenecks': top_operator_bottlenecks,
        'self_quant_performance_profile': self_quant.get('performance_profile'),
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
            'factor_parquet_bytes': parquet_path.stat().st_size if parquet_path.exists() else 0,
            'factor_csv_bytes': csv_path.stat().st_size if csv_path.exists() else 0,
            'factor_csv_sample_bytes': csv_sample_path.stat().st_size if csv_sample_path.exists() else 0,
        },
        'diagnostic_codes': [item['code'] for item in diagnostics],
        'diagnostics': diagnostics,
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
