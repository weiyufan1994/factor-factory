#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERSION = 'factorforge_formal_artifact_prepare_v1'
BLOCK_SCHEMA = 'BLOCK_FORMAL_ARTIFACT_SCHEMA_INVALID'
BLOCK_STEP1_RAW = 'BLOCK_FORMAL_STEP1_LLM_OUTPUT_REQUIRED'
BLOCK_STEP2_RAW = 'BLOCK_FORMAL_STEP2_LLM_OUTPUT_REQUIRED'
BLOCK_REPORT_ID = 'BLOCK_NON_CANONICAL_REPORT_ID'
RUNTIME_CONTEXT_DIR = ('objects', 'runtime_context')

from skills.factor_forge_step1.modules.report_ingestion.builders.report_map_builder import ReportMapBuilder
from skills.factor_forge_step1.modules.report_ingestion.challenger.challenger_to_thesis import challenger_intake_to_thesis
from skills.factor_forge_step1.modules.report_ingestion.finalizers.alpha_idea_master_writer import AlphaIdeaMasterWriter
from skills.factor_forge_step1.modules.report_ingestion.finalizers.handoff_to_step2 import HandoffToStep2
from skills.factor_forge_step1.modules.report_ingestion.intake.pdf_skill_client import PdfSkillClient
from skills.factor_forge_step1.modules.report_ingestion.merge.merge_to_alpha_idea_master import merge_to_alpha_idea_master
from skills.factor_forge_step1.modules.report_ingestion.normalizers.intake_to_alpha_thesis import intake_to_alpha_thesis
from skills.factor_forge_step1.modules.report_ingestion.orchestration.step1_pipeline import Step1Pipeline
from skills.factor_forge_step1.modules.report_ingestion.registry.report_registry import ReportRegistry
from skills.factor_forge_step1.modules.report_ingestion.registry.report_source_contract import normalize_report_source
from skills.factor_forge_step1.modules.report_ingestion.validators.schema_validator import SchemaValidator
from skills.factor_forge_step1.modules.report_ingestion.writers.object_writer import ObjectWriter


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return sha256_bytes(encoded)


def path_arg(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


def canonical_report_id_valid(report_id: str) -> bool:
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,127}', report_id or ''))


def resolve_factorforge_root(raw: str | None) -> Path:
    if raw:
        return Path(raw).expanduser().resolve()
    return Path(os.getenv('FACTORFORGE_ROOT') or REPO_ROOT).expanduser().resolve()


def resolve_report_pdf(raw: str, root: Path) -> tuple[Path, dict[str, Any]]:
    candidate = path_arg(raw)
    if candidate and candidate.suffix.lower() == '.json' and candidate.exists():
        manifest = read_json(candidate)
        for key in ['local_pdf_path', 'report_pdf', 'pdf_path', 'local_cache_path']:
            value = manifest.get(key)
            if isinstance(value, str) and value:
                p = Path(value).expanduser()
                if not p.is_absolute():
                    p = (candidate.parent / p).resolve()
                if p.exists():
                    return p, {'input_type': 's3_manifest', 'manifest_path': str(candidate), 'manifest_sha256': sha256_file(candidate)}
        s3_uri = manifest.get('s3_uri') or manifest.get('s3_url')
        raise SystemExit(f'BLOCK_REPORT_PDF_NOT_LOCAL: manifest has no local PDF path; s3_uri={s3_uri}')

    if not candidate:
        raise SystemExit('BLOCK_REPORT_PDF_MISSING')
    if not candidate.exists():
        relative_to_root = root / raw
        if relative_to_root.exists():
            candidate = relative_to_root.resolve()
        else:
            raise SystemExit(f'BLOCK_REPORT_PDF_MISSING: {candidate}')
    return candidate.resolve(), {'input_type': 'local_pdf'}


