import json
from types import SimpleNamespace
import pytest
from factor_factory import startup_experience as s

@pytest.fixture
def setup(tmp_path, monkeypatch):
    from factor_factory import knowledge_reference as k
    overlay=tmp_path/'overlay.json';overlay.write_text('{"source":"frozen"}')
    baseline={'blind_seed':{'economic_claim':'public surprise persistence','mathematical_object':'conditional expectation','falsifiers':['sign reversal'],'statement_ids':['must_not_query']}}
    receipt={'workspace_manifest_binding':{'workspace_root':str(tmp_path)},'report_id':'R',
             'source_first_overlay_binding':{'relative_path':'overlay.json','raw_sha256':s.digest(overlay.read_bytes())}}
    validated=SimpleNamespace(receipt=receipt,chief_advisory_raw=s.encoded({'source_first':baseline}))
    calls=[]
    def retrieve(**kwargs):
        calls.append(kwargs)
        return {'retrieval_status':'retrieved','experience_index_sha256':'index', 'retrieved_cases':[
            {'id':'method','doc_type':'research_note','identity':{'source_identity':{'source_sha256':{'archive':'sha'}}},
             'mathematical_object':'E[Y|F]','reuse_constraints':['no latent observability assumption'],
             'search_text':'historical performance 99','failure_conditions':['Sharpe 10']},
            {'id':'graph','mathematical_object':'graph duplicate'}]}
    monkeypatch.setattr(k,'build_knowledge_reference_contract',retrieve)
    monkeypatch.setattr(k,'resolve_runtime_retrieval_index',lambda root:tmp_path/'configured.jsonl')
    return tmp_path,overlay,validated,calls

def response(delivery,decision='reject'):
    return {'delivery_sha256':delivery['delivery_sha256'],
        'decisions':[{'id':c['id'],'decision':decision,'reason':'different mechanism',
                      'modeling_change':'unchanged: unrelated mechanism','falsification_change':'unchanged: unrelated mechanism'} for c in delivery['cases']],
        'modeling_before':'conditional expectation','modeling_after':'conditional expectation',
        'falsification_before':'sign reversal','falsification_after':'sign reversal',
        'overall_reason':'rejected because not applicable'}

def deliver(setup):
    ws,overlay,v,calls=setup
    return json.loads(s.emit_startup_advisory(v,ws))['post_source_experience']

def test_delivery_freeze_projection_configured_query_cache(setup):
    ws,o,v,calls=setup
    d=deliver(setup)
    assert len(calls)==1 and calls[0]['retrieval_index']==ws/'configured.jsonl'
    assert 'must_not_query' not in calls[0]['query_text']
    assert [c['id'] for c in d['cases']]==['method']
    assert 'historical performance' not in json.dumps(d)
    assert 'Sharpe' not in json.dumps(d)
    assert not (s.folder(ws,'R')/'use_receipt.json').exists()
    deliver(setup);assert len(calls)==1
    o.write_text('changed')
    with pytest.raises(ValueError,match='source freeze changed'):deliver(setup)
    assert len(calls)==1

def test_pending_reject_and_stale_source(setup):
    ws,o,v,calls=setup;d=deliver(setup)
    with pytest.raises(ValueError,match='pending'):s.require_recorded_use(ws,'R')
    s.record_use(ws,'R',response(d))
    assert s.require_recorded_use(ws,'R')['status']=='AUTHOR_DECISIONS_RECORDED'
    o.write_text('changed')
    with pytest.raises(ValueError,match='source freeze'):s.require_recorded_use(ws,'R')

def test_invalid_missing_and_duplicate_decisions(setup):
    ws,*_=setup;d=deliver(setup)
    for change in ({'decisions':[]},{'decisions':[{'id':'method','decision':'auto'}]},{'modeling_after':''},{'delivery_sha256':'wrong'}):
        r=response(d);r.update(change)
        with pytest.raises(ValueError):s.record_use(ws,'R',r)

def test_tamper_detected_before_reuse_or_gate(setup):
    ws,*_=setup;deliver(setup)
    f=s.folder(ws,'R')/'delivery.json';f.write_bytes(f.read_bytes()+b' ')
    with pytest.raises(ValueError,match='bytes changed'):deliver(setup)
    with pytest.raises(ValueError,match='bytes changed'):s.require_recorded_use(ws,'R')

