#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shlex
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FACTORFORGE.parent
OBJ = FACTORFORGE / 'objects'
RUNS = FACTORFORGE / 'runs'

from factor_factory.data_access import infer_signal_column
from factor_factory.runtime_context import (
    load_runtime_manifest,
    manifest_factorforge_root,
    manifest_path,
    manifest_report_id,
)

PLACEHOLDER_TOKENS = {'', 'TODO', 'TBD', 'PLACEHOLDER', 'placeholder', 'todo', 'tbd', None}


def enforce_direct_step_policy(manifest_path_arg: str | None = None) -> None:
    global FACTORFORGE, WORKSPACE, OBJ, RUNS
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step4 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FACTORFORGE.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    if manifest_path_arg:
        manifest = load_runtime_manifest(manifest_path_arg)
        if manifest_factorforge_root(manifest).expanduser().resolve() != debug_root:
            raise SystemExit('BLOCKED_DIRECT_STEP: direct debug manifest must point to FACTORFORGE_DEBUG_ROOT.')
    FACTORFORGE = debug_root
    WORKSPACE = FACTORFORGE.parent
    OBJ = FACTORFORGE / 'objects'
    RUNS = FACTORFORGE / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() in PLACEHOLDER_TOKENS
    if isinstance(value, dict):
        return any(contains_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_placeholder(v) for v in value)
    try:
        return value in PLACEHOLDER_TOKENS
    except TypeError:
        return False


def file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        'path': str(path),
        'size_bytes': stat.st_size,
        'mtime_utc': datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    }


def build_evaluation_plan(handoff: dict[str, Any]) -> dict[str, Any]:
    # COMMENT_POLICY: backend_extensibility
    # Evaluation plan is user-extensible via handoff_to_step4.evaluation_plan.
    # If absent, keep a visible default instead of hidden hard-code.
    plan = handoff.get('evaluation_plan') or {}
    backends = plan.get('backends') or [
        {'name': 'self_quant_analyzer', 'mode': 'quick'},
        {'name': 'qlib_backtest', 'mode': 'default'},
    ]
    return {
        'backends': backends,
        'metric_policy': plan.get('metric_policy', 'extensible')
    }


def build_backend_runs_stub(report_id: str, evaluation_plan: dict[str, Any], run_status: str) -> list[dict[str, Any]]:
    runs = []
    for item in evaluation_plan.get('backends', []):
        backend = item.get('name', 'unknown_backend')
        mode = item.get('mode', 'default')
        payload_dir = FACTORFORGE / 'evaluations' / report_id / backend
        payload_path = payload_dir / 'evaluation_payload.json'
        summary = {
            'mode': mode,
            'note': 'backend adapter placeholder; envelope is ready for self_quant / qlib / future evaluators'
        }
        status = 'skipped' if run_status == 'failed' else 'partial'
        runs.append({
            'backend': backend,
            'status': status,
            'summary': summary,
            'artifact_paths': [str(payload_path)] if status != 'skipped' else [],
            'payload_path': str(payload_path) if status != 'skipped' else None,
            'backend_config': item,
        })
    return runs


def runtime_python() -> Path:
    venv_python = WORKSPACE / '.venvs' / 'quant-research' / 'bin' / 'python'
    if venv_python.exists():
        return venv_python
    if sys.executable:
        return Path(sys.executable)
    return Path('/usr/bin/python3')


def resolve_backend_script_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    p = Path(raw_path)
    if p.is_absolute():
        return p

    # Accept either repo-relative path or short script name under step4/scripts.
    candidates = [
        REPO_ROOT / p,
        REPO_ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / p,
        FACTORFORGE / p,
        FACTORFORGE / 'skills' / 'factor-forge-step4' / 'scripts' / p,
    ]
    for c in candidates:
        if c.exists():
            return c
    return REPO_ROOT / p


