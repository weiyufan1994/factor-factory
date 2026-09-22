import json
from pathlib import Path
import importlib
import pytest

idx = importlib.import_module('scripts.build_factorforge_retrieval_index')

def episode(rid='R', **kw):
    d = {'episode_version':'factorforge_research_episode_v1','report_id':rid,'factor_id':'F',
         'run_status':'PAUSED','observations':[{'command':'run_step4','status':'PASS','returncode':0}],
         'lessons_status':'NEEDS_RESEARCHER_REVIEW','source_refs':['objects/runtime.json'],
         'advisory_only':True,'formal_step6_completed':False}
    d.update(kw); return d

def write(p, d): p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(d))

def test_local_episode_and_default_export_index_and_same_rid_facts(tmp_path, monkeypatch):
    root = tmp_path/'repo'; (root/'objects').mkdir(parents=True)
    write(root/'knowledge/research_episodes/episode__R__a.json', episode(run_status='PAUSED'))
    write(root/'knowledge/因子工厂/research_episode_exports/episode__R__b.json', episode(run_status='FAILED'))
    monkeypatch.setattr(idx, 'REPO_ROOT', root)
    docs = idx.build_corpus(root/'objects')
    assert {d['doc_type'] for d in docs} == {'research_episode'}
    assert len(docs) == 2 and len({d['id'] for d in docs}) == 2

def test_episode_rejects_wrong_version_and_formal_step6(tmp_path):
    p = tmp_path/'episode__R.json'
    for change in ({'episode_version':'wrong'}, {'formal_step6_completed':True},
                   {'formal_step6_completed':None}, {'advisory_only':False},
                   {'lessons_status':'IDENTIFIED'}):
        write(p, episode(**change))
        with pytest.raises(idx.CorpusBuildError): idx.make_research_episode_doc(p, json.loads(p.read_text()))

@pytest.mark.parametrize('kind', ['file','directory'])
def test_episode_rejects_symlink(tmp_path, monkeypatch, kind):
    root = tmp_path/'repo'; (root/'objects').mkdir(parents=True); e=root/'knowledge/research_episodes'; e.mkdir(parents=True)
    target=tmp_path/'outside'; target.mkdir()
    link=e/'episode__R__x.json'
    if kind=='file':
        real=target/'real.json'; write(real, episode()); link.symlink_to(real)
    else:
        link.unlink(missing_ok=True); link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(idx, 'REPO_ROOT', root)
    with pytest.raises(idx.CorpusBuildError): idx.build_corpus(root/'objects')

def test_withdrawn_excluded_and_old_bytes_preserved(tmp_path, monkeypatch):
    root=tmp_path/'repo'; (root/'objects').mkdir(parents=True); exp=root/'knowledge/因子工厂/workspace_experience_exports'; exp.mkdir(parents=True)
    old={'report_id':'R','factor_id':'F','export_version':'factorforge_workspace_experience_export_v1','advisory_only':True,'same_factor_not_generalized':True,'canonical_promotion_allowed':False,'export_status':'LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL'}
    oldp=exp/'knowledge_record__R.json'; write(oldp, old); before=oldp.read_bytes()
    rev={**old,'validity_status':'withdrawn','invalidation_reason':'retracted','export_revision':{'supersedes_file':oldp.name,'supersedes_sha256':__import__('hashlib').sha256(before).hexdigest(),'changed_fields':['invalidation_reason','validity_status'],'reason':'retracted'}}
    write(exp/'knowledge_record__R__correction.json', rev); monkeypatch.setattr(idx,'REPO_ROOT',root)
    assert not [d for d in idx.build_corpus(root/'objects') if d['doc_type']=='knowledge_record']; assert oldp.read_bytes()==before

def test_new_field_type_error_rejected(tmp_path):
    p=tmp_path/'k.json'; d={'report_id':'R','factor_id':'F','applicability_conditions':'bad'}; write(p,d)
    with pytest.raises(idx.CorpusBuildError): idx.make_knowledge_doc(p,d)
