from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

STEP2_SOURCE_CONTRACT_VERSION = 'factorforge_step2_source_contract_v2'
ALLOWED_IMPLEMENTATION_MODES = {'operator', 'direct_code', 'hybrid'}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def stable_hash(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode('utf-8')).hexdigest()


def normalize_implementation_mode(raw: Any, *, allow_legacy_alias: bool = False) -> str:
    value = str(raw or '').strip()
    if allow_legacy_alias:
        # Legacy aliases are accepted only at controlled migration/debug boundaries.
        # Formal artifacts must store operator/direct_code/hybrid.
        aliases = {
            'qlib_operator': 'operator',
            'formula_operator': 'operator',
            'direct_python': 'direct_code',
            'python': 'direct_code',
        }
        value = aliases.get(value, value)
    if value not in ALLOWED_IMPLEMENTATION_MODES:
        raise ValueError(f'unsupported implementation_mode: {raw}')
    return value


def build_spec_hash(master: dict[str, Any]) -> str:
    return stable_hash({
        'canonical_spec': master.get('canonical_spec') or {},
        'implementation_contract': master.get('implementation_contract') or {},
        'research_contract': master.get('research_contract') or {},
    })


def build_code_contract_hash(master: dict[str, Any]) -> str:
    return stable_hash(master.get('implementation_contract') or master.get('canonical_spec') or {})


def build_formula_hash(master: dict[str, Any]) -> str:
    canonical = master.get('canonical_spec') or {}
    return stable_hash({
        'formula_text': canonical.get('formula_text'),
        'formula_ir': canonical.get('formula_ir'),
        'operators': canonical.get('operators') or [],
    })


def build_custom_block_hash(master: dict[str, Any]) -> str:
    canonical = master.get('canonical_spec') or {}
    contract = master.get('implementation_contract') or {}
    return stable_hash({
        'custom_blocks': canonical.get('custom_blocks') or [],
        'contract_custom_blocks': contract.get('custom_blocks') or [],
        'implementation_assumptions': canonical.get('implementation_assumptions') or [],
        'time_series_steps': canonical.get('time_series_steps') or [],
        'cross_sectional_steps': canonical.get('cross_sectional_steps') or [],
    })


def build_artifact_identity(
    *,
    report_id: str,
    factor_id: str,
    source_type: str,
    implementation_mode: str,
    contract_version: str,
    producer: str,
    upstream_producer: str,
    spec_hash: str,
    branch_id: str,
    artifact_role: str,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    formula_hash: str | None = None,
    code_hash: str | None = None,
    code_contract_hash: str | None = None,
    custom_block_hash: str | None = None,
    hybrid_hash: str | None = None,
    created_at_utc: str | None = None,
) -> dict[str, Any]:
    identity = {
        'report_id': report_id,
        'factor_id': factor_id,
        'source_type': source_type,
        'implementation_mode': normalize_implementation_mode(implementation_mode),
        'contract_version': contract_version,
        'producer': producer,
        'upstream_producer': upstream_producer,
        'formula_hash': formula_hash,
        'code_hash': code_hash,
        'code_contract_hash': code_contract_hash,
        'custom_block_hash': custom_block_hash,
        'hybrid_hash': hybrid_hash,
        'spec_hash': spec_hash,
        'branch_id': branch_id,
        'run_id': run_id,
        'parent_run_id': parent_run_id,
        'created_at_utc': created_at_utc or utc_now(),
        'artifact_role': artifact_role,
    }
    mode = identity['implementation_mode']
    if mode == 'operator' and not identity.get('formula_hash'):
        raise ValueError('operator artifact_identity requires formula_hash')
    if mode == 'direct_code' and not (identity.get('code_hash') or identity.get('code_contract_hash')):
        raise ValueError('direct_code artifact_identity requires code_hash or code_contract_hash')
    if mode == 'hybrid' and not (identity.get('formula_hash') and identity.get('custom_block_hash')):
        raise ValueError('hybrid artifact_identity requires formula_hash and custom_block_hash')
    return identity


