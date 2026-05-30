#!/usr/bin/env python3
import argparse, hashlib, json
import os
import re
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
CSV_POLICY_VALUES = {'full_csv', 'sample_csv', 'no_csv'}
SORT_CONTRACT_VERSION = 'factorforge_sort_contract_v1'
DIRECT_CODE_CONTRACT_VERSION = 'factorforge_direct_code_contract_v1'
DIRECT_CODE_ALLOWED_SOURCE_DERIVATIONS = {
    'source_code_preserved_from_formal_step2_raw_direct_code_contract',
    'source_code_preserved_from_step2_direct_code_contract',
    'source_code_generated_by_step3a_llm_provider',
}


def validate_sort_contract(contract: dict) -> None:
    if not contract:
        return
    assert contract.get('version') == SORT_CONTRACT_VERSION, 'STEP3_DAILY_SORT_CONTRACT_INVALID: invalid sort_contract.version'
    assert contract.get('sorted_by') == ['ts_code', 'trade_date'], 'STEP3_DAILY_SORT_CONTRACT_INVALID: sorted_by must be ts_code/trade_date'
    assert isinstance(contract.get('row_count'), int) and contract.get('row_count') >= 0, 'STEP3_DAILY_SORT_CONTRACT_INVALID: row_count'
    key_dtype = contract.get('key_dtype')
    assert isinstance(key_dtype, dict) and key_dtype.get('ts_code') and key_dtype.get('trade_date'), 'STEP3_DAILY_SORT_CONTRACT_INVALID: key_dtype'
    assert contract.get('source') == 'step3a_local_input', 'STEP3_DAILY_SORT_CONTRACT_INVALID: source'
    assert isinstance(contract.get('data_hash'), str) and len(contract.get('data_hash')) >= 32, 'STEP3_DAILY_SORT_CONTRACT_INVALID: data_hash'
    assert isinstance(contract.get('duplicate_key_check'), bool), 'STEP3_DAILY_SORT_CONTRACT_INVALID: duplicate_key_check'
    assert isinstance(contract.get('sample_sortedness_check'), bool), 'STEP3_DAILY_SORT_CONTRACT_INVALID: sample_sortedness_check'


def direct_code_contract_from_plan(impl: dict) -> dict:
    code_contract = impl.get('code_contract') if isinstance(impl.get('code_contract'), dict) else {}
    if code_contract:
        return code_contract
    contract = impl.get('implementation_contract') if isinstance(impl.get('implementation_contract'), dict) else {}
    code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    if code_contract:
        return code_contract
    return {}


def validate_direct_code_source_contract(impl: dict) -> None:
    code_contract = direct_code_contract_from_plan(impl)
    assert code_contract, 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code requires code_contract before worker dispatch'
    assert code_contract.get('code_contract_version') == DIRECT_CODE_CONTRACT_VERSION, (
        'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: invalid direct_code code_contract_version'
    )
    source = str(code_contract.get('source_code') or impl.get('source_code') or '')
    assert source.strip(), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code requires code_contract.source_code before worker dispatch'
    source_derivation = code_contract.get('source_derivation')
    assert isinstance(source_derivation, dict), (
        'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code source_code requires source_derivation provenance'
    )
    assert source_derivation.get('not_fallback') is True, (
        'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code source_code provenance must mark not_fallback=true'
    )
    assert source_derivation.get('derivation') in DIRECT_CODE_ALLOWED_SOURCE_DERIVATIONS, (
        f'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: unsupported direct_code source derivation {source_derivation.get("derivation")}'
    )
    entrypoint = str(code_contract.get('entrypoint') or code_contract.get('function_name') or '')
    assert entrypoint == 'compute_factor', 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code entrypoint/function_name must be compute_factor'
    assert re.search(r'def\s+compute_factor\s*\(', source), (
        'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code source_code must define compute_factor()'
    )
    declared_hash = str(code_contract.get('code_hash') or impl.get('code_hash') or '')
    assert declared_hash, 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code requires code_hash'
    actual_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    assert declared_hash == actual_hash, (
        f'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_HASH_MISMATCH: declared={declared_hash} actual={actual_hash}'
    )
    imports = code_contract.get('imports') or code_contract.get('dependencies')
    assert isinstance(imports, list) and imports, 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code imports/dependencies required'
    input_schema = code_contract.get('input_schema')
    output_schema = code_contract.get('output_schema') or impl.get('output_schema')
    assert isinstance(input_schema, dict) and input_schema, 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code input_schema required'
    assert isinstance(output_schema, dict) and output_schema.get('columns'), (
        'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code output_schema.columns required'
    )
    required_outputs = {'ts_code', 'trade_date', 'factor_value'}
    assert required_outputs.issubset(set(output_schema.get('columns') or [])), (
        'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code output_schema must include ts_code/trade_date/factor_value'
    )

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


