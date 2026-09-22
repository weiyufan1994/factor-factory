#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.knowledge_reference import build_knowledge_reference_contract
from factor_factory.measurement_program import BLOCK_MEASUREMENT_PROGRAM_INVALID
from step12_intake_common import (
    attach_agent_authored_measurement_program,
    build_canonical_formula_step1,
    write_step1_artifacts,
)

STEP2_SCRIPT_DIR = REPO_ROOT / 'skills' / 'factor-forge-step2' / 'scripts'
if str(STEP2_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(STEP2_SCRIPT_DIR))

from run_step2 import run_step2


def main() -> None:
    parser = argparse.ArgumentParser(description='Formal Step1/2 intake from a canonical paper formula.')
    parser.add_argument('--report-id', required=True)
    parser.add_argument('--factor-id', required=True)
    parser.add_argument('--source-name', required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--formula', required=True)
    parser.add_argument('--window-start')
    parser.add_argument('--window-end')
    parser.add_argument(
        '--measurement-program-json',
        help=(
            'Current-agent authored mechanism-conditioned measurement program. '
            'Required before Step2; deterministic intake never invents it.'
        ),
    )
    parser.add_argument('--skip-step2', action='store_true', help='Only write Step1 intake artifacts.')
    args = parser.parse_args()

    artifacts = build_canonical_formula_step1(
        report_id=args.report_id,
        factor_id=args.factor_id,
        source_name=args.source_name,
        source_url=args.source_url,
        formula=args.formula,
        window_start=args.window_start,
        window_end=args.window_end,
    )
    if args.measurement_program_json:
        program_path = Path(args.measurement_program_json).expanduser().resolve(strict=True)
        program_payload = json.loads(program_path.read_text(encoding='utf-8'))
        if not isinstance(program_payload, dict):
            raise SystemExit(
                f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: measurement program must be a JSON object'
            )
        program = program_payload.get('mechanism_conditioned_measurement_program')
        if not isinstance(program, dict):
            program = program_payload
        knowledge = build_knowledge_reference_contract(
            repo_root=REPO_ROOT,
            knowledge_root=REPO_ROOT / 'knowledge' / '因子工厂',
            query_text=json.dumps(
                {
                    'report_id': args.report_id,
                    'factor_id': args.factor_id,
                    'source_name': args.source_name,
                    'formula': args.formula,
                    'measurement_program': program,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            producer='run_step12_from_canonical_formula_current_agent',
            retrieval_required=False,
        )
        try:
            artifacts = attach_agent_authored_measurement_program(
                artifacts,
                measurement_program=program,
                knowledge_reference_contract=knowledge,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    elif not args.skip_step2:
        raise SystemExit(
            f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: --measurement-program-json '
            'is required before formal Step2'
        )
    write_step1_artifacts(args.report_id, artifacts['aim'], artifacts['primary'], artifacts['challenger'], artifacts['report_map'])
    if args.skip_step2:
        print('[DONE] Step1 canonical formula intake complete; Step2 skipped by request.')
        return
    run_step2(args.report_id)
    print('[DONE] Step1/2 canonical formula intake complete.')


if __name__ == '__main__':
    main()
