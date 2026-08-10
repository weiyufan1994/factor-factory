from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factor_factory.catalog_policy import project_information_policy_attestation
from factor_factory.research_org.contracts import (
    AGENT_RESULT_CONTRACT_VERSION,
    AGENT_TASK_CONTRACT_VERSION,
    BLOCK_RESEARCH_ORG_IDENTITY_INVALID,
    BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID,
    BLOCK_RESEARCH_ORG_PATH_INVALID,
    BLOCK_RESEARCH_ORG_PLAN_INVALID,
    BLOCK_RESEARCH_ORG_PLAN_MISSING,
    BLOCK_RESEARCH_ORG_REGISTRY_INVALID,
    BLOCK_RESEARCH_ORG_RESULT_INVALID,
    BLOCK_RESEARCH_ORG_ROUTE_INVALID,
    BLOCK_RESEARCH_ORG_TASK_INVALID,
    DISPATCH_MANIFEST_CONTRACT_VERSION,
    DOMAIN_PROPOSAL_CONTRACT_VERSION,
    KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION,
    RESEARCH_ORG_PLAN_CONTRACT_VERSION,
    SHA256_RE,
    ResearchOrganizationError,
    normalize_workspace_relative_path,
    private_reasoning_paths,
    read_workspace_json,
    sha256_file,
    stable_json_hash,
    validate_content_hash,
    validate_identity_value,
    with_content_hash,
    workspace_file_lock,
    write_workspace_json,
    write_workspace_json_once,
)
from factor_factory.research_org.registry import (
    DOMAIN_ROLE_IDS,
    agent_registry_policy_compatible,
    build_agent_registry_snapshot,
    format_scope,
    registry_role_map,
    validate_agent_registry_snapshot,
)
from factor_factory.research_org.router import (
    ROUTER_CONTRACT_VERSION,
    route_research_request,
)
from factor_factory.research_workspace import (
    load_workspace_manifest,
    validate_workspace_manifest,
    workspace_manifest_path,
)

PLAN_RELATIVE_PATH = "identity/research_organization_plan.json"
ORG_ROOT_TEMPLATE = "objects/research_organization/{report_id}"
VALID_PLAN_STATES = {"ROUTED", "NEEDS_CLARIFICATION", "WAITING_CAPABILITY"}
VALID_RESULT_STATUSES = {"PASS", "BLOCK", "NEEDS_DATA", "NEEDS_CLARIFICATION"}
VALID_PRODUCER_MODES = {"real_agent", "single_agent_fallback"}
DOMAIN_PROPOSAL_STATUS_MAP = {
    "ready_for_director_review": "PASS",
    "under_specified": "NEEDS_CLARIFICATION",
    "awaiting_data": "NEEDS_DATA",
    "out_of_domain": "BLOCK",
    "delivery_rejected": "BLOCK",
}
INPUT_SNAPSHOT_CONTRACT_VERSION = "factorforge_research_org_input_snapshot_v1"
DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION = (
    "factorforge_host_research_director_record_v1"
)
PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION = (
    "factorforge_preformal_design_review_v3"
)
PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION = (
    "factorforge_preformal_independent_council_verdict_v3"
)
DATA_REQUEST_CONTRACT_VERSION = "factorforge_data_request_v1"
DATA_LIAISON_PREFORMAL_RESOLUTION_CONTRACT_VERSION = (
    "factorforge_data_liaison_preformal_resolution_v1"
)
DATA_LIAISON_FORMAL_EXECUTION_CHECKS = (
    "catalog_identity",
    "dataset_qa",
    "lookahead_policy",
    "coverage",
    "worker_read_smoke",
)
KNOWLEDGE_PRIOR_CONTRACT_VERSION = "factorforge_knowledge_prior_contract_v1"
KNOWLEDGE_RETRIEVAL_PROVENANCE_CONTRACT_VERSION = (
    "factorforge_knowledge_retrieval_provenance_v1"
)
KNOWLEDGE_PRIOR_EXECUTIVE_SUMMARY = (
    "Bound historical priors and falsifiers were retrieved for Host review; "
    "no current-factor empirical evidence or verdict is issued."
)
KNOWLEDGE_PRIOR_CLAIM_TYPES = {
    "MECHANISM_PRIOR",
    "NEGATIVE_RESULT_PRIOR",
    "FALSIFIER_PRIOR",
    "IMPLEMENTATION_PRIOR",
    "DATA_BOUNDARY_PRIOR",
}
PREFORMAL_CLEAR_DECISION = "CLEAR_FOR_FORMAL_EXECUTION"
PREFORMAL_BLOCK_DECISION = "BLOCK_FORMAL_EXECUTION"
PREFORMAL_ROLE_CHECK_IDS = {
    "quant_implementation": (
        "estimator_semantics",
        "timing_and_information_set",
        "operator_or_direct_code_route",
        "parity_and_invariants",
        "data_contract_alignment",
    ),
    "validation_evidence": (
        "is_oos_and_trial_budget",
        "metric_and_threshold_preregistration",
        "cost_turnover_and_long_side",
        "ablations_and_falsifiers",
        "proof_and_provenance",
    ),
    "independent_council": (
        "economic_mechanism",
        "math_measurement_identity",
        "data_and_timing_legality",
        "implementation_and_parity",
        "validation_and_falsification",
        "independence_and_scope",
    ),
}
PREFORMAL_CLAIM_TYPES = ("DESIGN_REQUIREMENT",)
PREFORMAL_FINDING_CODES = {
    "PASS": "DESIGN_CHECK_SATISFIED",
    "BLOCK": "DESIGN_CHECK_UNSATISFIED",
}
PREFORMAL_FALSIFIER_CODES = {
    check_id: f"{check_id.upper()}_FALSIFIED"
    for check_ids in PREFORMAL_ROLE_CHECK_IDS.values()
    for check_id in check_ids
}
PREFORMAL_EXECUTIVE_SUMMARIES = {
    PREFORMAL_CLEAR_DECISION: (
        "Pre-formal design checks cleared; no empirical factor verdict has been issued."
    ),
    PREFORMAL_BLOCK_DECISION: (
        "Pre-formal design checks blocked; no empirical factor verdict has been issued."
    ),
}
PREFORMAL_CLAIM_SCOPE = {
    "stage": "pre_formal_research_design",
    "claim_domain": "research_design_only",
    "allowed_claim_types": list(PREFORMAL_CLAIM_TYPES),
    "record_semantics": "controlled_design_checks_only",
    "free_text_claims_allowed": False,
    "realized_performance_evidence": False,
    "empirical_factor_verdict": "NOT_ISSUED",
    "promotion_authority": False,
}
_EMPIRICAL_CLAIM_KEY_RE = re.compile(
    r"^(?:factor_verdict|empirical_verdict|backtest_metrics?|sharpe|icir|"
    r"rank_?ic|annual(?:ized)?_return|max(?:imum)?_drawdown)$",
    re.IGNORECASE,
)
_REALIZED_EVIDENCE_RE = re.compile(
    r"(?:completed\s+(?:historical\s+)?(?:simulation|backtest|test)|"
    r"historical\s+(?:simulation|backtest)\s+(?:result|outcome)|"
    r"observed\s+(?:in[- ]?sample|out[- ]?of[- ]?sample|oos|empirical)|"
    r"realized\s+(?:performance|return|result|outcome)|"
    r"(?:已完成|历史)(?:仿真|模拟|回测)(?:结果|表现)?|"
    r"(?:样本内|样本外|oos|实证)(?:观察|结果|表现)|已实现(?:收益|表现|结果))",
    re.IGNORECASE,
)
_REALIZED_ASSERTION_RE = re.compile(
    r"(?:delivered|achieved|reached|recorded|obtained|produced|returned|"
    r"outperformed|underperformed|demonstrated|confirmed|showed|yielded|"
    r"达到|实现|录得|获得|产生|跑赢|跑输|证明|证实|显示)",
    re.IGNORECASE,
)
_EMPIRICAL_METRIC_VALUE_RE = re.compile(
    r"(?:sharpe(?:\s+ratio)?|icir|rank\s*ic|information\s+coefficient|"
    r"annual(?:ized)?\s+return|max(?:imum)?\s+drawdown|hit\s+rate|t[- ]?stat|"
    r"夏普(?:比率)?|信息系数|年化收益|最大回撤|胜率|t\s*值)"
    r".{0,48}?[-+]?\d+(?:\.\d+)?%?",
    re.IGNORECASE,
)
_EMPIRICAL_DISPOSITION_RE = re.compile(
    r"(?:promotion\s+(?:is\s+)?warranted|should\s+be\s+promoted|"
    r"factor\s+(?:is|was|should\s+be)\s+(?:accepted|rejected|promoted)|"
    r"(?:accept|reject|promote)\s+the\s+factor|"
    r"因子(?:应当|应该|可以|已)?(?:接受|拒绝|晋级|入库)|"
    r"(?:接受|拒绝|晋级|入库)该因子)",
    re.IGNORECASE,
)
_EMPIRICAL_VALUE_CLAIM_RE = re.compile(
    r"(?:\bbacktest\s+(?:proves?|proved|shows?|showed|confirms?|confirmed)\b|"
    r"\bfactor[_\s-]*verdict\s*(?:=|is|:)\s*(?:accept|promote|reject)\b|"
    r"回测(?:证明|证实|显示)|因子(?:结论|裁决)\s*(?:为|=|:)?\s*"
    r"(?:accept|promote|reject|接受|晋级|拒绝))",
    re.IGNORECASE,
)
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_valid_workspace(workspace: Path) -> tuple[Path, dict[str, Any]]:
    resolved = Path(workspace).expanduser().resolve(strict=False)
    manifest_path = workspace_manifest_path(resolved)
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PLAN_MISSING,
            [f"workspace_manifest:{manifest_path}"],
        )
    manifest = load_workspace_manifest(manifest_path)
    failures = validate_workspace_manifest(manifest)
    if failures:
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PLAN_INVALID, failures)
    if Path(str(manifest.get("workspace_root") or "")).expanduser().resolve(strict=False) != resolved:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_IDENTITY_INVALID,
            ["workspace_root_mismatch"],
        )
    return resolved, manifest


def _identity(manifest: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, str]:
    identity = {
        "factor_id": str(manifest.get("factor_id") or ""),
        "research_id": str(manifest.get("research_id") or ""),
        "report_id": str(request.get("report_id") or manifest.get("active_report_id") or ""),
        "job_id": str(request.get("job_id") or "local_research"),
    }
    reasons: list[str] = []
    for key, value in identity.items():
        reasons.extend(validate_identity_value(value, label=key))
    for key in ("factor_id", "research_id"):
        request_value = request.get(key)
        if request_value is not None and str(request_value) != identity[key]:
            reasons.append(f"{key}:request_workspace_mismatch")
    if reasons:
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_IDENTITY_INVALID, reasons)
    return identity


def _selected_domains(route: Mapping[str, Any]) -> list[str]:
    lead = route.get("lead_domain")
    supporting = route.get("supporting_domains")
    output: list[str] = []
    if isinstance(lead, str) and lead:
        output.append(lead)
    if isinstance(supporting, list):
        output.extend(str(item) for item in supporting if isinstance(item, str) and item)
    return list(dict.fromkeys(output))


def _role_plan(route: Mapping[str, Any], registry: Mapping[str, Any]) -> dict[str, Any]:
    role_map = registry_role_map(dict(registry))
    selected_domains = _selected_domains(route)
    domain_roles = [DOMAIN_ROLE_IDS[domain] for domain in selected_domains if domain in DOMAIN_ROLE_IDS]
    active_domain_roles = [
        role_id for role_id in domain_roles if role_map.get(role_id, {}).get("status") == "active"
    ]
    unavailable_domain_roles = [role_id for role_id in domain_roles if role_id not in active_domain_roles]
    intake_roles = ["research_director", "knowledge_librarian", "data_liaison", *active_domain_roles]
    downstream = ["quant_implementation", "validation_evidence", "independent_council"]
    if route.get("route_state") in {"UNDER_SPECIFIED", "WAITING_CAPABILITY"}:
        required_roles = intake_roles
        deferred_roles = downstream
    else:
        required_roles = [*intake_roles, *downstream]
        deferred_roles = []
    return {
        "required_roles": list(dict.fromkeys(required_roles)),
        "deferred_roles": deferred_roles,
        "unavailable_roles": unavailable_domain_roles,
        "domain_role_assignments": {
            domain: DOMAIN_ROLE_IDS.get(domain) for domain in selected_domains
        },
    }


def _plan_state(route_state: str) -> str:
    if route_state == "UNDER_SPECIFIED":
        return "NEEDS_CLARIFICATION"
    if route_state in {"WAITING_CAPABILITY", "ROUTED_WITH_CAPABILITY_GAP"}:
        return "WAITING_CAPABILITY"
    return "ROUTED"


