from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from factor_factory.research_org.contracts import (
    AGENT_RESULT_CONTRACT_VERSION,
    BLOCK_RESEARCH_ORG_PATH_INVALID,
    BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED,
    BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
    BLOCK_RESEARCH_ORG_RUNTIME_MISSING,
    BLOCK_RESEARCH_ORG_SESSION_FAILED,
    BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
    KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION,
    PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
    ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
    RUNTIME_ATTEMPT_CONTRACT_VERSION,
    RUNTIME_CONTEXT_CONTRACT_VERSION,
    RUNTIME_EVENT_CONTRACT_VERSION,
    RUNTIME_STATE_CONTRACT_VERSION,
    SESSION_RECEIPT_CONTRACT_VERSION,
    ResearchOrganizationError,
    normalize_workspace_relative_path,
    private_reasoning_paths,
    read_workspace_bytes,
    read_workspace_json,
    sha256_file,
    stable_json_hash,
    strict_json_loads,
    validate_content_hash,
    with_content_hash,
    workspace_file_lock,
    write_workspace_json,
    write_workspace_json_once,
)
from factor_factory.research_org.director import (
    DATA_LIAISON_FORMAL_EXECUTION_CHECKS,
    DATA_LIAISON_PREFORMAL_RESOLUTION_CONTRACT_VERSION,
    DATA_REQUEST_CONTRACT_VERSION,
    KNOWLEDGE_PRIOR_CLAIM_TYPES,
    KNOWLEDGE_PRIOR_CONTRACT_VERSION,
    KNOWLEDGE_PRIOR_EXECUTIVE_SUMMARY,
    KNOWLEDGE_RETRIEVAL_PROVENANCE_CONTRACT_VERSION,
    PREFORMAL_BLOCK_DECISION,
    PREFORMAL_CLAIM_SCOPE,
    PREFORMAL_CLEAR_DECISION,
    PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
    PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION,
    PREFORMAL_EXECUTIVE_SUMMARIES,
    PREFORMAL_FALSIFIER_CODES,
    PREFORMAL_FINDING_CODES,
    PREFORMAL_ROLE_CHECK_IDS,
    PLAN_RELATIVE_PATH,
    admit_agent_result,
    cleanup_materialized_data_requests,
    load_research_organization_plan,
    materialize_data_liaison_requests,
    transitive_dependency_roles,
    validate_agent_result,
    validate_research_organization_bundle,
)
from factor_factory.research_org.runtime_ledger import (
    LEDGER_CONTRACT_VERSION,
    ResearchOrgRuntimeLedger,
)
from factor_factory.research_org.runtime_trust import (
    RuntimeTrustStore,
    ensure_runtime_trust_store,
    load_runtime_trust_store,
)
RUNTIME_ROOT_NAME = "runtime"
RUNTIME_STATE_NAME = "runtime_state.json"
RUNTIME_LOCK_NAME = "dispatcher_lock.json"
RUNTIME_CANCEL_NAME = "cancel_request.json"
MAX_PRIVATE_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_STAGED_CONTEXT_BYTES = 16 * 1024 * 1024
STRONG_ISOLATION_CLASSES = {
    "container_staged_context",
}
VALID_RUNTIME_LIFECYCLES = {
    "READY",
    "RUNNING",
    "WAITING_HOST_RESULT",
    "WAITING_DATA",
    "WAITING_CLARIFICATION",
    "RETRY_EXHAUSTED",
    "BLOCKED",
    "CANCELLED",
    "COMPLETE",
}
VALID_ROLE_RUNTIME_STATES = {
    "PENDING",
    "READY",
    "RUNNING",
    "WAITING_HOST",
    "PASS",
    "NEEDS_DATA",
    "NEEDS_CLARIFICATION",
    "BLOCK",
    "RETRY_EXHAUSTED",
    "CANCELLED",
}
_SECRET_PATTERN = re.compile(
    r"(?i)(?:aws_secret_access_key|aws_session_token|api[_-]?key|"
    r"authorization\s*:\s*bearer|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
RESEARCH_ORG_CONTAINER_WORKSPACE = Path("/factorforge/research-org")
RESEARCH_ORG_CONTAINER_CONTEXT_ROOT = (
    RESEARCH_ORG_CONTAINER_WORKSPACE / "context"
)
RESEARCH_ORG_CONTAINER_PRIVATE_OUTPUT_PATH = (
    RESEARCH_ORG_CONTAINER_WORKSPACE / "output" / "agent_result.json"
)
RESEARCH_ORG_CONTAINER_TASK_PATH = (
    RESEARCH_ORG_CONTAINER_WORKSPACE / "task.md"
)

PREFORMAL_CHECK_RUBRICS = {
    "estimator_semantics": (
        "PASS only when the frozen plan distinguishes the observable factor-value "
        "estimator from evaluation metrics and states the estimand, signal orientation, "
        "and traded payoff without contradiction."
    ),
    "timing_and_information_set": (
        "PASS only when signal cutoff, field availability, entry, exit, label window, "
        "and holding period are explicit and mutually executable; a return beginning "
        "before entry is BLOCK."
    ),
    "operator_or_direct_code_route": (
        "PASS only when exactly one executable implementation route is selected and its "
        "operators or direct-code boundary implement the frozen factor law."
    ),
    "parity_and_invariants": (
        "PASS only when deterministic parity checks, limiting cases, invariants, and "
        "component mappings can distinguish implementation drift from the model."
    ),
    "data_contract_alignment": (
        "PASS only when every required input is present in the admitted catalog or a "
        "precise data request exists, with point-in-time and coverage obligations stated."
    ),
    "is_oos_and_trial_budget": (
        "PASS only when IS/OOS boundaries, purge/embargo, trial budget, and multiple-testing "
        "policy are frozen before empirical execution."
    ),
    "metric_and_threshold_preregistration": (
        "PASS only when the applicable metrics, directions, thresholds, and terminal "
        "success/reject/block rules are preregistered without using realized outcomes."
    ),
    "cost_turnover_and_long_side": (
        "PASS only when cost, turnover, capacity, long-side payoff, and NAV construction "
        "are specified on the same executable return path."
    ),
    "ablations_and_falsifiers": (
        "PASS only when component ablations, null/alternative models, regime checks, and "
        "mechanism-specific falsifiers can reject aliases and unsupported complexity."
    ),
    "proof_and_provenance": (
        "PASS only when planned artifacts, hashes, raw evidence, replay obligations, and "
        "authority boundaries can support a later formal proof certificate."
    ),
    "economic_mechanism": (
        "PASS only when the payer/receiver, persistent constraint, profit transfer, and "
        "failure boundary jointly imply the proposed return direction."
    ),
    "math_measurement_identity": (
        "PASS only when the selected mathematical object, observation map, estimator, "
        "estimand, and traded quantity are one coherent measurement identity."
    ),
    "data_and_timing_legality": (
        "PASS only when catalog provenance, legal information time, signal formation, "
        "execution, exit, and label semantics are mutually consistent."
    ),
    "implementation_and_parity": (
        "PASS only when the chosen route implements the frozen object and has deterministic "
        "parity, invariance, and component-level checks."
    ),
    "validation_and_falsification": (
        "PASS only when the frozen evidence design can test the preferred mechanism against "
        "its null and alternatives after costs without post-OOS tuning."
    ),
    "independence_and_scope": (
        "PASS only when all required admitted roles were reviewed in this independent "
        "session and the decision is limited to pre-formal execution readiness."
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ResearchOrgSessionInvocation:
    identity: dict[str, str]
    role_id: str
    task_id: str
    task_sha256: str
    attempt_id: str
    attempt_number: int
    session_id: str
    runtime_instance_id: str
    worktree: Path
    workspace: Path
    private_attempt_root: Path
    context_root: Path
    private_output_path: Path
    cancel_request_path: Path
    context_manifest_sha256: str
    required_skills: tuple[str, ...]
    timeout_seconds: int
    runtime_id: str = ""
    plan_sha256: str = ""
    scheduler_epoch: int = 0
    dispatch_event_seq: int = 0
    idempotency_key: str = ""
    adapter_challenge: str = ""
    dependency_admissions: tuple[dict[str, Any], ...] = ()
    parent_session_uid: str | None = None
    # Host-only operational routing.  This is intentionally separate from
    # ``identity`` so artifact identities and signed semantic receipts do not
    # acquire a Console job identifier.  Legacy/ordinary organization calls
    # may continue to route through ``identity.job_id``.
    host_job_id: str = ""


@dataclass(frozen=True)
class ResearchOrgSessionOutcome:
    returncode: int
    session_id: str
    runtime_instance_id: str
    started_at_utc: str
    finished_at_utc: str
    provider: str
    model: str
    transport: str
    isolation_class: str
    owned_termination_supported: bool
    cancelled: bool = False
    stdout_tail: str = ""
    stderr_tail: str = ""
    provider_session_handle_sha256: str = ""
    adapter_receipt: dict[str, Any] | None = None


class ResearchOrgSessionRunner(Protocol):
    def run_research_org_session(
        self,
        invocation: ResearchOrgSessionInvocation,
    ) -> ResearchOrgSessionOutcome: ...

    def cancel_research_org_session(self, runtime_instance_id: str) -> bool: ...


def build_research_org_session_prompt(
    invocation: ResearchOrgSessionInvocation,
    *,
    container_context_root: Path | None = None,
    container_private_output_path: Path | None = None,
) -> str:
    if invocation.role_id == "evo_child_independent_reviewer":
        from factor_factory.console.evo_child_assurance import (
            build_evo_child_review_prompt,
        )

        return build_evo_child_review_prompt(invocation)
    if invocation.role_id == "evo_child_preregistration_author":
        from factor_factory.evo_child_authoring import (
            build_evo_child_authoring_prompt,
        )

        return build_evo_child_authoring_prompt(invocation)
    evo_search_request = (
        invocation.context_root
        / "identity/evo_v2_cold_start_search_request.json"
    )
    if invocation.role_id == "knowledge_librarian" and (
        invocation.task_id.startswith("evo_v2_memory_search_")
        or evo_search_request.exists()
        or evo_search_request.is_symlink()
    ):
        from factor_factory.knowledge_context import (
            build_evo_v2_cold_start_search_prompt,
        )

        return build_evo_v2_cold_start_search_prompt(
            invocation,
            container_context_root=(
                container_context_root
                or RESEARCH_ORG_CONTAINER_CONTEXT_ROOT
            ),
            container_private_output_path=(
                container_private_output_path
                or RESEARCH_ORG_CONTAINER_PRIVATE_OUTPUT_PATH
            ),
        )
    if invocation.role_id == "researcher_memory_reviewer":
        from factor_factory.researcher_memory_review import (
            build_researcher_memory_review_prompt,
        )

        return build_researcher_memory_review_prompt(invocation)
    skill_lines = "\n".join(
        f"- {invocation.worktree / 'skills' / skill / 'SKILL.md'}"
        for skill in invocation.required_skills
    ) or "- No additional role skill is declared; follow the frozen task packet."
    task_path = (
        invocation.context_root
        / f"objects/research_organization/{invocation.identity['report_id']}"
        / "tasks"
        / f"{invocation.task_id}.json"
    )
    private_output_template: dict[str, Any] = {
        "contract_version": PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION,
        "status": "PASS|BLOCK|NEEDS_DATA|NEEDS_CLARIFICATION",
        "public_research_record": {},
    }
    task_packet = (
        strict_json_loads(
            task_path.read_bytes(),
            label="research_org_session_task",
        )
        if task_path.is_file() and not task_path.is_symlink()
        else {}
    )
    task_output_contract = (
        str(task_packet.get("output_contract") or "")
        if isinstance(task_packet, Mapping)
        else ""
    )
    memory_enabled = bool(
        isinstance(task_packet, Mapping)
        and isinstance(task_packet.get("role_memory"), Mapping)
        and task_packet["role_memory"].get("required") is True
    )
    if memory_enabled:
        private_output_template["learning_candidates"] = []
    if invocation.role_id in PREFORMAL_ROLE_CHECK_IDS:
        private_output_template["status"] = "PASS|BLOCK"
        check_ids = json.dumps(
            list(PREFORMAL_ROLE_CHECK_IDS[invocation.role_id]),
            ensure_ascii=False,
        )
        claim_scope = json.dumps(PREFORMAL_CLAIM_SCOPE, ensure_ascii=False)
        finding_codes = json.dumps(PREFORMAL_FINDING_CODES, ensure_ascii=False)
        falsifier_codes = json.dumps(
            {
                check_id: PREFORMAL_FALSIFIER_CODES[check_id]
                for check_id in PREFORMAL_ROLE_CHECK_IDS[invocation.role_id]
            },
            ensure_ascii=False,
        )
        executive_summaries = json.dumps(
            PREFORMAL_EXECUTIVE_SUMMARIES,
            ensure_ascii=False,
        )
        check_rubrics = json.dumps(
            {
                check_id: PREFORMAL_CHECK_RUBRICS[check_id]
                for check_id in PREFORMAL_ROLE_CHECK_IDS[invocation.role_id]
            },
            ensure_ascii=False,
            indent=2,
        )
        check_template = [
            {
                "check_id": check_id,
                "claim_type": "DESIGN_REQUIREMENT",
                "status": "PASS|BLOCK",
                "finding_code": (
                    "DESIGN_CHECK_SATISFIED|DESIGN_CHECK_UNSATISFIED"
                ),
                "falsifier_code": PREFORMAL_FALSIFIER_CODES[check_id],
                "evidence_refs": ["<AUTHORIZED_STAGED_WORKSPACE_PATH>"],
            }
            for check_id in PREFORMAL_ROLE_CHECK_IDS[invocation.role_id]
        ]
        public_record_template_payload = {
            "contract_version": ROLE_RESEARCH_RECORD_CONTRACT_VERSION,
            "executive_summary": "<EXACT_ALLOWED_EXECUTIVE_SUMMARY>",
            "claims": check_template,
            "artifact_refs": [
                {
                    "path": "<AUTHORIZED_STAGED_WORKSPACE_PATH>",
                    "sha256": "<SHA256_OF_FILE_BYTES>",
                }
            ],
            "handoff": {"status": "ready_for_host_review"},
            "design_review": {
                "contract_version": PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION,
                "stage": "pre_formal_research_design",
                "evidence_basis": "pre_registered_design_only",
                "claim_scope": PREFORMAL_CLAIM_SCOPE,
                "empirical_factor_verdict": "NOT_ISSUED",
                "decision": "CLEAR_FOR_FORMAL_EXECUTION|BLOCK_FORMAL_EXECUTION",
                "checks": check_template,
                "blockers": ["<BLOCKED_CHECK_ID_ONLY>"],
            },
        }
        private_output_template["public_research_record"] = (
            public_record_template_payload
        )
        public_record_template = json.dumps(
            public_record_template_payload,
            ensure_ascii=False,
            indent=2,
        )
        role_contract_guidance = f"""
For this `{invocation.role_id}` role, `public_research_record.design_review`
is mandatory. It must use contract
`{PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION}`, stage
`pre_formal_research_design`, evidence_basis
`pre_registered_design_only`, empirical_factor_verdict `NOT_ISSUED`, and
claim_scope exactly `{claim_scope}`. This is a controlled record: the only
top-level public record keys are `contract_version`, `executive_summary`,
`claims`, `artifact_refs`, `handoff`, and `design_review`; handoff must equal
`{{"status":"ready_for_host_review"}}`. Use exactly these ordered check_ids:
{check_ids}. Every check has exactly `check_id`,
`claim_type=DESIGN_REQUIREMENT`, `status=PASS|BLOCK`, `finding_code`,
`falsifier_code`, and `evidence_refs`. Finding codes are {finding_codes};
falsifier codes are {falsifier_codes}. Evidence refs are paths only and must
also appear as hash-bound `artifact_refs` authorized by the frozen task.
`public_research_record.claims` must exactly equal the ordered `checks` list;
no free-text claim, finding, falsifier, blocker, or extra field is allowed.
`blockers` must exactly list the ordered check_ids whose status is BLOCK.
Executive summaries must be selected exactly from {executive_summaries}. Use decision
`{PREFORMAL_CLEAR_DECISION}` only when every check
passes and `blockers=[]`; otherwise use `{PREFORMAL_BLOCK_DECISION}` and outer
status `BLOCK`. Do not report realized Sharpe, IC/ICIR, returns, drawdown,
historical-simulation outcomes, promotion suitability, backtest proof, or an
empirical factor verdict.

The outer `public_research_record.contract_version` is exactly
`{ROLE_RESEARCH_RECORD_CONTRACT_VERSION}`; only the nested
`design_review.contract_version` is
`{PREFORMAL_DESIGN_REVIEW_CONTRACT_VERSION}`. The nested review must include the
`decision` key. Follow this exact shape, replacing placeholders without adding
or removing keys:

```json
{public_record_template}
```

Apply these check rubrics to the frozen design rather than guessing from the
check names:

```json
{check_rubrics}
```

Evidence paths are limited to the task's input artifacts, exact admitted direct
or transitive dependency result paths, and hash-bound public artifact refs
carried by those admitted dependency results and listed in
`runtime_context.json.files`. A dependency's Host-bound
`identity/web_research_plan.json`, final execution ledger, or Agent-authored
Director source record is admissible only when it appears by that transitive
route. Merely appearing in staged context does not make a path evidence. Every
path cited by a check must appear once in `artifact_refs` with the SHA-256 of
the staged file bytes. Every `PASS` check must cite at least one such path;
`evidence_refs=[]` is never a satisfied design check.
"""
        if invocation.role_id == "independent_council":
            private_output_template["independence_attestation"] = {
                "independence_satisfied": True,
                "reviewed_role_ids": [
                    "<COPY_EXACT_TASK_REQUIRED_REVIEW_ROLE_IDS_IN_ORDER>"
                ],
            }
            private_output_template["formal_independent_verdict"] = {
                "contract_version": PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION,
                "stage": "pre_formal_research_design",
                "claim_scope": PREFORMAL_CLAIM_SCOPE,
                "decision": "CLEAR_FOR_FORMAL_EXECUTION|BLOCK_FORMAL_EXECUTION",
                "reviewed_role_ids": [
                    "<COPY_EXACT_TASK_REQUIRED_REVIEW_ROLE_IDS_IN_ORDER>"
                ],
                "blocking_findings": ["<BLOCKED_CHECK_ID_ONLY>"],
                "empirical_factor_verdict": "NOT_ISSUED",
            }
            council_private_keys = [
                "contract_version",
                "status",
                "public_research_record",
                "independence_attestation",
                "formal_independent_verdict",
            ]
            if memory_enabled:
                council_private_keys.append("learning_candidates")
            council_private_key_count = (
                "six" if len(council_private_keys) == 6 else "five"
            )
            council_private_key_text = ", ".join(
                f"`{key}`" for key in council_private_keys
            )
            role_contract_guidance += f"""
Also include top-level `formal_independent_verdict` using contract
`{PREFORMAL_COUNCIL_VERDICT_CONTRACT_VERSION}`, the same pre-formal stage and
claim_scope, decision, the exact task `required_review_role_ids`, the same blockers under
`blocking_findings`, and empirical_factor_verdict `NOT_ISSUED`. This clears or
blocks only formal execution; it is never factor ACCEPT/REJECT/PROMOTE.

For this Council role, "top-level" means the private output envelope, not the
public research record. The private output object has exactly these {council_private_key_count} keys:
{council_private_key_text}.
`independence_attestation` and `formal_independent_verdict` are siblings of
`public_research_record`; never place either one inside
`public_research_record`. The outer JSON template above contains the complete
controlled public record; use that single template without moving or adding
fields.
"""
    elif (
        invocation.role_id == "knowledge_librarian"
        and task_output_contract == KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION
    ):
        knowledge_template = json.dumps(
            {
                "contract_version": KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION,
                "executive_summary": KNOWLEDGE_PRIOR_EXECUTIVE_SUMMARY,
                "knowledge_prior_contract": {
                    "contract_version": KNOWLEDGE_PRIOR_CONTRACT_VERSION,
                    "authority": "historical_advisory_only",
                    "current_factor_empirical_verdict": "NOT_ISSUED",
                    "current_factor_performance_inference_allowed": False,
                    "historical_metrics_subject": "prior_artifacts_only",
                },
                "retrieval_provenance": {
                    "contract_version": (
                        KNOWLEDGE_RETRIEVAL_PROVENANCE_CONTRACT_VERSION
                    ),
                    "source_artifact_ref": {
                        "path": "<FACTOR_KNOWLEDGE_SUMMARY_PATH>",
                        "sha256": "<FILE_BYTE_SHA256_FROM_RUNTIME_CONTEXT>",
                    },
                    "cold_start": False,
                    "query_hash": "<64_LOWERCASE_HEX_QUERY_HASH>",
                    "top_k": 5,
                    "hit_count": 1,
                    "retrieved_node_ids": ["<SOURCE_NODE_ID>"],
                },
                "claims": [
                    {
                        "claim_type": "<ALLOWED_CLAIM_TYPE>",
                        "source_node_id": "<SOURCE_NODE_ID>",
                        "source_path": ["evidence", "falsification"],
                        "source_text": "<EXACT_TEXT_AT_SOURCE_PATH>",
                        "source_text_sha256": "<SHA256_OF_EXACT_SOURCE_TEXT>",
                        "applicability_to_current_factor": "advisory_only",
                        "current_factor_inference_allowed": False,
                        "evidence_ref": "<FACTOR_KNOWLEDGE_SUMMARY_PATH>",
                    }
                ],
                "historical_metrics": [
                    {
                        "source_node_id": "<SOURCE_NODE_ID>",
                        "source_path": [
                            "evidence",
                            "key_metrics",
                            "<METRIC_KEY>",
                        ],
                        "metric_value": 0.0,
                        "source_subject": "prior_artifact",
                        "evidence_ref": "<FACTOR_KNOWLEDGE_SUMMARY_PATH>",
                        "current_factor_inference_allowed": False,
                    }
                ],
                "artifact_refs": [
                    {
                        "path": "<FACTOR_KNOWLEDGE_SUMMARY_PATH>",
                        "sha256": "<FILE_BYTE_SHA256_FROM_RUNTIME_CONTEXT>",
                    }
                ],
                "handoff": {
                    "status": "ready_for_host_review",
                    "authority": "advisory_only",
                    "estimand_selected": False,
                    "current_factor_empirical_verdict": "NOT_ISSUED",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        claim_types = json.dumps(
            sorted(KNOWLEDGE_PRIOR_CLAIM_TYPES),
            ensure_ascii=False,
        )
        role_contract_guidance = f"""
This role retrieves historical advisory evidence; it does not evaluate the
current factor. Use exactly the public-record shape below. The executive
summary, authority contract and handoff values are literal constants. Copy the
sole `factor_knowledge_summary.json` path and its file-byte SHA-256 from
`runtime_context.json.files` into both source/artifact refs.

Allowed `claim_type` values are {claim_types}. Select only the semantic class;
there is no Agent-authored claim identifier or statement field. Every claim
must copy `source_text` exactly from the selected retrieved node at the JSON
`source_path` and hash those exact UTF-8 text bytes. The Host resolves the path
inside the captured summary and rejects any mismatch. Claim `source_path` must
start with one of `title`, `summary`, `mechanism`, `evidence`,
`reuse_guidance`, or `research_status`; metadata such as `overlap_terms`, ids,
factor ids, and report ids is not claim evidence. When the captured payload has
nodes, return at least one claim from an allowed path. For the required first
claim, prefer the first retrieved node's scalar
`["summary"]` path so no list-index coercion is involved. If a later path does
index a JSON list, the path segment must be a JSON integer such as `2`, never
the string `"2"`. Put every numeric
historical metric only in `historical_metrics`: `source_path` must be exactly
`["evidence","key_metrics","<key>"]`, and `metric_value` must equal that
source number. Its subject is fixed to `prior_artifact`, its node must be one of
the Host-derived retrieved nodes, and current-factor inference is always false.
Copy `query_hash`, `top_k`, ordered node ids and cold-start state exactly from
the captured knowledge payload; the Host does not accept Agent-invented
retrieval provenance. Use empty claim/metric lists for a cold start. This keeps
historical evidence usable without creating any model-authored current-factor
performance claim. Estimator selection and empirical verdict remain with their
declared downstream owners.

```json
{knowledge_template}
```
"""
    elif invocation.role_id == "knowledge_librarian":
        role_contract_guidance = """
This is a frozen legacy Knowledge Librarian task using
`factorforge_role_research_record_v1`. Follow that task's generic output
contract exactly. Do not use the newer `factorforge_knowledge_prior_record_v1`
shape, and do not issue a current-factor empirical result or verdict. This
legacy path exists only so an already-created runtime remains resumable and
cancellable after the registry upgrade.
"""
    elif invocation.role_id == "data_liaison":
        formal_checks = json.dumps(
            list(DATA_LIAISON_FORMAL_EXECUTION_CHECKS),
            ensure_ascii=False,
        )
        role_contract_guidance = f"""
This task is pre-formal. A Host-attested `base_market_dataset` may be used only
for design feasibility under the role skill; this never claims formal QA. If
you return PASS through that narrow route, `catalog_resolution` must have
exactly `contract_version={DATA_LIAISON_PREFORMAL_RESOLUTION_CONTRACT_VERSION}`,
`resolution_scope=pre_formal_design_only`, the exact catalog input artifact
`path` and `sha256` as `catalog_snapshot_ref`, non-empty
`design_time_reuse_hits`, `formal_execution_requirements={formal_checks}`,
`formal_execution_gate={{"status":"DEFERRED_TO_STEP3","formal_execution_allowed":false}}`,
and `generated_data_requests=[]`. Each reuse hit has exactly `dataset_id`,
`dataset_class`, `catalog_membership`, `materialized_uri`, `required_fields`,
`required_coverage` (`start` and `end`), `information_policy_present`, and
`producer_provenance_present`. The Host validator accepts only an active,
snapshot-bound base dataset whose deterministic Host information-policy
attestation passes, and rejects derived datamarts/states on this route. Free
text cannot establish PIT legality.
Copy `catalog_snapshot_ref.path` and `catalog_snapshot_ref.sha256` literally
from the matching `task.input_artifacts` entry. That SHA is the declared
`json_content` hash; do not substitute the file-byte SHA from
`runtime_context.json.files`, the inner source-catalog hash, or a recomputed
hash. This rule is specific to `catalog_snapshot_ref`.
An `approved_catalog_snapshot_member` is valid on this pre-formal-only route
when the frozen entry carries a valid `factorforge_host_catalog_qa_attestation_v1`
with verdict ACCEPT. Do not demand or invent active transport admission for
that workspace-local Host QA snapshot; copy its membership literally and keep
formal execution deferred to Step3.
For PASS, `permissions_boundary` must be exactly catalog read-only true and
catalog/data writes plus pipeline execution false.

If a dependency is missing, do not attempt to write the read-only staged
workspace. In `catalog_resolution.generated_data_requests`, embed each request
as exactly `request_id`, the task-authorized workspace-relative `path`, and
`request_payload`. The payload must use `{DATA_REQUEST_CONTRACT_VERSION}` and
bind the exact factor/research/report consumer identity. The Host validates and
atomically materializes the request, replaces the embedded payload with its
path/file hash reference, and only then admits your result.
"""
    else:
        role_contract_guidance = ""
    if memory_enabled:
        from factor_factory.researcher_memory import (
            MAX_LEARNING_CANDIDATES_PER_RESULT,
            MEMORY_KINDS,
        )

        memory_kinds = json.dumps(
            sorted(MEMORY_KINDS),
            ensure_ascii=False,
        )
        memory_guidance = f"""
The task contains exactly one role-scoped `role_memory.snapshot_ref`. It is a
frozen historical advisory snapshot for this role only. Read it after the task
packet. It may supply analogies, anti-patterns, and prior failure conditions,
but it cannot select the current estimand, prove current-factor performance, or
override the economic hypothesis and mathematical mechanism.

You may return zero to {MAX_LEARNING_CANDIDATES_PER_RESULT} reusable design
lessons in top-level `learning_candidates`. Each candidate has exactly
`memory_kind`, `title`, `lesson`, `applicability_conditions`,
`failure_conditions`, and `evidence_refs`. `memory_kind` is one of
{memory_kinds}. Evidence refs must exactly copy path/file-byte SHA-256 pairs
already present in `public_research_record.artifact_refs`. Do not put verdicts,
private reasoning, raw logs, credentials, or unreferenced claims in a candidate.
Candidates are optional, remain `candidate_only`, and never change the task
result. You cannot approve or promote your own candidate; the Host strips this
field from canonical `factorforge_agent_result_v1` and records it separately.
"""
    else:
        memory_guidance = ""
    private_output_template_json = json.dumps(
        private_output_template,
        ensure_ascii=False,
        indent=2,
    )
    return f"""# Factor Forge isolated specialist session

You are the `{invocation.role_id}` specialist for exactly one frozen Factor
Forge task. This is an internal Agent session, not the Host Research Director
and not a user-visible task.

## Immutable runtime identity

- task_id: {invocation.task_id}
- task_sha256: {invocation.task_sha256}
- attempt_id: {invocation.attempt_id}
- session_id: {invocation.session_id}
- factor_id: {invocation.identity['factor_id']}
- research_id: {invocation.identity['research_id']}
- report_id: {invocation.identity['report_id']}

Read these files first:

1. {invocation.context_root / 'runtime_context.json'}
2. {task_path}

The context manifest is the complete factor-workspace visibility grant. Read
only files listed there. The engine repository is read-only and may be used to
read these declared role skills:

{skill_lines}

This organization runtime is the pre-formal research-design stage. Follow the
task's `execution_stage_contract` exactly. Quant Implementation audits the
planned estimator and implementation boundary; Validation & Evidence audits
the preregistration and falsification design; Independent Council reviews that
complete pre-execution design. None of these roles may claim that a backtest ran
or issue an empirical factor verdict. Formal execution and the post-execution
empirical Council remain owned by Ultimate/Step6.

Do not inspect another factor workspace, another role's unlisted result,
credentials, environment variables, instance metadata, Agent stores, or
private prompts. Do not run production research, mutate code, materialize data,
change thresholds, or write any canonical workspace path. Treat knowledge and
catalog snapshots as advisory evidence, while the economic hypothesis and
selected mathematical mechanism remain authoritative.

Write exactly one UTF-8 JSON object to:

{invocation.private_output_path}

Write the final object directly to that exact absolute path. Do not create a
relative-path draft, scratch file, or `.openclaw` workspace file.

It must use this outer shape and no unknown top-level keys:

```json
{private_output_template_json}
```

The public record must satisfy the frozen task's `output_contract` and the
declared role skill. For Independent Council also add
`independence_attestation` with `independence_satisfied=true` and the exact
`required_review_role_ids` from the task. Do not include private chain-of-
thought, scratchpads, hidden reasoning, credentials, raw logs, task identity,
session identity, result hashes, or canonical paths outside the public record.
Expose only reproducible definitions, decisive derivation steps, assumptions,
evidence references, uncertainties, and falsifiers. The Host will bind the
task/session identity, compute the result hash, validate the record, and decide
whether it is admitted.

Hash semantics are deliberately distinct. For every
`public_research_record.artifact_refs` entry, copy the matching path and
file-byte SHA-256 from `runtime_context.json.files`. Each artifact reference
object has exactly two keys, `path` and `sha256`. The context manifest also
contains staging metadata such as `size_bytes`; never copy that metadata into
an artifact reference. Do not copy the task packet's `json_content` hash. A
role-specific contract may separately require a task input-artifact content
hash, such as Data Liaison's `catalog_snapshot_ref`; follow that role-specific
rule for that field only.


{role_contract_guidance}

{memory_guidance}
"""


def _runtime_relatives(plan: Mapping[str, Any]) -> dict[str, str]:
    organization_root = str(plan["workspace_policy"]["organization_root"])
    runtime_root = f"{organization_root}/{RUNTIME_ROOT_NAME}"
    return {
        "root": runtime_root,
        "state": f"{runtime_root}/{RUNTIME_STATE_NAME}",
        "lock": f"{runtime_root}/{RUNTIME_LOCK_NAME}",
        "cancel": f"{runtime_root}/{RUNTIME_CANCEL_NAME}",
        "events": f"{runtime_root}/events",
        "attempts": f"{runtime_root}/attempts",
    }


def _load_tasks(
    workspace: Path,
    plan: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    dispatch = read_workspace_json(
        workspace,
        str(plan["workspace_policy"]["dispatch_manifest_path"]),
    )
    tasks: list[dict[str, Any]] = []
    by_role: dict[str, dict[str, Any]] = {}
    for reference in dispatch.get("tasks") or []:
        if not isinstance(reference, dict):
            continue
        task = read_workspace_json(workspace, str(reference.get("path") or ""))
        tasks.append(task)
        by_role[str(task["role_id"])] = task
    return tasks, by_role


def _canonical_results(
    workspace: Path,
    tasks: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for task in tasks:
        relative = str(task["expected_result_path"])
        path = workspace / relative
        if path.is_file() and not path.is_symlink():
            results[str(task["role_id"])] = read_workspace_json(workspace, relative)
    return results


def _initial_role_state(task: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task["task_id"],
        "task_sha256": task["task_sha256"],
        "session_requirement": task["session_policy"]["requirement"],
        "status": "PENDING",
        "attempt_ids": [],
        "active_attempt_id": None,
        "result_status": None,
        "last_error": None,
    }


def _new_runtime_state(
    plan: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    *,
    max_attempts: int,
    max_concurrency: int,
    timeout_seconds: int,
    trust_manifest: Mapping[str, Any] | None,
    allow_unverified_test_runner: bool,
) -> dict[str, Any]:
    runtime_id = f"runtime_{str(plan['plan_sha256'])[:20]}"
    timestamp = utc_now()
    payload = {
        "contract_version": RUNTIME_STATE_CONTRACT_VERSION,
        "runtime_id": runtime_id,
        "identity": dict(plan["identity"]),
        "plan_ref": {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]},
        "lifecycle": "READY",
        "created_at_utc": timestamp,
        "updated_at_utc": timestamp,
        "policy": {
            "max_attempts_per_role": max_attempts,
            "max_concurrency": max_concurrency,
            "session_timeout_seconds": timeout_seconds,
            "host_only_canonical_admission": True,
            "private_output_transport": True,
            "staged_factor_context_only": True,
            "cancel_owned_sessions_only": True,
        },
        "authority": {
            "ledger_contract_version": LEDGER_CONTRACT_VERSION,
            "ledger_storage": "host_private_not_workspace",
            "workspace_json_semantics": "rebuildable_projection_only",
            "signed_adapter_receipts_required": not allow_unverified_test_runner,
            "trust_manifest": dict(trust_manifest) if trust_manifest is not None else None,
        },
        "roles": {
            str(task["role_id"]): _initial_role_state(task) for task in tasks
        },
        "attempt_count": 0,
        "last_event_sequence": 0,
        "last_event_sha256": None,
    }
    return with_content_hash(payload, hash_field="state_sha256")


def _write_state(workspace: Path, relative: str, state: Mapping[str, Any]) -> None:
    payload = dict(state)
    payload["updated_at_utc"] = utc_now()
    payload = with_content_hash(payload, hash_field="state_sha256")
    write_workspace_json(workspace, relative, payload)


def _append_event(
    *,
    workspace: Path,
    paths: Mapping[str, str],
    state: dict[str, Any],
    event_type: str,
    role_id: str | None = None,
    attempt_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
) -> None:
    sequence = int(state.get("last_event_sequence") or 0) + 1
    payload = with_content_hash(
        {
            "contract_version": RUNTIME_EVENT_CONTRACT_VERSION,
            "runtime_id": state["runtime_id"],
            "identity": dict(state["identity"]),
            "sequence": sequence,
            "event_type": event_type,
            "role_id": role_id,
            "attempt_id": attempt_id,
            "occurred_at_utc": utc_now(),
            "previous_event_sha256": state.get("last_event_sha256"),
            "detail": dict(detail or {}),
        },
        hash_field="event_sha256",
    )
    relative = f"{paths['events']}/event_{sequence:06d}.json"
    write_workspace_json_once(workspace, relative, payload)
    state["last_event_sequence"] = sequence
    state["last_event_sha256"] = payload["event_sha256"]


def _ensure_runtime_lock(
    workspace: Path,
    paths: Mapping[str, str],
    plan: Mapping[str, Any],
) -> None:
    lock_path = workspace / paths["lock"]
    if lock_path.exists() or lock_path.is_symlink():
        lock = read_workspace_json(workspace, paths["lock"])
        expected = {
            "contract_version": "factorforge_research_org_runtime_lock_v1",
            "identity": plan["identity"],
            "plan_ref": {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]},
        }
        if any(lock.get(key) != value for key, value in expected.items()):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["runtime_lock_binding"],
            )
        return
    payload = with_content_hash(
        {
            "contract_version": "factorforge_research_org_runtime_lock_v1",
            "identity": dict(plan["identity"]),
            "plan_ref": {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]},
        },
        hash_field="lock_sha256",
    )
    try:
        write_workspace_json_once(workspace, paths["lock"], payload)
    except FileExistsError:
        _ensure_runtime_lock(workspace, paths, plan)


def _load_or_create_state(
    *,
    workspace: Path,
    paths: Mapping[str, str],
    plan: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    max_attempts: int,
    max_concurrency: int,
    timeout_seconds: int,
    trust_manifest: Mapping[str, Any] | None,
    allow_unverified_test_runner: bool,
) -> dict[str, Any]:
    state_path = workspace / paths["state"]
    if state_path.is_file() and not state_path.is_symlink():
        state = read_workspace_json(workspace, paths["state"])
        if (
            state.get("contract_version") != RUNTIME_STATE_CONTRACT_VERSION
            or state.get("identity") != plan.get("identity")
            or state.get("plan_ref")
            != {"path": PLAN_RELATIVE_PATH, "sha256": plan.get("plan_sha256")}
            or validate_content_hash(state, hash_field="state_sha256", label="runtime_state")
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["runtime_state_binding"],
            )
        expected_policy = {
            "max_attempts_per_role": max_attempts,
            "max_concurrency": max_concurrency,
            "session_timeout_seconds": timeout_seconds,
            "host_only_canonical_admission": True,
            "private_output_transport": True,
            "staged_factor_context_only": True,
            "cancel_owned_sessions_only": True,
        }
        if state.get("policy") != expected_policy:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["runtime_policy_mismatch"],
            )
        expected_authority = {
            "ledger_contract_version": LEDGER_CONTRACT_VERSION,
            "ledger_storage": "host_private_not_workspace",
            "workspace_json_semantics": "rebuildable_projection_only",
            "signed_adapter_receipts_required": not allow_unverified_test_runner,
            "trust_manifest": (
                dict(trust_manifest) if trust_manifest is not None else None
            ),
        }
        if state.get("authority") != expected_authority:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["runtime_authority_mismatch"],
            )
        return state
    state = _new_runtime_state(
        plan,
        tasks,
        max_attempts=max_attempts,
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
        trust_manifest=trust_manifest,
        allow_unverified_test_runner=allow_unverified_test_runner,
    )
    try:
        write_workspace_json_once(workspace, paths["state"], state)
    except FileExistsError:
        return read_workspace_json(workspace, paths["state"])
    return state


def _safe_private_root(workspace: Path, private_root: Path) -> Path:
    resolved = Path(private_root).expanduser().resolve(strict=False)
    workspace = workspace.resolve(strict=True)
    if (
        resolved == workspace
        or resolved in workspace.parents
        or workspace in resolved.parents
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            ["private_runtime_root_must_be_disjoint"],
        )
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            ["unsafe_private_runtime_root"],
        )
    resolved.chmod(0o700)
    return resolved


def _context_source_paths(
    workspace: Path,
    task: Mapping[str, Any],
    tasks_by_role: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    task_path = (
        f"objects/research_organization/{task['identity']['report_id']}"
        f"/tasks/{task['task_id']}.json"
    )
    paths = [task_path]
    paths.extend(
        str(reference["path"])
        for reference in task.get("input_artifacts") or []
        if isinstance(reference, dict) and reference.get("path")
    )
    role_memory = task.get("role_memory")
    if isinstance(role_memory, Mapping):
        snapshot_ref = role_memory.get("snapshot_ref")
        if isinstance(snapshot_ref, Mapping) and snapshot_ref.get("path"):
            paths.append(str(snapshot_ref["path"]))
    for role_id in transitive_dependency_roles(
        task=task,
        tasks_by_role=tasks_by_role,
    ):
        dependency = tasks_by_role.get(str(role_id))
        if dependency is not None:
            result_relative = str(dependency["expected_result_path"])
            paths.append(result_relative)
            result_path = workspace / result_relative
            if result_path.is_file() and not result_path.is_symlink():
                result = read_workspace_json(workspace, result_relative)
                record = result.get("public_research_record")
                for reference in _typed_public_artifact_refs(record):
                    artifact_relative = normalize_workspace_relative_path(
                        reference["path"],
                        workspace=workspace,
                        label="runtime_dependency_artifact",
                    )
                    artifact_path = workspace / artifact_relative
                    if (
                        not artifact_path.is_file()
                        or artifact_path.is_symlink()
                        or sha256_file(artifact_path)
                        != reference.get("sha256")
                    ):
                        raise ResearchOrganizationError(
                            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                            [
                                "dependency_artifact_hash:"
                                f"{role_id}:{artifact_relative}"
                            ],
                        )
                    paths.append(artifact_relative)
    return list(dict.fromkeys(paths))


def _typed_public_artifact_refs(record: Any) -> list[Mapping[str, Any]]:
    if not isinstance(record, Mapping):
        return []
    candidates: list[Any] = list(record.get("artifact_refs") or [])
    catalog_resolution = record.get("catalog_resolution")
    if isinstance(catalog_resolution, Mapping):
        candidates.extend(
            catalog_resolution.get("generated_data_requests") or []
        )
    references: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for reference in candidates:
        if (
            not isinstance(reference, Mapping)
            or not isinstance(reference.get("path"), str)
            or not isinstance(reference.get("sha256"), str)
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["dependency_artifact_ref_contract"],
            )
        key = (str(reference["path"]), str(reference["sha256"]))
        if key in seen:
            continue
        seen.add(key)
        references.append(reference)
    return references


def _copy_context_file(
    *,
    workspace: Path,
    context_root: Path,
    relative: str,
) -> dict[str, Any]:
    normalized = normalize_workspace_relative_path(
        relative,
        workspace=workspace,
        label="runtime_context_source",
    )
    payload = read_workspace_bytes(
        workspace,
        normalized,
        max_bytes=MAX_STAGED_CONTEXT_BYTES,
    )
    destination = context_root / normalized
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.parent.chmod(0o700)
    destination.write_bytes(payload)
    destination.chmod(0o400)
    return {
        "path": normalized,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _prepare_context(
    *,
    workspace: Path,
    context_root: Path,
    task: Mapping[str, Any],
    tasks_by_role: Mapping[str, Mapping[str, Any]],
    session_id: str,
    runtime_id: str,
    scheduler_epoch: int,
    idempotency_key: str,
    adapter_challenge: str,
    dependency_admissions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    context_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    context_root.chmod(0o700)
    files = [
        _copy_context_file(
            workspace=workspace,
            context_root=context_root,
            relative=relative,
        )
        for relative in _context_source_paths(workspace, task, tasks_by_role)
    ]
    if sum(int(item["size_bytes"]) for item in files) > MAX_STAGED_CONTEXT_BYTES:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["runtime_context_budget"],
        )
    payload = with_content_hash(
        {
            "contract_version": RUNTIME_CONTEXT_CONTRACT_VERSION,
            "identity": dict(task["identity"]),
            "task_ref": {
                "task_id": task["task_id"],
                "sha256": task["task_sha256"],
            },
            "role_id": task["role_id"],
            "session_id": session_id,
            "runtime_id": runtime_id,
            "scheduler_epoch": scheduler_epoch,
            "idempotency_key": idempotency_key,
            "adapter_challenge": adapter_challenge,
            "dependency_admissions": [
                dict(item) for item in dependency_admissions
            ],
            "factor_workspace_visibility": "staged_files_only",
            "canonical_workspace_write_access": False,
            "files": files,
        },
        hash_field="context_sha256",
    )
    manifest_path = context_root / "runtime_context.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o400)
    for directory in sorted(
        (item for item in context_root.rglob("*") if item.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    context_root.chmod(0o500)
    return payload


def _context_unchanged(context_root: Path, manifest: Mapping[str, Any]) -> bool:
    manifest_path = context_root / "runtime_context.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return False
    try:
        observed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if observed != manifest:
        return False
    expected = {str(item["path"]): item for item in manifest.get("files") or []}
    actual: set[str] = set()
    for path in context_root.rglob("*"):
        if path == manifest_path or path.is_dir():
            continue
        if path.is_symlink() or not path.is_file():
            return False
        relative = path.relative_to(context_root).as_posix()
        actual.add(relative)
        reference = expected.get(relative)
        if reference is None or sha256_file(path) != reference.get("sha256"):
            return False
    return actual == set(expected)


def _attempt_relatives(
    paths: Mapping[str, str],
    *,
    role_id: str,
    attempt_id: str,
) -> dict[str, str]:
    root = f"{paths['attempts']}/{role_id}/{attempt_id}"
    return {
        "root": root,
        "context": f"{root}/context_manifest.json",
        "attempt": f"{root}/attempt.json",
        "receipt": f"{root}/session_receipt.json",
    }


def _prepare_attempt(
    *,
    workspace: Path,
    worktree: Path,
    private_root: Path,
    paths: Mapping[str, str],
    state: dict[str, Any],
    task: Mapping[str, Any],
    tasks_by_role: Mapping[str, Mapping[str, Any]],
    timeout_seconds: int,
    ledger: ResearchOrgRuntimeLedger,
    scheduler_epoch: int,
) -> tuple[ResearchOrgSessionInvocation, dict[str, Any], dict[str, str]]:
    role_id = str(task["role_id"])
    role_state = state["roles"][role_id]
    attempt_number = len(role_state["attempt_ids"]) + 1
    token = uuid.uuid4().hex
    attempt_id = f"attempt_{attempt_number:02d}_{token[:16]}"
    session_id = f"session_{token}"
    runtime_instance_id = (
        f"fforg-{str(task['identity']['job_id'])[:12]}-"
        f"{role_id[:18]}-{token[:8]}"
    ).lower().replace("_", "-")
    dependency_admissions, idempotency_key = ledger.dispatch_material(
        role_id=role_id,
        attempt_no=attempt_number,
        scheduler_epoch=scheduler_epoch,
    )
    adapter_challenge = uuid.uuid4().hex
    private_attempt_root = private_root / state["runtime_id"] / attempt_id
    if private_attempt_root.exists() or private_attempt_root.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            [f"private_attempt_exists:{attempt_id}"],
        )
    private_attempt_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    context_root = private_attempt_root / "context"
    private_output = private_attempt_root / "output" / "agent_result.json"
    private_output.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
    context = _prepare_context(
        workspace=workspace,
        context_root=context_root,
        task=task,
        tasks_by_role=tasks_by_role,
        session_id=session_id,
        runtime_id=str(state["runtime_id"]),
        scheduler_epoch=scheduler_epoch,
        idempotency_key=idempotency_key,
        adapter_challenge=adapter_challenge,
        dependency_admissions=dependency_admissions,
    )
    relatives = _attempt_relatives(
        paths,
        role_id=role_id,
        attempt_id=attempt_id,
    )
    lease = ledger.begin_attempt(
        role_id=role_id,
        attempt_id=attempt_id,
        attempt_no=attempt_number,
        session_uid=session_id,
        runtime_handle=runtime_instance_id,
        context_manifest_sha256=str(context["context_sha256"]),
        idempotency_key=idempotency_key,
        dependency_admissions=dependency_admissions,
        adapter_challenge=adapter_challenge,
        parent_session_uid=None,
        scheduler_epoch=scheduler_epoch,
    )
    write_workspace_json_once(workspace, relatives["context"], context)
    attempt = with_content_hash(
        {
            "contract_version": RUNTIME_ATTEMPT_CONTRACT_VERSION,
            "runtime_id": state["runtime_id"],
            "identity": dict(task["identity"]),
            "task_ref": {
                "task_id": task["task_id"],
                "sha256": task["task_sha256"],
            },
            "role_id": role_id,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "session_id": session_id,
            "runtime_instance_id": runtime_instance_id,
            "context_ref": {
                "path": relatives["context"],
                "sha256": context["context_sha256"],
            },
            "session_requirement": task["session_policy"]["requirement"],
            "started_at_utc": utc_now(),
            "status": "RUNNING",
            "ledger_ref": {
                "contract_version": LEDGER_CONTRACT_VERSION,
                "scheduler_epoch": lease.scheduler_epoch,
                "dispatch_event_seq": lease.dispatch_event_seq,
                "idempotency_key": lease.idempotency_key,
            },
        },
        hash_field="attempt_sha256",
    )
    write_workspace_json_once(workspace, relatives["attempt"], attempt)
    ledger.bind_attempt_projection(
        attempt_id=attempt_id,
        attempt_sha256=str(attempt["attempt_sha256"]),
    )
    role_state["attempt_ids"].append(attempt_id)
    role_state["active_attempt_id"] = attempt_id
    role_state["status"] = "RUNNING"
    state["attempt_count"] = int(state.get("attempt_count") or 0) + 1
    invocation = ResearchOrgSessionInvocation(
        identity=dict(task["identity"]),
        role_id=role_id,
        task_id=str(task["task_id"]),
        task_sha256=str(task["task_sha256"]),
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        session_id=session_id,
        runtime_instance_id=runtime_instance_id,
        worktree=worktree,
        workspace=workspace,
        private_attempt_root=private_attempt_root,
        context_root=context_root,
        private_output_path=private_output,
        cancel_request_path=workspace / paths["cancel"],
        context_manifest_sha256=str(context["context_sha256"]),
        required_skills=tuple(task["role_snapshot"].get("required_skills") or []),
        timeout_seconds=timeout_seconds,
        runtime_id=str(state["runtime_id"]),
        plan_sha256=str(state["plan_ref"]["sha256"]),
        scheduler_epoch=lease.scheduler_epoch,
        dispatch_event_seq=lease.dispatch_event_seq,
        idempotency_key=lease.idempotency_key,
        adapter_challenge=adapter_challenge,
        dependency_admissions=lease.dependency_admissions,
        parent_session_uid=None,
    )
    return invocation, context, relatives


def _invoke_session(
    runner: ResearchOrgSessionRunner,
    invocation: ResearchOrgSessionInvocation,
) -> ResearchOrgSessionOutcome:
    started = utc_now()
    try:
        return runner.run_research_org_session(invocation)
    except Exception as exc:  # noqa: BLE001 - adapter is an explicit trust boundary.
        return ResearchOrgSessionOutcome(
            returncode=1,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc=started,
            finished_at_utc=utc_now(),
            provider="unknown",
            model="unknown",
            transport="adapter_exception",
            isolation_class="unverified",
            owned_termination_supported=False,
            stderr_tail=f"{type(exc).__name__}: {exc}",
        )


def _private_output(
    invocation: ResearchOrgSessionInvocation,
    *,
    learning_candidates_allowed: bool,
) -> tuple[dict[str, Any], str, int]:
    path = invocation.private_output_path
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_SESSION_FAILED,
            ["private_output_missing_or_unsafe"],
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_PRIVATE_OUTPUT_BYTES
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_FAILED,
                ["private_output_missing_or_unsafe"],
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw_bytes = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw_bytes) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_FAILED,
                ["private_output_changed_while_reading"],
            )
    finally:
        os.close(descriptor)
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_SESSION_FAILED,
            ["private_output_json"],
        ) from exc
    if _SECRET_PATTERN.search(raw):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_SESSION_FAILED,
            ["private_output_secret_scan"],
        )
    try:
        payload = strict_json_loads(raw_bytes, label="private_agent_output")
    except ResearchOrganizationError as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_SESSION_FAILED,
            ["private_output_json"],
        ) from exc
    allowed = {
        "contract_version",
        "status",
        "public_research_record",
        "independence_attestation",
        "formal_independent_verdict",
    }
    if learning_candidates_allowed:
        allowed.add("learning_candidates")
    if (
        not isinstance(payload, dict)
        or payload.get("contract_version") != PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
        or not {"contract_version", "status", "public_research_record"}.issubset(payload)
        or set(payload) - allowed
        or private_reasoning_paths(payload)
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_SESSION_FAILED,
            ["private_output_contract"],
        )
    return payload, hashlib.sha256(raw_bytes).hexdigest(), len(raw_bytes)


