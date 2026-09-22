from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from factor_factory.console.evo_child_catalog import (
    validate_materialized_evo_child_calendar_projection,
)
from factor_factory.console.private_job_root import (
    PrivateJobRootError,
    ensure_host_private_job_subdirectory,
)
from factor_factory.evo_oos import formal_oos_incident_reasons
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
    validate_oos_exposure_private_registry_guard,
)
from factor_factory.research_conjecture import workspace_runtime_trust_manifest
from factor_factory.research_org.contracts import stable_json_hash
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
)

CONTAINER_ADMISSION_VERSION = "factorforge_console_evo_child_container_admission_v2"
CONTAINER_TERMINATION_VERSION = "factorforge_console_evo_child_container_termination_v1"
CONTAINER_INFLIGHT_VERSION = "factorforge_console_evo_child_container_inflight_v1"
CONTAINER_RECONCILIATION_VERSION = (
    "factorforge_console_evo_child_container_reconciliation_v1"
)
CONTAINER_ADMISSION_TYPE = "EVO_CHILD_AGENT_STAGE_CONTAINER_ADMISSION"
CONTAINER_TERMINATION_TYPE = "EVO_CHILD_AGENT_STAGE_CONTAINER_TERMINATION"
CONTAINER_INFLIGHT_TYPE = "EVO_CHILD_AGENT_STAGE_CONTAINER_INFLIGHT"
CONTAINER_RECONCILIATION_TYPE = "EVO_CHILD_AGENT_STAGE_CONTAINER_RECONCILIATION"
CONTAINER_ADMITTED = "HOST_ADMITTED_CLOSED_EVO_CHILD_CONTAINER"
CONTAINER_TERMINATED = "HOST_CONFIRMED_CONTAINER_PROCESS_TREE_ABSENT"
CONTAINER_RECONCILED = "HOST_RECONCILED_CONTAINER_PROCESS_TREE_ABSENT"
BLOCK_EVO_CHILD_CONTAINER = "BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_INVALID"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_IMAGE_DIGEST = re.compile(
    r"(?:[a-z0-9][a-z0-9._/-]{0,239}@)?sha256:[0-9a-f]{64}\Z"
)
_MEMORY = re.compile(r"[1-9][0-9]{0,5}[bkmg]\Z")
_CPUS = re.compile(r"(?:0\.[0-9]{1,3}|[1-9][0-9]{0,2}(?:\.[0-9]{1,3})?)\Z")
_TMPFS = re.compile(
    r"size=[1-9][0-9]{0,5}[kmg],mode=1777,noexec,nosuid,nodev\Z"
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}\Z")
_MAX_PRIVATE_JSON = 2 * 1024 * 1024
_MAX_STAGE_LOG_BYTES = 64 * 1024 * 1024
_LOG_TAIL_BYTES = 16 * 1024
_RUNTIME_CONTROL_TIMEOUT = 20

_STAGE_SCRIPTS = {
    "run_step3b": "skills/factor-forge-step3/scripts/run_step3b.py",
    "validate_step3b": "skills/factor-forge-step3/scripts/validate_step3b.py",
    "run_step4": "skills/factor-forge-step4/scripts/run_step4.py",
    "validate_step4": "skills/factor-forge-step4/scripts/validate_step4.py",
}
_PATH_ENV_KEYS = frozenset(
    {
        "FACTORFORGE_BACKTEST_BASE_CACHE_ROOT",
        "FACTORFORGE_DATA_CACHE",
        "FACTORFORGE_DATA_CATALOG",
        "FACTORFORGE_FACTOR_WORKSPACE",
        "FACTORFORGE_FACTOR_WORKSPACE_MANIFEST",
        "FACTORFORGE_LOCAL_DATA_ROOT",
        "FACTORFORGE_LOCAL_MINUTE_ROOT",
        "FACTORFORGE_RESEARCH_ORG_PLAN",
        "FACTORFORGE_ROOT",
        "FACTORFORGE_SHARED_FACTORFORGE_ROOT",
        "FACTORFORGE_STATE_CATALOG",
        "FACTORFORGE_STATE_RESOLUTION",
        "FACTORFORGE_STEP4_FLOW_DAILY_CACHE",
        "FACTORFORGE_TRUSTED_TRADE_CAL_CSV",
        "QLIB_PROVIDER_URI",
    }
)
_SCALAR_ENV_KEYS = frozenset(
    {
        "FACTORFORGE_ALLOW_GENERIC_MINUTE_FULL_WINDOW",
        "FACTORFORGE_BACKTEST_BASE_MIN_CONTROL_DATE_RATIO",
        "FACTORFORGE_BACKTEST_BASE_MIN_CONTROL_TICKERS",
        "FACTORFORGE_CSV_OUTPUT_POLICY",
        "FACTORFORGE_DISABLE_ADAPTIVE_POLARS",
        "FACTORFORGE_ENABLE_EXPERIMENTAL_POLARS",
        "FACTORFORGE_ENABLE_OPERATOR_PROFILE",
        "FACTORFORGE_ENABLE_SHARED_EVALUATION_CONTEXT",
        "FACTORFORGE_FORMULA_ENGINE",
        "FACTORFORGE_REQUIRE_STATE_REUSE_CONTRACT",
        "FACTORFORGE_STEP3B_SAMPLE_MAX_DATES",
        "FACTORFORGE_STEP3B_SAMPLE_MAX_ROWS",
        "FACTORFORGE_STEP3B_SAMPLE_MAX_TICKERS",
        "FACTORFORGE_STEP4_DERIVED_STATE_BATCH_DAYS",
        "FACTORFORGE_STEP4_FLOW_DAILY_CACHE_DISABLE",
        "FACTORFORGE_STEP4_GENERIC_MINUTE_MAX_DAYS",
        "FACTORFORGE_STEP4_MINUTE_STREAM_BATCH_DAYS",
        "FACTORFORGE_TRUST_STEP3A_SORT_CONTRACT",
        "TZ",
    }
)
_FIXED_POLICY = {
    "allowed_stages": list(_STAGE_SCRIPTS),
    "agent_data_credentials": "FORBIDDEN",
    "capabilities": "DROP_ALL",
    "engine_mount": "READ_ONLY",
    "environment": "CODE_OWNED_ALLOWLIST",
    "host_private_state_mount": "FORBIDDEN",
    "network": "none",
    "oos_carrier_mount": "FORBIDDEN",
    "pid_namespace": "private",
    "root_filesystem": "READ_ONLY",
    "workspace_mount": "READ_WRITE",
}


class EvoChildContainerError(RuntimeError):
    """A fail-closed EVO child container contract violation."""

    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(dict.fromkeys(str(item) for item in reasons if item))
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_EVO_CHILD_CONTAINER}:{reason}"


def _fail(reason: str) -> EvoChildContainerError:
    return EvoChildContainerError([_token(reason)])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
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
    except (TypeError, ValueError) as exc:
        raise _fail("non_canonical_json") from exc