def build_research_organization_plan(
    *,
    workspace_manifest: Mapping[str, Any],
    request: Mapping[str, Any],
    input_snapshot_refs: Iterable[Mapping[str, str]],
    researcher_memory_binding: Mapping[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    identity = _identity(workspace_manifest, request)
    route = route_research_request(request)
    registry = build_agent_registry_snapshot()
    role_plan = _role_plan(route, registry)
    org_root = ORG_ROOT_TEMPLATE.format(report_id=identity["report_id"])
    payload = {
        "contract_version": RESEARCH_ORG_PLAN_CONTRACT_VERSION,
        "identity": identity,
        "state": _plan_state(str(route.get("route_state") or "")),
        "generated_at_utc": generated_at_utc or utc_now(),
        "generated_by": "factorforge_host_research_director",
        "routing": route,
        "input_snapshot_refs": [copy.deepcopy(dict(item)) for item in input_snapshot_refs],
        "agent_registry": registry,
        "role_plan": role_plan,
        "execution_policy": {
            "one_user_task_per_factor": True,
            "one_isolated_factor_workspace": True,
            "domain_agents_use_isolated_sessions": True,
            "host_is_only_canonical_merger": True,
            "single_agent_fallback": False,
            "fallback_must_be_explicit": True,
            "fallback_cannot_claim_independent_council": True,
            "private_chain_of_thought_forbidden_in_artifacts": True,
            "public_derivation_and_decisive_steps_required": True,
        },
        "workflow": {
            "states": [
                "CREATED",
                "ROUTED",
                "DOMAIN_RESEARCH",
                "MECHANISM_FROZEN",
                "DATA_READY",
                "WAITING_DATA",
                "IMPLEMENTING",
                "EVIDENCE_READY",
                "COUNCIL_REVIEW",
                "ITERATE",
                "REJECT",
                "PROMOTE",
            ],
            "waiting_data_is_nonterminal": True,
            "promotion_requires_independent_council": True,
        },
        "data_team_interface": {
            "mode": "external_contract_only",
            "data_liaison_may_materialize_data": False,
            "request_contract": "data_request_v1",
            "accepted_delivery_evidence": ["catalog_entry", "qa_summary", "delivery_receipt"],
            "missing_data_state": "WAITING_DATA",
        },
        "workspace_policy": {
            "plan_path": PLAN_RELATIVE_PATH,
            "organization_root": org_root,
            "dispatch_manifest_path": f"{org_root}/dispatch_manifest.json",
            "task_root": f"{org_root}/tasks",
            "result_root": f"{org_root}/results",
            "all_writes_under_factor_workspace": True,
            "cross_factor_reads_or_writes_allowed": False,
        },
    }
    if researcher_memory_binding is not None:
        payload["researcher_memory"] = copy.deepcopy(
            dict(researcher_memory_binding)
        )
    return with_content_hash(payload, hash_field="plan_sha256")


def _captured_input_snapshot(
    *,
    source_payload: Mapping[str, Any],
    source_path: str,
    source_sha256: str,
    source_hash_kind: str,
    snapshot_name: str,
    report_id: str,
) -> dict[str, Any]:
    snapshot_path = (
        f"objects/research_organization/{report_id}/inputs/{snapshot_name}"
    )
    payload = with_content_hash(
        {
            "contract_version": INPUT_SNAPSHOT_CONTRACT_VERSION,
            "source_path": source_path,
            "source_sha256": source_sha256,
            "source_hash_kind": source_hash_kind,
            "captured_payload": copy.deepcopy(dict(source_payload)),
        },
        hash_field="snapshot_sha256",
    )
    return {
        "path": snapshot_path,
        "sha256": payload["snapshot_sha256"],
        "hash_kind": "json_content",
        "payload": payload,
    }


def _input_snapshot(workspace: Path, relative: str, *, report_id: str) -> dict[str, Any] | None:
    path = workspace / relative
    if not path.is_file() or path.is_symlink():
        return None
    try:
        source_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_TASK_INVALID,
            [f"input_snapshot_source:{relative}"],
        ) from exc
    if not isinstance(source_payload, dict):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_TASK_INVALID,
            [f"input_snapshot_object_required:{relative}"],
        )
    return _captured_input_snapshot(
        source_payload=source_payload,
        source_path=relative,
        source_sha256=sha256_file(path),
        source_hash_kind="file_bytes",
        snapshot_name=Path(relative).name,
        report_id=report_id,
    )


def _task_phase(role_id: str) -> str:
    if role_id in {"research_director", "knowledge_librarian", "data_liaison"}:
        return "intake"
    if role_id.endswith("_researcher"):
        return "domain_research"
    if role_id == "quant_implementation":
        return "implementation"
    if role_id == "validation_evidence":
        return "validation"
    if role_id == "independent_council":
        return "council"
    return "unknown"


def _task_dependencies(role_id: str, role_ids: list[str]) -> list[str]:
    domain = [item for item in role_ids if item.endswith("_researcher")]
    intake = [item for item in ("knowledge_librarian", "data_liaison") if item in role_ids]
    if role_id == "research_director":
        return [*domain, *intake]
    if role_id == "quant_implementation":
        return [*domain, *intake, "research_director"]
    if role_id == "validation_evidence":
        return ["quant_implementation"]
    if role_id == "independent_council":
        return ["validation_evidence", "research_director"]
    return []