def _canonical_result(
    *,
    task: Mapping[str, Any],
    invocation: ResearchOrgSessionInvocation,
    private_output: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_version": AGENT_RESULT_CONTRACT_VERSION,
        "task_ref": {
            "task_id": task["task_id"],
            "sha256": task["task_sha256"],
        },
        "identity": dict(task["identity"]),
        "role_id": task["role_id"],
        "status": private_output["status"],
        "producer_mode": "real_agent",
        "session_id": invocation.session_id,
        "public_research_record": private_output["public_research_record"],
    }
    for key in ("independence_attestation", "formal_independent_verdict"):
        if key in private_output:
            payload[key] = private_output[key]
    return with_content_hash(payload, hash_field="result_sha256")


def _outcome_binding_reasons(
    outcome: ResearchOrgSessionOutcome,
    invocation: ResearchOrgSessionInvocation,
    task: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if outcome.session_id != invocation.session_id:
        reasons.append("session_id_mismatch")
    if outcome.runtime_instance_id != invocation.runtime_instance_id:
        reasons.append("runtime_instance_id_mismatch")
    if not outcome.owned_termination_supported:
        reasons.append("owned_termination_unsupported")
    requirement = str(task["session_policy"]["requirement"])
    if (
        requirement in {"isolated_session", "independent_session"}
        and outcome.isolation_class not in STRONG_ISOLATION_CLASSES
    ):
        reasons.append("isolation_class")
    for value, label in (
        (outcome.started_at_utc, "started_at_utc"),
        (outcome.finished_at_utc, "finished_at_utc"),
        (outcome.provider, "provider"),
        (outcome.model, "model"),
        (outcome.transport, "transport"),
    ):
        if not isinstance(value, str) or not value:
            reasons.append(label)
    return reasons


def _receipt_payload(
    *,
    state: Mapping[str, Any],
    task: Mapping[str, Any],
    invocation: ResearchOrgSessionInvocation,
    outcome: ResearchOrgSessionOutcome,
    context: Mapping[str, Any],
    receipt_status: str,
    output_sha256: str | None,
    output_size_bytes: int | None,
    canonical_result: Mapping[str, Any] | None,
    error_code: str | None,
    retryable: bool,
    ledger_receipt_ref: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = {
        "contract_version": SESSION_RECEIPT_CONTRACT_VERSION,
        "runtime_id": state["runtime_id"],
        "identity": dict(task["identity"]),
        "task_ref": {
            "task_id": task["task_id"],
            "sha256": task["task_sha256"],
        },
        "role_id": task["role_id"],
        "attempt_id": invocation.attempt_id,
        "attempt_number": invocation.attempt_number,
        "session_id": invocation.session_id,
        "runtime_instance_id": invocation.runtime_instance_id,
        "status": receipt_status,
        "started_at_utc": outcome.started_at_utc,
        "finished_at_utc": outcome.finished_at_utc,
        "returncode": outcome.returncode,
        "provider": outcome.provider,
        "model": outcome.model,
        "transport": outcome.transport,
        "isolation": {
            "class": outcome.isolation_class,
            "factor_workspace_visibility": "staged_files_only",
            "canonical_workspace_write_access": False,
            "owned_termination_supported": outcome.owned_termination_supported,
            "context_manifest_sha256": context["context_sha256"],
            "context_unchanged_after_run": _context_unchanged(
                invocation.context_root,
                context,
            ),
        },
        "private_output": {
            "retention": "operator_private_not_canonical",
            "sha256": output_sha256,
            "size_bytes": output_size_bytes,
            "secret_scan": "PASS" if output_sha256 else "NOT_AVAILABLE",
        },
        "canonical_result_ref": (
            {
                "path": task["expected_result_path"],
                "sha256": canonical_result["result_sha256"],
            }
            if canonical_result is not None
            else None
        ),
        "cancelled": outcome.cancelled,
        "error_code": error_code,
        "retryable": retryable,
        "stdout_tail_sha256": stable_json_hash(outcome.stdout_tail),
        "stderr_tail_sha256": stable_json_hash(outcome.stderr_tail),
        "ledger_receipt_ref": (
            dict(ledger_receipt_ref) if ledger_receipt_ref is not None else None
        ),
    }
    return with_content_hash(payload, hash_field="receipt_sha256")


def _dependencies_pass(
    task: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
) -> bool:
    dependencies = list(task.get("depends_on_roles") or [])
    if task.get("role_id") == "independent_council":
        dependencies = list(task.get("required_review_role_ids") or [])
    return all(results.get(str(role), {}).get("status") == "PASS" for role in dependencies)


def _refresh_role_states(
    *,
    state: dict[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
) -> None:
    for task in tasks:
        role_id = str(task["role_id"])
        role_state = state["roles"][role_id]
        result = results.get(role_id)
        if result is not None:
            role_state["result_status"] = result.get("status")
            role_state["status"] = str(result.get("status"))
            role_state["active_attempt_id"] = None
            continue
        if role_state.get("status") in {
            "RUNNING",
            "RETRY_EXHAUSTED",
            "CANCELLED",
        }:
            continue
        if task["session_policy"]["requirement"] == "host_session":
            role_state["status"] = "WAITING_HOST"
        elif _dependencies_pass(task, results):
            role_state["status"] = "READY"
        else:
            role_state["status"] = "PENDING"


def _lifecycle(
    state: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
) -> str:
    statuses = [str(item.get("status")) for item in results.values()]
    role_statuses = [
        str(item.get("status")) for item in (state.get("roles") or {}).values()
    ]
    if "CANCELLED" in role_statuses:
        return "CANCELLED"
    if "NEEDS_DATA" in statuses:
        return "WAITING_DATA"
    if "NEEDS_CLARIFICATION" in statuses:
        return "WAITING_CLARIFICATION"
    if "BLOCK" in statuses:
        return "BLOCKED"
    if role_statuses and all(status == "PASS" for status in role_statuses):
        return "COMPLETE"
    if "RETRY_EXHAUSTED" in role_statuses:
        return "RETRY_EXHAUSTED"
    if "RUNNING" in role_statuses:
        return "RUNNING"
    if "WAITING_HOST" in role_statuses and "READY" not in role_statuses:
        return "WAITING_HOST_RESULT"
    return "READY"


def _finalize_attempt(
    *,
    workspace: Path,
    paths: Mapping[str, str],
    state: dict[str, Any],
    task: Mapping[str, Any],
    invocation: ResearchOrgSessionInvocation,
    context: Mapping[str, Any],
    relatives: Mapping[str, str],
    outcome: ResearchOrgSessionOutcome,
    max_attempts: int,
    ledger: ResearchOrgRuntimeLedger,
    tasks: Sequence[Mapping[str, Any]],
    allow_unverified_test_runner: bool,
) -> None:
    role_id = str(task["role_id"])
    role_state = state["roles"][role_id]
    canonical: dict[str, Any] | None = None
    private_output: dict[str, Any] | None = None
    output_sha: str | None = None
    output_size: int | None = None
    error_code: str | None = None
    receipt_status = "FAILED"
    ledger_receipt_ref: dict[str, Any] | None = None
    created_data_requests: tuple[str, ...] = ()
    memory_candidate_refs: list[dict[str, str]] = []
    memory_candidate_rejections: list[str] = []
    role_memory = task.get("role_memory")
    memory_enabled = (
        isinstance(role_memory, Mapping)
        and role_memory.get("required") is True
    )
    cancelled_before_admission = bool(
        outcome.cancelled or (workspace / paths["cancel"]).is_file()
    )
    if (workspace / paths["cancel"]).is_file():
        ledger.request_cancel(
            requested_by="workspace_cancel_projection",
            reason="workspace cancel request observed before admission",
        )
    reasons = _outcome_binding_reasons(outcome, invocation, task)
    if outcome.returncode != 0:
        reasons.append(f"returncode={outcome.returncode}")
    if not _context_unchanged(invocation.context_root, context):
        reasons.append("context_changed")
    if not reasons and not cancelled_before_admission:
        try:
            private_output, output_sha, output_size = _private_output(
                invocation,
                learning_candidates_allowed=memory_enabled,
            )
            canonical = _canonical_result(
                task=task,
                invocation=invocation,
                private_output=private_output,
            )
            canonical, created_data_requests = materialize_data_liaison_requests(
                result=canonical,
                task=task,
                workspace=workspace,
            )
            peer_session_ids = [
                str(result.get("session_id") or "")
                for result in _canonical_results(workspace, tasks).values()
            ]
            result_reasons = validate_agent_result(
                canonical,
                task=task,
                workspace=workspace,
                peer_session_ids=peer_session_ids,
                staged_context_files=context.get("files") or [],
                tasks_by_role={
                    str(item["role_id"]): item
                    for item in tasks
                },
            )
            if result_reasons:
                reasons.extend(result_reasons)
                canonical = None
        except ResearchOrganizationError as exc:
            if exc.token == BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED:
                cancelled_before_admission = True
            else:
                reasons.extend(exc.reasons or (str(exc),))
    if cancelled_before_admission:
        receipt_status = "CANCELLED"
        error_code = BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED
        canonical = None
    elif reasons:
        error_code = BLOCK_RESEARCH_ORG_SESSION_FAILED
        canonical = None

    if canonical is None and created_data_requests:
        cleanup_materialized_data_requests(
            workspace=workspace,
            relative_paths=created_data_requests,
        )
        created_data_requests = ()

    adapter_receipt_outcome = (
        outcome.adapter_receipt.get("outcome")
        if isinstance(outcome.adapter_receipt, Mapping)
        and isinstance(outcome.adapter_receipt.get("outcome"), Mapping)
        else None
    )
    adapter_termination_confirmed = (
        adapter_receipt_outcome.get("termination_confirmed")
        if adapter_receipt_outcome is not None
        else None
    )
    retryable = bool(
        receipt_status != "CANCELLED"
        and adapter_termination_confirmed is not False
        and not any(
            marker in " ".join(reasons)
            for marker in (
                "session_id_mismatch",
                "runtime_instance_id_mismatch",
                "context_changed",
                "isolation_class",
                "private_output_secret_scan",
            )
        )
    )
    try:
        host_receipt = ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=outcome.adapter_receipt,
            canonical_result=canonical,
            error_class=error_code,
            retryable=retryable,
            allow_unverified_test_runner=allow_unverified_test_runner,
            observed_private_output_sha256=output_sha,
            observed_private_output_size_bytes=output_size,
        )
    except ResearchOrganizationError as exc:
        if exc.token != BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED or canonical is None:
            cleanup_materialized_data_requests(
                workspace=workspace,
                relative_paths=created_data_requests,
            )
            created_data_requests = ()
            raise
        cancelled_before_admission = True
        receipt_status = "CANCELLED"
        error_code = BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED
        canonical = None
        retryable = False
        cleanup_materialized_data_requests(
            workspace=workspace,
            relative_paths=created_data_requests,
        )
        created_data_requests = ()
        host_receipt = ledger.complete_attempt(
            attempt_id=invocation.attempt_id,
            adapter_receipt=outcome.adapter_receipt,
            canonical_result=None,
            error_class=error_code,
            retryable=False,
            allow_unverified_test_runner=allow_unverified_test_runner,
            observed_private_output_sha256=output_sha,
            observed_private_output_size_bytes=output_size,
        )
    except Exception:
        cleanup_materialized_data_requests(
            workspace=workspace,
            relative_paths=created_data_requests,
        )
        created_data_requests = ()
        raise
    if canonical is None and created_data_requests:
        cleanup_materialized_data_requests(
            workspace=workspace,
            relative_paths=created_data_requests,
        )
        created_data_requests = ()
    if canonical is not None and host_receipt is not None:
        try:
            admit_agent_result(
                workspace=workspace,
                result=canonical,
                role_id=role_id,
            )
        except Exception:
            cleanup_materialized_data_requests(
                workspace=workspace,
                relative_paths=created_data_requests,
            )
            raise
        created_data_requests = ()
        receipt_status = "ADMITTED"
        if memory_enabled:
            try:
                from factor_factory.researcher_memory import (
                    materialize_learning_candidates,
                )

                memory_materialization = materialize_learning_candidates(
                    workspace=workspace,
                    task=task,
                    result=canonical,
                    proposals=(
                        private_output.get("learning_candidates")
                        if isinstance(private_output, Mapping)
                        else None
                    ),
                    runtime_provenance={
                        "adapter_receipt": dict(outcome.adapter_receipt or {}),
                        "host_admission_receipt": dict(host_receipt),
                    },
                    trust_store=ledger.trust_store,
                )
                memory_candidate_refs = list(
                    memory_materialization.get("candidate_refs") or []
                )
                memory_candidate_rejections = [
                    str(item)
                    for item in memory_materialization.get("rejections") or []
                ]
            except ResearchOrganizationError as exc:
                memory_candidate_rejections = [exc.token, *exc.reasons]
            except Exception as exc:
                memory_candidate_rejections = [
                    "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_CANDIDATE_INVALID",
                    f"materialization_error:{type(exc).__name__}",
                ]
        ledger_receipt_ref = {
            "ledger_contract_version": LEDGER_CONTRACT_VERSION,
            "adapter_receipt_id": (
                outcome.adapter_receipt.get("receipt_id")
                if outcome.adapter_receipt is not None
                else None
            ),
            "host_admission_receipt_id": host_receipt.get("receipt_id"),
            "evidence_class": (
                "signed_adapter"
                if outcome.adapter_receipt is not None
                else "unverified_test"
            ),
        }
    elif ledger_receipt_ref is None:
        ledger_receipt_ref = {
            "ledger_contract_version": LEDGER_CONTRACT_VERSION,
            "adapter_receipt_id": (
                outcome.adapter_receipt.get("receipt_id")
                if outcome.adapter_receipt is not None
                else None
            ),
            "host_admission_receipt_id": None,
            "evidence_class": (
                "signed_adapter"
                if outcome.adapter_receipt is not None
                else "unverified_test"
            ),
        }
    receipt = _receipt_payload(
        state=state,
        task=task,
        invocation=invocation,
        outcome=outcome,
        context=context,
        receipt_status=receipt_status,
        output_sha256=output_sha,
        output_size_bytes=output_size,
        canonical_result=canonical,
        error_code=error_code,
        retryable=(retryable if canonical is None else False),
        ledger_receipt_ref=ledger_receipt_ref,
    )
    write_workspace_json_once(workspace, relatives["receipt"], receipt)
    ledger.bind_receipt_projection(
        attempt_id=invocation.attempt_id,
        receipt_sha256=str(receipt["receipt_sha256"]),
    )
    role_state["active_attempt_id"] = None
    if receipt_status == "ADMITTED" and canonical is not None:
        role_state["status"] = str(canonical["status"])
        role_state["result_status"] = str(canonical["status"])
        role_state["last_error"] = None
    elif receipt_status == "CANCELLED":
        role_state["status"] = "CANCELLED"
        role_state["last_error"] = error_code
    elif not retryable or len(role_state["attempt_ids"]) >= max_attempts:
        role_state["status"] = "RETRY_EXHAUSTED"
        role_state["last_error"] = error_code
    else:
        role_state["status"] = "READY"
        role_state["last_error"] = error_code
    _append_event(
        workspace=workspace,
        paths=paths,
        state=state,
        event_type=(
            "SESSION_RESULT_ADMITTED"
            if receipt_status == "ADMITTED"
            else "SESSION_CANCELLED"
            if receipt_status == "CANCELLED"
            else "SESSION_ATTEMPT_FAILED"
        ),
        role_id=role_id,
        attempt_id=invocation.attempt_id,
        detail={
            "receipt_sha256": receipt["receipt_sha256"],
            "result_status": canonical.get("status") if canonical else None,
            "error_code": error_code,
            "memory_candidate_refs": memory_candidate_refs,
            "memory_candidate_rejections": memory_candidate_rejections,
        },
    )


def _recover_running_attempts(
    *,
    workspace: Path,
    paths: Mapping[str, str],
    state: dict[str, Any],
    runner: ResearchOrgSessionRunner,
    tasks_by_role: Mapping[str, Mapping[str, Any]],
    ledger: ResearchOrgRuntimeLedger,
    private_root: Path,
    max_attempts: int,
) -> None:
    for active in ledger.active_attempts():
        role_id = str(active["role_id"])
        attempt_id = str(active["attempt_id"])
        role_state = state["roles"][role_id]
        relatives = _attempt_relatives(
            paths,
            role_id=role_id,
            attempt_id=attempt_id,
        )
        runtime_instance_id = str(active["runtime_handle"])
        termination_confirmed = runner.cancel_research_org_session(
            runtime_instance_id
        )
        ledger.mark_attempt_lost(
            attempt_id=attempt_id,
            error_class="host_recovery_lost_session",
            retryable=True,
            termination_confirmed=termination_confirmed,
        )
        if not termination_confirmed:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_FAILED,
                [f"orphaned_runtime_instance:{runtime_instance_id}"],
            )
        private_context = (
            private_root
            / str(state["runtime_id"])
            / attempt_id
            / "context"
            / "runtime_context.json"
        )
        if not private_context.is_file() or private_context.is_symlink():
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_FAILED,
                [f"lost_context_manifest:{attempt_id}"],
            )
        context = json.loads(private_context.read_text(encoding="utf-8"))
        if not (workspace / relatives["context"]).is_file():
            write_workspace_json_once(workspace, relatives["context"], context)
        task = tasks_by_role[role_id]
        if not (workspace / relatives["attempt"]).is_file():
            attempt = with_content_hash(
                {
                    "contract_version": RUNTIME_ATTEMPT_CONTRACT_VERSION,
                    "runtime_id": state["runtime_id"],
                    "identity": dict(task["identity"]),
                    "task_ref": {
                        "task_id": task["task_id"],
                        "sha256": task["task_sha256"],
                    },
                    "role_id": role_id,
                    "attempt_id": attempt_id,
                    "attempt_number": int(active["attempt_no"]),
                    "session_id": active["session_uid"],
                    "runtime_instance_id": runtime_instance_id,
                    "context_ref": {
                        "path": relatives["context"],
                        "sha256": context["context_sha256"],
                    },
                    "session_requirement": task["session_policy"]["requirement"],
                    "started_at_utc": active["started_at_utc"],
                    "status": "RUNNING",
                    "ledger_ref": {
                        "contract_version": LEDGER_CONTRACT_VERSION,
                        "scheduler_epoch": int(active["scheduler_epoch"]),
                        "dispatch_event_seq": int(active["dispatch_event_seq"]),
                        "idempotency_key": active["idempotency_key"],
                    },
                },
                hash_field="attempt_sha256",
            )
            write_workspace_json_once(workspace, relatives["attempt"], attempt)
        else:
            attempt = read_workspace_json(workspace, relatives["attempt"])
        ledger.bind_attempt_projection(
            attempt_id=attempt_id,
            attempt_sha256=str(attempt["attempt_sha256"]),
        )
        if not (workspace / relatives["receipt"]).is_file():
            recovery_receipt = with_content_hash(
                {
                    "contract_version": SESSION_RECEIPT_CONTRACT_VERSION,
                    "runtime_id": state["runtime_id"],
                    "identity": dict(task["identity"]),
                    "task_ref": dict(attempt["task_ref"]),
                    "role_id": role_id,
                    "attempt_id": attempt_id,
                    "attempt_number": attempt["attempt_number"],
                    "session_id": attempt["session_id"],
                    "runtime_instance_id": runtime_instance_id,
                    "status": "ABANDONED",
                    "started_at_utc": attempt["started_at_utc"],
                    "finished_at_utc": utc_now(),
                    "returncode": 125,
                    "provider": "unknown_after_host_recovery",
                    "model": "unknown_after_host_recovery",
                    "transport": "owned_runtime_recovery",
                    "isolation": {
                        "class": "unverified_recovered_attempt",
                        "factor_workspace_visibility": "staged_files_only",
                        "canonical_workspace_write_access": False,
                        "owned_termination_supported": True,
                        "context_manifest_sha256": context["context_sha256"],
                        "context_unchanged_after_run": False,
                    },
                    "private_output": {
                        "retention": "operator_private_not_canonical",
                        "sha256": None,
                        "size_bytes": None,
                        "secret_scan": "NOT_AVAILABLE",
                    },
                    "canonical_result_ref": None,
                    "cancelled": True,
                    "error_code": BLOCK_RESEARCH_ORG_SESSION_FAILED,
                    "retryable": int(active["attempt_no"]) < max_attempts,
                    "stdout_tail_sha256": stable_json_hash(""),
                    "stderr_tail_sha256": stable_json_hash(
                        "host recovery terminated lost owned runtime"
                    ),
                    "ledger_receipt_ref": {
                        "ledger_contract_version": LEDGER_CONTRACT_VERSION,
                        "adapter_receipt_id": None,
                        "host_admission_receipt_id": None,
                        "evidence_class": "host_recovery",
                    },
                },
                hash_field="receipt_sha256",
            )
            write_workspace_json_once(
                workspace,
                relatives["receipt"],
                recovery_receipt,
            )
        recovery_receipt = read_workspace_json(workspace, relatives["receipt"])
        ledger.bind_receipt_projection(
            attempt_id=attempt_id,
            receipt_sha256=str(recovery_receipt["receipt_sha256"]),
        )
        if attempt_id not in role_state["attempt_ids"]:
            role_state["attempt_ids"].append(attempt_id)
            state["attempt_count"] = int(state.get("attempt_count") or 0) + 1
        role_state["active_attempt_id"] = None
        role_state["status"] = (
            "READY"
            if int(active["attempt_no"]) < max_attempts
            else "RETRY_EXHAUSTED"
        )
        role_state["last_error"] = "recovered_lost_attempt"
        _append_event(
            workspace=workspace,
            paths=paths,
            state=state,
            event_type="ABANDONED_SESSION_TERMINATED",
            role_id=role_id,
            attempt_id=attempt_id,
            detail={"runtime_instance_id": runtime_instance_id},
        )


