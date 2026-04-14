#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN_STEP3 = ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3.py'
RUN_STEP3B = ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'run_step3b.py'
VAL_STEP3 = ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'validate_step3.py'
VAL_STEP3B = ROOT / 'skills' / 'factor-forge-step3' / 'scripts' / 'validate_step3b.py'


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


def main() -> None:
    report_id = 'STEP3_SAMPLE_CPV'
    fixture_root = ROOT / 'fixtures' / 'step3'
    objects = ROOT / 'objects'
    runs = ROOT / 'runs' / report_id / 'step3a_local_inputs'
    generated = ROOT / 'generated_code' / report_id

    copy_fixture(fixture_root / 'factor_spec_master__sample.json', objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    copy_fixture(fixture_root / 'alpha_idea_master__sample.json', objects / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json')

    runs.mkdir(parents=True, exist_ok=True)
    copy_fixture(fixture_root / 'minute_input__sample.csv', runs / f'minute_input__{report_id}.csv')
    copy_fixture(fixture_root / 'daily_input__sample.csv', runs / f'daily_input__{report_id}.csv')

    step3 = load_module(RUN_STEP3, 'factorforge_step3_runner')
    step3b = load_module(RUN_STEP3B, 'factorforge_step3b_runner')
    val3 = load_module(VAL_STEP3, 'factorforge_step3_validator')
    val3b = load_module(VAL_STEP3B, 'factorforge_step3b_validator')

    # patch local snapshot builder to use tiny fixture files instead of huge real/synthetic packages
    def tiny_snapshots(_report_id: str, _sample_window: dict):
        return {
            'minute_df_csv': str((runs / f'minute_input__{report_id}.csv').relative_to(ROOT.parent)),
            'daily_df_csv': str((runs / f'daily_input__{report_id}.csv').relative_to(ROOT.parent)),
            'sample_window_actual': {'start': '20160104', 'end': '20160105'},
            'snapshot_note': 'Tiny committed Step 3 sample fixture.'
        }

    step3.build_local_cpv_snapshots = tiny_snapshots
    data_prep_master, qlib_adapter_config, implementation_plan_stub = step3.build_step3a(report_id)

    out_path = ROOT / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    qlib_path = ROOT / 'objects' / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    impl_stub_path = ROOT / 'objects' / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    val_path = ROOT / 'objects' / 'validation' / f'data_feasibility_report__{report_id}.json'
    handoff_path = ROOT / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json'

    step3.write_json(out_path, data_prep_master)
    step3.write_json(qlib_path, qlib_adapter_config)
    step3.write_json(impl_stub_path, implementation_plan_stub)
    step3.write_json(val_path, {
        'report_id': report_id,
        'final_result': data_prep_master['feasibility'],
        'checks': data_prep_master['coverage_checks'],
        'proxy_count': len(data_prep_master['proxy_rules']),
        'local_input_paths': data_prep_master['local_input_paths']
    })
    step3.write_json(handoff_path, {
        'report_id': report_id,
        'data_prep_master_ref': out_path.name,
        'qlib_adapter_config_ref': qlib_path.name,
        'implementation_plan_master_ref': impl_stub_path.name,
        'factor_spec_master_ref': f'factor_spec_master__{report_id}.json',
        'local_input_paths': data_prep_master['local_input_paths']
    })

    # install real implementation so Step3B can produce first-run outputs
    generated.mkdir(parents=True, exist_ok=True)
    copy_fixture(fixture_root / 'factor_impl__sample.py', generated / f'factor_impl__{report_id}.py')

    # emulate CLI execution of step3 validators and step3b main
    import subprocess, sys
    subprocess.run(['python3', str(VAL_STEP3), '--report-id', report_id], cwd=str(ROOT.parent), check=True)
    subprocess.run(['python3', str(RUN_STEP3B), '--report-id', report_id], cwd=str(ROOT.parent), check=True)
    subprocess.run(['python3', str(VAL_STEP3B), '--report-id', report_id], cwd=str(ROOT.parent), check=True)


if __name__ == '__main__':
    main()
