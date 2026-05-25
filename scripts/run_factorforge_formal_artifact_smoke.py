#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def run_cmd(cmd: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)


def build_root(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def write_bad_existing_artifacts(root: Path, report_id: str) -> None:
    (root / 'objects' / 'alpha_idea_master').mkdir(parents=True, exist_ok=True)
    (root / 'objects' / 'factor_spec_master').mkdir(parents=True, exist_ok=True)
    (root / 'objects' / 'handoff').mkdir(parents=True, exist_ok=True)
    (root / 'objects' / 'data_prep_master').mkdir(parents=True, exist_ok=True)
    (root / 'objects' / 'implementation_plan_master').mkdir(parents=True, exist_ok=True)
    (root / 'objects' / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json').write_text(
        json.dumps({'report_id': report_id, 'final_factor': {'name': report_id}}, ensure_ascii=False),
        encoding='utf-8',
    )
    (root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{report_id}.json').write_text(
        json.dumps({'report_id': 'WRONG_REPORT_ID', 'factor_id': report_id, 'canonical_spec': {}}, ensure_ascii=False),
        encoding='utf-8',
    )
    (root / 'objects' / 'handoff' / f'handoff_to_step3__{report_id}.json').write_text(
        json.dumps({'report_id': report_id}, ensure_ascii=False),
        encoding='utf-8',
    )


def run_prepare_formal_debug_chain_case(root: Path) -> dict:
    report_id = 'FORMAL_SMOKE_REPORT'
    output = root / 'objects' / 'validation' / f'formal_artifact_prepare_report__{report_id}.json'
    proc = run_cmd([
        sys.executable,
        'scripts/prepare_factorforge_formal_artifacts.py',
        '--factorforge-root',
        str(root),
        '--report-id',
        report_id,
        '--report-pdf',
        'fixtures/step2/sample_report_stub.pdf',
        '--step1-primary-raw',
        'fixtures/step1/sample_intake_response.json',
        '--step1-challenger-raw',
        'fixtures/step1/sample_intake_response.json',
        '--allow-deterministic-debug',
        '--end-step',
        '3a',
        '--write-report',
    ], root=root)
    payload = read_json(output) if output.exists() else {}
    paths = payload.get('artifact_paths') or {}
    alpha = read_json(Path(paths.get('alpha_idea_master'))) if paths.get('alpha_idea_master') else {}
    spec = read_json(Path(paths.get('factor_spec_master'))) if paths.get('factor_spec_master') else {}
    handoff = read_json(Path(paths.get('handoff_to_step3'))) if paths.get('handoff_to_step3') else {}
    prep = read_json(Path(paths.get('data_prep_master'))) if paths.get('data_prep_master') else {}
    impl_path = root / 'objects' / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    impl = read_json(impl_path) if impl_path.exists() else {}
    code_contract = impl.get('code_contract') if isinstance(impl.get('code_contract'), dict) else {}
    runtime_context = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'
    ok = bool(
        proc.returncode == 0
        and payload.get('verdict') == 'ACCEPT'
        and payload.get('formal_artifacts_valid') is True
        and payload.get('workflow_may_dispatch_worker') is True
        and payload.get('worker_started') is False
        and payload.get('worker_dispatch_status') == 'not_dispatched_by_prepare'
        and payload.get('canonical_report_id_preserved') is True
        and alpha.get('report_id') == report_id
        and spec.get('report_id') == report_id
        and handoff.get('report_id') == report_id
        and prep.get('report_id') == report_id
        and impl.get('implementation_mode') == 'direct_code'
        and isinstance(code_contract.get('source_code'), str)
        and 'def compute_factor' in code_contract.get('source_code', '')
        and code_contract.get('code_hash')
        and spec.get('artifact_identity')
        and handoff.get('artifact_identity', {}).get('spec_hash') == spec.get('artifact_identity', {}).get('spec_hash')
        and payload.get('validators', {}).get('step1', {}).get('rc') == 0
        and payload.get('validators', {}).get('step2', {}).get('rc') == 0
        and payload.get('validators', {}).get('step3', {}).get('rc') == 0
        and not runtime_context.exists()
    )
    return {
        'case': 'prepare_formal_artifacts_debug_chain',
        'rc': proc.returncode,
        'stdout_tail': proc.stdout[-2000:],
        'stderr_tail': proc.stderr[-2000:],
        'output': str(output),
        'payload_verdict': payload.get('verdict'),
        'canonical_report_id_preserved': payload.get('canonical_report_id_preserved'),
        'formal_artifacts_valid': payload.get('formal_artifacts_valid'),
        'workflow_may_dispatch_worker': payload.get('workflow_may_dispatch_worker'),
        'worker_started': payload.get('worker_started'),
        'worker_dispatch_status': payload.get('worker_dispatch_status'),
        'runtime_context_exists': runtime_context.exists(),
        'direct_code_source_contract_present': bool(code_contract.get('source_code') and code_contract.get('code_hash')),
        'ok': ok,
    }


def run_direct_code_missing_source_blocks_case(root: Path) -> dict:
    report_id = 'FORMAL_DIRECT_CODE_MISSING_SOURCE'
    output = root / 'objects' / 'validation' / f'formal_artifact_prepare_report__{report_id}.json'
    proc = run_cmd([
        sys.executable,
        'scripts/prepare_factorforge_formal_artifacts.py',
        '--factorforge-root',
        str(root),
        '--report-id',
        report_id,
        '--report-pdf',
        'fixtures/step2/sample_report_stub.pdf',
        '--step1-primary-raw',
        'fixtures/step1/sample_intake_response.json',
        '--step1-challenger-raw',
        'fixtures/step1/sample_intake_response.json',
        '--allow-deterministic-debug',
        '--end-step',
        '3a',
        '--write-report',
    ], root=root)
    impl_path = root / 'objects' / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    if impl_path.exists():
        impl = read_json(impl_path)
        if isinstance(impl.get('code_contract'), dict):
            impl['code_contract'].pop('source_code', None)
            impl['code_contract'].pop('code_hash', None)
        if isinstance(impl.get('implementation_contract'), dict) and isinstance(impl['implementation_contract'].get('code_contract'), dict):
            impl['implementation_contract']['code_contract'].pop('source_code', None)
            impl['implementation_contract']['code_contract'].pop('code_hash', None)
        impl.pop('source_code', None)
        impl.pop('code_hash', None)
        impl_path.write_text(json.dumps(impl, ensure_ascii=False, indent=2), encoding='utf-8')
    validate = run_cmd([
        sys.executable,
        'skills/factor-forge-step3/scripts/validate_step3.py',
        '--report-id',
        report_id,
    ], root=root)
    text = validate.stdout + validate.stderr
    token_present = 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING' in text
    runtime_context = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'
    return {
        'case': 'direct_code_missing_source_contract_blocks_step3_validation',
        'prepare_rc': proc.returncode,
        'prepare_report': str(output),
        'validate_rc': validate.returncode,
        'token_present': token_present,
        'runtime_context_exists': runtime_context.exists(),
        'stdout_tail': validate.stdout[-2000:],
        'stderr_tail': validate.stderr[-2000:],
        'ok': bool(proc.returncode == 0 and validate.returncode != 0 and token_present and not runtime_context.exists()),
    }


def run_no_raw_blocks_case(root: Path) -> dict:
    report_id = 'FORMAL_NO_RAW'
    proc = run_cmd([
        sys.executable,
        'scripts/prepare_factorforge_formal_artifacts.py',
        '--factorforge-root',
        str(root),
        '--report-id',
        report_id,
        '--report-pdf',
        'fixtures/step2/sample_report_stub.pdf',
        '--end-step',
        '3a',
        '--write-report',
    ], root=root)
    token_present = 'BLOCK_FORMAL_STEP1_LLM_OUTPUT_REQUIRED' in proc.stdout + proc.stderr
    runtime_context = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'
    return {
        'case': 'no_raw_formal_artifacts_block',
        'rc': proc.returncode,
        'token_present': token_present,
        'runtime_context_exists': runtime_context.exists(),
        'ok': bool(proc.returncode != 0 and token_present and not runtime_context.exists()),
    }


def run_bad_artifact_schema_blocks_case(root: Path) -> dict:
    report_id = 'FORMAL_BAD_ARTIFACT'
    write_bad_existing_artifacts(root, report_id)
    proc = run_cmd([
        sys.executable,
        'scripts/prepare_factorforge_formal_artifacts.py',
        '--factorforge-root',
        str(root),
        '--report-id',
        report_id,
        '--report-pdf',
        'fixtures/step2/sample_report_stub.pdf',
        '--end-step',
        '3a',
        '--validate-existing-only',
        '--write-report',
    ], root=root)
    token_present = 'BLOCK_FORMAL_ARTIFACT_SCHEMA_INVALID' in proc.stdout + proc.stderr
    runtime_context = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'
    return {
        'case': 'bad_formal_artifact_schema_blocks',
        'rc': proc.returncode,
        'token_present': token_present,
        'runtime_context_exists': runtime_context.exists(),
        'ok': bool(proc.returncode == 1 and token_present and not runtime_context.exists()),
    }


def main() -> int:
    root = build_root(Path('/tmp/factorforge_formal_artifact_smoke'))
    cases = [
        run_no_raw_blocks_case(build_root(Path('/tmp/factorforge_formal_artifact_no_raw_smoke'))),
        run_prepare_formal_debug_chain_case(root),
        run_direct_code_missing_source_blocks_case(build_root(Path('/tmp/factorforge_formal_artifact_direct_code_source_smoke'))),
        run_bad_artifact_schema_blocks_case(build_root(Path('/tmp/factorforge_formal_artifact_bad_smoke'))),
    ]
    verdict = 'ACCEPT' if all(case.get('ok') for case in cases) else 'BLOCK'
    summary = {'version': 'factorforge_formal_artifact_smoke_v1', 'verdict': verdict, 'cases': cases}
    out = Path('/tmp/factorforge_formal_artifact_smoke_summary.json')
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'[SUMMARY] {out}')
    return 0 if verdict == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
