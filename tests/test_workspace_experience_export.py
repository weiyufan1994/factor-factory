from __future__ import annotations

import hashlib
import json
import importlib.util
from pathlib import Path
import zipfile

import pytest

from factor_factory.workspace_experience_export import export_workspace_knowledge_record


def _load_script(name: str, relative_path: str):
    path = Path(__file__).parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_is_create_only_and_index_retrieves_from_default_root(tmp_path, monkeypatch):
    import scripts.build_factorforge_retrieval_index as indexer
    from factor_factory.knowledge_reference import build_knowledge_reference_contract
    repo, workspace = tmp_path / 'default', tmp_path / 'A'
    (repo / 'objects').mkdir(parents=True)
    record_path = workspace / 'objects/research_knowledge_base/knowledge_record__A.json'
    record_path.parent.mkdir(parents=True)
    record_path.write_text(json.dumps({
        'report_id': 'A', 'factor_id': 'A_factor', 'decision': 'iterate',
        'factor_family': 'price_volume', 'monetization_model': 'constraint', 'bias_type': 'none',
        'return_source_hypothesis': 'unique event pressure', 'expected_failure_regimes': ['unique illiquidity'],
        'objective_constraint_dependency': 'unique session constraint', 'constraint_sources': [],
        'success_patterns': [], 'failure_patterns': ['unique failure mode'], 'modification_hypotheses': ['candidate only'],
        'reusable_heuristics': ['reviewer heuristic'], 'modification_hypotheses_future_only': True,
        'mathematical_object': 'unique robust projection',
        'reusable_operator': {'observation_mapping': 'unique session operator'},
        'implementation_references': ['objects/handoff/step3b.json'],
        'research_variant': 'EVENT_U_DIRECT_CODE_EXTENSION',
        'paper_replication_status': 'NOT_PF_VV_REPLICATION',
        'learning_and_innovation': {
            'innovative_idea_seeds': [],
            'innovative_idea_seeds_absence_reason': 'No defensible neighboring idea was authored.',
        },
        'research_compatibility_profile': 'factorforge_ordinary_local_is_flexible_v1',
        'next_research_tests_absence_reason': 'The stopped study has no next test.',
        'knowledge_scope': 'same_factor', 'reuse_constraints': ['advisory only'],
        'artifact_identity': {'formula_hash': 'frozen-a'},
    }), encoding='utf-8')
    monkeypatch.setattr(indexer, 'REPO_ROOT', repo)
    first = export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')
    assert first['status'] == 'EXPORTED'
    assert export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')['status'] == 'IDEMPOTENT'
    exported = repo / 'knowledge/因子工厂/workspace_experience_exports/knowledge_record__A.json'
    export_payload = json.loads(exported.read_text(encoding='utf-8'))
    assert export_payload['source_record_relative_ref'] == 'objects/research_knowledge_base/knowledge_record__A.json'
    assert export_payload['source_record_sha256'] == hashlib.sha256(record_path.read_bytes()).hexdigest()
    assert export_payload['research_variant'] == 'EVENT_U_DIRECT_CODE_EXTENSION'
    assert export_payload['paper_replication_status'] == 'NOT_PF_VV_REPLICATION'
    assert export_payload['reusable_heuristics'] == ['reviewer heuristic']
    assert export_payload['modification_hypotheses_future_only'] is True
    assert export_payload['learning_and_innovation']['innovative_idea_seeds'] == []
    assert export_payload['research_compatibility_profile'] == 'factorforge_ordinary_local_is_flexible_v1'
    assert export_payload['next_research_tests_absence_reason'] == 'The stopped study has no next test.'
    indexer.refresh_retrieval_index(repo)
    indexed = json.loads((repo / 'knowledge/retrieval/factorforge_retrieval_index.jsonl').read_text(encoding='utf-8'))
    assert indexed['research_variant'] == 'EVENT_U_DIRECT_CODE_EXTENSION'
    assert indexed['paper_replication_status'] == 'NOT_PF_VV_REPLICATION'
    assert indexed['learning_and_innovation'] == export_payload['learning_and_innovation']
    assert indexed['research_compatibility_profile'] == export_payload['research_compatibility_profile']
    assert indexed['next_research_tests_absence_reason'] == export_payload['next_research_tests_absence_reason']
    # B supplies neither A's path nor its case/factor identifier.
    result = build_knowledge_reference_contract(repo_root=repo, knowledge_root=repo / 'knowledge', query_text='robust projection session operator unique failure', producer='B_step1', top_k=1, retrieval_required=True)
    assert result['retrieved_case_ids'] == ['knowledge_record::A']
    case = result['retrieved_cases'][0]
    assert case['mathematical_object'] == 'unique robust projection'
    assert case['reusable_operator']['observation_mapping'] == 'unique session operator'
    assert case['learning_and_innovation'] == export_payload['learning_and_innovation']
    assert case['research_compatibility_profile'] == export_payload['research_compatibility_profile']
    assert case['next_research_tests_absence_reason'] == export_payload['next_research_tests_absence_reason']
    assert case['modification_hypotheses'][0]['status'] == 'candidate_not_verified'
    assert case['identity']['artifact_identity'] == {'formula_hash': 'frozen-a'}
    assert case['workspace_export_source'] == {
        'record_relative_ref': 'objects/research_knowledge_base/knowledge_record__A.json',
        'record_sha256': hashlib.sha256(record_path.read_bytes()).hexdigest(),
    }


