#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from step12_intake_common import build_canonical_formula_step1, write_step1_artifacts

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
    write_step1_artifacts(args.report_id, artifacts['aim'], artifacts['primary'], artifacts['challenger'], artifacts['report_map'])
    if args.skip_step2:
        print('[DONE] Step1 canonical formula intake complete; Step2 skipped by request.')
        return
    run_step2(args.report_id)
    print('[DONE] Step1/2 canonical formula intake complete.')


if __name__ == '__main__':
    main()
