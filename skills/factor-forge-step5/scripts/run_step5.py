#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
W = FF.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

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
from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id

OBJ = FF / 'objects'


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FF, W, OBJ
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step5 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FF.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    if manifest_path:
        manifest = load_runtime_manifest(manifest_path)
        if manifest_factorforge_root(manifest).expanduser().resolve() != debug_root:
            raise SystemExit('BLOCKED_DIRECT_STEP: direct debug manifest must point to FACTORFORGE_DEBUG_ROOT.')
    FF = debug_root
    W = FF.parent
    OBJ = FF / 'objects'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def archive_artifacts(bundle: dict, evaluation_path: Path | None = None, case_path: Path | None = None) -> list[str]:
    rid = bundle['report_id']
    arch_dir = init_archive_dir(rid, FF)
    subdirs = normalize_archive_subdirs(arch_dir)
    runs_dir = subdirs['runs']
    eval_dir = subdirs['evaluations']
    obj_dir = subdirs['objects']

    candidates: list[tuple[Path, Path]] = []
    frm = bundle['objects'].get('factor_run_master') or {}

    for raw_path in frm.get('output_paths', []) or []:
        src = Path(raw_path)
        candidates.append((src, runs_dir / src.name))

    report_eval_dir = FF / 'evaluations' / rid
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


def build_handoff_to_step6(bundle: dict, evaluation: dict, case: dict, evaluation_path: Path, case_path: Path, archive_paths: list[str]) -> dict:
    frm = bundle["objects"].get("factor_run_master") or {}
    return {
        "report_id": bundle["report_id"],
        "factor_id": frm.get("factor_id"),
        "final_status": case.get("final_status"),
        "run_status": frm.get("run_status"),
        "factor_run_master_path": bundle["paths"].get("factor_run_master"),
        "factor_case_master_path": str(case_path),
        "factor_evaluation_path": str(evaluation_path),
        "archive_paths": archive_paths,
        "lessons": case.get("lessons") or [],
        "next_actions": case.get("next_actions") or [],
        "math_discipline_review": case.get("math_discipline_review") or {},
        "backend_summary": evaluation.get("backend_summary") or [],
        "known_limits": case.get("known_limits") or [],
        "created_by_step": "step5",
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    a = ap.parse_args()
    enforce_direct_step_policy(a.manifest)
    manifest = load_runtime_manifest(a.manifest) if a.manifest else None
    if manifest:
        FF = manifest_factorforge_root(manifest)
        W = FF.parent
        OBJ = FF / 'objects'
    rid = a.report_id or (manifest_report_id(manifest) if manifest else None)
    if not rid:
        raise SystemExit('run_step5.py requires --report-id or --manifest')

    bundle = load_step5_inputs(rid, FF)
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

    handoff_to_step6 = build_handoff_to_step6(
        bundle=bundle,
        evaluation=evaluation,
        case=case,
        evaluation_path=evaluation_path,
        case_path=case_path,
        archive_paths=archive_paths,
    )
    handoff_path = OBJ / 'handoff' / f'handoff_to_step6__{rid}.json'
    write_json(handoff_path, handoff_to_step6)
    print(f'[WRITE] {handoff_path}')
