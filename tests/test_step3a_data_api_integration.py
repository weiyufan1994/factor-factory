from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def write_catalog(path: Path, datasets: dict) -> None:
    write_json(path, {'catalog_version': 'factorforge_data_catalog_v1', 'datasets': datasets})


def catalog_dataset(path: Path, columns: list[str], **overrides) -> dict:
    payload = {
        'uri': str(path),
        'format': 'parquet',
        'storage': 'local',
        'columns': columns,
        'date_column': 'trade_date',
        'symbol_column': 'ts_code',
    }
    payload.update(overrides)
    return payload


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
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {
            'clean_daily_bar': catalog_dataset(
                data_path,
                ['ts_code', 'trade_date', 'close', 'vol', 'amount'],
                qlib_field_map={'$volume': 'vol', '$close': 'close', '$amount': 'amount'},
            )
        },
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'ready'
    assert prep['local_input_paths']['snapshot_source'] == 'factor_factory.data_api'
    assert prep['data_api_resolution']['datasets']['clean_daily_bar']['resolved_fields']['volume'] == 'vol'
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
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {'clean_daily_bar': catalog_dataset(data_path, ['ts_code', 'trade_date', 'high'])},
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'blocked'
    assert 'volume' in prep['data_api_resolution']['missing_fields']['clean_daily_bar']
    requirement_path = root / 'objects' / 'data_requirements' / prep['data_requirement_ref']
    requirement = json.loads(requirement_path.read_text())
    assert requirement['type'] == 'factorforge_data_requirement'
    assert requirement['dataset_id'] == 'clean_daily_bar'
    assert requirement['resolution']['status'] == 'blocked'
    assert requirement['data_api_result_metadata']['clean_daily_bar']['blocked_reason'].startswith('missing_fields')
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
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {'other_dataset': catalog_dataset(data_path, ['ts_code', 'trade_date', 'close'])},
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'blocked'
    assert prep['data_api_resolution']['missing_datasets'] == ['clean_daily_bar']
    requirement_path = root / 'objects' / 'data_requirements' / prep['data_requirement_ref']
    requirement = json.loads(requirement_path.read_text())
    assert requirement['resolution']['available_datasets'] == ['other_dataset']
    assert requirement['data_api_result_metadata']['clean_daily_bar']['blocked_reason'] == 'dataset_not_found: clean_daily_bar'
    assert not (root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv').exists()


def test_step3a_market_cap_proxy_ready_comes_from_data_api_result(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_DATA_API_PROXY_READY'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(market_cap)',
        required_inputs=['market_cap'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame(
        [
            {
                'ts_code': '000001.SZ',
                'trade_date': '20260102',
                'total_mv': 100000.0,
                'turnover_rate': 1.2,
                'pe': 10.0,
                'pb': 1.0,
                'ps': 2.0,
            },
        ]
    ).to_parquet(data_path, index=False)
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {
            'clean_daily_bar': catalog_dataset(
                data_path,
                ['ts_code', 'trade_date', 'total_mv', 'turnover_rate', 'pe', 'pb', 'ps'],
                proxy_fields={'market_cap': {'field': 'total_mv', 'rationale': 'catalog_configured_proxy'}},
            )
        },
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'proxy_ready'
    assert prep['data_api_resolution']['status'] == 'proxy_ready'
    assert prep['data_api_resolution']['datasets']['clean_daily_bar']['resolved_fields']['market_cap'] == 'total_mv'
    assert prep['data_api_resolution']['datasets']['clean_daily_bar']['proxy_rules'][0]['resolved'] == 'total_mv'
    daily_path = root.parent / prep['local_input_paths']['daily_df_csv']
    assert 'total_mv' in pd.read_csv(daily_path).columns


def test_step3a_blocks_daily_only_when_catalog_absent_even_if_shared_clean_exists(tmp_path):
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
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'catalog_missing'
    assert prep['data_api_resolution']['catalog_exists'] is False
    assert prep['local_input_paths']['snapshot_source'] == 'data_api_requirement'
    assert prep['data_requirement_ref']
    assert not (root / 'runs' / report_id / 'step3a_local_inputs' / f'daily_input__{report_id}.csv').exists()
    handoff = json.loads((root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json').read_text())
    assert handoff['step3a_ready'] is False


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
                'market_cap': 100000.0,
                'pe': 10.0,
                'pb': 1.0,
                'ps': 2.0,
            },
        ]
    ).to_parquet(data_path, index=False)
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {
            'clean_daily_bar': catalog_dataset(
                data_path,
                ['ts_code', 'trade_date', 'close', 'vol', 'amount', 'turnover_rate', 'market_cap', 'pe', 'pb', 'ps'],
            )
        },
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'blocked'
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
                'market_cap': 100000.0,
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
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {
            'clean_daily_bar': catalog_dataset(
                daily_path,
                ['ts_code', 'trade_date', 'close', 'vol', 'amount', 'turnover_rate', 'market_cap', 'pe', 'pb', 'ps'],
            ),
            'minute_bar': catalog_dataset(
                minute_path,
                ['ts_code', 'trade_date', 'trade_time', 'bar_time', 'minute_index', 'open', 'high', 'low', 'close', 'vol', 'amount'],
            ),
        },
    )

    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr
    check = validate_step3(root, report_id)
    assert check.returncode == 0, check.stderr

    prep = json.loads((root / 'objects' / 'data_prep_master' / f'data_prep_master__{report_id}.json').read_text())
    assert prep['feasibility'] == 'ready'
    assert prep['data_api_resolution']['status'] == 'ready'
    assert prep['data_api_resolution']['datasets']['minute_bar']['query']['dataset'] == 'minute_bar'
    assert prep['local_input_paths']['snapshot_source'] == 'factor_factory.data_api'
    assert (root.parent / prep['local_input_paths']['daily_df_csv']).exists()
    assert (root.parent / prep['local_input_paths']['minute_df_csv']).exists()


def test_step3a_cpv_blocks_when_catalog_absent_without_synthetic_fallback(tmp_path):
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
    assert prep['feasibility'] == 'blocked'
    assert prep['data_api_resolution']['status'] == 'catalog_missing'
    assert prep['data_api_resolution']['catalog_exists'] is False
    assert prep['data_requirement_ref']
    assert prep['local_input_paths']['snapshot_source'] == 'data_api_requirement'
    snapshot_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    assert not (snapshot_dir / f'daily_input__{report_id}.csv').exists()
    assert not (snapshot_dir / f'minute_input__{report_id}.csv').exists()
    handoff = json.loads((root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json').read_text())
    assert handoff['step3a_ready'] is False


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
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {'clean_daily_bar': catalog_dataset(data_path, ['ts_code', 'trade_date', 'close'])},
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


def test_validate_step3_rejects_resolution_mismatch(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_RESOLUTION_MISMATCH'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(close)',
        required_inputs=['close'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0}]).to_parquet(data_path, index=False)
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {'clean_daily_bar': catalog_dataset(data_path, ['ts_code', 'trade_date', 'close'])},
    )
    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr

    qcfg_path = root / 'objects' / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    qcfg = json.loads(qcfg_path.read_text())
    qcfg['data_api_resolution']['status'] = 'blocked'
    write_json(qcfg_path, qcfg)

    check = validate_step3(root, report_id)
    assert check.returncode != 0
    assert 'qlib_adapter_config.data_api_resolution must match data_prep_master' in check.stderr


def test_validate_step3_rejects_blocked_with_executable_snapshot(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_BLOCKED_WITH_SNAPSHOT'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(industry_code)',
        required_inputs=['industry_code'],
    )
    data_path = tmp_path / 'daily.parquet'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0}]).to_parquet(data_path, index=False)
    write_catalog(
        root / 'data' / 'catalog' / 'data_catalog.json',
        {'clean_daily_bar': catalog_dataset(data_path, ['ts_code', 'trade_date', 'close'])},
    )
    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr

    snapshot_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    fake_snapshot = snapshot_dir / f'daily_input__{report_id}.csv'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260102', 'industry_code': '801010'}]).to_csv(fake_snapshot, index=False)
    fake_rel = fake_snapshot.relative_to(root.parent).as_posix()
    for folder, filename in [
        ('data_prep_master', f'data_prep_master__{report_id}.json'),
        ('data_prep_master', f'qlib_adapter_config__{report_id}.json'),
        ('handoff', f'handoff_to_step4__{report_id}.json'),
    ]:
        artifact_path = root / 'objects' / folder / filename
        payload = json.loads(artifact_path.read_text())
        payload.setdefault('local_input_paths', {})['daily_df_csv'] = fake_rel
        write_json(artifact_path, payload)

    check = validate_step3(root, report_id)
    assert check.returncode != 0
    assert 'blocked Data API result must not write executable daily snapshot' in check.stderr


