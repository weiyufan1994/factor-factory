#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    print(f'[WRITE] {path}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def build_wrapper_code(report_id: str, factor_id: str, signal_column: str, base_rel: str, modification_targets: list[str], iteration_no: int) -> str:
    return f'''"""
Auto-generated Step 6 iterative refinement wrapper for {factor_id}.
This file is machine-generated from Step 6 judgment and wraps the previous Step 3B implementation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

REPORT_ID = {report_id!r}
FACTOR_ID = {factor_id!r}
SIGNAL_COLUMN = {signal_column!r}
BASE_IMPL_REL = {base_rel!r}
ITERATION_NO = {iteration_no}
MODIFICATION_TARGETS = {modification_targets!r}

# CONTEXT:
# - Step 6 decided this factor should iterate rather than stop.
# - This wrapper keeps the previous implementation intact and applies a conservative robustness pass.
#
# CONTRACT:
# - Base implementation must return ['ts_code', 'trade_date', SIGNAL_COLUMN].
# - This wrapper may only transform the signal column; it must not alter the row identity.
#
# RISK:
# - This is a generic refinement layer, not a paper-perfect rewrite.
# - It is intentionally conservative: temporal smoothing + cross-sectional winsorization + re-zscore.


def _load_base_module():
    base_path = Path(__file__).resolve().parents[2] / BASE_IMPL_REL
    spec = importlib.util.spec_from_file_location(base_path.stem, base_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot import base implementation from {{base_path}}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _winsorize_by_date(df: pd.DataFrame, column: str, lower: float = 0.025, upper: float = 0.975) -> pd.Series:
    lo = df.groupby('trade_date')[column].transform(lambda s: s.quantile(lower))
    hi = df.groupby('trade_date')[column].transform(lambda s: s.quantile(upper))
    return df[column].clip(lower=lo, upper=hi)


def _zscore_by_date(df: pd.DataFrame, column: str) -> pd.Series:
    grouped = df.groupby('trade_date')[column]
    mean = grouped.transform('mean')
    std = grouped.transform('std').replace(0, np.nan)
    return ((df[column] - mean) / std).fillna(0.0)


def compute_factor(minute_df: pd.DataFrame, daily_df: pd.DataFrame) -> pd.DataFrame:
    module = _load_base_module()
    base = module.compute_factor(minute_df, daily_df).copy()
    required = ['ts_code', 'trade_date', SIGNAL_COLUMN]
    missing = [c for c in required if c not in base.columns]
    if missing:
        raise KeyError(f'base implementation missing columns: {{missing}}')

    base = base[required].copy()
    base[SIGNAL_COLUMN] = pd.to_numeric(base[SIGNAL_COLUMN], errors='coerce')
    base = base.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)

    # Conservative iterative refinement:
    # 1) smooth idiosyncratic day noise along the time axis
    # 2) cap cross-sectional tails each day
    # 3) renormalize back to a comparable cross-sectional score
    base[SIGNAL_COLUMN] = (
        base.groupby('ts_code', sort=False)[SIGNAL_COLUMN]
        .transform(lambda s: s.rolling(3, min_periods=1).mean())
    )
    base[SIGNAL_COLUMN] = _winsorize_by_date(base, SIGNAL_COLUMN)
    base[SIGNAL_COLUMN] = _zscore_by_date(base, SIGNAL_COLUMN)
    return base


def main():
    raise SystemExit('This iteration wrapper is executed through Step 4 import flow only.')


if __name__ == '__main__':
    main()
'''


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the ultimate wrapper.')
    args = ap.parse_args()
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_APPLY: Step6 revision apply mutates canonical handoff/code and must be invoked by '
            'scripts/run_factorforge_ultimate.py, not by direct agent commands.'
        )
    manifest = load_runtime_manifest(args.manifest) if args.manifest else None
    if manifest:
        FF = manifest_factorforge_root(manifest)
        OBJ = FF / 'objects'
    report_id = args.report_id or (manifest_report_id(manifest) if manifest else None)
    if not report_id:
        raise SystemExit('apply_step6_iteration.py requires --report-id or --manifest')

    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    handoff3b_path = OBJ / 'handoff' / f'handoff_to_step3b__{report_id}.json'
    handoff4_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'
    impl_plan_path = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    proposal_path = OBJ / 'research_iteration_master' / f'revision_proposal__{report_id}.json'

    if not iteration_path.exists() or not handoff3b_path.exists() or not handoff4_path.exists() or not proposal_path.exists():
        raise SystemExit('STEP6_APPLY_INVALID: missing research_iteration/proposal or required handoff objects')

    iteration = load_json(iteration_path)
    handoff3b = load_json(handoff3b_path)
    handoff4 = load_json(handoff4_path)
    impl_plan = load_json(impl_plan_path) if impl_plan_path.exists() else {}
    proposal = load_json(proposal_path)

    if not iteration.get('loop_action', {}).get('should_modify_step3b'):
        raise SystemExit('STEP6_APPLY_SKIPPED: current decision does not request Step3B modification')
    if (proposal.get('approval') or {}).get('status') != 'approved':
        raise SystemExit('STEP6_APPROVAL_REQUIRED: revision proposal has not been approved by human')

    factor_id = str(iteration.get('factor_id') or report_id)
    signal_column = str(handoff4.get('signal_column') or f'{factor_id.lower()}_factor')
    current_impl_rel = handoff4.get('factor_impl_ref') or handoff4.get('factor_impl_stub_ref')
    if not current_impl_rel:
        raise SystemExit('STEP6_APPLY_INVALID: no current implementation path found in handoff_to_step4')

    current_impl_abs = FF / str(current_impl_rel)
    if not current_impl_abs.exists():
        raise SystemExit(f'STEP6_APPLY_INVALID: current implementation path does not exist: {current_impl_abs}')

    iteration_no = int(iteration.get('iteration_no') or 1)
    code_dir = current_impl_abs.parent
    next_rel = f'generated_code/{report_id}/factor_impl__{report_id}__iter{iteration_no}.py'
    next_abs = FF / next_rel

    wrapper = build_wrapper_code(
        report_id=report_id,
        factor_id=factor_id,
        signal_column=signal_column,
        base_rel=str(current_impl_rel),
        modification_targets=list(handoff3b.get('modification_targets') or []),
        iteration_no=iteration_no,
    )
    write_text(next_abs, wrapper)

    handoff4['factor_impl_ref'] = next_rel
    handoff4['execution_mode'] = handoff4.get('execution_mode') or 'direct_python'
    handoff4['step6_iteration_applied'] = {
        'iteration_no': iteration_no,
        'applied_at_utc': utc_now(),
        'base_impl_ref': str(current_impl_rel),
        'new_impl_ref': next_rel,
        'modification_targets': list(handoff3b.get('modification_targets') or []),
        'approval_notes': (proposal.get('approval') or {}).get('approver_notes'),
    }
    write_json(handoff4_path, handoff4)

    if impl_plan:
        impl_plan.setdefault('step4_contract', {})
        impl_plan['step4_contract']['runner_entry'] = next_rel
        impl_plan.setdefault('code_artifacts', {})
        impl_plan['code_artifacts'][f'iteration_impl_{iteration_no}'] = next_abs.name
        impl_plan.setdefault('iteration_history', [])
        impl_plan['iteration_history'].append(handoff4['step6_iteration_applied'])
        write_json(impl_plan_path, impl_plan)
