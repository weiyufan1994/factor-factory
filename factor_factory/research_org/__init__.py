"""Research organization interfaces; execution components load only when used."""
from importlib import import_module

_EXPORTS = {
    "AGENT_RESULT_CONTRACT_VERSION": "factor_factory.research_org.contracts",
    "AGENT_TASK_CONTRACT_VERSION": "factor_factory.research_org.contracts",
    "DISPATCH_MANIFEST_CONTRACT_VERSION": "factor_factory.research_org.contracts",
    "DOMAIN_PROPOSAL_CONTRACT_VERSION": "factor_factory.research_org.contracts",
    "KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION": "factor_factory.research_org.contracts",
    "RESEARCH_ORG_PLAN_CONTRACT_VERSION": "factor_factory.research_org.contracts",
    "ResearchOrganizationError": "factor_factory.research_org.contracts",
    "PLAN_RELATIVE_PATH": "factor_factory.research_org.director",
    "admit_agent_result": "factor_factory.research_org.director",
    "build_research_organization_bundle": "factor_factory.research_org.director",
    "load_research_organization_plan": "factor_factory.research_org.director",
    "resolve_research_organization_gate": "factor_factory.research_org.director",
    "validate_agent_result": "factor_factory.research_org.director",
    "validate_research_organization_bundle": "factor_factory.research_org.director",
    "write_research_organization_bundle": "factor_factory.research_org.director",
    "ResearchOrgSessionInvocation": "factor_factory.research_org.runtime",
    "ResearchOrgSessionOutcome": "factor_factory.research_org.runtime",
    "ResearchOrgSessionRunner": "factor_factory.research_org.runtime",
    "request_research_organization_cancel": "factor_factory.research_org.runtime",
    "run_research_organization_runtime": "factor_factory.research_org.runtime",
    "validate_research_organization_runtime": "factor_factory.research_org.runtime",
    "build_agent_registry_snapshot": "factor_factory.research_org.registry",
    "route_research_request": "factor_factory.research_org.router",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    try:
        module_name = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
