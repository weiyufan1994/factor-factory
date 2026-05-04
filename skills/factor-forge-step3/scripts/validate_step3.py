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
WORKSPACE = FF.parent
OBJ = FF / 'objects'
CODE = FF / 'generated_code'

from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id


def apply_runtime_manifest(manifest_path: str | None) -> tuple[dict | None, str | None]:
    global FF, WORKSPACE, OBJ, CODE
    if not manifest_path:
        return None, None
    manifest = load_runtime_manifest(manifest_path)
    FF = manifest_factorforge_root(manifest)
    WORKSPACE = FF.parent
    OBJ = FF / 'objects'
    CODE = FF / 'generated_code'
    os.environ['FACTORFORGE_ROOT'] = str(FF)
    return manifest, manifest_report_id(manifest)


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id')
    ap.add_argument('--manifest', help='Runtime context manifest built by the skill/agent orchestrator.')
    args = ap.parse_args()
    _manifest, manifest_rid = apply_runtime_manifest(args.manifest)
    report_id = args.report_id or manifest_rid
    if not report_id:
        raise SystemExit('validate_step3.py requires --report-id or --manifest')

    prep_path = OBJ / 'data_prep_master' / f'data_prep_master__{report_id}.json'
    qlib_path = OBJ / 'data_prep_master' / f'qlib_adapter_config__{report_id}.json'
    impl_path = OBJ / 'implementation_plan_master' / f'implementation_plan_master__{report_id}.json'
    handoff_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'

    prep = load(prep_path)
    qcfg = load(qlib_path)
    impl = load(impl_path)
    handoff = load(handoff_path)
    expected_step3a_ready = prep['feasibility'] in {'ready', 'proxy_ready'}

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
        assert handoff.get('step3a_ready') is expected_step3a_ready, (
            f'handoff_to_step4.step3a_ready mismatch: expected {expected_step3a_ready}, '
            f"got {handoff.get('step3a_ready')}"
        )
    if handoff.get('step3b_ready') is not None:
        assert handoff.get('step3b_ready') is True
    if handoff.get('execution_mode') is not None:
        assert handoff.get('execution_mode') == impl_mode
    assert isinstance(prep.get('local_input_paths'), dict)
    data_api_resolution = prep.get('data_api_resolution')
    assert isinstance(data_api_resolution, dict), 'data_prep_master.data_api_resolution is required for all Step3A outputs'
    assert qcfg.get('data_api_resolution') == data_api_resolution, 'qlib_adapter_config.data_api_resolution must match data_prep_master'
    assert handoff.get('data_api_resolution') == data_api_resolution, 'handoff_to_step4.data_api_resolution must match data_prep_master'
    status = data_api_resolution.get('status')
    assert status, 'data_api_resolution.status is required'
    assert status in {'ready', 'missing_dataset', 'missing_fields', 'catalog_absent_legacy_shared_clean_fallback'}, f'unsupported data_api_resolution.status={status}'
    daily_resolution = data_api_resolution.get('daily_resolution')
    assert isinstance(daily_resolution, dict), 'data_api_resolution.daily_resolution is required'
    assert daily_resolution.get('dataset_id') == 'clean_daily_bar', 'Step3A daily leg must resolve clean_daily_bar'
    minute_resolution = data_api_resolution.get('minute_resolution')
    if data_api_resolution.get('required_minute_fields'):
        assert isinstance(minute_resolution, dict), 'minute/high-frequency Step3A must include minute_resolution'
        assert minute_resolution.get('dataset_id') == 'minute_bar', 'minute/high-frequency Step3A must resolve minute_bar'

    if prep['feasibility'] in {'ready', 'proxy_ready'}:
        assert status in {'ready', 'catalog_absent_legacy_shared_clean_fallback'}, (
            f'non-blocked Step3A requires ready or explicit catalog-absent fallback, got {status}'
        )
    if status == 'ready':
        assert isinstance(data_api_resolution.get('resolved_fields'), dict) and data_api_resolution['resolved_fields'], 'ready Data API resolution must include resolved_fields'
        assert prep.get('local_input_paths', {}).get('snapshot_source') == 'factorforge_data_api', 'ready Data API resolution must drive the local snapshot source'
        daily_meta_rel = prep.get('local_input_paths', {}).get('daily_input_meta') or prep.get('local_input_paths', {}).get('daily_input_meta_json')
        assert daily_meta_rel and (WORKSPACE / daily_meta_rel).exists(), 'ready Data API resolution must write daily_input_meta'
        if minute_resolution:
            minute_meta_rel = prep.get('local_input_paths', {}).get('minute_input_meta') or prep.get('local_input_paths', {}).get('minute_input_meta_json')
            assert minute_meta_rel and (WORKSPACE / minute_meta_rel).exists(), 'ready minute Data API resolution must write minute_input_meta'
    if status in {'missing_dataset', 'missing_fields'}:
        req_ref = prep.get('data_requirement_ref')
        assert req_ref, 'missing Data API resolution must carry data_requirement_ref'
        assert qcfg.get('data_requirement_ref') == req_ref, 'qlib_adapter_config must carry matching data_requirement_ref'
        assert handoff.get('data_requirement_ref') == req_ref, 'handoff_to_step4 must carry matching data_requirement_ref'
        assert handoff.get('step3a_ready') is False, 'missing Data API resolution must set handoff_to_step4.step3a_ready=false'
        req_path = OBJ / 'data_requirements' / req_ref
        assert req_path.exists(), f'missing data requirement object: {req_path}'
        requirement = load(req_path)
        assert requirement.get('type') == 'factorforge_data_requirement', 'data requirement must use factorforge_data_requirement type'
        assert requirement.get('resolution') == data_api_resolution, 'data requirement must embed the exact Step3A data_api_resolution'
        assert prep.get('feasibility') == 'blocked', 'missing Data API fields/dataset must block Step3A feasibility'
    if status == 'catalog_absent_legacy_shared_clean_fallback':
        assert data_api_resolution.get('catalog_exists') is False, 'catalog absent fallback is valid only when the catalog file does not exist'
        catalog_path = data_api_resolution.get('catalog_path')
        assert catalog_path and not Path(catalog_path).expanduser().exists(), 'catalog absent fallback is invalid when the catalog file exists'
        assert prep.get('local_input_paths', {}).get('snapshot_source') != 'factorforge_data_api', 'catalog absent fallback must not masquerade as Data API ready'
        assert prep.get('local_input_paths', {}).get('daily_filter_policy') != 'factorforge_data_api_catalog_slice', 'catalog absent fallback must not use Data API ready policy'
    minute_rel = prep['local_input_paths'].get('minute_df_parquet') or prep['local_input_paths'].get('minute_df_csv')
    daily_rel = prep['local_input_paths'].get('daily_df_csv') or prep['local_input_paths'].get('daily_df_parquet')
    input_mode = str(prep['local_input_paths'].get('input_mode') or '')
    if prep['feasibility'] == 'blocked':
        assert prep.get('blocked_items'), 'blocked feasibility must carry explicit blocked_items'
        if status in {'missing_dataset', 'missing_fields'}:
            assert not minute_rel and not daily_rel, 'missing Data API resolution must not claim executable local snapshots'
        else:
            assert not (minute_rel and daily_rel), 'blocked feasibility must not claim executable local snapshots'
    else:
        assert daily_rel and (WORKSPACE / daily_rel).exists(), 'missing local input snapshot: daily_df_(csv/parquet)'
        if input_mode == 'daily_only':
            assert not minute_rel, 'daily_only Step 3A output must not claim minute snapshot'
        else:
            assert minute_rel and (WORKSPACE / minute_rel).exists(), 'missing local input snapshot: minute_df_(parquet/csv)'

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

    existing_stub = code_dir / f'factor_impl_stub__{report_id}.py'
    existing_qlib = code_dir / f'qlib_expression_draft__{report_id}.json'
    existing_hybrid = code_dir / f'hybrid_execution_scaffold__{report_id}.json'
    if existing_stub.exists() or existing_qlib.exists() or existing_hybrid.exists():
        assert handoff.get('step3a_ready') is expected_step3a_ready, 'handoff_to_step4 must keep correct step3a_ready after reruns'
        if existing_stub.exists():
            assert handoff.get('factor_impl_stub_ref'), 'Step 3A rerun must preserve factor_impl_stub_ref when Step 3B artifacts already exist'
        if existing_qlib.exists():
            assert handoff.get('qlib_expression_draft_ref'), 'Step 3A rerun must preserve qlib_expression_draft_ref when Step 3B artifacts already exist'
        if existing_hybrid.exists():
            assert handoff.get('hybrid_execution_scaffold_ref'), 'Step 3A rerun must preserve hybrid_execution_scaffold_ref when Step 3B artifacts already exist'

    for p in [prep_path, qlib_path, impl_path, handoff_path]:
        text = p.read_text(encoding='utf-8')
        for bad in ['TODO', 'TO_BE_FILLED', 'placeholder', 'PLACEHOLDER', '待补']:
            assert bad not in text

    print('RESULT: PASS')
