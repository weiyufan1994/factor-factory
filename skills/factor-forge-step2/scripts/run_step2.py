#!/usr/bin/env python3
"""
Independent Step 2 runner for FactorForge.
Consumes Step 1 artifacts and produces Step 2 side artifacts + factor_spec_master.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEGACY_WORKSPACE = Path('/opt/factorforge/workspace')
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FACTORFORGE.parent
OBJECTS = FACTORFORGE / 'objects'
VALIDATION = OBJECTS / 'validation'
SPEC_MASTER_DIR = OBJECTS / 'factor_spec_master'
HANDOFF_DIR = OBJECTS / 'handoff'
REGISTRY_PATH = FACTORFORGE / 'data' / 'report_ingestion' / 'report_registry.json'
SUPPORTED_SOURCE_TYPES = {'pdf_report', 'paper_canonical_formula', 'natural_language_hypothesis'}
STEP2_SOURCE_CONTRACT_VERSION = 'factorforge_step2_source_contract_v2'
HYBRID_CONTRACT_VERSION = 'factorforge_hybrid_contract_v1'
MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V2 = (
    'factorforge_step2_manifest_bound_dual_route_adapter_v2'
)
MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3 = (
    'factorforge_step2_manifest_bound_dual_route_adapter_v3'
)
# New builders use V3.  V2 remains readable, but non-identical V2 semantics
# never satisfy the independent-review gate.
MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION = (
    MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3
)
MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_KIND = 'manifest_bound_dual_route_pdf'
BLOCK_MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_INVALID = (
    'BLOCK_STEP2_MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_INVALID'
)
BLOCK_LOCAL_AGENT_SPEC_INPUTS_INVALID = (
    'BLOCK_STEP2_LOCAL_AGENT_SPEC_INPUTS_INVALID'
)
LOCAL_AGENT_SPEC_INPUTS_KEY = 'local_agent_spec_inputs'
LOCAL_AGENT_SPEC_ROLES = {
    'primary': 'local_agent_primary_spec',
    'challenger': 'local_agent_challenger_spec',
}
LOCAL_AGENT_SPEC_CANONICAL_CORE_FIELDS = (
    'raw_formula_text',
    'operators',
    'required_inputs',
    'rebalance_frequency',
)
SOURCE_STEP1_BINDING_PROFILE = 'factorforge_step2_source_step1_binding_v1'
DUAL_ROUTE_SEMANTIC_ALIGNMENT_PROFILE = (
    'factorforge_step2_dual_route_semantic_alignment_v1'
)
SOURCE_STEP1_BINDING_ROLES = (
    'source_pdf',
    'source_identity_receipt',
    'source_first_freeze_receipt',
    'source_first_successor_receipt',
    'measurement_program',
    'research_equation',
    'step1_validation',
)
SOURCE_STEP1_BINDING_ROLES_V3 = (
    *SOURCE_STEP1_BINDING_ROLES,
    'branch_parameter_registry',
)
INDEPENDENT_SEMANTIC_REVIEW_PROFILE = (
    'factorforge_step2_independent_semantic_review_receipt_v1'
)
ALPHA_SEMANTIC_SUBJECT_PROFILE = (
    'factorforge_step2_alpha_semantic_subject_projection_v1'
)
SEMANTIC_REVIEW_RELATIONS = frozenset(
    {'EQUAL', 'COMPLEMENTARY', 'CONFLICTING', 'INCOMPARABLE'}
)
RESEARCH_SUBJECT_MODES = frozenset(
    {'report_replication', 'source_extension', 'independent_hypothesis'}
)
SOURCE_SEMANTIC_REVIEW_STATUSES = frozenset({'match', 'mismatch', 'unassessed'})
SOURCE_SUBJECT_ROUTING_PROFILE = 'factorforge_step2_source_subject_routing_v1'
# The v2 contract is retained for compatibility with existing identity
# consumers, but every newly produced v2 master/handoff must carry this marker.
# Its absence is never a normal validation path; see validate_step2's explicit
# legacy switch for genuinely pre-routing artifacts.
SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER = 'source_subject_routing_required'
SOURCE_IDENTITY_RECEIPT_SCHEMA_ID = (
    'factorforge_report_source_identity_receipt_candidate_v1'
)
SOURCE_FREEZE_RECEIPT_SCHEMA_ID = (
    'factorforge_source_first_freeze_receipt_candidate_v1'
)
SOURCE_SUCCESSOR_RECEIPT_SCHEMA_ID = (
    'factorforge_source_first_source_successor_receipt_candidate_v1'
)
SOURCE_FREEZE_BINDING_ROLES = (
    'workspace_manifest',
    'source_capture_manifest',
    'source_only_human_readable_record',
    'source_first_overlay',
)
SOURCE_SUCCESSOR_BINDING_ROLES = (
    's3_report_object',
    'source_identity_receipt',
    'source_reading_delta',
    'post_a0_measurement_program',
)
STEP1_VALIDATION_CHECK_NAMES = (
    'alpha_idea_master_exists',
    'report_id_match',
    'final_factor_present',
    'step1_mathematical_object_present',
    'target_statistic_hint_present',
    'information_set_hint_present',
    'initial_return_source_hypothesis_present',
    'economic_hypothesis_present',
    'math_hypothesis_candidates_present',
    'market_process_thesis_present',
    'primary_mechanism_model_candidates_present',
    'market_outcome_projection_present',
    'measurement_program_present',
    'discipline_measurement_program_present',
    'measurement_program_consistent',
    'measurement_program_valid',
    'measurement_program_route_match',
    'similar_case_lessons_imported_present',
    'knowledge_reference_contract_present',
    'what_must_be_true_present',
    'what_would_break_it_present',
    'information_set_not_illegal',
)
DUAL_ROUTE_SEMANTIC_FIELDS = (
    'raw_formula_text',
    'operators',
    'time_series_steps',
    'cross_sectional_steps',
    'preprocessing',
    'normalization',
    'neutralization',
    'explicit_items',
    'inferred_items',
    'ambiguities',
)
DUAL_ROUTE_SHARED_EQUAL_FIELDS = (
    'factor_id',
    'report_id',
    'required_inputs',
    'rebalance_frequency',
)
DUAL_ROUTE_EQUAL_RELATION = 'EQUAL'
DUAL_ROUTE_NONIDENTICAL_RELATION = (
    'COMPLEMENTARY_ASSERTED__INDEPENDENT_SEMANTIC_REVIEW_REQUIRED'
)
RAW_SPEC_REQUIRED_FIELDS = frozenset({
    'factor_id',
    'report_id',
    'route',
    'raw_formula_text',
    'operators',
    'required_inputs',
    'time_series_steps',
    'cross_sectional_steps',
    'preprocessing',
    'normalization',
    'neutralization',
    'rebalance_frequency',
    'explicit_items',
    'inferred_items',
    'ambiguities',
})
RAW_SPEC_ALLOWED_FIELDS = frozenset({
    *RAW_SPEC_REQUIRED_FIELDS,
    'candidate_only',
    'candidate_status',
    'artifact_status',
    'authority_effect',
    'authority_boundary',
    'oos_accessed',
    'final_factor_name',
    'research_equation_ref',
})
DEFAULT_FORBIDDEN_CODE_PATTERNS = [
    r'shift\s*\(\s*-\d+',
    'future_return',
    'next_return',
    'forward_return',
    'label',
    'target',
    'future_',
    'lookahead',
    r'lead\s*\(',
]
SOURCE_TYPE_STEP2_PRODUCER = {
    'pdf_report': 'step2_pdf_report',
    'paper_canonical_formula': 'step12_canonical_formula_intake',
    'natural_language_hypothesis': 'step12_hypothesis_intake',
}

from factor_factory.artifact_identity import (
    build_artifact_identity,
    build_code_contract_hash,
    build_custom_block_hash,
    build_formula_hash,
    build_spec_hash,
    stable_hash,
)
from factor_factory.factor_families.base import FAMILY_PLUGIN_DECISION_VERSION
from factor_factory.formula import parse_formula, to_qlib_expression
from factor_factory.formula.field_aliases import build_standard_formula_fields_contract
from factor_factory.knowledge_context import retrieve_factor_knowledge_context
from factor_factory.knowledge_reference import (
    build_knowledge_reference_contract,
    build_legacy_knowledge_reference_contract,
    resolve_runtime_retrieval_index,
    validate_knowledge_reference_contract,
)
from factor_factory.measurement_program import (
    BLOCK_MEASUREMENT_PROGRAM_INVALID,
    MEASUREMENT_PROGRAM_VERSION_V2,
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    validate_measurement_program,
)


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FACTORFORGE, WORKSPACE, OBJECTS, VALIDATION, SPEC_MASTER_DIR, HANDOFF_DIR, REGISTRY_PATH
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step2 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FACTORFORGE.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    FACTORFORGE = debug_root
    WORKSPACE = FACTORFORGE.parent
    OBJECTS = FACTORFORGE / 'objects'
    VALIDATION = OBJECTS / 'validation'
    SPEC_MASTER_DIR = OBJECTS / 'factor_spec_master'
    HANDOFF_DIR = OBJECTS / 'handoff'
    REGISTRY_PATH = FACTORFORGE / 'data' / 'report_ingestion' / 'report_registry.json'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _block_manifest_bound_adapter(reason: str) -> None:
    raise SystemExit(f'{BLOCK_MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_INVALID}: {reason}')


def _block_local_agent_spec_inputs(reason: str) -> None:
    raise SystemExit(f'{BLOCK_LOCAL_AGENT_SPEC_INPUTS_INVALID}: {reason}')


def _exact_keys(value: Dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        _block_manifest_bound_adapter(
            f'{label} keys mismatch; missing={sorted(expected - actual)} '
            f'extra={sorted(actual - expected)}'
        )


def _canonical_json_sha256(value: Dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _domain_canonical_sha256(domain: str, value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    return hashlib.sha256(domain.encode('utf-8') + b'\x00' + encoded).hexdigest()


def _semantic_value_sha256(value: Any) -> str:
    encoded = json.dumps(
        {'value': value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _strict_json_bytes(raw: bytes, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f'non-finite JSON number {value}')

    def reject_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        value: Dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f'duplicate JSON key {key!r}')
            value[key] = item
        return value

    try:
        text = raw.decode('utf-8')
        return json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _block_manifest_bound_adapter(f'{label} is not strict UTF-8 JSON: {exc}')


def _canonical_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        _block_manifest_bound_adapter(f'{label} missing')
    if any(token in value for token in ('*', '?', '[')):
        _block_manifest_bound_adapter(f'{label} cannot contain glob syntax')
    pure = PurePosixPath(value)
    if pure.is_absolute() or '..' in pure.parts or pure.as_posix() != value:
        _block_manifest_bound_adapter(f'{label} must be canonical and relative')
    return value


def _read_bound_regular_file(relative_path: str, label: str) -> Tuple[Path, bytes]:
    path = FACTORFORGE / relative_path
    root = FACTORFORGE.resolve()
    cursor = path.parent
    while cursor != FACTORFORGE.parent:
        if cursor.is_symlink():
            _block_manifest_bound_adapter(
                f'{label} ancestor directories must not be symlink aliases'
            )
        if cursor == FACTORFORGE:
            break
        cursor = cursor.parent
    if path.is_symlink() or not path.is_file():
        _block_manifest_bound_adapter(
            f'{label} must resolve to a regular non-symlink file'
        )
    if path.stat().st_nlink != 1:
        _block_manifest_bound_adapter(f'{label} must not be a hard-linked alias')
    try:
        path.resolve().relative_to(root)
    except ValueError:
        _block_manifest_bound_adapter(f'{label} escapes FACTORFORGE_ROOT')
    return path, path.read_bytes()


def _same_physical_file(left: Path, right: Path) -> bool:
    left_stat = left.stat()
    right_stat = right.stat()
    return (left_stat.st_dev, left_stat.st_ino) == (
        right_stat.st_dev,
        right_stat.st_ino,
    )


def _verify_bound_artifact(
    *,
    role: str,
    binding: Any,
    expect_json: bool,
) -> Tuple[Dict[str, Any], Any]:
    if not isinstance(binding, dict):
        _block_manifest_bound_adapter(
            f'source_step1_binding.bindings.{role} must be an object'
        )
    _exact_keys(
        binding,
        {'relative_path', 'sha256'},
        f'source_step1_binding.bindings.{role}',
    )
    relative_path = _canonical_relative_path(
        binding.get('relative_path'),
        f'source_step1_binding.bindings.{role}.relative_path',
    )
    digest = binding.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        _block_manifest_bound_adapter(
            f'source_step1_binding.bindings.{role}.sha256 must be lowercase SHA-256'
        )
    _path, raw = _read_bound_regular_file(
        relative_path,
        f'source_step1_binding.bindings.{role}',
    )
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != digest:
        _block_manifest_bound_adapter(
            f'source_step1_binding.bindings.{role}.sha256 mismatch'
        )
    parsed = _strict_json_bytes(raw, role) if expect_json else None
    return {
        'role': role,
        'relative_path': relative_path,
        'sha256': digest,
        'bytes': len(raw),
    }, parsed


def _validate_local_agent_raw_spec(
    *,
    payload: Any,
    report_id: str,
    factor_id: str,
    route: str,
) -> Dict[str, Any]:
    """Validate the ordinary raw-spec schema without inventing its semantics."""
    if not isinstance(payload, dict):
        _block_local_agent_spec_inputs(f'{route} raw spec must be a JSON object')
    missing = sorted(RAW_SPEC_REQUIRED_FIELDS - set(payload))
    if missing:
        _block_local_agent_spec_inputs(
            f'{route} raw spec required fields missing: {missing}'
        )
    unexpected = sorted(set(payload) - RAW_SPEC_ALLOWED_FIELDS)
    if unexpected:
        _block_local_agent_spec_inputs(
            f'{route} raw spec unexpected fields: {unexpected}'
        )
    if (
        payload.get('report_id') != report_id
        or payload.get('factor_id') != factor_id
        or payload.get('route') != route
    ):
        _block_local_agent_spec_inputs(
            f'{route} raw spec report_id/factor_id/route identity mismatch'
        )
    scalar_fields = (
        'factor_id', 'report_id', 'route', 'raw_formula_text',
        'rebalance_frequency',
    )
    if any(
        not isinstance(payload.get(key), str) or not payload[key].strip()
        for key in scalar_fields
    ):
        _block_local_agent_spec_inputs(
            f'{route} raw spec required scalar fields must be nonempty strings'
        )
    for key in RAW_SPEC_REQUIRED_FIELDS - set(scalar_fields):
        value = payload.get(key)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            _block_local_agent_spec_inputs(
                f'{route} raw spec {key} must be an array of nonempty strings'
            )
    if payload.get('candidate_only') not in {None, True}:
        _block_local_agent_spec_inputs(
            f'{route} raw spec candidate_only must be true when present'
        )
    if payload.get('oos_accessed') not in {None, False}:
        _block_local_agent_spec_inputs(
            f'{route} raw spec oos_accessed must be false when present'
        )
    return payload


def _local_agent_canonical_core_differences(
    *,
    primary: Dict[str, Any],
    challenger: Dict[str, Any],
    canonical_core: Any,
) -> List[str]:
    """Return field-level disagreement; never select one local route by default."""
    if not isinstance(canonical_core, dict) or set(canonical_core) != set(
        LOCAL_AGENT_SPEC_CANONICAL_CORE_FIELDS
    ):
        return ['chief_canonical_core must contain exactly the canonical core fields']
    differences: List[str] = []
    for field in LOCAL_AGENT_SPEC_CANONICAL_CORE_FIELDS:
        expected = canonical_core.get(field)
        if primary.get(field) != expected:
            differences.append(f'primary.{field} != chief_canonical_core.{field}')
        if challenger.get(field) != expected:
            differences.append(f'challenger.{field} != chief_canonical_core.{field}')
    return differences


def load_local_agent_dual_route_specs(
    report_id: str,
    aim: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]] | None:
    """Read explicitly referenced local-IS raw specs; never synthesize them.

    The small AIM object is only an authored local input declaration.  It is
    neither an independent-review receipt nor an admission/promotion contract.
    """
    refs = aim.get(LOCAL_AGENT_SPEC_INPUTS_KEY)
    if refs is None:
        return None
    if os.getenv('FACTORFORGE_LOCAL_IS_ONLY') != '1':
        _block_local_agent_spec_inputs(
            f'{LOCAL_AGENT_SPEC_INPUTS_KEY} is available only with FACTORFORGE_LOCAL_IS_ONLY=1'
        )
    if normalize_source_type(aim) != 'pdf_report':
        _block_local_agent_spec_inputs(
            f'{LOCAL_AGENT_SPEC_INPUTS_KEY} is only valid for pdf_report sources'
        )
    factor_id = aim.get('factor_id')
    if not isinstance(factor_id, str) or not factor_id.strip():
        _block_local_agent_spec_inputs('alpha_idea_master.factor_id must be nonempty')
    if aim.get('report_id') != report_id:
        _block_local_agent_spec_inputs('report_id mismatch across invocation and alpha_idea_master')
    expected_ref_keys = {*LOCAL_AGENT_SPEC_ROLES, 'chief_canonical_core'}
    if not isinstance(refs, dict) or set(refs) != expected_ref_keys:
        _block_local_agent_spec_inputs(
            f'{LOCAL_AGENT_SPEC_INPUTS_KEY} must contain primary, challenger, and chief_canonical_core'
        )

    loaded: Dict[str, Dict[str, Any]] = {}
    paths: Dict[str, Path] = {}
    for route, expected_role in LOCAL_AGENT_SPEC_ROLES.items():
        binding = refs.get(route)
        if not isinstance(binding, dict) or set(binding) != {
            'relative_path', 'sha256', 'role', 'identity',
        }:
            _block_local_agent_spec_inputs(
                f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route} must be a closed ref object'
            )
        if binding.get('role') != expected_role:
            _block_local_agent_spec_inputs(
                f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}.role mismatch'
            )
        identity = binding.get('identity')
        if identity != {
            'report_id': report_id,
            'factor_id': factor_id,
            'route': route,
        }:
            _block_local_agent_spec_inputs(
                f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}.identity mismatch'
            )
        relative_path = _canonical_relative_path(
            binding.get('relative_path'),
            f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}.relative_path',
        )
        digest = binding.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            _block_local_agent_spec_inputs(
                f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}.sha256 must be lowercase SHA-256'
            )
        path, raw = _read_bound_regular_file(
            relative_path,
            f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}',
        )
        if hashlib.sha256(raw).hexdigest() != digest:
            _block_local_agent_spec_inputs(
                f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}.sha256 mismatch'
            )
        payload = _strict_json_bytes(raw, f'{LOCAL_AGENT_SPEC_INPUTS_KEY}.{route}')
        loaded[route] = _validate_local_agent_raw_spec(
            payload=payload,
            report_id=report_id,
            factor_id=factor_id,
            route=route,
        )
        paths[route] = path
    if _same_physical_file(paths['primary'], paths['challenger']):
        _block_local_agent_spec_inputs(
            'primary and challenger local specs must be distinct physical files'
        )
    core_differences = _local_agent_canonical_core_differences(
        primary=loaded['primary'],
        challenger=loaded['challenger'],
        canonical_core=refs.get('chief_canonical_core'),
    )
    if core_differences:
        _block_local_agent_spec_inputs(
            'local route canonical core mismatch: ' + ';'.join(core_differences)
        )
    source_subject_routing = _source_subject_routing(
        aim,
        loaded['primary'],
        mechanical_passed=True,
    )
    diagnostics = source_subject_routing.get('diagnostics')
    if not isinstance(diagnostics, list) or diagnostics:
        _block_local_agent_spec_inputs(
            'AIM source-subject routing invalid: ' + ';'.join(
                str(item) for item in (diagnostics or ['routing diagnostics missing'])
            )
        )
    return loaded['primary'], loaded['challenger']


def _candidate_receipt_identity_failures(
    receipt: Any,
    *,
    expected_schema_id: str,
    report_id: str,
    factor_id: str,
    research_id: str,
    exact_fields: set[str],
    label: str,
) -> List[str]:
    if not isinstance(receipt, dict):
        return [f'{label}:not_object']
    failures: List[str] = []
    if set(receipt) != exact_fields:
        failures.append(f'{label}:closed_schema_fields')
    expected = {
        'schema_id': expected_schema_id,
        'schema_version': '1.0.0',
        'report_id': report_id,
        'factor_id': factor_id,
        'research_id': research_id,
        'candidate_only': True,
        'signed': False,
        'authority_effect': 'NONE',
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            failures.append(f'{label}:{field}')
    return failures


def _verify_receipt_binding_rows(
    rows: Any,
    *,
    expected_roles: Tuple[str, ...],
    label: str,
) -> List[Dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(expected_roles):
        _block_manifest_bound_adapter(f'{label} must have exact{len(expected_roles)} rows')
    verified: List[Dict[str, Any]] = []
    for ordinal, (expected_role, row) in enumerate(zip(expected_roles, rows)):
        if not isinstance(row, dict) or set(row) != {
            'role',
            'relative_path',
            'bytes',
            'sha256',
        }:
            _block_manifest_bound_adapter(
                f'{label}[{ordinal}] must be a closed binding row'
            )
        if row.get('role') != expected_role:
            _block_manifest_bound_adapter(
                f'{label}[{ordinal}].role must equal {expected_role}'
            )
        relative_path = _canonical_relative_path(
            row.get('relative_path'),
            f'{label}[{ordinal}].relative_path',
        )
        digest = row.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            _block_manifest_bound_adapter(
                f'{label}[{ordinal}].sha256 must be lowercase SHA-256'
            )
        _path, raw = _read_bound_regular_file(
            relative_path,
            f'{label}[{ordinal}]',
        )
        if row.get('bytes') != len(raw):
            _block_manifest_bound_adapter(f'{label}[{ordinal}].bytes mismatch')
        if digest != hashlib.sha256(raw).hexdigest():
            _block_manifest_bound_adapter(f'{label}[{ordinal}].sha256 mismatch')
        verified.append(dict(row))
    return verified


def _parse_utc_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith('Z'):
        _block_manifest_bound_adapter(f'{label} must be an ISO-8601 UTC timestamp')
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError:
        _block_manifest_bound_adapter(f'{label} is not a valid timestamp')


def _recompute_step1_validation_payload(
    *,
    report_id: str,
    aim: Dict[str, Any],
    alpha_path: Path,
) -> Dict[str, Any]:
    validator_path = (
        REPO_ROOT / 'skills/factor-forge-step1/scripts/validate_step1.py'
    )
    spec = importlib.util.spec_from_file_location(
        'factorforge_step1_pure_validator_replay',
        validator_path,
    )
    if not spec or not spec.loader:
        _block_manifest_bound_adapter(
            f'cannot load Step1 pure validator from {validator_path}'
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder = getattr(module, 'build_step1_validation_payload', None)
    if not callable(builder):
        _block_manifest_bound_adapter(
            'Step1 validator does not expose build_step1_validation_payload'
        )
    payload = builder(
        report_id,
        aim=deepcopy(aim),
        alpha_path=alpha_path,
    )
    if not isinstance(payload, dict):
        _block_manifest_bound_adapter(
            'Step1 pure validator returned a non-object payload'
        )
    return payload


def _semantic_alignment_failures(
    contract: Any,
    primary: Dict[str, Any],
    challenger: Dict[str, Any],
) -> List[str]:
    failures: List[str] = []
    if not isinstance(contract, dict):
        return ['semantic_alignment:not_object']
    expected_keys = {
        'profile_id',
        'review_status',
        'relation',
        'authority_effect',
        'shared_equal_fields',
        'dimensions',
    }
    if set(contract) != expected_keys:
        failures.append('semantic_alignment:keys')
    if contract.get('profile_id') != DUAL_ROUTE_SEMANTIC_ALIGNMENT_PROFILE:
        failures.append('semantic_alignment:profile_id')
    if contract.get('review_status') != 'PRE_RESULT_CANDIDATE_ALIGNMENT_BOUND':
        failures.append('semantic_alignment:review_status')
    if contract.get('relation') != 'COMPLEMENTARY_SOURCE_AND_MECHANISM_LATTICE':
        failures.append('semantic_alignment:relation')
    if contract.get('authority_effect') != 'NONE':
        failures.append('semantic_alignment:authority_effect')
    if contract.get('shared_equal_fields') != list(DUAL_ROUTE_SHARED_EQUAL_FIELDS):
        failures.append('semantic_alignment:shared_equal_fields')
    for field in DUAL_ROUTE_SHARED_EQUAL_FIELDS:
        if primary.get(field) != challenger.get(field):
            failures.append(f'semantic_alignment:shared_value:{field}')
    dimensions = contract.get('dimensions')
    if not isinstance(dimensions, list) or len(dimensions) != len(
        DUAL_ROUTE_SEMANTIC_FIELDS
    ):
        failures.append('semantic_alignment:dimensions')
        return failures
    for ordinal, (field, row) in enumerate(
        zip(DUAL_ROUTE_SEMANTIC_FIELDS, dimensions)
    ):
        if not isinstance(row, dict) or set(row) != {
            'ordinal',
            'field',
            'relation',
            'primary_sha256',
            'challenger_sha256',
        }:
            failures.append(f'semantic_alignment:dimension_shape:{ordinal}')
            continue
        if row.get('ordinal') != ordinal or row.get('field') != field:
            failures.append(f'semantic_alignment:dimension_identity:{ordinal}')
        expected_relation = (
            DUAL_ROUTE_EQUAL_RELATION
            if primary.get(field) == challenger.get(field)
            else DUAL_ROUTE_NONIDENTICAL_RELATION
        )
        if row.get('relation') != expected_relation:
            failures.append(f'semantic_alignment:dimension_relation:{field}')
        if row.get('primary_sha256') != _semantic_value_sha256(primary.get(field)):
            failures.append(f'semantic_alignment:primary_digest:{field}')
        if row.get('challenger_sha256') != _semantic_value_sha256(
            challenger.get(field)
        ):
            failures.append(f'semantic_alignment:challenger_digest:{field}')
    return failures


def _alpha_semantic_subject_projection(
    *,
    aim: Dict[str, Any],
    contract: Dict[str, Any],
) -> Dict[str, Any]:
    """Closed projection intentionally excluding the review receipt binding.

    This prevents an alpha -> receipt -> alpha raw-hash cycle while still
    binding every semantic input consumed by the V3 adapter.
    """
    source_binding = contract.get('source_step1_binding')
    inputs = contract.get('inputs')
    return {
        'profile_id': ALPHA_SEMANTIC_SUBJECT_PROFILE,
        'report_id': aim.get('report_id'),
        'factor_id': aim.get('factor_id'),
        'source_type': normalize_source_type(aim),
        'implementation_mode': aim.get('implementation_mode'),
        'measurement_program_sha256': _canonical_json_sha256(
            aim.get('mechanism_conditioned_measurement_program')
        ),
        'research_equation_sha256': _canonical_json_sha256(
            aim.get('research_equation')
        ),
        'source_step1_binding_sha256': _canonical_json_sha256(source_binding),
        'semantic_alignment_sha256': _canonical_json_sha256(
            contract.get('semantic_alignment')
        ),
        'inputs': deepcopy(inputs),
    }


def _semantic_review_receipt_failures(
    *,
    receipt: Any,
    aim: Dict[str, Any],
    contract: Dict[str, Any],
    primary: Dict[str, Any],
    challenger: Dict[str, Any],
    source_step1_lineage: List[Dict[str, Any]],
) -> List[str]:
    if not isinstance(receipt, dict):
        return ['independent_semantic_review:not_object']
    expected_keys = {
        'schema_id',
        'profile_id',
        'review_id',
        'report_id',
        'factor_id',
        'alpha_semantic_subject_profile',
        'alpha_semantic_subject_sha256',
        'primary_raw_sha256',
        'challenger_raw_sha256',
        'subject_identities',
        'exact10_dimensions',
        'verdict',
        'p0_count',
        'p1_count',
        'no_result_data_accessed',
        'no_oos_accessed',
        'reviewer_boundary',
        'authority_effect',
    }
    failures: List[str] = []
    if set(receipt) != expected_keys:
        failures.append('independent_semantic_review:keys')
    if receipt.get('schema_id') != INDEPENDENT_SEMANTIC_REVIEW_PROFILE:
        failures.append('independent_semantic_review:schema_id')
    if receipt.get('profile_id') != INDEPENDENT_SEMANTIC_REVIEW_PROFILE:
        failures.append('independent_semantic_review:profile_id')
    if not isinstance(receipt.get('review_id'), str) or not receipt.get('review_id'):
        failures.append('independent_semantic_review:review_id')
    if receipt.get('report_id') != aim.get('report_id'):
        failures.append('independent_semantic_review:report_id')
    if receipt.get('factor_id') != aim.get('factor_id'):
        failures.append('independent_semantic_review:factor_id')
    projection = _alpha_semantic_subject_projection(aim=aim, contract=contract)
    if receipt.get('alpha_semantic_subject_profile') != ALPHA_SEMANTIC_SUBJECT_PROFILE:
        failures.append('independent_semantic_review:subject_profile')
    if receipt.get('alpha_semantic_subject_sha256') != _domain_canonical_sha256(
        ALPHA_SEMANTIC_SUBJECT_PROFILE, projection
    ):
        failures.append('independent_semantic_review:subject_digest')
    inputs = contract.get('inputs') or {}
    if receipt.get('primary_raw_sha256') != (inputs.get('primary') or {}).get('sha256'):
        failures.append('independent_semantic_review:primary_raw_sha256')
    if receipt.get('challenger_raw_sha256') != (inputs.get('challenger') or {}).get('sha256'):
        failures.append('independent_semantic_review:challenger_raw_sha256')
    expected_identities = {
        row['role']: row['sha256'] for row in source_step1_lineage
    }
    if receipt.get('subject_identities') != expected_identities:
        failures.append('independent_semantic_review:subject_identities')
    dimensions = receipt.get('exact10_dimensions')
    if not isinstance(dimensions, list) or len(dimensions) != len(
        DUAL_ROUTE_SEMANTIC_FIELDS
    ):
        failures.append('independent_semantic_review:exact10_dimensions')
    else:
        for ordinal, (field, row) in enumerate(
            zip(DUAL_ROUTE_SEMANTIC_FIELDS, dimensions)
        ):
            if not isinstance(row, dict) or set(row) != {
                'ordinal', 'field', 'relation', 'primary_sha256',
                'challenger_sha256', 'rationale', 'evidence',
            }:
                failures.append(
                    f'independent_semantic_review:dimension_shape:{ordinal}'
                )
                continue
            if row.get('ordinal') != ordinal or row.get('field') != field:
                failures.append(
                    f'independent_semantic_review:dimension_identity:{ordinal}'
                )
            if row.get('relation') not in SEMANTIC_REVIEW_RELATIONS:
                failures.append(
                    f'independent_semantic_review:dimension_relation:{field}'
                )
            values_equal = primary.get(field) == challenger.get(field)
            if row.get('relation') == 'EQUAL' and not values_equal:
                failures.append(
                    f'independent_semantic_review:false_equal:{field}'
                )
            if row.get('relation') != 'EQUAL' and values_equal:
                failures.append(
                    f'independent_semantic_review:false_non_equal:{field}'
                )
            if (
                not isinstance(row.get('rationale'), str)
                or not row.get('rationale').strip()
                or not isinstance(row.get('evidence'), list)
                or not row.get('evidence')
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in row.get('evidence', [])
                )
            ):
                failures.append(
                    f'independent_semantic_review:dimension_evidence:{field}'
                )
            if row.get('primary_sha256') != _semantic_value_sha256(
                primary.get(field)
            ):
                failures.append(
                    f'independent_semantic_review:primary_digest:{field}'
                )
            if row.get('challenger_sha256') != _semantic_value_sha256(
                challenger.get(field)
            ):
                failures.append(
                    f'independent_semantic_review:challenger_digest:{field}'
                )
    if receipt.get('verdict') != 'GO':
        failures.append('independent_semantic_review:verdict')
    if receipt.get('p0_count') != 0 or receipt.get('p1_count') != 0:
        failures.append('independent_semantic_review:open_findings')
    if receipt.get('no_result_data_accessed') is not True:
        failures.append('independent_semantic_review:result_boundary')
    if receipt.get('no_oos_accessed') is not True:
        failures.append('independent_semantic_review:oos_boundary')
    boundary = receipt.get('reviewer_boundary')
    if not isinstance(boundary, dict) or set(boundary) != {
        'attestation_class',
        'independent_from_author',
        'independent_from_implementation',
        'reviewer_role',
        'operating_authority_granted',
    }:
        failures.append('independent_semantic_review:reviewer_boundary_shape')
    elif (
        boundary.get('attestation_class')
        != 'CANDIDATE_NON_CRYPTOGRAPHIC_DECLARATION_ONLY'
        or boundary.get('independent_from_author') is not True
        or boundary.get('independent_from_implementation') is not True
        or not isinstance(boundary.get('reviewer_role'), str)
        or not boundary.get('reviewer_role')
        or boundary.get('operating_authority_granted') is not False
    ):
        failures.append('independent_semantic_review:reviewer_boundary')
    if receipt.get('authority_effect') != 'NONE':
        failures.append('independent_semantic_review:authority_effect')
    if isinstance(dimensions, list) and any(
        isinstance(row, dict)
        and row.get('relation') in {'CONFLICTING', 'INCOMPARABLE'}
        for row in dimensions
    ):
        failures.append('independent_semantic_review:unresolved_relation')
    return failures


def _manifest_bound_candidate_marker(payload: Dict[str, Any]) -> bool:
    if payload.get('candidate_only') is True:
        return True
    for key in ('candidate_status', 'artifact_status', 'status'):
        value = payload.get(key)
        if isinstance(value, str) and value.upper().startswith('CANDIDATE_ONLY'):
            return True
    return False


def _validate_manifest_bound_raw_spec(
    *,
    payload: Dict[str, Any],
    report_id: str,
    factor_id: str,
    route: str,
) -> None:
    missing = sorted(RAW_SPEC_REQUIRED_FIELDS - set(payload))
    if missing:
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw required fields missing: {missing}'
        )
    unexpected = sorted(set(payload) - RAW_SPEC_ALLOWED_FIELDS)
    if unexpected:
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw unexpected fields: {unexpected}'
        )
    if payload.get('report_id') != report_id:
        _block_manifest_bound_adapter(f'{route} factor_spec_raw report_id mismatch')
    if payload.get('factor_id') != factor_id:
        _block_manifest_bound_adapter(f'{route} factor_spec_raw factor_id mismatch')
    if payload.get('route') != route:
        _block_manifest_bound_adapter(f'{route} factor_spec_raw route mismatch')
    if not _manifest_bound_candidate_marker(payload):
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw must carry an explicit candidate-only marker'
        )
    if payload.get('authority_effect') not in {None, 'NONE'}:
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw authority_effect must be absent/null/NONE'
        )
    authority_boundary = payload.get('authority_boundary')
    if authority_boundary is not None:
        if not isinstance(authority_boundary, dict):
            _block_manifest_bound_adapter(
                f'{route} factor_spec_raw authority_boundary must be an object'
            )
        expected_authority_boundary = {
            'candidate_only': True,
            'full_is_only': True,
            'oos_accessed': False,
            'canonical_write': False,
            'promotion': False,
            'authority_effect': 'NONE',
        }
        if authority_boundary != expected_authority_boundary:
            _block_manifest_bound_adapter(
                f'{route} factor_spec_raw authority_boundary must equal the '
                'closed candidate-only boundary'
            )
    scalar_fields = ('factor_id', 'report_id', 'route', 'raw_formula_text', 'rebalance_frequency')
    if any(not isinstance(payload.get(key), str) or not payload.get(key).strip() for key in scalar_fields):
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw required scalar fields must be nonempty strings'
        )
    list_fields = RAW_SPEC_REQUIRED_FIELDS - set(scalar_fields)
    for key in list_fields:
        value = payload.get(key)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            _block_manifest_bound_adapter(
                f'{route} factor_spec_raw {key} must be an array of nonempty strings'
            )
    if payload.get('candidate_only') not in {None, True}:
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw candidate_only must be true when present'
        )
    if payload.get('oos_accessed') not in {None, False}:
        _block_manifest_bound_adapter(
            f'{route} factor_spec_raw oos_accessed must be false when present'
        )
    for key in ('candidate_status', 'artifact_status', 'final_factor_name'):
        if key in payload and (
            not isinstance(payload.get(key), str) or not payload.get(key).strip()
        ):
            _block_manifest_bound_adapter(
                f'{route} factor_spec_raw {key} must be a nonempty string'
            )
    equation_ref = payload.get('research_equation_ref')
    if equation_ref is not None:
        _canonical_relative_path(
            equation_ref,
            f'{route} factor_spec_raw research_equation_ref',
        )


def load_manifest_bound_dual_route_pdf_specs(
    report_id: str,
    aim: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]] | None:
    """Load explicitly bound candidate specs without ambient discovery.

    Absence of the new contract deliberately preserves the legacy PDF builder.
    Once the contract is present, every malformed or unavailable input blocks;
    it never falls through to the generic PDF path.
    """
    contract = aim.get('step2_input_adapter_contract')
    if contract is None:
        return None
    if not isinstance(contract, dict):
        _block_manifest_bound_adapter('step2_input_adapter_contract must be an object')

    adapter_version = contract.get('contract_version')
    if adapter_version not in {
        MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V2,
        MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3,
    }:
        _block_manifest_bound_adapter('unsupported contract_version')
    root_keys = {
        'contract_version',
        'kind',
        'source_type',
        'report_id',
        'factor_id',
        'allow_generic_pdf_fallback',
        'required_measurement_program_contract_version',
        'require_research_equation',
        'input_authority',
        'authority_effect',
        'source_step1_binding',
        'semantic_alignment',
        'inputs',
    }
    if adapter_version == MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3:
        root_keys.add('independent_semantic_review')
    _exact_keys(contract, root_keys, 'step2_input_adapter_contract')
    if contract.get('kind') != MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_KIND:
        _block_manifest_bound_adapter('unsupported adapter kind')
    if contract.get('source_type') != 'pdf_report' or normalize_source_type(aim) != 'pdf_report':
        _block_manifest_bound_adapter('adapter and alpha source_type must both be pdf_report')
    factor_id = aim.get('factor_id')
    if not isinstance(factor_id, str) or not factor_id.strip():
        _block_manifest_bound_adapter('alpha_idea_master.factor_id must be a nonempty string')
    if aim.get('report_id') != report_id or contract.get('report_id') != report_id:
        _block_manifest_bound_adapter('report_id mismatch across invocation/alpha/contract')
    if contract.get('factor_id') != factor_id:
        _block_manifest_bound_adapter('factor_id mismatch across alpha/contract')
    if contract.get('allow_generic_pdf_fallback') is not False:
        _block_manifest_bound_adapter('allow_generic_pdf_fallback must be false')
    if contract.get('input_authority') != 'CANDIDATE_ONLY':
        _block_manifest_bound_adapter('input_authority must be CANDIDATE_ONLY')
    if contract.get('authority_effect') != 'NONE':
        _block_manifest_bound_adapter('authority_effect must be NONE')
    if contract.get('required_measurement_program_contract_version') != MEASUREMENT_PROGRAM_VERSION_V2:
        _block_manifest_bound_adapter('required measurement-program version must be v2')
    if contract.get('require_research_equation') is not True:
        _block_manifest_bound_adapter('require_research_equation must be true')

    alpha_relative_path = (
        f'objects/alpha_idea_master/alpha_idea_master__{report_id}.json'
    )
    _alpha_path, alpha_raw = _read_bound_regular_file(
        alpha_relative_path,
        'alpha_idea_master',
    )
    alpha_from_bytes = _strict_json_bytes(alpha_raw, 'alpha_idea_master')
    if alpha_from_bytes != aim:
        _block_manifest_bound_adapter(
            'alpha_idea_master bytes do not equal the in-memory adapter input'
        )
    alpha_raw_sha256 = hashlib.sha256(alpha_raw).hexdigest()

    program = aim.get('mechanism_conditioned_measurement_program')
    if not isinstance(program, dict) or program.get('contract_version') != MEASUREMENT_PROGRAM_VERSION_V2:
        _block_manifest_bound_adapter('alpha_idea_master must carry measurement-program v2')
    research_equation = program.get('research_equation')
    if not isinstance(research_equation, dict) or not research_equation:
        _block_manifest_bound_adapter('measurement-program v2 must carry research_equation')
    alpha_equation = aim.get('research_equation')
    if not isinstance(alpha_equation, dict) or not alpha_equation:
        _block_manifest_bound_adapter('alpha_idea_master.research_equation mirror missing')
    if alpha_equation != research_equation:
        _block_manifest_bound_adapter(
            'alpha research_equation mirror must equal measurement-program v2 authority'
        )
    discipline = aim.get('research_discipline')
    discipline_equation = (
        discipline.get('research_equation')
        if isinstance(discipline, dict)
        else None
    )
    if discipline_equation != research_equation:
        _block_manifest_bound_adapter(
            'research_discipline.research_equation mirror must equal measurement-program v2 authority'
        )

    source_step1_binding = contract.get('source_step1_binding')
    if not isinstance(source_step1_binding, dict):
        _block_manifest_bound_adapter('source_step1_binding must be an object')
    _exact_keys(
        source_step1_binding,
        {'profile_id', 'authority_effect', 'bindings'},
        'step2_input_adapter_contract.source_step1_binding',
    )
    if source_step1_binding.get('profile_id') != SOURCE_STEP1_BINDING_PROFILE:
        _block_manifest_bound_adapter('source_step1_binding.profile_id mismatch')
    if source_step1_binding.get('authority_effect') != 'NONE':
        _block_manifest_bound_adapter(
            'source_step1_binding.authority_effect must be NONE'
        )
    bound_inputs = source_step1_binding.get('bindings')
    if not isinstance(bound_inputs, dict):
        _block_manifest_bound_adapter(
            'source_step1_binding.bindings must be an object'
        )
    binding_roles = (
        SOURCE_STEP1_BINDING_ROLES_V3
        if adapter_version == MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3
        else SOURCE_STEP1_BINDING_ROLES
    )
    _exact_keys(
        bound_inputs,
        set(binding_roles),
        'step2_input_adapter_contract.source_step1_binding.bindings',
    )
    source_step1_lineage: List[Dict[str, Any]] = []
    source_step1_objects: Dict[str, Any] = {}
    source_step1_paths: Dict[str, Path] = {}
    for role in binding_roles:
        row, parsed = _verify_bound_artifact(
            role=role,
            binding=bound_inputs.get(role),
            expect_json=role != 'source_pdf',
        )
        source_step1_lineage.append(row)
        source_step1_objects[role] = parsed
        source_step1_paths[role] = FACTORFORGE / row['relative_path']
    for ordinal, role in enumerate(binding_roles):
        for other_role in binding_roles[ordinal + 1:]:
            if _same_physical_file(
                source_step1_paths[role], source_step1_paths[other_role]
            ):
                _block_manifest_bound_adapter(
                    f'source Step1 roles {role} and {other_role} must be '
                    'distinct physical files'
                )
    pdf_row = source_step1_lineage[0]
    pdf_path = FACTORFORGE / pdf_row['relative_path']
    if not pdf_path.read_bytes().startswith(b'%PDF-'):
        _block_manifest_bound_adapter('source_pdf is not a PDF byte stream')
    source_receipt = source_step1_objects['source_identity_receipt']
    source_receipt_failures = _candidate_receipt_identity_failures(
        source_receipt,
        expected_schema_id=SOURCE_IDENTITY_RECEIPT_SCHEMA_ID,
        report_id=report_id,
        factor_id=factor_id,
        research_id=str(aim.get('research_id') or ''),
        exact_fields={
            'schema_id',
            'schema_version',
            'report_id',
            'factor_id',
            'research_id',
            'candidate_only',
            'signed',
            'authority_effect',
            'captured_at_utc',
            'allowed_use',
            'prohibited_inference',
            'provenance_boundary',
            'document_identity',
            'object_identity',
            'pdf_readback',
            'local_capture',
        },
        label='source_identity_receipt',
    )
    if source_receipt_failures:
        _block_manifest_bound_adapter(';'.join(source_receipt_failures))
    _parse_utc_timestamp(
        source_receipt.get('captured_at_utc'),
        'source_identity_receipt.captured_at_utc',
    )
    local_capture = source_receipt.get('local_capture')
    if (
        not isinstance(local_capture, dict)
        or local_capture.get('relative_path') != pdf_row['relative_path']
        or local_capture.get('sha256') != pdf_row['sha256']
        or local_capture.get('bytes') != pdf_row['bytes']
        or local_capture.get('regular_file') is not True
        or local_capture.get('link_count') != 1
    ):
        _block_manifest_bound_adapter(
            'source_identity_receipt does not bind the selected source PDF and identity'
        )
    if (
        source_receipt.get('allowed_use')
        != 'ISOLATED_FACTOR_RESEARCH_SOURCE_READING'
        or not isinstance(source_receipt.get('prohibited_inference'), list)
        or not source_receipt.get('prohibited_inference')
    ):
        _block_manifest_bound_adapter(
            'source_identity_receipt use/prohibition boundary mismatch'
        )
    provenance = source_receipt.get('provenance_boundary')
    if (
        not isinstance(provenance, dict)
        or provenance.get('s3_object_identity_verified') is not True
        or provenance.get('local_bytes_bound_to_s3_readback') is not True
        or provenance.get('full_report_acquired') is not True
        or provenance.get('official_publisher_origin_authenticated') is not False
        or provenance.get('pristine_publisher_byte_identity_claimed') is not False
    ):
        _block_manifest_bound_adapter(
            'source_identity_receipt provenance boundary mismatch'
        )
    object_identity = source_receipt.get('object_identity')
    if (
        not isinstance(object_identity, dict)
        or object_identity.get('provider') != 'AWS_S3'
        or object_identity.get('content_length') != pdf_row['bytes']
        or not isinstance(object_identity.get('s3_uri'), str)
        or not object_identity.get('s3_uri').startswith('s3://')
    ):
        _block_manifest_bound_adapter(
            'source_identity_receipt object identity mismatch'
        )
    pdf_readback = source_receipt.get('pdf_readback')
    if (
        not isinstance(pdf_readback, dict)
        or pdf_readback.get('encrypted') is not False
        or pdf_readback.get('javascript') is not False
        or not isinstance(pdf_readback.get('pages'), int)
        or pdf_readback.get('pages', 0) <= 0
    ):
        _block_manifest_bound_adapter(
            'source_identity_receipt PDF readback mismatch'
        )
    text_extraction = pdf_readback.get('text_extraction')
    if not isinstance(text_extraction, dict):
        _block_manifest_bound_adapter(
            'source_identity_receipt text_extraction missing'
        )
    _verify_receipt_binding_rows(
        [{
            'role': 'source_text_extraction',
            'relative_path': text_extraction.get('relative_path'),
            'bytes': text_extraction.get('bytes'),
            'sha256': text_extraction.get('sha256'),
        }],
        expected_roles=('source_text_extraction',),
        label='source_identity_receipt.pdf_readback.text_extraction',
    )

    freeze_receipt = source_step1_objects['source_first_freeze_receipt']
    freeze_failures = _candidate_receipt_identity_failures(
        freeze_receipt,
        expected_schema_id=SOURCE_FREEZE_RECEIPT_SCHEMA_ID,
        report_id=report_id,
        factor_id=factor_id,
        research_id=str(aim.get('research_id') or ''),
        exact_fields={
            'schema_id',
            'schema_version',
            'report_id',
            'factor_id',
            'research_id',
            'candidate_only',
            'signed',
            'authority_effect',
            'frozen_at_utc',
            'bindings',
            'source_boundary',
            'reading_process',
            'retrieval_boundary',
            'outcome_exposure',
            'source_first_compiler_preflight',
        },
        label='source_first_freeze_receipt',
    )
    if freeze_failures:
        _block_manifest_bound_adapter(';'.join(freeze_failures))
    freeze_time = _parse_utc_timestamp(
        freeze_receipt.get('frozen_at_utc'),
        'source_first_freeze_receipt.frozen_at_utc',
    )
    _verify_receipt_binding_rows(
        freeze_receipt.get('bindings'),
        expected_roles=SOURCE_FREEZE_BINDING_ROLES,
        label='source_first_freeze_receipt.bindings',
    )
    retrieval_boundary = freeze_receipt.get('retrieval_boundary')
    outcome_exposure = freeze_receipt.get('outcome_exposure')
    compiler_preflight = freeze_receipt.get('source_first_compiler_preflight')
    if (
        not isinstance(retrieval_boundary, dict)
        or retrieval_boundary.get('knowledge_retrieval_started_before_freeze')
        is not False
        or retrieval_boundary.get(
            'code_or_data_availability_consulted_before_freeze'
        ) is not False
        or retrieval_boundary.get(
            'current_factor_failure_or_metrics_consulted_before_freeze'
        ) is not False
        or not isinstance(outcome_exposure, dict)
        or outcome_exposure.get('current_factor_is_metrics_seen') is not False
        or outcome_exposure.get('oos_seen') is not False
        or not isinstance(compiler_preflight, dict)
        or compiler_preflight.get('verdict') != 'PASS'
        or compiler_preflight.get('retrieval_executed') is not False
    ):
        _block_manifest_bound_adapter(
            'source_first_freeze_receipt isolation/preflight mismatch'
        )

    successor_receipt = source_step1_objects['source_first_successor_receipt']
    successor_failures = _candidate_receipt_identity_failures(
        successor_receipt,
        expected_schema_id=SOURCE_SUCCESSOR_RECEIPT_SCHEMA_ID,
        report_id=report_id,
        factor_id=factor_id,
        research_id=str(aim.get('research_id') or ''),
        exact_fields={
            'schema_id',
            'schema_version',
            'report_id',
            'factor_id',
            'research_id',
            'candidate_only',
            'signed',
            'authority_effect',
            'created_at_utc',
            'predecessor',
            'state_transition',
            'successor_bindings',
            'temporal_order',
            'operating_boundary',
            'semantic_comparison',
        },
        label='source_first_successor_receipt',
    )
    if successor_failures:
        _block_manifest_bound_adapter(';'.join(successor_failures))
    successor_time = _parse_utc_timestamp(
        successor_receipt.get('created_at_utc'),
        'source_first_successor_receipt.created_at_utc',
    )
    if successor_time <= freeze_time:
        _block_manifest_bound_adapter(
            'source successor timestamp must be after source-first freeze'
        )
    predecessor = successor_receipt.get('predecessor')
    freeze_row = next(
        row
        for row in source_step1_lineage
        if row.get('role') == 'source_first_freeze_receipt'
    )
    if predecessor != {
        'relative_path': freeze_row['relative_path'],
        'bytes': freeze_row['bytes'],
        'sha256': freeze_row['sha256'],
        'frozen_bytes_modified': False,
    }:
        _block_manifest_bound_adapter(
            'source successor predecessor does not exactly bind freeze receipt'
        )
    successor_rows = _verify_receipt_binding_rows(
        successor_receipt.get('successor_bindings'),
        expected_roles=SOURCE_SUCCESSOR_BINDING_ROLES,
        label='source_first_successor_receipt.successor_bindings',
    )
    expected_successor_bindings = {
        's3_report_object': (
            pdf_row['relative_path'],
            pdf_row['bytes'],
            pdf_row['sha256'],
        ),
        'source_identity_receipt': (
            next(
                row['relative_path']
                for row in source_step1_lineage
                if row.get('role') == 'source_identity_receipt'
            ),
            next(
                row['bytes']
                for row in source_step1_lineage
                if row.get('role') == 'source_identity_receipt'
            ),
            next(
                row['sha256']
                for row in source_step1_lineage
                if row.get('role') == 'source_identity_receipt'
            ),
        ),
    }
    for row in successor_rows:
        expected = expected_successor_bindings.get(row['role'])
        if expected and (
            row['relative_path'],
            row['bytes'],
            row['sha256'],
        ) != expected:
            _block_manifest_bound_adapter(
                f"source successor {row['role']} crosswalk mismatch"
            )
    transition = successor_receipt.get('state_transition')
    temporal_order = successor_receipt.get('temporal_order')
    operating_boundary = successor_receipt.get('operating_boundary')
    semantic_comparison = successor_receipt.get('semantic_comparison')
    if (
        not isinstance(transition, dict)
        or transition.get('review_eligible') is not False
        or transition.get('source_reported_outcomes_only') is not True
        or not isinstance(temporal_order, dict)
        or temporal_order.get(
            'source_first_freeze_precedes_knowledge_retrieval'
        ) is not True
        or temporal_order.get('s3_original_capture_is_not_pre_a0') is not True
        or temporal_order.get('retroactive_prediction_rewrite_allowed')
        is not False
        or not isinstance(operating_boundary, dict)
        or operating_boundary.get('current_factor_metrics_accessed') is not False
        or operating_boundary.get('oos_values_accessed') is not False
        or operating_boundary.get('canonical_write') is not False
        or operating_boundary.get('promotion') is not False
        or not isinstance(semantic_comparison, dict)
        or semantic_comparison.get('formula_uniquely_recoverable') is not False
    ):
        _block_manifest_bound_adapter(
            'source successor temporal/operating/semantic boundary mismatch'
        )
    bound_program = source_step1_objects['measurement_program']
    if bound_program != program:
        _block_manifest_bound_adapter(
            'bound measurement_program bytes do not equal alpha measurement-program v2'
        )
    bound_equation = source_step1_objects['research_equation']
    if not isinstance(bound_equation, dict):
        _block_manifest_bound_adapter('bound research_equation must be an object')
    equation_projection = {
        key: value
        for key, value in bound_equation.items()
        if key not in {'contract_status', 'authority_effect'}
    }
    if equation_projection != research_equation:
        _block_manifest_bound_adapter(
            'bound research_equation projection does not equal measurement-program v2'
        )
    program_failures = validate_measurement_program(
        bound_program,
        available_knowledge_node_ids=_step1_knowledge_node_ids(aim),
        require_web_executable=False,
        compatibility_profile=(aim.get('research_compatibility_profile') or (aim.get('research_discipline') or {}).get('research_compatibility_profile')),
        scope='local_is_only' if os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1' else 'hosted_formal',
    )
    if program_failures:
        _block_manifest_bound_adapter(
            'bound measurement_program does not replay Step1 validation: '
            + ';'.join(program_failures)
        )
    step1_validation = source_step1_objects['step1_validation']
    if not isinstance(step1_validation, dict) or set(step1_validation) != {
        'report_id',
        'result',
        'checks',
        'errors',
        'warnings',
    }:
        _block_manifest_bound_adapter(
            'bound Step1 validation receipt must have the closed validation shape'
        )
    validation_checks = step1_validation.get('checks')
    if (
        step1_validation.get('report_id') != report_id
        or step1_validation.get('result') != 'PASS'
        or step1_validation.get('errors') != []
        or step1_validation.get('warnings') != []
        or not isinstance(validation_checks, list)
        or [row.get('name') for row in validation_checks if isinstance(row, dict)]
        != list(STEP1_VALIDATION_CHECK_NAMES)
        or any(
            not isinstance(row, dict)
            or set(row) != {'name', 'ok', 'status', 'severity', 'error'}
            or row.get('ok') is not True
            or row.get('status') != 'PASS'
            or row.get('error') is not None
            for row in validation_checks
        )
    ):
        _block_manifest_bound_adapter(
            'bound Step1 validation receipt is not a replayable exact22 PASS'
        )
    recomputed_step1_validation = _recompute_step1_validation_payload(
        report_id=report_id,
        aim=aim,
        alpha_path=_alpha_path,
    )
    if recomputed_step1_validation != step1_validation:
        _block_manifest_bound_adapter(
            'bound Step1 validation receipt does not equal pure-validator replay'
        )

    inputs = contract.get('inputs')
    if not isinstance(inputs, dict):
        _block_manifest_bound_adapter('inputs must be an object')
    _exact_keys(inputs, {'primary', 'challenger'}, 'step2_input_adapter_contract.inputs')

    loaded: Dict[str, Dict[str, Any]] = {}
    lineage_inputs: List[Dict[str, Any]] = []
    for route in ('primary', 'challenger'):
        row = inputs.get(route)
        if not isinstance(row, dict):
            _block_manifest_bound_adapter(f'inputs.{route} must be an object')
        _exact_keys(row, {'route', 'relative_path', 'sha256'}, f'inputs.{route}')
        if row.get('route') != route:
            _block_manifest_bound_adapter(f'inputs.{route}.route mismatch')
        relative_path = row.get('relative_path')
        digest = row.get('sha256')
        relative_path = _canonical_relative_path(
            relative_path,
            f'inputs.{route}.relative_path',
        )
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            _block_manifest_bound_adapter(f'inputs.{route}.sha256 must be lowercase SHA-256')
        expected_relative = (
            f'objects/validation/factor_spec_raw__{route}__{report_id}.json'
        )
        if relative_path != expected_relative:
            _block_manifest_bound_adapter(
                f'inputs.{route}.relative_path must equal {expected_relative}'
            )
        _path, raw = _read_bound_regular_file(relative_path, f'inputs.{route}')
        actual_digest = hashlib.sha256(raw).hexdigest()
        if actual_digest != digest:
            _block_manifest_bound_adapter(f'inputs.{route}.sha256 mismatch')
        payload = _strict_json_bytes(raw, f'inputs.{route}')
        if not isinstance(payload, dict):
            _block_manifest_bound_adapter(f'inputs.{route} JSON root must be an object')
        _validate_manifest_bound_raw_spec(
            payload=payload,
            report_id=report_id,
            factor_id=factor_id,
            route=route,
        )
        loaded[route] = payload
        lineage_inputs.append({
            'route': route,
            'relative_path': relative_path,
            'sha256': digest,
            'bytes': len(raw),
            'input_authority': 'CANDIDATE_ONLY',
            'authority_effect': 'NONE',
        })

    primary_path = FACTORFORGE / lineage_inputs[0]['relative_path']
    challenger_path = FACTORFORGE / lineage_inputs[1]['relative_path']
    if _same_physical_file(primary_path, challenger_path):
        _block_manifest_bound_adapter(
            'primary and challenger inputs must be distinct physical files'
        )

    semantic_alignment = contract.get('semantic_alignment')
    semantic_failures = _semantic_alignment_failures(
        semantic_alignment,
        loaded['primary'],
        loaded['challenger'],
    )
    if semantic_failures:
        _block_manifest_bound_adapter(';'.join(semantic_failures))

    semantic_review_satisfied = False
    semantic_review_lineage = None
    if adapter_version == MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3:
        review_binding = contract.get('independent_semantic_review')
        if not isinstance(review_binding, dict):
            _block_manifest_bound_adapter(
                'independent_semantic_review binding must be an object'
            )
        _exact_keys(
            review_binding,
            {'relative_path', 'sha256'},
            'independent_semantic_review',
        )
        review_relative = _canonical_relative_path(
            review_binding.get('relative_path'),
            'independent_semantic_review.relative_path',
        )
        review_sha = review_binding.get('sha256')
        if not isinstance(review_sha, str) or not re.fullmatch(
            r'[0-9a-f]{64}', review_sha
        ):
            _block_manifest_bound_adapter(
                'independent_semantic_review.sha256 must be lowercase SHA-256'
            )
        _review_path, review_raw = _read_bound_regular_file(
            review_relative,
            'independent_semantic_review',
        )
        if hashlib.sha256(review_raw).hexdigest() != review_sha:
            _block_manifest_bound_adapter(
                'independent_semantic_review.sha256 mismatch'
            )
        review_receipt = _strict_json_bytes(
            review_raw,
            'independent_semantic_review',
        )
        review_failures = _semantic_review_receipt_failures(
            receipt=review_receipt,
            aim=aim,
            contract=contract,
            primary=loaded['primary'],
            challenger=loaded['challenger'],
            source_step1_lineage=source_step1_lineage,
        )
        if review_failures:
            _block_manifest_bound_adapter(';'.join(review_failures))
        semantic_review_satisfied = True
        semantic_review_lineage = {
            'profile_id': INDEPENDENT_SEMANTIC_REVIEW_PROFILE,
            'relative_path': review_relative,
            'raw_sha256': review_sha,
            'canonical_sha256': _canonical_json_sha256(review_receipt),
            'review_id': review_receipt['review_id'],
            'verdict': review_receipt['verdict'],
            'p0_count': 0,
            'p1_count': 0,
            'authority_effect': 'NONE',
        }

    lineage = {
        'schema_id': 'factorforge_step2_manifest_bound_input_lineage_v1',
        'adapter_contract_version': adapter_version,
        'adapter_kind': MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_KIND,
        'adapter_contract_canonical_sha256': _canonical_json_sha256(contract),
        'alpha_idea_master_relative_path': alpha_relative_path,
        'alpha_idea_master_raw_sha256': alpha_raw_sha256,
        'alpha_idea_master_bytes': len(alpha_raw),
        'alpha_idea_master_canonical_sha256': _canonical_json_sha256(aim),
        'selection_source': 'alpha_idea_master.step2_input_adapter_contract',
        'report_id': report_id,
        'factor_id': factor_id,
        'input_authority': 'CANDIDATE_ONLY',
        'authority_effect': 'NONE',
        'admission_effect': 'NONE',
        'generic_pdf_fallback_used': False,
        'measurement_program_contract_version': MEASUREMENT_PROGRAM_VERSION_V2,
        'measurement_program_canonical_sha256': _canonical_json_sha256(program),
        'research_equation_source': 'mechanism_conditioned_measurement_program.research_equation',
        'research_equation_canonical_sha256': _canonical_json_sha256(
            research_equation
        ),
        'source_step1_binding_profile': SOURCE_STEP1_BINDING_PROFILE,
        'source_step1_binding_canonical_sha256': _canonical_json_sha256(
            source_step1_binding
        ),
        'source_step1_inputs': source_step1_lineage,
        'semantic_alignment_profile': DUAL_ROUTE_SEMANTIC_ALIGNMENT_PROFILE,
        'semantic_alignment_canonical_sha256': _canonical_json_sha256(
            semantic_alignment
        ),
        'semantic_review_required': any(
            row.get('relation') == DUAL_ROUTE_NONIDENTICAL_RELATION
            for row in semantic_alignment.get('dimensions', [])
            if isinstance(row, dict)
        ),
        'semantic_review_satisfied': semantic_review_satisfied,
        'independent_semantic_review': semantic_review_lineage,
        'inputs': lineage_inputs,
        'formalization_rule': (
            'candidate raw specs are evidence inputs only; factor_spec_master is a '
            'derived Step2 artifact and requires its own formal validation'
        ),
    }
    return loaded['primary'], loaded['challenger'], lineage


def _step1_knowledge_node_ids(aim: Dict[str, Any]) -> set[str]:
    discipline = aim.get('research_discipline') if isinstance(aim.get('research_discipline'), dict) else {}
    context = discipline.get('factor_knowledge_context') if isinstance(discipline.get('factor_knowledge_context'), dict) else {}
    node_ids = {
        str(item.get('id'))
        for item in context.get('nodes') or []
        if isinstance(item, dict) and item.get('id')
    }
    knowledge = discipline.get('knowledge_reference_contract') if isinstance(discipline.get('knowledge_reference_contract'), dict) else {}
    node_ids.update(str(item) for item in knowledge.get('cited_node_ids') or [] if str(item).strip())
    return node_ids


def validated_step1_measurement_program(
    *,
    aim: Dict[str, Any],
    primary: Dict[str, Any],
    implementation_mode: str,
) -> Dict[str, Any]:
    discipline = aim.get('research_discipline') if isinstance(aim.get('research_discipline'), dict) else {}
    candidates = [
        value
        for value in (
            primary.get('mechanism_conditioned_measurement_program'),
            aim.get('mechanism_conditioned_measurement_program'),
            discipline.get('mechanism_conditioned_measurement_program'),
        )
        if isinstance(value, dict) and value
    ]
    if not candidates:
        raise SystemExit(
            f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: Step1 measurement program missing'
        )
    program = candidates[0]
    if any(item != program for item in candidates[1:]):
        raise SystemExit(
            f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: Step1 measurement program copies mismatch'
        )
    reasons = validate_measurement_program(
        program,
        available_knowledge_node_ids=_step1_knowledge_node_ids(aim),
        require_web_executable=False,
        compatibility_profile=(aim.get('research_compatibility_profile') or (aim.get('research_discipline') or {}).get('research_compatibility_profile')),
        scope='local_is_only' if os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1' else 'hosted_formal',
    )
    route = (
        (program.get('implementation') or {}).get('route')
        if isinstance(program.get('implementation'), dict)
        else None
    )
    if route != implementation_mode:
        reasons.append(
            'measurement_program.implementation.route_implementation_mode_mismatch'
        )
    if reasons:
        raise SystemExit(
            f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: ' + ';'.join(reasons)
        )
    return deepcopy(program)
    print(f'[WRITE] {path}')


def load_alpha_idea_master(report_id: str) -> Dict[str, Any]:
    path = OBJECTS / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json'
    if not path.exists():
        raise FileNotFoundError(f'alpha_idea_master not found: {path}')
    return load_json(path)


def load_registry_record(report_id: str) -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f'report_registry not found: {REGISTRY_PATH}')
    reg = load_json(REGISTRY_PATH)
    if report_id not in reg:
        raise KeyError(f'report_id not found in registry: {report_id}')
    return reg[report_id]


def locate_pdf_path(report_id: str, aim: Dict[str, Any]) -> str:
    rec = load_registry_record(report_id)
    local_cache_path = rec.get('local_cache_path')
    if local_cache_path and Path(local_cache_path).exists():
        return local_cache_path

    handoff = HANDOFF_DIR / f'handoff__{report_id}.json'
    if handoff.exists():
        h = load_json(handoff)
        for key in ['pdf_path', 'local_cache_path', 'source_path']:
            v = h.get(key)
            if v and Path(v).exists():
                return v

    for key in ['source_uri', 'local_cache_path', 'pdf_path']:
        v = aim.get(key)
        if isinstance(v, str) and Path(v).exists():
            return v

    raise FileNotFoundError('No usable local PDF path found via registry / handoff / alpha_idea_master')


def read_step1_upstream(report_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    primary_thesis = load_json(VALIDATION / f'report_map_validation__{report_id}__alpha_thesis.json')
    challenger_thesis = load_json(VALIDATION / f'report_map_validation__{report_id}__challenger_alpha_thesis.json')
    primary_report_map = load_json(OBJECTS / 'report_maps' / f'report_map__{report_id}__primary.json')
    return primary_thesis, challenger_thesis, primary_report_map


def normalize_source_type(aim: Dict[str, Any]) -> str:
    raw = str(aim.get('source_type') or aim.get('source_kind') or '').strip()
    if raw in {'pdf', 'html', 'report', 'research_report'}:
        return 'pdf_report'
    if not raw:
        return 'pdf_report'
    if raw not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f'unsupported source_type for Step2: {raw}')
    return raw


def formal_step2_producer(source_type: str) -> str:
    return SOURCE_TYPE_STEP2_PRODUCER[source_type]


def hybrid_contract_executable(contract: Dict[str, Any]) -> bool:
    operator_subgraph = contract.get('operator_subgraph') if isinstance(contract.get('operator_subgraph'), dict) else {}
    formula_ir = operator_subgraph.get('formula_ir') if isinstance(operator_subgraph.get('formula_ir'), dict) else {}
    custom_blocks = contract.get('custom_blocks')
    return bool(
        contract.get('hybrid_contract_version') == HYBRID_CONTRACT_VERSION
        and formula_ir
        and formula_ir.get('parse_status') == 'success'
        and isinstance(custom_blocks, list)
        and custom_blocks
        and contract.get('formula_hash')
        and contract.get('custom_block_hash')
        and contract.get('hybrid_hash')
    )


def direct_code_contract_available(primary: Dict[str, Any], aim: Dict[str, Any]) -> bool:
    return bool(explicit_direct_code_source_contract(primary, aim))


def formula_ir_executable(primary: Dict[str, Any]) -> bool:
    formula_ir = primary.get('formula_ir') if isinstance(primary.get('formula_ir'), dict) else {}
    return bool(formula_ir and formula_ir.get('parse_status') == 'success')


def explicit_direct_code_source_contract(primary: Dict[str, Any], aim: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for payload in [primary, aim]:
        if not isinstance(payload, dict):
            continue
        raw_contract = payload.get('implementation_contract') if isinstance(payload.get('implementation_contract'), dict) else {}
        for candidate in [
            raw_contract.get('code_contract') if isinstance(raw_contract.get('code_contract'), dict) else {},
            payload.get('code_contract') if isinstance(payload.get('code_contract'), dict) else {},
            payload.get('direct_code_contract') if isinstance(payload.get('direct_code_contract'), dict) else {},
            (payload.get('canonical_spec') or {}).get('code_contract') if isinstance(payload.get('canonical_spec'), dict) and isinstance((payload.get('canonical_spec') or {}).get('code_contract'), dict) else {},
        ]:
            if candidate:
                candidates.append(candidate)

    for candidate in candidates:
        source = str(candidate.get('source_code') or candidate.get('code') or candidate.get('custom_source') or '').strip()
        if not source:
            continue
        source = source if source.endswith('\n') else source + '\n'
        imports = candidate.get('imports') or candidate.get('dependencies') or ['numpy', 'pandas']
        if not isinstance(imports, list):
            imports = [str(imports)]
        output_schema = candidate.get('output_schema') or {'columns': ['ts_code', 'trade_date', 'factor_value']}
        contract = {
            **candidate,
            'code_contract_version': candidate.get('code_contract_version') or 'factorforge_direct_code_contract_v1',
            'function_name': candidate.get('function_name') or candidate.get('entrypoint') or 'compute_factor',
            'entrypoint': candidate.get('entrypoint') or candidate.get('function_name') or 'compute_factor',
            'source_code': source,
            'code_hash': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'imports': imports,
            'dependencies': candidate.get('dependencies') or imports,
            'input_schema': candidate.get('input_schema') or {},
            'output_schema': output_schema,
            'required_fields': candidate.get('required_fields') or primary.get('required_inputs', []),
            'information_set_rules': candidate.get('information_set_rules') or ['no future-looking fields or negative shifts'],
            'forbidden_patterns': candidate.get('forbidden_patterns') or DEFAULT_FORBIDDEN_CODE_PATTERNS,
            'source_derivation': candidate.get('source_derivation') or {
                'derivation': 'source_code_preserved_from_formal_step2_raw_direct_code_contract',
                'not_fallback': True,
            },
        }
        return contract
    return {}


def infer_implementation_mode(source_type: str, primary: Dict[str, Any], aim: Dict[str, Any]) -> str:
    explicit = aim.get('implementation_mode') or primary.get('implementation_mode')
    if explicit:
        value = str(explicit)
        if value in {'operator', 'direct_code'}:
            return value
        if value == 'hybrid':
            hybrid_contract = build_hybrid_contract(primary, aim)
            if hybrid_contract_executable(hybrid_contract):
                return 'hybrid'
            return 'hybrid'
    if formula_ir_executable(primary):
        return 'operator'
    if direct_code_contract_available(primary, aim):
        return 'direct_code'
    if source_type == 'paper_canonical_formula':
        return 'operator'
    return 'operator'


def build_mode_decision(implementation_mode: str, primary: Dict[str, Any], aim: Dict[str, Any] | None = None) -> Dict[str, Any]:
    formula_ir = primary.get('formula_ir')
    parse_error = primary.get('formula_parse_error')
    direct_source_available = bool(explicit_direct_code_source_contract(primary, aim or {}))
    operator_success = (
        implementation_mode == 'operator'
        and isinstance(formula_ir, dict)
        and formula_ir.get('parse_status') == 'success'
    )
    return {
        'selected_mode': implementation_mode,
        'operator_attempted': True,
        'operator_result': 'success' if operator_success else ('failed' if parse_error else 'not_applicable'),
        'operator_failure_reason': None if operator_success else (parse_error or 'source requires non-operator implementation contract'),
        'hybrid_attempted': implementation_mode in {'hybrid', 'direct_code'},
        'hybrid_result': 'success' if implementation_mode == 'hybrid' else 'not_applicable',
        'hybrid_failure_reason': None if implementation_mode == 'hybrid' else 'not selected by Step2 contract',
        'direct_code_attempted': implementation_mode == 'direct_code',
        'direct_code_result': (
            'success' if implementation_mode == 'direct_code' and direct_source_available else
            'failed' if implementation_mode == 'direct_code' else
            'not_applicable'
        ),
        'direct_code_failure_reason': (
            None if implementation_mode == 'direct_code' and direct_source_available else
            'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: explicit direct_code mode requires source_code contract'
            if implementation_mode == 'direct_code' else
            'not selected by Step2 contract'
        ),
        'final_decision_reason': (
            'formula parsed into registered operator IR'
            if operator_success else
            'explicit source_code direct_code contract provided'
            if implementation_mode == 'direct_code' and direct_source_available else
            'direct_code selected explicitly but source_code contract is missing'
            if implementation_mode == 'direct_code' else
            'operator path selected; validator must confirm formula_ir'
        ),
    }


def build_hybrid_contract(primary: Dict[str, Any], aim: Dict[str, Any]) -> Dict[str, Any]:
    raw_contract = aim.get('implementation_contract') or primary.get('implementation_contract') or {}
    raw_operator = raw_contract.get('operator_subgraph') or primary.get('operator_subgraph') or {}
    formula_text = (
        raw_operator.get('formula_text')
        or primary.get('operator_subgraph_formula')
        or primary.get('raw_formula_text')
        or aim.get('operator_subgraph_formula')
        or aim.get('raw_formula')
        or ''
    )
    formula_ir = raw_operator.get('formula_ir')
    if not isinstance(formula_ir, dict) and formula_text:
        formula_ir = parse_formula(str(formula_text))
    operator_subgraph = {
        'formula_text': formula_text,
        'formula_ir_version': (formula_ir or {}).get('formula_ir_version'),
        'formula_ir': formula_ir or {},
        'operator_set': (formula_ir or {}).get('operator_set') or raw_operator.get('operator_set') or [],
        'required_fields': (formula_ir or {}).get('required_fields') or raw_operator.get('required_fields') or [],
        'resolved_fields': (formula_ir or {}).get('resolved_fields') or raw_operator.get('resolved_fields') or {},
        'formula_hash': (formula_ir or {}).get('formula_hash') or raw_operator.get('formula_hash') or stable_hash({'formula_text': formula_text}),
    }

    raw_blocks = raw_contract.get('custom_blocks') or primary.get('custom_blocks') or aim.get('custom_blocks') or []
    custom_blocks = []
    block_hash_inputs = []
    for idx, block in enumerate(raw_blocks if isinstance(raw_blocks, list) else [raw_blocks]):
        if not isinstance(block, dict):
            continue
        source_code = block.get('source_code') or block.get('code') or block.get('custom_source') or ''
        normalized = {
            'name': block.get('name') or f'custom_block_{idx + 1}',
            'purpose': block.get('purpose') or 'custom hybrid post-processing block',
            'function_name': block.get('function_name') or 'apply_custom_block',
            'input_schema': block.get('input_schema') or {'columns': ['ts_code', 'trade_date', 'operator_value'] + list(block.get('required_fields') or [])},
            'output_schema': block.get('output_schema') or {'columns': ['ts_code', 'trade_date', 'factor_value']},
            'required_fields': block.get('required_fields') or [],
            'forbidden_patterns': list(dict.fromkeys(DEFAULT_FORBIDDEN_CODE_PATTERNS + list(block.get('forbidden_patterns') or []))),
            'source_code': source_code,
        }
        block_hash = stable_hash({
            'source_code': source_code,
            'contract': {k: v for k, v in normalized.items() if k not in {'custom_block_hash'}},
        })
        normalized['custom_block_hash'] = block.get('custom_block_hash') or block_hash
        block_hash_inputs.append({'name': normalized['name'], 'custom_block_hash': normalized['custom_block_hash']})
        custom_blocks.append(normalized)

    custom_block_hash = raw_contract.get('custom_block_hash') or stable_hash(block_hash_inputs)
    required_custom_fields = []
    for block in custom_blocks:
        required_custom_fields.extend(str(field) for field in (block.get('required_fields') or []) if field)
    boundary = raw_contract.get('boundary') or {
        'operator_outputs': ['operator_value'],
        'custom_inputs': list(dict.fromkeys(['ts_code', 'trade_date', 'operator_value'] + required_custom_fields)),
        'custom_outputs': ['factor_value'],
        'protected_operator_outputs': ['operator_value'],
        'allow_operator_output_overwrite': False,
    }
    formula_hash = operator_subgraph.get('formula_hash')
    hybrid_hash = raw_contract.get('hybrid_hash') or stable_hash({
        'formula_hash': formula_hash,
        'custom_block_hash': custom_block_hash,
        'boundary': boundary,
    })
    return {
        'mode': 'hybrid',
        'implementation_mode': 'hybrid',
        'hybrid_contract_version': HYBRID_CONTRACT_VERSION,
        'operator_subgraph': operator_subgraph,
        'custom_blocks': custom_blocks,
        'boundary': boundary,
        'formula_hash': formula_hash,
        'custom_block_hash': custom_block_hash,
        'hybrid_hash': hybrid_hash,
    }


def explicit_family_plugin_selection(aim: Dict[str, Any], primary: Dict[str, Any]) -> Dict[str, Any]:
    """Propagate only explicit structured family-plugin declarations.

    Free-text mentions such as "shadow", "Williams", "candle", or price-volume shorthand
    may become suggestions, but they must not become executable plugin selection.
    """
    contract = aim.get('implementation_contract') or {}
    decision = aim.get('family_plugin_decision') or contract.get('family_plugin_decision') or {}
    family = aim.get('factor_family') or contract.get('factor_family') or primary.get('factor_family')
    plugin = aim.get('family_plugin') or contract.get('family_plugin') or primary.get('family_plugin')
    allowed = bool(aim.get('family_plugin_allowed') or contract.get('family_plugin_allowed') or primary.get('family_plugin_allowed'))
    if allowed and family and plugin:
        evidence = (
            decision.get('explicit_evidence')
            or aim.get('family_plugin_explicit_evidence')
            or contract.get('family_plugin_explicit_evidence')
            or primary.get('family_plugin_explicit_evidence')
            or []
        )
        evidence = as_list(evidence)
        return {
            'factor_family': str(family),
            'family_plugin': str(plugin),
            'family_plugin_allowed': True,
            'family_plugin_decision': {
                'decision_version': decision.get('decision_version') or FAMILY_PLUGIN_DECISION_VERSION,
                'plugin_selected': True,
                'plugin_id': str(plugin),
                'selection_reason': decision.get('selection_reason') or 'Explicit source artifact declared this family plugin.',
                'explicit_evidence': evidence,
                'not_selected_by_free_text': decision.get('not_selected_by_free_text', True),
                'human_review_required': bool(decision.get('human_review_required', not evidence)),
            },
        }

    suggestion_text = text_blob(aim, primary)
    if any(token in suggestion_text for token in ['shadow', 'williams', 'candlestick', '上影线', '下影线']):
        return {
            'family_plugin_suggestion': {
                'suggested_family': 'shadow_candlestick',
                'reason': 'source text mentions shadow/candlestick semantics',
                'formal_selection': False,
                'human_review_required': True,
            }
        }
    if 'price-volume' in suggestion_text or '价量' in suggestion_text:
        return {
            'family_plugin_suggestion': {
                'suggested_family': 'price_volume',
                'reason': 'source text mentions price-volume semantics',
                'formal_selection': False,
                'human_review_required': True,
            }
        }
    return {}


def load_source_context(report_id: str, aim: Dict[str, Any]) -> Dict[str, Any]:
    source_type = normalize_source_type(aim)
    if source_type == 'pdf_report':
        pdf_path = locate_pdf_path(report_id, aim)
        print(f'[FOUND] pdf_path={pdf_path}')
    else:
        pdf_path = None
        print(f'[SOURCE] {source_type}: no report_registry/PDF lookup required')
    primary_thesis, challenger_thesis, primary_report_map = read_step1_upstream(report_id)
    return {
        'source_type': source_type,
        'pdf_path': pdf_path,
        'primary_thesis': primary_thesis,
        'challenger_thesis': challenger_thesis,
        'primary_report_map': primary_report_map,
    }


def list_unresolved_ambiguities(aim: Dict[str, Any]) -> List[str]:
    out = []
    for item in aim.get('unresolved_ambiguities', []):
        if isinstance(item, dict):
            amb = item.get('ambiguity')
            if amb:
                out.append(amb)
        elif isinstance(item, str):
            out.append(item)
    return out


def normalize_direction(v: Any) -> str:
    if str(v).strip() in {'-1', 'Negative', 'negative'}:
        return 'Negative'
    return str(v) if v is not None else ''


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def text_blob(*objects: Any) -> str:
    return ' '.join(json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj for obj in objects).lower()


def infer_target_statistic(primary: Dict[str, Any], aim: Dict[str, Any]) -> str:
    step1_hint = ((aim.get('research_discipline') or {}).get('target_statistic_hint') or
                  (aim.get('math_discipline_review') or {}).get('target_statistic'))
    if step1_hint:
        return str(step1_hint)
    text = text_blob(primary.get('raw_formula_text'), primary.get('operators'), primary.get('time_series_steps'), primary.get('cross_sectional_steps'))
    if any(tok in text for tok in ['corr', '相关', 'cov']):
        return 'rolling dependence statistic used to forecast cross-sectional return ordering'
    if any(tok in text for tok in ['rank', 'zscore', 'bucket', 'quantile', '排序']):
        return 'cross-sectional ordering / standardized score statistic for future returns'
    if any(tok in text for tok in ['std', 'vol', '波动', '方差']):
        return 'conditional dispersion statistic linked to future returns'
    if any(tok in text for tok in ['argmax', 'argmin', 'ts_rank']):
        return 'time-series extremum/rank statistic linked to future returns'
    return 'conditional expected return or cross-sectional ranking effect inferred from the canonical spec'


def infer_step1_mathematical_object_fallback(primary: Dict[str, Any], aim: Dict[str, Any]) -> str:
    text = text_blob(primary, aim)
    if any(tok in text for tok in ['volume', 'turnover', 'amount', '成交量', '换手', '价量']):
        return 'A-share liquidity/order-flow and price panel observed through tradable market data'
    if any(tok in text for tok in ['close', 'open', 'high', 'low', 'return', '价格', '收益', '影线']):
        return 'A-share daily/intraday price-return panel and cross-sectional return ordering'
    if any(tok in text for tok in ['revenue', 'profit', 'cash', '营收', '利润', '现金流', '合同负债']):
        return 'firm fundamental information state observed through accounting and disclosure fields'
    return 'report-defined mathematical object; researcher must restate its precise economic and measurement semantics before promotion'


def infer_economic_mechanism(primary: Dict[str, Any], aim: Dict[str, Any], thesis: Dict[str, Any]) -> str:
    final_factor = aim.get('final_factor') or {}
    parts = [
        final_factor.get('economic_logic'),
        final_factor.get('behavioral_logic'),
        final_factor.get('causal_chain'),
        thesis.get('economic_logic'),
        thesis.get('behavioral_logic'),
        thesis.get('causal_chain'),
    ]
    mechanism = ' ; '.join(str(x) for x in parts if x)
    if mechanism.strip():
        return mechanism
    text = text_blob(primary)
    if any(tok in text for tok in ['volume', 'turnover', '成交量', '换手', '价量']):
        return 'Price-volume interaction may capture repeatable liquidity demand, attention, or temporary order-flow imbalance.'
    if any(tok in text for tok in ['revenue', 'profit', 'cash', '合同负债', '现金流']):
        return 'Fundamental feature changes may encode information diffusion before consensus reprices expected earnings.'
    return 'Economic mechanism is inferred but not yet fully explicit; Step6 must challenge whether it is risk premium, information advantage, constraint-driven arbitrage, or mixed.'


def infer_expected_failure_modes(primary: Dict[str, Any], consistency: Dict[str, Any], aim: Dict[str, Any]) -> List[str]:
    failures = []
    text = text_blob(primary, aim)
    if primary.get('ambiguities'):
        failures.append('Specification ambiguity can cause independent implementers to build different factors.')
    if consistency.get('distortion_risks'):
        failures.extend(str(x) for x in consistency.get('distortion_risks') or [])
    if any(tok in text for tok in ['rank', 'bucket', 'quantile', 'argmax', 'argmin', 'zscore']):
        failures.append('Boundary-sensitive ranking/normalization choices may overfit one sample or change behavior across regimes.')
    if any(tok in text for tok in ['turnover', 'volume', '分钟', 'intraday']):
        failures.append('Turnover, liquidity, and minute-data cleaning choices may consume or distort the theoretical spread.')
    if not failures:
        failures.append('The thesis may fail if signal evidence does not translate into a tradable, robust portfolio after costs and constraints.')
    return list(dict.fromkeys(failures))


def infer_innovative_idea_seeds(primary: Dict[str, Any], aim: Dict[str, Any]) -> List[str]:
    text = text_blob(primary, aim)
    seeds = []
    if any(tok in text for tok in ['corr', '相关']):
        seeds.append('Test whether the dependence statistic is more robust as a rank/quantile signal than as a raw correlation magnitude.')
    if any(tok in text for tok in ['volume', 'turnover', '成交量', '换手']):
        seeds.append('Explore separating permanent information volume shocks from temporary liquidity-pressure volume shocks.')
    if any(tok in text for tok in ['rank', 'zscore', 'bucket', 'quantile']):
        seeds.append('Run ablations for rank-only, zscore, winsorized, and neutralized variants to identify which operator carries the thesis.')
    if not seeds:
        seeds.append('Create one neighboring hypothesis that preserves the same return-source mechanism but changes the weakest operator.')
    return seeds


def build_reuse_instructions(primary: Dict[str, Any], aim: Dict[str, Any]) -> List[str]:
    return [
        'Future agents must preserve the author thesis before optimizing implementation details.',
        'Before Step3B coding, map every operator/window/neutralization choice to either explicit report evidence or an inferred assumption.',
        'If Step4 metrics are weak, revise the operator that most directly tests the return-source hypothesis rather than blindly adding complexity.',
    ]


def build_factor_knowledge_query(primary: Dict[str, Any], aim: Dict[str, Any], thesis: Dict[str, Any]) -> str:
    discipline = aim.get('research_discipline') or {}
    final_factor = aim.get('final_factor') or {}
    parts = [
        str(final_factor.get('name') or ''),
        str(final_factor.get('economic_logic') or ''),
        str(final_factor.get('behavioral_logic') or ''),
        str(final_factor.get('causal_chain') or ''),
        ' '.join(str(item) for item in final_factor.get('assembly_steps') or []),
        str(primary.get('raw_formula_text') or ''),
        ' '.join(str(item) for item in thesis.get('signals') or []),
        ' '.join(str(item) for item in thesis.get('key_variables') or []),
        json.dumps(discipline.get('economic_hypothesis') or {}, ensure_ascii=False),
        json.dumps(discipline.get('math_hypothesis_candidates') or [], ensure_ascii=False),
        str(discipline.get('initial_return_source_hypothesis') or ''),
        str(
            discipline.get('step1_mathematical_object')
            or discipline.get('step1_random_object')
            or ''
        ),
    ]
    return ' '.join(part for part in parts if part and part != '{}')


def retrieve_step2_factor_knowledge_context(primary: Dict[str, Any], aim: Dict[str, Any], thesis: Dict[str, Any]) -> Dict[str, Any]:
    query_text = build_factor_knowledge_query(primary, aim, thesis)
    try:
        return retrieve_factor_knowledge_context(text=query_text, top_k=5)
    except Exception as exc:
        return {
            'schema_version': 'factor_knowledge_context_v1',
            'node_count': 0,
            'nodes': [],
            'related_edges': [],
            'retrieval_error': str(exc),
            'query': {'text': query_text, 'top_k': 5},
        }


def summarize_factor_knowledge_context(context: Dict[str, Any]) -> List[str]:
    lessons: List[str] = []
    for node in context.get('nodes') or []:
        node_id = node.get('id') or 'unknown_graph_node'
        status = ','.join(str(item) for item in node.get('research_status') or [])
        summary = str(node.get('summary') or '').strip()
        lesson = f'Graph prior {node_id}'
        if status:
            lesson += f' [{status}]'
        if summary:
            lesson += f': {summary[:260]}'
        lessons.append(lesson)
    return lessons


def build_step2_research_contract(
    primary: Dict[str, Any],
    consistency: Dict[str, Any],
    aim: Dict[str, Any],
    thesis: Dict[str, Any],
) -> Dict[str, Any]:
    local_authored = _local_agent_authored_research_contract_inputs(aim)
    if local_authored is not None:
        # Local agent specs are an explicitly authored, bounded route.  Do not
        # concatenate historical thesis prose, synthesize failure/innovation
        # variants, or query the knowledge graph again here.
        discipline = local_authored['discipline']
        return {
            'target_statistic': discipline['target_statistic_hint'],
            'economic_mechanism': local_authored['economic_mechanism'],
            'formula_understanding': discipline.get('formula_understanding') or aim.get('formula_understanding') or {},
            'economic_hypothesis': deepcopy(discipline.get('economic_hypothesis') or {}),
            'economic_to_math_modelling': deepcopy(
                discipline.get('economic_to_math_modelling') or aim.get('economic_to_math_modelling') or {}
            ),
            'math_hypothesis_candidates': deepcopy(discipline.get('math_hypothesis_candidates') or []),
            'expected_failure_modes': deepcopy(local_authored['expected_failure_modes']),
            'innovative_idea_seeds': deepcopy(local_authored['innovative_idea_seeds']),
            'reuse_instruction_for_future_agents': deepcopy(
                local_authored['reuse_instruction_for_future_agents']
            ),
            'step1_mathematical_object': discipline['step1_mathematical_object'],
            'similar_case_lessons_imported': deepcopy(
                local_authored['similar_case_lessons_imported']
            ),
            'research_compatibility_profile': local_authored.get(
                'research_compatibility_profile'
            ),
            'innovative_idea_seeds_absence_reason': local_authored.get(
                'innovative_idea_seeds_absence_reason'
            ),
            'similar_case_lessons_absence_reason': local_authored.get(
                'similar_case_lessons_absence_reason'
            ),
            'factor_knowledge_context': deepcopy(local_authored['factor_knowledge_context']),
            'knowledge_reference_contract': deepcopy(
                local_authored['knowledge_reference_contract']
            ),
            'producer': 'step2_local_agent_authored_research_contract',
        }
    discipline = aim.get('research_discipline') or {}
    economic_hypothesis = discipline.get('economic_hypothesis') or {}
    math_hypothesis_candidates = discipline.get('math_hypothesis_candidates') or []
    formula_understanding = discipline.get('formula_understanding') or aim.get('formula_understanding') or {}
    economic_to_math_modelling = discipline.get('economic_to_math_modelling') or aim.get('economic_to_math_modelling') or {}
    prior_lessons = (
        discipline.get('similar_case_lessons_imported')
        or (aim.get('learning_and_innovation') or {}).get('similar_case_lessons_imported')
        or ['No similar prior case was imported from Step1; treat this as a cold-start prior and write back lessons after Step6.']
    )
    factor_knowledge_context = (
        discipline.get('factor_knowledge_context')
        or (aim.get('learning_and_innovation') or {}).get('factor_knowledge_context')
        or retrieve_step2_factor_knowledge_context(primary, aim, thesis)
    )
    graph_lessons = summarize_factor_knowledge_context(factor_knowledge_context)
    similar_case_lessons = list(dict.fromkeys([
        *[str(item) for item in prior_lessons if str(item).strip()],
        *graph_lessons,
    ]))
    existing_knowledge_reference_contract = (
        discipline.get('knowledge_reference_contract')
        or (aim.get('learning_and_innovation') or {}).get('knowledge_reference_contract')
    )
    if existing_knowledge_reference_contract and not validate_knowledge_reference_contract(
        existing_knowledge_reference_contract,
        retrieval_required=False,
    ):
        knowledge_reference_contract = existing_knowledge_reference_contract
    else:
        query_text = build_factor_knowledge_query(primary, aim, thesis)
        node_ids = [
            str(item.get('id'))
            for item in factor_knowledge_context.get('nodes') or []
            if isinstance(item, dict) and item.get('id')
        ]
        knowledge_reference_contract = build_knowledge_reference_contract(
            repo_root=REPO_ROOT,
            knowledge_root=REPO_ROOT / 'knowledge',
            retrieval_index=resolve_runtime_retrieval_index(REPO_ROOT),
            query_text=query_text,
            producer='step2_factor_knowledge_graph_retrieval',
            top_k=5,
            retrieval_required=False,
        )
        similar_case_lessons = list(dict.fromkeys([
            *similar_case_lessons,
            *knowledge_reference_contract.get('similar_case_lessons_imported', []),
        ]))
        knowledge_reference_contract.update({
            'source': 'factor_knowledge_reference',
            'context_schema_version': factor_knowledge_context.get('schema_version'),
            # A carried Step1 graph context is not the current query result.
            'cited_node_ids': node_ids,
            'similar_case_lessons_imported': similar_case_lessons,
            'retrieval_error': factor_knowledge_context.get('retrieval_error'),
            'not_same_factor_unless_identity_matches': True,
        })
    if not knowledge_reference_contract:
        knowledge_reference_contract = build_legacy_knowledge_reference_contract(
            similar_case_lessons=similar_case_lessons,
            producer='step2_legacy_step1_artifact_adapter',
        )
    return {
        'target_statistic': infer_target_statistic(primary, aim),
        'economic_mechanism': infer_economic_mechanism(primary, aim, thesis),
        'formula_understanding': formula_understanding,
        'economic_hypothesis': economic_hypothesis,
        'economic_to_math_modelling': economic_to_math_modelling,
        'math_hypothesis_candidates': math_hypothesis_candidates,
        'expected_failure_modes': infer_expected_failure_modes(primary, consistency, aim),
        'innovative_idea_seeds': infer_innovative_idea_seeds(primary, aim),
        'reuse_instruction_for_future_agents': build_reuse_instructions(primary, aim),
        'step1_mathematical_object': (
            (aim.get('research_discipline') or {}).get('step1_mathematical_object')
            or aim.get('step1_mathematical_object')
            or (aim.get('research_discipline') or {}).get('step1_random_object')
            or aim.get('step1_random_object')
            or infer_step1_mathematical_object_fallback(primary, aim)
        ),
        'similar_case_lessons_imported': similar_case_lessons,
        'factor_knowledge_context': factor_knowledge_context,
        'knowledge_reference_contract': knowledge_reference_contract,
        'producer': 'step2_research_contract',
    }


def _local_agent_authored_research_contract_inputs(
    aim: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Return the complete authored local contract or BLOCK without fallbacks."""
    if LOCAL_AGENT_SPEC_INPUTS_KEY not in aim:
        return None
    discipline = aim.get('research_discipline')
    if not isinstance(discipline, dict):
        _block_local_agent_spec_inputs('AIM.research_discipline must be an object for local authored research contract')
    profile = discipline.get('research_compatibility_profile') or aim.get(
        'research_compatibility_profile'
    )
    flexible_local = (
        os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1'
        and profile == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
    )

    def require_text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            _block_local_agent_spec_inputs(f'{label} must be a nonempty authored string; no inference fallback exists')
        return value

    def require_text_list(
        value: Any,
        label: str,
        *,
        allow_empty: bool = False,
        absence_reason: Any = None,
    ) -> List[str]:
        if (
            not isinstance(value, list)
            or (not value and not allow_empty)
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            _block_local_agent_spec_inputs(f'{label} must be a nonempty authored string list; no template fallback exists')
        if allow_empty and not value and (
            not isinstance(absence_reason, str) or not absence_reason.strip()
        ):
            _block_local_agent_spec_inputs(
                f'{label} may be empty only with an explicit absence reason'
            )
        return list(value)

    market_process = discipline.get('market_process_thesis')
    if not isinstance(market_process, dict):
        _block_local_agent_spec_inputs('research_discipline.market_process_thesis must be an object')
    economic_mechanism = market_process.get('economic_hypothesis')
    if not isinstance(economic_mechanism, str) or not economic_mechanism.strip():
        economic_mechanism = discipline.get('economic_mechanism')
    economic_mechanism = require_text(
        economic_mechanism,
        'research_discipline.market_process_thesis.economic_hypothesis or research_discipline.economic_mechanism',
    )
    factor_knowledge_context = discipline.get('factor_knowledge_context')
    if not isinstance(factor_knowledge_context, dict) or not factor_knowledge_context:
        _block_local_agent_spec_inputs('research_discipline.factor_knowledge_context must be explicitly carried; no Step2 KB retrieval exists')
    knowledge_reference_contract = discipline.get('knowledge_reference_contract')
    if not isinstance(knowledge_reference_contract, dict) or not knowledge_reference_contract:
        _block_local_agent_spec_inputs('research_discipline.knowledge_reference_contract must be explicitly carried; no Step2 KB reconstruction exists')
    return {
        'discipline': discipline,
        'economic_mechanism': economic_mechanism,
        'expected_failure_modes': require_text_list(
            discipline.get('expected_failure_modes'),
            'research_discipline.expected_failure_modes',
        ),
        'innovative_idea_seeds': require_text_list(
            discipline.get('innovative_idea_seeds'),
            'research_discipline.innovative_idea_seeds',
            allow_empty=flexible_local,
            absence_reason=discipline.get('innovative_idea_seeds_absence_reason'),
        ),
        'reuse_instruction_for_future_agents': require_text_list(
            discipline.get('reuse_instruction_for_future_agents'),
            'research_discipline.reuse_instruction_for_future_agents',
        ),
        'similar_case_lessons_imported': require_text_list(
            discipline.get('similar_case_lessons_imported'),
            'research_discipline.similar_case_lessons_imported',
            allow_empty=flexible_local,
            absence_reason=discipline.get('similar_case_lessons_absence_reason'),
        ),
        'research_compatibility_profile': profile,
        'innovative_idea_seeds_absence_reason': discipline.get(
            'innovative_idea_seeds_absence_reason'
        ),
        'similar_case_lessons_absence_reason': discipline.get(
            'similar_case_lessons_absence_reason'
        ),
        'factor_knowledge_context': factor_knowledge_context,
        'knowledge_reference_contract': knowledge_reference_contract,
    }


def _master_evaluation_contract(primary: Dict[str, Any], aim: Dict[str, Any]) -> Dict[str, Any]:
    """Use an explicit AIM contract for the local route; never manufacture one."""
    if LOCAL_AGENT_SPEC_INPUTS_KEY not in aim:
        return primary.get('evaluation_contract') or {}
    contract = aim.get('evaluation_contract')
    if not isinstance(contract, dict) or not contract:
        _block_local_agent_spec_inputs(
            'AIM.evaluation_contract must be an explicit nonempty object for local agent specs; no primary/raw fallback exists'
        )
    return deepcopy(contract)


def is_shadow_factor(final_factor: Dict[str, Any], thesis: Dict[str, Any]) -> bool:
    joined = ' '.join(str(x) for x in (thesis.get('signals', []) or []))
    return any(token in joined for token in ['candlestick_shadow_signal', 'williams_shadow_signal', 'shadow_composite_signal'])


def build_primary_spec(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    final_factor = aim.get('final_factor', {})
    shadow_factor = is_shadow_factor(final_factor, thesis)
    return {
        'factor_id': final_factor.get('name', report_id),
        'report_id': report_id,
        'route': 'primary',
        'raw_formula_text': ' ; '.join(final_factor.get('assembly_steps', []) or aim.get('assembly_path', [])),
        'operators': [
            'mean()', 'std()', 'corr()', 'regression()', 'residual()', 'ZScore()', 'neutralization()'
        ],
        'required_inputs': thesis.get('key_variables', report_map.get('variables', [])),
        'time_series_steps': (
            [
                '每日计算标准化蜡烛上影线与下影线',
                '每日计算威廉上影线与威廉下影线',
                '回溯过去20个交易日，构造均值与标准差特征序列',
                '提取蜡烛上_std 与 威廉下_mean 作为综合因子核心部件'
            ]
            if shadow_factor else
            [
                '每日计算单只股票当日分钟收盘价与分钟成交量的相关系数',
                '回溯过去20个交易日，构造相关系数时间序列',
                '计算20日均值、20日标准差、以及相关系数时间趋势'
            ]
        ),
        'cross_sectional_steps': final_factor.get('assembly_steps', []) or aim.get('assembly_path', []),
        'preprocessing': [
            '剔除ST股', '剔除停牌股', '剔除上市不足60个交易日股票'
        ],
        'normalization': ['横截面Z-Score标准化'],
        'neutralization': [
            '市值中性化', '剔除Ret20', '对趋势项剔除市值/Ret20/Turn20/Vol20'
        ],
        'rebalance_frequency': '月度调仓',
        'explicit_items': thesis.get('signals', []),
        'inferred_items': [
            '若报告未显式给出实现细节，则按 alpha_idea_master 与 thesis 做最小保守补全'
        ],
        'ambiguities': list_unresolved_ambiguities(aim),
        'direction': normalize_direction(final_factor.get('direction'))
    }


def build_challenger_spec(report_id: str, aim: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    final_factor = aim.get('final_factor', {})
    shadow_factor = is_shadow_factor(final_factor, challenger)
    amb = list_unresolved_ambiguities(aim)
    extra = [
        '相关系数类型是否为 Pearson 仍需人工确认',
        '分钟频率与异常值处理路径可能改变复现结果'
    ]
    return {
        'factor_id': final_factor.get('name', report_id),
        'report_id': report_id,
        'route': 'challenger',
        'raw_formula_text': '挑战视角重建：' + ' ; '.join(aim.get('assembly_path', [])),
        'operators': [
            'corr()', 'mean()', 'std()', 'time-trend regression()', 'cross-sectional regression()', 'residual()', 'ZScore()'
        ],
        'required_inputs': challenger.get('key_variables', report_map.get('variables', [])),
        'time_series_steps': (
            [
                '按20日窗口重建标准化蜡烛上/下影线序列与威廉上/下影线序列',
                '独立抽取均值与波动两类影线信号',
                '检查综合因子是否明确由蜡烛上_std 与 威廉下_mean 组成'
            ]
            if shadow_factor else
            [
                '按20日窗口重建每日分钟价量相关系数序列',
                '独立抽取均值、波动、趋势三类信号',
                '检查 assembly_path 是否遗漏趋势项与反转剔除项'
            ]
        ),
        'cross_sectional_steps': (
            [
                '分别标准化蜡烛与威廉影线子因子',
                '对综合因子做市值与常用风格中性化检查',
                '验证不同参数M下综合影线因子稳健性',
                '最终组合为综合影线因子'
            ]
            if shadow_factor else
            [
                '分别中性化均值与波动项',
                '对反转因子做残差剥离',
                '对趋势项做多变量残差剥离',
                '最终组合为价量相关结构因子'
            ]
        ),
        'preprocessing': [
            '剔除ST股', '剔除停牌股', '剔除上市不足60个交易日股票'
        ],
        'normalization': ['横截面Z-Score标准化'],
        'neutralization': [
            '市值中性化', 'Ret20剥离', '趋势项剔除市值/Ret20/Turn20/Vol20'
        ],
        'rebalance_frequency': '月度调仓（每月月底）',
        'explicit_items': challenger.get('signals', []),
        'inferred_items': [
            'challenger route 强调 primary 可能弱化的趋势项和控制变量',
            '若报告语义不足，则保留不确定性而不伪造确定细节'
        ],
        'ambiguities': list(dict.fromkeys(amb + ([] if shadow_factor else extra))),
        'direction': normalize_direction(final_factor.get('direction'))
    }


def infer_formula_inputs(formula: str, fallback: List[Any]) -> List[str]:
    aliases = {'vol': 'volume', 'returns': 'return', 'ret': 'return'}
    tokens = re.findall(r'\b(?:open|high|low|close|vwap|volume|vol|amount|turnover|returns?|ret|adv\d*)\b', formula.lower())
    out: List[str] = []
    for token in tokens:
        out.append('volume' if token.startswith('adv') else aliases.get(token, token))
    out.extend(str(x) for x in fallback if x)
    return list(dict.fromkeys(out)) or ['close', 'volume']


def infer_formula_operators(formula: str, fallback: List[Any]) -> List[str]:
    known = [
        'rank', 'correlation', 'corr', 'sum', 'mean', 'std', 'delta', 'delay',
        'ts_rank', 'argmax', 'argmin', 'decay_linear', 'signedpower', 'scale',
        'indneutralize', 'regression', 'zscore',
    ]
    text = formula.lower()
    operators = [f'{name}()' for name in known if name in text]
    operators.extend(str(x) for x in fallback if x)
    return list(dict.fromkeys(operators)) or ['formula_expression()']


def build_primary_spec_from_pdf(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    return build_primary_spec(report_id, aim, thesis, report_map)


def build_primary_spec_from_canonical_formula(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    formula = str(aim.get('raw_formula') or thesis.get('raw_formula_text') or report_map.get('raw_formula') or '').strip()
    required_inputs = infer_formula_inputs(formula, as_list(thesis.get('key_variables') or report_map.get('variables')))
    operators = infer_formula_operators(formula, as_list(thesis.get('operators') or report_map.get('operators')))
    formula_ir = None
    formula_parse_error = None
    qlib_expression = None
    try:
        formula_ir = parse_formula(formula)
        if formula_ir.get('parse_status') == 'success':
            required_inputs = formula_ir.get('required_fields') or required_inputs
            operators = [f'{op}()' for op in (formula_ir.get('operator_set') or [])] or operators
        else:
            formula_parse_error = '; '.join(str(item) for item in (formula_ir.get('parse_errors') or [])) or 'formula parse failed'
        qlib_expression = to_qlib_expression(formula_ir)
    except Exception as exc:
        formula_parse_error = str(exc)
    return {
        'factor_id': aim.get('factor_id') or thesis.get('factor_id') or report_id,
        'report_id': report_id,
        'route': 'primary',
        'source_type': 'paper_canonical_formula',
        'producer': 'step2_canonical_formula_spec_builder',
        'raw_formula_text': formula,
        'formula_ir': formula_ir,
        'formula_parse_error': formula_parse_error,
        'qlib_expression': qlib_expression,
        'operators': operators,
        'required_inputs': required_inputs,
        'time_series_steps': [
            'Parse the canonical formula into its declared operator tree.',
            'Apply each rolling or lagged operator using only data available at the rebalance date.',
            'Preserve published window lengths and rank/correlation semantics unless Step3B records a reviewed deviation.',
        ],
        'cross_sectional_steps': [
            'Compute the canonical formula score for each stock.',
            'Apply cross-sectional ranking/normalization exactly where specified by the source formula.',
            'Pass the final score to Step4 as the long-side candidate signal.',
        ],
        'preprocessing': ['Apply the canonical Factor Forge universe filters and missing-data policy before formula evaluation.'],
        'normalization': ['Preserve formula-defined rank/scale operations; otherwise Step3B must document any added normalization.'],
        'neutralization': ['No neutralization is implied by the canonical formula unless Step3B/Step4 explicitly evaluates it as a variant.'],
        'rebalance_frequency': 'daily signal; portfolio rebalance cadence remains a Step4 evaluation setting',
        'implementation_assumptions': [
            'Declared formula operator semantics are treated as source-of-truth.',
            'Window alignment must avoid forward-looking data.',
        ],
        'explicit_items': [formula],
        'inferred_items': ['Data-field aliases must be resolved conservatively by Step3B.'],
        'ambiguities': as_list(aim.get('ambiguities')),
        'direction': aim.get('expected_direction') or 'formula_defined',
    }


def build_challenger_spec_from_canonical_formula(report_id: str, aim: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    spec = build_primary_spec_from_canonical_formula(report_id, aim, challenger, report_map)
    spec.update({
        'route': 'challenger',
        'producer': 'step2_canonical_formula_challenger_spec_builder',
        'time_series_steps': spec['time_series_steps'] + [
            'Independently audit every window and nested operator to catch off-by-one or rank-domain errors.'
        ],
        'inferred_items': spec['inferred_items'] + [
            'Challenger must flag source convention uncertainty instead of silently changing formula semantics.'
        ],
    })
    return spec


def build_primary_spec_from_hypothesis(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    variables = list(dict.fromkeys(as_list(aim.get('candidate_variables')) + as_list(thesis.get('key_variables')) + as_list(report_map.get('variables'))))
    formula_text = str((aim.get('final_factor') or {}).get('assembly_steps', [''])[0] or thesis.get('raw_formula_text') or f'hypothesis_score({", ".join(str(x) for x in variables)})')
    formula_ir = thesis.get('formula_ir') if isinstance(thesis.get('formula_ir'), dict) else None
    if aim.get('implementation_mode') == 'operator':
        if not formula_ir or formula_ir.get('parse_status') != 'success':
            formula_ir = parse_formula(formula_text)
        if formula_ir.get('parse_status') == 'success':
            variables = list(formula_ir.get('required_fields') or variables)
    operators = list(dict.fromkeys(as_list(thesis.get('operators')) + ['change()', 'rank()', 'zscore()', 'lag_guard()']))
    if formula_ir and formula_ir.get('parse_status') == 'success':
        operators = [f'{operator}()' for operator in (formula_ir.get('operator_set') or [])]
    evaluation_contract = (
        thesis.get('evaluation_contract')
        if isinstance(thesis.get('evaluation_contract'), dict)
        else aim.get('evaluation_contract')
        if isinstance(aim.get('evaluation_contract'), dict)
        else {}
    )
    return {
        'factor_id': (aim.get('final_factor') or {}).get('name') or aim.get('title') or report_id,
        'report_id': report_id,
        'route': 'primary',
        'source_type': 'natural_language_hypothesis',
        'producer': 'step2_hypothesis_spec_builder',
        'raw_formula_text': formula_text,
        'formula_ir': formula_ir,
        'formula_parse_error': (
            '; '.join(str(item) for item in (formula_ir.get('parse_errors') or []))
            if formula_ir and formula_ir.get('parse_status') != 'success'
            else None
        ),
        'qlib_expression': to_qlib_expression(formula_ir) if formula_ir else None,
        'operators': operators,
        'required_inputs': variables or ['close', 'return'],
        'time_series_steps': [
            'Convert the stated hypothesis into lag-safe feature changes or levels.',
            'Apply disclosure-lag controls for any fundamental fields before scoring.',
            'Mark unresolved formula choices for human review instead of inventing precision.',
        ],
        'cross_sectional_steps': [
            'Transform the hypothesis strength into a cross-sectional score.',
            'Rank or z-score the score only after lag and availability checks are explicit.',
        ],
        'preprocessing': ['Use standard universe filters and enforce data availability at rebalance time.'],
        'normalization': ['Cross-sectional rank or z-score; exact choice requires review when the hypothesis is underspecified.'],
        'neutralization': ['Style/industry neutralization is an evaluation variant unless the hypothesis explicitly requires it.'],
        'rebalance_frequency': evaluation_contract.get('rebalance_frequency') or 'monthly by default for fundamental hypotheses unless Step3B justifies another cadence',
        'availability_lags': evaluation_contract.get('availability_lags') or thesis.get('availability_lags') or [],
        'missing_data_policy': evaluation_contract.get('missing_data_policy') or thesis.get('missing_data_policy') or '',
        'forward_horizon': evaluation_contract.get('forward_horizon') or thesis.get('forward_horizon') or '',
        'transaction_cost_bps': evaluation_contract.get('transaction_cost_bps'),
        'cost_model_id': evaluation_contract.get('cost_model_id') or thesis.get('cost_model_id') or '',
        'evaluation_contract': evaluation_contract,
        'implementation_assumptions': [
            'Natural-language intake is a research contract, not executable code.',
            'Ambiguous variables and lags remain human-review items until resolved.',
        ],
        'explicit_items': [aim.get('raw_user_hypothesis') or thesis.get('signals')],
        'inferred_items': ['Formula expression is a conservative placeholder derived from the user hypothesis.'],
        'ambiguities': as_list(aim.get('ambiguities')),
        'direction': aim.get('expected_direction') or 'positive_if_hypothesis_strengthens',
    }


def build_challenger_spec_from_hypothesis(report_id: str, aim: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    spec = build_primary_spec_from_hypothesis(report_id, aim, challenger, report_map)
    spec.update({
        'route': 'challenger',
        'producer': 'step2_hypothesis_challenger_spec_builder',
        'time_series_steps': spec['time_series_steps'] + [
            'Challenge whether each proposed variable is observable before the target return window.'
        ],
        'inferred_items': spec['inferred_items'] + [
            'Challenger should ask for human confirmation when variable mapping or expected direction is not explicit.'
        ],
    })
    return spec


def _declared_selected_construction_id(aim: Dict[str, Any]) -> str | None:
    final_factor = aim.get('final_factor')
    if isinstance(final_factor, dict):
        for key in ('construction_id', 'factor_id', 'name'):
            value = final_factor.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ('selected_construction_id', 'factor_id'):
        value = aim.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _primary_construction_id(primary: Dict[str, Any]) -> str | None:
    for key in ('construction_id', 'factor_id'):
        value = primary.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _source_subject_routing(
    aim: Dict[str, Any],
    primary: Dict[str, Any],
    mechanical_passed: bool,
) -> Dict[str, Any]:
    """Route source-baseline claims without treating a consistency score as semantics.

    This validates only the explicit, agent-authored comparison declaration.  It
    deliberately does not infer semantic equivalence from source bytes, text,
    formula ASTs, or implementation hashes.
    """
    mode = aim.get('research_subject_mode')
    if mode is None:
        return {
            'profile': SOURCE_SUBJECT_ROUTING_PROFILE,
            # Reading an old artifact remains compatible because validators do
            # not require this new projection.  A fresh scorer invocation,
            # however, must not let the historical 0.82 default imply source
            # faithfulness merely because the new declaration is absent.
            'research_subject_mode': 'unassessed',
            'mechanical_consistency_only': True,
            'mechanical_consistency_passed': bool(mechanical_passed),
            'source_semantic_match': None,
            'source_semantic_status': 'unassessed',
            'paper_replication_status': 'unassessed',
            'semantic_review_is_structured_agent_judgment_not_automatic_proof': True,
            'diagnostics': ['research_subject_mode required for newly scored Step2 output'],
        }

    diagnostics: list[str] = []
    if mode not in RESEARCH_SUBJECT_MODES:
        diagnostics.append('research_subject_mode must be report_replication, source_extension, or independent_hypothesis')

    reference = aim.get('source_baseline_reference')
    review = aim.get('source_semantic_review')
    selected_id = _primary_construction_id(primary)
    declared_selected_id = _declared_selected_construction_id(aim)
    if declared_selected_id and selected_id and declared_selected_id != selected_id:
        diagnostics.append('AIM selected construction must equal the primary canonical construction')
    reference_valid = isinstance(reference, dict)
    if mode in {'report_replication', 'source_extension'}:
        if not reference_valid:
            diagnostics.append('source_baseline_reference object required for report_replication/source_extension')
        else:
            for key in ('source_construction_id', 'selected_construction_id', 'relation'):
                if not isinstance(reference.get(key), str) or not reference[key].strip():
                    diagnostics.append(f'source_baseline_reference.{key} must be nonempty')
            if not selected_id:
                diagnostics.append('primary factor must declare construction_id or factor_id')
            elif reference.get('selected_construction_id') != selected_id:
                diagnostics.append('source_baseline_reference.selected_construction_id must bind the primary canonical construction')
            expected_relation = 'selected_baseline' if mode == 'report_replication' else 'source_extension'
            if reference.get('relation') != expected_relation:
                diagnostics.append(f'source_baseline_reference.relation must be {expected_relation}')
    elif mode == 'independent_hypothesis' and reference is not None:
        diagnostics.append('independent_hypothesis must not declare source_baseline_reference')

    review_valid = isinstance(review, dict)
    review_status = review.get('status') if review_valid else None
    if mode == 'report_replication':
        if not review_valid:
            diagnostics.append('source_semantic_review object required for report_replication')
        else:
            if review_status not in SOURCE_SEMANTIC_REVIEW_STATUSES:
                diagnostics.append('source_semantic_review.status must be match, mismatch, or unassessed')
            for key in ('reviewer_basis', 'compared_source_components', 'compared_selected_components', 'material_deviations'):
                value = review.get(key)
                if key == 'reviewer_basis':
                    valid = isinstance(value, str) and bool(value.strip())
                elif key in {'compared_source_components', 'compared_selected_components'}:
                    valid = isinstance(value, list) and bool(value)
                else:
                    valid = isinstance(value, list)
                if not valid:
                    diagnostics.append(f'source_semantic_review.{key} missing or invalid')
            if review_status == 'match' and review.get('material_deviations'):
                diagnostics.append('source_semantic_review.match cannot retain material_deviations')
    elif mode == 'source_extension' and review_valid and review_status not in SOURCE_SEMANTIC_REVIEW_STATUSES:
        diagnostics.append('source_semantic_review.status must be match, mismatch, or unassessed when supplied')
    elif mode == 'independent_hypothesis' and review is not None:
        diagnostics.append('independent_hypothesis must not declare source_semantic_review')

    baseline_match = (
        mode == 'report_replication'
        and not diagnostics
        and review_status == 'match'
    )
    return {
        'profile': SOURCE_SUBJECT_ROUTING_PROFILE,
        'research_subject_mode': mode,
        'source_baseline_reference': deepcopy(reference) if reference_valid else None,
        'primary_construction_id': selected_id,
        'source_semantic_review': deepcopy(review) if review_valid else None,
        'mechanical_consistency_only': True,
        'mechanical_consistency_passed': bool(mechanical_passed),
        'source_semantic_match': baseline_match,
        'source_semantic_status': review_status if review_status in SOURCE_SEMANTIC_REVIEW_STATUSES else 'unassessed',
        'paper_replication_status': (
            'source_baseline_selected_not_yet_evaluated' if baseline_match
            else 'not_reproduced' if mode == 'source_extension'
            else 'not_applicable' if mode == 'independent_hypothesis'
            else 'unassessed'
        ),
        'semantic_review_is_structured_agent_judgment_not_automatic_proof': True,
        'diagnostics': diagnostics,
    }


def score_consistency(
    primary: Dict[str, Any],
    challenger: Dict[str, Any],
    aim: Dict[str, Any],
    verified_lineage: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    mismatches = []
    missing_steps = []
    distortion_risks = []

    if set(primary.get('required_inputs', [])) != set(challenger.get('required_inputs', [])):
        mismatches.append('required_inputs between primary and challenger are not identical')
    if primary.get('rebalance_frequency') != challenger.get('rebalance_frequency'):
        mismatches.append('rebalance_frequency mismatch')

    adapter_contract = aim.get('step2_input_adapter_contract')
    semantic_alignment_bound = False
    semantic_review_required = False
    if isinstance(adapter_contract, dict):
        semantic_failures = _semantic_alignment_failures(
            adapter_contract.get('semantic_alignment'),
            primary,
            challenger,
        )
        if semantic_failures:
            mismatches.extend(
                f'dual-route semantic replay failed: {item}'
                for item in semantic_failures
            )
        else:
            semantic_alignment_bound = True
            nonidentical_semantics = any(
                isinstance(row, dict)
                and row.get('relation') == DUAL_ROUTE_NONIDENTICAL_RELATION
                for row in (
                    adapter_contract.get('semantic_alignment', {}).get(
                        'dimensions',
                        [],
                    )
                )
            )
            semantic_review_satisfied = bool(
                verified_lineage
                and verified_lineage.get('semantic_review_satisfied') is True
                and verified_lineage.get('adapter_contract_version')
                == MANIFEST_BOUND_DUAL_ROUTE_ADAPTER_VERSION_V3
            )
            semantic_review_required = (
                nonidentical_semantics and not semantic_review_satisfied
            )
            if semantic_review_required:
                distortion_risks.append(
                    'non-identical dual-route semantics are hash-bound candidate '
                    'assertions and require independent semantic review'
                )
    elif (
        primary.get('raw_formula_text') != challenger.get('raw_formula_text')
        or primary.get('operators') != challenger.get('operators')
    ):
        distortion_risks.append(
            'legacy dual-route formula/operator semantics differ without a '
            'manifest-bound semantic alignment profile'
        )

    if not primary.get('required_inputs'):
        missing_steps.append('primary required_inputs missing')
    if not challenger.get('required_inputs'):
        missing_steps.append('challenger required_inputs missing')

    unresolved = list_unresolved_ambiguities(aim)
    if unresolved:
        distortion_risks.append('unresolved ambiguities may alter exact reconstruction details')

    score = 0.82
    if mismatches:
        score -= 0.08 * len(mismatches)
    if missing_steps:
        score -= 0.1 * len(missing_steps)
    if semantic_review_required:
        score = min(score, 0.69)
    score = max(0.0, min(1.0, score))

    mechanical_passed = score >= 0.7 and not semantic_review_required
    source_subject_routing = _source_subject_routing(aim, primary, mechanical_passed)
    source_mode = source_subject_routing['research_subject_mode']
    source_semantic_match = source_subject_routing['source_semantic_match']
    source_routing_invalid = bool(source_subject_routing.get('diagnostics'))
    recommendation = (
        'independent_semantic_review_required'
        if semantic_review_required
        else 'revise'
        if source_routing_invalid
        or source_mode not in RESEARCH_SUBJECT_MODES
        or (source_mode == 'report_replication' and not source_semantic_match)
        else 'proceed' if mechanical_passed else 'revise'
    )
    return {
        'factor_id': primary.get('factor_id', 'unknown'),
        'report_id': primary.get('report_id'),
        'consistency_score': round(score, 2),
        'mechanical_consistency_only': True,
        'mechanical_consistency_passed': mechanical_passed,
        # A score is a mechanical primary/challenger check.  It must not turn
        # into a source-faithfulness claim without the explicit comparison.
        'matches_core_driver': bool(source_semantic_match),
        'mismatch_points': mismatches,
        'missing_steps': missing_steps,
        'distortion_risks': distortion_risks,
        'recommendation': recommendation,
        'semantic_alignment_bound': semantic_alignment_bound,
        'semantic_alignment_integrity_only': semantic_alignment_bound,
        'semantic_relation_authority': (
            'CANDIDATE_ASSERTION_ONLY'
            if semantic_alignment_bound
            else None
        ),
        'semantic_review_required': semantic_review_required,
        'semantic_review_satisfied': (
            semantic_alignment_bound and not semantic_review_required
            and bool(
                verified_lineage
                and verified_lineage.get('semantic_review_satisfied') is True
            )
        ),
        'semantic_alignment_profile': (
            DUAL_ROUTE_SEMANTIC_ALIGNMENT_PROFILE
            if semantic_alignment_bound
            else None
        ),
        'source_subject_routing': source_subject_routing,
    }


def build_factor_spec_master(
    report_id: str,
    aim: Dict[str, Any],
    primary: Dict[str, Any],
    consistency: Dict[str, Any],
    thesis: Dict[str, Any],
    source_adapter_lineage: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    score = consistency.get('consistency_score', 1.0)
    source_type = normalize_source_type(aim)
    producer = formal_step2_producer(source_type)
    upstream_producer = aim.get('producer') or producer
    implementation_mode = infer_implementation_mode(source_type, primary, aim)
    measurement_program = validated_step1_measurement_program(
        aim=aim,
        primary=primary,
        implementation_mode=implementation_mode,
    )
    branch_id = str(aim.get('branch_id') or 'main')
    run_id = str(aim.get('run_id') or 'run_001')
    parent_run_id = aim.get('parent_run_id')
    human_review_required = (
        score < 0.7
        or consistency.get('semantic_review_required') is True
        or consistency.get('recommendation') == 'revise'
        or bool(aim.get('human_review_required'))
    )
    chief_decision = None
    if consistency.get('recommendation') == 'revise':
        chief_decision = (
            'STEP2_REVISE_REQUIRED: source-subject routing requires an '
            'agent-authored semantic comparison or corrected selected construction'
        )
    elif human_review_required:
        chief_decision = f'CONSISTENCY_SCORE_TOO_LOW: {score} — needs chief review'
    research_contract = build_step2_research_contract(primary, consistency, aim, thesis)
    research_contract['producer'] = producer
    family_plugin_selection = explicit_family_plugin_selection(aim, primary)
    hybrid_contract = build_hybrid_contract(primary, aim) if implementation_mode == 'hybrid' else None
    direct_code_source_contract = explicit_direct_code_source_contract(primary, aim) if implementation_mode == 'direct_code' else {}
    evaluation_contract = _master_evaluation_contract(primary, aim)
    formula_text = str(primary.get('raw_formula_text') or '')
    formula_ir = primary.get('formula_ir') if isinstance(primary.get('formula_ir'), dict) else {}
    canonical_required_fields = (
        formula_ir.get('required_fields')
        if isinstance(formula_ir, dict) and formula_ir.get('required_fields')
        else primary.get('required_inputs', [])
    )
    canonical_construction_id = _primary_construction_id(primary)
    standard_formula_fields_contract = build_standard_formula_fields_contract(
        formula_text=formula_text,
        required_fields=canonical_required_fields,
        available_source_fields=[
            'amount',
            'close',
            'high',
            'low',
            'open',
            'pct_chg',
            'pre_close',
            'returns',
            'vol',
            'volume',
            'vwap',
        ],
    )

    master = {
        'contract_version': STEP2_SOURCE_CONTRACT_VERSION,
        'factor_id': primary.get('factor_id', report_id),
        'linked_idea_id': aim.get('report_id', report_id),
        'report_id': report_id,
        'source_type': source_type,
        'selected_construction_id': canonical_construction_id,
        SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER: True,
        'source_subject_routing': deepcopy(consistency.get('source_subject_routing') or {}),
        'implementation_mode': implementation_mode,
        'producer': producer,
        'upstream_producer': upstream_producer,
        'evaluation_contract': deepcopy(evaluation_contract),
        'source_metadata': {
            'factor_id': aim.get('factor_id'),
            'source_name': aim.get('source_name'),
            'source_url': aim.get('source_url'),
            'title': aim.get('title'),
            'window_start': aim.get('window_start'),
            'window_end': aim.get('window_end'),
            **({
                'source_uri': aim.get('source_uri'),
                'report_identity': deepcopy(aim.get('report_identity')),
                'source_identity': deepcopy(aim.get('source_identity')),
                'source_outcome_boundary': deepcopy(
                    aim.get('source_outcome_boundary')
                ),
                'source_adapter_alpha_raw_sha256': (
                    source_adapter_lineage.get(
                        'alpha_idea_master_raw_sha256'
                    )
                ),
                'source_adapter_pdf_sha256': next(
                    (
                        row.get('sha256')
                        for row in source_adapter_lineage.get(
                            'source_step1_inputs',
                            [],
                        )
                        if isinstance(row, dict)
                        and row.get('role') == 'source_pdf'
                    ),
                    None,
                ),
            } if source_adapter_lineage else {}),
        },
        'canonical_spec': {
            'construction_id': canonical_construction_id,
            'formula_text': formula_text,
            'formula_ir': primary.get('formula_ir'),
            'formula_parse_error': primary.get('formula_parse_error'),
            'parse_status': ((primary.get('formula_ir') or {}).get('parse_status') if isinstance(primary.get('formula_ir'), dict) else None),
            'qlib_expression': primary.get('qlib_expression'),
            'operator_set': ((primary.get('formula_ir') or {}).get('operator_set') if isinstance(primary.get('formula_ir'), dict) else None) or primary.get('operators', []),
            'required_fields': canonical_required_fields,
            'resolved_fields': ((primary.get('formula_ir') or {}).get('resolved_fields') if isinstance(primary.get('formula_ir'), dict) else None) or {},
            'required_inputs': primary.get('required_inputs', []),
            'operators': primary.get('operators', []),
            'standard_formula_fields_contract': standard_formula_fields_contract,
            'time_series_steps': primary.get('time_series_steps', []),
            'cross_sectional_steps': primary.get('cross_sectional_steps', []),
            'preprocessing': primary.get('preprocessing', []),
            'normalization': primary.get('normalization', []),
            'neutralization': primary.get('neutralization', []),
            'rebalance_frequency': primary.get('rebalance_frequency', ''),
            'availability_lags': primary.get('availability_lags', []),
            'missing_data_policy': primary.get('missing_data_policy', ''),
            'forward_horizon': primary.get('forward_horizon', ''),
            'transaction_cost_bps': primary.get('transaction_cost_bps'),
            'cost_model_id': primary.get('cost_model_id', ''),
            'evaluation_contract': deepcopy(evaluation_contract),
            'implementation_assumptions': primary.get('implementation_assumptions', []),
            'operator_subgraph': (hybrid_contract or {}).get('operator_subgraph'),
            'custom_blocks': (hybrid_contract or {}).get('custom_blocks') or primary.get('custom_blocks') or [],
            'boundary': (hybrid_contract or {}).get('boundary'),
        },
        'implementation_contract': {
            'implementation_mode': implementation_mode,
            'mode': implementation_mode,
            'branch_id': branch_id,
            'run_id': run_id,
            'parent_run_id': parent_run_id,
            'code_contract': (direct_code_source_contract or {
                'code_contract_version': 'factorforge_direct_code_contract_v1',
                'function_name': 'compute_factor',
                'entrypoint': 'compute_factor',
                'input_schema': {},
                'output_schema': {
                    'columns': ['ts_code', 'trade_date', 'factor_value'],
                },
                'required_fields': primary.get('required_inputs', []),
                'information_set_rules': ['no future-looking fields or negative shifts'],
                'forbidden_patterns': [
                    r'shift\s*\(\s*-\d+',
                    'future_return',
                    'next_return',
                    'label',
                    'target',
                    'future_',
                    'lookahead',
                ],
            }) if implementation_mode == 'direct_code' else None,
            'output_schema': {
                'columns': ['ts_code', 'trade_date', 'factor_value'],
            } if implementation_mode == 'direct_code' else None,
            'mode_contract': (
                'pure_formula_operator_graph'
                if implementation_mode == 'operator' else
                'agent_reviewed_direct_code_contract'
                if implementation_mode == 'direct_code' else
                'operator_subgraph_plus_custom_code_blocks'
            ),
            **(hybrid_contract or {}),
        },
        **{k: v for k, v in family_plugin_selection.items() if k in {'factor_family', 'family_plugin', 'family_plugin_allowed', 'family_plugin_decision', 'family_plugin_suggestion'}},
        'implementation_mode_decision': build_mode_decision(implementation_mode, primary, aim),
        'thesis': {
            'alpha_thesis': thesis.get('thesis_name') or (aim.get('final_factor') or {}).get('name'),
            'target_prediction': research_contract['target_statistic'],
            'economic_mechanism': research_contract['economic_mechanism'],
        },
        'math_discipline_review': {
            'mathematical_object': research_contract.get('step1_mathematical_object'),
            'target_statistic': research_contract['target_statistic'],
            'information_set_legality': (aim.get('math_discipline_review') or {}).get('information_set_legality') or (aim.get('research_discipline') or {}).get('information_set_hint') or 'requires_researcher_confirmation_no_forward_leakage',
            'expected_failure_modes': research_contract['expected_failure_modes'],
        },
        'learning_and_innovation': {
            'similar_case_lessons_imported': research_contract['similar_case_lessons_imported'],
            'knowledge_reference_contract': research_contract.get('knowledge_reference_contract') or {},
            'factor_knowledge_context': research_contract.get('factor_knowledge_context') or {},
            'innovative_idea_seeds': research_contract['innovative_idea_seeds'],
            'reuse_instruction_for_future_agents': research_contract['reuse_instruction_for_future_agents'],
        },
        'knowledge_reference_contract': research_contract.get('knowledge_reference_contract') or {},
        'research_contract': research_contract,
        'standard_formula_fields_contract': standard_formula_fields_contract,
        'ambiguities': list(dict.fromkeys(primary.get('ambiguities', []) + primary.get('inferred_items', []))),
        'human_review_required': human_review_required,
        'chief_decision': chief_decision,
        'opus_invoked': False
    }
    if family_plugin_selection.get('family_plugin_allowed'):
        for key in ['factor_family', 'family_plugin', 'family_plugin_allowed', 'family_plugin_decision']:
            master['implementation_contract'][key] = family_plugin_selection[key]
    elif family_plugin_selection.get('family_plugin_suggestion'):
        master['implementation_contract']['family_plugin_suggestion'] = family_plugin_selection['family_plugin_suggestion']
    # Legacy v1 is carried only when an upstream legacy artifact already has it.
    # Current research is governed by mechanism_conditioned_measurement_program.
    mechanism_math_contract = (
        primary.get('mechanism_math_contract')
        or aim.get('mechanism_math_contract')
    )
    if isinstance(mechanism_math_contract, dict):
        mechanism_math_contract.setdefault('source_economic_hypothesis', research_contract.get('economic_hypothesis') or {})
        mechanism_math_contract.setdefault('source_math_hypothesis_candidates', research_contract.get('math_hypothesis_candidates') or [])
    mechanism_math_contract_v2 = (
        primary.get('mechanism_math_contract_v2')
        or aim.get('mechanism_math_contract_v2')
    )
    if isinstance(mechanism_math_contract, dict) and mechanism_math_contract:
        master['mechanism_math_contract'] = mechanism_math_contract
        master['canonical_spec']['mechanism_math_contract'] = deepcopy(
            mechanism_math_contract
        )
    if isinstance(mechanism_math_contract_v2, dict) and mechanism_math_contract_v2:
        master['mechanism_math_contract_v2'] = mechanism_math_contract_v2
        master['canonical_spec']['mechanism_math_contract_v2'] = deepcopy(
            mechanism_math_contract_v2
        )
    if source_adapter_lineage:
        lineage_copy = deepcopy(source_adapter_lineage)
        master['source_adapter_lineage'] = lineage_copy
        master['research_contract']['source_adapter_lineage'] = deepcopy(
            lineage_copy
        )
    master['mechanism_conditioned_measurement_program'] = measurement_program
    master['canonical_spec'][
        'mechanism_conditioned_measurement_program'
    ] = deepcopy(measurement_program)
    selected_models = [
        item
        for item in (measurement_program.get('model_selection') or {}).get(
            'candidate_models', []
        )
        if isinstance(item, dict) and item.get('selected') is True
    ]
    selected_model = selected_models[0] if len(selected_models) == 1 else {}
    master['math_discipline_review']['measurement_program_ref'] = {
        'contract_version': measurement_program.get('contract_version'),
        'model_family': selected_model.get('model_family'),
        'mathematical_object': selected_model.get('mathematical_object'),
        'estimand': (
            measurement_program.get('observation_and_estimation') or {}
        ).get('estimand'),
        'implementation_route': (
            measurement_program.get('implementation') or {}
        ).get('route'),
    }
    if isinstance(mechanism_math_contract, dict) and mechanism_math_contract:
        master['math_discipline_review']['legacy_mechanism_math_contract_ref'] = {
            'math_model_status': mechanism_math_contract.get('math_model_status'),
            'model_family': mechanism_math_contract.get('model_family'),
            'state_or_object': mechanism_math_contract.get('state_or_object'),
            'target_functional': mechanism_math_contract.get('target_functional'),
            'monotonicity_claim': mechanism_math_contract.get('monotonicity_claim'),
        }
    spec_hash = build_spec_hash(master)
    formula_ir = (master.get('canonical_spec') or {}).get('formula_ir')
    formula_hash = (
        formula_ir.get('formula_hash')
        if implementation_mode in {'operator', 'hybrid'} and isinstance(formula_ir, dict) and formula_ir.get('formula_hash')
        else build_formula_hash(master)
    )
    code_contract_hash = build_code_contract_hash(master)
    if implementation_mode == 'hybrid' and hybrid_contract:
        formula_hash = hybrid_contract.get('formula_hash') or formula_hash
        custom_block_hash = hybrid_contract.get('custom_block_hash')
        hybrid_hash = hybrid_contract.get('hybrid_hash')
    else:
        custom_block_hash = build_custom_block_hash(master)
        hybrid_hash = stable_hash({'formula_hash': formula_hash, 'custom_block_hash': custom_block_hash})
    identity = build_artifact_identity(
        report_id=report_id,
        factor_id=str(master.get('factor_id') or report_id),
        source_type=source_type,
        implementation_mode=implementation_mode,
        contract_version=STEP2_SOURCE_CONTRACT_VERSION,
        producer=producer,
        upstream_producer=upstream_producer,
        spec_hash=spec_hash,
        branch_id=branch_id,
        run_id=run_id,
        parent_run_id=parent_run_id,
        artifact_role='factor_spec_master',
        formula_hash=formula_hash if implementation_mode in {'operator', 'hybrid'} else None,
        code_contract_hash=code_contract_hash if implementation_mode == 'direct_code' else None,
        custom_block_hash=custom_block_hash if implementation_mode == 'hybrid' else None,
        hybrid_hash=hybrid_hash if implementation_mode == 'hybrid' else None,
    )
    if family_plugin_selection.get('family_plugin_allowed'):
        identity['factor_family'] = family_plugin_selection.get('factor_family')
        identity['family_plugin'] = family_plugin_selection.get('family_plugin')
        identity['not_generic_fallback'] = True
    master['spec_hash'] = spec_hash
    master['artifact_identity'] = identity
    return master


def write_handoff_to_step3(report_id: str, factor_spec_master_path: Path) -> None:
    master = load_json(factor_spec_master_path)
    handoff = {
        'contract_version': STEP2_SOURCE_CONTRACT_VERSION,
        'report_id': report_id,
        'source_type': master.get('source_type'),
        SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER: master.get(
            SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER
        ) is True,
        'source_subject_routing': master.get('source_subject_routing') or {},
        'implementation_mode': master.get('implementation_mode'),
        'factor_family': master.get('factor_family'),
        'family_plugin': master.get('family_plugin'),
        'family_plugin_allowed': master.get('family_plugin_allowed'),
        'family_plugin_decision': master.get('family_plugin_decision'),
        'family_plugin_suggestion': master.get('family_plugin_suggestion'),
        'artifact_identity': {
            **(master.get('artifact_identity') or {}),
            'artifact_role': 'handoff_to_step3',
        },
        'spec_hash': master.get('spec_hash'),
        'producer': master.get('producer'),
        'upstream_producer': master.get('upstream_producer'),
        'step2_status': 'factor_spec_master_ready',
        'factor_spec_master_ref': factor_spec_master_path.name,
        'research_contract': master.get('research_contract') or {},
        'math_discipline_review': master.get('math_discipline_review') or {},
        'mechanism_conditioned_measurement_program': master.get(
            'mechanism_conditioned_measurement_program'
        ) or {},
        'learning_and_innovation': master.get('learning_and_innovation') or {},
        'knowledge_reference_contract': master.get('knowledge_reference_contract') or {},
        'evaluation_contract': master.get('evaluation_contract') or {},
    }
    if isinstance(master.get('source_adapter_lineage'), dict) and master.get(
        'source_adapter_lineage'
    ):
        handoff['source_adapter_lineage'] = deepcopy(
            master['source_adapter_lineage']
        )
    if isinstance(master.get('mechanism_math_contract'), dict) and master.get(
        'mechanism_math_contract'
    ):
        handoff['mechanism_math_contract'] = master['mechanism_math_contract']
    if isinstance(master.get('mechanism_math_contract_v2'), dict) and master.get(
        'mechanism_math_contract_v2'
    ):
        handoff['mechanism_math_contract_v2'] = master['mechanism_math_contract_v2']
    write_json(HANDOFF_DIR / f'handoff_to_step3__{report_id}.json', handoff)


def run_step2(report_id: str, dry_run: bool = False) -> None:
    print(f'Step 2 independent run for report_id={report_id}')
    print(f'dry_run={dry_run}')
    aim = load_alpha_idea_master(report_id)
    if (
        LOCAL_AGENT_SPEC_INPUTS_KEY in aim
        and os.getenv('FACTORFORGE_LOCAL_IS_ONLY') != '1'
    ):
        _block_local_agent_spec_inputs(
            f'{LOCAL_AGENT_SPEC_INPUTS_KEY} is available only with FACTORFORGE_LOCAL_IS_ONLY=1'
        )
    bound_specs = load_manifest_bound_dual_route_pdf_specs(report_id, aim)
    local_specs = (
        load_local_agent_dual_route_specs(report_id, aim)
        if bound_specs is None
        else None
    )
    source_adapter_lineage = None
    if bound_specs is not None:
        primary, challenger, source_adapter_lineage = bound_specs
        final_factor = aim.get('final_factor') if isinstance(aim.get('final_factor'), dict) else {}
        primary_thesis = {
            'thesis_name': final_factor.get('name') or aim.get('factor_id'),
            'signals': primary.get('explicit_items') or [],
            'key_variables': primary.get('required_inputs') or [],
            'economic_logic': final_factor.get('economic_logic'),
            'behavioral_logic': final_factor.get('behavioral_logic'),
            'causal_chain': final_factor.get('causal_chain'),
        }
        print('[LOAD] manifest-bound dual-route PDF candidate specs ready')
    elif local_specs is not None:
        primary, challenger = local_specs
        final_factor = aim.get('final_factor') if isinstance(aim.get('final_factor'), dict) else {}
        primary_thesis = {
            'thesis_name': final_factor.get('name') or aim.get('factor_id'),
            'signals': primary.get('explicit_items') or [],
            'key_variables': primary.get('required_inputs') or [],
            'economic_logic': final_factor.get('economic_logic'),
            'behavioral_logic': final_factor.get('behavioral_logic'),
            'causal_chain': final_factor.get('causal_chain'),
        }
        print('[LOAD] explicit local-IS agent primary/challenger specs ready')
    else:
        if (
            os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1'
            and normalize_source_type(aim) == 'pdf_report'
        ):
            _block_local_agent_spec_inputs(
                'local PDF Step2 requires AIM.local_agent_spec_inputs; '
                'generic PDF templates are disabled'
            )
        source_context = load_source_context(report_id, aim)
        source_type = source_context['source_type']
        primary_thesis = source_context['primary_thesis']
        challenger_thesis = source_context['challenger_thesis']
        primary_report_map = source_context['primary_report_map']
        print('[LOAD] Step 1 upstream artifacts ready')

        if source_type == 'paper_canonical_formula':
            primary = build_primary_spec_from_canonical_formula(report_id, aim, primary_thesis, primary_report_map)
            challenger = build_challenger_spec_from_canonical_formula(report_id, aim, challenger_thesis, primary_report_map)
        elif source_type == 'natural_language_hypothesis':
            primary = build_primary_spec_from_hypothesis(report_id, aim, primary_thesis, primary_report_map)
            challenger = build_challenger_spec_from_hypothesis(report_id, aim, challenger_thesis, primary_report_map)
        else:
            primary = build_primary_spec_from_pdf(report_id, aim, primary_thesis, primary_report_map)
            challenger = build_challenger_spec(report_id, aim, challenger_thesis, primary_report_map)
    consistency = score_consistency(
        primary,
        challenger,
        aim,
        verified_lineage=source_adapter_lineage,
    )
    if local_specs is not None:
        diagnostics = (
            consistency.get('source_subject_routing', {}).get('diagnostics')
            if isinstance(consistency.get('source_subject_routing'), dict)
            else ['source-subject routing missing']
        )
        if diagnostics:
            _block_local_agent_spec_inputs(
                'AIM source-subject routing invalid: ' + ';'.join(diagnostics)
            )
    if (
        source_adapter_lineage
        and consistency.get('semantic_review_required') is True
        and not dry_run
    ):
        _block_manifest_bound_adapter(
            'independent semantic review is required before formal Step2 writes'
        )
    if source_adapter_lineage:
        consistency['source_adapter_lineage'] = deepcopy(source_adapter_lineage)
    master = build_factor_spec_master(
        report_id,
        aim,
        primary,
        consistency,
        primary_thesis,
        source_adapter_lineage=source_adapter_lineage,
    )

    if dry_run:
        print('[DRY] primary/challenger/consistency/master prepared')
        return

    primary_path = VALIDATION / f'factor_spec_raw__primary__{report_id}.json'
    challenger_path = VALIDATION / f'factor_spec_raw__challenger__{report_id}.json'
    consistency_path = VALIDATION / f'factor_consistency__{report_id}.json'
    master_path = SPEC_MASTER_DIR / f'factor_spec_master__{report_id}.json'

    if source_adapter_lineage:
        # These two files are manifest-bound inputs.  Re-serializing them here
        # would mutate their raw-byte identity and invalidate the alpha contract.
        print(f'[PRESERVE] manifest-bound input {primary_path}')
        print(f'[PRESERVE] manifest-bound input {challenger_path}')
    else:
        write_json(primary_path, primary)
        write_json(challenger_path, challenger)
    write_json(consistency_path, consistency)
    write_json(master_path, master)
    write_handoff_to_step3(report_id, master_path)
    print('[DONE] Independent Step 2 run complete')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if not args.dry_run:
        enforce_direct_step_policy()
    run_step2(args.report_id, args.dry_run)