def test_new_workspace_missing_delivery_legacy_preserved(tmp_path):
    assert s.require_recorded_use(tmp_path,'R')['status'].startswith('LEGACY')
    s.save(tmp_path/'candidate_startup_experience/startup_required.json',{'required':True,'report_id':'R'})
    with pytest.raises(ValueError,match='new study requires'):s.require_recorded_use(tmp_path,'R')

def test_unavailable_nonblocking(setup,monkeypatch):
    from factor_factory import knowledge_reference as k
    def fail(**kwargs):raise RuntimeError('offline')
    monkeypatch.setattr(k,'build_knowledge_reference_contract',fail)
    ws,*_=setup;d=deliver(setup)
    assert d['retrieval_status']=='unavailable' and d['cases']==[]
    assert s.require_recorded_use(ws,'R')['status']=='NO_DELIVERED_CASES'

def test_all_decision_values_and_archive(setup):
    ws,*_=setup;d=deliver(setup)
    for decision in ('adopt','reject','defer'):
        result=s.record_use(ws,'R',response(d,decision))
        assert result['content_review']=='NOT_PERFORMED'
        s.require_recorded_use(ws,'R')
    assert len(list((s.folder(ws,'R')/'use_receipts').glob('*.json')))==3

def test_central_new_manifest_marker_direct_python_and_local_only_enforcement(tmp_path,monkeypatch):
    from factor_factory.research_workspace import write_workspace_manifest
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY','1')
    ws=tmp_path/'new'
    write_workspace_manifest(ws/'manifest.json',{'workspace_root':str(ws),'root_report_id':'R'})
    marker=ws/'candidate_startup_experience/startup_required.json'
    assert json.loads(marker.read_text())['report_id']=='R'
    assert s.require_recorded_use(ws,'CHILD')['status'].startswith('LEGACY')
    marker.unlink()
    write_workspace_manifest(ws/'manifest.json',{'workspace_root':str(ws),'root_report_id':'R'})
    assert not marker.exists() # Existing workspaces never retroactively rebound.
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    other=tmp_path/'hosted'
    write_workspace_manifest(other/'manifest.json',{'workspace_root':str(other),'root_report_id':'R'})
    assert (other/'candidate_startup_experience/startup_required.json').exists()
    # The marker is inert in hosted execution; its enforcement is local-only.

@pytest.mark.parametrize('script,args,method',[
 ('validate_factorforge_epistemic_source_first_advisory.py',['--receipt','receipt.json'],'validate_source_first_advisory_package'),
 ('run_factorforge_epistemic_source_first_advisory.py',['--factor-workspace','.','--report-id','R','--source-first-overlay','overlay.json','--emit-validated-advisory'],'run_and_validate_source_first_advisory')])