def test_validate_step3_rejects_catalog_missing_with_executable_snapshot(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_CATALOG_MISSING_WITH_SNAPSHOT'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(close)',
        required_inputs=['close'],
    )
    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr

    snapshot_dir = root / 'runs' / report_id / 'step3a_local_inputs'
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    fake_snapshot = snapshot_dir / f'daily_input__{report_id}.csv'
    pd.DataFrame([{'ts_code': '000001.SZ', 'trade_date': '20260102', 'close': 10.0}]).to_csv(fake_snapshot, index=False)
    fake_rel = fake_snapshot.relative_to(root.parent).as_posix()
    for folder, filename in [
        ('data_prep_master', f'data_prep_master__{report_id}.json'),
        ('data_prep_master', f'qlib_adapter_config__{report_id}.json'),
        ('handoff', f'handoff_to_step4__{report_id}.json'),
    ]:
        artifact_path = root / 'objects' / folder / filename
        payload = json.loads(artifact_path.read_text())
        payload.setdefault('local_input_paths', {})['daily_df_csv'] = fake_rel
        write_json(artifact_path, payload)

    check = validate_step3(root, report_id)
    assert check.returncode != 0
    assert 'blocked Data API result must not write executable daily snapshot' in check.stderr


def test_validate_step3_rejects_catalog_missing_with_step3a_ready_true(tmp_path):
    root = tmp_path / 'factorforge'
    report_id = 'STEP3A_CATALOG_MISSING_READY_TRUE'
    seed_step3_inputs(
        root,
        report_id,
        formula_text='rank(close)',
        required_inputs=['close'],
    )
    proc = run_step3(root, report_id)
    assert proc.returncode == 0, proc.stderr

    handoff_path = root / 'objects' / 'handoff' / f'handoff_to_step4__{report_id}.json'
    handoff = json.loads(handoff_path.read_text())
    handoff['step3a_ready'] = True
    write_json(handoff_path, handoff)

    check = validate_step3(root, report_id)
    assert check.returncode != 0
    assert 'handoff_to_step4.step3a_ready mismatch' in check.stderr
