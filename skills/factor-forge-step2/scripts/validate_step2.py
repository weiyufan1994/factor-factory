#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEGACY_WORKSPACE = Path('/opt/factorforge/workspace')
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJECTS = FACTORFORGE / 'objects'
STEP2_SOURCE_CONTRACT_VERSION = 'factorforge_step2_source_contract_v2'
HYBRID_CONTRACT_VERSION = 'factorforge_hybrid_contract_v1'
ALLOWED_SOURCE_TYPES = {'pdf_report', 'paper_canonical_formula', 'natural_language_hypothesis'}
ALLOWED_STEP2_PRODUCERS = {
    'step2_pdf_report',
    'step12_canonical_formula_intake',
    'step12_hypothesis_intake',
}
EXPECTED_PRODUCER_BY_SOURCE_TYPE = {
    'pdf_report': 'step2_pdf_report',
    'paper_canonical_formula': 'step12_canonical_formula_intake',
    'natural_language_hypothesis': 'step12_hypothesis_intake',
}
FORBIDDEN_PRODUCER_TOKENS = {
    'manual',
    'debug',
    'fake',
    'posthoc',
    'unknown',
    'adhoc',
    'ad_hoc',
}
ALLOWED_IMPLEMENTATION_MODES = {'operator', 'direct_code', 'hybrid'}
SOURCE_SUBJECT_ROUTING_PROFILE = 'factorforge_step2_source_subject_routing_v1'
RESEARCH_SUBJECT_MODES = {'report_replication', 'source_extension', 'independent_hypothesis'}
SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER = 'source_subject_routing_required'

from factor_factory.artifact_identity import build_spec_hash
from factor_factory.economic_taxonomy import FORMAL_RETURN_SOURCE_FAMILIES
from factor_factory.factor_families.base import FAMILY_PLUGIN_DECISION_VERSION
from factor_factory.factor_families.registry import FamilyPluginContractError, get_family_plugin_contract
from factor_factory.knowledge_reference import build_legacy_knowledge_reference_contract, validate_knowledge_reference_contract
from factor_factory.mechanism_math.validator import validate_mechanism_math_contract, validate_mechanism_math_contract_v2
from factor_factory.measurement_program import (
    BLOCK_MEASUREMENT_PROGRAM_INVALID,
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    validate_measurement_program,
)


def check(name: str, condition: bool, error: str | None = None, severity: str = 'BLOCK'):
    status = 'PASS' if condition else severity
    return {'name': name, 'ok': bool(condition), 'status': status, 'severity': severity, 'error': None if condition else error}


def nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def nonempty_list(value) -> bool:
    return isinstance(value, list) and bool(value)


def valid_knowledge_reference_contract(value, lessons=None) -> bool:
    candidate = value
    if not candidate and nonempty_list(lessons):
        candidate = build_legacy_knowledge_reference_contract(
            similar_case_lessons=lessons,
            producer='step2_legacy_artifact_validator',
        )
    return not validate_knowledge_reference_contract(candidate or {}, retrieval_required=False)


def available_knowledge_node_ids_for_measurement_program(
    learning: dict,
    research_contract: dict,
) -> set[str]:
    """Return only IDs explicitly carried by Step1/Step2 provenance.

    A native knowledge-reference contract may lawfully omit the optional
    ``cited_node_ids`` field while the frozen research contract carries the
    actual context nodes.  Both are explicit provenance sources; this helper
    does not query, infer, or manufacture any node ID.
    """
    node_ids = {
        str(item)
        for contract in (
            learning.get('knowledge_reference_contract'),
            research_contract.get('knowledge_reference_contract'),
        )
        if isinstance(contract, dict)
        for item in contract.get('cited_node_ids') or []
        if str(item).strip()
    }
    for context in (
        learning.get('factor_knowledge_context'),
        research_contract.get('factor_knowledge_context'),
    ):
        if not isinstance(context, dict):
            continue
        for node in context.get('nodes') or []:
            if isinstance(node, dict) and str(node.get('id') or '').strip():
                node_ids.add(str(node['id']))
    return node_ids


