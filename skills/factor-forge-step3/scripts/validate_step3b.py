#!/usr/bin/env python3
import argparse, json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
CODE = FF / 'generated_code'
RUNS = FF / 'runs'

from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    global FF, OBJ, CODE, RUNS
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    OBJ = FF / 'objects'
    CODE = FF / 'generated_code'
    RUNS = FF / 'runs'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    return manifest, manifest_report_id(manifest)


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def assert_step2_context(label: str, ctx: dict):
    assert isinstance(ctx, dict), f'{label}.step2_research_context must be a dict'
    for key in [
        'target_statistic',
        'economic_mechanism',
        'expected_failure_modes',
        'reuse_instruction_for_future_agents',
        'implementation_invariants',
    ]:
        assert ctx.get(key), f'{label}.step2_research_context.{key} is required'
    assert isinstance(ctx.get('expected_failure_modes'), list), (
        f'{label}.step2_research_context.expected_failure_modes must be a list'
    )
    assert isinstance(ctx.get('reuse_instruction_for_future_agents'), list), (
        f'{label}.step2_research_context.reuse_instruction_for_future_agents must be a list'
    )
    for key in ['target_statistic', 'economic_mechanism']:
        assert not str(ctx.get(key)).startswith('missing_'), (
            f'{label}.step2_research_context.{key} still carries a missing_* sentinel; rerun Step2 first'
        )