def build_default_chief_decision(primary_intake: Any, challenger_intake: Any) -> dict[str, Any]:
    def dedupe(values: list[Any]) -> list[Any]:
        out: list[Any] = []
        for value in values:
            if value and value not in out:
                out.append(value)
        return out

    pff = primary_intake.final_factor or {}
    cff = challenger_intake.final_factor or {}
    final = pff or cff
    subfactor_names = [
        sf.get('name')
        for sf in (primary_intake.subfactors or [])
        if isinstance(sf, dict) and sf.get('name')
    ]
    assembly_steps = final.get('assembly_steps') or pff.get('assembly_steps') or cff.get('assembly_steps') or []
    return {
        'final_factor': {
            'name': final.get('name') or pff.get('name') or cff.get('name') or 'UNNAMED_FACTOR',
            'assembly_steps': assembly_steps,
            'accepted_subfactor_names': dedupe(subfactor_names),
            'direction': final.get('direction', ''),
            'alpha_strength': final.get('alpha_strength', ''),
            'alpha_source': final.get('alpha_source', ''),
            'key_implementation_risks': final.get('key_implementation_risks', []),
            'economic_logic': final.get('economic_logic', ''),
            'economic_logic_provenance': final.get('economic_logic_provenance') or final.get('economic_logic_source', ''),
            'behavioral_logic': final.get('behavioral_logic', ''),
            'behavioral_logic_provenance': final.get('behavioral_logic_provenance') or final.get('behavioral_logic_source', ''),
            'causal_chain': final.get('causal_chain', ''),
            'causal_chain_provenance': final.get('causal_chain_provenance') or final.get('causal_chain_source', ''),
            'rejected_subfactor_details': [],
        },
        'logic_provenance_summary': {
            'merge_mode': 'deterministic_debug_fallback',
            'note': 'chief decision auto-built from provided primary/challenger intake payloads',
        },
        'assembly_path': assembly_steps,
        'unresolved_ambiguities': dedupe((primary_intake.ambiguities or []) + (challenger_intake.ambiguities or [])),
        'chief_decision_summary': 'Auto chief merge from primary/challenger intake payloads.',
        'chief_confidence': 'medium',
        'chief_rationale': 'Primary route preferred; challenger route used for ambiguity coverage and sanity check.',
    }


def build_step1_pipeline(root: Path) -> Step1Pipeline:
    schema_root = REPO_ROOT / 'skills' / 'factor_forge_step1' / 'schemas'
    return Step1Pipeline(
        registry=ReportRegistry(root / 'data' / 'report_ingestion' / 'report_registry.json'),
        pdf_skill_client=PdfSkillClient(),
        report_map_builder=ReportMapBuilder(schema_validator=SchemaValidator(schema_root)),
        object_writer=ObjectWriter(root / 'objects'),
    )


