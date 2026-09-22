from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _module():
    script_dir = Path(__file__).resolve().parents[1] / 'skills/factor-forge-step6/scripts'
    sys.path.insert(0, str(script_dir))
    try:
        path = script_dir / 'validate_step6.py'
        spec = importlib.util.spec_from_file_location('step6_local_terminal_protocol_gate', path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _terminal_iteration() -> dict:
    return {
        'research_judgment': {
            'decision': 'reject',
            'research_memo': {
                'decision_source': {
                    'source': 'concordant_authored_local_researcher_and_independent_review',
                    'decision': 'reject',
                    'promotion_allowed': False,
                    'automatic_revision_allowed': False,
                },
                'local_is_authority_boundary': {
                    'execution_status': 'step6_local_is_review_completed',
                    'factor_verdict': 'NOT_ISSUED',
                    'official_promotion_allowed': False,
                    'oos_access_allowed': False,
                    'original_quantitative_decision': 'reject',
                },
            },
        },
        'loop_action': {
            'should_modify_step3b': False,
            'loop_authorization': 'advisory_only',
            'next_runner': 'stop',
            'requires_human_approval_before_code_change': False,
            'modification_targets': [],
            'parallel_exploration_branches': [],
            'search_methods': [],
        },
    }


def test_local_terminal_reject_uses_pre_council_without_inventing_revision(tmp_path):
    module = _module()
    assert module.protocol_validation_stage(
        _terminal_iteration(),
        module.RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
        tmp_path / 'handoff.json',
    ) == 'pre_council'


def test_terminal_exception_rejects_iteration_or_handoff_near_misses(tmp_path):
    module = _module()
    iteration = _terminal_iteration()
    iteration['loop_action']['should_modify_step3b'] = True
    assert module.protocol_validation_stage(
        iteration,
        module.RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
        tmp_path / 'handoff.json',
    ) == 'pre_revision'

    iteration = _terminal_iteration()
    handoff = tmp_path / 'handoff.json'
    handoff.write_text('{}', encoding='utf-8')
    assert module.protocol_validation_stage(
        iteration,
        module.RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
        handoff,
    ) == 'pre_revision'


def test_hosted_and_promotion_paths_remain_strict(tmp_path):
    module = _module()
    iteration = _terminal_iteration()
    assert module.protocol_validation_stage(
        iteration,
        module.RESEARCH_PROTOCOL_SCOPE_HOSTED,
        tmp_path / 'handoff.json',
    ) == 'pre_revision'

    iteration['research_judgment']['decision'] = 'promote_official'
    assert module.protocol_validation_stage(
        iteration,
        module.RESEARCH_PROTOCOL_SCOPE_LOCAL_IS,
        tmp_path / 'handoff.json',
    ) == 'pre_promotion'


def test_no_human_approval_is_limited_to_authenticated_local_terminal_without_actions(
    monkeypatch, tmp_path
):
    module = _module()
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    strategy = {
        'revision_needed': False,
        'revision_hypotheses': [],
        'terminal_local_rejection': True,
    }
    policy = {'branch_templates': [], 'human_approval_required': False}
    iteration = _terminal_iteration()
    assert module.local_terminal_reject_without_actions(
        iteration, tmp_path / 'handoff.json', strategy, policy
    )

    strategy['revision_needed'] = True
    assert not module.local_terminal_reject_without_actions(
        iteration, tmp_path / 'handoff.json', strategy, policy
    )
    strategy['revision_needed'] = False
    policy['branch_templates'] = [{'branch_id': 'future'}]
    assert not module.local_terminal_reject_without_actions(
        iteration, tmp_path / 'handoff.json', strategy, policy
    )
    policy['branch_templates'] = []
    iteration['loop_action']['modification_targets'] = ['future revision']
    assert not module.local_terminal_reject_without_actions(
        iteration, tmp_path / 'handoff.json', strategy, policy
    )


def test_no_human_approval_exception_never_applies_to_hosted_terminal(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY', raising=False)
    assert not module.local_terminal_reject_without_actions(
        _terminal_iteration(),
        tmp_path / 'handoff.json',
        {
            'revision_needed': False,
            'revision_hypotheses': [],
            'terminal_local_rejection': True,
        },
        {'branch_templates': [], 'human_approval_required': False},
    )
