"""Offline consumer/maintenance tests; synthetic research proofs, no factor run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from factor_factory.advisory_runtime import configured_advisory_root, read_visible_experience
from factor_factory.knowledge_reference import build_knowledge_reference_contract, resolve_runtime_retrieval_index
from factor_factory.workspace_experience_export import export_workspace_knowledge_record
from scripts.build_factorforge_retrieval_index import (
    CorpusBuildError, active_research_notes, refresh_retrieval_index,
)
import scripts.run_factorforge_ultimate as ultimate

REPO = Path(__file__).resolve().parents[1]
QUERY = 'liquidity shock residual inventory'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


def note(root, note_id='SYNTHETIC', **updates):
    data = {
        'note_version': 'factorforge_research_note_v1', 'note_id': note_id,
        'report_id': note_id, 'factor_id': 'SYNTHETIC_FACTOR', 'decision': None,
        'source_identity': {'report_id': note_id, 'source_refs': ['synthetic-source']},
        'evidence_class': 'SYNTHETIC_TEST_ONLY', 'advisory_only': True,
        'canonical_promotion_allowed': False, 'formal_step6_completed': False,
        'return_source_hypothesis': QUERY, 'validity_status': 'active',
        **updates,
    }
    return write(root / 'knowledge/因子工厂/research_notes' / f'{note_id}.json', data)


def refresh(root):
    return refresh_retrieval_index(root, project_root=root)


def index(root):
    return root / 'knowledge/retrieval/factorforge_retrieval_index.jsonl'


def load_step(number):
    name = {1: 'standardize_step1_research_fields', 2: 'run_step2', 6: 'run_step6'}[number]
    path = REPO / f'skills/factor-forge-step{number}/scripts/{name}.py'
    spec = importlib.util.spec_from_file_location(f'advisory_step{number}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_step6_validator(monkeypatch):
    path = REPO / 'skills/factor-forge-step6/scripts/validate_step6.py'
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('advisory_step6_validator', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def aim():
    return {'final_factor': {'name': 'Fresh source only', 'economic_logic': QUERY},
            'research_discipline': {'economic_hypothesis': {'claim': QUERY},
                                    'math_hypothesis_candidates': ['independent source object']}}


def step6_context(module):
    return module.build_retrieval_context({
        'factor_run_master': {'report_id': 'NEW', 'factor_id': 'NEW'},
        'factor_case_master': {'lessons': [QUERY], 'next_actions': []},
    }, {})


def contract(root):
    return build_knowledge_reference_contract(
        repo_root=REPO, retrieval_index=resolve_runtime_retrieval_index(REPO),
        query_text=QUERY, producer='synthetic_consumer',
    )


@pytest.fixture
def private(tmp_path, monkeypatch):
    for key in os.environ:
        if key.startswith('FACTORFORGE_'):
            monkeypatch.delenv(key, raising=False)
    root = tmp_path / 'private'
    root.mkdir()
    monkeypatch.setenv('FACTORFORGE_ADVISORY_ROOT', str(root))
    monkeypatch.setenv('FACTORFORGE_LOCAL_IS_ONLY', '1')
    monkeypatch.setenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL', '1')
    monkeypatch.setenv('FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT', '1')
    return root


def test_actual_step1_step2_step6_consume_selected_library(private, monkeypatch):
    note(private)
    refresh(private)
    before = aim()
    enriched = load_step(1).attach_factor_knowledge_context(before)
    assert before == aim()  # Source interpretation is not rewritten by lookup.
    first = enriched['knowledge_reference_contract']
    assert 'research_note::SYNTHETIC' in first['retrieved_case_ids']
    second = load_step(2).build_step2_research_contract(
        {'report_id': 'NEW', 'factor_id': 'NEW', 'raw_formula_text': 'rank(close)'}, {}, enriched, {},
    )['knowledge_reference_contract']
    assert 'research_note::SYNTHETIC' in second['retrieved_case_ids']
    step6 = load_step(6)
    monkeypatch.setattr(step6, 'embed_query', lambda _: pytest.fail('network/legacy embedding must not run'))
    last = step6_context(step6)
    assert last['retrieval_index_path'] == str(index(private))
    assert any(x['report_id'] == 'SYNTHETIC' for x in last['similar_cases'])
    assert last['embedding_endpoint'] is None


def test_workspace_override_and_protected_scope_precedence(private, tmp_path, monkeypatch):
    note(private)
    refresh(private)
    workspace = tmp_path / 'workspace'
    note(workspace, 'WORKSPACE')
    refresh(workspace)
    monkeypatch.setenv('FACTORFORGE_FACTOR_WORKSPACE', str(workspace))
    assert resolve_runtime_retrieval_index(REPO) == index(workspace)
    index(workspace).write_text('broken')
    assert contract(private)['retrieval_status'] == 'unavailable'
    assert not any(x.get('report_id') == 'SYNTHETIC' for x in contract(private)['retrieved_cases'])
    missing = tmp_path / 'explicit-missing.jsonl'
    monkeypatch.setenv('FACTORFORGE_RETRIEVAL_INDEX', str(missing))
    assert resolve_runtime_retrieval_index(REPO) == missing
    assert contract(private)['retrieval_status'] == 'unavailable'
    monkeypatch.delenv('FACTORFORGE_RETRIEVAL_INDEX')
    monkeypatch.delenv('FACTORFORGE_FACTOR_WORKSPACE')
    monkeypatch.setenv('FACTORFORGE_OOS_HOST_INSTALLATION_ID', 'protected')
    assert configured_advisory_root() is None
    assert resolve_runtime_retrieval_index(REPO) == index(REPO)
    monkeypatch.delenv('FACTORFORGE_OOS_HOST_INSTALLATION_ID')
    monkeypatch.setenv('FACTORFORGE_ULTIMATE_RUN', '1')
    monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    assert configured_advisory_root() is None
    assert load_step(6).RETRIEVAL_INDEX == index(REPO)


@pytest.mark.parametrize('failure', ['missing', 'malformed', 'dangling_link', 'bad_manifest'])
def test_configured_bad_channel_has_no_seed_fallback(private, failure):
    if failure != 'missing':
        note(private)
        refresh(private)
        if failure == 'malformed':
            index(private).write_text('{bad')
        elif failure == 'dangling_link':
            index(private).unlink()
            index(private).symlink_to(private / 'missing')
        else:
            index(private).with_name('factorforge_retrieval_manifest.json').write_text('{bad')
    result = contract(private)
    assert result['retrieval_status'] == 'unavailable'
    assert result['index_paths_checked'] == [str(index(private))]
    assert all(x.get('doc_type') != 'knowledge_record' for x in result['retrieved_cases'])
    # A broken experience channel does not remove the public graph lane.
    assert result['graph_indexes_available']
    assert not step6_context(load_step(6))['retrieval_index_readable']


def revision(source, filename='revision.json', **changes):
    parent = json.loads(source.read_bytes())
    data = {**parent, **changes}
    changed = sorted(k for k in set(data) | set(parent)
                     if k != 'research_note_revision' and data.get(k) != parent.get(k))
    data['research_note_revision'] = {
        'supersedes_file': source.name, 'supersedes_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'changed_fields': changed, 'reason': 'Synthetic correction, not a research finding',
    }
    return write(source.with_name(filename), data)


def test_note_revision_withdrawal_and_stale_step2_carry(private):
    source = note(private, note_revision='HUMAN_R1')
    original = source.read_bytes()
    refresh(private)
    step1 = load_step(1)
    carried = step1.attach_factor_knowledge_context(aim())
    newer = revision(source, return_source_hypothesis=QUERY + ' revised',
                     source_identity={'report_id': 'SYNTHETIC', 'source_refs': ['synthetic-source', 'new-reference']})
    assert active_research_notes(source.parent)[0][0] == newer
    assert contract(private)['retrieval_status'] == 'unavailable'  # New source, old index.
    refresh(private)
    assert read_visible_experience(index(private))[0][0]['search_text'].startswith(QUERY + ' revised')
    revision(newer, 'withdrawal.json', validity_status='withdrawn', invalidation_reason='Synthetic withdrawal')
    assert contract(private)['retrieval_status'] == 'unavailable'
    refresh(private)
    assert read_visible_experience(index(private))[0] == []
    second = load_step(2).build_step2_research_contract(
        {'report_id': 'NEW', 'factor_id': 'NEW', 'raw_formula_text': 'rank(close)'}, {}, carried, {},
    )
    assert 'research_note::SYNTHETIC' not in second['knowledge_reference_contract']['retrieved_case_ids']
    assert not any('SYNTHETIC' in text for text in second['similar_case_lessons_imported'])
    assert not step6_context(load_step(6))['similar_cases']
    assert source.read_bytes() == original


@pytest.mark.parametrize('bad', ['missing_parent', 'wrong_hash', 'self', 'fork', 'identity', 'undeclared', 'duplicate', 'source_rewrite'])
def test_invalid_revision_keeps_old_files_but_old_cache_is_unavailable(private, bad):
    source = note(private)
    refresh(private)
    original_index = index(private).read_bytes()
    newer = revision(source, return_source_hypothesis=QUERY + ' revision')
    data = json.loads(newer.read_bytes())
    if bad == 'missing_parent':
        data['research_note_revision']['supersedes_file'] = 'missing.json'
    elif bad == 'wrong_hash':
        data['research_note_revision']['supersedes_sha256'] = '0' * 64
    elif bad == 'self':
        data['research_note_revision']['supersedes_file'] = newer.name
    elif bad == 'fork':
        revision(source, 'other.json', return_source_hypothesis='another fork')
    elif bad == 'identity':
        data['note_id'] = 'DIFFERENT'
        data['research_note_revision']['changed_fields'].append('note_id')
    elif bad == 'source_rewrite':
        data['source_identity']['report_id'] = 'DIFFERENT'
        data['research_note_revision']['changed_fields'].append('source_identity')
    elif bad == 'undeclared':
        data['failure_patterns'] = ['undeclared text']
    else:
        write(source.with_name('duplicate.json'), json.loads(source.read_bytes()))
    write(newer, data)
    with pytest.raises(CorpusBuildError):
        refresh(private)
    assert index(private).read_bytes() == original_index
    assert contract(private)['retrieval_status'] == 'unavailable'
    assert not step6_context(load_step(6))['similar_cases']


def test_step6_handoff_owner_acceptance_and_next_real_consumer(private, tmp_path, monkeypatch):
    workspace = tmp_path / 'research'
    source = write(workspace / 'objects/research_knowledge_base/knowledge_record__PRIOR.json', {
        'report_id': 'PRIOR', 'factor_id': 'PRIOR', 'return_source_hypothesis': QUERY,
        'decision': 'iterate', 'advisory_only': True,
    })
    proof = {'status': 'PASS', 'execution_scope': 'local_is_only',
             'formal_command_contract': {'satisfied': True},
             'commands': [{'name': name, 'status': 'PASS', 'returncode': 0}
                          for name in ('run_step6', 'validate_step6')]}
    proof_before, source_before = copy.deepcopy(proof), source.read_bytes()
    monkeypatch.setattr(ultimate, 'REPO_ROOT', tmp_path / 'code')
    args = argparse.Namespace(report_id='PRIOR', dry_run=False, local_is_only=True)
    result = ultimate.run_post_step6_knowledge_refresh_nonblocking(args=args, proof=proof, factor_workspace=workspace)
    handoff = result['workspace_experience_export']
    assert handoff['status'] == 'PENDING_REVIEW'
    assert handoff['dispatch_status'] == 'NOT_DISPATCHED'
    assert handoff['acceptance_status'] == 'NOT_ACCEPTED'
    assert not list(private.rglob('*')) and not (tmp_path / 'code').exists()
    again = ultimate.run_post_step6_knowledge_refresh_nonblocking(args=args, proof=proof, factor_workspace=workspace)
    assert again['workspace_experience_export']['write_status'] == 'IDEMPOTENT'
    # Explicit simulated owner acceptance, never an automatic research write.
    assert hashlib.sha256(Path(handoff['source_path']).read_bytes()).hexdigest() == handoff['source_sha256']
    accepted = export_workspace_knowledge_record(workspace=workspace, repo_root=private, report_id='PRIOR')
    assert export_workspace_knowledge_record(workspace=workspace, repo_root=private, report_id='PRIOR')['status'] == 'IDEMPOTENT'
    refresh(private)
    assert accepted['path'].startswith(str(private))
    assert 'knowledge_record::PRIOR' in load_step(1).attach_factor_knowledge_context(aim())['knowledge_reference_contract']['retrieved_case_ids']
    assert any(x['report_id'] == 'PRIOR' for x in step6_context(load_step(6))['similar_cases'])
    assert proof == proof_before and source.read_bytes() == source_before
    skipped = ultimate.run_post_step6_knowledge_refresh_nonblocking(
        args=args, proof={**proof, 'contract_smoke_only': True}, factor_workspace=workspace)
    assert skipped['status'] == 'SKIPPED'


@pytest.mark.parametrize('smoke,dry_run', [(False, False), (True, False), (False, True)])
def test_real_recovery_cli_keeps_candidates_local(private, tmp_path, smoke, dry_run):
    workspace = tmp_path / 'recovery'
    proof = write(workspace / 'objects/runtime_context/ultimate_run_report__RID.json', {
        'execution_scope': 'local_is_only', 'status': 'FAIL', 'dry_run': dry_run,
        'contract_smoke_only': smoke,
        'commands': [{'name': 'run_step2', 'status': 'FAIL', 'returncode': 1}],
    })
    before = proof.read_bytes()
    completed = subprocess.run([
        sys.executable, str(REPO / 'scripts/maintain_factorforge_knowledge.py'),
        '--workspace-root', str(workspace), '--report-id', 'RID',
    ], check=True, capture_output=True, text=True,
       env={**os.environ, 'PYTHONPATH': str(REPO), 'PYTHONDONTWRITEBYTECODE': '1'})
    result = json.loads(completed.stdout)
    assert not list(private.rglob('*'))
    assert proof.read_bytes() == before
    if smoke or dry_run:
        assert result['status'] == 'SKIPPED'
        assert not (workspace / 'knowledge/research_episodes').exists()
    else:
        assert result['export_status'] == 'PENDING_REVIEW'
        rows, _ = read_visible_experience(index(workspace))
        assert rows[0]['doc_type'] == 'research_episode'


def test_semantic_visible_ids_current_text_and_episode_exclusion(private, monkeypatch):
    from factor_factory import semantic_knowledge_retrieval as semantic
    source = note(private)
    refresh(private)
    rows, _ = read_visible_experience(index(private))
    encoder_calls = []
    def fake_encoder(texts):
        encoder_calls.append(texts)
        return [[1.0, 0.0] for _ in texts]
    monkeypatch.delenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL')
    monkeypatch.setattr(semantic, 'configured_encoder', lambda _: fake_encoder)
    config = index(private).with_name('semantic_config.json')
    write(config, {'enabled': True, 'model_id': semantic.MODEL_ID, 'model_path': 'unused-test-double'})
    semantic.build_semantic_index(rows + [{'id': 'INVISIBLE', 'search_text': QUERY}], fake_encoder,
                                  index(private).with_name('factorforge_semantic_index.json'))
    state = step6_context(load_step(6))['semantic_retrieval']
    assert {row['id'] for row in state['hits']} == {'research_note::SYNTHETIC'}
    revision(source, return_source_hypothesis=QUERY + ' changed')
    refresh(private)
    state = step6_context(load_step(6))['semantic_retrieval']
    assert not state['semantic_used'] and state['fallback'] == 'stale_source_text'
    assert any(x['report_id'] == 'SYNTHETIC' for x in step6_context(load_step(6))['similar_cases'])
    episode = {'id': 'EPISODE', 'doc_type': 'research_episode', 'search_text': QUERY, 'report_id': 'OLD'}
    module = load_step(6)
    monkeypatch.setattr(module, 'load_retrieval_docs', lambda: [episode])
    state = step6_context(module)['semantic_retrieval']
    assert not state['hits']  # An operational episode never becomes a dense method prior.


def test_note_handoff_never_claims_completed_step6(private, tmp_path):
    from factor_factory.research_knowledge_maintenance import create_pending_review_handoff
    workspace = tmp_path / 'note-workspace'
    source = note(workspace)
    raw = source.read_bytes()
    result = create_pending_review_handoff(
        workspace=workspace, source=source, report_id='SYNTHETIC', doc_type='research_note')
    assert result['formal_step6_completed'] is False
    assert result['status'] == 'PENDING_REVIEW' and result['acceptance_status'] == 'NOT_ACCEPTED'
    assert result['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert source.read_bytes() == raw and not list(private.rglob('*'))
    with pytest.raises(ValueError, match='identity'):
        create_pending_review_handoff(workspace=workspace, source=source, report_id='OTHER', doc_type='research_note')


def test_planned_commands_do_not_produce_episode(private, tmp_path):
    from factor_factory.research_knowledge_maintenance import record_local_research_episode
    workspace = tmp_path / 'planned'
    workspace.mkdir()
    result = record_local_research_episode(
        proof={'commands': [{'name': 'x', 'status': 'DRY_RUN', 'returncode': 0}]},
        workspace=workspace, repo_root=REPO, report_id='PLAN', dry_run=False, local_is_only=True)
    assert result['status'] == 'SKIPPED'
    assert not list(workspace.iterdir()) and not list(private.iterdir())


def test_authored_step2_invalidates_old_advisory_without_rewriting_source(private):
    source = note(private)
    refresh(private)
    authored = load_step(1).attach_factor_knowledge_context(aim())
    authored['local_agent_spec_inputs'] = {}
    authored['research_discipline'].update({
        'market_process_thesis': {'economic_hypothesis': 'Independently authored mechanism'},
        'target_statistic_hint': 'Authored target', 'step1_mathematical_object': {'kind': 'authored'},
        'expected_failure_modes': ['Independent falsification'],
        'innovative_idea_seeds': ['Independent idea'],
        'reuse_instruction_for_future_agents': ['Keep the source boundary'],
    })
    before = copy.deepcopy(authored)
    step2 = load_step(2)
    first = step2.build_step2_research_contract({}, {}, authored, {})
    assert 'research_note::SYNTHETIC' in first['knowledge_reference_contract']['retrieved_case_ids']
    revision(source, validity_status='withdrawn', invalidation_reason='Synthetic withdrawal')
    result = step2.build_step2_research_contract({}, {}, authored, {})
    assert not result['similar_case_lessons_imported']
    assert result['knowledge_reference_contract']['retrieval_status'] == 'unavailable'
    assert result['economic_mechanism'] == 'Independently authored mechanism'
    assert result['expected_failure_modes'] == ['Independent falsification']
    assert authored == before


def test_copied_static_index_cannot_bind_an_old_checkout(private, tmp_path):
    import shutil
    original = tmp_path / 'old-checkout'
    note(original)
    refresh(original)
    index(private).parent.mkdir(parents=True)
    shutil.copyfile(index(original), index(private))
    shutil.copyfile(index(original).with_name('factorforge_retrieval_manifest.json'),
                    index(private).with_name('factorforge_retrieval_manifest.json'))
    assert 'source_root_mismatch' in contract(private)['fallback_reason']


def test_real_graph_and_semantic_experience_share_unchanged_total_budget(private, monkeypatch):
    """Real packaged graph + consumer code; only the encoder is a test double."""
    from factor_factory import semantic_knowledge_retrieval as semantic
    for suffix in ['A', 'B', 'C']:
        note(private, 'SYNTHETIC_' + suffix)
    refresh(private)
    rows, _ = read_visible_experience(index(private))
    encoder = lambda texts: [[1.0, 0.0] for _ in texts]
    monkeypatch.delenv('FACTORFORGE_DISABLE_EMBEDDING_RETRIEVAL')
    monkeypatch.delenv('FACTORFORGE_DISABLE_GRAPH_KNOWLEDGE_CONTEXT')
    monkeypatch.setattr(semantic, 'configured_encoder', lambda _: encoder)
    write(index(private).with_name('semantic_config.json'),
          {'enabled': True, 'model_id': semantic.MODEL_ID, 'model_path': 'unused-test-double'})
    semantic.build_semantic_index(rows, encoder, index(private).with_name('factorforge_semantic_index.json'))
    query = ('盘中反复出现的正向价格与成交异常累积成每日收盘状态，可能反映分批交易尚未完成的压力并与下一交易日至一周的价格变化有关。'
             '只有匿名价量观测，无法识别交易者，且真实无事件与观测缺失同时存在。已有研究能提供哪些累积状态和时序压缩的类比、'
             '与未完成交易解释相竞争的反例，以及区分有符号价格方向和波动、处理零事件与缺失的测量提醒？'
             '尚无可交易账户或收益结果，只求知识提醒与可提议的区分性检验。')
    module = load_step(6)
    result = module.build_retrieval_context({
        'factor_run_master': {'report_id': 'CURRENT_SYNTHETIC', 'factor_id': 'KB_CONSUMER_ONLY_PROBE'},
        'factor_case_master': {'lessons': [query], 'next_actions': []},
    }, {}, top_k=5)
    selected = result['similar_cases']
    experiences = [item for item in selected if item['doc_type'] == 'research_note']
    graphs = [item for item in selected if item['doc_type'] == 'factor_knowledge_graph_node']
    assert result['semantic_retrieval']['semantic_used']
    assert len(selected) == 5 and len(experiences) == 3 and len(graphs) == 2
    assert min(item['score'] for item in graphs) > max(item['score'] for item in experiences)


@pytest.mark.parametrize('field,value', [
    ('research_variant', 'original_baseline'),
    ('paper_replication_status', 'full_paper_replication'),
    ('reported_research_recommendation', 'promote_official'),
])
def test_note_prose_correction_cannot_relabel_historical_research(private, field, value):
    source = note(private, research_variant='source_extension',
                  paper_replication_status='not_paper_replication', reported_research_recommendation='reject')
    refresh(private)
    revision(source, **{field: value})
    with pytest.raises(CorpusBuildError, match='identity or authority'):
        refresh(private)
    assert contract(private)['retrieval_status'] == 'unavailable'


@pytest.mark.parametrize('flexible', [True, False])
@pytest.mark.parametrize('state', ['changed', 'refresh_failed', 'withdrawn', 'current', 'declined', 'undeclared', 'unbound', 'unrelated_binding'])
def test_actual_iteration_producer_rechecks_authored_import_source(private, tmp_path, monkeypatch, flexible, state):
    """Real memo loader, index reader, retrieval, learning and iteration producer.

    Economics/evaluation/revision builders below are stubs: this is not a
    factor run or economic review. They must not mask the actual import path.
    """
    source = note(private)
    refresh(private)
    reference = load_step(1).attach_factor_knowledge_context(aim())['knowledge_reference_contract']
    learning = {
        'transferable_patterns': ['INDEPENDENT_AUTHORED_PATTERN'],
        'anti_patterns': ['INDEPENDENT_AUTHORED_COUNTEREXAMPLE'],
        'innovative_idea_seeds': ['INDEPENDENT_AUTHORED_IDEA'],
        'reuse_instruction_for_future_agents': ['INDEPENDENT_AUTHORED_REUSE'],
        'similar_case_lessons_imported': [] if state == 'declined' else ['HISTORICAL_IMPORTED_PROSE'],
        'similar_case_lessons_absence_reason': 'Author explicitly declines this retrieved analogy.',
    }
    authored = {'learning_and_innovation': learning, 'economic_logic': 'INDEPENDENT_ECONOMIC_LOGIC',
                'next_research_tests': ['INDEPENDENT_FALSIFIER']}
    if state == 'undeclared':
        learning.pop('similar_case_lessons_imported')
        learning.pop('similar_case_lessons_absence_reason')
    if state not in {'unbound', 'unrelated_binding'}:
        authored['knowledge_reference_contract'] = reference
    module = load_step(6)
    monkeypatch.setattr(module, 'OBJ', tmp_path / 'workspace/objects')
    memo_path = write(module.OBJ / 'research_iteration_master/researcher_memo__CURRENT.json', authored)
    memo_bytes = memo_path.read_bytes()
    if state in {'changed', 'refresh_failed', 'withdrawn'}:
        child = revision(source, validity_status='withdrawn', invalidation_reason='Synthetic withdrawal')
        if state == 'refresh_failed':
            invalid = json.loads(child.read_bytes())
            invalid['research_note_revision']['supersedes_sha256'] = '0' * 64
            write(child, invalid)
            with pytest.raises(CorpusBuildError):
                refresh(private)
        elif state == 'withdrawn':
            refresh(private)
    monkeypatch.setattr(module, 'load_researcher_journal', lambda _: {})
    monkeypatch.setattr(module, 'load_window_evidence', lambda _: pytest.fail('producer must not read OOS'))
    monkeypatch.setattr(module, 'decide', lambda *_: 'reject')
    monkeypatch.setattr(module, 'local_reviewers_agree_to_reject', lambda *_: False)
    monkeypatch.setattr(module, 'derive_strengths_weaknesses', lambda *_: ([], [], [], []))
    monkeypatch.setattr(module, 'extract_headline_metrics', lambda *_: {})
    monkeypatch.setattr(module, 'summarize_window_evidence', lambda _: ([], []))
    monkeypatch.setattr(module, 'infer_research_framework', lambda *_: {
        'factor_family': 'other', 'monetization_model': 'mixed', 'bias_type': 'other',
        'return_source_hypothesis': 'INDEPENDENT_ECONOMIC_LOGIC', 'expected_failure_regimes': [],
        'objective_constraint_dependency': 'none', 'constraint_sources': [],
        'crowding_risk': 'unknown', 'capacity_constraints': 'unknown', 'implementation_risk': 'unknown',
        'improvement_frontier': [], 'program_search_axes': [], 'review_checklist': [],
        'research_commentary': [], 'revision_principles': [],
    })
    monkeypatch.setattr(module, 'build_research_memo', lambda *a, **k: {
        'economic_logic': copy.deepcopy(k['authored_memo']['economic_logic']), 'evidence_quality': {'notes': []},
    })
    for name in ['build_evidence_status', 'build_formula_understanding', 'build_math_discipline_review',
                 'build_experience_chain', 'build_diversity_position', 'build_evidence_audit',
                 'build_mechanism_analysis', 'build_formula_specific_derivation',
                 'validate_mechanism_formula_consistency', 'build_case_comparison']:
        monkeypatch.setattr(module, name, lambda *a, **k: {})
    monkeypatch.setattr(module, 'build_metric_interpretation', lambda *_: {'verdict': 'inconclusive', 'long_side_adoption_review': {}})
    monkeypatch.setattr(module, 'build_revision_taxonomy', lambda *_: {'macro_revision': {}, 'micro_revision': {}, 'expression_revision': {}, 'portfolio_revision': {'forbidden': True}})
    monkeypatch.setattr(module, 'build_revision_strategy', lambda *_: {'revision_needed': False, 'loop_authorization': 'advisory_only', 'revision_quality': 'not_needed', 'primary_failure_signature': 'none'})
    monkeypatch.setattr(module, 'build_search_policy_decision', lambda *_: {'branch_templates': [], 'recommended_mode': 'kill', 'human_approval_required': False, 'selection_rationale': []})
    monkeypatch.setattr(module, 'should_write_step3b_handoff', lambda *_: False)
    bundle = {
        'factor_run_master': {'report_id': 'CURRENT', 'factor_id': 'CURRENT', 'run_status': 'complete',
                             'evaluation_results': {'backend_runs': []}, 'evaluation_plan': {}, 'artifact_identity': {}},
        'factor_case_master': {'factor_id': 'CURRENT', 'final_status': 'rejected', 'lessons': [QUERY]},
        'factor_evaluation': {}, 'handoff_to_step6': {},
        'factor_spec_master': {'research_contract': {
            'research_compatibility_profile': 'factorforge_ordinary_local_is_flexible_v1' if flexible else None}},
        'paths': {'handoff_to_step6': 'synthetic-handoff.json'},
    }
    if state == 'unrelated_binding':
        bundle['handoff_to_step6']['knowledge_reference_contract'] = reference
    result = module.build_iteration_payload(bundle, {})
    current = result['research_judgment']['research_memo']
    actual = current['learning_and_innovation']
    if state == 'current':
        assert actual['similar_case_lessons_imported'] == ['HISTORICAL_IMPORTED_PROSE']
        assert actual['advisory_import_status'] == 'CURRENT_SOURCE_VERSION'
    elif state == 'declined':
        assert actual['similar_case_lessons_imported'] == []
        assert actual['similar_case_lessons_absence_reason'] == learning['similar_case_lessons_absence_reason']
        assert actual['advisory_import_status'] == 'AUTHOR_IMPORTED_NONE'
    elif state == 'undeclared':
        assert actual['similar_case_lessons_imported'] == []
        assert actual['advisory_import_status'] == 'AUTHOR_IMPORT_NOT_DECLARED'
    else:
        assert actual['similar_case_lessons_imported'] == []
        assert actual['advisory_import_status'] == 'UNVERIFIED_OR_STALE_SOURCE_NOT_CURRENT'
        assert 'HISTORICAL_IMPORTED_PROSE' not in json.dumps(result['knowledge_writeback']['learning_and_innovation'])
    assert current['economic_logic'] == 'INDEPENDENT_ECONOMIC_LOGIC'
    assert current['researcher_agent_memo']['learning_and_innovation'] == learning
    if flexible:
        assert actual['transferable_patterns'] == learning['transferable_patterns']
        assert actual['anti_patterns'] == learning['anti_patterns']
        assert actual['innovative_idea_seeds'] == learning['innovative_idea_seeds']
    assert memo_path.read_bytes() == memo_bytes
    assert load_step6_validator(monkeypatch).learning_list_state_valid(
        actual, 'similar_case_lessons_imported', flexible)


@pytest.mark.parametrize('boundary', ['other_key', 'unconfigured', 'hosted', 'missing_reason', 'missing_status', 'unknown_status'])
def test_optional_advisory_absence_does_not_relax_other_validation(private, monkeypatch, boundary):
    validator = load_step6_validator(monkeypatch)
    key = 'similar_case_lessons_imported'
    value = {key: [], 'similar_case_lessons_absence_reason': 'Source no longer current.',
             'advisory_import_status': 'UNVERIFIED_OR_STALE_SOURCE_NOT_CURRENT'}
    if boundary == 'other_key':
        key = 'transferable_patterns'
        value.update({key: [], key + '_absence_reason': 'Cannot bypass required authorship.'})
    elif boundary == 'unconfigured':
        monkeypatch.delenv('FACTORFORGE_ADVISORY_ROOT')
    elif boundary == 'hosted':
        monkeypatch.setenv('FACTORFORGE_ULTIMATE_RUN', '1')
        monkeypatch.delenv('FACTORFORGE_LOCAL_IS_ONLY')
    elif boundary == 'missing_reason':
        value.pop('similar_case_lessons_absence_reason')
    elif boundary == 'missing_status':
        value.pop('advisory_import_status')
    else:
        value['advisory_import_status'] = 'UNKNOWN_STATUS'
    assert not validator.learning_list_state_valid(value, key, False)
