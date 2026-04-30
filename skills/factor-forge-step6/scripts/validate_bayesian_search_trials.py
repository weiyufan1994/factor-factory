#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
REPO_ROOT = Path(__file__).resolve().parents[3]
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def check(name: str, condition: bool, error: str, severity: str = 'BLOCK', evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        'name': name,
        'ok': bool(condition),
        'status': 'PASS' if condition else severity,
        'severity': severity,
        'error': None if condition else error,
        'evidence': evidence or {},
    }


def nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--branch-id', required=True)
    args = ap.parse_args()

    rid = args.report_id
    branch_id = args.branch_id
    result_path = OBJ / 'research_iteration_master' / f'search_branch_result__{rid}__{branch_id}.json'
    checks: list[dict[str, Any]] = [check('result_exists', result_path.exists(), f'missing {result_path}')]
    result: dict[str, Any] = {}
    if result_path.exists():
        result = load_json(result_path)
        bayes = result.get('bayesian_search') or {}
        evidence = result.get('evidence') or {}
        trials = bayes.get('trials') or []
        completed = [trial for trial in trials if trial.get('status') == 'completed']
        artifact_paths = evidence.get('step4_artifacts') or []
        checks.extend([
            check('producer_is_bayesian_worker', result.get('producer') == 'program_search_bayesian_worker_v1', 'result was not produced by Bayesian worker'),
            check('branch_id_match', result.get('branch_id') == branch_id, 'branch_id mismatch'),
            check('approval_gate_preserved', result.get('human_approval_required_before_canonicalization') is True, 'human approval gate must remain true'),
            check('search_space_present', isinstance(bayes.get('search_space'), dict) and bool(bayes.get('search_space')), 'search_space missing'),
            check('trial_list_present', isinstance(trials, list) and bool(trials), 'no trials recorded'),
            check('completed_or_failure_recorded', bool(completed) or bool(evidence.get('failure_signatures')), 'must contain completed trials or failure signatures'),
            check('best_trial_consistent', (not completed) or isinstance(bayes.get('best_trial'), dict), 'completed trials require best_trial'),
            check('metric_delta_present', isinstance(evidence.get('metric_delta'), dict) and bool(evidence.get('metric_delta')), 'metric_delta missing'),
            check('overfit_assessed', nonempty((result.get('research_assessment') or {}).get('overfit_assessment')), 'overfit assessment missing'),
            check('falsification_assessed', nonempty((result.get('research_assessment') or {}).get('falsification_result')), 'falsification result missing'),
            check('artifact_paths_recorded', bool(artifact_paths), 'trial artifacts missing'),
        ])
        canonical_forbidden = ['handoff_to_step3b__', 'handoff_to_step4__', 'factor_impl_stub__']
        touched_forbidden = [p for p in artifact_paths if any(token in str(p) for token in canonical_forbidden)]
        checks.append(check('no_canonical_artifacts_written', not touched_forbidden, 'Bayesian worker must not write canonical handoff or Step3B files', evidence={'forbidden_paths': touched_forbidden}))
        for idx, trial in enumerate(trials, start=1):
            checks.append(check(f'trial_{idx:03d}_params_present', isinstance(trial.get('params'), dict) and bool(trial.get('params')), 'trial params missing'))
            if trial.get('status') == 'completed':
                metrics = trial.get('metrics') or {}
                checks.append(check(f'trial_{idx:03d}_score_present', trial.get('score') is not None, 'completed trial score missing'))
                checks.append(check(f'trial_{idx:03d}_rank_ic_present', isinstance(metrics.get('rank_ic'), dict), 'completed trial rank_ic missing'))
                checks.append(check(f'trial_{idx:03d}_long_side_present', isinstance(metrics.get('long_side'), dict), 'completed trial long_side missing'))
                checks.append(check(f'trial_{idx:03d}_long_short_diagnostic_present', isinstance(metrics.get('long_short'), dict), 'completed trial long_short diagnostic missing'))
            else:
                checks.append(check(f'trial_{idx:03d}_failure_kept', nonempty(trial.get('failure_reason')) or bool(evidence.get('failure_signatures')), 'failed trial must keep failure reason'))

    has_block = any(item['status'] == 'BLOCK' for item in checks)
    has_warn = any(item['status'] == 'WARN' for item in checks)
    verdict = 'BLOCK' if has_block else 'WARN' if has_warn else 'PASS'
    report = {'report_id': rid, 'branch_id': branch_id, 'result': verdict, 'checks': checks}
    out = OBJ / 'validation' / f'bayesian_search_validation__{rid}__{branch_id}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {out}')
    print(f'RESULT: {verdict}')
    if has_block:
        sys.exit(1)


if __name__ == '__main__':
    main()