def assert_identity_matches(left: dict[str, Any], right: dict[str, Any], *, left_label: str, right_label: str) -> None:
    required = ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'spec_hash', 'branch_id']
    for key in required:
        if not left.get(key):
            raise AssertionError(f'{left_label}.artifact_identity.{key} is required')
        if not right.get(key):
            raise AssertionError(f'{right_label}.artifact_identity.{key} is required')
        if left.get(key) != right.get(key):
            raise AssertionError(
                f'artifact identity mismatch for {key}: {left_label}={left.get(key)} {right_label}={right.get(key)}'
            )


def assert_identity_matches_strict(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    expected_label: str,
    actual_label: str,
    require_run_id: bool = True,
    require_mode_hash: bool = True,
    allowed_role_transitions: set[tuple[str, str]] | None = None,
) -> None:
    required = ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'spec_hash', 'branch_id', 'artifact_role']
    for key in required:
        if not expected.get(key):
            raise AssertionError(f'{expected_label}.artifact_identity.{key} is required')
        if not actual.get(key):
            raise AssertionError(f'{actual_label}.artifact_identity.{key} is required')
    for key in ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'spec_hash', 'branch_id']:
        if expected.get(key) != actual.get(key):
            raise AssertionError(
                f'artifact identity mismatch for {key}: {expected_label}={expected.get(key)} {actual_label}={actual.get(key)}'
            )

    transition = (str(expected.get('artifact_role')), str(actual.get('artifact_role')))
    if allowed_role_transitions is not None and transition not in allowed_role_transitions:
        raise AssertionError(f'artifact_role transition not allowed: {expected_label}->{actual_label} {transition}')

    expected_run = expected.get('run_id')
    actual_run = actual.get('run_id')
    if require_run_id:
        if not expected_run and not actual_run:
            raise AssertionError(f'{expected_label}/{actual_label}.artifact_identity.run_id is required')
        if expected_run != actual_run and actual.get('parent_run_id') != expected_run:
            raise AssertionError(
                f'run lineage mismatch: {expected_label}.run_id={expected_run} '
                f'{actual_label}.run_id={actual_run} {actual_label}.parent_run_id={actual.get("parent_run_id")}'
            )

    if require_mode_hash:
        mode = expected.get('implementation_mode')
        if mode == 'operator':
            if not expected.get('formula_hash') or not actual.get('formula_hash'):
                raise AssertionError('operator identity requires formula_hash on both artifacts')
            if expected.get('formula_hash') != actual.get('formula_hash'):
                raise AssertionError('operator formula_hash mismatch')
        elif mode == 'direct_code':
            expected_contract_hash = expected.get('code_contract_hash')
            actual_contract_hash = actual.get('code_contract_hash')
            if not expected_contract_hash or not actual_contract_hash:
                raise AssertionError('direct_code identity requires code_contract_hash on both artifacts')
            if expected_contract_hash != actual_contract_hash:
                raise AssertionError('direct_code code_contract_hash mismatch')

            expected_code_hash = expected.get('code_hash')
            actual_code_hash = actual.get('code_hash')
            if expected_code_hash or actual_code_hash:
                if not expected_code_hash or not actual_code_hash:
                    raise AssertionError('direct_code code_hash must be present on both artifacts when declared')
                if expected_code_hash != actual_code_hash:
                    raise AssertionError('direct_code code_hash mismatch')
        elif mode == 'hybrid':
            for key in ['formula_hash', 'custom_block_hash', 'hybrid_hash']:
                if not expected.get(key) or not actual.get(key):
                    raise AssertionError(f'hybrid identity requires {key} on both artifacts')
                if expected.get(key) != actual.get(key):
                    raise AssertionError(f'hybrid {key} mismatch')
        else:
            raise AssertionError(f'unsupported implementation_mode: {mode}')
