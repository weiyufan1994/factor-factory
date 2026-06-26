from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_handoff_module():
    path = REPO_ROOT / 'scripts' / 'build_data_api_handoff_package.py'
    spec = importlib.util.spec_from_file_location('build_data_api_handoff_package', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_data_api_handoff_package_accepts_default_registries(tmp_path: Path):
    handoff_module = _load_handoff_module()
    output_dir = tmp_path / 'handoff'

    exit_code = handoff_module.main(['--output-dir', str(output_dir)])

    summary = json.loads((output_dir / 'handoff_summary.json').read_text(encoding='utf-8'))
    status = json.loads((output_dir / 'data_api_status_report.json').read_text(encoding='utf-8'))
    readme = (output_dir / 'README.md').read_text(encoding='utf-8')
    assert exit_code == 0
    assert summary['verdict'] == 'ACCEPT'
    assert status['verdict'] == 'ACCEPT'
    assert (output_dir / 'data_api_status_report.md').exists()
    assert (output_dir / 'feature_precompute_registry.validation.json').exists()
    assert (output_dir / 'feature_family_registry.validation.json').exists()
    assert (output_dir / 'data_team_ops_registry.validation.json').exists()
    assert (output_dir / 'registry_crosslinks.validation.json').exists()
    assert (output_dir / 'feature_precompute_decision_report.json').exists()
    assert (output_dir / 'feature_precompute_decision_report.md').exists()
    assert (output_dir / 'datamart_readiness_report.json').exists()
    assert (output_dir / 'datamart_readiness_report.md').exists()
    assert '# Data API Handoff Package' in readme
    assert 'not an active production catalog' in readme
    assert 'feature_precompute_decision_report.json' in readme
    assert 'datamart_readiness_report.json' in readme
    assert summary['paths']['datamart_readiness_json'].endswith('datamart_readiness_report.json')
    assert any(item['dataset_id'] == 'daily_technical_state_v1' for item in summary['recommended_p0_datasets'])
    assert any(item['dataset_id'] == 'intraday_flow_distribution_moments_v1' for item in summary['recommended_p0_datasets'])
    assert summary['safety']['starts_worker'] is False
    assert summary['safety']['writes_active_catalog'] is False
    assert summary['safety']['writes_factorforge_artifacts'] is False


def test_data_api_handoff_package_blocks_invalid_precompute_registry(tmp_path: Path):
    handoff_module = _load_handoff_module()
    bad_precompute = tmp_path / 'bad_precompute.json'
    bad_precompute.write_text(json.dumps({'schema_version': 'wrong', 'datasets': []}), encoding='utf-8')
    output_dir = tmp_path / 'handoff'

    exit_code = handoff_module.main([
        '--feature-precompute-registry',
        str(bad_precompute),
        '--output-dir',
        str(output_dir),
    ])

    summary = json.loads((output_dir / 'handoff_summary.json').read_text(encoding='utf-8'))
    validation = json.loads((output_dir / 'feature_precompute_registry.validation.json').read_text(encoding='utf-8'))
    status = json.loads((output_dir / 'data_api_status_report.json').read_text(encoding='utf-8'))
    decision = json.loads((output_dir / 'feature_precompute_decision_report.json').read_text(encoding='utf-8'))
    assert exit_code == 1
    assert summary['verdict'] == 'BLOCK'
    assert status['verdict'] == 'BLOCK'
    assert decision['verdict'] == 'ACCEPT'
    assert validation['verdict'] == 'BLOCK'
    assert validation['issues']
    assert summary['safety']['starts_worker'] is False
    assert summary['safety']['production_loop_side_effect'] is False
