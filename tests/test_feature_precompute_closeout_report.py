from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from factor_factory.data_api.data_team_ops_registry import read_data_team_ops_registry
from factor_factory.data_api.feature_family_registry import read_feature_family_registry
from factor_factory.data_api.feature_precompute_closeout import build_feature_precompute_closeout_report
from factor_factory.data_api.feature_precompute_registry import read_feature_registry


REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURE_PRECOMPUTE = REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json'
FEATURE_FAMILY = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'
DATA_TEAM_OPS = REPO_ROOT / 'docs' / 'operations' / 'data-team-daily-ops-checklist.v1.json'


def _load_script_module():
    path = REPO_ROOT / 'scripts' / 'build_feature_precompute_closeout_report.py'
    spec = importlib.util.spec_from_file_location('build_feature_precompute_closeout_report', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_feature_precompute_closeout_report_covers_goal_scope():
    report = build_feature_precompute_closeout_report(
        feature_precompute=read_feature_registry(FEATURE_PRECOMPUTE),
        feature_family=read_feature_family_registry(FEATURE_FAMILY),
        data_team_ops=read_data_team_ops_registry(DATA_TEAM_OPS),
        repo_root=REPO_ROOT,
    )

    assert report['schema_version'] == 'feature_precompute_closeout_report_v1'
    assert report['verdict'] == 'ACCEPT'
    assert report['objective_coverage']['time_series_precompute_menu']
    assert report['objective_coverage']['alpha360_position']
    assert report['objective_coverage']['private_fund_data_team_daily_work']
    assert report['alpha360_assessment']['decision'] == 'bounded_proof_then_model_specific'
    assert report['alpha360_assessment']['recommended_dataset'] == 'daily_alpha360_lite_v1'
    assert report['data_team_daily_work']['not_just_cleaning'] is True
    assert report['data_team_daily_work']['research_blocking_task_count'] >= 4
    assert report['remaining_blockers']['not_started'] == []
    assert report['safety']['starts_worker'] is False
    assert report['safety']['writes_active_catalog'] is False


def test_feature_precompute_closeout_cli_writes_json_and_markdown(tmp_path: Path):
    module = _load_script_module()
    output = tmp_path / 'closeout.json'
    markdown = tmp_path / 'closeout.md'

    exit_code = module.main(['--output', str(output), '--markdown-output', str(markdown)])

    payload = json.loads(output.read_text(encoding='utf-8'))
    md = markdown.read_text(encoding='utf-8')
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert '# Feature Precompute Closeout Report' in md
    assert 'Alpha360 Position' in md
    assert 'Data Team Daily Work' in md
    assert 'Not started: ``' in md


def test_feature_precompute_closeout_blocks_when_dataset_not_started(tmp_path: Path):
    precompute = read_feature_registry(FEATURE_PRECOMPUTE)
    precompute['datasets'][0] = dict(precompute['datasets'][0])
    precompute['datasets'][0]['status'] = 'planned'
    precompute['datasets'][0]['production_readiness'] = 'not_started'

    report = build_feature_precompute_closeout_report(
        feature_precompute=precompute,
        feature_family=read_feature_family_registry(FEATURE_FAMILY),
        data_team_ops=read_data_team_ops_registry(DATA_TEAM_OPS),
        repo_root=REPO_ROOT,
    )

    assert report['verdict'] == 'BLOCK'
    assert 'daily_technical_state_v1' in report['remaining_blockers']['not_started']
