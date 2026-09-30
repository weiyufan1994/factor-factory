import importlib.util
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step6/scripts/run_step6.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('authored_partial_iterate_test', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('mutation,expected', [
    ('none', 'iterate'), ('journal_conflict', 'needs_human_review'),
    ('missing_author', 'needs_human_review'), ('branch', 'needs_human_review'),
    ('hosted', 'needs_human_review'), ('failed', 'needs_human_review'),
    ('reject', 'reject'), ('promote_official', 'promote_official'),
])
def test_partial_judgment_is_concordant_local_and_nonexecuting(module, monkeypatch, mutation, expected):
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    bundle = {
        'factor_case_master': {'final_status': 'partial'},
        'factor_evaluation': {'evaluation_status': 'partial'},
        'factor_run_master': {'run_status': 'partial'},
    }
    memo = {
        'researcher_decision': 'iterate',
        'revision_brief_to_step3b': {'should_modify': False},
        'program_search_policy': {'decision': 'stop_search_no_new_branch_authorized'},
    }
    journal = {'reflection': {'current_decision': 'iterate'}}
    decision = 'needs_human_review'
    if mutation == 'journal_conflict':
        journal['reflection']['current_decision'] = 'reject'
    elif mutation == 'missing_author':
        memo.pop('researcher_decision')
    elif mutation == 'branch':
        memo['revision_brief_to_step3b']['should_modify'] = True
    elif mutation == 'hosted':
        monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    elif mutation == 'failed':
        bundle['factor_run_master']['run_status'] = 'failed'
    elif mutation in {'reject', 'promote_official'}:
        decision = mutation
    assert module.preserve_authored_partial_iterate(decision, bundle, memo, journal) == expected


def test_real_partial_bundle_preserves_final_stop(monkeypatch):
    """Opt-in read-only replay; never executes a backend or writes artifacts."""
    root = os.getenv('FACTORFORGE_PARTIAL_REPLAY_WORKSPACE')
    report = os.getenv('FACTORFORGE_PARTIAL_REPLAY_REPORT')
    if not root or not report:
        pytest.skip('requires explicit existing partial diagnostic workspace')
    monkeypatch.setenv('FACTORFORGE_ROOT', root)
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    path = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step6/scripts/run_step6.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('partial_bundle_replay', path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    bundle = mod.load_required_inputs(report)
    payloads = mod.load_backend_payloads(report, bundle['factor_run_master'])
    result = mod.build_iteration_payload(bundle, payloads)
    assert result['research_judgment']['decision'] == 'iterate'
    loop = result['loop_action']
    assert loop['loop_authorization'] == 'advisory_only'
    assert loop['should_modify_step3b'] is False
    assert loop['parallel_exploration_branches'] == []
    assert loop['next_runner'] == 'stop'
    strategy = result['research_judgment']['research_memo']['revision_strategy']
    assert strategy['loop_authorization'] == 'advisory_only'
