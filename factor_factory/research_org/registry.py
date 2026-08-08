from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from factor_factory.research_org.contracts import (
    AGENT_REGISTRY_CONTRACT_VERSION,
    BLOCK_RESEARCH_ORG_REGISTRY_INVALID,
    DOMAIN_PROPOSAL_CONTRACT_VERSION,
    ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
    SAFE_ID_RE,
    validate_content_hash,
    with_content_hash,
)


@dataclass(frozen=True)
class AgentRoleDefinition:
    role_id: str
    status: str
    capability_tags: tuple[str, ...]
    activation_rules: tuple[str, ...]
    required_skills: tuple[str, ...]
    input_contracts: tuple[str, ...]
    output_contract: str
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    model_policy: str
    independence_class: str
    session_requirement: str
    allowed_tools: tuple[str, ...]
    forbidden_side_effects: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, tuple):
                payload[key] = list(value)
        return payload


DEFAULT_ROLES: tuple[AgentRoleDefinition, ...] = (
    AgentRoleDefinition(
        role_id="research_director",
        status="active",
        capability_tags=("routing", "mechanism_synthesis", "state_control"),
        activation_rules=("always",),
        required_skills=("factor-forge-ultimate",),
        input_contracts=("factorforge_research_org_plan_v1",),
        output_contract=ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "objects/research_organization/{report_id}/results/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="reasoning_capability_first",
        independence_class="host_director",
        session_requirement="host_session",
        allowed_tools=("read_workspace", "knowledge_search", "dispatch"),
        forbidden_side_effects=("canonical_write", "production_execution", "shared_data_write"),
    ),
    AgentRoleDefinition(
        role_id="fundamental_researcher",
        status="active",
        capability_tags=("fundamental", "valuation", "accounting", "cash_flow"),
        activation_rules=("route:fundamental",),
        required_skills=("factor-forge-domain-fundamental",),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=DOMAIN_PROPOSAL_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "knowledge/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="domain_reasoning_capability_first",
        independence_class="domain_analysis",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "knowledge_search", "catalog_read"),
        forbidden_side_effects=("canonical_write", "code_execution", "data_materialization"),
    ),
    AgentRoleDefinition(
        role_id="price_volume_researcher",
        status="active",
        capability_tags=("price_volume", "microstructure", "path_functional", "signal_processing"),
        activation_rules=("route:price_volume",),
        required_skills=("factor-forge-domain-price-volume",),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=DOMAIN_PROPOSAL_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "knowledge/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="domain_reasoning_capability_first",
        independence_class="domain_analysis",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "knowledge_search", "catalog_read"),
        forbidden_side_effects=("canonical_write", "code_execution", "data_materialization"),
    ),
    AgentRoleDefinition(
        role_id="event_researcher",
        status="planned",
        capability_tags=("event_text", "disclosure", "news", "causal_timing"),
        activation_rules=("route:event_text",),
        required_skills=(),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=DOMAIN_PROPOSAL_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "knowledge/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="domain_reasoning_capability_first",
        independence_class="domain_analysis",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "knowledge_search", "catalog_read"),
        forbidden_side_effects=("canonical_write", "code_execution", "data_materialization"),
    ),
    AgentRoleDefinition(
        role_id="macro_cross_asset_researcher",
        status="planned",
        capability_tags=("macro", "cross_asset", "rates", "commodities"),
        activation_rules=("route:macro_cross_asset",),
        required_skills=(),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=DOMAIN_PROPOSAL_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "knowledge/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="domain_reasoning_capability_first",
        independence_class="domain_analysis",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "knowledge_search", "catalog_read"),
        forbidden_side_effects=("canonical_write", "code_execution", "data_materialization"),
    ),
    AgentRoleDefinition(
        role_id="knowledge_librarian",
        status="active",
        capability_tags=("knowledge_retrieval", "case_analogy", "negative_results"),
        activation_rules=("always",),
        required_skills=("factor-forge-ultimate",),
        input_contracts=("factorforge_agent_task_v1", "factorforge_knowledge_reference_contract_v1"),
        output_contract=ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
        read_scopes=("identity/**", "knowledge/**", "reports/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="retrieval_precision_first",
        independence_class="advisory",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "knowledge_search"),
        forbidden_side_effects=("canonical_knowledge_write", "research_verdict", "shared_write"),
    ),
    AgentRoleDefinition(
        role_id="data_liaison",
        status="active",
        capability_tags=("catalog_resolution", "data_gap", "data_contract"),
        activation_rules=("always",),
        required_skills=("factor-forge-data-liaison",),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=DOMAIN_PROPOSAL_CONTRACT_VERSION,
        read_scopes=("identity/data_catalog_summary.json", "identity/**", "reports/**"),
        write_scopes=(
            "objects/research_organization/{report_id}/results/{role_id}.json",
            "objects/research_organization/{report_id}/data_requests/**",
        ),
        model_policy="contract_precision_first",
        independence_class="data_interface",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "catalog_read", "write_data_request"),
        forbidden_side_effects=("data_materialization", "catalog_mutation", "shared_data_write"),
    ),
    AgentRoleDefinition(
        role_id="quant_implementation",
        status="active",
        capability_tags=("implementation_plan", "operator", "direct_code", "parity"),
        activation_rules=("after:mechanism_frozen",),
        required_skills=("factor-forge-step3", "factor-forge-step4"),
        input_contracts=("factorforge_agent_task_v1", "factorforge_domain_research_proposal_v1"),
        output_contract=ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "objects/research_organization/{report_id}/results/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="implementation_correctness_first",
        independence_class="implementation",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "catalog_read", "bounded_test"),
        forbidden_side_effects=("canonical_write", "production_run", "shared_data_write"),
    ),
    AgentRoleDefinition(
        role_id="validation_evidence",
        status="active",
        capability_tags=("evidence_replay", "falsification", "metric_validation"),
        activation_rules=("after:evidence_ready",),
        required_skills=("factor-forge-step5", "factor-forge-step6-researcher"),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
        read_scopes=("identity/**", "objects/**", "evaluations/**", "runs/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="verification_precision_first",
        independence_class="verification",
        session_requirement="isolated_session",
        allowed_tools=("read_workspace", "validator_execution", "evidence_replay"),
        forbidden_side_effects=("canonical_write", "threshold_change", "search_after_oos"),
    ),
    AgentRoleDefinition(
        role_id="independent_council",
        status="active",
        capability_tags=("independent_review", "counterexample", "terminal_verdict"),
        activation_rules=("after:evidence_ready",),
        required_skills=("factor-forge-step6",),
        input_contracts=("factorforge_agent_task_v1",),
        output_contract=ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
        read_scopes=("identity/**", "reports/**", "objects/**", "evaluations/**"),
        write_scopes=("objects/research_organization/{report_id}/results/{role_id}.json",),
        model_policy="independent_critical_reasoning",
        independence_class="independent_review",
        session_requirement="independent_session",
        allowed_tools=("read_workspace", "validator_execution", "knowledge_search"),
        forbidden_side_effects=("canonical_write", "implementation_mutation", "threshold_change"),
    ),
)