def source_subject_routing_checks(
    master,
    handoff,
    *,
    allow_legacy_source_subject_routing_omission: bool = False,
):
    """Validate current routing; legacy omission requires an explicit switch.

    The contract version remains v2 for established identity consumers.  New
    v2 writers therefore mark routing as required.  Absence of both the marker
    and routing is *not* evidence of legacy provenance: callers must explicitly
    select the narrow legacy path when validating a pre-marker artifact.
    """
    routing = master.get('source_subject_routing')
    handoff_routing = (
        handoff.get('source_subject_routing')
        if isinstance(handoff, dict)
        else None
    )
    master_marker = master.get(SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER)
    handoff_marker = (
        handoff.get(SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER)
        if isinstance(handoff, dict) and handoff
        else None
    )
    legacy_omission_explicit = (
        allow_legacy_source_subject_routing_omission
        and master.get('contract_version') == STEP2_SOURCE_CONTRACT_VERSION
        and SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER not in master
        and (
            not handoff
            or SOURCE_SUBJECT_ROUTING_REQUIRED_MARKER not in handoff
        )
    )
    if not isinstance(routing, dict) or not routing:
        if legacy_omission_explicit:
            return [check(
                'source_subject_routing_legacy_omission_explicit',
                True,
            )]
        return [
            check(
                'source_subject_routing_required',
                False,
                'source_subject_routing is required for current Step2 outputs; '
                'use the explicit legacy omission switch only for pre-marker artifacts',
            ),
            check(
                'handoff_source_subject_routing_required',
                False,
                'handoff source_subject_routing is required for current Step2 outputs',
            ),
        ]
    mode = routing.get('research_subject_mode')
    canonical = master.get('canonical_spec') if isinstance(master.get('canonical_spec'), dict) else {}
    canonical_construction_id = canonical.get('construction_id') or master.get('selected_construction_id')
    reference = routing.get('source_baseline_reference') if isinstance(routing.get('source_baseline_reference'), dict) else {}
    review = routing.get('source_semantic_review') if isinstance(routing.get('source_semantic_review'), dict) else {}
    checks = [
        check(
            'source_subject_routing_required_marker',
            legacy_omission_explicit or master_marker is True,
            'source_subject_routing_required=true missing from current factor_spec_master',
        ),
        check(
            'handoff_source_subject_routing_required_marker',
            handoff_marker is True,
            'source_subject_routing_required=true missing from current handoff_to_step3',
        ),
        check(
            'handoff_source_subject_routing_required',
            isinstance(handoff_routing, dict) and bool(handoff_routing),
            'handoff source_subject_routing is required for current Step2 outputs',
        ),
        check(
            'source_subject_routing_profile',
            routing.get('profile') == SOURCE_SUBJECT_ROUTING_PROFILE,
            'source_subject_routing profile mismatch',
        ),
        check(
            'source_subject_routing_mechanical_only',
            routing.get('mechanical_consistency_only') is True,
            'consistency_score must be marked mechanical_consistency_only',
        ),
        check(
            'source_subject_routing_no_automatic_semantic_proof',
            routing.get('semantic_review_is_structured_agent_judgment_not_automatic_proof') is True,
            'routing must not treat text, AST, or hash equality as semantic proof',
        ),
    ]
    checks.extend([
        check(
            'source_subject_routing_mode_allowed',
            mode in RESEARCH_SUBJECT_MODES,
            f'unsupported research_subject_mode: {mode}',
        ),
        check(
            'source_subject_routing_diagnostics_clear',
            not routing.get('diagnostics'),
            f'source-subject routing diagnostics: {routing.get("diagnostics")}',
        ),
        check(
            'source_subject_routing_handoff_match',
            handoff_routing == routing,
            'handoff source_subject_routing mismatch',
        ),
        check(
            'source_subject_routing_primary_canonical_identity_match',
            routing.get('primary_construction_id') == canonical_construction_id,
            'source_subject_routing primary construction must equal canonical construction',
        ),
    ])
    if mode == 'report_replication':
        checks.extend([
            check(
                'report_replication_reference_canonical_identity_match',
                reference.get('selected_construction_id') == canonical_construction_id,
                'report_replication reference must bind canonical construction',
            ),
            check(
                'report_replication_reference_relation',
                reference.get('relation') == 'selected_baseline',
                'report_replication reference relation must be selected_baseline',
            ),
            check(
                'report_replication_review_declared_match',
                review.get('status') == 'match'
                and nonempty_str(review.get('reviewer_basis'))
                and nonempty_list(review.get('compared_source_components'))
                and nonempty_list(review.get('compared_selected_components'))
                and isinstance(review.get('material_deviations'), list)
                and not review.get('material_deviations'),
                'report_replication requires a declared match with compared components and no material deviations',
            ),
            check(
                'report_replication_semantic_match_required',
                routing.get('source_semantic_match') is True,
                'report_replication requires an explicit source-vs-selected construction match',
            ),
            check(
                'report_replication_status',
                routing.get('paper_replication_status') == 'source_baseline_selected_not_yet_evaluated',
                'report_replication must not be labeled unassessed or not_reproduced',
            ),
        ])
    elif mode == 'source_extension':
        checks.extend([
            check(
                'source_extension_reference_canonical_identity_match',
                reference.get('selected_construction_id') == canonical_construction_id,
                'source_extension reference must bind canonical construction',
            ),
            check(
                'source_extension_reference_relation',
                reference.get('relation') == 'source_extension',
                'source_extension reference relation must be source_extension',
            ),
            check(
                'source_extension_not_paper_replication',
                routing.get('paper_replication_status') == 'not_reproduced'
                and routing.get('source_semantic_match') is False,
                'source_extension cannot claim paper replication',
            ),
        ])
    elif mode == 'independent_hypothesis':
        checks.extend([
            check(
                'independent_hypothesis_not_paper_replication',
                routing.get('paper_replication_status') == 'not_applicable'
                and routing.get('source_semantic_match') is False,
                'independent_hypothesis cannot claim paper replication',
            ),
        ])
    return checks


