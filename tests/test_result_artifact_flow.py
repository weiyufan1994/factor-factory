"""Synthetic files, real subprocesses/consumers; no market data or research evidence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.code_review_handoff import HandoffError
import factor_factory.code_review_handoff as handoff_module
from skills.factor_forge_step5.modules.evaluator import build_factor_evaluation
from test_factorforge_code_review_handoff import flow_case, _flow, _ready, _write, _now, REPORT, REPO
from test_primary_evaluator_bridge import _payload, _plan


def _native_envelopes(workspace, payload_path):
    identity = dict(report_id=REPORT, factor_id='SYNTHETIC', run_id='fixture_run',
                    source_type='hypothesis', implementation_mode='direct_code',
                    contract_version='synthetic_v1', producer='offline_fixture',
                    spec_hash='a' * 64, code_hash='b' * 64, code_contract_hash='c' * 64,
                    branch_id='fixture')
    base = {**{k: identity[k] for k in ('report_id', 'factor_id', 'run_id', 'producer')},
            'artifact_root': str(workspace), 'status': 'partial', 'verdict': 'PASS'}
    frm = {**base, 'artifact_identity': {**identity, 'artifact_role': 'factor_run_master'},
           'run_status': 'partial', 'evaluation_plan': _plan(), 'output_paths': [str(payload_path)],
           'acceptance_summary': {
               'version': 'factorforge_production_acceptance_summary_v1', **base, 'repo_sha': 'f' * 40,
               'step4': {'self_quant_status': 'not_applicable', 'qlib_native_status': 'not_applicable'},
               'reuse': {'reuse_gate_status': 'not_applicable'},
               'side_effects': {k: False for k in ('clean_data_mutated', 'generated_code_digest_changed',
                                                 'official_record_written', 'search_worker_started')},
           }}
    return {'factor_run_master': frm,
            'factor_run_diagnostics': {'run_status': 'partial', 'output_validation': {'row_count': 2},
                                       'quality_checks': {'sort_order_ok': True}},
            'handoff_to_step5': {**base, 'artifact_identity': {**identity, 'artifact_role': 'handoff_to_step5'},
                                 'recommended_step5_scope': 'partial_scope_only'}}


def _execute(case, name, argv, *, record=True):
    context = {'command': argv, 'cwd': str(REPO), 'manifest': deepcopy(case['manifest'])}
    assert _flow(case).before_command(name, end_step='5', execution_context=context)['status'] == 'RUN'
    started = _now()
    cp = subprocess.run(argv, cwd=REPO, env={**os.environ, 'FACTORFORGE_ROOT': str(case['workspace']),
                         'PYTHONPATH': str(REPO) + os.pathsep + os.environ.get('PYTHONPATH', ''),
                         'FACTORFORGE_RUNTIME_PYTHON': sys.executable, 'FACTORFORGE_LOCAL_IS_ONLY': '1'},
                        capture_output=True, text=True)
    result = dict(name=name, command=argv, cwd=str(REPO), started_at_utc=started, finished_at_utc=_now(),
                  returncode=cp.returncode, status='PASS' if cp.returncode == 0 else 'FAIL',
                  stdout_tail=cp.stdout, stderr_tail=cp.stderr)
    if record:
        _flow(case).record_command(result)
    return context, result


def _run(case, *, legacy=False, file_only=False):
    """Run a tiny producer; current mode goes through Step4's actual adapter process launcher."""
    workspace = case['workspace']
    case['manifest']['step_io']['step4']['outputs'] = {
        'factor_run_master': str(workspace / f'objects/factor_run_master/factor_run_master__{REPORT}.json'),
        'factor_run_diagnostics': str(workspace / f'objects/validation/factor_run_diagnostics__{REPORT}.json'),
        'handoff_to_step5': str(workspace / f'objects/handoff/handoff_to_step5__{REPORT}.json')}
    payload_path = workspace / f'evaluations/{REPORT}/mszq_portfolio/evaluation_payload.json'
    adapter = workspace / 'producer.py'
    payload = _payload({})
    payload.update(status='partial', candidate_decision='JOINT_INFERENCE_UNKNOWN',
                   trial_consumption_status={'consumed': 3, 'remaining': 7})
    adapter.write_text('''import argparse, json, os
from pathlib import Path
from factor_factory.runtime_context import FactorForgeContext
from factor_factory.result_artifacts import prepare_result_paths, write_result_payload
p = argparse.ArgumentParser()
p.add_argument('--report-id'); p.add_argument('--output')
a = p.parse_args()
root = Path(os.environ['FACTORFORGE_ROOT'])
ctx = FactorForgeContext(root, root, root)
slots = prepare_result_paths(ctx, a.report_id, 'mszq_portfolio',
    files={key: key + '.csv' for key in ['daily_nav','trades','monthly_ic','performance','coverage']}
          | {'month_01': 'monthly diagnostics/01.json', 'month_02': 'monthly diagnostics/02.json'},
    directories={'monthly_diagnostics': 'monthly diagnostics'})
for role, raw in slots['artifacts'].items():
    Path(raw).write_text('{}' if raw.endswith('.json') else 'value\\n1\\n')
with (root / 'writer_calls.txt').open('a') as log: log.write('one actual producer invocation\\n')
payload = ''' + repr(payload) + '''
payload.update(artifacts=slots['artifacts'], artifact_directories=slots['artifact_directories'])
''' + ('''payload['artifacts'].pop('month_01'); payload['artifacts'].pop('month_02')
payload['artifacts'].update(payload.pop('artifact_directories'))
Path(a.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
''' if legacy else ('''payload.pop('artifact_directories')
write_result_payload(a.output, payload, base_dir=root)
''' if file_only else '''write_result_payload(a.output, payload, base_dir=root)
''')))
    envelopes = _native_envelopes(workspace, payload_path)
    config = {'backend': 'mszq_portfolio', 'status': 'partial', 'payload_path': str(payload_path),
              'backend_config': {'script_path': str(adapter)}}
    driver = workspace / 'synthetic_step4.py'
    driver.write_text('''import importlib.util, json, subprocess, sys
from pathlib import Path
config = ''' + repr(config) + '''
''' + ('''Path(config['payload_path']).parent.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, config['backend_config']['script_path'], '--report-id', ''' + repr(REPORT) + ''', '--output', config['payload_path']], check=True)
runs = [config]
''' if legacy else '''spec = importlib.util.spec_from_file_location('real_step4', ''' + repr(str(REPO / 'skills/factor-forge-step4/scripts/run_step4.py')) + ''')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
runs, timing = module.write_backend_payloads(''' + repr(REPORT) + ''', [config])
assert runs[0]['status'] == 'partial', runs
''') + '''
envelopes = ''' + repr(envelopes) + '''
envelopes['factor_run_master']['evaluation_results'] = {'backend_runs': runs}
for key, raw in ''' + repr(case['manifest']['step_io']['step4']['outputs']) + '''.items():
    path = Path(raw); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelopes[key]))
''')
    case['request']['helpers'].extend([{'path': str(adapter)}, {'path': str(driver)}])
    request_id = _ready(case)
    context, result = _execute(case, 'run_step4', [sys.executable, '-B', str(driver)], record=False)
    assert result['returncode'] == 0, result['stdout_tail'] + result['stderr_tail']
    proof = workspace / 'original-wrapper-failure.json'
    if legacy:
        with pytest.raises(HandoffError, match='ARTIFACT_FILE_REQUIRED') as error:
            _flow(case).record_command(result)
        manifest_file = workspace / 'manifest.json'
        _write(manifest_file, case['manifest'])
        _write(proof, {'report_id': REPORT, 'status': 'FAIL', 'manifest_path': str(manifest_file),
                      'commands': [result], 'failure': {'command': 'save_code_review_continuation',
                      'actual_command': 'run_step4', 'detail': str(error.value)}})
    else:
        _flow(case).record_command(result)
    return request_id, payload_path, context, proof