def run_backend_script(
    report_id: str,
    backend: str,
    script_path: Path,
    payload_path: Path,
    backend_cfg: dict[str, Any],
    manifest_path_arg: Path | None = None,
) -> tuple[int, str]:
    extra_args: list[str] = []
    raw_args = backend_cfg.get('args')
    if isinstance(raw_args, list):
        extra_args = [str(x) for x in raw_args]
    elif isinstance(raw_args, str):
        extra_args = shlex.split(raw_args)

    # Custom backends receive the same CLI envelope as built-in adapters.
    cmd = [
        str(runtime_python()),
        str(script_path),
        '--report-id',
        report_id,
        '--output',
        str(payload_path),
        *extra_args,
    ]
    if manifest_path_arg is not None:
        cmd.extend(['--manifest', str(manifest_path_arg)])
    env = os.environ.copy()
    env['STEP4_BACKEND_NAME'] = backend
    if manifest_path_arg is not None:
        env['FACTORFORGE_RUNTIME_MANIFEST'] = str(manifest_path_arg)
        try:
            manifest = load_runtime_manifest(manifest_path_arg)
            env['FACTORFORGE_ROOT'] = str(manifest_factorforge_root(manifest))
        except Exception:
            pass
    raw_env = backend_cfg.get('env')
    if isinstance(raw_env, dict):
        for k, v in raw_env.items():
            env[str(k)] = str(v)

    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='')
    return result.returncode, f'cmd={" ".join(cmd)}'


