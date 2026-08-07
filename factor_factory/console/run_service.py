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
from pathlib import Path
from typing import Any

from factor_factory.console.agent_adapter import (
    BLOCK_AGENT_ORPHANED_WRITER,
    BLOCK_AGENT_RUNTIME_UNAVAILABLE,
    AgentResumeTask,
    AgentRunResult,
    ResearchAgentAdapter,
    RESUME_MEMO_MAX_BYTES,
    RESUME_MEMO_COMPONENT_IDENTITY_FIELDS,
    RESUME_MEMO_IMMUTABLE_FIELDS,
    RESUME_MEMO_OPERATOR_FLAG_FIELDS,
)
from factor_factory.console.artifact_service import SafeArtifact, publish_official_artifacts
from factor_factory.console.catalog_health import catalogs_healthy, require_catalogs_healthy
from factor_factory.console.config import ConsoleConfig
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
from factor_factory.console.models import (
    ResearchJob,
    ResearchRequest,
    validate_pilot_evaluation_request,
    validate_public_source_url,
)
from factor_factory.console.runner_health import probe_runner_health
from factor_factory.console.secret_safety import redact_secret_values
from factor_factory.console.store import ResearchJobStore, utc_now
from factor_factory.console.ultimate_reader import UltimateRunSummary, read_ultimate_workspace
from factor_factory.console.web_research_plan import (
    required_web_resume_start_step,
    stable_json_hash,
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
from factor_factory.mechanism_math.main_agent_memo import (
    CONTRACT_VERSION,
    MAX_MECHANISM_MEMO_REVISIONS,
    REQUIRED_QA_FIELDS,
    validate_main_agent_mechanism_memo,
)
from factor_factory.mechanism_math.formula_specific import BASELINE_MODEL_FAMILIES


_SYSTEM_SUBPROCESS_RUN = subprocess.run


BLOCK_ISOLATION_AUDIT_FAILED = "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED"
BLOCK_EVIDENCE_IDENTITY_MISMATCH = "BLOCK_FACTORFORGE_CONSOLE_EVIDENCE_IDENTITY_MISMATCH"
BLOCK_FORMAL_EVIDENCE_MISSING = "BLOCK_FACTORFORGE_CONSOLE_FORMAL_EVIDENCE_MISSING"
BLOCK_CREDENTIAL_REGISTRY_INVALID = "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_REGISTRY_INVALID"
BLOCK_AGENT_WRITE_SCOPE_INVALID = "BLOCK_FACTORFORGE_CONSOLE_AGENT_WRITE_SCOPE_INVALID"
BLOCK_AGENT_RESUME_ARTIFACT_INVALID = "BLOCK_FACTORFORGE_CONSOLE_AGENT_RESUME_ARTIFACT_INVALID"
BLOCK_AGENT_DELIVERABLE_MISSING = "BLOCK_FACTORFORGE_CONSOLE_AGENT_DELIVERABLE_MISSING"
BLOCK_HOST_FORMAL_EXECUTION_FAILED = "BLOCK_FACTORFORGE_CONSOLE_HOST_FORMAL_EXECUTION_FAILED"
BLOCK_RESUME_TRUST_INVALID = "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID"
EXPLICIT_HUMAN_DECISION_REQUIRED = "FACTORFORGE_CONSOLE_EXPLICIT_HUMAN_DECISION_REQUIRED"
DATA_API_BRIDGE_RELATIVE = Path("deploy/factorforge-console/data-api-bridge")
FORMAL_ENGINE_SCRIPTS = {
    "materialize_web_research": Path("scripts/materialize_factorforge_web_research.py"),
    "run_factorforge_ultimate": Path("scripts/run_factorforge_ultimate.py"),
}
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
RESUME_KIND_HUMAN_COUNCIL_SYNTHESIS = "human_council_synthesis"
RESUME_KIND_HUMAN_NEXT_DERIVATION = "human_next_derivation"
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
    if job.error_code in NON_RESUMABLE_SECURITY_BLOCKERS:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: prior security blocker is not resumable; "
            "start a new isolated research task"
        )
    if not job.worktree_path or not job.workspace_path or not job.base_commit:
        raise RuntimeError(
            f"{BLOCK_RESUME_TRUST_INVALID}: persisted workspace identity is incomplete"
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
        return self.store.create_job(request, initial_messages=initial_messages)

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

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.pause_interrupted_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, name="factorforge-console-worker", daemon=True)
        self._thread.start()

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
    ) -> ResearchJob:
        validate_pilot_evaluation_request(request)
        if request.source_url:
            raise ValueError(
                "source URL ingestion is disabled until the read-only fetch broker is available"
            )
        require_catalogs_healthy(self.config)
        job = self.store.create_job(request, initial_messages=initial_messages)
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
        self._validate_trusted_resume_context(
            job,
            worktree=allocation.worktree_path,
            workspace=allocation.workspace_path,
        )
        job = self.store.request_resume(job_id)
        self._wake.set()
        return job

    def cancel_queued(self, job_id: str) -> ResearchJob:
        return self.store.cancel_queued(job_id)

    def run_once(self) -> ResearchJob | None:
        if not catalogs_healthy(self.config):
            return None
        job = self.store.claim_next_job()
        if job is None:
            return None
        self._run_job(job)
        return self.store.get_job(job.job_id)

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
        resume_restore_state: ResumeRestoreState | None = None
        resume_parent_restored = False
        private_completion_status: str | None = None
        private_attestation_id = ""
        council_ingress_tasks: tuple[CouncilIngressTask, ...] = ()
        try:
            resume = bool(job.workspace_path and job.worktree_path)
            self._begin_private_execution(job, resume=resume)
            validate_public_source_url(job.request.source_url)
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
                )
                resume_route = _apply_execution_mode_resume_policy(
                    resume_route,
                    execution_mode=self.config.execution_mode,
                )
                if resume_route.kind == RESUME_KIND_MECHANISM_AGENT:
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
                }:
                    council_result_paths = tuple(
                        task.expected_result_path for task in council_ingress_tasks
                    )
                    resume_restore_state = _capture_resume_restore_state(
                        workspace,
                        report_id=job.report_id,
                        expected_absent_paths=council_result_paths,
                        managed_directories=tuple(
                            sorted(
                                {
                                    Path(relative).parent.as_posix()
                                    for relative in council_result_paths
                                }
                            )
                        ),
                    )
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

            uses_research_agent = bool(
                not resume
                or (
                    resume_route is not None
                    and resume_route.kind
                    in {RESUME_KIND_MECHANISM_AGENT, RESUME_KIND_COUNCIL_INGRESS}
                )
            )
            if uses_research_agent:
                agent_write_snapshot = _workspace_file_snapshot(workspace)
                allowed_agent_writes, required_agent_outputs = _allowed_agent_write_paths(
                    workspace,
                    report_id=job.report_id,
                    resume=resume,
                    trusted_resume_proof_sha256=(
                        str(resume_trust["ultimate_proof_sha256"])
                        if resume_trust is not None
                        else None
                    ),
                    council_ingress_tasks=council_ingress_tasks,
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
            if council_ingress_tasks:
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
                if resume_route is None or resume_route.kind != RESUME_KIND_HOST_FORMAL_CHECKPOINT:
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
            formal_execution = self._execute_host_formal_pipeline(
                current_job,
                worktree=worktree,
                workspace=workspace,
                resume=resume,
                denied_values=denied_values,
                host_data_env=host_data_env,
                resume_trust=resume_trust,
                resume_task=resume_task,
                validated_resume_artifacts=validated_resume_artifacts,
            )
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
            attested_workspace = self._snapshot_workspace_evidence(
                current_job,
                workspace,
            )
            web_materialization = validate_materialized_web_research(
                attested_workspace
            )
            summary = read_ultimate_workspace(
                attested_workspace,
                report_id=job.report_id,
            )
            self._validate_summary_identity(current_job, summary)
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
            result["host_attestation_id"] = host_attestation_id
            result["model_execution"] = {
                "provider": agent_result.provider,
                "model": agent_result.model,
                "provenance": "host_pinned_agent_runtime",
            }
            execution_status = _web_execution_status(summary, agent_result.returncode)
            finished = utc_now() if execution_status in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"} else ""
            error_code = ""
            error_message = ""
            if execution_status == "FAILED":
                error_code = BLOCK_FORMAL_EVIDENCE_MISSING
                error_message = "研究代理返回后未形成可核验的正式终态或暂停态。"
            elif (
                execution_status == "REVIEW_REQUIRED"
                and summary.current_stage
                in {
                    "awaiting_main_agent_council_synthesis",
                    "awaiting_next_derivation",
                }
            ):
                error_code = EXPLICIT_HUMAN_DECISION_REQUIRED
                error_message = (
                    "Council 已完成证据审议，但下一步需要显式数学推导或主代理综合，"
                    "普通续跑不能代替该决定。"
                )
            updated = self.store.update_job(
                job.job_id,
                execution_status=execution_status,
                protocol_status=_normalize_protocol(summary.protocol_status),
                factor_verdict=summary.factor_verdict,
                council_status=_normalize_council(summary.council_status),
                formal_proof_eligible=summary.formal_proof_eligible,
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
        path = self._private_lifecycle_path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
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
        marker_path = self._non_resumable_marker_path(job.job_id)
        if marker_path.exists() or marker_path.is_symlink():
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: runner-private non-resumable marker exists"
            )
        lifecycle = self._read_private_lifecycle(job)
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
                marker_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                marker_path.parent.chmod(0o700)
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
        if not isinstance(lifecycle, dict) or lifecycle.get("status") != PRIVATE_LIFECYCLE_RESUMABLE:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: private lifecycle is not resumable"
            )

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
        if current_entries != entries:
            raise invalid("workspace formal evidence tree changed after host attestation")

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
        ]
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

    def _snapshot_workspace_evidence(
        self,
        job: ResearchJob,
        workspace: Path,
    ) -> Path:
        source_root = workspace.resolve(strict=True)
        state_root = self.config.state_root.resolve(strict=True)
        snapshot_parent = (
            state_root / "attestations" / job.job_id / "snapshots"
        )
        snapshot_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        snapshot_parent.chmod(0o700)
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
        resume_task: AgentResumeTask | None = None,
        validated_resume_artifacts: ValidatedAgentResumeArtifacts | None = None,
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
            "agent_provider": agent_result.provider,
            "agent_model": agent_result.model,
            "agent_result_id": agent_receipt_snapshot_relative,
            "agent_result_sha256": agent_receipt_snapshot_sha256,
            "agent_result_source_id": agent_result_relative.as_posix(),
            "agent_resume_artifact_binding": resume_artifact_binding,
            "host_evidence_reader_invoked": True,
            "host_terminal_formal_validation_status": (
                "PASS"
                if summary.formal_proof_eligible
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
                preserve_existing_plan=preserve_plan,
                trusted_resume_start_step=trusted_resume_start_step,
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
            or questionnaire_fields != set(fields)
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
                "observed_metrics": metric_facts,
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
        agent_result_raw = Path(agent_result.result_path).expanduser()
        if agent_result_raw.is_symlink():
            failures.append("agent_run_receipt_unsafe")
        else:
            try:
                agent_result_path = agent_result_raw.resolve(strict=True)
                agent_result_relative = agent_result_path.relative_to(state_root)
                agent_run = json.loads(agent_result_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, RuntimeError, ValueError, json.JSONDecodeError):
                failures.append("agent_run_receipt_invalid")
            else:
                if (
                    not agent_result_path.is_file()
                    or agent_result_path.is_symlink()
                    or agent_result_relative.parts[:2] != ("jobs", job.job_id)
                    or not isinstance(agent_run, dict)
                    or agent_run.get("version") != "factorforge_console_agent_run_v1"
                    or agent_run.get("job_id") != job.job_id
                    or agent_run.get("factor_id") != job.factor_id
                    or agent_run.get("research_id") != job.research_id
                    or agent_run.get("report_id") != job.report_id
                    or agent_run.get("agent_id") != agent_result.agent_id
                    or agent_run.get("resume") is not True
                    or agent_run.get("resume_attempt_id") != resume_task.attempt_id
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
            agent_run_receipt_sha256=_sha256(agent_result_path),
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


def _allowed_agent_write_paths(
    workspace: Path,
    *,
    report_id: str,
    resume: bool,
    trusted_resume_proof_sha256: str | None = None,
    council_ingress_tasks: tuple[CouncilIngressTask, ...] = (),
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
        if trusted_resume_proof_sha256 is not None:
            raise RuntimeError(
                f"{BLOCK_RESUME_TRUST_INVALID}: fresh agent run cannot carry resume proof"
            )
        allowed.add("identity/web_research_plan.json")
        required.add("identity/web_research_plan.json")
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
        allowed = {prompt}
        required = set()
        for task in council_ingress_tasks:
            allowed.add(task.expected_result_path)
            required.add(task.expected_result_path)
        return allowed, required
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
        require_results_absent=True,
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


def _web_execution_status(summary: UltimateRunSummary, agent_returncode: int) -> str:
    if agent_returncode != 0:
        return "FAILED"
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
    text = str(message).replace("\n", " ")[:1200]
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
    return text


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
    descriptor = os.open(root_path, directory_flags)
    try:
        for part in relative.parts[:-1]:
            next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode):
                raise RuntimeError(
                    f"{block_token}: {label} parent is unsafe"
                )
        yield descriptor, relative.parts[-1]
    except OSError as exc:
        raise RuntimeError(f"{block_token}: {label} parent is unsafe") from exc
    finally:
        os.close(descriptor)


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
