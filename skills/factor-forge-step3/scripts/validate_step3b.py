#!/usr/bin/env python3
import argparse, json
from pathlib import Path

W = Path('/home/ubuntu/.openclaw/workspace')
FF = W / 'factorforge'
OBJ = FF / 'objects'
CODE = FF / 'generated_code'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    a = ap.parse_args()
    rid = a.report_id

    impl = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{rid}.json'
    handoff = OBJ / 'handoff' / f'handoff_to_step4__{rid}.json'
    stub = CODE / rid / f'factor_impl_stub__{rid}.py'
    real_impl = CODE / rid / f'factor_impl__{rid}.py'
    qlib = CODE / rid / f'qlib_expression_draft__{rid}.json'
    hybrid = CODE / rid / f'hybrid_execution_scaffold__{rid}.json'

    data = load(impl)
    h = load(handoff)
    assert data.get('report_id') == rid, f'implementation_plan_master.report_id mismatch: expected {rid}, got {data.get("report_id")}'
    assert h.get('report_id') == rid, f'handoff_to_step4.report_id mismatch: expected {rid}, got {h.get("report_id")}'
    assert data['implementation_mode'] in {'direct_python', 'qlib_operator', 'hybrid'}
    assert stub.exists()
    assert qlib.exists()
    assert hybrid.exists()
    assert handoff.exists()
    assert h.get('local_input_paths'), 'handoff_to_step4 must carry Step 3A local inputs for Step 4 consumption'
    if real_impl.exists():
        assert h.get('factor_impl_ref'), 'handoff_to_step4 should prefer real factor_impl when it exists'

    txt = stub.read_text(encoding='utf-8')
    for bad in ['TODO', 'TO_BE_FILLED', 'placeholder']:
        assert bad not in txt

    # Business acceptance upgrade: if Step 3A already prepared local execution snapshots,
    # Step 3B should not stop at a plan-only pass.
    local_inputs = h.get('local_input_paths') or {}
    minute_rel = local_inputs.get('minute_df_parquet') or local_inputs.get('minute_df_csv')
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    if minute_rel and daily_rel:
        run_dir = FF / 'runs' / rid
        factor_parquet = run_dir / f'factor_values__{rid}.parquet'
        factor_csv = run_dir / f'factor_values__{rid}.csv'
        meta_json = run_dir / f'run_metadata__{rid}.json'
        assert factor_parquet.exists() or factor_csv.exists(), 'Step 3B requires first-run factor_values when local snapshots exist'
        assert meta_json.exists(), 'Step 3B requires run_metadata when local snapshots exist'

        first_run_outputs = data.get('first_run_outputs') or h.get('first_run_outputs')
        assert isinstance(first_run_outputs, dict), 'Step 3B schema must expose first_run_outputs when local snapshots exist'
        assert first_run_outputs.get('status') in {'ready', 'partial', 'pending'}
        if first_run_outputs.get('status') == 'ready':
            assert first_run_outputs.get('output_paths'), 'ready first_run_outputs must carry output_paths'
            assert first_run_outputs.get('run_metadata_path'), 'ready first_run_outputs must carry run_metadata_path'

    print('RESULT: PASS')
