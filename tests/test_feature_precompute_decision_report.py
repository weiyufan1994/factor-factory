from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from factor_factory.data_api.feature_family_registry import read_feature_family_registry
from factor_factory.data_api.feature_precompute_decision import (
    build_feature_precompute_decision_report,
    recommended_precompute_sequence,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json'


def _load_script_module():
    path = REPO_ROOT / 'scripts' / 'build_feature_precompute_decision_report.py'
    spec = importlib.util.spec_from_file_location('build_feature_precompute_decision_report', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_feature_precompute_decision_report_classifies_core_families():
    registry = read_feature_family_registry(REGISTRY_PATH)

    report = build_feature_precompute_decision_report(registry)
    by_family = {entry['family_id']: entry for entry in report['decisions']}

    assert report['schema_version'] == 'feature_precompute_decision_report_v1'
    assert by_family['daily_technical_state']['decision'] == 'productionize_first'
    assert by_family['daily_alpha360_lag_tensor']['decision'] == 'bounded_proof_then_model_specific'
    assert 'alpha360_temporal_context' in by_family['daily_alpha360_lag_tensor']['reason_tags']
    assert by_family['intraday_distribution_moments']['decision'] == 'productionize_after_source_ready'
    assert 'raw_minute_scan_avoidance' in by_family['intraday_distribution_moments']['reason_tags']
    assert by_family['cross_sectional_post_transforms']['decision'] == 'keep_on_research_side'


def test_recommended_precompute_sequence_prioritizes_low_cost_broad_reuse():
    registry = read_feature_family_registry(REGISTRY_PATH)
    report = build_feature_precompute_decision_report(registry)

    sequence = recommended_precompute_sequence(report)

    assert sequence[0]['family_id'] == 'daily_technical_state'
    assert any(item['family_id'] == 'intraday_distribution_moments' for item in sequence[1:4])


def test_feature_precompute_decision_report_cli_writes_json_and_markdown(tmp_path: Path):
    module = _load_script_module()
    output = tmp_path / 'decision.json'
    markdown = tmp_path / 'decision.md'

    exit_code = module.main(['--output', str(output), '--markdown-output', str(markdown)])

    payload = json.loads(output.read_text(encoding='utf-8'))
    md = markdown.read_text(encoding='utf-8')
    assert exit_code == 0
    assert payload['verdict'] == 'ACCEPT'
    assert payload['by_decision']['productionize_first'] >= 1
    assert '# Feature Precompute Decision Report' in md
    assert 'Alpha360-style daily lag tensors' in md


def test_feature_precompute_decision_report_cli_blocks_invalid_registry(tmp_path: Path):
    module = _load_script_module()
    registry = tmp_path / 'bad_family.json'
    registry.write_text(json.dumps({'schema_version': 'wrong', 'feature_families': []}), encoding='utf-8')
    output = tmp_path / 'decision.json'

    exit_code = module.main(['--feature-family-registry', str(registry), '--output', str(output)])

    payload = json.loads(output.read_text(encoding='utf-8'))
    assert exit_code == 1
    assert payload['verdict'] == 'BLOCK'
    assert payload['issues']
