from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FEATURE_FAMILY_REGISTRY_SCHEMA_VERSION = 'feature_family_registry_v1'

ALLOWED_DOMAINS = {'daily', 'intraday', 'cross_sectional', 'event_bar'}
ALLOWED_PRECOMPUTE_POLICIES = {
    'precompute_now',
    'precompute_after_source_ready',
    'model_specific_only',
    'on_demand_only',
    'do_not_precompute',
}
ALLOWED_REUSE_TIERS = {'broad', 'medium', 'narrow', 'experimental'}
ALLOWED_COST_TIERS = {'low', 'medium', 'high', 'very_high'}


@dataclass(frozen=True)
class FeatureFamilyIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {'field': self.field, 'message': self.message}


def read_feature_family_registry(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'feature family registry root must be an object: {source}')
    return payload


def _require_string(entry: dict[str, Any], field: str, issues: list[FeatureFamilyIssue], prefix: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(FeatureFamilyIssue(f'{prefix}.{field}', 'must be a non-empty string'))
        return ''
    return value


def _require_bool(entry: dict[str, Any], field: str, issues: list[FeatureFamilyIssue], prefix: str) -> bool | None:
    value = entry.get(field)
    if not isinstance(value, bool):
        issues.append(FeatureFamilyIssue(f'{prefix}.{field}', 'must be a boolean'))
        return None
    return value


def _require_string_list(
    entry: dict[str, Any],
    field: str,
    issues: list[FeatureFamilyIssue],
    prefix: str,
    *,
    allow_empty: bool = False,
) -> list[str]:
    value = entry.get(field)
    if not isinstance(value, list):
        issues.append(FeatureFamilyIssue(f'{prefix}.{field}', 'must be a list'))
        return []
    if not allow_empty and not value:
        issues.append(FeatureFamilyIssue(f'{prefix}.{field}', 'must not be empty'))
    result: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(FeatureFamilyIssue(f'{prefix}.{field}[{idx}]', 'must be a non-empty string'))
        else:
            result.append(item)
    return result


def _validate_family(entry: Any, index: int, seen: set[str]) -> list[FeatureFamilyIssue]:
    prefix = f'feature_families[{index}]'
    issues: list[FeatureFamilyIssue] = []
    if not isinstance(entry, dict):
        return [FeatureFamilyIssue(prefix, 'must be an object')]

    family_id = _require_string(entry, 'family_id', issues, prefix)
    if family_id:
        if family_id in seen:
            issues.append(FeatureFamilyIssue(f'{prefix}.family_id', 'must be unique'))
        seen.add(family_id)

    domain = _require_string(entry, 'domain', issues, prefix)
    if domain and domain not in ALLOWED_DOMAINS:
        issues.append(FeatureFamilyIssue(f'{prefix}.domain', f'must be one of {sorted(ALLOWED_DOMAINS)}'))

    policy = _require_string(entry, 'precompute_policy', issues, prefix)
    if policy and policy not in ALLOWED_PRECOMPUTE_POLICIES:
        issues.append(FeatureFamilyIssue(f'{prefix}.precompute_policy', f'must be one of {sorted(ALLOWED_PRECOMPUTE_POLICIES)}'))

    reuse = _require_string(entry, 'reuse_tier', issues, prefix)
    if reuse and reuse not in ALLOWED_REUSE_TIERS:
        issues.append(FeatureFamilyIssue(f'{prefix}.reuse_tier', f'must be one of {sorted(ALLOWED_REUSE_TIERS)}'))

    cost = _require_string(entry, 'cost_tier', issues, prefix)
    if cost and cost not in ALLOWED_COST_TIERS:
        issues.append(FeatureFamilyIssue(f'{prefix}.cost_tier', f'must be one of {sorted(ALLOWED_COST_TIERS)}'))

    _require_string(entry, 'description', issues, prefix)
    _require_string(entry, 'information_set_legality', issues, prefix)
    _require_string(entry, 'recommended_dataset', issues, prefix)
    _require_string(entry, 'reasoning', issues, prefix)
    _require_bool(entry, 'alpha360_related', issues, prefix)
    _require_bool(entry, 'requires_state_continuity', issues, prefix)
    examples = _require_string_list(entry, 'example_features', issues, prefix)
    _require_string_list(entry, 'source_datasets', issues, prefix)
    _require_string_list(entry, 'not_for', issues, prefix, allow_empty=True)

    if policy == 'precompute_now' and reuse not in {'broad', 'medium'}:
        issues.append(FeatureFamilyIssue(f'{prefix}.reuse_tier', 'precompute_now requires broad or medium reuse'))
    if policy in {'precompute_now', 'precompute_after_source_ready'} and not examples:
        issues.append(FeatureFamilyIssue(f'{prefix}.example_features', 'precomputed families must list examples'))
    if cost == 'very_high' and policy == 'precompute_now':
        issues.append(FeatureFamilyIssue(f'{prefix}.precompute_policy', 'very_high cost features must not be precompute_now'))
    if entry.get('requires_state_continuity') is True and 'state' not in entry.get('information_set_legality', '').lower():
        issues.append(FeatureFamilyIssue(f'{prefix}.information_set_legality', 'state-continuity families must document state legality'))

    return issues


def validate_feature_family_registry(payload: dict[str, Any]) -> list[FeatureFamilyIssue]:
    issues: list[FeatureFamilyIssue] = []
    if payload.get('schema_version') != FEATURE_FAMILY_REGISTRY_SCHEMA_VERSION:
        issues.append(
            FeatureFamilyIssue(
                'schema_version',
                f'must equal {FEATURE_FAMILY_REGISTRY_SCHEMA_VERSION}',
            )
        )
    families = payload.get('feature_families')
    if not isinstance(families, list) or not families:
        issues.append(FeatureFamilyIssue('feature_families', 'must be a non-empty list'))
        return issues
    seen: set[str] = set()
    for idx, family in enumerate(families):
        issues.extend(_validate_family(family, idx, seen))
    return issues


def feature_family_summary(payload: dict[str, Any]) -> dict[str, Any]:
    families = payload.get('feature_families') if isinstance(payload.get('feature_families'), list) else []
    entries = [entry for entry in families if isinstance(entry, dict)]
    by_domain: dict[str, int] = {}
    by_policy: dict[str, int] = {}
    alpha360_related: list[str] = []
    precompute_now: list[str] = []
    for entry in entries:
        domain = str(entry.get('domain') or '')
        policy = str(entry.get('precompute_policy') or '')
        by_domain[domain] = by_domain.get(domain, 0) + 1
        by_policy[policy] = by_policy.get(policy, 0) + 1
        if entry.get('alpha360_related') is True:
            alpha360_related.append(str(entry.get('family_id')))
        if policy == 'precompute_now':
            precompute_now.append(str(entry.get('family_id')))
    return {
        'schema_version': payload.get('schema_version'),
        'family_count': len(entries),
        'by_domain': by_domain,
        'by_precompute_policy': by_policy,
        'precompute_now': precompute_now,
        'alpha360_related': alpha360_related,
    }
