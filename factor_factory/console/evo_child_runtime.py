from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Protocol

from factor_factory.console.evo_child_assurance import (
    materialize_evo_child_assurance,
)
from factor_factory.console.evo_child_container import (
    materialize_evo_child_container_admission,
    reconcile_evo_child_agent_stage_containers,
    validate_evo_child_container_admission,
    validate_latest_evo_child_agent_termination,
)
from factor_factory.console.private_job_root import (
    PrivateJobRootError,
    ensure_host_private_job_subdirectory,
)
from factor_factory.console.evo_resume import (
    PROGRESS_HOST_CHECKPOINT_READY,
    PROGRESS_TERMINAL_CHECKPOINT_READY,
    PROGRESS_WAITING,
    assess_evo_v2_external_resume,
)
from factor_factory.console.web_factor_proof import (
    validate_web_evo_is_checkpoint,
    web_factor_proof_oos_recovery_state,
)
from factor_factory.console.web_research_plan import (
    required_web_resume_start_step,
    stable_json_hash,
)
from factor_factory.evo_child_authoring import (
    evo_child_authoring_admission_path,
    run_and_admit_evo_child_authoring,
)
from factor_factory.evo_child_materialization_admission import (
    child_materialization_admission_path,
    child_materialization_report_path,
    materialize_evo_child_materialization_admission,
    validate_evo_child_materialization_admission,
)
from factor_factory.evo_child_materialization_ticket import (
    materialize_public_child_materialization_ticket,
    public_child_materialization_ticket_path,
    validate_public_child_materialization_ticket,
)
from factor_factory.evo_child_preregistration import (
    child_preregistration_receipt_path,
    materialize_evo_child_preregistration,
    project_authorized_evo_child_search_trial_ledger,
    project_evo_child_metric_verifier_spec,
    project_evo_child_threshold_registration,
    validate_and_resolve_evo_child_web_research_plan,
)
from factor_factory.evo_oos import formal_oos_incident_reasons
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
)
from factor_factory.research_org.runtime_trust import load_runtime_trust_store

CHILD_RUNTIME_VERSION = "factorforge_console_evo_child_runtime_v1"
CHILD_EXECUTION_READY = "CHILD_EXECUTION_READY"
CHILD_RESUME_READY = "CHILD_RESUME_READY"
CHILD_TERMINAL = "CHILD_TERMINAL"
CHILD_RECOVERY_READY = "CHILD_RECOVERY_READY"
CHILD_QUALIFICATION_READY = "CHILD_QUALIFICATION_READY"
CHILD_QUALIFICATION_WAIT = "CHILD_QUALIFICATION_WAIT"
CHILD_PHASE_READY = "CHILD_PHASE_READY"
_CHILD_PHASES = frozenset(
    {
        "COUNCIL_RESULTS",
        "ROOT_SYNTHESIS",
        "HOST_COUNCIL_OUTCOME",
        "HOST_TRANSFER_USE",
        "HOST_CHILD_HANDOFF",
    }
)
_DURABLE_INFLIGHT_PHASES = frozenset(
    {"COUNCIL_RESULTS", "ROOT_SYNTHESIS", "HOST_COUNCIL_OUTCOME"}
)
BLOCK_EVO_CHILD_RUNTIME = "BLOCK_FACTORFORGE_CONSOLE_EVO_CHILD_RUNTIME_INVALID"
_STAGES = (
    "AUTHORING_ADMITTED",
    "CHILD_PREREGISTERED",
    "MATERIALIZATION_READY",
    "CHILD_MATERIALIZED",
    "POST_MATERIALIZATION_ADMITTED",
    "CONTAINER_ADMITTED",
    CHILD_EXECUTION_READY,
)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_HEX = frozenset("0123456789abcdef")


class EvoChildRuntimeError(RuntimeError):
    pass


class EvoChildAuthoringRunner(Protocol):
    def run_research_org_session(self, invocation: Any) -> Any: ...


