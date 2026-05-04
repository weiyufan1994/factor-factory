from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from factor_factory.data_access.catalog import DatasetEntry, upsert_dataset


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def seed_step3_inputs(root: Path, report_id: str, *, formula_text: str, required_inputs: list[str]) -> None:
    objects = root / 'objects'
    write_json(
        objects / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json',
        {
            'report_id': report_id,
            'final_factor': {'name': report_id, 'formula': formula_text},
        },
    )
    write_json(
        objects / 'factor_spec_master' / f'factor_spec_master__{report_id}.json',
        {
            'report_id': report_id,
            'factor_id': report_id,
            'canonical_spec': {
                'formula_text': formula_text,
                'required_inputs': required_inputs,
                'operators': [],
                'time_series_steps': [],
                'cross_sectional_steps': [],
            },
        },
    )


def run_step3(root: Path, report_id: str, *, catalog_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    env['FACTORFORGE_ULTIMATE_RUN'] = '1'
    if catalog_path is None:
        env.pop('FACTORFORGE_DATA_CATALOG', None)
    else:
        env['FACTORFORGE_DATA_CATALOG'] = str(catalog_path)
    return subprocess.run(
        [sys.executable, 'skills/factor-forge-step3/scripts/run_step3.py', '--report-id', report_id],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def validate_step3(root: Path, report_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['FACTORFORGE_ROOT'] = str(root)
    env.pop('FACTORFORGE_DATA_CATALOG', None)
    return subprocess.run(
        [sys.executable, 'skills/factor-forge-step3/scripts/validate_step3.py', '--report-id', report_id],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


def test_step3a_uses_data_api_catalog_and_resolves_volume_alias(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_DATA_API_READY'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='sum(rank(volume), 5)',
        required_inputs=['volume', 'close'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0, 'vol': 100, 'amount': 1000},
            {'ts_code': '000002.SZ', 'trade_date': '20260102', 'close': 20.0, 'vol': 200, 'amount': 2000},
        ]
    ).to_parquet(data_path, index=False)
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(data_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close', 'vol', 'amount'),
            qlib_field_map={'$volume': 'vol', '$close': 'close', '$amount': 'amount'},
        ),
        root / 'data' / 'catalog' / 'data_catalog.json',
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'ready'
    assert prep['local_input_paths']['snapshot_source'] == 'factorforge_data_api'
    assert prep['data_api_resolution']['daily_resolution']['resolved_fields']['volume'] == 'vol'
    daily_path = root.parent / prep['local_input_paths']['daily_df_csv']
    daily_meta = root.parent / prep['local_input_paths']['daily_input_meta']
    assert daily_path.exists()
    assert daily_meta.exists()
    assert set(pd.read_csv(daily_path).columns) == {'ts_code', 'trade_date', 'close', 'vol'}
    handoff = json.loads((root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json').read_text())
    assert handoff['data_api_resolution']['status'] == 'ready'


def test_step3a_writes_requirement_when_catalog_missing_fields(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_DATA_API_REQUIREMENT'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='correlation(rank(high), rank(volume), 3)',
        required_inputs=['high', 'volume'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {'ts_code': '000001.SZ', 'trade_date': '20260102', 'high': 11.0},
        ]
    ).to_parquet(data_path, index=False)
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(data_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'high'),
        ),
        root / 'data' / 'catalog' / 'data_catalog.json',
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'missing_fields'
    assert 'volume' in prep['data_api_resolution']['missing_fields']['clean_daily_bar']
    requirement_path = root / 'objects' / 'data_requirements' / prep['data_requirement_ref']
    requirement = json.loads(requirement_path.read_text())
    assert requirement['type'] == 'factorforge_data_requirement'
    assert requirement['dataset_id'] == 'clean_daily_bar'
    assert requirement['resolution']['status'] == 'missing_fields'
    assert not (root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv').exists()


def test_step3a_writes_requirement_when_catalog_missing_dataset(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_DATA_API_MISSING_DATASET'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(close)',
        required_inputs=['close'],
    )
    data_path = tmp_path / 'other.parquet'
    pd.DataFrame(
        [
            {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0},
        ]
    ).to_parquet(data_path, index=False)
    upsert_dataset(
        DatasetEntry(
            dataset_id='other_dataset',
            uri=str(data_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close'),
        ),
        root / 'data' / 'catalog' / 'data_catalog.json',
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'missing_dataset'
    assert prep['data_api_resolution']['missing_datasets'] == ['clean_daily_bar']
    requirement_path = root / 'objects' / 'data_requirements' / prep['data_requirement_ref']
    requirement = json.loads(requirement_path.read_text())
    assert requirement['resolution']['available_datasets'] == ['other_dataset']
    assert not (root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv').exists()


def test_step3a_records_catalog_absent_legacy_shared_clean_fallback(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_CATALOG_ABSENT_FALLBACK'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(close)',
        required_inputs=['close'],
    )
    clean_dir = root / 'data' / 'clean'
    clean_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0, 'vol': 100},
            {'ts_code': '000002.SZ', 'trade_date': '20260103', 'close': 20.0, 'vol': 200},
        ]
    ).to_parquet(clean_dir / 'daily_clean.parquet', index=False)
    write_json(
        clean_dir / 'daily_clean.meta.json',
        {
            'mode': 'shared_clean_daily_layer',
            'policy': {},
            'clean_meta': {'counts': {}, 'drop_counts': {}},
            'output_summary': {'rows': 2, 'tickers': 2, 'trade_dates': 2},
        },
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'ready'
    assert prep['data_api_resolution']['status'] == 'catalog_absent_legacy_shared_clean_fallback'
    assert prep['local_input_paths']['snapshot_source'] == 'shared_clean_daily_layer'
    assert prep['local_input_paths']['daily_filter_policy'] != 'factorforge_data_api_catalog_slice'


def test_step3a_cpv_blocks_when_catalog_exists_without_minute_bar(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'CPV_DATA_API_MISSING_MINUTE'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='price-volume correlation using close, volume and amount',
        required_inputs=['close', 'volume', 'amount'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {
                'ts_code': '000001.SZ',
                'trade_date': '20160104',
                'close': 10.0,
                'vol': 100,
                'amount': 1000,
                'turnover_rate': 1.2,
                'total_mv': 100000.0,
                'pe': 10.0,
                'pb': 1.0,
                'ps': 2.0,
            },
        ]
    ).to_parquet(data_path, index=False)
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(data_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close', 'vol', 'amount', 'turnover_rate', 'total_mv', 'pe', 'pb', 'ps'),
        ),
        root / 'data' / 'catalog' / 'data_catalog.json',
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'missing_dataset'
    assert prep['data_api_resolution']['missing_datasets'] == ['minute_bar']
    assert prep['local_input_paths']['snapshot_source'] == 'data_api_requirement'
    assert not (root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv').exists()
    handoff = json.loads((root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json').read_text())
    assert handoff['step3a_ready'] is False


def test_step3a_cpv_uses_data_api_for_daily_and_minute(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'CPV_DATA_API_READY'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='price-volume correlation using close, volume and amount',
        required_inputs=['close', 'volume', 'amount'],
    )
    daily_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {
                'ts_code': '000001.SZ',
                'trade_date': '20160104',
                'close': 10.0,
                'vol': 100,
                'amount': 1000,
                'turnover_rate': 1.2,
                'total_mv': 100000.0,
                'pe': 10.0,
                'pb': 1.0,
                'ps': 2.0,
            },
        ]
    ).to_parquet(daily_path, index=False)
    minute_path = tmp_path / 'minute.parquet'
    pd.DataFrame(
        [
            {
                'ts_code': '000001.SZ',
                'trade_date': '20160104',
                'trade_time': '20160104 09:30:00',
                'bar_time': '09:30:00',
                'minute_index': 0,
                'open': 10.0,
                'high': 10.2,
                'low': 9.9,
                'close': 10.1,
                'vol': 100,
                'amount': 1010,
            },
        ]
    ).to_parquet(minute_path, index=False)
    catalog_path = root / 'data' / 'catalog' / 'data_catalog.json'
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(daily_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close', 'vol', 'amount', 'turnover_rate', 'total_mv', 'pe', 'pb', 'ps'),
        ),
        catalog_path,
    )
    upsert_dataset(
        DatasetEntry(
            dataset_id='minute_bar',
            uri=str(minute_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'trade_time', 'bar_time', 'minute_index', 'open', 'high', 'low', 'close', 'vol', 'amount'),
        ),
        catalog_path,
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'proxy_ready'
    assert prep['data_api_resolution']['status'] == 'ready'
    assert prep['data_api_resolution']['minute_resolution']['dataset_id'] == 'minute_bar'
    assert prep['local_input_paths']['snapshot_source'] == 'factorforge_data_api'
    assert (root.parent / prep['local_input_paths']['daily_df_csv']).exists()
    assert (root.parent / prep['local_input_paths']['minute_df_csv']).exists()


def test_step3a_cpv_catalog_absent_fallback_records_resolution(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP_CPV_CATALOG_ABSENT_FALLBACK'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='price-volume correlation using close, volume and amount',
        required_inputs=['close', 'volume', 'amount'],
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['data_api_resolution']['status'] == 'catalog_absent_legacy_shared_clean_fallback'
    assert prep['data_api_resolution']['catalog_exists'] is False
    assert prep['local_input_paths']['snapshot_source'] == 'synthetic_fallback'


def test_validate_step3_rejects_ready_without_data_api_resolution(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_FAKE_READY'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(close)',
        required_inputs=['close'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0},
        ]
    ).to_parquet(data_path, index=False)
    upsert_dataset(
        DatasetEntry(
            dataset_id='clean_daily_bar',
            uri=str(data_path),
            format='parquet',
            columns=('ts_code', 'trade_date', 'close'),
        ),
        root / 'data' / 'catalog' / 'data_catalog.json',
    )
    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr

    for rel in [
        ('data_prep_master', f'data_prep_master__{report_id}.json'),
        ('data_prep_master', f'qlib_adapter_config__{report_id}.json'),
        ('handoff', f'handoff_to_step4__{report_id}.json'),
    ]:
        path = root / 'objects' / rel[0] / rel[1]
        payload = json.loads(path.read_text())
        payload.pop('data_api_resolution', None)
        write_json(path, payload)

    check = validate_step3(root, report_id)
    assert check.returncode != 0
    assert 'data_api_resolution is required' in check.stderr