def _canonical_directory(path: Path | str, *, label: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise _fail(f"{label}_symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(f"{label}_missing") from exc
    if not resolved.is_dir():
        raise _fail(f"{label}_not_directory")
    return resolved


def _private_directory(path: Path, *, create: bool = False) -> Path:
    candidate = path.expanduser()
    if create and not candidate.exists() and not candidate.is_symlink():
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:
            pass
    if candidate.is_symlink() or not candidate.is_dir():
        raise _fail("unsafe_private_directory")
    metadata = candidate.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise _fail("unsafe_private_directory")
    return candidate.resolve(strict=True)


def _state_root_directory(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_symlink() or not candidate.is_dir():
        raise _fail("unsafe_state_root")
    metadata = candidate.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or mode & 0o007
        or mode & 0o700 != 0o700
    ):
        raise _fail("unsafe_state_root")
    return candidate.resolve(strict=True)


def _private_subdirectory(root: Path, *parts: str, create: bool = False) -> Path:
    current = _state_root_directory(root)
    for part in parts:
        if not _SAFE_ID.fullmatch(part) or part in {".", ".."}:
            raise _fail("unsafe_private_directory_component")
        current = _private_directory(current / part, create=create)
    return current


def _assert_disjoint(path: Path, roots: Sequence[Path], *, label: str) -> None:
    for root in roots:
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            raise _fail(f"overlapping_roots:{label}")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _stable_regular_file(
    path: Path | str,
    *,
    label: str,
    max_bytes: int = _MAX_STAGE_LOG_BYTES,
    executable: bool = False,
    allow_empty: bool = False,
) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise _fail(f"{label}_symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(f"{label}_missing") from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as exc:
        raise _fail(f"{label}_open") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < (0 if allow_empty else 1)
            or before.st_size > max_bytes
            or (executable and not before.st_mode & 0o111)
        ):
            raise _fail(f"{label}_unsafe")
        digest = hashlib.sha256()
        length = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            length += len(chunk)
        after = os.fstat(descriptor)
        current = os.stat(resolved, follow_symlinks=False)
        identity = lambda item: (
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_ctime_ns,
            item.st_nlink,
        )
        if identity(before) != identity(after) or identity(before) != identity(current):
            raise _fail(f"{label}_changed_during_read")
        if length != before.st_size:
            raise _fail(f"{label}_short_read")
        return {
            "path": str(resolved),
            "sha256": digest.hexdigest(),
            "size_bytes": before.st_size,
        }
    finally:
        os.close(descriptor)


def _read_private_file(path: Path | str, *, max_bytes: int = _MAX_PRIVATE_JSON) -> bytes:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise _fail("private_file_symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail("private_file_missing") from exc
    metadata = resolved.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= max_bytes
    ):
        raise _fail("private_file_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(resolved, flags)
    try:
        before = os.fstat(descriptor)
        payload = bytearray()
        while len(payload) <= max_bytes:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise _fail("private_file_changed_during_read")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _load_private_json(path: Path | str) -> dict[str, Any]:
    try:
        payload = json.loads(_read_private_file(path).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("private_json_invalid") from exc
    if not isinstance(payload, dict):
        raise _fail("private_json_object_required")
    return payload


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path: Path, payload: bytes) -> bool:
    if path.exists() or path.is_symlink():
        if _read_private_file(path, max_bytes=max(len(payload), 1)) != payload:
            raise _fail(f"write_once_mismatch:{path.name}")
        return False
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if _read_private_file(path, max_bytes=max(len(payload), 1)) != payload:
            raise _fail(f"write_once_mismatch:{path.name}")
        return False
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(path.parent)
    return True


def _validate_ids(*values: str) -> None:
    if not all(isinstance(value, str) and _SAFE_ID.fullmatch(value) for value in values):
        raise _fail("identity")


def _validate_resources(
    *, memory: str, cpus: str, pids: int, tmpfs: str
) -> dict[str, Any]:
    if not isinstance(memory, str) or not _MEMORY.fullmatch(memory):
        raise _fail("memory")
    if not isinstance(cpus, str) or not _CPUS.fullmatch(cpus):
        raise _fail("cpus")
    try:
        cpu_value = Decimal(cpus)
    except InvalidOperation as exc:
        raise _fail("cpus") from exc
    if cpu_value <= 0 or cpu_value > 256:
        raise _fail("cpus")
    if isinstance(pids, bool) or not isinstance(pids, int) or not 8 <= pids <= 4096:
        raise _fail("pids")
    if not isinstance(tmpfs, str) or not _TMPFS.fullmatch(tmpfs):
        raise _fail("tmpfs")
    return {"memory": memory, "cpus": cpus, "pids": pids, "tmpfs": tmpfs}


def _validate_host_trust(
    *,
    workspace: Path,
    trust: Path,
    installation_id: str,
    parent_report_id: str,
    expected_pin: str,
) -> Any:
    if not _HEX64.fullmatch(expected_pin or ""):
        raise _fail("external_host_trust_pin_required")
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    manifest = workspace_runtime_trust_manifest(workspace, report_id=parent_report_id)
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest != store.public_manifest
        or manifest.get("manifest_sha256") != expected_pin
    ):
        raise _fail("trust_manifest_pin")
    return store


def _content_hash(receipt: Mapping[str, Any]) -> str:
    core = {
        key: value
        for key, value in receipt.items()
        if key
        not in {
            "content_sha256",
            "contract_version",
            "issuer",
            "receipt_id",
            "signature",
        }
    }
    return stable_json_hash(core)


def _validate_catalog_projection_binding(
    *,
    engine: Path,
    workspace: Path,
    snapshot_path: Path | str,
    projection_path: Path | str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    snapshot = _stable_regular_file(
        snapshot_path,
        label="catalog_snapshot",
        max_bytes=32 * 1024 * 1024,
    )
    projection = _stable_regular_file(
        projection_path,
        label="catalog_projection",
        max_bytes=2 * 1024 * 1024,
    )
    snapshot_file = Path(snapshot["path"])
    projection_file = Path(projection["path"])
    for label, path in (
        ("catalog_snapshot", snapshot_file),
        ("catalog_projection", projection_file),
    ):
        try:
            path.relative_to(engine)
        except ValueError as exc:
            raise _fail(f"{label}_outside_engine") from exc
        if path == workspace or path.is_relative_to(workspace):
            raise _fail(f"{label}_inside_writable_workspace")
    try:
        payload = json.loads(projection_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("catalog_projection_json") from exc
    identity = payload.get("identity") if isinstance(payload, dict) else None
    bound_snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or payload.get("projection_version")
        != "factorforge_console_evo_child_catalog_projection_v1"
        or payload.get("status") != "HOST_PROJECTED_APPROVED_CATALOG"
        or identity
        != {
            "job_id": job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
        }
        or payload.get("content_sha256") != _content_hash(payload)
        or not isinstance(bound_snapshot, dict)
        or set(bound_snapshot) != {"path", "sha256", "size_bytes"}
        or engine / str(bound_snapshot.get("path") or "") != snapshot_file
        or bound_snapshot.get("sha256") != snapshot["sha256"]
        or bound_snapshot.get("size_bytes") != snapshot["size_bytes"]
    ):
        raise _fail("catalog_projection_binding")
    return {"snapshot": snapshot, "projection": projection}


def _admission_root(
    state: Path, job_id: str, child_report_id: str, *, create: bool = False
) -> Path:
    try:
        return ensure_host_private_job_subdirectory(
            state,
            job_id,
            ("evo-child-container", child_report_id),
            create=create,
        )
    except PrivateJobRootError as exc:
        raise _fail("unsafe_private_job_root") from exc


def _validate_engine_commit(engine: Path, expected_commit: str) -> str:
    """Bind a claimed execution commit to the admitted worktree itself."""

    if re.fullmatch(r"[0-9a-f]{40,64}", expected_commit or "") is None:
        raise _fail("engine_commit")
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(engine), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _fail("engine_commit_unverifiable") from exc
    actual = str(result.stdout or "").strip().lower()
    if (
        result.returncode != 0
        or re.fullmatch(r"[0-9a-f]{40,64}", actual) is None
        or actual != expected_commit
    ):
        raise _fail("engine_commit_mismatch")
    return actual


def materialize_evo_child_container_admission(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    engine_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    container_runtime: Path | str,
    image_digest: str,
    memory: str,
    cpus: str,
    pids: int,
    tmpfs: str,
    engine_commit: str,
    catalog_snapshot_path: Path | str,
    catalog_projection_path: Path | str,
    calendar_projection_path: Path | str,
) -> dict[str, Any]:
    """Create an immutable Host-signed admission for four child Agent stages."""

    _validate_ids(installation_id, job_id, parent_report_id, child_report_id)
    if parent_report_id == child_report_id:
        raise _fail("parent_child_identity_collision")
    if not isinstance(image_digest, str) or not _IMAGE_DIGEST.fullmatch(image_digest):
        raise _fail("immutable_image_digest_required")
    if re.fullmatch(r"[0-9a-f]{40,64}", engine_commit or "") is None:
        raise _fail("engine_commit")
    resources = _validate_resources(
        memory=memory, cpus=cpus, pids=pids, tmpfs=tmpfs
    )
    state = _state_root_directory(_canonical_directory(state_root, label="state_root"))
    trust = _canonical_directory(trust_root, label="trust_root")
    workspace = _canonical_directory(workspace_root, label="workspace_root")
    tree = _canonical_directory(worktree, label="worktree")
    engine = _canonical_directory(engine_root, label="engine_root")
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=workspace,
        report_id=child_report_id,
        trust_root=trust,
        installation_id=installation_id,
    )
    if incident_reasons:
        raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
    if engine != tree:
        raise _fail("engine_root_must_equal_pinned_worktree")
    engine_commit = _validate_engine_commit(engine, engine_commit)
    try:
        workspace.relative_to(tree)
    except ValueError as exc:
        raise _fail("workspace_outside_worktree") from exc
    _assert_disjoint(tree, (state, trust), label="worktree_private_state")
    _assert_disjoint(workspace, (state, trust), label="workspace_private_state")
    store = _validate_host_trust(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        parent_report_id=parent_report_id,
        expected_pin=expected_host_trust_manifest_sha256,
    )
    runtime = _stable_regular_file(
        container_runtime, label="container_runtime", executable=True
    )
    scripts: dict[str, dict[str, Any]] = {}
    for stage_name, relative in _STAGE_SCRIPTS.items():
        script = _stable_regular_file(
            engine / relative,
            label=f"stage_script:{stage_name}",
        )
        script["relative_path"] = relative
        scripts[stage_name] = script
    catalog_projection = _validate_catalog_projection_binding(
        engine=engine,
        workspace=workspace,
        snapshot_path=catalog_snapshot_path,
        projection_path=catalog_projection_path,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
    )
    calendar_resolution = validate_materialized_evo_child_calendar_projection(
        engine_root=engine,
        workspace_root=workspace,
        projection_path=calendar_projection_path,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
    )
    calendar_projection = {
        "snapshot": _stable_regular_file(
            calendar_resolution["snapshot_path"],
            label="calendar_snapshot",
            max_bytes=32 * 1024 * 1024,
        ),
        "projection": _stable_regular_file(
            calendar_resolution["projection_path"],
            label="calendar_projection",
            max_bytes=2 * 1024 * 1024,
        ),
        "calendar_identity": calendar_resolution["projection"][
            "calendar_identity"
        ],
    }
    root = _admission_root(state, job_id, child_report_id, create=True)
    admission_path = root / "admission.json"
    core = {
        "receipt_type": CONTAINER_ADMISSION_TYPE,
        "admission_version": CONTAINER_ADMISSION_VERSION,
        "status": CONTAINER_ADMITTED,
        "identity": {
            "installation_id": installation_id,
            "job_id": job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
        },
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
        "roots": {
            "state_root": str(state),
            "trust_root": str(trust),
            "worktree": str(tree),
            "engine_root": str(engine),
            "workspace_root": str(workspace),
        },
        "container": {
            "runtime": runtime,
            "image_digest": image_digest,
            "resources": resources,
        },
        "engine_identity": {
            "commit": engine_commit,
            "source": "HOST_VALIDATED_DETACHED_WORKTREE",
        },
        "stages": scripts,
        "catalog_projection": catalog_projection,
        "calendar_projection": calendar_projection,
        "policy": dict(_FIXED_POLICY),
    }
    core["content_sha256"] = stable_json_hash(core)
    with oos_exposure_private_registry_guard(
        trust,
        installation_id=installation_id,
    ):
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=workspace,
            report_id=child_report_id,
            trust_root=trust,
            installation_id=installation_id,
        )
        if incident_reasons:
            raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
        admission = store.sign("host_admission", core)
        _write_once(admission_path, _canonical_bytes(admission))
    validated = validate_evo_child_container_admission(
        admission_path=admission_path,
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
        "status": CONTAINER_ADMITTED,
        "factor_verdict": "NOT_ISSUED",
        "admission_path": str(admission_path),
        "admission_sha256": _sha256_bytes(_read_private_file(admission_path)),
        "admission": validated["admission"],
    }


def validate_evo_child_container_admission(
    *,
    admission_path: Path | str,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_pin: str,
) -> dict[str, Any]:
    """Replay current identity, signature, runtime and mount-policy admission."""

    return _validate_evo_child_container_admission_impl(
        admission_path=admission_path,
        state_root=state_root,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        workspace_root=workspace_root,
        worktree=worktree,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_pin=expected_host_pin,
        allow_oos_incident_for_cleanup=False,
    )


def _validate_evo_child_container_admission_impl(
    *,
    admission_path: Path | str,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_pin: str,
    allow_oos_incident_for_cleanup: bool,
    incident_guard: object | None = None,
) -> dict[str, Any]:
    """Internal structural replay, optionally retained solely for cleanup."""

    _validate_ids(installation_id, job_id, parent_report_id, child_report_id)
    state = _state_root_directory(_canonical_directory(state_root, label="state_root"))
    trust = _canonical_directory(trust_root, label="trust_root")
    workspace = _canonical_directory(workspace_root, label="workspace_root")
    tree = _canonical_directory(worktree, label="worktree")
    if allow_oos_incident_for_cleanup:
        validate_oos_exposure_private_registry_guard(
            incident_guard,
            trust_root=trust,
            installation_id=installation_id,
        )
    if not allow_oos_incident_for_cleanup:
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
        raise _fail("workspace_outside_worktree") from exc
    expected_root = _admission_root(state, job_id, child_report_id)
    candidate_path = Path(admission_path).expanduser()
    if candidate_path.is_symlink():
        raise _fail("admission_symlink")
    try:
        path = candidate_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail("admission_missing") from exc
    if path != expected_root / "admission.json":
        raise _fail("admission_location")
    admission = _load_private_json(path)
    store = _validate_host_trust(
        workspace=workspace,
        trust=trust,
        installation_id=installation_id,
        parent_report_id=parent_report_id,
        expected_pin=expected_host_pin,
    )
    reasons = [
        _token(f"signature:{reason}")
        for reason in store.verify(admission, expected_issuer="host_admission")
    ]
    identity = admission.get("identity")
    roots = admission.get("roots")
    container = admission.get("container")
    stages = admission.get("stages")
    catalog_projection = admission.get("catalog_projection")
    calendar_projection = admission.get("calendar_projection")
    engine_identity = admission.get("engine_identity")
    expected_identity = {
        "installation_id": installation_id,
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
    }
    if (
        admission.get("receipt_type") != CONTAINER_ADMISSION_TYPE
        or admission.get("admission_version") != CONTAINER_ADMISSION_VERSION
        or admission.get("status") != CONTAINER_ADMITTED
        or identity != expected_identity
        or admission.get("expected_host_trust_manifest_sha256") != expected_host_pin
        or admission.get("policy") != _FIXED_POLICY
        or not isinstance(engine_identity, dict)
        or set(engine_identity) != {"commit", "source"}
        or re.fullmatch(
            r"[0-9a-f]{40,64}", str(engine_identity.get("commit") or "")
        )
        is None
        or engine_identity.get("source")
        != "HOST_VALIDATED_DETACHED_WORKTREE"
        or not isinstance(roots, dict)
        or set(roots)
        != {"state_root", "trust_root", "worktree", "engine_root", "workspace_root"}
        or roots.get("state_root") != str(state)
        or roots.get("trust_root") != str(trust)
        or roots.get("worktree") != str(tree)
        or roots.get("engine_root") != str(tree)
        or roots.get("workspace_root") != str(workspace)
        or not isinstance(container, dict)
        or set(container) != {"runtime", "image_digest", "resources"}
        or not isinstance(stages, dict)
        or set(stages) != set(_STAGE_SCRIPTS)
        or not isinstance(catalog_projection, dict)
        or not isinstance(calendar_projection, dict)
        or admission.get("content_sha256") != _content_hash(admission)
    ):
        reasons.append(_token("admission_shape_or_identity"))
    if isinstance(engine_identity, dict):
        try:
            _validate_engine_commit(
                tree, str(engine_identity.get("commit") or "")
            )
        except EvoChildContainerError as exc:
            reasons.extend(exc.reasons)
    runtime = container.get("runtime") if isinstance(container, dict) else None
    image_digest = container.get("image_digest") if isinstance(container, dict) else None
    resources = container.get("resources") if isinstance(container, dict) else None
    if not isinstance(runtime, dict) or set(runtime) != {"path", "sha256", "size_bytes"}:
        reasons.append(_token("runtime_binding_shape"))
    else:
        try:
            actual_runtime = _stable_regular_file(
                str(runtime.get("path") or ""),
                label="container_runtime",
                executable=True,
            )
            if actual_runtime != runtime:
                reasons.append(_token("runtime_binding_mismatch"))
        except EvoChildContainerError as exc:
            reasons.extend(exc.reasons)
    if not isinstance(image_digest, str) or not _IMAGE_DIGEST.fullmatch(image_digest):
        reasons.append(_token("immutable_image_digest_required"))
    try:
        if not isinstance(resources, dict) or resources != _validate_resources(
            memory=resources.get("memory") if isinstance(resources, dict) else "",
            cpus=resources.get("cpus") if isinstance(resources, dict) else "",
            pids=resources.get("pids") if isinstance(resources, dict) else 0,
            tmpfs=resources.get("tmpfs") if isinstance(resources, dict) else "",
        ):
            reasons.append(_token("resource_binding"))
    except EvoChildContainerError as exc:
        reasons.extend(exc.reasons)
    try:
        if not isinstance(calendar_projection, dict) or set(
            calendar_projection
        ) != {"snapshot", "projection", "calendar_identity"}:
            raise _fail("calendar_projection_binding_shape")
        actual_calendar = validate_materialized_evo_child_calendar_projection(
            engine_root=tree,
            workspace_root=workspace,
            projection_path=calendar_projection["projection"].get("path", ""),
            job_id=job_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
        )
        expected_calendar_projection = {
            "snapshot": _stable_regular_file(
                actual_calendar["snapshot_path"],
                label="calendar_snapshot",
                max_bytes=32 * 1024 * 1024,
            ),
            "projection": _stable_regular_file(
                actual_calendar["projection_path"],
                label="calendar_projection",
                max_bytes=2 * 1024 * 1024,
            ),
            "calendar_identity": actual_calendar["projection"][
                "calendar_identity"
            ],
        }
        if expected_calendar_projection != calendar_projection:
            reasons.append(_token("calendar_projection_binding_mismatch"))
    except (EvoChildContainerError, RuntimeError, KeyError, TypeError) as exc:
        if isinstance(exc, EvoChildContainerError):
            reasons.extend(exc.reasons)
        else:
            reasons.append(_token("calendar_projection_binding_invalid"))
    for stage_name, relative in _STAGE_SCRIPTS.items():
        bound = stages.get(stage_name) if isinstance(stages, dict) else None
        if (
            not isinstance(bound, dict)
            or set(bound) != {"path", "relative_path", "sha256", "size_bytes"}
            or bound.get("relative_path") != relative
            or bound.get("path") != str(tree / relative)
        ):
            reasons.append(_token(f"stage_binding_shape:{stage_name}"))
            continue
        try:
            actual = _stable_regular_file(
                tree / relative, label=f"stage_script:{stage_name}"
            )
            actual["relative_path"] = relative
            if actual != bound:
                reasons.append(_token(f"stage_hash_mismatch:{stage_name}"))
        except EvoChildContainerError as exc:
            reasons.extend(exc.reasons)
    try:
        actual_catalog_projection = _validate_catalog_projection_binding(
            engine=tree,
            workspace=workspace,
            snapshot_path=(
                catalog_projection.get("snapshot", {}).get("path", "")
                if isinstance(catalog_projection, dict)
                else ""
            ),
            projection_path=(
                catalog_projection.get("projection", {}).get("path", "")
                if isinstance(catalog_projection, dict)
                else ""
            ),
            job_id=job_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
        )
        if actual_catalog_projection != catalog_projection:
            reasons.append(_token("catalog_projection_binding_mismatch"))
    except EvoChildContainerError as exc:
        reasons.extend(exc.reasons)
    try:
        _assert_disjoint(tree, (state, trust), label="worktree_private_state")
        _assert_disjoint(workspace, (state, trust), label="workspace_private_state")
    except EvoChildContainerError as exc:
        reasons.extend(exc.reasons)
    if reasons:
        raise EvoChildContainerError(reasons)
    return {
        "verdict": "PASS",
        "status": CONTAINER_ADMITTED,
        "factor_verdict": "NOT_ISSUED",
        "admission_path": path,
        "admission": admission,
    }


def _path_within(value: str, roots: Sequence[Path], *, key: str) -> str:
    candidate = Path(value).expanduser()
    if candidate.is_symlink():
        raise _fail(f"environment_path_symlink:{key}")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail(f"environment_path_missing:{key}") from exc
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise _fail(f"environment_path_outside_mounts:{key}")
    return str(resolved)


def _closed_environment(
    source: Mapping[str, str], *, workspace: Path, engine: Path
) -> dict[str, str]:
    if not isinstance(source, Mapping):
        raise _fail("environment_mapping_required")
    output = {
        "AWS_EC2_METADATA_DISABLED": "true",
        "FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY": "DENY",
        "FACTORFORGE_FACTOR_WORKSPACE": str(workspace),
        "FACTORFORGE_REPO_ROOT": str(engine),
        "FACTORFORGE_ROOT": str(workspace),
        "FACTORFORGE_ULTIMATE_RUN": "1",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(engine),
        "TMPDIR": "/tmp",
    }
    for raw_key, raw_value in source.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            raise _fail("environment_string_pairs_required")
        if raw_key in _PATH_ENV_KEYS:
            output[raw_key] = _path_within(
                raw_value, (workspace, engine), key=raw_key
            )
        elif raw_key in _SCALAR_ENV_KEYS:
            if (
                not raw_value
                or len(raw_value) > 256
                or any(character in raw_value for character in "\x00\r\n")
                or not re.fullmatch(r"[A-Za-z0-9_.,:+/-]+", raw_value)
            ):
                raise _fail(f"environment_scalar:{raw_key}")
            output[raw_key] = raw_value
    # Callers may pass a full process environment.  Unknown keys are ignored,
    # never forwarded; this is a code-owned projection rather than a blacklist.
    return dict(sorted(output.items()))


def _validate_logical_command(
    *,
    stage_name: str,
    logical_command: Sequence[str],
    admission: Mapping[str, Any],
) -> list[str]:
    if stage_name not in _STAGE_SCRIPTS:
        raise _fail("unsupported_stage")
    if (
        isinstance(logical_command, (str, bytes))
        or not isinstance(logical_command, Sequence)
        or not all(isinstance(item, str) for item in logical_command)
    ):
        raise _fail("logical_command_string_sequence_required")
    command = list(logical_command)
    expected_script = _STAGE_SCRIPTS[stage_name]
    if len(command) < 4 or command[0] != sys.executable or command[1] != expected_script:
        raise _fail("logical_command_template")
    identity = admission["identity"]
    roots = admission["roots"]
    workspace = Path(roots["workspace_root"])
    pin = admission["expected_host_trust_manifest_sha256"]
    if stage_name in {"run_step3b", "validate_step3b", "run_step4"}:
        expected = [sys.executable, expected_script, "--manifest", command[3]]
        manifest = Path(command[3]).expanduser()
        if manifest.is_symlink():
            raise _fail("manifest_symlink")
        try:
            resolved_manifest = manifest.resolve(strict=True)
            resolved_manifest.relative_to(workspace)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _fail("manifest_outside_workspace") from exc
        expected[3] = str(resolved_manifest)
        command[3] = str(resolved_manifest)
        if stage_name == "run_step4":
            expected.extend(["--expected-host-trust-manifest-sha256", pin])
    else:
        expected = [
            sys.executable,
            expected_script,
            "--report-id",
            identity["child_report_id"],
            "--expected-host-trust-manifest-sha256",
            pin,
        ]
    if command != expected:
        raise _fail("logical_command_template")
    return ["python3", *command[1:]]


def _mount(source: Path, *, readonly: bool) -> str:
    fields = [
        "type=bind",
        f"src={source}",
        f"dst={source}",
        "bind-propagation=rprivate",
    ]
    if readonly:
        fields.append("readonly")
    return ",".join(fields)


def _runtime_completed(
    runtime: str,
    args: Sequence[str],
    *,
    timeout: int = _RUNTIME_CONTROL_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [runtime, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            start_new_session=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _fail("container_runtime_control_failed") from exc


def resolve_evo_child_container_image_digest(
    container_runtime: Path | str,
    image_reference: str,
) -> str:
    """Resolve one caller image reference to an immutable runtime image ID."""

    runtime = _stable_regular_file(
        container_runtime, label="container_runtime", executable=True
    )["path"]
    if (
        not isinstance(image_reference, str)
        or not image_reference
        or len(image_reference) > 512
        or any(character in image_reference for character in "\x00\r\n")
        or image_reference.startswith("-")
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,511}", image_reference)
    ):
        raise _fail("image_reference")
    process = _runtime_completed(
        runtime,
        ["image", "inspect", "--format", "{{.Id}}", image_reference],
    )
    if process.returncode != 0:
        raise _fail("image_digest_resolution_failed")
    lines = [line.strip() for line in process.stdout.splitlines() if line.strip()]
    if len(lines) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", lines[0]):
        raise _fail("image_digest_resolution_invalid")
    return lines[0]


def _container_not_found(
    process: subprocess.CompletedProcess[str], container_name: str
) -> bool:
    if process.returncode == 0:
        return False
    detail = f"{process.stdout or ''}\n{process.stderr or ''}".strip().lower()
    name = container_name.lower()
    return detail in {
        f"error: no such object: {name}",
        f"no such object: {name}",
        f"error response from daemon: no such object: {name}",
        f"error response from daemon: no such container: {name}",
        f"no such container: {name}",
    }


def _remove_and_confirm_absent(runtime: str, name: str) -> dict[str, Any]:
    remove = _runtime_completed(runtime, ["rm", "-f", name])
    inspect = _runtime_completed(runtime, ["inspect", name])
    remove_ok = remove.returncode == 0 or _container_not_found(remove, name)
    absent = _container_not_found(inspect, name)
    return {
        "remove_returncode": remove.returncode,
        "remove_ok": remove_ok,
        "inspect_returncode": inspect.returncode,
        "inspect_not_found": absent,
        "container_present": not absent,
        "process_tree_absent": bool(remove_ok and absent),
    }


def _prepare_container_name(admission: Mapping[str, Any], attempt: int) -> str:
    seed = ":".join(
        [
            admission["identity"]["installation_id"],
            admission["identity"]["job_id"],
            admission["identity"]["child_report_id"],
            admission["receipt_id"],
            str(attempt),
        ]
    )
    return f"ff-evo-child-{hashlib.sha256(seed.encode()).hexdigest()[:32]}"


def _workspace_tree(workspace: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for directory, dirnames, filenames in os.walk(workspace, followlinks=False):
        dirnames.sort()
        filenames.sort()
        base = Path(directory)
        for name in list(dirnames):
            candidate = base / name
            if candidate.is_symlink():
                raise _fail("workspace_tree_symlink")
        for name in filenames:
            candidate = base / name
            relative = candidate.relative_to(workspace).as_posix()
            metadata = candidate.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or metadata.st_size > 4 * 1024 * 1024 * 1024
            ):
                raise _fail("workspace_tree_unsafe_entry")
            bound = _stable_regular_file(
                candidate,
                label="workspace_tree_file",
                max_bytes=4 * 1024 * 1024 * 1024,
            )
            entries.append(
                {
                    "relative_path": relative,
                    "sha256": bound["sha256"],
                    "size_bytes": bound["size_bytes"],
                }
            )
            total_bytes += bound["size_bytes"]
            if len(entries) > 100_000 or total_bytes > 8 * 1024 * 1024 * 1024:
                raise _fail("workspace_tree_limit")
    return {
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "tree_sha256": stable_json_hash(entries),
    }


def _attempt_artifacts(root: Path) -> dict[str, dict[int, tuple[str, Path]]]:
    patterns = {
        "inflight": r"inflight__([0-9]{6})__([a-z0-9_]+)\.json",
        "termination": r"termination__([0-9]{6})__([a-z0-9_]+)\.json",
        "reconciliation": r"reconciliation__([0-9]{6})__([a-z0-9_]+)\.json",
    }
    output: dict[str, dict[int, tuple[str, Path]]] = {
        key: {} for key in patterns
    }
    for kind, pattern in patterns.items():
        for path in root.glob(f"{kind}__*.json"):
            match = re.fullmatch(pattern, path.name)
            if match is None or match.group(2) not in _STAGE_SCRIPTS:
                raise _fail(f"unexpected_{kind}_artifact")
            attempt = int(match.group(1))
            if attempt in output[kind]:
                raise _fail(f"duplicate_{kind}_attempt")
            _read_private_file(path)
            output[kind][attempt] = (match.group(2), path)
    return output


def _next_attempt(root: Path) -> int:
    artifacts = _attempt_artifacts(root)
    for attempt, (stage, _path) in artifacts["inflight"].items():
        termination = artifacts["termination"].get(attempt)
        reconciliation = artifacts["reconciliation"].get(attempt)
        if termination is None and reconciliation is None:
            raise _fail("unreconciled_inflight")
        if termination is not None and termination[0] != stage:
            raise _fail("inflight_termination_stage_mismatch")
        if reconciliation is not None and reconciliation[0] != stage:
            raise _fail("inflight_reconciliation_stage_mismatch")
    all_attempts = {
        attempt for values in artifacts.values() for attempt in values
    }
    return max(all_attempts, default=0) + 1


def _open_runner_lock(root: Path) -> int:
    lock_path = root / "runner.lock"
    descriptor = os.open(
        lock_path,
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or metadata.st_nlink != 1
    ):
        os.close(descriptor)
        raise _fail("unsafe_runner_lock")
    return descriptor


def _materialize_inflight(
    *,
    root: Path,
    store: Any,
    admission: Mapping[str, Any],
    attempt: int,
    stage_name: str,
    container_name: str,
    logical_command: Sequence[str],
    container_command: Sequence[str],
    closed_env: Mapping[str, str],
    mounts: Sequence[Mapping[str, str]],
) -> tuple[Path, dict[str, Any]]:
    core = {
        "receipt_type": CONTAINER_INFLIGHT_TYPE,
        "inflight_version": CONTAINER_INFLIGHT_VERSION,
        "status": "HOST_RECORDED_CONTAINER_LAUNCH_INTENT",
        "identity": dict(admission["identity"]),
        "attempt": attempt,
        "stage_name": stage_name,
        "admission_ref": {
            "receipt_id": admission["receipt_id"],
            "sha256": _sha256_bytes(_read_private_file(root / "admission.json")),
        },
        "container": {
            "runtime": dict(admission["container"]["runtime"]),
            "image_digest": admission["container"]["image_digest"],
            "container_name": container_name,
            "network": "none",
            "pid_namespace": "private",
            "mounts": [dict(item) for item in mounts],
        },
        "command": {
            "logical_sha256": stable_json_hash(list(logical_command)),
            "container_sha256": stable_json_hash(list(container_command)),
            "environment_sha256": stable_json_hash(dict(closed_env)),
            "script_sha256": admission["stages"][stage_name]["sha256"],
        },
        "factor_verdict": "NOT_ISSUED",
    }
    core["content_sha256"] = stable_json_hash(core)
    receipt = store.sign("host_admission", core)
    path = root / f"inflight__{attempt:06d}__{stage_name}.json"
    _write_once(path, _canonical_bytes(receipt))
    return path, receipt


def _validate_inflight_receipt(
    *,
    inflight: Mapping[str, Any],
    admission: Mapping[str, Any],
    store: Any,
    attempt: int,
    stage_name: str,
) -> list[str]:
    reasons = [
        _token(f"inflight_signature:{reason}")
        for reason in store.verify(inflight, expected_issuer="host_admission")
    ]
    container = inflight.get("container")
    command = inflight.get("command")
    expected_mounts = [
        {
            "source": admission["roots"]["engine_root"],
            "target": admission["roots"]["engine_root"],
            "mode": "ro",
        },
        {
            "source": admission["roots"]["workspace_root"],
            "target": admission["roots"]["workspace_root"],
            "mode": "rw",
        },
    ]
    if (
        inflight.get("receipt_type") != CONTAINER_INFLIGHT_TYPE
        or inflight.get("inflight_version") != CONTAINER_INFLIGHT_VERSION
        or inflight.get("status") != "HOST_RECORDED_CONTAINER_LAUNCH_INTENT"
        or inflight.get("identity") != admission["identity"]
        or inflight.get("attempt") != attempt
        or inflight.get("stage_name") != stage_name
        or inflight.get("admission_ref")
        != {
            "receipt_id": admission["receipt_id"],
            "sha256": admission.get("_file_sha256"),
        }
        or inflight.get("factor_verdict") != "NOT_ISSUED"
        or inflight.get("content_sha256") != _content_hash(inflight)
        or not isinstance(container, dict)
        or container.get("runtime") != admission["container"]["runtime"]
        or container.get("image_digest") != admission["container"]["image_digest"]
        or container.get("container_name")
        != _prepare_container_name(admission, attempt)
        or container.get("network") != "none"
        or container.get("pid_namespace") != "private"
        or container.get("mounts") != expected_mounts
        or not isinstance(command, dict)
        or command.get("script_sha256")
        != admission["stages"][stage_name]["sha256"]
        or not all(
            _HEX64.fullmatch(str(command.get(key) or ""))
            for key in (
                "logical_sha256",
                "container_sha256",
                "environment_sha256",
            )
        )
    ):
        reasons.append(_token("inflight_shape_or_binding"))
    return list(dict.fromkeys(reasons))


def _log_ref(path: Path) -> dict[str, Any]:
    bound = _stable_regular_file(path, label="stage_log", allow_empty=True)
    payload = path.read_bytes()
    return {
        "path": str(path),
        "sha256": bound["sha256"],
        "size_bytes": bound["size_bytes"],
        "tail": payload[-_LOG_TAIL_BYTES:].decode("utf-8", errors="replace"),
    }


def _run_attached(
    command: Sequence[str],
    *,
    timeout: float,
    stdout_path: Path,
    stderr_path: Path,
    on_started: Callable[[], None] | None = None,
) -> tuple[int, bool]:
    stdout_descriptor = os.open(
        stdout_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    stderr_descriptor = os.open(
        stderr_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    process: subprocess.Popen[bytes] | None = None
    timed_out = False
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=stdout_descriptor,
            stderr=stderr_descriptor,
            start_new_session=True,
            close_fds=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C"},
        )
        if on_started is not None:
            callback = on_started
            callback()
            on_started = None
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            returncode = process.wait(timeout=10)
        os.fsync(stdout_descriptor)
        os.fsync(stderr_descriptor)
        return int(returncode), timed_out
    except OSError as exc:
        raise _fail("container_runtime_launch_failed") from exc
    finally:
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        os.close(stdout_descriptor)
        os.close(stderr_descriptor)


def _read_cidfile(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
    ):
        raise _fail("container_id_unsafe")
    path.chmod(0o600)
    raw = _read_private_file(path, max_bytes=256).decode("ascii", errors="strict").strip()
    if not _CONTAINER_ID.fullmatch(raw):
        raise _fail("container_id_invalid")
    return raw


def run_evo_child_agent_stage(
    admission_path: Path | str,
    stage_name: str,
    logical_command: Sequence[str],
    env: Mapping[str, str],
    timeout: float,
    trust_root: Path | str,
    installation_id: str,
) -> dict[str, Any]:
    """Run one admitted stage, then remove and independently inspect its container."""

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 86400:
        raise _fail("timeout")
    raw_admission = _load_private_json(admission_path)
    identity = raw_admission.get("identity")
    roots = raw_admission.get("roots")
    if not isinstance(identity, dict) or not isinstance(roots, dict):
        raise _fail("admission_shape_or_identity")
    validated = validate_evo_child_container_admission(
        admission_path=admission_path,
        state_root=str(roots.get("state_root") or ""),
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=str(identity.get("job_id") or ""),
        workspace_root=str(roots.get("workspace_root") or ""),
        worktree=str(roots.get("worktree") or ""),
        parent_report_id=str(identity.get("parent_report_id") or ""),
        child_report_id=str(identity.get("child_report_id") or ""),
        expected_host_pin=str(
            raw_admission.get("expected_host_trust_manifest_sha256") or ""
        ),
    )
    admission = validated["admission"]
    root = Path(validated["admission_path"]).parent
    trust = Path(admission["roots"]["trust_root"])
    incident_context = oos_exposure_private_registry_guard(
        trust,
        installation_id=installation_id,
    )
    incident_guard: object | None = None
    incident_guard_active = False
    lock_descriptor: int | None = None
    runner_locked = False
    try:
        incident_guard = incident_context.__enter__()
        incident_guard_active = True
        validate_oos_exposure_private_registry_guard(
            incident_guard,
            trust_root=trust,
            installation_id=installation_id,
        )
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=Path(admission["roots"]["workspace_root"]),
            report_id=admission["identity"]["child_report_id"],
            trust_root=trust,
            installation_id=installation_id,
        )
        if incident_reasons:
            raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
        lock_descriptor = _open_runner_lock(root)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        runner_locked = True
        validated = validate_evo_child_container_admission(
            admission_path=admission_path,
            state_root=admission["roots"]["state_root"],
            trust_root=trust_root,
            installation_id=installation_id,
            job_id=admission["identity"]["job_id"],
            workspace_root=admission["roots"]["workspace_root"],
            worktree=admission["roots"]["worktree"],
            parent_report_id=admission["identity"]["parent_report_id"],
            child_report_id=admission["identity"]["child_report_id"],
            expected_host_pin=admission[
                "expected_host_trust_manifest_sha256"
            ],
        )
        admission = validated["admission"]
        from factor_factory.console.web_factor_proof import (
            web_factor_proof_oos_recovery_state,
        )

        recovery = web_factor_proof_oos_recovery_state(
            Path(admission["roots"]["workspace_root"]),
            admission["identity"]["child_report_id"],
        )
        if recovery.get("recovery_required") is True:
            raise _fail("agent_stage_forbidden_after_oos_publication")
        container_command = _validate_logical_command(
            stage_name=stage_name,
            logical_command=logical_command,
            admission=admission,
        )
        workspace = Path(admission["roots"]["workspace_root"])
        engine = Path(admission["roots"]["engine_root"])
        expected_catalog = admission["catalog_projection"]["snapshot"]["path"]
        expected_calendar = admission["calendar_projection"]["snapshot"]["path"]
        admitted_source = dict(env)
        # These paths are code-owned capabilities derived from the signed
        # admission.  Caller-provided values (including a scrubbed/missing
        # alias) never select a catalog or calendar.
        admitted_source.update(
            {
                "FACTORFORGE_STATE_CATALOG": expected_catalog,
                "FACTORFORGE_DATA_CATALOG": expected_catalog,
                "FACTORFORGE_TRUSTED_TRADE_CAL_CSV": expected_calendar,
            }
        )
        closed_env = _closed_environment(
            admitted_source,
            workspace=workspace,
            engine=engine,
        )
        closed_env["FACTORFORGE_ADMITTED_ENGINE_COMMIT"] = admission[
            "engine_identity"
        ]["commit"]
        closed_env = dict(sorted(closed_env.items()))
        attempt = _next_attempt(root)
        name = _prepare_container_name(admission, attempt)
        runtime = admission["container"]["runtime"]["path"]
        resources = admission["container"]["resources"]
        engine_mount = _mount(engine, readonly=True)
        workspace_mount = _mount(workspace, readonly=False)
        mounts = [
            {"source": str(engine), "target": str(engine), "mode": "ro"},
            {"source": str(workspace), "target": str(workspace), "mode": "rw"},
        ]
        store = load_runtime_trust_store(
            Path(trust_root), installation_id=installation_id
        )
        inflight_path, inflight = _materialize_inflight(
            root=root,
            store=store,
            admission=admission,
            attempt=attempt,
            stage_name=stage_name,
            container_name=name,
            logical_command=list(logical_command),
            container_command=container_command,
            closed_env=closed_env,
            mounts=mounts,
        )
        pre_inspect = _runtime_completed(runtime, ["inspect", name])
        if _container_not_found(pre_inspect, name):
            pre_tree = {
                "container_present": False,
                "inspect_not_found": True,
                "process_tree_absent": True,
            }
        else:
            pre_tree = _remove_and_confirm_absent(runtime, name)
            if pre_tree.get("process_tree_absent") is not True:
                raise _fail("preexisting_container_process_tree_not_removed")
        workspace_pre = _workspace_tree(workspace)
        cid_path = root / f"container_id__{attempt:06d}.txt"
        stdout_path = root / f"stdout__{attempt:06d}__{stage_name}.log"
        stderr_path = root / f"stderr__{attempt:06d}__{stage_name}.log"
        docker_argv = [
            runtime,
            "run",
            "--name",
            name,
            "--cidfile",
            str(cid_path),
            "--label",
            "factorforge.console.managed=true",
            "--label",
            f"factorforge.console.installation={installation_id}",
            "--label",
            f"factorforge.console.evo-child-job={admission['identity']['job_id']}",
            "--network",
            "none",
            "--pid=",
            "--ipc",
            "private",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit",
            str(resources["pids"]),
            "--memory",
            resources["memory"],
            "--cpus",
            resources["cpus"],
            "--tmpfs",
            f"/tmp:{resources['tmpfs']}",
            "--user",
            f"{os.geteuid()}:{os.getegid()}",
            "--workdir",
            str(engine),
            "--mount",
            engine_mount,
            "--mount",
            workspace_mount,
        ]
        for key, value in closed_env.items():
            docker_argv.extend(["--env", f"{key}={value}"])
        docker_argv.extend(
            [admission["container"]["image_digest"], *container_command]
        )
        started_at = _utc_now()
        returncode: int | None = None
        timed_out = False
        launch_error: str | None = None

        def release_launch_incident_guard() -> None:
            nonlocal incident_guard_active
            if not incident_guard_active:
                raise _fail("launch_incident_guard_already_released")
            incident_context.__exit__(None, None, None)
            incident_guard_active = False

        try:
            returncode, timed_out = _run_attached(
                docker_argv,
                timeout=float(timeout),
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                on_started=release_launch_incident_guard,
            )
        except EvoChildContainerError as exc:
            launch_error = exc.reasons[0] if exc.reasons else _token("launch_failed")
            returncode = 127
        post_tree = _remove_and_confirm_absent(runtime, name)
        finished_at = _utc_now()
        if post_tree.get("process_tree_absent") is not True:
            raise _fail("container_process_tree_not_absent")
        container_id = _read_cidfile(cid_path)
        workspace_post = _workspace_tree(workspace)
        for bound_stage, relative in _STAGE_SCRIPTS.items():
            actual_script = _stable_regular_file(
                engine / relative, label=f"stage_script:{bound_stage}"
            )
            actual_script["relative_path"] = relative
            if actual_script != admission["stages"][bound_stage]:
                raise _fail(f"stage_hash_changed:{bound_stage}")
        actual_runtime = _stable_regular_file(
            runtime, label="container_runtime", executable=True
        )
        if actual_runtime != admission["container"]["runtime"]:
            raise _fail("runtime_hash_changed")
        actual_catalog_projection = _validate_catalog_projection_binding(
            engine=engine,
            workspace=workspace,
            snapshot_path=admission["catalog_projection"]["snapshot"]["path"],
            projection_path=admission["catalog_projection"]["projection"]["path"],
            job_id=admission["identity"]["job_id"],
            parent_report_id=admission["identity"]["parent_report_id"],
            child_report_id=admission["identity"]["child_report_id"],
        )
        if actual_catalog_projection != admission["catalog_projection"]:
            raise _fail("catalog_projection_changed_during_stage")
        actual_calendar = validate_materialized_evo_child_calendar_projection(
            engine_root=engine,
            workspace_root=workspace,
            projection_path=admission["calendar_projection"]["projection"]["path"],
            job_id=admission["identity"]["job_id"],
            parent_report_id=admission["identity"]["parent_report_id"],
            child_report_id=admission["identity"]["child_report_id"],
        )
        if (
            actual_calendar["projection_sha256"]
            != admission["calendar_projection"]["projection"]["sha256"]
            or actual_calendar["snapshot_sha256"]
            != admission["calendar_projection"]["snapshot"]["sha256"]
        ):
            raise _fail("calendar_projection_changed_during_stage")
        stdout_ref = _log_ref(stdout_path)
        stderr_ref = _log_ref(stderr_path)

        # Popen establishment is the launch linearization point.  The incident
        # lock is deliberately not held while the untrusted container runs.
        # Once its process tree is absent, drop the runner lock before taking
        # the incident lock again so every authority phase has the single lock
        # order: incident registry -> runner.
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        runner_locked = False
        if not incident_guard_active:
            incident_context = oos_exposure_private_registry_guard(
                trust,
                installation_id=installation_id,
            )
            incident_guard = incident_context.__enter__()
            incident_guard_active = True
        validate_oos_exposure_private_registry_guard(
            incident_guard,
            trust_root=trust,
            installation_id=installation_id,
        )
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        runner_locked = True
        validate_oos_exposure_private_registry_guard(
            incident_guard,
            trust_root=trust,
            installation_id=installation_id,
        )
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=workspace,
            report_id=admission["identity"]["child_report_id"],
            trust_root=trust,
            installation_id=installation_id,
        )
        if incident_reasons:
            raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
        final_validated = validate_evo_child_container_admission(
            admission_path=admission_path,
            state_root=admission["roots"]["state_root"],
            trust_root=trust,
            installation_id=installation_id,
            job_id=admission["identity"]["job_id"],
            workspace_root=admission["roots"]["workspace_root"],
            worktree=admission["roots"]["worktree"],
            parent_report_id=admission["identity"]["parent_report_id"],
            child_report_id=admission["identity"]["child_report_id"],
            expected_host_pin=admission[
                "expected_host_trust_manifest_sha256"
            ],
        )
        admission = final_validated["admission"]
        final_recovery = web_factor_proof_oos_recovery_state(
            workspace,
            admission["identity"]["child_report_id"],
        )
        if final_recovery.get("recovery_required") is True:
            raise _fail("agent_stage_forbidden_after_oos_publication")
        artifacts = _attempt_artifacts(root)
        if (
            artifacts["inflight"].get(attempt) != (stage_name, inflight_path)
            or artifacts["termination"].get(attempt) is not None
            or artifacts["reconciliation"].get(attempt) is not None
        ):
            raise _fail("current_attempt_binding_changed")
        latest_attempt = max(
            (known for values in artifacts.values() for known in values),
            default=0,
        )
        if latest_attempt != attempt:
            raise _fail("current_attempt_superseded")
        authority_admission = dict(admission)
        authority_admission["_file_sha256"] = _sha256_bytes(
            _read_private_file(admission_path)
        )
        inflight_reasons = _validate_inflight_receipt(
            inflight=_load_private_json(inflight_path),
            admission=authority_admission,
            store=store,
            attempt=attempt,
            stage_name=stage_name,
        )
        if inflight_reasons:
            raise EvoChildContainerError(inflight_reasons)
        final_inspect = _runtime_completed(runtime, ["inspect", name])
        if not _container_not_found(final_inspect, name):
            raise _fail("container_process_tree_reappeared")

        logical = list(logical_command)
        core = {
            "receipt_type": CONTAINER_TERMINATION_TYPE,
            "termination_version": CONTAINER_TERMINATION_VERSION,
            "status": CONTAINER_TERMINATED,
            "identity": dict(admission["identity"]),
            "stage_name": stage_name,
            "attempt": attempt,
            "admission_ref": {
                "receipt_id": admission["receipt_id"],
                "sha256": _sha256_bytes(_read_private_file(admission_path)),
            },
            "inflight_ref": {
                "receipt_id": inflight["receipt_id"],
                "sha256": _sha256_bytes(_read_private_file(inflight_path)),
            },
            "container": {
                "runtime": dict(admission["container"]["runtime"]),
                "image_digest": admission["container"]["image_digest"],
                "container_name": name,
                "container_id": container_id,
                "created": container_id is not None,
                "network": "none",
                "pid_namespace": "private",
                "mounts": mounts,
                "resources": dict(resources),
            },
            "command": {
                "logical_argv": logical,
                "logical_sha256": stable_json_hash(logical),
                "container_argv": container_command,
                "container_sha256": stable_json_hash(container_command),
                "script_sha256": admission["stages"][stage_name]["sha256"],
                "environment_keys": list(closed_env),
                "environment_sha256": stable_json_hash(closed_env),
            },
            "execution": {
                "started_at_utc": started_at,
                "finished_at_utc": finished_at,
                "returncode": returncode,
                "timed_out": timed_out,
                "launch_error": launch_error,
                "stage_status": (
                    "TIMED_OUT"
                    if timed_out
                    else "SUCCEEDED"
                    if returncode == 0
                    else "FAILED"
                ),
                "factor_verdict": "NOT_ISSUED",
                "stdout": {key: value for key, value in stdout_ref.items() if key != "tail"},
                "stderr": {key: value for key, value in stderr_ref.items() if key != "tail"},
            },
            "process_tree": {
                "pre_run": pre_tree,
                "post_run": post_tree,
                "process_tree_absent": True,
            },
            "workspace_tree": {"pre_run": workspace_pre, "post_run": workspace_post},
        }
        core["content_sha256"] = stable_json_hash(core)
        receipt = store.sign("host_admission", core)
        termination_path = root / f"termination__{attempt:06d}__{stage_name}.json"
        _write_once(termination_path, _canonical_bytes(receipt))
        validated_termination = validate_latest_evo_child_agent_termination(
            state_root=admission["roots"]["state_root"],
            trust_root=trust_root,
            installation_id=installation_id,
            job_id=admission["identity"]["job_id"],
            workspace_root=admission["roots"]["workspace_root"],
            worktree=admission["roots"]["worktree"],
            parent_report_id=admission["identity"]["parent_report_id"],
            child_report_id=admission["identity"]["child_report_id"],
            expected_host_pin=admission["expected_host_trust_manifest_sha256"],
            required_stage=stage_name,
        )
        command_result = {
            "name": stage_name,
            "command": logical,
            "cwd": str(engine),
            "started_at_utc": started_at,
            "finished_at_utc": finished_at,
            "returncode": returncode,
            "stdout_tail": stdout_ref["tail"],
            "stderr_tail": stderr_ref["tail"],
            "status": "PASS" if returncode == 0 and not timed_out else "FAIL",
        }
        return {
            "verdict": "PASS",
            "status": CONTAINER_TERMINATED,
            "factor_verdict": "NOT_ISSUED",
            "stage_name": stage_name,
            "stage_status": receipt["execution"]["stage_status"],
            "returncode": returncode,
            "timed_out": timed_out,
            "process_tree_absent": True,
            "termination_receipt_path": str(termination_path),
            "termination_receipt_sha256": _sha256_bytes(
                _read_private_file(termination_path)
            ),
            "termination_receipt": validated_termination["termination_receipt"],
            "stdout_tail": stdout_ref["tail"],
            "stderr_tail": stderr_ref["tail"],
            "command_result": command_result,
        }
    finally:
        if lock_descriptor is not None:
            try:
                if runner_locked:
                    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)
        if incident_guard_active:
            incident_context.__exit__(None, None, None)