def _reconcile_projection_event_head(
    *,
    workspace: Path,
    paths: Mapping[str, str],
    state: dict[str, Any],
) -> None:
    events_root = workspace / paths["events"]
    if not events_root.exists():
        if int(state.get("last_event_sequence") or 0) != 0:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["projection_event_directory_missing"],
            )
        return
    if events_root.is_symlink() or not events_root.is_dir():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["projection_event_directory_unsafe"],
        )
    files = sorted(events_root.iterdir(), key=lambda path: path.name)
    expected_names = [
        f"event_{sequence:06d}.json" for sequence in range(1, len(files) + 1)
    ]
    if [path.name for path in files] != expected_names or any(
        path.is_symlink() or not path.is_file() for path in files
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["projection_event_directory_not_closed"],
        )
    previous: str | None = None
    observed: list[dict[str, Any]] = []
    for sequence, path in enumerate(files, start=1):
        event = read_workspace_json(
            workspace,
            f"{paths['events']}/{path.name}",
        )
        if (
            event.get("contract_version") != RUNTIME_EVENT_CONTRACT_VERSION
            or event.get("runtime_id") != state.get("runtime_id")
            or event.get("identity") != state.get("identity")
            or event.get("sequence") != sequence
            or event.get("previous_event_sha256") != previous
            or validate_content_hash(
                event,
                hash_field="event_sha256",
                label="runtime_event",
            )
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"projection_event_chain:{sequence}"],
            )
        observed.append(event)
        previous = str(event["event_sha256"])
    state_sequence = int(state.get("last_event_sequence") or 0)
    if state_sequence > len(observed):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["projection_event_head_ahead"],
        )
    expected_state_head = (
        observed[state_sequence - 1]["event_sha256"] if state_sequence else None
    )
    if state.get("last_event_sha256") != expected_state_head:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["projection_event_head_mismatch"],
        )
    if len(observed) > state_sequence:
        state["last_event_sequence"] = len(observed)
        state["last_event_sha256"] = previous
        _write_state(workspace, paths["state"], state)