def transitive_dependency_roles(
    *,
    task: Mapping[str, Any],
    tasks_by_role: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return the frozen direct and transitive role dependency order."""

    roots = list(task.get("depends_on_roles") or [])
    if task.get("role_id") == "independent_council":
        roots = list(task.get("required_review_role_ids") or [])
    closure: list[str] = []
    pending = [str(item) for item in roots]
    while pending:
        role_id = pending.pop(0)
        if not role_id or role_id in closure:
            continue
        closure.append(role_id)
        dependency_task = tasks_by_role.get(role_id)
        if dependency_task is not None:
            pending.extend(
                str(item)
                for item in dependency_task.get("depends_on_roles") or []
            )
    return tuple(closure)


def _execution_stage_contract(role_id: str) -> dict[str, Any]:
    objectives = {
        "research_director": (
            "Synthesize admitted intake into one frozen mechanism-first research plan."
        ),
        "knowledge_librarian": (
            "Retrieve advisory priors, analogous structures, negative results, and "
            "falsifiers without choosing the estimand."
        ),
        "data_liaison": (
            "Resolve the proposed legal information set against the catalog and emit "
            "auditable data gaps without materializing data."
        ),
        "quant_implementation": (
            "Audit the frozen plan's estimator, implementation route, operator or "
            "direct-code boundary, timing, and parity obligations before execution."
        ),
        "validation_evidence": (
            "Audit the pre-registered IS/OOS windows, trial budget, timing, costs, "
            "thresholds, ablations, falsifiers, and proof obligations before execution."
        ),
        "independent_council": (
            "Independently challenge the complete pre-execution research design and "
            "either clear it for formal Ultimate execution or return a precise blocker."
        ),
    }
    objective = objectives.get(
        role_id,
        "Develop a mechanism-first domain proposal before formal execution.",
    )
    return {
        "stage": "pre_formal_research_design",
        "objective": objective,
        "formal_backtest_evidence_available": False,
        "empirical_factor_verdict_allowed": False,
        "post_execution_empirical_council_owner": "factor-forge-step6",
    }


def _task_role_memory(
    plan: Mapping[str, Any],
    *,
    role_id: str,
) -> dict[str, Any] | None:
    from factor_factory.researcher_memory import CANDIDATE_CONTRACT_VERSION

    binding = plan.get("researcher_memory")
    if not isinstance(binding, Mapping):
        return None
    references = binding.get("role_snapshot_refs")
    if not isinstance(references, Mapping):
        return None
    reference = references.get(role_id)
    if not isinstance(reference, Mapping):
        return None
    return {
        "required": True,
        "snapshot_ref": copy.deepcopy(dict(reference)),
        "learning_output_contract": CANDIDATE_CONTRACT_VERSION,
        "canonical_write_allowed": False,
    }


def _build_tasks(
    *,
    plan: Mapping[str, Any],
    input_artifacts: list[dict[str, str]],
) -> list[dict[str, Any]]:
    identity = dict(plan["identity"])
    report_id = identity["report_id"]
    role_ids = list(plan["role_plan"]["required_roles"])
    registry = registry_role_map(dict(plan["agent_registry"]))
    shared_inputs = copy.deepcopy(input_artifacts)
    tasks: list[dict[str, Any]] = []
    for sequence, role_id in enumerate(role_ids, start=1):
        role = registry[role_id]
        task_id = f"task_{sequence:02d}_{role_id}"
        write_scopes = [
            format_scope(scope, report_id=report_id, role_id=role_id)
            for scope in role["write_scopes"]
        ]
        expected = f"objects/research_organization/{report_id}/results/{role_id}.json"
        payload = {
            "contract_version": AGENT_TASK_CONTRACT_VERSION,
            "task_id": task_id,
            "identity": identity,
            "plan_ref": {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]},
            "registry_sha256": plan["agent_registry"]["registry_sha256"],
            "role_id": role_id,
            "role_snapshot": copy.deepcopy(role),
            "phase": _task_phase(role_id),
            "status": "READY" if not _task_dependencies(role_id, role_ids) else "PENDING",
            "depends_on_roles": _task_dependencies(role_id, role_ids),
            "input_artifacts": copy.deepcopy(shared_inputs),
            "read_scopes": [
                format_scope(scope, report_id=report_id, role_id=role_id)
                for scope in role["read_scopes"]
            ],
            "write_scopes": write_scopes,
            "expected_result_path": expected,
            "result_envelope_contract": AGENT_RESULT_CONTRACT_VERSION,
            "output_contract": role["output_contract"],
            "result_ingress": {
                "mode": "host_validated_atomic_admission",
                "agent_direct_workspace_write_allowed": False,
                "admission_script": "scripts/admit_factorforge_agent_result.py",
            },
            "session_policy": {
                "requirement": role["session_requirement"],
                "independence_class": role["independence_class"],
                "single_agent_fallback_allowed": bool(
                    plan["execution_policy"]["single_agent_fallback"]
                    and role_id != "independent_council"
                ),
            },
            "research_record_policy": {
                "public_derivation_required": True,
                "private_chain_of_thought_forbidden": True,
                "claims_require_artifact_or_falsifier_refs": True,
            },
            "execution_stage_contract": _execution_stage_contract(role_id),
            "created_by": "factorforge_host_research_director",
        }
        role_memory = _task_role_memory(plan, role_id=role_id)
        if role_memory is not None:
            payload["role_memory"] = role_memory
        if role_id == "independent_council":
            payload["required_review_role_ids"] = [
                item for item in role_ids if item != "independent_council"
            ]
        tasks.append(with_content_hash(payload, hash_field="task_sha256"))
    return tasks


def _build_dispatch(plan: Mapping[str, Any], tasks: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    task_refs = [
        {
            "task_id": task["task_id"],
            "role_id": task["role_id"],
            "phase": task["phase"],
            "status": task["status"],
            "path": (
                f"objects/research_organization/{plan['identity']['report_id']}"
                f"/tasks/{task['task_id']}.json"
            ),
            "sha256": task["task_sha256"],
            "expected_result_path": task["expected_result_path"],
        }
        for task in tasks
    ]
    payload = {
        "contract_version": DISPATCH_MANIFEST_CONTRACT_VERSION,
        "identity": dict(plan["identity"]),
        "plan_ref": {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]},
        "state": plan["state"],
        "tasks": task_refs,
        "dispatch_policy": {
            "independent_sessions_for_non_host_roles": True,
            "parallelize_ready_tasks": True,
            "host_validates_before_merge": True,
            "do_not_create_user_visible_threads": True,
        },
    }
    return with_content_hash(payload, hash_field="dispatch_sha256")


def build_research_organization_bundle(
    *,
    workspace: Path,
    request: Mapping[str, Any],
    researcher_memory_root: Path | None = None,
    researcher_memory_installation_id: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    resolved, manifest = _load_valid_workspace(workspace)
    identity = _identity(manifest, request)
    report_id = identity["report_id"]
    captured_request = copy.deepcopy(dict(request))
    for key, value in identity.items():
        captured_request.setdefault(key, value)
    request_snapshot = _captured_input_snapshot(
        source_payload=captured_request,
        source_path="host_request_payload",
        source_sha256=stable_json_hash(captured_request),
        source_hash_kind="json_content",
        snapshot_name="web_research_request.json",
        report_id=report_id,
    )
    input_snapshots = [
        request_snapshot,
        *[
            item
            for item in (
                _input_snapshot(
                    resolved,
                    "identity/web_research_authoring_contract.json",
                    report_id=report_id,
                ),
                _input_snapshot(
                    resolved,
                    "identity/factor_knowledge_summary.json",
                    report_id=report_id,
                ),
                _input_snapshot(
                    resolved,
                    "identity/data_catalog_summary.json",
                    report_id=report_id,
                ),
                _input_snapshot(
                    resolved,
                    "identity/uploaded_source_report_manifest.json",
                    report_id=report_id,
                ),
            )
            if item is not None
        ],
    ]
    input_artifacts = [
        {key: value for key, value in item.items() if key != "payload"}
        for item in input_snapshots
    ]
    memory_snapshots: dict[str, dict[str, Any]] = {}
    memory_binding: dict[str, Any] | None = None
    if researcher_memory_root is not None:
        from factor_factory.researcher_memory import (
            build_role_memory_snapshots,
            build_snapshot_binding,
        )

        if not researcher_memory_installation_id:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_INVALID,
                ["researcher_memory_installation_id_required"],
            )
        route = route_research_request(request)
        registry = build_agent_registry_snapshot()
        role_ids = list(_role_plan(route, registry)["required_roles"])
        role_map = registry_role_map(registry)
        memory_snapshots = build_role_memory_snapshots(
            researcher_memory_root,
            installation_id=researcher_memory_installation_id,
            identity=identity,
            roles=[role_map[role_id] for role_id in role_ids],
            repo_root=Path(str(manifest["repo_root"])),
            workspace=resolved,
        )
        memory_snapshot_refs = {
            role_id: {
                "path": (
                    f"objects/research_organization/{report_id}"
                    f"/memory_snapshots/{role_id}.json"
                ),
                "sha256": memory_snapshots[role_id]["snapshot_sha256"],
                "hash_kind": "json_content",
            }
            for role_id in role_ids
        }
        memory_binding = build_snapshot_binding(
            role_snapshot_refs=memory_snapshot_refs,
            snapshots=memory_snapshots,
        )
    plan = build_research_organization_plan(
        workspace_manifest=manifest,
        request=request,
        input_snapshot_refs=input_artifacts,
        researcher_memory_binding=memory_binding,
        generated_at_utc=generated_at_utc,
    )
    tasks = _build_tasks(plan=plan, input_artifacts=input_artifacts)
    dispatch = _build_dispatch(plan, tasks)
    return {
        "plan": plan,
        "input_snapshots": input_snapshots,
        "memory_snapshots": memory_snapshots,
        "tasks": tasks,
        "dispatch": dispatch,
    }


def _identity_reasons(actual: Any, expected: Mapping[str, str], *, label: str) -> list[str]:
    if not isinstance(actual, Mapping):
        return [f"{label}:missing"]
    reasons = [
        f"{label}.{key}_mismatch"
        for key, value in expected.items()
        if str(actual.get(key) or "") != str(value)
    ]
    if set(actual) != set(expected):
        reasons.append(f"{label}.shape")
    return reasons


def _ordinary_directory_entries(
    *,
    workspace: Path,
    relative_root: str,
    label: str,
    required: bool,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    try:
        relative = normalize_workspace_relative_path(
            relative_root,
            workspace=workspace,
            label=label,
            allow_directory=True,
        )
    except ResearchOrganizationError as exc:
        return [], [str(exc)]
    root = workspace / relative
    if not root.exists() and not root.is_symlink():
        return (
            [],
            [f"{BLOCK_RESEARCH_ORG_PATH_INVALID}:missing_directory:{relative}"]
            if required
            else [],
        )
    if root.is_symlink() or not root.is_dir():
        return [], [f"{BLOCK_RESEARCH_ORG_PATH_INVALID}:unsafe_directory:{relative}"]
    entries: list[str] = []
    try:
        children = list(root.iterdir())
    except OSError as exc:
        return [], [f"{BLOCK_RESEARCH_ORG_PATH_INVALID}:unreadable_directory:{relative}:{exc}"]
    for child in children:
        child_relative = child.relative_to(workspace).as_posix()
        entries.append(child_relative)
        if child.is_symlink() or not child.is_file():
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_PATH_INVALID}:unsafe_directory_entry:{child_relative}"
            )
    return sorted(entries), reasons


def validate_research_organization_plan(
    plan: Any,
    *,
    workspace: Path,
    expected_identity: Mapping[str, str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(plan, dict):
        return [f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:missing"]
    if plan.get("contract_version") != RESEARCH_ORG_PLAN_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:contract_version")
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:{reason}"
        for reason in validate_content_hash(plan, hash_field="plan_sha256", label="plan")
    )
    identity = plan.get("identity")
    if not isinstance(identity, dict):
        reasons.append(f"{BLOCK_RESEARCH_ORG_IDENTITY_INVALID}:identity")
        identity = {}
    for key in ("factor_id", "research_id", "report_id", "job_id"):
        for item in validate_identity_value(identity.get(key), label=key):
            reasons.append(f"{BLOCK_RESEARCH_ORG_IDENTITY_INVALID}:{item}")
    if expected_identity:
        reasons.extend(
            f"{BLOCK_RESEARCH_ORG_IDENTITY_INVALID}:{item}"
            for item in _identity_reasons(identity, expected_identity, label="identity")
        )
    if plan.get("state") not in VALID_PLAN_STATES:
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:state")
    route = plan.get("routing")
    if not isinstance(route, dict) or route.get("contract_version") != ROUTER_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:routing")
    else:
        route_state = route.get("route_state")
        if route_state not in {
            "ROUTED",
            "ROUTED_WITH_CAPABILITY_GAP",
            "UNDER_SPECIFIED",
            "WAITING_CAPABILITY",
        }:
            reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:route_state")
        if not isinstance(route.get("domain_scores"), dict):
            reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:domain_scores")
        if not isinstance(route.get("routing_input_sha256"), str):
            reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:routing_input_sha256")
        projection = route.get("routing_input_projection")
        if (
            not isinstance(projection, dict)
            or route.get("routing_input_sha256") != stable_json_hash(projection)
            or projection.get("source_count") != len(projection.get("sources") or [])
        ):
            reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:routing_input_projection")
        if plan.get("state") != _plan_state(str(route_state or "")):
            reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:plan_state_mismatch")
    registry = plan.get("agent_registry")
    reasons.extend(validate_agent_registry_snapshot(registry))
    if not agent_registry_policy_compatible(registry):
        reasons.append(f"{BLOCK_RESEARCH_ORG_REGISTRY_INVALID}:policy_mismatch")
    input_snapshot_refs = plan.get("input_snapshot_refs")
    if not isinstance(input_snapshot_refs, list) or not input_snapshot_refs:
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:input_snapshot_refs")
    else:
        seen_snapshot_paths: set[str] = set()
        for reference in input_snapshot_refs:
            if (
                not isinstance(reference, dict)
                or set(reference) != {"path", "sha256", "hash_kind"}
                or reference.get("hash_kind") != "json_content"
                or not isinstance(reference.get("sha256"), str)
                or not SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:input_snapshot_ref"
                )
                continue
            relative = str(reference.get("path") or "")
            if relative in seen_snapshot_paths:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:duplicate_input_snapshot:{relative}"
                )
            seen_snapshot_paths.add(relative)
    role_map = registry_role_map(registry) if isinstance(registry, dict) else {}
    role_plan = plan.get("role_plan")
    required_role_ids: list[str] = []
    if not isinstance(role_plan, dict):
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:role_plan")
    else:
        required_roles = role_plan.get("required_roles")
        if not isinstance(required_roles, list) or not required_roles:
            reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:required_roles")
        elif any(role not in role_map or role_map[role].get("status") != "active" for role in required_roles):
            reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:inactive_required_role")
        else:
            required_role_ids = [str(role) for role in required_roles]
        if (
            isinstance(route, dict)
            and isinstance(registry, dict)
            and role_plan != _role_plan(route, registry)
        ):
            reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:role_plan_mismatch")
    memory_binding = plan.get("researcher_memory")
    if memory_binding is not None:
        from factor_factory.researcher_memory import validate_snapshot_binding

        reasons.extend(
            validate_snapshot_binding(
                memory_binding,
                required_role_ids=required_role_ids,
            )
        )
        memory_refs = (
            memory_binding.get("role_snapshot_refs")
            if isinstance(memory_binding, Mapping)
            else None
        )
        if isinstance(memory_refs, Mapping):
            input_paths = {
                str(reference.get("path") or "")
                for reference in input_snapshot_refs or []
                if isinstance(reference, Mapping)
            }
            if any(
                str(reference.get("path") or "") in input_paths
                for reference in memory_refs.values()
                if isinstance(reference, Mapping)
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:researcher_memory_shared_input"
                )
    execution = plan.get("execution_policy")
    if execution != {
        "one_user_task_per_factor": True,
        "one_isolated_factor_workspace": True,
        "domain_agents_use_isolated_sessions": True,
        "host_is_only_canonical_merger": True,
        "single_agent_fallback": False,
        "fallback_must_be_explicit": True,
        "fallback_cannot_claim_independent_council": True,
        "private_chain_of_thought_forbidden_in_artifacts": True,
        "public_derivation_and_decisive_steps_required": True,
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:execution_policy")
    if plan.get("workflow") != {
        "states": [
            "CREATED",
            "ROUTED",
            "DOMAIN_RESEARCH",
            "MECHANISM_FROZEN",
            "DATA_READY",
            "WAITING_DATA",
            "IMPLEMENTING",
            "EVIDENCE_READY",
            "COUNCIL_REVIEW",
            "ITERATE",
            "REJECT",
            "PROMOTE",
        ],
        "waiting_data_is_nonterminal": True,
        "promotion_requires_independent_council": True,
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:workflow")
    if plan.get("data_team_interface") != {
        "mode": "external_contract_only",
        "data_liaison_may_materialize_data": False,
        "request_contract": "data_request_v1",
        "accepted_delivery_evidence": ["catalog_entry", "qa_summary", "delivery_receipt"],
        "missing_data_state": "WAITING_DATA",
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:data_team_interface")
    workspace_policy = plan.get("workspace_policy")
    if not isinstance(workspace_policy, dict):
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:workspace_policy")
    else:
        for key in ("plan_path", "organization_root", "dispatch_manifest_path", "task_root", "result_root"):
            try:
                normalize_workspace_relative_path(
                    workspace_policy.get(key),
                    workspace=workspace,
                    label=f"workspace_policy.{key}",
                    allow_directory=key.endswith("root"),
                )
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
        if workspace_policy.get("all_writes_under_factor_workspace") is not True:
            reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:workspace_policy.write_boundary")
        report_id = str(identity.get("report_id") or "")
        organization_root = ORG_ROOT_TEMPLATE.format(report_id=report_id)
        if workspace_policy != {
            "plan_path": PLAN_RELATIVE_PATH,
            "organization_root": organization_root,
            "dispatch_manifest_path": f"{organization_root}/dispatch_manifest.json",
            "task_root": f"{organization_root}/tasks",
            "result_root": f"{organization_root}/results",
            "all_writes_under_factor_workspace": True,
            "cross_factor_reads_or_writes_allowed": False,
        }:
            reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:workspace_policy_mismatch")
    return reasons


def _validate_task(
    task: Any,
    *,
    plan: Mapping[str, Any],
    workspace: Path,
    expected_path: str,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(task, dict):
        return [f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:missing"]
    if task.get("contract_version") != AGENT_TASK_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:contract_version")
    if task.get("task_id") != Path(expected_path).stem:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:task_id")
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:{reason}"
        for reason in validate_content_hash(task, hash_field="task_sha256", label="task")
    )
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{item}"
        for item in _identity_reasons(task.get("identity"), plan["identity"], label="identity")
    )
    plan_ref = task.get("plan_ref")
    if not isinstance(plan_ref, dict) or plan_ref != {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]}:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:plan_ref")
    registry = registry_role_map(dict(plan["agent_registry"]))
    role_id = task.get("role_id")
    role = registry.get(str(role_id))
    if role is None or role.get("status") != "active":
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:role_id")
    elif task.get("role_snapshot") != role:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:role_snapshot")
    role_ids = list((plan.get("role_plan") or {}).get("required_roles") or [])
    dependencies = _task_dependencies(str(role_id), role_ids)
    expected_result_path = (
        f"objects/research_organization/{plan['identity']['report_id']}"
        f"/results/{role_id}.json"
    )
    if task.get("registry_sha256") != plan["agent_registry"].get("registry_sha256"):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:registry_sha256")
    if task.get("phase") != _task_phase(str(role_id)):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:phase")
    if task.get("depends_on_roles") != dependencies:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:depends_on_roles")
    if task.get("status") != ("READY" if not dependencies else "PENDING"):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:status")
    if task.get("expected_result_path") != expected_result_path:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:result_path")
    if role is not None:
        expected_read_scopes = [
            format_scope(
                scope,
                report_id=plan["identity"]["report_id"],
                role_id=str(role_id),
            )
            for scope in role["read_scopes"]
        ]
        expected_write_scopes = [
            format_scope(
                scope,
                report_id=plan["identity"]["report_id"],
                role_id=str(role_id),
            )
            for scope in role["write_scopes"]
        ]
        if task.get("read_scopes") != expected_read_scopes:
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:read_scopes")
        if task.get("write_scopes") != expected_write_scopes:
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:write_scopes")
        if task.get("output_contract") != role.get("output_contract"):
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:output_contract")
        if task.get("session_policy") != {
            "requirement": role.get("session_requirement"),
            "independence_class": role.get("independence_class"),
            "single_agent_fallback_allowed": bool(
                plan["execution_policy"]["single_agent_fallback"]
                and role_id != "independent_council"
            ),
        }:
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:session_policy")
    if task.get("result_envelope_contract") != AGENT_RESULT_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:result_contract")
    if task.get("research_record_policy") != {
        "public_derivation_required": True,
        "private_chain_of_thought_forbidden": True,
        "claims_require_artifact_or_falsifier_refs": True,
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:record_policy")
    if task.get("execution_stage_contract") != _execution_stage_contract(
        str(role_id)
    ):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:execution_stage_contract"
        )
    if task.get("created_by") != "factorforge_host_research_director":
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:created_by")
    expected_role_memory = _task_role_memory(plan, role_id=str(role_id))
    if expected_role_memory is None:
        if "role_memory" in task:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:unexpected_role_memory"
            )
    elif task.get("role_memory") != expected_role_memory:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:role_memory"
        )
    if task.get("input_artifacts") != plan.get("input_snapshot_refs"):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:input_artifacts"
        )
    if role_id == "independent_council":
        expected_review_roles = [
            item for item in role_ids if item != "independent_council"
        ]
        if task.get("required_review_role_ids") != expected_review_roles:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:required_review_role_ids"
            )
    elif "required_review_role_ids" in task:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:unexpected_review_roles"
        )
    result_path = task.get("expected_result_path")
    try:
        relative = normalize_workspace_relative_path(
            result_path,
            workspace=workspace,
            label="task.expected_result_path",
        )
        if relative not in (task.get("write_scopes") or []):
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:write_scope")
    except ResearchOrganizationError as exc:
        reasons.append(str(exc))
    ingress = task.get("result_ingress")
    if not isinstance(ingress, dict) or ingress != {
        "mode": "host_validated_atomic_admission",
        "agent_direct_workspace_write_allowed": False,
        "admission_script": "scripts/admit_factorforge_agent_result.py",
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:result_ingress")
    for artifact in task.get("input_artifacts") or []:
        if not isinstance(artifact, dict):
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:input_artifact")
            continue
        try:
            relative = normalize_workspace_relative_path(
                artifact.get("path"), workspace=workspace, label="task.input_artifact"
            )
            path = workspace / relative
            if not path.is_file() or path.is_symlink():
                reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:input_hash:{relative}")
            elif artifact.get("hash_kind") == "json_content":
                snapshot = read_workspace_json(workspace, relative)
                snapshot_reasons = validate_content_hash(
                    snapshot,
                    hash_field="snapshot_sha256",
                    label="snapshot",
                )
                if (
                    snapshot.get("contract_version") != INPUT_SNAPSHOT_CONTRACT_VERSION
                    or snapshot.get("snapshot_sha256") != artifact.get("sha256")
                    or snapshot_reasons
                ):
                    reasons.append(
                        f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:input_hash:{relative}"
                    )
            elif sha256_file(path) != artifact.get("sha256"):
                reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{expected_path}:input_hash:{relative}")
        except ResearchOrganizationError as exc:
            reasons.append(str(exc))
    return reasons


def validate_research_organization_bundle(
    *,
    workspace: Path,
    require_results: bool = False,
    review_trust_root: Path | None = None,
    review_installation_id: str | None = None,
) -> dict[str, Any]:
    resolved, manifest = _load_valid_workspace(workspace)
    plan_path = resolved / PLAN_RELATIVE_PATH
    if not plan_path.is_file() or plan_path.is_symlink():
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PLAN_MISSING, [PLAN_RELATIVE_PATH])
    plan = read_workspace_json(resolved, PLAN_RELATIVE_PATH)
    expected_identity = {
        "factor_id": str(manifest.get("factor_id") or ""),
        "research_id": str(manifest.get("research_id") or ""),
        "report_id": str(plan.get("identity", {}).get("report_id") or ""),
        "job_id": str(plan.get("identity", {}).get("job_id") or ""),
    }
    reasons = validate_research_organization_plan(
        plan,
        workspace=resolved,
        expected_identity=expected_identity,
    )
    review_trust_store: Any | None = None
    if (review_trust_root is None) is not (review_installation_id is None):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_review_trust_binding"
        )
    elif review_trust_root is not None and review_installation_id is not None:
        try:
            from factor_factory.research_org.runtime_trust import (
                load_runtime_trust_store,
            )

            review_trust_store = load_runtime_trust_store(
                Path(review_trust_root),
                installation_id=review_installation_id,
            )
        except (OSError, ResearchOrganizationError) as exc:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_review_trust:{exc}"
            )
    input_root_relative = (
        f"objects/research_organization/{expected_identity['report_id']}/inputs"
    )
    snapshot_specs = {
        f"{input_root_relative}/web_research_request.json": (
            "host_request_payload",
            "json_content",
        ),
        f"{input_root_relative}/web_research_authoring_contract.json": (
            "identity/web_research_authoring_contract.json",
            "file_bytes",
        ),
        f"{input_root_relative}/factor_knowledge_summary.json": (
            "identity/factor_knowledge_summary.json",
            "file_bytes",
        ),
        f"{input_root_relative}/data_catalog_summary.json": (
            "identity/data_catalog_summary.json",
            "file_bytes",
        ),
        f"{input_root_relative}/uploaded_source_report_manifest.json": (
            "identity/uploaded_source_report_manifest.json",
            "file_bytes",
        ),
    }
    input_snapshot_refs = (
        plan.get("input_snapshot_refs")
        if isinstance(plan.get("input_snapshot_refs"), list)
        else []
    )
    referenced_snapshot_paths = [
        str(reference.get("path") or "")
        for reference in input_snapshot_refs
        if isinstance(reference, dict)
    ]
    expected_reference_order = [
        relative for relative in snapshot_specs if relative in referenced_snapshot_paths
    ]
    request_snapshot_relative = next(iter(snapshot_specs))
    if (
        referenced_snapshot_paths != expected_reference_order
        or request_snapshot_relative not in referenced_snapshot_paths
    ):
        reasons.append(f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:input_snapshot_paths")
    snapshots: dict[str, dict[str, Any]] = {}
    for reference in input_snapshot_refs:
        if not isinstance(reference, dict):
            continue
        relative = str(reference.get("path") or "")
        spec = snapshot_specs.get(relative)
        if spec is None:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:unexpected_input_snapshot:{relative}"
            )
            continue
        try:
            snapshot = read_workspace_json(resolved, relative)
        except ResearchOrganizationError as exc:
            reasons.append(str(exc))
            continue
        snapshots[relative] = snapshot
        source_path, source_hash_kind = spec
        if (
            snapshot.get("contract_version") != INPUT_SNAPSHOT_CONTRACT_VERSION
            or snapshot.get("source_path") != source_path
            or snapshot.get("source_hash_kind") != source_hash_kind
            or not isinstance(snapshot.get("source_sha256"), str)
            or not SHA256_RE.fullmatch(str(snapshot.get("source_sha256") or ""))
            or not isinstance(snapshot.get("captured_payload"), dict)
            or snapshot.get("snapshot_sha256") != reference.get("sha256")
            or validate_content_hash(
                snapshot,
                hash_field="snapshot_sha256",
                label="snapshot",
            )
        ):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:input_snapshot:{relative}"
            )
    try:
        normalize_workspace_relative_path(
            input_root_relative,
            workspace=resolved,
            label="organization.input_root",
            allow_directory=True,
        )
        input_root = resolved / input_root_relative
        actual_snapshot_paths = sorted(
            path.relative_to(resolved).as_posix()
            for path in input_root.iterdir()
        )
        if sorted(referenced_snapshot_paths) != actual_snapshot_paths:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:input_snapshot_directory"
            )
    except (OSError, ResearchOrganizationError) as exc:
        reasons.append(str(exc))
    memory_binding = plan.get("researcher_memory")
    memory_snapshot_root = (
        f"objects/research_organization/{expected_identity['report_id']}"
        "/memory_snapshots"
    )
    if isinstance(memory_binding, Mapping):
        from factor_factory.researcher_memory import validate_role_memory_snapshot

        memory_refs = memory_binding.get("role_snapshot_refs")
        if not isinstance(memory_refs, Mapping):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:researcher_memory_refs"
            )
            memory_refs = {}
        expected_memory_paths = {
            str(reference.get("path") or "")
            for reference in memory_refs.values()
            if isinstance(reference, Mapping)
        }
        memory_entries, memory_entry_reasons = _ordinary_directory_entries(
            workspace=resolved,
            relative_root=memory_snapshot_root,
            label="organization.memory_snapshot_root",
            required=True,
        )
        reasons.extend(memory_entry_reasons)
        if set(memory_entries) != expected_memory_paths:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:researcher_memory_directory"
            )
        for role_id, reference in memory_refs.items():
            if not isinstance(reference, Mapping):
                continue
            relative = str(reference.get("path") or "")
            try:
                snapshot = read_workspace_json(resolved, relative)
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
                continue
            reasons.extend(
                validate_role_memory_snapshot(
                    snapshot,
                    expected_identity=expected_identity,
                    expected_role_id=str(role_id),
                )
            )
            if (
                snapshot.get("snapshot_sha256") != reference.get("sha256")
                or snapshot.get("store_id") != memory_binding.get("store_id")
                or snapshot.get("source_generation")
                != memory_binding.get("source_generation")
                or snapshot.get("source_manifest_sha256")
                != memory_binding.get("source_manifest_sha256")
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:researcher_memory_binding:{role_id}"
                )
    else:
        memory_root_path = resolved / memory_snapshot_root
        if memory_root_path.exists() or memory_root_path.is_symlink():
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_PLAN_INVALID}:unexpected_researcher_memory_directory"
            )
    request_snapshot = snapshots.get(request_snapshot_relative, {})
    captured_request = request_snapshot.get("captured_payload")
    if (
        request_snapshot.get("contract_version") != INPUT_SNAPSHOT_CONTRACT_VERSION
        or request_snapshot.get("source_path") != "host_request_payload"
        or request_snapshot.get("source_hash_kind") != "json_content"
        or not isinstance(captured_request, dict)
        or request_snapshot.get("source_sha256")
        != stable_json_hash(captured_request or {})
        or validate_content_hash(
            request_snapshot,
            hash_field="snapshot_sha256",
            label="request_snapshot",
        )
    ):
        reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:request_snapshot")
    elif plan.get("routing") != route_research_request(captured_request):
        reasons.append(f"{BLOCK_RESEARCH_ORG_ROUTE_INVALID}:request_route_mismatch")
    if isinstance(captured_request, dict):
        for key, value in expected_identity.items():
            if str(captured_request.get(key) or "") != value:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_IDENTITY_INVALID}:request_snapshot.{key}_mismatch"
                )
    dispatch_relative = str(plan.get("workspace_policy", {}).get("dispatch_manifest_path") or "")
    try:
        dispatch = read_workspace_json(resolved, dispatch_relative)
    except ResearchOrganizationError as exc:
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PLAN_INVALID, [*reasons, str(exc)]) from exc
    if dispatch.get("contract_version") != DISPATCH_MANIFEST_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.contract_version")
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{reason}"
        for reason in validate_content_hash(dispatch, hash_field="dispatch_sha256", label="dispatch")
    )
    if dispatch.get("plan_ref") != {"path": PLAN_RELATIVE_PATH, "sha256": plan.get("plan_sha256")}:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.plan_ref")
    if dispatch.get("identity") != plan.get("identity"):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.identity")
    if dispatch.get("state") != plan.get("state"):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.state")
    if dispatch.get("dispatch_policy") != {
        "independent_sessions_for_non_host_roles": True,
        "parallelize_ready_tasks": True,
        "host_validates_before_merge": True,
        "do_not_create_user_visible_threads": True,
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.policy")
    task_count = 0
    task_results: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    seen_task_ids: set[str] = set()
    seen_role_ids: set[str] = set()
    expected_role_ids = list((plan.get("role_plan") or {}).get("required_roles") or [])
    references = dispatch.get("tasks") or []
    if not isinstance(references, list) or len(references) != len(expected_role_ids):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.task_count")
        references = references if isinstance(references, list) else []
    expected_task_paths = sorted(
        str(reference.get("path") or "")
        for reference in references
        if isinstance(reference, dict)
    )
    task_entries, task_directory_reasons = _ordinary_directory_entries(
        workspace=resolved,
        relative_root=str(plan.get("workspace_policy", {}).get("task_root") or ""),
        label="organization.task_root",
        required=True,
    )
    reasons.extend(task_directory_reasons)
    if task_entries != expected_task_paths:
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:task_directory")
    expected_result_paths = {
        f"objects/research_organization/{plan['identity']['report_id']}/results/{role_id}.json"
        for role_id in expected_role_ids
    }
    result_entries, result_directory_reasons = _ordinary_directory_entries(
        workspace=resolved,
        relative_root=str(plan.get("workspace_policy", {}).get("result_root") or ""),
        label="organization.result_root",
        required=False,
    )
    reasons.extend(result_directory_reasons)
    unexpected_results = sorted(set(result_entries) - expected_result_paths)
    if unexpected_results:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:result_directory:"
            + ",".join(unexpected_results)
        )
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.task_ref")
            continue
        relative = str(reference.get("path") or "")
        task_id = str(reference.get("task_id") or "")
        role_id = str(reference.get("role_id") or "")
        expected_role_id = (
            str(expected_role_ids[index]) if index < len(expected_role_ids) else ""
        )
        expected_task_id = f"task_{index + 1:02d}_{expected_role_id}"
        expected_relative = (
            f"objects/research_organization/{plan['identity']['report_id']}"
            f"/tasks/{expected_task_id}.json"
        )
        if (
            task_id in seen_task_ids
            or role_id in seen_role_ids
            or role_id != expected_role_id
            or task_id != expected_task_id
            or relative != expected_relative
        ):
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.task_identity")
        seen_task_ids.add(task_id)
        seen_role_ids.add(role_id)
        try:
            task = read_workspace_json(resolved, relative)
        except ResearchOrganizationError as exc:
            reasons.append(str(exc))
            continue
        task_count += 1
        reasons.extend(_validate_task(task, plan=plan, workspace=resolved, expected_path=relative))
        if task.get("task_sha256") != reference.get("sha256"):
            reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{relative}:dispatch_hash")
        for key in ("task_id", "role_id", "phase", "status", "expected_result_path"):
            if reference.get(key) != task.get(key):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:{relative}:dispatch_{key}"
                )
        result_path = str(task.get("expected_result_path") or "")
        path = resolved / result_path
        if path.is_file() and not path.is_symlink():
            result = read_workspace_json(resolved, result_path)
            task_results.append((task, result))
        else:
            task_results.append((task, None))
        if require_results and not (path.is_file() and not path.is_symlink()):
            reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:missing:{result_path}")
    if seen_role_ids != set(expected_role_ids):
        reasons.append(f"{BLOCK_RESEARCH_ORG_TASK_INVALID}:dispatch.role_coverage")
    result_count = sum(result is not None for _task, result in task_results)
    tasks_by_role: dict[str, Mapping[str, Any]] = {}
    for task, _result in task_results:
        task_role_id = task.get("role_id")
        if isinstance(task_role_id, str) and task_role_id:
            tasks_by_role[task_role_id] = task
    for task, result in task_results:
        if result is None:
            continue
        peer_session_ids = [
            str(peer_result.get("session_id") or "")
            for peer_task, peer_result in task_results
            if peer_result is not None and peer_task.get("role_id") != task.get("role_id")
        ]
        reasons.extend(
            validate_agent_result(
                result,
                task=task,
                workspace=resolved,
                peer_session_ids=peer_session_ids,
                tasks_by_role=tasks_by_role,
            )
        )
    candidate_root_relative = (
        f"objects/research_organization/{expected_identity['report_id']}"
        "/memory_candidates"
    )
    candidate_root = resolved / candidate_root_relative
    candidate_payloads_by_path: dict[str, Mapping[str, Any]] = {}
    if plan.get("researcher_memory") is None:
        if candidate_root.exists() or candidate_root.is_symlink():
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:unexpected_memory_candidates"
            )
    else:
        from factor_factory.researcher_memory import validate_memory_candidate

        candidate_entries, candidate_entry_reasons = _ordinary_directory_entries(
            workspace=resolved,
            relative_root=candidate_root_relative,
            label="organization.memory_candidate_root",
            required=False,
        )
        reasons.extend(candidate_entry_reasons)
        results_by_role = {
            str(task.get("role_id")): result
            for task, result in task_results
            if result is not None
        }
        for relative in candidate_entries:
            try:
                candidate = read_workspace_json(resolved, relative)
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
                continue
            role_id = str(candidate.get("source_role_id") or "")
            task = tasks_by_role.get(role_id)
            result = results_by_role.get(role_id)
            if task is None or result is None:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_candidate_source:{relative}"
                )
                continue
            expected_name = f"{role_id}__{candidate.get('candidate_id')}.json"
            if Path(relative).name != expected_name:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_candidate_name:{relative}"
                )
            reasons.extend(
                validate_memory_candidate(
                    candidate,
                    task=task,
                    result=result,
                    trust_store=review_trust_store,
                )
            )
            candidate_payloads_by_path[relative] = candidate
    review_root_relative = (
        f"objects/research_organization/{expected_identity['report_id']}"
        "/memory_reviews"
    )
    review_root = resolved / review_root_relative
    if plan.get("researcher_memory") is None:
        if review_root.exists() or review_root.is_symlink():
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:unexpected_memory_reviews"
            )
    else:
        from factor_factory.researcher_memory import validate_candidate_review

        review_entries, review_entry_reasons = _ordinary_directory_entries(
            workspace=resolved,
            relative_root=review_root_relative,
            label="organization.memory_review_root",
            required=False,
        )
        reasons.extend(review_entry_reasons)
        if review_entries and review_trust_store is None:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_review_trust_required"
            )
        for relative in review_entries:
            try:
                review = read_workspace_json(resolved, relative)
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
                continue
            candidate_ref = review.get("candidate_ref")
            candidate_path = (
                str(candidate_ref.get("path") or "")
                if isinstance(candidate_ref, Mapping)
                else ""
            )
            candidate = candidate_payloads_by_path.get(candidate_path)
            if candidate is None:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_review_candidate:{relative}"
                )
                continue
            if Path(relative).name != f"{review.get('review_id')}.json":
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:memory_review_name:{relative}"
                )
            reasons.extend(
                validate_candidate_review(
                    review,
                    candidate=candidate,
                    trust_store=review_trust_store,
                )
            )
    if reasons:
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PLAN_INVALID, reasons)
    result_statuses = {
        str(task.get("role_id")): str(result.get("status"))
        for task, result in task_results
        if result is not None
    }
    if any(status == "NEEDS_DATA" for status in result_statuses.values()):
        execution_state = "WAITING_DATA"
    elif any(status == "NEEDS_CLARIFICATION" for status in result_statuses.values()):
        execution_state = "NEEDS_CLARIFICATION"
    elif any(status == "BLOCK" for status in result_statuses.values()):
        execution_state = "BLOCKED"
    elif result_count == task_count and task_count:
        execution_state = "COMPLETE"
    elif result_count:
        execution_state = "IN_PROGRESS"
    else:
        execution_state = "DISPATCH_CONTRACT_GENERATED"
    council_result = next(
        (
            result
            for task, result in task_results
            if task.get("role_id") == "independent_council" and result is not None
        ),
        None,
    )
    council_independence_attestation_valid = bool(
        execution_state == "COMPLETE"
        and council_result
        and council_result.get("producer_mode") == "real_agent"
        and (council_result.get("independence_attestation") or {}).get(
            "independence_satisfied"
        )
        is True
    )
    return {
        "verdict": "PASS",
        "plan_path": str(plan_path),
        "plan_sha256": plan["plan_sha256"],
        "state": plan["state"],
        "lead_domain": plan["routing"].get("lead_domain"),
        "supporting_domains": plan["routing"].get("supporting_domains") or [],
        "task_count": task_count,
        "result_count": result_count,
        "execution_state": execution_state,
        "result_statuses": result_statuses,
        "council_independence_attestation_valid": (
            council_independence_attestation_valid
        ),
        "independence_satisfied": False,
        "independence_authority": "signed_runtime_ledger_required",
        "single_agent_fallback": plan["execution_policy"]["single_agent_fallback"],
    }


def _nonempty_public_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _contains_realized_outcome_claim(value: str) -> bool:
    normalized = " ".join(value.split())
    if _EMPIRICAL_DISPOSITION_RE.search(normalized):
        return True
    realized_context = _REALIZED_EVIDENCE_RE.search(normalized) is not None
    realized_assertion = _REALIZED_ASSERTION_RE.search(normalized) is not None
    metric_value = _EMPIRICAL_METRIC_VALUE_RE.search(normalized) is not None
    return bool(
        _EMPIRICAL_VALUE_CLAIM_RE.search(normalized)
        or (realized_context and (realized_assertion or metric_value))
        or (realized_assertion and metric_value)
    )


def _empirical_claim_reasons(value: Any, *, path: str = "public_research_record") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _EMPIRICAL_CLAIM_KEY_RE.fullmatch(key_text):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:empirical_claim_key:{child_path}"
                )
            reasons.extend(_empirical_claim_reasons(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reasons.extend(
                _empirical_claim_reasons(item, path=f"{path}[{index}]")
            )
    elif isinstance(value, str) and _contains_realized_outcome_claim(value):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:empirical_claim:{path}"
        )
    return reasons


def _task_knowledge_snapshot(
    *,
    task: Mapping[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    references = [
        item
        for item in task.get("input_artifacts") or []
        if isinstance(item, Mapping)
        and str(item.get("path") or "").endswith(
            "/factor_knowledge_summary.json"
        )
    ]
    if len(references) != 1:
        return None, None, ["knowledge_prior_record.source_ref_count"]
    reference = dict(references[0])
    try:
        relative = normalize_workspace_relative_path(
            reference.get("path"),
            workspace=workspace,
            label="knowledge_librarian.source",
        )
        snapshot = read_workspace_json(workspace, relative)
    except ResearchOrganizationError as exc:
        return reference, None, [str(exc)]
    if (
        snapshot.get("contract_version") != INPUT_SNAPSHOT_CONTRACT_VERSION
        or snapshot.get("snapshot_sha256") != reference.get("sha256")
        or validate_content_hash(
            snapshot,
            hash_field="snapshot_sha256",
            label="knowledge_librarian.snapshot",
        )
        or not isinstance(snapshot.get("captured_payload"), Mapping)
    ):
        return reference, None, ["knowledge_prior_record.source_binding"]
    return reference, dict(snapshot["captured_payload"]), []


def _knowledge_source_text(
    node: Mapping[str, Any],
    source_path: Any,
) -> str | None:
    if (
        not isinstance(source_path, list)
        or not 1 <= len(source_path) <= 5
        or source_path[0]
        not in {
            "title",
            "summary",
            "mechanism",
            "evidence",
            "reuse_guidance",
            "research_status",
        }
    ):
        return None
    current: Any = node
    for segment in source_path:
        if isinstance(current, Mapping):
            if not isinstance(segment, str) or segment not in current:
                return None
            current = current[segment]
        elif isinstance(current, list):
            if (
                type(segment) is not int
                or segment < 0
                or segment >= len(current)
            ):
                return None
            current = current[segment]
        else:
            return None
    return str(current) if _nonempty_public_text(current) else None


def _knowledge_librarian_record_reasons(
    *,
    record: Mapping[str, Any],
    task: Mapping[str, Any],
    workspace: Path,
) -> list[str]:
    reasons: list[str] = []
    expected_record_keys = {
        "contract_version",
        "executive_summary",
        "knowledge_prior_contract",
        "retrieval_provenance",
        "claims",
        "historical_metrics",
        "artifact_refs",
        "handoff",
    }
    if set(record) != expected_record_keys:
        reasons.append("knowledge_prior_record.shape")
    if record.get("executive_summary") != KNOWLEDGE_PRIOR_EXECUTIVE_SUMMARY:
        reasons.append("knowledge_prior_record.executive_summary")

    reference, summary, snapshot_reasons = _task_knowledge_snapshot(
        task=task,
        workspace=workspace,
    )
    reasons.extend(snapshot_reasons)
    expected_source_ref: dict[str, str] | None = None
    if reference is not None:
        relative = str(reference.get("path") or "")
        source_path = workspace / relative
        if source_path.is_file() and not source_path.is_symlink():
            expected_source_ref = {
                "path": relative,
                "sha256": sha256_file(source_path),
            }
    if expected_source_ref is None or record.get("artifact_refs") != [
        expected_source_ref
    ]:
        reasons.append("knowledge_prior_record.artifact_refs")

    if record.get("knowledge_prior_contract") != {
        "contract_version": KNOWLEDGE_PRIOR_CONTRACT_VERSION,
        "authority": "historical_advisory_only",
        "current_factor_empirical_verdict": "NOT_ISSUED",
        "current_factor_performance_inference_allowed": False,
        "historical_metrics_subject": "prior_artifacts_only",
    }:
        reasons.append("knowledge_prior_record.authority")

    node_map: dict[str, dict[str, Any]] = {}
    expected_query_hash = ""
    expected_top_k: int | None = None
    if summary is None:
        reasons.append("knowledge_prior_record.source_payload")
    else:
        if (
            summary.get("version") != "factorforge_web_knowledge_summary_v1"
            or summary.get("schema_version") != "factor_knowledge_context_v1"
            or not isinstance(summary.get("retrieval_provenance"), Mapping)
            or not isinstance(summary.get("nodes"), list)
        ):
            reasons.append("knowledge_prior_record.source_payload")
        source_provenance = summary.get("retrieval_provenance")
        if isinstance(source_provenance, Mapping):
            query = source_provenance.get("query")
            query_hash = source_provenance.get("query_hash")
            if (
                not isinstance(query_hash, str)
                or not SHA256_RE.fullmatch(query_hash)
            ):
                reasons.append("knowledge_prior_record.source_payload")
            else:
                expected_query_hash = query_hash
            if (
                not isinstance(query, Mapping)
                or type(query.get("top_k")) is not int
                or query["top_k"] <= 0
            ):
                reasons.append("knowledge_prior_record.source_payload")
            else:
                expected_top_k = int(query["top_k"])
        for node in summary.get("nodes") or []:
            if not isinstance(node, Mapping) or not _nonempty_public_text(
                node.get("id")
            ):
                reasons.append("knowledge_prior_record.source_node")
                continue
            node_id = str(node["id"])
            if node_id in node_map:
                reasons.append("knowledge_prior_record.source_node_duplicate")
                continue
            node_map[node_id] = dict(node)
        if (
            type(summary.get("node_count")) is not int
            or summary.get("node_count") != len(node_map)
        ):
            reasons.append("knowledge_prior_record.source_node_count")

    expected_node_ids = list(node_map)
    expected_cold_start = not expected_node_ids
    provenance = record.get("retrieval_provenance")
    expected_provenance = {
        "contract_version": KNOWLEDGE_RETRIEVAL_PROVENANCE_CONTRACT_VERSION,
        "source_artifact_ref": expected_source_ref,
        "cold_start": expected_cold_start,
        "query_hash": expected_query_hash,
        "top_k": expected_top_k,
        "hit_count": len(expected_node_ids),
        "retrieved_node_ids": expected_node_ids,
    }
    if provenance != expected_provenance:
        reasons.append("knowledge_prior_record.retrieval_provenance")

    claims = record.get("claims")
    if not isinstance(claims, list) or (expected_node_ids and not claims):
        reasons.append("knowledge_prior_record.claims")
        claims = []
    seen_claim_bindings: set[tuple[str, str, str]] = set()
    expected_claim_keys = {
        "claim_type",
        "source_node_id",
        "source_path",
        "source_text",
        "source_text_sha256",
        "applicability_to_current_factor",
        "current_factor_inference_allowed",
        "evidence_ref",
    }
    for index, claim in enumerate(claims):
        label = f"knowledge_prior_record.claims[{index}]"
        if not isinstance(claim, Mapping) or set(claim) != expected_claim_keys:
            reasons.append(f"{label}.shape")
            continue
        if claim.get("claim_type") not in KNOWLEDGE_PRIOR_CLAIM_TYPES:
            reasons.append(f"{label}.claim_type")
        source_node_id = str(claim.get("source_node_id") or "")
        claim_binding = (
            str(claim.get("claim_type") or ""),
            source_node_id,
            json.dumps(
                claim.get("source_path"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if claim_binding in seen_claim_bindings:
            reasons.append(f"{label}.duplicate_binding")
        else:
            seen_claim_bindings.add(claim_binding)
        node = node_map.get(source_node_id)
        source_text = (
            _knowledge_source_text(node, claim.get("source_path"))
            if node is not None
            else None
        )
        if node is None:
            reasons.append(f"{label}.source_node_id")
        if source_text is None or claim.get("source_text") != source_text:
            reasons.append(f"{label}.source_text")
        expected_text_hash = (
            hashlib.sha256(source_text.encode("utf-8")).hexdigest()
            if source_text is not None
            else None
        )
        if claim.get("source_text_sha256") != expected_text_hash:
            reasons.append(f"{label}.source_text_sha256")
        if claim.get("applicability_to_current_factor") != "advisory_only":
            reasons.append(f"{label}.applicability_to_current_factor")
        if claim.get("current_factor_inference_allowed") is not False:
            reasons.append(f"{label}.current_factor_inference_allowed")
        if (
            expected_source_ref is None
            or claim.get("evidence_ref") != expected_source_ref["path"]
        ):
            reasons.append(f"{label}.evidence_ref")

    historical_metrics = record.get("historical_metrics")
    if not isinstance(historical_metrics, list):
        reasons.append("knowledge_prior_record.historical_metrics")
        historical_metrics = []
    expected_metric_keys = {
        "source_node_id",
        "source_path",
        "metric_value",
        "source_subject",
        "evidence_ref",
        "current_factor_inference_allowed",
    }
    for index, metric in enumerate(historical_metrics):
        label = f"knowledge_prior_record.historical_metrics[{index}]"
        if not isinstance(metric, Mapping) or set(metric) != expected_metric_keys:
            reasons.append(f"{label}.shape")
            continue
        source_node_id = str(metric.get("source_node_id") or "")
        node = node_map.get(source_node_id)
        source_path = metric.get("source_path")
        source_value: Any = None
        if (
            node is not None
            and isinstance(source_path, list)
            and len(source_path) == 3
            and source_path[:2] == ["evidence", "key_metrics"]
            and isinstance(source_path[2], str)
        ):
            evidence = node.get("evidence")
            key_metrics = (
                evidence.get("key_metrics")
                if isinstance(evidence, Mapping)
                else None
            )
            if isinstance(key_metrics, Mapping):
                source_value = key_metrics.get(source_path[2])
        if (
            isinstance(source_value, bool)
            or not isinstance(source_value, (int, float))
            or not math.isfinite(float(source_value))
            or metric.get("metric_value") != source_value
        ):
            reasons.append(f"{label}.source_binding")
        if metric.get("source_subject") != "prior_artifact":
            reasons.append(f"{label}.source_subject")
        if (
            expected_source_ref is None
            or metric.get("evidence_ref") != expected_source_ref["path"]
        ):
            reasons.append(f"{label}.evidence_ref")
        if metric.get("current_factor_inference_allowed") is not False:
            reasons.append(f"{label}.current_factor_inference_allowed")

    if record.get("handoff") != {
        "status": "ready_for_host_review",
        "authority": "advisory_only",
        "estimand_selected": False,
        "current_factor_empirical_verdict": "NOT_ISSUED",
    }:
        reasons.append("knowledge_prior_record.handoff")
    return reasons


def _preformal_allowed_evidence_paths(
    task: Mapping[str, Any],
    *,
    workspace: Path,
    staged_context_files: Iterable[Mapping[str, Any]] | None = None,
    tasks_by_role: Mapping[str, Mapping[str, Any]] | None = None,
) -> set[str]:
    staged_hashes: dict[str, str] | None = None
    if staged_context_files is not None:
        staged_hashes = {
            str(item.get("path") or ""): str(item.get("sha256") or "")
            for item in staged_context_files
            if isinstance(item, Mapping)
            and _nonempty_public_text(item.get("path"))
            and SHA256_RE.fullmatch(str(item.get("sha256") or ""))
        }

    def staged(path: str, *, sha256: str | None = None) -> bool:
        if staged_hashes is None:
            return True
        observed = staged_hashes.get(path)
        return observed is not None and (sha256 is None or observed == sha256)

    allowed = {
        str(item.get("path") or "")
        for item in task.get("input_artifacts") or []
        if isinstance(item, Mapping) and _nonempty_public_text(item.get("path"))
        and staged(str(item.get("path") or ""))
    }
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    report_id = str(identity.get("report_id") or "")
    task_id = str(task.get("task_id") or "")
    if report_id and task_id:
        task_relative = (
            f"objects/research_organization/{report_id}/tasks/{task_id}.json"
        )
        if staged(task_relative):
            allowed.add(task_relative)
    for role_id in transitive_dependency_roles(
        task=task,
        tasks_by_role=tasks_by_role or {},
    ):
        if role_id:
            result_relative = (
                f"objects/research_organization/{report_id}/results/{role_id}.json"
            )
            result_path = workspace / result_relative
            if not result_path.is_file() or result_path.is_symlink():
                continue
            try:
                dependency_result = read_workspace_json(workspace, result_relative)
            except ResearchOrganizationError:
                continue
            if (
                dependency_result.get("role_id") != role_id
                or dependency_result.get("status") != "PASS"
                or validate_content_hash(
                    dependency_result,
                    hash_field="result_sha256",
                    label="dependency_result",
                )
            ):
                continue
            if staged(result_relative, sha256=sha256_file(result_path)):
                allowed.add(result_relative)
            record = dependency_result.get("public_research_record")
            if not isinstance(record, Mapping):
                continue
            references: list[Any] = list(record.get("artifact_refs") or [])
            catalog_resolution = record.get("catalog_resolution")
            if isinstance(catalog_resolution, Mapping):
                references.extend(
                    catalog_resolution.get("generated_data_requests") or []
                )
            for reference in references:
                if (
                    not isinstance(reference, Mapping)
                    or set(reference) != {"path", "sha256"}
                    or not SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
                ):
                    continue
                try:
                    relative = normalize_workspace_relative_path(
                        reference.get("path"),
                        workspace=workspace,
                        label="dependency_artifact_ref",
                    )
                except ResearchOrganizationError:
                    continue
                path = workspace / relative
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and sha256_file(path) == reference.get("sha256")
                    and staged(relative, sha256=str(reference.get("sha256")))
                ):
                    allowed.add(relative)
    return allowed


def _validate_preformal_typed_claims(
    *,
    record: Mapping[str, Any],
    task: Mapping[str, Any],
    checks: list[Mapping[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    claims = record.get("claims")
    if not isinstance(claims, list) or not claims:
        return [f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:typed_claims"]
    if claims != checks:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:typed_claims.controlled_check_binding"
        )
    return reasons


def _validate_preformal_design_review(
    *,
    result: Mapping[str, Any],
    record: Mapping[str, Any],
    task: Mapping[str, Any],
    workspace: Path,
    staged_context_files: Iterable[Mapping[str, Any]] | None = None,
    tasks_by_role: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    role_id = str(task.get("role_id") or "")
    expected_check_ids = PREFORMAL_ROLE_CHECK_IDS.get(role_id)
    if expected_check_ids is None:
        return []
    reasons: list[str] = []
    if set(record) != {
        "contract_version",
        "executive_summary",
        "claims",
        "artifact_refs",
        "handoff",
        "design_review",
    }:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:preformal_record.shape"
        )
    handoff = record.get("handoff")
    if handoff != {"status": "ready_for_host_review"}:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:preformal_handoff.shape"
        )
    review = record.get("design_review")
    if not isinstance(review, Mapping):
        return [
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.design_review"
        ]
    if review.get("contract_version") != PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.contract_version"
        )
    if review.get("stage") != "pre_formal_research_design":
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.stage")
    if review.get("evidence_basis") != "pre_registered_design_only":
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.evidence_basis"
        )
    if review.get("empirical_factor_verdict") != "NOT_ISSUED":
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.empirical_factor_verdict"
        )
    if set(review) != {
        "contract_version",
        "stage",
        "evidence_basis",
        "claim_scope",
        "empirical_factor_verdict",
        "decision",
        "checks",
        "blockers",
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.shape")
    if review.get("claim_scope") != PREFORMAL_CLAIM_SCOPE:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.claim_scope")
    checks = review.get("checks")
    if not isinstance(checks, list):
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.checks")
        checks = []
    observed_ids: list[str] = []
    observed_statuses: list[str] = []
    controlled_checks: list[Mapping[str, Any]] = []
    allowed_paths = _preformal_allowed_evidence_paths(
        task,
        workspace=workspace,
        staged_context_files=staged_context_files,
        tasks_by_role=tasks_by_role,
    )
    artifact_paths = {
        str(item.get("path") or "")
        for item in record.get("artifact_refs") or []
        if isinstance(item, Mapping)
    }
    for index, check in enumerate(checks):
        if not isinstance(check, Mapping):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.checks[{index}]"
            )
            continue
        if set(check) != {
            "check_id",
            "claim_type",
            "status",
            "finding_code",
            "falsifier_code",
            "evidence_refs",
        }:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.check_shape:{index}"
            )
        check_id = str(check.get("check_id") or "")
        observed_ids.append(check_id)
        status = str(check.get("status") or "")
        observed_statuses.append(status)
        if status not in {"PASS", "BLOCK"}:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.check_status:{check_id}"
            )
        if check.get("claim_type") != "DESIGN_REQUIREMENT":
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.claim_type:{check_id}"
            )
        if check.get("finding_code") != PREFORMAL_FINDING_CODES.get(status):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.finding_code:{check_id}"
            )
        if check.get("falsifier_code") != PREFORMAL_FALSIFIER_CODES.get(check_id):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.falsifier_code:{check_id}"
            )
        evidence_refs = check.get("evidence_refs")
        if (
            not isinstance(evidence_refs, list)
            or (status == "PASS" and not evidence_refs)
            or any(
                not isinstance(item, str)
                or not item
                or item not in allowed_paths
                or item not in artifact_paths
                for item in evidence_refs or []
            )
        ):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.evidence_scope:{check_id}"
            )
        controlled_checks.append(check)
    if observed_ids != list(expected_check_ids):
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.check_ids")
    blockers = review.get("blockers")
    expected_blockers = [
        check_id
        for check_id, status in zip(observed_ids, observed_statuses, strict=False)
        if status == "BLOCK"
    ]
    if blockers != expected_blockers:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.blockers")
        blockers = blockers if isinstance(blockers, list) else []
    clear = bool(
        observed_ids == list(expected_check_ids)
        and observed_statuses
        and all(status == "PASS" for status in observed_statuses)
        and not blockers
    )
    expected_decision = (
        PREFORMAL_CLEAR_DECISION if clear else PREFORMAL_BLOCK_DECISION
    )
    if review.get("decision") != expected_decision:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.decision")
    if record.get("executive_summary") != PREFORMAL_EXECUTIVE_SUMMARIES.get(
        expected_decision
    ):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:preformal_record.executive_summary"
        )
    expected_status = "PASS" if clear else "BLOCK"
    if result.get("status") != expected_status:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:design_review.status_mapping"
        )
    reasons.extend(
        _validate_preformal_typed_claims(
            record=record,
            task=task,
            checks=controlled_checks,
        )
    )
    if role_id == "independent_council":
        verdict = result.get("formal_independent_verdict")
        if not isinstance(verdict, Mapping):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict"
            )
        else:
            if (
                verdict.get("contract_version")
                != PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.contract_version"
                )
            if verdict.get("stage") != "pre_formal_research_design":
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.stage"
                )
            if verdict.get("decision") != expected_decision:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.decision"
                )
            if verdict.get("reviewed_role_ids") != task.get(
                "required_review_role_ids"
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.reviewed_roles"
                )
            if verdict.get("blocking_findings") != blockers:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.blockers"
                )
            if verdict.get("empirical_factor_verdict") != "NOT_ISSUED":
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.empirical_factor_verdict"
                )
            if set(verdict) != {
                "contract_version",
                "stage",
                "claim_scope",
                "decision",
                "reviewed_role_ids",
                "blocking_findings",
                "empirical_factor_verdict",
            }:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.shape"
                )
            if verdict.get("claim_scope") != PREFORMAL_CLAIM_SCOPE:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:formal_verdict.claim_scope"
                )
            reasons.extend(
                _empirical_claim_reasons(
                    verdict,
                    path="formal_independent_verdict",
                )
            )
    elif result.get("formal_independent_verdict") is not None:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:unexpected_formal_verdict"
        )
    return reasons


def _validate_director_synthesis(
    *,
    result: Mapping[str, Any],
    record: Mapping[str, Any],
    task: Mapping[str, Any],
    workspace: Path,
) -> list[str]:
    if task.get("role_id") != "research_director":
        return []
    reasons: list[str] = []
    synthesis = record.get("director_synthesis")
    if not isinstance(synthesis, Mapping):
        return [
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.director_synthesis"
        ]
    if synthesis.get("contract_version") != DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.contract_version"
        )
    if synthesis.get("stage") != "pre_formal_research_design":
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.stage"
        )
    if synthesis.get("handoff_status") != "ready_for_specialist_verification":
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.handoff_status"
        )
    for field in ("mechanism_decision", "selected_measurement_object"):
        if not _nonempty_public_text(synthesis.get(field)):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.{field}"
            )
    for field in ("rejected_alternatives", "falsifiers"):
        values = synthesis.get(field)
        if not isinstance(values, list) or not values or any(
            not _nonempty_public_text(item) for item in values
        ):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.{field}"
            )
    unresolved = synthesis.get("unresolved_risks")
    if not isinstance(unresolved, list) or any(
        not _nonempty_public_text(item) for item in unresolved
    ):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.unresolved_risks"
        )
    expected_roles = list(task.get("depends_on_roles") or [])
    reviewed = synthesis.get("reviewed_specialist_results")
    if not isinstance(reviewed, list):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.reviewed_specialist_results"
        )
        reviewed = []
    observed_roles: list[str] = []
    report_id = str((task.get("identity") or {}).get("report_id") or "")
    for item in reviewed:
        if not isinstance(item, Mapping):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.reviewed_result_ref"
            )
            continue
        role_id = str(item.get("role_id") or "")
        observed_roles.append(role_id)
        expected_path = (
            f"objects/research_organization/{report_id}/results/{role_id}.json"
        )
        if item.get("path") != expected_path:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.reviewed_result_path:{role_id}"
            )
            continue
        path = workspace / expected_path
        if not path.is_file() or path.is_symlink():
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.reviewed_result_missing:{role_id}"
            )
            continue
        dependency_result = read_workspace_json(workspace, expected_path)
        if (
            dependency_result.get("role_id") != role_id
            or dependency_result.get("status") != "PASS"
            or dependency_result.get("result_sha256")
            != item.get("result_sha256")
        ):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.reviewed_result_binding:{role_id}"
            )
    if observed_roles != expected_roles:
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.reviewed_roles"
        )
    source_ref = synthesis.get("source_record_ref")
    artifact_refs = record.get("artifact_refs") or []
    if (
        not isinstance(source_ref, Mapping)
        or source_ref.get("path") != "identity/web_research_director_record.json"
        or not any(
            isinstance(item, Mapping)
            and item.get("path") == source_ref.get("path")
            and item.get("sha256") == source_ref.get("sha256")
            for item in artifact_refs
        )
    ):
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.source_record_ref"
        )
    if result.get("status") != "PASS":
        reasons.append(
            f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:director_synthesis.status_mapping"
        )
    return reasons


def _data_request_payload_reasons(
    payload: Any,
    *,
    task: Mapping[str, Any],
    request_id: str,
) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["request_payload_object_required"]
    reasons: list[str] = []
    if payload.get("contract_version") != DATA_REQUEST_CONTRACT_VERSION:
        reasons.append("request_payload.contract_version")
    if payload.get("request_id") != request_id:
        reasons.append("request_payload.request_id")
    for field in ("request_type", "dataset_id"):
        if not _nonempty_public_text(payload.get(field)):
            reasons.append(f"request_payload.{field}")
    required_fields = payload.get("required_fields")
    if not isinstance(required_fields, list) or not required_fields or any(
        not _nonempty_public_text(item) for item in required_fields
    ):
        reasons.append("request_payload.required_fields")
    if not isinstance(payload.get("required_coverage"), Mapping):
        reasons.append("request_payload.required_coverage")
    if not isinstance(payload.get("parameters"), Mapping):
        reasons.append("request_payload.parameters")
    if not isinstance(payload.get("lookahead_policy_required"), bool):
        reasons.append("request_payload.lookahead_policy_required")
    if "qa_required" in payload and not isinstance(payload.get("qa_required"), bool):
        reasons.append("request_payload.qa_required")
    expected_consumer = {
        "factor_id": (task.get("identity") or {}).get("factor_id"),
        "research_id": (task.get("identity") or {}).get("research_id"),
        "report_id": (task.get("identity") or {}).get("report_id"),
    }
    if payload.get("consumer") != expected_consumer:
        reasons.append("request_payload.consumer")
    if payload.get("status") != "requested":
        reasons.append("request_payload.status")
    if payload.get("production_execution_allowed") is not False:
        reasons.append("request_payload.production_execution_allowed")
    if private_reasoning_paths(payload):
        reasons.append("request_payload.private_reasoning")
    return reasons


def materialize_data_liaison_requests(
    *,
    result: Mapping[str, Any],
    task: Mapping[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Publish embedded Liaison requests through the Host, never the Agent mount."""

    candidate = copy.deepcopy(dict(result))
    if task.get("role_id") != "data_liaison":
        return candidate, ()
    hash_reasons = validate_content_hash(
        candidate,
        hash_field="result_sha256",
        label="result",
    )
    if hash_reasons:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RESULT_INVALID,
            [f"embedded_data_request:{reason}" for reason in hash_reasons],
        )
    record = candidate.get("public_research_record")
    catalog_resolution = (
        record.get("catalog_resolution")
        if isinstance(record, dict)
        else None
    )
    requests = (
        catalog_resolution.get("generated_data_requests")
        if isinstance(catalog_resolution, dict)
        else None
    )
    if not isinstance(requests, list):
        return candidate, ()
    if not any(
        isinstance(item, Mapping) and "request_payload" in item
        for item in requests
    ):
        return candidate, ()
    report_id = str((task.get("identity") or {}).get("report_id") or "")
    request_root = f"objects/research_organization/{report_id}/data_requests/"
    created: list[str] = []
    canonical_refs: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    try:
        for index, item in enumerate(requests):
            if not isinstance(item, Mapping) or set(item) != {
                "request_id",
                "path",
                "request_payload",
            }:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RESULT_INVALID,
                    [f"embedded_data_request.entry:{index}"],
                )
            request_id = str(item.get("request_id") or "")
            identity_reasons = validate_identity_value(
                request_id,
                label=f"data_request[{index}].request_id",
            )
            if identity_reasons:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RESULT_INVALID,
                    identity_reasons,
                )
            relative = normalize_workspace_relative_path(
                item.get("path"),
                workspace=workspace,
                label="embedded_data_request.path",
            )
            if (
                not relative.startswith(request_root)
                or relative != f"{request_root}{request_id}.json"
                or relative in seen_paths
                or request_id in seen_ids
            ):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RESULT_INVALID,
                    [f"embedded_data_request.path:{relative}"],
                )
            payload = copy.deepcopy(item.get("request_payload"))
            payload_reasons = _data_request_payload_reasons(
                payload,
                task=task,
                request_id=request_id,
            )
            if payload_reasons:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RESULT_INVALID,
                    [f"embedded_data_request:{reason}" for reason in payload_reasons],
                )
            path = workspace / relative
            if path.exists() or path.is_symlink():
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or stable_json_hash(read_workspace_json(workspace, relative))
                    != stable_json_hash(payload)
                ):
                    raise ResearchOrganizationError(
                        BLOCK_RESEARCH_ORG_RESULT_INVALID,
                        [f"embedded_data_request.immutable_conflict:{relative}"],
                    )
            else:
                write_workspace_json_once(workspace, relative, payload)
                created.append(relative)
            seen_paths.add(relative)
            seen_ids.add(request_id)
            canonical_refs.append(
                {
                    "request_id": request_id,
                    "path": relative,
                    "sha256": sha256_file(workspace / relative),
                }
            )
    except Exception:
        cleanup_materialized_data_requests(
            workspace=workspace,
            relative_paths=created,
        )
        raise
    assert isinstance(record, dict)
    assert isinstance(catalog_resolution, dict)
    catalog_resolution["generated_data_requests"] = canonical_refs
    candidate = with_content_hash(candidate, hash_field="result_sha256")
    return candidate, tuple(created)


