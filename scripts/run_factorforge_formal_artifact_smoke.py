#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECT_CODE_SOURCE = """import numpy as np
import pandas as pd


def compute_factor(daily_df: pd.DataFrame | None = None, minute_df: pd.DataFrame | None = None) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        raise ValueError("daily_df is required")
    df = daily_df.copy()
    required = {"ts_code", "trade_date", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"daily_df missing required columns: {missing}")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["factor_value"] = df.groupby("ts_code", sort=False)["close"].pct_change()
    out = df[["ts_code", "trade_date", "factor_value"]].replace([np.inf, -np.inf], np.nan)
    return out.dropna(subset=["factor_value"]).sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
"""


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def run_cmd(cmd: list[str], *, root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)


def stable_source_hash(source: str) -> str:
    import hashlib

    return hashlib.sha256(source.encode('utf-8')).hexdigest()


def build_root(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def write_step2_raw_files(root: Path, report_id: str, *, include_source: bool) -> dict[str, Path]:
    raw_dir = root / 'objects' / 'raw_llm' / report_id / 'step2'
    raw_dir.mkdir(parents=True, exist_ok=True)
    required_inputs = ['ts_code', 'trade_date', 'close']
    code_contract = {
        'code_contract_version': 'factorforge_direct_code_contract_v1',
        'function_name': 'compute_factor',
        'entrypoint': 'compute_factor',
        'imports': ['numpy', 'pandas'],
        'dependencies': ['numpy', 'pandas'],
        'input_schema': {'daily_df': required_inputs},
        'output_schema': {'columns': ['ts_code', 'trade_date', 'factor_value']},
        'required_fields': required_inputs,
        'information_set_rules': ['no future-looking fields or negative shifts'],
        'forbidden_patterns': [r'shift\s*\(\s*-\d+', 'future_return', 'next_return', 'label', 'target', 'future_', 'lookahead'],
    }
    if include_source:
        code_contract['source_code'] = SAMPLE_DIRECT_CODE_SOURCE
        code_contract['code_hash'] = stable_source_hash(SAMPLE_DIRECT_CODE_SOURCE)
    primary = {
        'report_id': report_id,
        'factor_id': 'FORMAL_DIRECT_CODE_SOURCE',
        'route': 'primary',
        'implementation_mode': 'direct_code',
        'raw_formula_text': 'direct_code smart money VWAP implementation supplied by formal Step2 raw',
        'operators': ['custom_direct_code'],
        'required_inputs': required_inputs,
        'implementation_contract': {
            'implementation_mode': 'direct_code',
            'mode': 'direct_code',
            'required_fields': required_inputs,
            'code_contract': code_contract,
            'output_schema': {'columns': ['ts_code', 'trade_date', 'factor_value']},
        },
        'time_series_steps': ['compute direct-code signal from current and prior close only'],
        'cross_sectional_steps': ['none'],
        'preprocessing': ['numeric close conversion'],
        'normalization': [],
        'neutralization': [],
        'ambiguities': [],
    }
    challenger = {**primary, 'route': 'challenger'}
    auditor = {
        'report_id': report_id,
        'factor_id': primary['factor_id'],
        'consistency_score': 0.92,
        'matches_core_driver': True,
        'mismatch_points': [],
        'missing_steps': [],
        'distortion_risks': [],
        'recommendation': 'proceed',
    }
    paths = {
        'primary': raw_dir / 'step2_primary_raw.json',
        'challenger': raw_dir / 'step2_challenger_raw.json',
        'auditor': raw_dir / 'step2_auditor_raw.json',
    }
    paths['primary'].write_text(json.dumps(primary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    paths['challenger'].write_text(json.dumps(challenger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    paths['auditor'].write_text(json.dumps(auditor, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return paths


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
    step2_raw = write_step2_raw_files(root, report_id, include_source=True)
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
        '--step2-primary-raw',
        str(step2_raw['primary']),
        '--step2-challenger-raw',
        str(step2_raw['challenger']),
        '--step2-auditor-raw',
        str(step2_raw['auditor']),
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
    step2_raw = write_step2_raw_files(root, report_id, include_source=False)
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
        '--step2-primary-raw',
        str(step2_raw['primary']),
        '--step2-challenger-raw',
        str(step2_raw['challenger']),
        '--step2-auditor-raw',
        str(step2_raw['auditor']),
        '--allow-deterministic-debug',
        '--end-step',
        '3a',
        '--write-report',
    ], root=root)
    payload = read_json(output) if output.exists() else {}
    step3_validate = (payload.get('validators') or {}).get('step3') or {}
    text = proc.stdout + proc.stderr + str(step3_validate.get('stdout_tail') or '') + str(step3_validate.get('stderr_tail') or '')
    token_present = 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING' in text
    runtime_context = root / 'objects' / 'runtime_context' / f'runtime_context__{report_id}.json'
    return {
        'case': 'direct_code_missing_source_contract_blocks_step3a_producer_path',
        'prepare_rc': proc.returncode,
        'prepare_report': str(output),
        'prepare_verdict': payload.get('verdict'),
        'validate_rc': step3_validate.get('rc'),
        'token_present': token_present,
        'runtime_context_exists': runtime_context.exists(),
        'stdout_tail': proc.stdout[-2000:],
        'stderr_tail': proc.stderr[-2000:],
        'ok': bool(proc.returncode != 0 and payload.get('verdict') == 'BLOCK' and step3_validate.get('rc') == 1 and token_present and not runtime_context.exists()),
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