def _reconcile_ledger_results(
    *,
    workspace: Path,
    tasks: Sequence[Mapping[str, Any]],
    ledger: ResearchOrgRuntimeLedger,
    allow_unverified_test_runner: bool,
) -> dict[str, dict[str, Any]]:
    workspace_results = _canonical_results(workspace, tasks)
    ledger_results = ledger.canonical_results()
    for task in tasks:
        role_id = str(task["role_id"])
        workspace_result = workspace_results.get(role_id)
        ledger_result = ledger_results.get(role_id)
        if task["session_policy"]["requirement"] == "host_session":
            if workspace_result is not None and ledger_result is None:
                ledger.import_host_result(
                    role_id=role_id,
                    result=workspace_result,
                    allow_unverified_test_runner=allow_unverified_test_runner,
                )
        elif workspace_result is not None and ledger_result is None:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"canonical_result_without_ledger_admission:{role_id}"],
            )
        elif (
            workspace_result is not None
            and ledger_result is not None
            and workspace_result.get("result_sha256")
            != ledger_result.get("result_sha256")
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"ledger_projection_result_mismatch:{role_id}"],
            )

    ledger_results = ledger.canonical_results()
    pending = {
        role_id: result
        for role_id, result in ledger_results.items()
        if role_id not in workspace_results
    }
    while pending:
        progressed = False
        for task in tasks:
            role_id = str(task["role_id"])
            result = pending.get(role_id)
            if result is None:
                continue
            try:
                admit_agent_result(
                    workspace=workspace,
                    result=result,
                    role_id=role_id,
                )
            except ResearchOrganizationError:
                continue
            workspace_results[role_id] = result
            pending.pop(role_id)
            progressed = True
        if not progressed:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                [f"ledger_projection_dependencies:{','.join(sorted(pending))}"],
            )
    return workspace_results