def run_step1(args: argparse.Namespace, root: Path, report_pdf: Path, pdf_meta: dict[str, Any]) -> dict[str, Any]:
    primary_raw_path = path_arg(args.step1_primary_raw)
    challenger_raw_path = path_arg(args.step1_challenger_raw)
    chief_raw_path = path_arg(args.step1_chief_raw)
    if not primary_raw_path or not challenger_raw_path:
        raise SystemExit(f'{BLOCK_STEP1_RAW}: primary/challenger Step1 raw JSON outputs are required outside an explicit PDF LLM bridge')
    if not primary_raw_path.exists() or not challenger_raw_path.exists():
        raise SystemExit(f'{BLOCK_STEP1_RAW}: raw path missing')
    if not chief_raw_path and not args.allow_deterministic_debug:
        raise SystemExit(f'{BLOCK_STEP1_RAW}: chief merge raw output is required unless --allow-deterministic-debug is set')

    primary_raw = read_text(primary_raw_path)
    challenger_raw = read_text(challenger_raw_path)
    source = normalize_report_source(source_type='pdf', source_uri=str(report_pdf), title=report_pdf.stem)
    source.report_id = args.report_id
    source.local_cache_path = str(report_pdf)
    source.status = 'cached'

    pipeline = build_step1_pipeline(root)
    step1_result = pipeline.run_pdf_skill(source=source, response_text=primary_raw, challenger_response_text=challenger_raw)

    parser = PdfSkillClient()
    primary_intake = parser.parse_response(args.report_id, primary_raw)
    challenger_intake = parser.parse_response(args.report_id, challenger_raw)
    primary_thesis = intake_to_alpha_thesis(primary_intake)
    challenger_thesis = challenger_intake_to_thesis(challenger_intake)
    if chief_raw_path:
        chief_decision = read_json(chief_raw_path)
        step1_mode = 'formal_llm_raw'
    else:
        chief_decision = build_default_chief_decision(primary_intake, challenger_intake)
        step1_mode = 'deterministic_debug_fallback'

    alpha_idea_master = merge_to_alpha_idea_master(
        primary_intake=primary_intake,
        challenger_intake=challenger_intake,
        primary_thesis=primary_thesis,
        challenger_thesis=challenger_thesis,
        chief_decision=chief_decision,
    )
    alpha_idea_master.update({
        'report_id': args.report_id,
        'source_type': 'pdf_report',
        'implementation_mode': 'direct_code' if args.allow_deterministic_debug and not args.step2_primary_raw else alpha_idea_master.get('implementation_mode'),
        'source_uri': str(report_pdf),
        'local_cache_path': str(report_pdf),
        'producer': 'step2_pdf_report',
        'step1_producer': 'step1_pdf_dual_llm',
        'formal_artifact_generation': {
            'version': VERSION,
            'artifact_role': 'alpha_idea_master',
            'step1_extraction_mode': step1_mode,
            'formal_llm_extraction': step1_mode == 'formal_llm_raw',
            'debug_fallback': step1_mode != 'formal_llm_raw',
            'pdf_sha256': sha256_file(report_pdf),
            'pdf_metadata': pdf_meta,
            'primary_raw_sha256': sha256_file(primary_raw_path),
            'challenger_raw_sha256': sha256_file(challenger_raw_path),
            'chief_raw_sha256': sha256_file(chief_raw_path) if chief_raw_path else stable_hash(chief_decision),
            'prompt_hashes': {
                'step1_report_intake': stable_hash(PdfSkillClient().build_request(report_pdf).get('prompt')),
            },
            'model_provenance': {
                'primary_model': 'provided_raw_output',
                'challenger_model': 'provided_raw_output',
                'chief_model': 'provided_raw_output' if chief_raw_path else 'deterministic_debug_fallback',
            },
        },
    })

    alpha_path = AlphaIdeaMasterWriter(root / 'objects' / 'alpha_idea_master').write(args.report_id, alpha_idea_master)
    handoff_path = HandoffToStep2(root / 'objects' / 'handoff').write_handoff(
        args.report_id,
        alpha_idea_master,
        metadata={
            'producer': 'prepare_factorforge_formal_artifacts.py',
            'step1_extraction_mode': step1_mode,
            'primary_raw_path': str(primary_raw_path),
            'challenger_raw_path': str(challenger_raw_path),
            'chief_raw_path': str(chief_raw_path) if chief_raw_path else None,
        },
    )
    validation_dir = root / 'objects' / 'validation'
    raw_paths = {
        'step1_primary_raw': write_json(validation_dir / f'step1_llm_raw__primary__{args.report_id}.json', json.loads(primary_raw)),
        'step1_challenger_raw': write_json(validation_dir / f'step1_llm_raw__challenger__{args.report_id}.json', json.loads(challenger_raw)),
        'step1_chief_raw': write_json(validation_dir / f'step1_chief_merge_raw__{args.report_id}.json', chief_decision),
        'step1_provenance': write_json(validation_dir / f'formal_step1_provenance__{args.report_id}.json', alpha_idea_master['formal_artifact_generation']),
    }
    return {
        'step1_result': step1_result,
        'alpha_idea_master': str(alpha_path),
        'handoff_to_step2': str(handoff_path),
        **{k: str(v) for k, v in raw_paths.items()},
    }


def run_subprocess(cmd: list[str], root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    env['FACTORFORGE_ULTIMATE_RUN'] = '1'
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, text=True, capture_output=True)
    return {
        'cmd': cmd,
        'rc': proc.returncode,
        'stdout_tail': proc.stdout[-4000:],
        'stderr_tail': proc.stderr[-4000:],
    }


