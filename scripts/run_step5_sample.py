#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def copy_fixture(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def csv_to_parquet(csv_path: Path, parquet_path: Path) -> None:
    import pandas as pd
    df = pd.read_csv(csv_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)


def main() -> None:
    report_id = 'STEP5_SAMPLE_CPV'
    fixture_root = ROOT / 'fixtures' / 'step5'
    objects = ROOT / 'objects'
    runs = ROOT / 'runs' / report_id
    eval_dir = ROOT / 'evaluations' / report_id / 'self_quant_analyzer'

    copy_fixture(fixture_root / 'factor_run_master__sample.json', objects / 'factor_run_master' / f'factor_run_master__{report_id}.json')
    copy_fixture(fixture_root / 'factor_spec_master__sample.json', objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json')
    copy_fixture(fixture_root / 'data_prep_master__sample.json', objects / 'data_prep_master' / f'data_prep_master__{report_id}.json')
    copy_fixture(fixture_root / 'handoff_to_step5__sample.json', objects / 'handoff' / f'handoff_to_step5__{report_id}.json')
    copy_fixture(fixture_root / 'factor_run_diagnostics__sample.json', objects / 'validation' / f'factor_run_diagnostics__{report_id}.json')

    runs.mkdir(parents=True, exist_ok=True)
    csv_path = runs / f'factor_values__{report_id}.csv'
    parquet_path = runs / f'factor_values__{report_id}.parquet'
    meta_path = runs / f'run_metadata__{report_id}.json'
    copy_fixture(fixture_root / 'factor_values__sample.csv', csv_path)
    csv_to_parquet(csv_path, parquet_path)
    copy_fixture(fixture_root / 'run_metadata__sample.json', meta_path)

    eval_dir.mkdir(parents=True, exist_ok=True)
    copy_fixture(fixture_root / 'evaluation_payload__sample.json', eval_dir / 'evaluation_payload.json')

    subprocess.run(['python3', str(ROOT / 'skills' / 'factor-forge-step5' / 'scripts' / 'run_step5.py'), '--report-id', report_id], cwd=str(ROOT.parent), check=True)
    subprocess.run(['python3', str(ROOT / 'skills' / 'factor-forge-step5' / 'scripts' / 'validate_step5.py'), '--report-id', report_id], cwd=str(ROOT.parent), check=True)


if __name__ == '__main__':
    main()