def test_both_native_emitters_use_post_source_delivery(setup,monkeypatch,script,args,method):
    import importlib.util
    import io
    import sys
    from pathlib import Path
    from factor_factory import epistemic_ultimate_source_first_bridge as bridge
    ws,o,v,calls=setup
    monkeypatch.setattr(bridge,method,lambda **kwargs:v)
    spec=importlib.util.spec_from_file_location('startup_emitter',Path(s.__file__).parents[1]/'scripts'/script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sink=io.BytesIO()
    monkeypatch.setattr(sys,'stdout',SimpleNamespace(buffer=sink))
    assert module.main(args)==0
    parsed=json.loads(sink.getvalue())
    assert parsed['post_source_experience']['cases'][0]['id']=='method'
    assert parsed['source_first']==json.loads(v.chief_advisory_raw)['source_first']


def test_response_binding_tamper_blocks(setup):
    ws,*_=setup;d=deliver(setup);s.record_use(ws,'R',response(d))
    p=s.folder(ws,'R')/'use_receipt.json';v=json.loads(p.read_text());v['author_response']['delivery_sha256']='wrong';s.save(p,v)
    with pytest.raises(ValueError,match='binding'):s.require_recorded_use(ws,'R')

def test_invalid_source_never_gets_operational_fallback(tmp_path,monkeypatch):
    from factor_factory import epistemic_ultimate_source_first_bridge as b
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY','1')
    monkeypatch.setattr(b,'validate_native_factor_workspace',lambda **kw:({'root_report_id':'R'}, {}, b''))
    monkeypatch.setattr(b,'_operating_factorforge_root',lambda:tmp_path)
    monkeypatch.setattr(b,'_read_overlay_file',lambda **kw:({'invalid':'source'},b'',{}))
    with pytest.raises(ValueError):
        s.record_operational_failure(tmp_path,tmp_path/'overlay','R',OSError('offline'),tmp_path)
    assert not (s.folder(tmp_path,'R')/'operational_failure.json').exists()


def test_narrow_operational_failure_nonblocking_source_bound(tmp_path,monkeypatch):
    from factor_factory import epistemic_ultimate_source_first_bridge as b
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY','1')
    o=tmp_path/'overlay';o.write_text('source')
    binding={'relative_path':'overlay','raw_sha256':s.digest(o.read_bytes())}
    monkeypatch.setattr(b,'validate_native_factor_workspace',lambda **kw:({'root_report_id':'R'}, {}, b''))
    monkeypatch.setattr(b,'_operating_factorforge_root',lambda:tmp_path)
    monkeypatch.setattr(b,'_read_overlay_file',lambda **kw:({},b'',binding))
    monkeypatch.setattr(b,'_compile_agent_source_first_overlay',lambda *a,**kw:({}, {'source_compiled_before_knowledge_resolution':True}))
    s.record_operational_failure(tmp_path,o,'R',OSError('offline'),tmp_path)
    assert s.require_recorded_use(tmp_path,'R')['status']=='A0_OPERATIONALLY_UNAVAILABLE'
    o.write_text('changed')
    with pytest.raises(ValueError,match='source freeze'):s.require_recorded_use(tmp_path,'R')
    with pytest.raises(ValueError,match='not a local'):s.record_operational_failure(tmp_path,o,'R',ValueError('integrity'),tmp_path)


def test_actual_ultimate_command_loop_stops_pending_and_passes_recorded(setup,monkeypatch):
    from factor_factory.ultimate_loop import runner
    ws,*_=setup;d=deliver(setup)
    proof={}
    def stop_after_gate(**kwargs):
        raise RuntimeError('TEST_STOP_BEFORE_ANY_STAGE_EXECUTION')
    monkeypatch.setattr(runner,'command_environment_for_host_controls',stop_after_gate)
    kwargs=dict(mode=SimpleNamespace(web_is_evo_child=False,web_secure_child_oos=False),
        args=SimpleNamespace(dry_run=False,report_id='R'),
        commands=[('run_step2',['never-executed'])],container_host_env=None,
        ctx=SimpleNamespace(factor_workspace=ws),end='2',env={},
        finish_local_maintenance=lambda rc:rc,host_private_oos_raw={},host_private_proof_values={},
        incident_host_env=None,legacy_protocol_smoke=False,local_is_only=True,
        manifest={},manifest_path=ws/'manifest.json',proof=proof,proof_path=ws/'proof.json',
        refresh_runtime_manifest_for_command=lambda name:{})
    assert runner._execute_commands(**kwargs)[0]==1
    assert proof['failure']['blocked_before']=='run_step2'
    assert proof['failure']['executed'] is False
    s.record_use(ws,'R',response(d))
    with pytest.raises(RuntimeError,match='TEST_STOP_BEFORE_ANY_STAGE_EXECUTION'):
        runner._execute_commands(**kwargs)
    assert proof['startup_experience_use']['status']=='AUTHOR_DECISIONS_RECORDED'


def test_documented_direct_python_initializer_creates_marker(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    env={k:v for k,v in os.environ.items() if not k.startswith('FACTORFORGE_')}
    repo=Path(s.__file__).parents[1]
    cp=subprocess.run([sys.executable,str(repo/'scripts/init_factor_research_workspace.py'),
        '--factor-id','TEST_DIRECT_START','--research-id','TEST_DIRECT_START_R1',
        '--report-id','TEST_DIRECT_START','--factorforge-root',str(tmp_path),
        '--implementation-mode','direct_code'],env=env,capture_output=True,text=True)
    assert cp.returncode==0, cp.stdout+cp.stderr
    marker=tmp_path/'factor_research/TEST_DIRECT_START/TEST_DIRECT_START_R1/candidate_startup_experience/startup_required.json'
    assert json.loads(marker.read_text())['report_id']=='TEST_DIRECT_START'
