from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_report_module():
    path = REPO_ROOT / 'scripts' / 'build_data_api_status_report.py'
    spec = importlib.util.spec_from_file_location('build_data_api_status_report', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_data_api_status_report_accepts_default_registries(tmp_path: Path):
    report_module = _load_report_module()
    output_path = tmp_path / 'status.json'

    exit_code = report_module.main(['--output', str(output_path)])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['registries']['feature_precompute']['verdict'] == 'ACCEPT'
    assert payload['registries']['feature_family']['verdict'] == 'ACCEPT'
    assert payload['registries']['data_team_ops']['verdict'] == 'ACCEPT'
    assert payload['registries']['crosslinks']['verdict'] == 'ACCEPT'
    assert any(item['dataset_id'] == 'daily_technical_state_v1' for item in payload['recommended_dataset_actions'])
    assert any(item['family_id'] == 'intraday_distribution_moments' for item in payload['recommended_feature_family_actions'])
    assert any(item['task_id'] == 'active_catalog_publication_gate' for item in payload['research_blocking_ops'])
    assert payload['safety']['starts_worker'] is False
    assert payload['safety']['writes_active_catalog'] is False


def test_data_api_status_report_can_render_markdown(tmp_path: Path):
    report_module = _load_report_module()
    output_path = tmp_path / 'status.json'
    markdown_path = tmp_path / 'status.md'

    exit_code = report_module.main([
        '--output',
        str(output_path),
        '--markdown-output',
        str(markdown_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    markdown = markdown_path.read_text(encoding='utf-8')
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert '# Data API Status Report' in markdown
    assert '## Recommended Dataset Actions' in markdown
    assert '| crosslinks | `ACCEPT` |' in markdown
    assert '`daily_technical_state_v1`' in markdown
    assert '`intraday_distribution_moments`' in markdown
    assert 'starts_worker: `False`' in markdown


def test_data_api_status_report_blocks_invalid_registry(tmp_path: Path):
    report_module = _load_report_module()
    bad_precompute = tmp_path / 'bad_precompute.json'
    bad_precompute.write_text(json.dumps({'schema_version': 'wrong', 'datasets': []}), encoding='utf-8')
    output_path = tmp_path / 'status.json'

    exit_code = report_module.main([
        '--feature-precompute-registry',
        str(bad_precompute),
        '--output',
        str(output_path),
    ])

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['registries']['feature_precompute']['verdict'] == 'BLOCK'
    assert payload['registries']['feature_precompute']['issues']
