from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from factor_factory.data_access import build_forward_return_frame, normalize_trade_date_series

BACKTEST_BASE_CONTRACT_VERSION = 'factorforge_backtest_base_dataset_contract_v1'
BACKTEST_BASE_PROFILE_VERSION = 'factorforge_backtest_base_profile_v1'

LABEL_POLICY = {
    'horizon': 'T+1',
    'return_field': 'pct_chg',
    'alignment': 'factor_date_t_to_return_t_plus_1',
    'same_day_return_forbidden': True,
}
TRADABLE_POLICY = {
    'exclude_st': True,
    'exclude_suspended': True,
    'exclude_limit_up_down': True,
    'exclude_new_stock_days': None,
}
COST_POLICY = {
    'version': 'factorforge_default_cost_policy_v1',
    'default_cost_rate': 0.003,
    'turnover_cost_formula': 'turnover * cost_rate',
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def stable_json_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')


def _artifact_contract(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        'path': str(path),
        'sha256': sha256_file(path),
        'row_count': int(len(frame)),
        'schema': [str(col) for col in frame.columns],
    }


def universe_hash_from_daily(daily_df: pd.DataFrame) -> str:
    values = sorted(str(value) for value in daily_df['ts_code'].dropna().unique()) if 'ts_code' in daily_df.columns else []
    return stable_json_hash(values)


def calendar_hash_from_daily(daily_df: pd.DataFrame) -> str:
    if 'trade_date' not in daily_df.columns:
        return stable_json_hash([])
    dates = normalize_trade_date_series(daily_df['trade_date']).dt.strftime('%Y%m%d')
    return stable_json_hash(sorted(str(value) for value in dates.dropna().unique()))


def expected_backtest_base_identity(
    *,
    daily_df: pd.DataFrame,
    daily_input_path: Path,
    window_start: str | None,
    window_end: str | None,
    universe_id: str = 'a_share_all',
    source_data_version: str | None = None,
    clean_data_hash: str | None = None,
) -> dict[str, Any]:
    daily_hash = sha256_file(daily_input_path)
    source_version = source_data_version or f'daily_input_sha256:{daily_hash}'
    clean_hash = clean_data_hash or daily_hash
    identity = {
        'source_data_version': source_version,
        'clean_data_hash': clean_hash,
        'window_start': window_start,
        'window_end': window_end,
        'universe_id': universe_id,
        'universe_hash': universe_hash_from_daily(daily_df),
        'label_policy': LABEL_POLICY,
        'tradable_policy': TRADABLE_POLICY,
        'cost_policy': COST_POLICY,
        'calendar_hash': calendar_hash_from_daily(daily_df),
    }
    identity['backtest_base_dataset_id'] = stable_json_hash(identity)
    return identity


def _build_artifacts(base_dir: Path, daily_df: pd.DataFrame) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    labels_path = base_dir / 'labels.parquet'
    tradable_path = base_dir / 'tradable_mask.parquet'
    calendar_path = base_dir / 'calendar.parquet'
    cost_path = base_dir / 'cost_inputs.parquet'

    daily_for_labels = daily_df[[col for col in ['ts_code', 'trade_date', 'close', 'pct_chg'] if col in daily_df.columns]].rename(columns={'ts_code': 'code'})
    labels = build_forward_return_frame(
        daily_for_labels,
        instrument_col='code',
        date_col='trade_date',
        price_col='close',
        horizon=1,
    )
    labels = labels.rename(columns={'future_return_1d': 'label_return_1d'})

    mask = daily_df[[col for col in ['ts_code', 'trade_date'] if col in daily_df.columns]].copy()
    if 'ts_code' in mask.columns:
        mask = mask.rename(columns={'ts_code': 'code'})
    mask['is_tradable'] = True

    dates = normalize_trade_date_series(daily_df['trade_date']).dt.strftime('%Y%m%d') if 'trade_date' in daily_df.columns else pd.Series([], dtype=str)
    calendar = pd.DataFrame({'trade_date': sorted(str(value) for value in dates.dropna().unique())})

    cost_inputs = daily_df[[col for col in ['ts_code', 'trade_date'] if col in daily_df.columns]].copy()
    if 'ts_code' in cost_inputs.columns:
        cost_inputs = cost_inputs.rename(columns={'ts_code': 'code'})
    cost_inputs['default_cost_rate'] = COST_POLICY['default_cost_rate']

    labels.to_parquet(labels_path, index=False)
    mask.to_parquet(tradable_path, index=False)
    calendar.to_parquet(calendar_path, index=False)
    cost_inputs.to_parquet(cost_path, index=False)

    paths = {
        'labels': str(labels_path),
        'tradable_mask': str(tradable_path),
        'calendar': str(calendar_path),
        'cost_inputs': str(cost_path),
    }
    contracts = {
        'labels': _artifact_contract(labels_path, labels),
        'tradable_mask': _artifact_contract(tradable_path, mask),
        'calendar': _artifact_contract(calendar_path, calendar),
        'cost_inputs': _artifact_contract(cost_path, cost_inputs),
    }
    return paths, contracts


def build_or_reuse_backtest_base_dataset(
    *,
    report_id: str,
    factor_id: str | None,
    daily_df: pd.DataFrame,
    daily_input_path: Path,
    run_root: Path,
    window_start: str | None,
    window_end: str | None,
    producer_repo_sha: str | None,
    universe_id: str = 'a_share_all',
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    expected = expected_backtest_base_identity(
        daily_df=daily_df,
        daily_input_path=daily_input_path,
        window_start=window_start,
        window_end=window_end,
        universe_id=universe_id,
    )
    dataset_id = expected['backtest_base_dataset_id']
    base_dir = run_root / '_shared' / 'backtest_base' / dataset_id
    contract_path = base_dir / 'backtest_base_dataset_contract.json'
    reuse_hit = False
    reuse_reason = 'missing_dataset'
    validate_started = time.perf_counter()
    if contract_path.exists():
        existing = json.loads(contract_path.read_text(encoding='utf-8'))
        issues = validate_backtest_base_dataset_contract(existing, expected_identity=expected)
        if not issues:
            reuse_hit = True
            reuse_reason = 'identity_match'
            contract = existing
        else:
            reuse_reason = _reuse_reason_from_issues(issues)
            contract = {}
    else:
        contract = {}
    validate_seconds = time.perf_counter() - validate_started

    if not reuse_hit:
        base_dir.mkdir(parents=True, exist_ok=True)
        artifact_paths, artifact_contracts = _build_artifacts(base_dir, daily_df)
        contract = {
            'version': BACKTEST_BASE_CONTRACT_VERSION,
            'report_id': report_id,
            'factor_id': factor_id,
            **expected,
            'artifact_paths': artifact_paths,
            'artifact_hashes': {key: value.get('sha256') for key, value in artifact_contracts.items()},
            'artifact_contracts': artifact_contracts,
            'producer_step': 'backtest_base_producer',
            'producer_repo_sha': producer_repo_sha,
            'created_at': utc_now(),
            'validator_verdict': 'PASS',
        }
        _write_json(contract_path, contract)

    profile = {
        'version': BACKTEST_BASE_PROFILE_VERSION,
        'backtest_base_dataset_id': dataset_id,
        'backtest_base_reuse_hit': reuse_hit,
        'backtest_base_reuse_reason': reuse_reason,
        'backtest_base_load_seconds': time.perf_counter() - started,
        'backtest_base_validate_seconds': validate_seconds,
        'factor_values_load_seconds': 0.0,
        'evaluation_seconds': 0.0,
        'write_outputs_seconds': 0.0,
        'contract_path': str(contract_path),
    }
    return contract, profile


def _reuse_reason_from_issues(issues: list[dict[str, Any]]) -> str:
    mapping = {
        'BLOCK_BACKTEST_BASE_LABEL_POLICY_MISMATCH': 'label_policy_mismatch',
        'BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH': 'universe_hash_mismatch',
        'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH': 'source_data_version_mismatch',
        'BLOCK_BACKTEST_BASE_TRADABLE_POLICY_MISMATCH': 'tradable_policy_mismatch',
        'BLOCK_BACKTEST_BASE_COST_POLICY_MISMATCH': 'cost_policy_mismatch',
        'BLOCK_BACKTEST_BASE_ARTIFACT_HASH_MISMATCH': 'artifact_hash_mismatch',
        'BLOCK_STEP4_REUSE_GATE_AMBIGUOUS': 'ambiguous_identity',
    }
    return mapping.get(str(issues[0].get('code')), 'ambiguous_identity') if issues else 'identity_match'


def validate_backtest_base_dataset_contract(
    contract: dict[str, Any] | None,
    *,
    expected_identity: dict[str, Any] | None = None,
    require_artifacts: bool = True,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(contract, dict) or not contract:
        return [{'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_DATASET_MISSING', 'message': 'backtest_base_dataset_contract missing'}]
    if contract.get('version') != BACKTEST_BASE_CONTRACT_VERSION:
        issues.append({'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_DATASET_MISSING', 'message': 'invalid backtest_base_dataset_contract.version'})
    if not contract.get('backtest_base_dataset_id'):
        issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_REUSE_GATE_AMBIGUOUS', 'message': 'backtest_base_dataset_id missing'})
    if contract.get('validator_verdict') != 'PASS':
        issues.append({'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_DATASET_MISSING', 'message': 'backtest base validator_verdict must be PASS'})

    if expected_identity:
        comparisons = [
            ('source_data_version', 'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH'),
            ('clean_data_hash', 'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH'),
            ('window_start', 'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH'),
            ('window_end', 'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH'),
            ('universe_id', 'BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH'),
            ('universe_hash', 'BLOCK_BACKTEST_BASE_UNIVERSE_MISMATCH'),
            ('calendar_hash', 'BLOCK_BACKTEST_BASE_DATA_VERSION_MISMATCH'),
        ]
        for field, code in comparisons:
            if str(contract.get(field)) != str(expected_identity.get(field)):
                issues.append({'severity': 'error', 'code': code, 'message': f'backtest base {field} mismatch'})
        for field, code in [
            ('label_policy', 'BLOCK_BACKTEST_BASE_LABEL_POLICY_MISMATCH'),
            ('tradable_policy', 'BLOCK_BACKTEST_BASE_TRADABLE_POLICY_MISMATCH'),
            ('cost_policy', 'BLOCK_BACKTEST_BASE_COST_POLICY_MISMATCH'),
        ]:
            if contract.get(field) != expected_identity.get(field):
                issues.append({'severity': 'error', 'code': code, 'message': f'backtest base {field} mismatch'})
        expected_id = expected_identity.get('backtest_base_dataset_id')
        if expected_id and contract.get('backtest_base_dataset_id') != expected_id:
            issues.append({'severity': 'error', 'code': 'BLOCK_STEP4_REUSE_GATE_AMBIGUOUS', 'message': 'backtest_base_dataset_id does not match identity fields'})

    if require_artifacts:
        paths = contract.get('artifact_paths') if isinstance(contract.get('artifact_paths'), dict) else {}
        hashes = contract.get('artifact_hashes') if isinstance(contract.get('artifact_hashes'), dict) else {}
        for key in ['labels', 'tradable_mask', 'calendar', 'cost_inputs']:
            raw_path = paths.get(key)
            declared_hash = hashes.get(key)
            if not raw_path or not declared_hash:
                issues.append({'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_ARTIFACT_HASH_MISMATCH', 'message': f'backtest base {key} path/hash missing'})
                continue
            actual_hash = sha256_file(Path(raw_path).expanduser())
            if actual_hash != declared_hash:
                issues.append({'severity': 'error', 'code': 'BLOCK_BACKTEST_BASE_ARTIFACT_HASH_MISMATCH', 'message': f'backtest base {key} artifact hash mismatch'})
    return issues
