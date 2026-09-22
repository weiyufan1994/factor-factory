#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.formula.field_aliases import validate_standard_formula_fields_contract


REPORT_ID = 'STANDARD_FIELDS_ALPHA036_SMOKE'
FORMULA = (
    '(((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) '
    '+ (0.7 * rank((open - close)))) '
    '+ (0.73 * rank(ts_rank(delay((-1 * returns), 6), 5)))) '
    '+ rank(abs(correlation(vwap, adv20, 6)))) '
    '+ (0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))))'
)


def run(cmd: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env['FACTORFORGE_ROOT'] = str(root)
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    root = Path(tempfile.gettempdir()) / 'factorforge_standard_formula_fields_contract_smoke'
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    proc = run(
        [
            sys.executable,
            'scripts/run_step12_from_canonical_formula.py',
            '--report-id',
            REPORT_ID,
            '--factor-id',
            'Alpha036',
            '--source-name',
            'WorldQuant 101 Formulaic Alphas',
            '--source-url',
            'https://arxiv.org/abs/1601.00991',
            '--formula',
            FORMULA,
            '--window-start',
            '20160101',
        ],
        root,
    )
    spec_path = root / 'objects' / 'factor_spec_master' / f'factor_spec_master__{REPORT_ID}.json'
    case: dict[str, object] = {
        'case': 'fresh_step12_alpha036_emits_standard_formula_fields_contract',
        'rc': proc.returncode,
        'spec_path': str(spec_path),
        'spec_exists': spec_path.exists(),
        'ok': False,
    }
    if proc.returncode == 0 and spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding='utf-8'))
        canonical = spec.get('canonical_spec') if isinstance(spec.get('canonical_spec'), dict) else {}
        contract = spec.get('standard_formula_fields_contract')
        canonical_contract = canonical.get('standard_formula_fields_contract')
        required = contract.get('required_standard_formula_fields') if isinstance(contract, dict) else []
        failures = validate_standard_formula_fields_contract(
            contract if isinstance(contract, dict) else None,
            formula_text=str(canonical.get('formula_text') or ''),
            required_fields=canonical.get('required_fields') or [],
        )
        case.update(
            {
                'required_standard_formula_fields': required,
                'canonical_contract_present': isinstance(canonical_contract, dict),
                'validator_failures': failures,
                'ok': (
                    isinstance(contract, dict)
                    and isinstance(canonical_contract, dict)
                    and set(required) == {'adv20', 'returns', 'volume', 'vwap'}
                    and not failures
                ),
            }
        )
    else:
        case.update({'stdout_tail': proc.stdout[-4000:], 'stderr_tail': proc.stderr[-4000:]})

    summary = {
        'version': 'factorforge_standard_formula_fields_contract_smoke_v1',
        'factorforge_root': str(root),
        'cases': [case],
        'verdict': 'ACCEPT' if case.get('ok') is True else 'BLOCK',
    }
    out = root / 'standard_formula_fields_contract_smoke_summary.json'
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'[SUMMARY] {out}')
    return 0 if summary['verdict'] == 'ACCEPT' else 1


if __name__ == '__main__':
    raise SystemExit(main())