def cleanup_materialized_data_requests(
    *,
    workspace: Path,
    relative_paths: Iterable[str],
) -> None:
    for value in reversed(tuple(relative_paths)):
        relative = normalize_workspace_relative_path(
            value,
            workspace=workspace,
            label="data_request_cleanup",
        )
        path = workspace / relative
        if path.is_file() and not path.is_symlink():
            path.unlink()


def _normalized_date(value: Any) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"[0-9]{8}", raw):
        candidate = raw
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        candidate = raw.replace("-", "")
    else:
        return ""
    try:
        datetime.strptime(candidate, "%Y%m%d")
    except ValueError:
        return ""
    return candidate


def _task_catalog_snapshot(
    *,
    task: Mapping[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    refs = [
        item
        for item in (task.get("input_artifacts") or [])
        if isinstance(item, Mapping)
        and str(item.get("path") or "").endswith("/data_catalog_summary.json")
    ]
    if len(refs) != 1:
        return None, None, ["catalog_snapshot_ref_count"]
    reference = dict(refs[0])
    try:
        relative = normalize_workspace_relative_path(
            reference.get("path"),
            workspace=workspace,
            label="data_liaison.catalog_snapshot",
        )
        snapshot = read_workspace_json(workspace, relative)
    except ResearchOrganizationError as exc:
        return reference, None, [str(exc)]
    if (
        snapshot.get("contract_version") != INPUT_SNAPSHOT_CONTRACT_VERSION
        or snapshot.get("snapshot_sha256") != reference.get("sha256")
        or validate_content_hash(
            snapshot,
            hash_field="snapshot_sha256",
            label="data_liaison.catalog_snapshot",
        )
        or not isinstance(snapshot.get("captured_payload"), dict)
    ):
        return reference, None, ["catalog_snapshot_binding"]
    return reference, dict(snapshot["captured_payload"]), []


def _catalog_entry_map(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for catalog in summary.get("catalogs") or []:
        if not isinstance(catalog, Mapping):
            continue
        for entry in catalog.get("entries") or []:
            if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
                entries[str(entry["name"])] = dict(entry)
    return entries


def _host_information_policy_attested(entry: Mapping[str, Any]) -> bool:
    policy = entry.get("information_policy")
    if not isinstance(policy, Mapping):
        return False
    expected = project_information_policy_attestation(
        str(entry.get("name") or ""),
        policy,
    )
    return bool(
        expected.get("verdict") == "PASS"
        and entry.get("host_information_policy_attestation") == expected
    )


def _data_liaison_preformal_pass_reasons(
    *,
    record: Mapping[str, Any],
    task: Mapping[str, Any],
    workspace: Path,
) -> list[str]:
    reference, summary, reasons = _task_catalog_snapshot(
        task=task,
        workspace=workspace,
    )
    if reasons or summary is None or reference is None:
        return reasons
    if summary.get("version") != "factorforge_web_data_catalog_summary_v2":
        legacy_resolution = record.get("catalog_resolution")
        if (
            legacy_resolution == {"reuse_hits": [], "generated_data_requests": []}
            and record.get("permissions_boundary") == {"data_materialization": False}
        ):
            return []
        return ["legacy_catalog_reuse_forbidden"]
    all_entries = _catalog_entry_map(summary)
    if not all_entries:
        legacy_no_data_resolution = record.get("catalog_resolution")
        if (
            legacy_no_data_resolution
            == {"reuse_hits": [], "generated_data_requests": []}
            and record.get("permissions_boundary") == {"data_materialization": False}
        ):
            return []
        return ["active_catalog_entries"]
    admission = summary.get("active_catalog_admission")
    if (
        not isinstance(admission, Mapping)
        or admission.get("version") != "factorforge_console_catalog_admission_v1"
        or admission.get("verdict") != "PASS"
        or admission.get("admission_scope")
        != "active_catalog_identity_freshness_and_transport"
        or admission.get("formal_dataset_qa_implied") is not False
        or SHA256_RE.fullmatch(str(admission.get("catalog_sha256") or "")) is None
        or SHA256_RE.fullmatch(
            str(admission.get("catalog_receipt_sha256") or "")
        )
        is None
    ):
        reasons.append("active_catalog_admission")
    catalogs = summary.get("catalogs")
    admission_hash = (
        str(admission.get("catalog_sha256") or "")
        if isinstance(admission, Mapping)
        else ""
    )
    bound_catalogs = [
        dict(catalog)
        for catalog in catalogs
        if isinstance(catalog, Mapping)
        and catalog.get("catalog_sha256") == admission_hash
    ] if isinstance(catalogs, list) else []
    if len(bound_catalogs) != 1:
        reasons.append("active_catalog_binding")
    entries = _catalog_entry_map({"catalogs": bound_catalogs})
    execution_stage = task.get("execution_stage_contract")
    if (
        not isinstance(execution_stage, Mapping)
        or execution_stage.get("stage") != "pre_formal_research_design"
    ):
        reasons.append("execution_stage_contract")
    resolution = record.get("catalog_resolution")
    expected_resolution_keys = {
        "contract_version",
        "resolution_scope",
        "catalog_snapshot_ref",
        "design_time_reuse_hits",
        "formal_execution_requirements",
        "formal_execution_gate",
        "generated_data_requests",
    }
    if not isinstance(resolution, Mapping):
        return [*reasons, "catalog_resolution"]
    if set(resolution) != expected_resolution_keys:
        reasons.append("catalog_resolution.shape")
    if resolution.get("contract_version") != (
        DATA_LIAISON_PREFORMAL_RESOLUTION_CONTRACT_VERSION
    ):
        reasons.append("catalog_resolution.contract_version")
    if resolution.get("resolution_scope") != "pre_formal_design_only":
        reasons.append("catalog_resolution.resolution_scope")
    expected_snapshot_ref = {
        "path": reference.get("path"),
        "sha256": reference.get("sha256"),
    }
    if resolution.get("catalog_snapshot_ref") != expected_snapshot_ref:
        reasons.append("catalog_resolution.catalog_snapshot_ref")
    if resolution.get("formal_execution_requirements") != list(
        DATA_LIAISON_FORMAL_EXECUTION_CHECKS
    ):
        reasons.append("catalog_resolution.formal_execution_requirements")
    if resolution.get("formal_execution_gate") != {
        "status": "DEFERRED_TO_STEP3",
        "formal_execution_allowed": False,
    }:
        reasons.append("catalog_resolution.formal_execution_gate")
    if resolution.get("generated_data_requests") != []:
        reasons.append("catalog_resolution.generated_data_requests")
    hits = resolution.get("design_time_reuse_hits")
    if not isinstance(hits, list) or not hits:
        reasons.append("catalog_resolution.design_time_reuse_hits")
        return reasons
    expected_hit_keys = {
        "dataset_id",
        "dataset_class",
        "catalog_membership",
        "materialized_uri",
        "required_fields",
        "required_coverage",
        "information_policy_present",
        "producer_provenance_present",
    }
    seen: set[str] = set()
    for index, hit in enumerate(hits):
        label = f"catalog_resolution.design_time_reuse_hits[{index}]"
        if not isinstance(hit, Mapping) or set(hit) != expected_hit_keys:
            reasons.append(f"{label}.shape")
            continue
        dataset_id = str(hit.get("dataset_id") or "")
        entry = entries.get(dataset_id)
        if not dataset_id or dataset_id in seen or entry is None:
            reasons.append(f"{label}.dataset_id")
            continue
        seen.add(dataset_id)
        if (
            entry.get("dataset_class") != "base_market_dataset"
            or hit.get("dataset_class") != entry.get("dataset_class")
        ):
            reasons.append(f"{label}.dataset_class")
        if (
            entry.get("catalog_membership") != "active_catalog_member"
            or hit.get("catalog_membership") != entry.get("catalog_membership")
        ):
            reasons.append(f"{label}.catalog_membership")
        materialized_uri = str(entry.get("materialized_uri") or "")
        if (
            not materialized_uri.startswith("s3://")
            or hit.get("materialized_uri") != materialized_uri
        ):
            reasons.append(f"{label}.materialized_uri")
        required_fields = hit.get("required_fields")
        columns = entry.get("columns")
        valid_columns = bool(
            isinstance(columns, list)
            and columns
            and all(isinstance(field, str) and field for field in columns)
        )
        valid_required_fields = bool(
            isinstance(required_fields, list)
            and required_fields
            and all(isinstance(field, str) and field for field in required_fields)
        )
        if valid_columns and valid_required_fields:
            available_fields = set(columns)
            valid_required_fields = bool(
                len(set(required_fields)) == len(required_fields)
                and all(field in available_fields for field in required_fields)
            )
        if not valid_columns or not valid_required_fields:
            reasons.append(f"{label}.required_fields")
        coverage = hit.get("required_coverage")
        freshness = (
            entry.get("freshness")
            if isinstance(entry.get("freshness"), Mapping)
            else {}
        )
        available_start = _normalized_date(
            entry.get("start_date") or freshness.get("trade_date_min")
        )
        available_end = _normalized_date(
            entry.get("end_date") or freshness.get("trade_date_max")
        )
        if not isinstance(coverage, Mapping) or set(coverage) != {"start", "end"}:
            reasons.append(f"{label}.required_coverage")
        else:
            required_start = _normalized_date(coverage.get("start"))
            required_end = _normalized_date(coverage.get("end"))
            if (
                not required_start
                or not required_end
                or not available_start
                or not available_end
                or required_start > required_end
                or required_start < available_start
                or required_end > available_end
            ):
                reasons.append(f"{label}.required_coverage")
        information_policy_present = _host_information_policy_attested(entry)
        if (
            hit.get("information_policy_present") is not True
            or not information_policy_present
        ):
            reasons.append(f"{label}.information_policy_present")
        producer = entry.get("producer_provenance")
        producer_present = bool(
            isinstance(producer, Mapping)
            and any(str(value or "").strip() for value in producer.values())
        )
        if hit.get("producer_provenance_present") is not True or not producer_present:
            reasons.append(f"{label}.producer_provenance_present")
    permissions = record.get("permissions_boundary")
    if permissions != {
        "catalog_read_only": True,
        "catalog_write_allowed": False,
        "data_write_allowed": False,
        "pipeline_execution_allowed": False,
    }:
        reasons.append("permissions_boundary")
    return reasons


def validate_agent_result(
    result: Any,
    *,
    task: Mapping[str, Any],
    workspace: Path,
    peer_session_ids: Iterable[str] = (),
    staged_context_files: Iterable[Mapping[str, Any]] | None = None,
    tasks_by_role: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(result, dict):
        return [f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:missing"]
    session_policy = (
        task.get("session_policy")
        if isinstance(task.get("session_policy"), dict)
        else {}
    )
    expected_result_keys = {
        "contract_version",
        "task_ref",
        "identity",
        "role_id",
        "status",
        "producer_mode",
        "session_id",
        "public_research_record",
        "result_sha256",
    }
    if session_policy.get("independence_class") == "independent_review":
        expected_result_keys.update(
            {"independence_attestation", "formal_independent_verdict"}
        )
    if set(result) != expected_result_keys:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:result_envelope.shape")
    if result.get("contract_version") != AGENT_RESULT_CONTRACT_VERSION:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:contract_version")
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:{reason}"
        for reason in validate_content_hash(result, hash_field="result_sha256", label="result")
    )
    if result.get("task_ref") != {
        "task_id": task.get("task_id"),
        "sha256": task.get("task_sha256"),
    }:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:task_ref")
    if result.get("role_id") != task.get("role_id"):
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:role_id")
    reasons.extend(
        f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:{item}"
        for item in _identity_reasons(result.get("identity"), task.get("identity") or {}, label="identity")
    )
    if result.get("status") not in VALID_RESULT_STATUSES:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:status")
    producer_mode = result.get("producer_mode")
    if producer_mode not in VALID_PRODUCER_MODES:
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:producer_mode")
    session_id = result.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:session_id")
    record = result.get("public_research_record")
    if not isinstance(record, dict):
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record")
    else:
        if record.get("contract_version") != task.get("output_contract"):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.contract_version"
            )
        if task.get("output_contract") == DOMAIN_PROPOSAL_CONTRACT_VERSION:
            required = (
                "identity",
                "domain",
                "proposal_status",
                "domain_fit",
                "public_research_record",
                "knowledge_use",
                "data_dependencies",
                "uncertainties",
                "artifact_refs",
                "handoff",
            )
            if task.get("role_id") == "data_liaison":
                required = (
                    "identity",
                    "domain",
                    "proposal_status",
                    "domain_fit",
                    "catalog_resolution",
                    "delivery_receipt_verification",
                    "knowledge_use",
                    "permissions_boundary",
                    "uncertainties",
                    "handoff",
                )
            else:
                required = (*required, "math_model_search", "measurement_proposal", "falsification_plan")
            for key in required:
                if key not in record:
                    reasons.append(
                        f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.{key}"
                    )
            if (
                task.get("role_id") != "data_liaison"
                and "artifact_refs" in record
                and not isinstance(record.get("artifact_refs"), list)
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.artifact_refs"
                )
            expected_domain = next(
                (
                    domain
                    for domain, assigned_role in DOMAIN_ROLE_IDS.items()
                    if assigned_role == task.get("role_id")
                ),
                "data_liaison" if task.get("role_id") == "data_liaison" else None,
            )
            if expected_domain is not None and record.get("domain") != expected_domain:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.domain"
                )
            proposal_status = record.get("proposal_status")
            expected_status = DOMAIN_PROPOSAL_STATUS_MAP.get(str(proposal_status))
            if expected_status is None or result.get("status") != expected_status:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:proposal_status_mapping"
                )
            proposal_identity = record.get("identity")
            expected_proposal_identity = {
                "task_id": task.get("task_id"),
                "factor_id": (task.get("identity") or {}).get("factor_id"),
                "research_id": (task.get("identity") or {}).get("research_id"),
                "report_id": (task.get("identity") or {}).get("report_id"),
                "agent_role": task.get("role_id"),
            }
            if not isinstance(proposal_identity, dict) or any(
                proposal_identity.get(key) != value
                for key, value in expected_proposal_identity.items()
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.identity"
                )
        else:
            for key in ("executive_summary", "claims", "artifact_refs", "handoff"):
                if key not in record:
                    reasons.append(
                        f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:public_research_record.{key}"
                    )
            strict_knowledge_record = bool(
                task.get("role_id") == "knowledge_librarian"
                and task.get("output_contract")
                == KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION
            )
            if strict_knowledge_record:
                reasons.extend(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:{item}"
                    for item in _knowledge_librarian_record_reasons(
                        record=record,
                        task=task,
                        workspace=workspace,
                    )
                )
            else:
                reasons.extend(_empirical_claim_reasons(record))
            reasons.extend(
                _validate_preformal_design_review(
                    result=result,
                    record=record,
                    task=task,
                    workspace=workspace,
                    staged_context_files=staged_context_files,
                    tasks_by_role=tasks_by_role,
                )
            )
            reasons.extend(
                _validate_director_synthesis(
                    result=result,
                    record=record,
                    task=task,
                    workspace=workspace,
                )
            )
    for path in private_reasoning_paths(result):
        reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:private_reasoning:{path}")
    for artifact in (record or {}).get("artifact_refs") or []:
        if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}:
            reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:artifact_ref")
            continue
        try:
            relative = normalize_workspace_relative_path(
                artifact.get("path"), workspace=workspace, label="result.artifact_ref"
            )
            path = workspace / relative
            if not path.is_file() or path.is_symlink() or sha256_file(path) != artifact.get("sha256"):
                reasons.append(f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:artifact_hash:{relative}")
        except ResearchOrganizationError as exc:
            reasons.append(str(exc))
    if task.get("role_id") == "data_liaison" and isinstance(record, dict):
        if result.get("status") == "PASS":
            reasons.extend(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:data_liaison_preformal:{item}"
                for item in _data_liaison_preformal_pass_reasons(
                    record=record,
                    task=task,
                    workspace=workspace,
                )
            )
        catalog_resolution = record.get("catalog_resolution")
        generated_requests = (
            catalog_resolution.get("generated_data_requests")
            if isinstance(catalog_resolution, dict)
            else []
        )
        if not isinstance(generated_requests, list):
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:generated_data_requests"
            )
            generated_requests = []
        report_id = str((task.get("identity") or {}).get("report_id") or "")
        request_root = f"objects/research_organization/{report_id}/data_requests/"
        expected_request_paths: set[str] = set()
        for request_ref in generated_requests:
            if not isinstance(request_ref, dict) or set(request_ref) != {
                "request_id",
                "path",
                "sha256",
            }:
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:data_request_ref"
                )
                continue
            try:
                relative = normalize_workspace_relative_path(
                    request_ref.get("path"),
                    workspace=workspace,
                    label="result.data_request_ref",
                )
                request_path = workspace / relative
                expected_request_paths.add(relative)
                if (
                    not relative.startswith(request_root)
                    or not request_path.is_file()
                    or request_path.is_symlink()
                    or sha256_file(request_path) != request_ref.get("sha256")
                ):
                    reasons.append(
                        f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:data_request_hash:{relative}"
                    )
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
        request_entries, request_directory_reasons = _ordinary_directory_entries(
            workspace=workspace,
            relative_root=request_root.rstrip("/"),
            label="organization.data_request_root",
            required=False,
        )
        reasons.extend(request_directory_reasons)
        if set(request_entries) != expected_request_paths:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_RESULT_INVALID}:data_request_directory"
            )
    if (
        producer_mode == "single_agent_fallback"
        and session_policy.get("single_agent_fallback_allowed") is not True
    ):
        reasons.append(f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:fallback_not_allowed")
    if (
        producer_mode == "real_agent"
        and session_policy.get("requirement") in {"isolated_session", "independent_session"}
        and session_id in set(peer_session_ids)
    ):
        reasons.append(f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:session_reused")
    if session_policy.get("independence_class") == "independent_review":
        attestation = result.get("independence_attestation")
        if not isinstance(attestation, dict):
            reasons.append(f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:attestation")
        elif set(attestation) != {
            "independence_satisfied",
            "reviewed_role_ids",
        }:
            reasons.append(
                f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:attestation.shape"
            )
        elif producer_mode == "real_agent":
            if attestation.get("independence_satisfied") is not True:
                reasons.append(f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:not_satisfied")
            if attestation.get("reviewed_role_ids") != task.get(
                "required_review_role_ids"
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:reviewed_roles"
                )
        else:
            if attestation.get("independence_satisfied") is not False:
                reasons.append(f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:fallback_overclaim")
            if result.get("formal_independent_verdict") is not None:
                reasons.append(f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:fallback_verdict")
    return reasons


def admit_agent_result(
    *,
    workspace: Path,
    result: Mapping[str, Any],
    role_id: str | None = None,
) -> dict[str, Any]:
    """Validate a private Agent result and atomically admit it to the workspace."""

    resolved, _manifest = _load_valid_workspace(workspace)
    with workspace_file_lock(resolved, PLAN_RELATIVE_PATH):
        return _admit_agent_result_locked(
            workspace=resolved,
            result=result,
            role_id=role_id,
        )


def _admit_agent_result_locked(
    *,
    workspace: Path,
    result: Mapping[str, Any],
    role_id: str | None,
) -> dict[str, Any]:
    resolved = workspace
    existing_summary = validate_research_organization_bundle(workspace=resolved)
    plan = read_workspace_json(resolved, PLAN_RELATIVE_PATH)
    dispatch = read_workspace_json(
        resolved,
        str(plan["workspace_policy"]["dispatch_manifest_path"]),
    )
    requested_role = role_id or str(result.get("role_id") or "")
    matching = [
        reference
        for reference in dispatch.get("tasks") or []
        if isinstance(reference, dict) and reference.get("role_id") == requested_role
    ]
    if len(matching) != 1:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RESULT_INVALID,
            [f"role_task_binding:{requested_role}"],
        )
    task = read_workspace_json(resolved, str(matching[0]["path"]))
    unsatisfied_dependencies = [
        dependency
        for dependency in task.get("depends_on_roles") or []
        if existing_summary.get("result_statuses", {}).get(dependency) != "PASS"
    ]
    if unsatisfied_dependencies:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_TASK_INVALID,
            [
                "dependencies_not_satisfied:"
                + ",".join(str(item) for item in unsatisfied_dependencies)
            ],
        )
    peer_session_ids: list[str] = []
    peer_results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for reference in dispatch.get("tasks") or []:
        if not isinstance(reference, dict) or reference.get("role_id") == requested_role:
            continue
        peer_path = resolved / str(reference.get("expected_result_path") or "")
        if peer_path.is_file() and not peer_path.is_symlink():
            peer = read_workspace_json(
                resolved,
                str(reference.get("expected_result_path") or ""),
            )
            peer_session_ids.append(str(peer.get("session_id") or ""))
            peer_task = read_workspace_json(resolved, str(reference.get("path") or ""))
            peer_results.append((peer_task, peer))
    candidate, created_data_requests = materialize_data_liaison_requests(
        result=result,
        task=task,
        workspace=resolved,
    )
    destination: Path | None = None
    result_created = False
    try:
        tasks_by_role: dict[str, Mapping[str, Any]] = {}
        for reference in dispatch.get("tasks") or []:
            if not isinstance(reference, Mapping):
                continue
            referenced_task = read_workspace_json(
                resolved,
                str(reference.get("path") or ""),
            )
            referenced_role_id = referenced_task.get("role_id")
            if isinstance(referenced_role_id, str) and referenced_role_id:
                tasks_by_role[referenced_role_id] = referenced_task
        reasons = validate_agent_result(
            candidate,
            task=task,
            workspace=resolved,
            peer_session_ids=peer_session_ids,
            tasks_by_role=tasks_by_role,
        )
        candidate_session_id = str(candidate.get("session_id") or "")
        for peer_task, peer in peer_results:
            peer_policy = (
                peer_task.get("session_policy")
                if isinstance(peer_task.get("session_policy"), dict)
                else {}
            )
            if (
                candidate.get("producer_mode") == "real_agent"
                and peer.get("producer_mode") == "real_agent"
                and candidate_session_id
                and candidate_session_id == str(peer.get("session_id") or "")
                and peer_policy.get("requirement")
                in {"isolated_session", "independent_session"}
            ):
                reasons.append(
                    f"{BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID}:session_reused"
                )
        if reasons:
            raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_RESULT_INVALID, reasons)
        expected_result_path = str(task["expected_result_path"])
        destination = resolved / expected_result_path
        if destination.is_symlink() or (
            destination.exists() and not destination.is_file()
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RESULT_INVALID,
                [f"unsafe_result_path:{expected_result_path}"],
            )
        if destination.is_file():
            existing = read_workspace_json(resolved, expected_result_path)
            if stable_json_hash(existing) != stable_json_hash(candidate):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RESULT_INVALID,
                    [f"immutable_result_conflict:{expected_result_path}"],
                )
            summary = validate_research_organization_bundle(workspace=resolved)
            return {
                **summary,
                "admitted_role_id": requested_role,
                "idempotent": True,
            }
        try:
            write_workspace_json_once(resolved, expected_result_path, candidate)
            result_created = True
        except FileExistsError:
            existing = read_workspace_json(resolved, expected_result_path)
            if stable_json_hash(existing) != stable_json_hash(candidate):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_RESULT_INVALID,
                    [f"immutable_result_conflict:{expected_result_path}"],
                )
            summary = validate_research_organization_bundle(workspace=resolved)
            return {
                **summary,
                "admitted_role_id": requested_role,
                "idempotent": True,
            }
        summary = validate_research_organization_bundle(workspace=resolved)
        return {
            **summary,
            "admitted_role_id": requested_role,
            "idempotent": False,
        }
    except Exception:
        if (
            result_created
            and destination is not None
            and destination.is_file()
            and not destination.is_symlink()
        ):
            destination.unlink()
        cleanup_materialized_data_requests(
            workspace=resolved,
            relative_paths=created_data_requests,
        )
        raise


def write_research_organization_bundle(
    *,
    workspace: Path,
    request: Mapping[str, Any],
    preserve_existing: bool = False,
    researcher_memory_root: Path | None = None,
    researcher_memory_installation_id: str | None = None,
) -> dict[str, Any]:
    resolved, manifest = _load_valid_workspace(workspace)
    plan_path = resolved / PLAN_RELATIVE_PATH
    if preserve_existing:
        if not plan_path.is_file() or plan_path.is_symlink():
            raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PLAN_MISSING, [PLAN_RELATIVE_PATH])
        result = validate_research_organization_bundle(workspace=resolved)
        plan = read_workspace_json(resolved, PLAN_RELATIVE_PATH)
        request_identity = _identity(manifest, request)
        mismatches = _identity_reasons(plan.get("identity"), request_identity, label="identity")
        if mismatches:
            raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_IDENTITY_INVALID, mismatches)
        return result
    if plan_path.exists() or plan_path.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PLAN_INVALID,
            ["plan_exists_without_preserve"],
        )
    bundle = build_research_organization_bundle(
        workspace=resolved,
        request=request,
        researcher_memory_root=researcher_memory_root,
        researcher_memory_installation_id=researcher_memory_installation_id,
    )
    plan = bundle["plan"]
    tasks = bundle["tasks"]
    report_id = plan["identity"]["report_id"]
    for snapshot in bundle["input_snapshots"]:
        write_workspace_json(
            resolved,
            snapshot["path"],
            snapshot["payload"],
        )
    memory_binding = plan.get("researcher_memory")
    if isinstance(memory_binding, Mapping):
        for role_id, reference in memory_binding["role_snapshot_refs"].items():
            write_workspace_json(
                resolved,
                str(reference["path"]),
                bundle["memory_snapshots"][role_id],
            )
    for task in tasks:
        relative = f"objects/research_organization/{report_id}/tasks/{task['task_id']}.json"
        write_workspace_json(resolved, relative, task)
    dispatch_relative = plan["workspace_policy"]["dispatch_manifest_path"]
    write_workspace_json(resolved, dispatch_relative, bundle["dispatch"])
    # The plan is the bundle commit marker. Write it only after every referenced
    # immutable object is durable so readers never accept a partial bundle.
    write_workspace_json(resolved, PLAN_RELATIVE_PATH, plan)
    return validate_research_organization_bundle(workspace=resolved)


