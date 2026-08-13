from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from factor_factory.console.agent_adapter import (
    BLOCK_AGENT_ORPHANED_WRITER,
    BLOCK_AGENT_RUNTIME_UNAVAILABLE,
    AgentResumeTask,
    AgentRunResult,
    PreOosRootSynthesisTask,
    ResearchAgentAdapter,
    RESUME_MEMO_MAX_BYTES,
    RESUME_MEMO_COMPONENT_IDENTITY_FIELDS,
    RESUME_MEMO_IMMUTABLE_FIELDS,
    RESUME_MEMO_OPERATOR_FLAG_FIELDS,
)
from factor_factory.console.artifact_service import SafeArtifact, publish_official_artifacts
from factor_factory.console.catalog_health import (
    catalog_admission_projection,
    catalogs_healthy,
    require_catalogs_healthy,
)
from factor_factory.console.config import ConsoleConfig
from factor_factory.console.report_upload import (
    BLOCK_PDF_EXTRACTION_FAILED,
    ResearchAttachmentUpload,
    extract_pdf_markdown_isolated,
    write_bytes_atomic,
)
from factor_factory.console.conversation_ledger import (
    BLOCK_CONVERSATION_LEDGER_INVALID,
    CONVERSATION_LEDGER_MAX_MESSAGES,
    CONVERSATION_LEDGER_REFERENCE_FIELD,
    plan_conversation_checkpoints,
    validate_request_conversation_ledger,
    write_planned_checkpoints,
)
from factor_factory.console.council_ingress import (
    CouncilIngressTask,
    load_council_ingress_tasks,
)
from factor_factory.console.evo_resume import (
    EVO_V2_EXTERNAL_PAUSES,
    PROGRESS_CHILD_HANDOFF_AUTHORIZED,
    PROGRESS_CHILD_HANDOFF_READY,
    PROGRESS_HOST_CHECKPOINT_READY,
    PROGRESS_TERMINAL_CHECKPOINT_READY,
    PROGRESS_WAITING,
    EvoV2ExternalResumeError,
    assess_evo_v2_external_resume,
    is_evo_v2_external_pause,
)
from factor_factory.console.evo_child_runtime import (
    CHILD_EXECUTION_READY,
    CHILD_QUALIFICATION_READY,
    CHILD_QUALIFICATION_WAIT,
    CHILD_PHASE_READY,
    CHILD_RECOVERY_READY,
    CHILD_RESUME_READY,
    CHILD_TERMINAL,
    execute_evo_child_ready,
    load_evo_child_execution_baseline,
    load_latest_evo_child_execution_baseline,
    load_pending_evo_child_phase_inflight,
    materialize_evo_child_phase_inflight,
    materialize_evo_child_qualification_checkpoint,
    materialize_evo_child_phase_checkpoint,
    materialize_evo_child_terminal_checkpoint,
    prepare_evo_child_execution,
    validate_evo_child_execution_state,
    validate_evo_child_phase_checkpoint,
)
from factor_factory.console.evo_child_container import (
    resolve_evo_child_container_image_digest,
)
from factor_factory.console.evo_child_catalog import (
    evo_child_calendar_projection_paths,
    evo_child_catalog_projection_paths,
    materialize_evo_child_calendar_projection,
    materialize_evo_child_catalog_projection,
    materialize_host_job_frozen_catalog_snapshot,
    validate_materialized_evo_child_calendar_projection,
    validate_materialized_evo_child_catalog_projection,
)
from factor_factory.console.private_job_root import (
    PrivateJobRootError,
    ensure_host_private_job_root,
    ensure_host_private_job_subdirectory,
)
from factor_factory.console.models import (
    RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY,
    ResearchJob,
    ResearchRequest,
    validate_pilot_evaluation_request,
    validate_public_source_url,
)
from factor_factory.console.model_broker import normalize_deepseek_openclaw_model
from factor_factory.console.runner_health import probe_runner_health
from factor_factory.console.secret_safety import redact_secret_values
from factor_factory.console.store import ResearchJobStore, utc_now
from factor_factory.console.ultimate_reader import (
    UltimateRunSummary,
    read_current_ultimate_workspace,
    validate_current_ultimate_authority,
)
from factor_factory.console.web_research_plan import (
    required_web_resume_start_step,
    stable_json_hash,
    validate_plan,
    validate_materialized_web_research,
    write_text_atomic,
    write_web_research_packet,
)
from factor_factory.console.worktree_allocator import (
    FactorWorktreeAllocator,
    WorktreeAllocation,
    WorktreeAllocationError,
)
from factor_factory.console.workspace_transaction import workspace_transaction_lock
from factor_factory.research_workspace import load_workspace_manifest, validate_workspace_manifest
from factor_factory.research_org import (
    AGENT_RESULT_CONTRACT_VERSION,
    admit_agent_result,
    load_research_organization_plan,
    run_research_organization_runtime,
    validate_research_organization_bundle,
    validate_research_organization_runtime,
    write_research_organization_bundle,
)
from factor_factory.research_org.runtime_trust import (
    ensure_runtime_trust_store,
    load_runtime_trust_store,
)
from factor_factory.oos_exposure_incident import (
    ensure_empty_oos_exposure_private_registry,
    oos_exposure_private_registry_guard,
)
from factor_factory.research_org.contracts import with_content_hash
from factor_factory.research_org.director import (
    DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
)
from factor_factory.research_conjecture import research_protocol_paths
from factor_factory.researcher_memory import (
    BLOCK_MEMORY_STORE_INVALID,
    record_research_outcome,
)
from factor_factory.evo_memory_runtime import (
    BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID,
    BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
    is_validated_evo_v2_memory_runtime_enabled,
    load_evo_v2_memory_round_state,
    prepare_evo_v2_memory_round,
    register_terminal_historical_episode_candidate,
)
from factor_factory.evo_child_preregistration import (
    validate_and_resolve_evo_child_web_research_plan,
)
from factor_factory.pre_oos_human_bridge import (
    pre_oos_child_handoff_path,
    pre_oos_child_intent_path,
    pre_oos_human_approval_path,
)
from factor_factory.mechanism_math.main_agent_memo import (
    CONTRACT_VERSION,
    MAX_MECHANISM_MEMO_REVISIONS,
    REQUIRED_QA_FIELDS,
    project_public_observed_metric_conflict_keys,
    project_public_observed_metrics,
    validate_main_agent_mechanism_memo,
)
from factor_factory.mechanism_math.formula_specific import BASELINE_MODEL_FAMILIES
from factor_factory.revision_council.pre_oos_outcome import (
    PRE_OOS_ROOT_SYNTHESIS_VERSION,
    pre_oos_root_synthesis_path,
    validate_pre_oos_root_synthesis,
)
from factor_factory.revision_council.production import result_evo_outcome_summary


_SYSTEM_SUBPROCESS_RUN = subprocess.run


class EvoV2MemoryGatePause(RuntimeError):
    def __init__(self, state: dict[str, Any], receipt: dict[str, Any]):
        super().__init__(
            f"{BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID}: {state.get('stage')}"
        )
        self.state = state
        self.receipt = receipt


BLOCK_ISOLATION_AUDIT_FAILED = "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED"
BLOCK_EVIDENCE_IDENTITY_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_EVIDENCE_IDENTITY_MISMATCH"
BLOCK_FORMAL_EVIDENCE_MISSING = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_EVIDENCE_MISSING"
BLOCK_CREDENTIAL_REGISTRY_INVALID = "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_REGISTRY_INVALID"
BLOCK_AGENT_WRITE_SCOPE_INVALID = "BLOCK_FACTORFORGE_CONSOLE_AGENT_WRITE_SCOPE_INVALID"
BLOCK_AGENT_RESUME_ARTIFACT_INVALID = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RESUME_ARTIFACT_INVALID"
BLOCK_AGENT_DELIVERABLE_MISSING = "BLOCK_FACTORFORGE_CONSOLE_AGENT_DELIVERABLE_MISSING"
BLOCK_HOST_FORMAL_EXECUTION_FAILED = "BLOCK_FACTORFORGE_CONSOLE_HOST_FORMAL_EXECUTION_FAILED"
BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED = (
    "BLOCK_FACTORFORGE_CONSOLE_RESEARCH_ORG_RUNTIME_REQUIRED"
)
BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE = (
    "BLOCK_FACTORFORGE_CONSOLE_RESEARCH_ORG_RUNTIME_INCOMPLETE"
)
BLOCK_RESUME_TRUST_INVALID = "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
EXPLICIT_HUMAN_DECISION_REQUIRED = "FACTORFORGE_CONSOLE_EXPLICIT_HUMAN_DECISION_REQUIRED"
EVO_V2_EXTERNAL_CONTROL_REQUIRED = (
    "FACTORFORGE_CONSOLE_EVO_V2_EXTERNAL_CONTROL_REQUIRED"
)
EVO_V2_CHILD_MATERIALIZATION_REQUIRED = (
    "FACTORFORGE_CONSOLE_EVO_V2_CHILD_MATERIALIZATION_REQUIRED"
)
EVO_V2_CHILD_EXECUTION_READY = (
    "FACTORFORGE_CONSOLE_EVO_V2_CHILD_EXECUTION_READY"
)
RESEARCH_ORG_CLARIFICATION_REQUIRED = (
    "FACTORFORGE_CONSOLE_RESEARCH_ORG_CLARIFICATION_REQUIRED"
)
PREFORMAL_DESIGN_ONLY_COMPLETE = (
    "FACTORFORGE_CONSOLE_PREFORMAL_DESIGN_ONLY_COMPLETE"
)
PREFORMAL_CHECKPOINT_RECEIPT_TYPE = (
    "factorforge_console_preformal_design_checkpoint_v1"
)
PREFORMAL_CHECKPOINT_POINTER_VERSION = (
    "factorforge_console_preformal_design_checkpoint_pointer_v1"
)
PREFORMAL_RUNTIME_ASSURANCE = (
    "signed_specialist_runtime_complete_host_director_external"
)
HOST_DIRECTOR_RECORD_RELATIVE = "identity/web_research_director_record.json"
DATA_API_BRIDGE_RELATIVE = Path("deploy/factorforge-console/data-api-bridge")
FORMAL_ENGINE_SCRIPTS = {
    "materialize_web_research": Path("scripts/materialize_factorforge_web_research.py"),
    "run_factorforge_ultimate": Path("scripts/run_factorforge_ultimate.py"),
}
EVO_CHILD_MATERIALIZER_RELATIVE = Path(
    "skills/factor-forge-step6/scripts/materialize_step6_child_revision.py"
)
PRIVATE_LIFECYCLE_VERSION = "factorforge_console_private_job_lifecycle_v1"
PRIVATE_LIFECYCLE_RUNNING = "RUNNING"
PRIVATE_LIFECYCLE_RESUMABLE = "RESUMABLE"
PRIVATE_LIFECYCLE_TERMINAL = "TERMINAL"
PRIVATE_LIFECYCLE_NON_RESUMABLE = "NON_RESUMABLE"
HOST_CONVERSATION_LEDGER_BINDING_VERSION = (
    "factorforge_console_host_conversation_ledger_binding_v1"
)

NON_RESUMABLE_SECURITY_BLOCKERS = frozenset(
    {
        BLOCK_AGENT_WRITE_SCOPE_INVALID,
        BLOCK_ISOLATION_AUDIT_FAILED,
        BLOCK_CREDENTIAL_REGISTRY_INVALID,
        BLOCK_RESUME_TRUST_INVALID,
        BLOCK_AGENT_ORPHANED_WRITER,
        "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
    }
)

RETRYABLE_AGENT_RESUME_BLOCKERS = frozenset(
    {
        BLOCK_AGENT_DELIVERABLE_MISSING,
        BLOCK_AGENT_RESUME_ARTIFACT_INVALID,
        BLOCK_AGENT_RUNTIME_UNAVAILABLE,
        "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED",
    }
)

RESUME_KIND_HOST_FORMAL_CHECKPOINT = "host_formal_checkpoint"
RESUME_KIND_MECHANISM_AGENT = "mechanism_agent"
RESUME_KIND_COUNCIL_INGRESS = "council_ingress"
RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS = "pre_oos_root_synthesis"
RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS = "human_council_synthesis"
RESUME_KIND_HUMAN_NEXT_DERIVATION = "human_next_derivation"
RESUME_KIND_EVO_V2_MEMORY_GATE = "evo_v2_memory_gate"
RESUME_KIND_EVO_V2_EXTERNAL_WAIT = "evo_v2_external_wait"
RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY = "evo_v2_child_handoff_ready"
RESUME_KIND_EVO_V2_TERMINAL_CHECKPOINT = "evo_v2_terminal_checkpoint"
MECHANISM_MEMO_INITIAL_STATUS = "awaiting_main_agent_mechanism_memo"
MECHANISM_MEMO_REVISION_STATUS = "awaiting_main_agent_mechanism_memo_revision"
MECHANISM_MEMO_INITIAL_TOKEN = "AWAITING_MAIN_AGENT_MECHANISM_MEMO"
MECHANISM_MEMO_REVISION_TOKEN = "AWAITING_MAIN_AGENT_MECHANISM_MEMO_REVISION"
MECHANISM_MEMO_MANUAL_REVIEW_STATUS = (
    "awaiting_main_agent_mechanism_manual_review"
)
MECHANISM_MEMO_MANUAL_REVIEW_TOKEN = (
    "AWAITING_MAIN_AGENT_MECHANISM_MANUAL_REVIEW"
)
PRE_OOS_ROOT_SYNTHESIS_PAUSE_TOKEN = (
    "AWAITING_PRE_OOS_COUNCIL_ROOT_SYNTHESIS"
)
PRE_OOS_ROOT_SYNTHESIS_TASK_VERSION = (
    "factorforge_console_pre_oos_root_synthesis_task_v1"
)
@dataclass(frozen=True)
class ResumeRoute:
    kind: str
    start_step: str
    pause_state: str = ""
    pause_token: str = ""


@dataclass(frozen=True)
class ResumeRestoreState:
    files: dict[str, str | None]
    initially_absent_directories: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidatedAgentResumeArtifacts:
    attempt_id: str
    workspace_file_sha256: tuple[tuple[str, str], ...]
    agent_run_receipt_id: str
    agent_run_receipt_sha256: str
    prior_output_archive_id: str = ""
    prior_output_archive_sha256: str = ""


@dataclass(frozen=True)
class ValidatedAgentReceipt:
    receipt_id: str
    receipt_sha256: str


MECHANISM_METRIC_KEYS = frozenset(
    {
        "metric_period",
        "rank_ic_mean",
        "rank_ic_std",
        "rank_ic_ir",
        "rank_icir",
        "pearson_ic_mean",
        "pearson_ic_std",
        "pearson_ic_ir",
        "fama_macbeth",
        "fama_macbeth_beta",
        "fama_macbeth_premium",
        "fama_macbeth_risk_premium",
        "fama_macbeth_t_stat",
        "fama_macbeth_tstat",
        "fama_macbeth_p_value",
        "long_side_return_daily",
        "long_side_annual_return",
        "long_side_annual_volatility",
        "long_side_sharpe",
        "long_side_max_drawdown",
        "long_side_recovery_days",
        "long_side_turnover_mean_daily",
        "turnover_mean",
        "daily_turnover",
        "trading_cogs_daily",
        "trading_cogs_annual",
        "transaction_cost",
        "cost_adjusted_return_daily",
        "cost_adjusted_annual_return",
        "cost_adjusted_long_side_sharpe",
        "cost_adjusted_long_side_max_drawdown",
        "cost_adjusted_long_side_recovery_days",
        "long_short_spread_mean",
        "long_short_spread_std",
        "long_short_spread_ir",
        "monotonicity",
        "monotonicity_score",
        "decile_monotonicity",
        "quintile_monotonicity",
        "top_decile_mean_return",
        "bottom_decile_mean_return",
        "group_top_decile_mean_return",
        "group_bottom_decile_mean_return",
        "coverage_ratio",
        "coverage_rate",
        "valid_observation_ratio",
        "long_end_return",
        "long_end_annual_return",
    }
)
MECHANISM_METRIC_PREFIXES = (
    "group_",
    "decile_",
    "quintile_",
    "quantile_",
    "fama_macbeth_",
)


def _configure_host_formal_python_environment(
    env: dict[str, str],
    *,
    worktree: Path,
    data_api_pythonpath: Path | None,
) -> None:
    try:
        worktree_root = worktree.expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as exc:
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal worktree is invalid"
        ) from exc

    python_paths = [str(worktree_root)]
    excluded_inherited_root: Path | None = None
    env.pop("FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT", None)
    if data_api_pythonpath is not None:
        checkout_candidate = data_api_pythonpath.expanduser()
        package_candidate = checkout_candidate / "factor_factory" / "data_api"
        bridge_candidate = worktree_root / DATA_API_BRIDGE_RELATIVE
        package_entry = package_candidate / "__init__.py"
        bridge_entry = bridge_candidate / "factorforge_data_api" / "__init__.py"
        if (
            checkout_candidate.is_symlink()
            or package_candidate.is_symlink()
            or package_entry.is_symlink()
            or bridge_candidate.is_symlink()
            or bridge_entry.is_symlink()
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Data API bridge path is unsafe"
            )
        try:
            checkout = checkout_candidate.resolve(strict=True)
            package_root = package_candidate.resolve(strict=True)
            bridge_root = bridge_candidate.resolve(strict=True)
            package_root.relative_to(checkout)
            bridge_root.relative_to(worktree_root)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Data API bridge path is invalid"
            ) from exc
        if not package_entry.is_file() or not bridge_entry.is_file():
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Data API bridge package is missing"
            )
        python_paths.append(str(bridge_root))
        excluded_inherited_root = checkout
        env["FACTORFORGE_CONSOLE_DATA_API_PACKAGE_ROOT"] = str(package_root)

    inherited_pythonpath = env.get("PYTHONPATH", "")
    seen_python_paths = set(python_paths)
    for item in inherited_pythonpath.split(os.pathsep):
        value = item.strip()
        if not value:
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = worktree_root / candidate
        try:
            canonical = candidate.resolve(strict=False)
        except RuntimeError:
            continue
        if excluded_inherited_root is not None and (
            canonical == excluded_inherited_root
            or canonical.is_relative_to(excluded_inherited_root)
        ):
            continue
        canonical_value = str(canonical)
        if canonical_value not in seen_python_paths:
            python_paths.append(canonical_value)
            seen_python_paths.add(canonical_value)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["FACTORFORGE_REPO_ROOT"] = str(worktree_root)


def _formal_engine_script(source_repo: Path, relative: Path) -> Path:
    try:
        source_root = source_repo.expanduser().resolve(strict=True)
        candidate = source_root / relative
        if candidate.is_symlink():
            raise RuntimeError("formal engine script uses a symlink")
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(source_root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal engine script is unsafe"
        ) from exc
    if not resolved.is_file():
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal engine script is missing"
        )
    return resolved


def _git_blob_sha256(source_repo: Path, commit: str, relative: Path) -> str:
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(commit or "").lower()):
        raise RuntimeError("formal engine commit is invalid")
    try:
        proc = _SYSTEM_SUBPROCESS_RUN(
            [
                "git",
                "-C",
                str(source_repo),
                "show",
                f"{commit}:{relative.as_posix()}",
            ],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "formal engine commit does not contain the required script"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError("formal engine commit does not contain the required script")
    return hashlib.sha256(proc.stdout).hexdigest()


def _validate_formal_engine_checkout(source_repo: Path, expected_commit: str) -> str:
    try:
        source_root = source_repo.expanduser().resolve(strict=True)
        head_proc = _SYSTEM_SUBPROCESS_RUN(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        status_proc = _SYSTEM_SUBPROCESS_RUN(
            [
                "git",
                "-C",
                str(source_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal engine checkout is invalid"
        ) from exc
    if head_proc.returncode != 0 or status_proc.returncode != 0:
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal engine checkout is invalid"
        )
    head = head_proc.stdout.strip().lower()
    tracked_status = status_proc.stdout.strip()
    if head != str(expected_commit or "").lower() or tracked_status:
        raise RuntimeError(
            f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal engine commit changed"
        )
    return head


def _formal_receipt_engine_paths_valid(
    *,
    receipt: dict[str, Any],
    source_repo: Path,
    materialize: dict[str, Any],
    materialize_argv: list[Any],
    ultimate: dict[str, Any],
    ultimate_argv: list[Any],
) -> bool:
    engine_commit = str(receipt.get("engine_commit") or "").lower()
    engine_root = str(receipt.get("engine_root") or "")
    if not engine_commit and not engine_root:
        return bool(
            materialize_argv[1]
            == FORMAL_ENGINE_SCRIPTS["materialize_web_research"].as_posix()
            and ultimate_argv[1]
            == FORMAL_ENGINE_SCRIPTS["run_factorforge_ultimate"].as_posix()
        )
    try:
        source_root = source_repo.expanduser().resolve(strict=True)
        expected_materialize = source_root / FORMAL_ENGINE_SCRIPTS[
            "materialize_web_research"
        ]
        expected_ultimate = source_root / FORMAL_ENGINE_SCRIPTS[
            "run_factorforge_ultimate"
        ]
        return bool(
            engine_root == str(source_root)
            and re.fullmatch(r"[0-9a-f]{40,64}", engine_commit)
            and str(materialize_argv[1]) == str(expected_materialize)
            and str(ultimate_argv[1]) == str(expected_ultimate)
            and materialize.get("engine_script_sha256")
            == _git_blob_sha256(
                source_root,
                engine_commit,
                FORMAL_ENGINE_SCRIPTS["materialize_web_research"],
            )
            and ultimate.get("engine_script_sha256")
            == _git_blob_sha256(
                source_root,
                engine_commit,
                FORMAL_ENGINE_SCRIPTS["run_factorforge_ultimate"],
            )
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False


def _require_resume_request_allowed(job: ResearchJob) -> None:
    if (
        job.request.research_scope == RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
        and job.current_stage == "preformal_design_complete"
    ):
        raise RuntimeError(
            f"{PREFORMAL_DESIGN_ONLY_COMPLETE}: design-only checkpoints are "
            "terminal; start a new full_formal task"
        )
    if job.error_code in NON_RESUMABLE_SECURITY_BLOCKERS:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior security blocker is not resumable; "
            "start a new isolated research task"
        )
    if not job.worktree_path or not job.workspace_path or not job.base_commit:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: persisted workspace identity is incomplete"
        )


def _is_evo_v2_memory_gate_pause(job: ResearchJob) -> bool:
    result = job.result if isinstance(job.result, dict) else {}
    memory = result.get("evo_v2_memory")
    return bool(
        isinstance(memory, dict)
        and memory.get("status") == "PAUSED_PRE_RESULT_MEMORY_GATE"
        and memory.get("formal_execution_allowed") is False
        and memory.get("results_or_oos_accessed") is False
        and isinstance(memory.get("state_ref"), dict)
    )


def _is_evo_v2_child_runtime_pause(job: ResearchJob) -> bool:
    result = job.result if isinstance(job.result, dict) else {}
    child_runtime = result.get("evo_v2_child_runtime")
    execution = (
        child_runtime.get("execution")
        if isinstance(child_runtime, dict)
        and isinstance(child_runtime.get("execution"), dict)
        else {}
    )
    return bool(
        job.error_code == EVO_V2_CHILD_EXECUTION_READY
        and execution.get("status") in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
        and isinstance(execution.get("child_report_id"), str)
        and isinstance(execution.get("execution_receipt_path"), str)
    )


def _read_host_conversation_parent(
    *,
    state_root: Path,
    job: ResearchJob,
    resume_trust: dict[str, Any],
) -> None:
    root = state_root.resolve(strict=True)

    def read_host_json(
        relative_value: Any,
        expected_sha256: Any,
        *,
        label: str,
    ) -> dict[str, Any]:
        relative = Path(str(relative_value or ""))
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) < 3
            or not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256 or ""))
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} identity is unsafe"
            )
        candidate = root / relative
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} uses a symlink"
                )
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} is missing"
            ) from exc
        if candidate.is_symlink() or not resolved.is_file():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} is unsafe"
            )
        if _sha256(resolved) != str(expected_sha256):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} hash mismatch"
            )
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} is invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation {label} is invalid"
            )
        return payload

    attestation = read_host_json(
        resume_trust.get("attestation_id"),
        resume_trust.get("attestation_sha256"),
        label="parent attestation",
    )
    receipt = read_host_json(
        resume_trust.get("receipt_id"),
        resume_trust.get("receipt_sha256"),
        label="parent formal receipt",
    )
    expected_identity = {
        "job_id": job.job_id,
        "factor_id": job.factor_id,
        "research_id": job.research_id,
        "report_id": job.report_id,
        "base_commit": job.base_commit,
    }
    if (
        attestation.get("version")
        != "factorforge_console_host_execution_attestation_v2"
        or receipt.get("version")
        != "factorforge_console_host_formal_execution_v2"
        or any(
            attestation.get(key) != value or receipt.get(key) != value
            for key, value in expected_identity.items()
        )
        or attestation.get("formal_execution_receipt_id")
        != resume_trust.get("receipt_id")
        or attestation.get("formal_execution_receipt_sha256")
        != resume_trust.get("receipt_sha256")
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: conversation parent host provenance is invalid"
        )


def _validate_host_conversation_ledger_binding(
    *,
    workspace: Path,
    state_root: Path,
    job: ResearchJob,
    resume: bool,
    resume_trust: dict[str, Any] | None,
) -> dict[str, Any]:
    request = _read_regular_workspace_json(
        workspace,
        "identity/web_research_request.json",
    )
    try:
        ledger = validate_request_conversation_ledger(
            workspace,
            request,
            expected_job_id=job.job_id,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: host conversation ledger validation failed"
        ) from exc
    current_reference = deepcopy(ledger["reference"])
    current_payload = ledger["current"]
    chain = ledger["chain"]
    request_sha256 = stable_json_hash(request)
    parent_reference: dict[str, Any] | None = None
    parent_request_sha256 = ""
    parent_attestation_id = ""
    parent_attestation_sha256 = ""
    parent_receipt_id = ""
    parent_receipt_sha256 = ""

    if not resume:
        if (
            resume_trust is not None
            or len(chain) != 1
            or current_payload.get("source") != "initial"
            or current_payload.get("parent_checkpoint") is not None
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh conversation ledger root is invalid"
            )
        mode = "initial"
    else:
        if not isinstance(resume_trust, dict):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: conversation parent trust is missing"
            )
        _read_host_conversation_parent(
            state_root=state_root,
            job=job,
            resume_trust=resume_trust,
        )
        parent_attestation_id = str(resume_trust.get("attestation_id") or "")
        parent_attestation_sha256 = str(
            resume_trust.get("attestation_sha256") or ""
        )
        parent_receipt_id = str(resume_trust.get("receipt_id") or "")
        parent_receipt_sha256 = str(resume_trust.get("receipt_sha256") or "")
        parent_request_sha256 = str(
            resume_trust.get("conversation_request_sha256") or ""
        )
        raw_parent_reference = resume_trust.get("conversation_ledger_checkpoint")
        parent_reference = (
            deepcopy(raw_parent_reference)
            if isinstance(raw_parent_reference, dict)
            else None
        )
        if not re.fullmatch(r"[0-9a-f]{64}", parent_request_sha256):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: parent conversation request hash is invalid"
            )
        if parent_reference is not None and current_reference == parent_reference:
            if request_sha256 != parent_request_sha256:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: unchanged conversation request changed"
                )
            mode = "unchanged"
        elif parent_reference is not None:
            current_parent = current_payload.get("parent_checkpoint")
            if (
                current_payload.get("source") != "resume"
                or not isinstance(current_parent, dict)
                or any(
                    current_parent.get(field) != parent_reference.get(field)
                    for field in (
                        "version",
                        "path",
                        "sha256",
                        "root_sha256",
                        "message_count",
                    )
                )
                or current_parent.get("attestation_id") != parent_attestation_id
                or current_parent.get("attestation_sha256")
                != parent_attestation_sha256
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: conversation checkpoint parent is not host trusted"
                )
            mode = "append"
        else:
            oldest_payload = chain[0][1]
            legacy_parent = oldest_payload.get("legacy_parent_attestation")
            if (
                oldest_payload.get("source") != "legacy_attested_request"
                or oldest_payload.get("legacy_request_sha256")
                != parent_request_sha256
                or not isinstance(legacy_parent, dict)
                or legacy_parent.get("attestation_id") != parent_attestation_id
                or legacy_parent.get("attestation_sha256")
                != parent_attestation_sha256
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: legacy conversation root is not host trusted"
                )
            if current_payload.get("source") == "resume":
                current_parent = current_payload.get("parent_checkpoint")
                if (
                    not isinstance(current_parent, dict)
                    or current_parent.get("attestation_id")
                    != parent_attestation_id
                    or current_parent.get("attestation_sha256")
                    != parent_attestation_sha256
                ):
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: legacy conversation extension is not host trusted"
                    )
            elif current_payload.get("source") != "legacy_attested_request":
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: legacy conversation lineage is invalid"
                )
            mode = "legacy_migration"

    return {
        "version": HOST_CONVERSATION_LEDGER_BINDING_VERSION,
        "mode": mode,
        "request_sha256": request_sha256,
        "current_checkpoint": current_reference,
        "current_root_sha256": str(current_payload.get("root_sha256") or ""),
        "current_message_count": int(current_payload.get("message_count") or 0),
        "parent_request_sha256": parent_request_sha256,
        "parent_checkpoint": parent_reference,
        "parent_attestation_id": parent_attestation_id,
        "parent_attestation_sha256": parent_attestation_sha256,
        "parent_receipt_id": parent_receipt_id,
        "parent_receipt_sha256": parent_receipt_sha256,
    }


def _classify_resume_route(
    workspace: Path,
    report_id: str,
    *,
    start_step: str,
    trusted_proof_sha256: str,
    evo_v2_external_progress: Mapping[str, Any] | None = None,
) -> ResumeRoute:
    proof_relative = (
        "objects/runtime_context/"
        f"ultimate_run_report__{report_id}.json"
    )
    proof_path = _read_regular_workspace_file(workspace, proof_relative)
    if not trusted_proof_sha256 or _sha256(proof_path) != trusted_proof_sha256:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume route proof hash mismatch"
        )
    if start_step not in {"3", "4", "5", "6"}:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume route start step is invalid"
        )
    proof = _read_regular_workspace_json(workspace, proof_relative)
    status = str(proof.get("status") or "").upper()
    if status in {"FAIL", "BLOCK_DATA_REQUEST_PENDING"}:
        return ResumeRoute(
            kind=RESUME_KIND_HOST_FORMAL_CHECKPOINT,
            start_step=start_step,
        )
    if status != "PAUSED" or start_step != "6":
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: unsupported formal resume state"
        )

    pause_outcome = str(proof.get("final_outcome") or "")
    if pause_outcome in EVO_V2_EXTERNAL_PAUSES:
        try:
            if evo_v2_external_progress is None:
                raise EvoV2ExternalResumeError(
                    ["attested external resume assessment is required"]
                )
            assessment = dict(evo_v2_external_progress)
            if (
                assessment.get("report_id") != report_id
                or assessment.get("pause_outcome") != pause_outcome
                or assessment.get("status")
                not in {
                    PROGRESS_WAITING,
                    PROGRESS_CHILD_HANDOFF_AUTHORIZED,
                    PROGRESS_HOST_CHECKPOINT_READY,
                    PROGRESS_CHILD_HANDOFF_READY,
                    PROGRESS_TERMINAL_CHECKPOINT_READY,
                }
            ):
                raise EvoV2ExternalResumeError(
                    ["external resume assessment binding mismatch"]
                )
        except (EvoV2ExternalResumeError, OSError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 external resume validation failed: {exc}"
            ) from exc
        if assessment["status"] == PROGRESS_HOST_CHECKPOINT_READY:
            if assessment.get("start_step") != "6":
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 checkpoint step is invalid"
                )
            return ResumeRoute(
                kind=RESUME_KIND_HOST_FORMAL_CHECKPOINT,
                start_step="6",
                pause_state=pause_outcome,
                pause_token=str(assessment.get("reason") or ""),
            )
        if assessment["status"] in {
            PROGRESS_CHILD_HANDOFF_AUTHORIZED,
            PROGRESS_CHILD_HANDOFF_READY,
        }:
            if assessment.get("start_step") is not None:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: parent formal resume is forbidden after child approval"
                )
            return ResumeRoute(
                kind=RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY,
                start_step="6",
                pause_state=pause_outcome,
                pause_token=str(assessment.get("child_report_id") or ""),
            )
        if assessment["status"] == PROGRESS_TERMINAL_CHECKPOINT_READY:
            if (
                assessment.get("start_step") is not None
                or assessment.get("terminal_factor_verdict")
                not in {"ACCEPT", "REJECT"}
                or assessment.get("terminal_decision")
                not in {"promote_official", "reject"}
                or not isinstance(assessment.get("terminal_closure_path"), str)
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(assessment.get("terminal_closure_sha256") or ""),
                )
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 terminal checkpoint is invalid"
                )
            return ResumeRoute(
                kind=RESUME_KIND_EVO_V2_TERMINAL_CHECKPOINT,
                start_step="6",
                pause_state=pause_outcome,
                pause_token=str(assessment.get("terminal_closure_sha256") or ""),
            )
        if assessment.get("start_step") is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: waiting EVO V2 pause carries execution authority"
            )
        return ResumeRoute(
            kind=RESUME_KIND_EVO_V2_EXTERNAL_WAIT,
            start_step="6",
            pause_state=pause_outcome,
            pause_token=str(assessment.get("reason") or ""),
        )

    mechanism = (
        proof.get("main_agent_mechanism_memo")
        if isinstance(proof.get("main_agent_mechanism_memo"), dict)
        else {}
    )
    mechanism_token = str(mechanism.get("token") or "")
    mechanism_state = str(mechanism.get("status") or "")
    if (
        (
            mechanism_token == MECHANISM_MEMO_INITIAL_TOKEN
            and mechanism_state in {"", MECHANISM_MEMO_INITIAL_STATUS}
        )
        or (
            mechanism_token == MECHANISM_MEMO_REVISION_TOKEN
            and mechanism_state == MECHANISM_MEMO_REVISION_STATUS
        )
    ):
        return ResumeRoute(
            kind=RESUME_KIND_MECHANISM_AGENT,
            start_step="6",
            pause_state=(mechanism_state or MECHANISM_MEMO_INITIAL_STATUS),
            pause_token=mechanism_token,
        )
    if (
        mechanism_token == MECHANISM_MEMO_MANUAL_REVIEW_TOKEN
        and mechanism_state == MECHANISM_MEMO_MANUAL_REVIEW_STATUS
    ):
        return ResumeRoute(
            kind=RESUME_KIND_HUMAN_NEXT_DERIVATION,
            start_step="6",
            pause_state="awaiting_next_derivation",
            pause_token=mechanism_token,
        )

    council = (
        proof.get("revision_council")
        if isinstance(proof.get("revision_council"), dict)
        else {}
    )
    if (
        str(council.get("status") or "") == "awaiting_agent_results"
        and str(council.get("effective_mode") or "")
        == "agentic_dispatch_manifest"
    ):
        return ResumeRoute(
            kind=RESUME_KIND_COUNCIL_INGRESS,
            start_step="6",
            pause_state="awaiting_agent_results",
            pause_token="AWAITING_REVISION_COUNCIL_AGENT_RESULTS",
        )
    if str(council.get("status") or "") == "awaiting_root_synthesis":
        canonical = pre_oos_root_synthesis_path(
            workspace.resolve(strict=True),
            report_id,
        ).resolve(strict=False)
        declared_raw = str(council.get("root_synthesis_path") or "")
        declared = Path(declared_raw)
        council_commands = council.get("commands")
        exact_pause = (
            str(proof.get("proof_semantics") or "")
            == "awaiting_agent_authored_pre_oos_root_synthesis"
            and str(proof.get("final_outcome") or "")
            == "awaiting_pre_oos_council_root_synthesis"
            and proof.get("failure") is None
            and proof.get("factor_verdict") == "NOT_ISSUED"
            and proof.get("formal_proof_eligible") is False
            and str(council.get("requested_mode") or "")
            in {"agentic", "auto"}
            and str(council.get("effective_mode") or "")
            == "agentic_dispatch_manifest"
            and str(council.get("evidence_view") or "") == "PURGED_IS_ONLY"
            and str(council.get("oos_state") or "")
            == "SEALED_NOT_ACCESSED"
            and isinstance(council_commands, list)
            and bool(council_commands)
            and all(
                isinstance(command, dict)
                and command.get("status") == "PASS"
                and command.get("returncode") == 0
                for command in council_commands
            )
            and declared.is_absolute()
            and declared.resolve(strict=False) == canonical
            and not canonical.exists()
            and not canonical.is_symlink()
        )
        if not exact_pause:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS root synthesis pause binding is invalid"
            )
        return ResumeRoute(
            kind=RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS,
            start_step="6",
            pause_state="awaiting_root_synthesis",
            pause_token=PRE_OOS_ROOT_SYNTHESIS_PAUSE_TOKEN,
        )

    pause_state = str(proof.get("final_outcome") or "")
    paused_note_relative = (
        "objects/research_iteration_master/"
        f"paused_research_note__{report_id}.json"
    )
    paused_note_path = workspace / paused_note_relative
    if paused_note_path.exists() or paused_note_path.is_symlink():
        paused_note = _read_regular_workspace_json(workspace, paused_note_relative)
        note_state = str(paused_note.get("pause_state") or "")
        if pause_state and note_state and pause_state != note_state:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: paused state evidence is inconsistent"
            )
        pause_state = pause_state or note_state
    if pause_state == "awaiting_main_agent_council_synthesis":
        return ResumeRoute(
            kind=RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS,
            start_step="6",
            pause_state=pause_state,
        )
    if pause_state == "awaiting_next_derivation":
        return ResumeRoute(
            kind=RESUME_KIND_HUMAN_NEXT_DERIVATION,
            start_step="6",
            pause_state=pause_state,
        )
    raise RuntimeError(
        f"{BLOCK_RESUME_TRUST_INVALID}: unknown or unsupported paused resume state"
    )


def _apply_execution_mode_resume_policy(
    route: ResumeRoute,
    *,
    execution_mode: str,
) -> ResumeRoute:
    if (
        route.kind == RESUME_KIND_MECHANISM_AGENT
        and route.pause_token == MECHANISM_MEMO_REVISION_TOKEN
        and execution_mode != "container"
    ):
        return ResumeRoute(
            kind=RESUME_KIND_HUMAN_NEXT_DERIVATION,
            start_step="6",
            pause_state=MECHANISM_MEMO_REVISION_STATUS,
            pause_token=MECHANISM_MEMO_REVISION_TOKEN,
        )
    return route


def _human_resume_message(route: ResumeRoute) -> tuple[str, str]:
    if route.kind == RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS:
        return (
            "Council 已返回多个修订方案，需要明确选择修订法则后才能继续。普通续跑不会代替该决定。",
            "请在专用 Council 综合审批入口选择方案、公式、证伪标准与终止条件。",
        )
    if route.kind == RESUME_KIND_HUMAN_NEXT_DERIVATION:
        if (
            route.pause_token == MECHANISM_MEMO_REVISION_TOKEN
            and route.pause_state == MECHANISM_MEMO_REVISION_STATUS
        ):
            return (
                "当前部署模式不支持对既有机制 memo 做可审计替换；任务保持暂停，未覆盖旧证据。",
                "请切换到隔离容器执行模式，或由人工审查后新建独立研究任务。",
            )
        return (
            "当前修订分支已被证伪，需要明确选择下一条数学推导方向。普通续跑不会自动生成或批准新分支。",
            "请在专用下一轮推导入口选择问题分类和研究对象后再继续。",
        )
    raise ValueError("resume route does not require an explicit human decision")


def _evo_v2_external_resume_message(
    route: ResumeRoute,
) -> tuple[str, str, str]:
    if route.kind == RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY:
        child = route.pause_token or "fresh child"
        return (
            "外部 human 签名、Host fresh sealed OOS allocation 与 pre-OOS child "
            "handoff 已通过重放；父报告没有继续执行权限。",
            f"由受控 child materializer 重放当前 gates，并以 child report {child} 建立独立执行任务。",
            EVO_V2_CHILD_MATERIALIZATION_REQUIRED,
        )
    if route.kind != RESUME_KIND_EVO_V2_EXTERNAL_WAIT:
        raise ValueError("resume route is not an EVO V2 external-control pause")
    next_actions = {
        "awaiting_evo_v2_host_qualification": (
            "由 Ultimate Host 基于 purged-IS checkpoint 完成 qualification，追加签名 "
            "lifecycle CAS；QUALIFIED 分支还必须 admission feedback staging。"
        ),
        "awaiting_host_lifecycle_transition_and_staged_council_outcome": (
            "由 Ultimate Host 重放 canonical pre-OOS outcome verifier，完成签名 "
            "lifecycle transition 与 exact Council outcome staging。"
        ),
        "awaiting_evo_v2_transfer_and_actual_use": (
            "由 Host 完成 canonical transfer-use orchestration、签名 lifecycle CAS 与"
            "四事件 staging readback；found-memory 分支还必须绑定未执行的 preregistered "
            "execution addendum，cold-start 分支必须保持 addendum absent。"
        ),
        "awaiting_evo_v2_external_approval_and_fresh_child": (
            "由外部 human control plane 签发绑定 selected law 的 receipt，并由 Host "
            "CAS 分配 fresh sealed child OOS 后运行 pre-OOS approval bridge。"
        ),
        "awaiting_evo_v2_non_revision_terminal_closure": (
            "由 Ultimate Host 对已消费 OOS 的 NO_QUALIFIED_CONTRADICTION 路径签发"
            "不可变 terminal closure；该签名只关闭终态，不授予修订或记忆提升权限。"
        ),
    }
    return (
        "EVO V2 的外部控制动作尚未形成完整可重放证明；任务保持暂停，未启动研究代理或 formal runner。",
        next_actions.get(route.pause_state, "完成当前 EVO V2 外部控制动作后再续跑。"),
        EVO_V2_EXTERNAL_CONTROL_REQUIRED,
    )


def _pre_oos_root_synthesis_runner(adapter: object):
    runner = getattr(adapter, "run_pre_oos_root_synthesis", None)
    if not callable(runner):
        raise RuntimeError(
            f"{BLOCK_AGENT_RUNTIME_UNAVAILABLE}: isolated pre-OOS root synthesis adapter is missing"
        )
    return runner


def _validate_evo_child_active_lineage(
    *,
    lineage: Mapping[str, Any],
    signed_execution: Mapping[str, Any],
    trusted_parent_checkpoint: Mapping[str, Any],
    state_root: Path,
    trust_root: Path,
    installation_id: str,
    job_id: str,
    expected_host_pin: str,
    workspace_root: Path,
    replay_phase_receipts: bool,
) -> dict[str, Any]:
    """Validate root-to-active recursive child lineage without trusting the DB row.

    The structural/hash pass is safe before a new Step6 semantic delta has been
    admitted.  Full signed historical receipt replay is enabled only after the
    active workspace is exact or a phase/qualification checkpoint has closed
    that delta; historical receipts intentionally do not compare their old
    evidence tree to the newer descendant workspace.
    """

    if not isinstance(replay_phase_receipts, bool):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: child lineage replay mode is invalid"
        )
    required_lineage = {
        "root_report_id",
        "phase_owner_parent_report_id",
        "parent_report_id",
        "child_report_id",
        "parent_phase_receipt",
        "ancestry",
    }
    if set(lineage) != required_lineage:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: active child lineage shape is invalid"
        )
    root_report_id = str(lineage.get("root_report_id") or "")
    active_parent = str(lineage.get("parent_report_id") or "")
    active_child = str(lineage.get("child_report_id") or "")
    ancestry = lineage.get("ancestry")
    if (
        not root_report_id
        or not active_parent
        or not active_child
        or active_parent == active_child
        or active_parent != signed_execution.get("parent_report_id")
        or active_child != signed_execution.get("child_report_id")
        or not isinstance(ancestry, list)
        or not ancestry
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: active child lineage identity is invalid"
        )
    normalized: list[dict[str, Any]] = []
    seen_children: set[str] = set()
    previous_child = ""
    for index, raw_edge in enumerate(ancestry):
        if not isinstance(raw_edge, Mapping) or set(raw_edge) != {
            "root_report_id",
            "phase_owner_parent_report_id",
            "parent_report_id",
            "child_report_id",
            "parent_phase_receipt",
        }:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child ancestry edge shape is invalid"
            )
        edge = dict(raw_edge)
        owner_parent = str(edge.get("phase_owner_parent_report_id") or "")
        edge_parent = str(edge.get("parent_report_id") or "")
        edge_child = str(edge.get("child_report_id") or "")
        phase_ref = edge.get("parent_phase_receipt")
        if (
            edge.get("root_report_id") != root_report_id
            or not owner_parent
            or not edge_parent
            or not edge_child
            or edge_parent == edge_child
            or (index > 0 and previous_child != edge_parent)
            or edge_child in seen_children
            or not isinstance(phase_ref, Mapping)
            or set(phase_ref) != {"path", "sha256", "receipt_id"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(phase_ref.get("sha256") or ""))
            or not isinstance(phase_ref.get("receipt_id"), str)
            or not phase_ref.get("receipt_id")
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child ancestry edge binding is invalid"
            )
        raw_phase_path = Path(str(phase_ref.get("path") or "")).expanduser()
        if raw_phase_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child ancestry receipt changed"
            )
        try:
            phase_path = raw_phase_path.resolve(strict=True)
            expected_phase_root = (
                state_root.resolve(strict=True)
                / "jobs"
                / job_id
                / "evo-child-runtime"
                / edge_parent
            ).resolve(strict=True)
            phase_path.relative_to(expected_phase_root)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child ancestry receipt is missing"
            ) from exc
        if (
            not phase_path.is_file()
            or _sha256(phase_path) != phase_ref.get("sha256")
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child ancestry receipt changed"
            )
        if replay_phase_receipts:
            validated = validate_evo_child_phase_checkpoint(
                state_root=state_root,
                trust_root=trust_root,
                installation_id=installation_id,
                job_id=job_id,
                parent_report_id=owner_parent,
                child_report_id=edge_parent,
                expected_host_trust_manifest_sha256=expected_host_pin,
                phase_receipt_path=phase_path,
                workspace_root=workspace_root,
                verify_workspace_exact=False,
            )
            receipt = validated.get("receipt")
            phase_context = (
                receipt.get("phase_context") if isinstance(receipt, Mapping) else None
            )
            assessment = (
                phase_context.get("external_resume_assessment")
                if isinstance(phase_context, Mapping)
                else None
            )
            if (
                validated.get("phase") != "HOST_CHILD_HANDOFF"
                or validated.get("phase_receipt_sha256") != phase_ref.get("sha256")
                or not isinstance(receipt, Mapping)
                or receipt.get("receipt_id") != phase_ref.get("receipt_id")
                or not isinstance(assessment, Mapping)
                or assessment.get("report_id") != edge_parent
                or assessment.get("child_report_id") != edge_child
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child ancestry handoff receipt is invalid"
                )
        normalized.append(edge)
        previous_child = edge_child
        seen_children.add(edge_child)
    last = normalized[-1]
    if (
        last.get("parent_report_id") != active_parent
        or last.get("child_report_id") != active_child
        or lineage.get("phase_owner_parent_report_id")
        != last.get("phase_owner_parent_report_id")
        or lineage.get("parent_phase_receipt") != last.get("parent_phase_receipt")
        or trusted_parent_checkpoint.get("parent_phase_receipt_path")
        != last["parent_phase_receipt"]["path"]
        or trusted_parent_checkpoint.get("parent_phase_receipt_sha256")
        != last["parent_phase_receipt"]["sha256"]
        or trusted_parent_checkpoint.get("parent_phase_receipt_id")
        != last["parent_phase_receipt"]["receipt_id"]
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: active child ancestry tail is invalid"
        )
    return {**dict(lineage), "ancestry": normalized}


def _extend_evo_child_lineage(
    *,
    root_report_id: str,
    phase_owner_parent_report_id: str,
    parent_report_id: str,
    child_report_id: str,
    phase_checkpoint: Mapping[str, Any],
    descendant_runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Prepend one closed handoff edge while retaining the deepest active child."""

    receipt = phase_checkpoint.get("receipt")
    phase_path = str(phase_checkpoint.get("phase_receipt_path") or "")
    phase_sha = str(phase_checkpoint.get("phase_receipt_sha256") or "")
    phase_receipt_id = (
        str(receipt.get("receipt_id") or "") if isinstance(receipt, Mapping) else ""
    )
    if (
        not all(
            isinstance(value, str) and value
            for value in (
                root_report_id,
                phase_owner_parent_report_id,
                parent_report_id,
                child_report_id,
                phase_path,
                phase_receipt_id,
            )
        )
        or parent_report_id == child_report_id
        or not re.fullmatch(r"[0-9a-f]{64}", phase_sha)
        or phase_checkpoint.get("phase") != "HOST_CHILD_HANDOFF"
        or phase_checkpoint.get("status") != CHILD_PHASE_READY
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: recursive child handoff receipt is invalid"
        )
    current_edge = {
        "root_report_id": root_report_id,
        "phase_owner_parent_report_id": phase_owner_parent_report_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "parent_phase_receipt": {
            "path": phase_path,
            "sha256": phase_sha,
            "receipt_id": phase_receipt_id,
        },
    }
    existing_lineage = descendant_runtime.get("lineage")
    if not isinstance(existing_lineage, Mapping):
        return {**current_edge, "ancestry": [current_edge]}
    ancestry = existing_lineage.get("ancestry")
    if (
        existing_lineage.get("root_report_id") != root_report_id
        or not isinstance(ancestry, list)
        or not ancestry
        or not all(isinstance(edge, Mapping) for edge in ancestry)
        or ancestry[0].get("parent_report_id") != child_report_id
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: recursive child ancestry is discontinuous"
        )
    return {
        **dict(existing_lineage),
        "root_report_id": root_report_id,
        "ancestry": [current_edge, *[dict(edge) for edge in ancestry]],
    }


def _current_authority_report_id(job: ResearchJob) -> str:
    result = job.result if isinstance(job.result, dict) else {}
    child_runtime = result.get("evo_v2_child_runtime")
    execution = (
        child_runtime.get("execution")
        if isinstance(child_runtime, dict)
        and isinstance(child_runtime.get("execution"), dict)
        else {}
    )
    child_report_id = str(execution.get("child_report_id") or "")
    return child_report_id or job.report_id


@contextmanager
def _host_current_authority_transaction(
    *,
    state_root: Path,
    workspace_root: Path,
    installation_id: str,
):
    """Lock incident registry before workspace for one Host authority commit."""

    trust_root = state_root / "research-org-trust"
    with oos_exposure_private_registry_guard(
        trust_root,
        installation_id=installation_id,
    ) as incident_guard:
        with workspace_transaction_lock(
            state_root,
            workspace_root,
            error_code=BLOCK_RESUME_TRUST_INVALID,
        ):
            yield incident_guard


class ResearchQueueService:
    """Unprivileged web-side queue facade; execution lives in the runner process."""

    def __init__(
        self,
        *,
        store: ResearchJobStore,
        runner_health_socket: str | Path,
        expected_engine_commit: str = "",
        config: ConsoleConfig | None = None,
    ) -> None:
        self.store = store
        self.runner_health_socket = Path(runner_health_socket).expanduser().resolve(strict=False)
        self.expected_engine_commit = expected_engine_commit
        self.config = config

    def start(self) -> None:
        return None

    def stop(self, timeout: float = 10.0) -> None:
        return None

    def healthcheck(self) -> bool:
        payload = probe_runner_health(self.runner_health_socket)
        return bool(
            payload
            and payload.get("ok") is True
            and (self.config is None or catalogs_healthy(self.config))
            and (
                not self.expected_engine_commit
                or payload.get("engine_commit") == self.expected_engine_commit
            )
        )

    def submit(
        self,
        request: ResearchRequest,
        *,
        initial_messages: list[tuple[str, str]] | None = None,
        initial_attachments: list[ResearchAttachmentUpload] | None = None,
    ) -> ResearchJob:
        validate_pilot_evaluation_request(request)
        if request.source_url:
            raise ValueError(
                "source URL ingestion is disabled until the read-only fetch broker is available"
            )
        if self.config is not None:
            require_catalogs_healthy(self.config)
        if not self.healthcheck():
            raise RuntimeError("BLOCK_FACTORFORGE_CONSOLE_RUNNER_UNAVAILABLE")
        return self.store.create_job(
            request,
            initial_messages=initial_messages,
            initial_attachments=initial_attachments,
        )

    def request_resume(self, job_id: str) -> ResearchJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        validate_pilot_evaluation_request(job.request)
        _require_resume_request_allowed(job)
        if self.config is not None:
            require_catalogs_healthy(self.config)
        if not self.healthcheck():
            raise RuntimeError("BLOCK_FACTORFORGE_CONSOLE_RUNNER_UNAVAILABLE")
        return self.store.request_resume(job_id)

    def cancel_queued(self, job_id: str) -> ResearchJob:
        return self.store.cancel_queued(job_id)


class ResearchRunService:
    def __init__(
        self,
        *,
        config: ConsoleConfig,
        store: ResearchJobStore,
        allocator: FactorWorktreeAllocator,
        agent_adapter: ResearchAgentAdapter,
        poll_seconds: float = 1.0,
    ) -> None:
        self.config = config
        self.store = store
        self.allocator = allocator
        self.agent_adapter = agent_adapter
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._expected_base_commit = self.allocator.validate_ready()
        self._health_lock = threading.Lock()
        self._health_checked_at = 0.0
        self._health_cached = False
        self._health_ttl_seconds = 30.0
        self._startup_reconciliation_healthy = True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.pause_interrupted_jobs()
        self._startup_reconciliation_healthy = (
            self._reconcile_preformal_terminal_lifecycles()
        )
        with self._health_lock:
            self._health_checked_at = 0.0
            self._health_cached = False
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="factorforge-console-worker", daemon=True)
        self._thread.start()

    def _reconcile_preformal_terminal_lifecycles(self) -> bool:
        try:
            jobs = self.store.list_jobs(limit=500)
        except Exception:
            return False
        startup_healthy = True
        for job in jobs:
            if (
                job.request.research_scope
                != RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
                or job.current_stage != "preformal_design_complete"
                or job.execution_status != "REVIEW_REQUIRED"
                or not job.workspace_path
            ):
                continue
            try:
                self._reconcile_preformal_terminal_lifecycle(job)
            except Exception:
                if not self._quarantine_failed_preformal_reconciliation(job):
                    startup_healthy = False
        return startup_healthy

    def _reconcile_preformal_terminal_lifecycle(self, job: ResearchJob) -> None:
        lifecycle = self._read_private_lifecycle(job)
        if (
            not isinstance(lifecycle, dict)
            or lifecycle.get("status") != PRIVATE_LIFECYCLE_RUNNING
        ):
            return
        workspace = Path(job.workspace_path).expanduser().resolve(strict=True)
        with workspace_transaction_lock(
            self.config.state_root,
            workspace,
            error_code=BLOCK_RESUME_TRUST_INVALID,
        ):
            replay = self._replay_preformal_design_checkpoint(
                job,
                workspace=workspace,
            )
        projected_checkpoint = (
            job.result.get("preformal_design", {}).get("checkpoint", {})
            if isinstance(job.result, dict)
            else {}
        )
        if (
            not isinstance(projected_checkpoint, dict)
            or projected_checkpoint.get("receipt_id")
            != replay["receipt_id"]
            or projected_checkpoint.get("receipt_sha256")
            != replay["receipt_sha256"]
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: terminal preformal DB projection "
                "does not match signed checkpoint"
            )
        self._finish_private_execution(
            job,
            status=PRIVATE_LIFECYCLE_TERMINAL,
            attestation_id=replay["receipt_id"],
        )
        self.store.append_event(
            job.job_id,
            "PREFORMAL_DESIGN_LIFECYCLE_RECONCILED",
            "Host 已重放签名设计检查点并补全终态生命周期。",
            {"receipt_id": replay["receipt_id"]},
        )

    def _quarantine_failed_preformal_reconciliation(
        self,
        job: ResearchJob,
    ) -> bool:
        public_message = (
            "Host 未能安全重放终态设计检查点；当前任务已禁止续跑，"
            "请新建隔离任务。"
        )
        try:
            self._mark_job_non_resumable(
                job,
                token=BLOCK_RESUME_TRUST_INVALID,
            )
            self.store.update_job(
                job.job_id,
                execution_status="BLOCKED",
                protocol_status="BLOCK",
                factor_verdict="BLOCK",
                formal_proof_eligible=False,
                current_stage="blocked",
                error_code=BLOCK_RESUME_TRUST_INVALID,
                error_message=public_message,
                result=_result_without_resume_attestation(
                    self.store.get_job(job.job_id) or job
                ),
                finished_at_utc=utc_now(),
            )
            self.store.append_event(
                job.job_id,
                "PREFORMAL_DESIGN_RECONCILIATION_BLOCKED",
                public_message,
                {"code": BLOCK_RESUME_TRUST_INVALID},
            )
            return True
        except Exception:
            try:
                self.store.append_event(
                    job.job_id,
                    "PREFORMAL_DESIGN_RECONCILIATION_HEALTH_BLOCKED",
                    (
                        "终态设计检查点恢复失败，且不可续跑分类未能"
                        "可靠持久化；Runner 已进入不健康状态，未执行队列任务。"
                    ),
                    {"code": BLOCK_RESUME_TRUST_INVALID},
                )
            except Exception:
                pass
            return False

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        stop_all = getattr(self.agent_adapter, "stop_all", None)
        if callable(stop_all):
            stop_all()
        if self._thread:
            self._thread.join(timeout=timeout)

    def healthcheck(self) -> bool:
        if not self._thread or not self._thread.is_alive() or self._stop.is_set():
            return False
        now = time.monotonic()
        with self._health_lock:
            if now - self._health_checked_at < self._health_ttl_seconds:
                return self._health_cached
            self._health_cached = self._compute_healthcheck()
            self._health_checked_at = time.monotonic()
            return self._health_cached

    def _compute_healthcheck(self) -> bool:
        if not self._startup_reconciliation_healthy:
            return False
        adapter_health = getattr(self.agent_adapter, "healthcheck", None)
        try:
            source_ready = self.allocator.validate_ready() == self._expected_base_commit
            runtime_ready = bool(adapter_health()) if callable(adapter_health) else True
        except (OSError, RuntimeError, ValueError):
            return False
        return bool(
            source_ready
            and runtime_ready
            and catalogs_healthy(self.config)
        )

    def submit(
        self,
        request: ResearchRequest,
        *,
        initial_messages: list[tuple[str, str]] | None = None,
        initial_attachments: list[ResearchAttachmentUpload] | None = None,
    ) -> ResearchJob:
        validate_pilot_evaluation_request(request)
        if request.source_url:
            raise ValueError(
                "source URL ingestion is disabled until the read-only fetch broker is available"
            )
        require_catalogs_healthy(self.config)
        job = self.store.create_job(
            request,
            initial_messages=initial_messages,
            initial_attachments=initial_attachments,
        )
        self._wake.set()
        return job

    def request_resume(self, job_id: str) -> ResearchJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        validate_pilot_evaluation_request(job.request)
        _require_resume_request_allowed(job)
        require_catalogs_healthy(self.config)
        self._require_private_resume_allowed(job)
        allocation = self.allocator.validate_allocation(
            factor_id=job.factor_id,
            research_id=job.research_id,
            report_id=job.report_id,
            persisted_worktree_path=job.worktree_path,
            persisted_workspace_path=job.workspace_path,
            persisted_base_commit=job.base_commit,
        )
        if (
            job.request.research_scope
            == RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
        ):
            job = self.store.request_resume(job_id)
            self._wake.set()
            return job
        active_report_id = _current_authority_report_id(job)
        with _host_current_authority_transaction(
            state_root=self.config.state_root,
            workspace_root=allocation.workspace_path,
            installation_id=self.config.installation_id,
        ) as incident_guard:
            current_authority = validate_current_ultimate_authority(
                allocation.workspace_path,
                report_id=active_report_id,
                expected_factor_verdict=job.factor_verdict,
                formal_proof_eligible=False,
                incident_trust_root=(
                    self.config.state_root / "research-org-trust"
                ),
                incident_installation_id=self.config.installation_id,
                _incident_guard=incident_guard,
            )
            if current_authority.get("status") == "BLOCK":
                raise RuntimeError(
                    ";".join(
                        current_authority.get("block_reasons")
                        or [BLOCK_HOST_FORMAL_EXECUTION_FAILED]
                    )
                )
            if _is_evo_v2_child_runtime_pause(job):
                self._validate_evo_v2_child_runtime_resume(job)
            elif _is_evo_v2_memory_gate_pause(job):
                self._validate_evo_v2_memory_resume_context(
                    job,
                    worktree=allocation.worktree_path,
                    workspace=allocation.workspace_path,
                )
            else:
                self._validate_trusted_resume_context(
                    job,
                    worktree=allocation.worktree_path,
                    workspace=allocation.workspace_path,
                )
            job = self.store.request_resume(job_id)
        self._wake.set()
        return job

    def _validate_evo_v2_child_runtime_resume(
        self, job: ResearchJob
    ) -> dict[str, Any]:
        result = job.result if isinstance(job.result, dict) else {}
        child_runtime = result.get("evo_v2_child_runtime")
        execution = (
            child_runtime.get("execution")
            if isinstance(child_runtime, dict)
            and isinstance(child_runtime.get("execution"), dict)
            else {}
        )
        child_report_id = str(execution.get("child_report_id") or "")
        parent_report_id = str(execution.get("parent_report_id") or job.report_id)
        trust_root = self.config.state_root / "research-org-trust"
        store = load_runtime_trust_store(
            trust_root, installation_id=self.config.installation_id
        )
        common = {
            "state_root": self.config.state_root,
            "trust_root": trust_root,
            "installation_id": self.config.installation_id,
            "job_id": job.job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
            "expected_host_trust_manifest_sha256": store.public_manifest[
                "manifest_sha256"
            ],
            "execution_receipt_path": str(
                execution.get("execution_receipt_path") or ""
            ),
            "workspace_root": job.workspace_path,
        }
        baseline = load_latest_evo_child_execution_baseline(
            **{
                key: value
                for key, value in common.items()
                if key != "execution_receipt_path"
            }
        )
        common["execution_receipt_path"] = baseline["execution_receipt_path"]
        if (
            baseline.get("status") == CHILD_RESUME_READY
            and baseline.get("resume_start_step") == "6"
        ):
            phase_recovery = load_pending_evo_child_phase_inflight(
                **{
                    key: value
                    for key, value in common.items()
                    if key != "execution_receipt_path"
                },
                execution_receipt_path=baseline["execution_receipt_path"],
            )
            if phase_recovery is not None:
                baseline["phase_recovery"] = phase_recovery
        # Step4/5 have no legitimate external writer between executions, so
        # their whole workspace stays byte-exact. Step6 is different: signed
        # lifecycle, Council and terminal-closure deltas are intentionally
        # written before the next Console turn and are admitted by the
        # phase-specific closed-delta validators. Partial-OOS recovery is also
        # classified against its signed inflight state, not the old tree.
        if (
            baseline.get("status") == CHILD_RESUME_READY
            and baseline.get("resume_start_step") in {"4", "5"}
        ):
            return validate_evo_child_execution_state(**common)
        if (
            baseline.get("status") == CHILD_RESUME_READY
            and baseline.get("resume_start_step") == "6"
        ) or baseline.get("status") == CHILD_RECOVERY_READY:
            return baseline
        if (
            baseline.get("status") == CHILD_TERMINAL
            and baseline.get("host_execution_receipt_verified") is True
        ):
            return baseline
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: child execution has no resumable state"
        )

    def cancel_queued(self, job_id: str) -> ResearchJob:
        return self.store.cancel_queued(job_id)

    def run_once(self) -> ResearchJob | None:
        if (
            not self._startup_reconciliation_healthy
            or not catalogs_healthy(self.config)
        ):
            return None
        job = self.store.claim_next_job()
        if job is None:
            return None
        self._run_job(job)
        return self.store.get_job(job.job_id)

    def replay_preformal_design_checkpoint(
        self,
        job_id: str,
    ) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if (
            job.request.research_scope
            != RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
            or job.current_stage != "preformal_design_complete"
            or not job.workspace_path
        ):
            raise ValueError("job has no terminal preformal design checkpoint")
        workspace = Path(job.workspace_path).expanduser().resolve(strict=True)
        with workspace_transaction_lock(
            self.config.state_root,
            workspace,
            error_code=BLOCK_RESUME_TRUST_INVALID,
        ):
            return self._replay_preformal_design_checkpoint(
                job,
                workspace=workspace,
            )

    def _preformal_current_pointer_exists(self, job: ResearchJob) -> bool:
        pointer = (
            self.config.state_root
            / "jobs"
            / job.job_id
            / "preformal_design"
            / "current.json"
        )
        return pointer.exists() or pointer.is_symlink()

    def _record_preformal_design_completion(
        self,
        job: ResearchJob,
        *,
        checkpoint: dict[str, Any],
        recovered: bool,
    ) -> None:
        summary = (
            "独立 Research Org 已完成研究设计并通过正式独立性核验；"
            "任务按 design-only 范围停在取数、实现、回测和 OOS 之前。"
        )
        result = {
            "summary": summary,
            "next_actions": [
                "如需进入正式 Step3-6，请新建 full_formal 任务并显式提交。"
            ],
            "research_organization": {
                "state": "COMPLETE",
                "runtime_id": checkpoint["organization_runtime_id"],
                "result_count": checkpoint["organization_result_count"],
                "formal_independence_verified": True,
                "runtime_assurance": PREFORMAL_RUNTIME_ASSURANCE,
            },
            "preformal_design": {
                "scope": RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY,
                "status": "CHECKPOINTED",
                "current_factor_empirical_verdict": "NOT_ISSUED",
                "formal": False,
                "formal_proof_eligible": False,
                "production_eligible": False,
                "promotion_allowed": False,
                "host_data_lease_requested": False,
                "data_materializer_invoked": False,
                "ultimate_invoked": False,
                "step3_6_invoked": False,
                "oos_allocated": False,
                "oos_read": False,
                "oos_released": False,
                "oos_consumed": False,
                "resume_allowed": False,
                "checkpoint": {
                    key: checkpoint[key]
                    for key in (
                        "status",
                        "receipt_id",
                        "receipt_sha256",
                        "trust_manifest_sha256",
                        "workspace_tree_sha256",
                        "organization_runtime_sha256",
                        "organization_results_sha256",
                    )
                },
            },
        }
        self.store.update_job(
            job.job_id,
            execution_status="REVIEW_REQUIRED",
            protocol_status="PAUSED",
            factor_verdict="UNKNOWN",
            council_status="NOT_STARTED",
            formal_proof_eligible=False,
            current_stage="preformal_design_complete",
            error_code=PREFORMAL_DESIGN_ONLY_COMPLETE,
            error_message=summary,
            result=result,
            finished_at_utc=utc_now(),
        )
        self.store.append_event(
            job.job_id,
            (
                "PREFORMAL_DESIGN_CHECKPOINT_RECOVERED"
                if recovered
                else "PREFORMAL_DESIGN_CHECKPOINTED"
            ),
            summary,
            {
                "scope": RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY,
                "receipt_id": checkpoint["receipt_id"],
                "current_factor_empirical_verdict": "NOT_ISSUED",
                "formal": False,
                "promotion_allowed": False,
                "recovered": recovered,
            },
        )

    def _research_org_runtime_available(self) -> bool:
        return bool(
            callable(getattr(self.agent_adapter, "run_research_org_session", None))
            and callable(
                getattr(self.agent_adapter, "cancel_research_org_session", None)
            )
        )

    def _run_research_org_stage(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        stage: str,
    ) -> dict[str, Any]:
        if not self._research_org_runtime_available():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED}: "
                "the configured agent adapter has no isolated specialist runtime"
            )
        self.store.append_event(
            job.job_id,
            "RESEARCH_ORG_RUNTIME_STARTED",
            "研究组织正在执行隔离 specialist sessions",
            {"stage": stage},
        )
        try:
            research_org_private = ensure_host_private_job_subdirectory(
                self.config.state_root,
                job.job_id,
                ("research_org_private",),
                create=True,
            )
        except PrivateJobRootError as exc:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host-private job root is unsafe"
            ) from exc
        result = run_research_organization_runtime(
            workspace=workspace,
            worktree=worktree,
            private_root=research_org_private,
            runner=self.agent_adapter,
            max_attempts=2,
            max_concurrency=1,
            timeout_seconds=max(
                60,
                min(3_300, int(self.config.agent_timeout_seconds)),
            ),
            trust_root=self.config.state_root / "research-org-trust",
            installation_id=self.config.installation_id,
        )
        self.store.append_event(
            job.job_id,
            "RESEARCH_ORG_RUNTIME_STOPPED",
            f"研究组织阶段结束：{result['lifecycle']}",
            {
                "stage": stage,
                "lifecycle": result["lifecycle"],
                "result_count": result["result_count"],
                "formal_independence_verified": result[
                    "formal_independence_verified"
                ],
            },
        )
        return result

    def _research_org_ultimate_args(
        self,
        *,
        job: ResearchJob,
        workspace: Path,
    ) -> list[str]:
        plan_path = workspace / "identity" / "research_organization_plan.json"
        if not plan_path.is_file() or plan_path.is_symlink():
            return []
        if self.config.auth_disabled:
            return []
        return [
            "--research-org-runtime-mode",
            "formal-complete",
            "--research-org-runtime-private-root",
            str(
                self.config.state_root
                / "jobs"
                / job.job_id
                / "research_org_private"
            ),
            "--research-org-runtime-trust-root",
            str(self.config.state_root / "research-org-trust"),
            "--research-org-runtime-installation-id",
            self.config.installation_id,
        ]

    @staticmethod
    def _research_org_task(workspace: Path, role_id: str) -> dict[str, Any]:
        validate_research_organization_bundle(workspace=workspace)
        plan = load_research_organization_plan(workspace)
        dispatch_path = workspace / str(
            plan["workspace_policy"]["dispatch_manifest_path"]
        )
        if dispatch_path.is_symlink() or not dispatch_path.is_file():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED}: unsafe dispatch manifest"
            )
        dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
        matches = [
            item
            for item in dispatch.get("tasks") or []
            if isinstance(item, dict) and item.get("role_id") == role_id
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED}: missing role task {role_id}"
            )
        task_path = workspace / str(matches[0]["path"])
        if task_path.is_symlink() or not task_path.is_file():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED}: unsafe role task {role_id}"
            )
        task = json.loads(task_path.read_text(encoding="utf-8"))
        if not isinstance(task, dict):
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED}: invalid role task {role_id}"
            )
        return task

    def _admit_host_research_director_result(
        self,
        *,
        job: ResearchJob,
        workspace: Path,
        agent_result: AgentRunResult,
    ) -> dict[str, Any]:
        plan_path = workspace / "identity" / "web_research_plan.json"
        if plan_path.is_symlink() or not plan_path.is_file():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: Host Director plan is missing"
            )
        try:
            authored_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: Host Director plan is invalid"
            ) from exc
        if not isinstance(authored_plan, dict):
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: Host Director plan is invalid"
            )
        validate_plan(authored_plan, workspace=workspace)
        task = self._research_org_task(workspace, "research_director")
        organization = validate_research_organization_bundle(workspace=workspace)
        reviewed_roles = list(task.get("depends_on_roles") or [])
        if (
            not reviewed_roles
            or any(
                organization.get("result_statuses", {}).get(role_id) != "PASS"
                for role_id in reviewed_roles
            )
        ):
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host Director specialist intake is incomplete"
            )
        reviewed_results: list[dict[str, str]] = []
        for role_id in reviewed_roles:
            dependency_task = self._research_org_task(workspace, role_id)
            result_relative = str(dependency_task["expected_result_path"])
            result_path = workspace / result_relative
            if result_path.is_symlink() or not result_path.is_file():
                raise RuntimeError(
                    f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                    f"Host Director specialist result is missing:{role_id}"
                )
            dependency_result = json.loads(result_path.read_text(encoding="utf-8"))
            if (
                not isinstance(dependency_result, dict)
                or dependency_result.get("role_id") != role_id
                or dependency_result.get("status") != "PASS"
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(dependency_result.get("result_sha256") or ""),
                )
            ):
                raise RuntimeError(
                    f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                    f"Host Director specialist result is invalid:{role_id}"
                )
            reviewed_results.append(
                {
                    "role_id": role_id,
                    "path": result_relative,
                    "result_sha256": str(dependency_result["result_sha256"]),
                }
            )
        ledger_path = workspace / "identity" / "web_execution_ledger.md"
        if ledger_path.is_symlink() or not ledger_path.is_file():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: Host Director ledger is missing"
            )
        director_record_path = workspace / HOST_DIRECTOR_RECORD_RELATIVE
        if director_record_path.is_symlink() or not director_record_path.is_file():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "agent-authored Host Director record is missing"
            )
        try:
            director_record = json.loads(
                director_record_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "agent-authored Host Director record is invalid"
            ) from exc
        expected_record_keys = {
            "contract_version",
            "identity",
            "task_ref",
            "reviewed_specialist_results",
            "plan_ref",
            "ledger_ref",
            "synthesis",
            "handoff_status",
        }
        synthesis = (
            director_record.get("synthesis")
            if isinstance(director_record, dict)
            else None
        )
        if (
            not isinstance(director_record, dict)
            or set(director_record) != expected_record_keys
            or director_record.get("contract_version")
            != DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION
            or director_record.get("identity") != task.get("identity")
            or director_record.get("task_ref")
            != {"task_id": task.get("task_id"), "sha256": task.get("task_sha256")}
            or director_record.get("reviewed_specialist_results")
            != reviewed_results
            or director_record.get("plan_ref")
            != {
                "path": "identity/web_research_plan.json",
                "sha256": _sha256(plan_path),
            }
            or director_record.get("ledger_ref")
            != {
                "path": "identity/web_execution_ledger.md",
                "sha256": _sha256(ledger_path),
            }
            or director_record.get("handoff_status")
            != "ready_for_specialist_verification"
            or not isinstance(synthesis, dict)
            or set(synthesis)
            != {
                "mechanism_decision",
                "selected_measurement_object",
                "rejected_alternatives",
                "unresolved_risks",
                "falsifiers",
            }
            or any(
                not isinstance(synthesis.get(field), str)
                or not str(synthesis.get(field)).strip()
                for field in ("mechanism_decision", "selected_measurement_object")
            )
            or any(
                not isinstance(synthesis.get(field), list)
                or (field != "unresolved_risks" and not synthesis.get(field))
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in synthesis.get(field) or []
                )
                for field in (
                    "rejected_alternatives",
                    "unresolved_risks",
                    "falsifiers",
                )
            )
        ):
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "agent-authored Host Director record is not causally bound"
            )
        resolved_receipt = self._validated_host_agent_receipt(
            job=job,
            agent_result=agent_result,
        )
        artifact_refs = [
            {
                "path": "identity/web_research_plan.json",
                "sha256": _sha256(plan_path),
            },
            {
                "path": "identity/web_execution_ledger.md",
                "sha256": _sha256(ledger_path),
            },
            {
                "path": HOST_DIRECTOR_RECORD_RELATIVE,
                "sha256": _sha256(director_record_path),
            },
        ]
        assert isinstance(synthesis, dict)
        director_synthesis = {
            "contract_version": DIRECTOR_AUTHORING_RECORD_CONTRACT_VERSION,
            "stage": "pre_formal_research_design",
            **deepcopy(synthesis),
            "reviewed_specialist_results": reviewed_results,
            "source_record_ref": artifact_refs[-1],
            "handoff_status": "ready_for_specialist_verification",
        }
        payload = with_content_hash(
            {
                "contract_version": AGENT_RESULT_CONTRACT_VERSION,
                "task_ref": {
                    "task_id": task["task_id"],
                    "sha256": task["task_sha256"],
                },
                "identity": task["identity"],
                "role_id": "research_director",
                "status": "PASS",
                "producer_mode": "real_agent",
                "session_id": agent_result.session_key,
                "public_research_record": {
                    "contract_version": task["output_contract"],
                    "executive_summary": str(synthesis["mechanism_decision"]),
                    "claims": [
                        {
                            "claim": str(synthesis["selected_measurement_object"]),
                            "falsifier": str(synthesis["falsifiers"][0]),
                        }
                    ],
                    "artifact_refs": artifact_refs,
                    "director_synthesis": director_synthesis,
                    "handoff": {
                        "status": "ready_for_specialist_verification",
                        "reviewed_specialist_results": reviewed_results,
                        "web_research_plan_sha256": _sha256(plan_path),
                        "web_execution_ledger_sha256": _sha256(ledger_path),
                        "host_agent_run_receipt_sha256": _sha256(resolved_receipt),
                        "host_agent_provider": agent_result.provider,
                        "host_agent_model": agent_result.model,
                        "host_agent_started_at_utc": agent_result.started_at_utc,
                        "host_agent_finished_at_utc": agent_result.finished_at_utc,
                    },
                },
            },
            hash_field="result_sha256",
        )
        return admit_agent_result(
            workspace=workspace,
            result=payload,
            role_id="research_director",
        )

    def _validated_host_agent_receipt(
        self,
        *,
        job: ResearchJob,
        agent_result: AgentRunResult,
    ) -> Path:
        agent_receipt_path = Path(agent_result.result_path).expanduser()
        if agent_receipt_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host Director private Agent receipt is unsafe"
            )
        try:
            resolved_receipt = agent_receipt_path.resolve(strict=True)
            resolved_receipt.relative_to(
                (self.config.state_root / "jobs" / job.job_id).resolve(strict=True)
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host Director private Agent receipt is invalid"
            ) from exc
        if resolved_receipt.is_symlink() or not resolved_receipt.is_file():
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host Director private Agent receipt is unsafe"
            )
        try:
            receipt = json.loads(resolved_receipt.read_text(encoding="utf-8"))
            expected_model = (
                normalize_deepseek_openclaw_model(self.config.openclaw_model)
                if self.config.openclaw_auth_provider == "deepseek"
                else self.config.openclaw_model
            )
            started = datetime.fromisoformat(
                agent_result.started_at_utc.replace("Z", "+00:00")
            )
            finished = datetime.fromisoformat(
                agent_result.finished_at_utc.replace("Z", "+00:00")
            )
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host Director private Agent receipt is invalid"
            ) from exc
        required_keys = {
            "version",
            "job_id",
            "factor_id",
            "research_id",
            "report_id",
            "agent_id",
            "session_key_sha256",
            "resume",
            "resume_attempt_id",
            "started_at_utc",
            "finished_at_utc",
            "returncode",
            "provider",
            "model",
            "error_code",
            "stdout_tail",
            "stderr_tail",
        }
        expected_bindings = {
            "version": "factorforge_console_agent_run_v1",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "agent_id": agent_result.agent_id,
            "session_key_sha256": hashlib.sha256(
                agent_result.session_key.encode("utf-8")
            ).hexdigest(),
            "resume": False,
            "resume_attempt_id": "",
            "started_at_utc": agent_result.started_at_utc,
            "finished_at_utc": agent_result.finished_at_utc,
            "returncode": agent_result.returncode,
            "provider": agent_result.provider,
            "model": agent_result.model,
            "stdout_tail": agent_result.stdout_tail,
            "stderr_tail": agent_result.stderr_tail,
        }
        invalid = bool(
            not isinstance(receipt, dict)
            or set(receipt) - {*required_keys, "execution_mode"}
            or not required_keys.issubset(receipt)
            or any(receipt.get(key) != value for key, value in expected_bindings.items())
            or agent_result.returncode != 0
            or receipt.get("error_code") != ""
            or not agent_result.provider
            or agent_result.provider != self.config.openclaw_auth_provider
            or not agent_result.model
            or agent_result.model != expected_model
            or not agent_result.started_at_utc.endswith("Z")
            or not agent_result.finished_at_utc.endswith("Z")
            or started.tzinfo is None
            or finished.tzinfo is None
            or started.astimezone(timezone.utc) > finished.astimezone(timezone.utc)
            or (
                "execution_mode" in receipt
                and receipt.get("execution_mode") != self.config.execution_mode
            )
        )
        if invalid:
            raise RuntimeError(
                f"{BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE}: "
                "Host Director private Agent receipt binding is invalid"
            )
        return resolved_receipt

    def _pause_for_research_org_gate(
        self,
        *,
        job: ResearchJob,
        workspace: Path,
        runtime: dict[str, Any] | None,
    ) -> str:
        organization = validate_research_organization_bundle(workspace=workspace)
        lifecycle = str((runtime or {}).get("lifecycle") or "NOT_STARTED")
        plan = load_research_organization_plan(workspace)
        route = plan.get("routing") if isinstance(plan.get("routing"), dict) else {}
        capability_gaps = route.get("capability_gaps") or []
        if organization["state"] == "NEEDS_CLARIFICATION" or lifecycle == "WAITING_CLARIFICATION":
            stage = "research_clarification_required"
            code = RESEARCH_ORG_CLARIFICATION_REQUIRED
            message = (
                "当前输入尚未给出足以选择研究领域的经济机制。请补充要交易的状态、"
                "付款方/收益来源、观测时点和可证伪预测后新建研究任务。"
            )
        elif organization["state"] == "WAITING_CAPABILITY":
            stage = "research_capability_required"
            code = RESEARCH_ORG_CLARIFICATION_REQUIRED
            message = (
                "研究所需领域能力尚未安装，任务保持待处理，未转派给不匹配的研究员。"
            )
        elif lifecycle == "WAITING_DATA":
            stage = "waiting_data"
            code = RESEARCH_ORG_CLARIFICATION_REQUIRED
            message = "Data Liaison 已识别数据缺口；收到 catalog、QA 和 delivery receipt 后再继续。"
        else:
            stage = "research_org_review_required"
            code = BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE
            message = f"研究组织未达到正式执行条件：{lifecycle}。"
        result = {
            "summary": message,
            "next_actions": [
                "在新的输入中明确 economic hypothesis 与可证伪的 measurement target。"
            ],
            "research_organization": {
                "contract_version": plan.get("contract_version"),
                "state": organization["state"],
                "lead_domain": organization.get("lead_domain"),
                "supporting_domains": organization.get("supporting_domains") or [],
                "capability_gaps": capability_gaps,
                "dispatch_task_count": organization["task_count"],
                "validated_result_count": organization["result_count"],
                "execution_state": organization["execution_state"],
                "independence_satisfied": False,
                "runtime": runtime,
                "assurance": (
                    "verified_runtime_history_partial"
                    if runtime is not None
                    else "routing_and_dispatch_contract_only"
                ),
            },
        }
        self.store.update_job(
            job.job_id,
            execution_status="REVIEW_REQUIRED",
            protocol_status="PAUSED",
            factor_verdict="UNKNOWN",
            council_status="NOT_STARTED",
            formal_proof_eligible=False,
            current_stage=stage,
            result=result,
            error_code=code,
            error_message=message,
            finished_at_utc="",
        )
        self.store.append_event(
            job.job_id,
            "RESEARCH_ORG_REVIEW_REQUIRED",
            message,
            {"state": organization["state"], "lifecycle": lifecycle},
        )
        plan_sha256 = str(plan.get("plan_sha256") or "")
        attestation_root = (
            self.config.state_root
            / "jobs"
            / job.job_id
            / "research-org-gates"
        )
        attestation_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        attestation_root.chmod(0o700)
        unsigned = {
            "version": "factorforge_console_research_org_gate_attestation_v1",
            **self._private_lifecycle_identity(job),
            "plan_sha256": plan_sha256,
            "organization_state": organization["state"],
            "execution_state": organization["execution_state"],
            "runtime_lifecycle": lifecycle,
            "formal_independence_verified": bool(
                (runtime or {}).get("formal_independence_verified") is True
            ),
            "disposition": stage,
            "created_at_utc": utc_now(),
        }
        payload = {**unsigned, "attestation_sha256": stable_json_hash(unsigned)}
        attestation_path = (
            attestation_root
            / f"attestation_{plan_sha256[:20] or job.report_id}.json"
        )
        _write_json_atomic(
            attestation_path,
            payload,
            root=self.config.state_root,
        )
        return attestation_path.relative_to(self.config.state_root).as_posix()

    def _pause_for_evo_v2_memory_gate(
        self,
        *,
        job: ResearchJob,
        workspace: Path,
        state: dict[str, Any],
        formal_receipt: dict[str, Any],
    ) -> str:
        """Publish a nonterminal pre-result pause without issuing a verdict."""

        stage = str(state.get("stage") or "")
        event_sha256 = str(state.get("event_sha256") or "")
        if (
            state.get("formal_execution_allowed") is not False
            or not stage
            or not re.fullmatch(r"[0-9a-f]{64}", event_sha256)
            or not isinstance(state.get("pause"), dict)
            or state["pause"].get("required") is not True
        ):
            raise RuntimeError(
                f"{BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID}: invalid pause state"
            )
        message = (
            "EVO V2 已在读取任何研究结果或 OOS 前暂停："
            f"{state['pause'].get('reason') or stage}"
        )
        state_relative = (
            f"objects/evo_v2/{job.report_id}/memory_runtime/"
            "memory_runtime_state.json"
        )
        state_path = workspace / state_relative
        if state_path.is_symlink() or not state_path.is_file():
            raise RuntimeError(
                f"{BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID}: pause state readback"
            )
        try:
            observed_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID}: pause state readback"
            ) from exc
        if observed_state != state:
            raise RuntimeError(
                f"{BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID}: pause state readback"
            )
        result = {
            "summary": message,
            "next_actions": [str(state["pause"].get("resume_action") or "")],
            "evo_v2_memory": {
                "status": "PAUSED_PRE_RESULT_MEMORY_GATE",
                "stage": stage,
                "state_ref": {
                    "path": state_relative,
                    "sha256": _sha256(state_path),
                    "event_sha256": event_sha256,
                },
                "formal_execution_allowed": False,
                "results_or_oos_accessed": False,
                "resume_api": (
                    "prepare_evo_v2_memory_round"
                    if stage != "AWAITING_TRANSFER_AUTHORING_AND_REVIEW"
                    else "admit_evo_v2_memory_transfer_round"
                ),
            },
        }
        self.store.update_job(
            job.job_id,
            execution_status="REVIEW_REQUIRED",
            protocol_status="PAUSED",
            factor_verdict="UNKNOWN",
            council_status="NOT_STARTED",
            formal_proof_eligible=False,
            current_stage="evo_v2_memory_review_required",
            result=result,
            error_code=BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
            error_message=message,
            finished_at_utc="",
        )
        self.store.append_event(
            job.job_id,
            "EVO_V2_MEMORY_GATE_PAUSED",
            message,
            {"stage": stage, "event_sha256": event_sha256},
        )
        attestation_root = (
            self.config.state_root / "jobs" / job.job_id / "evo-v2-memory-gates"
        )
        attestation_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        attestation_root.chmod(0o700)
        unsigned = {
            "version": "factorforge_console_evo_v2_memory_gate_attestation_v1",
            **self._private_lifecycle_identity(job),
            "stage": stage,
            "state_event_sha256": event_sha256,
            "state_file_sha256": _sha256(state_path),
            "formal_execution_receipt_id": formal_receipt.get("receipt_id"),
            "formal_execution_receipt_sha256": formal_receipt.get(
                "receipt_sha256"
            ),
            "formal_execution_allowed": False,
            "results_or_oos_accessed": False,
            "created_at_utc": utc_now(),
        }
        payload = {**unsigned, "attestation_sha256": stable_json_hash(unsigned)}
        attestation_path = (
            attestation_root / f"attestation_{event_sha256[:20]}.json"
        )
        _write_json_atomic(
            attestation_path,
            payload,
            root=self.config.state_root,
        )
        return attestation_path.relative_to(self.config.state_root).as_posix()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            if not catalogs_healthy(self.config) or not self.healthcheck():
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            job = self.store.claim_next_job()
            if job is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
                continue
            self._run_job(job)

    def _run_job(self, job: ResearchJob) -> None:
        transaction_stack = ExitStack()
        transaction_release_failed = False
        denied_values: tuple[str, ...] = ()
        resume_trust: dict[str, Any] | None = None
        resume_route: ResumeRoute | None = None
        resume_task: AgentResumeTask | None = None
        validated_resume_artifacts: ValidatedAgentResumeArtifacts | None = None
        validated_agent_receipt: ValidatedAgentReceipt | None = None
        resume_restore_state: ResumeRestoreState | None = None
        resume_parent_restored = False
        private_completion_status: str | None = None
        private_attestation_id = ""
        council_ingress_tasks: tuple[CouncilIngressTask, ...] = ()
        pre_oos_root_synthesis_task: PreOosRootSynthesisTask | None = None
        organization_runtime: dict[str, Any] | None = None
        organization_runtime_required = False
        try:
            resume = bool(job.workspace_path and job.worktree_path)
            evo_v2_memory_resume = bool(
                resume and _is_evo_v2_memory_gate_pause(job)
            )
            evo_v2_child_runtime_resume = bool(
                resume and _is_evo_v2_child_runtime_pause(job)
            )
            self._begin_private_execution(job, resume=resume)
            validate_public_source_url(job.request.source_url)
            if (
                resume
                and job.request.research_scope
                == RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
            ):
                allocation = self.allocator.validate_allocation(
                    factor_id=job.factor_id,
                    research_id=job.research_id,
                    report_id=job.report_id,
                    persisted_worktree_path=job.worktree_path,
                    persisted_workspace_path=job.workspace_path,
                    persisted_base_commit=job.base_commit,
                )
                worktree = allocation.worktree_path
                workspace = allocation.workspace_path
                isolation_failures = audit_factor_worktree(worktree, workspace)
                if isolation_failures:
                    raise RuntimeError(
                        f"{BLOCK_ISOLATION_AUDIT_FAILED}: "
                        f"{'; '.join(isolation_failures)}"
                    )
                with workspace_transaction_lock(
                    self.config.state_root,
                    workspace,
                    error_code=BLOCK_RESUME_TRUST_INVALID,
                ):
                    if self._preformal_current_pointer_exists(job):
                        preformal_checkpoint = (
                            self._replay_preformal_design_checkpoint(
                                job,
                                workspace=workspace,
                            )
                        )
                    else:
                        try:
                            preformal_checkpoint = (
                                self._write_preformal_design_checkpoint(
                                    job,
                                    workspace=workspace,
                                )
                            )
                        except (OSError, RuntimeError, ValueError) as exc:
                            raise RuntimeError(
                                f"{BLOCK_RESUME_TRUST_INVALID}: interrupted "
                                "design-only task lacks a replayable checkpoint "
                                "or signed COMPLETE organization runtime"
                            ) from exc
                self._record_preformal_design_completion(
                    job,
                    checkpoint=preformal_checkpoint,
                    recovered=True,
                )
                private_completion_status = PRIVATE_LIFECYCLE_TERMINAL
                private_attestation_id = preformal_checkpoint["receipt_id"]
                return
            if resume:
                allocation = self.allocator.validate_allocation(
                    factor_id=job.factor_id,
                    research_id=job.research_id,
                    report_id=job.report_id,
                    persisted_worktree_path=job.worktree_path,
                    persisted_workspace_path=job.workspace_path,
                    persisted_base_commit=job.base_commit,
                )
                worktree = allocation.worktree_path
                workspace = allocation.workspace_path
                with _host_current_authority_transaction(
                    state_root=self.config.state_root,
                    workspace_root=workspace,
                    installation_id=self.config.installation_id,
                ) as resume_incident_guard:
                    resume_current_authority = validate_current_ultimate_authority(
                        workspace,
                        report_id=_current_authority_report_id(job),
                        expected_factor_verdict=job.factor_verdict,
                        formal_proof_eligible=False,
                        incident_trust_root=(
                            self.config.state_root / "research-org-trust"
                        ),
                        incident_installation_id=self.config.installation_id,
                        _incident_guard=resume_incident_guard,
                    )
                    if resume_current_authority.get("status") == "BLOCK":
                        raise RuntimeError(
                            ";".join(
                                resume_current_authority.get("block_reasons")
                                or [BLOCK_HOST_FORMAL_EXECUTION_FAILED]
                            )
                        )
                if evo_v2_child_runtime_resume:
                    child_state = self._validate_evo_v2_child_runtime_resume(job)
                    prior_result = (
                        job.result if isinstance(job.result, dict) else {}
                    )
                    prior_runtime = prior_result.get("evo_v2_child_runtime")
                    prior_ready = (
                        prior_runtime.get("ready")
                        if isinstance(prior_runtime, dict)
                        and isinstance(prior_runtime.get("ready"), dict)
                        else {}
                    )
                    checkpoint_path = str(prior_ready.get("checkpoint_path") or "")
                    checkpoint_receipt = json.loads(
                        Path(checkpoint_path).read_text(encoding="utf-8")
                    )
                    parent_checkpoint = checkpoint_receipt.get(
                        "trusted_parent_checkpoint"
                    )
                    progress = prior_result.get("evo_v2_external_progress")
                    if (
                        not isinstance(parent_checkpoint, dict)
                        or not isinstance(progress, dict)
                    ):
                        raise RuntimeError(
                            f"{BLOCK_RESUME_TRUST_INVALID}: child parent checkpoint missing"
                        )
                    resume_trust = {
                        **parent_checkpoint,
                        "start_step": "6",
                        "evo_v2_external_progress": progress,
                    }
                    active_lineage = (
                        prior_runtime.get("lineage")
                        if isinstance(prior_runtime, Mapping)
                        and isinstance(prior_runtime.get("lineage"), Mapping)
                        else None
                    )
                    if active_lineage is not None:
                        _validate_evo_child_active_lineage(
                            lineage=active_lineage,
                            signed_execution=child_state,
                            trusted_parent_checkpoint=parent_checkpoint,
                            state_root=self.config.state_root,
                            trust_root=self.config.state_root
                            / "research-org-trust",
                            installation_id=self.config.installation_id,
                            job_id=job.job_id,
                            expected_host_pin=load_runtime_trust_store(
                                self.config.state_root / "research-org-trust",
                                installation_id=self.config.installation_id,
                            ).public_manifest["manifest_sha256"],
                            workspace_root=workspace,
                            # Request admission may precede a legitimate signed
                            # Step6 delta. At this point check the DB lineage's
                            # exact receipt hashes; full historical receipt replay
                            # occurs after that delta is checkpointed below.
                            replay_phase_receipts=False,
                        )
                    resume_route = ResumeRoute(
                        kind=RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY,
                        start_step=str(child_state["resume_start_step"]),
                        pause_state=str(progress.get("pause_outcome") or ""),
                        pause_token=str(child_state["child_report_id"]),
                    )
                elif evo_v2_memory_resume:
                    memory_chain = self._validate_evo_v2_memory_resume_context(
                        job,
                        worktree=worktree,
                        workspace=workspace,
                        private_execution_started=True,
                    )
                    resume_route = ResumeRoute(
                        kind=RESUME_KIND_EVO_V2_MEMORY_GATE,
                        start_step="3",
                        pause_state=str(
                            memory_chain["current_state"].get("stage") or ""
                        ),
                        pause_token=BLOCK_EVO_V2_MEMORY_RUNTIME_INVALID,
                    )
                else:
                    resume_trust = self._validate_trusted_resume_context(
                        job,
                        worktree=worktree,
                        workspace=workspace,
                        private_execution_started=True,
                    )
                    resume_route = _classify_resume_route(
                        workspace,
                        job.report_id,
                        start_step=str(resume_trust["start_step"]),
                        trusted_proof_sha256=str(
                            resume_trust["ultimate_proof_sha256"]
                        ),
                        evo_v2_external_progress=(
                            resume_trust.get("evo_v2_external_progress")
                            if isinstance(
                                resume_trust.get("evo_v2_external_progress"),
                                dict,
                            )
                            else None
                        ),
                    )
                    resume_route = _apply_execution_mode_resume_policy(
                        resume_route,
                        execution_mode=self.config.execution_mode,
                    )
                if resume_route.kind in {
                    RESUME_KIND_MECHANISM_AGENT,
                    RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS,
                    RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY,
                }:
                    transaction_stack.enter_context(
                        workspace_transaction_lock(
                            self.config.state_root,
                            workspace,
                            error_code=BLOCK_RESUME_TRUST_INVALID,
                        )
                    )
                if resume_route.kind in {
                    RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS,
                    RESUME_KIND_HUMAN_NEXT_DERIVATION,
                }:
                    summary_message, next_action = _human_resume_message(resume_route)
                    preserved_result = (
                        dict(job.result) if isinstance(job.result, dict) else {}
                    )
                    preserved_result["summary"] = summary_message
                    preserved_result["next_actions"] = [next_action]
                    self.store.update_job(
                        job.job_id,
                        execution_status="REVIEW_REQUIRED",
                        protocol_status="PAUSED",
                        factor_verdict=job.factor_verdict,
                        council_status="PAUSED",
                        current_stage="review_required",
                        error_code=EXPLICIT_HUMAN_DECISION_REQUIRED,
                        error_message=summary_message,
                        result=preserved_result,
                        finished_at_utc="",
                    )
                    self.store.append_event(
                        job.job_id,
                        "EXPLICIT_HUMAN_DECISION_REQUIRED",
                        summary_message,
                        {"pause_state": resume_route.pause_state},
                    )
                    private_completion_status = PRIVATE_LIFECYCLE_RESUMABLE
                    private_attestation_id = str(
                        resume_trust.get("attestation_id") or ""
                    )
                    return
                if resume_route.kind == RESUME_KIND_EVO_V2_TERMINAL_CHECKPOINT:
                    transaction_stack.close()
                    transaction_stack = ExitStack()
                    incident_guard = transaction_stack.enter_context(
                        _host_current_authority_transaction(
                            state_root=self.config.state_root,
                            workspace_root=workspace,
                            installation_id=self.config.installation_id,
                        )
                    )
                    expected_terminal_verdict = str(
                        (
                            resume_trust.get("evo_v2_external_progress")
                            if isinstance(resume_trust, Mapping)
                            else {}
                        ).get("terminal_factor_verdict")
                        or ""
                    )
                    current_authority = validate_current_ultimate_authority(
                        workspace,
                        report_id=job.report_id,
                        expected_factor_verdict=expected_terminal_verdict,
                        formal_proof_eligible=True,
                        incident_trust_root=(
                            self.config.state_root / "research-org-trust"
                        ),
                        incident_installation_id=self.config.installation_id,
                        _incident_guard=incident_guard,
                    )
                    if current_authority.get("status") != "PASS":
                        raise RuntimeError(
                            ";".join(
                                current_authority.get("block_reasons")
                                or [BLOCK_HOST_FORMAL_EXECUTION_FAILED]
                            )
                        )
                    checkpoint = self._write_evo_v2_terminal_checkpoint(
                        job,
                        workspace=workspace,
                        resume_trust=resume_trust,
                    )
                    formal_verdict = str(
                        checkpoint["formal_factor_verdict"]
                    )
                    preserved_result = (
                        dict(job.result) if isinstance(job.result, dict) else {}
                    )
                    preserved_result.update(
                        {
                            "summary": (
                                "EVO V2 非修订路径的 Host 签名 terminal closure "
                                f"已验证；因子终态为 {formal_verdict}，未再次启动"
                                "研究代理或父 wrapper。"
                            ),
                            "next_actions": [],
                            "host_attestation_id": str(
                                resume_trust.get("attestation_id") or ""
                            ),
                            "evo_v2_external_progress": deepcopy(
                                resume_trust.get("evo_v2_external_progress")
                            ),
                            "evo_v2_terminal_checkpoint": checkpoint,
                            "current_formal_authority": current_authority,
                        }
                    )
                    self.store.update_job(
                        job.job_id,
                        execution_status="COMPLETED",
                        protocol_status="PASS",
                        factor_verdict=formal_verdict,
                        council_status="NOT_REQUIRED",
                        formal_proof_eligible=True,
                        current_stage="completed",
                        error_code="",
                        error_message="",
                        result=preserved_result,
                        finished_at_utc=utc_now(),
                    )
                    self.store.append_event(
                        job.job_id,
                        "EVO_V2_TERMINAL_CHECKPOINT_ACCEPTED",
                        "Host 签名 terminal closure 已通过精确重放，任务直接进入终态。",
                        {
                            "factor_verdict": formal_verdict,
                            "terminal_decision": checkpoint[
                                "terminal_decision"
                            ],
                            "closure_path": checkpoint[
                                "terminal_closure_path"
                            ],
                            "closure_sha256": checkpoint[
                                "terminal_closure_sha256"
                            ],
                            "checkpoint_path": checkpoint["path"],
                            "checkpoint_sha256": checkpoint["sha256"],
                            "agent_invoked": False,
                            "parent_wrapper_invoked": False,
                        },
                    )
                    private_completion_status = PRIVATE_LIFECYCLE_TERMINAL
                    private_attestation_id = str(
                        resume_trust.get("attestation_id") or ""
                    )
                    return
                if resume_route.kind == RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY:
                    if resume_trust is None:
                        raise RuntimeError(
                            f"{BLOCK_RESUME_TRUST_INVALID}: child handoff trust is missing"
                        )
                    child_report_id = str(resume_route.pause_token or "")
                    child_parent_report_id = (
                        str(child_state.get("parent_report_id") or job.report_id)
                        if evo_v2_child_runtime_resume
                        else job.report_id
                    )
                    child_runtime = self._execute_evo_v2_child_from_parent_handoff(
                        job,
                        worktree=worktree,
                        workspace=workspace,
                        resume_trust=resume_trust,
                        child_report_id=child_report_id,
                        parent_report_id=child_parent_report_id,
                        trusted_prior_execution=(
                            child_state if evo_v2_child_runtime_resume else None
                        ),
                    )
                    child_execution = child_runtime["execution"]
                    child_status = str(child_execution.get("status") or "")
                    if child_status not in {
                        CHILD_RESUME_READY,
                        CHILD_RECOVERY_READY,
                        CHILD_TERMINAL,
                    }:
                        raise RuntimeError(
                            f"{BLOCK_RESUME_TRUST_INVALID}: child execution state is invalid"
                        )
                    child_terminal_verdict = str(
                        child_execution.get("scientific_factor_verdict") or ""
                    )
                    child_terminal_is_trusted = bool(
                        child_status == CHILD_TERMINAL
                        and (
                            child_execution.get("terminal_checkpoint") is True
                            or child_execution.get(
                                "host_execution_receipt_verified"
                            )
                            is True
                        )
                        and child_execution.get("proof_status") == "PASS"
                        and child_execution.get("returncode") == 0
                        and child_terminal_verdict in {"ACCEPT", "REJECT"}
                    )
                    child_current_authority: dict[str, Any] | None = None
                    if child_terminal_is_trusted:
                        transaction_stack.close()
                        transaction_stack = ExitStack()
                        child_incident_guard = transaction_stack.enter_context(
                            _host_current_authority_transaction(
                                state_root=self.config.state_root,
                                workspace_root=workspace,
                                installation_id=self.config.installation_id,
                            )
                        )
                        child_current_authority = (
                            validate_current_ultimate_authority(
                                workspace,
                                report_id=child_report_id,
                                expected_factor_verdict=child_terminal_verdict,
                                formal_proof_eligible=True,
                                incident_trust_root=(
                                    self.config.state_root
                                    / "research-org-trust"
                                ),
                                incident_installation_id=(
                                    self.config.installation_id
                                ),
                                _incident_guard=child_incident_guard,
                            )
                        )
                        if child_current_authority.get("status") != "PASS":
                            raise RuntimeError(
                                ";".join(
                                    child_current_authority.get("block_reasons")
                                    or [BLOCK_HOST_FORMAL_EXECUTION_FAILED]
                                )
                            )
                    preserved_result = (
                        dict(job.result) if isinstance(job.result, dict) else {}
                    )
                    preserved_result.update(
                        {
                            "summary": (
                                "EVO V2 子代已完成 Host admission 与隔离 Ultimate "
                                f"执行；当前状态为 {child_status}。"
                            ),
                            "next_actions": (
                                [
                                    "从 Host 签名 child execution receipt 的精确 "
                                    f"Step{child_execution.get('resume_start_step')} 继续子代，"
                                    "不得重跑父代。"
                                ]
                                if child_status in {
                                    CHILD_RESUME_READY,
                                    CHILD_RECOVERY_READY,
                                }
                                else []
                            ),
                            "evo_v2_external_progress": deepcopy(
                                resume_trust.get("evo_v2_external_progress")
                            ),
                            "evo_v2_child_runtime": child_runtime,
                            "current_formal_authority": (
                                child_current_authority
                                if child_current_authority is not None
                                else {
                                    "status": "NOT_APPLICABLE",
                                    "formal_proof_eligible": False,
                                }
                            ),
                        }
                    )
                    self.store.update_job(
                        job.job_id,
                        execution_status=(
                            "REVIEW_REQUIRED"
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else "COMPLETED"
                        ),
                        protocol_status=(
                            "PAUSED"
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else (
                                "PASS"
                                if child_execution.get("proof_status") == "PASS"
                                and child_execution.get("returncode") == 0
                                else "FAIL"
                            )
                        ),
                        factor_verdict=(
                            job.factor_verdict
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else (
                                child_terminal_verdict
                                if child_terminal_is_trusted
                                else "UNKNOWN"
                            )
                        ),
                        council_status=(
                            "PAUSED"
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else "NOT_REQUIRED"
                        ),
                        formal_proof_eligible=child_terminal_is_trusted,
                        current_stage=(
                            "evo_v2_child_recovery_ready"
                            if child_status == CHILD_RECOVERY_READY
                            else "evo_v2_child_resume_ready"
                            if child_status == CHILD_RESUME_READY
                            else "evo_v2_child_terminal"
                        ),
                        error_code=(
                            EVO_V2_CHILD_EXECUTION_READY
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else ""
                        ),
                        error_message=(
                            "子代隔离执行已暂停在 Host 签名 resume point。"
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else ""
                        ),
                        result=preserved_result,
                        finished_at_utc=(
                            ""
                            if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                            else utc_now()
                        ),
                    )
                    self.store.append_event(
                        job.job_id,
                        child_status,
                        preserved_result["summary"],
                        {
                            "parent_report_id": str(
                                child_execution.get("parent_report_id")
                                or job.report_id
                            ),
                            "child_report_id": child_report_id,
                            "execution_receipt_path": child_execution[
                                "execution_receipt_path"
                            ],
                            "execution_receipt_sha256": child_execution[
                                "execution_receipt_sha256"
                            ],
                            "resume_start_step": child_execution.get(
                                "resume_start_step"
                            ),
                            "parent_wrapper_invoked": False,
                        },
                    )
                    private_completion_status = (
                        PRIVATE_LIFECYCLE_RESUMABLE
                        if child_status in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
                        else PRIVATE_LIFECYCLE_TERMINAL
                    )
                    private_attestation_id = str(
                        resume_trust.get("attestation_id") or ""
                    )
                    return
                if resume_route.kind == RESUME_KIND_EVO_V2_EXTERNAL_WAIT:
                    summary_message, next_action, error_code = (
                        _evo_v2_external_resume_message(resume_route)
                    )
                    preserved_result = (
                        dict(job.result) if isinstance(job.result, dict) else {}
                    )
                    preserved_result["summary"] = summary_message
                    preserved_result["next_actions"] = [next_action]
                    preserved_result["evo_v2_external_progress"] = deepcopy(
                        resume_trust.get("evo_v2_external_progress")
                    )
                    self.store.update_job(
                        job.job_id,
                        execution_status="REVIEW_REQUIRED",
                        protocol_status="PAUSED",
                        factor_verdict=job.factor_verdict,
                        council_status="PAUSED",
                        current_stage=(
                            "evo_v2_external_control_required"
                        ),
                        error_code=error_code,
                        error_message=summary_message,
                        result=preserved_result,
                        finished_at_utc="",
                    )
                    self.store.append_event(
                        job.job_id,
                        (
                            "EVO_V2_EXTERNAL_CONTROL_REQUIRED"
                        ),
                        summary_message,
                        {
                            "pause_state": resume_route.pause_state,
                            "reason": resume_route.pause_token,
                        },
                    )
                    private_completion_status = PRIVATE_LIFECYCLE_RESUMABLE
                    private_attestation_id = str(
                        resume_trust.get("attestation_id") or ""
                    )
                    return
                if resume_route.kind == RESUME_KIND_COUNCIL_INGRESS:
                    council_ingress_tasks = _trusted_council_ingress_tasks(
                        workspace,
                        report_id=job.report_id,
                        trusted_resume_proof_sha256=str(
                            resume_trust["ultimate_proof_sha256"]
                        ),
                    )
                    if not council_ingress_tasks:
                        raise RuntimeError(
                            f"{BLOCK_RESUME_TRUST_INVALID}: Council resume has no trusted ingress tasks"
                        )
                if resume_route.kind in {
                    RESUME_KIND_MECHANISM_AGENT,
                    RESUME_KIND_COUNCIL_INGRESS,
                    RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS,
                }:
                    expected_agent_paths = tuple(
                        task.expected_result_path for task in council_ingress_tasks
                    )
                    if resume_route.kind == RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS:
                        expected_agent_paths = (
                            _pre_oos_root_synthesis_relative(job.report_id),
                        )
                    resume_restore_state = _capture_resume_restore_state(
                        workspace,
                        report_id=job.report_id,
                        expected_absent_paths=expected_agent_paths,
                        managed_directories=tuple(
                            sorted(
                                {
                                    Path(relative).parent.as_posix()
                                    for relative in expected_agent_paths
                                    if not (workspace / Path(relative).parent).is_dir()
                                }
                            )
                        ),
                    )
                if not evo_v2_memory_resume and not evo_v2_child_runtime_resume:
                    self._write_request_artifacts(
                        job,
                        allocation,
                        preserve_plan=True,
                        trusted_resume_start_step=str(resume_trust["start_step"]),
                        trusted_resume_context=resume_trust,
                    )
                    self._write_resume_authorization(job, workspace)
                if resume_route.kind == RESUME_KIND_MECHANISM_AGENT:
                    resume_task = self._write_agent_resume_contract(
                        job,
                        workspace,
                        resume_trust=resume_trust,
                        attempt_id=f"resume_{uuid.uuid4().hex}",
                    )
                elif resume_route.kind == RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS:
                    pre_oos_root_synthesis_task = (
                        _write_pre_oos_root_synthesis_task(
                            job,
                            workspace,
                            trusted_resume_proof_sha256=str(
                                resume_trust["ultimate_proof_sha256"]
                            ),
                            attempt_id=f"resume_{uuid.uuid4().hex}",
                        )
                    )
            else:
                allocation = self.allocator.allocate(
                    factor_id=job.factor_id,
                    research_id=job.research_id,
                    report_id=job.report_id,
                    implementation_mode="operator",
                )
                worktree = allocation.worktree_path
                workspace = allocation.workspace_path
                self.store.update_job(
                    job.job_id,
                    base_commit=allocation.base_commit,
                    worktree_path=str(worktree),
                    workspace_path=str(workspace),
                    current_stage="researching",
                )
                self._write_request_artifacts(job, allocation)
                self.store.append_event(
                    job.job_id,
                    "WORKTREE_ALLOCATED",
                    "已分配固定代码版本的独立 Git worktree 和 factor workspace",
                    {"base_commit": allocation.base_commit},
                )

                organization = validate_research_organization_bundle(
                    workspace=workspace
                )
                if organization["state"] != "ROUTED":
                    private_attestation_id = self._pause_for_research_org_gate(
                        job=job,
                        workspace=workspace,
                        runtime=None,
                    )
                    private_completion_status = PRIVATE_LIFECYCLE_TERMINAL
                    return

                if self._research_org_runtime_available():
                    organization_runtime_required = True
                    organization_runtime = self._run_research_org_stage(
                        job,
                        worktree=worktree,
                        workspace=workspace,
                        stage="specialist_intake",
                    )
                    if organization_runtime["lifecycle"] != "WAITING_HOST_RESULT":
                        private_attestation_id = self._pause_for_research_org_gate(
                            job=job,
                            workspace=workspace,
                            runtime=organization_runtime,
                        )
                        private_completion_status = PRIVATE_LIFECYCLE_TERMINAL
                        return
                elif not self.config.auth_disabled:
                    raise RuntimeError(
                        f"{BLOCK_RESEARCH_ORG_RUNTIME_REQUIRED}: "
                        "production web research requires the isolated specialist runtime"
                    )
                else:
                    self.store.append_event(
                        job.job_id,
                        "RESEARCH_ORG_DEVELOPMENT_BYPASS",
                        "开发测试 adapter 未提供 specialist runtime；不得据此声明正式组织独立性",
                        {},
                    )

            uses_research_agent = bool(
                not resume
                or (
                    resume_route is not None
                    and resume_route.kind
                    in {
                        RESUME_KIND_MECHANISM_AGENT,
                        RESUME_KIND_COUNCIL_INGRESS,
                        RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS,
                    }
                )
            )
            if uses_research_agent:
                agent_write_snapshot = _workspace_file_snapshot(workspace)
                allowed_agent_writes, required_agent_outputs = _allowed_agent_write_paths(
                    workspace,
                    report_id=job.report_id,
                    resume=resume,
                    require_research_director_record=(
                        organization_runtime_required and not resume
                    ),
                    trusted_resume_proof_sha256=(
                        str(resume_trust["ultimate_proof_sha256"])
                        if resume_trust is not None
                        else None
                    ),
                    council_ingress_tasks=council_ingress_tasks,
                    pre_oos_root_synthesis_task=pre_oos_root_synthesis_task,
                )
            else:
                agent_write_snapshot = {}
                allowed_agent_writes = set()
                required_agent_outputs = set()

            self.store.update_job(
                job.job_id,
                execution_status="RESEARCHING",
                protocol_status="RUNNING",
                current_stage=(
                    "researching" if uses_research_agent else "formal_checkpoint_retry"
                ),
            )
            if uses_research_agent:
                self.store.append_event(
                    job.job_id,
                    "AGENT_STARTED" if not resume else "AGENT_RESUMED",
                    "隔离研究代理已启动" if not resume else "研究代理已从现有证据继续",
                    {},
                )
            else:
                self.store.append_event(
                    job.job_id,
                    "HOST_FORMAL_CHECKPOINT_RETRY_STARTED",
                    "主机正在从可信失败检查点重试正式步骤，未启动研究代理",
                    {"start_step": resume_route.start_step if resume_route else ""},
                )
            current_job = self.store.get_job(job.job_id) or job
            if pre_oos_root_synthesis_task is not None:
                run_pre_oos_root_synthesis = (
                    _pre_oos_root_synthesis_runner(self.agent_adapter)
                )
                agent_result = run_pre_oos_root_synthesis(
                    current_job,
                    worktree=worktree,
                    workspace=workspace,
                    task=pre_oos_root_synthesis_task,
                )
            elif council_ingress_tasks:
                run_council_ingress = getattr(
                    self.agent_adapter,
                    "run_council_ingress",
                    None,
                )
                if not callable(run_council_ingress):
                    raise RuntimeError(
                        "BLOCK_FACTORFORGE_CONSOLE_COUNCIL_INGRESS_UNAVAILABLE: "
                        "isolated Council ingress adapter is missing"
                    )
                agent_result = run_council_ingress(
                    current_job,
                    worktree=worktree,
                    workspace=workspace,
                    tasks=council_ingress_tasks,
                )
            elif uses_research_agent:
                if resume:
                    if resume_task is None:
                        raise RuntimeError(
                            f"{BLOCK_RESUME_TRUST_INVALID}: typed resume task is missing"
                        )
                    agent_result = self.agent_adapter.run(
                        current_job,
                        worktree=worktree,
                        workspace=workspace,
                        resume=True,
                        resume_task=resume_task,
                    )
                else:
                    agent_result = self.agent_adapter.run(
                        current_job,
                        worktree=worktree,
                        workspace=workspace,
                        resume=False,
                    )
            else:
                if resume_route is None or resume_route.kind not in {
                    RESUME_KIND_HOST_FORMAL_CHECKPOINT,
                    RESUME_KIND_EVO_V2_MEMORY_GATE,
                }:
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: host formal resume route is invalid"
                    )
                agent_result = self._write_host_formal_checkpoint_result(
                    current_job,
                    start_step=resume_route.start_step,
                )
            denied_values = _adapter_denied_values(self.agent_adapter, job.job_id)
            self.store.update_job(
                job.job_id,
                agent_id=agent_result.agent_id,
                agent_session_key=agent_result.session_key,
                execution_status="VERIFYING",
                current_stage="verifying",
            )
            self.store.append_event(
                job.job_id,
                "AGENT_FINISHED" if uses_research_agent else "HOST_FORMAL_CHECKPOINT_READY",
                (
                    "研究代理已返回，开始核验正式证据"
                    if uses_research_agent
                    else "可信失败检查点已通过主机预检，开始正式重试"
                ),
                {"returncode": agent_result.returncode},
            )

            if uses_research_agent:
                _validate_agent_write_boundary(
                    workspace,
                    before=agent_write_snapshot,
                    allowed=allowed_agent_writes,
                    required=(
                        required_agent_outputs
                        if agent_result.returncode == 0
                        else set()
                    ),
                )
            if agent_result.returncode != 0:
                raise RuntimeError(
                    f"BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: returncode={agent_result.returncode}"
                )
            if (
                resume
                and resume_route is not None
                and resume_route.kind == RESUME_KIND_MECHANISM_AGENT
            ):
                validated_resume_artifacts = self._validate_agent_resume_artifact(
                    current_job,
                    workspace,
                    resume_trust=resume_trust or {},
                    resume_task=resume_task,
                    agent_result=agent_result,
                )
                validated_agent_receipt = ValidatedAgentReceipt(
                    receipt_id=validated_resume_artifacts.agent_run_receipt_id,
                    receipt_sha256=validated_resume_artifacts.agent_run_receipt_sha256,
                )
            elif (
                resume
                and resume_route is not None
                and resume_route.kind == RESUME_KIND_COUNCIL_INGRESS
            ):
                validated_agent_receipt = self._validate_council_ingress_receipt(
                    current_job,
                    workspace,
                    tasks=council_ingress_tasks,
                    agent_result=agent_result,
                )
            elif (
                resume
                and resume_route is not None
                and resume_route.kind == RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS
            ):
                if pre_oos_root_synthesis_task is None:
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS root synthesis task is missing"
                    )
                validated_agent_receipt = (
                    self._validate_pre_oos_root_synthesis_receipt(
                        current_job,
                        workspace,
                        task=pre_oos_root_synthesis_task,
                        agent_result=agent_result,
                    )
                )

            if organization_runtime_required:
                self._admit_host_research_director_result(
                    job=current_job,
                    workspace=workspace,
                    agent_result=agent_result,
                )
                organization_runtime = self._run_research_org_stage(
                    current_job,
                    worktree=worktree,
                    workspace=workspace,
                    stage="specialist_verification_and_council",
                )
                if (
                    organization_runtime["lifecycle"] != "COMPLETE"
                    or organization_runtime["formal_independence_verified"] is not True
                ):
                    private_attestation_id = self._pause_for_research_org_gate(
                        job=current_job,
                        workspace=workspace,
                        runtime=organization_runtime,
                    )
                    private_completion_status = PRIVATE_LIFECYCLE_TERMINAL
                    return

            if (
                current_job.request.research_scope
                == RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
            ):
                isolation_failures = audit_factor_worktree(worktree, workspace)
                if isolation_failures:
                    raise RuntimeError(
                        f"{BLOCK_ISOLATION_AUDIT_FAILED}: "
                        f"{'; '.join(isolation_failures)}"
                    )
                with workspace_transaction_lock(
                    self.config.state_root,
                    workspace,
                    error_code=BLOCK_RESUME_TRUST_INVALID,
                ):
                    preformal_checkpoint = (
                        self._write_preformal_design_checkpoint(
                            current_job,
                            workspace=workspace,
                        )
                    )
                self._record_preformal_design_completion(
                    current_job,
                    checkpoint=preformal_checkpoint,
                    recovered=False,
                )
                private_completion_status = PRIVATE_LIFECYCLE_TERMINAL
                private_attestation_id = preformal_checkpoint["receipt_id"]
                return

            if validated_resume_artifacts is not None:
                _require_validated_resume_artifacts_unchanged(
                    workspace,
                    state_root=self.config.state_root,
                    resume_task=resume_task,
                    validation=validated_resume_artifacts,
                )
            isolation_failures = audit_factor_worktree(worktree, workspace)
            if isolation_failures:
                raise RuntimeError(f"{BLOCK_ISOLATION_AUDIT_FAILED}: {'; '.join(isolation_failures)}")
            host_data_env: dict[str, str] = {}
            prepare_host_data = getattr(
                self.agent_adapter,
                "prepare_host_data_environment",
                None,
            )
            if callable(prepare_host_data):
                host_data_env, host_denied_values = prepare_host_data(job.job_id)
                denied_values = tuple(
                    dict.fromkeys((*denied_values, *host_denied_values))
                )
            elif self.config.execution_mode == "container" and not self.config.auth_disabled:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease provider is missing"
                )
            try:
                formal_resume = bool(resume and not evo_v2_memory_resume)
                formal_execution = self._execute_host_formal_pipeline(
                    current_job,
                    worktree=worktree,
                    workspace=workspace,
                    resume=formal_resume,
                    denied_values=denied_values,
                    host_data_env=host_data_env,
                    resume_trust=(resume_trust if formal_resume else None),
                    resume_task=(resume_task if formal_resume else None),
                    validated_resume_artifacts=(
                        validated_resume_artifacts if formal_resume else None
                    ),
                )
            except EvoV2MemoryGatePause as pause:
                private_attestation_id = self._pause_for_evo_v2_memory_gate(
                    job=current_job,
                    workspace=workspace,
                    state=pause.state,
                    formal_receipt=pause.receipt,
                )
                private_completion_status = PRIVATE_LIFECYCLE_RESUMABLE
                return
            if validated_resume_artifacts is not None:
                _require_validated_resume_artifacts_unchanged(
                    workspace,
                    state_root=self.config.state_root,
                    resume_task=resume_task,
                    validation=validated_resume_artifacts,
                    allowed_workspace_changes=_formal_owned_resume_relatives(
                        resume_task
                    ),
                )
            isolation_failures = audit_factor_worktree(worktree, workspace)
            if isolation_failures:
                raise RuntimeError(f"{BLOCK_ISOLATION_AUDIT_FAILED}: {'; '.join(isolation_failures)}")
            organization_plan_path = (
                workspace / "identity" / "research_organization_plan.json"
            )
            if organization_plan_path.is_symlink() or (
                organization_plan_path.exists()
                and not organization_plan_path.is_file()
            ):
                raise RuntimeError(
                    "BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_INVALID: unsafe plan path"
                )
            if organization_plan_path.is_file():
                organization_validation = validate_research_organization_bundle(
                    workspace=workspace
                )
                organization_plan = load_research_organization_plan(workspace)
                organization_runtime_path = (
                    workspace
                    / str(organization_plan["workspace_policy"]["organization_root"])
                    / "runtime"
                    / "runtime_state.json"
                )
                organization_runtime = (
                    validate_research_organization_runtime(
                        workspace=workspace,
                        require_complete=not self.config.auth_disabled,
                        private_root=(
                            self.config.state_root
                            / "jobs"
                            / current_job.job_id
                            / "research_org_private"
                        ),
                        trust_root=self.config.state_root / "research-org-trust",
                        installation_id=self.config.installation_id,
                        require_formal=not self.config.auth_disabled,
                    )
                    if organization_runtime_path.exists()
                    or organization_runtime_path.is_symlink()
                    else None
                )
            else:
                # Jobs created before the v1 organization contract remain
                # resumable, but they receive no organization assurance.
                organization_validation = None
                organization_plan = None
                organization_runtime = None
            # The Agent/wrapper phase is complete.  Release any earlier
            # workspace-only transaction, then reacquire locks in the sole
            # authority order: incident registry first, workspace second.  This
            # guard remains live through attestation, formal memory, and DB CAS.
            transaction_stack.close()
            transaction_stack = ExitStack()
            incident_guard = transaction_stack.enter_context(
                _host_current_authority_transaction(
                    state_root=self.config.state_root,
                    workspace_root=workspace,
                    installation_id=self.config.installation_id,
                )
            )
            attested_workspace = self._snapshot_workspace_evidence(
                current_job,
                workspace,
            )
            web_materialization = validate_materialized_web_research(
                attested_workspace
            )
            evo_v2_memory_enabled = is_validated_evo_v2_memory_runtime_enabled(
                workspace=attested_workspace,
                report_id=current_job.report_id,
                validated_materialization=web_materialization,
            )
            current_read = read_current_ultimate_workspace(
                attested_workspace,
                report_id=job.report_id,
                incident_trust_root=(
                    self.config.state_root / "research-org-trust"
                ),
                incident_installation_id=self.config.installation_id,
                _incident_guard=incident_guard,
            )
            summary = current_read.summary
            current_authority_validation = current_read.authority_validation
            self._validate_summary_identity(current_job, summary)
            require_formal_organization = bool(
                organization_plan is not None and not self.config.auth_disabled
            )
            execution_status = _web_execution_status(
                summary,
                agent_result.returncode,
                organization_runtime=organization_runtime,
                require_formal_organization=require_formal_organization,
            )
            normalized_protocol_status = _normalize_protocol(summary.protocol_status)
            normalized_factor_verdict = (
                "BLOCK"
                if execution_status == "BLOCKED"
                and require_formal_organization
                else summary.factor_verdict
            )
            normalized_council_status = _normalize_council(summary.council_status)
            normalized_formal_proof_eligible = bool(
                summary.formal_proof_eligible
                and current_authority_validation.get("status") == "PASS"
                and (
                    not require_formal_organization
                    or (
                        organization_runtime is not None
                        and organization_runtime.get(
                            "formal_independence_verified"
                        )
                        is True
                    )
                )
            )
            runtime_ledger = (
                organization_runtime.get("transactional_ledger")
                if isinstance(organization_runtime, dict)
                else None
            )
            organization_runtime_verified = bool(
                isinstance(organization_runtime, dict)
                and organization_runtime.get("lifecycle") == "COMPLETE"
                and organization_runtime.get("formal_independence_verified")
                is True
                and organization_runtime.get("runtime_assurance")
                == "signed_specialist_runtime_complete_host_director_external"
                and isinstance(runtime_ledger, dict)
                and runtime_ledger.get("ledger_state") == "COMPLETE"
                and runtime_ledger.get("formal_independence_verified") is True
                and runtime_ledger.get("assurance")
                == "signed_specialist_runtime_complete_host_director_external"
            )
            researcher_memory_attested_outcome = {
                "execution_status": execution_status,
                "protocol_status": normalized_protocol_status,
                "factor_verdict": normalized_factor_verdict,
                "council_status": normalized_council_status,
                "formal_proof_eligible": normalized_formal_proof_eligible,
                "organization_runtime_verified": organization_runtime_verified,
                "roles": list(
                    (organization_plan.get("role_plan") or {}).get(
                        "required_roles"
                    )
                    or []
                ),
            }
            host_attestation_id = self._write_host_attestation(
                job=current_job,
                workspace=workspace,
                evidence_root=attested_workspace,
                summary=summary,
                agent_result=agent_result,
                web_materialization=web_materialization,
                formal_execution=formal_execution,
                resume_task=resume_task,
                validated_resume_artifacts=validated_resume_artifacts,
                validated_agent_receipt=validated_agent_receipt,
                researcher_memory_outcome=researcher_memory_attested_outcome,
                current_authority_validation=current_authority_validation,
            )
            researcher_memory_outcome: dict[str, Any] | None = None
            evo_v2_episode_registration: dict[str, Any] | None = None
            memory_binding = (
                organization_plan.get("researcher_memory")
                if isinstance(organization_plan, dict)
                else None
            )
            publication_id, public_artifacts = publish_official_artifacts(
                attested_workspace,
                self.config.state_root / "public" / job.job_id,
                role_artifact_ids=summary.artifact_ids,
                identity={
                    "job_id": job.job_id,
                    "report_id": job.report_id,
                    "factor_id": job.factor_id,
                    "research_id": job.research_id,
                },
                denied_values=denied_values,
            )
            result = _redact_public_payload(
                build_web_result(
                    summary,
                    publication_id=publication_id,
                    public_artifacts=public_artifacts,
                ),
                denied_values,
            )
            if organization_plan is not None and organization_validation is not None:
                organization_roles = organization_plan.get("role_plan") or {}
                result["research_organization"] = {
                    "contract_version": organization_plan.get("contract_version"),
                    "state": organization_plan.get("state"),
                    "lead_domain": organization_validation.get("lead_domain"),
                    "supporting_domains": organization_validation.get("supporting_domains") or [],
                    "required_roles": organization_roles.get("required_roles") or [],
                    "deferred_roles": organization_roles.get("deferred_roles") or [],
                    "capability_gaps": (
                        organization_plan.get("routing", {}).get("capability_gaps") or []
                    ),
                    "dispatch_task_count": organization_validation.get("task_count", 0),
                    "validated_result_count": organization_validation.get("result_count", 0),
                    "execution_state": organization_validation.get("execution_state"),
                    "council_independence_attestation_valid": (
                        organization_validation.get(
                            "council_independence_attestation_valid", False
                        )
                    ),
                    "independence_satisfied": bool(
                        organization_runtime is not None
                        and organization_runtime.get(
                            "formal_independence_verified"
                        )
                        is True
                    ),
                    "runtime": organization_runtime,
                    "assurance": (
                        "validated_results_and_signed_runtime_independence"
                        if organization_runtime is not None
                        and organization_runtime.get(
                            "formal_independence_verified"
                        )
                        is True
                        else "routing_and_dispatch_contract_only"
                        if organization_runtime is None
                        else "verified_runtime_history_partial"
                    ),
                }
            else:
                result["research_organization"] = {
                    "contract_version": None,
                    "state": "LEGACY_NOT_PRESENT",
                    "lead_domain": None,
                    "supporting_domains": [],
                    "required_roles": [],
                    "deferred_roles": [],
                    "capability_gaps": [],
                    "dispatch_task_count": 0,
                    "validated_result_count": 0,
                    "execution_state": "LEGACY_NOT_PRESENT",
                    "independence_satisfied": False,
                    "runtime": None,
                    "assurance": "legacy_no_research_organization_contract",
                }
            result["host_attestation_id"] = host_attestation_id
            result["current_formal_authority"] = current_authority_validation
            result["model_execution"] = {
                "provider": agent_result.provider,
                "model": agent_result.model,
                "provenance": "host_pinned_agent_runtime",
            }
            finished = utc_now() if execution_status in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"} else ""
            error_code, error_message = _web_terminal_error(
                execution_status=execution_status,
                summary=summary,
                require_formal_organization=require_formal_organization,
                organization_runtime_verified=organization_runtime_verified,
                denied_values=denied_values,
            )
            if (
                isinstance(memory_binding, dict)
                and execution_status == "COMPLETED"
                and normalized_factor_verdict in {"ACCEPT", "REJECT"}
                and organization_runtime_verified
                and current_authority_validation.get("status") == "PASS"
            ):
                attestation_path = self.config.state_root / host_attestation_id
                try:
                    researcher_memory_outcome = record_research_outcome(
                        self.config.state_root / "researcher-memory",
                        installation_id=self.config.installation_id,
                        store_id=str(memory_binding.get("store_id") or ""),
                        identity={
                            "job_id": current_job.job_id,
                            "factor_id": current_job.factor_id,
                            "research_id": current_job.research_id,
                            "report_id": current_job.report_id,
                        },
                        role_ids=list(
                            (organization_plan.get("role_plan") or {}).get(
                                "required_roles"
                            )
                            or []
                        ),
                        execution_status=execution_status,
                        protocol_status=normalized_protocol_status,
                        factor_verdict=normalized_factor_verdict,
                        council_status=normalized_council_status,
                        formal_proof_eligible=normalized_formal_proof_eligible,
                        organization_runtime_verified=True,
                        host_attestation_ref={
                            "id": host_attestation_id,
                            "sha256": _sha256(attestation_path),
                        },
                        model_execution={
                            "provider": agent_result.provider or "unknown",
                            "model": agent_result.model or "unknown",
                            "provenance": "host_pinned_agent_runtime",
                        },
                        repo_root=worktree,
                        workspace=workspace,
                    )
                    if evo_v2_memory_enabled:
                        try:
                            evo_v2_episode_registration = (
                                register_terminal_historical_episode_candidate(
                                    root=(
                                        self.config.state_root
                                        / "researcher-memory-evo-v2-episodes"
                                    ),
                                    evidence_workspace=attested_workspace,
                                    repo_root=worktree,
                                    state_root=self.config.state_root,
                                    installation_id=self.config.installation_id,
                                    identity={
                                        "job_id": current_job.job_id,
                                        "factor_id": current_job.factor_id,
                                        "research_id": current_job.research_id,
                                        "report_id": current_job.report_id,
                                    },
                                    terminal_outcome=researcher_memory_attested_outcome,
                                    outcome_event_ref={
                                        "event_id": researcher_memory_outcome[
                                            "event_id"
                                        ],
                                        "event_sha256": researcher_memory_outcome[
                                            "event_sha256"
                                        ],
                                        "path": researcher_memory_outcome["path"],
                                    },
                                    host_attestation_ref={
                                        "id": host_attestation_id,
                                        "sha256": _sha256(attestation_path),
                                    },
                                )
                            )
                        except Exception as exc:  # noqa: BLE001 - secondary governance write.
                            episode_error_token = getattr(
                                exc,
                                "token",
                                BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID,
                            )
                            if not isinstance(episode_error_token, str) or not re.fullmatch(
                                r"[A-Z0-9_]+",
                                episode_error_token,
                            ):
                                episode_error_token = (
                                    BLOCK_EVO_V2_HISTORICAL_EPISODE_INVALID
                                )
                            evo_v2_episode_registration = {
                                "status": "WRITE_BLOCKED",
                                "authority": "historical_episode_candidate_only",
                                "retryable": True,
                                "error_code": episode_error_token,
                                "formal_outcome_preserved": True,
                                "structural_or_conditional_lesson_generated": False,
                            }
                except Exception as exc:  # noqa: BLE001 - secondary governance write.
                    memory_error_token = getattr(
                        exc,
                        "token",
                        BLOCK_MEMORY_STORE_INVALID,
                    )
                    if not isinstance(memory_error_token, str) or not re.fullmatch(
                        r"[A-Z0-9_]+",
                        memory_error_token,
                    ):
                        memory_error_token = BLOCK_MEMORY_STORE_INVALID
                    result["researcher_memory"] = {
                        "status": "WRITE_BLOCKED",
                        "authority": "host_private_store",
                        "retryable": True,
                        "error_code": memory_error_token,
                        "formal_outcome_preserved": True,
                    }
            result["researcher_memory"] = (
                {
                    "status": "OUTCOME_RECORDED",
                    "authority": "host_private_store",
                    **researcher_memory_outcome,
                }
                if researcher_memory_outcome is not None
                else result.get("researcher_memory")
                or {
                    "status": (
                        "AWAITING_VERIFIED_ORGANIZATION_OUTCOME"
                        if isinstance(memory_binding, dict)
                        and not organization_runtime_verified
                        else "AWAITING_TERMINAL_OUTCOME"
                        if isinstance(memory_binding, dict)
                        else "LEGACY_NOT_ENABLED"
                    ),
                    "authority": (
                        "host_private_store"
                        if isinstance(memory_binding, dict)
                        else "none"
                    ),
                }
            )
            if evo_v2_episode_registration is not None:
                result["researcher_memory"]["evo_v2_historical_episode"] = (
                    {
                        "status": "CANDIDATE_RECORDED",
                        **evo_v2_episode_registration,
                    }
                    if evo_v2_episode_registration.get("status")
                    != "WRITE_BLOCKED"
                    else evo_v2_episode_registration
                )
            updated = self.store.update_job(
                job.job_id,
                execution_status=execution_status,
                protocol_status=normalized_protocol_status,
                factor_verdict=normalized_factor_verdict,
                council_status=normalized_council_status,
                formal_proof_eligible=normalized_formal_proof_eligible,
                current_stage=_web_stage(summary),
                result=result,
                error_code=error_code,
                error_message=error_message,
                finished_at_utc=finished,
            )
            self.store.append_event(
                job.job_id,
                "EVIDENCE_VERIFIED",
                f"证据核验完成：{updated.execution_status} / {updated.factor_verdict}",
                {
                    "protocol_status": updated.protocol_status,
                    "council_status": updated.council_status,
                    "formal_proof_eligible": updated.formal_proof_eligible,
                },
            )
            private_completion_status = (
                PRIVATE_LIFECYCLE_RESUMABLE
                if execution_status in {"REVIEW_REQUIRED", "BLOCKED", "FAILED"}
                else PRIVATE_LIFECYCLE_TERMINAL
            )
            private_attestation_id = host_attestation_id
        except (WorktreeAllocationError, FileNotFoundError, ValueError, RuntimeError) as exc:
            message = str(exc)
            registry_read_failed = False
            if not denied_values:
                try:
                    denied_values = _adapter_denied_values(self.agent_adapter, job.job_id)
                except (OSError, RuntimeError, ValueError):
                    registry_read_failed = True
            credential_state = "not_issued"
            if registry_read_failed:
                try:
                    credential_state = _adapter_credential_material_state(
                        self.agent_adapter,
                        job.job_id,
                    )
                except (OSError, RuntimeError, ValueError):
                    credential_state = "unknown"
            if registry_read_failed and credential_state != "not_issued":
                token = BLOCK_CREDENTIAL_REGISTRY_INVALID
                public_message = (
                    "临时凭证脱敏状态无法验证；任务已安全阻断，未公开原始异常详情。"
                )
            else:
                token = message.split(":", 1)[0] if message.startswith("BLOCK_") else "BLOCK_FACTORFORGE_CONSOLE_RUN_FAILED"
                public_message = _public_error_message(message, denied_values=denied_values)
            if (
                token in RETRYABLE_AGENT_RESUME_BLOCKERS
                and resume_restore_state is not None
                and resume_trust is not None
            ):
                try:
                    _restore_resume_workspace(
                        Path(job.workspace_path),
                        resume_restore_state,
                        report_id=job.report_id,
                        expected_tree_sha256=str(
                            resume_trust.get("workspace_evidence_tree_root_sha256")
                            or ""
                        ),
                    )
                    private_completion_status = PRIVATE_LIFECYCLE_RESUMABLE
                    private_attestation_id = str(
                        resume_trust.get("attestation_id") or ""
                    )
                    resume_parent_restored = True
                except (OSError, RuntimeError, UnicodeError, ValueError):
                    token = BLOCK_RESUME_TRUST_INVALID
                    public_message = (
                        "续跑交付失败后未能恢复到已认证暂停证据；当前任务已禁止再次续跑，"
                        "请新建隔离任务。"
                    )
            if token in NON_RESUMABLE_SECURITY_BLOCKERS:
                try:
                    self._mark_job_non_resumable(job, token=token)
                except (OSError, RuntimeError, ValueError):
                    token = BLOCK_RESUME_TRUST_INVALID
                    public_message = (
                        "任务触发安全阻断，且主机私有不可续跑标记未能可靠落盘；"
                        "当前任务已禁止续跑，请新建隔离任务。"
                    )
            failure_result = _result_without_resume_attestation(
                self.store.get_job(job.job_id) or job
            )
            if resume_parent_restored and private_attestation_id:
                failure_result["host_attestation_id"] = private_attestation_id
                failure_result["summary"] = public_message
                failure_result["next_actions"] = [
                    "父暂停证据已完整恢复；可从同一任务重新继续。"
                ]
            self.store.update_job(
                job.job_id,
                execution_status="BLOCKED" if token.startswith("BLOCK_") else "FAILED",
                protocol_status="BLOCK" if token.startswith("BLOCK_") else "FAIL",
                factor_verdict="BLOCK" if token.startswith("BLOCK_") else "UNKNOWN",
                formal_proof_eligible=False,
                current_stage="blocked" if token.startswith("BLOCK_") else "failed",
                error_code=token,
                error_message=public_message,
                result=failure_result,
                finished_at_utc=utc_now(),
            )
            self.store.append_event(
                job.job_id,
                "RUN_BLOCKED",
                public_message,
                {"code": token},
            )
        except Exception as exc:
            token = "BLOCK_FACTORFORGE_CONSOLE_INTERNAL_ERROR"
            self.store.update_job(
                job.job_id,
                execution_status="BLOCKED",
                protocol_status="BLOCK",
                factor_verdict="BLOCK",
                formal_proof_eligible=False,
                current_stage="blocked",
                error_code=token,
                error_message="研究服务发生未预期错误；任务证据已保留，未自动重试。",
                result=_result_without_resume_attestation(
                    self.store.get_job(job.job_id) or job
                ),
                finished_at_utc=utc_now(),
            )
            self.store.append_event(
                job.job_id,
                "RUN_BLOCKED",
                "研究服务发生未预期错误；任务证据已保留，未自动重试。",
                {"code": token, "exception_type": type(exc).__name__},
            )
        finally:
            try:
                transaction_stack.close()
            except (OSError, RuntimeError):
                transaction_release_failed = True
            cleanup_succeeded = not transaction_release_failed
            release = getattr(self.agent_adapter, "deactivate_denied_secrets", None)
            if not callable(release):
                release = getattr(self.agent_adapter, "clear_denied_secrets", None)
            if callable(release):
                try:
                    release(job.job_id)
                except (OSError, RuntimeError, ValueError):
                    cleanup_succeeded = False
                    try:
                        self._mark_job_non_resumable(
                            job,
                            token="BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
                        )
                    except (OSError, RuntimeError, ValueError):
                        pass
                    self.store.update_job(
                        job.job_id,
                        execution_status="BLOCKED",
                        protocol_status="BLOCK",
                        factor_verdict="BLOCK",
                        formal_proof_eligible=False,
                        current_stage="blocked",
                        error_code="BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
                        error_message="临时凭证脱敏 registry 未能安全停用，任务已阻断。",
                        result=_result_without_resume_attestation(
                            self.store.get_job(job.job_id) or job
                        ),
                        finished_at_utc=utc_now(),
                    )
            if transaction_release_failed:
                try:
                    self._mark_job_non_resumable(
                        job,
                        token=BLOCK_AGENT_ORPHANED_WRITER,
                    )
                except (OSError, RuntimeError, ValueError):
                    pass
                self.store.update_job(
                    job.job_id,
                    execution_status="BLOCKED",
                    protocol_status="BLOCK",
                    factor_verdict="BLOCK",
                    formal_proof_eligible=False,
                    current_stage="blocked",
                    error_code=BLOCK_AGENT_ORPHANED_WRITER,
                    error_message=(
                        "研究工作区单写者事务未能可靠释放；当前任务已禁止续跑，"
                        "请新建隔离任务。"
                    ),
                    result=_result_without_resume_attestation(
                        self.store.get_job(job.job_id) or job
                    ),
                    finished_at_utc=utc_now(),
                )
            if cleanup_succeeded and private_completion_status is not None:
                try:
                    self._finish_private_execution(
                        job,
                        status=private_completion_status,
                        attestation_id=private_attestation_id,
                    )
                except (OSError, RuntimeError, ValueError):
                    try:
                        self._mark_job_non_resumable(
                            job,
                            token=BLOCK_RESUME_TRUST_INVALID,
                        )
                    except (OSError, RuntimeError, ValueError):
                        pass
                    self.store.update_job(
                        job.job_id,
                        execution_status="BLOCKED",
                        protocol_status="BLOCK",
                        factor_verdict="BLOCK",
                        formal_proof_eligible=False,
                        current_stage="blocked",
                        error_code=BLOCK_RESUME_TRUST_INVALID,
                        error_message=(
                            "主机私有研究生命周期未能可靠完成；当前任务已禁止续跑，"
                            "请新建隔离任务。"
                        ),
                        result=_result_without_resume_attestation(
                            self.store.get_job(job.job_id) or job
                        ),
                        finished_at_utc=utc_now(),
                    )

    def _non_resumable_marker_path(self, job_id: str) -> Path:
        return (
            self.config.state_root
            / "jobs"
            / job_id
            / "security"
            / "non_resumable.json"
        )

    def _private_lifecycle_path(self, job_id: str) -> Path:
        return self.config.state_root / "jobs" / job_id / "security" / "lifecycle.json"

    @staticmethod
    def _private_lifecycle_identity(job: ResearchJob) -> dict[str, str]:
        return {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
        }

    def _read_private_lifecycle(self, job: ResearchJob) -> dict[str, Any] | None:
        path = self._private_lifecycle_path(job.job_id)
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle uses a symlink"
            )
        if not path.exists():
            return None
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.config.state_root.resolve(strict=True))
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is unreadable"
            ) from exc
        expected = self._private_lifecycle_identity(job)
        if (
            not isinstance(payload, dict)
            or payload.get("version") != PRIVATE_LIFECYCLE_VERSION
            or any(payload.get(key) != value for key, value in expected.items())
            or payload.get("status")
            not in {
                PRIVATE_LIFECYCLE_RUNNING,
                PRIVATE_LIFECYCLE_RESUMABLE,
                PRIVATE_LIFECYCLE_TERMINAL,
                PRIVATE_LIFECYCLE_NON_RESUMABLE,
            }
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle identity is invalid"
            )
        return payload

    def _write_private_lifecycle(
        self,
        job: ResearchJob,
        *,
        status: str,
        prior_status: str | None,
        attestation_id: str = "",
        blocker: str = "",
    ) -> None:
        try:
            security_root = ensure_host_private_job_subdirectory(
                self.config.state_root,
                job.job_id,
                ("security",),
                create=True,
            )
        except PrivateJobRootError as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: Host-private job root is unsafe"
            ) from exc
        path = security_root / "lifecycle.json"
        _write_json_atomic(
            path,
            {
                "version": PRIVATE_LIFECYCLE_VERSION,
                **self._private_lifecycle_identity(job),
                "status": status,
                "prior_status": prior_status,
                "attestation_id": attestation_id,
                "blocker": blocker,
                "updated_at_utc": utc_now(),
            },
            root=self.config.state_root,
        )

    def _begin_private_execution(self, job: ResearchJob, *, resume: bool) -> None:
        try:
            ensure_host_private_job_root(
                self.config.state_root,
                job.job_id,
                create=True,
            )
        except PrivateJobRootError as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: Host-private job root is unsafe"
            ) from exc
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        lifecycle = self._read_private_lifecycle(job)
        if (
            resume
            and job.request.research_scope
            == RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
            and isinstance(lifecycle, dict)
            and lifecycle.get("status") == PRIVATE_LIFECYCLE_RUNNING
        ):
            # A process may die after the create-once signed checkpoint but
            # before the DB projection.  Only the dedicated preformal recovery
            # branch may consume this RUNNING lifecycle, and that branch must
            # replay a signed pointer or prove the org runtime COMPLETE before
            # creating one.  It never re-enters an Agent/formal route.
            return
        if (
            isinstance(lifecycle, dict)
            and lifecycle.get("status") == PRIVATE_LIFECYCLE_RESUMABLE
        ):
            self._write_private_lifecycle(
                job,
                status=PRIVATE_LIFECYCLE_RUNNING,
                prior_status=PRIVATE_LIFECYCLE_RESUMABLE,
            )
            if not resume:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: resumable private lifecycle cannot be reclassified as fresh"
                )
            return
        if resume:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not resumable"
            )
        if lifecycle is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: existing private lifecycle cannot be reclassified as fresh"
            )
        self._write_private_lifecycle(
            job,
            status=PRIVATE_LIFECYCLE_RUNNING,
            prior_status=None,
        )

    def _finish_private_execution(
        self,
        job: ResearchJob,
        *,
        status: str,
        attestation_id: str,
    ) -> None:
        if status not in {PRIVATE_LIFECYCLE_RESUMABLE, PRIVATE_LIFECYCLE_TERMINAL}:
            raise ValueError("private lifecycle completion status is invalid")
        lifecycle = self._read_private_lifecycle(job)
        if not isinstance(lifecycle, dict) or lifecycle.get("status") != PRIVATE_LIFECYCLE_RUNNING:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not running"
            )
        if not attestation_id:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle lacks host attestation"
            )
        self._write_private_lifecycle(
            job,
            status=status,
            prior_status=PRIVATE_LIFECYCLE_RUNNING,
            attestation_id=attestation_id,
        )

    def _mark_job_non_resumable(self, job: ResearchJob, *, token: str) -> None:
        failures: list[Exception] = []
        try:
            lifecycle = self._read_private_lifecycle(job)
            prior_status = (
                str(lifecycle.get("status")) if isinstance(lifecycle, dict) else None
            )
            self._write_private_lifecycle(
                job,
                status=PRIVATE_LIFECYCLE_NON_RESUMABLE,
                prior_status=prior_status,
                blocker=token,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(exc)
        marker_path = self._non_resumable_marker_path(job.job_id)
        try:
            if marker_path.is_symlink():
                raise RuntimeError("private non-resumable marker uses a symlink")
            if not marker_path.exists():
                security_root = ensure_host_private_job_subdirectory(
                    self.config.state_root,
                    job.job_id,
                    ("security",),
                    create=True,
                )
                marker_path = security_root / "non_resumable.json"
                payload = {
                    "version": "factorforge_console_non_resumable_marker_v1",
                    "job_id": job.job_id,
                    "factor_id": job.factor_id,
                    "research_id": job.research_id,
                    "report_id": job.report_id,
                    "base_commit": job.base_commit,
                    "security_blocker": token,
                    "marked_at_utc": utc_now(),
                }
                _write_json_atomic(marker_path, payload, root=self.config.state_root)
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append(exc)
        if len(failures) == 2:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private non-resumable state could not be persisted"
            ) from failures[0]

    def _require_private_resume_allowed(self, job: ResearchJob) -> None:
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        lifecycle = self._read_private_lifecycle(job)
        if (
            job.request.research_scope
            == RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY
            and isinstance(lifecycle, dict)
            and lifecycle.get("status") == PRIVATE_LIFECYCLE_RUNNING
        ):
            return
        if not isinstance(lifecycle, dict) or lifecycle.get("status") != PRIVATE_LIFECYCLE_RESUMABLE:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not resumable"
            )

    def _validate_evo_v2_memory_resume_context(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        private_execution_started: bool = False,
    ) -> dict[str, Any]:
        """Validate the pre-Ultimate pause without inventing an Ultimate proof."""

        if not _is_evo_v2_memory_gate_pause(job):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 memory pause marker is missing"
            )
        lifecycle = self._read_private_lifecycle(job)
        expected_status = (
            PRIVATE_LIFECYCLE_RUNNING
            if private_execution_started
            else PRIVATE_LIFECYCLE_RESUMABLE
        )
        if (
            not isinstance(lifecycle, dict)
            or lifecycle.get("status") != expected_status
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 private lifecycle is invalid"
            )
        worktree = Path(worktree).expanduser().resolve(strict=True)
        workspace = Path(workspace).expanduser().resolve(strict=True)
        if (
            Path(job.worktree_path).expanduser().resolve(strict=True) != worktree
            or Path(job.workspace_path).expanduser().resolve(strict=True) != workspace
            or not is_validated_evo_v2_memory_runtime_enabled(
                workspace=workspace,
                report_id=job.report_id,
            )
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 allocation or materialization changed"
            )
        chain = load_evo_v2_memory_round_state(
            workspace=workspace,
            state_root=self.config.state_root,
            installation_id=self.config.installation_id,
        )
        memory = job.result["evo_v2_memory"]
        state_ref = memory["state_ref"]
        prior_event_sha256 = str(state_ref.get("event_sha256") or "")
        prior_event = next(
            (
                event
                for event in chain["events"]
                if event.get("event_sha256") == prior_event_sha256
            ),
            None,
        )
        expected_state_path = (
            f"objects/evo_v2/{job.report_id}/memory_runtime/"
            "memory_runtime_state.json"
        )
        if (
            not isinstance(prior_event, dict)
            or state_ref.get("path") != expected_state_path
            or not re.fullmatch(r"[0-9a-f]{64}", str(state_ref.get("sha256") or ""))
            or prior_event.get("formal_execution_allowed") is not False
            or prior_event.get("authority_guard", {}).get("results_or_oos_accessed")
            is not False
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 paused state binding is invalid"
            )
        event_relative = (
            f"objects/evo_v2/{job.report_id}/memory_runtime/events/"
            f"event_{prior_event['generation']:06d}_{prior_event_sha256[:12]}.json"
        )
        event_path = workspace / event_relative
        if (
            event_path.is_symlink()
            or not event_path.is_file()
            or _sha256(event_path) != state_ref.get("sha256")
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 paused event readback failed"
            )

        state_root = self.config.state_root.resolve(strict=True)

        def read_host_json(relative_value: Any, *, label: str) -> tuple[dict[str, Any], Path]:
            relative = Path(str(relative_value or ""))
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 {label} path is unsafe"
                )
            path = state_root / relative
            current = state_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 {label} uses a symlink"
                    )
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(state_root)
                payload = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 {label} is unreadable"
                ) from exc
            if not resolved.is_file() or not isinstance(payload, dict):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 {label} is invalid"
                )
            return payload, resolved

        attestation, _attestation_path = read_host_json(
            lifecycle.get("attestation_id"),
            label="memory gate attestation",
        )
        expected_identity = self._private_lifecycle_identity(job)
        receipt_id = str(attestation.get("formal_execution_receipt_id") or "")
        receipt, receipt_path = read_host_json(
            receipt_id,
            label="memory gate formal receipt",
        )
        commands = receipt.get("commands")
        if (
            attestation.get("version")
            != "factorforge_console_evo_v2_memory_gate_attestation_v1"
            or any(attestation.get(key) != value for key, value in expected_identity.items())
            or attestation.get("stage") != prior_event.get("stage")
            or attestation.get("state_event_sha256") != prior_event_sha256
            or attestation.get("state_file_sha256") != state_ref.get("sha256")
            or attestation.get("formal_execution_allowed") is not False
            or attestation.get("results_or_oos_accessed") is not False
            or attestation.get("formal_execution_receipt_sha256")
            != _sha256(receipt_path)
            or receipt.get("version")
            != "factorforge_console_host_formal_execution_v2"
            or any(
                receipt.get(key) != value
                for key, value in {
                    **expected_identity,
                    "base_commit": job.base_commit,
                }.items()
            )
            or receipt.get("resume") is not False
            or not isinstance(commands, list)
            or len(commands) != 1
            or not isinstance(commands[0], dict)
            or commands[0].get("name") != "materialize_web_research"
            or commands[0].get("returncode") != 0
            or any(command.get("name") == "run_factorforge_ultimate" for command in commands)
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 pause provenance is invalid"
            )
        return chain

    def _validate_trusted_resume_context(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        private_execution_started: bool = False,
    ) -> dict[str, Any]:
        lifecycle = self._read_private_lifecycle(job)
        expected_private_status = (
            PRIVATE_LIFECYCLE_RUNNING
            if private_execution_started
            else PRIVATE_LIFECYCLE_RESUMABLE
        )
        if (
            not isinstance(lifecycle, dict)
            or lifecycle.get("status") != expected_private_status
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle state is invalid for resume validation"
            )
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        state_root = self.config.state_root.resolve(strict=True)
        worktree_root = worktree.resolve(strict=True)
        workspace_root = workspace.resolve(strict=True)

        def invalid(detail: str) -> RuntimeError:
            return RuntimeError(f"{BLOCK_RESUME_TRUST_INVALID}: {detail}")

        def read_host_json(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
            try:
                relative = path.relative_to(state_root)
            except ValueError as exc:
                raise invalid(f"{label} escapes host state") from exc
            current = state_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise invalid(f"{label} uses a symlink")
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(state_root)
            except (FileNotFoundError, ValueError) as exc:
                raise invalid(f"{label} is missing or outside host state") from exc
            if not resolved.is_file() or resolved.is_symlink():
                raise invalid(f"{label} is not a regular host-state file")
            try:
                payload = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise invalid(f"{label} is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise invalid(f"{label} must be a JSON object")
            return payload, _sha256(resolved)

        expected_identity = {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
        }
        if (
            Path(job.worktree_path).expanduser().resolve(strict=True) != worktree_root
            or Path(job.workspace_path).expanduser().resolve(strict=True) != workspace_root
        ):
            raise invalid("persisted allocation does not match the active workspace")

        pointer_path = state_root / "attestations" / f"{job.job_id}.current.json"
        pointer, _pointer_sha256 = read_host_json(
            pointer_path,
            label="host attestation pointer",
        )
        if (
            pointer.get("version") != "factorforge_console_host_attestation_pointer_v1"
            or pointer.get("job_id") != job.job_id
        ):
            raise invalid("host attestation pointer identity is invalid")
        attestation_id = str(pointer.get("attestation_id") or "")
        attestation_relative = Path(attestation_id)
        if (
            not attestation_id
            or attestation_relative.is_absolute()
            or ".." in attestation_relative.parts
        ):
            raise invalid("host attestation identity is unsafe")
        attestation_path = state_root / attestation_relative
        attestation, attestation_sha256 = read_host_json(
            attestation_path,
            label="host attestation",
        )
        if attestation_sha256 != str(pointer.get("attestation_sha256") or ""):
            raise invalid("host attestation hash does not match current pointer")
        if (
            attestation.get("version")
            != "factorforge_console_host_execution_attestation_v2"
            or any(attestation.get(key) != value for key, value in expected_identity.items())
            or attestation.get("host_observed_ultimate_process") is not True
            or attestation.get("host_evidence_reader_invoked") is not True
        ):
            raise invalid("host attestation identity or provenance is invalid")

        manifest_path = workspace_root / "manifest.json"
        if (
            not manifest_path.is_file()
            or manifest_path.is_symlink()
            or attestation.get("workspace_manifest_sha256") != _sha256(manifest_path)
        ):
            raise invalid("workspace manifest is not bound to the host attestation")

        materialization = attestation.get("web_materialization")
        if not isinstance(materialization, dict):
            raise invalid("web materialization provenance is missing")
        expected_plan_hash = str(materialization.get("plan_sha256") or "")
        plan_path = workspace_root / "identity" / "web_research_plan.json"
        if expected_plan_hash and (
            not plan_path.is_file()
            or plan_path.is_symlink()
            or _sha256(plan_path) != expected_plan_hash
        ):
            raise invalid("research plan no longer matches the host attestation")

        evidence_tree_id = str(attestation.get("workspace_evidence_tree_id") or "")
        evidence_tree_relative = Path(evidence_tree_id)
        if (
            not evidence_tree_id
            or evidence_tree_relative.is_absolute()
            or ".." in evidence_tree_relative.parts
        ):
            raise invalid("workspace evidence tree identity is unsafe")
        evidence_tree_path = state_root / evidence_tree_relative
        evidence_tree, evidence_tree_sha256 = read_host_json(
            evidence_tree_path,
            label="workspace evidence tree",
        )
        entries = evidence_tree.get("entries")
        if (
            evidence_tree.get("version")
            != "factorforge_console_workspace_evidence_tree_v1"
            or any(evidence_tree.get(key) != value for key, value in expected_identity.items())
            or not isinstance(entries, dict)
            or not all(
                isinstance(path, str) and isinstance(digest, str)
                for path, digest in entries.items()
            )
            or evidence_tree_sha256
            != str(attestation.get("workspace_evidence_tree_sha256") or "")
            or stable_json_hash(entries)
            != str(attestation.get("workspace_evidence_tree_root_sha256") or "")
            or evidence_tree.get("tree_sha256") != stable_json_hash(entries)
        ):
            raise invalid("workspace evidence tree provenance is invalid")
        try:
            current_entries = _workspace_evidence_tree(workspace_root)
        except RuntimeError as exc:
            raise invalid("current workspace evidence tree is unsafe") from exc
        workspace_evidence_changed = current_entries != entries

        receipt_id = str(attestation.get("formal_execution_receipt_id") or "")
        receipt_relative = Path(receipt_id)
        if (
            not receipt_id
            or receipt_relative.is_absolute()
            or ".." in receipt_relative.parts
        ):
            raise invalid("formal execution receipt identity is unsafe")
        receipt_path = state_root / receipt_relative
        receipt, receipt_sha256 = read_host_json(
            receipt_path,
            label="formal execution receipt",
        )
        if receipt_sha256 != str(
            attestation.get("formal_execution_receipt_sha256") or ""
        ):
            raise invalid("formal execution receipt hash does not match attestation")
        if (
            receipt.get("version") != "factorforge_console_host_formal_execution_v2"
            or any(receipt.get(key) != value for key, value in expected_identity.items())
        ):
            raise invalid("formal execution receipt identity is invalid")

        commands = receipt.get("commands")
        if not isinstance(commands, list) or len(commands) != 2:
            raise invalid("formal execution receipt command chain is incomplete")
        materialize, ultimate = commands
        if not isinstance(materialize, dict) or not isinstance(ultimate, dict):
            raise invalid("formal execution receipt commands are invalid")
        materialize_argv = materialize.get("argv")
        ultimate_argv = ultimate.get("argv")
        if not isinstance(materialize_argv, list) or not isinstance(ultimate_argv, list):
            raise invalid("formal execution receipt argv is invalid")
        engine_paths_valid = bool(
            len(materialize_argv) >= 2
            and len(ultimate_argv) >= 2
            and _formal_receipt_engine_paths_valid(
                receipt=receipt,
                source_repo=self.config.source_repo,
                materialize=materialize,
                materialize_argv=materialize_argv,
                ultimate=ultimate,
                ultimate_argv=ultimate_argv,
            )
        )
        if (
            materialize.get("name") != "materialize_web_research"
            or materialize.get("returncode") != 0
            or materialize.get("host_observed_process") is not True
            or materialize.get("cwd") != str(worktree_root)
            or len(materialize_argv) < 2
            or not engine_paths_valid
            or _argv_value(materialize_argv, "--workspace-root") != str(workspace_root)
            or _argv_value(materialize_argv, "--plan") != str(plan_path)
            or stable_json_hash(materialize_argv)
            != str(materialize.get("argv_sha256") or "")
        ):
            raise invalid("host materializer receipt is invalid")
        if (
            ultimate.get("name") != "run_factorforge_ultimate"
            or ultimate.get("host_observed_process") is not True
            or ultimate.get("cwd") != str(worktree_root)
            or len(ultimate_argv) < 2
            or _argv_value(ultimate_argv, "--report-id") != job.report_id
            or _argv_value(ultimate_argv, "--factor-id") != job.factor_id
            or _argv_value(ultimate_argv, "--research-id") != job.research_id
            or _argv_value(ultimate_argv, "--factorforge-root") != str(worktree_root)
            or _argv_value(ultimate_argv, "--factor-workspace") != str(workspace_root)
            or _argv_value(ultimate_argv, "--start-step") not in {"3", "4", "5", "6"}
            or _argv_value(ultimate_argv, "--end-step") != "all"
            or stable_json_hash(ultimate_argv) != str(ultimate.get("argv_sha256") or "")
            or stable_json_hash(ultimate_argv)
            != str(attestation.get("ultimate_argv_sha256") or "")
            or ultimate.get("returncode") != attestation.get("ultimate_returncode")
        ):
            raise invalid("host Ultimate receipt is invalid")
        receipt_resume = receipt.get("resume")
        receipt_start_step = _argv_value(ultimate_argv, "--start-step")
        receipt_parent = receipt.get("resume_parent")
        if receipt_resume is False:
            if receipt_start_step != "3" or receipt_parent is not None:
                raise invalid("fresh formal receipt has invalid start step or parent")
        elif receipt_resume is True:
            if not isinstance(receipt_parent, dict):
                raise invalid("resumed formal receipt is missing its trusted parent")
            required_parent_fields = {
                "start_step",
                "ultimate_proof_sha256",
                "attestation_id",
                "attestation_sha256",
                "receipt_id",
                "receipt_sha256",
            }
            if (
                set(receipt_parent) != required_parent_fields
                or receipt_parent.get("start_step") != receipt_start_step
            ):
                raise invalid("resumed formal receipt parent contract is invalid")
            parent_attestation_id = str(receipt_parent.get("attestation_id") or "")
            parent_receipt_id = str(receipt_parent.get("receipt_id") or "")
            parent_attestation_relative = Path(parent_attestation_id)
            parent_receipt_relative = Path(parent_receipt_id)
            if (
                not parent_attestation_id
                or parent_attestation_relative.is_absolute()
                or ".." in parent_attestation_relative.parts
                or not parent_receipt_id
                or parent_receipt_relative.is_absolute()
                or ".." in parent_receipt_relative.parts
            ):
                raise invalid("resumed formal receipt parent identity is unsafe")
            parent_attestation, parent_attestation_sha256 = read_host_json(
                state_root / parent_attestation_relative,
                label="parent host attestation",
            )
            parent_receipt, parent_receipt_sha256 = read_host_json(
                state_root / parent_receipt_relative,
                label="parent formal execution receipt",
            )
            parent_wrapper = (
                parent_attestation.get("evidence_hashes", {}).get("wrapper_report", {})
                if isinstance(parent_attestation.get("evidence_hashes"), dict)
                else {}
            )
            if (
                parent_attestation_sha256
                != str(receipt_parent.get("attestation_sha256") or "")
                or parent_receipt_sha256
                != str(receipt_parent.get("receipt_sha256") or "")
                or parent_attestation.get("version")
                != "factorforge_console_host_execution_attestation_v2"
                or parent_receipt.get("version")
                != "factorforge_console_host_formal_execution_v2"
                or any(
                    parent_attestation.get(key) != value
                    or parent_receipt.get(key) != value
                    for key, value in expected_identity.items()
                )
                or parent_attestation.get("formal_execution_receipt_id")
                != parent_receipt_id
                or parent_attestation.get("formal_execution_receipt_sha256")
                != parent_receipt_sha256
                or parent_receipt.get("ultimate_proof_sha256")
                != str(receipt_parent.get("ultimate_proof_sha256") or "")
                or not isinstance(parent_wrapper, dict)
                or parent_wrapper.get("sha256")
                != str(receipt_parent.get("ultimate_proof_sha256") or "")
            ):
                raise invalid("resumed formal receipt parent trust is invalid")
        else:
            raise invalid("formal receipt resume flag is invalid")

        prior_conversation_binding = receipt.get("conversation_ledger_binding")
        attested_conversation_binding = attestation.get(
            "conversation_ledger_binding"
        )
        if (
            prior_conversation_binding is not None
            or attested_conversation_binding is not None
        ):
            if (
                not isinstance(prior_conversation_binding, dict)
                or not isinstance(attested_conversation_binding, dict)
                or stable_json_hash(prior_conversation_binding)
                != stable_json_hash(attested_conversation_binding)
            ):
                raise invalid("host conversation ledger binding is inconsistent")
            prior_binding_resume_trust = None
            if receipt_resume is True:
                prior_binding_resume_trust = {
                    "attestation_id": prior_conversation_binding.get(
                        "parent_attestation_id"
                    ),
                    "attestation_sha256": prior_conversation_binding.get(
                        "parent_attestation_sha256"
                    ),
                    "receipt_id": prior_conversation_binding.get(
                        "parent_receipt_id"
                    ),
                    "receipt_sha256": prior_conversation_binding.get(
                        "parent_receipt_sha256"
                    ),
                    "conversation_request_sha256": prior_conversation_binding.get(
                        "parent_request_sha256"
                    ),
                    "conversation_ledger_checkpoint": prior_conversation_binding.get(
                        "parent_checkpoint"
                    ),
                }
            try:
                verified_prior_binding = _validate_host_conversation_ledger_binding(
                    workspace=workspace_root,
                    state_root=state_root,
                    job=job,
                    resume=receipt_resume is True,
                    resume_trust=prior_binding_resume_trust,
                )
            except RuntimeError as exc:
                raise invalid("host conversation ledger binding cannot be verified") from exc
            if stable_json_hash(verified_prior_binding) != stable_json_hash(
                prior_conversation_binding
            ):
                raise invalid("host conversation ledger binding changed")

        proof_path = (
            workspace_root
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        if not proof_path.is_file() or proof_path.is_symlink():
            raise invalid("current Ultimate proof is missing or unsafe")
        proof_sha256 = _sha256(proof_path)
        wrapper_evidence = (
            attestation.get("evidence_hashes", {}).get("wrapper_report", {})
            if isinstance(attestation.get("evidence_hashes"), dict)
            else {}
        )
        if (
            receipt.get("ultimate_proof_sha256") != proof_sha256
            or not isinstance(wrapper_evidence, dict)
            or wrapper_evidence.get("artifact_id")
            != (
                "objects/runtime_context/"
                f"ultimate_run_report__{job.report_id}.json"
            )
            or wrapper_evidence.get("sha256") != proof_sha256
        ):
            raise invalid("current Ultimate proof is not bound to trusted host evidence")
        proof = _read_regular_workspace_json(
            workspace_root,
            (
                "objects/runtime_context/"
                f"ultimate_run_report__{job.report_id}.json"
            ),
        )
        evo_v2_external_progress: dict[str, Any] | None = None
        if is_evo_v2_external_pause(proof):
            try:
                evo_v2_external_progress = assess_evo_v2_external_resume(
                    workspace_root=workspace_root,
                    report_id=job.report_id,
                    proof=proof,
                    attested_entries=entries,
                    trust_root=self.config.state_root / "research-org-trust",
                    installation_id=self.config.installation_id,
                    admissions_root=(
                        self.config.state_root / "researcher-memory-evo-v2"
                    ),
                ).to_dict()
            except (EvoV2ExternalResumeError, OSError, ValueError) as exc:
                raise invalid(
                    "EVO V2 external progress does not replay against the "
                    f"attested lifecycle generation: {exc}"
                ) from exc
        elif workspace_evidence_changed:
            raise invalid("workspace formal evidence tree changed after host attestation")
        try:
            start_step = required_web_resume_start_step(workspace_root, job.report_id)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            raise invalid("trusted Ultimate proof is not safely resumable") from exc
        if start_step not in {"3", "4", "5", "6"}:
            raise invalid("trusted Ultimate proof has no legal resume point")
        trusted_request = _read_regular_workspace_json(
            workspace_root,
            "identity/web_research_request.json",
        )
        trusted_conversation_reference = trusted_request.get(
            CONVERSATION_LEDGER_REFERENCE_FIELD
        )
        return {
            "start_step": start_step,
            "ultimate_proof_sha256": proof_sha256,
            "attestation_id": attestation_id,
            "attestation_sha256": attestation_sha256,
            "receipt_id": receipt_id,
            "receipt_sha256": receipt_sha256,
            "workspace_evidence_tree_root_sha256": stable_json_hash(entries),
            "evo_v2_external_progress": evo_v2_external_progress,
            "conversation_request_sha256": stable_json_hash(trusted_request),
            "conversation_ledger_checkpoint": (
                deepcopy(trusted_conversation_reference)
                if isinstance(trusted_conversation_reference, dict)
                else None
            ),
        }

    def _write_host_formal_checkpoint_result(
        self,
        job: ResearchJob,
        *,
        start_step: str,
    ) -> AgentRunResult:
        if start_step not in {"3", "4", "5", "6"}:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: host checkpoint start step is invalid"
            )
        recorded_at = utc_now()
        result_root = (
            self.config.state_root / "jobs" / job.job_id / "host-checkpoint-runs"
        )
        result_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        result_root.chmod(0o700)
        result_path = result_root / (
            f"host_checkpoint_{_stamp(recorded_at)}_{uuid.uuid4().hex[:12]}.json"
        )
        session_key = f"host-formal:{job.job_id}:{uuid.uuid4().hex}"
        payload = {
            "version": "factorforge_console_host_checkpoint_run_v1",
            "actor_kind": "host_formal_checkpoint",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "start_step": start_step,
            "session_key_sha256": hashlib.sha256(
                session_key.encode("utf-8")
            ).hexdigest(),
            "returncode": 0,
            "recorded_at_utc": recorded_at,
        }
        _write_json_atomic(result_path, payload, root=self.config.state_root)
        return AgentRunResult(
            returncode=0,
            agent_id="factorforge-console-host",
            session_key=session_key,
            started_at_utc=recorded_at,
            finished_at_utc=recorded_at,
            stdout_tail="host formal checkpoint accepted",
            stderr_tail="",
            result_path=str(result_path),
        )

    def _write_evo_v2_terminal_checkpoint(
        self,
        job: ResearchJob,
        *,
        workspace: Path,
        resume_trust: Mapping[str, Any],
    ) -> dict[str, Any]:
        progress = resume_trust.get("evo_v2_external_progress")
        if not isinstance(progress, Mapping):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 terminal progress is missing"
            )
        closure_relative = str(progress.get("terminal_closure_path") or "")
        closure_sha256 = str(progress.get("terminal_closure_sha256") or "")
        closure_path = _read_regular_workspace_file(
            workspace.resolve(strict=True),
            closure_relative,
        )
        proof_relative = (
            "objects/runtime_context/"
            f"ultimate_run_report__{job.report_id}.json"
        )
        proof_path = _read_regular_workspace_file(
            workspace.resolve(strict=True),
            proof_relative,
        )
        formal_verdict = str(progress.get("terminal_factor_verdict") or "")
        terminal_decision = str(progress.get("terminal_decision") or "")
        expected_decision = {
            "ACCEPT": "promote_official",
            "REJECT": "reject",
        }.get(formal_verdict)
        expected_closure_relative = (
            f"objects/evo_v2/{job.report_id}/post_oos_terminal_closure.json"
        )
        expected_snapshot_relative = (
            f"objects/evo_v2/{job.report_id}/lifecycle_history/"
            "lifecycle__0002.json"
        )
        if (
            progress.get("report_id") != job.report_id
            or progress.get("status") != PROGRESS_TERMINAL_CHECKPOINT_READY
            or progress.get("start_step") is not None
            or progress.get("pause_outcome")
            != "awaiting_evo_v2_non_revision_terminal_closure"
            or progress.get("current_lifecycle_state")
            != "NO_QUALIFIED_CONTRADICTION"
            or progress.get("paused_lifecycle_state")
            != "NO_QUALIFIED_CONTRADICTION"
            or expected_decision is None
            or terminal_decision != expected_decision
            or closure_relative != expected_closure_relative
            or not re.fullmatch(r"[0-9a-f]{64}", closure_sha256)
            or _sha256(closure_path) != closure_sha256
            or _sha256(proof_path)
            != str(resume_trust.get("ultimate_proof_sha256") or "")
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(resume_trust.get("attestation_sha256") or ""),
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(resume_trust.get("receipt_sha256") or ""),
            )
            or isinstance(progress.get("paused_lifecycle_generation"), bool)
            or progress.get("paused_lifecycle_generation") != 2
            or progress.get("paused_lifecycle_snapshot_path")
            != expected_snapshot_relative
            or isinstance(progress.get("current_lifecycle_generation"), bool)
            or progress.get("current_lifecycle_generation") != 2
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(progress.get("paused_lifecycle_snapshot_sha256") or ""),
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(progress.get("current_lifecycle_sha256") or ""),
            )
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 terminal checkpoint binding is invalid"
            )
        checkpoint_root = (
            self.config.state_root
            / "jobs"
            / job.job_id
            / "host-checkpoint-runs"
        )
        checkpoint_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        checkpoint_root.chmod(0o700)
        recorded_at = utc_now()
        checkpoint_path = checkpoint_root / (
            f"evo_terminal_checkpoint_{_stamp(recorded_at)}_"
            f"{uuid.uuid4().hex[:12]}.json"
        )
        progress_copy = deepcopy(dict(progress))
        unsigned = {
            "version": "factorforge_console_evo_v2_terminal_checkpoint_v1",
            "actor_kind": "host_terminal_checkpoint",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "trusted_pause": {
                "path": proof_relative,
                "sha256": _sha256(proof_path),
                "attestation_id": str(
                    resume_trust.get("attestation_id") or ""
                ),
                "attestation_sha256": str(
                    resume_trust.get("attestation_sha256") or ""
                ),
                "receipt_id": str(resume_trust.get("receipt_id") or ""),
                "receipt_sha256": str(
                    resume_trust.get("receipt_sha256") or ""
                ),
            },
            "terminal_closure": {
                "path": closure_relative,
                "sha256": closure_sha256,
                "formal_factor_verdict": formal_verdict,
                "terminal_decision": terminal_decision,
            },
            "lifecycle_generation_binding": {
                "paused_state": progress.get("paused_lifecycle_state"),
                "paused_generation": progress.get(
                    "paused_lifecycle_generation"
                ),
                "paused_snapshot_path": progress.get(
                    "paused_lifecycle_snapshot_path"
                ),
                "paused_snapshot_sha256": progress.get(
                    "paused_lifecycle_snapshot_sha256"
                ),
                "current_state": progress.get("current_lifecycle_state"),
                "current_generation": progress.get(
                    "current_lifecycle_generation"
                ),
                "current_lifecycle_sha256": progress.get(
                    "current_lifecycle_sha256"
                ),
            },
            "external_resume_assessment_sha256": stable_json_hash(
                progress_copy
            ),
            "authority": {
                "agent_invoked": False,
                "parent_wrapper_invoked": False,
                "revision_authority": False,
                "human_approval_authority": False,
                "canonical_memory_write_allowed": False,
            },
            "recorded_at_utc": recorded_at,
        }
        payload = {**unsigned, "content_sha256": stable_json_hash(unsigned)}
        _write_json_atomic(
            checkpoint_path,
            payload,
            root=self.config.state_root,
        )
        relative = checkpoint_path.relative_to(self.config.state_root).as_posix()
        return {
            "path": relative,
            "sha256": _sha256(checkpoint_path),
            "content_sha256": payload["content_sha256"],
            "formal_factor_verdict": formal_verdict,
            "terminal_decision": terminal_decision,
            "terminal_closure_path": closure_relative,
            "terminal_closure_sha256": closure_sha256,
        }

    def _prepare_evo_v2_child_execution_ready(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume_trust: Mapping[str, Any],
        child_report_id: str,
        parent_report_id: str | None = None,
        trusted_parent_checkpoint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the Host-owned child admission chain through execution readiness.

        The resulting checkpoint authorizes exactly one child report and the
        code-owned start-step=3b command.  It deliberately does not execute the
        command in this parent resume transaction; a crash or operator restart
        can replay the signed checkpoint without re-authoring child semantics.
        """

        parent_id = parent_report_id or job.report_id
        progress = resume_trust.get("evo_v2_external_progress")
        if (
            not isinstance(progress, Mapping)
            or progress.get("status")
            not in {
                PROGRESS_CHILD_HANDOFF_AUTHORIZED,
                PROGRESS_CHILD_HANDOFF_READY,
            }
            or progress.get("report_id") != parent_id
            or progress.get("child_report_id") != child_report_id
            or progress.get("start_step") is not None
            or not child_report_id
            or child_report_id == parent_id
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: EVO V2 child handoff identity is invalid"
            )
        trust_root = self.config.state_root / "research-org-trust"
        store = load_runtime_trust_store(
            trust_root,
            installation_id=self.config.installation_id,
        )
        expected_pin = str(store.public_manifest.get("manifest_sha256") or "")
        if (
            not job.base_commit
            or re.fullmatch(r"[0-9a-f]{40,64}", job.base_commit.lower()) is None
            or Path(job.worktree_path).expanduser().resolve(strict=True) != worktree
            or Path(job.workspace_path).expanduser().resolve(strict=True) != workspace
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: persisted child worktree allocation changed"
            )
        engine_commit = _validate_formal_engine_checkout(
            worktree,
            job.base_commit,
        )
        engine_root = worktree
        materializer = _formal_engine_script(
            engine_root, EVO_CHILD_MATERIALIZER_RELATIVE
        )
        ultimate = _formal_engine_script(
            engine_root, FORMAL_ENGINE_SCRIPTS["run_factorforge_ultimate"]
        )
        for script, relative in (
            (materializer, EVO_CHILD_MATERIALIZER_RELATIVE),
            (ultimate, FORMAL_ENGINE_SCRIPTS["run_factorforge_ultimate"]),
        ):
            if _sha256(script) != _git_blob_sha256(
                engine_root, engine_commit, relative
            ):
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: EVO child engine "
                    "script does not match the pinned commit"
                )
        if not self.config.data_catalogs:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: approved data catalog is missing"
            )
        _catalog_snapshot_path, catalog_projection_path = (
            evo_child_catalog_projection_paths(
                engine_root,
                job_id=job.job_id,
                child_report_id=child_report_id,
            )
        )
        if catalog_projection_path.is_file() and not catalog_projection_path.is_symlink():
            catalog_projection = validate_materialized_evo_child_catalog_projection(
                engine_root=engine_root,
                workspace_root=workspace,
                projection_path=catalog_projection_path,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
            )
        else:
            frozen_catalog = materialize_host_job_frozen_catalog_snapshot(
                state_root=self.config.state_root,
                workspace_root=workspace,
                approved_catalog_path=self.config.data_catalogs[0],
                job_id=job.job_id,
            )
            catalog_projection = materialize_evo_child_catalog_projection(
                engine_root=engine_root,
                workspace_root=workspace,
                approved_catalog_path=frozen_catalog["snapshot_path"],
                approved_catalog_admission=frozen_catalog["catalog_admission"],
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
            )
        external_calendar = str(
            os.environ.get("FACTORFORGE_TRUSTED_TRADE_CAL_CSV") or ""
        ).strip()
        if not external_calendar:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: trusted trade calendar is missing"
            )
        _calendar_snapshot_path, calendar_projection_path = (
            evo_child_calendar_projection_paths(
                engine_root,
                job_id=job.job_id,
                child_report_id=child_report_id,
            )
        )
        if calendar_projection_path.is_file() and not calendar_projection_path.is_symlink():
            calendar_projection = validate_materialized_evo_child_calendar_projection(
                engine_root=engine_root,
                workspace_root=workspace,
                projection_path=calendar_projection_path,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
            )
        else:
            calendar_projection = materialize_evo_child_calendar_projection(
                engine_root=engine_root,
                workspace_root=workspace,
                trusted_calendar_path=external_calendar,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
            )
        parent_checkpoint = (
            dict(trusted_parent_checkpoint)
            if trusted_parent_checkpoint is not None
            else {
                "ultimate_proof_sha256": str(
                    resume_trust.get("ultimate_proof_sha256") or ""
                ),
                "attestation_id": str(
                    resume_trust.get("attestation_id") or ""
                ),
                "attestation_sha256": str(
                    resume_trust.get("attestation_sha256") or ""
                ),
                "receipt_id": str(resume_trust.get("receipt_id") or ""),
                "receipt_sha256": str(
                    resume_trust.get("receipt_sha256") or ""
                ),
                "external_progress_sha256": stable_json_hash(dict(progress)),
            }
        )
        return prepare_evo_child_execution(
            runner=self.agent_adapter,
            state_root=self.config.state_root,
            trust_root=trust_root,
            admissions_root=(
                self.config.state_root / "researcher-memory-evo-v2"
            ),
            installation_id=self.config.installation_id,
            job_id=job.job_id,
            workspace_root=workspace,
            worktree=worktree,
            parent_report_id=parent_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_pin,
            trusted_parent_checkpoint=parent_checkpoint,
            child_materializer_script=materializer,
            ultimate_script=ultimate,
            engine_root=engine_root,
            container_runtime=Path(
                shutil.which(self.config.container_runtime)
                or self.config.container_runtime
            ),
            container_image_digest=resolve_evo_child_container_image_digest(
                Path(
                    shutil.which(self.config.container_runtime)
                    or self.config.container_runtime
                ),
                self.config.agent_container_image,
            ),
            container_memory=self.config.container_memory,
            container_cpus=str(self.config.container_cpus),
            container_pids=self.config.container_pids_limit,
            container_tmpfs=(
                f"size={self.config.container_tmpfs_size},"
                "mode=1777,noexec,nosuid,nodev"
            ),
            research_base_commit=job.base_commit.lower(),
            execution_engine_commit=engine_commit.lower(),
            catalog_snapshot_path=catalog_projection["snapshot_path"],
            catalog_projection_path=catalog_projection["projection_path"],
            calendar_snapshot_path=calendar_projection["snapshot_path"],
            calendar_projection_path=calendar_projection["projection_path"],
            timeout_seconds=max(
                60, min(3_300, int(self.config.agent_timeout_seconds))
            ),
        )

    def _evo_child_phase_checkpoint(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        child_report_id: str,
        prior_execution: Mapping[str, Any],
        trust_root: Path,
        expected_host_pin: str,
        parent_report_id: str | None = None,
    ) -> dict[str, Any]:
        parent_id = parent_report_id or job.report_id
        prior_receipt_path = str(
            prior_execution.get("execution_receipt_path") or ""
        )
        prior_proof_path = str(prior_execution.get("proof_path") or "")
        if not prior_receipt_path or not prior_proof_path:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child phase prior evidence is missing"
            )
        baseline = load_evo_child_execution_baseline(
            state_root=self.config.state_root,
            trust_root=trust_root,
            installation_id=self.config.installation_id,
            job_id=job.job_id,
            parent_report_id=parent_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_pin,
            execution_receipt_path=prior_receipt_path,
            workspace_root=workspace,
        )
        if (
            baseline.get("status") != CHILD_RESUME_READY
            or baseline.get("resume_start_step") != "6"
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child phase is not Step6-resumable"
            )
        proof_path = Path(prior_proof_path).expanduser().resolve(strict=True)
        if (
            proof_path.parent
            != (workspace / "objects/runtime_context").resolve(strict=True)
            or _sha256(proof_path) != prior_execution.get("proof_sha256")
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child phase proof binding changed"
            )
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        pause = str(proof.get("final_outcome") or "")
        external_assessment = None
        if pause in EVO_V2_EXTERNAL_PAUSES:
            external_assessment = assess_evo_v2_external_resume(
                workspace_root=workspace,
                report_id=child_report_id,
                proof=proof,
                attested_entries=baseline["entries"],
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                trusted_lifecycle_manifest=load_runtime_trust_store(
                    trust_root,
                    installation_id=self.config.installation_id,
                ).public_manifest,
                require_signed_lifecycle_genesis=False,
            )
        route = _classify_resume_route(
            workspace,
            child_report_id,
            start_step="6",
            trusted_proof_sha256=_sha256(proof_path),
            evo_v2_external_progress=(
                external_assessment.to_dict()
                if external_assessment is not None
                else None
            ),
        )

        child_job = deepcopy(job)
        child_job.report_id = child_report_id
        plan = validate_and_resolve_evo_child_web_research_plan(
            workspace_root=workspace,
            parent_report_id=parent_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_pin,
            incident_trust_root=trust_root,
            incident_installation_id=self.config.installation_id,
        )["raw_plan"]
        identity = plan.get("identity") if isinstance(plan, Mapping) else {}
        child_job.factor_id = str(identity.get("factor_id") or "")
        child_job.research_id = str(identity.get("research_id") or "")
        if not child_job.factor_id or not child_job.research_id:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child plan identity is incomplete"
            )

        def file_ref(path: Path) -> dict[str, Any]:
            resolved = path.expanduser().resolve(strict=True)
            if resolved.is_symlink() or not resolved.is_file():
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child phase evidence is unsafe"
                )
            return {
                "path": str(resolved),
                "sha256": _sha256(resolved),
                "size_bytes": resolved.stat().st_size,
            }

        def replay_phase_receipt_if_present(
            inflight: Mapping[str, Any],
        ) -> dict[str, Any] | None:
            candidate = Path(
                str(inflight.get("phase_receipt_candidate_path") or "")
            )
            if not candidate.is_file() or candidate.is_symlink():
                return None
            return validate_evo_child_phase_checkpoint(
                state_root=self.config.state_root,
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=expected_host_pin,
                phase_receipt_path=candidate,
                workspace_root=workspace,
            )

        def matching_private_receipts(
            pattern: str,
            predicate: Any,
        ) -> list[tuple[Path, dict[str, Any]]]:
            private_root = (
                self.config.state_root.resolve(strict=True)
                / "jobs"
                / job.job_id
            )
            matches: list[tuple[Path, dict[str, Any]]] = []
            for candidate in sorted(private_root.glob(pattern)):
                if candidate.is_symlink() or not candidate.is_file():
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: child phase private receipt is unsafe"
                    )
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: child phase private receipt is invalid"
                    ) from exc
                if isinstance(payload, dict) and predicate(payload):
                    matches.append((candidate, payload))
            if len(matches) != 1:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child phase private receipt is missing or ambiguous"
                )
            return matches

        def recover_council_result(
            tasks: tuple[CouncilIngressTask, ...],
        ) -> AgentRunResult:
            expected_hashes = {
                task.task_id: _sha256(
                    _read_regular_workspace_file(
                        workspace, task.expected_result_path
                    )
                )
                for task in tasks
            }
            primary_agent_id = child_job.agent_id or (
                f"factorforge-web-{job.job_id.removeprefix('job_')}"
            )
            primary_session_key = child_job.agent_session_key or (
                f"agent:{primary_agent_id}:{job.job_id}"
            )

            def matches(payload: Mapping[str, Any]) -> bool:
                runs = payload.get("runs")
                if not isinstance(runs, list) or len(runs) != len(tasks):
                    return False
                by_task = {
                    str(run.get("task_id") or ""): run
                    for run in runs
                    if isinstance(run, Mapping)
                }
                return bool(
                    payload.get("version")
                    == "factorforge_console_council_ingress_v1"
                    and payload.get("job_id") == job.job_id
                    and payload.get("factor_id") == child_job.factor_id
                    and payload.get("research_id") == child_job.research_id
                    and payload.get("report_id") == child_report_id
                    and payload.get("agent_id") == primary_agent_id
                    and payload.get("session_key_sha256")
                    == hashlib.sha256(primary_session_key.encode("utf-8")).hexdigest()
                    and payload.get("resume") is True
                    and payload.get("research_base_commit") == child_job.base_commit
                    and payload.get("engine_commit") == self._expected_base_commit
                    and payload.get("returncode") == 0
                    and payload.get("error_code") == ""
                    and all(
                        isinstance(by_task.get(task.task_id), Mapping)
                        and by_task[task.task_id].get("agent_role")
                        == task.agent_role
                        and by_task[task.task_id].get(
                            "expected_agent_identifier"
                        )
                        == task.expected_agent_identifier
                        and by_task[task.task_id].get("expected_result_path")
                        == task.expected_result_path
                        and by_task[task.task_id].get("returncode") == 0
                        and by_task[task.task_id].get("error_code") == ""
                        and by_task[task.task_id].get(
                            "imported_result_sha256"
                        )
                        == expected_hashes[task.task_id]
                        for task in tasks
                    )
                )

            receipt_path, payload = matching_private_receipts(
                "council_ingress*.json", matches
            )[0]
            return AgentRunResult(
                returncode=0,
                agent_id=primary_agent_id,
                session_key=primary_session_key,
                started_at_utc=str(payload.get("started_at_utc") or ""),
                finished_at_utc=str(payload.get("finished_at_utc") or ""),
                stdout_tail="recovered_exact_council_outputs",
                stderr_tail="",
                result_path=str(receipt_path),
                provider=str(payload.get("provider") or ""),
                model=str(payload.get("model") or ""),
            )

        def load_existing_root_task(
            *, phase_attempt_id: str, task_relative: str, output_relative: str
        ) -> PreOosRootSynthesisTask:
            packet_path = _read_regular_workspace_file(workspace, task_relative)
            try:
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child root synthesis task is invalid"
                ) from exc
            unsigned = dict(packet) if isinstance(packet, dict) else {}
            content_sha = unsigned.pop("content_sha256", None)
            inputs = packet.get("read_only_inputs") if isinstance(packet, Mapping) else None
            if (
                not isinstance(packet, Mapping)
                or packet.get("version") != PRE_OOS_ROOT_SYNTHESIS_TASK_VERSION
                or packet.get("attempt_id") != phase_attempt_id
                or packet.get("identity")
                != {
                    "job_id": job.job_id,
                    "factor_id": child_job.factor_id,
                    "research_id": child_job.research_id,
                    "report_id": child_report_id,
                }
                or content_sha != stable_json_hash(unsigned)
                or not isinstance(inputs, list)
                or not inputs
                or (packet.get("required_output") or {}).get("path")
                != output_relative
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child root synthesis task binding is invalid"
                )
            read_only: list[tuple[str, str]] = []
            for reference in inputs:
                if (
                    not isinstance(reference, Mapping)
                    or set(reference) != {"path", "sha256"}
                    or not isinstance(reference.get("path"), str)
                    or not re.fullmatch(
                        r"[0-9a-f]{64}", str(reference.get("sha256") or "")
                    )
                    or _sha256(
                        _read_regular_workspace_file(
                            workspace, str(reference["path"])
                        )
                    )
                    != reference["sha256"]
                ):
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: child root synthesis task evidence changed"
                    )
                read_only.append(
                    (str(reference["path"]), str(reference["sha256"]))
                )
            return PreOosRootSynthesisTask(
                version=PRE_OOS_ROOT_SYNTHESIS_TASK_VERSION,
                attempt_id=phase_attempt_id,
                job_id=job.job_id,
                factor_id=child_job.factor_id,
                research_id=child_job.research_id,
                report_id=child_report_id,
                trusted_proof_sha256=_sha256(proof_path),
                task_packet_relative=task_relative,
                task_packet_sha256=_sha256(packet_path),
                expected_output_relative=output_relative,
                read_only_input_sha256=tuple(
                    sorted(
                        pair
                        for pair in read_only
                        if pair[0] != task_relative
                    )
                ),
            )

        def recover_root_synthesis_result(
            task: PreOosRootSynthesisTask,
        ) -> AgentRunResult:
            output_sha = _sha256(
                _read_regular_workspace_file(
                    workspace, task.expected_output_relative
                )
            )
            agent_id = (
                f"ff-root-{job.job_id.removeprefix('job_')[:10]}-"
                f"{task.attempt_id[-8:]}"
            )
            session_key = f"agent:{agent_id}:{job.job_id}:{task.attempt_id}"

            def matches(payload: Mapping[str, Any]) -> bool:
                return bool(
                    payload.get("version")
                    == "factorforge_console_pre_oos_root_synthesis_run_v1"
                    and payload.get("job_id") == job.job_id
                    and payload.get("factor_id") == child_job.factor_id
                    and payload.get("research_id") == child_job.research_id
                    and payload.get("report_id") == child_report_id
                    and payload.get("agent_id") == agent_id
                    and payload.get("session_key_sha256")
                    == hashlib.sha256(session_key.encode("utf-8")).hexdigest()
                    and payload.get("attempt_id") == task.attempt_id
                    and payload.get("trusted_proof_sha256")
                    == task.trusted_proof_sha256
                    and payload.get("task_packet_sha256")
                    == task.task_packet_sha256
                    and payload.get("expected_output_path")
                    == task.expected_output_relative
                    and payload.get("imported_output_sha256") == output_sha
                    and payload.get("returncode") == 0
                    and payload.get("error_code") == ""
                )

            receipt_path, payload = matching_private_receipts(
                "pre_oos_root_synthesis*.json", matches
            )[0]
            return AgentRunResult(
                returncode=0,
                agent_id=agent_id,
                session_key=session_key,
                started_at_utc=str(payload.get("started_at_utc") or ""),
                finished_at_utc=str(payload.get("finished_at_utc") or ""),
                stdout_tail=str(payload.get("stdout_tail") or ""),
                stderr_tail=str(payload.get("stderr_tail") or ""),
                result_path=str(receipt_path),
                provider=str(payload.get("provider") or ""),
                model=str(payload.get("model") or ""),
            )

        before = _workspace_evidence_tree(workspace)
        baseline_entries = baseline["entries"]
        phase: str
        evidence: dict[str, dict[str, Any]] = {}
        phase_context: dict[str, Any] | None = None
        phase_inflight_path: str | None = None
        recursive_child_report_id: str | None = None
        if route.kind == RESUME_KIND_COUNCIL_INGRESS:
            tasks = _trusted_council_ingress_tasks(
                workspace,
                report_id=child_report_id,
                trusted_resume_proof_sha256=_sha256(proof_path),
                require_results_absent=False,
            )
            if not tasks:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child Council task set is missing"
                )
            expected_paths = (
                "identity/web_agent_resume.md",
                *(task.expected_result_path for task in tasks),
            )
            inflight = materialize_evo_child_phase_inflight(
                state_root=self.config.state_root,
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=expected_host_pin,
                execution_receipt_path=prior_receipt_path,
                workspace_root=workspace,
                phase="COUNCIL_RESULTS",
                expected_workspace_paths=expected_paths,
                operation_binding={
                    "operation_kind": "isolated_council_ingress",
                    "trusted_proof_sha256": _sha256(proof_path),
                    "tasks": [
                        {
                            "task_id": task.task_id,
                            "agent_role": task.agent_role,
                            "expected_agent_identifier": (
                                task.expected_agent_identifier
                            ),
                            "task_packet_path": task.task_packet_path,
                            "task_packet_sha256": task.task_packet_sha256,
                            "expected_result_path": task.expected_result_path,
                        }
                        for task in tasks
                    ],
                },
                require_pristine_baseline=True,
            )
            replayed = replay_phase_receipt_if_present(inflight)
            if replayed is not None:
                return replayed
            phase_inflight_path = str(inflight["phase_inflight_path"])
            if inflight.get("preexisting") is True:
                for task in tasks:
                    _read_regular_workspace_file(
                        workspace, task.expected_result_path
                    )
                _read_regular_workspace_file(
                    workspace, "identity/web_agent_resume.md"
                )
                result = recover_council_result(tasks)
            else:
                runner = getattr(self.agent_adapter, "run_council_ingress", None)
                if not callable(runner):
                    raise RuntimeError(
                        "BLOCK_FACTORFORGE_CONSOLE_COUNCIL_INGRESS_UNAVAILABLE: "
                        "child Council ingress adapter is missing"
                    )
                result = runner(
                    child_job,
                    worktree=worktree,
                    workspace=workspace,
                    tasks=tasks,
                )
                _validate_agent_write_boundary(
                    workspace,
                    before=before,
                    allowed=set(expected_paths),
                    required={task.expected_result_path for task in tasks},
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: "
                        f"child Council returncode={result.returncode}"
                    )
            receipt = self._validate_council_ingress_receipt(
                child_job,
                workspace,
                tasks=tasks,
                agent_result=result,
            )
            evidence["council_ingress_receipt"] = file_ref(
                self.config.state_root / receipt.receipt_id
            )
            for task in tasks:
                evidence[f"council_result__{task.task_id}"] = file_ref(
                    workspace / task.expected_result_path
                )
            phase = "COUNCIL_RESULTS"
        elif route.kind == RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS:
            task_relative = (
                "identity/"
                f"web_pre_oos_root_synthesis_task__{child_report_id}.json"
            )
            output_relative = _pre_oos_root_synthesis_relative(child_report_id)
            expected_paths = (task_relative, output_relative)
            inflight = materialize_evo_child_phase_inflight(
                state_root=self.config.state_root,
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=expected_host_pin,
                execution_receipt_path=prior_receipt_path,
                workspace_root=workspace,
                phase="ROOT_SYNTHESIS",
                expected_workspace_paths=expected_paths,
                operation_binding={
                    "operation_kind": "isolated_pre_oos_root_synthesis",
                    "trusted_proof_sha256": _sha256(proof_path),
                    "task_packet_path": task_relative,
                    "expected_output_path": output_relative,
                },
                require_pristine_baseline=True,
            )
            replayed = replay_phase_receipt_if_present(inflight)
            if replayed is not None:
                return replayed
            phase_inflight_path = str(inflight["phase_inflight_path"])
            phase_attempt_id = str(inflight["phase_attempt_id"])
            if inflight.get("preexisting") is True:
                task = load_existing_root_task(
                    phase_attempt_id=phase_attempt_id,
                    task_relative=task_relative,
                    output_relative=output_relative,
                )
                output_path = workspace / output_relative
                if output_path.is_file() and not output_path.is_symlink():
                    result = recover_root_synthesis_result(task)
                elif output_path.exists() or output_path.is_symlink():
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: child root synthesis output is unsafe"
                    )
                else:
                    runner = _pre_oos_root_synthesis_runner(
                        self.agent_adapter
                    )
                    result = runner(
                        child_job,
                        worktree=worktree,
                        workspace=workspace,
                        task=task,
                    )
                    if result.returncode != 0:
                        raise RuntimeError(
                            "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: "
                            f"child root synthesis returncode={result.returncode}"
                        )
            else:
                task = _write_pre_oos_root_synthesis_task(
                    child_job,
                    workspace,
                    trusted_resume_proof_sha256=_sha256(proof_path),
                    attempt_id=phase_attempt_id,
                )
                runner = _pre_oos_root_synthesis_runner(self.agent_adapter)
                result = runner(
                    child_job,
                    worktree=worktree,
                    workspace=workspace,
                    task=task,
                )
                _validate_agent_write_boundary(
                    workspace,
                    before=before,
                    allowed=set(expected_paths),
                    required={task.expected_output_relative},
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: "
                        f"child root synthesis returncode={result.returncode}"
                    )
            receipt = self._validate_pre_oos_root_synthesis_receipt(
                child_job,
                workspace,
                task=task,
                agent_result=result,
            )
            evidence["root_synthesis_receipt"] = file_ref(
                self.config.state_root / receipt.receipt_id
            )
            evidence["root_synthesis_task"] = file_ref(
                workspace / task.task_packet_relative
            )
            evidence["root_synthesis"] = file_ref(
                workspace / task.expected_output_relative
            )
            phase = "ROOT_SYNTHESIS"
        elif route.kind == RESUME_KIND_EVO_V2_TERMINAL_CHECKPOINT:
            return materialize_evo_child_terminal_checkpoint(
                state_root=self.config.state_root,
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=expected_host_pin,
                execution_receipt_path=prior_receipt_path,
                workspace_root=workspace,
            )
        elif (
            route.kind == RESUME_KIND_HOST_FORMAL_CHECKPOINT
            and pause == "awaiting_evo_v2_transfer_and_actual_use"
        ):
            assessment = external_assessment
            if (
                assessment is None
                or assessment.status != PROGRESS_HOST_CHECKPOINT_READY
                or assessment.start_step != "6"
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child transfer/use is not ready"
                )
            assessment_payload = assessment.to_dict()
            lifecycle_path = research_protocol_paths(
                workspace, child_report_id
            )["evo_lifecycle"]
            evidence["host_transfer_lifecycle"] = file_ref(lifecycle_path)
            for label, raw_path in (
                (
                    "transfer_use_orchestration",
                    assessment.transfer_use_orchestration_path,
                ),
                ("execution_addendum", assessment.execution_addendum_path),
            ):
                if isinstance(raw_path, str) and raw_path:
                    evidence[label] = file_ref(workspace / raw_path)
            phase = "HOST_TRANSFER_USE"
            phase_context = {
                "external_resume_assessment": assessment_payload,
            }
        elif route.kind == RESUME_KIND_EVO_V2_CHILD_HANDOFF_READY:
            assessment = external_assessment
            if (
                assessment is None
                or assessment.status
                not in {
                    PROGRESS_CHILD_HANDOFF_AUTHORIZED,
                    PROGRESS_CHILD_HANDOFF_READY,
                }
                or assessment.start_step is not None
                or not assessment.child_report_id
                or assessment.child_report_id == child_report_id
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: recursive child handoff is invalid"
                )
            for label, path in (
                (
                    "pre_oos_child_handoff",
                    pre_oos_child_handoff_path(workspace, child_report_id),
                ),
                (
                    "pre_oos_child_intent",
                    pre_oos_child_intent_path(workspace, child_report_id),
                ),
                (
                    "pre_oos_human_approval",
                    pre_oos_human_approval_path(workspace, child_report_id),
                ),
            ):
                evidence[label] = file_ref(path)
            phase = "HOST_CHILD_HANDOFF"
            phase_context = {
                "external_resume_assessment": assessment.to_dict(),
            }
            recursive_child_report_id = str(assessment.child_report_id)
        else:
            if pause != "awaiting_host_lifecycle_transition_and_staged_council_outcome":
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: unsupported child Step6 phase {route.kind}"
                )
            assessment = external_assessment
            if assessment is None:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child Host Council assessment is missing"
                )
            if assessment.status == PROGRESS_WAITING:
                return {
                    "verdict": "PASS",
                    "status": CHILD_QUALIFICATION_WAIT,
                    "reason": assessment.reason,
                    "phase": "HOST_COUNCIL_OUTCOME",
                }
            if (
                assessment.status != PROGRESS_HOST_CHECKPOINT_READY
                or assessment.start_step != "6"
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child Host Council outcome is not ready"
                )
            lifecycle_path = research_protocol_paths(
                workspace, child_report_id
            )["evo_lifecycle"]
            evidence["host_council_lifecycle"] = file_ref(lifecycle_path)
            phase = "HOST_COUNCIL_OUTCOME"

        after = _workspace_evidence_tree(workspace)
        changed = {
            path
            for path in set(baseline_entries) | set(after)
            if baseline_entries.get(path) != after.get(path)
        }
        if any(path not in after for path in changed):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: child phase deleted prior evidence"
            )
        if phase == "HOST_COUNCIL_OUTCOME":
            inflight = materialize_evo_child_phase_inflight(
                state_root=self.config.state_root,
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                job_id=job.job_id,
                parent_report_id=parent_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=expected_host_pin,
                execution_receipt_path=prior_receipt_path,
                workspace_root=workspace,
                phase=phase,
                expected_workspace_paths=tuple(sorted(changed)),
                operation_binding={
                    "operation_kind": "host_council_outcome",
                    "trusted_proof_sha256": _sha256(proof_path),
                    "external_resume_assessment_sha256": stable_json_hash(
                        external_assessment.to_dict()
                    ),
                    "phase_evidence": {
                        label: reference["sha256"]
                        for label, reference in sorted(evidence.items())
                    },
                },
                require_pristine_baseline=False,
            )
            replayed = replay_phase_receipt_if_present(inflight)
            if replayed is not None:
                return replayed
            phase_inflight_path = str(inflight["phase_inflight_path"])
        checkpoint = materialize_evo_child_phase_checkpoint(
            state_root=self.config.state_root,
            trust_root=trust_root,
            installation_id=self.config.installation_id,
            job_id=job.job_id,
            parent_report_id=parent_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=expected_host_pin,
            execution_receipt_path=prior_receipt_path,
            workspace_root=workspace,
            phase=phase,
            allowed_workspace_delta={path: after[path] for path in sorted(changed)},
            phase_evidence=evidence,
            phase_context=phase_context,
            phase_inflight_path=phase_inflight_path,
        )
        if recursive_child_report_id is not None:
            checkpoint["recursive_parent_report_id"] = child_report_id
            checkpoint["recursive_child_report_id"] = recursive_child_report_id
            checkpoint["recursive_external_progress"] = dict(
                phase_context["external_resume_assessment"]
            )
        return checkpoint

    def _execute_evo_v2_child_from_parent_handoff(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume_trust: Mapping[str, Any],
        child_report_id: str,
        parent_report_id: str | None = None,
        trusted_parent_checkpoint: Mapping[str, Any] | None = None,
        trusted_prior_execution: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        parent_id = parent_report_id or job.report_id
        prior_result = job.result if isinstance(job.result, Mapping) else {}
        prior_runtime = prior_result.get("evo_v2_child_runtime")
        prior_ready = (
            prior_runtime.get("ready")
            if isinstance(prior_runtime, Mapping)
            and isinstance(prior_runtime.get("ready"), Mapping)
            else {}
        )
        prior_execution = (
            dict(trusted_prior_execution)
            if trusted_prior_execution is not None
            else (
                prior_runtime.get("execution")
                if isinstance(prior_runtime, Mapping)
                and isinstance(prior_runtime.get("execution"), Mapping)
                else {}
            )
        )
        if (
            prior_ready.get("status") == CHILD_EXECUTION_READY
            and prior_ready.get("parent_report_id") == parent_id
            and prior_ready.get("child_report_id") == child_report_id
            and isinstance(prior_ready.get("checkpoint_path"), str)
            and isinstance(prior_ready.get("catalog_snapshot_path"), str)
            and isinstance(prior_ready.get("calendar_snapshot_path"), str)
        ):
            ready = dict(prior_ready)
        else:
            ready = self._prepare_evo_v2_child_execution_ready(
                job,
                worktree=worktree,
                workspace=workspace,
                resume_trust=resume_trust,
                child_report_id=child_report_id,
                parent_report_id=parent_id,
                trusted_parent_checkpoint=trusted_parent_checkpoint,
            )
        environment = os.environ.copy()
        for key in list(environment):
            upper = key.upper()
            if any(
                token in upper
                for token in ("API_KEY", "PASSWORD", "SECRET", "TOKEN", "COOKIE")
            ):
                environment.pop(key, None)
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_CREDENTIAL_EXPIRATION",
        ):
            environment.pop(key, None)
        prepare_host_data = getattr(
            self.agent_adapter, "prepare_host_data_environment", None
        )
        host_data_env: dict[str, str] = {}
        if callable(prepare_host_data):
            host_data_env, _denied = prepare_host_data(job.job_id)
        elif self.config.execution_mode == "container" and not self.config.auth_disabled:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease provider is missing"
            )
        allowed_lease_keys = {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_CREDENTIAL_EXPIRATION",
        }
        if set(host_data_env) - allowed_lease_keys or any(
            not isinstance(value, str)
            or not value
            or any(control in value for control in ("\x00", "\n", "\r"))
            for value in host_data_env.values()
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: child Host data lease is invalid"
            )
        if self.config.execution_mode == "container" and not self.config.auth_disabled:
            if set(host_data_env) != allowed_lease_keys:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: child Host data lease is incomplete"
                )
        environment.update(host_data_env)
        environment["AWS_EC2_METADATA_DISABLED"] = "true"
        catalog = Path(ready["catalog_snapshot_path"]).expanduser().resolve(
            strict=True
        )
        calendar = Path(ready["calendar_snapshot_path"]).expanduser().resolve(
            strict=True
        )
        for projection_path, label in (
            (catalog, "catalog"),
            (calendar, "calendar"),
        ):
            if (
                projection_path == workspace
                or projection_path.is_relative_to(workspace)
                or not projection_path.is_relative_to(worktree)
            ):
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: child {label} projection is outside the read-only engine"
                )
        environment["FACTORFORGE_STATE_CATALOG"] = str(catalog)
        environment["FACTORFORGE_DATA_CATALOG"] = str(catalog)
        environment["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(calendar)
        _configure_host_formal_python_environment(
            environment,
            worktree=worktree,
            data_api_pythonpath=self.config.data_api_pythonpath,
        )
        trust_root = self.config.state_root / "research-org-trust"
        pin = load_runtime_trust_store(
            trust_root, installation_id=self.config.installation_id
        ).public_manifest["manifest_sha256"]
        # These are Host-control-plane locator credentials, not Agent data
        # credentials.  Ultimate removes them from every ordinary/Agent
        # command and injects them only into the trusted OOS finalizer.  Do not
        # depend on an ambient service environment: an explicit, pinned source
        # is required for crash/restart release liveness.
        environment["FACTORFORGE_OOS_HOST_TRUST_ROOT"] = str(
            trust_root.resolve(strict=True)
        )
        environment["FACTORFORGE_OOS_HOST_INSTALLATION_ID"] = (
            self.config.installation_id
        )
        environment["FACTORFORGE_EVO_CHILD_CONTAINER_STATE_ROOT"] = str(
            self.config.state_root.resolve(strict=True)
        )
        environment["FACTORFORGE_EVO_CHILD_CONTAINER_JOB_ID"] = job.job_id
        resume_child = bool(
            prior_execution.get("status")
            in {CHILD_RESUME_READY, CHILD_RECOVERY_READY}
            and prior_execution.get("child_report_id") == child_report_id
            and prior_execution.get("parent_report_id", parent_id) == parent_id
            and prior_execution.get("resume_start_step") in {"4", "5", "6"}
        )
        qualification: dict[str, Any] | None = None
        qualification_path: str | None = None
        phase_checkpoint: dict[str, Any] | None = None
        phase_checkpoint_path: str | None = None
        if (
            resume_child
            and prior_execution.get("status") == CHILD_RESUME_READY
            and prior_execution.get("resume_start_step") == "6"
        ):
            prior_receipt_path = str(
                prior_execution.get("execution_receipt_path") or ""
            )
            if not prior_receipt_path:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: child execution receipt is missing"
                )
            proof_path = Path(
                str(prior_execution.get("proof_path") or "")
            )
            try:
                prior_proof = json.loads(proof_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: child phase proof is invalid"
                ) from exc
            if (
                isinstance(prior_proof, Mapping)
                and prior_proof.get("final_outcome")
                == "awaiting_evo_v2_host_qualification"
            ):
                qualification = materialize_evo_child_qualification_checkpoint(
                    state_root=self.config.state_root,
                    trust_root=trust_root,
                    installation_id=self.config.installation_id,
                    job_id=job.job_id,
                    parent_report_id=parent_id,
                    child_report_id=child_report_id,
                    expected_host_trust_manifest_sha256=pin,
                    execution_receipt_path=prior_receipt_path,
                    workspace_root=workspace,
                )
            else:
                phase_checkpoint = self._evo_child_phase_checkpoint(
                    job,
                    worktree=worktree,
                    workspace=workspace,
                    child_report_id=child_report_id,
                    prior_execution=prior_execution,
                    trust_root=trust_root,
                    expected_host_pin=pin,
                    parent_report_id=parent_id,
                )
                if phase_checkpoint.get("status") == CHILD_QUALIFICATION_WAIT:
                    waiting_execution = dict(prior_execution)
                    waiting_execution["idempotent_replay"] = True
                    waiting_execution["phase_status"] = CHILD_QUALIFICATION_WAIT
                    waiting_execution["phase_reason"] = phase_checkpoint.get(
                        "reason"
                    )
                    return {
                        "ready": ready,
                        "qualification": None,
                        "phase_checkpoint": phase_checkpoint,
                        "execution": waiting_execution,
                    }
                if phase_checkpoint.get("status") == CHILD_TERMINAL:
                    return {
                        "ready": ready,
                        "qualification": None,
                        "phase_checkpoint": phase_checkpoint,
                        "execution": phase_checkpoint,
                    }
                recursive_child = str(
                    phase_checkpoint.get("recursive_child_report_id") or ""
                )
                recursive_progress = phase_checkpoint.get(
                    "recursive_external_progress"
                )
                if recursive_child:
                    if not isinstance(recursive_progress, Mapping):
                        raise RuntimeError(
                            f"{BLOCK_RESUME_TRUST_INVALID}: recursive child progress is missing"
                        )
                    recursive_parent_checkpoint = {
                        "ultimate_proof_sha256": _sha256(proof_path),
                        "parent_execution_receipt_path": prior_receipt_path,
                        "parent_execution_receipt_sha256": str(
                            prior_execution.get("execution_receipt_sha256") or ""
                        ),
                        "parent_phase_receipt_path": str(
                            phase_checkpoint.get("phase_receipt_path") or ""
                        ),
                        "parent_phase_receipt_sha256": str(
                            phase_checkpoint.get("phase_receipt_sha256") or ""
                        ),
                        "parent_phase_receipt_id": str(
                            phase_checkpoint.get("receipt", {}).get("receipt_id")
                            or ""
                        ),
                        "external_progress_sha256": stable_json_hash(
                            dict(recursive_progress)
                        ),
                    }
                    recursive_runtime = self._execute_evo_v2_child_from_parent_handoff(
                        job,
                        worktree=worktree,
                        workspace=workspace,
                        resume_trust={
                            "evo_v2_external_progress": dict(recursive_progress),
                        },
                        parent_report_id=child_report_id,
                        child_report_id=recursive_child,
                        trusted_parent_checkpoint=recursive_parent_checkpoint,
                    )
                    recursive_runtime["lineage"] = _extend_evo_child_lineage(
                        root_report_id=job.report_id,
                        phase_owner_parent_report_id=parent_id,
                        parent_report_id=child_report_id,
                        child_report_id=recursive_child,
                        phase_checkpoint=phase_checkpoint,
                        descendant_runtime=recursive_runtime,
                    )
                    return recursive_runtime
                if phase_checkpoint.get("status") != CHILD_PHASE_READY:
                    raise RuntimeError(
                        f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: child phase checkpoint is invalid"
                    )
                phase_checkpoint_path = str(
                    phase_checkpoint.get("phase_receipt_path") or ""
                )
            if phase_checkpoint is not None:
                qualification = None
            assert qualification is not None or phase_checkpoint is not None
        if qualification is not None:
            if qualification.get("status") == CHILD_QUALIFICATION_WAIT:
                waiting_execution = dict(prior_execution)
                waiting_execution["idempotent_replay"] = True
                waiting_execution["qualification_status"] = (
                    CHILD_QUALIFICATION_WAIT
                )
                waiting_execution["qualification_reason"] = qualification.get(
                    "reason"
                )
                return {
                    "ready": ready,
                    "qualification": qualification,
                    "execution": waiting_execution,
                }
            if qualification.get("status") != CHILD_QUALIFICATION_READY:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: child qualification checkpoint is invalid"
                )
            qualification_path = str(
                qualification.get("qualification_receipt_path") or ""
            )
        active_lineage = (
            prior_runtime.get("lineage")
            if isinstance(prior_runtime, Mapping)
            and isinstance(prior_runtime.get("lineage"), Mapping)
            else None
        )
        if (
            active_lineage is not None
            and active_lineage.get("child_report_id") == child_report_id
            and active_lineage.get("parent_report_id") == parent_id
        ):
            try:
                ready_receipt = json.loads(
                    Path(str(ready.get("checkpoint_path") or "")).read_text(
                        encoding="utf-8"
                    )
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: active child ready receipt is invalid"
                ) from exc
            ready_parent_checkpoint = (
                ready_receipt.get("trusted_parent_checkpoint")
                if isinstance(ready_receipt, Mapping)
                else None
            )
            if not isinstance(ready_parent_checkpoint, Mapping):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: active child parent checkpoint is missing"
                )
            _validate_evo_child_active_lineage(
                lineage=active_lineage,
                signed_execution=prior_execution,
                trusted_parent_checkpoint=ready_parent_checkpoint,
                state_root=self.config.state_root,
                trust_root=trust_root,
                installation_id=self.config.installation_id,
                job_id=job.job_id,
                expected_host_pin=pin,
                workspace_root=workspace,
                # Step4/5 were exact-replayed at request admission; Step6 has
                # just produced an exact qualification/phase checkpoint.
                replay_phase_receipts=True,
            )
        execution = execute_evo_child_ready(
            checkpoint_path=ready["checkpoint_path"],
            state_root=self.config.state_root,
            trust_root=trust_root,
            installation_id=self.config.installation_id,
            job_id=job.job_id,
            workspace_root=workspace,
            worktree=worktree,
            parent_report_id=parent_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=pin,
            host_environment=environment,
            timeout_seconds=max(
                60, min(3_300, int(self.config.agent_timeout_seconds))
            ),
            resume=resume_child,
            qualification_checkpoint_path=qualification_path,
            phase_checkpoint_path=phase_checkpoint_path,
        )
        return {
            "ready": ready,
            "qualification": qualification,
            "phase_checkpoint": phase_checkpoint,
            "execution": execution,
        }

    def _execute_host_formal_pipeline(
        self,
        job: ResearchJob,
        *,
        worktree: Path,
        workspace: Path,
        resume: bool,
        denied_values: tuple[str, ...],
        host_data_env: dict[str, str] | None = None,
        resume_trust: dict[str, Any] | None = None,
        resume_task: AgentResumeTask | None = None,
        validated_resume_artifacts: ValidatedAgentResumeArtifacts | None = None,
    ) -> dict[str, Any]:
        if not self.config.data_catalogs:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: approved data catalog is missing"
            )
        catalog = self.config.data_catalogs[0].expanduser().resolve(strict=True)
        engine_commit = _validate_formal_engine_checkout(
            self.config.source_repo,
            self._expected_base_commit,
        )
        engine_root = self.config.source_repo.resolve(strict=True)
        engine_scripts = {
            name: _formal_engine_script(engine_root, relative)
            for name, relative in FORMAL_ENGINE_SCRIPTS.items()
        }
        for name, script_path in engine_scripts.items():
            if _sha256(script_path) != _git_blob_sha256(
                engine_root,
                engine_commit,
                FORMAL_ENGINE_SCRIPTS[name],
            ):
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal engine script "
                    "does not match the pinned commit"
                )
        env = os.environ.copy()
        for key in list(env):
            upper = key.upper()
            if any(
                token in upper
                for token in ("API_KEY", "PASSWORD", "SECRET", "TOKEN", "COOKIE")
            ):
                env.pop(key, None)
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_CREDENTIAL_EXPIRATION",
        ):
            env.pop(key, None)
        allowed_lease_keys = {
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_CREDENTIAL_EXPIRATION",
        }
        lease_env = dict(host_data_env or {})
        if set(lease_env) - allowed_lease_keys or any(
            not isinstance(value, str)
            or not value
            or "\x00" in value
            or "\n" in value
            or "\r" in value
            for value in lease_env.values()
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease environment is invalid"
            )
        if self.config.execution_mode == "container" and not self.config.auth_disabled:
            if set(lease_env) != allowed_lease_keys:
                raise RuntimeError(
                    f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: host data lease environment is incomplete"
                )
        env.update(lease_env)
        env["AWS_EC2_METADATA_DISABLED"] = "true"
        env["FACTORFORGE_STATE_CATALOG"] = str(catalog)
        env["FACTORFORGE_DATA_CATALOG"] = str(catalog)
        incident_trust_root = self.config.state_root / "research-org-trust"
        ensure_runtime_trust_store(
            incident_trust_root,
            installation_id=self.config.installation_id,
        )
        ensure_empty_oos_exposure_private_registry(
            incident_trust_root,
            installation_id=self.config.installation_id,
        )
        incident_trust_root = incident_trust_root.resolve(strict=True)
        incident_store = load_runtime_trust_store(
            incident_trust_root,
            installation_id=self.config.installation_id,
        )
        if not incident_store.public_manifest.get("manifest_sha256"):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Host incident trust pin is invalid"
            )
        # Root Web materialization occurs before Ultimate starts, so it must
        # receive the same explicit Host-private negative-incident context as
        # the child prepare path. Ultimate captures and strips this pair before
        # launching ordinary/Agent commands.
        env["FACTORFORGE_OOS_HOST_TRUST_ROOT"] = str(incident_trust_root)
        env["FACTORFORGE_OOS_HOST_INSTALLATION_ID"] = (
            self.config.installation_id
        )
        _configure_host_formal_python_environment(
            env,
            worktree=worktree,
            data_api_pythonpath=self.config.data_api_pythonpath,
        )
        plan_path = workspace / "identity" / "web_research_plan.json"
        commands: list[dict[str, Any]] = []
        if resume:
            if not isinstance(resume_trust, dict) or resume_trust.get("start_step") not in {
                "3",
                "4",
                "5",
                "6",
            }:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: host-verified resume context is required"
                )
        elif resume_trust is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh execution cannot carry resume trust"
            )
        conversation_ledger_binding = _validate_host_conversation_ledger_binding(
            workspace=workspace,
            state_root=self.config.state_root,
            job=job,
            resume=resume,
            resume_trust=resume_trust,
        )

        def run_host_command(
            name: str,
            argv: list[str],
            *,
            timeout: int,
        ) -> dict[str, Any]:
            started = utc_now()
            timed_out = False
            try:
                proc = subprocess.run(
                    argv,
                    cwd=worktree,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                )
                returncode = proc.returncode
                stdout = proc.stdout
                stderr = proc.stderr
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                returncode = 124
                stdout = _subprocess_text(exc.stdout)
                stderr = _subprocess_text(exc.stderr)
            return {
                "name": name,
                "argv": argv,
                "argv_sha256": stable_json_hash(argv),
                "engine_script_sha256": _sha256(Path(argv[1])),
                "cwd": str(worktree),
                "host_observed_process": True,
                "readonly_data_lease_injected": bool(lease_env),
                "started_at_utc": started,
                "finished_at_utc": utc_now(),
                "returncode": returncode,
                "timed_out": timed_out,
                "stdout_tail": redact_secret_values(
                    stdout[-16_000:],
                    denied_values,
                    replacement="[redacted]",
                ),
                "stderr_tail": redact_secret_values(
                    stderr[-16_000:],
                    denied_values,
                    replacement="[redacted]",
                ),
            }

        materialize_argv = [
            sys.executable,
            str(engine_scripts["materialize_web_research"]),
            "--workspace-root",
            str(workspace),
            "--plan",
            str(plan_path),
        ]
        materialize_argv.extend(
            self._research_org_ultimate_args(job=job, workspace=workspace)
        )
        materialize = run_host_command(
            "materialize_web_research",
            materialize_argv,
            timeout=180,
        )
        commands.append(materialize)
        if materialize["returncode"] != 0:
            receipt = self._write_formal_execution_receipt(
                job,
                workspace=workspace,
                commands=commands,
                resume=resume,
                resume_trust=resume_trust,
                resume_task=resume_task,
                validated_resume_artifacts=validated_resume_artifacts,
                conversation_ledger_binding=conversation_ledger_binding,
            )
            detail = materialize["stderr_tail"] or materialize["stdout_tail"]
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: materializer returncode="
                f"{materialize['returncode']} receipt={receipt['receipt_id']} detail={detail[-1200:]}"
            )

        if is_validated_evo_v2_memory_runtime_enabled(
            workspace=workspace,
            report_id=job.report_id,
        ):
            evo_v2_memory_state = prepare_evo_v2_memory_round(
                workspace=workspace,
                worktree=worktree,
                state_root=self.config.state_root,
                installation_id=self.config.installation_id,
                runner=self.agent_adapter,
            )
            if evo_v2_memory_state.get("formal_execution_allowed") is not True:
                receipt = self._write_formal_execution_receipt(
                    job,
                    workspace=workspace,
                    commands=commands,
                    resume=resume,
                    resume_trust=resume_trust,
                    resume_task=resume_task,
                    validated_resume_artifacts=validated_resume_artifacts,
                    conversation_ledger_binding=conversation_ledger_binding,
                )
                raise EvoV2MemoryGatePause(evo_v2_memory_state, receipt)

        start_step = str(resume_trust["start_step"]) if resume_trust is not None else "3"
        ultimate_argv = [
            sys.executable,
            str(engine_scripts["run_factorforge_ultimate"]),
            "--report-id",
            job.report_id,
            "--start-step",
            start_step,
            "--end-step",
            "all",
            "--factorforge-root",
            str(worktree),
            "--factor-id",
            job.factor_id,
            "--research-id",
            job.research_id,
            "--factor-workspace",
            str(workspace),
            "--research-org-mode",
            (
                "required"
                if (workspace / "identity" / "research_organization_plan.json").is_file()
                else "auto"
            ),
        ]
        ultimate_argv.extend(
            self._research_org_ultimate_args(job=job, workspace=workspace)
        )
        ultimate = run_host_command(
            "run_factorforge_ultimate",
            ultimate_argv,
            timeout=max(60, min(3000, self.config.agent_timeout_seconds)),
        )
        commands.append(ultimate)
        receipt = self._write_formal_execution_receipt(
            job,
            workspace=workspace,
            commands=commands,
            resume=resume,
            resume_trust=resume_trust,
            resume_task=resume_task,
            validated_resume_artifacts=validated_resume_artifacts,
            conversation_ledger_binding=conversation_ledger_binding,
        )
        if ultimate["timed_out"]:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Ultimate timed out; "
                f"receipt={receipt['receipt_id']}"
            )
        if ultimate["returncode"] != 0:
            self._validate_formal_failure_checkpoint(
                job,
                workspace=workspace,
                returncode=int(ultimate["returncode"]),
                receipt_id=str(receipt["receipt_id"]),
            )
        return receipt

    @staticmethod
    def _validate_formal_failure_checkpoint(
        job: ResearchJob,
        *,
        workspace: Path,
        returncode: int,
        receipt_id: str,
    ) -> None:
        proof_relative = (
            "objects/runtime_context/"
            f"ultimate_run_report__{job.report_id}.json"
        )
        try:
            proof = _read_regular_workspace_json(workspace, proof_relative)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Ultimate returncode="
                f"{returncode} lacks a safe wrapper proof; receipt={receipt_id}"
            ) from exc
        failure = proof.get("failure") if isinstance(proof, dict) else None
        expected_identity = {
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
        }
        if (
            not isinstance(proof, dict)
            or proof.get("contract_version") != "factorforge_ultimate_wrapper_v1"
            or any(proof.get(key) != value for key, value in expected_identity.items())
            or str(proof.get("status") or "").upper()
            not in {"FAIL", "BLOCK_DATA_REQUEST_PENDING"}
            or not isinstance(proof.get("finished_at_utc"), str)
            or not proof["finished_at_utc"].strip()
            or not isinstance(failure, dict)
            or not str(failure.get("command") or "").strip()
            or isinstance(failure.get("returncode"), bool)
            or not isinstance(failure.get("returncode"), int)
            or failure.get("returncode") != returncode
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: Ultimate returncode="
                f"{returncode} wrapper failure checkpoint is invalid; "
                f"receipt={receipt_id}"
            )

    def _write_formal_execution_receipt(
        self,
        job: ResearchJob,
        *,
        workspace: Path,
        commands: list[dict[str, Any]],
        resume: bool,
        resume_trust: dict[str, Any] | None = None,
        resume_task: AgentResumeTask | None = None,
        validated_resume_artifacts: ValidatedAgentResumeArtifacts | None = None,
        conversation_ledger_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if resume and not isinstance(resume_trust, dict):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resumed receipt requires a trusted parent"
            )
        if not resume and resume_trust is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh receipt cannot carry a trusted parent"
            )
        if (resume_task is None) != (validated_resume_artifacts is None):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation audit identity is incomplete"
            )
        if (
            not isinstance(conversation_ledger_binding, dict)
            or conversation_ledger_binding.get("version")
            != HOST_CONVERSATION_LEDGER_BINDING_VERSION
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: formal conversation ledger binding is missing"
            )
        formal_owned_artifact_transitions: dict[str, dict[str, Any]] = {}
        if resume_task is not None and validated_resume_artifacts is not None:
            validated_hashes = dict(
                validated_resume_artifacts.workspace_file_sha256
            )
            formal_owned_relatives = _formal_owned_resume_relatives(resume_task)
            if not formal_owned_relatives.issubset(validated_hashes):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation audit baseline is incomplete"
                )
            for relative in sorted(formal_owned_relatives):
                candidate = workspace / relative
                after_sha256 = None
                if candidate.is_file() and not candidate.is_symlink():
                    after_sha256 = _sha256(candidate)
                formal_owned_artifact_transitions[relative] = {
                    "before_sha256": validated_hashes[relative],
                    "after_sha256": after_sha256,
                    "changed": after_sha256 != validated_hashes[relative],
                    "producer": "host_formal_pipeline",
                }
        proof_path = (
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        engine_commit = _validate_formal_engine_checkout(
            self.config.source_repo,
            self._expected_base_commit,
        )
        engine_root = self.config.source_repo.resolve(strict=True)
        payload = {
            "version": "factorforge_console_host_formal_execution_v2",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
            "engine_commit": engine_commit,
            "engine_root": str(engine_root),
            "resume": resume,
            "resume_parent": (
                {
                    "start_step": str(resume_trust["start_step"]),
                    "ultimate_proof_sha256": str(
                        resume_trust["ultimate_proof_sha256"]
                    ),
                    "attestation_id": str(resume_trust["attestation_id"]),
                    "attestation_sha256": str(resume_trust["attestation_sha256"]),
                    "receipt_id": str(resume_trust["receipt_id"]),
                    "receipt_sha256": str(resume_trust["receipt_sha256"]),
                }
                if resume_trust is not None
                else None
            ),
            "conversation_ledger_binding": deepcopy(
                conversation_ledger_binding
            ),
            "readonly_data_lease_injected": bool(
                commands
                and all(
                    command.get("readonly_data_lease_injected") is True
                    for command in commands
                )
            ),
            "commands": commands,
            "formal_owned_artifact_transitions": (
                formal_owned_artifact_transitions
            ),
            "ultimate_proof_sha256": (
                _sha256(proof_path)
                if proof_path.is_file() and not proof_path.is_symlink()
                else None
            ),
            "recorded_at_utc": utc_now(),
        }
        receipt_root = self.config.state_root / "jobs" / job.job_id / "formal-execution"
        receipt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt_root.chmod(0o700)
        receipt_path = receipt_root / (
            f"receipt_{_stamp(utc_now())}_{uuid.uuid4().hex[:12]}.json"
        )
        _write_json_atomic(receipt_path, payload, root=self.config.state_root)
        return {
            "receipt_id": receipt_path.relative_to(self.config.state_root).as_posix(),
            "receipt_sha256": _sha256(receipt_path),
            "ultimate_argv_sha256": next(
                (
                    str(item.get("argv_sha256") or "")
                    for item in commands
                    if item.get("name") == "run_factorforge_ultimate"
                ),
                "",
            ),
            "ultimate_returncode": next(
                (
                    int(item.get("returncode"))
                    for item in commands
                    if item.get("name") == "run_factorforge_ultimate"
                ),
                None,
            ),
            "conversation_ledger_binding": deepcopy(
                conversation_ledger_binding
            ),
        }

    @staticmethod
    def _validate_summary_identity(job: ResearchJob, summary: UltimateRunSummary) -> None:
        expected = {
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
        }
        for key, value in expected.items():
            actual = str(getattr(summary, key) or "")
            if actual != value:
                raise RuntimeError(
                    f"{BLOCK_EVIDENCE_IDENTITY_MISMATCH}: {key} expected={value!r} actual={actual!r}"
                )

    @staticmethod
    def _preformal_forbidden_artifacts(workspace: Path) -> list[str]:
        forbidden: list[str] = []
        for path in sorted(workspace.rglob("*")):
            if not path.exists() and not path.is_symlink():
                continue
            relative = path.relative_to(workspace).as_posix()
            name = path.name.lower()
            if (
                relative == "identity/web_research_bootstrap_result.json"
                or relative.startswith("objects/evo_v2/")
                or relative.startswith("objects/runtime_context/ultimate_run_report__")
                or name.startswith("evo_oos_allocation__")
                or name.startswith("oos_release_manifest__")
            ):
                forbidden.append(relative)
        return forbidden

    @staticmethod
    def _workspace_refs_under(
        workspace: Path,
        relative_root: str,
    ) -> list[dict[str, str]]:
        relative = Path(relative_root)
        if (
            relative.is_absolute()
            or relative == Path(".")
            or ".." in relative.parts
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: research organization root is unsafe"
            )
        root = workspace / relative
        resolved_workspace = workspace.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        try:
            resolved_root.relative_to(resolved_workspace)
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: research organization root escapes workspace"
            ) from exc
        refs: list[dict[str, str]] = []
        for path in sorted(resolved_root.rglob("*")):
            item_relative = path.relative_to(resolved_workspace).as_posix()
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: unsafe organization artifact "
                    f"{item_relative}"
                )
            if path.is_file():
                refs.append({"path": item_relative, "sha256": _sha256(path)})
        return refs

    def _validated_preformal_organization_binding(
        self,
        job: ResearchJob,
        *,
        workspace: Path,
    ) -> dict[str, Any]:
        bundle = validate_research_organization_bundle(
            workspace=workspace,
            require_results=True,
        )
        plan = load_research_organization_plan(workspace)
        expected_identity = {
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "job_id": job.job_id,
        }
        if plan.get("identity") != expected_identity:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: organization identity changed"
            )
        runtime = validate_research_organization_runtime(
            workspace=workspace,
            require_complete=True,
            private_root=(
                self.config.state_root
                / "jobs"
                / job.job_id
                / "research_org_private"
            ),
            trust_root=self.config.state_root / "research-org-trust",
            installation_id=self.config.installation_id,
            require_formal=True,
        )
        ledger = (
            runtime.get("transactional_ledger")
            if isinstance(runtime.get("transactional_ledger"), dict)
            else {}
        )
        if (
            bundle.get("execution_state") != "COMPLETE"
            or runtime.get("lifecycle") != "COMPLETE"
            or runtime.get("formal_independence_verified") is not True
            or runtime.get("runtime_assurance") != PREFORMAL_RUNTIME_ASSURANCE
            or ledger.get("ledger_state") != "COMPLETE"
            or ledger.get("formal_independence_verified") is not True
            or ledger.get("assurance") != PREFORMAL_RUNTIME_ASSURANCE
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: formal organization runtime is incomplete"
            )
        policy = plan.get("workspace_policy")
        if not isinstance(policy, dict):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: organization workspace policy is missing"
            )
        organization_root = str(policy.get("organization_root") or "")
        result_root = str(policy.get("result_root") or "")
        runtime_refs = self._workspace_refs_under(
            workspace,
            f"{organization_root}/runtime",
        )
        result_refs = self._workspace_refs_under(workspace, result_root)
        expected_result_count = int(runtime.get("result_count") or 0)
        if (
            not runtime_refs
            or len(result_refs) != expected_result_count
            or int(bundle.get("result_count") or 0) != expected_result_count
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: organization runtime/result set is incomplete"
            )
        return {
            "plan_sha256": str(plan.get("plan_sha256") or ""),
            "runtime_id": str(runtime.get("runtime_id") or ""),
            "lifecycle": "COMPLETE",
            "formal_independence_verified": True,
            "runtime_assurance": PREFORMAL_RUNTIME_ASSURANCE,
            "runtime_projection_sha256": stable_json_hash(runtime),
            "transactional_ledger_sha256": stable_json_hash(ledger),
            "runtime_artifact_refs": runtime_refs,
            "result_artifact_refs": result_refs,
            "runtime_artifact_count": len(runtime_refs),
            "result_count": expected_result_count,
        }

    def _write_preformal_design_checkpoint(
        self,
        job: ResearchJob,
        *,
        workspace: Path,
    ) -> dict[str, Any]:
        if job.request.research_scope != RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: preformal scope is not authorized"
            )
        forbidden = self._preformal_forbidden_artifacts(workspace)
        if forbidden:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: formal/OOS artifacts already exist: "
                f"{', '.join(forbidden)}"
            )
        organization_binding = self._validated_preformal_organization_binding(
            job,
            workspace=workspace,
        )
        trust_store = load_runtime_trust_store(
            self.config.state_root / "research-org-trust",
            installation_id=self.config.installation_id,
        )
        preformal_snapshot_parent = ensure_host_private_job_subdirectory(
            self.config.state_root,
            job.job_id,
            ("preformal_design", "snapshots"),
            create=True,
        )
        snapshot = self._snapshot_workspace_evidence(
            job,
            workspace,
            snapshot_parent=preformal_snapshot_parent,
        )
        snapshot_entries = _workspace_evidence_tree(snapshot)
        snapshot_relative = snapshot.relative_to(
            self.config.state_root.resolve(strict=True)
        ).as_posix()
        receipt = trust_store.sign(
            "host_admission",
            {
                "receipt_type": PREFORMAL_CHECKPOINT_RECEIPT_TYPE,
                "checkpoint_id": f"preformal_{uuid.uuid4().hex}",
                "issued_at_utc": utc_now(),
                "identity": self._private_lifecycle_identity(job),
                "request_binding": {
                    "research_scope": RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY,
                    "request_sha256": stable_json_hash(job.request.to_dict()),
                },
                "research_organization": organization_binding,
                "workspace_evidence": {
                    "snapshot_relative_path": snapshot_relative,
                    "workspace_tree_sha256": stable_json_hash(snapshot_entries),
                    "file_count": len(snapshot_entries),
                },
                "authority_boundary": {
                    "current_factor_empirical_verdict": "NOT_ISSUED",
                    "factor_verdict": "UNKNOWN",
                    "formal": False,
                    "formal_proof_eligible": False,
                    "production_eligible": False,
                    "promotion_allowed": False,
                    "resume_allowed": False,
                },
                "negative_execution_attestation": {
                    "host_data_lease_requested": False,
                    "data_materializer_invoked": False,
                    "ultimate_invoked": False,
                    "step3_6_invoked": False,
                    "oos_allocated": False,
                    "oos_read": False,
                    "oos_released": False,
                    "oos_consumed": False,
                    "forbidden_artifacts_absent": True,
                },
                "trust_manifest_sha256": trust_store.public_manifest[
                    "manifest_sha256"
                ],
            },
        )
        checkpoint_root = ensure_host_private_job_subdirectory(
            self.config.state_root,
            job.job_id,
            ("preformal_design",),
            create=True,
        )
        receipt_root = ensure_host_private_job_subdirectory(
            self.config.state_root,
            job.job_id,
            ("preformal_design", "receipts"),
            create=True,
        )
        receipt_id = str(receipt["receipt_id"])
        receipt_path = receipt_root / f"receipt_{receipt_id}.json"
        _write_private_json_once(
            receipt_path,
            receipt,
            root=self.config.state_root,
            block_token=BLOCK_RESUME_TRUST_INVALID,
            label="preformal design receipt",
        )
        pointer = {
            "version": PREFORMAL_CHECKPOINT_POINTER_VERSION,
            "identity": self._private_lifecycle_identity(job),
            "receipt_id": receipt_id,
            "receipt_sha256": _sha256(receipt_path),
        }
        _write_private_json_once(
            checkpoint_root / "current.json",
            pointer,
            root=self.config.state_root,
            block_token=BLOCK_RESUME_TRUST_INVALID,
            label="preformal design current pointer",
        )
        return self._replay_preformal_design_checkpoint(
            job,
            workspace=workspace,
        )

    def _replay_preformal_design_checkpoint(
        self,
        job: ResearchJob,
        *,
        workspace: Path,
    ) -> dict[str, Any]:
        state_root = self.config.state_root.resolve(strict=True)
        checkpoint_root = ensure_host_private_job_subdirectory(
            state_root,
            job.job_id,
            ("preformal_design",),
            create=False,
        )
        _recover_private_json_once_publish(
            checkpoint_root / "current.json",
            root=state_root,
            block_token=BLOCK_RESUME_TRUST_INVALID,
            label="preformal design current pointer",
        )
        pointer_bytes, _pointer_sha256, _pointer_relative = (
            _read_private_regular_file_once(
                state_root,
                checkpoint_root / "current.json",
                block_token=BLOCK_RESUME_TRUST_INVALID,
                label="preformal design current pointer",
            )
        )
        try:
            pointer = json.loads(pointer_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: preformal pointer is invalid JSON"
            ) from exc
        expected_identity = self._private_lifecycle_identity(job)
        if (
            not isinstance(pointer, dict)
            or set(pointer)
            != {"version", "identity", "receipt_id", "receipt_sha256"}
            or pointer.get("version") != PREFORMAL_CHECKPOINT_POINTER_VERSION
            or pointer.get("identity") != expected_identity
            or not re.fullmatch(r"[0-9a-f]{64}", str(pointer.get("receipt_id") or ""))
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(pointer.get("receipt_sha256") or "")
            )
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: preformal pointer identity is invalid"
            )
        receipt_id = str(pointer["receipt_id"])
        receipt_path = (
            checkpoint_root / "receipts" / f"receipt_{receipt_id}.json"
        )
        _recover_private_json_once_publish(
            receipt_path,
            root=state_root,
            block_token=BLOCK_RESUME_TRUST_INVALID,
            label="preformal design receipt",
        )
        receipt_bytes, receipt_sha256, _receipt_relative = (
            _read_private_regular_file_once(
                state_root,
                receipt_path,
                block_token=BLOCK_RESUME_TRUST_INVALID,
                label="preformal design receipt",
            )
        )
        try:
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: preformal receipt is invalid JSON"
            ) from exc
        trust_store = load_runtime_trust_store(
            state_root / "research-org-trust",
            installation_id=self.config.installation_id,
        )
        verification_reasons = (
            trust_store.verify(receipt, expected_issuer="host_admission")
            if isinstance(receipt, dict)
            else ["receipt.object_required"]
        )
        expected_boundary = {
            "current_factor_empirical_verdict": "NOT_ISSUED",
            "factor_verdict": "UNKNOWN",
            "formal": False,
            "formal_proof_eligible": False,
            "production_eligible": False,
            "promotion_allowed": False,
            "resume_allowed": False,
        }
        expected_negative = {
            "host_data_lease_requested": False,
            "data_materializer_invoked": False,
            "ultimate_invoked": False,
            "step3_6_invoked": False,
            "oos_allocated": False,
            "oos_read": False,
            "oos_released": False,
            "oos_consumed": False,
            "forbidden_artifacts_absent": True,
        }
        if (
            verification_reasons
            or receipt_sha256 != pointer["receipt_sha256"]
            or not isinstance(receipt, dict)
            or receipt.get("receipt_id") != receipt_id
            or receipt.get("receipt_type") != PREFORMAL_CHECKPOINT_RECEIPT_TYPE
            or receipt.get("identity") != expected_identity
            or receipt.get("request_binding")
            != {
                "research_scope": RESEARCH_SCOPE_PREFORMAL_DESIGN_ONLY,
                "request_sha256": stable_json_hash(job.request.to_dict()),
            }
            or receipt.get("authority_boundary") != expected_boundary
            or receipt.get("negative_execution_attestation") != expected_negative
            or receipt.get("trust_manifest_sha256")
            != trust_store.public_manifest["manifest_sha256"]
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: preformal receipt failed signed replay"
            )
        organization_binding = self._validated_preformal_organization_binding(
            job,
            workspace=workspace,
        )
        if receipt.get("research_organization") != organization_binding:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: organization evidence changed"
            )
        workspace_evidence = receipt.get("workspace_evidence")
        if not isinstance(workspace_evidence, dict):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: workspace evidence is missing"
            )
        snapshot_relative = Path(
            str(workspace_evidence.get("snapshot_relative_path") or "")
        )
        if snapshot_relative.is_absolute() or ".." in snapshot_relative.parts:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: snapshot reference is unsafe"
            )
        snapshot = (state_root / snapshot_relative).resolve(strict=True)
        expected_snapshot_parent = ensure_host_private_job_subdirectory(
            state_root,
            job.job_id,
            ("preformal_design", "snapshots"),
            create=False,
        )
        if (
            snapshot.parent != expected_snapshot_parent
            or not snapshot.name.startswith("workspace_")
            or snapshot.is_symlink()
            or not snapshot.is_dir()
            or snapshot.stat().st_mode & 0o222
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: snapshot is not immutable Host evidence"
            )
        snapshot_entries = _workspace_evidence_tree(snapshot)
        current_entries = _workspace_evidence_tree(workspace)
        tree_sha256 = stable_json_hash(snapshot_entries)
        if (
            snapshot_entries != current_entries
            or workspace_evidence
            != {
                "snapshot_relative_path": snapshot_relative.as_posix(),
                "workspace_tree_sha256": tree_sha256,
                "file_count": len(snapshot_entries),
            }
            or self._preformal_forbidden_artifacts(workspace)
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: preformal workspace evidence changed"
            )
        return {
            "status": "PASS",
            "receipt_id": receipt_id,
            "receipt_sha256": receipt_sha256,
            "trust_manifest_sha256": trust_store.public_manifest[
                "manifest_sha256"
            ],
            "workspace_tree_sha256": tree_sha256,
            "organization_runtime_sha256": organization_binding[
                "runtime_projection_sha256"
            ],
            "organization_results_sha256": stable_json_hash(
                organization_binding["result_artifact_refs"]
            ),
            "organization_runtime_id": organization_binding["runtime_id"],
            "organization_result_count": organization_binding["result_count"],
        }

    def _snapshot_workspace_evidence(
        self,
        job: ResearchJob,
        workspace: Path,
        *,
        snapshot_parent: Path | None = None,
    ) -> Path:
        source_root = workspace.resolve(strict=True)
        state_root = self.config.state_root.resolve(strict=True)
        if snapshot_parent is None:
            snapshot_parent = (
                state_root / "attestations" / job.job_id / "snapshots"
            )
            snapshot_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            snapshot_parent.chmod(0o700)
        snapshot_parent = snapshot_parent.resolve(strict=True)
        try:
            snapshot_parent.relative_to(state_root)
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: snapshot parent escapes Host state"
            ) from exc
        suffix = f"{_stamp(utc_now())}_{uuid.uuid4().hex[:12]}"
        final_root = snapshot_parent / f"workspace_{suffix}"
        temporary_root = snapshot_parent / f".workspace_{suffix}.tmp"
        temporary_root.mkdir(mode=0o700)
        try:
            source_entries = _workspace_evidence_tree(source_root)
            for relative, expected_sha256 in source_entries.items():
                relative_path = Path(relative)
                source = source_root / relative_path
                resolved = source.resolve(strict=True)
                try:
                    resolved.relative_to(source_root)
                except ValueError as exc:
                    raise RuntimeError(
                        f"{BLOCK_ISOLATION_AUDIT_FAILED}: snapshot source escapes workspace"
                    ) from exc
                if source.is_symlink() or not source.is_file():
                    raise RuntimeError(
                        f"{BLOCK_ISOLATION_AUDIT_FAILED}: snapshot source is unsafe"
                    )
                destination = temporary_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                source_descriptor = os.open(
                    source,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                destination_descriptor = os.open(
                    destination,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                try:
                    source_before = os.fstat(source_descriptor)
                    if not stat.S_ISREG(source_before.st_mode):
                        raise RuntimeError(
                            f"{BLOCK_ISOLATION_AUDIT_FAILED}: snapshot source is not regular"
                        )
                    while True:
                        chunk = os.read(source_descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        offset = 0
                        while offset < len(chunk):
                            offset += os.write(
                                destination_descriptor,
                                chunk[offset:],
                            )
                    os.utime(
                        destination_descriptor,
                        ns=(source_before.st_atime_ns, source_before.st_mtime_ns),
                    )
                    os.fsync(destination_descriptor)
                    source_after = os.fstat(source_descriptor)
                finally:
                    os.close(destination_descriptor)
                    os.close(source_descriptor)
                if (
                    source_before.st_ino != source_after.st_ino
                    or source_before.st_size != source_after.st_size
                    or source_before.st_mtime_ns != source_after.st_mtime_ns
                    or digest.hexdigest() != expected_sha256
                ):
                    raise RuntimeError(
                        f"{BLOCK_ISOLATION_AUDIT_FAILED}: workspace changed during evidence snapshot"
                    )
            source_entries_after = _workspace_evidence_tree(source_root)
            snapshot_entries = _workspace_evidence_tree(temporary_root)
            if (
                source_entries_after != source_entries
                or snapshot_entries != source_entries
            ):
                raise RuntimeError(
                    f"{BLOCK_ISOLATION_AUDIT_FAILED}: workspace evidence snapshot is inconsistent"
                )
            for path in sorted(temporary_root.rglob("*"), reverse=True):
                path.chmod(0o500 if path.is_dir() else 0o400)
            temporary_root.chmod(0o500)
            temporary_root.replace(final_root)
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise
        return final_root

    def _write_host_attestation(
        self,
        *,
        job: ResearchJob,
        workspace: Path,
        evidence_root: Path,
        summary: UltimateRunSummary,
        agent_result: AgentRunResult,
        web_materialization: dict[str, str],
        formal_execution: dict[str, Any],
        researcher_memory_outcome: dict[str, Any],
        current_authority_validation: dict[str, Any] | None = None,
        resume_task: AgentResumeTask | None = None,
        validated_resume_artifacts: ValidatedAgentResumeArtifacts | None = None,
        validated_agent_receipt: ValidatedAgentReceipt | None = None,
    ) -> str:
        workspace_root = workspace.resolve(strict=True)
        state_root = self.config.state_root.resolve(strict=True)
        snapshot_root = evidence_root.resolve(strict=True)
        expected_snapshot_parent = (
            state_root / "attestations" / job.job_id / "snapshots"
        ).resolve(strict=True)
        try:
            snapshot_relative = snapshot_root.relative_to(state_root)
            snapshot_root.relative_to(expected_snapshot_parent)
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: attestation evidence is not a host snapshot"
            ) from exc
        if (
            snapshot_root.parent != expected_snapshot_parent
            or not snapshot_root.name.startswith("workspace_")
            or snapshot_root.is_symlink()
            or not snapshot_root.is_dir()
            or snapshot_root.stat().st_mode & 0o222
        ):
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: attestation evidence snapshot is unsafe"
            )
        workspace_entries = _workspace_evidence_tree(snapshot_root)
        expected_wrapper_artifact_id = (
            "objects/runtime_context/"
            f"ultimate_run_report__{job.report_id}.json"
        )
        if summary.artifact_ids.get("wrapper_report") != expected_wrapper_artifact_id:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: "
                "current wrapper summary binding is invalid"
            )
        evidence_hashes: dict[str, dict[str, str]] = {}
        for role, artifact_id in sorted(summary.artifact_ids.items()):
            relative_input = Path(artifact_id)
            if relative_input.is_absolute() or ".." in relative_input.parts:
                raise RuntimeError(
                    f"{BLOCK_ISOLATION_AUDIT_FAILED}: attested evidence identity is unsafe"
                )
            lexical = snapshot_root / relative_input
            current = snapshot_root
            for part in relative_input.parts:
                current = current / part
                if current.is_symlink():
                    raise RuntimeError(
                        f"{BLOCK_FORMAL_EVIDENCE_MISSING}: attested evidence uses a symlink"
                    )
            candidate = lexical.resolve(strict=True)
            try:
                relative = candidate.relative_to(snapshot_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"{BLOCK_ISOLATION_AUDIT_FAILED}: attested evidence escapes workspace"
                ) from exc
            if not candidate.is_file() or candidate.is_symlink():
                raise RuntimeError(
                    f"{BLOCK_FORMAL_EVIDENCE_MISSING}: attested evidence is unsafe"
                )
            evidence_hashes[role] = {
                "artifact_id": relative.as_posix(),
                "sha256": workspace_entries[relative.as_posix()],
            }

        agent_result_raw = Path(agent_result.result_path).expanduser()
        if agent_result_raw.is_symlink():
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: agent result record is unsafe"
            )
        agent_result_path = agent_result_raw.resolve(strict=True)
        try:
            agent_result_relative = agent_result_path.relative_to(state_root)
        except ValueError as exc:
            raise RuntimeError(
                f"BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: agent result path is outside host state"
            ) from exc
        if (
            not agent_result_path.is_file()
            or agent_result_path.is_symlink()
            or agent_result_relative.parts[:2] != ("jobs", job.job_id)
        ):
            raise RuntimeError(
                "BLOCK_FACTORFORGE_CONSOLE_AGENT_RUNTIME_FAILED: agent result record is unsafe"
            )
        immutable_suffix = snapshot_root.name.removeprefix("workspace_")
        agent_receipt_snapshot_path = (
            snapshot_root.parent / f"agent_receipt_{immutable_suffix}.json"
        )
        expected_agent_receipt_sha256 = (
            validated_resume_artifacts.agent_run_receipt_sha256
            if validated_resume_artifacts is not None
            else None
        )
        if validated_agent_receipt is not None:
            if (
                validated_agent_receipt.receipt_id
                != agent_result_relative.as_posix()
                or (
                    expected_agent_receipt_sha256 is not None
                    and expected_agent_receipt_sha256
                    != validated_agent_receipt.receipt_sha256
                )
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: validated agent receipt identity changed"
                )
            expected_agent_receipt_sha256 = (
                validated_agent_receipt.receipt_sha256
            )
        agent_receipt_snapshot_sha256 = _copy_immutable_regular_file(
            agent_result_path,
            agent_receipt_snapshot_path,
            root=state_root,
            expected_sha256=expected_agent_receipt_sha256,
            block_token=BLOCK_RESUME_TRUST_INVALID,
            label="agent run receipt",
        )
        agent_receipt_snapshot_relative = (
            agent_receipt_snapshot_path.relative_to(state_root).as_posix()
        )
        resume_artifact_binding: dict[str, Any] | None = None
        if resume_task is None and validated_resume_artifacts is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh attestation carries resume artifacts"
            )
        if resume_task is not None:
            if validated_resume_artifacts is None:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: resumed attestation lacks validated agent artifacts"
                )
            formal_owned_relatives = _formal_owned_resume_relatives(resume_task)
            if any(
                relative not in formal_owned_relatives
                and workspace_entries.get(relative) != digest
                for relative, digest in validated_resume_artifacts.workspace_file_sha256
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: host snapshot disagrees with validated resume artifacts"
                )
            if (
                validated_resume_artifacts.agent_run_receipt_id
                != agent_result_relative.as_posix()
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: validated agent receipt identity changed"
                )
            prior_archive_snapshot_id = ""
            prior_archive_snapshot_sha256 = ""
            if validated_resume_artifacts.prior_output_archive_id:
                prior_archive_source = _read_private_resume_archive(
                    self.config.state_root,
                    resume_task,
                )
                prior_archive_snapshot_path = (
                    snapshot_root.parent
                    / f"prior_memo_archive_{immutable_suffix}.json"
                )
                prior_archive_snapshot_sha256 = _copy_immutable_regular_file(
                    prior_archive_source,
                    prior_archive_snapshot_path,
                    root=state_root,
                    expected_sha256=(
                        validated_resume_artifacts.prior_output_archive_sha256
                    ),
                    block_token=BLOCK_RESUME_TRUST_INVALID,
                    label="prior mechanism memo archive",
                )
                prior_archive_snapshot_id = (
                    prior_archive_snapshot_path.relative_to(
                        state_root
                    ).as_posix()
                )
            resume_artifact_binding = {
                "version": "factorforge_console_agent_resume_artifact_binding_v1",
                "attempt_id": validated_resume_artifacts.attempt_id,
                "agent_id": agent_result.agent_id,
                "agent_run_receipt_id": agent_receipt_snapshot_relative,
                "agent_run_receipt_sha256": agent_receipt_snapshot_sha256,
                "agent_run_receipt_source_id": (
                    validated_resume_artifacts.agent_run_receipt_id
                ),
                "resume_contract_sha256": dict(
                    validated_resume_artifacts.workspace_file_sha256
                )[resume_task.contract_relative],
                "mechanism_memo_artifact_id": resume_task.required_output_relative,
                "mechanism_memo_sha256": dict(
                    validated_resume_artifacts.workspace_file_sha256
                )[resume_task.required_output_relative],
                "prior_mechanism_memo_archive_id": (
                    prior_archive_snapshot_id
                ),
                "prior_mechanism_memo_archive_sha256": (
                    prior_archive_snapshot_sha256
                ),
            }

        source_receipt_id = str(formal_execution.get("receipt_id") or "")
        receipt_relative = Path(source_receipt_id)
        if receipt_relative.is_absolute() or ".." in receipt_relative.parts:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt identity is unsafe"
            )
        source_receipt_path = (state_root / receipt_relative).resolve(strict=True)
        try:
            source_receipt_path.relative_to(state_root)
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt escapes host state"
            ) from exc
        if source_receipt_path.is_symlink() or not source_receipt_path.is_file():
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt is unsafe"
            )
        formal_receipt_sha256 = str(formal_execution.get("receipt_sha256") or "")
        if not formal_receipt_sha256:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt hash mismatch"
            )
        formal_receipt_snapshot_path = (
            snapshot_root.parent / f"formal_receipt_{immutable_suffix}.json"
        )
        formal_receipt_snapshot_sha256 = _copy_immutable_regular_file(
            source_receipt_path,
            formal_receipt_snapshot_path,
            root=state_root,
            expected_sha256=formal_receipt_sha256,
            block_token=BLOCK_HOST_FORMAL_EXECUTION_FAILED,
            label="formal execution receipt",
        )
        receipt_path = formal_receipt_snapshot_path
        receipt_id = receipt_path.relative_to(state_root).as_posix()
        formal_receipt_sha256 = formal_receipt_snapshot_sha256
        formal_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected_receipt_identity = {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
        }
        if (
            formal_receipt.get("version")
            != "factorforge_console_host_formal_execution_v2"
            or any(
                formal_receipt.get(key) != value
                for key, value in expected_receipt_identity.items()
            )
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt identity mismatch"
            )
        formal_owned_artifact_transitions = (
            _validate_formal_owned_artifact_transitions(
                formal_receipt=formal_receipt,
                workspace_entries=workspace_entries,
                resume_task=resume_task,
                validation=validated_resume_artifacts,
            )
        )
        if (
            self.config.execution_mode == "container"
            and not self.config.auth_disabled
            and formal_receipt.get("readonly_data_lease_injected") is not True
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt lacks read-only data lease"
            )
        commands = formal_receipt.get("commands")
        if not isinstance(commands, list) or len(commands) != 2:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt command count invalid"
            )
        materialize_receipt, ultimate_receipt = commands
        materialize_argv = (
            materialize_receipt.get("argv")
            if isinstance(materialize_receipt, dict)
            and isinstance(materialize_receipt.get("argv"), list)
            else []
        )
        ultimate_argv = (
            ultimate_receipt.get("argv")
            if isinstance(ultimate_receipt, dict)
            and isinstance(ultimate_receipt.get("argv"), list)
            else []
        )
        engine_paths_valid = bool(
            len(materialize_argv) >= 2
            and len(ultimate_argv) >= 2
            and isinstance(materialize_receipt, dict)
            and isinstance(ultimate_receipt, dict)
            and _formal_receipt_engine_paths_valid(
                receipt=formal_receipt,
                source_repo=self.config.source_repo,
                materialize=materialize_receipt,
                materialize_argv=materialize_argv,
                ultimate=ultimate_receipt,
                ultimate_argv=ultimate_argv,
            )
        )
        if (
            not isinstance(materialize_receipt, dict)
            or materialize_receipt.get("name") != "materialize_web_research"
            or materialize_receipt.get("returncode") != 0
            or materialize_receipt.get("host_observed_process") is not True
            or materialize_receipt.get("cwd") != str(job.worktree_path)
            or len(materialize_argv) < 2
            or not engine_paths_valid
            or _argv_value(materialize_argv, "--workspace-root")
            != str(workspace_root)
            or _argv_value(materialize_argv, "--plan")
            != str(workspace_root / "identity" / "web_research_plan.json")
            or stable_json_hash(materialize_argv)
            != str(materialize_receipt.get("argv_sha256") or "")
            or not isinstance(ultimate_receipt, dict)
            or ultimate_receipt.get("name") != "run_factorforge_ultimate"
            or ultimate_receipt.get("host_observed_process") is not True
            or ultimate_receipt.get("cwd") != str(job.worktree_path)
            or len(ultimate_argv) < 2
            or _argv_value(ultimate_argv, "--report-id") != job.report_id
            or _argv_value(ultimate_argv, "--factor-id") != job.factor_id
            or _argv_value(ultimate_argv, "--research-id") != job.research_id
            or _argv_value(ultimate_argv, "--factorforge-root")
            != str(job.worktree_path)
            or _argv_value(ultimate_argv, "--factor-workspace") != str(workspace_root)
            or _argv_value(ultimate_argv, "--end-step") != "all"
            or stable_json_hash(ultimate_argv)
            != str(ultimate_receipt.get("argv_sha256") or "")
            or stable_json_hash(ultimate_argv)
            != str(formal_execution.get("ultimate_argv_sha256") or "")
            or ultimate_receipt.get("returncode")
            != formal_execution.get("ultimate_returncode")
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal Ultimate receipt invalid"
            )
        receipt_start_step = _argv_value(ultimate_argv, "--start-step")
        receipt_parent = formal_receipt.get("resume_parent")
        if formal_receipt.get("resume") is False:
            receipt_trust_valid = receipt_start_step == "3" and receipt_parent is None
        elif formal_receipt.get("resume") is True:
            receipt_trust_valid = (
                isinstance(receipt_parent, dict)
                and receipt_parent.get("start_step") == receipt_start_step
                and set(receipt_parent)
                == {
                    "start_step",
                    "ultimate_proof_sha256",
                    "attestation_id",
                    "attestation_sha256",
                    "receipt_id",
                    "receipt_sha256",
                }
            )
        else:
            receipt_trust_valid = False
        if not receipt_trust_valid:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt resume trust invalid"
            )
        receipt_conversation_binding = formal_receipt.get(
            "conversation_ledger_binding"
        )
        if (
            not isinstance(receipt_conversation_binding, dict)
            or receipt_conversation_binding.get("version")
            != HOST_CONVERSATION_LEDGER_BINDING_VERSION
            or stable_json_hash(receipt_conversation_binding)
            != stable_json_hash(
                formal_execution.get("conversation_ledger_binding")
            )
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal conversation ledger binding invalid"
            )
        binding_resume_trust = None
        if formal_receipt.get("resume") is True:
            binding_resume_trust = {
                "attestation_id": receipt_conversation_binding.get(
                    "parent_attestation_id"
                ),
                "attestation_sha256": receipt_conversation_binding.get(
                    "parent_attestation_sha256"
                ),
                "receipt_id": receipt_conversation_binding.get(
                    "parent_receipt_id"
                ),
                "receipt_sha256": receipt_conversation_binding.get(
                    "parent_receipt_sha256"
                ),
                "conversation_request_sha256": receipt_conversation_binding.get(
                    "parent_request_sha256"
                ),
                "conversation_ledger_checkpoint": receipt_conversation_binding.get(
                    "parent_checkpoint"
                ),
            }
        snapshot_conversation_binding = _validate_host_conversation_ledger_binding(
            workspace=snapshot_root,
            state_root=state_root,
            job=job,
            resume=formal_receipt.get("resume") is True,
            resume_trust=binding_resume_trust,
        )
        if stable_json_hash(snapshot_conversation_binding) != stable_json_hash(
            receipt_conversation_binding
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: attested conversation ledger changed"
            )
        wrapper_path = (
            snapshot_root
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{job.report_id}.json"
        )
        if (
            not wrapper_path.is_file()
            or wrapper_path.is_symlink()
            or formal_receipt.get("ultimate_proof_sha256") != _sha256(wrapper_path)
        ):
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal proof is not bound to receipt"
            )

        attestation_root = state_root / "attestations"
        attestation_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        attestation_root.chmod(0o700)
        immutable_root = attestation_root / job.job_id
        immutable_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        immutable_root.chmod(0o700)
        attestation_suffix = f"{_stamp(utc_now())}_{uuid.uuid4().hex[:12]}"
        evidence_tree_path = immutable_root / f"evidence_tree_{attestation_suffix}.json"
        evidence_tree_payload = {
            "version": "factorforge_console_workspace_evidence_tree_v1",
            **expected_receipt_identity,
            "entries": workspace_entries,
            "tree_sha256": stable_json_hash(workspace_entries),
            "recorded_at_utc": utc_now(),
        }
        _write_json_atomic(
            evidence_tree_path,
            evidence_tree_payload,
            root=state_root,
        )
        evidence_tree_id = evidence_tree_path.relative_to(state_root).as_posix()
        payload = {
            "version": "factorforge_console_host_execution_attestation_v2",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": job.base_commit,
            "host_observed_agent_process": (
                agent_result.agent_id != "factorforge-console-host"
            ),
            "host_observed_checkpoint_actor": (
                agent_result.agent_id == "factorforge-console-host"
            ),
            "host_observed_ultimate_process": True,
            "agent_returncode": agent_result.returncode,
            "agent_provider": agent_result.provider or "unknown",
            "agent_model": agent_result.model or "unknown",
            "researcher_memory_outcome": deepcopy(
                researcher_memory_outcome
            ),
            "current_formal_authority": deepcopy(
                current_authority_validation
            ),
            "agent_result_id": agent_receipt_snapshot_relative,
            "agent_result_sha256": agent_receipt_snapshot_sha256,
            "agent_result_source_id": agent_result_relative.as_posix(),
            "agent_resume_artifact_binding": resume_artifact_binding,
            "host_evidence_reader_invoked": True,
            "host_terminal_formal_validation_status": (
                "PASS"
                if summary.formal_proof_eligible
                and isinstance(current_authority_validation, dict)
                and current_authority_validation.get("status") == "PASS"
                else "NOT_APPLICABLE"
                if summary.execution_status.upper() in {
                    "PAUSED",
                    "ITERATING",
                    "REVIEW_REQUIRED",
                    "RUNNING",
                }
                else "BLOCK"
            ),
            "summary_sha256": stable_json_hash(summary.to_dict()),
            "workspace_manifest_sha256": _sha256(snapshot_root / "manifest.json"),
            "workspace_snapshot_id": snapshot_relative.as_posix(),
            "web_materialization": web_materialization,
            "formal_execution_receipt_id": receipt_id,
            "formal_execution_receipt_sha256": formal_receipt_sha256,
            "formal_execution_receipt_source_id": source_receipt_id,
            "formal_owned_artifact_transitions": (
                formal_owned_artifact_transitions
            ),
            "conversation_ledger_binding": deepcopy(
                receipt_conversation_binding
            ),
            "ultimate_argv_sha256": formal_execution["ultimate_argv_sha256"],
            "ultimate_returncode": formal_execution["ultimate_returncode"],
            "evidence_hashes": evidence_hashes,
            "workspace_evidence_tree_id": evidence_tree_id,
            "workspace_evidence_tree_sha256": _sha256(evidence_tree_path),
            "workspace_evidence_tree_root_sha256": stable_json_hash(workspace_entries),
            "attested_at_utc": utc_now(),
        }
        if _sha256(receipt_path) != formal_receipt_sha256:
            raise RuntimeError(
                f"{BLOCK_HOST_FORMAL_EXECUTION_FAILED}: formal receipt changed during attestation"
            )
        attestation_path = immutable_root / f"attestation_{attestation_suffix}.json"
        _write_json_atomic(
            attestation_path,
            payload,
            root=state_root,
        )
        attestation_id = attestation_path.relative_to(state_root).as_posix()
        pointer_path = attestation_root / f"{job.job_id}.current.json"
        _write_json_atomic(
            pointer_path,
            {
                "version": "factorforge_console_host_attestation_pointer_v1",
                "job_id": job.job_id,
                "attestation_id": attestation_id,
                "attestation_sha256": _sha256(attestation_path),
                "updated_at_utc": utc_now(),
            },
            root=state_root,
        )
        return attestation_id

    def _write_request_artifacts(
        self,
        job: ResearchJob,
        allocation: WorktreeAllocation,
        *,
        preserve_plan: bool = False,
        trusted_resume_start_step: str | None = None,
        trusted_resume_context: dict[str, Any] | None = None,
    ) -> None:
        workspace = allocation.workspace_path
        total_messages, all_messages = self.store.snapshot_messages(
            job.job_id,
            limit=CONVERSATION_LEDGER_MAX_MESSAGES,
        )
        if total_messages != len(all_messages):
            raise RuntimeError(
                f"{BLOCK_CONVERSATION_LEDGER_INVALID}: message history exceeds the ledger budget"
            )
        conversation_snapshot = _conversation_snapshot_from_messages(
            job.job_id,
            total_messages,
            all_messages[-40:],
        )
        existing_request: dict[str, Any] | None = None
        request_path = workspace / "identity" / "web_research_request.json"
        if preserve_plan:
            if not request_path.is_file() or request_path.is_symlink():
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: existing web research request is unsafe"
                )
            existing_request = json.loads(request_path.read_text(encoding="utf-8"))
            if not isinstance(existing_request, dict):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: existing web research request is invalid"
                )
        parent_attestation_id = ""
        parent_attestation_sha256 = ""
        if preserve_plan:
            if not isinstance(trusted_resume_context, dict):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: trusted parent attestation is missing"
                )
            parent_attestation_id = str(
                trusted_resume_context.get("attestation_id") or ""
            )
            parent_attestation_sha256 = str(
                trusted_resume_context.get("attestation_sha256") or ""
            )
        elif trusted_resume_context is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh request cannot carry resume trust"
            )
        uploaded_report = self._materialize_uploaded_report(
            job,
            workspace,
            preserve_plan=preserve_plan,
        )
        conversation_reference, planned_checkpoints = plan_conversation_checkpoints(
            workspace,
            job_id=job.job_id,
            messages=all_messages,
            existing_request=existing_request,
            parent_attestation_id=parent_attestation_id,
            parent_attestation_sha256=parent_attestation_sha256,
        )
        request_payload = {
            **job.request.to_dict(),
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "base_commit": allocation.base_commit,
            "allocation_manifest_sha256": _sha256(allocation.manifest_path),
            "submitted_at_utc": job.created_at_utc,
            "source_type": "natural_language_hypothesis",
            "source_materials": (
                [uploaded_report] if uploaded_report is not None else []
            ),
            "conversation_snapshot": conversation_snapshot,
            "conversation_snapshot_sha256": conversation_snapshot["sha256"],
            CONVERSATION_LEDGER_REFERENCE_FIELD: conversation_reference,
            "data_access": {
                "mode": "read_only",
                "catalog_count": len(self.config.data_catalogs),
            },
            "write_policy": {
                "factor_workspace_only": True,
                "repo_root_knowledge_write_allowed": False,
                "repo_root_data_write_allowed": False,
            },
        }
        source_path = workspace / "reports" / "user_hypothesis.md"
        guide_path = workspace / "identity" / "web_research_runtime.md"
        resume_restore_text: dict[Path, str | None] = {}
        if preserve_plan:
            for path in (source_path, request_path, guide_path):
                if path.is_symlink() or (path.exists() and not path.is_file()):
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: resume request artifact is unsafe"
                    )
                resume_restore_text[path] = (
                    path.read_text(encoding="utf-8") if path.is_file() else None
                )
        new_checkpoint_paths = [
            workspace / relative
            for relative, _payload in planned_checkpoints
            if not (workspace / relative).exists()
            and not (workspace / relative).is_symlink()
        ]
        source_lines = [
            f"# {job.request.title}",
            "",
            "- Source type: natural language hypothesis",
            f"- Factor ID: {job.factor_id}",
            f"- Research ID: {job.research_id}",
            f"- Report ID: {job.report_id}",
            f"- Universe: {job.request.universe}",
            f"- Sample: {job.request.sample_start} to {job.request.sample_end}",
            f"- Forward horizon: {job.request.forward_horizon}",
            f"- Transaction cost: {job.request.transaction_cost_bps:g} bps",
            "",
            "## Hypothesis",
            "",
            job.request.hypothesis,
        ]
        if uploaded_report is not None:
            source_lines.extend(
                [
                    "",
                    "## Uploaded report",
                    "",
                    f"- Original filename: {uploaded_report['original_filename']}",
                    f"- PDF: `{uploaded_report['workspace_pdf_path']}`",
                    f"- Page-aware text: `{uploaded_report['extracted_text_path']}`",
                    f"- SHA-256: `{uploaded_report['sha256']}`",
                    "- Attribution status: user supplied; external authenticity not asserted",
                ]
            )
        if job.request.source_url:
            source_lines.extend(["", "## User Reference", "", job.request.source_url])
        try:
            write_planned_checkpoints(workspace, planned_checkpoints)
            write_text_atomic(
                source_path,
                "\n".join(source_lines) + "\n",
                root=workspace,
            )
            write_web_research_packet(
                workspace=workspace,
                worktree=allocation.worktree_path,
                request=request_payload,
                catalogs=self.config.data_catalogs,
                catalog_admission=catalog_admission_projection(self.config),
                preserve_existing_plan=preserve_plan,
                trusted_resume_start_step=trusted_resume_start_step,
            )
            freeze_catalog = None
            if self.config.data_catalogs:
                candidate_catalog = self.config.data_catalogs[0]
                try:
                    candidate_payload = json.loads(
                        candidate_catalog.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError):
                    candidate_payload = None
                if (
                    isinstance(candidate_payload, dict)
                    and isinstance(candidate_payload.get("datasets"), list)
                    and candidate_payload["datasets"]
                ):
                    freeze_catalog = candidate_catalog
            if freeze_catalog is not None:
                materialize_host_job_frozen_catalog_snapshot(
                    state_root=self.config.state_root,
                    workspace_root=workspace,
                    approved_catalog_path=freeze_catalog,
                    job_id=job.job_id,
                )
            research_org_plan = workspace / "identity" / "research_organization_plan.json"
            if not preserve_plan or research_org_plan.is_file():
                write_research_organization_bundle(
                    workspace=workspace,
                    request=request_payload,
                    preserve_existing=preserve_plan,
                    researcher_memory_root=(
                        self.config.state_root / "researcher-memory"
                    ),
                    researcher_memory_installation_id=(
                        self.config.installation_id
                    ),
                )
        except Exception:
            if preserve_plan:
                try:
                    for path, prior_text in resume_restore_text.items():
                        if path.is_symlink() or (path.exists() and not path.is_file()):
                            raise RuntimeError("resume request rollback target is unsafe")
                        if prior_text is None:
                            path.unlink(missing_ok=True)
                        else:
                            write_text_atomic(path, prior_text, root=workspace)
                    for path in reversed(new_checkpoint_paths):
                        if path.is_symlink() or (path.exists() and not path.is_file()):
                            raise RuntimeError("resume checkpoint rollback target is unsafe")
                        path.unlink(missing_ok=True)
                except (OSError, RuntimeError, UnicodeError) as rollback_exc:
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: resume request rollback failed"
                    ) from rollback_exc
            raise

    def _materialize_uploaded_report(
        self,
        job: ResearchJob,
        workspace: Path,
        *,
        preserve_plan: bool,
    ) -> dict[str, Any] | None:
        attachments = self.store.list_attachments(job.job_id)
        if not attachments:
            return None
        if len(attachments) != 1:
            raise RuntimeError(
                f"{BLOCK_PDF_EXTRACTION_FAILED}: expected exactly one report attachment"
            )
        attachment = attachments[0]
        pdf_relative = "reports/uploaded_source_report.pdf"
        text_relative = "reports/uploaded_source_report_text.md"
        manifest_relative = "identity/uploaded_source_report_manifest.json"
        pdf_path = workspace / pdf_relative
        text_path = workspace / text_relative
        manifest_path = workspace / manifest_relative

        def read_existing_manifest(*, block_token: str) -> dict[str, Any]:
            for path in (pdf_path, text_path, manifest_path):
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError(
                        f"{block_token}: uploaded report artifact is unsafe"
                    )
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"{block_token}: uploaded report manifest is invalid"
                ) from exc
            if (
                not isinstance(payload, dict)
                or payload.get("contract_version")
                != "factorforge_console_uploaded_report_v1"
                or payload.get("attachment_id") != attachment.attachment_id
                or payload.get("original_filename") != attachment.original_filename
                or payload.get("media_type") != attachment.media_type
                or payload.get("size_bytes") != attachment.size_bytes
                or payload.get("sha256") != attachment.sha256
                or payload.get("workspace_pdf_path") != pdf_relative
                or payload.get("workspace_pdf_sha256") != attachment.sha256
                or _sha256(pdf_path) != attachment.sha256
                or pdf_path.stat().st_size != attachment.size_bytes
                or payload.get("extracted_text_path") != text_relative
                or payload.get("extracted_text_sha256") != _sha256(text_path)
                or payload.get("source_authenticity_verified") is not False
                or payload.get("source_attribution") != "user_supplied_unverified"
            ):
                raise RuntimeError(
                    f"{block_token}: uploaded report provenance changed"
                )
            return payload

        if preserve_plan:
            manifest = read_existing_manifest(block_token=BLOCK_RESUME_TRUST_INVALID)
        else:
            existing = [
                path.exists() or path.is_symlink()
                for path in (pdf_path, text_path, manifest_path)
            ]
            if any(existing):
                if not all(existing):
                    raise RuntimeError(
                        f"{BLOCK_PDF_EXTRACTION_FAILED}: partial report output exists"
                    )
                manifest = read_existing_manifest(
                    block_token=BLOCK_PDF_EXTRACTION_FAILED
                )
            else:
                data = self.store.read_attachment(attachment)
                write_bytes_atomic(pdf_path, data, root=workspace)
                extraction = extract_pdf_markdown_isolated(
                    pdf_path,
                    original_filename=attachment.original_filename,
                )
                write_text_atomic(
                    text_path,
                    str(extraction.pop("markdown")),
                    root=workspace,
                )
                manifest = {
                    "contract_version": "factorforge_console_uploaded_report_v1",
                    "attachment_id": attachment.attachment_id,
                    "original_filename": attachment.original_filename,
                    "media_type": attachment.media_type,
                    "size_bytes": attachment.size_bytes,
                    "sha256": attachment.sha256,
                    "workspace_pdf_path": pdf_relative,
                    "workspace_pdf_sha256": _sha256(pdf_path),
                    "extracted_text_path": text_relative,
                    "extracted_text_sha256": _sha256(text_path),
                    "extraction": extraction,
                    "source_authenticity_verified": False,
                    "source_attribution": "user_supplied_unverified",
                }
                _write_json_atomic(manifest_path, manifest, root=workspace)

        return {
            **manifest,
            "manifest_path": manifest_relative,
            "manifest_sha256": _sha256(manifest_path),
        }

    def _write_resume_authorization(self, job: ResearchJob, workspace: Path) -> None:
        payload = {
            "version": "factorforge_console_resume_authorization_v1",
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "authorization_type": "web_user_resume",
            "human_approval_recorded": False,
            "automated_policy_approval": False,
            "authorized_at_utc": utc_now(),
            "scope": "resume existing workspace; do not infer promotion or revision approval",
        }
        _write_json_atomic(
            workspace / "identity" / "web_resume_authorization.json",
            payload,
            root=workspace,
        )

    def _write_agent_resume_contract(
        self,
        job: ResearchJob,
        workspace: Path,
        *,
        resume_trust: dict[str, Any],
        attempt_id: str,
    ) -> AgentResumeTask:
        if not re.fullmatch(r"resume_[a-f0-9]{32}", attempt_id):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume attempt identity is invalid"
            )
        proof_relative = (
            "objects/runtime_context/"
            f"ultimate_run_report__{job.report_id}.json"
        )
        proof_path = workspace / proof_relative
        proof = _read_regular_workspace_json(workspace, proof_relative)
        if _sha256(proof_path) != str(resume_trust.get("ultimate_proof_sha256") or ""):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume contract proof hash mismatch"
            )
        pause = (
            proof.get("main_agent_mechanism_memo")
            if isinstance(proof.get("main_agent_mechanism_memo"), dict)
            else {}
        )
        pause_token = str(pause.get("token") or "")
        if (
            str(proof.get("status") or "").upper() != "PAUSED"
            or pause_token
            not in {
                MECHANISM_MEMO_INITIAL_TOKEN,
                MECHANISM_MEMO_REVISION_TOKEN,
            }
            or str(resume_trust.get("start_step") or "") != "6"
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: unsupported or unknown agent resume pause"
            )
        rim = "objects/research_iteration_master"
        status_relative = (
            f"{rim}/main_agent_mechanism_memo_status__{job.report_id}.json"
        )
        questionnaire_relative = (
            f"{rim}/main_agent_mechanism_questionnaire__{job.report_id}.json"
        )
        questionnaire_markdown_relative = (
            f"{rim}/main_agent_mechanism_questionnaire__{job.report_id}.md"
        )
        spec_relative = (
            "objects/factor_spec_master/"
            f"factor_spec_master__{job.report_id}.json"
        )
        case_relative = (
            "objects/factor_case_master/"
            f"factor_case_master__{job.report_id}.json"
        )
        evaluation_relative = (
            "objects/validation/"
            f"factor_evaluation__{job.report_id}.json"
        )
        status = _read_regular_workspace_json(workspace, status_relative)
        questionnaire = _read_regular_workspace_json(
            workspace, questionnaire_relative
        )
        _read_regular_workspace_file(
            workspace, questionnaire_markdown_relative
        )
        factor_spec = _read_regular_workspace_json(workspace, spec_relative)
        factor_case = _read_regular_workspace_json(workspace, case_relative)
        evaluation = _read_regular_workspace_json(workspace, evaluation_relative)
        mechanism_status = str(status.get("status") or "")
        expected_pause_token = (
            MECHANISM_MEMO_REVISION_TOKEN
            if mechanism_status == MECHANISM_MEMO_REVISION_STATUS
            else MECHANISM_MEMO_INITIAL_TOKEN
        )
        if (
            mechanism_status
            not in {
                MECHANISM_MEMO_INITIAL_STATUS,
                MECHANISM_MEMO_REVISION_STATUS,
            }
            or pause_token != expected_pause_token
            or status.get("token") != expected_pause_token
            or str(status.get("report_id") or "") != job.report_id
            or questionnaire.get("contract_version")
            != "factorforge_main_agent_mechanism_questionnaire_v1"
            or str(questionnaire.get("report_id") or "") != job.report_id
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: mechanism pause evidence is inconsistent"
            )
        questionnaire_ref = (
            status.get("questionnaire_ref")
            if isinstance(status.get("questionnaire_ref"), dict)
            else {}
        )
        expected_memo_ref = (
            status.get("expected_memo_ref")
            if isinstance(status.get("expected_memo_ref"), dict)
            else {}
        )
        expected_questionnaire_path = workspace / questionnaire_relative
        expected_questionnaire_markdown_path = (
            workspace / questionnaire_markdown_relative
        )
        expected_memo_path = (
            workspace
            / f"{rim}/main_agent_mechanism_memo__{job.report_id}.json"
        )
        expected_memo_markdown_path = (
            workspace
            / f"{rim}/main_agent_mechanism_memo__{job.report_id}.md"
        )
        revision_failures: list[str] = []
        revision_number = 0
        prior_output_sha256: dict[str, str] = {}
        prior_output_archive_id = ""
        if mechanism_status == MECHANISM_MEMO_REVISION_STATUS:
            raw_revision_failures = status.get("revision_failures")
            revision_number = status.get("revision_number")
            if (
                not isinstance(raw_revision_failures, list)
                or not raw_revision_failures
                or len(raw_revision_failures) > 16
                or any(
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item) > 2_000
                    for item in raw_revision_failures
                )
                or not isinstance(revision_number, int)
                or not 1 <= revision_number <= MAX_MECHANISM_MEMO_REVISIONS
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: mechanism revision failures are invalid"
                )
            revision_failures = [item.strip() for item in raw_revision_failures]
            prior_memo_path = _read_regular_workspace_file(
                workspace,
                expected_memo_path.relative_to(workspace).as_posix(),
            )
            prior_memo_sha256 = _sha256(prior_memo_path)
            if prior_memo_sha256 != str(status.get("prior_memo_sha256") or ""):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: prior mechanism memo hash mismatch"
                )
            prior_output_sha256[
                expected_memo_path.relative_to(workspace).as_posix()
            ] = prior_memo_sha256
            expected_prewrite_relative = (
                "objects/validation/"
                f"step6_prewrite_block__{job.report_id}.json"
            )
            prewrite_path = _read_regular_workspace_file(
                workspace,
                expected_prewrite_relative,
            )
            if (
                str(status.get("questionnaire_sha256") or "")
                != _sha256(expected_questionnaire_path)
                or str(status.get("prewrite_block_ref") or "")
                != expected_prewrite_relative
                or str(status.get("prewrite_block_sha256") or "")
                != _sha256(prewrite_path)
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: mechanism revision evidence binding mismatch"
                )
            prior_output_archive_id = (
                f"jobs/{job.job_id}/resume-history/{attempt_id}/prior_memo.json"
            )
        else:
            if expected_memo_path.exists() or expected_memo_path.is_symlink():
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: initial mechanism memo already exists"
                )
        if (
            expected_memo_markdown_path.exists()
            or expected_memo_markdown_path.is_symlink()
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: prior optional mechanism memo is unsupported"
            )
        if any(
            not _artifact_ref_path_matches(reference, key, expected)
            for reference, key, expected in (
                (questionnaire_ref, "json_path", expected_questionnaire_path),
                (
                    questionnaire_ref,
                    "markdown_path",
                    expected_questionnaire_markdown_path,
                ),
                (expected_memo_ref, "json_path", expected_memo_path),
                (
                    expected_memo_ref,
                    "markdown_path",
                    expected_memo_markdown_path,
                ),
            )
        ) or (
            questionnaire_ref.get("contract_version")
            != "factorforge_main_agent_mechanism_questionnaire_v1"
            or expected_memo_ref.get("contract_version") != CONTRACT_VERSION
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: mechanism pause refs are invalid"
            )
        questionnaire_formula_facts = (
            questionnaire.get("formula_facts")
            if isinstance(questionnaire.get("formula_facts"), dict)
            else {}
        )
        formula_facts = _mechanism_formula_facts(factor_spec)
        formula = str(formula_facts["formula"])
        fields = list(formula_facts["fields"])
        operators = list(formula_facts["operators"])
        questionnaire_formula = str(
            questionnaire_formula_facts.get("formula") or ""
        ).strip()
        questionnaire_fields = {
            str(item).strip()
            for item in questionnaire_formula_facts.get("fields") or []
            if str(item).strip()
        }
        questionnaire_operators = {
            _normalized_operator_name(item)
            for item in questionnaire_formula_facts.get("operators") or []
            if _normalized_operator_name(item)
        }
        if (
            questionnaire_formula != formula
            or not _questionnaire_fields_match_authoritative(
                questionnaire_fields,
                fields,
                factor_spec,
            )
            or questionnaire_operators != set(operators)
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: questionnaire formula facts disagree with the authoritative factor spec"
            )
        questionnaire_metric_facts = (
            questionnaire.get("metric_facts")
            if isinstance(questionnaire.get("metric_facts"), dict)
            else {}
        )
        metric_facts, metric_availability = _complete_mechanism_metric_facts(
            factor_case,
            evaluation,
        )
        memo_metric_facts = project_public_observed_metrics(metric_facts)
        memo_metric_conflict_keys = project_public_observed_metric_conflict_keys(
            metric_facts
        )
        if not memo_metric_facts:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: public mechanism metric facts are missing"
            )
        for key, value in questionnaire_metric_facts.items():
            if (
                key in metric_facts
                and not _questionnaire_metric_matches_projection(
                    metric_facts,
                    key,
                    value,
                )
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: questionnaire metric fact mismatch:{key}"
                )
        components = [
            {
                "component_id": "formula_root",
                "formula_subexpression": formula,
                "operators": operators,
                "observable_estimator": "",
                "economic_state": "",
                "mathematical_object": "",
                "expected_role": "",
                "metric_link": "",
            }
        ]
        profile = (
            formula_facts.get("profile_flags")
            if isinstance(formula_facts.get("profile_flags"), dict)
            else {}
        )
        operator_set = {item.lower() for item in operators}
        source_refs = {
            "factor_spec_master": spec_relative,
            "factor_case_master": case_relative,
            "evaluation_summary": evaluation_relative,
        }
        facts_relative = "identity/web_main_agent_mechanism_facts.json"
        facts_packet = {
            "version": "factorforge_console_mechanism_facts_v1",
            "attempt_id": attempt_id,
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "formula_facts": formula_facts,
            "evaluation_contract": _project_evaluation_contract(factor_spec),
            "observed_metrics": metric_facts,
            "metric_availability": metric_availability,
            "conversation_snapshot": (
                _read_regular_workspace_json(
                    workspace,
                    "identity/web_research_request.json",
                ).get("conversation_snapshot")
                or {}
            ),
            "revision_context": {
                "mode": (
                    "revision"
                    if mechanism_status == MECHANISM_MEMO_REVISION_STATUS
                    else "initial"
                ),
                "revision_number": revision_number,
                "failures": revision_failures,
            },
            "source_artifacts": {
                key: {
                    "artifact_id": relative,
                    "sha256": _sha256(
                        _read_regular_workspace_file(workspace, relative)
                    ),
                }
                for key, relative in source_refs.items()
            },
            "research_fields_are_intentionally_blank": True,
        }
        _write_json_atomic(
            workspace / facts_relative,
            facts_packet,
            root=workspace,
        )
        metric_signature_form = {
            "rank_ic": "",
            "long_side": "",
            "cost_adjusted": "",
            "monotonicity": "",
            "turnover": "",
        }
        answer_form = {
            "contract_version": CONTRACT_VERSION,
            "resume_attempt_id": attempt_id,
            "report_id": job.report_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "created_at_utc": utc_now(),
            "producer": "",
            "agent_authorship": {
                "authoring_mode": "",
                "agent_role": "",
                "answered_without_deterministic_template": False,
            },
            "source_refs": source_refs,
            "formula": formula,
            "formula_understanding": {
                "formula_features": {"fields": fields, "operators": operators}
            },
            "formula_component_map": components,
            "mechanism_qa": {field: "" for field in REQUIRED_QA_FIELDS},
            "economic_hypothesis": {
                "return_source_class": "",
                "payer_or_counterparty": "",
                "why_they_pay": "",
                "necessary_market_structure": "",
            },
            "math_hypothesis": {
                "selected_model_family": "",
                "why_this_model": "",
                "why_not_generic_template": "",
                "mathematical_object": "",
                "mechanism_equation_or_functional": "",
                "target_functional": "",
                "market_outcome_projection": "",
                "observation_mapping": "",
                "expected_metric_signature": dict(metric_signature_form),
            },
            "math_model_selection": {
                "model_family": "",
                "mechanism_equation_or_functional": "",
                "model_mutation": "",
            },
            "payer": {
                "payer_or_counterparty": "",
                "why_they_pay": "",
                "necessary_market_structure": "",
            },
            "mathematical_object_mapping": {
                "mathematical_object": "",
                "observation_mapping": "",
                "component_links": [],
            },
            "expected_metric_signature": dict(metric_signature_form),
            "falsification_tests": [],
            "evidence_comparison": {
                "observed_metrics": memo_metric_facts,
                "observed_metric_conflict_keys": memo_metric_conflict_keys,
                "mechanism_supported": "",
                "contradictions": [],
                "revision_implications": [],
                "kill_criteria_triggered": [],
            },
            "operator_claim_consistency": {
                "claims_correlation_or_covariance": False,
                "formula_has_correlation_or_covariance_operator": bool(
                    operator_set & {"correlation", "corr", "covariance", "cov"}
                ),
                "claims_dependence_without_operator_justification": False,
                "explicit_dependence_justification": "",
                "has_sign_or_threshold": bool(
                    operator_set & {"sign", "where"}
                ) or bool(profile.get("has_sign")),
                "sign_threshold_discussion_present": False,
                "has_volume_ratio": bool(profile.get("has_volume_ratio")),
                "volume_ratio_participation_discussion_present": False,
                "has_additive_rank_raw_ratio": bool(
                    profile.get("has_additive_score")
                    and profile.get("has_volume_ratio")
                ),
                "additive_scale_commensurability_discussion_present": False,
            },
            "council_questions": [],
            "canonical_write_permission": False,
            "execution_allowed_by_default": False,
        }
        answer_form_relative = "identity/web_main_agent_mechanism_answer_form.json"
        answer_form_path = workspace / answer_form_relative
        _write_json_atomic(answer_form_path, answer_form, root=workspace)
        memo_relative = (
            f"{rim}/main_agent_mechanism_memo__{job.report_id}.json"
        )
        optional_memo_relative = (
            f"{rim}/main_agent_mechanism_memo__{job.report_id}.md"
        )
        validation_command = (
            f"FACTORFORGE_ROOT={workspace} python3 -B "
            f"{workspace.parents[2] / 'skills' / 'factor-forge-step6' / 'scripts' / 'validate_main_agent_mechanism_memo.py'} "
            f"--report-id {job.report_id}"
        )
        read_only_inputs = (
            facts_relative,
            answer_form_relative,
            "identity/web_resume_authorization.json",
            "identity/web_research_request.json",
            "identity/factor_knowledge_summary.json",
        )
        protected_inputs = tuple(
            dict.fromkeys(
                (
                    proof_relative,
                    status_relative,
                    questionnaire_relative,
                    questionnaire_markdown_relative,
                    spec_relative,
                    case_relative,
                    evaluation_relative,
                    *read_only_inputs,
                )
            )
        )
        protected_input_hashes = {
            relative: _sha256(
                _read_regular_workspace_file(workspace, relative)
            )
            for relative in protected_inputs
        }
        contract_relative = "identity/web_agent_resume_contract.json"
        contract = {
            "version": "factorforge_console_resume_task_v1",
            "attempt_id": attempt_id,
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
            "resume_start_step": "6",
            "pause_kind": "main_agent_mechanism_memo",
            "pause_token": pause_token,
            "session_policy": "fresh_phase_agent",
            "ultimate_proof_sha256": _sha256(proof_path),
            "facts": facts_relative,
            "answer_form": answer_form_relative,
            "required_output": memo_relative,
            "optional_output": optional_memo_relative,
            "allowed_writes": [
                memo_relative,
                "identity/web_execution_ledger.md",
            ],
            "required_writes": [
                memo_relative,
                "identity/web_execution_ledger.md",
            ],
            "agent_read_only_inputs": list(read_only_inputs),
            "required_qa_fields": REQUIRED_QA_FIELDS,
            "allowed_model_families": sorted(BASELINE_MODEL_FAMILIES),
            "validation_command": validation_command,
            "input_sha256": {
                relative: _sha256(_read_regular_workspace_file(workspace, relative))
                for relative in read_only_inputs
            },
            "prior_output_sha256": prior_output_sha256,
            "prior_output_archive_id": prior_output_archive_id,
            "host_audit_tree_sha256": stable_json_hash(protected_input_hashes),
        }
        _write_json_atomic(
            workspace / contract_relative,
            contract,
            root=workspace,
        )
        return AgentResumeTask(
            version=str(contract["version"]),
            attempt_id=attempt_id,
            job_id=job.job_id,
            factor_id=job.factor_id,
            research_id=job.research_id,
            report_id=job.report_id,
            resume_start_step="6",
            pause_kind="main_agent_mechanism_memo",
            pause_token=pause_token,
            session_policy="fresh_phase_agent",
            ultimate_proof_sha256=str(contract["ultimate_proof_sha256"]),
            contract_relative=contract_relative,
            status_relative=status_relative,
            questionnaire_relative=questionnaire_relative,
            questionnaire_markdown_relative=questionnaire_markdown_relative,
            facts_relative=facts_relative,
            answer_form_relative=answer_form_relative,
            required_output_relative=memo_relative,
            optional_output_relative=optional_memo_relative,
            read_only_inputs=read_only_inputs,
            protected_inputs=protected_inputs,
            allowed_model_families=tuple(sorted(BASELINE_MODEL_FAMILIES)),
            validation_command=validation_command,
            prior_output_sha256=tuple(sorted(prior_output_sha256.items())),
            prior_output_archive_id=prior_output_archive_id,
        )

    def _validate_council_ingress_receipt(
        self,
        job: ResearchJob,
        workspace: Path,
        *,
        tasks: tuple[CouncilIngressTask, ...],
        agent_result: AgentRunResult,
    ) -> ValidatedAgentReceipt:
        state_root = self.config.state_root.resolve(strict=True)
        raw_path = Path(agent_result.result_path).expanduser()
        try:
            receipt_bytes, receipt_sha256, receipt_id = (
                _read_private_regular_file_once(
                    state_root,
                    raw_path,
                    block_token=BLOCK_RESUME_TRUST_INVALID,
                    label="Council ingress receipt",
                )
            )
            receipt_relative = Path(receipt_id)
            receipt_path = state_root / receipt_relative
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (
            FileNotFoundError,
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress receipt is invalid"
            ) from exc
        if (
            not receipt_path.is_file()
            or receipt_path.is_symlink()
            or receipt_relative.parts[:2] != ("jobs", job.job_id)
            or not isinstance(receipt, dict)
            or receipt.get("version") != "factorforge_console_council_ingress_v1"
            or receipt.get("job_id") != job.job_id
            or receipt.get("factor_id") != job.factor_id
            or receipt.get("research_id") != job.research_id
            or receipt.get("report_id") != job.report_id
            or receipt.get("agent_id") != agent_result.agent_id
            or receipt.get("session_key_sha256")
            != hashlib.sha256(agent_result.session_key.encode("utf-8")).hexdigest()
            or receipt.get("resume") is not True
            or receipt.get("research_base_commit") != job.base_commit
            or receipt.get("engine_commit") != self._expected_base_commit
            or receipt.get("independent_agent_count") != len(tasks)
            or receipt.get("required_agent_count") != len(tasks)
            or receipt.get("returncode") != 0
            or receipt.get("error_code") != ""
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress receipt binding is invalid"
            )
        runs = receipt.get("runs")
        if not isinstance(runs, list) or len(runs) != len(tasks):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress run set is invalid"
            )
        runs_by_task: dict[str, dict[str, Any]] = {}
        for run in runs:
            if not isinstance(run, dict):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress run is invalid"
                )
            task_id = str(run.get("task_id") or "")
            if not task_id or task_id in runs_by_task:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress run identity is invalid"
                )
            runs_by_task[task_id] = run
        for task in tasks:
            run = runs_by_task.get(task.task_id)
            result_path = _read_regular_workspace_file(
                workspace,
                task.expected_result_path,
            )
            if (
                run is None
                or run.get("agent_role") != task.agent_role
                or run.get("expected_agent_identifier")
                != task.expected_agent_identifier
                or run.get("expected_result_path") != task.expected_result_path
                or run.get("returncode") != 0
                or run.get("error_code") != ""
                or run.get("imported_result_sha256") != _sha256(result_path)
            ):
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress run binding is invalid"
                )
        return ValidatedAgentReceipt(
            receipt_id=receipt_relative.as_posix(),
            receipt_sha256=receipt_sha256,
        )

    def _validate_pre_oos_root_synthesis_receipt(
        self,
        job: ResearchJob,
        workspace: Path,
        *,
        task: PreOosRootSynthesisTask,
        agent_result: AgentRunResult,
    ) -> ValidatedAgentReceipt:
        state_root = self.config.state_root.resolve(strict=True)
        try:
            receipt_bytes, receipt_sha256, receipt_id = (
                _read_private_regular_file_once(
                    state_root,
                    Path(agent_result.result_path).expanduser(),
                    block_token=BLOCK_RESUME_TRUST_INVALID,
                    label="pre-OOS root synthesis receipt",
                )
            )
            receipt_relative = Path(receipt_id)
            receipt = json.loads(receipt_bytes.decode("utf-8"))
        except (
            FileNotFoundError,
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS root synthesis receipt is invalid"
            ) from exc
        expected_inputs = [
            {"path": relative, "sha256": digest}
            for relative, digest in task.read_only_input_sha256
        ]
        output_path = _read_regular_workspace_file(
            workspace,
            task.expected_output_relative,
        )
        if (
            receipt_relative.parts[:2] != ("jobs", job.job_id)
            or not isinstance(receipt, dict)
            or receipt.get("version")
            != "factorforge_console_pre_oos_root_synthesis_run_v1"
            or receipt.get("job_id") != job.job_id
            or receipt.get("factor_id") != job.factor_id
            or receipt.get("research_id") != job.research_id
            or receipt.get("report_id") != job.report_id
            or receipt.get("agent_id") != agent_result.agent_id
            or receipt.get("session_key_sha256")
            != hashlib.sha256(agent_result.session_key.encode("utf-8")).hexdigest()
            or receipt.get("resume") is not True
            or receipt.get("attempt_id") != task.attempt_id
            or receipt.get("research_base_commit") != job.base_commit
            or receipt.get("engine_commit") != self._expected_base_commit
            or receipt.get("trusted_proof_sha256")
            != task.trusted_proof_sha256
            or receipt.get("task_packet_path") != task.task_packet_relative
            or receipt.get("task_packet_sha256") != task.task_packet_sha256
            or receipt.get("read_only_inputs") != expected_inputs
            or receipt.get("expected_output_path")
            != task.expected_output_relative
            or receipt.get("imported_output_sha256") != _sha256(output_path)
            or receipt.get("returncode") != 0
            or receipt.get("error_code") != ""
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS root synthesis receipt binding is invalid"
            )
        if _sha256(
            _read_regular_workspace_file(workspace, task.task_packet_relative)
        ) != task.task_packet_sha256:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS root synthesis prompt changed"
            )
        for relative, digest in task.read_only_input_sha256:
            if _sha256(_read_regular_workspace_file(workspace, relative)) != digest:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS root synthesis evidence changed"
                )
        try:
            synthesis = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: pre-OOS root synthesis is invalid JSON"
            ) from exc
        _verifier, reasons = validate_pre_oos_root_synthesis(
            synthesis,
            workspace_root=workspace,
            report_id=job.report_id,
            synthesis_path=output_path,
        )
        if reasons:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: pre-OOS root synthesis failed formal validation:"
                + ",".join(str(reason) for reason in reasons[:12])
            )
        return ValidatedAgentReceipt(
            receipt_id=receipt_relative.as_posix(),
            receipt_sha256=receipt_sha256,
        )

    def _validate_agent_resume_artifact(
        self,
        job: ResearchJob,
        workspace: Path,
        *,
        resume_trust: dict[str, Any],
        resume_task: AgentResumeTask | None,
        agent_result: AgentRunResult,
    ) -> ValidatedAgentResumeArtifacts:
        if resume_task is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: typed resume task missing"
            )
        contract_relative = "identity/web_agent_resume_contract.json"
        contract = _read_regular_workspace_json(workspace, contract_relative)
        if any(
            contract.get(key) != expected
            for key, expected in {
                "version": "factorforge_console_resume_task_v1",
                "attempt_id": resume_task.attempt_id,
                "job_id": job.job_id,
                "factor_id": job.factor_id,
                "research_id": job.research_id,
                "report_id": job.report_id,
                "resume_start_step": str(resume_trust.get("start_step") or ""),
                "ultimate_proof_sha256": str(
                    resume_trust.get("ultimate_proof_sha256") or ""
                ),
                "pause_kind": "main_agent_mechanism_memo",
                "pause_token": resume_task.pause_token,
                "session_policy": "fresh_phase_agent",
                "facts": resume_task.facts_relative,
                "answer_form": resume_task.answer_form_relative,
                "required_output": resume_task.required_output_relative,
                "optional_output": resume_task.optional_output_relative,
            }.items()
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: resume contract identity mismatch"
            )
        contract_prior_outputs = contract.get("prior_output_sha256")
        expected_prior_outputs = dict(resume_task.prior_output_sha256)
        if (
            not isinstance(contract_prior_outputs, dict)
            or contract_prior_outputs != expected_prior_outputs
            or len(expected_prior_outputs) != len(resume_task.prior_output_sha256)
            or contract.get("prior_output_archive_id")
            != resume_task.prior_output_archive_id
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: prior resume output binding mismatch"
            )
        protected_input_hashes = {
            relative: _sha256(
                _read_regular_workspace_file(workspace, relative)
            )
            for relative in resume_task.protected_inputs
        }
        if contract.get("host_audit_tree_sha256") != stable_json_hash(
            protected_input_hashes
        ):
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: host audit input tree mismatch"
            )
        input_hashes = (
            contract.get("input_sha256")
            if isinstance(contract.get("input_sha256"), dict)
            else {}
        )
        for relative, expected_hash in input_hashes.items():
            input_path = _read_regular_workspace_file(workspace, str(relative))
            if _sha256(input_path) != str(expected_hash or ""):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: resume input hash mismatch:{relative}"
                )
        expected_output = (
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo__{job.report_id}.json"
        )
        if contract.get("required_output") != expected_output:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: mechanism memo output binding mismatch"
            )
        memo = _read_agent_resume_artifact_json(workspace, expected_output)
        answer_form_relative = str(contract.get("answer_form") or "")
        answer_form = _read_regular_workspace_json(
            workspace, answer_form_relative
        )
        spec_relative = (
            "objects/factor_spec_master/"
            f"factor_spec_master__{job.report_id}.json"
        )
        factor_spec = _read_regular_workspace_json(workspace, spec_relative)
        failures = validate_main_agent_mechanism_memo(memo, factor_spec)
        for field in RESUME_MEMO_IMMUTABLE_FIELDS:
            if stable_json_hash(memo.get(field)) != stable_json_hash(
                answer_form.get(field)
            ):
                failures.append(f"immutable_field_changed:{field}")
        if memo.get("resume_attempt_id") != resume_task.attempt_id:
            failures.append("resume_attempt_id_mismatch")
        if memo.get("research_id") != job.research_id:
            failures.append("research_id_mismatch")
        if memo.get("producer") != "current_main_agent":
            failures.append("producer_not_current_main_agent")
        authorship = (
            memo.get("agent_authorship")
            if isinstance(memo.get("agent_authorship"), dict)
            else {}
        )
        if authorship.get("authoring_mode") != "current_agent_freeform":
            failures.append("agent_authorship.authoring_mode_invalid")
        if authorship.get("agent_role") != "main_agent":
            failures.append("agent_authorship.agent_role_invalid")
        if authorship.get("answered_without_deterministic_template") is not True:
            failures.append(
                "agent_authorship.answered_without_deterministic_template_invalid"
            )

        state_root = self.config.state_root.resolve(strict=True)
        agent_result_path: Path | None = None
        agent_result_relative: Path | None = None
        agent_result_sha256 = ""
        agent_result_raw = Path(agent_result.result_path).expanduser()
        try:
            receipt_bytes, agent_result_sha256, receipt_id = (
                _read_private_regular_file_once(
                    state_root,
                    agent_result_raw,
                    block_token=BLOCK_AGENT_RESUME_ARTIFACT_INVALID,
                    label="agent run receipt",
                )
            )
            agent_result_relative = Path(receipt_id)
            agent_result_path = state_root / agent_result_relative
            agent_run = json.loads(receipt_bytes.decode("utf-8"))
        except (
            FileNotFoundError,
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            failures.append("agent_run_receipt_invalid")
        else:
            if (
                agent_result_relative.parts[:2] != ("jobs", job.job_id)
                or not isinstance(agent_run, dict)
                or agent_run.get("version") != "factorforge_console_agent_run_v1"
                or agent_run.get("job_id") != job.job_id
                or agent_run.get("factor_id") != job.factor_id
                or agent_run.get("research_id") != job.research_id
                or agent_run.get("report_id") != job.report_id
                or agent_run.get("agent_id") != agent_result.agent_id
                or agent_run.get("resume") is not True
                or agent_run.get("resume_attempt_id") != resume_task.attempt_id
                or agent_run.get("research_base_commit") != job.base_commit
                or agent_run.get("engine_commit") != self._expected_base_commit
                or agent_run.get("returncode") != 0
                or agent_run.get("session_key_sha256")
                != hashlib.sha256(
                    agent_result.session_key.encode("utf-8")
                ).hexdigest()
            ):
                failures.append("agent_run_receipt_binding_invalid")
        observed = (
            memo.get("evidence_comparison", {}).get("observed_metrics")
            if isinstance(memo.get("evidence_comparison"), dict)
            else None
        )
        expected_observed = (
            answer_form.get("evidence_comparison", {}).get("observed_metrics")
            if isinstance(answer_form.get("evidence_comparison"), dict)
            else None
        )
        if stable_json_hash(observed) != stable_json_hash(expected_observed):
            failures.append("immutable_field_changed:evidence_comparison.observed_metrics")
        observed_conflicts = (
            memo.get("evidence_comparison", {}).get(
                "observed_metric_conflict_keys"
            )
            if isinstance(memo.get("evidence_comparison"), dict)
            else None
        )
        expected_observed_conflicts = (
            answer_form.get("evidence_comparison", {}).get(
                "observed_metric_conflict_keys"
            )
            if isinstance(answer_form.get("evidence_comparison"), dict)
            else None
        )
        if stable_json_hash(observed_conflicts) != stable_json_hash(
            expected_observed_conflicts
        ):
            failures.append(
                "immutable_field_changed:"
                "evidence_comparison.observed_metric_conflict_keys"
            )
        memo_components = memo.get("formula_component_map") or []
        form_components = answer_form.get("formula_component_map") or []
        if (
            not isinstance(memo_components, list)
            or not isinstance(form_components, list)
            or len(memo_components) != len(form_components)
        ):
            failures.append("immutable_field_changed:formula_component_map.required_components")
        else:
            for index, (memo_component, form_component) in enumerate(
                zip(memo_components, form_components)
            ):
                for field in RESUME_MEMO_COMPONENT_IDENTITY_FIELDS:
                    memo_value = memo_component.get(field) if isinstance(memo_component, dict) else None
                    form_value = form_component.get(field) if isinstance(form_component, dict) else None
                    if stable_json_hash(memo_value) != stable_json_hash(form_value):
                        failures.append(
                            f"immutable_field_changed:formula_component_map.{index}.{field}"
                        )
        memo_operator = (
            memo.get("operator_claim_consistency")
            if isinstance(memo.get("operator_claim_consistency"), dict)
            else {}
        )
        form_operator = (
            answer_form.get("operator_claim_consistency")
            if isinstance(answer_form.get("operator_claim_consistency"), dict)
            else {}
        )
        for field in RESUME_MEMO_OPERATOR_FLAG_FIELDS:
            if memo_operator.get(field) != form_operator.get(field):
                failures.append(
                    f"immutable_field_changed:operator_claim_consistency.{field}"
                )
        if failures:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: "
                + ",".join(dict.fromkeys(failures))
            )
        if agent_result_path is None or agent_result_relative is None:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: agent run receipt was not validated"
            )
        prior_output_archive_sha256 = ""
        if resume_task.prior_output_archive_id:
            prior_output_archive_path = _read_private_resume_archive(
                self.config.state_root,
                resume_task,
            )
            prior_output_archive_sha256 = _sha256(prior_output_archive_path)
            if prior_output_archive_sha256 != expected_prior_outputs.get(
                resume_task.required_output_relative
            ):
                raise RuntimeError(
                    f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: prior memo archive hash mismatch"
                )
        elif expected_prior_outputs:
            raise RuntimeError(
                f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: prior memo archive is missing"
            )
        validated_workspace_relatives = tuple(
            sorted(
                set(resume_task.protected_inputs)
                | {
                    contract_relative,
                    expected_output,
                    answer_form_relative,
                    spec_relative,
                }
            )
        )
        return ValidatedAgentResumeArtifacts(
            attempt_id=resume_task.attempt_id,
            workspace_file_sha256=tuple(
                (
                    relative,
                    _sha256(_read_regular_workspace_file(workspace, relative)),
                )
                for relative in validated_workspace_relatives
            ),
            agent_run_receipt_id=agent_result_relative.as_posix(),
            agent_run_receipt_sha256=agent_result_sha256,
            prior_output_archive_id=resume_task.prior_output_archive_id,
            prior_output_archive_sha256=prior_output_archive_sha256,
        )


def _require_validated_resume_artifacts_unchanged(
    workspace: Path,
    *,
    state_root: Path,
    resume_task: AgentResumeTask | None,
    validation: ValidatedAgentResumeArtifacts,
    allowed_workspace_changes: frozenset[str] = frozenset(),
) -> None:
    if (
        resume_task is None
        or validation.attempt_id != resume_task.attempt_id
        or not validation.workspace_file_sha256
        or not validation.agent_run_receipt_id
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated resume artifact identity is incomplete"
        )
    expected_workspace_hashes = dict(validation.workspace_file_sha256)
    if len(expected_workspace_hashes) != len(validation.workspace_file_sha256):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated resume artifact paths are duplicated"
        )
    required_paths = {
        resume_task.contract_relative,
        resume_task.required_output_relative,
    }
    if not required_paths.issubset(expected_workspace_hashes):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated resume artifact set is incomplete"
        )
    if not allowed_workspace_changes.issubset(expected_workspace_hashes):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: formal workspace mutation allowance is invalid"
        )
    for relative, expected_sha256 in expected_workspace_hashes.items():
        if relative in allowed_workspace_changes:
            continue
        path = _read_regular_workspace_file(workspace, relative)
        if not expected_sha256 or _sha256(path) != expected_sha256:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: validated resume artifact changed:{relative}"
            )

    root = state_root.resolve(strict=True)
    receipt_relative = Path(validation.agent_run_receipt_id)
    if (
        receipt_relative.is_absolute()
        or ".." in receipt_relative.parts
        or receipt_relative.parts[:2] != ("jobs", resume_task.job_id)
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated agent receipt identity is unsafe"
        )
    receipt_path = root / receipt_relative
    try:
        resolved_receipt = receipt_path.resolve(strict=True)
        resolved_receipt.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated agent receipt is unavailable"
        ) from exc
    if (
        receipt_path.is_symlink()
        or not resolved_receipt.is_file()
        or not validation.agent_run_receipt_sha256
        or _sha256(resolved_receipt) != validation.agent_run_receipt_sha256
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated agent receipt changed"
        )
    if validation.prior_output_archive_id != resume_task.prior_output_archive_id:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior memo archive identity changed"
        )
    if validation.prior_output_archive_id:
        archive_path = _read_private_resume_archive(state_root, resume_task)
        if (
            not validation.prior_output_archive_sha256
            or _sha256(archive_path)
            != validation.prior_output_archive_sha256
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: prior memo archive changed"
            )
    elif validation.prior_output_archive_sha256:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior memo archive binding is invalid"
        )


def _formal_owned_resume_relatives(
    resume_task: AgentResumeTask | None,
) -> frozenset[str]:
    if resume_task is None:
        return frozenset()
    return frozenset(
        {
            resume_task.status_relative,
            resume_task.questionnaire_relative,
            resume_task.questionnaire_markdown_relative,
            (
                "objects/runtime_context/"
                f"ultimate_run_report__{resume_task.report_id}.json"
            ),
        }
    )


def _validate_formal_owned_artifact_transitions(
    *,
    formal_receipt: dict[str, Any],
    workspace_entries: dict[str, str],
    resume_task: AgentResumeTask | None,
    validation: ValidatedAgentResumeArtifacts | None,
) -> dict[str, dict[str, Any]]:
    raw = formal_receipt.get("formal_owned_artifact_transitions")
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation receipt is invalid"
        )
    if resume_task is None and validation is None:
        if raw:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: non-mechanism receipt carries formal mutation claims"
            )
        return {}
    if resume_task is None or validation is None:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation attestation identity is incomplete"
        )

    expected_relatives = _formal_owned_resume_relatives(resume_task)
    if set(raw) != expected_relatives:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation receipt path set is invalid"
        )
    validated_hashes = dict(validation.workspace_file_sha256)
    if not expected_relatives.issubset(validated_hashes):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation validation baseline is incomplete"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for relative in sorted(expected_relatives):
        transition = raw.get(relative)
        before_sha256 = validated_hashes[relative]
        after_sha256 = workspace_entries.get(relative)
        if (
            not isinstance(transition, dict)
            or set(transition)
            != {"before_sha256", "after_sha256", "changed", "producer"}
            or transition.get("before_sha256") != before_sha256
            or transition.get("after_sha256") != after_sha256
            or re.fullmatch(r"[0-9a-f]{64}", before_sha256) is None
            or not isinstance(after_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", after_sha256) is None
            or not isinstance(transition.get("changed"), bool)
            or transition.get("changed") != (after_sha256 != before_sha256)
            or transition.get("producer") != "host_formal_pipeline"
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: formal mutation receipt hash mismatch:{relative}"
            )
        normalized[relative] = {
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "changed": after_sha256 != before_sha256,
            "producer": "host_formal_pipeline",
        }
    return normalized


def _read_private_resume_archive(
    state_root: Path,
    resume_task: AgentResumeTask,
) -> Path:
    expected_id = (
        f"jobs/{resume_task.job_id}/resume-history/"
        f"{resume_task.attempt_id}/prior_memo.json"
    )
    if resume_task.prior_output_archive_id != expected_id:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior memo archive identity is unsafe"
        )
    root = state_root.resolve(strict=True)
    archive = root / expected_id
    try:
        resolved = archive.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior memo archive is unavailable"
        ) from exc
    metadata = resolved.stat()
    if (
        archive.is_symlink()
        or not resolved.is_file()
        or metadata.st_nlink != 1
        or metadata.st_size > 2 * 1024 * 1024
        or metadata.st_mode & 0o022
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior memo archive is unsafe"
        )
    return resolved


def _normalized_operator_name(value: Any) -> str:
    return str(value or "").strip().lower().removesuffix("()")


def _questionnaire_fields_match_authoritative(
    questionnaire_fields: set[str],
    authoritative_fields: list[str],
    factor_spec: dict[str, Any],
) -> bool:
    canonical = (
        factor_spec.get("canonical_spec")
        if isinstance(factor_spec.get("canonical_spec"), dict)
        else factor_spec
    )
    formula_ir = (
        canonical.get("formula_ir")
        if isinstance(canonical.get("formula_ir"), dict)
        else {}
    )
    raw_aliases = (
        formula_ir.get("field_aliases")
        if isinstance(formula_ir.get("field_aliases"), dict)
        else {}
    )
    required = {
        str(item).strip().lower()
        for item in authoritative_fields
        if str(item).strip()
    }
    alias_targets: dict[str, set[str]] = {}
    for field in required:
        aliases = raw_aliases.get(field)
        candidates = [field, *(aliases if isinstance(aliases, list) else [])]
        for candidate in candidates:
            alias = str(candidate).strip().lower()
            if alias:
                alias_targets.setdefault(alias, set()).add(field)

    projected: set[str] = set()
    for raw_field in questionnaire_fields:
        alias = str(raw_field).strip().lower()
        targets = alias_targets.get(alias, set())
        if len(targets) != 1:
            return False
        projected.update(targets)
    return projected == required


def _mechanism_formula_facts(factor_spec: dict[str, Any]) -> dict[str, Any]:
    canonical = (
        factor_spec.get("canonical_spec")
        if isinstance(factor_spec.get("canonical_spec"), dict)
        else factor_spec
    )
    formula_ir = (
        canonical.get("formula_ir")
        if isinstance(canonical.get("formula_ir"), dict)
        else {}
    )
    formula = str(
        canonical.get("formula_text")
        or formula_ir.get("formula_text")
        or ""
    ).strip()
    fields = sorted(
        {
            str(item).strip()
            for item in (
                formula_ir.get("required_fields")
                or canonical.get("required_fields")
                or canonical.get("required_inputs")
                or []
            )
            if str(item).strip()
        }
    )
    operators = sorted(
        {
            _normalized_operator_name(item)
            for item in (
                formula_ir.get("operator_set")
                or canonical.get("operator_set")
                or canonical.get("operators")
                or []
            )
            if _normalized_operator_name(item)
        }
    )
    if not formula or not fields or not operators:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: authoritative formula syntax is incomplete"
        )
    lower_fields = {item.lower() for item in fields}
    operator_set = set(operators)
    compact_formula = re.sub(r"\s+", "", formula.lower())
    has_volume = bool(lower_fields & {"volume", "vol"})
    profile_flags = {
        "has_sign": "sign" in operator_set,
        "has_open_close_position": {"open", "close"}.issubset(lower_fields),
        "has_volume_ratio": bool(
            has_volume
            and "divide" in operator_set
            and ("sum" in operator_set or "sum(" in compact_formula)
        ),
        "has_additive_score": bool(
            "plus" in operator_set or "+" in formula
        ),
    }
    return {
        "formula": formula,
        "formula_ir_sha256": str(formula_ir.get("formula_hash") or ""),
        "fields": fields,
        "operators": operators,
        "profile_flags": profile_flags,
    }


def _metric_fact_value(value: Any) -> Any | None:
    budget = {"nodes": 0, "text_bytes": 0}

    def project(item: Any, *, depth: int) -> Any | None:
        if depth > 8:
            raise ValueError("metric fact nesting exceeds limit")
        budget["nodes"] += 1
        if budget["nodes"] > 2048:
            raise ValueError("metric fact node count exceeds limit")
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int):
            if item.bit_length() > 1024:
                raise ValueError("metric fact integer exceeds limit")
            return item
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("metric fact number must be finite")
            return item
        if isinstance(item, str):
            encoded_size = len(item.encode("utf-8"))
            if encoded_size > 4096:
                raise ValueError("metric fact string exceeds limit")
            budget["text_bytes"] += encoded_size
            if budget["text_bytes"] > 128 * 1024:
                raise ValueError("metric fact text budget exceeds limit")
            return item
        if isinstance(item, list):
            if len(item) > 100:
                raise ValueError("metric fact list width exceeds limit")
            return [project(child, depth=depth + 1) for child in item]
        if isinstance(item, dict):
            if len(item) > 100:
                raise ValueError("metric fact mapping width exceeds limit")
            projected_dict: dict[str, Any] = {}
            for raw_key, child in item.items():
                key = str(raw_key)
                key_size = len(key.encode("utf-8"))
                if key_size > 256:
                    raise ValueError("metric fact key exceeds limit")
                budget["text_bytes"] += key_size
                if budget["text_bytes"] > 128 * 1024:
                    raise ValueError("metric fact text budget exceeds limit")
                if key in projected_dict:
                    raise ValueError("metric fact keys collide after normalization")
                projected_dict[key] = project(child, depth=depth + 1)
            return projected_dict
        raise ValueError("metric fact value type is unsupported")

    projected = project(value, depth=0)
    try:
        serialized_size = len(
            json.dumps(
                projected,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("metric fact cannot be serialized") from exc
    if serialized_size > 256 * 1024:
        raise ValueError("metric fact serialized size exceeds limit")
    return projected


def _questionnaire_metric_matches_projection(
    metric_facts: dict[str, Any],
    key: str,
    questionnaire_value: Any,
) -> bool:
    expected_hash = stable_json_hash(questionnaire_value)
    conflicts = metric_facts.get("backend_metric_conflicts")
    conflict = conflicts.get(key) if isinstance(conflicts, dict) else None
    if isinstance(conflict, dict):
        observations = conflict.get("backend_observations")
        if not isinstance(observations, list):
            return False
        return any(
            isinstance(observation, dict)
            and stable_json_hash(observation.get("value")) == expected_hash
            for observation in observations
        )
    return stable_json_hash(metric_facts.get(key)) == expected_hash


def _project_metric_mapping(
    target: dict[str, Any],
    candidate: Any,
) -> None:
    if not isinstance(candidate, dict):
        return
    if len(candidate) > 512:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: metric mapping width exceeds limit"
        )
    for raw_key, raw_value in candidate.items():
        key = str(raw_key)
        if (
            key not in MECHANISM_METRIC_KEYS
            and not key.startswith(MECHANISM_METRIC_PREFIXES)
        ):
            continue
        try:
            value = _metric_fact_value(raw_value)
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: metric fact projection rejected bounds"
            ) from exc
        target[key] = value


def _complete_mechanism_metric_facts(
    factor_case: dict[str, Any],
    evaluation: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics: dict[str, Any] = {}
    for candidate in (
        factor_case.get("headline_metrics"),
        factor_case.get("metrics"),
        evaluation.get("headline_metrics"),
        evaluation.get("key_metrics"),
        evaluation.get("metrics"),
    ):
        _project_metric_mapping(metrics, candidate)
    backends: list[dict[str, Any]] = []
    backend_observations: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(evaluation.get("backend_summary") or []):
        if not isinstance(item, dict):
            continue
        try:
            raw_backend_metrics = _metric_fact_value(item.get("key_metrics"))
        except ValueError as exc:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: backend metric facts rejected bounds"
            ) from exc
        backend_metrics = (
            raw_backend_metrics
            if isinstance(raw_backend_metrics, dict)
            else {}
        )
        promoted_backend_metrics: dict[str, Any] = {}
        _project_metric_mapping(
            promoted_backend_metrics,
            item.get("key_metrics"),
        )
        backend_name = str(
            item.get("backend")
            or item.get("name")
            or item.get("backend_id")
            or f"backend_{index}"
        )
        backend_status = str(item.get("status") or item.get("verdict") or "")
        backend_record = {
            "index": index,
            "backend": backend_name,
            "status": backend_status,
            "metric_keys": sorted(backend_metrics),
            "promoted_metric_keys": sorted(promoted_backend_metrics),
            "metrics": backend_metrics,
        }
        backends.append(backend_record)
        for key, value in promoted_backend_metrics.items():
            backend_observations.setdefault(key, []).append(
                {
                    "index": index,
                    "backend": backend_name,
                    "status": backend_status,
                    "value": value,
                }
            )
    coverage = (
        evaluation.get("coverage_summary")
        if isinstance(evaluation.get("coverage_summary"), dict)
        else {}
    )
    _project_metric_mapping(metrics, coverage)
    backend_conflicts: dict[str, Any] = {}
    for key, observations in sorted(backend_observations.items()):
        unique_values = {
            stable_json_hash(observation["value"])
            for observation in observations
        }
        if key in metrics:
            canonical_hash = stable_json_hash(metrics[key])
            if unique_values != {canonical_hash}:
                conflict = {
                    "status": "backend_conflict",
                    "reported_aggregate": metrics[key],
                    "backend_observations": observations,
                }
                metrics[key] = conflict
                backend_conflicts[key] = conflict
        elif len(unique_values) == 1:
            metrics[key] = observations[0]["value"]
        else:
            conflict = {
                "status": "backend_conflict",
                "backend_observations": observations,
            }
            metrics[key] = conflict
            backend_conflicts[key] = conflict
    for key in ("row_count", "date_count", "ticker_count", "period_count"):
        if key in coverage:
            metrics[f"coverage_{key}"] = coverage[key]
    long_side_review = (
        factor_case.get("long_side_review")
        if isinstance(factor_case.get("long_side_review"), dict)
        else {}
    )
    if "monotonicity_diagnostic" in long_side_review:
        metrics["monotonicity_diagnostic"] = long_side_review[
            "monotonicity_diagnostic"
        ]
    metrics["backend_metrics"] = backends
    if backend_conflicts:
        metrics["backend_metric_conflicts"] = backend_conflicts
    required_core = (
        "rank_ic_mean",
        "rank_ic_ir",
        "pearson_ic_mean",
        "pearson_ic_ir",
        "long_side_annual_volatility",
        "long_side_sharpe",
        "long_side_max_drawdown",
        "long_side_recovery_days",
        "long_side_turnover_mean_daily",
        "trading_cogs_annual",
        "cost_adjusted_annual_return",
        "cost_adjusted_long_side_sharpe",
        "cost_adjusted_long_side_max_drawdown",
        "cost_adjusted_long_side_recovery_days",
    )
    availability = {
        "required_core_metric_keys": list(required_core),
        "present_core_metric_keys": [key for key in required_core if key in metrics],
        "missing_core_metric_keys": [key for key in required_core if key not in metrics],
        "fama_macbeth_present": any(
            key == "fama_macbeth" or key.startswith("fama_macbeth_")
            for key in metrics
        ),
        "monotonicity_present": any(
            "monotonic" in key or key.startswith(("group_", "decile_", "quintile_"))
            for key in metrics
        ),
        "backends": backends,
    }
    substantive_metric_keys = {
        key
        for key in metrics
        if key not in {"backend_metrics", "backend_metric_conflicts"}
    }
    if not substantive_metric_keys:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: validated Step4/5 metric facts are missing"
        )
    return metrics, availability


def _project_evaluation_contract(factor_spec: dict[str, Any]) -> dict[str, Any]:
    canonical = (
        factor_spec.get("canonical_spec")
        if isinstance(factor_spec.get("canonical_spec"), dict)
        else factor_spec
    )
    evaluation = (
        canonical.get("evaluation_contract")
        if isinstance(canonical.get("evaluation_contract"), dict)
        else {}
    )
    allowed = (
        "version",
        "forward_horizon",
        "signal_timestamp_policy",
        "position_entry_policy",
        "position_exit_policy",
        "payoff_label_expression",
        "rebalance_frequency",
        "transaction_cost_bps",
        "cost_model_id",
        "cost_formula",
        "label_policy",
        "availability_lags",
        "missing_data_policy",
    )
    return {
        key: evaluation[key]
        for key in allowed
        if key in evaluation
    }


def _workspace_file_snapshot(workspace: Path) -> dict[str, str]:
    root = workspace.resolve(strict=True)
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = f"symlink:{os.readlink(path)}"
        elif path.is_file():
            snapshot[relative] = f"file:{_sha256(path)}"
    return snapshot


def _capture_resume_restore_state(
    workspace: Path,
    *,
    report_id: str,
    expected_absent_paths: tuple[str, ...] = (),
    managed_directories: tuple[str, ...] = (),
) -> ResumeRestoreState:
    root = workspace.resolve(strict=True)
    state: dict[str, str | None] = {}
    identity = root / "identity"
    if identity.is_symlink() or not identity.is_dir():
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume identity directory is unsafe"
        )
    for path in sorted(identity.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume identity contains a symlink"
            )
        if path.is_file():
            state[relative] = path.read_text(encoding="utf-8")
        elif not path.is_dir():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume identity contains an unsafe entry"
            )
    for relative in (
        "reports/user_hypothesis.md",
        (
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo__{report_id}.json"
        ),
        (
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo__{report_id}.md"
        ),
    ):
        path = root / relative
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume restore target is a symlink"
            )
        state[relative] = path.read_text(encoding="utf-8") if path.is_file() else None
    for relative in expected_absent_paths:
        path = _safe_resume_restore_target(root, relative)
        if path.exists() or path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: expected resume output already exists"
            )
        state[relative] = None

    initially_absent_directories: list[str] = []
    for relative in managed_directories:
        path = _safe_resume_restore_target(root, relative)
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: managed resume directory is a symlink"
            )
        if path.exists():
            if not path.is_dir():
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: managed resume directory is unsafe"
                )
        else:
            initially_absent_directories.append(relative)
    return ResumeRestoreState(
        files=state,
        initially_absent_directories=tuple(initially_absent_directories),
    )


def _restore_resume_workspace(
    workspace: Path,
    state: ResumeRestoreState,
    *,
    report_id: str,
    expected_tree_sha256: str,
) -> None:
    root = workspace.resolve(strict=True)
    identity = root / "identity"
    if identity.is_symlink() or not identity.is_dir():
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume identity directory is unsafe"
        )
    baseline_identity = {
        relative for relative in state.files if relative.startswith("identity/")
    }
    for path in sorted(identity.rglob("*"), reverse=True):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: failed resume created an unsafe identity entry"
            )
        if path.is_file() and relative not in baseline_identity:
            path.unlink()
    expected_memo_paths = {
        (
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo__{report_id}.json"
        ),
        (
            "objects/research_iteration_master/"
            f"main_agent_mechanism_memo__{report_id}.md"
        ),
    }
    if not expected_memo_paths.issubset(state.files):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume restore state is incomplete"
        )
    for relative, content in state.files.items():
        path = _safe_resume_restore_target(root, relative)
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume restore target is a symlink"
            )
        if content is None:
            if path.exists():
                if not path.is_file():
                    raise RuntimeError(
                        f"{BLOCK_RESUME_TRUST_INVALID}: resume restore target is not a file"
                    )
                path.unlink()
        else:
            write_text_atomic(path, content, root=root)
    for relative in sorted(
        state.initially_absent_directories,
        key=lambda value: len(Path(value).parts),
        reverse=True,
    ):
        path = _safe_resume_restore_target(root, relative)
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: managed resume directory is unsafe"
            )
        if path.exists():
            try:
                path.rmdir()
            except OSError as exc:
                raise RuntimeError(
                    f"{BLOCK_RESUME_TRUST_INVALID}: managed resume directory is not empty"
                ) from exc
    restored_tree = _workspace_evidence_tree(root)
    if not expected_tree_sha256 or stable_json_hash(restored_tree) != expected_tree_sha256:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: restored workspace evidence tree mismatch"
        )


def _safe_resume_restore_target(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or ".." in relative_path.parts
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume restore target is unsafe"
        )
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: resume restore target is a symlink"
            )
    return root / relative_path


def _read_regular_workspace_file(workspace: Path, relative: str) -> Path:
    root = workspace.resolve(strict=True)
    path = workspace / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume input is missing or outside workspace: {relative}"
        ) from exc
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume input is not a regular file: {relative}"
        )
    return path


def _artifact_ref_path_matches(
    reference: dict[str, Any],
    key: str,
    expected: Path,
) -> bool:
    value = str(reference.get(key) or "")
    if not value:
        return False
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = expected.parents[2] / candidate
    try:
        return candidate.resolve(strict=False) == expected.resolve(strict=False)
    except (OSError, RuntimeError):
        return False


def _read_regular_workspace_json(workspace: Path, relative: str) -> dict[str, Any]:
    path = _read_regular_workspace_file(workspace, relative)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume input is invalid JSON: {relative}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: resume input must be a JSON object: {relative}"
        )
    return payload


def _read_agent_resume_artifact_json(
    workspace: Path,
    relative: str,
) -> dict[str, Any]:
    path = _read_regular_workspace_file(workspace, relative)
    try:
        with path.open("rb") as handle:
            raw = handle.read(RESUME_MEMO_MAX_BYTES + 1)
    except OSError as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: invalid JSON:{relative}"
        ) from exc
    if len(raw) > RESUME_MEMO_MAX_BYTES:
        raise RuntimeError(
            f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: file too large:{relative}"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: invalid JSON:{relative}"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{BLOCK_AGENT_RESUME_ARTIFACT_INVALID}: JSON root must be an object:{relative}"
        )
    return payload


def _result_without_resume_attestation(job: ResearchJob) -> dict[str, Any]:
    result = dict(job.result) if isinstance(job.result, dict) else {}
    result.pop("host_attestation_id", None)
    return result


def _workspace_evidence_tree(workspace: Path) -> dict[str, str]:
    root = workspace.resolve(strict=True)
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: workspace evidence tree contains symlink {relative}"
            )
        if path.is_file():
            entries[relative] = _sha256(path)
        elif not path.is_dir():
            raise RuntimeError(
                f"{BLOCK_ISOLATION_AUDIT_FAILED}: workspace evidence tree contains non-regular entry {relative}"
            )
    return entries


def _pre_oos_root_synthesis_relative(report_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,180}", report_id):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: unsafe pre-OOS report identity"
        )
    return (
        Path("objects")
        / "research_iteration_master"
        / "revision_council"
        / report_id
        / f"pre_oos_council_root_synthesis__{report_id}.json"
    ).as_posix()


def _append_pre_oos_input_ref(
    workspace: Path,
    refs: dict[str, str],
    raw_path: object,
    *,
    declared_sha256: object = None,
) -> None:
    if not isinstance(raw_path, str) or not raw_path:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis evidence path is invalid"
        )
    relative = Path(raw_path)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis evidence path is unsafe"
        )
    relative_text = relative.as_posix()
    path = _read_regular_workspace_file(workspace, relative_text)
    digest = _sha256(path)
    if declared_sha256 is not None and declared_sha256 != digest:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis evidence hash mismatch"
        )
    prior = refs.get(relative_text)
    if prior is not None and prior != digest:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis evidence identity conflict"
        )
    refs[relative_text] = digest


def _collect_pre_oos_context_refs(
    workspace: Path,
    refs: dict[str, str],
    value: object,
) -> None:
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            _append_pre_oos_input_ref(
                workspace,
                refs,
                value.get("path"),
                declared_sha256=value.get("sha256"),
            )
        for child in value.values():
            _collect_pre_oos_context_refs(workspace, refs, child)
    elif isinstance(value, list):
        for child in value:
            _collect_pre_oos_context_refs(workspace, refs, child)


def _write_pre_oos_root_synthesis_task(
    job: ResearchJob,
    workspace: Path,
    *,
    trusted_resume_proof_sha256: str,
    attempt_id: str,
) -> PreOosRootSynthesisTask:
    root = workspace.resolve(strict=True)
    proof_relative = (
        "objects/runtime_context/"
        f"ultimate_run_report__{job.report_id}.json"
    )
    proof_path = _read_regular_workspace_file(root, proof_relative)
    if (
        not re.fullmatch(r"resume_[0-9a-f]{32}", attempt_id)
        or not re.fullmatch(r"[0-9a-f]{64}", trusted_resume_proof_sha256)
        or _sha256(proof_path) != trusted_resume_proof_sha256
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis task trust binding is invalid"
        )
    route = _classify_resume_route(
        root,
        job.report_id,
        start_step="6",
        trusted_proof_sha256=trusted_resume_proof_sha256,
    )
    if route.kind != RESUME_KIND_PRE_OOS_ROOT_SYNTHESIS:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis task route is invalid"
        )

    council_relative = (
        Path("objects")
        / "research_iteration_master"
        / "revision_council"
        / job.report_id
    )
    dispatch_relative = (
        council_relative / f"dispatch_manifest__{job.report_id}.json"
    ).as_posix()
    collection_relative = (
        council_relative / f"agentic_result_collection__{job.report_id}.json"
    ).as_posix()
    summary_relative = (
        council_relative / f"revision_council_summary__{job.report_id}.json"
    ).as_posix()
    appendix_json_relative = (
        council_relative / f"council_derivation_appendix__{job.report_id}.json"
    ).as_posix()
    appendix_md_relative = (
        council_relative / f"council_derivation_appendix__{job.report_id}.md"
    ).as_posix()
    refs: dict[str, str] = {}
    for relative in (
        proof_relative,
        dispatch_relative,
        collection_relative,
        summary_relative,
        appendix_json_relative,
        appendix_md_relative,
    ):
        _append_pre_oos_input_ref(root, refs, relative)
    lifecycle_path = research_protocol_paths(root, job.report_id)["evo_lifecycle"]
    _append_pre_oos_input_ref(
        root,
        refs,
        lifecycle_path.relative_to(root).as_posix(),
    )

    dispatch = _read_regular_workspace_json(root, dispatch_relative)
    dispatch_evo = (
        dispatch.get("evo_v2")
        if isinstance(dispatch.get("evo_v2"), dict)
        else {}
    )
    dispatch_oos = (
        dispatch_evo.get("oos_control")
        if isinstance(dispatch_evo.get("oos_control"), dict)
        else {}
    )
    if (
        dispatch.get("dispatch_manifest_version")
        != "factorforge_agentic_council_dispatch_manifest_v1"
        or dispatch.get("report_id") != job.report_id
        or dispatch.get("status") != "awaiting_agent_results"
        or dispatch.get("canonical_write_permission") is not False
        or dispatch.get("execution_allowed_by_default") is not False
        or dispatch.get("human_approval_required") is not True
        or dispatch_evo.get("required") is not True
        or dispatch_evo.get("evidence_view") != "PURGED_IS_ONLY"
        or dispatch_oos.get("search_use") != "SEALED_NOT_ACCESSED"
        or dispatch_oos.get("oos_refs_allowed") is not False
        or dispatch_oos.get("consumed_oos_reuse_allowed") is not False
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis dispatch binding is invalid"
        )
    tasks = dispatch.get("agent_tasks")
    if (
        not isinstance(tasks, list)
        or not tasks
        or dispatch.get("agent_task_count") != len(tasks)
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis dispatch task set is invalid"
        )
    seen_tasks: set[str] = set()
    route_options: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict) or task.get("required") is not True:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis dispatch task is invalid"
            )
        task_id = str(task.get("task_id") or "")
        if not task_id or task_id in seen_tasks:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis dispatch identity is invalid"
            )
        seen_tasks.add(task_id)
        _append_pre_oos_input_ref(
            root,
            refs,
            task.get("task_packet_path"),
            declared_sha256=task.get("task_packet_sha256"),
        )
        result_relative = task.get("expected_result_path")
        _append_pre_oos_input_ref(
            root,
            refs,
            result_relative,
        )
        result = _read_regular_workspace_json(root, str(result_relative or ""))
        outcome = result_evo_outcome_summary(result)
        result_ref = {
            "task_id": task_id,
            "path": str(result_relative),
            "sha256": refs[str(result_relative)],
        }
        laws = result.get("candidate_revision_laws")
        law = laws[0] if isinstance(laws, list) and len(laws) == 1 else None
        if (
            not isinstance(outcome, dict)
            or outcome.get("outcome")
            not in {"MINIMAL_MECHANISM_DELTA", "NO_DERIVED_LAW"}
            or result.get("report_id") != job.report_id
            or result.get("task_id") != task_id
            or result.get("agent_role") != task.get("agent_role")
            or result.get("agent_identifier")
            != task.get("expected_agent_identifier")
        ):
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis raw result binding is invalid"
            )
        route_options.append(
            {
                "task_id": task_id,
                "route_id": task.get("route_id"),
                "route_family": task.get("route_family"),
                "agent_identifier": result.get("agent_identifier"),
                "result_ref": result_ref,
                "outcome": outcome.get("outcome"),
                "selected_outcome_if_chosen": {
                    "outcome": outcome.get("outcome"),
                    "task_id": task_id,
                    "route_id": task.get("route_id"),
                    "result_sha256": result_ref["sha256"],
                    "law_id": law.get("law_id") if isinstance(law, dict) else None,
                    "law_sha256": outcome.get("law_sha256"),
                    "delta_id": outcome.get("delta_id"),
                    "mechanism_delta_sha256": outcome.get(
                        "mechanism_delta_sha256"
                    ),
                    "economic_backprojection_sha256": outcome.get(
                        "economic_backprojection_sha256"
                    ),
                    "no_derived_law_sha256": outcome.get(
                        "no_derived_law_sha256"
                    ),
                },
            }
        )
    _collect_pre_oos_context_refs(root, refs, dispatch["evo_v2"])
    if len(refs) > 128:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis evidence set is too large"
        )

    output_relative = _pre_oos_root_synthesis_relative(job.report_id)
    output_path = root / output_relative
    canonical_output = pre_oos_root_synthesis_path(root, job.report_id)
    if (
        output_path.resolve(strict=False) != canonical_output.resolve(strict=False)
        or output_path.exists()
        or output_path.is_symlink()
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: pre-OOS synthesis output is not clean and canonical"
        )
    task_packet_relative = (
        "identity/"
        f"web_pre_oos_root_synthesis_task__{job.report_id}.json"
    )
    unsigned = {
        "version": PRE_OOS_ROOT_SYNTHESIS_TASK_VERSION,
        "attempt_id": attempt_id,
        "identity": {
            "job_id": job.job_id,
            "factor_id": job.factor_id,
            "research_id": job.research_id,
            "report_id": job.report_id,
        },
        "trusted_pause_ref": {
            "path": proof_relative,
            "sha256": trusted_resume_proof_sha256,
            "proof_semantics": "awaiting_agent_authored_pre_oos_root_synthesis",
            "final_outcome": "awaiting_pre_oos_council_root_synthesis",
            "council_status": "awaiting_root_synthesis",
        },
        "evidence_view": "PURGED_IS_ONLY",
        "oos_state": "SEALED_NOT_ACCESSED",
        "read_only_inputs": [
            {"path": relative, "sha256": digest}
            for relative, digest in sorted(refs.items())
        ],
        "required_output": {
            "path": output_relative,
            "contract_version": PRE_OOS_ROOT_SYNTHESIS_VERSION,
            "exact_top_level_fields": [
                "contract_version",
                "report_id",
                "evidence_view",
                "authority",
                "evidence_bindings",
                "route_result_analysis",
                "dissent_resolution",
                "selection",
                "selected_outcome",
                "content_sha256",
            ],
            "authority": {
                "status": "AGENT_AUTHORED_REVIEW_ONLY",
                "host_transition_authority": False,
                "human_approval_authority": False,
                "canonical_write_allowed": False,
                "execution_allowed": False,
                "factor_verdict": "NOT_ISSUED",
                "oos_accessed": False,
                "child_execution_allowed": False,
            },
            "content_sha256_rule": (
                "sha256 of compact UTF-8 JSON with sorted keys for the exact "
                "object after removing content_sha256"
            ),
            "exact_nested_fields": {
                "evidence_bindings": [
                    "feedback_ledger_ref",
                    "lifecycle_ref",
                    "dispatch_manifest_ref",
                    "result_collection_ref",
                    "council_summary_ref",
                    "derivation_appendix_json_ref",
                    "derivation_appendix_markdown_ref",
                    "raw_result_refs",
                    "selected_proposal_ref",
                ],
                "route_result_analysis_item": [
                    "task_id",
                    "route_id",
                    "route_family",
                    "agent_identifier",
                    "result_ref",
                    "outcome",
                    "disposition",
                    "exact_gap_or_closed_obligation",
                    "incompatible_assumptions",
                    "discriminating_evidence",
                    "open_proof_obligations",
                    "dissent",
                ],
                "dissent": ["status", "position", "resolution"],
                "dissent_resolution": [
                    "policy",
                    "all_result_positions_covered",
                    "resolution_summary",
                    "unresolved_task_ids",
                ],
                "selection": [
                    "policy",
                    "selected_task_id",
                    "selected_result_sha256",
                    "rationale",
                    "decisive_evidence",
                    "majority_vote_used",
                    "score_or_rank_used",
                    "result_aggregation_used",
                ],
                "selected_outcome": [
                    "outcome",
                    "task_id",
                    "route_id",
                    "result_sha256",
                    "law_id",
                    "law_sha256",
                    "delta_id",
                    "mechanism_delta_sha256",
                    "economic_backprojection_sha256",
                    "no_derived_law_sha256",
                ],
            },
        },
        "fixed_evidence_bindings": {
            "feedback_ledger_ref": dispatch["evo_v2"][
                "canonical_feedback_ref"
            ],
            "lifecycle_ref": dispatch["evo_v2"]["lifecycle_ref"],
            "dispatch_manifest_ref": {
                "path": dispatch_relative,
                "sha256": refs[dispatch_relative],
            },
            "result_collection_ref": {
                "path": collection_relative,
                "sha256": refs[collection_relative],
            },
            "council_summary_ref": {
                "path": summary_relative,
                "sha256": refs[summary_relative],
            },
            "derivation_appendix_json_ref": {
                "path": appendix_json_relative,
                "sha256": refs[appendix_json_relative],
            },
            "derivation_appendix_markdown_ref": {
                "path": appendix_md_relative,
                "sha256": refs[appendix_md_relative],
            },
            "raw_result_refs": [
                option["result_ref"] for option in route_options
            ],
        },
        "route_selection_options": route_options,
        "synthesis_policy": {
            "select_exactly_one_raw_result": True,
            "compare_every_route": True,
            "resolve_or_preserve_every_dissent": True,
            "list_open_proof_obligations": True,
            "majority_vote_forbidden": True,
            "score_or_rank_forbidden": True,
            "result_aggregation_forbidden": True,
            "copy_evidence_refs_exactly": True,
            "invented_evidence_forbidden": True,
            "selection_policy": (
                "EVIDENCE_BASED_EXACT_RAW_RESULT_SELECTION_NO_AGGREGATION"
            ),
            "dissent_policy": (
                "PRESERVE_OR_RESOLVE_EACH_RESULT_DISSENT_WITH_DISCRIMINATING_EVIDENCE"
            ),
        },
        "permissions": {
            "agent_workspace_write_paths": [output_relative],
            "host_transition_allowed": False,
            "human_approval_allowed": False,
            "child_creation_allowed": False,
            "oos_access_allowed": False,
            "canonical_knowledge_write_allowed": False,
        },
    }
    packet = {**unsigned, "content_sha256": stable_json_hash(unsigned)}
    _write_json_atomic(root / task_packet_relative, packet, root=root)
    packet_path = _read_regular_workspace_file(root, task_packet_relative)
    return PreOosRootSynthesisTask(
        version=PRE_OOS_ROOT_SYNTHESIS_TASK_VERSION,
        attempt_id=attempt_id,
        job_id=job.job_id,
        factor_id=job.factor_id,
        research_id=job.research_id,
        report_id=job.report_id,
        trusted_proof_sha256=trusted_resume_proof_sha256,
        task_packet_relative=task_packet_relative,
        task_packet_sha256=_sha256(packet_path),
        expected_output_relative=output_relative,
        read_only_input_sha256=tuple(sorted(refs.items())),
    )


def _allowed_agent_write_paths(
    workspace: Path,
    *,
    report_id: str,
    resume: bool,
    trusted_resume_proof_sha256: str | None = None,
    council_ingress_tasks: tuple[CouncilIngressTask, ...] = (),
    pre_oos_root_synthesis_task: PreOosRootSynthesisTask | None = None,
    require_research_director_record: bool = False,
) -> tuple[set[str], set[str]]:
    prompt = "identity/web_agent_resume.md" if resume else "identity/web_agent_task.md"
    allowed = {
        prompt,
        "identity/web_execution_ledger.md",
        "identity/web_agent_completion.json",
    }
    required = {
        "identity/web_execution_ledger.md",
    }
    if not resume:
        if council_ingress_tasks:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh run cannot carry Council ingress tasks"
            )
        if pre_oos_root_synthesis_task is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh run cannot carry a pre-OOS root synthesis task"
            )
        if trusted_resume_proof_sha256 is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh agent run cannot carry resume proof"
            )
        allowed.add("identity/web_research_plan.json")
        required.add("identity/web_research_plan.json")
        if require_research_director_record:
            allowed.add(HOST_DIRECTOR_RECORD_RELATIVE)
            required.add(HOST_DIRECTOR_RECORD_RELATIVE)
        return allowed, required

    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    )
    if (
        not trusted_resume_proof_sha256
        or not proof_path.is_file()
        or proof_path.is_symlink()
        or _sha256(proof_path) != trusted_resume_proof_sha256
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: current resume proof does not match host trust"
        )
    if council_ingress_tasks:
        if pre_oos_root_synthesis_task is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress and root synthesis cannot share a resume"
            )
        allowed = {prompt}
        required = set()
        for task in council_ingress_tasks:
            allowed.add(task.expected_result_path)
            required.add(task.expected_result_path)
        return allowed, required
    if pre_oos_root_synthesis_task is not None:
        expected = pre_oos_root_synthesis_task.expected_output_relative
        canonical = pre_oos_root_synthesis_path(
            workspace.resolve(strict=True),
            report_id,
        ).relative_to(workspace.resolve(strict=True)).as_posix()
        if expected != canonical:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: root synthesis output path is not canonical"
            )
        return {expected}, {expected}
    if proof_path.is_file() and not proof_path.is_symlink():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        pause = (
            proof.get("main_agent_mechanism_memo")
            if isinstance(proof.get("main_agent_mechanism_memo"), dict)
            else {}
        )
        if (
            str(proof.get("status") or "").upper() == "PAUSED"
            and str(pause.get("token") or "")
            in {
                MECHANISM_MEMO_INITIAL_TOKEN,
                MECHANISM_MEMO_REVISION_TOKEN,
            }
        ):
            memo_json = (
                "objects/research_iteration_master/"
                f"main_agent_mechanism_memo__{report_id}.json"
            )
            memo_md = (
                "objects/research_iteration_master/"
                f"main_agent_mechanism_memo__{report_id}.md"
            )
            allowed.add(memo_json)
            required.add(memo_json)
    return allowed, required


def _trusted_council_ingress_tasks(
    workspace: Path,
    *,
    report_id: str,
    trusted_resume_proof_sha256: str,
    require_results_absent: bool = True,
) -> tuple[CouncilIngressTask, ...]:
    proof_path = (
        workspace
        / "objects"
        / "runtime_context"
        / f"ultimate_run_report__{report_id}.json"
    )
    if (
        not trusted_resume_proof_sha256
        or not proof_path.is_file()
        or proof_path.is_symlink()
        or _sha256(proof_path) != trusted_resume_proof_sha256
    ):
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: Council ingress proof is not host trusted"
        )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    council = (
        proof.get("revision_council")
        if isinstance(proof.get("revision_council"), dict)
        else {}
    )
    awaiting = (
        str(proof.get("status") or "").upper() == "PAUSED"
        and str(council.get("status") or "") == "awaiting_agent_results"
        and str(council.get("effective_mode") or "")
        == "agentic_dispatch_manifest"
    )
    if not awaiting:
        return ()
    return load_council_ingress_tasks(
        workspace,
        report_id,
        require_results_absent=require_results_absent,
    )


def _validate_agent_write_boundary(
    workspace: Path,
    *,
    before: dict[str, str],
    allowed: set[str],
    required: set[str],
) -> None:
    after = _workspace_file_snapshot(workspace)
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    unexpected = sorted(changed - allowed)
    if unexpected:
        raise RuntimeError(
            f"{BLOCK_AGENT_WRITE_SCOPE_INVALID}: unexpected writes="
            + ",".join(unexpected[:50])
        )
    missing = sorted(
        path
        for path in required
        if not str(after.get(path) or "").startswith("file:")
    )
    unsafe = sorted(
        path
        for path in changed & allowed
        if path in after and not after[path].startswith("file:")
    )
    if unsafe:
        detail = [f"unsafe:{path}" for path in unsafe]
        raise RuntimeError(
            f"{BLOCK_AGENT_WRITE_SCOPE_INVALID}: " + ",".join(detail[:50])
        )
    if missing:
        detail = [f"missing:{path}" for path in missing]
        raise RuntimeError(
            f"{BLOCK_AGENT_DELIVERABLE_MISSING}: " + ",".join(detail[:50])
        )


def audit_factor_worktree(worktree: Path, workspace: Path) -> list[str]:
    failures: list[str] = []
    worktree = worktree.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    try:
        workspace.relative_to(worktree)
    except ValueError:
        return ["workspace is outside allocated worktree"]

    manifest_path = workspace / "manifest.json"
    if not manifest_path.is_file():
        failures.append("workspace manifest missing")
    else:
        failures.extend(validate_workspace_manifest(load_workspace_manifest(manifest_path)))

    for path in workspace.rglob("*"):
        if path.is_symlink():
            failures.append(f"symlink forbidden inside workspace: {path.relative_to(workspace).as_posix()}")

    changed: set[str] = set()
    commands = (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
        ("ls-files", "--others", "--ignored", "--exclude-standard", "-z"),
    )
    for args in commands:
        proc = subprocess.run(
            ["git", "-C", str(worktree), *args],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            failures.append(f"git audit failed for {' '.join(args)}")
            continue
        changed.update(item for item in proc.stdout.split("\0") if item)
    for relative in sorted(changed):
        candidate = (worktree / relative).resolve(strict=False)
        try:
            candidate.relative_to(workspace)
        except ValueError:
            failures.append(f"write outside factor workspace: {relative}")
    return list(dict.fromkeys(failures))


def build_web_result(
    summary: UltimateRunSummary,
    *,
    publication_id: str,
    public_artifacts: list[SafeArtifact],
) -> dict[str, Any]:
    artifacts = []
    for item in public_artifacts[:300]:
        kind = "image" if item.media_type.startswith("image/") and item.content_disposition == "inline" else "document"
        artifacts.append(
            {
                "artifact_id": item.artifact_id,
                "label": _artifact_label(item.artifact_id),
                "kind": kind,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
            }
        )
    research_method = dict(summary.research_method)
    if summary.economic_game:
        research_method.setdefault("economic_mechanism", summary.economic_game)
    if summary.math_mechanism:
        research_method.setdefault("mathematical_object", summary.math_mechanism)
    data_implementation = {**summary.data_contract, **summary.implementation_contract}
    metric_evidence_class = str(
        summary.backtest_center.get("evidence_class") or "FORMAL UNVERIFIED"
    )
    metric_evidence = {
        key: {
            "evidence_class": metric_evidence_class,
            "artifact_id": summary.metric_sources.get(key, ""),
            "validator_verdict": summary.backtest_center.get("validator_verdict", "UNKNOWN"),
        }
        for key in summary.core_metrics
    }
    return {
        "contract_version": "factorforge_console_web_result_v2",
        "public_artifact_set_id": publication_id,
        "summary": _result_summary(summary),
        "execution_status": summary.execution_status,
        "protocol_status": summary.protocol_status,
        "factor_verdict": summary.factor_verdict,
        "council_status": summary.council_status,
        "formal_proof_eligible": summary.formal_proof_eligible,
        "current_stage": summary.current_stage,
        "research_method": research_method,
        "data_implementation": data_implementation,
        "metrics": summary.core_metrics,
        "metric_sources": summary.metric_sources,
        "metric_evidence": metric_evidence,
        "research_notebook": summary.research_notebook,
        "math_notebook": summary.math_notebook,
        "backtest_center": summary.backtest_center,
        "council": summary.council,
        "blockers": summary.blockers + summary.evidence_errors,
        "next_actions": summary.next_actions,
        "timestamps": summary.timestamps,
        "evidence_artifact_ids": summary.artifact_ids,
        "stages": _stage_records(summary),
        "artifacts": artifacts,
    }


def _conversation_snapshot(
    store: ResearchJobStore,
    job: ResearchJob,
) -> dict[str, Any]:
    total_message_count, messages = store.snapshot_messages(job.job_id, limit=40)
    return _conversation_snapshot_from_messages(
        job.job_id,
        total_message_count,
        messages,
    )


def _conversation_snapshot_from_messages(
    job_id: str,
    total_message_count: int,
    messages: list[Any],
) -> dict[str, Any]:
    projected: list[dict[str, Any]] = []
    remaining = 40_000
    content_truncated = False
    for message in reversed(messages):
        content = message.content.strip()
        if not content or remaining <= 0:
            if content:
                content_truncated = True
            continue
        clipped = content[:remaining]
        if clipped != content:
            content_truncated = True
        remaining -= len(clipped)
        projected.append(
            {
                "message_id": message.message_id,
                "sequence_no": message.sequence_no,
                "role": message.role,
                "content_kind": message.content_kind,
                "content": clipped,
                "model": message.model,
                "created_at_utc": message.created_at_utc,
            }
        )
    projected.reverse()
    unsigned = {
        "contract_version": "factorforge_console_conversation_snapshot_v1",
        "job_id": job_id,
        "message_count": len(projected),
        "total_message_count": total_message_count,
        "omitted_message_count": max(0, total_message_count - len(projected)),
        "content_truncated": content_truncated,
        "history_complete": (
            total_message_count == len(projected) and not content_truncated
        ),
        "character_budget": 40_000,
        "included_character_count": sum(
            len(str(item.get("content") or "")) for item in projected
        ),
        "messages": projected,
    }
    return {**unsigned, "sha256": stable_json_hash(unsigned)}


def _web_execution_status(
    summary: UltimateRunSummary,
    agent_returncode: int,
    *,
    organization_runtime: dict[str, Any] | None = None,
    require_formal_organization: bool = False,
) -> str:
    if agent_returncode != 0:
        return "FAILED"
    if require_formal_organization and not (
        organization_runtime is not None
        and organization_runtime.get("lifecycle") == "COMPLETE"
        and organization_runtime.get("formal_independence_verified") is True
    ):
        return "BLOCKED"
    status = summary.execution_status.upper()
    if status == "COMPLETED" or status == "REJECTED":
        return "COMPLETED"
    if status in {"PAUSED", "ITERATING", "REVIEW_REQUIRED", "RUNNING"}:
        return "REVIEW_REQUIRED"
    if status == "BLOCKED":
        return "BLOCKED"
    if status in {"FAILED", "DRY_RUN"}:
        return "FAILED"
    return "FAILED"


def _web_terminal_error(
    *,
    execution_status: str,
    summary: UltimateRunSummary,
    require_formal_organization: bool,
    organization_runtime_verified: bool,
    denied_values: tuple[str, ...] = (),
) -> tuple[str, str]:
    def public(code: str, message: str) -> tuple[str, str]:
        return code, _public_error_message(message, denied_values=denied_values)

    if execution_status == "FAILED":
        return public(
            BLOCK_FORMAL_EVIDENCE_MISSING,
            "研究代理返回后未形成可核验的正式终态或暂停态。",
        )
    if execution_status == "BLOCKED":
        if require_formal_organization and not organization_runtime_verified:
            return public(
                BLOCK_RESEARCH_ORG_RUNTIME_INCOMPLETE,
                "Ultimate 已返回，但签名 specialist runtime、Host Director admission "
                "或 Independent Council 未形成完整正式证明。",
            )
        evidence = next(
            (str(item) for item in summary.blockers if str(item).strip()),
            "",
        )
        detail = f" 证据分类：{evidence}。" if evidence else ""
        organization_prefix = (
            "研究组织已通过核验，但"
            if require_formal_organization and organization_runtime_verified
            else ""
        )
        return public(
            BLOCK_HOST_FORMAL_EXECUTION_FAILED,
            f"{organization_prefix}Ultimate 正式执行在后续步骤被阻断。{detail}",
        )
    if execution_status == "REVIEW_REQUIRED" and summary.current_stage in {
        "awaiting_main_agent_council_synthesis",
        "awaiting_next_derivation",
    }:
        return public(
            EXPLICIT_HUMAN_DECISION_REQUIRED,
            "Council 已完成证据审议，但下一步需要显式数学推导或主代理综合，"
            "普通续跑不能代替该决定。",
        )
    return "", ""


def _normalize_protocol(value: str) -> str:
    normalized = str(value or "UNKNOWN").upper()
    return {
        "BLOCKED": "BLOCK",
        "FAILED": "FAIL",
        "COMPLETED": "PASS",
    }.get(normalized, normalized if normalized in {"NOT_STARTED", "RUNNING", "PAUSED", "PASS", "BLOCK", "FAIL", "UNKNOWN"} else "UNKNOWN")


def _normalize_council(value: str) -> str:
    normalized = str(value or "UNKNOWN").upper()
    if normalized == "BLOCKED":
        return "BLOCK"
    return normalized if normalized in {"NOT_STARTED", "RUNNING", "PAUSED", "PASS", "BLOCK", "REJECTED", "NOT_REQUIRED", "UNKNOWN"} else "UNKNOWN"


def _web_stage(summary: UltimateRunSummary) -> str:
    status = summary.execution_status.upper()
    if status == "COMPLETED" or status == "REJECTED":
        return "completed"
    if status in {"PAUSED", "ITERATING", "REVIEW_REQUIRED"}:
        return "review_required"
    if status == "BLOCKED":
        return "blocked"
    return "failed"


def _stage_records(summary: UltimateRunSummary) -> list[dict[str, str]]:
    has_method = bool(summary.research_method or summary.economic_game or summary.math_mechanism)
    has_data = bool(summary.data_contract)
    has_implementation = bool(summary.implementation_contract)
    has_metrics = bool(summary.core_metrics)
    council = summary.council_status.upper()
    return [
        {"id": "mechanism", "status": "done" if has_method else "pending"},
        {"id": "data", "status": "done" if has_data else "pending"},
        {"id": "implementation", "status": "done" if has_implementation else "pending"},
        {"id": "evaluation", "status": "done" if has_metrics else "pending"},
        {
            "id": "council",
            "status": "done" if council in {"PASS", "REJECTED", "NOT_REQUIRED"} else "blocked" if council in {"BLOCK", "BLOCKED"} else "active" if council in {"RUNNING", "PAUSED"} else "pending",
        },
    ]


def _result_summary(summary: UltimateRunSummary) -> str:
    if summary.execution_status == "PAUSED":
        return "研究处于可恢复暂停状态，尚未形成正式因子结论。"
    if summary.factor_verdict == "ACCEPT":
        return "研究协议与正式证明链通过，因子达到当前合同的接受条件。"
    if summary.factor_verdict == "REJECT":
        return "研究流程已完成，但因子未通过收益、成本或稳健性要求。"
    if summary.factor_verdict == "ITERATE":
        return "当前证据建议修订；需在现有 workspace 上显式继续。"
    if summary.factor_verdict == "BLOCK":
        return "研究被数据、实现或证明合同阻断，不能把现有结果当作因子结论。"
    return "尚未形成可核验的正式因子结论。"


def _artifact_label(artifact_id: str) -> str:
    name = Path(artifact_id).stem.replace("__", " · ").replace("_", " ")
    return name[:120]


def _public_error_message(
    message: str,
    *,
    denied_values: tuple[str, ...] = (),
) -> str:
    text = str(message).replace("\n", " ")
    text = re.sub(
        r"(?i)(?:file://\S+|s3://\S+|/(?:Users|home|srv|private|tmp|var/lib|root|etc|opt)/\S+)",
        "[internal-path]",
        text,
    )
    text = re.sub(
        r"(?i)((?:api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        text,
    )
    text = _redact_public_text(text, denied_values)
    return text[:1200]


def _adapter_denied_values(
    adapter: ResearchAgentAdapter,
    job_id: str,
) -> tuple[str, ...]:
    reader = getattr(adapter, "denied_secret_values", None)
    if not callable(reader):
        return ()
    values = reader(job_id)
    return tuple(str(value) for value in values if len(str(value)) >= 8)


def _adapter_credential_material_state(
    adapter: ResearchAgentAdapter,
    job_id: str,
) -> str:
    reader = getattr(adapter, "credential_material_state", None)
    if not callable(reader):
        return "unknown"
    state = str(reader(job_id))
    if state not in {"unknown", "not_issued", "may_have_been_issued"}:
        raise RuntimeError("credential material state is invalid")
    return state


def _redact_public_payload(value: Any, denied_values: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            _redact_public_text(str(key), denied_values): _redact_public_payload(
                child,
                denied_values,
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_public_payload(child, denied_values) for child in value]
    if isinstance(value, tuple):
        return [_redact_public_payload(child, denied_values) for child in value]
    if isinstance(value, str):
        return _redact_public_text(value, denied_values)
    return value


def _redact_public_text(value: str, denied_values: tuple[str, ...]) -> str:
    return redact_secret_values(value, denied_values, replacement="[redacted]")


def _subprocess_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _stamp(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", value)


def _argv_value(argv: list[Any], flag: str) -> str:
    normalized = [str(value) for value in argv]
    try:
        index = normalized.index(flag)
    except ValueError:
        return ""
    return normalized[index + 1] if index + 1 < len(normalized) else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _open_private_parent_fd(
    root: Path,
    path: Path,
    *,
    block_token: str,
    label: str,
):
    root_path = root.resolve(strict=True)
    candidate = path if path.is_absolute() else root_path / path
    try:
        relative = candidate.relative_to(root_path)
    except ValueError as exc:
        raise RuntimeError(f"{block_token}: {label} path escapes private state") from exc
    if (
        relative == Path(".")
        or not relative.parts
        or ".." in relative.parts
    ):
        raise RuntimeError(f"{block_token}: {label} path is unsafe")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open(root_path, directory_flags)
        for part in relative.parts[:-1]:
            next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError(
                    f"{block_token}: {label} parent is unsafe"
                )
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise RuntimeError(f"{block_token}: {label} parent is unsafe") from exc
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    try:
        # Keep caller I/O outside the traversal exception handler.  Otherwise
        # a failed create-once publish would be mislabeled as an unsafe parent
        # and its durable temporary file could escape cleanup.
        yield descriptor, relative.parts[-1]
    finally:
        os.close(descriptor)


def _read_private_regular_file_once(
    root: Path,
    path: Path,
    *,
    block_token: str,
    label: str,
    max_bytes: int = 2 * 1024 * 1024,
) -> tuple[bytes, str, str]:
    root_path = root.resolve(strict=True)
    candidate = path if path.is_absolute() else root_path / path
    try:
        relative = candidate.relative_to(root_path)
    except ValueError as exc:
        raise RuntimeError(
            f"{block_token}: {label} path escapes private state"
        ) from exc
    if (
        relative == Path(".")
        or not relative.parts
        or ".." in relative.parts
    ):
        raise RuntimeError(f"{block_token}: {label} path is unsafe")
    try:
        with _open_private_parent_fd(
            root_path,
            candidate,
            block_token=block_token,
            label=label,
        ) as (parent_descriptor, name):
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_descriptor,
            )
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.geteuid()
                    or before.st_nlink != 1
                    or before.st_size <= 0
                    or before.st_size > max_bytes
                ):
                    raise RuntimeError(
                        f"{block_token}: {label} is not a bounded private file"
                    )
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(descriptor)
                path_after = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            finally:
                os.close(descriptor)
    except OSError as exc:
        raise RuntimeError(f"{block_token}: {label} is unsafe") from exc
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_dev != path_after.st_dev
        or before.st_ino != path_after.st_ino
        or before.st_size != after.st_size
        or before.st_size != path_after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_mtime_ns != path_after.st_mtime_ns
    ):
        raise RuntimeError(f"{block_token}: {label} changed during read")
    content = b"".join(chunks)
    return content, hashlib.sha256(content).hexdigest(), relative.as_posix()


def _copy_immutable_regular_file(
    source: Path,
    destination: Path,
    *,
    root: Path,
    expected_sha256: str | None,
    block_token: str,
    label: str,
) -> str:
    destination_created = False
    try:
        with _open_private_parent_fd(
            root,
            source,
            block_token=block_token,
            label=f"{label} source",
        ) as (source_parent_descriptor, source_name), _open_private_parent_fd(
            root,
            destination,
            block_token=block_token,
            label=f"{label} destination",
        ) as (destination_parent_descriptor, destination_name):
            source_descriptor = os.open(
                source_name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=source_parent_descriptor,
            )
            destination_descriptor = -1
            created_destination_metadata = None
            try:
                destination_descriptor = os.open(
                    destination_name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=destination_parent_descriptor,
                )
                destination_created = True
                created_destination_metadata = os.fstat(destination_descriptor)
                digest = hashlib.sha256()
                try:
                    source_before = os.fstat(source_descriptor)
                    if (
                        not stat.S_ISREG(source_before.st_mode)
                        or source_before.st_nlink != 1
                        or source_before.st_size <= 0
                        or source_before.st_size > 2 * 1024 * 1024
                    ):
                        raise RuntimeError(
                            f"{block_token}: {label} source is not a bounded private file"
                        )
                    while True:
                        chunk = os.read(source_descriptor, 1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        offset = 0
                        while offset < len(chunk):
                            offset += os.write(destination_descriptor, chunk[offset:])
                    os.fchmod(destination_descriptor, 0o400)
                    os.fsync(destination_descriptor)
                    source_after = os.fstat(source_descriptor)
                    destination_metadata = os.fstat(destination_descriptor)
                finally:
                    os.close(destination_descriptor)
                    destination_descriptor = -1
                path_after = os.stat(
                    source_name,
                    dir_fd=source_parent_descriptor,
                    follow_symlinks=False,
                )
                actual_sha256 = digest.hexdigest()
                if (
                    source_before.st_ino != source_after.st_ino
                    or source_before.st_ino != path_after.st_ino
                    or source_before.st_size != source_after.st_size
                    or source_before.st_size != path_after.st_size
                    or source_before.st_mtime_ns != source_after.st_mtime_ns
                    or source_before.st_mtime_ns != path_after.st_mtime_ns
                    or not stat.S_ISREG(destination_metadata.st_mode)
                    or destination_metadata.st_nlink != 1
                    or destination_metadata.st_mode & 0o222
                    or (
                        expected_sha256 is not None
                        and actual_sha256 != expected_sha256
                    )
                ):
                    raise RuntimeError(
                        f"{block_token}: {label} changed during snapshot"
                    )
                parent_entry_metadata = os.stat(
                    destination_name,
                    dir_fd=destination_parent_descriptor,
                    follow_symlinks=False,
                )
                with _open_private_parent_fd(
                    root,
                    destination,
                    block_token=block_token,
                    label=f"{label} destination verification",
                ) as (verification_parent_descriptor, verification_name):
                    path_entry_metadata = os.stat(
                        verification_name,
                        dir_fd=verification_parent_descriptor,
                        follow_symlinks=False,
                    )
                if any(
                    metadata.st_dev != created_destination_metadata.st_dev
                    or metadata.st_ino != created_destination_metadata.st_ino
                    for metadata in (
                        destination_metadata,
                        parent_entry_metadata,
                        path_entry_metadata,
                    )
                ):
                    raise RuntimeError(
                        f"{block_token}: {label} destination changed during snapshot"
                    )
                os.fsync(destination_parent_descriptor)
                return actual_sha256
            except (OSError, RuntimeError):
                if destination_created and created_destination_metadata is not None:
                    try:
                        current_destination = os.stat(
                            destination_name,
                            dir_fd=destination_parent_descriptor,
                            follow_symlinks=False,
                        )
                        if (
                            current_destination.st_dev
                            == created_destination_metadata.st_dev
                            and current_destination.st_ino
                            == created_destination_metadata.st_ino
                        ):
                            os.unlink(
                                destination_name,
                                dir_fd=destination_parent_descriptor,
                            )
                            os.fsync(destination_parent_descriptor)
                            destination_created = False
                    except (FileNotFoundError, OSError):
                        pass
                raise
            finally:
                if destination_descriptor >= 0:
                    os.close(destination_descriptor)
                os.close(source_descriptor)
    except RuntimeError:
        if destination_created:
            try:
                with _open_private_parent_fd(
                    root,
                    destination,
                    block_token=block_token,
                    label=f"{label} cleanup",
                ) as (parent_descriptor, name):
                    os.unlink(name, dir_fd=parent_descriptor)
                    os.fsync(parent_descriptor)
            except (FileNotFoundError, OSError, RuntimeError):
                pass
        raise
    except OSError as exc:
        if destination_created:
            try:
                with _open_private_parent_fd(
                    root,
                    destination,
                    block_token=block_token,
                    label=f"{label} cleanup",
                ) as (parent_descriptor, name):
                    os.unlink(name, dir_fd=parent_descriptor)
                    os.fsync(parent_descriptor)
            except (FileNotFoundError, OSError, RuntimeError):
                pass
        raise RuntimeError(f"{block_token}: {label} snapshot failed") from exc


def _write_json_atomic(
    path: Path,
    payload: dict[str, Any],
    *,
    root: Path,
) -> None:
    write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        root=root,
    )


def _write_private_json_once(
    path: Path,
    payload: dict[str, Any],
    *,
    root: Path,
    block_token: str,
    label: str,
) -> None:
    encoded = (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with _open_private_parent_fd(
            root,
            path,
            block_token=block_token,
            label=label,
        ) as (parent_descriptor, name):
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
            try:
                offset = 0
                while offset < len(encoded):
                    offset += os.write(descriptor, encoded[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
                raise
            os.fsync(parent_descriptor)
            os.unlink(temporary_name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
    except FileExistsError as exc:
        raise RuntimeError(
            f"{block_token}: {label} is create-once and already exists"
        ) from exc
    except OSError as exc:
        try:
            with _open_private_parent_fd(
                root,
                path,
                block_token=block_token,
                label=f"{label} temporary cleanup",
            ) as (parent_descriptor, _name):
                try:
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                    os.fsync(parent_descriptor)
                except FileNotFoundError:
                    pass
        except RuntimeError:
            pass
        raise RuntimeError(f"{block_token}: {label} write failed") from exc


def _recover_private_json_once_publish(
    path: Path,
    *,
    root: Path,
    block_token: str,
    label: str,
) -> bool:
    """Finish the sole safe crash window in the create-once link publish."""

    try:
        with _open_private_parent_fd(
            root,
            path,
            block_token=block_token,
            label=f"{label} recovery",
        ) as (parent_descriptor, name):
            try:
                destination = os.stat(
                    name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return False
            if (
                not stat.S_ISREG(destination.st_mode)
                or destination.st_uid != os.geteuid()
            ):
                raise RuntimeError(
                    f"{block_token}: {label} recovery destination is unsafe"
                )
            if destination.st_nlink == 1:
                return False
            if destination.st_nlink != 2:
                raise RuntimeError(
                    f"{block_token}: {label} recovery link count is invalid"
                )

            temporary_pattern = re.compile(
                rf"\.{re.escape(name)}\.[0-9a-f]{{32}}\.tmp\Z"
            )
            linked_temporary_names: list[str] = []
            for entry_name in os.listdir(parent_descriptor):
                if not temporary_pattern.fullmatch(entry_name):
                    continue
                entry = os.stat(
                    entry_name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if (
                    entry.st_dev == destination.st_dev
                    and entry.st_ino == destination.st_ino
                ):
                    linked_temporary_names.append(entry_name)
            if len(linked_temporary_names) != 1:
                raise RuntimeError(
                    f"{block_token}: {label} recovery hardlink evidence is invalid"
                )

            temporary_name = linked_temporary_names[0]
            linked_before = os.stat(
                temporary_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            destination_before = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if any(
                metadata.st_dev != destination.st_dev
                or metadata.st_ino != destination.st_ino
                or not stat.S_ISREG(metadata.st_mode)
                for metadata in (linked_before, destination_before)
            ):
                raise RuntimeError(
                    f"{block_token}: {label} recovery hardlink changed"
                )
            os.unlink(temporary_name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
            destination_after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                destination_after.st_dev != destination.st_dev
                or destination_after.st_ino != destination.st_ino
                or destination_after.st_size != destination.st_size
                or destination_after.st_mtime_ns != destination.st_mtime_ns
                or destination_after.st_nlink != 1
                or not stat.S_ISREG(destination_after.st_mode)
            ):
                raise RuntimeError(
                    f"{block_token}: {label} recovery destination changed"
                )
            return True
    except OSError as exc:
        raise RuntimeError(f"{block_token}: {label} recovery failed") from exc
