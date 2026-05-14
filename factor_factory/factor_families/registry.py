from __future__ import annotations

from typing import Any

from .base import (
    FAMILY_PLUGIN_PRODUCER,
    FamilyPlugin,
    FamilyPluginContract,
    FamilyPluginContractError,
    family_declaration,
    plugin_identity_fields,
    validate_explicit_declaration,
)
from .cpv import PLUGIN as CPV_PLUGIN
from .shadow_candlestick import PLUGIN as SHADOW_CANDLESTICK_PLUGIN

PLUGINS: dict[str, FamilyPlugin] = {
    SHADOW_CANDLESTICK_PLUGIN.contract.plugin_id: SHADOW_CANDLESTICK_PLUGIN,
    CPV_PLUGIN.contract.plugin_id: CPV_PLUGIN,
}


def get_family_plugin_contract(plugin_id: str) -> FamilyPluginContract:
    plugin = PLUGINS.get(str(plugin_id or ''))
    if plugin is None:
        raise FamilyPluginContractError(f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: unknown family_plugin={plugin_id!r}')
    return plugin.contract


def resolve_family_plugin(spec: dict[str, Any], implementation_mode: str | None = None) -> FamilyPlugin:
    declaration = family_declaration(spec)
    plugin_id = declaration.get('family_plugin')
    if not declaration.get('family_plugin_allowed'):
        raise FamilyPluginContractError('BLOCK_FAMILY_PLUGIN_NOT_DECLARED: family_plugin_allowed must be true')
    plugin = PLUGINS.get(str(plugin_id or ''))
    if plugin is None:
        raise FamilyPluginContractError(f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: unknown family_plugin={plugin_id!r}')
    if implementation_mode and implementation_mode != plugin.contract.implementation_mode:
        raise FamilyPluginContractError(
            f'BLOCK_FAMILY_PLUGIN_MODE_MISMATCH: dispatcher mode={implementation_mode!r} '
            f'plugin mode={plugin.contract.implementation_mode!r}'
        )
    validate_explicit_declaration(spec, plugin.contract)
    return plugin


def has_family_plugin_declaration(spec: dict[str, Any]) -> bool:
    declaration = family_declaration(spec)
    return bool(declaration.get('family_plugin') or declaration.get('factor_family') or declaration.get('family_plugin_allowed'))


def explicit_plugin_identity_fields(spec: dict[str, Any]) -> dict[str, Any]:
    declaration = family_declaration(spec)
    plugin_id = declaration.get('family_plugin')
    contract = get_family_plugin_contract(str(plugin_id or ''))
    return plugin_identity_fields(contract)


def validate_family_plugin_artifacts(spec: dict[str, Any], artifacts: list[tuple[str, dict[str, Any]]]) -> None:
    plugin_produced = False
    for _, artifact in artifacts:
        identity = artifact.get('artifact_identity') or ((artifact.get('metadata') or {}).get('artifact_identity')) or {}
        if artifact.get('producer') == FAMILY_PLUGIN_PRODUCER or identity.get('producer') == FAMILY_PLUGIN_PRODUCER:
            plugin_produced = True
            break
    if not plugin_produced:
        return

    plugin = resolve_family_plugin(spec, spec.get('implementation_mode'))
    fields = plugin_identity_fields(plugin.contract)
    for label, artifact in artifacts:
        identity = artifact.get('artifact_identity') or ((artifact.get('metadata') or {}).get('artifact_identity')) or {}
        producer = artifact.get('producer') or identity.get('producer')
        if producer != FAMILY_PLUGIN_PRODUCER:
            raise AssertionError(f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: {label}.producer must be {FAMILY_PLUGIN_PRODUCER}')
        for key, expected in fields.items():
            actual = artifact.get(key) if artifact.get(key) is not None else identity.get(key)
            if actual != expected:
                raise AssertionError(
                    f'BLOCK_FAMILY_PLUGIN_NOT_DECLARED: {label}.{key}={actual!r} expected {expected!r}'
                )
        if identity.get('implementation_mode') != plugin.contract.implementation_mode:
            raise AssertionError(
                f'BLOCK_FAMILY_PLUGIN_MODE_MISMATCH: {label}.artifact_identity.implementation_mode={identity.get("implementation_mode")!r}'
            )
