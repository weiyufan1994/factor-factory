#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.factor_forge_step1.modules.report_ingestion.challenger.challenger_to_thesis import challenger_intake_to_thesis
from skills.factor_forge_step1.modules.report_ingestion.finalizers.alpha_idea_master_writer import AlphaIdeaMasterWriter
from skills.factor_forge_step1.modules.report_ingestion.finalizers.handoff_to_step2 import HandoffToStep2
from skills.factor_forge_step1.modules.report_ingestion.intake.pdf_skill_client import PdfSkillClient
from skills.factor_forge_step1.modules.report_ingestion.merge.merge_to_alpha_idea_master import merge_to_alpha_idea_master
from skills.factor_forge_step1.modules.report_ingestion.normalizers.intake_to_alpha_thesis import intake_to_alpha_thesis
from skills.factor_forge_step1.modules.report_ingestion.orchestration.wiring import build_step1_pipeline
from skills.factor_forge_step1.modules.report_ingestion.registry.report_source_contract import normalize_report_source


def load_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        if not v:
            continue
        if v not in out:
            out.append(v)
    return out


def build_default_chief_decision(primary_intake, challenger_intake) -> dict:
    pff = primary_intake.final_factor or {}
    cff = challenger_intake.final_factor or {}
    final = pff or cff

    factor_name = final.get('name') or pff.get('name') or cff.get('name') or 'UNNAMED_FACTOR'
    assembly_steps = final.get('assembly_steps') or pff.get('assembly_steps') or cff.get('assembly_steps') or []
    unresolved = dedupe((primary_intake.ambiguities or []) + (challenger_intake.ambiguities or []))
    subfactor_names = []
    for sf in (primary_intake.subfactors or []):
        if isinstance(sf, dict) and sf.get('name'):
            subfactor_names.append(sf['name'])

    return {
        'final_factor': {
            'name': factor_name,
            'assembly_steps': assembly_steps,
            'accepted_subfactor_names': dedupe(subfactor_names),
            'direction': final.get('direction', ''),
            'alpha_strength': final.get('alpha_strength', ''),
            'alpha_source': final.get('alpha_source', ''),
            'key_implementation_risks': final.get('key_implementation_risks', []),
            'economic_logic': final.get('economic_logic', ''),
            'economic_logic_provenance': final.get('economic_logic_provenance', ''),
            'behavioral_logic': final.get('behavioral_logic', ''),
            'behavioral_logic_provenance': final.get('behavioral_logic_provenance', ''),
            'causal_chain': final.get('causal_chain', ''),
            'causal_chain_provenance': final.get('causal_chain_provenance', ''),
            'rejected_subfactor_details': [],
        },
        'logic_provenance_summary': {
            'merge_mode': 'auto_fallback',
            'note': 'chief decision auto-built from provided intake JSON files',
        },
        'assembly_path': assembly_steps,
        'unresolved_ambiguities': unresolved,
        'chief_decision_summary': 'Auto chief merge from primary/challenger intake payloads.',
        'chief_confidence': 'medium',
        'chief_rationale': 'Primary route preferred; challenger route used for ambiguity coverage and sanity check.',
    }


def load_step2_runner():
    runner_path = ROOT / 'skills' / 'factor-forge-step2' / 'scripts' / 'run_step2.py'
    spec = importlib.util.spec_from_file_location('factorforge_step2_runner', runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load Step 2 runner from {runner_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run_step2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-file', required=True, help='Local report path (.pdf/.html).')
    ap.add_argument('--primary-intake-json', required=True, help='Primary intake JSON file.')
    ap.add_argument('--challenger-intake-json', help='Challenger intake JSON file. Defaults to primary file if omitted.')
    ap.add_argument('--report-id', help='Optional forced report_id.')
    ap.add_argument('--title', help='Optional report title.')
    ap.add_argument('--skip-step2', action='store_true', help='Only run Step1 artifacts generation.')
    args = ap.parse_args()

    report_path = Path(args.report_file).expanduser().resolve()
    if not report_path.exists():
        raise FileNotFoundError(f'report file not found: {report_path}')

    primary_intake_path = Path(args.primary_intake_json).expanduser().resolve()
    if not primary_intake_path.exists():
        raise FileNotFoundError(f'primary intake json not found: {primary_intake_path}')

    challenger_intake_path = (
        Path(args.challenger_intake_json).expanduser().resolve()
        if args.challenger_intake_json
        else primary_intake_path
    )
    if not challenger_intake_path.exists():
        raise FileNotFoundError(f'challenger intake json not found: {challenger_intake_path}')

    suffix = report_path.suffix.lower()
    source_type = 'html' if suffix in {'.html', '.htm'} else 'pdf'
    source = normalize_report_source(
        source_type=source_type,  # type: ignore[arg-type]
        source_uri=str(report_path),
        title=args.title or report_path.stem,
    )
    if args.report_id:
        source.report_id = args.report_id
    source.local_cache_path = str(report_path)
    source.status = 'cached'

    primary_response = load_text(primary_intake_path)
    challenger_response = load_text(challenger_intake_path)
    if primary_intake_path == challenger_intake_path:
        print('[WARN] challenger intake not provided; using primary intake as challenger fallback.')

    pipeline = build_step1_pipeline(ROOT)
    step1_result = pipeline.run_pdf_skill(
        source=source,
        response_text=primary_response,
        challenger_response_text=challenger_response,
    )

    parser = PdfSkillClient()
    primary_intake = parser.parse_response(source.report_id, primary_response)
    challenger_intake = parser.parse_response(source.report_id, challenger_response)
    primary_thesis = intake_to_alpha_thesis(primary_intake)
    challenger_thesis = challenger_intake_to_thesis(challenger_intake)
    chief_decision = build_default_chief_decision(primary_intake, challenger_intake)

    alpha_idea_master = merge_to_alpha_idea_master(
        primary_intake=primary_intake,
        challenger_intake=challenger_intake,
        primary_thesis=primary_thesis,
        challenger_thesis=challenger_thesis,
        chief_decision=chief_decision,
    )
    alpha_idea_master['source_uri'] = str(report_path)
    alpha_idea_master['local_cache_path'] = str(report_path)

    alpha_writer = AlphaIdeaMasterWriter(ROOT / 'objects' / 'alpha_idea_master')
    alpha_path = alpha_writer.write(source.report_id, alpha_idea_master)

    handoff_writer = HandoffToStep2(ROOT / 'objects' / 'handoff')
    handoff_path = handoff_writer.write_handoff(
        source.report_id,
        alpha_idea_master,
        metadata={
            'producer': 'run_step12_from_intake.py',
            'primary_intake_json': str(primary_intake_path),
            'challenger_intake_json': str(challenger_intake_path),
        },
    )

    step2_ran = False
    if not args.skip_step2:
        run_step2 = load_step2_runner()
        run_step2(source.report_id, dry_run=False)
        step2_ran = True

    summary = {
        'report_id': source.report_id,
        'report_file': str(report_path),
        'step1_status': step1_result.get('status'),
        'alpha_idea_master_path': str(alpha_path),
        'handoff_to_step2_path': str(handoff_path),
        'step2_ran': step2_ran,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'REPORT_ID={source.report_id}')


if __name__ == '__main__':
    main()
