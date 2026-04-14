#!/usr/bin/env python3
import argparse, json
from pathlib import Path

WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
OBJ = WORKSPACE / 'factorforge' / 'objects'
CODE = WORKSPACE / 'factorforge' / 'generated_code'


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    report_id = args.report_id

    prep_path = OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    qlib_path = OBJ / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    impl_path = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'

    prep = load(prep_path)
    qcfg = load(qlib_path)
    impl = load(impl_path)
    handoff = load(handoff_path)

    assert prep.get('report_id') == report_id, f'data_prep_master.report_id mismatch: expected {report_id}, got {prep.get("report_id")}'
    assert qcfg.get('report_id') == report_id, f'qlib_adapter_config.report_id mismatch: expected {report_id}, got {qcfg.get("report_id")}'
    assert impl.get('report_id') == report_id, f'implementation_plan_master.report_id mismatch: expected {report_id}, got {impl.get("report_id")}'
    assert handoff.get('report_id') == report_id, f'handoff_to_step4.report_id mismatch: expected {report_id}, got {handoff.get("report_id")}'

    assert prep['feasibility'] in {'ready', 'proxy_ready', 'blocked'}
    assert isinstance(prep['data_sources'], list) and prep['data_sources']
    assert 'sample_window' in prep and 'start' in prep['sample_window'] and 'end' in prep['sample_window']
    assert 'logical_fields' in qcfg and 'close' in qcfg['logical_fields']
    assert 'qlib_field_map' in qcfg and '$close' in qcfg['qlib_field_map']
    assert qcfg.get('instrument_field') in {'ts_code', 'instrument'}, 'qlib adapter must declare instrument field explicitly'
    assert qcfg.get('date_field') in {'trade_date', 'datetime'}, 'qlib adapter must declare date field explicitly'

    impl_mode = impl.get('implementation_mode') or impl.get('preferred_execution_mode')
    assert impl_mode in {'direct_python', 'qlib_operator', 'hybrid'}
    if 'calculation_steps' in impl:
        assert isinstance(impl.get('calculation_steps'), list) and impl['calculation_steps']
    if 'code_artifacts' in impl:
        assert isinstance(impl.get('code_artifacts'), dict) and impl['code_artifacts']
    if 'step4_contract' in impl:
        assert impl['step4_contract'].get('execution_mode') == impl_mode

    if handoff.get('step3a_ready') is not None:
        assert handoff.get('step3a_ready') is True
    if handoff.get('step3b_ready') is not None:
        assert handoff.get('step3b_ready') is True
    if handoff.get('execution_mode') is not None:
        assert handoff.get('execution_mode') == impl_mode
    assert isinstance(prep.get('local_input_paths'), dict) and prep['local_input_paths']
    minute_rel = prep['local_input_paths'].get('minute_df_parquet') or prep['local_input_paths'].get('minute_df_csv')
    daily_rel = prep['local_input_paths'].get('daily_df_csv') or prep['local_input_paths'].get('daily_df_parquet')
    assert minute_rel and (WORKSPACE / minute_rel).exists(), 'missing local input snapshot: minute_df_(parquet/csv)'
    assert daily_rel and (WORKSPACE / daily_rel).exists(), 'missing local input snapshot: daily_df_(csv/parquet)'

    # Step 3A must not silently package a full-minute snapshot together with a tiny sample daily layer.
    import pandas as pd
    minute_path = WORKSPACE / minute_rel
    daily_path = WORKSPACE / daily_rel
    minute_df = pd.read_parquet(minute_path, columns=['ts_code']) if minute_path.suffix.lower() == '.parquet' else pd.read_csv(minute_path, usecols=['ts_code'])
    daily_df = pd.read_parquet(daily_path, columns=['ts_code']) if daily_path.suffix.lower() == '.parquet' else pd.read_csv(daily_path, usecols=['ts_code'])
    minute_tickers = int(minute_df['ts_code'].nunique())
    daily_tickers = int(daily_df['ts_code'].nunique())
    assert minute_tickers > 0 and daily_tickers > 0, 'local input snapshots must have positive ticker coverage'
    coverage_ratio = min(minute_tickers, daily_tickers) / max(minute_tickers, daily_tickers)
    assert coverage_ratio >= 0.5, f'inconsistent local input scope: minute_tickers={minute_tickers}, daily_tickers={daily_tickers}'

    code_dir = CODE / report_id
    if 'code_artifacts' in impl:
        for key in ['python_stub', 'qlib_expression_draft', 'hybrid_execution_scaffold']:
            rel = impl['code_artifacts'][key]
            assert (code_dir / rel).exists()

    for p in [prep_path, qlib_path, impl_path, handoff_path]:
        text = p.read_text(encoding='utf-8')
        for bad in ['TODO', 'TO_BE_FILLED', 'placeholder', 'PLACEHOLDER', '待补']:
            assert bad not in text

    print('RESULT: PASS')
