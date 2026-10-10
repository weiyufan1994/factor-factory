"""Detect an explicitly selected organization without loading its execution stack.

Local research retains the ordinary absent/disabled result. An existing hosted
plan requires the optional director; absence never validates or bypasses it.
"""
from pathlib import Path
from typing import Any

from factor_factory.research_org.contracts import (
    BLOCK_RESEARCH_ORG_PLAN_INVALID,
    BLOCK_RESEARCH_ORG_PLAN_MISSING,
    BLOCK_RESEARCH_ORG_ROUTE_INVALID,
    ResearchOrganizationError,
)

PLAN_RELATIVE_PATH = "identity/research_organization_plan.json"


def resolve_research_organization_gate(
    *,
    mode: str,
    factor_workspace: Path | None,
    explicit_plan: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"off", "auto", "required"}:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PLAN_INVALID, [f"unsupported_mode={mode}"]
        )
    if mode == "off":
        if explicit_plan is not None:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_INVALID,
                ["explicit plan cannot be used when mode is off"],
            )
        return {"requested_mode": mode, "status": "disabled", "formal_org_independence": False}
    if factor_workspace is None:
        if mode == "required":
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_MISSING, ["factor workspace is required"]
            )
        return {"requested_mode": mode, "status": "not_present_legacy", "formal_org_independence": False}
    workspace = Path(factor_workspace).expanduser().resolve(strict=False)
    expected_path = (workspace / PLAN_RELATIVE_PATH).resolve(strict=False)
    if explicit_plan is not None:
        explicit = Path(explicit_plan).expanduser().resolve(strict=False)
        if explicit != expected_path:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_INVALID,
                [f"explicit_plan_path={explicit}", f"expected={expected_path}"],
            )
    if not expected_path.is_file() or expected_path.is_symlink():
        if mode == "required" or explicit_plan is not None:
            raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PLAN_MISSING, [str(expected_path)])
        return {"requested_mode": mode, "status": "not_present_legacy", "formal_org_independence": False}
    try:
        from factor_factory.research_org.director import validate_research_organization_bundle
    except ModuleNotFoundError as exc:
        if exc.name != "factor_factory.research_org.director":
            raise
        raise ResearchOrganizationError(
            "BLOCK_FACTORFORGE_HOSTED_COMPONENTS_NOT_INSTALLED",
            ["The selected organization requires the full hosted source distribution."],
        ) from exc
    summary = validate_research_organization_bundle(workspace=workspace)
    if summary["state"] != "ROUTED":
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_ROUTE_INVALID, [f"organization_state={summary['state']}"]
        )
    return {
        "requested_mode": mode,
        "status": "validated",
        "plan_path": str(expected_path),
        "plan_sha256": summary["plan_sha256"],
        "organization_state": summary["state"],
        "lead_domain": summary["lead_domain"],
        "supporting_domains": summary["supporting_domains"],
        "dispatch_task_count": summary["task_count"],
        "validated_result_count": summary["result_count"],
        "formal_org_independence": False,
        "assurance": "routing_and_result_envelopes_only",
    }
