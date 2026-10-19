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


def test_tail_recall_and_one_hit_per_document(tmp_path):
    path = tmp_path/'chunks.json'
    text = 'unrelated padding ' * 90 + ' pressure'
    build_semantic_index([{'id':'long','text':text},{'id':'other','text':'value'}], enc, path)
    result = retrieve_semantic('压力',path,enc,allowed_ids={'long','other'})
    assert [x['id'] for x in result['hits']] == ['long']
    assert result['hits'][0]['matched_chunk'] > 0
    assert result['hits'][0]['chunk_count'] > 1
    stale=retrieve_semantic('压力',path,enc,expected_text_hashes={'long':semantic.text_hash(text+'x')})
    assert stale['fallback']=='stale_source_text'


def test_v1_index_remains_readable(tmp_path):
    path=tmp_path/'old.json'
    path.write_text(json.dumps({'schema':'factorforge_semantic_index_v1','model_id':semantic.MODEL_ID,
      'dimension':2,'row_count':1,'rows':[{'id':'old','text_sha256':semantic.text_hash('pressure'),'vector':[1,0]}]}))
    assert retrieve_semantic('压力',path,enc)['hits'][0]['id']=='old'


def test_chunk_coverage_and_boundaries():
    text=''.join(chr(0x4e00+i) for i in range(1700))
    chunks=semantic.text_chunks(text)
    assert max(map(len,chunks))<=384
    assert all(char in ''.join(chunks) for char in text)


def test_reranker_rejects_nonlocal_endpoint():
    with pytest.raises(ValueError,match='local'):
        semantic.rerank_local('q',[],{'endpoint':'https://remote.example/chat'},top_k=3)


@pytest.mark.parametrize('matches', [[{'ordinal':8,'reason':'x'}], [{'ordinal':True,'reason':'x'}],
    [{'ordinal':0,'reason':'x'},{'ordinal':0,'reason':'x'}], [{'ordinal':0,'reason':''}]])
def test_reranker_rejects_invalid_output(monkeypatch,matches):
    import io
    def response(*args,**kwargs):
        return io.BytesIO(json.dumps({'message':{'content':json.dumps({'matches':matches})}}).encode())
    monkeypatch.setattr(semantic.urllib.request,'urlopen',response)
    with pytest.raises(ValueError):
        semantic.rerank_local('q',[{'id':'x','text':'hello'}],{'model':'local'},top_k=3)


def test_reranker_sees_full_visible_corpus_not_dense_shortlist(tmp_path,monkeypatch):
    rows=[{'id':str(i),'search_text':'pressure'} for i in range(12)]
    build_semantic_index(rows,enc,tmp_path/'dense.json')
    config=tmp_path/'semantic_config.json'
    config.write_text(json.dumps({'enabled':True,'model_path':'unused','index_path':'dense.json',
      'reranker':{'enabled':True,'model':'test'}}))
    monkeypatch.setattr(semantic,'configured_encoder',lambda _:enc)
    def rank(q,visible,c,*,top_k):
        assert len(visible)==12
        return {'hits':[{'id':'11','semantic_only':True,'similarity_is_evidence':False}], 'trace':{}}
    monkeypatch.setattr(semantic,'rerank_local',rank)
    result=semantic.retrieve_configured('压力',rows,config,top_k=3)
    assert result['hits'][0]['id']=='11' and result['reranker_used']
    assert len(result['dense_hits'])==3


def test_reranker_failure_is_explicit_and_preserves_dense(tmp_path,monkeypatch):
    rows=[{'id':'a','search_text':'pressure'}]
    build_semantic_index(rows,enc,tmp_path/'dense.json')
    config=tmp_path/'semantic_config.json'
    config.write_text(json.dumps({'enabled':True,'model_path':'unused','index_path':'dense.json',
      'reranker':{'enabled':True,'model':'test'}}))
    monkeypatch.setattr(semantic,'configured_encoder',lambda _:enc)
    def fail(*a,**kw): raise TimeoutError('offline')
    monkeypatch.setattr(semantic,'rerank_local',fail)
    result=semantic.retrieve_configured('压力',rows,config)
    assert result['hits'][0]['id']=='a'
    assert result['reranker_used'] is False and result['reranker_fallback']
    config_data=json.loads(config.read_text())
    # Stale sources must fail closed before invoking any ranking model.
    result=semantic.retrieve_configured('压力',[{'id':'a','search_text':'changed'}],config)
    assert result['fallback']=='stale_source_text' and 'reranker_used' not in result


def test_method_fingerprint_is_source_projection_not_identity_or_outcome():
    row={'id':'SPECIAL_ID','decision':'promote','search_text':'fallback',
         'advisory_projection':{'mathematical_object':'variance projection',
         'return_source_hypothesis':'unidentified pressure',
         'reuse_constraints':['full source remains in delivery']}}
    card=semantic.method_fingerprint(row)
    assert 'variance projection' in card and 'unidentified pressure' in card
    assert 'SPECIAL_ID' not in card and 'promote' not in card
    assert semantic.method_fingerprint({'search_text':'unstructured method'})=='unstructured method'


def test_chunk_sidecar_does_not_replace_legacy_cache(tmp_path,monkeypatch):
    rows=[{'id':'a','search_text':'pressure'}]
    legacy=tmp_path/'legacy.json';legacy.write_text('legacy bytes unchanged')
    build_semantic_index(rows,enc,tmp_path/'chunks.json')
    config=tmp_path/'semantic_config.json'
    config.write_text(json.dumps({'enabled':True,'model_path':'unused','index_path':'legacy.json',
                                 'chunk_index_path':'chunks.json'}))
    monkeypatch.setattr(semantic,'configured_encoder',lambda _:enc)
    assert semantic.retrieve_configured('压力',rows,config)['hits'][0]['id']=='a'
    assert legacy.read_text()=='legacy bytes unchanged'


def test_bulk_encoder_budget_does_not_change_query_budget(monkeypatch):
    import types
    calls=[]
    def run(*args,**kwargs):
        calls.append(kwargs['timeout'])
        texts=json.loads(kwargs['input'])
        return types.SimpleNamespace(stdout=json.dumps([[1,0] for _ in texts]))
    monkeypatch.setattr(semantic.subprocess,'run',run)
    encode=semantic.configured_encoder({'model_path':'local','python_path':'/different/python'})
    assert len(encode(['query']))==1
    assert len(encode(['first','second']))==2
    assert calls==[60,600]
