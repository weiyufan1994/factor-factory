import hashlib
import json

import pytest

from scripts.build_factorforge_retrieval_index import active_workspace_exports, CorpusBuildError


def seed(tmp_path):
    original = tmp_path / 'knowledge_record__A.json'
    payload = {'report_id': 'A', 'factor_id': 'A', 'decision': 'reject',
               'export_version': 'factorforge_workspace_experience_export_v1',
               'advisory_only': True, 'same_factor_not_generalized': True,
               'canonical_promotion_allowed': False,
               'export_status': 'LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL',
               'expected_failure_regimes': ['unsupported template']}
    original.write_text(json.dumps(payload))
    revised = {**payload, 'expected_failure_regimes': [],
               'research_variant': 'separate_extension', 'paper_replication_status': 'not_reproduced',
               'export_revision': {'supersedes_file': original.name,
                                   'supersedes_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
                                   'changed_fields': ['expected_failure_regimes', 'research_variant', 'paper_replication_status'],
                                   'reason': 'Remove unsupported interpretation; retain original evidence.'}}
    return original, revised


def test_correction_selects_revision_and_preserves_old_bytes(tmp_path):
    original, revised = seed(tmp_path)
    before = original.read_bytes()
    correction = tmp_path / 'knowledge_record__A__correction.json'
    correction.write_text(json.dumps(revised))
    selected = active_workspace_exports(tmp_path)
    assert [path for path, _ in selected] == [correction]
    assert selected[0][1]['expected_failure_regimes'] == []
    assert original.read_bytes() == before


@pytest.mark.parametrize('change', ['missing', 'changed_parent', 'identity', 'authority', 'two_children', 'undeclared_edit'])
def test_bad_correction_never_silently_selects_latest(tmp_path, change):
    original, revised = seed(tmp_path)
    if change == 'missing':
        revised['export_revision']['supersedes_file'] = 'missing.json'
    elif change == 'changed_parent':
        original.write_text(original.read_text() + ' ')
    elif change == 'identity':
        revised['factor_id'] = 'different_factor'
    elif change == 'authority':
        revised['canonical_promotion_allowed'] = True
    elif change == 'two_children':
        (tmp_path / 'knowledge_record__A__other.json').write_text(json.dumps(revised))
    elif change == 'undeclared_edit':
        revised['failure_patterns'] = ['unlisted modification']
    (tmp_path / 'knowledge_record__A__correction.json').write_text(json.dumps(revised))
    with pytest.raises(CorpusBuildError):
        active_workspace_exports(tmp_path)
