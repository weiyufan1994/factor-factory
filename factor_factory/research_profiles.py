"""Versioned content rules for new ordinary IS studies; no legacy relabelling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Keep the historical public name pinned to V1.
ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE = "factorforge_ordinary_local_is_flexible_v1"
ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2 = "factorforge_ordinary_local_is_flexible_v2"
ORDINARY_LOCAL_IS_FLEXIBLE_PROFILES = frozenset({
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE,
    ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2,
})


def flexible_local_profile(profile: Any, scope: str | None) -> bool:
    return isinstance(profile, str) and profile in ORDINARY_LOCAL_IS_FLEXIBLE_PROFILES and scope == "local_is_only"


def revision_evidence_minimum(profile: Any, scope: str | None) -> int:
    """Presence/shape only: a reviewer still assesses whether a test is sufficient."""
    return 1 if profile == ORDINARY_LOCAL_IS_FLEXIBLE_PROFILE_V2 and scope == "local_is_only" else 2


INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING = (
    "__invalid_research_compatibility_profile_binding__"
)


def research_compatibility_profile_from_spec(spec: Any) -> str | None:
    """Return only the profile consistently bound on the current Step2 spec."""
    if not isinstance(spec, dict):
        return None
    contract = spec.get("research_contract")
    contract_has_profile = (
        isinstance(contract, dict) and "research_compatibility_profile" in contract
    )
    top_has_profile = "research_compatibility_profile" in spec
    contract_profile = (
        contract.get("research_compatibility_profile")
        if isinstance(contract, dict)
        else None
    )
    if top_has_profile and (
        not contract_has_profile
        or spec.get("research_compatibility_profile") != contract_profile
    ):
        return INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING
    return contract_profile if contract_has_profile else None


def research_profile_from_workspace(root: Path, report_id: str) -> str | None:
    """Read the declared profile, never infer it from results or a missing file."""
    path = root / "objects/factor_spec_master" / f"factor_spec_master__{report_id}.json"
    if path.is_symlink():
        return INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        spec = json.loads(raw)
    except (ValueError, TypeError):
        return INVALID_RESEARCH_COMPATIBILITY_PROFILE_BINDING
    return research_compatibility_profile_from_spec(spec)