def _validate_termination_receipt(
    *, receipt: Mapping[str, Any], admission: Mapping[str, Any], store: Any
) -> list[str]:
    reasons = [
        _token(f"termination_signature:{reason}")
        for reason in store.verify(receipt, expected_issuer="host_admission")
    ]
    stage = receipt.get("stage_name")
    container = receipt.get("container")
    command = receipt.get("command")
    execution = receipt.get("execution")
    process_tree = receipt.get("process_tree")
    workspace_tree = receipt.get("workspace_tree")
    attempt = receipt.get("attempt")
    stage_valid = isinstance(stage, str) and stage in _STAGE_SCRIPTS
    expected_mounts = [
        {
            "source": admission["roots"]["engine_root"],
            "target": admission["roots"]["engine_root"],
            "mode": "ro",
        },
        {
            "source": admission["roots"]["workspace_root"],
            "target": admission["roots"]["workspace_root"],
            "mode": "rw",
        },
    ]
    if (
        receipt.get("receipt_type") != CONTAINER_TERMINATION_TYPE
        or receipt.get("termination_version") != CONTAINER_TERMINATION_VERSION
        or receipt.get("status") != CONTAINER_TERMINATED
        or receipt.get("identity") != admission["identity"]
        or not stage_valid
        or isinstance(receipt.get("attempt"), bool)
        or not isinstance(receipt.get("attempt"), int)
        or receipt.get("attempt", 0) < 1
        or receipt.get("admission_ref")
        != {
            "receipt_id": admission["receipt_id"],
            "sha256": admission.get("_file_sha256"),
        }
        or not isinstance(receipt.get("inflight_ref"), dict)
        or receipt.get("content_sha256") != _content_hash(receipt)
        or not isinstance(container, dict)
        or container.get("runtime") != admission["container"]["runtime"]
        or container.get("image_digest") != admission["container"]["image_digest"]
        or container.get("network") != "none"
        or container.get("pid_namespace") != "private"
        or container.get("mounts") != expected_mounts
        or container.get("resources") != admission["container"]["resources"]
        or not isinstance(command, dict)
        or command.get("logical_sha256") != stable_json_hash(command.get("logical_argv"))
        or command.get("container_sha256") != stable_json_hash(command.get("container_argv"))
        or command.get("script_sha256")
        != (admission["stages"].get(stage, {}).get("sha256") if stage_valid else None)
        or not isinstance(execution, dict)
        or execution.get("factor_verdict") != "NOT_ISSUED"
        or execution.get("stage_status") not in {"SUCCEEDED", "FAILED", "TIMED_OUT"}
        or not isinstance(process_tree, dict)
        or process_tree.get("process_tree_absent") is not True
        or not isinstance(process_tree.get("pre_run"), dict)
        or process_tree["pre_run"].get("process_tree_absent") is not True
        or not isinstance(process_tree.get("post_run"), dict)
        or process_tree["post_run"].get("process_tree_absent") is not True
        or process_tree["post_run"].get("inspect_not_found") is not True
        or not isinstance(workspace_tree, dict)
        or set(workspace_tree) != {"pre_run", "post_run"}
    ):
        reasons.append(_token("termination_shape_or_binding"))
    if isinstance(attempt, int) and not isinstance(attempt, bool) and stage_valid:
        root = (
            Path(admission["roots"]["state_root"])
            / "jobs"
            / admission["identity"]["job_id"]
            / "evo-child-container"
            / admission["identity"]["child_report_id"]
        )
        inflight_path = root / f"inflight__{attempt:06d}__{stage}.json"
        try:
            inflight = _load_private_json(inflight_path)
            reasons.extend(
                _validate_inflight_receipt(
                    inflight=inflight,
                    admission=admission,
                    store=store,
                    attempt=attempt,
                    stage_name=stage,
                )
            )
            if receipt.get("inflight_ref") != {
                "receipt_id": inflight.get("receipt_id"),
                "sha256": _sha256_bytes(_read_private_file(inflight_path)),
            }:
                reasons.append(_token("termination_inflight_ref"))
            if isinstance(command, dict):
                inflight_command = inflight.get("command")
                if not isinstance(inflight_command, dict) or any(
                    command.get(termination_key) != inflight_command.get(inflight_key)
                    for termination_key, inflight_key in (
                        ("logical_sha256", "logical_sha256"),
                        ("container_sha256", "container_sha256"),
                        ("environment_sha256", "environment_sha256"),
                        ("script_sha256", "script_sha256"),
                    )
                ):
                    reasons.append(_token("termination_inflight_command_binding"))
        except EvoChildContainerError as exc:
            reasons.extend(exc.reasons)
    if isinstance(command, dict) and stage_valid:
        try:
            expected_container = _validate_logical_command(
                stage_name=stage,
                logical_command=command.get("logical_argv") or [],
                admission=admission,
            )
            if command.get("container_argv") != expected_container:
                reasons.append(_token("termination_command_replay"))
        except EvoChildContainerError as exc:
            reasons.extend(exc.reasons)
    if isinstance(container, dict):
        created = container.get("created")
        container_id = container.get("container_id")
        if created is True and (
            not isinstance(container_id, str) or not _CONTAINER_ID.fullmatch(container_id)
        ):
            reasons.append(_token("termination_container_id"))
        if created is False and container_id is not None:
            reasons.append(_token("termination_container_id"))
    return list(dict.fromkeys(reasons))


