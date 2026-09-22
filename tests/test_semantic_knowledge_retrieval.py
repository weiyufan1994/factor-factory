from factor_factory.semantic_knowledge_retrieval import build_semantic_index, retrieve_semantic
import json
import pytest
from factor_factory import semantic_knowledge_retrieval as semantic
from factor_factory.knowledge_reference import build_knowledge_reference_contract

def enc(xs):
    return [[1,0] if "压力" in x or "pressure" in x else [0,1] for x in xs]

def test_mock_dense_recall_and_filter(tmp_path):
    p=tmp_path/'i.json'; build_semantic_index([{"id":"a","text":"temporary price pressure"},{"id":"b","text":"长期价值"}],enc,p)
    r=retrieve_semantic("短期压力",p,enc,allowed_ids={"a"}); assert r["semantic_used"] and r["hits"][0]["id"]=="a" and not r["hits"][0]["similarity_is_evidence"]

def test_stale_falls_back(tmp_path):
    p=tmp_path/'i.json'; build_semantic_index([],enc,p,model_id='old'); assert retrieve_semantic('x',p,enc)['fallback']=='stale_model'


def test_search_text_excludes_decision_and_stale_source_is_visible(tmp_path):
    path = tmp_path / 'i.json'
    row = {'id': 'case', 'text': 'decision=promote_official', 'search_text': 'pressure'}
    seen = []
    def encode(values):
        seen.extend(values)
        return [[1, 0] for _ in values]
    build_semantic_index([row], encode, path)
    assert seen == ['pressure']
    result = retrieve_semantic('question', path, encode, allowed_ids={'case'},
                              expected_text_hashes={'case': semantic.text_hash('changed')})
    assert result['fallback'] == 'stale_source_text'
    assert seen == ['pressure']  # stale check occurs before expensive inference


@pytest.mark.parametrize('vectors', [[[0, 0]], [[float('nan'), 1]], [[float('inf'), 1]], []])
def test_invalid_encoder_preserves_previous_index(tmp_path, vectors):
    path = tmp_path / 'i.json'
    path.write_text('previous cache')
    with pytest.raises(ValueError):
        build_semantic_index([{'id': 'a', 'text': 'pressure'}], lambda _: vectors, path)
    assert path.read_text() == 'previous cache'


def test_dimension_mismatch_and_duplicate_ids(tmp_path):
    path = tmp_path / 'i.json'
    rows = [{'id': 'a', 'text': 'pressure'}, {'id': 'b', 'text': 'value'}]
    with pytest.raises(ValueError):
        build_semantic_index(rows, lambda _: [[1, 0], [1, 0, 0]], path)
    with pytest.raises(ValueError):
        build_semantic_index([rows[0], rows[0]], enc, path)
    build_semantic_index(rows, enc, path)
    result = retrieve_semantic('pressure', path, lambda _: [[1, 0, 0]])
    assert result['semantic_available'] is False


def test_filter_before_topk_and_ignore_unrelated_stale_text(tmp_path):
    path = tmp_path / 'i.json'
    rows = [{'id': 'hidden', 'text': 'pressure'}, {'id': 'visible', 'text': 'pressure'}]
    build_semantic_index(rows, enc, path)
    result = retrieve_semantic('压力', path, enc, top_k=1, allowed_ids={'visible'},
                              expected_text_hashes={'visible': semantic.text_hash('pressure')})
    assert [hit['id'] for hit in result['hits']] == ['visible']


def test_real_consumer_dense_only_hit_and_explicit_root_isolation(tmp_path, monkeypatch):
    directory = tmp_path / 'knowledge/retrieval'
    directory.mkdir(parents=True)
    index = directory / 'factorforge_retrieval_index.jsonl'
    rows = [{'id': 'case', 'report_id': 'OLD', 'factor_id': 'F',
             'doc_type': 'knowledge_record', 'search_text': 'pressure',
             'metadata': {}, 'advisory_projection': {}}]
    index.write_text(json.dumps(rows[0]) + '\n')
    build_semantic_index(rows, enc, directory / 'dense.json')
    (directory / 'semantic_config.json').write_text(json.dumps(
        {'enabled': True, 'model_path': '/not-loaded', 'index_path': 'dense.json'}))
    monkeypatch.delenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', raising=False)
    monkeypatch.setattr(semantic, 'configured_encoder', lambda _: enc)
    result = build_knowledge_reference_contract(repo_root=tmp_path, query_text='压力', producer='test')
    assert result['semantic_retrieval']['semantic_used'] is True
    assert 'case' in result['retrieved_case_ids']
    assert result['retrieved_cases'][0]['advisory_only'] is True
    # An explicit empty knowledge root must not pick up this project's config.
    isolated = build_knowledge_reference_contract(repo_root=tmp_path, knowledge_root=tmp_path/'other',
                                                  query_text='压力', producer='test')
    assert isolated['hit_count'] == 0
    assert isolated['semantic_retrieval']['semantic_used'] is False
    rows[0]['search_text'] = 'changed source'
    index.write_text(json.dumps(rows[0]) + '\n')
    stale = build_knowledge_reference_contract(repo_root=tmp_path, query_text='压力', producer='test')
    assert stale['semantic_retrieval']['fallback'] == 'stale_source_text'
    assert stale['hit_count'] == 0


def test_disable_switch_never_loads_encoder(tmp_path, monkeypatch):
    config = tmp_path/'semantic_config.json'
    config.write_text('{"enabled":true,"model_path":"missing"}')
    monkeypatch.setenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', '1')
    monkeypatch.setattr(semantic, 'configured_encoder', lambda _: pytest.fail('model should not load'))
    assert semantic.retrieve_configured('question', [], config)['fallback'] == 'explicitly_disabled'


def test_missing_model_dependency_returns_visible_fallback(tmp_path, monkeypatch):
    rows = [{'id': 'case', 'search_text': 'pressure'}]
    build_semantic_index(rows, enc, tmp_path/'dense.json')
    config = tmp_path/'semantic_config.json'
    config.write_text(json.dumps({'enabled': True, 'model_path': 'missing', 'index_path': 'dense.json'}))
    monkeypatch.delenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', raising=False)
    def missing(_):
        raise ImportError('missing optional sentence_transformers')
    monkeypatch.setattr(semantic, 'configured_encoder', missing)
    result = semantic.retrieve_configured('压力', rows, config)
    assert result['semantic_available'] is False
    assert result['fallback'] == 'index_or_encoder_unavailable'