def _repair(path):
    original = json.loads(path.read_text())
    files = {k: v for k, v in original['artifacts'].items() if k != 'monthly_diagnostics'}
    root = Path(original['artifacts']['monthly_diagnostics'])
    files.update({f'month_{i:02}': str(root / f'{i:02}.json') for i in (1, 2)})
    repair = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'artifacts': files, 'artifact_directories': {'monthly_diagnostics': str(root)}}
    repair_path = path.parent / 'explicit_reference_repair.json'
    _write(repair_path, repair)
    return repair_path, repair


def _native_validate_and_step5(case):
    _, result = _execute(case, 'validate_step4', [sys.executable, '-B', str(
        REPO / 'skills/factor-forge-step4/scripts/validate_step4.py'), '--report-id', REPORT])
    assert result['returncode'] == 0, result
    assert _flow(case).status()['request']['execution']['4']['status'] == 'complete'
    outputs = case['manifest']['step_io']['step4']['outputs']
    frm = json.loads(Path(outputs['factor_run_master']).read_text())
    evaluation = build_factor_evaluation({'report_id': REPORT, 'workspace_root': str(case['workspace']),
        'objects': {'factor_run_master': frm}, 'paths': outputs})
    assert evaluation['step4_quality_gate']['verdict'] == 'PASS', evaluation
    metrics = evaluation['backend_summary'][0]['key_metrics']
    assert metrics['long_side_sharpe'] == 0.58
    assert metrics['rank_ic_ir'] is None  # No invented unavailable metrics.
    assert evaluation['run_status'] == 'partial'