def parquet_schema_columns(parquet_path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq

        return list(pq.read_schema(parquet_path).names)
    except Exception:
        import pandas as pd

        return list(pd.read_parquet(parquet_path).head(0).columns)


def validate_daily_io_contract(local_inputs: dict, *, require_full_parity: bool = False) -> None:
    daily_parquet_rel = local_inputs.get('daily_df_parquet')
    daily_csv_rel = local_inputs.get('daily_df_csv')
    daily_csv_sample_rel = local_inputs.get('daily_df_csv_sample')
    contract = local_inputs.get('daily_io_contract') or {}
    preferred = local_inputs.get('preferred_daily_format')
    audit_format = local_inputs.get('audit_daily_format')
    policy = contract.get('csv_output_policy') or ('full_csv' if daily_csv_rel else None)

    assert policy in CSV_POLICY_VALUES, f'STEP3_DAILY_CSV_POLICY_INVALID: {policy}'
    assert contract.get('version') == 'factorforge_step3a_daily_io_contract_v1', 'STEP3_DAILY_IO_CONTRACT_MISSING: invalid or missing daily_io_contract.version'

    if preferred == 'parquet' or daily_parquet_rel:
        assert daily_parquet_rel, 'STEP3_DAILY_PARQUET_MISSING: preferred_daily_format=parquet but daily_df_parquet missing'
        parquet_path = WORKSPACE / daily_parquet_rel
        assert parquet_path.exists(), f'STEP3_DAILY_PARQUET_MISSING: {parquet_path}'
        assert contract.get('formal_evidence_format', 'parquet') == 'parquet', 'STEP3_DAILY_IO_CONTRACT_MISSING: daily_io_contract formal_evidence_format must be parquet'
        assert contract.get('parquet_required_for_performance', True) is not False, 'STEP3_DAILY_IO_CONTRACT_MISSING: parquet formal evidence must be required for performance'
        validate_sort_contract(contract.get('sort_contract') or local_inputs.get('sort_contract') or {})
        expected_audit_path = 'csv' if policy == 'full_csv' else ('csv_sample' if policy == 'sample_csv' else 'none')
        assert contract.get('performance_path') == 'parquet' and contract.get('audit_path') == expected_audit_path, 'STEP3_DAILY_IO_CONTRACT_MISSING: daily_io_contract path roles invalid'

        if policy == 'no_csv':
            assert audit_format == 'none', 'STEP3_DAILY_CSV_POLICY_INVALID: no_csv requires audit_daily_format=none'
            assert not daily_csv_rel and not daily_csv_sample_rel, 'STEP3_DAILY_NO_CSV_PATH_DECLARED: no_csv must not claim local_input_paths CSV audit paths'
            assert not contract.get('csv_path') and not contract.get('csv_sample_path'), 'STEP3_DAILY_NO_CSV_PATH_DECLARED: no_csv must not claim daily_io_contract CSV paths'
            assert contract.get('full_csv_available') is False, 'STEP3_DAILY_CSV_POLICY_INVALID: no_csv full_csv_available must be false'
            assert contract.get('full_csv_absent_validated', True) is not False, 'STEP3_DAILY_CSV_POLICY_INVALID: no_csv must validate full CSV absence'
            assert int(contract.get('csv_rows_written') or 0) == 0, 'STEP3_DAILY_CSV_POLICY_INVALID: no_csv csv_rows_written must be 0'
            return

        if policy == 'full_csv':
            assert audit_format == 'csv', 'STEP3_DAILY_CSV_POLICY_INVALID: full_csv requires audit_daily_format=csv'
            assert daily_csv_rel, 'STEP3_DAILY_CSV_AUDIT_MISSING: local_input_paths.daily_df_csv is required for full_csv audit'
            csv_path = WORKSPACE / daily_csv_rel
            assert csv_path.exists(), f'STEP3_DAILY_CSV_AUDIT_MISSING: {csv_path}'
            assert contract.get('full_csv_available') is not False, 'STEP3_DAILY_CSV_POLICY_INVALID: full_csv must mark full_csv_available'
        else:
            assert audit_format == 'csv_sample', 'STEP3_DAILY_CSV_POLICY_INVALID: sample_csv requires audit_daily_format=csv_sample'
            assert not daily_csv_rel, 'STEP3_DAILY_CSV_POLICY_INVALID: sample_csv must not claim full daily_df_csv'
            assert daily_csv_sample_rel, 'STEP3_DAILY_CSV_AUDIT_MISSING: local_input_paths.daily_df_csv_sample is required for sample_csv audit'
            csv_path = WORKSPACE / daily_csv_sample_rel
            assert csv_path.exists(), f'STEP3_DAILY_CSV_AUDIT_MISSING: {csv_path}'
            assert contract.get('full_csv_available') is False, 'STEP3_DAILY_CSV_POLICY_INVALID: sample_csv full_csv_available must be false'

        import pandas as pd

        required_cols = {'ts_code', 'trade_date'}
        parquet_cols = parquet_schema_columns(parquet_path)
        csv_cols = list(pd.read_csv(csv_path, nrows=0).columns)
        assert required_cols.issubset(set(parquet_cols)) and required_cols.issubset(set(csv_cols)), (
            'STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH: key columns missing'
        )
        assert parquet_cols == csv_cols, (
            f'STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH: column order/header mismatch parquet={parquet_cols} csv={csv_cols}'
        )
        if policy == 'sample_csv':
            sample_rows = len(pd.read_csv(csv_path))
            assert sample_rows == int(contract.get('csv_rows_written') or -1), (
                f'STEP3_DAILY_CSV_AUDIT_MISSING: sample row count mismatch metadata={contract.get("csv_rows_written")} actual={sample_rows}'
            )
            return
        small_enough = require_full_parity or (parquet_path.stat().st_size < 50_000_000 and csv_path.stat().st_size < 100_000_000)
        if small_enough:
            pq = pd.read_parquet(parquet_path)
            cs = pd.read_csv(csv_path)
            assert len(pq) == len(cs), (
                f'STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH: row count mismatch parquet={len(pq)} csv={len(cs)}'
            )
            assert set(pq.columns) == set(cs.columns), (
                f'STEP3_DAILY_PARQUET_CSV_SCHEMA_MISMATCH: column mismatch parquet={sorted(pq.columns)} csv={sorted(cs.columns)}'
            )


def _data_api_resolution(prep: dict, qcfg: dict) -> dict:
    local_inputs = prep.get('local_input_paths') if isinstance(prep.get('local_input_paths'), dict) else {}
    for candidate in [
        prep.get('data_api_resolution'),
        local_inputs.get('data_api_resolution'),
        qcfg.get('data_api_resolution'),
    ]:
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def _daily_filter_policy(prep: dict, qcfg: dict) -> dict:
    local_inputs = prep.get('local_input_paths') if isinstance(prep.get('local_input_paths'), dict) else {}
    data_api = _data_api_resolution(prep, qcfg)
    clean_daily = data_api.get('clean_daily_bar') if isinstance(data_api.get('clean_daily_bar'), dict) else {}
    for candidate in [
        prep.get('daily_filter_policy'),
        local_inputs.get('daily_filter_policy'),
        qcfg.get('daily_filter_policy'),
        clean_daily.get('daily_filter_policy'),
    ]:
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def validate_step3_readiness_contract(
    prep: dict,
    qcfg: dict,
    impl: dict,
    handoff: dict,
    *,
    workspace: Path | None = None,
) -> None:
    del impl
    workspace = workspace or WORKSPACE
    feasibility = prep.get('feasibility')
    expected_step3a_ready = feasibility in {'ready', 'proxy_ready'}
    if handoff.get('step3a_ready') is not None:
        assert handoff.get('step3a_ready') is expected_step3a_ready, (
            f'handoff_to_step4.step3a_ready mismatch: expected {expected_step3a_ready}, '
            f"got {handoff.get('step3a_ready')}"
        )
    if feasibility == 'blocked':
        assert handoff.get('step3b_ready') is not True, (
            'BLOCK_STEP3A_HANDOFF_CONTRADICTION: blocked Step3A cannot claim step3b_ready=true'
        )
        return

    data_api = _data_api_resolution(prep, qcfg)
    clean_daily = data_api.get('clean_daily_bar') if isinstance(data_api.get('clean_daily_bar'), dict) else {}
    assert clean_daily.get('status') == 'ready', (
        'BLOCK_STEP3A_DATA_API_RESOLUTION_MISSING: executable Step3A requires ready clean_daily_bar Data API resolution'
    )

    policy = _daily_filter_policy(prep, qcfg)
    assert policy.get('drop_suspended') is True and policy.get('drop_limit_events') is True, (
        'BLOCK_STEP3A_DAILY_FILTER_POLICY_MISSING: clean daily policy must explicitly drop suspended and limit-event days'
    )

    local_inputs = prep.get('local_input_paths') if isinstance(prep.get('local_input_paths'), dict) else {}
    daily_rel = local_inputs.get('daily_df_parquet') or local_inputs.get('daily_df_csv')
    if daily_rel:
        daily_path = workspace / daily_rel
        assert daily_path.exists(), f'BLOCK_STEP3A_LOCAL_SNAPSHOT_MISSING: {daily_path}'


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
    assert impl_mode in {'operator', 'direct_code', 'hybrid'}, (
        f'formal implementation_mode must be operator/direct_code/hybrid, got {impl_mode}'
    )
    if impl_mode == 'direct_code':
        validate_direct_code_source_contract(impl)
    if 'calculation_steps' in impl:
        assert isinstance(impl.get('calculation_steps'), list) and impl['calculation_steps']
    if 'code_artifacts' in impl:
        assert isinstance(impl.get('code_artifacts'), dict) and impl['code_artifacts']
    if 'step4_contract' in impl:
        assert impl['step4_contract'].get('execution_mode') == impl_mode

    validate_step3_readiness_contract(prep, qcfg, impl, handoff, workspace=WORKSPACE)
    if handoff.get('execution_mode') is not None:
        assert handoff.get('execution_mode') == impl_mode
    assert isinstance(prep.get('local_input_paths'), dict)
    minute_rel = prep['local_input_paths'].get('minute_df_parquet') or prep['local_input_paths'].get('minute_df_csv')
    daily_rel = prep['local_input_paths'].get('daily_df_parquet') or prep['local_input_paths'].get('daily_df_csv')
    input_mode = str(prep['local_input_paths'].get('input_mode') or '')
    if prep['feasibility'] == 'blocked':
        assert prep.get('blocked_items'), 'blocked feasibility must carry explicit blocked_items'
        assert not (minute_rel and daily_rel), 'blocked feasibility must not claim executable local snapshots'
    else:
        assert daily_rel and (WORKSPACE / daily_rel).exists(), 'missing local input snapshot: daily_df_(csv/parquet)'
        validate_daily_io_contract(prep['local_input_paths'])
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