def write_backend_payloads(report_id: str, backend_runs: list[dict[str, Any]], manifest_path_arg: Path | None = None) -> list[dict[str, Any]]:
    # Builtin adapters and custom adapters share one payload contract.
    updated: list[dict[str, Any]] = []
    for item in backend_runs:
        payload_path = item.get('payload_path')
        if not payload_path:
            updated.append(item)
            continue
        p = Path(payload_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        backend = item.get('backend')
        backend_cfg = item.get('backend_config') if isinstance(item.get('backend_config'), dict) else {}
        if backend in {'self_quant_analyzer', 'qlib_backtest'}:
            script_name = 'self_quant_adapter.py' if backend == 'self_quant_analyzer' else 'qlib_backtest_adapter.py'
            adapter = REPO_ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / script_name
            result, exec_note = run_backend_script(report_id, backend, adapter, p, backend_cfg, manifest_path_arg=manifest_path_arg)
            new_item = dict(item)
            new_item['status'] = 'success' if result == 0 else 'failed'
            if not p.exists():
                payload = {
                    'backend': backend,
                    'status': new_item['status'],
                    'mode': backend_cfg.get('mode', 'builtin'),
                    'summary': {
                        'error': 'builtin backend did not write payload',
                        'exec_note': exec_note,
                        'returncode': result,
                    },
                    'producer': 'step4-builtin-fallback',
                }
                p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            if p.exists():
                payload = json.loads(p.read_text(encoding='utf-8'))
                payload_status = payload.get('status')
                if payload_status in {'success', 'partial', 'failed', 'skipped'}:
                    new_item['status'] = payload_status
                if backend == 'self_quant_analyzer':
                    new_item['summary'] = payload.get('ic_summary', payload)
                else:
                    new_item['summary'] = payload.get('native_backtest_metrics') or payload.get('stub_backtest_metrics', payload)
            updated.append(new_item)
            continue

        custom_script = resolve_backend_script_path(
            str(backend_cfg.get('script_path') or backend_cfg.get('adapter_script') or '').strip() or None
        )
        if custom_script is not None:
            # Non-builtin backends are first-class: execute script and trust payload contract.
            new_item = dict(item)
            rc, exec_note = run_backend_script(report_id, backend, custom_script, p, backend_cfg, manifest_path_arg=manifest_path_arg)
            new_item['status'] = 'success' if rc == 0 else 'failed'
            if not p.exists():
                # Guardrail: never leave missing payload for downstream Step5 readers.
                payload = {
                    'backend': backend,
                    'status': new_item['status'],
                    'mode': backend_cfg.get('mode', 'custom'),
                    'summary': {'error': 'custom backend did not write payload', 'exec_note': exec_note},
                    'producer': 'step4-custom-hook',
                }
                p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            payload = json.loads(p.read_text(encoding='utf-8'))
            new_item['summary'] = payload.get('summary') or payload.get('metrics') or payload
            updated.append(new_item)
            continue

        payload = {
            'backend': backend,
            'status': item.get('status'),
            'summary': item.get('summary'),
            'producer': 'step4-envelope',
            'extensible_metrics': True
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        updated.append(item)
    return updated


def resolve_input_paths(report_id: str, manifest: dict[str, Any] | None = None) -> dict[str, Path]:
    if manifest:
        objects = manifest.get('objects') or {}
        paths = {
            'factor_spec_master': Path(objects['factor_spec_master']),
            'data_prep_master': Path(objects['data_prep_master']),
            'handoff_to_step4': Path(objects['handoff_to_step4']),
        }
        return paths
    return {
        'factor_spec_master': OBJ / 'factor_spec_master' / f'factor_spec_master__{report_id}.json',
        'data_prep_master': OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json',
        'handoff_to_step4': OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json',
    }


def validate_inputs(report_id: str, fsm: dict[str, Any], dpm: dict[str, Any], handoff: dict[str, Any], input_paths: dict[str, Path]) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[dict[str, Any]] = []
    warnings: list[str] = []

    for name, path in input_paths.items():
        if not path.exists():
            issues.append({'severity': 'error', 'code': 'MISSING_INPUT', 'message': f'missing required input: {name}', 'evidence': {'path': str(path)}})

    if issues:
        return issues, warnings

    if fsm.get('report_id') != report_id:
        issues.append({'severity': 'error', 'code': 'FSM_REPORT_ID_MISMATCH', 'message': 'factor_spec_master.report_id mismatch', 'evidence': {'expected': report_id, 'actual': fsm.get('report_id')}})
    if dpm.get('report_id') != report_id:
        issues.append({'severity': 'error', 'code': 'DPM_REPORT_ID_MISMATCH', 'message': 'data_prep_master.report_id mismatch', 'evidence': {'expected': report_id, 'actual': dpm.get('report_id')}})
    if handoff.get('report_id') != report_id:
        issues.append({'severity': 'error', 'code': 'HANDOFF_REPORT_ID_MISMATCH', 'message': 'handoff_to_step4.report_id mismatch', 'evidence': {'expected': report_id, 'actual': handoff.get('report_id')}})

    factor_id = fsm.get('factor_id')
    if contains_placeholder(factor_id):
        issues.append({'severity': 'error', 'code': 'FACTOR_ID_INVALID', 'message': 'factor_id is missing or placeholder', 'evidence': {'factor_id': factor_id}})
    if dpm.get('factor_id') != factor_id:
        issues.append({'severity': 'error', 'code': 'FACTOR_ID_MISMATCH', 'message': 'data_prep_master.factor_id mismatch', 'evidence': {'fsm': factor_id, 'dpm': dpm.get('factor_id')}})

    sample_window = dpm.get('sample_window', {})
    if contains_placeholder(sample_window.get('start')) or contains_placeholder(sample_window.get('end')):
        issues.append({'severity': 'error', 'code': 'SAMPLE_WINDOW_INVALID', 'message': 'sample window missing start/end', 'evidence': {'sample_window': sample_window}})

    if contains_placeholder(dpm.get('field_mapping')):
        issues.append({'severity': 'error', 'code': 'FIELD_MAPPING_INVALID', 'message': 'field_mapping missing or contains placeholder', 'evidence': {'field_mapping': dpm.get('field_mapping')}})

    if not dpm.get('data_sources'):
        issues.append({'severity': 'error', 'code': 'DATA_SOURCES_MISSING', 'message': 'data_sources missing', 'evidence': {}})

    if fsm.get('human_review_required'):
        warnings.append('factor_spec_master indicates human_review_required=true; Step 4 proceeds under frozen-schema execution discipline.')

    ambiguities = fsm.get('ambiguities') or []
    if ambiguities:
        warnings.append(f'factor_spec_master ambiguities present: {len(ambiguities)} item(s); Step 4 will not invent missing semantics.')

    return issues, warnings


def resolve_implementation_path(handoff: dict[str, Any], fsm: dict[str, Any]) -> tuple[str | None, list[str]]:
    notes: list[str] = []
    path = handoff.get('factor_impl_ref') or handoff.get('factor_impl_stub_ref') or handoff.get('implementation_path')
    if path and not contains_placeholder(path):
        source = 'factor_impl_ref' if handoff.get('factor_impl_ref') else ('factor_impl_stub_ref' if handoff.get('factor_impl_stub_ref') else 'implementation_path')
        notes.append(f'implementation path resolved from handoff_to_step4:{source}')
        return path, notes

    canonical = fsm.get('canonical_spec', {})
    fallback = canonical.get('implementation_path') or fsm.get('implementation_path')
    if fallback and not contains_placeholder(fallback):
        notes.append('implementation path resolved from factor_spec_master fallback')
        return fallback, notes

    notes.append('implementation path missing in handoff_to_step4 and factor_spec_master fallback')
    return None, notes


def import_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot create import spec for {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_failure_outputs(report_id: str, factor_id: str | None, implementation_path: str | None, sample_window: dict[str, Any], run_dir: Path, input_paths: dict[str, Path], issues: list[dict[str, Any]], warnings: list[str], failure_reason: str, failed_stage: str, start_utc: str, revision_of: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json'
    diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json'

    evaluation_plan = {
        'backends': [
            {'name': 'self_quant_analyzer', 'mode': 'quick'},
            {'name': 'qlib_backtest', 'mode': 'default'},
        ],
        'metric_policy': 'extensible',
    }
    backend_runs = build_backend_runs_stub(report_id, evaluation_plan, 'failed')

    run_master = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'failed',
        'implementation_path': implementation_path,
        'output_paths': [],
        'sample_window': sample_window or {},
        'runtime_notes': warnings + [f'failed_stage={failed_stage}'],
        'diagnostic_summary': {'row_count': 0, 'date_count': 0, 'ticker_count': 0},
        'evaluation_plan': evaluation_plan,
        'evaluation_results': {'backend_runs': backend_runs},
        'failure_reason': failure_reason,
        'started_at_utc': start_utc,
        'finished_at_utc': utc_now(),
        'input_paths': {k: str(v) for k, v in input_paths.items()},
        'validation_pointer': str(diag_path),
        'handoff_to_step5_path': str(handoff_path),
    }
    if revision_of:
        run_master['revision'] = {'revises': revision_of, 'reason': 'validator-directed explicit revision'}

    diagnostics = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'failed',
        'diagnostic_generated_at_utc': utc_now(),
        'evaluation_plan': evaluation_plan,
        'evaluation_results': {'backend_runs': backend_runs},
        'input_validation': {
            'exists_check': {k: v.exists() for k, v in input_paths.items()},
            'schema_check': {'frozen_schema_execution': True},
            'consistency_check': {},
            'placeholder_check': {}
        },
        'execution_trace': {
            'implementation_path': implementation_path,
            'commands': [],
            'runtime_seconds': None,
            'exception_type': None,
            'exception_message': failure_reason
        },
        'output_validation': {
            'output_exists': False,
            'output_paths': [],
            'file_sizes': {},
            'row_count': 0,
            'date_count': 0,
            'ticker_count': 0
        },
        'quality_checks': {
            'window_complete': False,
            'null_ratio': {},
            'duplicate_ratio': {},
            'key_uniqueness': {},
            'sort_order_ok': False
        },
        'issues': issues,
        'failure_context': {
            'failed_stage': failed_stage,
            'failure_reason': failure_reason,
            'retryable': True
        },
        'recommendation': {
            'can_handoff_to_step5': False,
            'recommended_status': 'failed',
            'next_action': 'Fix input/schema/implementation path and rerun Step 4.'
        }
    }

    handoff = {
        'report_id': report_id,
        'factor_id': factor_id,
        'run_status': 'failed',
        'factor_run_master_path': str(run_master_path),
        'diagnostics_path': str(diag_path),
        'output_paths': [],
        'sample_window_target': sample_window or {},
        'sample_window_actual': None,
        'coverage_ratio': 0.0,
        'row_count': 0,
        'date_count': 0,
        'ticker_count': 0,
        'evaluation_plan': evaluation_plan,
        'evaluation_results': {'backend_runs': backend_runs},
        'key_warnings': warnings,
        'failure_reason': failure_reason,
        'can_enter_step5': False,
        'recommended_step5_scope': None,
        'notes_for_step5': [f'Step 4 failed at {failed_stage}; do not evaluate.']
    }
    return run_master, diagnostics, handoff


def main() -> None:
    global FACTORFORGE, WORKSPACE, OBJ, RUNS
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    args = ap.parse_args()
    enforce_direct_step_policy(args.manifest)
    manifest: dict[str, Any] | None = load_runtime_manifest(args.manifest) if args.manifest else None
    if manifest:
        FACTORFORGE = manifest_factorforge_root(manifest)
        WORKSPACE = FACTORFORGE.parent
        OBJ = FACTORFORGE / 'objects'
        RUNS = FACTORFORGE / 'runs'
    report_id = args.report_id or (manifest_report_id(manifest) if manifest else None)
    if not report_id:
        raise SystemExit('run_step4.py requires --report-id or --manifest')
    manifest_path_arg = Path(args.manifest).expanduser() if args.manifest else None
    start_utc = utc_now()
    input_paths = resolve_input_paths(report_id, manifest=manifest)
    run_dir = RUNS / report_id
    ensure_dir(run_dir)

    issues: list[dict[str, Any]] = []
    warnings: list[str] = []
    fsm: dict[str, Any] = {}
    dpm: dict[str, Any] = {}
    handoff: dict[str, Any] = {}
    factor_id: str | None = None
    implementation_path: str | None = None

    try:
        missing = [name for name, path in input_paths.items() if not path.exists()]
        if missing:
            for name in missing:
                issues.append({'severity': 'error', 'code': 'MISSING_INPUT', 'message': f'missing required input: {name}', 'evidence': {'path': str(input_paths[name])}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, None, None, {}, run_dir, input_paths, issues, warnings, 'MISSING_REQUIRED_INPUT', 'input_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        fsm = load_json(input_paths['factor_spec_master'])
        dpm = load_json(input_paths['data_prep_master'])
        handoff = load_json(input_paths['handoff_to_step4'])
        factor_id = fsm.get('factor_id')

        v_issues, v_warnings = validate_inputs(report_id, fsm, dpm, handoff, input_paths)
        issues.extend(v_issues)
        warnings.extend(v_warnings)
        implementation_path, path_notes = resolve_implementation_path(handoff, fsm)
        warnings.extend(path_notes)

        if implementation_path is None:
            issues.append({'severity': 'error', 'code': 'IMPLEMENTATION_PATH_MISSING', 'message': 'implementation path unresolved', 'evidence': {'resolution_order': ['handoff_to_step4', 'factor_spec_master']}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, None, dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'IMPLEMENTATION_PATH_MISSING', 'implementation_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        if issues:
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, implementation_path, dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'INPUT_VALIDATION_FAILED', 'input_validation', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        impl_path = Path(implementation_path)
        if not impl_path.is_absolute():
            impl_path = (FACTORFORGE / impl_path) if str(implementation_path).startswith('generated_code/') else (WORKSPACE / implementation_path)
        if not impl_path.exists():
            issues.append({'severity': 'error', 'code': 'IMPLEMENTATION_PATH_NOT_FOUND', 'message': 'resolved implementation path does not exist', 'evidence': {'path': str(impl_path)}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'IMPLEMENTATION_PATH_NOT_FOUND', 'implementation_resolution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        module = import_module_from_path(impl_path)
        if not hasattr(module, 'compute_factor'):
            issues.append({'severity': 'error', 'code': 'COMPUTE_FACTOR_MISSING', 'message': 'implementation module missing compute_factor', 'evidence': {'path': str(impl_path)}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'COMPUTE_FACTOR_MISSING', 'implementation_import', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        # Frozen-schema execution: do not fabricate external data access. If no normalized local input snapshots
        # are provided by Step 3A, Step 4 fails explicitly rather than pretending to have executed.
        local_inputs = handoff.get('local_input_paths') or dpm.get('local_input_paths') or {}
        minute_path = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
        daily_path = (
            local_inputs.get('daily_df_parquet')
            or local_inputs.get('daily_df_csv')
            or str(manifest_path(manifest, 'runs', 'step3a_daily_input_csv') or '')
        )
        input_mode = str(local_inputs.get('input_mode') or '')
        minute_required = input_mode != 'daily_only'
        if (minute_required and (not minute_path or not daily_path)) or ((not minute_required) and not daily_path):
            issues.append({'severity': 'error', 'code': 'LOCAL_EXECUTION_INPUTS_MISSING', 'message': 'no local normalized input snapshots provided for actual execution', 'evidence': {'local_input_paths': local_inputs}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'LOCAL_EXECUTION_INPUTS_MISSING', 'execution_precheck', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        import pandas as pd  # local import to keep hard dependency only for real execution path
        minute_file = Path(minute_path) if minute_path else None
        daily_file = Path(daily_path)
        if minute_file is not None and not minute_file.is_absolute():
            minute_file = WORKSPACE / minute_file
        if not daily_file.is_absolute():
            daily_file = WORKSPACE / daily_file
        if (minute_required and minute_file is not None and not minute_file.exists()) or not daily_file.exists():
            issues.append({'severity': 'error', 'code': 'LOCAL_INPUT_FILES_NOT_FOUND', 'message': 'declared local input files do not exist', 'evidence': {'minute': str(minute_file) if minute_file else None, 'daily': str(daily_file)}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'LOCAL_INPUT_FILES_NOT_FOUND', 'execution_precheck', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        def read_df(p: Path):
            if p.suffix.lower() == '.parquet':
                return pd.read_parquet(p)
            return pd.read_csv(p)

        minute_df = read_df(minute_file) if minute_file is not None else pd.DataFrame()
        daily_df = read_df(daily_file)
        result_df = module.compute_factor(minute_df, daily_df)

        if result_df is None or len(result_df) == 0:
            issues.append({'severity': 'error', 'code': 'EMPTY_MAIN_RESULT', 'message': 'main result not materially generated', 'evidence': {'rows': 0}})
            run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, str(impl_path), dpm.get('sample_window', {}), run_dir, input_paths, issues, warnings, 'EMPTY_MAIN_RESULT', 'execution', start_utc)
            write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
            write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
            write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
            return

        ensure_dir(run_dir)
        parquet_path = run_dir / f'factor_values__{report_id}.parquet'
        csv_path = run_dir / f'factor_values__{report_id}.csv'
        meta_path = run_dir / f'run_metadata__{report_id}.json'

        signal_col = infer_signal_column(result_df, factor_id=factor_id)
        result_df.to_parquet(parquet_path, index=False)
        result_df.to_csv(csv_path, index=False)

        row_count = int(len(result_df))
        date_count = int(result_df['trade_date'].nunique()) if 'trade_date' in result_df.columns else 0
        ticker_count = int(result_df['ts_code'].nunique()) if 'ts_code' in result_df.columns else 0
        actual_start = str(result_df['trade_date'].min()) if 'trade_date' in result_df.columns and row_count else None
        actual_end = str(result_df['trade_date'].max()) if 'trade_date' in result_df.columns and row_count else None
        target_window = dpm.get('sample_window', {}) or {}
        prepared_window = (dpm.get('local_input_paths') or {}).get('sample_window_actual') or {}
        target_start_raw = target_window.get('start')
        target_start = str(target_start_raw) if target_start_raw is not None else None
        target_end_raw = target_window.get('end')
        input_daily_start = str(daily_df['trade_date'].min()) if 'trade_date' in daily_df.columns and len(daily_df) else None
        input_daily_end = str(daily_df['trade_date'].max()) if 'trade_date' in daily_df.columns and len(daily_df) else None
        prepared_start = str(prepared_window.get('start')) if prepared_window.get('start') is not None else None
        prepared_end = str(prepared_window.get('end')) if prepared_window.get('end') is not None else None
        effective_target_start = prepared_start or input_daily_start or target_start
        if str(target_end_raw) == 'current':
            effective_target_end = input_daily_end
        else:
            effective_target_end = prepared_end or (str(target_end_raw) if target_end_raw is not None else None)
        target_end = effective_target_end
        coverage_complete = (actual_start == effective_target_start and actual_end == effective_target_end)
        run_status = 'success' if coverage_complete else 'partial'
        failure_reason = None
        evaluation_plan = build_evaluation_plan(handoff)
        backend_runs = build_backend_runs_stub(report_id, evaluation_plan, run_status)
        backend_runs = write_backend_payloads(report_id, backend_runs, manifest_path_arg=manifest_path_arg)

        meta = {
            'report_id': report_id,
            'factor_id': factor_id,
            'implementation_path': str(impl_path),
            'started_at_utc': start_utc,
            'finished_at_utc': utc_now(),
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'signal_column': signal_col,
            'actual_window': {'start': actual_start, 'end': actual_end},
            'target_window': target_window,
            'effective_target_window': {'start': effective_target_start, 'end': effective_target_end},
            'run_status_candidate': run_status
        }
        write_json(meta_path, meta)

        run_master_path = OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json'
        diag_path = OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json'
        handoff_path = OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json'

        run_master = {
            'report_id': report_id,
            'factor_id': factor_id,
            'run_status': run_status,
            'implementation_path': str(impl_path),
            'output_paths': [str(parquet_path), str(csv_path), str(meta_path)],
            'sample_window': target_window,
            'runtime_notes': warnings,
            'diagnostic_summary': {'row_count': row_count, 'date_count': date_count, 'ticker_count': ticker_count},
            'signal_column': signal_col,
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'failure_reason': failure_reason,
            'started_at_utc': start_utc,
            'finished_at_utc': utc_now(),
            'input_paths': {k: str(v) for k, v in input_paths.items()},
            'window_coverage': {
                'target_start': target_window.get('start'),
                'target_end': target_window.get('end'),
                'effective_target_start': effective_target_start,
                'effective_target_end': effective_target_end,
                'input_daily_start': input_daily_start,
                'input_daily_end': input_daily_end,
                'actual_start': actual_start,
                'actual_end': actual_end,
                'coverage_complete': coverage_complete,
            },
            'validation_pointer': str(diag_path),
            'handoff_to_step5_path': str(handoff_path),
        }

        null_ratio = {}
        for col in [signal_col]:
            if col in result_df.columns and row_count:
                null_ratio[col] = float(result_df[col].isna().mean())
        duplicate_ratio = {}
        if {'ts_code', 'trade_date'}.issubset(result_df.columns):
            duplicate_ratio['ts_code_trade_date'] = float(result_df.duplicated(['ts_code', 'trade_date']).mean())
        sort_order_ok = True
        if {'ts_code', 'trade_date'}.issubset(result_df.columns):
            sort_order_ok = result_df[['ts_code', 'trade_date']].reset_index(drop=True).equals(
                result_df.sort_values(['ts_code', 'trade_date'])[['ts_code', 'trade_date']].reset_index(drop=True)
            )

        diagnostics = {
            'report_id': report_id,
            'factor_id': factor_id,
            'run_status': run_status,
            'diagnostic_generated_at_utc': utc_now(),
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'input_validation': {
                'exists_check': {k: v.exists() for k, v in input_paths.items()},
                'schema_check': {'frozen_schema_execution': True},
                'consistency_check': {
                    'report_id_consistent': True,
                    'factor_id_consistent': True
                },
                'placeholder_check': {
                    'factor_spec_master_has_placeholder': contains_placeholder(fsm),
                    'data_prep_master_has_placeholder': contains_placeholder(dpm),
                    'handoff_to_step4_has_placeholder': contains_placeholder(handoff)
                }
            },
            'execution_trace': {
                'implementation_path': str(impl_path),
                'commands': [f'python3 skills/factor-forge-step4/scripts/run_step4.py --report-id {report_id}'],
                'runtime_seconds': None,
                'exception_type': None,
                'exception_message': None
            },
            'output_validation': {
                'output_exists': True,
                'output_paths': [str(parquet_path), str(csv_path), str(meta_path)],
                'file_sizes': {
                    str(parquet_path): parquet_path.stat().st_size,
                    str(csv_path): csv_path.stat().st_size,
                    str(meta_path): meta_path.stat().st_size,
                },
                'row_count': row_count,
                'date_count': date_count,
                'ticker_count': ticker_count,
                'signal_column': signal_col,
            },
            'quality_checks': {
                'window_complete': coverage_complete,
                'null_ratio': null_ratio,
                'duplicate_ratio': duplicate_ratio,
                'key_uniqueness': {'ts_code_trade_date_unique': duplicate_ratio.get('ts_code_trade_date', 0.0) == 0.0},
                'sort_order_ok': sort_order_ok
            },
            'issues': issues,
            'failure_context': {
                'failed_stage': None,
                'failure_reason': None,
                'retryable': False
            },
            'recommendation': {
                'can_handoff_to_step5': True,
                'recommended_status': run_status,
                'next_action': 'Proceed to Step 5 using declared evaluation scope.'
            }
        }

        # COMMENT_POLICY: execution_handoff
        # Step 4 emits a stable handoff envelope for Step 5 to avoid implicit coupling.
        handoff_out = {
            'report_id': report_id,
            'factor_id': factor_id,
            'run_status': run_status,
            'factor_run_master_path': str(run_master_path),
            'diagnostics_path': str(diag_path),
            'output_paths': [str(parquet_path), str(csv_path), str(meta_path)],
            'sample_window_target': target_window,
            'sample_window_actual': {'start': actual_start, 'end': actual_end},
            'coverage_ratio': 1.0 if coverage_complete else None,
            'row_count': row_count,
            'date_count': date_count,
            'ticker_count': ticker_count,
            'signal_column': signal_col,
            'evaluation_plan': evaluation_plan,
            'evaluation_results': {'backend_runs': backend_runs},
            'key_warnings': warnings,
            'failure_reason': None,
            'can_enter_step5': True,
            'recommended_step5_scope': 'full' if run_status == 'success' else 'partial_scope_only',
            'notes_for_step5': ['partial result: evaluate only covered window/instruments'] if run_status == 'partial' else ['full result ready for evaluation']
        }

        write_json(run_master_path, run_master)
        write_json(diag_path, diagnostics)
        write_json(handoff_path, handoff_out)
    except Exception as e:
        issues.append({'severity': 'error', 'code': 'UNHANDLED_EXCEPTION', 'message': str(e), 'evidence': {'traceback': traceback.format_exc()[-4000:]}})
        run_master, diagnostics, handoff_out = build_failure_outputs(report_id, factor_id, implementation_path, dpm.get('sample_window', {}) if dpm else {}, run_dir, input_paths, issues, warnings, type(e).__name__, 'unhandled_exception', start_utc)
        diagnostics['execution_trace']['exception_type'] = type(e).__name__
        diagnostics['execution_trace']['exception_message'] = str(e)
        diagnostics['issues'] = issues
        write_json(OBJ / 'factor_run_master' / f'factor_run_master__{report_id}.json', run_master)
        write_json(OBJ / 'validation' / f'factor_run_diagnostics__{report_id}.json', diagnostics)
        write_json(OBJ / 'handoff' / f'handoff_to_step5__{report_id}.json', handoff_out)
        raise


if __name__ == '__main__':
    main()