@pytest.mark.parametrize('file_only', [False, True])
def test_real_producer_step4_validator_step5_and_continuation(flow_case, file_only):
    _, path, context, _ = _run(flow_case, file_only=file_only)
    before = path.read_bytes()
    _native_validate_and_step5(flow_case)
    assert _flow(flow_case).before_command('run_step4', end_step='5', execution_context=context)['status'] == 'REUSE'
    assert path.read_bytes() == before
    assert (flow_case['workspace'] / 'writer_calls.txt').read_text().count('\n') == 1


def test_real_repair_cli_preserves_history_and_requires_fresh_native_validator(flow_case):
    request_id, path, context, proof = _run(flow_case, legacy=True)
    old_execution = deepcopy(_flow(flow_case)._active()['execution']['4'])
    original, original_proof = path.read_bytes(), proof.read_bytes()
    repair_path, repair = _repair(path)
    original_files = {raw: (Path(raw).read_bytes(), Path(raw).stat()) for raw in repair['artifacts'].values()}
    argv = [sys.executable, '-B', str(REPO / 'scripts/manage_factorforge_code_review.py'), 'recover-artifacts',
            '--workspace-root', str(flow_case['workspace']), '--report-id', REPORT,
            '--repo-root', str(REPO), '--request-id', request_id, '--step', '4', '--proof', str(proof),
            '--artifact-repair', str(repair_path), '--reference', 'synthetic real subprocess result']
    cp = subprocess.run(argv, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    recovered = json.loads(cp.stdout)['request']['execution']['4']
    assert recovered['status'] == 'computed' and 'validate_step4' not in recovered
    for key in ('run_step4', 'run_step4_binding', 'pending_invocation', 'pending_artifacts', 'started_at'):
        assert recovered[key] == old_execution[key]
    receipt = recovered['artifact_recovery_history'][-1]['reference_repair']
    assert Path(receipt['preserved_original']['path']).read_bytes() == original
    assert proof.read_bytes() == original_proof
    for raw, (content, stat) in original_files.items():
        assert Path(raw).read_bytes() == content and Path(raw).stat() == stat
    updated = json.loads(path.read_bytes())
    assert {k: v for k, v in updated.items() if k not in ('artifacts', 'artifact_directories')} == {
        k: v for k, v in json.loads(original).items() if k != 'artifacts'}
    assert _flow(flow_case).before_command('run_step4', end_step='5', execution_context=context)['status'] == 'REUSE'
    _native_validate_and_step5(flow_case)
    assert (flow_case['workspace'] / 'writer_calls.txt').read_text().count('\n') == 1


@pytest.mark.parametrize('change,match', [
    ('metric', 'REFERENCE_REPAIR_FIELDS'), ('input', 'ARTIFACT_CHANGED_OR_MISSING'),
    ('output', 'ARTIFACT_CHANGED_AFTER_COMMAND'), ('late_file', 'ARTIFACT_CHANGED_AFTER_COMMAND'),
    ('payload', 'HASH_MISMATCH'), ('file_role', 'EXISTING_FILE_CHANGED'),
    ('undeclared', 'PAYLOAD_NOT_DECLARED|ARTIFACT_FILE_REQUIRED'), ('proof', 'Original wrapper'),
])
def test_repair_rejects_changes_before_any_write(flow_case, change, match):
    request_id, path, _, proof = _run(flow_case, legacy=True)
    repair_path, repair = _repair(path)
    if change == 'metric': repair['long_side_performance'] = {'long_side_sharpe': 99}
    if change == 'input': flow_case['prep'].write_text('{"changed":true}')
    if change == 'output': Path(repair['artifacts']['daily_nav']).write_text('modified after exit')
    if change == 'late_file':
        late = path.parent / 'monthly diagnostics/late.json'
        late.write_text('{}')
        repair['artifacts']['late'] = str(late)
    if change == 'payload': path.write_text(path.read_text() + '\n')
    if change == 'file_role': repair['artifacts']['daily_nav'] = repair['artifacts']['trades']
    if change == 'undeclared':
        other = path.parent / 'undeclared.json'
        other.write_bytes(path.read_bytes())
        repair['path'] = str(other)
    if change == 'proof':
        value = json.loads(proof.read_text()); value['commands'][0]['command'] = ['different writer']
        _write(proof, value)
    _write(repair_path, repair)
    original_journal, original_payload = _flow(flow_case).path.read_bytes(), path.read_bytes()
    with pytest.raises(ValueError, match=match):
        _flow(flow_case).recover_artifacts(request_id, '4', proof_path=proof,
            repair_path=repair_path, reference='synthetic changed-evidence rejection')
    assert _flow(flow_case).path.read_bytes() == original_journal
    assert path.read_bytes() == original_payload


@pytest.mark.parametrize('after_write', [False, True])
def test_interrupted_repair_keeps_original_and_prepared_block(flow_case, monkeypatch, after_write):
    request_id, path, _, proof = _run(flow_case, legacy=True)
    repair_path, _ = _repair(path)
    original = path.read_bytes()
    real_write = handoff_module.write_json_atomic
    def fail_payload_write(target, data):
        if target == path:
            if after_write: real_write(target, data)
            raise OSError('synthetic interrupted atomic metadata write')
        return real_write(target, data)
    monkeypatch.setattr(handoff_module, 'write_json_atomic', fail_payload_write)
    with pytest.raises(OSError, match='interrupted'):
        _flow(flow_case).recover_artifacts(request_id, '4', proof_path=proof,
            repair_path=repair_path, reference='synthetic interruption')
    execution = _flow(flow_case)._active()['execution']['4']
    assert execution['status'] == 'artifacts_blocked'
    attempt = execution['artifact_repair_attempts'][-1]
    assert attempt['status'] == 'prepared'
    assert Path(attempt['preserved_original']['path']).read_bytes() == original
    assert (path.read_bytes() == original) is not after_write
    with pytest.raises(ValueError):
        _flow(flow_case).before_command('run_step4', end_step='5', execution_context={})


@pytest.mark.parametrize('payload_first', [False, True])
@pytest.mark.parametrize('bad_directory', [False, True])
def test_multirole_file_is_counted_once_but_payload_refs_are_expanded(flow_case, payload_first, bad_directory):
    root = flow_case['workspace']
    leaf = root / 'leaf.csv'; leaf.write_text('synthetic data')
    payload = root / 'payload.json'
    _write(payload, {'artifacts': {'leaf': str(root if bad_directory else leaf)}})
    roles = ['backend_payload', 'result'] if payload_first else ['result', 'backend_payload']
    contract = {'paths': [{'path': str(payload), 'key': role, 'direction': 'outputs', 'required': True}
                          for role in roles]}
    if bad_directory:
        with pytest.raises(HandoffError, match='ARTIFACT_FILE_REQUIRED'):
            _flow(flow_case)._capture_artifacts(contract)
    else:
        versions = _flow(flow_case)._capture_artifacts(contract)
        assert set(versions) == {str(payload), str(leaf)}
        leaf.write_text('modified after capture')
        assert _flow(flow_case)._changed_artifacts(versions) == [f'ARTIFACT_CHANGED_OR_MISSING:{leaf}']


def test_native_validator_saves_mismatch_and_directory_errors(flow_case):
    _, path, _, _ = _run(flow_case)
    original = json.loads(path.read_text())
    for invalid in ({**original, 'status': 'success'},
                    {**original, 'artifacts': {'bad_file': str(path.parent)}}):
        _write(path, invalid)
        cp = subprocess.run([sys.executable, '-B', str(REPO / 'skills/factor-forge-step4/scripts/validate_step4.py'),
            '--report-id', REPORT], env={**os.environ, 'FACTORFORGE_ROOT': str(flow_case['workspace']),
            'FACTORFORGE_LOCAL_IS_ONLY': '1'}, capture_output=True, text=True)
        assert cp.returncode == 1 and 'Traceback' not in cp.stderr, cp.stdout + cp.stderr
        revision = json.loads((flow_case['workspace'] /
            f'objects/validation/factor_run_validation_revision__{REPORT}.json').read_text())
        expected = 'BACKEND_STATUS_PAYLOAD_MISMATCH' if invalid['status'] == 'success' else 'BACKEND_RESULT_ARTIFACTS_INVALID'
        assert any(i['code'] == expected for i in revision['issues'])
