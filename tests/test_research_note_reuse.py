import json
from pathlib import Path
import pytest
import scripts.build_factorforge_retrieval_index as indexer
from factor_factory.knowledge_reference import build_knowledge_reference_contract


def test_authored_note_retrievable_without_claiming_completed_step6(tmp_path, monkeypatch):
    # Synthetic content keeps the offline suite portable, without distributing
    # this user's live research notes or their private source-document paths.
    note = {
        'note_version':'factorforge_research_note_v1', 'note_id':'synthetic_note',
        'report_id':'EXAMPLE', 'factor_id':'EXAMPLE', 'decision':'needs_human_review',
        'advisory_only':True, 'formal_step6_completed':False,
        'canonical_promotion_allowed':False, 'evidence_class':'synthetic_test',
        'failure_patterns':['A=0 不等于没有事件'], 'success_patterns':[],
        'modification_hypotheses':[], 'reuse_constraints':['Not a causal result'],
        'applicability_conditions':['Synthetic case only'],
        'regime_detection':{'status':'not_identified'},
        'source_identity':{'report_path':'synthetic-report.md'},
    }
    target = tmp_path/'knowledge/因子工厂/research_notes/note.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(note))
    monkeypatch.setattr(indexer, 'REPO_ROOT', tmp_path)
    indexer.refresh_retrieval_index(tmp_path)
    result = build_knowledge_reference_contract(repo_root=tmp_path, query_text='A=0 不等于没有事件', producer='fresh_reader')
    case = next(case for case in result['retrieved_cases'] if case['doc_type'] == 'research_note')
    assert case['formal_step6_completed'] is False
    assert case['decision'] is None
    assert case['advisory_only'] is True
    assert case['regime_detection']['status'] == 'not_identified'
    assert case['applicability_conditions']
    assert case['failure_patterns']
    assert case['identity']['source_identity']['report_path']
    before = target.read_bytes()
    indexer.refresh_retrieval_index(tmp_path)
    assert target.read_bytes() == before


def test_note_cannot_claim_formal_step6(tmp_path, monkeypatch):
    target = tmp_path/'knowledge/因子工厂/research_notes/note.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'note_version':'factorforge_research_note_v1',
                                 'formal_step6_completed':True}))
    monkeypatch.setattr(indexer, 'REPO_ROOT', tmp_path)
    with pytest.raises(indexer.CorpusBuildError):
        indexer.refresh_retrieval_index(tmp_path)