def assert_no_step4_outputs_in_step3b(first_run_outputs: dict, code_dir: Path, meta: dict | None = None) -> None:
    """Step3B may prove factor-value executability, but it must not perform Step4 evaluation."""
    forbidden_tokens = [
        'evaluation_payload',
        'factor_run_master',
        'factor_run_diagnostics',
        'factor_evaluation',
        'self_quant',
        'qlib_backtest',
        'rank_ic',
        'pearson_ic',
        'quantile_nav',
        'quantile_returns',
        'long_short_nav',
        'portfolio_value',
        'benchmark_vs_strategy',
        'turnover_timeseries',
    ]
    for raw_path in first_run_outputs.get('output_paths') or []:
        text = str(raw_path)
        assert not any(token in text for token in forbidden_tokens), (
            f'Step3B first_run_outputs contains Step4-only artifact path: {text}'
        )
    if meta:
        assert meta.get('producer') == 'step3b_first_run', (
            f'run_metadata.producer must be step3b_first_run, got {meta.get("producer")}'
        )
        note = str(meta.get('boundary_note') or '')
        assert 'Step4 owns' in note, 'run_metadata must document Step3B/Step4 boundary'

    if code_dir.exists():
        forbidden_files = [
            path for path in code_dir.iterdir()
            if path.is_file() and any(token in path.name for token in forbidden_tokens)
        ]
        assert not forbidden_files, (
            'Step3B generated_code directory contains Step4-only artifacts: '
            + ', '.join(str(path.name) for path in forbidden_files)
        )
    for key in ['expected_failure_modes', 'reuse_instruction_for_future_agents']:
        assert not any(str(item).startswith('missing_') for item in ctx.get(key, [])), (
            f'{label}.step2_research_context.{key} still carries a missing_* sentinel; rerun Step2 first'
        )


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    a = ap.parse_args()
    _manifest, manifest_rid = apply_runtime_manifest(a.manifest)
    rid = a.report_id or manifest_rid
    if not rid:
        raise SystemExit('validate_step3b.py requires --report-id or --manifest')

    impl = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{rid}.json'
    handoff = OBJ / 'handoff' / f'handoff_to_step4__{rid}.json'
    prep_path = OBJ / 'data_prep_master' / f'data_prep_master__{rid}.json'
    stub = CODE / rid / f'factor_impl_stub__{rid}.py'
    real_impl = CODE / rid / f'factor_impl__{rid}.py'
    qlib = CODE / rid / f'qlib_expression_draft__{rid}.json'
    hybrid = CODE / rid / f'hybrid_execution_scaffold__{rid}.json'

    data = load(impl)
    h = load(handoff)
    prep = load(prep_path)
    qlib_data = load(qlib)
    hybrid_data = load(hybrid)
    expected_step3a_ready = prep.get('feasibility') in {'ready', 'proxy_ready'}
    assert data.get('report_id') == rid, f'implementation_plan_master.report_id mismatch: expected {rid}, got {data.get("report_id")}'
    assert h.get('report_id') == rid, f'handoff_to_step4.report_id mismatch: expected {rid}, got {h.get("report_id")}'
    assert prep.get('report_id') == rid, f'data_prep_master.report_id mismatch: expected {rid}, got {prep.get("report_id")}'
    assert data['implementation_mode'] in {'direct_python', 'qlib_operator', 'hybrid'}
    assert stub.exists()
    assert qlib.exists()
    assert hybrid.exists()
    assert handoff.exists()
    assert isinstance(h.get('local_input_paths'), dict), 'handoff_to_step4.local_input_paths must be explicit even when blocked'
    assert h.get('step3a_ready') is expected_step3a_ready, (
        f'handoff_to_step4.step3a_ready mismatch: expected {expected_step3a_ready}, '
        f"got {h.get('step3a_ready')}"
    )
    assert h.get('step3b_ready') is True, 'handoff_to_step4 must preserve step3b_ready'
    assert h.get('data_prep_master_ref'), 'handoff_to_step4 must preserve Step 3A data_prep_master reference'
    assert h.get('qlib_adapter_config_ref'), 'handoff_to_step4 must preserve Step 3A qlib_adapter_config reference'
    assert h.get('factor_spec_master_ref'), 'handoff_to_step4 must preserve factor_spec_master reference'
    if real_impl.exists():
        assert h.get('factor_impl_ref'), 'handoff_to_step4 should prefer real factor_impl when it exists'
    assert_step2_context('implementation_plan_master', data.get('step2_research_context'))
    assert_step2_context('handoff_to_step4', h.get('step2_research_context'))
    assert_step2_context('qlib_expression_draft', qlib_data.get('step2_research_context'))
    assert_step2_context('hybrid_execution_scaffold', hybrid_data.get('step2_research_context'))
    assert data.get('step2_research_context') == h.get('step2_research_context'), (
        'Step 3B must pass the same Step2 research context from plan into handoff'
    )

    txt = stub.read_text(encoding='utf-8')
    assert 'STEP2_RESEARCH_CONTEXT' in txt, 'factor implementation stub must expose Step2 research context for IDE review'
    assert 'target_statistic:' in txt, 'factor implementation stub must include Step2 target_statistic'
    for bad in ['TODO', 'TO_BE_FILLED', 'placeholder']:
        assert bad not in txt

    # Business acceptance upgrade: if Step 3A already prepared local execution snapshots,
    # Step 3B should not stop at a plan-only pass.
    local_inputs = h.get('local_input_paths') or {}
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    input_mode = str(local_inputs.get('input_mode') or '')
    if (minute_rel and daily_rel) or (input_mode == 'daily_only' and daily_rel):
        run_dir = FF / 'runs' / rid
        factor_parquet = run_dir / f'factor_values__{rid}.parquet'
        factor_csv = run_dir / f'factor_values__{rid}.csv'
        meta_json = run_dir / f'run_metadata__{rid}.json'
        assert factor_parquet.exists() or factor_csv.exists(), 'Step 3B requires first-run factor_values when local snapshots exist'
        assert meta_json.exists(), 'Step 3B requires run_metadata when local snapshots exist'
        run_meta = load(meta_json)
        assert_step2_context('run_metadata', run_meta.get('step2_research_context'))
        assert_no_step4_outputs_in_step3b(data.get('first_run_outputs') or h.get('first_run_outputs') or {}, code_dir, run_meta)
        first_run_outputs = data.get('first_run_outputs') or h.get('first_run_outputs')
        assert isinstance(first_run_outputs, dict), 'Step 3B schema must expose first_run_outputs when local snapshots exist'
        assert first_run_outputs.get('status') in {'ready', 'partial', 'pending'}
        if first_run_outputs.get('status') == 'ready':
            assert first_run_outputs.get('output_paths'), 'ready first_run_outputs must carry output_paths'
            assert first_run_outputs.get('run_metadata_path'), 'ready first_run_outputs must carry run_metadata_path'
            assert_no_step4_outputs_in_step3b(first_run_outputs, code_dir, run_meta)
    else:
        first_run_outputs = data.get('first_run_outputs') or h.get('first_run_outputs') or {}
        assert first_run_outputs.get('status') in {None, 'pending'}, 'Step 3B should stay pending when no executable local snapshots exist'

    print('RESULT: PASS')
