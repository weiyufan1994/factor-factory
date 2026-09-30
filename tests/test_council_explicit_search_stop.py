import copy
import importlib.util
import sys
from pathlib import Path

import pytest


def trigger(iteration):
    path = Path(__file__).resolve().parents[1] / 'scripts/run_factorforge_ultimate.py'
    spec = importlib.util.spec_from_file_location('ultimate_search_stop_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.council_auto_trigger(iteration)


def stopped_iteration():
    return {
        'research_judgment': {
            'decision': 'iterate',
            'research_memo': {
                'revision_strategy': {'revision_needed': True},
                'program_search_policy': {'decision': 'stop_search_no_new_branch_authorized'},
                'researcher_agent_memo': {'revision_brief_to_step3b': {'should_modify': False}},
            },
        },
        'loop_action': {
            'should_modify_step3b': False,
            'next_runner': 'stop',
            'loop_authorization': 'advisory_only',
            'parallel_exploration_branches': [],
        },
    }


@pytest.mark.parametrize('decision', ['iterate', 'needs_human_review'])
def test_explicit_empty_search_stop_does_not_dispatch_council(decision):
    iteration = stopped_iteration()
    iteration['research_judgment']['decision'] = decision
    assert trigger(iteration) == (False, 'explicit_advisory_search_stop')


@pytest.mark.parametrize('field,value', [
    ('should_modify_step3b', True),
    ('next_runner', 'step3b'),
    ('parallel_exploration_branches', ['proposal']),
])
def test_contradictory_or_active_revision_keeps_council_review(field, value):
    iteration = copy.deepcopy(stopped_iteration())
    iteration['loop_action'][field] = value
    assert trigger(iteration)[0] is True


def test_advisory_alone_does_not_disable_council():
    iteration = stopped_iteration()
    iteration['research_judgment']['research_memo'].pop('program_search_policy')
    assert trigger(iteration)[0] is True


def test_evidence_block_still_takes_precedence():
    iteration = stopped_iteration()
    iteration['research_judgment']['research_memo']['evidence_audit'] = {'evidence_verdict': 'blocked'}
    assert trigger(iteration) == (False, 'evidence_blocked')