def test_export_conflict_never_overwrites_prior_default_record(tmp_path):
    repo, workspace = tmp_path / 'default', tmp_path / 'A'
    record_path = workspace / 'objects/research_knowledge_base/knowledge_record__A.json'
    record_path.parent.mkdir(parents=True)
    initial = {'report_id': 'A', 'factor_id': 'A', 'failure_patterns': ['first']}
    record_path.write_text(json.dumps(initial), encoding='utf-8')
    export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')
    exported = repo / 'knowledge/因子工厂/workspace_experience_exports/knowledge_record__A.json'
    before = exported.read_bytes()
    record_path.write_text(json.dumps({**initial, 'failure_patterns': ['changed']}), encoding='utf-8')
    with pytest.raises(FileExistsError, match='workspace_experience_export_conflict'):
        export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')
    assert exported.read_bytes() == before


def test_export_preserves_optional_experience_fields(tmp_path):
    repo, workspace = tmp_path / 'repo', tmp_path / 'A'
    source = workspace / 'objects/research_knowledge_base/knowledge_record__A.json'
    source.parent.mkdir(parents=True)
    fields = {
        'report_id': 'A', 'factor_id': 'A',
        'applicability_conditions': ['PIT aligned'], 'regime_detection': 'candidate only',
        'treatment_effect': 'unknown', 'evidence_class': 'source_reviewed',
        'validity_status': 'active_candidate',
    }
    source.write_text(json.dumps(fields), encoding='utf-8')
    export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')
    exported = json.loads((repo / 'knowledge/因子工厂/workspace_experience_exports/knowledge_record__A.json').read_text())
    for key, value in fields.items():
        assert exported[key] == value


def test_withdrawn_export_requires_invalidation_reason(tmp_path):
    repo, workspace = tmp_path / 'repo', tmp_path / 'A'
    source = workspace / 'objects/research_knowledge_base/knowledge_record__A.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'report_id': 'A', 'factor_id': 'A', 'validity_status': 'withdrawn'}))
    with pytest.raises(ValueError, match='withdrawn_reason_missing'):
        export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')


def test_export_rejects_symlinked_target_parent_outside_repo(tmp_path):
    repo, workspace = tmp_path / 'repo', tmp_path / 'A'
    source = workspace / 'objects/research_knowledge_base/knowledge_record__A.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'report_id': 'A', 'factor_id': 'A'}))
    outside = tmp_path / 'outside'
    outside.mkdir()
    export_root = repo / 'knowledge/因子工厂'
    export_root.mkdir(parents=True)
    (export_root / 'workspace_experience_exports').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='target_outside_repo'):
        export_workspace_knowledge_record(workspace=workspace, repo_root=repo, report_id='A')


def test_workspace_refresh_does_not_ingest_default_exports(tmp_path, monkeypatch):
    import scripts.build_factorforge_retrieval_index as indexer

    repo, workspace_a, workspace_b = tmp_path / 'default', tmp_path / 'A', tmp_path / 'B'
    (repo / 'objects').mkdir(parents=True)
    record_a = workspace_a / 'objects/research_knowledge_base/knowledge_record__A.json'
    record_b = workspace_b / 'objects/research_knowledge_base/knowledge_record__B.json'
    record_a.parent.mkdir(parents=True)
    record_b.parent.mkdir(parents=True)
    record_a.write_text(json.dumps({'report_id': 'A', 'factor_id': 'A'}), encoding='utf-8')
    record_b.write_text(json.dumps({'report_id': 'B', 'factor_id': 'B'}), encoding='utf-8')
    monkeypatch.setattr(indexer, 'REPO_ROOT', repo)
    export_workspace_knowledge_record(workspace=workspace_a, repo_root=repo, report_id='A')

    workspace_summary = indexer.refresh_retrieval_index(workspace_b)
    workspace_docs = [
        json.loads(line)
        for line in (workspace_b / 'knowledge/retrieval/factorforge_retrieval_index.jsonl').read_text(encoding='utf-8').splitlines()
    ]
    assert workspace_summary['doc_count'] == 1
    assert [doc['id'] for doc in workspace_docs] == ['knowledge_record::B']
    default_summary = indexer.refresh_retrieval_index(repo)
    assert default_summary['doc_count'] == 1


