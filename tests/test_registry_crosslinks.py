from __future__ import annotations

import json
import importlib.util
from pathlib import Path

from factor_factory.data_api.registry_crosslinks import (
    registry_crosslink_summary,
    validate_registry_crosslinks,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_registries() -> tuple[dict, dict, dict]:
    precompute = json.loads((REPO_ROOT / 'docs' / 'operations' / 'feature-precompute-registry.v1.json').read_text(encoding='utf-8'))
    family = json.loads((REPO_ROOT / 'docs' / 'operations' / 'feature-family-registry.v1.json').read_text(encoding='utf-8'))
    ops = json.loads((REPO_ROOT / 'docs' / 'operations' / 'data-team-daily-ops-checklist.v1.json').read_text(encoding='utf-8'))
    return precompute, family, ops


def _load_cli_module():
    path = REPO_ROOT / 'scripts' / 'validate_registry_crosslinks.py'
    spec = importlib.util.spec_from_file_location('validate_registry_crosslinks', path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_crosslinks_accept_current_contracts():
    precompute, family, ops = _load_registries()

    issues = validate_registry_crosslinks(
        feature_precompute=precompute,
        feature_family=family,
        data_team_ops=ops,
    )

    assert issues == []
    summary = registry_crosslink_summary(
        feature_precompute=precompute,
        feature_family=family,
        data_team_ops=ops,
    )
    assert summary['dataset_count'] >= 7
    assert summary['family_links']['daily_technical_state'] == 'daily_technical_state_v1'


def test_registry_crosslinks_block_missing_recommended_dataset():
    precompute, family, ops = _load_registries()
    family['feature_families'][0]['recommended_dataset'] = 'missing_dataset_v1'

    fields = {
        issue.field
        for issue in validate_registry_crosslinks(
            feature_precompute=precompute,
            feature_family=family,
            data_team_ops=ops,
        )
    }

    assert 'feature_families[0].recommended_dataset' in fields


def test_registry_crosslinks_block_unreferenced_p0_dataset():
    precompute, family, ops = _load_registries()
    family['feature_families'] = [
        entry for entry in family['feature_families']
        if entry.get('recommended_dataset') != 'daily_technical_state_v1'
    ]

    fields = {
        issue.field
        for issue in validate_registry_crosslinks(
            feature_precompute=precompute,
            feature_family=family,
            data_team_ops=ops,
        )
    }

    assert 'datasets[0].dataset_id' in fields


def test_registry_crosslinks_block_unknown_ops_dataset():
    precompute, family, ops = _load_registries()
    ops['tasks'][0]['datasets'].append('unknown_dataset_v1')

    fields = {
        issue.field
        for issue in validate_registry_crosslinks(
            feature_precompute=precompute,
            feature_family=family,
            data_team_ops=ops,
        )
    }

    assert 'tasks[0].datasets[4]' in fields


def test_registry_crosslink_cli_accepts_default_contracts(tmp_path: Path):
    cli = _load_cli_module()
    output_path = tmp_path / 'crosslinks.json'
    import sys

    old_argv = sys.argv
    sys.argv = ['validate_registry_crosslinks.py', '--output', str(output_path)]
    try:
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        sys.argv = old_argv

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['verdict'] == 'ACCEPT'
    assert payload['summary']['family_link_count'] >= 8


def test_registry_crosslink_cli_blocks_invalid_contract(tmp_path: Path):
    cli = _load_cli_module()
    precompute, family, _ops = _load_registries()
    family['feature_families'][0]['recommended_dataset'] = 'missing_dataset_v1'
    family_path = tmp_path / 'family.json'
    output_path = tmp_path / 'crosslinks.json'
    family_path.write_text(json.dumps(family), encoding='utf-8')
    precompute_path = tmp_path / 'precompute.json'
    precompute_path.write_text(json.dumps(precompute), encoding='utf-8')

    import sys

    old_argv = sys.argv
    sys.argv = [
        'validate_registry_crosslinks.py',
        '--feature-family-registry',
        str(family_path),
        '--feature-precompute-registry',
        str(precompute_path),
        '--output',
        str(output_path),
    ]
    try:
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 2
    finally:
        sys.argv = old_argv

    payload = json.loads(output_path.read_text(encoding='utf-8'))
    assert payload['verdict'] == 'BLOCK'
    assert payload['issues']
