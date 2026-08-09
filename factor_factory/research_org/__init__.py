"""Governed multi-agent research organization for Factor Forge."""

from factor_factory.research_org.contracts import (
    AGENT_RESULT_CONTRACT_VERSION,
    AGENT_TASK_CONTRACT_VERSION,
    DISPATCH_MANIFEST_CONTRACT_VERSION,
    DOMAIN_PROPOSAL_CONTRACT_VERSION,
    KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION,
    RESEARCH_ORG_PLAN_CONTRACT_VERSION,
    ResearchOrganizationError,
)
from factor_factory.research_org.director import (
    PLAN_RELATIVE_PATH,
    admit_agent_result,
    build_research_organization_bundle,
    load_research_organization_plan,
    resolve_research_organization_gate,
    validate_agent_result,
    validate_research_organization_bundle,
    write_research_organization_bundle,
)
from factor_factory.research_org.registry import build_agent_registry_snapshot
from factor_factory.research_org.router import route_research_request
from factor_factory.research_org.runtime import (
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
    ResearchOrgSessionRunner,
    request_research_organization_cancel,
    run_research_organization_runtime,
    validate_research_organization_runtime,
)

__all__ = [
    "AGENT_RESULT_CONTRACT_VERSION",
    "AGENT_TASK_CONTRACT_VERSION",
    "DISPATCH_MANIFEST_CONTRACT_VERSION",
    "DOMAIN_PROPOSAL_CONTRACT_VERSION",
    "KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION",
    "PLAN_RELATIVE_PATH",
    "RESEARCH_ORG_PLAN_CONTRACT_VERSION",
    "ResearchOrganizationError",
    "ResearchOrgSessionInvocation",
    "ResearchOrgSessionOutcome",
    "ResearchOrgSessionRunner",
    "admit_agent_result",
    "build_agent_registry_snapshot",
    "build_research_organization_bundle",
    "load_research_organization_plan",
    "resolve_research_organization_gate",
    "route_research_request",
    "request_research_organization_cancel",
    "run_research_organization_runtime",
    "validate_agent_result",
    "validate_research_organization_bundle",
    "validate_research_organization_runtime",
    "write_research_organization_bundle",
]