def load_research_organization_plan(workspace: Path) -> dict[str, Any]:
    resolved, _manifest = _load_valid_workspace(workspace)
    return read_workspace_json(resolved, PLAN_RELATIVE_PATH)


def resolve_research_organization_gate(
    *,
    mode: str,
    factor_workspace: Path | None,
    explicit_plan: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"off", "auto", "required"}:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PLAN_INVALID,
            [f"unsupported_mode={mode}"],
        )
    if mode == "off":
        if explicit_plan is not None:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_INVALID,
                ["explicit plan cannot be used when mode is off"],
            )
        return {
            "requested_mode": mode,
            "status": "disabled",
            "formal_org_independence": False,
        }
    if factor_workspace is None:
        if mode == "required":
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_MISSING,
                ["factor workspace is required"],
            )
        return {
            "requested_mode": mode,
            "status": "not_present_legacy",
            "formal_org_independence": False,
        }
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
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PLAN_MISSING,
                [str(expected_path)],
            )
        return {
            "requested_mode": mode,
            "status": "not_present_legacy",
            "formal_org_independence": False,
        }
    summary = validate_research_organization_bundle(workspace=workspace)
    if summary["state"] != "ROUTED":
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_ROUTE_INVALID,
            [f"organization_state={summary['state']}"],
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