def _validate_reconciliation_receipt(
    *,
    receipt: Mapping[str, Any],
    inflight: Mapping[str, Any],
    admission: Mapping[str, Any],
    store: Any,
) -> list[str]:
    reasons = [
        _token(f"reconciliation_signature:{reason}")
        for reason in store.verify(receipt, expected_issuer="host_admission")
    ]
    attempt = inflight.get("attempt")
    stage = inflight.get("stage_name")
    process_tree = receipt.get("process_tree")
    inflight_path = (
        Path(admission["roots"]["state_root"])
        / "jobs"
        / admission["identity"]["job_id"]
        / "evo-child-container"
        / admission["identity"]["child_report_id"]
        / f"inflight__{attempt:06d}__{stage}.json"
    )
    try:
        expected_inflight_sha256 = _sha256_bytes(_read_private_file(inflight_path))
    except EvoChildContainerError as exc:
        reasons.extend(exc.reasons)
        expected_inflight_sha256 = None
    if (
        receipt.get("receipt_type") != CONTAINER_RECONCILIATION_TYPE
        or receipt.get("reconciliation_version")
        != CONTAINER_RECONCILIATION_VERSION
        or receipt.get("status") != CONTAINER_RECONCILED
        or receipt.get("identity") != admission["identity"]
        or receipt.get("attempt") != attempt
        or receipt.get("stage_name") != stage
        or receipt.get("admission_ref") != inflight.get("admission_ref")
        or receipt.get("inflight_ref")
        != {
            "receipt_id": inflight.get("receipt_id"),
            "sha256": expected_inflight_sha256,
        }
        or receipt.get("factor_verdict") != "NOT_ISSUED"
        or receipt.get("retry_authorized") is not True
        or receipt.get("content_sha256") != _content_hash(receipt)
        or not isinstance(process_tree, dict)
        or process_tree.get("process_tree_absent") is not True
        or process_tree.get("post_reconcile", {}).get("inspect_not_found") is not True
        or process_tree.get("post_reconcile", {}).get("process_tree_absent") is not True
    ):
        reasons.append(_token("reconciliation_shape_or_binding"))
    return list(dict.fromkeys(reasons))


