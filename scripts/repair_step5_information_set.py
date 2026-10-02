#!/usr/bin/env python3
"""Re-derive only a legacy Step5 narrative information-time classification.

Use after independent engineering review, under an explicit new Step5
maintenance continuation. This does not execute a factor, evaluator, validator
or journal transition. Default is an external preview; --apply is single-writer
maintenance of the manifest's case/handoff only. Partial failures are retained
for reconciliation, never automatically retried or called a successful stage.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from factor_factory import information_set_review as classifier
from factor_factory.runtime_context import write_json_atomic


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_bound(path: Path, expected: str) -> tuple[bytes, dict]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError(f"Expected bounded concrete JSON: {path}")
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError(f"Reviewed input changed: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return raw, value


def derive(manifest_path: Path, expected: dict[str, str]) -> tuple[dict, dict, dict]:
    manifest_raw, manifest = read_bound(manifest_path, expected['manifest'])
    objects = manifest['objects']
    output_contract = manifest['step_io']['step5']['outputs']
    paths = {'manifest': manifest_path}
    for key, name in [('spec', 'factor_spec_master'), ('case', 'factor_case_master'),
                      ('handoff', 'handoff_to_step6')]:
        path = Path(objects[name])
        if not path.is_absolute():
            raise ValueError('Maintenance requires explicit absolute manifest paths')
        if key != 'spec' and output_contract[name] != str(path):
            raise ValueError('Manifest object/output paths disagree')
        paths[key] = path
    if len({p.resolve() for p in paths.values()}) != len(paths):
        raise ValueError('Maintenance inputs/outputs must be distinct')
    originals = {'manifest': manifest_raw}
    loaded = {}
    for key in ('spec', 'case', 'handoff'):
        originals[key], loaded[key] = read_bound(paths[key], expected[key])
    spec, case, handoff = (loaded[k] for k in ('spec', 'case', 'handoff'))
    report_id = spec.get('report_id')
    if not report_id or any(v.get('report_id') != report_id for v in (case, handoff)):
        raise ValueError('Report identity mismatch')
    if case.get('factor_id') != handoff.get('factor_id'):
        raise ValueError('Case/handoff factor identity mismatch')
    if case.get('math_discipline_review') != handoff.get('math_discipline_review'):
        raise ValueError('Case/handoff math review mismatch')
    canonical = spec['canonical_spec']
    old = (case.get('math_discipline_review') or {}).get('information_set_legality')
    new = classifier.classify_information_set(canonical)
    if old != classifier.ILLEGAL or classifier.legacy_information_set(canonical) != old:
        raise ValueError('Not an original legacy forward-reference classification')
    if new != classifier.UNCONFIRMED:
        raise ValueError('Only legacy narrative BLOCK to unconfirmed review is supported')
    if 'information_set_metadata_revision' in case['math_discipline_review']:
        raise ValueError('Already revised; preserve history and reconcile instead of retrying')
    revision = {
        'kind': 'step5_information_set_metadata_maintenance_v1',
        'old_classification': old, 'new_classification': new,
        'independent_confirmation_required': True,
        'implementation_safety_confirmed': False,
        'market_or_economic_computation_executed': False,
        'original_artifact_identity_preserved': True,
        'parents': {key: {'path': str(paths[key]), 'sha256': digest(raw)}
                    for key, raw in originals.items()},
        'maintenance_tool': {'path': str(Path(__file__).resolve()),
                             'sha256': digest(Path(__file__).read_bytes())},
        'classifier': {'path': str(Path(classifier.__file__).resolve()),
                       'sha256': digest(Path(classifier.__file__).read_bytes())},
    }
    candidates = {}
    for key in ('case', 'handoff'):
        updated = deepcopy(loaded[key])
        updated['math_discipline_review']['information_set_legality'] = new
        updated['math_discipline_review']['information_set_metadata_revision'] = revision
        candidates[key] = updated
    return paths, originals, candidates


def repair(manifest_path: Path, expected: dict[str, str], evidence_dir: Path, *, apply: bool = False) -> dict:
    paths, originals, candidates = derive(manifest_path, expected)
    # Preservation must be outside the live artifact directories and use a fresh
    # location. No existing receipt or original file may be overwritten.
    dest = evidence_dir.resolve()
    if any(dest == p.parent.resolve() or p.resolve().is_relative_to(dest) for p in paths.values()):
        raise ValueError('Evidence directory overlaps live inputs/outputs')
    dest.mkdir(parents=True, exist_ok=False)
    for key in ('case', 'handoff'):
        (dest / f'original_{key}.json').write_bytes(originals[key])
        write_json_atomic(dest / f'derived_{key}.json', candidates[key])
    receipt = {
        'status': 'PREVIEW', 'applied_paths': [],
        'scope': 'Metadata classification only; native validator and Step6 remain required',
        'originals': {key: {'path': str(paths[key]), 'sha256': digest(raw)}
                      for key, raw in originals.items()},
        'outputs': {key: {'path': str(paths[key]),
                         'sha256': digest((dest / f'derived_{key}.json').read_bytes())}
                    for key in ('case', 'handoff')},
        'revision': candidates['case']['math_discipline_review']['information_set_metadata_revision'],
    }
    receipt_path = dest / 'receipt.json'
    write_json_atomic(receipt_path, receipt)
    if not apply:
        return receipt
    try:
        for key, raw in originals.items():
            read_bound(paths[key], digest(raw))
        for key in ('case', 'handoff'):
            write_json_atomic(paths[key], candidates[key])
            receipt['applied_paths'].append(str(paths[key]))
            read_bound(paths[key], receipt['outputs'][key]['sha256'])
        for key in ('manifest', 'spec'):
            read_bound(paths[key], digest(originals[key]))
        receipt['status'] = 'METADATA_REDERIVED_REQUIRES_NATIVE_VALIDATION'
    except Exception as exc:
        receipt['status'] = 'APPLY_FAILED_RECONCILE_NO_AUTOMATIC_RETRY'
        receipt['error'] = str(exc)
        write_json_atomic(receipt_path, receipt)
        raise
    write_json_atomic(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    for key in ('manifest', 'spec', 'case', 'handoff'):
        parser.add_argument(f'--expected-{key}-sha256', required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = repair(args.manifest, {k: getattr(args, f'expected_{k}_sha256')
                        for k in ('manifest', 'spec', 'case', 'handoff')},
                        args.evidence_dir, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'status': 'BLOCK', 'reason': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
