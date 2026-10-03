#!/usr/bin/env python3
"""Offline result-file construction demo, not a factor or performance result."""
from pathlib import Path
import argparse
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from factor_factory.runtime_context import FactorForgeContext
from factor_factory.result_artifacts import build_result_artifacts, prepare_result_paths, write_result_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, help='New absolute workspace path; spaces are supported')
    args = parser.parse_args()
    root = Path(args.output_dir).expanduser()
    if not root.is_absolute() or root.exists():
        parser.error('--output-dir must be a new absolute directory; existing results are preserved')
    context = FactorForgeContext(REPO, root.parent, root, factor_workspace=root)
    paths = prepare_result_paths(context, 'RESULT_FILES_DEMO', 'synthetic',
        files={'daily_nav': 'account/nav.csv', 'month_202001': 'diagnostics/202001.json'},
        directories={'monthly_diagnostics': 'diagnostics'})
    Path(paths['artifacts']['daily_nav']).write_text('trade_date,nav\n20200102,1.0\n20200103,1.0\n')
    Path(paths['artifacts']['month_202001']).write_text('{"scope":"synthetic file interface only"}')
    fields = build_result_artifacts(files={**paths['artifacts'], 'optional_chart': None},
                                   directories=paths['artifact_directories'], base_dir=root)
    write_result_payload(paths['payload_path'], {'status': 'partial',
        'scope': 'synthetic interface demonstration; no research or backtest conclusion',
        'metrics': {'example_rows': 2}, **fields}, base_dir=root)
    print(paths['payload_path'])


if __name__ == '__main__':
    main()