DOMAIN_ROLE_IDS = {
    "fundamental": "fundamental_researcher",
    "price_volume": "price_volume_researcher",
    "event_text": "event_researcher",
    "macro_cross_asset": "macro_cross_asset_researcher",
}


def build_agent_registry_snapshot() -> dict[str, Any]:
    payload = {
        "contract_version": AGENT_REGISTRY_CONTRACT_VERSION,
        "roles": [role.to_dict() for role in DEFAULT_ROLES],
    }
    return with_content_hash(payload, hash_field="registry_sha256")


def registry_role_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(role.get("role_id")): role
        for role in snapshot.get("roles") or []
        if isinstance(role, dict) and role.get("role_id")
    }


def validate_agent_registry_snapshot(snapshot: Any) -> list[str]:
    reasons: list[str] = []
    if not isinstance(snapshot, dict):
        return [f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:missing"]
    if snapshot.get("contract_version") != AGENT_REGISTRY_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:contract_version")
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:{reason}"
        for reason in validate_content_hash(
            snapshot,
            hash_field="registry_sha256",
            label="registry",
        )
    )
    roles = snapshot.get("roles")
    if not isinstance(roles, list) or not roles:
        reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:roles")
        return reasons
    seen: set[str] = set()
    allowed_statuses = {"active", "planned", "retired"}
    allowed_sessions = {"host_session", "isolated_session", "independent_session"}
    for index, role in enumerate(roles):
        label = f"roles[{index}]"
        if not isinstance(role, dict):
            reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:{label}")
            continue
        role_id = role.get("role_id")
        if not isinstance(role_id, str) or not SAFE_ID_RE.fullmatch(role_id):
            reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:{label}.role_id")
        elif role_id in seen:
            reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:duplicate:{role_id}")
        else:
            seen.add(role_id)
        if role.get("status") not in allowed_statuses:
            reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:{label}.status")
        if role.get("session_requirement") not in allowed_sessions:
            reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:{label}.session_requirement")
        for key in (
            "capability_tags",
            "activation_rules",
            "input_contracts",
            "read_scopes",
            "write_scopes",
            "allowed_tools",
            "forbidden_side_effects",
        ):
            value = role.get(key)
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(item, str) or not item for item in value
            ):
                reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:{label}.{key}")
    required = {
        "research_director",
        "fundamental_researcher",
        "price_volume_researcher",
        "knowledge_librarian",
        "data_liaison",
        "quant_implementation",
        "validation_evidence",
        "independent_council",
    }
    if not required.issubset(seen):
        reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:required_roles")
    return reasons


def format_scope(scope: str, *, report_id: str, role_id: str) -> str:
    return scope.format(report_id=report_id, role_id=role_id)
