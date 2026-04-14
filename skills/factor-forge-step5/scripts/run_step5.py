#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

W = Path('/home/ubuntu/.openclaw/workspace')
if str(W) not in sys.path:
    sys.path.insert(0, str(W))

from skills.factor_forge_step5.modules.io import write_json  # type: ignore
from skills.factor_forge_step5.modules.archiver import (  # type: ignore
    init_archive_dir,
    normalize_archive_subdirs,
    copy_many_preserve_existing,
)
from skills.factor_forge_step5.modules.rules import (  # type: ignore
    determine_final_status,
    load_step5_inputs,
    validate_input_consistency,
)
from skills.factor_forge_step5.modules.evaluator import build_factor_evaluation  # type: ignore
from skills.factor_forge_step5.modules.case_builder import build_factor_case_master  # type: ignore

OBJ = W / 'factorforge' / 'objects'


def archive_artifacts(bundle: dict, evaluation_path: Path | None = None, case_path: Path | None = None) -> list[str]:
    rid = bundle['report_id']
    arch_dir = init_archive_dir(rid, W)
    subdirs = normalize_archive_subdirs(arch_dir)
    runs_dir = subdirs['runs']
    eval_dir = subdirs['evaluations']
    obj_dir = subdirs['objects']

    candidates: list[tuple[Path, Path]] = []
    frm = bundle['objects'].get('factor_run_master') or {}

    for raw_path in frm.get('output_paths', []) or []:
        src = Path(raw_path)
        candidates.append((src, runs_dir / src.name))

    report_eval_dir = W / 'factorforge' / 'evaluations' / rid
    if report_eval_dir.exists():
        for src in report_eval_dir.glob('**/*'):
            if src.is_file():
                rel = src.relative_to(report_eval_dir)
                candidates.append((src, eval_dir / rel))

    for raw_path in bundle['paths'].values():
        src = Path(raw_path)
        candidates.append((src, obj_dir / src.name))

    if evaluation_path is not None:
        candidates.append((evaluation_path, obj_dir / evaluation_path.name))
    if case_path is not None:
        candidates.append((case_path, obj_dir / case_path.name))

    real_candidates = [(src, dst) for src, dst in candidates if src.exists() and src.is_file()]
    copy_many_preserve_existing(real_candidates)
    return [str(dst) for _, dst in real_candidates]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    a = ap.parse_args()
    rid = a.report_id

    bundle = load_step5_inputs(rid, W)
    ok, errors, warnings = validate_input_consistency(bundle)
    if not ok:
        raise SystemExit('STEP5_INPUT_INVALID: ' + '; '.join(errors))

    evaluation = build_factor_evaluation(bundle)
    evaluation['warnings'] = list(dict.fromkeys((evaluation.get('warnings') or []) + warnings))
    final_status = determine_final_status(bundle, evaluation)
    evaluation['evaluation_status'] = final_status

    evaluation_path = OBJ / 'validation' / f'factor_evaluation__{rid}.json'
    write_json(evaluation_path, evaluation)
    print(f'[WRITE] {evaluation_path}')

    case = build_factor_case_master(
        bundle=bundle,
        evaluation=evaluation,
        archive_paths=[],
        final_status=final_status,
        evaluation_path=str(evaluation_path),
    )
    case_path = OBJ / 'factor_case_master' / f'factor_case_master__{rid}.json'
    write_json(case_path, case)
    print(f'[WRITE] {case_path}')

    archive_paths = archive_artifacts(bundle, evaluation_path=evaluation_path, case_path=case_path)
    case['evidence']['archive_paths'] = archive_paths
    write_json(case_path, case)
    print(f'[WRITE] {case_path}')