def load_step2_module(root: Path) -> Any:
    os.environ['FACTORFORGE_ROOT'] = str(root)
    path = REPO_ROOT / 'skills' / 'factor-forge-step2' / 'scripts' / 'run_step2.py'
    spec = importlib.util.spec_from_file_location(f'factorforge_step2_runner_{stable_hash(str(root))[:12]}', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load Step2 runner from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_step2(args: argparse.Namespace, root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    validation_dir = root / 'objects' / 'validation'
    primary_raw = path_arg(args.step2_primary_raw)
    challenger_raw = path_arg(args.step2_challenger_raw)
    auditor_raw = path_arg(args.step2_auditor_raw)
    if primary_raw or challenger_raw or auditor_raw:
        if not (primary_raw and challenger_raw and auditor_raw):
            raise SystemExit(f'{BLOCK_STEP2_RAW}: primary/challenger/auditor raw outputs must be provided together')
        module = load_step2_module(root)
        aim = module.load_alpha_idea_master(args.report_id)
        source_context = module.load_source_context(args.report_id, aim)
        primary = read_json(primary_raw)
        challenger = read_json(challenger_raw)
        consistency = read_json(auditor_raw)
        thesis = source_context['primary_thesis']
        master = module.build_factor_spec_master(args.report_id, aim, primary, consistency, thesis)
        paths = {
            'factor_spec_raw_primary': str(module.write_json(validation_dir / f'factor_spec_raw__primary__{args.report_id}.json', primary) or validation_dir / f'factor_spec_raw__primary__{args.report_id}.json'),
            'factor_spec_raw_challenger': str(module.write_json(validation_dir / f'factor_spec_raw__challenger__{args.report_id}.json', challenger) or validation_dir / f'factor_spec_raw__challenger__{args.report_id}.json'),
            'factor_consistency': str(module.write_json(validation_dir / f'factor_consistency__{args.report_id}.json', consistency) or validation_dir / f'factor_consistency__{args.report_id}.json'),
        }
        master.setdefault('formal_artifact_generation', {})['step2_extraction_mode'] = 'formal_llm_raw'
        master_path = root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{args.report_id}.json'
        module.write_json(master_path, master)
        module.write_handoff_to_step3(args.report_id, master_path)
        provenance = {
            'version': VERSION,
            'artifact_role': 'factor_spec_master',
            'step2_extraction_mode': 'formal_llm_raw',
            'formal_llm_extraction': True,
            'debug_fallback': False,
            'primary_raw_sha256': sha256_file(primary_raw),
            'challenger_raw_sha256': sha256_file(challenger_raw),
            'auditor_raw_sha256': sha256_file(auditor_raw),
        }
        write_json(validation_dir / f'formal_step2_provenance__{args.report_id}.json', provenance)
        return {**paths, 'factor_spec_master': str(master_path), 'handoff_to_step3': str(root / 'objects' / 'handoff' / f'handoff_to_step3__{args.report_id}.json')}, {'mode': 'formal_llm_raw'}

    if not args.allow_deterministic_debug:
        raise SystemExit(f'{BLOCK_STEP2_RAW}: Step2 formal extraction raw outputs are required unless --allow-deterministic-debug is set')

    result = run_subprocess([
        sys.executable,
        'skills/factor-forge-step2/scripts/run_step2.py',
        '--report-id',
        args.report_id,
    ], root)
    if result['rc'] != 0:
        return {}, {'mode': 'deterministic_debug_fallback', 'subprocess': result}

    provenance = {
        'version': VERSION,
        'artifact_role': 'factor_spec_master',
        'step2_extraction_mode': 'deterministic_debug_fallback',
        'formal_llm_extraction': False,
        'debug_fallback': True,
        'note': 'Existing deterministic Step2 builder used only because --allow-deterministic-debug was set.',
    }
    for rel in [
        ('objects', 'validation', f'factor_spec_raw__primary__{args.report_id}.json'),
        ('objects', 'validation', f'factor_spec_raw__challenger__{args.report_id}.json'),
        ('objects', 'validation', f'factor_consistency__{args.report_id}.json'),
        ('objects', 'factor_spec_master', f'factor_spec_master__{args.report_id}.json'),
        ('objects', 'handoff', f'handoff_to_step3__{args.report_id}.json'),
    ]:
        p = root.joinpath(*rel)
        if p.exists():
            payload = read_json(p)
            payload.setdefault('formal_artifact_generation', {}).update(provenance)
            write_json(p, payload)
    write_json(validation_dir / f'formal_step2_provenance__{args.report_id}.json', provenance)
    return {
        'factor_spec_raw_primary': str(root / 'objects' / 'validation' / f'factor_spec_raw__primary__{args.report_id}.json'),
        'factor_spec_raw_challenger': str(root / 'objects' / 'validation' / f'factor_spec_raw__challenger__{args.report_id}.json'),
        'factor_consistency': str(root / 'objects' / 'validation' / f'factor_consistency__{args.report_id}.json'),
        'factor_spec_master': str(root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{args.report_id}.json'),
        'handoff_to_step3': str(root / 'objects' / 'handoff' / f'handoff_to_step3__{args.report_id}.json'),
    }, {'mode': 'deterministic_debug_fallback', 'subprocess': result}


def run_step3a(args: argparse.Namespace, root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    result = run_subprocess([
        sys.executable,
        'skills/factor-forge-step3/scripts/run_step3.py',
        '--report-id',
        args.report_id,
        '--csv-output-policy',
        args.csv_output_policy,
    ], root)
    return {
        'data_prep_master': str(root / 'objects' / 'data_prep_master' / f'data_prep_master__{args.report_id}.json'),
        'qlib_adapter_config': str(root / 'objects' / 'data_prep_master' / f'qlib_adapter_config__{args.report_id}.json'),
        'implementation_plan_master': str(root / 'objects' / 'implementation_plan_master' / f'implementation_plan_master__{args.report_id}.json'),
        'handoff_to_step4': str(root / 'objects' / 'handoff' / f'handoff_to_step4__{args.report_id}.json'),
    }, {'subprocess': result}


def run_validator(script: str, report_id: str, root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    proc = subprocess.run(
        [sys.executable, script, '--report-id', report_id],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    return {
        'script': script,
        'rc': proc.returncode,
        'stdout_tail': proc.stdout[-5000:],
        'stderr_tail': proc.stderr[-5000:],
    }


def validate_chain(report_id: str, root: Path, end_step: str) -> dict[str, Any]:
    validators: dict[str, Any] = {}
    validators['step1'] = run_validator('skills/factor-forge-step1/scripts/validate_step1.py', report_id, root)
    if end_step in {'2', '3a'}:
        validators['step2'] = run_validator('skills/factor-forge-step2/scripts/validate_step2.py', report_id, root)
    if end_step == '3a':
        validators['step3'] = run_validator('skills/factor-forge-step3/scripts/validate_step3.py', report_id, root)
    return validators


def artifact_paths(root: Path, report_id: str, end_step: str) -> dict[str, str]:
    paths = {
        'alpha_idea_master': str(root / 'objects' / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json'),
        'handoff_to_step2': str(root / 'objects' / 'handoff' / f'handoff__{report_id}.json'),
        'step1_primary_raw': str(root / 'objects' / 'validation' / f'step1_llm_raw__primary__{report_id}.json'),
        'step1_challenger_raw': str(root / 'objects' / 'validation' / f'step1_llm_raw__challenger__{report_id}.json'),
        'step1_chief_raw': str(root / 'objects' / 'validation' / f'step1_chief_merge_raw__{report_id}.json'),
    }
    if end_step in {'2', '3a'}:
        paths.update({
            'factor_spec_raw_primary': str(root / 'objects' / 'validation' / f'factor_spec_raw__primary__{report_id}.json'),
            'factor_spec_raw_challenger': str(root / 'objects' / 'validation' / f'factor_spec_raw__challenger__{report_id}.json'),
            'factor_consistency': str(root / 'objects' / 'validation' / f'factor_consistency__{report_id}.json'),
            'factor_spec_master': str(root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{report_id}.json'),
            'handoff_to_step3': str(root / 'objects' / 'handoff' / f'handoff_to_step3__{report_id}.json'),
        })
    if end_step == '3a':
        paths.update({
            'data_prep_master': str(root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json'),
            'qlib_adapter_config': str(root / 'objects' / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'),
        })
    return paths


def load_optional(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {}
    return read_json(p)


def canonical_identity_check(root: Path, report_id: str, end_step: str) -> tuple[bool, list[str]]:
    paths = artifact_paths(root, report_id, end_step)
    errors: list[str] = []
    for name in ['alpha_idea_master', 'factor_spec_master', 'handoff_to_step3', 'data_prep_master']:
        if name not in paths:
            continue
        payload = load_optional(paths[name])
        if payload and payload.get('report_id') != report_id:
            errors.append(f'{name}.report_id mismatch: {payload.get("report_id")}')
    spec = load_optional(paths.get('factor_spec_master', ''))
    handoff = load_optional(paths.get('handoff_to_step3', ''))
    if spec and handoff:
        spec_identity = spec.get('artifact_identity') or {}
        handoff_identity = handoff.get('artifact_identity') or {}
        if not spec_identity:
            errors.append('factor_spec_master.artifact_identity missing')
        if not handoff_identity:
            errors.append('handoff_to_step3.artifact_identity missing')
        if spec_identity and handoff_identity:
            for key in ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'spec_hash', 'branch_id']:
                if spec_identity.get(key) != handoff_identity.get(key):
                    errors.append(f'handoff_to_step3.artifact_identity.{key} mismatch')
    return not errors, errors


def runtime_context_exists(root: Path, report_id: str) -> bool:
    return root.joinpath(*RUNTIME_CONTEXT_DIR, f'runtime_context__{report_id}.json').exists()


def write_report_if_requested(args: argparse.Namespace, root: Path, report: dict[str, Any]) -> None:
    if not args.write_report:
        return
    out = root / 'objects' / 'validation' / f'formal_artifact_prepare_report__{args.report_id}.json'
    write_json(out, report)


def build_report(args: argparse.Namespace, root: Path, verdict: str, validators: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    identity_ok, identity_errors = canonical_identity_check(root, args.report_id, args.end_step)
    validator_ok = all((v or {}).get('rc') == 0 for v in validators.values())
    paths = artifact_paths(root, args.report_id, args.end_step)
    report = {
        'version': VERSION,
        'report_id': args.report_id,
        'end_step': args.end_step,
        'verdict': verdict,
        'artifact_paths': paths,
        'validators': validators,
        'canonical_report_id_preserved': bool(identity_ok and validator_ok),
        'canonical_identity_errors': identity_errors,
        'runtime_context_written': runtime_context_exists(root, args.report_id),
        'worker_dispatch_allowed': bool(verdict == 'ACCEPT' and identity_ok and validator_ok and not runtime_context_exists(root, args.report_id)),
    }
    if extra:
        report.update(extra)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--factorforge-root')
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--report-pdf', required=True)
    ap.add_argument('--end-step', choices=['1', '2', '3a'], default='3a')
    ap.add_argument('--write-report', action='store_true')
    ap.add_argument('--validate-existing-only', action='store_true')
    ap.add_argument('--step1-primary-raw')
    ap.add_argument('--step1-challenger-raw')
    ap.add_argument('--step1-chief-raw')
    ap.add_argument('--step2-primary-raw')
    ap.add_argument('--step2-challenger-raw')
    ap.add_argument('--step2-auditor-raw')
    ap.add_argument('--allow-deterministic-debug', action='store_true')
    ap.add_argument('--csv-output-policy', default='sample_csv', choices=['full_csv', 'sample_csv', 'no_csv'])
    args = ap.parse_args()

    root = resolve_factorforge_root(args.factorforge_root)
    root.mkdir(parents=True, exist_ok=True)
    os.environ['FACTORFORGE_ROOT'] = str(root)

    if not canonical_report_id_valid(args.report_id):
        print(f'{BLOCK_REPORT_ID}: {args.report_id}', file=sys.stderr)
        return 1

    try:
        report_pdf, pdf_meta = resolve_report_pdf(args.report_pdf, root)
        extra: dict[str, Any] = {'report_pdf': str(report_pdf), 'report_pdf_sha256': sha256_file(report_pdf), 'report_pdf_metadata': pdf_meta}
        if not args.validate_existing_only:
            if args.end_step in {'1', '2', '3a'}:
                step1_paths = run_step1(args, root, report_pdf, pdf_meta)
                extra['step1_paths'] = step1_paths
            if args.end_step in {'2', '3a'}:
                step2_paths, step2_meta = run_step2(args, root)
                extra['step2_paths'] = step2_paths
                extra['step2_meta'] = step2_meta
            if args.end_step == '3a':
                step3_paths, step3_meta = run_step3a(args, root)
                extra['step3a_paths'] = step3_paths
                extra['step3a_meta'] = step3_meta

        validators = validate_chain(args.report_id, root, args.end_step)
        identity_ok, identity_errors = canonical_identity_check(root, args.report_id, args.end_step)
        validator_ok = all(v.get('rc') == 0 for v in validators.values())
        verdict = 'ACCEPT' if validator_ok and identity_ok and not runtime_context_exists(root, args.report_id) else 'BLOCK'
        report = build_report(args, root, verdict, validators, extra)
        write_report_if_requested(args, root, report)
        if verdict != 'ACCEPT':
            print(f'{BLOCK_SCHEMA}: validators_ok={validator_ok} identity_ok={identity_ok} identity_errors={identity_errors}', file=sys.stderr)
            return 1
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except SystemExit as exc:
        message = str(exc)
        validators = validate_chain(args.report_id, root, args.end_step) if args.validate_existing_only else {}
        report = build_report(args, root, 'BLOCK', validators, {'block_reason': message})
        write_report_if_requested(args, root, report)
        print(message, file=sys.stderr)
        if message.startswith(BLOCK_SCHEMA):
            return 1
        return int(exc.code) if isinstance(exc.code, int) and exc.code else 1
    except Exception as exc:
        validators = validate_chain(args.report_id, root, args.end_step) if args.validate_existing_only else {}
        report = build_report(args, root, 'BLOCK', validators, {'block_reason': f'{type(exc).__name__}: {exc}'})
        write_report_if_requested(args, root, report)
        print(f'{BLOCK_SCHEMA}: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
