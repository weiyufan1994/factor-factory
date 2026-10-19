#!/usr/bin/env python3
"""Bind existing state once for normal Ultimate Step3/4 consumption."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factor_factory.prepared_inputs import bind_prepared_inputs, verify_prepared_binding, write_prepared_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--base-dir', required=True, type=Path)
    parser.add_argument('--sample-controller', type=Path)
    parser.add_argument('--evaluation-daily', type=Path)
    parser.add_argument('--dependency', action='append', type=Path, default=[])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    payload = json.loads(args.inputs.read_text())
    if args.check:
        if not payload.get('prepared_input_hashes'):
            parser.error('--check requires an already bound input declaration')
        verify_prepared_binding(payload, base_dir=args.base_dir)
        print('PASS: bound files unchanged; no data fetched or computed')
        return
    if not all((args.sample_controller, args.evaluation_daily, args.output)):
        parser.error('binding requires --sample-controller, --evaluation-daily and --output')
    result = bind_prepared_inputs(payload, sample_controller=args.sample_controller,
        evaluation_daily=args.evaluation_daily, base_dir=args.base_dir,
        dependencies=tuple(args.dependency))
    write_prepared_inputs(args.output, result)
    print(json.dumps({'prepared_local_inputs': str(args.output.resolve()),
                      'verified_files': len(result['prepared_input_hashes']),
                      'data_copied': False, 'producer_executed': False}))


if __name__ == '__main__':
    main()
