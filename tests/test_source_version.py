"""Offline source-archive identity and narrow native-validator recovery."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from factor_factory.source_version import current_source_commit, verify_source_archive, write_source_archive_version
from test_factorforge_code_review_handoff import flow_case, _flow, _write, REPO, REPORT
import test_result_artifact_flow as vertical

ANCHORS = ['factor_factory/runtime_context.py', 'skills/factor-forge-step4/scripts/run_step4.py']
COMMIT = 'c' * 40  # Synthetic build record only; never used for a real release.


def test_archive_version_is_explicit_and_checks_its_files(tmp_path, monkeypatch):
    for name in ANCHORS:
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# synthetic archive\n')
    write_source_archive_version(tmp_path, COMMIT, ANCHORS)
    elsewhere = tmp_path / 'other cwd'; elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv('FACTORFORGE_ADMITTED_ENGINE_COMMIT', 'd' * 40)
    assert current_source_commit(tmp_path) == COMMIT
    with pytest.raises(FileExistsError): write_source_archive_version(tmp_path, COMMIT, ANCHORS)
    (tmp_path / ANCHORS[0]).write_text('changed')
    with pytest.raises(ValueError, match='FILE_CHANGED'): current_source_commit(tmp_path)


def test_unmarked_archive_never_uses_a_parent_git_repository(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    archive = tmp_path / 'archive'; archive.mkdir()
    assert current_source_commit(archive) == 'unknown'


def test_version_paths_and_commit_do_not_guess(tmp_path):
    with pytest.raises(ValueError, match='ABSOLUTE_ROOT'):
        current_source_commit(Path('relative-repository'))
    with pytest.raises(ValueError, match='COMMIT_INVALID'):
        write_source_archive_version(tmp_path, 'c' * 41, ANCHORS)


def _failed_native_version(case, monkeypatch):
    # A synthetic historical assembly selects this exact source through an
    # explicit release alias; all producer source hashes are real.
    release = case['workspace'] / 'synthetic release'; release.mkdir()
    (release / 'factor-factory').symlink_to(REPO, target_is_directory=True)
    assembly = release / 'assembly.json'
    _write(assembly, {'release': str(release), 'framework_commit': COMMIT,
        'archive_source': 'git archive ' + COMMIT,
        'files': {'factor-factory/' + name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in ANCHORS}})
    original_envelopes = vertical._native_envelopes
    def unknown_envelopes(*args):
        envelopes = original_envelopes(*args)
        envelopes['factor_run_master']['acceptance_summary']['repo_sha'] = 'unknown'
        return envelopes
    monkeypatch.setattr(vertical, '_native_envelopes', unknown_envelopes)
    request, payload, context, _ = vertical._run(case)
    _, result = vertical._execute(case, 'validate_step4', [sys.executable, '-B', str(
        REPO / 'skills/factor-forge-step4/scripts/validate_step4.py'), '--report-id', REPORT])
    assert result['returncode'] == 1, result
    revision = json.loads((case['workspace'] / f'objects/validation/factor_run_validation_revision__{REPORT}.json').read_text())
    assert [i['code'] for i in revision['issues']] == ['BLOCK_ACCEPTANCE_SUMMARY_REPO_IDENTITY_INVALID']
    manifest = case['workspace'] / 'runtime_manifest.json'; _write(manifest, case['manifest'])
    proof = case['workspace'] / 'original_validator_failure.json'
    _write(proof, {'report_id': REPORT, 'status': 'FAIL', 'manifest_path': str(manifest),
                  'commands': [result], 'failure': {'command': 'validate_step4', 'returncode': 1}})
    return request, assembly, proof, payload, context


def test_version_recovery_cli_then_native_validation_without_recomputing(flow_case, monkeypatch):
    request, assembly, proof, payload, context = _failed_native_version(flow_case, monkeypatch)
    previous = deepcopy(_flow(flow_case)._active()['execution']['4'])
    run_path = Path(flow_case['manifest']['step_io']['step4']['outputs']['factor_run_master'])
    original_run, original_payload, original_proof = run_path.read_bytes(), payload.read_bytes(), proof.read_bytes()
    revision_path = flow_case['workspace'] / f'objects/validation/factor_run_validation_revision__{REPORT}.json'
    original_revision = revision_path.read_bytes()
    command = [sys.executable, '-B', str(REPO / 'scripts/manage_factorforge_code_review.py'), 'recover-source-version',
        '--workspace-root', str(flow_case['workspace']), '--report-id', REPORT, '--repo-root', str(REPO),
        '--request-id', request, '--proof', str(proof), '--release-record', str(assembly),
        '--reference', 'synthetic real native validator failure']
    original_journal = _flow(flow_case).path.read_bytes()
    cp = subprocess.run(command + ['--dry-run'], capture_output=True, text=True)
    assert cp.returncode == 0 and json.loads(cp.stdout)['writes_performed'] is False, cp.stdout + cp.stderr
    assert _flow(flow_case).path.read_bytes() == original_journal and run_path.read_bytes() == original_run
    cp = subprocess.run(command, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    execution = json.loads(cp.stdout)['request']['execution']['4']
    history = execution['source_version_recovery_history'][-1]
    assert execution['status'] == 'computed' and 'validate_step4' not in execution
    assert history['failed_validator'] == previous['validate_step4']
    assert history['failed_validator_binding'] == previous['validate_step4_binding']
    assert execution['run_step4'] == previous['run_step4'] and execution['run_step4_binding'] == previous['run_step4_binding']
    assert Path(history['preserved_original']['path']).read_bytes() == original_run
    expected = json.loads(original_run); expected['acceptance_summary']['repo_sha'] = COMMIT
    assert json.loads(run_path.read_bytes()) == expected
    assert payload.read_bytes() == original_payload and proof.read_bytes() == original_proof
    assert _flow(flow_case).before_command('run_step4', end_step='5', execution_context=context)['status'] == 'REUSE'
    vertical._native_validate_and_step5(flow_case)
    assert json.loads(revision_path.read_bytes())['verdict'] == 'PASS'
    saved_revision = Path(history['preserved_validation']['path']).read_bytes()
    assert saved_revision == original_revision
    assert json.loads(saved_revision)['issues'][0]['code'] == 'BLOCK_ACCEPTANCE_SUMMARY_REPO_IDENTITY_INVALID'
    assert (flow_case['workspace'] / 'writer_calls.txt').read_text().count('\n') == 1


@pytest.mark.parametrize('change', ['input', 'metrics', 'source_hash', 'release_path', 'late_record', 'other_error', 'proof'])
def test_version_recovery_rejects_unrelated_or_changed_evidence(flow_case, monkeypatch, change):
    request, assembly, proof, payload, _ = _failed_native_version(flow_case, monkeypatch)
    if change == 'input': flow_case['prep'].write_text('changed input')
    if change == 'metrics':
        value = json.loads(payload.read_text()); value['ic_summary']['rank_ic_mean'] = 99; _write(payload, value)
    if change in ('source_hash', 'release_path', 'late_record'):
        value = json.loads(assembly.read_text())
        if change == 'source_hash': value['files']['factor-factory/' + ANCHORS[0]] = '0' * 64
        if change == 'release_path': value['release'] = '/unrelated'
        _write(assembly, value)
    if change == 'other_error':
        path = flow_case['workspace'] / f'objects/validation/factor_run_validation_revision__{REPORT}.json'
        value = json.loads(path.read_text()); value['issues'].append({'severity': 'error', 'code': 'MISSING_METRICS'}); _write(path, value)
    if change == 'proof':
        value = json.loads(proof.read_text()); value['commands'][0]['command'] = ['different']; _write(proof, value)
    original_journal = _flow(flow_case).path.read_bytes()
    original_run = Path(flow_case['manifest']['step_io']['step4']['outputs']['factor_run_master']).read_bytes()
    with pytest.raises(ValueError):
        _flow(flow_case).recover_source_version(request, proof_path=proof, release_record=assembly, reference='synthetic rejection')
    assert _flow(flow_case).path.read_bytes() == original_journal
    assert Path(flow_case['manifest']['step_io']['step4']['outputs']['factor_run_master']).read_bytes() == original_run
