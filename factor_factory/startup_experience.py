"""Post-source-freeze method delivery and explicit author consumption evidence.

This is separate from the byte-exact A0 package. No market execution or
research verdict is performed here. A receipt proves recorded decisions, not
that a methodological change is scientifically sound.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid
from pathlib import Path

VERSION = "startup_experience_v1"
FIELDS = ("mathematical_object", "reusable_operator", "applicability_conditions",
          "reuse_constraints", "failure_conditions")
PERFORMANCE = re.compile(r"(?i)\b(?:sharpe|pnl|oos|backtest|rank.?ic|drawdown)\b|年化收益|最大回撤|夏普|历史绩效|回测绩效")

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)+"\n").encode()

def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_bytes(encoded(obj))
    temp.replace(path)

def folder(workspace, report_id):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", report_id) or report_id in {'.', '..'}:
        raise ValueError('unsafe report id')
    return Path(workspace)/'candidate_startup_experience'/report_id

def clean(value):
    # Fail closed per textual leaf; never copy raw search text or history.
    if isinstance(value, str):
        return value if not PERFORMANCE.search(value) else None
    if isinstance(value, list):
        return [v for x in value if (v := clean(x)) is not None]
    if isinstance(value, dict):
        return {k:v for k,x in value.items() if not PERFORMANCE.search(k) and (v := clean(x)) is not None}
    return value if isinstance(value, (int,float,bool)) or value is None else None

def projection(case):
    provenance = case.get('workspace_export_source') or {}
    source_identity = (case.get('identity') or {}).get('source_identity') or {}
    if case.get('doc_type') not in {'knowledge_record','research_episode','research_note'}:
        return None
    if not provenance.get('record_sha256'):
        provenance = {'source_sha256':source_identity.get('source_sha256'), 'source_path':case.get('source_path')}
    result = {k:clean(case.get(k)) for k in FIELDS if case.get(k)}
    learning = case.get('learning_and_innovation') or {}
    if isinstance(learning,dict):
        for key in ('learning_goal','transferable_patterns','anti_patterns'):
            if learning.get(key):
                result[key] = clean(learning[key])
    mechanism = case.get('mechanism') or {}
    if mechanism.get('return_source_hypothesis'):
        result['return_source_hypothesis'] = clean(mechanism['return_source_hypothesis'])
    # Graph history is already delivered in the original validated A0 bytes.
    # Only explicit reviewed-experience method fields enter this separate lane.
    if not any(result.values()):
        return None
    return {'id':case['id'], 'method':result,
            'provenance':provenance,
            'advisory_only':True,
            'projection_policy':'explicit_method_fields_only; performance-bearing leaves omitted'}

def _verify_binding(workspace, binding):
    overlay = (Path(workspace)/binding['relative_path']).resolve(strict=True)
    if not overlay.is_relative_to(Path(workspace).resolve()):
        raise ValueError('overlay outside workspace')
    if digest(overlay.read_bytes()) != binding['raw_sha256']:
        raise ValueError('source freeze changed: regenerate delivery and author decisions')

def emit_startup_advisory(validated, repo_root):
    # Caller must have completed native strict replay before invoking this.
    receipt = validated.receipt
    workspace = Path(receipt['workspace_manifest_binding']['workspace_root'])
    report_id = receipt['report_id']
    target = folder(workspace, report_id)
    binding = receipt['source_first_overlay_binding']
    _verify_binding(workspace, binding)
    original = json.loads(validated.chief_advisory_raw)
    baseline = original['source_first']
    base_binding = {'source_overlay':binding, 'a0_sha256':digest(validated.chief_advisory_raw),
                    'report_id':report_id, 'workspace':str(workspace)}
    path = target/'delivery.json'
    cached = json.loads(path.read_text()) if path.exists() else None
    if cached and cached.get('binding') == base_binding:
        frozen = json.loads((target/'delivery_binding.json').read_text())
        if frozen['delivery_sha256'] != digest(path.read_bytes()):
            raise ValueError('stored delivery bytes changed')
        delivery = cached
    else:
        from factor_factory.knowledge_reference import build_knowledge_reference_contract, resolve_runtime_retrieval_index
        # Natural source semantics only; exclude IDs, assertions and provenance.
        semantic_fields = {'economic_claim','estimand','information_set','horizon',
                           'mathematical_object','observation_mapping','falsifiers',
                           'material_rivals','pre_a0_predictions','economic_mechanism_claim',
                           'payer_or_constraint','failure_signature','broken_invariant_or_boundary'}
        def collect(value):
            if not isinstance(value,dict):
                return {}
            out={k:v for k,v in value.items() if k in semantic_fields}
            for k,v in value.items():
                if isinstance(v,dict) and (nested := collect(v)):
                    out[k]=nested
            return out
        query = json.dumps(collect(baseline), ensure_ascii=False, sort_keys=True)
        try:
            contract = build_knowledge_reference_contract(repo_root=Path(repo_root),
                query_text=query, producer=VERSION, top_k=3, retrieval_required=False,
                retrieval_index=resolve_runtime_retrieval_index(Path(repo_root)))
            cases = [item for c in contract.get('retrieved_cases',[]) if (item := projection(c))]
            status = contract.get('retrieval_status', 'unavailable')
            error = contract.get('fallback_reason')
        except Exception as exc:
            contract = {'retrieval_status':'unavailable','error_type':type(exc).__name__}
            cases, status, error = [], 'unavailable', type(exc).__name__
        delivery = {'version':VERSION,'binding':base_binding,'source_only_baseline':baseline,
                    'query_sha256':digest(query.encode()),'retrieval_status':status,
                    'retrieval_limitation':error,'cases':cases,'advisory_only':True,
                    'experience_index_sha256':contract.get('experience_index_sha256'),
                    'no_market_execution':True}
        save(target/'retrieval_provenance.json', contract)
        save(path, delivery)
        delivery_hash = digest(path.read_bytes())
        save(target/'deliveries'/f'{delivery_hash}.json',delivery)
        save(target/'delivery_binding.json',{'delivery_sha256':delivery_hash})
        # An existing author receipt is retained but becomes hash-stale.
    payload = dict(original)
    payload['post_source_experience'] = {
        **delivery, 'delivery_path':str(path),'delivery_sha256':digest(path.read_bytes()),
        'next_action': 'Before authoring formal Step2, read these methods and record one adopt/reject/defer decision per case. Describe your source-only modeling and falsification baseline, then the actual after-design and reasons; unchanged is allowed with explanation. Do not claim tested results.',
        'record_command': [str(Path(repo_root).parent/'run-ultimate'),'--python',
             str(Path(repo_root)/'scripts/record_factorforge_startup_experience_use.py'),
             '--factor-workspace',str(workspace),'--report-id',report_id,'--response-json','YOUR_AUTHORED_RESPONSE.json'],
        'response_schema': {
            'delivery_sha256':digest(path.read_bytes()),
            'decisions':[{'id':x['id'],'decision':'adopt|reject|defer','reason':'author explanation',
                          'modeling_change':'specific change or unchanged with reason',
                          'falsification_change':'specific change or unchanged with reason'} for x in delivery['cases']],
            'modeling_before':'source-only baseline in your own words',
            'modeling_after':'actual design after consideration',
            'falsification_before':'source-only tests',
            'falsification_after':'actual tests after consideration',
            'overall_reason':'why changed or unchanged; acknowledge unavailable retrieval when applicable'}
    }
    return encoded(payload)

def record_use(workspace, report_id, response):
    target = folder(workspace, report_id)
    raw = (target/'delivery.json').read_bytes()
    delivery = json.loads(raw)
    frozen = json.loads((target/'delivery_binding.json').read_text())
    if frozen['delivery_sha256'] != digest(raw):
        raise ValueError('stored delivery bytes changed')
    _verify_binding(workspace, delivery['binding']['source_overlay'])
    if response.get('delivery_sha256') != digest(raw):
        raise ValueError('delivery hash mismatch')
    expected = {c['id'] for c in delivery['cases']}
    decisions = response.get('decisions')
    if not isinstance(decisions,list) or len(decisions)!=len(expected) or {d.get('id') for d in decisions} != expected:
        raise ValueError('one explicit decision required for each delivered case')
    for d in decisions:
        if d.get('decision') not in {'adopt','reject','defer'}:
            raise ValueError('decision must be adopt/reject/defer')
        for key in ('reason','modeling_change','falsification_change'):
            if not isinstance(d.get(key),str) or not d[key].strip():
                raise ValueError('missing author '+key)
    for key in ('modeling_before','modeling_after','falsification_before','falsification_after','overall_reason'):
        if not isinstance(response.get(key),str) or not response[key].strip():
            raise ValueError('missing author '+key)
    result = {'version':VERSION,'delivery_sha256':digest(raw),'author_response':response,
              'source_overlay_sha256':delivery['binding']['source_overlay']['raw_sha256'],
              'status':'AUTHOR_DECISIONS_RECORDED','content_review':'NOT_PERFORMED',
              'not_proof_of_research_quality':True,'not_market_evidence':True}
    save(target/'use_receipts'/f'{digest(encoded(result))}.json', result)
    save(target/'use_receipt.json',result)
    return result

def require_recorded_use(workspace, report_id):
    target = folder(workspace, report_id)
    if not (target/'delivery.json').exists():
        failure_path = target/'operational_failure.json'
        if failure_path.exists():
            failure = json.loads(failure_path.read_text())
            _verify_binding(workspace, failure['source_overlay'])
            if failure.get('status') == 'A0_OPERATIONALLY_UNAVAILABLE' and failure.get('source_preflight',{}).get('source_compiled_before_knowledge_resolution') is True:
                return {'status':'A0_OPERATIONALLY_UNAVAILABLE','no_adoption_claim':True}
        marker = Path(workspace)/'candidate_startup_experience'/'startup_required.json'
        if marker.exists() and json.loads(marker.read_text()).get('report_id') == report_id:
            raise ValueError('new study requires source-only overlay freeze, then run scripts/run_factorforge_epistemic_source_first_advisory.py --factor-workspace WORKSPACE --report-id REPORT --source-first-overlay OVERLAY --emit-validated-advisory before Step2')
        return {'status':'LEGACY_OR_NO_VALIDATED_SOURCE_DELIVERY'}
    delivery_raw = (target/'delivery.json').read_bytes()
    delivery = json.loads(delivery_raw)
    frozen = json.loads((target/'delivery_binding.json').read_text())
    if frozen['delivery_sha256'] != digest(delivery_raw):
        raise ValueError('stored delivery bytes changed')
    _verify_binding(workspace, delivery['binding']['source_overlay'])
    # Unavailable retrieval is explicitly nonblocking; no adoption is invented.
    if not delivery['cases']:
        return {'status':'NO_DELIVERED_CASES', 'retrieval_status':delivery['retrieval_status']}
    if not (target/'use_receipt.json').exists():
        raise ValueError('pending author decisions: use record_factorforge_startup_experience_use.py from validator output')
    record = json.loads((target/'use_receipt.json').read_text())
    if record.get('delivery_sha256') != digest(delivery_raw):
        raise ValueError('stale author decisions: delivery changed')
    # Revalidate every author field without rewriting the recorded artifact.
    response = record.get('author_response',{})
    if response.get('delivery_sha256') != digest(delivery_raw) or record.get('source_overlay_sha256') != delivery['binding']['source_overlay']['raw_sha256']:
        raise ValueError('stale author source or delivery binding')
    expected = {c['id'] for c in delivery['cases']}
    decisions = response.get('decisions',[])
    if len(decisions)!=len(expected) or {d.get('id') for d in decisions}!=expected:
        raise ValueError('incomplete author decisions')
    for d in decisions:
        if d.get('decision') not in {'adopt','reject','defer'} or any(not isinstance(d.get(k),str) or not d[k].strip() for k in ('reason','modeling_change','falsification_change')):
            raise ValueError('invalid author decision')
    for k in ('modeling_before','modeling_after','falsification_before','falsification_after','overall_reason'):
        if not isinstance(response.get(k),str) or not response[k].strip():
            raise ValueError('incomplete author before/after')
    return {'status':'AUTHOR_DECISIONS_RECORDED','content_review':'NOT_PERFORMED'}


def record_operational_failure(workspace, overlay_path, report_id, error, repo_root):
    """Record a narrow I/O outage after independent native source preflight.

    Integrity/semantic failures are never reclassified. No failed A0 content is
    consumed, and an already delivered packet cannot be erased by an outage.
    """
    import os
    if not isinstance(error, OSError) or os.environ.get('FACTORFORGE_LOCAL_IS_ONLY') != '1':
        raise ValueError('not a local operational I/O outage')
    from factor_factory.epistemic_ultimate_source_first_bridge import (
        validate_native_factor_workspace, _operating_factorforge_root,
        _read_overlay_file, _compile_agent_source_first_overlay,
    )
    workspace=Path(workspace).resolve(strict=True)
    manifest,_,_ = validate_native_factor_workspace(workspace=workspace,
        repo_root=Path(repo_root).resolve(), expected_factorforge_root=_operating_factorforge_root())
    if report_id not in {manifest.get('active_report_id'),manifest.get('root_report_id')}:
        raise ValueError('report not active or root')
    overlay,_,binding = _read_overlay_file(workspace=workspace,
        overlay_path=Path(overlay_path).absolute(),report_id=report_id)
    _,preflight = _compile_agent_source_first_overlay(overlay,report_id=report_id)
    target=folder(workspace,report_id)
    if (target/'delivery.json').exists():
        raise ValueError('existing method delivery retained; cannot bypass author decisions')
    failure={'version':VERSION,'status':'A0_OPERATIONALLY_UNAVAILABLE',
             'phase':'native_source_first_bridge','error_type':type(error).__name__,
             'source_overlay':binding,'source_preflight':preflight,
             'advisory_only':True,'no_adoption_claim':True}
    save(target/'operational_failure.json',failure)
    return failure