def reconcile_evo_child_agent_stage_containers(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_pin: str,
) -> dict[str, Any]:
    """Reconcile launch journals left by an outer Host timeout or process crash.

    A reconciliation only proves that the deterministic container process tree
    is absent and authorizes a retry.  It is never a successful stage receipt
    and cannot satisfy an OOS/finalization termination gate.
    """

    _validate_ids(installation_id, job_id, parent_report_id, child_report_id)
    state = _state_root_directory(_canonical_directory(state_root, label="state_root"))
    trust = _canonical_directory(trust_root, label="trust_root")
    root = _admission_root(state, job_id, child_report_id)
    admission_path = root / "admission.json"
    with oos_exposure_private_registry_guard(
        trust,
        installation_id=installation_id,
    ) as incident_guard:
        validate_oos_exposure_private_registry_guard(
            incident_guard,
            trust_root=trust,
            installation_id=installation_id,
        )
        lock_descriptor = _open_runner_lock(root)
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            validate_oos_exposure_private_registry_guard(
                incident_guard,
                trust_root=trust,
                installation_id=installation_id,
            )
            # Reconciliation may use an otherwise-valid admission only to
            # remove a deterministic process tree after an incident.  Current
            # authority is checked again after cleanup and before any retry
            # receipt can be signed.
            validated = _validate_evo_child_container_admission_impl(
                admission_path=admission_path,
                state_root=state,
                trust_root=trust,
                installation_id=installation_id,
                job_id=job_id,
                workspace_root=workspace_root,
                worktree=worktree,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_pin=expected_host_pin,
                allow_oos_incident_for_cleanup=True,
                incident_guard=incident_guard,
            )
            admission = dict(validated["admission"])
            admission["_file_sha256"] = _sha256_bytes(
                _read_private_file(admission_path)
            )
            store = _validate_host_trust(
                workspace=Path(admission["roots"]["workspace_root"]),
                trust=trust,
                installation_id=installation_id,
                parent_report_id=parent_report_id,
                expected_pin=expected_host_pin,
            )
            artifacts = _attempt_artifacts(root)
            reconciled: list[dict[str, Any]] = []
            inspected_attempts: list[int] = []
            incident_reasons = formal_oos_incident_reasons(
                workspace_root=Path(admission["roots"]["workspace_root"]),
                report_id=child_report_id,
                trust_root=trust,
                installation_id=installation_id,
            )
            for attempt, (stage, inflight_path) in sorted(
                artifacts["inflight"].items()
            ):
                inflight = _load_private_json(inflight_path)
                reasons = _validate_inflight_receipt(
                    inflight=inflight,
                    admission=admission,
                    store=store,
                    attempt=attempt,
                    stage_name=stage,
                )
                if reasons:
                    raise EvoChildContainerError(reasons)
                name = inflight["container"]["container_name"]
                initial = _runtime_completed(
                    admission["container"]["runtime"]["path"],
                    ["inspect", name],
                )
                pre = {
                    "container_present": not _container_not_found(initial, name),
                    "inspect_not_found": _container_not_found(initial, name),
                }
                post = _remove_and_confirm_absent(
                    admission["container"]["runtime"]["path"], name
                )
                if post.get("process_tree_absent") is not True:
                    raise _fail("reconciliation_process_tree_not_absent")
                inspected_attempts.append(attempt)
                existing_termination = artifacts["termination"].get(attempt)
                existing_reconciliation = artifacts["reconciliation"].get(attempt)
                if existing_termination is not None:
                    if existing_termination[0] != stage:
                        raise _fail("inflight_termination_stage_mismatch")
                    continue
                if existing_reconciliation is not None:
                    if existing_reconciliation[0] != stage:
                        raise _fail("inflight_reconciliation_stage_mismatch")
                    prior = _load_private_json(existing_reconciliation[1])
                    prior_reasons = _validate_reconciliation_receipt(
                        receipt=prior,
                        inflight=inflight,
                        admission=admission,
                        store=store,
                    )
                    if prior_reasons:
                        raise EvoChildContainerError(prior_reasons)
                    continue
                if incident_reasons:
                    # Cleanup is non-authoritative and remains allowed, but an
                    # incident that linearized before reconciliation forever
                    # forbids signing a fresh retry capability.
                    continue
                core = {
                    "receipt_type": CONTAINER_RECONCILIATION_TYPE,
                    "reconciliation_version": CONTAINER_RECONCILIATION_VERSION,
                    "status": CONTAINER_RECONCILED,
                    "identity": dict(admission["identity"]),
                    "attempt": attempt,
                    "stage_name": stage,
                    "admission_ref": dict(inflight["admission_ref"]),
                    "inflight_ref": {
                        "receipt_id": inflight["receipt_id"],
                        "sha256": _sha256_bytes(_read_private_file(inflight_path)),
                    },
                    "container": {
                        "runtime": dict(admission["container"]["runtime"]),
                        "image_digest": admission["container"]["image_digest"],
                        "container_name": name,
                    },
                    "process_tree": {
                        "pre_reconcile": pre,
                        "post_reconcile": post,
                        "process_tree_absent": True,
                    },
                    "retry_authorized": True,
                    "factor_verdict": "NOT_ISSUED",
                }
                core["content_sha256"] = stable_json_hash(core)
                receipt = store.sign("host_admission", core)
                receipt_path = (
                    root / f"reconciliation__{attempt:06d}__{stage}.json"
                )
                _write_once(receipt_path, _canonical_bytes(receipt))
                reconciled.append(
                    {
                        "attempt": attempt,
                        "stage_name": stage,
                        "receipt_path": str(receipt_path),
                        "receipt_sha256": _sha256_bytes(
                            _read_private_file(receipt_path)
                        ),
                        "receipt_id": receipt["receipt_id"],
                    }
                )
            if incident_reasons:
                raise _fail(
                    "oos_exposure_incident:" + ",".join(incident_reasons)
                )
            return {
                "verdict": "PASS",
                "status": CONTAINER_RECONCILED,
                "factor_verdict": "NOT_ISSUED",
                "process_tree_absent": True,
                "retry_authorized": True,
                "inspected_attempts": inspected_attempts,
                "reconciled": reconciled,
            }
        finally:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)


