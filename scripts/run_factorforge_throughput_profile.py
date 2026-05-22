#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


LARGE_CSV_BYTES = 100 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def is_tmp_path(path: Path) -> bool:
    resolved = path.expanduser().resolve()
    text = str(resolved)
    return text.startswith('/tmp/') or text.startswith('/private/tmp/')


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return {'_load_error': f'{type(exc).__name__}: {exc}'}


def safe_file_size(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except OSError:
        return None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def diagnostic(severity: str, code: str, message: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'severity': severity,
        'code': code,
        'message': message,
        'evidence': evidence or {},
    }


def recursive_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    except TypeError:
        return str(value).lower()


def has_qlib_provider_missing_native_attempt(payload: dict[str, Any]) -> bool:
    text = recursive_text(payload)
    provider_missing = any(token in text for token in [
        'no usable qlib provider',
        'provider missing',
        'provider_missing',
        'provider not found',
        'qlib provider',
    ])
    native_attempted = any(token in text for token in [
        'native',
        'native_attempted',
        'qlib.init',
        'provider_uri',
    ])
    return bool(provider_missing and native_attempted)


def collect_backend_timing(factor_run_master: dict[str, Any], qlib_payload: dict[str, Any], self_quant_payload: dict[str, Any]) -> dict[str, Any]:
    backend_runs = (((factor_run_master or {}).get('evaluation_results') or {}).get('backend_runs') or [])
    timing: dict[str, Any] = {
        'backend_runs': [
            {
                'backend': item.get('backend'),
                'status': item.get('status'),
                'mode': item.get('mode') or ((item.get('backend_config') or {}).get('mode') if isinstance(item.get('backend_config'), dict) else None),
                'payload_path': item.get('payload_path'),
            }
            for item in backend_runs
            if isinstance(item, dict)
        ],
    }
    sq_phase = ((self_quant_payload.get('performance_profile') or {}).get('phase_seconds') or {})
    if sq_phase:
        timing['self_quant_phase_seconds'] = sq_phase
    qlib_phase = ((qlib_payload.get('performance_profile') or {}).get('phase_seconds') or {})
    if qlib_phase:
        timing['qlib_phase_seconds'] = qlib_phase
    return timing


def collect_backend_timing_profile(run_meta: dict[str, Any], factor_run_master: dict[str, Any]) -> dict[str, Any]:
    for source in (run_meta, factor_run_master):
        profile = (source or {}).get('backend_timing_profile')
        if isinstance(profile, dict) and profile.get('version') == 'factorforge_step4_backend_timing_profile_v1':
            return profile
    return {}


def build_profile(root: Path, report_id: str) -> dict[str, Any]:
    run_dir = root / 'runs' / report_id
    eval_dir = root / 'evaluations' / report_id
    obj_dir = root / 'objects'
    run_meta_path = run_dir / f'run_metadata__{report_id}.json'
    factor_run_master_path = obj_dir / 'factor_run_master' / f'factor_run_master__{report_id}.json'
    self_quant_path = eval_dir / 'self_quant_analyzer' / 'evaluation_payload.json'
    qlib_path = eval_dir / 'qlib_backtest' / 'evaluation_payload.json'
    factor_parquet = run_dir / f'factor_values__{report_id}.parquet'
    factor_csv = run_dir / f'factor_values__{report_id}.csv'
    factor_csv_sample = run_dir / f'factor_values_sample__{report_id}.csv'

    run_meta = load_json(run_meta_path)
    factor_run_master = load_json(factor_run_master_path)
    self_quant_payload = load_json(self_quant_path)
    qlib_payload = load_json(qlib_path)
    diagnostics: list[dict[str, Any]] = []

    if not run_meta_path.exists():
        diagnostics.append(diagnostic('warning', 'ARTIFACT_MISSING', 'Step3B/Step4 run metadata is missing.', {'path': str(run_meta_path)}))
    if not self_quant_path.exists():
        diagnostics.append(diagnostic('info', 'ARTIFACT_MISSING', 'self_quant payload is missing.', {'path': str(self_quant_path)}))
    if not qlib_path.exists():
        diagnostics.append(diagnostic('info', 'ARTIFACT_MISSING', 'qlib payload is missing.', {'path': str(qlib_path)}))

    perf = run_meta.get('performance_profile') if isinstance(run_meta.get('performance_profile'), dict) else {}
    phase = perf.get('phase_seconds') if isinstance(perf.get('phase_seconds'), dict) else {}
    csv_output_profile = perf.get('csv_output_profile') if isinstance(perf.get('csv_output_profile'), dict) else {}
    normalize_sort_profile = perf.get('normalize_sort_profile') if isinstance(perf.get('normalize_sort_profile'), dict) else {}
    step4_factor_io = run_meta.get('step4_factor_io_profile') if isinstance(run_meta.get('step4_factor_io_profile'), dict) else {}
    step4_input_io = run_meta.get('input_io_profile') if isinstance(run_meta.get('input_io_profile'), dict) else {}
    backend_timing_profile = collect_backend_timing_profile(run_meta, factor_run_master)
    backend_timing = collect_backend_timing(factor_run_master, qlib_payload, self_quant_payload)

    compute_seconds = as_float(phase.get('compute_factor'))
    normalize_seconds = as_float(phase.get('normalize_sort'))
    factor_parquet_bytes = safe_file_size(factor_parquet)
    factor_csv_bytes = safe_file_size(factor_csv)
    factor_csv_sample_bytes = safe_file_size(factor_csv_sample)
    csv_output_policy = csv_output_profile.get('csv_output_policy')
    formal_evidence_format = csv_output_profile.get('formal_evidence_format')
    if formal_evidence_format is None and factor_parquet_bytes is not None:
        formal_evidence_format = 'parquet'
    row_count = run_meta.get('row_count')
    parquet_formal_evidence_ok = bool(
        formal_evidence_format == 'parquet'
        and factor_parquet_bytes is not None
        and row_count is not None
    )
    full_csv_absent_by_policy = bool(
        csv_output_policy in {'sample_csv', 'no_csv'}
        and factor_csv_bytes is None
    )
    sample_csv_present = bool(factor_csv_sample_bytes is not None)
    full_csv_absence_reason = csv_output_profile.get('full_csv_absence_reason')
    if full_csv_absent_by_policy and not full_csv_absence_reason:
        full_csv_absence_reason = f'step3b_{csv_output_policy}_policy'
    self_quant_phase = ((self_quant_payload.get('performance_profile') or {}).get('phase_seconds') or {})
    self_quant_seconds = as_float(self_quant_phase.get('total'))

    artifacts_found = {
        'step3b_run_metadata': bool(run_meta_path.exists() and perf),
        'step4_run_metadata': bool(run_meta_path.exists() and (step4_factor_io or step4_input_io)),
        'factor_run_master': factor_run_master_path.exists(),
        'self_quant_payload': self_quant_path.exists(),
        'qlib_payload': qlib_path.exists(),
    }

    if factor_csv_bytes is not None and factor_csv_bytes > LARGE_CSV_BYTES:
        diagnostics.append(diagnostic(
            'warning',
            'FULL_CSV_LARGE',
            'Full factor CSV exists and exceeds 100MB.',
            {'path': str(factor_csv), 'bytes': factor_csv_bytes, 'threshold_bytes': LARGE_CSV_BYTES},
        ))
    if normalize_seconds is not None and compute_seconds is not None and normalize_seconds > compute_seconds * 0.8:
        diagnostics.append(diagnostic(
            'warning',
            'NORMALIZE_SORT_DOMINANT',
            'normalize_sort cost is close to compute_factor cost.',
            {'normalize_sort_seconds': normalize_seconds, 'compute_factor_seconds': compute_seconds, 'ratio': normalize_seconds / compute_seconds if compute_seconds else None},
        ))
    if normalize_sort_profile.get('sort_contract_trusted') is True:
        diagnostics.append(diagnostic(
            'info',
            'SORT_CONTRACT_TRUSTED',
            'Step3B trusted the Step3A sort contract after validation.',
            normalize_sort_profile,
        ))
    if normalize_sort_profile.get('full_sort_skipped') is True:
        diagnostics.append(diagnostic(
            'info',
            'FULL_SORT_SKIPPED_BY_CONTRACT',
            'Step3B skipped full normalize_sort sorting because the Step3A sort contract was trusted.',
            normalize_sort_profile,
        ))
    if normalize_sort_profile and normalize_sort_profile.get('sort_contract_present') is True and normalize_sort_profile.get('sort_contract_trusted') is not True:
        diagnostics.append(diagnostic(
            'info',
            'SORT_CONTRACT_FALLBACK',
            'Step3B did not trust the Step3A sort contract and used the full normalize_sort path.',
            {'fallback_reason': normalize_sort_profile.get('fallback_reason'), **normalize_sort_profile},
        ))
    if step4_factor_io.get('source') == 'step4_recompute_fallback' or step4_factor_io.get('recomputed_factor') is True:
        diagnostics.append(diagnostic(
            'blocker_candidate',
            'STEP4_RECOMPUTE_FALLBACK',
            'Step4 appears to recompute factor values instead of reusing Step3B parquet.',
            step4_factor_io,
        ))
    if has_qlib_provider_missing_native_attempt(qlib_payload):
        diagnostics.append(diagnostic(
            'warning',
            'QLIB_PROVIDER_MISSING_NATIVE_ATTEMPTED',
            'qlib payload indicates native/provider attempt while provider is missing.',
            {'path': str(qlib_path), 'status': qlib_payload.get('status'), 'mode': qlib_payload.get('mode')},
        ))
    qlib_native_timing = ((backend_timing_profile.get('backends') or {}).get('qlib_native') or {})
    if qlib_native_timing.get('attempted') is False and str(qlib_native_timing.get('status') or '').startswith('skipped'):
        diagnostics.append(diagnostic(
            'info',
            'QLIB_NATIVE_SKIPPED_PREFLIGHT',
            'Step4 qlib native backend was skipped by preflight.',
            qlib_native_timing,
        ))
    if not backend_timing_profile and not backend_timing.get('backend_runs') and not backend_timing.get('self_quant_phase_seconds') and not backend_timing.get('qlib_phase_seconds'):
        diagnostics.append(diagnostic(
            'info',
            'BACKEND_TIMING_MISSING',
            'Step4 backend timing is not available in existing artifacts.',
            {'factor_run_master_path': str(factor_run_master_path)},
        ))
    if parquet_formal_evidence_ok:
        diagnostics.append(diagnostic(
            'info',
            'PARQUET_FORMAL_EVIDENCE_OK',
            'Factor parquet exists and run metadata declares row_count.',
            {'path': str(factor_parquet), 'bytes': factor_parquet_bytes, 'row_count': row_count},
        ))
    if full_csv_absent_by_policy:
        diagnostics.append(diagnostic(
            'info',
            'FULL_CSV_ABSENT_BY_POLICY',
            'Full factor CSV is absent as allowed by the Step3B CSV output policy.',
            {'csv_output_policy': csv_output_policy, 'reason': full_csv_absence_reason},
        ))
    if csv_output_policy == 'sample_csv' and sample_csv_present:
        diagnostics.append(diagnostic(
            'info',
            'SAMPLE_CSV_PRESENT',
            'Sample factor CSV exists for audit while parquet remains formal evidence.',
            {'path': str(factor_csv_sample), 'bytes': factor_csv_sample_bytes},
        ))
    if csv_output_policy == 'no_csv' and full_csv_absent_by_policy and not sample_csv_present:
        diagnostics.append(diagnostic(
            'info',
            'NO_CSV_ACCEPTED',
            'No factor CSV audit file is present as allowed by explicit no_csv policy.',
            {'csv_output_policy': csv_output_policy, 'reason': full_csv_absence_reason},
        ))

    recommendations: list[str] = []
    codes = {item['code'] for item in diagnostics}
    if 'FULL_CSV_LARGE' in codes:
        recommendations.append('Use sample_csv or no_csv for performance runs after audit requirements are satisfied.')
    if 'NORMALIZE_SORT_DOMINANT' in codes:
        recommendations.append('Inspect sortedness and normalize_sort path before optimizing formula compute.')
    if 'STEP4_RECOMPUTE_FALLBACK' in codes:
        recommendations.append('Ensure Step4 reuses Step3B factor parquet and does not run compute_factor fallback.')
    if 'QLIB_PROVIDER_MISSING_NATIVE_ATTEMPTED' in codes:
        recommendations.append('Gate native qlib backend on provider availability or record it as skipped.')
    if 'QLIB_NATIVE_SKIPPED_PREFLIGHT' in codes:
        recommendations.append('qlib native backend is already preflight-gated; inspect provider setup only if native qlib evidence is required.')
    qlib_native_attempted = bool(has_qlib_provider_missing_native_attempt(qlib_payload) or 'native' in recursive_text(qlib_payload))
    if qlib_native_timing.get('attempted') is False:
        qlib_native_attempted = False

    return {
        'contract_version': 'factorforge_throughput_profile_v1',
        'report_id': report_id,
        'root': str(root),
        'created_at_utc': utc_now(),
        'artifacts_found': artifacts_found,
        'step3b': {
            'total_seconds': as_float(phase.get('total')),
            'phase_seconds': phase,
            'compute_factor_seconds': compute_seconds,
            'normalize_sort_seconds': normalize_seconds,
            'normalize_sort_profile': normalize_sort_profile,
            'parquet_write_seconds': as_float(phase.get('write_parquet')),
            'csv_write_seconds': as_float(phase.get('write_csv')),
            'metadata_write_seconds': as_float(phase.get('write_metadata')),
            'csv_output_policy': csv_output_policy,
            'formal_evidence_format': formal_evidence_format,
            'parquet_formal_evidence_ok': parquet_formal_evidence_ok,
            'full_csv_absent_by_policy': full_csv_absent_by_policy,
            'full_csv_absence_reason': full_csv_absence_reason,
            'sample_csv_present': sample_csv_present,
            'factor_parquet_path': str(factor_parquet),
            'factor_csv_path': str(factor_csv) if factor_csv_bytes is not None else None,
            'factor_csv_sample_path': str(factor_csv_sample) if factor_csv_sample_bytes is not None else None,
            'factor_parquet_bytes': factor_parquet_bytes,
            'factor_csv_bytes': factor_csv_bytes,
            'factor_csv_sample_bytes': factor_csv_sample_bytes,
        },
        'step4': {
            'total_seconds': None,
            'factor_io_profile': step4_factor_io,
            'input_io_profile': step4_input_io,
            'backend_timing': backend_timing,
            'backend_timing_profile': backend_timing_profile,
            'self_quant_seconds': self_quant_seconds,
            'qlib_status': qlib_payload.get('status') or qlib_native_timing.get('status'),
            'qlib_native_attempted': qlib_native_attempted,
        },
        'diagnostics': diagnostics,
        'recommendations': recommendations,
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', default=None)
    ap.add_argument('--allow-non-tmp-output', action='store_true')
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    output = Path(args.output).expanduser() if args.output else None
    if output is not None and not is_tmp_path(output) and not args.allow_non_tmp_output:
        print(f'BLOCK_THROUGHPUT_PROFILE_NON_TMP_OUTPUT: {output}', file=sys.stderr)
        return 1
    profile = build_profile(root, args.report_id)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
