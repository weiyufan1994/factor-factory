from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

FAMILY_PLUGIN_DECISION_VERSION = 'factorforge_family_plugin_decision_v1'
FAMILY_PLUGIN_PRODUCER = 'factor_family_plugin'


class FamilyPluginContractError(AssertionError):
    pass


@dataclass(frozen=True)
class FamilyPluginContract:
    family_id: str
    plugin_id: str
    plugin_version: str
    implementation_mode: str
    allowed_factor_ids: tuple[str, ...]
    allowed_source_types: tuple[str, ...] = ('pdf_report', 'natural_language_hypothesis')
    required_explicit_declaration: bool = True
    not_generic_fallback: bool = True
    producer: str = FAMILY_PLUGIN_PRODUCER


class FamilyPlugin(Protocol):
    contract: FamilyPluginContract

    def generate(self, report_id: str, prep: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
        ...


def signal_column_name(factor_id: str | None) -> str:
    raw = re.sub(r'[^0-9a-zA-Z]+', '_', str(factor_id or '').strip().lower()).strip('_') or 'factor'
    return raw if raw.endswith('_factor') else f'{raw}_factor'


def family_declaration(spec: dict[str, Any]) -> dict[str, Any]:
    contract = spec.get('implementation_contract') or {}
    decision = spec.get('family_plugin_decision') or contract.get('family_plugin_decision') or {}
    return {
        'factor_family': spec.get('factor_family') or contract.get('factor_family'),
        'family_plugin': spec.get('family_plugin') or contract.get('family_plugin'),
        'family_plugin_allowed': bool(spec.get('family_plugin_allowed') or contract.get('family_plugin_allowed')),
        'family_plugin_decision': decision,
        'allow_unlisted_factor_id_with_human_review': bool(
            spec.get('allow_unlisted_factor_id_with_human_review')
            or contract.get('allow_unlisted_factor_id_with_human_review')
        ),
    }


def validate_explicit_declaration(spec: dict[str, Any], contract: FamilyPluginContract) -> None:
    declaration = family_declaration(spec)
    if not declaration['family_plugin_allowed']:
        raise FamilyPluginContractError('BLOCK_FAMILY_PLUGIN_NOT_DECLARED: family_plugin_allowed must be true')
    if declaration['factor_family'] != contract.family_id:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: factor_family={declaration["factor_family"]!r} '
            f'does not match plugin family {contract.family_id!r}'
        )
    if declaration['family_plugin'] != contract.plugin_id:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: family_plugin={declaration["family_plugin"]!r} '
            f'does not match plugin_id {contract.plugin_id!r}'
        )
    if spec.get('implementation_mode') != contract.implementation_mode:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_MODE_MISMATCH: implementation_mode={spec.get("implementation_mode")!r} '
            f'does not match plugin mode {contract.implementation_mode!r}'
        )
    if spec.get('source_type') not in contract.allowed_source_types:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_SOURCE_TYPE_NOT_ALLOWED: source_type={spec.get("source_type")!r}'
        )

    allowed_ids = {item.upper() for item in contract.allowed_factor_ids}
    factor_id = str(spec.get('factor_id') or '')
    if allowed_ids and factor_id.upper() not in allowed_ids and not declaration['allow_unlisted_factor_id_with_human_review']:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_FACTOR_ID_NOT_ALLOWED: factor_id={factor_id!r} plugin={contract.plugin_id!r}'
        )

    decision = declaration['family_plugin_decision']
    if not isinstance(decision, dict) or not decision:
        raise FamilyPluginContractError('BLOCK_FAMILY_PLUGIN_NOT_DECLARED: family_plugin_decision is required')
    if decision.get('decision_version') != FAMILY_PLUGIN_DECISION_VERSION:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: family_plugin_decision.decision_version must be {FAMILY_PLUGIN_DECISION_VERSION}'
        )
    if decision.get('plugin_selected') is not True or decision.get('plugin_id') != contract.plugin_id:
        raise FamilyPluginContractError('BLOCK_FAMILY_PLUGIN_NOT_DECLARED: family_plugin_decision must select this plugin')
    if decision.get('not_selected_by_free_text') is not True:
        raise FamilyPluginContractError('BLOCK_FAMILY_PLUGIN_FREE_TEXT_TRIGGER: plugin selection cannot come from free-text tokens')
    explicit_evidence = decision.get('explicit_evidence')
    if not isinstance(explicit_evidence, list) or not explicit_evidence:
        raise FamilyPluginContractError('BLOCK_FAMILY_PLUGIN_NOT_DECLARED: explicit_evidence is required')


def plugin_identity_fields(contract: FamilyPluginContract) -> dict[str, Any]:
    return {
        'factor_family': contract.family_id,
        'family_plugin': contract.plugin_id,
        'plugin_version': contract.plugin_version,
        'not_generic_fallback': contract.not_generic_fallback,
    }