def test_default_export_refresh_without_objects_is_durable_but_workspace_stays_strict(tmp_path, monkeypatch):
    import scripts.build_factorforge_retrieval_index as indexer

    default, workspace = tmp_path / 'default', tmp_path / 'workspace'
    record = workspace / 'objects/research_knowledge_base/knowledge_record__A.json'
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({
        'report_id': 'A', 'factor_id': 'A', 'decision': 'iterate',
        'failure_patterns': ['durable failure'], 'mathematical_object': 'durable object',
        'reusable_operator': {'mapping': 'durable operator'}, 'reuse_constraints': ['advisory only'],
    }), encoding='utf-8')
    monkeypatch.setattr(indexer, 'REPO_ROOT', default)
    export_workspace_knowledge_record(workspace=workspace, repo_root=default, report_id='A')

    first = indexer.refresh_retrieval_index(default)
    second = indexer.refresh_retrieval_index(default)
    index = default / 'knowledge/retrieval/factorforge_retrieval_index.jsonl'
    assert first['doc_count'] == second['doc_count'] == 1
    assert json.loads(index.read_text(encoding='utf-8'))['source_path'] == (
        'knowledge/因子工厂/workspace_experience_exports/knowledge_record__A.json'
    )
    with pytest.raises(indexer.CorpusBuildError, match='source objects directory is missing'):
        indexer.refresh_retrieval_index(tmp_path / 'ordinary-workspace')


def test_default_export_refresh_does_not_tolerate_objects_regular_file(tmp_path, monkeypatch):
    import scripts.build_factorforge_retrieval_index as indexer

    default = tmp_path / 'default'
    default.mkdir()
    (default / 'objects').write_text('not a directory', encoding='utf-8')
    monkeypatch.setattr(indexer, 'REPO_ROOT', default)
    with pytest.raises(indexer.CorpusBuildError, match='source objects directory must be a directory'):
        indexer.refresh_retrieval_index(default)


def test_new_study_default_step1_and_step2_retrieve_export_without_a_root(tmp_path, monkeypatch):
    """A completed local case reaches B only through default export and index."""
    import scripts.build_factorforge_retrieval_index as indexer

    default, workspace_a = tmp_path / 'default', tmp_path / 'A'
    (default / 'objects').mkdir(parents=True)
    source = workspace_a / 'objects/research_knowledge_base/knowledge_record__A.json'
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        'report_id': 'A', 'factor_id': 'old_case', 'decision': 'iterate',
        'factor_family': 'price_volume', 'monetization_model': 'constraint', 'bias_type': 'none',
        'return_source_hypothesis': 'distinct pressure mechanism',
        'expected_failure_regimes': ['distinct failure regime'],
        'objective_constraint_dependency': 'distinct session rule', 'constraint_sources': [],
        'success_patterns': [], 'failure_patterns': ['distinct failure mode'],
        'modification_hypotheses': ['future idea'],
        'mathematical_object': 'distinct robust object',
        'reusable_operator': {'mapping': 'distinct operator'},
        'implementation_references': ['implementation/old_case.py'],
        'knowledge_scope': 'same_factor', 'reuse_constraints': ['advisory only'],
    }), encoding='utf-8')
    monkeypatch.setattr(indexer, 'REPO_ROOT', default)
    export_workspace_knowledge_record(workspace=workspace_a, repo_root=default, report_id='A')
    indexer.refresh_retrieval_index(default)

    # B has its own workspace.  It supplies no A root and queries mechanism,
    # mathematics and failure terms rather than a report/case identifier.
    workspace_b = tmp_path / 'B'
    monkeypatch.setenv('FACTORFORGE_ROOT', str(workspace_b))
    monkeypatch.setenv('FACTORFORGE_FACTOR_WORKSPACE', str(workspace_b))
    monkeypatch.delenv('FACTORFORGE_SHARED_FACTORFORGE_ROOT', raising=False)
    monkeypatch.delenv('FACTORFORGE_RETRIEVAL_INDEX', raising=False)
    monkeypatch.setenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', '1')
    step1 = _load_script('workspace_export_b_step1', 'skills/factor-forge-step1/scripts/standardize_step1_research_fields.py')
    step2 = _load_script('workspace_export_b_step2', 'skills/factor-forge-step2/scripts/run_step2.py')
    monkeypatch.setattr(step1, 'REPO_ROOT', default)
    monkeypatch.setattr(step2, 'REPO_ROOT', default)
    aim = {
        'final_factor': {'name': 'new_case', 'economic_logic': 'distinct pressure mechanism'},
        'research_discipline': {
            'economic_hypothesis': {'claim': 'distinct pressure mechanism'},
            'math_hypothesis_candidates': ['distinct robust object distinct operator'],
        },
    }
    step1_result = step1.attach_factor_knowledge_context(aim)
    step2_result = step2.build_step2_research_contract(
        {'report_id': 'B', 'factor_id': 'new_case', 'raw_formula_text': 'rank(signal)'},
        {}, aim, {},
    )
    for contract in (
        step1_result['knowledge_reference_contract'],
        step2_result['knowledge_reference_contract'],
    ):
        assert contract['retrieved_case_ids'] == ['knowledge_record::A']
        case = contract['retrieved_cases'][0]
        assert case['mathematical_object'] == 'distinct robust object'
        assert case['failure_patterns'] == ['distinct failure mode']
        assert case['reusable_operator'] == {'mapping': 'distinct operator'}
        assert case['advisory_only'] is True
        assert case['not_same_factor_unless_identity_matches'] is True