def validate_latest_evo_child_agent_termination(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_pin: str,
    required_stage: str | None = None,
) -> dict[str, Any]:
    """Validate the latest signed receipt and re-inspect that container as absent."""

    if required_stage is not None and required_stage not in _STAGE_SCRIPTS:
        raise _fail("required_stage")
    state = _state_root_directory(_canonical_directory(state_root, label="state_root"))
    root = _admission_root(state, job_id, child_report_id)
    admission_path = root / "admission.json"
    validated = validate_evo_child_container_admission(
        admission_path=admission_path,
        state_root=state,
        trust_root=trust_root,
        installation_id=installation_id,
        job_id=job_id,
        workspace_root=workspace_root,
        worktree=worktree,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_pin=expected_host_pin,
    )
    admission = dict(validated["admission"])
    admission["_file_sha256"] = _sha256_bytes(_read_private_file(admission_path))
    store = _validate_host_trust(
        workspace=Path(admission["roots"]["workspace_root"]),
        trust=Path(trust_root),
        installation_id=installation_id,
        parent_report_id=parent_report_id,
        expected_pin=expected_host_pin,
    )
    artifacts = _attempt_artifacts(root)
    if not artifacts["termination"]:
        raise _fail("termination_receipt_missing")
    reasons: list[str] = []
    loaded_inflight: dict[int, dict[str, Any]] = {}
    for inflight_attempt, (inflight_stage, inflight_path) in artifacts[
        "inflight"
    ].items():
        inflight = _load_private_json(inflight_path)
        loaded_inflight[inflight_attempt] = inflight
        reasons.extend(
            _validate_inflight_receipt(
                inflight=inflight,
                admission=admission,
                store=store,
                attempt=inflight_attempt,
                stage_name=inflight_stage,
            )
        )
        termination_entry = artifacts["termination"].get(inflight_attempt)
        reconciliation_entry = artifacts["reconciliation"].get(inflight_attempt)
        if termination_entry is None and reconciliation_entry is None:
            reasons.append(_token("unreconciled_inflight"))
        if termination_entry is not None and reconciliation_entry is not None:
            reasons.append(_token("ambiguous_inflight_closure"))
        if termination_entry is not None and termination_entry[0] != inflight_stage:
            reasons.append(_token("inflight_termination_stage_mismatch"))
        if reconciliation_entry is not None and reconciliation_entry[0] != inflight_stage:
            reasons.append(_token("inflight_reconciliation_stage_mismatch"))
    for termination_attempt, (termination_stage, termination_path) in artifacts[
        "termination"
    ].items():
        if termination_attempt not in loaded_inflight:
            reasons.append(_token("termination_without_inflight"))
            continue
        termination = _load_private_json(termination_path)
        if (
            termination.get("attempt") != termination_attempt
            or termination.get("stage_name") != termination_stage
        ):
            reasons.append(_token("termination_filename_binding"))
        reasons.extend(
            _validate_termination_receipt(
                receipt=termination, admission=admission, store=store
            )
        )
    for reconciliation_attempt, (reconciliation_stage, reconciliation_path) in artifacts[
        "reconciliation"
    ].items():
        inflight = loaded_inflight.get(reconciliation_attempt)
        if inflight is None:
            reasons.append(_token("reconciliation_without_inflight"))
            continue
        reconciliation = _load_private_json(reconciliation_path)
        if (
            reconciliation.get("attempt") != reconciliation_attempt
            or reconciliation.get("stage_name") != reconciliation_stage
        ):
            reasons.append(_token("reconciliation_filename_binding"))
        reasons.extend(
            _validate_reconciliation_receipt(
                receipt=reconciliation,
                inflight=inflight,
                admission=admission,
                store=store,
            )
        )
    runtime = admission["container"]["runtime"]["path"]
    for known_attempt in sorted(artifacts["inflight"]):
        known_name = _prepare_container_name(admission, known_attempt)
        inspect = _runtime_completed(runtime, ["inspect", known_name])
        if not _container_not_found(inspect, known_name):
            reasons.append(_token("termination_reinspection_not_absent"))
    managed = _runtime_completed(
        runtime,
        [
            "ps",
            "-aq",
            "--filter",
            "label=factorforge.console.managed=true",
            "--filter",
            (
                "label=factorforge.console.evo-child-job="
                + admission["identity"]["job_id"]
            ),
        ],
    )
    managed_ids = [item for item in (managed.stdout or "").split() if item]
    if (
        managed.returncode != 0
        or any(not _CONTAINER_ID.fullmatch(item) for item in managed_ids)
        or managed_ids
    ):
        reasons.append(_token("managed_child_container_still_present"))
    latest_attempt = max(
        attempt for values in artifacts.values() for attempt in values
    )
    latest_entry = artifacts["termination"].get(latest_attempt)
    if latest_entry is None:
        reasons.append(_token("latest_attempt_is_not_termination"))
        path = root / "missing-latest-termination"
        receipt: dict[str, Any] = {}
        attempt = latest_attempt
    else:
        latest_stage, path = latest_entry
        attempt = latest_attempt
        receipt = _load_private_json(path)
        if required_stage is not None and latest_stage != required_stage:
            reasons.append(_token("latest_termination_required_stage_mismatch"))
    name = (receipt.get("container") or {}).get("container_name")
    if not isinstance(name, str) or name != _prepare_container_name(admission, attempt):
        reasons.append(_token("termination_container_name"))
    else:
        inspect = _runtime_completed(runtime, ["inspect", name])
        if not _container_not_found(inspect, name):
            reasons.append(_token("termination_reinspection_not_absent"))
    if reasons:
        raise EvoChildContainerError(reasons)
    execution = receipt["execution"]
    return {
        "verdict": "PASS",
        "status": CONTAINER_TERMINATED,
        "factor_verdict": "NOT_ISSUED",
        "stage_name": receipt["stage_name"],
        "stage_status": execution["stage_status"],
        "stage_succeeded": execution["stage_status"] == "SUCCEEDED",
        "process_tree_absent": True,
        "termination_receipt_path": path,
        "termination_receipt_sha256": _sha256_bytes(
            _read_private_file(path)
        ),
        "termination_receipt_id": receipt["receipt_id"],
        "termination_receipt": receipt,
    }


