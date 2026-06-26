from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from factor_factory.data_api.datamart_readiness import build_datamart_readiness_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    path = REPO_ROOT / 'scripts' / 'build_datamart_readiness_report.py'
    spec = importlib.util.spec_from_file_location('build_datamart_readiness_report', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registry(tmp_path: Path) -> dict:
    builder = tmp_path / 'builder.py'
    validator = tmp_path / 'validator.py'
    worker_bundle = tmp_path / 'bundle.json'
    worker_validation = tmp_path / 'bundle.validation.json'
    builder.write_text('pass\n', encoding='utf-8')
    validator.write_text('pass\n', encoding='utf-8')
    worker_bundle.write_text(json.dumps({'verdict': 'ACCEPT'}), encoding='utf-8')
    worker_validation.write_text(json.dumps({'verdict': 'ACCEPT'}), encoding='utf-8')
    return {
        'schema_version': 'feature_precompute_registry_v1',
        'datasets': [
            {
                'dataset_id': 'daily_technical_state_v1',
                'frequency': 'daily',
                'priority': 'P0',
                'status': 'production_candidate',
                'production_readiness': 'worker_plan_accept',
                'feature_family': 'daily_technical_state',
                'full_window_strategy': 'worker_partitioned_resume',
                'information_set_legality': 'current and prior daily bars only',
                'notes': 'test',
                'recommended_first_production': True,
                'projection_required': True,
                'source_datasets': ['clean_daily_bar'],
                'unique_key': ['ts_code', 'trade_date'],
                'partition_columns': ['trade_date'],
                'registration_blockers': ['true worker full-window build'],
                'builder_script': str(builder),
                'validator_script': str(validator),
                'proof_paths': {
                    'worker_resume_bundle': str(worker_bundle),
                    'worker_resume_bundle_validation': str(worker_validation),
                },
            },
            {
                'dataset_id': 'intraday_cutoff_state_pack_v1',
                'frequency': 'intraday_cutoff',
                'priority': 'P1',
                'status': 'planned',
                'production_readiness': 'not_started',
                'feature_family': 'intraday_cutoff_state',
                'full_window_strategy': 'after_source_ready',
                'information_set_legality': 'trade_time <= cutoff_time',
                'notes': 'test',
                'recommended_first_production': False,
                'projection_required': True,
                'source_datasets': ['minute_bar'],
                'unique_key': ['ts_code', 'trade_date', 'cutoff_time'],
                'partition_columns': ['trade_date'],
                'registration_blockers': ['builder implementation'],
                'builder_script': '',
                'validator_script': '',
                'proof_paths': {},
            },
        ],
    }


def test_datamart_readiness_report_classifies_worker_plan_and_not_started(tmp_path: Path):
    report = build_datamart_readiness_report(_registry(tmp_path), repo_root=REPO_ROOT)
    by_dataset = {item['dataset_id']: item for item in report['datasets']}

    assert report['schema_version'] == 'datamart_readiness_report_v1'
    assert report['verdict'] == 'ACCEPT'
    assert by_dataset['daily_technical_state_v1']['stage'] == 'worker_plan_ready'
    assert by_dataset['daily_technical_state_v1']['missing_required_paths'] == []
    assert by_dataset['daily_technical_state_v1']['non_accept_proofs'] == []
    assert by_dataset['intraday_cutoff_state_pack_v1']['stage'] == 'not_started'
    assert report['safety']['starts_worker'] is False


def test_datamart_readiness_report_marks_missing_proof_incomplete(tmp_path: Path):
    registry = _registry(tmp_path)
    Path(registry['datasets'][0]['proof_paths']['worker_resume_bundle_validation']).unlink()

    report = build_datamart_readiness_report(registry, repo_root=REPO_ROOT)
    item = next(row for row in report['datasets'] if row['dataset_id'] == 'daily_technical_state_v1')

    assert item['stage'] == 'blocked_or_incomplete'
    assert 'proof_paths.worker_resume_bundle_validation' in item['missing_required_paths']
    assert item['next_action'] == 'generate or restore missing proof artifacts'


def test_datamart_readiness_report_marks_read_only_builder_available(tmp_path: Path):
    registry = _registry(tmp_path)
    builder = tmp_path / 'cutoff_builder.py'
    validator = tmp_path / 'cutoff_validator.py'
    builder.write_text('pass\n', encoding='utf-8')
    validator.write_text('pass\n', encoding='utf-8')
    registry['datasets'][-1] = {
        'dataset_id': 'intraday_cutoff_state_pack_v1',
        'frequency': 'intraday_cutoff',
        'priority': 'P1',
        'status': 'read_only_builder_available',
        'production_readiness': 'not_started',
        'feature_family': 'intraday_cutoff_state',
        'full_window_strategy': 'after_source_ready',
        'information_set_legality': 'trade_time <= cutoff_time',
        'notes': 'test',
        'recommended_first_production': False,
        'projection_required': True,
        'source_datasets': ['minute_bar'],
        'unique_key': ['ts_code', 'trade_date', 'cutoff_time'],
        'partition_columns': ['trade_date'],
        'registration_blockers': ['bounded proof'],
        'builder_script': str(builder),
        'validator_script': str(validator),
        'proof_paths': {},
    }

    report = build_datamart_readiness_report(registry, repo_root=REPO_ROOT)
    item = next(row for row in report['datasets'] if row['dataset_id'] == 'intraday_cutoff_state_pack_v1')

    assert item['stage'] == 'builder_available'
    assert item['next_action'] == 'run bounded real-data proof before worker planning'


def test_datamart_readiness_report_keeps_exploratory_worker_plan_out_of_full_window(tmp_path: Path):
    registry = _registry(tmp_path)
    registry['datasets'][0]['dataset_id'] = 'intraday_pseudo_dollar_bar_v1'
    registry['datasets'][0]['status'] = 'exploratory'
    registry['datasets'][0]['feature_family'] = 'intraday_pseudo_dollar_bar'
    registry['datasets'][0]['frequency'] = 'event_bar'
    registry['datasets'][0]['priority'] = 'P2'
    registry['datasets'][0]['recommended_first_production'] = False

    report = build_datamart_readiness_report(registry, repo_root=REPO_ROOT)
    item = next(row for row in report['datasets'] if row['dataset_id'] == 'intraday_pseudo_dollar_bar_v1')

    assert item['stage'] == 'worker_plan_ready'
    assert item['next_action'] == (
        'run exploratory true-worker partition probe and cost decision before any full-window production plan'
    )


def test_datamart_readiness_report_cli_accepts_default_registry(tmp_path: Path):
    module = _load_script_module()
    output = tmp_path / 'readiness.json'
    markdown = tmp_path / 'readiness.md'

    exit_code = module.main(['--output', str(output), '--markdown-output', str(markdown)])

    payload = json.loads(output.read_text(encoding='utf-8'))
    md = markdown.read_text(encoding='utf-8')
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['dataset_count'] >= 7
    assert '# Datamart Readiness Report' in md
    assert 'daily_technical_state_v1' in md


def test_datamart_readiness_report_cli_blocks_invalid_registry(tmp_path: Path):
    module = _load_script_module()
    registry = tmp_path / 'bad_registry.json'
    registry.write_text(json.dumps({'schema_version': 'wrong', 'datasets': []}), encoding='utf-8')
    output = tmp_path / 'readiness.json'

    exit_code = module.main([
        '--feature-precompute-registry',
        str(registry),
        '--output',
        str(output),
    ])

    payload = json.loads(output.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['issues']
