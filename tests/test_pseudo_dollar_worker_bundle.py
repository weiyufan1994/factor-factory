from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = REPO_ROOT / 'scripts' / name
    spec = importlib.util.spec_from_file_location(name.removesuffix('.py'), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pseudo_dollar_worker_bundle_is_plan_only_and_labeled_pseudo(tmp_path: Path):
    builder = _load_script('build_pseudo_dollar_worker_bundle.py')
    validator = _load_script('validate_pseudo_dollar_worker_bundle.py')
    bundle_path = tmp_path / 'bundle.json'
    validation_path = tmp_path / 'validation.json'

    assert builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/home/ubuntu/.openclaw/workspace/factorforge-data-api',
        '--cache-root',
        '/home/ubuntu/factorforge_data_api_cache',
        '--s3-root',
        's3://yufan-data-lake/factorforge/datamart/intraday_pseudo_dollar_bar_v1/is',
        '--local-input-dir',
        '/home/ubuntu/factorforge_data_api_cache/proofs/intraday_pseudo_dollar_bar_v1/input',
        '--artifact-dir',
        '/home/ubuntu/factorforge_data_api_cache/proofs/intraday_pseudo_dollar_bar_v1',
        '--trade-date',
        '20240110',
        '--output-path',
        str(bundle_path),
    ]) == 0
    assert validator.main(['--bundle-path', str(bundle_path), '--output-path', str(validation_path)]) == 0

    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    command_text = '\n'.join(payload['worker_commands'])
    assert validation['verdict'] == 'ACCEPT'
    assert payload['dataset_id'] == 'intraday_pseudo_dollar_bar_v1'
    assert payload['true_tick_dollar_bar'] is False
    assert payload['source_is_pseudo_from_1m_bar'] is True
    assert payload['not_full_window_production_plan'] is True
    assert payload['full_window_contract']['unique_key'] == ['ts_code', 'trade_date', 'bucket_id']
    assert 'scripts/probe_clickhouse_intraday_pseudo_dollar_bar.py' in command_text
    assert 'aws s3 cp' in command_text
    assert 'not true tick dollar bar' in command_text
    assert 'aws ssm send-command' not in command_text
    assert payload['safety']['runs_worker_command'] is False


def test_pseudo_dollar_worker_bundle_validator_blocks_remote_dispatch(tmp_path: Path):
    builder = _load_script('build_pseudo_dollar_worker_bundle.py')
    validator = _load_script('validate_pseudo_dollar_worker_bundle.py')
    bundle_path = tmp_path / 'bundle.json'
    validation_path = tmp_path / 'validation.json'
    assert builder.main([
        '--instance-id',
        'i-02cc0b6e93856fbb4',
        '--repo',
        '/repo',
        '--cache-root',
        '/cache',
        '--s3-root',
        's3://bucket/path',
        '--local-input-dir',
        '/cache/input',
        '--artifact-dir',
        '/cache/proofs',
        '--output-path',
        str(bundle_path),
    ]) == 0
    payload = json.loads(bundle_path.read_text(encoding='utf-8'))
    payload['worker_commands'].append('aws ssm send-command --document-name AWS-RunShellScript')
    payload['safety']['runs_worker_command'] = True
    bundle_path.write_text(json.dumps(payload), encoding='utf-8')

    exit_code = validator.main(['--bundle-path', str(bundle_path), '--output-path', str(validation_path)])

    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert validation['verdict'] == 'BLOCK'
    assert any('aws ssm send-command' in issue for issue in validation['issues'])