def run_research_organization_runtime(
    *,
    workspace: Path,
    worktree: Path,
    private_root: Path,
    runner: ResearchOrgSessionRunner,
    max_attempts: int = 2,
    max_concurrency: int = 1,
    timeout_seconds: int = 1_800,
    trust_root: Path | None = None,
    installation_id: str | None = None,
    allow_unverified_test_runner: bool = False,
) -> dict[str, Any]:
    if max_attempts < 1 or max_attempts > 5:
        raise ValueError("max_attempts must be between 1 and 5")
    if max_concurrency < 1 or max_concurrency > 8:
        raise ValueError("max_concurrency must be between 1 and 8")
    if timeout_seconds < 60 or timeout_seconds > 3_300:
        raise ValueError("timeout_seconds must be between 60 and 3300")
    workspace = Path(workspace).expanduser().resolve(strict=True)
    worktree = Path(worktree).expanduser().resolve(strict=True)
    private_root = _safe_private_root(workspace, private_root)
    if not allow_unverified_test_runner and (
        trust_root is None or not installation_id
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["formal_runtime_requires_trust_root_and_installation_id"],
        )
    trust_store: RuntimeTrustStore | None = None
    if trust_root is not None and installation_id:
        trust_store = ensure_runtime_trust_store(
            Path(trust_root),
            installation_id=installation_id,
        )
    validate_research_organization_bundle(workspace=workspace)
    plan = load_research_organization_plan(workspace)
    tasks, tasks_by_role = _load_tasks(workspace, plan)
    paths = _runtime_relatives(plan)
    runtime_id = f"runtime_{str(plan['plan_sha256'])[:20]}"
    policy = {
        "max_attempts_per_role": max_attempts,
        "max_concurrency": max_concurrency,
        "session_timeout_seconds": timeout_seconds,
        "host_only_canonical_admission": True,
        "private_output_transport": True,
        "staged_factor_context_only": True,
        "cancel_owned_sessions_only": True,
    }
    ledger = ResearchOrgRuntimeLedger(
        private_root=private_root,
        runtime_id=runtime_id,
        identity=plan["identity"],
        plan_sha256=str(plan["plan_sha256"]),
        tasks=tasks,
        policy=policy,
        trust_store=trust_store,
    )
    _ensure_runtime_lock(workspace, paths, plan)
    with workspace_file_lock(workspace, paths["lock"]):
        state = _load_or_create_state(
            workspace=workspace,
            paths=paths,
            plan=plan,
            tasks=tasks,
            max_attempts=max_attempts,
            max_concurrency=max_concurrency,
            timeout_seconds=timeout_seconds,
            trust_manifest=(
                trust_store.public_manifest if trust_store is not None else None
            ),
            allow_unverified_test_runner=allow_unverified_test_runner,
        )
        _reconcile_projection_event_head(
            workspace=workspace,
            paths=paths,
            state=state,
        )
        _recover_running_attempts(
            workspace=workspace,
            paths=paths,
            state=state,
            runner=runner,
            tasks_by_role=tasks_by_role,
            ledger=ledger,
            private_root=private_root,
            max_attempts=max_attempts,
        )
        if (workspace / paths["cancel"]).is_file():
            ledger.request_cancel(
                requested_by="workspace_cancel_projection",
                reason="workspace cancel request present at scheduler start",
            )
            scheduler_epoch = int(ledger.snapshot()["scheduler_epoch"])
        else:
            scheduler_epoch = ledger.start_scheduler()
        _reconcile_ledger_results(
            workspace=workspace,
            tasks=tasks,
            ledger=ledger,
            allow_unverified_test_runner=allow_unverified_test_runner,
        )
        _append_event(
            workspace=workspace,
            paths=paths,
            state=state,
            event_type="DISPATCHER_STARTED",
            detail={
                "max_concurrency": max_concurrency,
                "scheduler_epoch": scheduler_epoch,
                "authority": "host_private_sqlite",
            },
        )
        while True:
            results = _canonical_results(workspace, tasks)
            _refresh_role_states(state=state, tasks=tasks, results=results)
            state["lifecycle"] = _lifecycle(state, results)
            if (workspace / paths["cancel"]).is_file():
                ledger.request_cancel(
                    requested_by="workspace_cancel_projection",
                    reason="workspace cancel request observed by scheduler",
                )
                for role_state in state["roles"].values():
                    if role_state["status"] in {"READY", "PENDING", "WAITING_HOST"}:
                        role_state["status"] = "CANCELLED"
                state["lifecycle"] = "CANCELLED"
                break
            ready = [
                task
                for task in tasks
                if state["roles"][str(task["role_id"])]["status"] == "READY"
                and len(
                    state["roles"][str(task["role_id"])]["attempt_ids"]
                )
                < max_attempts
            ]
            if not ready:
                break
            wave = ready[:max_concurrency]
            prepared: list[
                tuple[
                    Mapping[str, Any],
                    ResearchOrgSessionInvocation,
                    dict[str, Any],
                    dict[str, str],
                ]
            ] = []
            for task in wave:
                invocation, context, relatives = _prepare_attempt(
                    workspace=workspace,
                    worktree=worktree,
                    private_root=private_root,
                    paths=paths,
                    state=state,
                    task=task,
                    tasks_by_role=tasks_by_role,
                    timeout_seconds=timeout_seconds,
                    ledger=ledger,
                    scheduler_epoch=scheduler_epoch,
                )
                prepared.append((task, invocation, context, relatives))
                _append_event(
                    workspace=workspace,
                    paths=paths,
                    state=state,
                    event_type="SESSION_ATTEMPT_STARTED",
                    role_id=str(task["role_id"]),
                    attempt_id=invocation.attempt_id,
                    detail={
                        "session_id": invocation.session_id,
                        "runtime_instance_id": invocation.runtime_instance_id,
                    },
                )
            state["lifecycle"] = "RUNNING"
            _write_state(workspace, paths["state"], state)
            outcomes: dict[str, ResearchOrgSessionOutcome] = {}
            with ThreadPoolExecutor(max_workers=len(prepared)) as executor:
                future_map = {
                    executor.submit(_invoke_session, runner, invocation): invocation
                    for _task, invocation, _context, _relatives in prepared
                }
                for future in as_completed(future_map):
                    invocation = future_map[future]
                    outcomes[invocation.attempt_id] = future.result()
            for task, invocation, context, relatives in prepared:
                _finalize_attempt(
                    workspace=workspace,
                    paths=paths,
                    state=state,
                    task=task,
                    invocation=invocation,
                    context=context,
                    relatives=relatives,
                    outcome=outcomes[invocation.attempt_id],
                    max_attempts=max_attempts,
                    ledger=ledger,
                    tasks=tasks,
                    allow_unverified_test_runner=allow_unverified_test_runner,
                )
            _write_state(workspace, paths["state"], state)
        results = _canonical_results(workspace, tasks)
        _refresh_role_states(state=state, tasks=tasks, results=results)
        state["lifecycle"] = _lifecycle(state, results)
        ledger_state = ledger.finish_scheduler()
        _append_event(
            workspace=workspace,
            paths=paths,
            state=state,
            event_type="DISPATCHER_STOPPED",
            detail={
                "lifecycle": state["lifecycle"],
                "ledger_state": ledger_state,
            },
        )
        _write_state(workspace, paths["state"], state)
    return validate_research_organization_runtime(
        workspace=workspace,
        private_root=private_root,
        trust_root=trust_root,
        installation_id=installation_id,
        require_formal=False,
    )


