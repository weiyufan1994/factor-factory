"""Historical source scope is relative; current evidence identity remains strict."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def step6(monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith('FACTORFORGE_'):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', '1')
    monkeypatch.setenv('FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT', '1')
    path = ROOT/'skills/factor-forge-step6/scripts/run_step6.py'
    spec = importlib.util.spec_from_file_location('relative_scope_step6', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity(factor='CURRENT'):
    return {'factor_id': factor, 'formula_hash': 'formula', 'code_hash': 'code',
            'code_contract_hash': 'contract', 'custom_block_hash': 'custom',
            'hybrid_hash': 'hybrid', 'branch_id': 'main', 'run_id': 'run1'}


def historical(factor='OTHER'):
    return {'id': 'knowledge_record::PRIOR', 'report_id': 'PRIOR', 'factor_id': factor,
            'doc_type': 'knowledge_record', 'knowledge_scope': 'same_factor',
            'artifact_identity': identity(factor), 'source_identity': identity(factor),
            'source_path': '/synthetic/prior.json', 'decision': 'promote_official',
            'text': 'liquidity response', 'search_text': 'liquidity response'}


def compare(module, item, current=None):
    return module.build_case_comparison({'factor_family': 'unknown'}, {'similar_cases': [item]},
                                       current or identity(), {'evidence_audit': {}})


def test_different_source_factor_keeps_provenance_but_is_only_analogy(step6):
    source = historical()
    saved = deepcopy(source)
    result = step6.project_retrieved_case_scope(source, identity(), 'CURRENT')
    assert source == saved
    assert result['source_knowledge_scope'] == 'same_factor'
    assert result['knowledge_scope'] == 'similar_case'
    assert result['retrieval_scope_resolution']['source_factor_id'] == 'OTHER'
    assert result['retrieval_scope_resolution']['query_factor_id'] == 'CURRENT'
    for key in ['id', 'report_id', 'factor_id', 'source_path', 'artifact_identity', 'source_identity', 'decision']:
        assert result[key] == saved[key]
    comparison = compare(step6, result)
    assert comparison['case_comparison_verdict'] == 'usable'
    assert comparison['same_factor_cases'] == []
    assert comparison['similar_case_cases'][0]['reuse_as'] == 'analogy_only'
    assert comparison['similar_case_promotion_evidence_used'] is False
    # The strict consumer itself has not been weakened for same-factor claims.
    direct = compare(step6, source)
    assert direct['case_comparison_verdict'] == 'blocked'
    assert 'factor_id' in direct['identity_mismatch_cases'][0]['mismatch_fields']


@pytest.mark.parametrize('field', ['formula_hash', 'code_hash', 'code_contract_hash',
                                  'custom_block_hash', 'hybrid_hash', 'branch_id', 'run_id'])
def test_same_factor_stale_version_and_run_still_block(step6, field):
    source = historical('CURRENT')
    source['artifact_identity'][field] = 'stale'
    projected = step6.project_retrieved_case_scope(source, identity(), 'CURRENT')
    assert projected == source and projected['knowledge_scope'] == 'same_factor'
    comparison = compare(step6, projected)
    assert comparison['case_comparison_verdict'] == 'blocked'
    assert field in comparison['identity_mismatch_cases'][0]['mismatch_fields']


def test_exact_same_factor_identity_keeps_existing_history_route(step6):
    source = historical('CURRENT')
    result = step6.project_retrieved_case_scope(source, identity(), 'CURRENT')
    assert result == source
    comparison = compare(step6, result)
    assert comparison['case_comparison_verdict'] == 'usable'
    assert comparison['same_factor_cases'][0]['reuse_as'] == 'same_factor_history_with_provenance_check'


@pytest.mark.parametrize('problem', ['unknown_owner', 'conflicting_top', 'conflicting_source',
                                   'invalid_owner', 'unknown_current', 'routing_identity_conflict'])
def test_ambiguous_identity_does_not_get_downgraded_to_escape_guard(step6, problem):
    source, current, query = historical(), identity(), 'CURRENT'
    if problem == 'unknown_owner':
        source.pop('factor_id')
        source['artifact_identity'].pop('factor_id')
        source['source_identity'].pop('factor_id')
    elif problem == 'conflicting_top':
        source['factor_id'] = 'CURRENT'
    elif problem == 'conflicting_source':
        source['source_identity']['factor_id'] = 'SOME_THIRD_FACTOR'
    elif problem == 'invalid_owner':
        source['factor_id'] = 42
    elif problem == 'unknown_current':
        current = {}
    else:
        query = 'SOME_OTHER_ROUTING_ID'
    assert step6.project_retrieved_case_scope(source, current, query) == source


@pytest.mark.parametrize('claim', ['top_level', 'artifact_identity', 'source_identity'])
def test_conflicting_owner_claims_block_even_when_preferred_identity_matches(step6, claim):
    source = historical('CURRENT')
    target = source if claim == 'top_level' else source[claim]
    target['factor_id'] = 'UNRELATED'
    result = step6.project_retrieved_case_scope(source, identity(), 'CURRENT')
    assert result['knowledge_scope'] == 'same_factor'
    comparison = compare(step6, result)
    assert comparison['case_comparison_verdict'] == 'blocked'
    mismatch = comparison['identity_mismatch_cases'][0]
    assert 'factor_id' in mismatch['mismatch_fields']
    assert mismatch['source_factor_id_claims'][claim] == 'UNRELATED'


def test_both_unknown_factor_owners_cannot_establish_same_factor_history(step6):
    source = {'knowledge_scope': 'same_factor', 'artifact_identity': {}}
    projected = step6.project_retrieved_case_scope(source, {}, '')
    comparison = step6.build_case_comparison({}, {'similar_cases': [projected]}, {}, {})
    assert comparison['case_comparison_verdict'] == 'blocked'


@pytest.mark.parametrize('scope', ['similar_case', 'anti_pattern', 'general_methodology', None])
def test_existing_other_scopes_are_not_rewritten(step6, scope):
    source = historical()
    source['knowledge_scope'] = scope
    assert step6.project_retrieved_case_scope(source, identity(), 'CURRENT') == source


@pytest.mark.parametrize('lane', ['lexical', 'local_semantic', 'legacy_embedding'])
def test_native_retrieval_projects_after_ranking_without_changing_ids_or_budget(step6, monkeypatch, tmp_path, lane):
    import numpy as np
    source = historical()
    extra = {**historical('THIRD'), 'id': 'knowledge_record::SECOND', 'report_id': 'SECOND',
             'text': 'liquidity response extra', 'search_text': 'liquidity response extra'}
    extra['artifact_identity'] = extra['source_identity'] = identity('THIRD')
    docs = [source, extra]
    saved = deepcopy(docs)
    path = tmp_path/'index.jsonl'
    original_bytes = '\n'.join(json.dumps(row) for row in docs).encode()
    path.write_bytes(original_bytes)
    monkeypatch.setattr(step6, 'RETRIEVAL_INDEX', path)
    monkeypatch.setattr(step6, 'load_retrieval_docs', lambda: deepcopy(docs))
    if lane == 'local_semantic':
        extra['text'] = extra['search_text'] = 'unrelated_dense_only_terms'
        saved = deepcopy(docs)
        monkeypatch.setattr(step6, 'uses_local_advisory', lambda: True)
        from factor_factory import semantic_knowledge_retrieval
        monkeypatch.setattr(semantic_knowledge_retrieval, 'retrieve_configured', lambda *args, **kwargs: {
            'semantic_available': True, 'semantic_used': True, 'hits': [{'id': extra['id']}, {'id': source['id']}],
        })
    elif lane == 'legacy_embedding':
        extra['text'] = extra['search_text'] = 'unrelated_dense_only_terms'
        saved = deepcopy(docs)
        monkeypatch.delenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL')
        matrix, metadata = tmp_path/'matrix.npy', tmp_path/'meta.jsonl'
        np.save(matrix, np.array([[.9, 0.], [.8, 0.]]))
        metadata.write_text('synthetic')
        monkeypatch.setattr(step6, 'EMBEDDING_MATRIX', matrix)
        monkeypatch.setattr(step6, 'EMBEDDING_META', metadata)
        monkeypatch.setattr(step6, 'embed_query', lambda query: np.array([1., 0.]))
        monkeypatch.setattr(step6, 'load_embedding_docs', lambda: deepcopy(docs))
    bundle = {'factor_run_master': {'report_id': 'NOW', 'factor_id': 'CURRENT', 'artifact_identity': identity()},
              'factor_case_master': {'lessons': ['liquidity response'], 'next_actions': []}}
    real_projection = step6.project_retrieved_case_scope
    monkeypatch.setattr(step6, 'project_retrieved_case_scope', lambda item, *args: dict(item))
    before = step6.build_retrieval_context(bundle, {}, top_k=2)
    monkeypatch.setattr(step6, 'project_retrieved_case_scope', real_projection)
    after = step6.build_retrieval_context(bundle, {}, top_k=2)
    key = lambda c: [(x.get('id'), x['report_id'], x['score']) for x in c['similar_cases']]
    assert key(before) == key(after) and len(after['similar_cases']) == 2
    assert all(x['knowledge_scope'] == 'similar_case' for x in after['similar_cases'])
    assert all(x['source_knowledge_scope'] == 'same_factor' for x in after['similar_cases'])
    assert docs == saved and path.read_bytes() == original_bytes