def test_local_trial_patch_includes_explicit_untracked_export_source(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'scripts'))
    trial = _load_script('workspace_export_trial_builder', 'scripts/build_factorforge_local_trial.py')
    head = trial.subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=trial.REPO, text=True).strip()
    monkeypatch.setattr(trial, 'BASE', head)
    monkeypatch.setattr(trial, 'PATCH_PATHS', ('factor_factory/workspace_experience_export.py',))
    monkeypatch.setattr(trial, 'STANDALONE', ())

    def minimal_preview(*, source_root, output):
        with zipfile.ZipFile(output, 'x') as archive:
            archive.writestr('README.txt', 'synthetic')
        return output

    monkeypatch.setattr(trial, 'build_preview', minimal_preview)
    output = tmp_path / 'trial.zip'
    trial.build(output)
    with zipfile.ZipFile(output) as archive:
        patch = archive.read('ultimate-integration.patch').decode('utf-8')
    assert 'factor_factory/workspace_experience_export.py' in patch
    assert 'new file mode' in patch
    assert 'package_projection' not in patch


def test_candidate_export_seed_patch_is_explicit_scrubbed_and_rejects_bad_inputs(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'scripts'))
    trial = _load_script('workspace_export_seed_builder', 'scripts/build_factorforge_local_trial.py')
    root = tmp_path / 'repo'
    relative = Path('knowledge/因子工厂/workspace_experience_exports/knowledge_record__A.json')
    candidate = root / relative
    candidate.parent.mkdir(parents=True)
    candidate.write_text(json.dumps({
        'report_id': 'A', 'factor_id': 'A', 'export_version': 'factorforge_workspace_experience_export_v1',
        'export_status': 'LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL',
        'advisory_only': True, 'same_factor_not_generalized': True,
        'canonical_promotion_allowed': False,
        'implementation_references': ['/Users/private/implementation.py'],
        'source_record_relative_ref': 'objects/research_knowledge_base/knowledge_record__A.json',
    }), encoding='utf-8')
    monkeypatch.setattr(trial, 'REPO', root)
    patch = trial._candidate_export_patch(relative).decode('utf-8')
    assert 'new file mode 100644' in patch
    assert '/Users/private' not in patch
    assert 'original_source_record_included":false' in patch
    assert 'same_factor_not_generalized":true' in patch
    with pytest.raises(ValueError, match='immediate relative'):
        trial._candidate_export_patch(Path('/tmp/knowledge_record__A.json'))
    candidate.write_text(json.dumps({'report_id': 'A', 'export_status': 'wrong'}), encoding='utf-8')
    with pytest.raises(ValueError, match='invalid advisory contract'):
        trial._candidate_export_patch(relative)


def test_candidate_export_seed_rejects_lexical_symlink_and_duplicate_paths(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'scripts'))
    trial = _load_script('workspace_export_symlink_builder', 'scripts/build_factorforge_local_trial.py')
    root = tmp_path / 'repo'
    relative = Path('knowledge/因子工厂/workspace_experience_exports/knowledge_record__A.json')
    outside = tmp_path / 'outside.json'
    outside.write_text('{}', encoding='utf-8')
    link = root / relative
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    monkeypatch.setattr(trial, 'REPO', root)
    with pytest.raises(ValueError, match='must not use a symlink'):
        trial._candidate_export_patch(relative)

    head = trial.subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parents[1], text=True).strip()
    monkeypatch.setattr(trial, 'REPO', Path(__file__).parents[1])
    monkeypatch.setattr(trial, 'BASE', head)
    with pytest.raises(ValueError, match='duplicate candidate export'):
        trial.build(tmp_path / 'trial.zip', candidate_exports=(relative, relative))