def request_research_organization_cancel(
    *,
    workspace: Path,
    requested_by: str,
    reason: str,
    private_root: Path | None = None,
    trust_root: Path | None = None,
    installation_id: str | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve(strict=True)
    validate_research_organization_bundle(workspace=workspace)
    plan = load_research_organization_plan(workspace)
    paths = _runtime_relatives(plan)
    runtime_state_path = workspace / paths["state"]
    if not runtime_state_path.exists() and not runtime_state_path.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_MISSING,
            [paths["state"]],
        )
    if runtime_state_path.is_symlink() or not runtime_state_path.is_file():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["runtime_state_unsafe"],
        )
    if private_root is not None:
        state = read_workspace_json(workspace, paths["state"])
        tasks, _tasks_by_role = _load_tasks(workspace, plan)
        policy = state.get("policy")
        if not isinstance(policy, dict):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
                ["runtime_policy_missing"],
            )
        trust_store = None
        if trust_root is not None and installation_id:
            trust_store = load_runtime_trust_store(
                Path(trust_root),
                installation_id=installation_id,
            )
        ledger = ResearchOrgRuntimeLedger(
            private_root=Path(private_root),
            runtime_id=str(state["runtime_id"]),
            identity=plan["identity"],
            plan_sha256=str(plan["plan_sha256"]),
            tasks=tasks,
            policy=policy,
            trust_store=trust_store,
            existing_only=True,
        )
        ledger.request_cancel(requested_by=requested_by, reason=reason)
    payload = with_content_hash(
        {
            "contract_version": "factorforge_research_org_cancel_request_v1",
            "identity": dict(plan["identity"]),
            "plan_ref": {"path": PLAN_RELATIVE_PATH, "sha256": plan["plan_sha256"]},
            "requested_by": requested_by,
            "reason": reason,
            "requested_at_utc": utc_now(),
        },
        hash_field="cancel_sha256",
    )
    with workspace_file_lock(workspace, PLAN_RELATIVE_PATH):
        try:
            write_workspace_json_once(workspace, paths["cancel"], payload)
        except FileExistsError:
            existing = read_workspace_json(workspace, paths["cancel"])
            return existing
    return payload


def _closed_directory(
    path: Path,
    *,
    expected_files: set[str],
    expected_directories: set[str],
    label: str,
) -> list[str]:
    if path.is_symlink() or not path.is_dir():
        return [f"{label}:unsafe_or_missing"]
    files: set[str] = set()
    directories: set[str] = set()
    reasons: list[str] = []
    for child in path.iterdir():
        if child.is_symlink():
            reasons.append(f"{label}:symlink:{child.name}")
        elif child.is_file():
            files.add(child.name)
        elif child.is_dir():
            directories.add(child.name)
        else:
            reasons.append(f"{label}:special:{child.name}")
    if files != expected_files:
        reasons.append(
            f"{label}:files:{','.join(sorted(files))}"
        )
    if directories != expected_directories:
        reasons.append(
            f"{label}:directories:{','.join(sorted(directories))}"
        )
    return reasons


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _expected_stopped_role_statuses(
    *,
    task: Mapping[str, Any],
    role_state: Mapping[str, Any],
    results: Mapping[str, Mapping[str, Any]],
    cancel_exists: bool,
    max_attempts: int,
) -> set[str]:
    role_id = str(task["role_id"])
    result = results.get(role_id)
    if result is not None:
        return {str(result.get("status"))}
    if cancel_exists:
        allowed = {"CANCELLED"}
        if len(role_state.get("attempt_ids") or []) >= max_attempts:
            allowed.add("RETRY_EXHAUSTED")
        return allowed
    if task["session_policy"]["requirement"] == "host_session":
        return {"WAITING_HOST"}
    if (
        role_state.get("status") == "RETRY_EXHAUSTED"
        and _is_non_empty_string(role_state.get("last_error"))
    ):
        return {"RETRY_EXHAUSTED"}
    if len(role_state.get("attempt_ids") or []) >= max_attempts:
        return {"RETRY_EXHAUSTED"}
    if _dependencies_pass(task, results):
        return {"READY"}
    return {"PENDING"}


