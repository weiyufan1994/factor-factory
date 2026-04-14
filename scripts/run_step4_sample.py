#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_STEP4 = ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / 'run_step4.py'
VAL_STEP4 = ROOT / 'skills' / 'factor-forge-step4' / 'scripts' / 'validate_step4.py'


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load module from {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_fixture(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    report_id = 'STEP4_SAMPLE_CPV'
    fixture_root = ROOT / 'fixtures' / 'step4'
    objects = ROOT / 'objects'
    runs = ROOT / 'runs' / report_id / 'step3a_local_inputs'
    generated = ROOT / 'generated_code' / report_id

    copy_fixture(fixture_root / 'factor_spec_master__sample.json', objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    copy_fixture(fixture_root / 'data_prep_master__sample.json', objects / 'data_prep_master' / f'data_prep_master__{report_id}.json')

    runs.mkdir(parents=True, exist_ok=True)
    copy_fixture(fixture_root / 'minute_input__sample.csv', runs / f'minute_input__{report_id}.csv')
    copy_fixture(fixture_root / 'daily_input__sample.csv', runs / f'daily_input__{report_id}.csv')

    generated.mkdir(parents=True, exist_ok=True)
    copy_fixture(fixture_root / 'factor_impl__sample.py', generated / f'factor_impl__{report_id}.py')
    copy_fixture(fixture_root / 'factor_impl__sample.py', generated / f'factor_impl_stub__{report_id}.py')
    write_json(generated / f'qlib_expression_draft__{report_id}.json', {'report_id': report_id, 'status': 'draft', 'mode': 'hybrid_only'})
    write_json(generated / f'hybrid_execution_scaffold__{report_id}.json', {'report_id': report_id, 'execution_mode': 'hybrid'})

    copy_fixture(fixture_root / 'handoff_to_step4__sample.json', objects / 'handoff' / f'handoff_to_step4__{report_id}.json')
    write_json(objects / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json', {
        'report_id': report_id,
        'factor_id': 'CPV',
        'implementation_mode': 'hybrid',
        'step4_contract': {'execution_mode': 'hybrid'}
    })

    import subprocess
    subprocess.run(['python3', str(RUN_STEP4), '--report-id', report_id], cwd=str(ROOT.parent), check=True)
    subprocess.run(['python3', str(VAL_STEP4), '--report-id', report_id], cwd=str(ROOT.parent), check=True)


if __name__ == '__main__':
    main()
