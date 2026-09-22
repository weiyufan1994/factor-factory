from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from factor_factory.knowledge_reference import build_knowledge_reference_contract


ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_step6_projection_is_retrievable_by_math_and_operator_without_case_id(tmp_path: Path) -> None:
    step6 = _load(ROOT / 'skills/factor-forge-step6/scripts/run_step6.py', 'step6_projection_test')
    indexer = _load(ROOT / 'scripts/build_factorforge_retrieval_index.py', 'indexer_projection_test')
    iteration = {
        'main_agent_mechanism_memo_ref': {'contract_version': 'factorforge_main_agent_mechanism_memo_v1', 'path': 'objects/research_iteration_master/main_agent_mechanism_memo__R.json'},
        'research_judgment': {'research_memo': {'mechanism_analysis': {'formula_specific_derivation': {
            'mathematical_object': 'unique robust event-pressure projection',
            'observation_mapping': 'unique session-aware residual pressure operator',
            'formula_components': ['event_u', 'robust_z'],
        }}}},
        'evidence_identity': {'step3b_mode_decision_ref': 'objects/handoff/step3b_mode_decision__R.json'},
    }
    projected = step6._knowledge_reuse_projection(iteration)
    assert projected['structured_knowledge_status'].startswith('VALIDATED_MAIN_AGENT')
    runtime = tmp_path / 'workspace'
    record_dir = runtime / 'objects/research_knowledge_base'
    record_dir.mkdir(parents=True)
    record = {
        'report_id': 'R', 'factor_id': 'unrelated_factor_name', 'decision': 'iterate',
        'success_patterns': [], 'failure_patterns': ['unique residual-pressure failure'],
        'modification_hypotheses': ['candidate only'], 'factor_family': 'price_volume',
        'monetization_model': 'constraint', 'bias_type': 'none',
        'return_source_hypothesis': 'unique event-pressure mechanism',
        'expected_failure_regimes': [], 'objective_constraint_dependency': 'unique session constraint',
        'constraint_sources': [], 'reuse_constraints': ['same factor only'],
        'source_identity': {}, 'evidence_identity': {}, 'source_case_identity': {},
        'artifact_identity': {}, 'knowledge_scope': 'same_factor', 'created_at_utc': '2026-09-08T00:00:00Z',
        **projected,
    }
    (record_dir / 'knowledge_record__R.json').write_text(json.dumps(record), encoding='utf-8')
    indexer.refresh_retrieval_index(runtime)
    result = build_knowledge_reference_contract(
        repo_root=ROOT,
        knowledge_root=runtime / 'knowledge',
        query_text='robust event-pressure projection session-aware residual pressure operator',
        producer='test', top_k=1, retrieval_required=True,
    )
    assert result['retrieved_case_ids'] == ['knowledge_record::R']
    doc = result['retrieved_cases'][0]
    assert doc['mathematical_object'] == 'unique robust event-pressure projection'
    assert doc['reusable_operator']['observation_mapping'] == 'unique session-aware residual pressure operator'
    assert doc['implementation_references'] == ['objects/handoff/step3b_mode_decision__R.json']