def _fail(reason: str) -> EvoChildRuntimeError:
    return EvoChildRuntimeError(f"{BLOCK_EVO_CHILD_RUNTIME}:{reason}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _ref(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise _fail(f"artifact_missing_or_unsafe:{path.name}")
    return {
        "path": str(path.resolve(strict=True)),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _runtime_root(state: Path, job_id: str, child_report_id: str) -> Path:
    try:
        return ensure_host_private_job_subdirectory(
            state,
            job_id,
            ("evo-child-runtime", child_report_id),
            create=True,
        )
    except PrivateJobRootError as exc:
        raise _fail("unsafe_private_runtime_root") from exc


def _write_once(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise _fail(f"durable_stage_mismatch:{path.name}")
        return
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stage_path(root: Path, index: int, stage: str) -> Path:
    return root / f"stage__{index:02d}__{stage.lower()}.json"


def _record_stage(
    *,
    root: Path,
    store: Any,
    index: int,
    stage: str,
    identity: Mapping[str, str],
    parent_checkpoint: Mapping[str, Any],
    previous_receipt_id: str | None,
    artifacts: Mapping[str, Any],
    execution: Mapping[str, Any] | None = None,
    incident_workspace: Path | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    incident_report_id: str | None = None,
) -> dict[str, Any]:
    if _STAGES[index - 1] != stage:
        raise _fail("stage_order")
    core = {
        "receipt_type": "EVO_CHILD_RUNTIME_STAGE",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "stage_index": index,
        "stage": stage,
        "identity": dict(identity),
        "trusted_parent_checkpoint": dict(parent_checkpoint),
        "previous_stage_receipt_id": previous_receipt_id,
        "artifacts": dict(artifacts),
        "execution": dict(execution) if execution is not None else None,
        "authority": {
            "child_execution_allowed": stage == CHILD_EXECUTION_READY,
            "allowed_start_step": "3b" if stage == CHILD_EXECUTION_READY else None,
            "oos_release_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "skill_or_policy_mutation_allowed": False,
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    guarded = (
        oos_exposure_private_registry_guard(
            incident_trust_root,
            installation_id=str(incident_installation_id),
        )
        if incident_workspace is not None
        and incident_report_id is not None
        and incident_trust_root is not None
        and incident_installation_id is not None
        else nullcontext(None)
    )
    with guarded:
        if incident_workspace is not None and incident_report_id is not None:
            incident_reasons = formal_oos_incident_reasons(
                workspace_root=incident_workspace,
                report_id=incident_report_id,
                trust_root=incident_trust_root,
                installation_id=incident_installation_id,
            )
            if incident_reasons:
                raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
        receipt = store.sign("host_admission", core)
        path = _stage_path(root, index, stage)
        _write_once(path, _canonical_bytes(receipt))
    if store.verify(receipt, expected_issuer="host_admission"):
        raise _fail(f"stage_signature:{stage}")
    return {"path": path, "receipt": receipt, "ref": _ref(path)}


def _sign_runtime_receipt_under_incident_guard(
    *,
    workspace: Path,
    trust: Path,
    installation_id: str,
    report_id: str,
    store: Any,
    path: Path,
    core: Mapping[str, Any],
) -> dict[str, Any]:
    with oos_exposure_private_registry_guard(
        trust,
        installation_id=installation_id,
    ):
        reasons = formal_oos_incident_reasons(
            workspace_root=workspace,
            report_id=report_id,
            trust_root=trust,
            installation_id=installation_id,
        )
        if reasons:
            raise _fail("oos_exposure_incident:" + ",".join(reasons))
        receipt = store.sign("host_admission", dict(core))
        _write_once(path, _canonical_bytes(receipt))
        return receipt


def _assert_no_runtime_incident(
    *,
    workspace: Path,
    trust: Path,
    installation_id: str,
    report_id: str,
) -> None:
    reasons = formal_oos_incident_reasons(
        workspace_root=workspace,
        report_id=report_id,
        trust_root=trust,
        installation_id=installation_id,
    )
    if reasons:
        raise _fail("oos_exposure_incident:" + ",".join(reasons))


def _canonical_script(path: Path | str, *, engine_root: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise _fail("engine_script_symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(engine_root)
    except ValueError as exc:
        raise _fail("engine_script_outside_pinned_engine_root") from exc
    if not resolved.is_file():
        raise _fail("engine_script_missing")
    return resolved


def _run_child_materializer(
    *,
    script: Path,
    worktree: Path,
    workspace: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path,
    incident_installation_id: str,
) -> dict[str, Any]:
    argv = [
        sys.executable,
        str(script),
        "--factorforge-root",
        str(workspace),
        "--parent-report-id",
        parent_report_id,
        "--child-report-id",
        child_report_id,
        "--expected-host-trust-manifest-sha256",
        expected_host_trust_manifest_sha256,
        "--incident-trust-root",
        str(incident_trust_root),
        "--incident-installation-id",
        incident_installation_id,
    ]
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(worktree),
        "PYTHONDONTWRITEBYTECODE": "1",
        "FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE": "1",
    }
    completed = subprocess.run(
        argv,
        cwd=worktree,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        raise _fail(f"child_materializer_returncode:{completed.returncode}:{detail}")
    return {
        "argv": argv,
        "argv_sha256": stable_json_hash(argv),
        "script_sha256": _sha256(script),
        "returncode": completed.returncode,
    }


def _run_owned_process_group(
    argv: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
    launch_guard: Any = None,
) -> subprocess.CompletedProcess[str]:
    """Run a Host wrapper whose complete descendant tree is Host-owned.

    A timeout or Console exception must not leave a prefetch/finalizer child
    holding credentials or a stale writer behind.  On POSIX we create one
    session, terminate the whole process group, escalate, and reap the leader
    before returning control to the recovery classifier.
    """

    with launch_guard if launch_guard is not None else nullcontext():
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            tail_out, tail_err = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            tail_out, tail_err = process.communicate()
        raise subprocess.TimeoutExpired(
            argv,
            timeout_seconds,
            output=stdout + (tail_out or ""),
            stderr=stderr + (tail_err or ""),
        ) from None
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise


_EVO_AGENT_COMMAND_ORDER = (
    "run_step3b",
    "validate_step3b",
    "materialize_evo_pre_release_data",
    "run_step4",
    "validate_step4",
)
_PREFETCH_FROM_WORKSPACE = object()


def _validated_prefetch_receipt_ref(
    workspace: Path, child_report_id: str
) -> dict[str, Any] | None:
    receipt_path = (
        workspace
        / "runs"
        / child_report_id
        / f"evo_pre_release_data_receipt__{child_report_id}.json"
    )
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return None
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    unsigned = dict(receipt) if isinstance(receipt, dict) else {}
    content_sha256 = unsigned.pop("content_sha256", None)
    if (
        not isinstance(receipt, dict)
        or receipt.get("contract_version")
        != "factorforge_evo_pre_release_data_receipt_v1"
        or receipt.get("report_id") != child_report_id
        or receipt.get("authority")
        != "ULTIMATE_HOST_TRUSTED_FETCH_ONLY_NO_FACTOR_EXECUTION"
        or receipt.get("full_contract_input") is not True
        or content_sha256 != stable_json_hash(unsigned)
    ):
        return None
    return _ref(receipt_path)


def _validated_command_crash_boundary(
    *,
    workspace: Path,
    child_report_id: str,
    proof: Mapping[str, Any],
    prefetch_receipt: object = _PREFETCH_FROM_WORKSPACE,
) -> dict[str, Any] | None:
    commands = proof.get("commands")
    if not isinstance(commands, list):
        return None
    if any(
        not isinstance(item, Mapping)
        or item.get("returncode") != 0
        or item.get("status") != "PASS"
        for item in commands
    ):
        return None
    names = [str(item.get("name") or "") for item in commands]
    sequence: tuple[str, ...] | None = None
    for start_index in range(len(_EVO_AGENT_COMMAND_ORDER)):
        for end_index in range(start_index + 1, len(_EVO_AGENT_COMMAND_ORDER)):
            candidate = _EVO_AGENT_COMMAND_ORDER[start_index:end_index]
            if tuple(names) == candidate:
                sequence = candidate
                break
        if sequence is not None:
            break
    if sequence is None:
        return None
    last_command = sequence[-1]
    next_command = _EVO_AGENT_COMMAND_ORDER[
        _EVO_AGENT_COMMAND_ORDER.index(last_command) + 1
    ]
    required_stage = (
        last_command
        if last_command in {"run_step3b", "validate_step3b", "run_step4"}
        else "validate_step3b"
    )
    receipt_path = workspace / "runs" / child_report_id / (
        f"evo_pre_release_data_receipt__{child_report_id}.json"
    )
    prefetch_completed = (
        _EVO_AGENT_COMMAND_ORDER.index(last_command)
        >= _EVO_AGENT_COMMAND_ORDER.index("materialize_evo_pre_release_data")
        or _EVO_AGENT_COMMAND_ORDER.index(sequence[0])
        > _EVO_AGENT_COMMAND_ORDER.index("materialize_evo_pre_release_data")
    )
    if not prefetch_completed:
        if (
            prefetch_receipt is _PREFETCH_FROM_WORKSPACE
            and (receipt_path.exists() or receipt_path.is_symlink())
        ) or (
            prefetch_receipt is not _PREFETCH_FROM_WORKSPACE
            and prefetch_receipt is not None
        ):
            return None
        return {
            "boundary": f"{last_command.upper()}_COMPLETE",
            "command_prefix_sha256": stable_json_hash(commands),
            "completed_commands": list(sequence),
            "next_command": next_command,
            "required_start_step": (
                "3b" if next_command == "validate_step3b" else "4"
            ),
            "required_termination_stage": required_stage,
            "prefetch_receipt": None,
        }
    if prefetch_receipt is _PREFETCH_FROM_WORKSPACE:
        resolved_prefetch = _validated_prefetch_receipt_ref(
            workspace, child_report_id
        )
    elif isinstance(prefetch_receipt, Mapping):
        try:
            resolved_prefetch = _ref(
                Path(str(prefetch_receipt.get("path") or ""))
            )
        except EvoChildRuntimeError:
            return None
        if resolved_prefetch != dict(prefetch_receipt):
            return None
    else:
        resolved_prefetch = None
    if resolved_prefetch is None:
        return None
    return {
        "boundary": f"{last_command.upper()}_COMPLETE",
        "command_prefix_sha256": stable_json_hash(commands),
        "completed_commands": list(sequence),
        "next_command": next_command,
        "required_start_step": "4",
        "required_termination_stage": required_stage,
        "prefetch_receipt": resolved_prefetch,
    }


def _validated_step4_finalizer_boundary(
    *, workspace: Path, child_report_id: str, proof: Mapping[str, Any]
) -> dict[str, Any] | None:
    commands = proof.get("commands")
    if (
        not isinstance(commands, list)
        or any(
            not isinstance(item, Mapping)
            or item.get("returncode") != 0
            or item.get("status") != "PASS"
            for item in commands
        )
    ):
        return None
    names = tuple(str(item.get("name") or "") for item in commands)
    allowed = {
        _EVO_AGENT_COMMAND_ORDER[start_index:]
        for start_index in range(len(_EVO_AGENT_COMMAND_ORDER))
    }
    if names not in allowed or names[-1] != "validate_step4":
        return None
    prefetch_receipt = _validated_prefetch_receipt_ref(
        workspace, child_report_id
    )
    if prefetch_receipt is None:
        return None
    return {
        "boundary": "VALIDATE_STEP4_COMPLETE",
        "completed_commands": list(names),
        "command_prefix_sha256": stable_json_hash(commands),
        "prefetch_receipt": prefetch_receipt,
    }


def _materialize_command_recovery_admission(
    *,
    runtime_root: Path,
    store: Any,
    identity: Mapping[str, Any],
    inflight_path: Path,
    proof_path: Path,
    termination_path: Path,
    boundary: Mapping[str, Any],
    workspace: Path,
    trust: Path,
    installation_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    proof_bytes = proof_path.read_bytes()
    proof_sha = hashlib.sha256(proof_bytes).hexdigest()
    proof_snapshot_path = runtime_root / f"command_recovery_proof__{proof_sha}.json"
    _write_once(proof_snapshot_path, proof_bytes)
    core = {
        "receipt_type": "EVO_CHILD_COMMAND_RECOVERY_ADMISSION",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "status": "HOST_ADMITTED_EXACT_NEXT_COMMAND",
        "identity": dict(identity),
        "inflight_attempt": _ref(inflight_path),
        "running_proof": _ref(proof_snapshot_path),
        "workspace_proof_path": str(proof_path),
        "latest_container_termination": _ref(termination_path),
        "boundary": dict(boundary),
        "authority": {
            "exact_next_command": boundary["next_command"],
            "required_start_step": boundary["required_start_step"],
            "oos_release_allowed": False,
            "scientific_verdict_issued": False,
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    path = runtime_root / (
        "command_recovery__"
        f"{core['running_proof']['sha256'][:16]}__"
        f"{boundary['next_command']}.json"
    )
    receipt = _sign_runtime_receipt_under_incident_guard(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
        store=store,
        path=path,
        core=core,
    )
    return {"path": path, "receipt": receipt}


def validate_evo_child_command_recovery_admission(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    admission_path: Path | str,
    workspace_root: Path | str,
    verify_workspace_exact: bool = True,
) -> dict[str, Any]:
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    _assert_no_runtime_incident(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
    )
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    runtime_root = _runtime_root(state, job_id, child_report_id)
    path = Path(admission_path).expanduser().resolve(strict=True)
    try:
        path.relative_to(runtime_root)
    except ValueError as exc:
        raise _fail("command_recovery_admission_location") from exc
    receipt = _load_signed_private_receipt(path, store=store)
    expected_identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
    }
    boundary = receipt.get("boundary")
    authority = receipt.get("authority")
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    if (
        receipt.get("receipt_type") != "EVO_CHILD_COMMAND_RECOVERY_ADMISSION"
        or receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
        or receipt.get("status") != "HOST_ADMITTED_EXACT_NEXT_COMMAND"
        or receipt.get("identity") != expected_identity
        or not isinstance(boundary, Mapping)
        or boundary.get("next_command") not in _EVO_AGENT_COMMAND_ORDER[1:]
        or boundary.get("required_start_step") not in {"3b", "4"}
        or authority
        != {
            "exact_next_command": boundary.get("next_command"),
            "required_start_step": boundary.get("required_start_step"),
            "oos_release_allowed": False,
            "scientific_verdict_issued": False,
        }
        or content_sha != stable_json_hash(content)
    ):
        raise _fail("command_recovery_admission_shape")
    for key in (
        "inflight_attempt",
        "running_proof",
        "latest_container_termination",
    ):
        reference = receipt.get(key)
        if (
            not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256", "size_bytes"}
            or _ref(Path(str(reference.get("path") or ""))) != dict(reference)
        ):
            raise _fail(f"command_recovery_ref:{key}")
    try:
        proof_snapshot = json.loads(
            Path(str(receipt["running_proof"]["path"])).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("command_recovery_proof_snapshot") from exc
    projected_boundary = (
        _validated_command_crash_boundary(
            workspace=workspace,
            child_report_id=child_report_id,
            proof=proof_snapshot,
            prefetch_receipt=boundary.get("prefetch_receipt"),
        )
        if isinstance(proof_snapshot, Mapping)
        else None
    )
    if projected_boundary != dict(boundary):
        raise _fail("command_recovery_boundary_replay")
    termination = _load_signed_private_receipt(
        Path(str(receipt["latest_container_termination"]["path"])),
        store=store,
    )
    process_tree = termination.get("process_tree")
    if (
        termination.get("stage_name")
        != boundary.get("required_termination_stage")
        or not isinstance(process_tree, Mapping)
        or process_tree.get("process_tree_absent") is not True
    ):
        raise _fail("command_recovery_termination_replay")
    proof_path = Path(str(receipt.get("workspace_proof_path") or ""))
    try:
        expected_proof = (
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{child_report_id}.json"
        ).resolve(strict=False)
        if proof_path.resolve(strict=False) != expected_proof:
            raise ValueError
        snapshot_ref = receipt["running_proof"]
        if verify_workspace_exact and proof_path.is_file() and not proof_path.is_symlink():
            if _sha256(proof_path) != snapshot_ref["sha256"]:
                raise _fail("command_recovery_workspace_proof_changed")
    except ValueError as exc:
        raise _fail("command_recovery_proof_location") from exc
    return {
        "verdict": "PASS",
        "status": receipt["status"],
        "admission_path": path,
        "receipt": receipt,
    }


def _resolve_replayable_command_recovery(
    *,
    state: Path,
    trust: Path,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    workspace: Path,
    inflight_path: Path,
    proof: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Replay one prior admission when the resumed wrapper made no progress."""

    if proof is not None and proof.get("commands") != []:
        return None
    runtime_root = _runtime_root(state, job_id, child_report_id)
    matches: list[dict[str, Any]] = []
    inflight_ref = _ref(inflight_path)
    for candidate in sorted(runtime_root.glob("command_recovery__*.json")):
        try:
            resolution = validate_evo_child_command_recovery_admission(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                admission_path=candidate,
                workspace_root=workspace,
                verify_workspace_exact=False,
            )
        except (EvoChildRuntimeError, OSError, ValueError):
            continue
        receipt = resolution["receipt"]
        if receipt.get("inflight_attempt") == inflight_ref:
            matches.append(resolution)
    if len(matches) != 1:
        return None
    return matches[0]


def prepare_evo_child_execution(
    *,
    runner: EvoChildAuthoringRunner,
    state_root: Path | str,
    trust_root: Path | str,
    admissions_root: Path | str | None,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    trusted_parent_checkpoint: Mapping[str, Any],
    child_materializer_script: Path | str,
    ultimate_script: Path | str,
    engine_root: Path | str,
    container_runtime: Path | str,
    container_image_digest: str,
    container_memory: str,
    container_cpus: str,
    container_pids: int,
    container_tmpfs: str,
    research_base_commit: str,
    execution_engine_commit: str,
    catalog_snapshot_path: Path | str,
    catalog_projection_path: Path | str,
    calendar_snapshot_path: Path | str,
    calendar_projection_path: Path | str,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    if (
        not all(
            _SAFE_ID.fullmatch(value or "")
            for value in (job_id, installation_id, parent_report_id, child_report_id)
        )
        or parent_report_id == child_report_id
        or not _is_sha256(expected_host_trust_manifest_sha256)
        or re.fullmatch(r"[0-9a-f]{40,64}", research_base_commit or "") is None
        or re.fullmatch(r"[0-9a-f]{40,64}", execution_engine_commit or "") is None
        or not isinstance(trusted_parent_checkpoint, Mapping)
        or not _is_sha256(trusted_parent_checkpoint.get("ultimate_proof_sha256"))
    ):
        raise _fail("identity_pin_or_parent_checkpoint")
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    tree = Path(worktree).expanduser().resolve(strict=True)
    engine = Path(engine_root).expanduser().resolve(strict=True)
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=workspace,
        report_id=child_report_id,
        trust_root=trust,
        installation_id=installation_id,
    )
    if incident_reasons:
        raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
    try:
        workspace.relative_to(tree)
    except ValueError as exc:
        raise _fail("workspace_not_in_worktree") from exc
    materializer = _canonical_script(child_materializer_script, engine_root=engine)
    ultimate = _canonical_script(ultimate_script, engine_root=engine)
    runtime_root = _runtime_root(state, job_id, child_report_id)
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    parent_checkpoint = dict(trusted_parent_checkpoint)
    previous: str | None = None

    final_path = _stage_path(runtime_root, 7, CHILD_EXECUTION_READY)
    if final_path.is_file() and not final_path.is_symlink():
        final_receipt = _load_signed_private_receipt(final_path, store=store)
        final_unsigned = {
            key: value
            for key, value in final_receipt.items()
            if key not in {"contract_version", "issuer", "receipt_id", "signature"}
        }
        final_content = dict(final_unsigned)
        final_content_sha = final_content.pop("content_sha256", None)
        final_execution = final_receipt.get("execution")
        if (
            final_receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
            or final_receipt.get("stage") != CHILD_EXECUTION_READY
            or final_receipt.get("stage_index") != 7
            or final_receipt.get("identity") != identity
            or final_receipt.get("trusted_parent_checkpoint") != parent_checkpoint
            or final_content_sha != stable_json_hash(final_content)
            or not isinstance(final_execution, Mapping)
            or final_execution.get("start_step") != "3b"
            or final_execution.get("argv_sha256")
            != stable_json_hash(final_execution.get("argv"))
            or final_execution.get("research_base_commit")
            != research_base_commit
            or final_execution.get("execution_engine_commit")
            != execution_engine_commit
        ):
            raise _fail("execution_ready_replay")
        _validate_artifact_refs(final_receipt.get("artifacts"))
        container_reference = final_receipt["artifacts"].get(
            "container_admission"
        )
        if not isinstance(container_reference, Mapping):
            raise _fail("execution_ready_container_ref")
        validate_evo_child_container_admission(
            admission_path=str(container_reference["path"]),
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            workspace_root=workspace,
            worktree=tree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_trust_manifest_sha256,
        )
        return {
            "verdict": "PASS",
            "status": CHILD_EXECUTION_READY,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
            "checkpoint_path": str(final_path),
            "checkpoint_sha256": _sha256(final_path),
            "checkpoint_receipt_id": final_receipt["receipt_id"],
            "ultimate_argv": list(final_execution["argv"]),
            "research_base_commit": final_execution["research_base_commit"],
            "execution_engine_commit": final_execution[
                "execution_engine_commit"
            ],
            "container_admission_path": str(container_reference["path"]),
            "catalog_snapshot_path": str(
                final_receipt["artifacts"]["catalog_snapshot"]["path"]
            ),
            "catalog_projection_path": str(
                final_receipt["artifacts"]["catalog_projection"]["path"]
            ),
            "calendar_snapshot_path": str(
                final_receipt["artifacts"]["calendar_snapshot"]["path"]
            ),
            "calendar_projection_path": str(
                final_receipt["artifacts"]["calendar_projection"]["path"]
            ),
            "materialization_admission": {"idempotent_replay": True},
            "idempotent_replay": True,
        }

    authoring = run_and_admit_evo_child_authoring(
        runner=runner,
        workspace_root=workspace,
        worktree=tree,
        private_root=runtime_root / "authoring-private",
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        trust_root=trust,
        installation_id=installation_id,
        timeout_seconds=timeout_seconds,
    )
    semantic = authoring["semantic_bundle"]
    if set(semantic) != {
        "research_state",
        "research_conjecture",
        "approach_registry",
        "base_search_trial_ledger",
        "agent_authored_child_web_research_plan",
    }:
        raise _fail("agent_semantic_bundle_shape")
    authoring_path = evo_child_authoring_admission_path(workspace, child_report_id)
    assurance = materialize_evo_child_assurance(
        runner=runner,
        workspace_root=workspace,
        worktree=tree,
        private_root=runtime_root / "review-private",
        trust_root=trust,
        installation_id=installation_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        timeout_seconds=timeout_seconds,
    )
    stage = _record_stage(
        root=runtime_root,
        store=store,
        index=1,
        stage=_STAGES[0],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={
            "authoring_admission": _ref(authoring_path),
            "revision_child_assurance": _ref(Path(assurance["assurance_path"])),
        },
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    previous = stage["receipt"]["receipt_id"]

    ledger = project_authorized_evo_child_search_trial_ledger(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        base_search_trial_ledger=semantic["base_search_trial_ledger"],
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    metric = project_evo_child_metric_verifier_spec(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        research_conjecture=semantic["research_conjecture"],
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    threshold = project_evo_child_threshold_registration(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        research_conjecture=semantic["research_conjecture"],
        search_trial_ledger=ledger,
        metric_verifier_spec=metric,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    materialize_evo_child_preregistration(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        research_state=semantic["research_state"],
        research_conjecture=semantic["research_conjecture"],
        approach_registry=semantic["approach_registry"],
        base_search_trial_ledger=semantic["base_search_trial_ledger"],
        metric_verifier_spec=metric,
        threshold_registration=threshold,
        agent_authored_child_web_research_plan=semantic[
            "agent_authored_child_web_research_plan"
        ],
        agent_authoring_admission=authoring_path,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    prereg_path = child_preregistration_receipt_path(workspace, child_report_id)
    stage = _record_stage(
        root=runtime_root,
        store=store,
        index=2,
        stage=_STAGES[1],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={"preregistration_receipt": _ref(prereg_path)},
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    previous = stage["receipt"]["receipt_id"]

    materialize_public_child_materialization_ticket(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        trust_root=trust,
        installation_id=installation_id,
        admissions_root=admissions_root,
        materialization_ready=True,
    )
    ready_path = public_child_materialization_ticket_path(
        workspace, child_report_id, materialization_ready=True
    )
    ticket, ticket_reasons = validate_public_child_materialization_ticket(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        require_materialization_ready=True,
        exact_ticket_path=ready_path,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    if ticket is None or ticket_reasons:
        raise _fail("ready_ticket_replay:" + ",".join(ticket_reasons))
    stage = _record_stage(
        root=runtime_root,
        store=store,
        index=3,
        stage=_STAGES[2],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={"materialization_ready_ticket": _ref(ready_path)},
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    previous = stage["receipt"]["receipt_id"]

    materializer_run = _run_child_materializer(
        script=materializer,
        worktree=tree,
        workspace=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    report_path = child_materialization_report_path(
        workspace, parent_report_id, child_report_id
    )
    stage = _record_stage(
        root=runtime_root,
        store=store,
        index=4,
        stage=_STAGES[3],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={"child_materialization_report": _ref(report_path)},
        execution=materializer_run,
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    previous = stage["receipt"]["receipt_id"]

    admission_result = materialize_evo_child_materialization_admission(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        trust_root=trust,
        installation_id=installation_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    admission, admission_reasons = validate_evo_child_materialization_admission(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    if admission is None or admission_reasons:
        raise _fail("materialization_admission_replay:" + ",".join(admission_reasons))
    admission_path = child_materialization_admission_path(workspace, child_report_id)
    stage = _record_stage(
        root=runtime_root,
        store=store,
        index=5,
        stage=_STAGES[4],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={
            "child_materialization_admission": _ref(admission_path),
            "child_materialization_report": _ref(report_path),
        },
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    previous = stage["receipt"]["receipt_id"]

    container_result = materialize_evo_child_container_admission(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        workspace_root=workspace,
        worktree=tree,
        engine_root=engine,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        container_runtime=container_runtime,
        image_digest=container_image_digest,
        memory=container_memory,
        cpus=container_cpus,
        pids=container_pids,
        tmpfs=container_tmpfs,
        engine_commit=execution_engine_commit,
        catalog_snapshot_path=catalog_snapshot_path,
        catalog_projection_path=catalog_projection_path,
        calendar_projection_path=calendar_projection_path,
    )
    container_resolution = validate_evo_child_container_admission(
        admission_path=container_result["admission_path"],
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        workspace_root=workspace,
        worktree=tree,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_pin=expected_host_trust_manifest_sha256,
    )
    stage = _record_stage(
        root=runtime_root,
        store=store,
        index=6,
        stage=_STAGES[5],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={
            "container_admission": _ref(
                Path(container_result["admission_path"])
            ),
        },
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    previous = stage["receipt"]["receipt_id"]

    plan_resolution = validate_and_resolve_evo_child_web_research_plan(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    plan = plan_resolution["raw_plan"]
    plan_identity = plan.get("identity") if isinstance(plan, Mapping) else {}
    argv = [
        sys.executable,
        str(ultimate),
        "--report-id",
        child_report_id,
        "--start-step",
        "3b",
        "--end-step",
        "all",
        "--factorforge-root",
        str(tree),
        "--factor-workspace",
        str(workspace),
        "--factor-id",
        str(plan_identity.get("factor_id") or ""),
        "--research-id",
        str(plan_identity.get("research_id") or ""),
        "--research-org-mode",
        "off",
        "--research-org-runtime-mode",
        "revision-child-assured",
        "--research-org-runtime-private-root",
        str(state / "jobs" / job_id / "research_org_private"),
        "--research-org-runtime-trust-root",
        str(trust),
        "--research-org-runtime-installation-id",
        installation_id,
        "--evo-child-research-org-assurance",
        str(assurance["assurance_path"]),
        "--expected-host-trust-manifest-sha256",
        expected_host_trust_manifest_sha256,
        "--agent-execution-container-admission",
        str(container_resolution["admission_path"]),
    ]
    if not all(str(value).strip() for value in (plan_identity.get("factor_id"), plan_identity.get("research_id"))):
        raise _fail("child_plan_identity")
    execution = {
        "argv": argv,
        "argv_sha256": stable_json_hash(argv),
        "ultimate_script_sha256": _sha256(ultimate),
        "cwd": str(tree),
        "start_step": "3b",
        "credential_environment": "HOST_PREFETCH_ONLY_AGENT_STAGES_STRIPPED",
        "container_admission_sha256": _sha256(
            Path(container_resolution["admission_path"])
        ),
        "research_base_commit": research_base_commit,
        "execution_engine_commit": execution_engine_commit,
    }
    final = _record_stage(
        root=runtime_root,
        store=store,
        index=7,
        stage=_STAGES[6],
        identity=identity,
        parent_checkpoint=parent_checkpoint,
        previous_receipt_id=previous,
        artifacts={
            "authoring_admission": _ref(authoring_path),
            "revision_child_assurance": _ref(Path(assurance["assurance_path"])),
            "preregistration_receipt": _ref(prereg_path),
            "materialization_ready_ticket": _ref(ready_path),
            "child_materialization_report": _ref(report_path),
            "child_materialization_admission": _ref(admission_path),
            "container_admission": _ref(
                Path(container_result["admission_path"])
            ),
            "child_web_research_plan": _ref(Path(plan_resolution["plan_path"])),
            "catalog_snapshot": _ref(Path(catalog_snapshot_path)),
            "catalog_projection": _ref(Path(catalog_projection_path)),
            "calendar_snapshot": _ref(Path(calendar_snapshot_path)),
            "calendar_projection": _ref(Path(calendar_projection_path)),
            "ultimate_script": _ref(ultimate),
        },
        execution=execution,
        incident_workspace=workspace,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
        incident_report_id=child_report_id,
    )
    return {
        "verdict": "PASS",
        "status": CHILD_EXECUTION_READY,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "checkpoint_path": str(final["path"]),
        "checkpoint_sha256": final["ref"]["sha256"],
        "checkpoint_receipt_id": final["receipt"]["receipt_id"],
        "ultimate_argv": argv,
        "research_base_commit": research_base_commit,
        "execution_engine_commit": execution_engine_commit,
        "container_admission_path": str(
            container_resolution["admission_path"]
        ),
        "catalog_snapshot_path": str(Path(catalog_snapshot_path).resolve(strict=True)),
        "catalog_projection_path": str(Path(catalog_projection_path).resolve(strict=True)),
        "calendar_snapshot_path": str(Path(calendar_snapshot_path).resolve(strict=True)),
        "calendar_projection_path": str(Path(calendar_projection_path).resolve(strict=True)),
        "materialization_admission": admission_result,
    }


def _load_signed_private_receipt(path: Path, *, store: Any) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise _fail("signed_private_receipt_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("signed_private_receipt_json") from exc
    if not isinstance(payload, dict) or store.verify(
        payload, expected_issuer="host_admission"
    ):
        raise _fail("signed_private_receipt_signature")
    return payload


def _validate_artifact_refs(refs: Any) -> None:
    if not isinstance(refs, Mapping) or not refs:
        raise _fail("execution_checkpoint_artifacts")
    for label, reference in refs.items():
        if (
            not isinstance(label, str)
            or not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256", "size_bytes"}
            or not _is_sha256(reference.get("sha256"))
        ):
            raise _fail("execution_checkpoint_artifact_shape")
        path = Path(str(reference.get("path") or ""))
        if (
            path.is_symlink()
            or not path.is_file()
            or _sha256(path) != reference.get("sha256")
            or path.stat().st_size != reference.get("size_bytes")
        ):
            raise _fail(f"execution_checkpoint_artifact_changed:{label}")


def _workspace_evidence_tree(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise _fail(f"workspace_evidence_symlink:{relative}")
        if path.is_file():
            entries[relative] = _sha256(path)
        elif not path.is_dir():
            raise _fail(f"workspace_evidence_nonregular:{relative}")
    return entries


def _replace_argv_value(argv: list[str], option: str, value: str) -> list[str]:
    matches = [index for index, item in enumerate(argv) if item == option]
    if len(matches) != 1 or matches[0] + 1 >= len(argv):
        raise _fail(f"execution_argv_option:{option}")
    projected = list(argv)
    projected[matches[0] + 1] = value
    return projected


def _load_evo_child_execution_receipt(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
    verify_workspace_exact: bool,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    _assert_no_runtime_incident(
        workspace=workspace, trust=trust,
        installation_id=installation_id, report_id=child_report_id,
    )
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    path = Path(execution_receipt_path).expanduser().resolve(strict=True)
    expected_root = (
        state / "jobs" / job_id / "evo-child-runtime" / child_report_id
    ).resolve(strict=True)
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise _fail("execution_receipt_outside_job_state") from exc
    receipt = _load_signed_private_receipt(path, store=store)
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    proof = receipt.get("proof")
    previous_proof = receipt.get("previous_proof")
    evidence_ref = receipt.get("child_evidence_tree")
    resume_admission = receipt.get("resume_admission")
    inflight_ref = receipt.get("inflight_attempt")
    container_termination = receipt.get("container_termination")
    command_recovery = receipt.get("command_recovery")
    authority = receipt.get("authority")
    if (
        receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
        or receipt.get("receipt_type") != "EVO_CHILD_ULTIMATE_EXECUTION"
        or receipt.get("identity") != identity
        or receipt.get("status")
        not in {CHILD_RESUME_READY, CHILD_RECOVERY_READY, CHILD_TERMINAL}
        or content_sha != stable_json_hash(content)
        or (
            proof is not None
            and (
                not isinstance(proof, Mapping)
                or set(proof) != {"path", "sha256", "size_bytes"}
            )
        )
        or (proof is None and receipt.get("status") != CHILD_RECOVERY_READY)
        or not isinstance(evidence_ref, Mapping)
        or set(evidence_ref) != {"path", "sha256", "size_bytes"}
        or (
            previous_proof is not None
            and (
                not isinstance(previous_proof, Mapping)
                or set(previous_proof) != {"path", "sha256", "size_bytes"}
                or (
                    isinstance(proof, Mapping)
                    and previous_proof.get("sha256") == proof.get("sha256")
                    and receipt.get("status") != CHILD_RECOVERY_READY
                )
            )
        )
        or not isinstance(authority, Mapping)
        or not isinstance(inflight_ref, Mapping)
        or set(inflight_ref) != {"path", "sha256", "size_bytes"}
        or (
            container_termination is not None
            and (
                not isinstance(container_termination, Mapping)
                or set(container_termination)
                != {
                    "receipt",
                    "receipt_id",
                    "stage_name",
                    "process_tree_absent",
                }
                or container_termination.get("process_tree_absent") is not True
            )
        )
        or (
            resume_admission is not None
            and (
                not isinstance(resume_admission, Mapping)
                or set(resume_admission) != {"path", "sha256", "size_bytes"}
            )
        )
    ):
        raise _fail("execution_receipt_exact_replay")
    if isinstance(proof, Mapping):
        proof_path = Path(str(proof.get("path") or ""))
        if (
            proof_path.is_symlink()
            or not proof_path.is_file()
            or _sha256(proof_path) != proof.get("sha256")
            or proof_path.stat().st_size != proof.get("size_bytes")
        ):
            raise _fail("execution_receipt_proof_changed")
    if isinstance(container_termination, Mapping):
        termination_ref = container_termination.get("receipt")
        if (
            not isinstance(termination_ref, Mapping)
            or set(termination_ref) != {"path", "sha256", "size_bytes"}
        ):
            raise _fail("execution_receipt_container_termination")
        termination_path = Path(str(termination_ref.get("path") or ""))
        expected_container_root = (
            state
            / "jobs"
            / job_id
            / "evo-child-container"
            / child_report_id
        ).resolve(strict=True)
        try:
            termination_path.resolve(strict=True).relative_to(
                expected_container_root
            )
            termination = _load_signed_private_receipt(
                termination_path, store=store
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise _fail("execution_receipt_container_termination") from exc
        if (
            _ref(termination_path) != dict(termination_ref)
            or termination.get("receipt_type")
            != "EVO_CHILD_AGENT_STAGE_CONTAINER_TERMINATION"
            or termination.get("receipt_id")
            != container_termination.get("receipt_id")
            or termination.get("stage_name")
            != container_termination.get("stage_name")
            or termination.get("identity")
            != {
                "installation_id": installation_id,
                "job_id": job_id,
                "parent_report_id": parent_report_id,
                "child_report_id": child_report_id,
            }
            or termination.get("process_tree", {}).get("process_tree_absent")
            is not True
        ):
            raise _fail("execution_receipt_container_termination")
    if command_recovery is not None:
        if not isinstance(command_recovery, Mapping):
            raise _fail("execution_receipt_command_recovery")
        recovery_ref = command_recovery.get("recovery_admission")
        if (
            not isinstance(recovery_ref, Mapping)
            or set(recovery_ref) != {"path", "sha256", "size_bytes"}
        ):
            raise _fail("execution_receipt_command_recovery_ref")
        recovery_resolution = validate_evo_child_command_recovery_admission(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            admission_path=str(recovery_ref.get("path") or ""),
            workspace_root=workspace,
            verify_workspace_exact=False,
        )
        expected_recovery = dict(recovery_resolution["receipt"]["boundary"])
        expected_recovery.update(
            {
                "recovery_admission": dict(recovery_ref),
                "replayed_signed_admission": command_recovery.get(
                    "replayed_signed_admission"
                ),
                "resumed_argv_sha256": command_recovery.get(
                    "resumed_argv_sha256"
                ),
            }
        )
        if (
            dict(command_recovery) != expected_recovery
            or not isinstance(command_recovery.get("replayed_signed_admission"), bool)
            or not _is_sha256(command_recovery.get("resumed_argv_sha256"))
        ):
            raise _fail("execution_receipt_command_recovery_binding")
    evidence_path = Path(str(evidence_ref.get("path") or ""))
    try:
        evidence_path.relative_to(expected_root)
        evidence_raw = evidence_path.read_bytes()
        evidence = json.loads(evidence_raw.decode("utf-8"))
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("execution_receipt_evidence_tree") from exc
    evidence_unsigned = dict(evidence) if isinstance(evidence, dict) else {}
    evidence_content_sha = evidence_unsigned.pop("content_sha256", None)
    if (
        evidence_path.is_symlink()
        or not evidence_path.is_file()
        or _sha256(evidence_path) != evidence_ref.get("sha256")
        or len(evidence_raw) != evidence_ref.get("size_bytes")
        or evidence_content_sha != stable_json_hash(evidence_unsigned)
        or evidence.get("job_id") != job_id
        or evidence.get("child_report_id") != child_report_id
        or (
            verify_workspace_exact
            and evidence.get("entries") != _workspace_evidence_tree(workspace)
        )
    ):
        raise _fail("execution_receipt_evidence_tree")
    status = str(receipt["status"])
    expected_start = receipt.get("resume_start_step")
    if status == CHILD_RESUME_READY and expected_start not in {"4", "5", "6"}:
        raise _fail("execution_receipt_resume_step")
    if status == CHILD_RECOVERY_READY and (
        expected_start != "6" or authority.get("finalizer_only") is not True
    ):
        raise _fail("execution_receipt_recovery_authority")
    if status == CHILD_TERMINAL and expected_start is not None:
        raise _fail("execution_receipt_terminal_resume")
    inflight_path = Path(str(inflight_ref.get("path") or ""))
    try:
        inflight_path.relative_to(expected_root)
    except ValueError as exc:
        raise _fail("execution_receipt_inflight") from exc
    inflight = _load_signed_private_receipt(inflight_path, store=store)
    if (
        _ref(inflight_path) != dict(inflight_ref)
        or inflight.get("receipt_type") != "EVO_CHILD_ULTIMATE_INFLIGHT"
        or inflight.get("identity") != identity
        or inflight.get("attempt") != receipt.get("attempt")
        or (
            command_recovery is None
            and inflight.get("start_step") != receipt.get("start_step")
        )
        or (
            isinstance(command_recovery, Mapping)
            and command_recovery.get("required_start_step")
            != receipt.get("start_step")
        )
        or inflight.get("argv_sha256") != receipt.get("argv_sha256")
        or inflight.get("resume_admission") != receipt.get("resume_admission")
        or inflight.get("previous_execution_receipt_id")
        != receipt.get("previous_execution_receipt_id")
    ):
        raise _fail("execution_receipt_inflight")
    start_step = str(receipt.get("start_step") or "")
    if start_step == "6" and resume_admission is None:
        raise _fail("execution_receipt_step6_admission_missing")
    if resume_admission is not None:
        admission_path = Path(str(resume_admission.get("path") or ""))
        try:
            admission_path.relative_to(expected_root)
        except ValueError as exc:
            raise _fail("execution_receipt_resume_admission") from exc
        admission = _load_signed_private_receipt(admission_path, store=store)
        admission_type = admission.get("receipt_type")
        prior_binding = (
            admission.get("receipt_id")
            if admission_type == "EVO_CHILD_ULTIMATE_EXECUTION"
            else admission.get("prior_execution_receipt_id")
        )
        if (
            _ref(admission_path) != dict(resume_admission)
            or admission_type
            not in {
                "EVO_CHILD_HOST_QUALIFICATION",
                "EVO_CHILD_DURABLE_PHASE",
                "EVO_CHILD_ULTIMATE_EXECUTION",
            }
            or admission.get("identity") != identity
            or admission.get("resume_start_step") != start_step
            or prior_binding != receipt.get("previous_execution_receipt_id")
            or (
                admission_type == "EVO_CHILD_ULTIMATE_EXECUTION"
                and (
                    admission.get("status") != CHILD_RECOVERY_READY
                    or admission.get("authority", {}).get("finalizer_only")
                    is not True
                )
            )
        ):
            raise _fail("execution_receipt_resume_admission")
    return receipt, path, evidence


def validate_evo_child_execution_state(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    receipt, path, _evidence = _load_evo_child_execution_receipt(
        state_root=state_root,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace_root,
        verify_workspace_exact=True,
    )
    status = str(receipt["status"])
    expected_start = receipt.get("resume_start_step")
    return {
        "verdict": "PASS",
        "status": status,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "resume_start_step": expected_start,
        "execution_receipt_path": str(path),
        "execution_receipt_sha256": _sha256(path),
        "receipt": receipt,
    }


def load_evo_child_execution_baseline(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    receipt, path, evidence = _load_evo_child_execution_receipt(
        state_root=state_root,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace_root,
        verify_workspace_exact=False,
    )
    proof = receipt.get("proof")
    authority = receipt.get("authority")
    return {
        "verdict": "PASS",
        "status": receipt["status"],
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "resume_start_step": receipt.get("resume_start_step"),
        "execution_receipt_path": str(path),
        "execution_receipt_sha256": _sha256(path),
        "proof_path": (
            str(proof.get("path")) if isinstance(proof, Mapping) else None
        ),
        "proof_sha256": (
            str(proof.get("sha256")) if isinstance(proof, Mapping) else None
        ),
        "returncode": receipt.get("returncode"),
        "proof_status": receipt.get("proof_status"),
        "scientific_factor_verdict": (
            authority.get("factor_verdict")
            if isinstance(authority, Mapping)
            and authority.get("scientific_verdict_issued") is True
            else "NOT_ISSUED"
        ),
        "terminal_checkpoint": False,
        "host_execution_receipt_verified": True,
        "receipt": receipt,
        "entries": dict(evidence["entries"]),
    }


def load_latest_evo_child_execution_baseline(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    state = Path(state_root).expanduser().resolve(strict=True)
    runtime_root = (
        state / "jobs" / job_id / "evo-child-runtime" / child_report_id
    ).resolve(strict=True)
    paths = sorted(runtime_root.glob("execution__*.json"))
    if not paths or any(path.is_symlink() or not path.is_file() for path in paths):
        raise _fail("latest_execution_receipt_missing_or_unsafe")
    return load_evo_child_execution_baseline(
        state_root=state,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=paths[-1],
        workspace_root=workspace_root,
    )


def _qualification_paths(runtime_root: Path, attempt: int) -> tuple[Path, Path]:
    return (
        runtime_root / f"qualification__{attempt:04d}.json",
        runtime_root / f"qualification_evidence_tree__{attempt:04d}.json",
    )


def _validate_child_is_checkpoint(
    *,
    workspace: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    incident_trust_root: Path,
    incident_installation_id: str,
) -> dict[str, Any]:
    resolution = validate_and_resolve_evo_child_web_research_plan(
        workspace_root=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
        incident_trust_root=incident_trust_root,
        incident_installation_id=incident_installation_id,
    )
    allocation = resolution.get("allocation")
    token_hash = (
        str(allocation.get("sealed_token_sha256") or "")
        if isinstance(allocation, Mapping)
        else None
    )
    return validate_web_evo_is_checkpoint(
        workspace,
        dict(resolution["raw_plan"]),
        oos_release_token_hash=token_hash,
    )


def materialize_evo_child_qualification_checkpoint(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    """Admit only the exact Host qualification delta after a child IS pause.

    The semantic qualification remains an external Host decision.  This
    function verifies its signed lifecycle CAS, the purged-IS checkpoint and
    the complete workspace delta before issuing a new private execution
    baseline.  An unchanged or only partially completed lifecycle returns a
    durable wait result and never authorizes Step 6.
    """

    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        prior.get("status") != CHILD_RESUME_READY
        or prior.get("resume_start_step") != "6"
    ):
        raise _fail("qualification_prior_resume_state")
    proof_ref = prior.get("proof")
    if not isinstance(proof_ref, Mapping):
        raise _fail("qualification_prior_proof")
    proof_path = Path(str(proof_ref.get("path") or ""))
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("qualification_prior_proof_json") from exc
    if (
        not isinstance(proof, Mapping)
        or proof.get("report_id") != child_report_id
        or proof.get("status") != "PAUSED"
        or proof.get("final_outcome")
        != "awaiting_evo_v2_host_qualification"
        or proof.get("proof_semantics")
        != "purged_is_checkpoint_only_awaiting_host_qualification"
    ):
        raise _fail("qualification_prior_proof_semantics")
    checkpoint = _validate_child_is_checkpoint(
        workspace=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    assessment = assess_evo_v2_external_resume(
        workspace_root=workspace,
        report_id=child_report_id,
        proof=proof,
        attested_entries=prior_evidence.get("entries"),
        trust_root=trust,
        installation_id=installation_id,
        trusted_lifecycle_manifest=store.public_manifest,
        # Genesis is frozen by the strict child preregistration receipt; every
        # transition after it is still a signed Host lifecycle event.
        require_signed_lifecycle_genesis=False,
    )
    if assessment.status == PROGRESS_WAITING:
        return {
            "verdict": "PASS",
            "status": CHILD_QUALIFICATION_WAIT,
            "child_report_id": child_report_id,
            "resume_start_step": None,
            "reason": assessment.reason,
            "current_lifecycle_state": assessment.current_lifecycle_state,
        }
    if (
        assessment.status != PROGRESS_HOST_CHECKPOINT_READY
        or assessment.start_step != "6"
        or assessment.current_lifecycle_state
        not in {"NO_QUALIFIED_CONTRADICTION", "QUALIFIED_CONTRADICTION"}
    ):
        raise _fail("qualification_assessment_not_ready")

    runtime_root = _runtime_root(state, job_id, child_report_id)
    attempt = int(prior.get("attempt") or 0)
    receipt_path, evidence_path = _qualification_paths(runtime_root, attempt)
    evidence_payload = {
        "version": "factorforge_console_evo_child_qualification_evidence_v1",
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "prior_execution_receipt_id": prior["receipt_id"],
        "entries": _workspace_evidence_tree(workspace),
    }
    evidence_payload["content_sha256"] = stable_json_hash(evidence_payload)
    _write_once(evidence_path, _canonical_bytes(evidence_payload))
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
    }
    lifecycle_path = (
        workspace / "objects" / "evo_v2" / child_report_id / "lifecycle.json"
    )
    core = {
        "receipt_type": "EVO_CHILD_HOST_QUALIFICATION",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "status": CHILD_QUALIFICATION_READY,
        "identity": identity,
        "prior_execution": _ref(prior_path),
        "prior_execution_receipt_id": prior["receipt_id"],
        "prior_evidence_tree": dict(prior["child_evidence_tree"]),
        "is_checkpoint": dict(checkpoint),
        "lifecycle": _ref(lifecycle_path),
        "external_resume_assessment": assessment.to_dict(),
        "rebaseline_evidence_tree": _ref(evidence_path),
        "resume_start_step": "6",
        "authority": {
            "closed_host_delta_verified": True,
            "child_step6_allowed": True,
            "parent_execution_allowed": False,
            "oos_release_allowed": assessment.current_lifecycle_state
            == "NO_QUALIFIED_CONTRADICTION",
            "revision_council_allowed": assessment.current_lifecycle_state
            == "QUALIFIED_CONTRADICTION",
            "scientific_factor_verdict": "NOT_ISSUED",
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    receipt = _sign_runtime_receipt_under_incident_guard(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
        store=store,
        path=receipt_path,
        core=core,
    )
    return validate_evo_child_qualification_checkpoint(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        qualification_receipt_path=receipt_path,
        workspace_root=workspace,
    )


def validate_evo_child_qualification_checkpoint(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    qualification_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    _assert_no_runtime_incident(
        workspace=workspace, trust=trust,
        installation_id=installation_id, report_id=child_report_id,
    )
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    expected_root = (
        state / "jobs" / job_id / "evo-child-runtime" / child_report_id
    ).resolve(strict=True)
    path = Path(qualification_receipt_path).expanduser().resolve(strict=True)
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise _fail("qualification_receipt_outside_job_state") from exc
    receipt = _load_signed_private_receipt(path, store=store)
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
    }
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    authority = receipt.get("authority")
    assessment_payload = receipt.get("external_resume_assessment")
    assessment_state = (
        assessment_payload.get("current_lifecycle_state")
        if isinstance(assessment_payload, Mapping)
        else None
    )
    prior_ref = receipt.get("prior_execution")
    evidence_ref = receipt.get("rebaseline_evidence_tree")
    if (
        receipt.get("receipt_type") != "EVO_CHILD_HOST_QUALIFICATION"
        or receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
        or receipt.get("status") != CHILD_QUALIFICATION_READY
        or receipt.get("identity") != identity
        or receipt.get("resume_start_step") != "6"
        or content_sha != stable_json_hash(content)
        or not isinstance(prior_ref, Mapping)
        or set(prior_ref) != {"path", "sha256", "size_bytes"}
        or not isinstance(evidence_ref, Mapping)
        or set(evidence_ref) != {"path", "sha256", "size_bytes"}
        or authority
        != {
            "closed_host_delta_verified": True,
            "child_step6_allowed": True,
            "parent_execution_allowed": False,
            "oos_release_allowed": assessment_state
            == "NO_QUALIFIED_CONTRADICTION",
            "revision_council_allowed": assessment_state
            == "QUALIFIED_CONTRADICTION",
            "scientific_factor_verdict": "NOT_ISSUED",
        }
    ):
        raise _fail("qualification_receipt_exact_replay")
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=str(prior_ref.get("path") or ""),
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        _ref(prior_path) != dict(prior_ref)
        or prior.get("receipt_id") != receipt.get("prior_execution_receipt_id")
        or prior.get("child_evidence_tree") != receipt.get("prior_evidence_tree")
    ):
        raise _fail("qualification_prior_execution_binding")
    checkpoint = _validate_child_is_checkpoint(
        workspace=workspace,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        incident_trust_root=trust,
        incident_installation_id=installation_id,
    )
    if checkpoint != receipt.get("is_checkpoint"):
        raise _fail("qualification_is_checkpoint_binding")
    proof_ref = prior.get("proof")
    if not isinstance(proof_ref, Mapping):
        raise _fail("qualification_prior_proof")
    proof = json.loads(Path(str(proof_ref["path"])).read_text(encoding="utf-8"))
    assessment = assess_evo_v2_external_resume(
        workspace_root=workspace,
        report_id=child_report_id,
        proof=proof,
        attested_entries=prior_evidence.get("entries"),
        trust_root=trust,
        installation_id=installation_id,
        trusted_lifecycle_manifest=store.public_manifest,
        require_signed_lifecycle_genesis=False,
    )
    if (
        assessment.status != PROGRESS_HOST_CHECKPOINT_READY
        or assessment.start_step != "6"
        or assessment.to_dict() != receipt.get("external_resume_assessment")
    ):
        raise _fail("qualification_assessment_replay")
    lifecycle_ref = receipt.get("lifecycle")
    lifecycle_path = (
        workspace / "objects" / "evo_v2" / child_report_id / "lifecycle.json"
    )
    if not isinstance(lifecycle_ref, Mapping) or _ref(lifecycle_path) != dict(
        lifecycle_ref
    ):
        raise _fail("qualification_lifecycle_binding")
    evidence_path = Path(str(evidence_ref.get("path") or ""))
    try:
        evidence_path.relative_to(expected_root)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("qualification_evidence_tree") from exc
    evidence_unsigned = dict(evidence) if isinstance(evidence, dict) else {}
    evidence_sha = evidence_unsigned.pop("content_sha256", None)
    if (
        _ref(evidence_path) != dict(evidence_ref)
        or evidence_sha != stable_json_hash(evidence_unsigned)
        or evidence.get("job_id") != job_id
        or evidence.get("parent_report_id") != parent_report_id
        or evidence.get("child_report_id") != child_report_id
        or evidence.get("prior_execution_receipt_id") != prior["receipt_id"]
        or evidence.get("entries") != _workspace_evidence_tree(workspace)
    ):
        raise _fail("qualification_evidence_tree")
    return {
        "verdict": "PASS",
        "status": CHILD_QUALIFICATION_READY,
        "child_report_id": child_report_id,
        "resume_start_step": "6",
        "current_lifecycle_state": assessment.current_lifecycle_state,
        "qualification_receipt_path": str(path),
        "qualification_receipt_sha256": _sha256(path),
        "receipt": receipt,
    }


def _phase_slug(phase: str) -> str:
    if phase not in _CHILD_PHASES:
        raise _fail("child_phase_identity")
    return phase.lower()


def _phase_inflight_paths(
    runtime_root: Path, attempt: int, phase: str
) -> tuple[Path, Path, Path]:
    slug = _phase_slug(phase)
    return (
        runtime_root / f"phase_inflight__{attempt:04d}__{slug}.json",
        runtime_root / f"phase_prelaunch_tree__{attempt:04d}__{slug}.json",
        runtime_root / f"phase__{attempt:04d}__{slug}.json",
    )


def _validate_phase_workspace_paths(paths: object) -> tuple[str, ...]:
    if not isinstance(paths, (list, tuple)) or not paths:
        raise _fail("child_phase_inflight_output_paths")
    normalized: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw:
            raise _fail("child_phase_inflight_output_paths")
        relative = Path(raw)
        if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
            raise _fail("child_phase_inflight_output_paths")
        text = relative.as_posix()
        if text in normalized:
            raise _fail("child_phase_inflight_output_paths")
        normalized.append(text)
    return tuple(sorted(normalized))


def materialize_evo_child_phase_inflight(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
    phase: str,
    expected_workspace_paths: list[str] | tuple[str, ...],
    operation_binding: Mapping[str, Any],
    require_pristine_baseline: bool,
) -> dict[str, Any]:
    """Freeze one deterministic child Step6 phase before any phase writer runs.

    The signed journal is recovery authority only.  It never admits the output
    delta by itself; the normal phase validator must still replay the exact
    Agent/Host evidence before Step6 can continue.
    """

    if phase not in _DURABLE_INFLIGHT_PHASES:
        raise _fail("child_phase_inflight_identity")
    if not isinstance(require_pristine_baseline, bool):
        raise _fail("child_phase_inflight_mode")
    expected_paths = _validate_phase_workspace_paths(expected_workspace_paths)
    binding = dict(operation_binding) if isinstance(operation_binding, Mapping) else {}
    if not binding:
        raise _fail("child_phase_inflight_operation_binding")
    # Ensure the binding has a deterministic canonical representation before
    # any durable path is selected.
    try:
        stable_json_hash(binding)
    except (TypeError, ValueError) as exc:
        raise _fail("child_phase_inflight_operation_binding") from exc

    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if prior.get("status") != CHILD_RESUME_READY or prior.get("resume_start_step") != "6":
        raise _fail("child_phase_inflight_prior_state")
    baseline = prior_evidence.get("entries")
    if not isinstance(baseline, Mapping) or not all(
        isinstance(path, str) and _is_sha256(digest)
        for path, digest in baseline.items()
    ):
        raise _fail("child_phase_inflight_prior_evidence")
    current = _workspace_evidence_tree(workspace)
    changed = {
        path
        for path in set(baseline) | set(current)
        if baseline.get(path) != current.get(path)
    }
    runtime_root = _runtime_root(state, job_id, child_report_id)
    attempt = int(prior.get("attempt") or 0)
    inflight_path, tree_path, phase_receipt_path = _phase_inflight_paths(
        runtime_root, attempt, phase
    )
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    proof = prior.get("proof")
    proof_sha256 = proof.get("sha256") if isinstance(proof, Mapping) else None
    attempt_seed = {
        "identity": identity,
        "phase": phase,
        "prior_execution_receipt_id": prior["receipt_id"],
        "proof_sha256": proof_sha256,
        "expected_workspace_paths": list(expected_paths),
        "operation_binding": binding,
    }
    phase_attempt_id = f"resume_{stable_json_hash(attempt_seed)[:32]}"
    if inflight_path.exists() or inflight_path.is_symlink():
        validated = validate_evo_child_phase_inflight(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            phase_inflight_path=inflight_path,
            workspace_root=workspace,
        )
        receipt = validated["receipt"]
        if (
            receipt.get("expected_workspace_paths") != list(expected_paths)
            or receipt.get("operation_binding") != binding
            or receipt.get("require_pristine_baseline")
            is not require_pristine_baseline
            or receipt.get("phase_attempt_id") != phase_attempt_id
        ):
            raise _fail("child_phase_inflight_exact_replay")
        validated["preexisting"] = True
        return validated

    if any(path not in current for path in changed):
        raise _fail("child_phase_inflight_deleted_baseline")
    if require_pristine_baseline:
        if changed:
            raise _fail("child_phase_inflight_nonpristine_baseline")
    elif not changed or not changed.issubset(set(expected_paths)):
        raise _fail("child_phase_inflight_unscoped_host_delta")

    tree_payload = {
        "version": "factorforge_console_evo_child_phase_prelaunch_tree_v1",
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "phase": phase,
        "phase_attempt_id": phase_attempt_id,
        "prior_execution_receipt_id": prior["receipt_id"],
        "entries": current,
    }
    tree_payload["content_sha256"] = stable_json_hash(tree_payload)
    _write_once(tree_path, _canonical_bytes(tree_payload))
    core = {
        "receipt_type": "EVO_CHILD_DURABLE_PHASE_INFLIGHT",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "status": "CHILD_PHASE_INFLIGHT",
        "identity": identity,
        "phase": phase,
        "phase_attempt_id": phase_attempt_id,
        "prior_execution": _ref(prior_path),
        "prior_execution_receipt_id": prior["receipt_id"],
        "trusted_proof_sha256": proof_sha256,
        "prelaunch_evidence_tree": _ref(tree_path),
        "expected_workspace_paths": list(expected_paths),
        "operation_binding": binding,
        "require_pristine_baseline": require_pristine_baseline,
        "authority": {
            "recovery_only": True,
            "phase_delta_admitted": False,
            "child_step6_allowed": False,
            "parent_execution_allowed": False,
            "oos_release_allowed": False,
            "scientific_factor_verdict": "NOT_ISSUED",
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    receipt = _sign_runtime_receipt_under_incident_guard(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
        store=store,
        path=inflight_path,
        core=core,
    )
    validated = validate_evo_child_phase_inflight(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        phase_inflight_path=inflight_path,
        workspace_root=workspace,
    )
    validated["preexisting"] = False
    validated["phase_receipt_candidate_path"] = str(phase_receipt_path)
    return validated


def validate_evo_child_phase_inflight(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    phase_inflight_path: Path | str,
    workspace_root: Path | str,
    verify_workspace_delta: bool = True,
) -> dict[str, Any]:
    if not isinstance(verify_workspace_delta, bool):
        raise _fail("child_phase_inflight_replay_mode")
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    _assert_no_runtime_incident(
        workspace=workspace, trust=trust,
        installation_id=installation_id, report_id=child_report_id,
    )
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    expected_root = (
        state / "jobs" / job_id / "evo-child-runtime" / child_report_id
    ).resolve(strict=True)
    path = Path(phase_inflight_path).expanduser().resolve(strict=True)
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise _fail("child_phase_inflight_outside_job_state") from exc
    receipt = _load_signed_private_receipt(path, store=store)
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    prior_ref = receipt.get("prior_execution")
    tree_ref = receipt.get("prelaunch_evidence_tree")
    expected_paths = _validate_phase_workspace_paths(
        receipt.get("expected_workspace_paths")
    )
    operation_binding = receipt.get("operation_binding")
    if (
        receipt.get("receipt_type") != "EVO_CHILD_DURABLE_PHASE_INFLIGHT"
        or receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
        or receipt.get("status") != "CHILD_PHASE_INFLIGHT"
        or receipt.get("identity") != identity
        or receipt.get("phase") not in _DURABLE_INFLIGHT_PHASES
        or not re.fullmatch(r"resume_[0-9a-f]{32}", str(receipt.get("phase_attempt_id") or ""))
        or content_sha != stable_json_hash(content)
        or not isinstance(prior_ref, Mapping)
        or set(prior_ref) != {"path", "sha256", "size_bytes"}
        or not isinstance(tree_ref, Mapping)
        or set(tree_ref) != {"path", "sha256", "size_bytes"}
        or not isinstance(operation_binding, Mapping)
        or not operation_binding
        or not isinstance(receipt.get("require_pristine_baseline"), bool)
        or receipt.get("authority")
        != {
            "recovery_only": True,
            "phase_delta_admitted": False,
            "child_step6_allowed": False,
            "parent_execution_allowed": False,
            "oos_release_allowed": False,
            "scientific_factor_verdict": "NOT_ISSUED",
        }
    ):
        raise _fail("child_phase_inflight_exact_replay")
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=str(prior_ref.get("path") or ""),
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        _ref(prior_path) != dict(prior_ref)
        or prior.get("receipt_id") != receipt.get("prior_execution_receipt_id")
        or prior.get("status") != CHILD_RESUME_READY
        or prior.get("resume_start_step") != "6"
    ):
        raise _fail("child_phase_inflight_prior_binding")
    proof = prior.get("proof")
    proof_sha256 = proof.get("sha256") if isinstance(proof, Mapping) else None
    attempt_seed = {
        "identity": identity,
        "phase": receipt["phase"],
        "prior_execution_receipt_id": prior["receipt_id"],
        "proof_sha256": proof_sha256,
        "expected_workspace_paths": list(expected_paths),
        "operation_binding": dict(operation_binding),
    }
    if (
        receipt.get("trusted_proof_sha256") != proof_sha256
        or receipt.get("phase_attempt_id")
        != f"resume_{stable_json_hash(attempt_seed)[:32]}"
    ):
        raise _fail("child_phase_inflight_attempt_identity")
    tree_path = Path(str(tree_ref.get("path") or ""))
    try:
        tree_path.relative_to(expected_root)
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("child_phase_inflight_prelaunch_tree") from exc
    tree_unsigned = dict(tree) if isinstance(tree, dict) else {}
    tree_sha = tree_unsigned.pop("content_sha256", None)
    prelaunch = tree.get("entries") if isinstance(tree, Mapping) else None
    if (
        _ref(tree_path) != dict(tree_ref)
        or tree_sha != stable_json_hash(tree_unsigned)
        or tree.get("job_id") != job_id
        or tree.get("parent_report_id") != parent_report_id
        or tree.get("child_report_id") != child_report_id
        or tree.get("phase") != receipt.get("phase")
        or tree.get("phase_attempt_id") != receipt.get("phase_attempt_id")
        or tree.get("prior_execution_receipt_id") != prior["receipt_id"]
        or not isinstance(prelaunch, Mapping)
        or not all(
            isinstance(name, str) and _is_sha256(digest)
            for name, digest in prelaunch.items()
        )
    ):
        raise _fail("child_phase_inflight_prelaunch_tree")
    baseline = prior_evidence.get("entries")
    if not isinstance(baseline, Mapping):
        raise _fail("child_phase_inflight_prior_evidence")
    prelaunch_changed = {
        name
        for name in set(baseline) | set(prelaunch)
        if baseline.get(name) != prelaunch.get(name)
    }
    if any(name not in prelaunch for name in prelaunch_changed):
        raise _fail("child_phase_inflight_deleted_baseline")
    if receipt.get("require_pristine_baseline") is True:
        if prelaunch_changed:
            raise _fail("child_phase_inflight_nonpristine_baseline")
    elif not prelaunch_changed or not prelaunch_changed.issubset(set(expected_paths)):
        raise _fail("child_phase_inflight_unscoped_host_delta")
    current = _workspace_evidence_tree(workspace)
    if verify_workspace_delta:
        postlaunch_changed = {
            name
            for name in set(prelaunch) | set(current)
            if prelaunch.get(name) != current.get(name)
        }
        if any(
            name not in current for name in postlaunch_changed
        ) or not postlaunch_changed.issubset(set(expected_paths)):
            raise _fail("child_phase_inflight_workspace_delta")
    _inflight_path, _tree_path, phase_receipt_path = _phase_inflight_paths(
        expected_root, int(prior.get("attempt") or 0), str(receipt["phase"])
    )
    return {
        "verdict": "PASS",
        "status": "CHILD_PHASE_INFLIGHT",
        "phase": receipt["phase"],
        "phase_attempt_id": receipt["phase_attempt_id"],
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "phase_inflight_path": str(path),
        "phase_inflight_sha256": _sha256(path),
        "phase_receipt_candidate_path": str(phase_receipt_path),
        "phase_receipt_exists": (
            phase_receipt_path.is_file() and not phase_receipt_path.is_symlink()
        ),
        "receipt": receipt,
        "prelaunch_entries": dict(prelaunch),
        "current_entries": current,
    }


def load_pending_evo_child_phase_inflight(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any] | None:
    """Return the one signed phase transaction not yet consumed by execution."""

    baseline = load_evo_child_execution_baseline(
        state_root=state_root,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace_root,
    )
    if baseline.get("status") != CHILD_RESUME_READY or baseline.get("resume_start_step") != "6":
        return None
    runtime_root = (
        Path(state_root).expanduser().resolve(strict=True)
        / "jobs"
        / job_id
        / "evo-child-runtime"
        / child_report_id
    ).resolve(strict=True)
    attempt = int(baseline["receipt"].get("attempt") or 0)
    candidates = sorted(runtime_root.glob(f"phase_inflight__{attempt:04d}__*.json"))
    if not candidates:
        return None
    if len(candidates) != 1 or candidates[0].is_symlink() or not candidates[0].is_file():
        raise _fail("child_phase_inflight_ambiguous")
    return validate_evo_child_phase_inflight(
        state_root=state_root,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        phase_inflight_path=candidates[0],
        workspace_root=workspace_root,
    )


def materialize_evo_child_phase_checkpoint(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
    phase: str,
    allowed_workspace_delta: Mapping[str, str],
    phase_evidence: Mapping[str, Mapping[str, Any]],
    phase_context: Mapping[str, Any] | None = None,
    phase_inflight_path: Path | str | None = None,
) -> dict[str, Any]:
    if phase not in _CHILD_PHASES:
        raise _fail("child_phase_identity")
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        prior.get("status") != CHILD_RESUME_READY
        or prior.get("resume_start_step") != "6"
    ):
        raise _fail("child_phase_prior_state")
    before = prior_evidence.get("entries")
    after = _workspace_evidence_tree(workspace)
    if not isinstance(before, Mapping) or not all(
        isinstance(path, str) and _is_sha256(digest)
        for path, digest in before.items()
    ):
        raise _fail("child_phase_prior_evidence")
    allowed = dict(allowed_workspace_delta)
    if not all(
        isinstance(path, str)
        and path
        and not Path(path).is_absolute()
        and ".." not in Path(path).parts
        and _is_sha256(digest)
        for path, digest in allowed.items()
    ):
        raise _fail("child_phase_allowlist")
    changed = {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    if changed != set(allowed) or any(
        after.get(path) != digest for path, digest in allowed.items()
    ):
        raise _fail("child_phase_workspace_delta")
    phase_inflight_ref: dict[str, Any] | None = None
    if phase in _DURABLE_INFLIGHT_PHASES:
        if phase_inflight_path is None:
            raise _fail("child_phase_inflight_missing")
        inflight = validate_evo_child_phase_inflight(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            phase_inflight_path=phase_inflight_path,
            workspace_root=workspace,
        )
        inflight_receipt = inflight["receipt"]
        if (
            inflight.get("phase") != phase
            or inflight_receipt.get("prior_execution_receipt_id")
            != prior["receipt_id"]
            or not changed.issubset(
                set(inflight_receipt.get("expected_workspace_paths") or [])
            )
        ):
            raise _fail("child_phase_inflight_binding")
        phase_inflight_ref = _ref(Path(str(inflight["phase_inflight_path"])))
    elif phase_inflight_path is not None:
        raise _fail("child_phase_inflight_unexpected")
    evidence = {key: dict(value) for key, value in phase_evidence.items()}
    if not evidence:
        raise _fail("child_phase_evidence_missing")
    for label, reference in evidence.items():
        if (
            not isinstance(label, str)
            or not label
            or set(reference) != {"path", "sha256", "size_bytes"}
            or _ref(Path(str(reference.get("path") or ""))) != reference
        ):
            raise _fail(f"child_phase_evidence:{label}")
    context = dict(phase_context) if phase_context is not None else None
    _validate_child_phase_context(phase, context)
    runtime_root = _runtime_root(state, job_id, child_report_id)
    attempt = int(prior.get("attempt") or 0)
    slug = phase.lower()
    receipt_path = runtime_root / f"phase__{attempt:04d}__{slug}.json"
    evidence_path = runtime_root / f"phase_evidence__{attempt:04d}__{slug}.json"
    evidence_payload = {
        "version": "factorforge_console_evo_child_phase_evidence_v1",
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "phase": phase,
        "prior_execution_receipt_id": prior["receipt_id"],
        "allowed_workspace_delta": allowed,
        "entries": after,
    }
    evidence_payload["content_sha256"] = stable_json_hash(evidence_payload)
    _write_once(evidence_path, _canonical_bytes(evidence_payload))
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    core = {
        "receipt_type": "EVO_CHILD_DURABLE_PHASE",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "status": CHILD_PHASE_READY,
        "identity": identity,
        "phase": phase,
        "phase_inflight": phase_inflight_ref,
        "prior_execution": _ref(prior_path),
        "prior_execution_receipt_id": prior["receipt_id"],
        "phase_evidence": evidence,
        "phase_context": context,
        "rebaseline_evidence_tree": _ref(evidence_path),
        "resume_start_step": "6",
        "authority": {
            "closed_phase_delta_verified": True,
            "child_step6_allowed": True,
            "parent_execution_allowed": False,
            "scientific_factor_verdict": "NOT_ISSUED",
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    receipt = _sign_runtime_receipt_under_incident_guard(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
        store=store,
        path=receipt_path,
        core=core,
    )
    return validate_evo_child_phase_checkpoint(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        phase_receipt_path=receipt_path,
        workspace_root=workspace,
    )


def validate_evo_child_phase_checkpoint(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    phase_receipt_path: Path | str,
    workspace_root: Path | str,
    verify_workspace_exact: bool = True,
) -> dict[str, Any]:
    if not isinstance(verify_workspace_exact, bool):
        raise _fail("child_phase_workspace_replay_mode")
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    _assert_no_runtime_incident(
        workspace=workspace, trust=trust,
        installation_id=installation_id, report_id=child_report_id,
    )
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    expected_root = (
        state / "jobs" / job_id / "evo-child-runtime" / child_report_id
    ).resolve(strict=True)
    path = Path(phase_receipt_path).expanduser().resolve(strict=True)
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise _fail("child_phase_receipt_outside_job_state") from exc
    receipt = _load_signed_private_receipt(path, store=store)
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    prior_ref = receipt.get("prior_execution")
    evidence_ref = receipt.get("rebaseline_evidence_tree")
    phase_evidence = receipt.get("phase_evidence")
    phase_context = receipt.get("phase_context")
    phase_inflight_ref = receipt.get("phase_inflight")
    if (
        receipt.get("receipt_type") != "EVO_CHILD_DURABLE_PHASE"
        or receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
        or receipt.get("status") != CHILD_PHASE_READY
        or receipt.get("identity") != identity
        or receipt.get("phase") not in _CHILD_PHASES
        or receipt.get("resume_start_step") != "6"
        or content_sha != stable_json_hash(content)
        or receipt.get("authority")
        != {
            "closed_phase_delta_verified": True,
            "child_step6_allowed": True,
            "parent_execution_allowed": False,
            "scientific_factor_verdict": "NOT_ISSUED",
        }
        or not isinstance(prior_ref, Mapping)
        or set(prior_ref) != {"path", "sha256", "size_bytes"}
        or not isinstance(evidence_ref, Mapping)
        or set(evidence_ref) != {"path", "sha256", "size_bytes"}
        or not isinstance(phase_evidence, Mapping)
        or not phase_evidence
        or (
            receipt.get("phase") in _DURABLE_INFLIGHT_PHASES
            and (
                not isinstance(phase_inflight_ref, Mapping)
                or set(phase_inflight_ref) != {"path", "sha256", "size_bytes"}
            )
        )
        or (
            receipt.get("phase") not in _DURABLE_INFLIGHT_PHASES
            and phase_inflight_ref is not None
        )
    ):
        raise _fail("child_phase_receipt_exact_replay")
    _validate_child_phase_context(str(receipt["phase"]), phase_context)
    prior, prior_path, _prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=str(prior_ref.get("path") or ""),
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        _ref(prior_path) != dict(prior_ref)
        or prior.get("receipt_id") != receipt.get("prior_execution_receipt_id")
    ):
        raise _fail("child_phase_prior_binding")
    if receipt.get("phase") in _DURABLE_INFLIGHT_PHASES:
        inflight = validate_evo_child_phase_inflight(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            phase_inflight_path=str(phase_inflight_ref.get("path") or ""),
            workspace_root=workspace,
            verify_workspace_delta=verify_workspace_exact,
        )
        if (
            _ref(Path(str(phase_inflight_ref.get("path") or "")))
            != dict(phase_inflight_ref)
            or inflight.get("phase") != receipt.get("phase")
            or inflight["receipt"].get("prior_execution_receipt_id")
            != prior["receipt_id"]
        ):
            raise _fail("child_phase_inflight_binding")
    if (
        receipt.get("phase") in {"HOST_TRANSFER_USE", "HOST_CHILD_HANDOFF"}
        and verify_workspace_exact
    ):
        proof_ref = prior.get("proof")
        if not isinstance(proof_ref, Mapping):
            raise _fail("child_phase_external_proof")
        try:
            proof = json.loads(
                Path(str(proof_ref.get("path") or "")).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _fail("child_phase_external_proof") from exc
        assessment = assess_evo_v2_external_resume(
            workspace_root=workspace,
            report_id=child_report_id,
            proof=proof,
            attested_entries=_prior_evidence.get("entries"),
            trust_root=trust,
            installation_id=installation_id,
            trusted_lifecycle_manifest=store.public_manifest,
            require_signed_lifecycle_genesis=False,
        )
        if assessment.to_dict() != phase_context.get(
            "external_resume_assessment"
        ):
            raise _fail("child_phase_external_assessment_replay")
    for label, raw_reference in phase_evidence.items():
        reference = dict(raw_reference) if isinstance(raw_reference, Mapping) else {}
        if (
            not isinstance(label, str)
            or not label
            or set(reference) != {"path", "sha256", "size_bytes"}
            or _ref(Path(str(reference.get("path") or ""))) != reference
        ):
            raise _fail(f"child_phase_evidence:{label}")
    evidence_path = Path(str(evidence_ref.get("path") or ""))
    try:
        evidence_path.relative_to(expected_root)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("child_phase_rebaseline") from exc
    evidence_unsigned = dict(evidence) if isinstance(evidence, dict) else {}
    evidence_content_sha = evidence_unsigned.pop("content_sha256", None)
    current_entries = _workspace_evidence_tree(workspace)
    if (
        _ref(evidence_path) != dict(evidence_ref)
        or evidence_content_sha != stable_json_hash(evidence_unsigned)
        or evidence.get("job_id") != job_id
        or evidence.get("parent_report_id") != parent_report_id
        or evidence.get("child_report_id") != child_report_id
        or evidence.get("phase") != receipt.get("phase")
        or evidence.get("prior_execution_receipt_id") != prior["receipt_id"]
        or (
            verify_workspace_exact and evidence.get("entries") != current_entries
        )
        or (
            not verify_workspace_exact
            and (
                not isinstance(evidence.get("entries"), Mapping)
                or any(
                    current_entries.get(name) != digest
                    for name, digest in evidence["entries"].items()
                )
            )
        )
    ):
        raise _fail("child_phase_rebaseline")
    return {
        "verdict": "PASS",
        "status": CHILD_PHASE_READY,
        "phase": receipt["phase"],
        "child_report_id": child_report_id,
        "resume_start_step": "6",
        "phase_receipt_path": str(path),
        "phase_receipt_sha256": _sha256(path),
        "phase_inflight_path": (
            str(phase_inflight_ref.get("path"))
            if isinstance(phase_inflight_ref, Mapping)
            else None
        ),
        "receipt": receipt,
    }


def _validate_child_phase_context(
    phase: str, context: Mapping[str, Any] | None
) -> None:
    external_phases = {"HOST_TRANSFER_USE", "HOST_CHILD_HANDOFF"}
    if phase not in external_phases:
        if context is not None:
            raise _fail("child_phase_context_unexpected")
        return
    if not isinstance(context, Mapping) or set(context) != {
        "external_resume_assessment"
    }:
        raise _fail("child_phase_context_shape")
    assessment = context.get("external_resume_assessment")
    if not isinstance(assessment, Mapping):
        raise _fail("child_phase_context_assessment")
    if phase == "HOST_TRANSFER_USE":
        if (
            assessment.get("status") != PROGRESS_HOST_CHECKPOINT_READY
            or assessment.get("start_step") != "6"
            or assessment.get("pause_outcome")
            != "awaiting_evo_v2_transfer_and_actual_use"
        ):
            raise _fail("child_phase_transfer_context")
    elif (
        assessment.get("status")
        not in {"CHILD_HANDOFF_AUTHORIZED", "CHILD_HANDOFF_READY"}
        or assessment.get("start_step") is not None
        or assessment.get("pause_outcome")
        != "awaiting_evo_v2_external_approval_and_fresh_child"
        or not isinstance(assessment.get("child_report_id"), str)
        or not assessment.get("child_report_id")
        or assessment.get("child_report_id") == assessment.get("report_id")
    ):
        raise _fail("child_phase_handoff_context")


def _terminal_checkpoint_paths(
    runtime_root: Path, attempt: int
) -> tuple[Path, Path]:
    return (
        runtime_root / f"terminal__{attempt:04d}.json",
        runtime_root / f"terminal_evidence_tree__{attempt:04d}.json",
    )


def materialize_evo_child_terminal_checkpoint(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    execution_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    """Close a child only from its replayed Host-signed NQC terminal delta.

    This is deliberately not an Ultimate retry.  Once the child proof pauses
    after fresh-OOS evaluation, the external Host terminal-closure receipt is
    the only scientific authority that may turn the durable child state into a
    terminal ACCEPT/REJECT.
    """

    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=execution_receipt_path,
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        prior.get("status") != CHILD_RESUME_READY
        or prior.get("resume_start_step") != "6"
    ):
        raise _fail("terminal_prior_resume_state")
    proof_ref = prior.get("proof")
    if not isinstance(proof_ref, Mapping):
        raise _fail("terminal_prior_proof")
    proof_path = Path(str(proof_ref.get("path") or ""))
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("terminal_prior_proof_json") from exc
    if (
        not isinstance(proof, Mapping)
        or proof.get("report_id") != child_report_id
        or proof.get("status") != "PAUSED"
        or proof.get("final_outcome")
        != "awaiting_evo_v2_non_revision_terminal_closure"
        or proof.get("proof_semantics")
        != "awaiting_evo_v2_non_revision_terminal_closure"
    ):
        raise _fail("terminal_prior_proof_semantics")
    assessment = assess_evo_v2_external_resume(
        workspace_root=workspace,
        report_id=child_report_id,
        proof=proof,
        attested_entries=prior_evidence.get("entries"),
        trust_root=trust,
        installation_id=installation_id,
        trusted_lifecycle_manifest=store.public_manifest,
        require_signed_lifecycle_genesis=False,
    )
    assessment_payload = assessment.to_dict()
    formal_verdict = assessment.terminal_factor_verdict
    terminal_decision = assessment.terminal_decision
    closure_relative = assessment.terminal_closure_path
    if (
        assessment.status != PROGRESS_TERMINAL_CHECKPOINT_READY
        or assessment.start_step is not None
        or formal_verdict not in {"ACCEPT", "REJECT"}
        or terminal_decision
        != {"ACCEPT": "promote_official", "REJECT": "reject"}[formal_verdict]
        or not isinstance(closure_relative, str)
        or not closure_relative
        or Path(closure_relative).is_absolute()
        or ".." in Path(closure_relative).parts
        or not _is_sha256(assessment.terminal_closure_sha256)
    ):
        raise _fail("terminal_assessment_not_ready")
    closure_path = workspace / closure_relative
    try:
        closure_path.resolve(strict=True).relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise _fail("terminal_closure_path") from exc
    closure_ref = _ref(closure_path)
    if closure_ref["sha256"] != assessment.terminal_closure_sha256:
        raise _fail("terminal_closure_hash")

    runtime_root = _runtime_root(state, job_id, child_report_id)
    attempt = int(prior.get("attempt") or 0)
    receipt_path, evidence_path = _terminal_checkpoint_paths(runtime_root, attempt)
    evidence_payload = {
        "version": "factorforge_console_evo_child_terminal_evidence_v1",
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "prior_execution_receipt_id": prior["receipt_id"],
        "entries": _workspace_evidence_tree(workspace),
    }
    evidence_payload["content_sha256"] = stable_json_hash(evidence_payload)
    _write_once(evidence_path, _canonical_bytes(evidence_payload))
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
    }
    core = {
        "receipt_type": "EVO_CHILD_TERMINAL_CHECKPOINT",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "status": CHILD_TERMINAL,
        "identity": identity,
        "prior_execution": _ref(prior_path),
        "prior_execution_receipt_id": prior["receipt_id"],
        "prior_evidence_tree": dict(prior["child_evidence_tree"]),
        "proof": dict(proof_ref),
        "terminal_closure": closure_ref,
        "external_resume_assessment": assessment_payload,
        "rebaseline_evidence_tree": _ref(evidence_path),
        "formal_factor_verdict": formal_verdict,
        "terminal_decision": terminal_decision,
        "resume_start_step": None,
        "authority": {
            "closed_host_delta_verified": True,
            "child_execution_allowed": False,
            "parent_execution_allowed": False,
            "scientific_verdict_issued": True,
            "scientific_factor_verdict": formal_verdict,
            "canonical_memory_write_allowed": False,
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    receipt = _sign_runtime_receipt_under_incident_guard(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
        store=store,
        path=receipt_path,
        core=core,
    )
    return validate_evo_child_terminal_checkpoint(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        terminal_receipt_path=receipt_path,
        workspace_root=workspace,
    )


def validate_evo_child_terminal_checkpoint(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    terminal_receipt_path: Path | str,
    workspace_root: Path | str,
) -> dict[str, Any]:
    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    _assert_no_runtime_incident(
        workspace=workspace, trust=trust,
        installation_id=installation_id, report_id=child_report_id,
    )
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    expected_root = (
        state / "jobs" / job_id / "evo-child-runtime" / child_report_id
    ).resolve(strict=True)
    path = Path(terminal_receipt_path).expanduser().resolve(strict=True)
    try:
        path.relative_to(expected_root)
    except ValueError as exc:
        raise _fail("terminal_receipt_outside_job_state") from exc
    receipt = _load_signed_private_receipt(path, store=store)
    identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": (
            expected_host_trust_manifest_sha256
        ),
    }
    unsigned = {
        key: value
        for key, value in receipt.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    formal_verdict = receipt.get("formal_factor_verdict")
    expected_authority = {
        "closed_host_delta_verified": True,
        "child_execution_allowed": False,
        "parent_execution_allowed": False,
        "scientific_verdict_issued": True,
        "scientific_factor_verdict": formal_verdict,
        "canonical_memory_write_allowed": False,
    }
    prior_ref = receipt.get("prior_execution")
    proof_ref = receipt.get("proof")
    closure_ref = receipt.get("terminal_closure")
    evidence_ref = receipt.get("rebaseline_evidence_tree")
    if (
        receipt.get("receipt_type") != "EVO_CHILD_TERMINAL_CHECKPOINT"
        or receipt.get("runtime_version") != CHILD_RUNTIME_VERSION
        or receipt.get("status") != CHILD_TERMINAL
        or receipt.get("identity") != identity
        or receipt.get("resume_start_step") is not None
        or formal_verdict not in {"ACCEPT", "REJECT"}
        or receipt.get("terminal_decision")
        != {"ACCEPT": "promote_official", "REJECT": "reject"}[formal_verdict]
        or receipt.get("authority") != expected_authority
        or content_sha != stable_json_hash(content)
        or any(
            not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256", "size_bytes"}
            for reference in (prior_ref, proof_ref, closure_ref, evidence_ref)
        )
    ):
        raise _fail("terminal_receipt_exact_replay")
    prior, prior_path, prior_evidence = _load_evo_child_execution_receipt(
        state_root=state,
        trust_root=trust,
        installation_id=installation_id,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
        execution_receipt_path=str(prior_ref.get("path") or ""),
        workspace_root=workspace,
        verify_workspace_exact=False,
    )
    if (
        _ref(prior_path) != dict(prior_ref)
        or prior.get("receipt_id") != receipt.get("prior_execution_receipt_id")
        or prior.get("child_evidence_tree") != receipt.get("prior_evidence_tree")
        or prior.get("proof") != proof_ref
    ):
        raise _fail("terminal_prior_execution_binding")
    proof_path = Path(str(proof_ref.get("path") or ""))
    if _ref(proof_path) != dict(proof_ref):
        raise _fail("terminal_proof_binding")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("terminal_proof_json") from exc
    assessment = assess_evo_v2_external_resume(
        workspace_root=workspace,
        report_id=child_report_id,
        proof=proof,
        attested_entries=prior_evidence.get("entries"),
        trust_root=trust,
        installation_id=installation_id,
        trusted_lifecycle_manifest=store.public_manifest,
        require_signed_lifecycle_genesis=False,
    )
    if (
        assessment.status != PROGRESS_TERMINAL_CHECKPOINT_READY
        or assessment.to_dict() != receipt.get("external_resume_assessment")
        or assessment.terminal_factor_verdict != formal_verdict
        or assessment.terminal_decision != receipt.get("terminal_decision")
    ):
        raise _fail("terminal_assessment_replay")
    closure_path = workspace / str(assessment.terminal_closure_path or "")
    if _ref(closure_path) != dict(closure_ref):
        raise _fail("terminal_closure_binding")
    evidence_path = Path(str(evidence_ref.get("path") or ""))
    try:
        evidence_path.relative_to(expected_root)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("terminal_evidence_tree") from exc
    evidence_unsigned = dict(evidence) if isinstance(evidence, dict) else {}
    evidence_content_sha = evidence_unsigned.pop("content_sha256", None)
    if (
        _ref(evidence_path) != dict(evidence_ref)
        or evidence_content_sha != stable_json_hash(evidence_unsigned)
        or evidence.get("job_id") != job_id
        or evidence.get("parent_report_id") != parent_report_id
        or evidence.get("child_report_id") != child_report_id
        or evidence.get("prior_execution_receipt_id") != prior["receipt_id"]
        or evidence.get("entries") != _workspace_evidence_tree(workspace)
    ):
        raise _fail("terminal_evidence_tree")
    return {
        "verdict": "PASS",
        "status": CHILD_TERMINAL,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "resume_start_step": None,
        "execution_receipt_path": str(path),
        "execution_receipt_sha256": _sha256(path),
        "proof_path": str(proof_path),
        "proof_sha256": proof_ref["sha256"],
        "returncode": 0,
        "proof_status": "PASS",
        "scientific_factor_verdict": formal_verdict,
        "terminal_decision": receipt["terminal_decision"],
        "terminal_checkpoint": True,
        "idempotent_replay": False,
        "receipt": receipt,
    }


def execute_evo_child_ready(
    *,
    checkpoint_path: Path | str,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    host_environment: Mapping[str, str],
    timeout_seconds: int,
    resume: bool = False,
    qualification_checkpoint_path: Path | str | None = None,
    phase_checkpoint_path: Path | str | None = None,
) -> dict[str, Any]:
    """Execute or resume only the command authorized by CHILD_EXECUTION_READY."""

    state = Path(state_root).expanduser().resolve(strict=True)
    trust = Path(trust_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    tree = Path(worktree).expanduser().resolve(strict=True)
    def assert_no_incident() -> None:
        reasons = formal_oos_incident_reasons(
            workspace_root=workspace,
            report_id=child_report_id,
            trust_root=trust,
            installation_id=installation_id,
        )
        if reasons:
            raise _fail("oos_exposure_incident:" + ",".join(reasons))

    @contextmanager
    def incident_launch_guard():
        with oos_exposure_private_registry_guard(
            trust,
            installation_id=installation_id,
        ):
            assert_no_incident()
            yield

    assert_no_incident()
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    checkpoint = _load_signed_private_receipt(
        Path(checkpoint_path).expanduser().resolve(strict=True), store=store
    )
    identity = checkpoint.get("identity")
    authority = checkpoint.get("authority")
    execution = checkpoint.get("execution")
    unsigned = {
        key: value
        for key, value in checkpoint.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    expected_identity = {
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
    }
    if (
        checkpoint.get("runtime_version") != CHILD_RUNTIME_VERSION
        or checkpoint.get("stage") != CHILD_EXECUTION_READY
        or checkpoint.get("stage_index") != 7
        or identity != expected_identity
        or content_sha != stable_json_hash(content)
        or authority
        != {
            "child_execution_allowed": True,
            "allowed_start_step": "3b",
            "oos_release_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "skill_or_policy_mutation_allowed": False,
        }
        or not isinstance(execution, Mapping)
        or execution.get("start_step") != "3b"
        or not isinstance(execution.get("argv"), list)
        or execution.get("argv_sha256") != stable_json_hash(execution["argv"])
    ):
        raise _fail("execution_checkpoint_exact_replay")
    runtime_root = _runtime_root(state, job_id, child_report_id)
    prior_paths = sorted(runtime_root.glob("execution__*.json"))
    prior_path = prior_paths[-1] if prior_paths else None
    prior = (
        _load_signed_private_receipt(prior_path, store=store)
        if prior_path is not None
        else None
    )
    attempt = len(prior_paths) + 1
    inflight_path = runtime_root / f"inflight__{attempt:04d}.json"
    inflight_preexisting = inflight_path.is_file() and not inflight_path.is_symlink()
    if inflight_path.is_symlink():
        raise _fail("child_inflight_unsafe")
    if prior is not None and not resume:
        # The signed private execution chain is authoritative if the Console
        # process died after writing its receipt but before updating the job
        # row.  Replay it before any mutable workspace materialization check;
        # the next semantic resume turn owns any legal external delta.
        with oos_exposure_private_registry_guard(
            trust,
            installation_id=installation_id,
        ):
            assert_no_incident()
            validated_prior = load_evo_child_execution_baseline(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                execution_receipt_path=prior_path,
                workspace_root=workspace,
            )
            prior_receipt = validated_prior["receipt"]
            proof_reference = prior_receipt.get("proof")
            authority = prior_receipt.get("authority")
            return {
            "verdict": "PASS",
            "status": validated_prior["status"],
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
            "resume_start_step": validated_prior.get("resume_start_step"),
            "execution_receipt_path": str(prior_path),
            "execution_receipt_sha256": _sha256(prior_path),
            "proof_path": (
                str(proof_reference.get("path"))
                if isinstance(proof_reference, Mapping)
                else None
            ),
            "proof_sha256": (
                str(proof_reference.get("sha256"))
                if isinstance(proof_reference, Mapping)
                else None
            ),
            "returncode": prior_receipt.get("returncode"),
            "proof_status": prior_receipt.get("proof_status"),
            "scientific_factor_verdict": (
                authority.get("factor_verdict")
                if isinstance(authority, Mapping)
                and authority.get("scientific_verdict_issued") is True
                else "NOT_ISSUED"
            ),
        "terminal_checkpoint": False,
        "host_execution_receipt_verified": True,
                "idempotent_replay": True,
            }

    def validate_execution_checkpoint_inputs(
        *, require_seed_materialization: bool
    ) -> None:
        _validate_artifact_refs(checkpoint.get("artifacts"))
        container_ref = checkpoint["artifacts"].get("container_admission")
        if not isinstance(container_ref, Mapping):
            raise _fail("container_admission_ref")
        validate_evo_child_container_admission(
            admission_path=str(container_ref["path"]),
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            workspace_root=workspace,
            worktree=tree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_trust_manifest_sha256,
        )
        if not require_seed_materialization:
            return
        materialization, materialization_reasons = (
            validate_evo_child_materialization_admission(
                workspace_root=workspace,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                incident_trust_root=trust,
                incident_installation_id=installation_id,
            )
        )
        if materialization is None or materialization_reasons:
            raise _fail("materialization_admission_changed")

    # A signed inflight attempt must be classified before consulting mutable
    # workspace admissions.  Otherwise an authorized Step3B/4 crash can be
    # stranded by outputs it wrote before the Host recorded the execution
    # receipt.  Normal launches still replay all mutable inputs first.
    if not inflight_preexisting:
        validate_execution_checkpoint_inputs(
            # The materialization admission freezes the Step3B seed.  Step3B
            # is authorized to replace its handoff with an execution result,
            # so later attempts must use the signed prior execution evidence
            # tree and phase admission as their authority instead of trying to
            # replay the now-obsolete seed admission.
            require_seed_materialization=prior is None,
        )
    if resume:
        if prior is None or prior_path is None or prior.get("status") not in {
            CHILD_RESUME_READY,
            CHILD_RECOVERY_READY,
        }:
            raise _fail("child_resume_not_authorized")
        start_step = str(prior.get("resume_start_step") or "")
        if (
            start_step not in {"4", "5", "6"}
            or (
                prior.get("status") == CHILD_RECOVERY_READY
                and start_step != "6"
            )
        ):
            raise _fail("child_resume_start_step")
        resume_admission_ref: dict[str, Any] | None = None
        if qualification_checkpoint_path is not None and phase_checkpoint_path is not None:
            raise _fail("multiple_child_resume_checkpoints")
        if qualification_checkpoint_path is not None:
            qualification = validate_evo_child_qualification_checkpoint(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                qualification_receipt_path=qualification_checkpoint_path,
                workspace_root=workspace,
            )
            if (
                prior.get("status") != CHILD_RESUME_READY
                or start_step != "6"
                or qualification["receipt"].get(
                    "prior_execution_receipt_id"
                )
                != prior.get("receipt_id")
            ):
                raise _fail("qualification_execution_binding")
            resume_admission_ref = _ref(
                Path(qualification_checkpoint_path).expanduser().resolve(strict=True)
            )
        elif phase_checkpoint_path is not None:
            phase_checkpoint = validate_evo_child_phase_checkpoint(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                phase_receipt_path=phase_checkpoint_path,
                workspace_root=workspace,
            )
            if (
                prior.get("status") != CHILD_RESUME_READY
                or start_step != "6"
                or phase_checkpoint["receipt"].get(
                    "prior_execution_receipt_id"
                )
                != prior.get("receipt_id")
            ):
                raise _fail("child_phase_execution_binding")
            resume_admission_ref = _ref(
                Path(phase_checkpoint_path).expanduser().resolve(strict=True)
            )
        else:
            if inflight_preexisting:
                # The prior workspace necessarily changed if the interrupted
                # wrapper published a proof or partial OOS.  The signed
                # inflight classifier below owns that recovery; do not compare
                # it to the prelaunch evidence tree here.
                pass
            else:
                validate_evo_child_execution_state(
                    state_root=state,
                    trust_root=trust,
                    installation_id=installation_id,
                    job_id=job_id,
                    parent_report_id=parent_report_id,
                    child_report_id=child_report_id,
                    expected_host_trust_manifest_sha256=(
                        expected_host_trust_manifest_sha256
                    ),
                    execution_receipt_path=prior_path,
                    workspace_root=workspace,
                )
            if (
                not inflight_preexisting
                and
                prior.get("status") == CHILD_RESUME_READY
                and start_step == "6"
            ):
                raise _fail("child_step6_host_qualification_required")
            if prior.get("status") == CHILD_RECOVERY_READY:
                resume_admission_ref = _ref(prior_path)
    else:
        start_step = "3b"
        resume_admission_ref = None
    proof_path = (
        workspace
        / "objects/runtime_context"
        / f"ultimate_run_report__{child_report_id}.json"
    )
    prior_proof_ref = (
        _ref(proof_path)
        if proof_path.is_file() and not proof_path.is_symlink()
        else None
    )
    container_root = (
        state
        / "jobs"
        / job_id
        / "evo-child-container"
        / child_report_id
    )
    prior_container_termination_ref: dict[str, Any] | None = None
    if (
        container_root.is_dir()
        and not container_root.is_symlink()
        and any(container_root.glob("termination__*.json"))
    ):
        prior_termination = validate_latest_evo_child_agent_termination(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            workspace_root=workspace,
            worktree=tree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_trust_manifest_sha256,
        )
        prior_container_termination_ref = _ref(
            Path(prior_termination["termination_receipt_path"])
        )
    argv = _replace_argv_value(list(execution["argv"]), "--start-step", start_step)
    if prior is not None and prior.get("status") == CHILD_RECOVERY_READY:
        if prior_path is None:
            raise _fail("child_recovery_admission_missing")
        argv.extend(
            [
                "--evo-child-finalizer-recovery-admission",
                str(prior_path),
            ]
        )
    if _replace_argv_value(argv, "--report-id", child_report_id) != argv:
        raise _fail("child_report_argv")
    environment = dict(host_environment)
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\x00" in key + value
        or "\n" in key + value
        or "\r" in key + value
        for key, value in environment.items()
    ):
        raise _fail("host_environment")
    inflight_core = {
        "receipt_type": "EVO_CHILD_ULTIMATE_INFLIGHT",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "identity": expected_identity,
        "execution_ready_receipt_id": checkpoint["receipt_id"],
        "previous_execution_receipt_id": (
            prior.get("receipt_id") if prior is not None else None
        ),
        "attempt": attempt,
        "start_step": start_step,
        "argv_sha256": stable_json_hash(argv),
        "resume_admission": resume_admission_ref,
        "prior_proof": prior_proof_ref,
        "prior_container_termination": prior_container_termination_ref,
        "prelaunch_workspace_tree_sha256": stable_json_hash(
            _workspace_evidence_tree(workspace)
        ),
        "authority": {
            "execution_inflight_only": True,
            "rerun_after_unknown_crash_allowed": False,
            "partial_oos_finalizer_only": True,
            "scientific_factor_verdict": "NOT_ISSUED",
        },
    }
    inflight_core["content_sha256"] = stable_json_hash(inflight_core)
    if inflight_preexisting:
        inflight = _load_signed_private_receipt(inflight_path, store=store)
        recorded_resume_admission = inflight.get("resume_admission")
        if recorded_resume_admission is not None and (
            not isinstance(recorded_resume_admission, Mapping)
            or set(recorded_resume_admission)
            != {"path", "sha256", "size_bytes"}
            or _ref(Path(str(recorded_resume_admission.get("path") or "")))
            != dict(recorded_resume_admission)
        ):
            raise _fail("child_inflight_resume_admission")
        if (
            resume_admission_ref is not None
            and recorded_resume_admission != resume_admission_ref
        ):
            raise _fail("child_inflight_resume_admission_changed")
        resume_admission_ref = (
            dict(recorded_resume_admission)
            if isinstance(recorded_resume_admission, Mapping)
            else None
        )
        recorded_prior_proof = inflight.get("prior_proof")
        if recorded_prior_proof is not None and (
            not isinstance(recorded_prior_proof, Mapping)
            or set(recorded_prior_proof) != {"path", "sha256", "size_bytes"}
        ):
            raise _fail("child_inflight_prior_proof")
        prior_proof_ref = (
            dict(recorded_prior_proof)
            if isinstance(recorded_prior_proof, Mapping)
            else None
        )
        recorded_prior_termination = inflight.get("prior_container_termination")
        if recorded_prior_termination is not None and (
            not isinstance(recorded_prior_termination, Mapping)
            or set(recorded_prior_termination)
            != {"path", "sha256", "size_bytes"}
            or _ref(Path(str(recorded_prior_termination.get("path") or "")))
            != dict(recorded_prior_termination)
        ):
            raise _fail("child_inflight_prior_container_termination")
        prior_container_termination_ref = (
            dict(recorded_prior_termination)
            if isinstance(recorded_prior_termination, Mapping)
            else None
        )
        recorded_tree_sha = inflight.get("prelaunch_workspace_tree_sha256")
        if not _is_sha256(recorded_tree_sha):
            raise _fail("child_inflight_evidence_tree")
        inflight_core.pop("content_sha256", None)
        inflight_core["resume_admission"] = resume_admission_ref
        inflight_core["prior_proof"] = prior_proof_ref
        inflight_core["prior_container_termination"] = (
            prior_container_termination_ref
        )
        inflight_core["prelaunch_workspace_tree_sha256"] = recorded_tree_sha
        inflight_core["content_sha256"] = stable_json_hash(inflight_core)
        expected_unsigned = {
            key: value
            for key, value in inflight.items()
            if key not in {"contract_version", "issuer", "receipt_id", "signature"}
        }
        if expected_unsigned != inflight_core:
            raise _fail("child_inflight_exact_replay")
    else:
        inflight = _sign_runtime_receipt_under_incident_guard(
            workspace=workspace,
            trust=trust,
            installation_id=installation_id,
            report_id=child_report_id,
            store=store,
            path=inflight_path,
            core=inflight_core,
        )

    recovered_from_inflight = False
    validated_step4_finalizer_recovery = False
    validated_command_recovery: dict[str, Any] | None = None
    if inflight_preexisting:
        reconcile_evo_child_agent_stage_containers(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            workspace_root=workspace,
            worktree=tree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_trust_manifest_sha256,
        )
        validate_execution_checkpoint_inputs(require_seed_materialization=False)
        recovery_before_proof = web_factor_proof_oos_recovery_state(
            workspace, child_report_id
        )
        fresh_proof_exists = bool(
            proof_path.is_file()
            and not proof_path.is_symlink()
            and (
                prior_proof_ref is None
                or _sha256(proof_path) != prior_proof_ref["sha256"]
            )
        )
        if recovery_before_proof.get("recovery_required") is True:
            completed = subprocess.CompletedProcess(
                argv, 124, stdout="", stderr="recovered_partial_oos_inflight"
            )
            recovered_from_inflight = True
        elif fresh_proof_exists:
            try:
                recovered_proof = json.loads(proof_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise _fail("child_inflight_proof_invalid") from exc
            recovered_status = str(
                recovered_proof.get("status")
                if isinstance(recovered_proof, Mapping)
                else ""
            ).upper()
            if (
                not isinstance(recovered_proof, Mapping)
                or recovered_proof.get("report_id") != child_report_id
            ):
                raise _fail("child_inflight_proof_invalid")
            if recovered_status in {"PAUSED", "PASS", "FAIL"}:
                completed = subprocess.CompletedProcess(
                    argv,
                    0 if recovered_status in {"PAUSED", "PASS"} else 1,
                    stdout="",
                    stderr="recovered_completed_proof_inflight",
                )
                recovered_from_inflight = True
            elif recovered_status == "RUNNING":
                command_recovery = _validated_command_crash_boundary(
                    workspace=workspace,
                    child_report_id=child_report_id,
                    proof=recovered_proof,
                )
                replayed_command_admission = (
                    _resolve_replayable_command_recovery(
                        state=state,
                        trust=trust,
                        installation_id=installation_id,
                        job_id=job_id,
                        parent_report_id=parent_report_id,
                        child_report_id=child_report_id,
                        expected_host_trust_manifest_sha256=(
                            expected_host_trust_manifest_sha256
                        ),
                        workspace=workspace,
                        inflight_path=inflight_path,
                        proof=recovered_proof,
                    )
                    if command_recovery is None
                    else None
                )
                if replayed_command_admission is not None:
                    command_recovery = dict(
                        replayed_command_admission["receipt"]["boundary"]
                    )
                finalizer_boundary = (
                    _validated_step4_finalizer_boundary(
                        workspace=workspace,
                        child_report_id=child_report_id,
                        proof=recovered_proof,
                    )
                    if command_recovery is None
                    and replayed_command_admission is None
                    else None
                )
                if command_recovery is None and finalizer_boundary is None:
                    raise _fail("child_inflight_proof_unknown_command_prefix")
                required_stage = (
                    str(command_recovery["required_termination_stage"])
                    if command_recovery is not None
                    else "validate_step4"
                )
                terminated = validate_latest_evo_child_agent_termination(
                    state_root=state,
                    trust_root=trust,
                    installation_id=installation_id,
                    job_id=job_id,
                    workspace_root=workspace,
                    worktree=tree,
                    parent_report_id=parent_report_id,
                    child_report_id=child_report_id,
                    expected_host_pin=expected_host_trust_manifest_sha256,
                    required_stage=required_stage,
                )
                fresh_termination_ref = _ref(
                    Path(terminated["termination_receipt_path"])
                )
                if (
                    terminated.get("process_tree_absent") is not True
                    or fresh_termination_ref == prior_container_termination_ref
                    or (
                        replayed_command_admission is not None
                        and fresh_termination_ref
                        != replayed_command_admission["receipt"][
                            "latest_container_termination"
                        ]
                    )
                ):
                    raise _fail("child_inflight_validate_step4_not_fresh")
                if command_recovery is not None:
                    start_step = str(command_recovery["required_start_step"])
                    argv = _replace_argv_value(argv, "--start-step", start_step)
                    if replayed_command_admission is None:
                        recovery_admission = _materialize_command_recovery_admission(
                            runtime_root=runtime_root,
                            store=store,
                            identity=expected_identity,
                            inflight_path=inflight_path,
                            proof_path=proof_path,
                            termination_path=Path(
                                terminated["termination_receipt_path"]
                            ),
                            boundary=command_recovery,
                            workspace=workspace,
                            trust=trust,
                            installation_id=installation_id,
                            child_report_id=child_report_id,
                        )
                        validate_evo_child_command_recovery_admission(
                            state_root=state,
                            trust_root=trust,
                            installation_id=installation_id,
                            job_id=job_id,
                            parent_report_id=parent_report_id,
                            child_report_id=child_report_id,
                            expected_host_trust_manifest_sha256=(
                                expected_host_trust_manifest_sha256
                            ),
                            admission_path=recovery_admission["path"],
                            workspace_root=workspace,
                        )
                    else:
                        recovery_admission = {
                            "path": replayed_command_admission[
                                "admission_path"
                            ],
                            "receipt": replayed_command_admission["receipt"],
                        }
                    argv.extend(
                        [
                            "--evo-child-command-recovery-admission",
                            str(recovery_admission["path"]),
                        ]
                    )
                    command_recovery["recovery_admission"] = _ref(
                        recovery_admission["path"]
                    )
                    command_recovery["replayed_signed_admission"] = (
                        replayed_command_admission is not None
                    )
                    command_recovery["resumed_argv_sha256"] = stable_json_hash(argv)
                    assert_no_incident()
                    completed = _run_owned_process_group(
                        argv,
                        cwd=tree,
                        env=environment,
                        timeout_seconds=timeout_seconds,
                        launch_guard=incident_launch_guard(),
                    )
                    validated_command_recovery = command_recovery
                else:
                    completed = subprocess.CompletedProcess(
                        argv,
                        124,
                        stdout="",
                        stderr="recovered_validate_step4_finalizer_only_inflight",
                    )
                    validated_step4_finalizer_recovery = True
                recovered_from_inflight = True
            else:
                raise _fail("child_inflight_proof_invalid")
        else:
            if proof_path.exists() or proof_path.is_symlink():
                raise _fail("child_inflight_unclassified_no_rerun")
            replayed_command_admission = _resolve_replayable_command_recovery(
                state=state,
                trust=trust,
                installation_id=installation_id,
                job_id=job_id,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
                workspace=workspace,
                inflight_path=inflight_path,
                proof=None,
            )
            if replayed_command_admission is None:
                raise _fail("child_inflight_unclassified_no_rerun")
            recovery_receipt = replayed_command_admission["receipt"]
            command_recovery = dict(recovery_receipt["boundary"])
            required_stage = str(
                command_recovery["required_termination_stage"]
            )
            terminated = validate_latest_evo_child_agent_termination(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                workspace_root=workspace,
                worktree=tree,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_pin=expected_host_trust_manifest_sha256,
                required_stage=required_stage,
            )
            termination_ref = _ref(
                Path(terminated["termination_receipt_path"])
            )
            if (
                terminated.get("process_tree_absent") is not True
                or termination_ref
                != recovery_receipt["latest_container_termination"]
                or termination_ref == prior_container_termination_ref
            ):
                raise _fail("child_inflight_command_recovery_not_latest")
            start_step = str(command_recovery["required_start_step"])
            argv = _replace_argv_value(argv, "--start-step", start_step)
            recovery_path = replayed_command_admission["admission_path"]
            argv.extend(
                [
                    "--evo-child-command-recovery-admission",
                    str(recovery_path),
                ]
            )
            command_recovery["recovery_admission"] = _ref(recovery_path)
            command_recovery["replayed_signed_admission"] = True
            command_recovery["resumed_argv_sha256"] = stable_json_hash(argv)
            assert_no_incident()
            completed = _run_owned_process_group(
                argv,
                cwd=tree,
                env=environment,
                timeout_seconds=timeout_seconds,
                launch_guard=incident_launch_guard(),
            )
            validated_command_recovery = command_recovery
            recovered_from_inflight = True
    else:
        try:
            assert_no_incident()
            completed = _run_owned_process_group(
                argv,
                cwd=tree,
                env=environment,
                timeout_seconds=timeout_seconds,
                launch_guard=incident_launch_guard(),
            )
        except subprocess.TimeoutExpired as exc:
            reconcile_evo_child_agent_stage_containers(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                workspace_root=workspace,
                worktree=tree,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_pin=expected_host_trust_manifest_sha256,
            )
            recovery = web_factor_proof_oos_recovery_state(workspace, child_report_id)
            if recovery.get("recovery_required") is not True:
                raise _fail("child_ultimate_timeout_without_recovery_checkpoint") from exc
            completed = subprocess.CompletedProcess(
                argv,
                124,
                stdout=(exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""),
                stderr=(exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""),
            )
        except BaseException:
            reconcile_evo_child_agent_stage_containers(
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                workspace_root=workspace,
                worktree=tree,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_pin=expected_host_trust_manifest_sha256,
            )
            raise
    resume_start: str | None = None
    # Information-release recovery is authoritative before proof freshness.
    # A crash can publish a partial OOS state without ever replacing the
    # wrapper proof; treating that stale/missing proof first would strand the
    # only safe finalizer-only recovery route.
    recovery = web_factor_proof_oos_recovery_state(workspace, child_report_id)
    proof_ref: dict[str, Any] | None = None
    proof: dict[str, Any] = {}
    if (
        recovery.get("recovery_required") is True
        or validated_step4_finalizer_recovery
    ):
        if proof_path.is_file() and not proof_path.is_symlink():
            candidate_ref = _ref(proof_path)
            if (
                prior_proof_ref is None
                or candidate_ref["sha256"] != prior_proof_ref["sha256"]
            ):
                try:
                    candidate = json.loads(proof_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    candidate = None
                if isinstance(candidate, dict) and candidate.get(
                    "report_id"
                ) == child_report_id:
                    proof_ref = candidate_ref
                    proof = candidate
        proof_status = (
            "VALIDATE_STEP4_COMPLETE_FINALIZER_ONLY_RECOVERY"
            if validated_step4_finalizer_recovery
            else str(
                proof.get("status") or "RECOVERY_REQUIRED_NO_FRESH_PROOF"
            ).upper()
        )
        resume_start = "6"
        status = CHILD_RECOVERY_READY
    else:
        proof_ref = _ref(proof_path)
        if (
            prior_proof_ref is not None
            and prior_proof_ref["sha256"] == proof_ref["sha256"]
        ):
            raise _fail("child_ultimate_stale_proof")
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise _fail("child_ultimate_proof_json") from exc
        if not isinstance(proof, dict) or proof.get("report_id") != child_report_id:
            raise _fail("child_ultimate_proof_identity")
        proof_status = str(proof.get("status") or "").upper()
        expected_requested_steps = {
            "3b": ["3b", "4", "5", "6"],
            "4": ["4", "5", "6"],
            "5": ["5", "6"],
            "6": ["6"],
        }[start_step]
        if proof.get("requested_steps") != expected_requested_steps:
            raise _fail("child_ultimate_requested_steps")
        command_rows = proof.get("commands")
        if not isinstance(command_rows, list) or any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("returncode"), int)
            for row in command_rows
        ):
            raise _fail("child_ultimate_command_evidence")
        if proof_status == "PAUSED" and completed.returncode == 0:
            resume_start = required_web_resume_start_step(
                workspace, child_report_id
            )
            if resume_start not in {"4", "5", "6"}:
                raise _fail("child_pause_resume_point")
            status = CHILD_RESUME_READY
        elif proof_status == "PASS" and completed.returncode == 0 or proof_status == "FAIL" or completed.returncode != 0:
            status = CHILD_TERMINAL
        else:
            raise _fail("child_ultimate_proof_status")

    container_termination: dict[str, Any] | None = None
    container_attempt_exists = bool(
        container_root.is_dir()
        and not container_root.is_symlink()
        and any(container_root.glob("inflight__*.json"))
    )
    termination_required = bool(
        recovery.get("recovery_required") is True
        or validated_step4_finalizer_recovery
        or (proof_status in {"PAUSED", "PASS"} and completed.returncode == 0)
    )
    if termination_required or container_attempt_exists:
        terminated = validate_latest_evo_child_agent_termination(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            workspace_root=workspace,
            worktree=tree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_trust_manifest_sha256,
            required_stage=("validate_step4" if termination_required else None),
        )
        termination_path = Path(terminated["termination_receipt_path"])
        termination_receipt = terminated["termination_receipt"]
        if (
            terminated.get("process_tree_absent") is not True
            or not isinstance(termination_receipt, Mapping)
            or not isinstance(termination_receipt.get("receipt_id"), str)
        ):
            raise _fail("child_container_termination_authority")
        container_termination = {
            "receipt": _ref(termination_path),
            "receipt_id": termination_receipt["receipt_id"],
            "stage_name": terminated["stage_name"],
            "process_tree_absent": True,
        }
    evidence_payload = {
        "version": "factorforge_console_evo_child_evidence_tree_v1",
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "attempt": attempt,
        "entries": _workspace_evidence_tree(workspace),
    }
    evidence_payload["content_sha256"] = stable_json_hash(evidence_payload)
    evidence_path = runtime_root / f"evidence_tree__{attempt:04d}.json"
    _write_once(evidence_path, _canonical_bytes(evidence_payload))
    core = {
        "receipt_type": "EVO_CHILD_ULTIMATE_EXECUTION",
        "runtime_version": CHILD_RUNTIME_VERSION,
        "status": status,
        "identity": expected_identity,
        "execution_ready_receipt_id": checkpoint["receipt_id"],
        "previous_execution_receipt_id": (
            prior.get("receipt_id") if prior is not None else None
        ),
        "resume_admission": resume_admission_ref,
        "inflight_attempt": _ref(inflight_path),
        "attempt": attempt,
        "start_step": start_step,
        "argv_sha256": (
            inflight["argv_sha256"]
            if validated_command_recovery is not None
            else stable_json_hash(argv)
        ),
        "returncode": completed.returncode,
        "stdout_tail_sha256": hashlib.sha256(
            completed.stdout[-16_000:].encode("utf-8")
        ).hexdigest(),
        "stderr_tail_sha256": hashlib.sha256(
            completed.stderr[-16_000:].encode("utf-8")
        ).hexdigest(),
        "proof": proof_ref,
        "previous_proof": prior_proof_ref,
        "child_evidence_tree": _ref(evidence_path),
        "proof_status": proof_status,
        "recovered_from_inflight": recovered_from_inflight,
        "command_recovery": validated_command_recovery,
        "container_termination": container_termination,
        "resume_start_step": resume_start,
        "authority": {
            "parent_execution_allowed": False,
            "child_execution_allowed": status == CHILD_RESUME_READY,
            "allowed_child_start_step": resume_start,
            "finalizer_only": status == CHILD_RECOVERY_READY,
            "oos_release_allowed": False,
            # A wrapper PASS proves only that the requested command contract
            # completed.  It is never scientific verdict authority.  The
            # separate EVO_CHILD_TERMINAL_CHECKPOINT validator replays the
            # formal terminal closure before it may issue ACCEPT or REJECT.
            "factor_verdict": "NOT_ISSUED",
            "scientific_verdict_issued": False,
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    receipt_path = runtime_root / f"execution__{attempt:04d}.json"
    receipt = _sign_runtime_receipt_under_incident_guard(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        report_id=child_report_id,
        store=store,
        path=receipt_path,
        core=core,
    )
    return {
        "verdict": "PASS",
        "status": status,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "resume_start_step": resume_start,
        "execution_receipt_path": str(receipt_path),
        "execution_receipt_sha256": _sha256(receipt_path),
        "proof_path": str(proof_path) if proof_ref is not None else None,
        "proof_sha256": proof_ref["sha256"] if proof_ref is not None else None,
        "returncode": completed.returncode,
        "proof_status": proof_status,
        "scientific_factor_verdict": core["authority"]["factor_verdict"],
        "terminal_checkpoint": False,
        "host_execution_receipt_verified": True,
        "idempotent_replay": False,
    }


__all__ = [
    "BLOCK_EVO_CHILD_RUNTIME",
    "CHILD_EXECUTION_READY",
    "CHILD_PHASE_READY",
    "CHILD_QUALIFICATION_READY",
    "CHILD_QUALIFICATION_WAIT",
    "CHILD_RECOVERY_READY",
    "CHILD_RESUME_READY",
    "CHILD_RUNTIME_VERSION",
    "CHILD_TERMINAL",
    "EvoChildRuntimeError",
    "execute_evo_child_ready",
    "load_evo_child_execution_baseline",
    "load_latest_evo_child_execution_baseline",
    "load_pending_evo_child_phase_inflight",
    "materialize_evo_child_phase_checkpoint",
    "materialize_evo_child_phase_inflight",
    "materialize_evo_child_qualification_checkpoint",
    "materialize_evo_child_terminal_checkpoint",
    "prepare_evo_child_execution",
    "validate_evo_child_command_recovery_admission",
    "validate_evo_child_execution_state",
    "validate_evo_child_phase_checkpoint",
    "validate_evo_child_phase_inflight",
    "validate_evo_child_qualification_checkpoint",
    "validate_evo_child_terminal_checkpoint",
]