def direct_code_contract_checks(master):
    if master.get('implementation_mode') != 'direct_code':
        return []
    contract = master.get('implementation_contract') or {}
    code_contract = contract.get('code_contract') if isinstance(contract.get('code_contract'), dict) else {}
    source_code = code_contract.get('source_code')
    source_derivation = code_contract.get('source_derivation')
    output_schema = code_contract.get('output_schema')
    required_fields = code_contract.get('required_fields') or contract.get('required_fields') or (master.get('canonical_spec') or {}).get('required_inputs')
    code_hash = code_contract.get('code_hash')
    expected_hash = None
    if nonempty_str(source_code):
        normalized_source = source_code if str(source_code).endswith('\n') else f'{source_code}\n'
        import hashlib
        expected_hash = hashlib.sha256(normalized_source.encode('utf-8')).hexdigest()
    return [
        check('direct_code_contract_present', isinstance(code_contract, dict) and bool(code_contract), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: implementation_contract.code_contract missing'),
        check('direct_code_source_code_present', nonempty_str(source_code), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: implementation_contract.code_contract.source_code missing'),
        check('direct_code_entrypoint_present', nonempty_str(code_contract.get('entrypoint') or code_contract.get('function_name')), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code entrypoint/function_name missing'),
        check('direct_code_hash_present', nonempty_str(code_hash), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code code_hash missing'),
        check('direct_code_hash_matches_source', not expected_hash or code_hash == expected_hash, 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code code_hash mismatch'),
        check('direct_code_required_fields_present', nonempty_list(required_fields), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code required_fields missing'),
        check('direct_code_output_schema_present', isinstance(output_schema, dict) and nonempty_list(output_schema.get('columns')), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code output_schema.columns missing'),
        check('direct_code_source_derivation_present', isinstance(source_derivation, dict) and bool(source_derivation), 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code source_derivation missing'),
        check('direct_code_source_derivation_not_fallback', isinstance(source_derivation, dict) and source_derivation.get('not_fallback') is True, 'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: direct_code source_derivation.not_fallback=true required'),
    ]


def valid_economic_hypothesis(value) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    if value.get('macro_return_source') not in FORMAL_RETURN_SOURCE_FAMILIES:
        return False
    second = value.get('second_layer')
    return (
        isinstance(second, dict)
        and nonempty_str(second.get('subtype'))
        and nonempty_str(second.get('expected_counterparty_or_payer'))
        and nonempty_str(second.get('why_they_may_pay'))
        and nonempty_str(value.get('counterparty_loss_hypothesis'))
    )


def valid_math_hypothesis_candidates(value) -> bool:
    if not isinstance(value, list) or not value:
        return False
    required = {
        'hypothesis_id',
        'linked_economic_hypothesis',
        'model_family',
        'math_tools',
        'observable_estimator',
        'target_functional',
        'why_suitable',
        'falsification_tests',
    }
    for item in value:
        if not isinstance(item, dict):
            return False
        if any(key not in item for key in required):
            return False
        if not nonempty_str(item.get('mathematical_object') or item.get('state_or_object')):
            return False
        if not nonempty_str(
            item.get('mechanism_equation_or_functional')
            or item.get('process_or_distribution_hypothesis')
        ):
            return False
        if not nonempty_list(item.get('math_tools')) or not nonempty_list(item.get('falsification_tests')):
            return False
        for key in required - {'math_tools', 'falsification_tests'}:
            if not nonempty_str(item.get(key)):
                return False
    return True


def mechanism_contract_carries_source_hypotheses(contract, expected_economic, expected_math) -> bool:
    if not isinstance(contract, dict) or not contract:
        return False
    source_economic = contract.get('source_economic_hypothesis')
    source_math = contract.get('source_math_hypothesis_candidates')
    return (
        valid_economic_hypothesis(source_economic)
        and valid_math_hypothesis_candidates(source_math)
        and source_economic == expected_economic
        and source_math == expected_math
    )


def mechanism_contract_v2_consistent(master_v2, canonical_v2, handoff_v2) -> bool:
    if not isinstance(master_v2, dict) or not isinstance(canonical_v2, dict):
        return False
    if master_v2 != canonical_v2:
        return False
    if handoff_v2 is not None and handoff_v2 != master_v2:
        return False
    return True


def producer_has_forbidden_token(value) -> bool:
    text = str(value or '').lower()
    return any(token in text for token in FORBIDDEN_PRODUCER_TOKENS)


def producer_allowed(value) -> bool:
    return nonempty_str(value) and value in ALLOWED_STEP2_PRODUCERS and not producer_has_forbidden_token(value)


def manifest_bound_adapter_lineage_checks(master, handoff, rid):
    master_lineage = master.get('source_adapter_lineage')
    research_lineage = (master.get('research_contract') or {}).get(
        'source_adapter_lineage'
    )
    handoff_lineage = handoff.get('source_adapter_lineage') if handoff else None
    present = [
        isinstance(value, dict) and bool(value)
        for value in (master_lineage, research_lineage, handoff_lineage)
    ]
    alpha_path = (
        OBJECTS
        / 'alpha_idea_master'
        / f'alpha_idea_master__{rid}.json'
    )
    consistency_path = (
        OBJECTS / 'validation' / f'factor_consistency__{rid}.json'
    )
    source_metadata = (
        master.get('source_metadata')
        if isinstance(master.get('source_metadata'), dict)
        else {}
    )
    adapter_projection_present = any(
        nonempty_str(source_metadata.get(key))
        for key in (
            'source_adapter_alpha_raw_sha256',
            'source_adapter_pdf_sha256',
        )
    )
    if not any(present):
        if (
            not alpha_path.is_file()
            or alpha_path.is_symlink()
            or alpha_path.stat().st_nlink != 1
        ):
            if adapter_projection_present:
                return [check(
                    'manifest_bound_lineage_stripped_with_alpha_unavailable',
                    False,
                    'manifest-bound adapter projection exists but all lineage '
                    'copies were stripped and alpha bytes are unavailable or aliased',
                )]
            return []
        try:
            alpha_probe_text = alpha_path.read_text(encoding='utf-8')
            alpha_probe = json.loads(alpha_probe_text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return [check(
                'manifest_bound_alpha_master_json',
                False,
                f'cannot determine adapter-contract absence because alpha JSON is invalid: {exc}',
            )]
        adapter_token_present = '"step2_input_adapter_contract"' in alpha_probe_text
        if (
            not adapter_token_present
            and 'step2_input_adapter_contract' not in alpha_probe
        ):
            return []

    checks = [
        check(
            'manifest_bound_lineage_all_output_copies_present',
            all(present),
            'manifest-bound adapter lineage must be present in master, research_contract, and handoff',
        ),
        check(
            'manifest_bound_lineage_output_copies_equal',
            bool(master_lineage)
            and master_lineage == research_lineage == handoff_lineage,
            'manifest-bound adapter lineage copies mismatch',
        ),
    ]
    checks.extend([
        check(
            'manifest_bound_alpha_master_exists',
            alpha_path.is_file()
            and not alpha_path.is_symlink()
            and alpha_path.stat().st_nlink == 1,
            f'manifest-bound alpha_idea_master missing, linked, or aliased: {alpha_path}',
        ),
        check(
            'manifest_bound_consistency_exists',
            consistency_path.is_file()
            and not consistency_path.is_symlink()
            and consistency_path.stat().st_nlink == 1,
            f'manifest-bound consistency artifact missing, linked, or aliased: {consistency_path}',
        ),
    ])
    if (
        not alpha_path.is_file()
        or alpha_path.is_symlink()
        or alpha_path.stat().st_nlink != 1
    ):
        return checks

    try:
        aim = json.loads(alpha_path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        checks.append(check(
            'manifest_bound_alpha_master_json',
            False,
            f'manifest-bound alpha_idea_master is not valid UTF-8 JSON: {exc}',
        ))
        return checks

    runner_path = Path(__file__).with_name('run_step2.py')
    spec = importlib.util.spec_from_file_location(
        'factorforge_step2_manifest_bound_validator_replay',
        runner_path,
    )
    if not spec or not spec.loader:
        checks.append(check(
            'manifest_bound_adapter_replay_loader',
            False,
            f'cannot load manifest-bound adapter replay from {runner_path}',
        ))
        return checks
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.FACTORFORGE = FACTORFORGE
    try:
        replay = runner.load_manifest_bound_dual_route_pdf_specs(rid, aim)
    except SystemExit as exc:
        checks.append(check(
            'manifest_bound_adapter_replay',
            False,
            str(exc),
        ))
        return checks
    if replay is None:
        checks.append(check(
            'manifest_bound_adapter_contract_present',
            False,
            'source_adapter_lineage exists but alpha adapter contract is absent',
        ))
        return checks
    expected_lineage = replay[2]
    checks.extend([
        check(
            'manifest_bound_adapter_replay',
            True,
        ),
        check(
            'manifest_bound_lineage_equals_replay',
            master_lineage == expected_lineage,
            'source_adapter_lineage does not equal replayed alpha contract and raw input identities',
        ),
        check(
            'manifest_bound_lineage_identity_match',
            expected_lineage.get('report_id') == rid
            and expected_lineage.get('factor_id') == master.get('factor_id'),
            'manifest-bound lineage report_id/factor_id mismatch',
        ),
        check(
            'manifest_bound_lineage_candidate_only',
            expected_lineage.get('input_authority') == 'CANDIDATE_ONLY'
            and expected_lineage.get('authority_effect') == 'NONE'
            and expected_lineage.get('admission_effect') == 'NONE',
            'candidate raw inputs cannot acquire formal authority or admission effect',
        ),
        check(
            'manifest_bound_generic_fallback_forbidden',
            expected_lineage.get('generic_pdf_fallback_used') is False,
            'manifest-bound adapter cannot use generic PDF fallback',
        ),
        check(
            'manifest_bound_source_metadata_alpha_identity',
            source_metadata.get('source_adapter_alpha_raw_sha256')
            == expected_lineage.get('alpha_idea_master_raw_sha256'),
            'source_metadata alpha identity does not equal replayed adapter lineage',
        ),
        check(
            'manifest_bound_source_metadata_pdf_identity',
            source_metadata.get('source_adapter_pdf_sha256')
            == next(
                (
                    row.get('sha256')
                    for row in expected_lineage.get('source_step1_inputs', [])
                    if isinstance(row, dict) and row.get('role') == 'source_pdf'
                ),
                None,
            ),
            'source_metadata PDF identity does not equal replayed adapter lineage',
        ),
    ])
    if (
        consistency_path.is_file()
        and not consistency_path.is_symlink()
        and consistency_path.stat().st_nlink == 1
    ):
        try:
            consistency = json.loads(consistency_path.read_text(encoding='utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            checks.append(check(
                'manifest_bound_consistency_json',
                False,
                f'manifest-bound consistency is not valid UTF-8 JSON: {exc}',
            ))
        else:
            review_required = expected_lineage.get(
                'semantic_review_required'
            ) is True
            review_satisfied = expected_lineage.get(
                'semantic_review_satisfied'
            ) is True
            checks.extend([
                check(
                    'manifest_bound_consistency_lineage_match',
                    consistency.get('source_adapter_lineage') == expected_lineage,
                    'factor_consistency source_adapter_lineage mismatch',
                ),
                check(
                    'manifest_bound_semantic_review_gate_satisfied',
                    not review_required or review_satisfied,
                    'non-identical manifest-bound semantics require a verified '
                    'V3 independent semantic-review receipt',
                ),
                check(
                    'manifest_bound_consistency_semantic_gate_match',
                    consistency.get('semantic_review_required')
                    == (review_required and not review_satisfied)
                    and consistency.get('semantic_review_satisfied')
                    == (review_required and review_satisfied),
                    'factor_consistency semantic-review state does not equal '
                    'replayed lineage',
                ),
                check(
                    'manifest_bound_consistency_recommendation',
                    consistency.get('recommendation') == 'proceed'
                    if (not review_required or review_satisfied)
                    else consistency.get('recommendation')
                    == 'independent_semantic_review_required',
                    'factor_consistency recommendation contradicts semantic gate',
                ),
                check(
                    'manifest_bound_master_review_gate',
                    master.get('human_review_required') is False
                    and master.get('chief_decision') is None,
                    'formal master cannot PASS with human/semantic review pending',
                ),
            ])
    return checks


def identity_check(master, handoff, rid):
    identity = master.get('artifact_identity') or {}
    handoff_identity = handoff.get('artifact_identity') or {}
    expected_hash = build_spec_hash(master)
    required = ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'spec_hash', 'branch_id', 'artifact_role']
    checks = [
        check('artifact_identity_present', isinstance(identity, dict) and bool(identity), 'artifact_identity missing'),
        check('artifact_identity_required_fields', all(nonempty_str(identity.get(k)) for k in required), f'artifact_identity required fields missing: {identity}'),
        check('artifact_identity_report_id_match', identity.get('report_id') == rid, 'artifact_identity.report_id mismatch'),
        check('artifact_identity_factor_id_match', identity.get('factor_id') == master.get('factor_id'), 'artifact_identity.factor_id mismatch'),
        check('artifact_identity_source_type_match', identity.get('source_type') == master.get('source_type'), 'artifact_identity.source_type mismatch'),
        check('artifact_identity_mode_allowed', identity.get('implementation_mode') in ALLOWED_IMPLEMENTATION_MODES, f'unsupported implementation_mode: {identity.get("implementation_mode")}'),
        check('artifact_identity_mode_match', identity.get('implementation_mode') == master.get('implementation_mode'), 'artifact_identity.implementation_mode mismatch'),
        check('artifact_identity_contract_version_match', identity.get('contract_version') == STEP2_SOURCE_CONTRACT_VERSION, 'artifact_identity.contract_version mismatch'),
        check('artifact_identity_producer_match', identity.get('producer') == master.get('producer'), 'artifact_identity.producer mismatch'),
        check('artifact_identity_spec_hash_match', identity.get('spec_hash') == master.get('spec_hash') == expected_hash, 'spec_hash mismatch'),
        check('artifact_identity_role', identity.get('artifact_role') == 'factor_spec_master', 'artifact_identity.artifact_role must be factor_spec_master'),
        check('handoff_artifact_identity_present', isinstance(handoff_identity, dict) and bool(handoff_identity), 'handoff artifact_identity missing'),
        check('handoff_artifact_identity_role', not handoff_identity or handoff_identity.get('artifact_role') == 'handoff_to_step3', 'handoff artifact_identity.artifact_role must be handoff_to_step3'),
    ]
    for key in ['report_id', 'factor_id', 'source_type', 'implementation_mode', 'contract_version', 'producer', 'upstream_producer', 'spec_hash', 'branch_id']:
        checks.append(check(f'handoff_identity_{key}_match', not handoff_identity or handoff_identity.get(key) == identity.get(key), f'handoff artifact_identity.{key} mismatch'))
    mode = identity.get('implementation_mode')
    checks.extend([
        check('operator_formula_hash_required', mode != 'operator' or nonempty_str(identity.get('formula_hash')), 'operator mode requires formula_hash'),
        check('direct_code_hash_required', mode != 'direct_code' or nonempty_str(identity.get('code_hash') or identity.get('code_contract_hash')), 'direct_code mode requires code_hash or code_contract_hash'),
        check('hybrid_hashes_required', mode != 'hybrid' or (nonempty_str(identity.get('formula_hash')) and nonempty_str(identity.get('custom_block_hash')) and nonempty_str(identity.get('hybrid_hash'))), 'hybrid mode requires formula_hash, custom_block_hash, and hybrid_hash'),
    ])
    return checks


def hybrid_contract_checks(master):
    if master.get('implementation_mode') != 'hybrid':
        return []
    contract = master.get('implementation_contract') or {}
    operator_subgraph = contract.get('operator_subgraph') or {}
    formula_ir = operator_subgraph.get('formula_ir') if isinstance(operator_subgraph.get('formula_ir'), dict) else {}
    custom_blocks = contract.get('custom_blocks') or []
    boundary = contract.get('boundary') or {}
    identity = master.get('artifact_identity') or {}
    return [
        check('hybrid_contract_version', contract.get('hybrid_contract_version') == HYBRID_CONTRACT_VERSION, f'hybrid_contract_version must be {HYBRID_CONTRACT_VERSION}'),
        check('hybrid_operator_subgraph_present', isinstance(operator_subgraph, dict) and bool(operator_subgraph), 'BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph missing'),
        check('hybrid_operator_formula_ir_present', bool(formula_ir), 'BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph.formula_ir missing'),
        check('hybrid_operator_formula_ir_success', not formula_ir or formula_ir.get('parse_status') == 'success', f'BLOCK_INVALID_HYBRID_CONTRACT: operator_subgraph formula_ir parse failed {formula_ir.get("parse_errors")}'),
        check('hybrid_custom_blocks_nonempty', isinstance(custom_blocks, list) and bool(custom_blocks), 'BLOCK_INVALID_HYBRID_CONTRACT: custom_blocks missing'),
        check('hybrid_boundary_present', isinstance(boundary, dict) and bool(boundary), 'BLOCK_INVALID_HYBRID_CONTRACT: boundary missing'),
        check('hybrid_formula_hash_present', nonempty_str(contract.get('formula_hash')), 'BLOCK_INVALID_HYBRID_CONTRACT: formula_hash missing'),
        check('hybrid_custom_block_hash_present', nonempty_str(contract.get('custom_block_hash')), 'BLOCK_INVALID_HYBRID_CONTRACT: custom_block_hash missing'),
        check('hybrid_hash_present', nonempty_str(contract.get('hybrid_hash')), 'BLOCK_INVALID_HYBRID_CONTRACT: hybrid_hash missing'),
        check('hybrid_identity_formula_hash_match', identity.get('formula_hash') == contract.get('formula_hash'), 'BLOCK_INVALID_HYBRID_CONTRACT: identity formula_hash mismatch'),
        check('hybrid_identity_custom_block_hash_match', identity.get('custom_block_hash') == contract.get('custom_block_hash'), 'BLOCK_INVALID_HYBRID_CONTRACT: identity custom_block_hash mismatch'),
        check('hybrid_identity_hybrid_hash_match', identity.get('hybrid_hash') == contract.get('hybrid_hash'), 'BLOCK_INVALID_HYBRID_CONTRACT: identity hybrid_hash mismatch'),
    ]


def family_plugin_checks(master, handoff):
    checks = []
    contract = master.get('implementation_contract') or {}
    allowed = bool(master.get('family_plugin_allowed') or contract.get('family_plugin_allowed'))
    plugin_id = master.get('family_plugin') or contract.get('family_plugin')
    family_id = master.get('factor_family') or contract.get('factor_family')
    decision = master.get('family_plugin_decision') or contract.get('family_plugin_decision') or {}
    if not allowed and not plugin_id and not family_id:
        suggestion = master.get('family_plugin_suggestion') or contract.get('family_plugin_suggestion')
        if suggestion:
            checks.append(check('family_plugin_suggestion_not_formal', suggestion.get('formal_selection') is False, 'family_plugin_suggestion must not be formal selection'))
        return checks

    checks.extend([
        check('family_plugin_allowed_explicit', allowed is True, 'family_plugin_allowed must be true for formal family plugin'),
        check('family_plugin_present', nonempty_str(plugin_id), 'family_plugin missing'),
        check('factor_family_present', nonempty_str(family_id), 'factor_family missing'),
        check('family_plugin_decision_present', isinstance(decision, dict) and bool(decision), 'family_plugin_decision missing'),
        check('family_plugin_decision_version', decision.get('decision_version') == FAMILY_PLUGIN_DECISION_VERSION, f'family_plugin_decision.decision_version must be {FAMILY_PLUGIN_DECISION_VERSION}'),
        check('family_plugin_selected', decision.get('plugin_selected') is True, 'family_plugin_decision.plugin_selected must be true'),
        check('family_plugin_id_match', decision.get('plugin_id') == plugin_id, 'family_plugin_decision.plugin_id mismatch'),
        check('family_plugin_not_free_text', decision.get('not_selected_by_free_text') is True, 'family plugin cannot be selected by free-text trigger'),
        check('family_plugin_explicit_evidence', nonempty_list(decision.get('explicit_evidence')), 'family_plugin_decision.explicit_evidence missing'),
    ])
    try:
        plugin_contract = get_family_plugin_contract(str(plugin_id or ''))
        checks.extend([
            check('family_plugin_registry_family_match', family_id == plugin_contract.family_id, 'factor_family does not match registry'),
            check('family_plugin_registry_mode_match', master.get('implementation_mode') == plugin_contract.implementation_mode, 'implementation_mode does not match plugin contract'),
            check('family_plugin_registry_source_type_allowed', master.get('source_type') in plugin_contract.allowed_source_types, 'source_type not allowed for plugin'),
            check('family_plugin_not_generic_fallback', plugin_contract.not_generic_fallback is True, 'plugin must declare not_generic_fallback'),
        ])
        factor_id = str(master.get('factor_id') or '').upper()
        allowed_ids = {item.upper() for item in plugin_contract.allowed_factor_ids}
        allow_unlisted = bool(master.get('allow_unlisted_factor_id_with_human_review') or contract.get('allow_unlisted_factor_id_with_human_review'))
        checks.append(check('family_plugin_factor_id_allowed', factor_id in allowed_ids or allow_unlisted, 'factor_id is not allowed for plugin'))
    except FamilyPluginContractError as exc:
        checks.append(check('family_plugin_registry_known', False, str(exc)))
    if handoff:
        checks.extend([
            check('handoff_family_plugin_match', handoff.get('family_plugin') == plugin_id, 'handoff family_plugin mismatch'),
            check('handoff_factor_family_match', handoff.get('factor_family') == family_id, 'handoff factor_family mismatch'),
            check('handoff_family_plugin_allowed_match', bool(handoff.get('family_plugin_allowed')) is allowed, 'handoff family_plugin_allowed mismatch'),
        ])
    return checks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument(
        '--allow-legacy-source-subject-routing-omission',
        action='store_true',
        help=(
            'Validate a pre-marker v2 artifact that genuinely predates '
            'source-subject routing. This is an explicit compatibility path; '
            'missing routing is otherwise a BLOCK.'
        ),
    )
    args = ap.parse_args()
    rid = args.report_id
    master_path = OBJECTS / 'factor_spec_master' / f'factor_spec_master__{rid}.json'
    handoff_path = OBJECTS / 'handoff' / f'handoff_to_step3__{rid}.json'
    checks = [
        check('factor_spec_master_exists', master_path.exists(), f'missing {master_path}'),
        check('handoff_to_step3_exists', handoff_path.exists(), f'missing {handoff_path}'),
    ]
    errors = []
    warnings = []
    if master_path.exists():
        master = json.loads(master_path.read_text(encoding='utf-8'))
        handoff = json.loads(handoff_path.read_text(encoding='utf-8')) if handoff_path.exists() else {}
        canonical = master.get('canonical_spec') or {}
        thesis = master.get('thesis') or {}
        math_review = master.get('math_discipline_review') or {}
        learning = master.get('learning_and_innovation') or {}
        research_contract = master.get('research_contract') or {}
        expected_economic_hypothesis = research_contract.get('economic_hypothesis')
        expected_math_hypotheses = research_contract.get('math_hypothesis_candidates')
        info_legality = str(math_review.get('information_set_legality') or '').lower()
        source_type = master.get('source_type')
        expected_producer = EXPECTED_PRODUCER_BY_SOURCE_TYPE.get(source_type)
        handoff_research_contract = handoff.get('research_contract') or {}
        producer_fields = {
            'factor_spec_master.producer': master.get('producer'),
            'factor_spec_master.upstream_producer': master.get('upstream_producer'),
            'factor_spec_master.research_contract.producer': research_contract.get('producer'),
            'handoff_to_step3.producer': handoff.get('producer'),
            'handoff_to_step3.upstream_producer': handoff.get('upstream_producer'),
            'handoff_to_step3.research_contract.producer': handoff_research_contract.get('producer'),
        }
        implementation_mode = master.get('implementation_mode')
        formula_ir = canonical.get('formula_ir') if isinstance(canonical.get('formula_ir'), dict) else {}
        master_mechanism_math_contract = master.get('mechanism_math_contract')
        canonical_mechanism_math_contract = canonical.get('mechanism_math_contract')
        handoff_mechanism_math_contract = handoff.get('mechanism_math_contract') if isinstance(handoff, dict) else None
        master_mechanism_math_contract_v2 = master.get('mechanism_math_contract_v2')
        canonical_mechanism_math_contract_v2 = canonical.get('mechanism_math_contract_v2')
        handoff_mechanism_math_contract_v2 = handoff.get('mechanism_math_contract_v2') if isinstance(handoff, dict) else None
        mechanism_math_contract = master_mechanism_math_contract or canonical_mechanism_math_contract
        has_any_mechanism_math_v1 = any(
            isinstance(item, dict) and bool(item)
            for item in [
                master_mechanism_math_contract,
                canonical_mechanism_math_contract,
                handoff_mechanism_math_contract,
            ]
        )
        mechanism_math_failures = (
            validate_mechanism_math_contract(mechanism_math_contract)
            if has_any_mechanism_math_v1
            else []
        )
        has_any_mechanism_math_v2 = any(isinstance(item, dict) and bool(item) for item in [master_mechanism_math_contract_v2, canonical_mechanism_math_contract_v2, handoff_mechanism_math_contract_v2])
        mechanism_math_v2_failures = validate_mechanism_math_contract_v2(master_mechanism_math_contract_v2) if has_any_mechanism_math_v2 else []
        master_measurement_program = master.get('mechanism_conditioned_measurement_program')
        canonical_measurement_program = canonical.get('mechanism_conditioned_measurement_program')
        handoff_measurement_program = handoff.get('mechanism_conditioned_measurement_program') if isinstance(handoff, dict) else None
        canonical_research_contract = canonical.get('research_contract') if isinstance(canonical.get('research_contract'), dict) else {}
        handoff_research_contract = handoff.get('research_contract') if isinstance(handoff, dict) and isinstance(handoff.get('research_contract'), dict) else {}
        knowledge_node_ids = available_knowledge_node_ids_for_measurement_program(
            learning,
            research_contract,
        )
        compatibility_profile = research_contract.get('research_compatibility_profile')
        local_is_only = os.getenv('FACTORFORGE_LOCAL_IS_ONLY') == '1'
        flexible_local = local_is_only and compatibility_profile == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE
        idea_value = learning.get('innovative_idea_seeds') if 'innovative_idea_seeds' in learning else research_contract.get('innovative_idea_seeds')
        lesson_value = learning.get('similar_case_lessons_imported') if 'similar_case_lessons_imported' in learning else research_contract.get('similar_case_lessons_imported')
        measurement_program_failures = validate_measurement_program(
            master_measurement_program,
            available_knowledge_node_ids=knowledge_node_ids,
            require_web_executable=False,
            compatibility_profile=compatibility_profile,
            scope='local_is_only' if local_is_only else 'hosted_formal',
        )
        measurement_route = (
            (master_measurement_program.get('implementation') or {}).get('route')
            if isinstance(master_measurement_program, dict)
            and isinstance(master_measurement_program.get('implementation'), dict)
            else None
        )
        checks.extend([
            check('report_id_match', master.get('report_id') == rid, 'report_id mismatch'),
            check('contract_version_present', nonempty_str(master.get('contract_version')), 'contract_version missing'),
            check('contract_version_expected', master.get('contract_version') == STEP2_SOURCE_CONTRACT_VERSION, f'contract_version must be {STEP2_SOURCE_CONTRACT_VERSION}'),
            check('handoff_contract_version_present', not handoff or nonempty_str(handoff.get('contract_version')), 'handoff contract_version missing'),
            check('handoff_contract_version_expected', not handoff or handoff.get('contract_version') == STEP2_SOURCE_CONTRACT_VERSION, f'handoff contract_version must be {STEP2_SOURCE_CONTRACT_VERSION}'),
            check('source_type_present', nonempty_str(source_type), 'missing_source_type'),
            check('source_type_allowed', source_type in ALLOWED_SOURCE_TYPES, f'unsupported source_type: {source_type}'),
            check('implementation_mode_present', nonempty_str(implementation_mode), 'implementation_mode missing'),
            check('implementation_mode_allowed', implementation_mode in ALLOWED_IMPLEMENTATION_MODES, f'unsupported implementation_mode: {implementation_mode}'),
            check('implementation_contract_mode_match', (master.get('implementation_contract') or {}).get('implementation_mode') == implementation_mode, 'implementation_contract.implementation_mode mismatch'),
            check('handoff_source_type_match', not handoff or handoff.get('source_type') == source_type, 'handoff source_type mismatch'),
            check('handoff_source_type_allowed', not handoff or handoff.get('source_type') in ALLOWED_SOURCE_TYPES, f'unsupported handoff source_type: {handoff.get("source_type")}'),
            check('producers_nonempty', all(nonempty_str(v) for v in producer_fields.values()), f'producer fields must be nonempty: {producer_fields}'),
            check('producers_allowlisted', all(producer_allowed(v) for v in producer_fields.values()), f'producer fields must be allowlisted: {producer_fields}'),
            check('producers_no_forbidden_tokens', not any(producer_has_forbidden_token(v) for v in producer_fields.values()), f'producer field contains forbidden token: {producer_fields}'),
            check('source_type_producer_match', expected_producer is not None and all(v == expected_producer for v in producer_fields.values()), f'{source_type} must use producer {expected_producer}: {producer_fields}'),
            check('canonical_formula_present', nonempty_str(canonical.get('formula_text')), 'canonical formula_text missing'),
            check('canonical_required_inputs_present', nonempty_list(canonical.get('required_inputs')), 'required_inputs missing'),
            check('canonical_operators_present', nonempty_list(canonical.get('operators')), 'operators missing'),
            check('operator_formula_ir_present', implementation_mode != 'operator' or bool(formula_ir), 'operator mode requires formula_ir'),
            check('operator_formula_ir_parse_success', implementation_mode != 'operator' or formula_ir.get('parse_status') == 'success', f'operator formula_ir parse failed: {formula_ir.get("parse_errors")}'),
            check('operator_formula_hash_present', implementation_mode != 'operator' or nonempty_str(formula_ir.get('formula_hash')), 'operator formula_ir.formula_hash missing'),
            check('operator_formula_hash_identity_match', implementation_mode != 'operator' or formula_ir.get('formula_hash') == ((master.get('artifact_identity') or {}).get('formula_hash')), 'operator formula_ir.formula_hash must match artifact_identity.formula_hash'),
            check('operator_set_present', implementation_mode != 'operator' or nonempty_list(formula_ir.get('operator_set')), 'operator formula_ir.operator_set missing'),
            check('operator_required_fields_present', implementation_mode != 'operator' or nonempty_list(formula_ir.get('required_fields')), 'operator formula_ir.required_fields missing'),
            check('paper_canonical_formula_ir_required', source_type != 'paper_canonical_formula' or bool(formula_ir), 'paper_canonical_formula requires formula_ir'),
            check('thesis_alpha_thesis_present', nonempty_str(thesis.get('alpha_thesis')), 'thesis.alpha_thesis missing'),
            check('thesis_target_prediction_present', nonempty_str(thesis.get('target_prediction')), 'thesis.target_prediction missing'),
            check('thesis_economic_mechanism_present', nonempty_str(thesis.get('economic_mechanism')), 'thesis.economic_mechanism missing'),
            check('target_statistic_present', nonempty_str(math_review.get('target_statistic') or research_contract.get('target_statistic')), 'target_statistic missing'),
            check('economic_mechanism_present', nonempty_str(research_contract.get('economic_mechanism')), 'economic_mechanism missing'),
            check('economic_hypothesis_present', valid_economic_hypothesis(research_contract.get('economic_hypothesis')), 'research_contract.economic_hypothesis missing or incomplete'),
            check('math_hypothesis_candidates_present', valid_math_hypothesis_candidates(research_contract.get('math_hypothesis_candidates')), 'research_contract.math_hypothesis_candidates missing or incomplete'),
            check('expected_failure_modes_present', nonempty_list(research_contract.get('expected_failure_modes') or math_review.get('expected_failure_modes')), 'expected_failure_modes missing'),
            check('legacy_mechanism_math_contract_valid_when_present', not mechanism_math_failures, f'legacy mechanism_math_contract invalid: {mechanism_math_failures}'),
            check('legacy_mechanism_math_contract_consistent_when_present', not has_any_mechanism_math_v1 or mechanism_contract_v2_consistent(master_mechanism_math_contract, canonical_mechanism_math_contract, handoff_mechanism_math_contract if handoff else None), 'legacy mechanism_math_contract mismatch across master/canonical/handoff'),
            check('mechanism_math_contract_v2_present', not has_any_mechanism_math_v2 or (isinstance(master_mechanism_math_contract_v2, dict) and bool(master_mechanism_math_contract_v2)), 'mechanism_math_contract_v2 missing'),
            check('canonical_mechanism_math_contract_v2_present', not has_any_mechanism_math_v2 or (isinstance(canonical_mechanism_math_contract_v2, dict) and bool(canonical_mechanism_math_contract_v2)), 'canonical_spec.mechanism_math_contract_v2 missing'),
            check('handoff_mechanism_math_contract_v2_present', not has_any_mechanism_math_v2 or not handoff or (isinstance(handoff_mechanism_math_contract_v2, dict) and bool(handoff_mechanism_math_contract_v2)), 'handoff mechanism_math_contract_v2 missing'),
            check('mechanism_math_contract_v2_valid', not mechanism_math_v2_failures, f'mechanism_math_contract_v2 invalid: {mechanism_math_v2_failures}'),
            check('mechanism_math_contract_v2_consistent', not has_any_mechanism_math_v2 or mechanism_contract_v2_consistent(master_mechanism_math_contract_v2, canonical_mechanism_math_contract_v2, handoff_mechanism_math_contract_v2 if handoff else None), 'mechanism_math_contract_v2 mismatch across master/canonical/handoff'),
            check('measurement_program_present', isinstance(master_measurement_program, dict) and bool(master_measurement_program), f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: master measurement program missing'),
            check('canonical_measurement_program_present', isinstance(canonical_measurement_program, dict) and bool(canonical_measurement_program), f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: canonical measurement program missing'),
            check('handoff_measurement_program_present', not handoff or (isinstance(handoff_measurement_program, dict) and bool(handoff_measurement_program)), f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: handoff measurement program missing'),
            check('measurement_program_valid', not measurement_program_failures, f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: {measurement_program_failures}'),
            check('measurement_program_consistent', isinstance(master_measurement_program, dict) and master_measurement_program == canonical_measurement_program and (not handoff or master_measurement_program == handoff_measurement_program), f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: master/canonical/handoff mismatch'),
            check('measurement_program_route_match', measurement_route == implementation_mode, f'{BLOCK_MEASUREMENT_PROGRAM_INVALID}: implementation route mismatch'),
            check(
                'mechanism_math_contract_source_economic_hypothesis_present',
                not has_any_mechanism_math_v1 or mechanism_contract_carries_source_hypotheses(master_mechanism_math_contract, expected_economic_hypothesis, expected_math_hypotheses),
                'legacy mechanism_math_contract.source_economic_hypothesis/source_math_hypothesis_candidates missing or not equal to research_contract',
            ),
            check(
                'canonical_mechanism_math_contract_source_hypotheses_present',
                not has_any_mechanism_math_v1 or mechanism_contract_carries_source_hypotheses(canonical_mechanism_math_contract, expected_economic_hypothesis, expected_math_hypotheses),
                'legacy canonical_spec.mechanism_math_contract source hypotheses missing or not equal to research_contract',
            ),
            check(
                'handoff_mechanism_math_contract_source_hypotheses_present',
                not has_any_mechanism_math_v1 or not handoff or mechanism_contract_carries_source_hypotheses(handoff_mechanism_math_contract, expected_economic_hypothesis, expected_math_hypotheses),
                'legacy handoff mechanism_math_contract source hypotheses missing or not equal to research_contract',
            ),
            check('handoff_legacy_mechanism_math_contract_match', not has_any_mechanism_math_v1 or not handoff or (handoff.get('mechanism_math_contract') or {}) == (mechanism_math_contract or {}), 'legacy handoff mechanism_math_contract mismatch'),
            check('research_compatibility_profile_scope', compatibility_profile is None or flexible_local, 'compatibility profile is valid only for an explicit ordinary local IS object'),
            check('research_compatibility_profile_consistent', canonical_research_contract.get('research_compatibility_profile', compatibility_profile) == compatibility_profile and handoff_research_contract.get('research_compatibility_profile', compatibility_profile) == compatibility_profile, 'research compatibility profile mismatch across master/canonical/handoff'),
            check('innovative_idea_seeds_present', nonempty_list(idea_value) or (flexible_local and isinstance(idea_value, list) and not idea_value and nonempty_str((learning if 'innovative_idea_seeds' in learning else research_contract).get('innovative_idea_seeds_absence_reason'))), 'innovative_idea_seeds missing'),
            check('reuse_instruction_present', nonempty_list(learning.get('reuse_instruction_for_future_agents') or research_contract.get('reuse_instruction_for_future_agents')), 'reuse_instruction_for_future_agents missing'),
            check('similar_case_lessons_imported_present', nonempty_list(lesson_value) or (flexible_local and isinstance(lesson_value, list) and not lesson_value and nonempty_str((learning if 'similar_case_lessons_imported' in learning else research_contract).get('similar_case_lessons_absence_reason'))), 'similar_case_lessons_imported missing'),
            check(
                'knowledge_reference_contract_present',
                valid_knowledge_reference_contract(
                    learning.get('knowledge_reference_contract') or research_contract.get('knowledge_reference_contract'),
                    learning.get('similar_case_lessons_imported') or research_contract.get('similar_case_lessons_imported'),
                ),
                'knowledge_reference_contract missing or invalid',
            ),
            check('information_set_not_illegal', 'illegal' not in info_legality and 'forward_reference' not in info_legality, f'information_set_legality blocks Step2 acceptance: {info_legality}', severity='WARN'),
        ])
        checks.extend(identity_check(master, handoff, rid))
        checks.extend(source_subject_routing_checks(
            master,
            handoff,
            allow_legacy_source_subject_routing_omission=(
                args.allow_legacy_source_subject_routing_omission
            ),
        ))
        checks.extend(manifest_bound_adapter_lineage_checks(master, handoff, rid))
        checks.extend(family_plugin_checks(master, handoff))
        checks.extend(hybrid_contract_checks(master))
        checks.extend(direct_code_contract_checks(master))
    for item in checks:
        if item['status'] == 'BLOCK':
            errors.append(item['error'])
        elif item['status'] == 'WARN':
            warnings.append(item['error'])
    result = 'BLOCK' if errors else 'WARN' if warnings else 'PASS'
    print(json.dumps({'report_id': rid, 'result': result, 'checks': checks, 'errors': errors, 'warnings': warnings}, ensure_ascii=False, indent=2))
    if result == 'BLOCK':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