@contextmanager
def guard_evo_child_oos_finalization(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_pin: str,
    _incident_guard: object,
):
    """Hold the child runner lock across termination replay and OOS publish.

    The same lock serializes every admitted Agent stage.  Keeping it held
    until the Host finalizer has either failed or durably written its complete
    release prevents a new Agent process from starting in the validation to
    publication gap.
    """

    _validate_ids(installation_id, job_id, parent_report_id, child_report_id)
    trust = _canonical_directory(trust_root, label="trust_root")
    validate_oos_exposure_private_registry_guard(
        _incident_guard,
        trust_root=trust,
        installation_id=installation_id,
    )
    incident_reasons = formal_oos_incident_reasons(
        workspace_root=_canonical_directory(
            workspace_root,
            label="workspace_root",
        ),
        report_id=child_report_id,
        trust_root=trust,
        installation_id=installation_id,
    )
    if incident_reasons:
        raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
    state = _state_root_directory(_canonical_directory(state_root, label="state_root"))
    root = _admission_root(state, job_id, child_report_id)
    descriptor = _open_runner_lock(root)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        validate_oos_exposure_private_registry_guard(
            _incident_guard,
            trust_root=trust,
            installation_id=installation_id,
        )
        incident_reasons = formal_oos_incident_reasons(
            workspace_root=_canonical_directory(
                workspace_root,
                label="workspace_root",
            ),
            report_id=child_report_id,
            trust_root=trust,
            installation_id=installation_id,
        )
        if incident_reasons:
            raise _fail("oos_exposure_incident:" + ",".join(incident_reasons))
        validated = validate_latest_evo_child_agent_termination(
            state_root=state,
            trust_root=trust,
            installation_id=installation_id,
            job_id=job_id,
            workspace_root=workspace_root,
            worktree=worktree,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_pin=expected_host_pin,
            required_stage="validate_step4",
        )
        if (
            validated.get("stage_name") != "validate_step4"
            or validated.get("stage_succeeded") is not True
            or validated.get("process_tree_absent") is not True
        ):
            raise _fail("oos_finalizer_termination_gate")
        yield validated
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


__all__ = [
    "BLOCK_EVO_CHILD_CONTAINER",
    "CONTAINER_ADMISSION_VERSION",
    "CONTAINER_INFLIGHT_VERSION",
    "CONTAINER_RECONCILIATION_VERSION",
    "CONTAINER_TERMINATION_VERSION",
    "EvoChildContainerError",
    "guard_evo_child_oos_finalization",
    "materialize_evo_child_container_admission",
    "reconcile_evo_child_agent_stage_containers",
    "resolve_evo_child_container_image_digest",
    "run_evo_child_agent_stage",
    "validate_evo_child_container_admission",
    "validate_latest_evo_child_agent_termination",
]