def validate_research_organization_runtime(
    *,
    workspace: Path,
    require_complete: bool = False,
    private_root: Path | None = None,
    trust_root: Path | None = None,
    installation_id: str | None = None,
    require_formal: bool = False,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve(strict=True)
    bundle = validate_research_organization_bundle(workspace=workspace)
    plan = load_research_organization_plan(workspace)
    tasks, tasks_by_role = _load_tasks(workspace, plan)
    paths = _runtime_relatives(plan)
    runtime_state_path = workspace / paths["state"]
    if not runtime_state_path.exists() and not runtime_state_path.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_MISSING,
            [paths["state"]],
        )
    if runtime_state_path.is_symlink() or not runtime_state_path.is_file():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_RUNTIME_INVALID,
            ["runtime_state_unsafe"],
        )
    state = read_workspace_json(workspace, paths["state"])
    reasons: list[str] = []
    expected_state_fields = {
        "contract_version",
        "runtime_id",
        "identity",
        "plan_ref",
        "lifecycle",
        "created_at_utc",
        "updated_at_utc",
        "policy",
        "authority",
        "roles",
        "attempt_count",
        "last_event_sequence",
        "last_event_sha256",
        "state_sha256",
    }
    if set(state) != expected_state_fields:
        reasons.append("runtime_state.fields")
    if state.get("contract_version") != RUNTIME_STATE_CONTRACT_VERSION:
        reasons.append("runtime_state.contract_version")
    reasons.extend(
        validate_content_hash(state, hash_field="state_sha256", label="runtime_state")
    )
    if state.get("identity") != plan.get("identity"):
        reasons.append("runtime_state.identity")
    if state.get("plan_ref") != {
        "path": PLAN_RELATIVE_PATH,
        "sha256": plan.get("plan_sha256"),
    }:
        reasons.append("runtime_state.plan_ref")
    if state.get("runtime_id") != f"runtime_{str(plan['plan_sha256'])[:20]}":
        reasons.append("runtime_state.runtime_id")
    if state.get("lifecycle") not in VALID_RUNTIME_LIFECYCLES:
        reasons.append("runtime_state.lifecycle")
    if (
        not _is_non_empty_string(state.get("created_at_utc"))
        or not _is_non_empty_string(state.get("updated_at_utc"))
        or type(state.get("attempt_count")) is not int
        or int(state.get("attempt_count") or 0) < 0
        or type(state.get("last_event_sequence")) is not int
        or int(state.get("last_event_sequence") or 0) < 0
    ):
        reasons.append("runtime_state.scalar_fields")
    policy = state.get("policy")
    if not isinstance(policy, dict) or set(policy) != {
        "max_attempts_per_role",
        "max_concurrency",
        "session_timeout_seconds",
        "host_only_canonical_admission",
        "private_output_transport",
        "staged_factor_context_only",
        "cancel_owned_sessions_only",
    }:
        reasons.append("runtime_state.policy")
        policy = {}
    if (
        type(policy.get("max_attempts_per_role")) is not int
        or not 1 <= int(policy.get("max_attempts_per_role") or 0) <= 5
        or type(policy.get("max_concurrency")) is not int
        or not 1 <= int(policy.get("max_concurrency") or 0) <= 8
        or type(policy.get("session_timeout_seconds")) is not int
        or not 60 <= int(policy.get("session_timeout_seconds") or 0) <= 3_300
        or policy.get("host_only_canonical_admission") is not True
        or policy.get("private_output_transport") is not True
        or policy.get("staged_factor_context_only") is not True
        or policy.get("cancel_owned_sessions_only") is not True
    ):
        reasons.append("runtime_state.policy_values")
    authority = state.get("authority")
    if (
        not isinstance(authority, dict)
        or set(authority)
        != {
            "ledger_contract_version",
            "ledger_storage",
            "workspace_json_semantics",
            "signed_adapter_receipts_required",
            "trust_manifest",
        }
        or authority.get("ledger_contract_version") != LEDGER_CONTRACT_VERSION
        or authority.get("ledger_storage") != "host_private_not_workspace"
        or authority.get("workspace_json_semantics")
        != "rebuildable_projection_only"
        or type(authority.get("signed_adapter_receipts_required")) is not bool
        or (
            authority.get("signed_adapter_receipts_required") is True
            and not isinstance(authority.get("trust_manifest"), dict)
        )
    ):
        reasons.append("runtime_state.authority")

    runtime_root = workspace / paths["root"]
    cancel_exists = (workspace / paths["cancel"]).exists() or (
        workspace / paths["cancel"]
    ).is_symlink()
    reasons.extend(
        _closed_directory(
            runtime_root,
            expected_files={
                RUNTIME_STATE_NAME,
                RUNTIME_LOCK_NAME,
                *({RUNTIME_CANCEL_NAME} if cancel_exists else set()),
            },
            expected_directories={"events", "attempts"},
            label="runtime_root",
        )
    )
    try:
        lock = read_workspace_json(workspace, paths["lock"])
    except ResearchOrganizationError as exc:
        reasons.append(str(exc))
    else:
        if (
            set(lock)
            != {"contract_version", "identity", "plan_ref", "lock_sha256"}
            or lock.get("contract_version")
            != "factorforge_research_org_runtime_lock_v1"
            or lock.get("identity") != plan.get("identity")
            or lock.get("plan_ref")
            != {"path": PLAN_RELATIVE_PATH, "sha256": plan.get("plan_sha256")}
            or validate_content_hash(lock, hash_field="lock_sha256", label="runtime_lock")
        ):
            reasons.append("runtime_lock.contract")
    if cancel_exists:
        try:
            cancel = read_workspace_json(workspace, paths["cancel"])
        except ResearchOrganizationError as exc:
            reasons.append(str(exc))
        else:
            if (
                set(cancel)
                != {
                    "contract_version",
                    "identity",
                    "plan_ref",
                    "requested_by",
                    "reason",
                    "requested_at_utc",
                    "cancel_sha256",
                }
                or cancel.get("contract_version")
                != "factorforge_research_org_cancel_request_v1"
                or cancel.get("identity") != plan.get("identity")
                or cancel.get("plan_ref")
                != {"path": PLAN_RELATIVE_PATH, "sha256": plan.get("plan_sha256")}
                or validate_content_hash(
                    cancel,
                    hash_field="cancel_sha256",
                    label="runtime_cancel",
                )
                or not isinstance(cancel.get("requested_by"), str)
                or not str(cancel.get("requested_by") or "").strip()
                or not isinstance(cancel.get("reason"), str)
                or not str(cancel.get("reason") or "").strip()
            ):
                reasons.append("runtime_cancel.contract")
    results = _canonical_results(workspace, tasks)
    role_states = state.get("roles")
    if not isinstance(role_states, dict) or set(role_states) != set(tasks_by_role):
        reasons.append("runtime_state.roles")
        role_states = {}
    expected_attempt_roles = {
        role_id
        for role_id, role_state in role_states.items()
        if isinstance(role_state, dict) and role_state.get("attempt_ids")
    }
    reasons.extend(
        _closed_directory(
            workspace / paths["attempts"],
            expected_files=set(),
            expected_directories=expected_attempt_roles,
            label="runtime_attempts",
        )
    )
    session_ids: set[str] = set()
    runtime_instance_ids: set[str] = set()
    admitted_receipts: dict[str, dict[str, Any]] = {}
    latest_receipts: dict[str, dict[str, Any]] = {}
    receipt_count = 0
    observed_attempt_count = 0
    for role_id, task in tasks_by_role.items():
        role_state = role_states.get(role_id)
        if not isinstance(role_state, dict):
            continue
        if set(role_state) != {
            "task_id",
            "task_sha256",
            "session_requirement",
            "status",
            "attempt_ids",
            "active_attempt_id",
            "result_status",
            "last_error",
        }:
            reasons.append(f"role_state.fields:{role_id}")
        if role_state.get("status") not in VALID_ROLE_RUNTIME_STATES:
            reasons.append(f"role_state.status:{role_id}")
        if (
            role_state.get("task_id") != task.get("task_id")
            or role_state.get("task_sha256") != task.get("task_sha256")
            or role_state.get("session_requirement")
            != task.get("session_policy", {}).get("requirement")
        ):
            reasons.append(f"role_state.task_id:{role_id}")
        if role_state.get("active_attempt_id") is not None:
            reasons.append(f"role_state.active_attempt:{role_id}")
        expected_statuses = _expected_stopped_role_statuses(
            task=task,
            role_state=role_state,
            results=results,
            cancel_exists=cancel_exists,
            max_attempts=int(policy.get("max_attempts_per_role") or 0),
        )
        if role_state.get("status") not in expected_statuses:
            reasons.append(f"role_state.derived_status:{role_id}")
        result = results.get(role_id)
        expected_result_status = result.get("status") if result is not None else None
        if role_state.get("result_status") != expected_result_status:
            reasons.append(f"role_state.result_status:{role_id}")
        attempt_ids = role_state.get("attempt_ids")
        if not isinstance(attempt_ids, list) or len(attempt_ids) != len(set(attempt_ids)):
            reasons.append(f"role_state.attempt_ids:{role_id}")
            continue
        if attempt_ids:
            reasons.extend(
                _closed_directory(
                    workspace / paths["attempts"] / role_id,
                    expected_files=set(),
                    expected_directories=set(attempt_ids),
                    label=f"runtime_attempt_role:{role_id}",
                )
            )
        for index, attempt_id in enumerate(attempt_ids, start=1):
            observed_attempt_count += 1
            if not isinstance(attempt_id, str):
                reasons.append(f"attempt_id:{role_id}")
                continue
            relatives = _attempt_relatives(
                paths,
                role_id=role_id,
                attempt_id=attempt_id,
            )
            reasons.extend(
                _closed_directory(
                    workspace / relatives["root"],
                    expected_files={
                        "context_manifest.json",
                        "attempt.json",
                        "session_receipt.json",
                    },
                    expected_directories=set(),
                    label=f"runtime_attempt:{role_id}:{attempt_id}",
                )
            )
            try:
                context = read_workspace_json(workspace, relatives["context"])
                attempt = read_workspace_json(workspace, relatives["attempt"])
                receipt = read_workspace_json(workspace, relatives["receipt"])
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
                continue
            receipt_count += 1
            latest_receipts[role_id] = receipt
            expected_context_fields = {
                "contract_version",
                "identity",
                "task_ref",
                "role_id",
                "session_id",
                "runtime_id",
                "scheduler_epoch",
                "idempotency_key",
                "adapter_challenge",
                "dependency_admissions",
                "factor_workspace_visibility",
                "canonical_workspace_write_access",
                "files",
                "context_sha256",
            }
            expected_task_ref = {
                "task_id": task["task_id"],
                "sha256": task["task_sha256"],
            }
            if (
                set(context) != expected_context_fields
                or context.get("contract_version")
                != RUNTIME_CONTEXT_CONTRACT_VERSION
                or context.get("identity") != task.get("identity")
                or context.get("task_ref") != expected_task_ref
                or context.get("role_id") != role_id
                or not _is_non_empty_string(context.get("session_id"))
                or context.get("runtime_id") != state.get("runtime_id")
                or type(context.get("scheduler_epoch")) is not int
                or int(context.get("scheduler_epoch") or 0) < 1
                or not _is_sha256(context.get("idempotency_key"))
                or not isinstance(context.get("adapter_challenge"), str)
                or not re.fullmatch(
                    r"[0-9a-f]{32}",
                    str(context.get("adapter_challenge") or ""),
                )
                or not isinstance(context.get("dependency_admissions"), list)
                or context.get("factor_workspace_visibility")
                != "staged_files_only"
                or context.get("canonical_workspace_write_access") is not False
                or validate_content_hash(
                    context,
                    hash_field="context_sha256",
                    label="runtime_context",
                )
            ):
                reasons.append(f"context_contract:{role_id}:{attempt_id}")
            context_files = context.get("files")
            if not isinstance(context_files, list):
                reasons.append(f"context_files:{role_id}:{attempt_id}")
                context_files = []
            expected_sources = _context_source_paths(
                workspace,
                task,
                tasks_by_role,
            )
            actual_sources = [
                item.get("path") if isinstance(item, dict) else None
                for item in context_files
            ]
            if actual_sources != expected_sources:
                reasons.append(f"context_sources:{role_id}:{attempt_id}")
            dependency_admissions = context.get("dependency_admissions")
            if not isinstance(dependency_admissions, list) or len(
                {
                    item.get("role_id")
                    for item in dependency_admissions
                    if isinstance(item, dict)
                }
            ) != len(dependency_admissions):
                reasons.append(f"context_dependencies:{role_id}:{attempt_id}")
                dependency_admissions = []
            for dependency in dependency_admissions:
                if (
                    not isinstance(dependency, dict)
                    or set(dependency)
                    != {
                        "role_id",
                        "result_sha256",
                        "admission_receipt_id",
                        "event_seq",
                    }
                    or not _is_non_empty_string(dependency.get("role_id"))
                    or not _is_sha256(dependency.get("result_sha256"))
                    or not _is_sha256(dependency.get("admission_receipt_id"))
                    or type(dependency.get("event_seq")) is not int
                    or int(dependency.get("event_seq") or 0) < 1
                ):
                    reasons.append(f"context_dependency:{role_id}:{attempt_id}")
            for reference in context_files:
                if (
                    not isinstance(reference, dict)
                    or set(reference) != {"path", "sha256", "size_bytes"}
                    or not _is_sha256(reference.get("sha256"))
                    or type(reference.get("size_bytes")) is not int
                    or int(reference.get("size_bytes") or -1) < 0
                ):
                    reasons.append(f"context_reference:{role_id}:{attempt_id}")
                    continue
                try:
                    source_payload = read_workspace_bytes(
                        workspace,
                        str(reference.get("path") or ""),
                        max_bytes=MAX_STAGED_CONTEXT_BYTES,
                    )
                except ResearchOrganizationError:
                    reasons.append(f"context_source_hash:{role_id}:{attempt_id}")
                    continue
                if (
                    hashlib.sha256(source_payload).hexdigest()
                    != reference.get("sha256")
                    or len(source_payload) != reference.get("size_bytes")
                ):
                    reasons.append(f"context_source_hash:{role_id}:{attempt_id}")

            expected_attempt_fields = {
                "contract_version",
                "runtime_id",
                "identity",
                "task_ref",
                "role_id",
                "attempt_id",
                "attempt_number",
                "session_id",
                "runtime_instance_id",
                "context_ref",
                "session_requirement",
                "started_at_utc",
                "status",
                "ledger_ref",
                "attempt_sha256",
            }
            if (
                set(attempt) != expected_attempt_fields
                or attempt.get("contract_version")
                != RUNTIME_ATTEMPT_CONTRACT_VERSION
                or validate_content_hash(
                    attempt,
                    hash_field="attempt_sha256",
                    label="runtime_attempt",
                )
                or attempt.get("attempt_id") != attempt_id
                or attempt.get("attempt_number") != index
                or type(attempt.get("attempt_number")) is not int
                or attempt.get("role_id") != role_id
                or attempt.get("runtime_id") != state.get("runtime_id")
                or attempt.get("identity") != task.get("identity")
                or attempt.get("session_requirement")
                != task.get("session_policy", {}).get("requirement")
                or attempt.get("status") != "RUNNING"
                or not _is_non_empty_string(attempt.get("session_id"))
                or not _is_non_empty_string(attempt.get("runtime_instance_id"))
                or not _is_non_empty_string(attempt.get("started_at_utc"))
                or context.get("session_id") != attempt.get("session_id")
                or attempt.get("task_ref") != expected_task_ref
                or attempt.get("context_ref")
                != {
                    "path": relatives["context"],
                    "sha256": context.get("context_sha256"),
                }
                or attempt.get("ledger_ref")
                != {
                    "contract_version": LEDGER_CONTRACT_VERSION,
                    "scheduler_epoch": context.get("scheduler_epoch"),
                    "dispatch_event_seq": (
                        attempt.get("ledger_ref", {}).get("dispatch_event_seq")
                        if isinstance(attempt.get("ledger_ref"), dict)
                        else None
                    ),
                    "idempotency_key": context.get("idempotency_key"),
                }
                or not isinstance(attempt.get("ledger_ref"), dict)
                or type(attempt.get("ledger_ref", {}).get("dispatch_event_seq"))
                is not int
                or int(attempt.get("ledger_ref", {}).get("dispatch_event_seq") or 0)
                < 1
            ):
                reasons.append(f"attempt_contract:{role_id}:{attempt_id}")

            expected_receipt_fields = {
                "contract_version",
                "runtime_id",
                "identity",
                "task_ref",
                "role_id",
                "attempt_id",
                "attempt_number",
                "session_id",
                "runtime_instance_id",
                "status",
                "started_at_utc",
                "finished_at_utc",
                "returncode",
                "provider",
                "model",
                "transport",
                "isolation",
                "private_output",
                "canonical_result_ref",
                "cancelled",
                "error_code",
                "retryable",
                "stdout_tail_sha256",
                "stderr_tail_sha256",
                "ledger_receipt_ref",
                "receipt_sha256",
            }
            if (
                set(receipt) != expected_receipt_fields
                or receipt.get("contract_version")
                != SESSION_RECEIPT_CONTRACT_VERSION
                or validate_content_hash(
                    receipt,
                    hash_field="receipt_sha256",
                    label="session_receipt",
                )
                or receipt.get("attempt_id") != attempt_id
                or receipt.get("session_id") != attempt.get("session_id")
                or receipt.get("runtime_instance_id")
                != attempt.get("runtime_instance_id")
                or receipt.get("task_ref") != attempt.get("task_ref")
                or receipt.get("role_id") != role_id
                or receipt.get("runtime_id") != state.get("runtime_id")
                or receipt.get("identity") != task.get("identity")
                or receipt.get("attempt_number") != index
                or type(receipt.get("attempt_number")) is not int
                or type(receipt.get("returncode")) is not int
                or type(receipt.get("cancelled")) is not bool
                or type(receipt.get("retryable")) is not bool
                or receipt.get("status")
                not in {"ADMITTED", "FAILED", "CANCELLED", "ABANDONED"}
                or any(
                    not _is_non_empty_string(receipt.get(field))
                    for field in (
                        "started_at_utc",
                        "finished_at_utc",
                        "provider",
                        "model",
                        "transport",
                    )
                )
                or not _is_sha256(receipt.get("stdout_tail_sha256"))
                or not _is_sha256(receipt.get("stderr_tail_sha256"))
            ):
                reasons.append(f"receipt_contract:{role_id}:{attempt_id}")
            ledger_receipt_ref = receipt.get("ledger_receipt_ref")
            if (
                not isinstance(ledger_receipt_ref, dict)
                or set(ledger_receipt_ref)
                != {
                    "ledger_contract_version",
                    "adapter_receipt_id",
                    "host_admission_receipt_id",
                    "evidence_class",
                }
                or ledger_receipt_ref.get("ledger_contract_version")
                != LEDGER_CONTRACT_VERSION
                or ledger_receipt_ref.get("evidence_class")
                not in {"signed_adapter", "unverified_test", "host_recovery"}
                or (
                    ledger_receipt_ref.get("adapter_receipt_id") is not None
                    and not _is_sha256(
                        ledger_receipt_ref.get("adapter_receipt_id")
                    )
                )
                or (
                    ledger_receipt_ref.get("host_admission_receipt_id") is not None
                    and not _is_sha256(
                        ledger_receipt_ref.get("host_admission_receipt_id")
                    )
                )
            ):
                reasons.append(f"receipt_ledger_ref:{role_id}:{attempt_id}")
            session_id = str(receipt.get("session_id") or "")
            runtime_instance_id = str(receipt.get("runtime_instance_id") or "")
            if session_id in session_ids or runtime_instance_id in runtime_instance_ids:
                reasons.append(f"receipt_identity_reuse:{role_id}:{attempt_id}")
            session_ids.add(session_id)
            runtime_instance_ids.add(runtime_instance_id)
            isolation = (
                receipt.get("isolation")
                if isinstance(receipt.get("isolation"), dict)
                else {}
            )
            expected_isolation_fields = {
                "class",
                "factor_workspace_visibility",
                "canonical_workspace_write_access",
                "owned_termination_supported",
                "context_manifest_sha256",
                "context_unchanged_after_run",
            }
            if (
                set(isolation) != expected_isolation_fields
                or not _is_non_empty_string(isolation.get("class"))
                or isolation.get("factor_workspace_visibility")
                != "staged_files_only"
                or isolation.get("canonical_workspace_write_access") is not False
                or type(isolation.get("owned_termination_supported")) is not bool
                or type(isolation.get("context_unchanged_after_run")) is not bool
                or isolation.get("context_manifest_sha256")
                != context.get("context_sha256")
            ):
                reasons.append(f"receipt_context_proof:{role_id}:{attempt_id}")

            private_output = (
                receipt.get("private_output")
                if isinstance(receipt.get("private_output"), dict)
                else {}
            )
            if (
                set(private_output)
                != {"retention", "sha256", "size_bytes", "secret_scan"}
                or private_output.get("retention")
                != "operator_private_not_canonical"
                or private_output.get("secret_scan")
                not in {"PASS", "NOT_AVAILABLE"}
            ):
                reasons.append(f"receipt_private_output:{role_id}:{attempt_id}")
            if private_output.get("sha256") is None:
                if (
                    private_output.get("size_bytes") is not None
                    or private_output.get("secret_scan") != "NOT_AVAILABLE"
                ):
                    reasons.append(
                        f"receipt_private_output_missing:{role_id}:{attempt_id}"
                    )
            elif (
                not _is_sha256(private_output.get("sha256"))
                or type(private_output.get("size_bytes")) is not int
                or not 0 < int(private_output.get("size_bytes") or 0)
                <= MAX_PRIVATE_OUTPUT_BYTES
                or private_output.get("secret_scan") != "PASS"
            ):
                reasons.append(f"receipt_private_output_hash:{role_id}:{attempt_id}")

            receipt_status = receipt.get("status")
            if receipt_status == "ADMITTED":
                if (
                    receipt.get("returncode") != 0
                    or receipt.get("cancelled") is not False
                    or receipt.get("error_code") is not None
                    or receipt.get("retryable") is not False
                    or private_output.get("sha256") is None
                    or isolation.get("owned_termination_supported") is not True
                    or isolation.get("context_unchanged_after_run") is not True
                    or (
                        task["session_policy"]["requirement"]
                        in {"isolated_session", "independent_session"}
                        and isolation.get("class") not in STRONG_ISOLATION_CLASSES
                    )
                ):
                    reasons.append(f"receipt_admitted_proof:{role_id}:{attempt_id}")
                if role_id in admitted_receipts:
                    reasons.append(f"receipt_multiple_admissions:{role_id}")
                admitted_receipts[role_id] = receipt
            else:
                if receipt.get("canonical_result_ref") is not None:
                    reasons.append(
                        f"receipt_unadmitted_result_ref:{role_id}:{attempt_id}"
                    )
                if not _is_non_empty_string(receipt.get("error_code")):
                    reasons.append(f"receipt_error_code:{role_id}:{attempt_id}")
            if receipt_status == "ABANDONED" and (
                receipt.get("returncode") != 125
                or receipt.get("cancelled") is not True
                or isolation.get("owned_termination_supported") is not True
                or private_output.get("sha256") is not None
            ):
                reasons.append(f"receipt_abandoned_proof:{role_id}:{attempt_id}")
            if receipt_status == "CANCELLED" and receipt.get("error_code") != (
                BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED
            ):
                reasons.append(f"receipt_cancel_proof:{role_id}:{attempt_id}")
            if receipt_status == "CANCELLED" and receipt.get("retryable") is not False:
                reasons.append(f"receipt_cancel_retry:{role_id}:{attempt_id}")
            if receipt_status == "FAILED" and receipt.get("error_code") != (
                BLOCK_RESEARCH_ORG_SESSION_FAILED
            ):
                reasons.append(f"receipt_failure_proof:{role_id}:{attempt_id}")
            if receipt_status != "ADMITTED" and role_id in admitted_receipts:
                # An admitted receipt must be terminal for this immutable role result.
                reasons.append(f"receipt_unadmitted_result_ref:{role_id}:{attempt_id}")
    for role_id, role_state in role_states.items():
        task = tasks_by_role[role_id]
        if (
            task["session_policy"]["requirement"] == "host_session"
            or role_id in results
            or cancel_exists
        ):
            continue
        latest = latest_receipts.get(role_id)
        if latest is None:
            continue
        expected_terminal_status = (
            "READY"
            if latest.get("retryable") is True
            and len(role_state.get("attempt_ids") or [])
            < int(policy.get("max_attempts_per_role") or 0)
            else "RETRY_EXHAUSTED"
        )
        if role_state.get("status") != expected_terminal_status:
            reasons.append(f"role_state.retry_disposition:{role_id}")
    for role_id, result in results.items():
        task = tasks_by_role[role_id]
        if task["session_policy"]["requirement"] == "host_session":
            continue
        receipt = admitted_receipts.get(role_id)
        if (
            receipt is None
            or receipt.get("session_id") != result.get("session_id")
            or receipt.get("canonical_result_ref")
            != {
                "path": task["expected_result_path"],
                "sha256": result.get("result_sha256"),
            }
        ):
            reasons.append(f"result_receipt_binding:{role_id}")
    if observed_attempt_count != state.get("attempt_count"):
        reasons.append("runtime_state.attempt_count")
    previous_sha: str | None = None
    event_count = int(state.get("last_event_sequence") or 0)
    reasons.extend(
        _closed_directory(
            workspace / paths["events"],
            expected_files={
                f"event_{sequence:06d}.json"
                for sequence in range(1, event_count + 1)
            },
            expected_directories=set(),
            label="runtime_events",
        )
    )
    event_types = {
        "DISPATCHER_STARTED",
        "DISPATCHER_STOPPED",
        "SESSION_ATTEMPT_STARTED",
        "SESSION_RESULT_ADMITTED",
        "SESSION_CANCELLED",
        "SESSION_ATTEMPT_FAILED",
        "ABANDONED_SESSION_TERMINATED",
    }
    for sequence in range(1, event_count + 1):
        relative = f"{paths['events']}/event_{sequence:06d}.json"
        try:
            event = read_workspace_json(workspace, relative)
        except ResearchOrganizationError as exc:
            reasons.append(str(exc))
            continue
        if (
            set(event)
            != {
                "contract_version",
                "runtime_id",
                "identity",
                "sequence",
                "event_type",
                "role_id",
                "attempt_id",
                "occurred_at_utc",
                "previous_event_sha256",
                "detail",
                "event_sha256",
            }
            or event.get("contract_version") != RUNTIME_EVENT_CONTRACT_VERSION
            or validate_content_hash(event, hash_field="event_sha256", label="runtime_event")
            or event.get("sequence") != sequence
            or event.get("runtime_id") != state.get("runtime_id")
            or event.get("identity") != state.get("identity")
            or event.get("event_type") not in event_types
            or not _is_non_empty_string(event.get("occurred_at_utc"))
            or not isinstance(event.get("detail"), dict)
            or event.get("previous_event_sha256") != previous_sha
        ):
            reasons.append(f"event_chain:{sequence}")
        previous_sha = event.get("event_sha256")
    if previous_sha != state.get("last_event_sha256"):
        reasons.append("event_chain_head")
    expected_lifecycle = _lifecycle(state, results)
    if state.get("lifecycle") != expected_lifecycle:
        reasons.append("runtime_state.lifecycle_derived")
    if require_complete and state.get("lifecycle") != "COMPLETE":
        reasons.append("runtime_not_complete")
    if require_formal and private_root is None:
        reasons.append("formal_runtime_private_ledger_required")
    if reasons:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
            reasons,
        )
    output = {
        "verdict": "PASS",
        "contract_version": RUNTIME_STATE_CONTRACT_VERSION,
        "runtime_id": state["runtime_id"],
        "lifecycle": state["lifecycle"],
        "task_count": bundle["task_count"],
        "result_count": len(results),
        "receipt_count": receipt_count,
        "session_count": len(session_ids),
        "role_states": {
            role_id: role_state["status"] for role_id, role_state in role_states.items()
        },
        "formal_independence_verified": False,
        "runtime_assurance": "workspace_runtime_projection_valid_only",
    }
    if private_root is not None:
        trust_store: RuntimeTrustStore | None = None
        signed_required = bool(
            (state.get("authority") or {}).get("signed_adapter_receipts_required")
        )
        if trust_root is not None and installation_id:
            trust_store = load_runtime_trust_store(
                Path(trust_root),
                installation_id=installation_id,
            )
        elif signed_required:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                ["formal_runtime_trust_store_required"],
            )
        ledger_path = (
            Path(private_root).expanduser()
            / str(state["runtime_id"])
            / "runtime_ledger.sqlite3"
        )
        if not ledger_path.is_file() or ledger_path.is_symlink():
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_RUNTIME_MISSING,
                ["host_private_runtime_ledger"],
            )
        ledger = ResearchOrgRuntimeLedger(
            private_root=Path(private_root),
            runtime_id=str(state["runtime_id"]),
            identity=plan["identity"],
            plan_sha256=str(plan["plan_sha256"]),
            tasks=tasks,
            policy=policy,
            trust_store=trust_store,
            existing_only=True,
            read_only=True,
        )
        ledger_projection_reasons: list[str] = []
        for binding in ledger.projection_bindings():
            relatives = _attempt_relatives(
                paths,
                role_id=str(binding["role_id"]),
                attempt_id=str(binding["attempt_id"]),
            )
            try:
                projected_context = read_workspace_json(
                    workspace,
                    relatives["context"],
                )
                projected_attempt = read_workspace_json(
                    workspace,
                    relatives["attempt"],
                )
                projected_receipt = read_workspace_json(
                    workspace,
                    relatives["receipt"],
                )
            except ResearchOrganizationError as exc:
                ledger_projection_reasons.append(str(exc))
                continue
            if (
                projected_context.get("context_sha256")
                != binding["context_manifest_sha256"]
                or projected_attempt.get("attempt_sha256")
                != binding["attempt_projection_sha256"]
                or projected_receipt.get("receipt_sha256")
                != binding["receipt_projection_sha256"]
            ):
                ledger_projection_reasons.append(
                    f"ledger_projection_hash:{binding['attempt_id']}"
                )
        ledger_results = ledger.canonical_results()
        for role_id, ledger_result in ledger_results.items():
            workspace_result = results.get(role_id)
            if (
                workspace_result is None
                or workspace_result.get("result_sha256")
                != ledger_result.get("result_sha256")
            ):
                ledger_projection_reasons.append(
                    f"ledger_result_projection:{role_id}"
                )
        if ledger_projection_reasons:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID,
                ledger_projection_reasons,
            )
        ledger_validation = ledger.validate(require_formal=require_formal)
        output["transactional_ledger"] = {
            key: value
            for key, value in ledger_validation.items()
            if key != "ledger_path"
        }
        output["formal_independence_verified"] = ledger_validation[
            "formal_independence_verified"
        ]
        output["runtime_assurance"] = ledger_validation["assurance"]
    return output
