from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from factor_factory.research_org.contracts import (
    SAFE_ID_RE,
    SHA256_RE,
    ResearchOrganizationError,
    normalize_workspace_relative_path,
    read_workspace_json,
    sha256_file,
    stable_json_hash,
    strict_json_loads,
    validate_content_hash,
    with_content_hash,
    write_workspace_json_once,
)


STORE_CONTRACT_VERSION = "factorforge_researcher_memory_store_v1"
ROLE_SNAPSHOT_CONTRACT_VERSION = "factorforge_researcher_memory_snapshot_v1"
SNAPSHOT_BINDING_CONTRACT_VERSION = "factorforge_researcher_memory_binding_v1"
CANDIDATE_CONTRACT_VERSION = "factorforge_researcher_memory_candidate_v1"
REVIEW_CONTRACT_VERSION = "factorforge_researcher_memory_review_v1"
CANONICAL_RECORD_CONTRACT_VERSION = "factorforge_researcher_memory_record_v1"
OUTCOME_EVENT_CONTRACT_VERSION = "factorforge_researcher_outcome_event_v1"
STORE_TRANSACTION_CONTRACT_VERSION = "factorforge_researcher_memory_transaction_v1"
EVO_V2_MEMORY_ADMISSION_CONTRACT_VERSION = (
    "factorforge_researcher_memory_evo_v2_admission_v1"
)
EVO_V2_MEMORY_ADMISSION_RECEIPT_TYPE = (
    "RESEARCHER_MEMORY_EVO_V2_PAYLOAD_ADMITTED"
)
EVO_V2_TRANSFER_USE_CHANGE_RECEIPT_TYPE = (
    "factorforge_researcher_memory_evo_v2_transfer_use_change_receipt_v1"
)

BLOCK_MEMORY_ROOT_INVALID = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_ROOT_INVALID"
BLOCK_MEMORY_STORE_INVALID = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_STORE_INVALID"
BLOCK_MEMORY_SNAPSHOT_INVALID = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_SNAPSHOT_INVALID"
BLOCK_MEMORY_CANDIDATE_INVALID = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_CANDIDATE_INVALID"
BLOCK_MEMORY_REVIEW_INVALID = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_REVIEW_INVALID"
BLOCK_MEMORY_PROMOTION_FORBIDDEN = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_PROMOTION_FORBIDDEN"
BLOCK_MEMORY_WRITE_CONFLICT = "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_WRITE_CONFLICT"
BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID = (
    "BLOCK_FACTORFORGE_RESEARCHER_MEMORY_EVO_V2_ADMISSION_INVALID"
)

MEMORY_KINDS = {
    "economic_mechanism",
    "mathematical_measurement",
    "implementation_pattern",
    "falsification_pattern",
    "failure_mode",
    "research_workflow",
}
REVIEW_DECISIONS = {"APPROVE_CANONICAL", "REJECT"}
FACTOR_VERDICTS = {"ACCEPT", "REJECT", "ITERATE", "BLOCK", "UNKNOWN"}
MAX_CANONICAL_RECORDS_PER_SNAPSHOT = 32
MAX_LEARNING_CANDIDATES_PER_RESULT = 3
MAX_MEMORY_FILE_BYTES = 4 * 1024 * 1024

_MANIFEST_NAME = "store_manifest.json"
_LOCK_NAME = ".store.lock"
_TEMP_DIR_NAME = "tmp"
_PRIVATE_DIR_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_SAFE_RELATIVE_RE = re.compile(r"[A-Za-z0-9_.@/-]+\Z")
_TEMP_FILE_RE = re.compile(r"write_[0-9]+_[0-9a-f]{32}\.tmp\Z")


def _raise(token: str, *reasons: str) -> None:
    raise ResearchOrganizationError(token, reasons)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or _is_relative_to(left, right) or _is_relative_to(right, left)


def _assert_private_root(
    root: Path,
    *,
    repo_root: Path | None = None,
    workspace: Path | None = None,
    create: bool,
) -> Path:
    requested = Path(os.path.abspath(Path(root).expanduser()))

    def reject_symlink_components(path: Path) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            try:
                component = current.lstat()
            except FileNotFoundError:
                break
            except OSError as exc:
                _raise(BLOCK_MEMORY_ROOT_INVALID, f"root_component_unreadable:{exc}")
            if stat.S_ISLNK(component.st_mode):
                _raise(BLOCK_MEMORY_ROOT_INVALID, f"root_component_symlink:{current}")

    reject_symlink_components(requested)
    resolved = requested.resolve(strict=False)
    for label, forbidden in (("repo_root", repo_root), ("factor_workspace", workspace)):
        if forbidden is None:
            continue
        forbidden_resolved = Path(forbidden).expanduser().resolve(strict=False)
        if _paths_overlap(resolved, forbidden_resolved):
            _raise(BLOCK_MEMORY_ROOT_INVALID, f"memory_root_overlaps_{label}")

    existed = requested.exists()
    if create and not existed:
        try:
            requested.mkdir(parents=True, exist_ok=False, mode=_PRIVATE_DIR_MODE)
            requested.chmod(_PRIVATE_DIR_MODE)
        except OSError as exc:
            _raise(BLOCK_MEMORY_ROOT_INVALID, f"root_create_failed:{exc}")
    reject_symlink_components(requested)
    resolved = requested.resolve(strict=False)
    try:
        metadata = requested.lstat()
    except OSError as exc:
        _raise(BLOCK_MEMORY_ROOT_INVALID, f"root_missing:{exc}")
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIR_MODE
    ):
        _raise(BLOCK_MEMORY_ROOT_INVALID, "root_owner_or_mode")
    return resolved


def _safe_store_relative(relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or not _SAFE_RELATIVE_RE.fullmatch(relative)
    ):
        _raise(BLOCK_MEMORY_STORE_INVALID, f"unsafe_relative_path:{relative!r}")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or any(not part for part in path.parts):
        _raise(BLOCK_MEMORY_STORE_INVALID, f"unsafe_relative_path:{relative!r}")
    return path


def _ensure_private_directory(root: Path, relative: str) -> Path:
    current = root
    for part in _safe_store_relative(relative).parts:
        current = current / part
        created = False
        try:
            current.mkdir(mode=_PRIVATE_DIR_MODE)
            created = True
        except FileExistsError:
            pass
        except OSError as exc:
            _raise(BLOCK_MEMORY_ROOT_INVALID, f"directory_create_failed:{relative}:{exc}")
        try:
            metadata = current.lstat()
        except OSError as exc:
            _raise(BLOCK_MEMORY_ROOT_INVALID, f"directory_unreadable:{relative}:{exc}")
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIR_MODE
        ):
            _raise(BLOCK_MEMORY_ROOT_INVALID, f"unsafe_directory:{relative}")
        if created:
            try:
                current.chmod(_PRIVATE_DIR_MODE)
            except OSError as exc:
                _raise(
                    BLOCK_MEMORY_ROOT_INVALID,
                    f"directory_mode_failed:{relative}:{exc}",
                )
    return current


def _read_store_bytes(root: Path, relative: str) -> bytes:
    rel = _safe_store_relative(relative)
    path = root / rel
    if not _is_relative_to(path.resolve(strict=False), root):
        _raise(BLOCK_MEMORY_STORE_INVALID, f"path_escape:{relative}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _raise(BLOCK_MEMORY_STORE_INVALID, f"unreadable:{relative}:{exc}")
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != _PRIVATE_FILE_MODE
            or not 0 < before.st_size <= MAX_MEMORY_FILE_BYTES
        ):
            _raise(BLOCK_MEMORY_STORE_INVALID, f"unsafe_file:{relative}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            _raise(BLOCK_MEMORY_STORE_INVALID, f"changed_while_reading:{relative}")
        return payload
    finally:
        os.close(descriptor)


def _read_store_json(root: Path, relative: str) -> dict[str, Any]:
    payload = strict_json_loads(_read_store_bytes(root, relative), label=relative)
    if not isinstance(payload, dict):
        _raise(BLOCK_MEMORY_STORE_INVALID, f"object_required:{relative}")
    return payload


def _atomic_store_json(
    root: Path,
    relative: str,
    payload: Mapping[str, Any],
    *,
    replace: bool,
) -> tuple[Path, bool]:
    rel = _safe_store_relative(relative)
    parent_relative = rel.parent.as_posix()
    parent = root if parent_relative == "." else _ensure_private_directory(root, parent_relative)
    destination = root / rel
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"unsafe_destination:{relative}")
        if not replace:
            existing = _read_store_json(root, relative)
            if stable_json_hash(existing) == stable_json_hash(dict(payload)):
                return destination, False
            _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"immutable_conflict:{relative}")
    raw = (
        json.dumps(
            dict(payload),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if len(raw) > MAX_MEMORY_FILE_BYTES:
        _raise(BLOCK_MEMORY_STORE_INVALID, f"file_too_large:{relative}")
    temporary_root = _ensure_private_directory(root, _TEMP_DIR_NAME)
    temporary_name = f"write_{os.getpid()}_{uuid.uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    parent_descriptor = -1
    try:
        parent_descriptor = os.open(
            temporary_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        descriptor = os.open(
            temporary_name,
            flags,
            _PRIVATE_FILE_MODE,
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
        _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"temporary_create_failed:{relative}:{exc}")
    try:
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                _raise(
                    BLOCK_MEMORY_WRITE_CONFLICT,
                    f"temporary_write_failed:{relative}",
                )
            written += count
        os.fsync(descriptor)
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
    finally:
        os.close(descriptor)
        os.close(parent_descriptor)
    temporary = temporary_root / temporary_name
    try:
        if not replace and (destination.exists() or destination.is_symlink()):
            temporary.unlink(missing_ok=True)
            existing = _read_store_json(root, relative)
            if stable_json_hash(existing) == stable_json_hash(dict(payload)):
                return destination, False
            _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"immutable_conflict:{relative}")
        os.replace(temporary, destination)
        destination.chmod(_PRIVATE_FILE_MODE)
        directory_descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        temporary_directory_descriptor = os.open(
            temporary_root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(temporary_directory_descriptor)
        finally:
            os.close(temporary_directory_descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination, True


def _unlink_store_file(root: Path, relative: str) -> None:
    rel = _safe_store_relative(relative)
    parent = root / rel.parent
    parent_descriptor = os.open(
        parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        descriptor = os.open(
            rel.name,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_descriptor,
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
            ):
                _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"unsafe_unlink:{relative}")
        finally:
            os.close(descriptor)
        os.unlink(rel.name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    except FileNotFoundError:
        return
    finally:
        os.close(parent_descriptor)


@contextmanager
def _store_lock(root: Path, *, create: bool = True) -> Iterator[None]:
    flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if create:
        flags |= os.O_CREAT
    try:
        descriptor = os.open(root / _LOCK_NAME, flags, _PRIVATE_FILE_MODE)
    except OSError as exc:
        _raise(BLOCK_MEMORY_ROOT_INVALID, f"lock_open_failed:{exc}")
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
        ):
            _raise(BLOCK_MEMORY_ROOT_INVALID, "unsafe_store_lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _store_id(installation_id: str) -> tuple[str, str]:
    if not isinstance(installation_id, str) or not SAFE_ID_RE.fullmatch(installation_id):
        _raise(BLOCK_MEMORY_STORE_INVALID, "installation_id")
    digest = hashlib.sha256(installation_id.encode("utf-8")).hexdigest()
    return f"researcher_memory_{digest[:20]}", digest


def _new_manifest(installation_id: str) -> dict[str, Any]:
    store_id, installation_hash = _store_id(installation_id)
    return with_content_hash(
        {
            "contract_version": STORE_CONTRACT_VERSION,
            "store_id": store_id,
            "installation_id_sha256": installation_hash,
            "generation": 0,
            "canonical_records": [],
            "reviews": [],
            "outcome_events": [],
        },
        hash_field="manifest_sha256",
    )


def _manifest_reasons(manifest: Any, *, installation_id: str) -> list[str]:
    if not isinstance(manifest, dict):
        return ["manifest_object"]
    expected_fields = {
        "contract_version",
        "store_id",
        "installation_id_sha256",
        "generation",
        "canonical_records",
        "reviews",
        "outcome_events",
        "manifest_sha256",
    }
    reasons: list[str] = []
    store_id, installation_hash = _store_id(installation_id)
    if set(manifest) != expected_fields:
        reasons.append("manifest_fields")
    if manifest.get("contract_version") != STORE_CONTRACT_VERSION:
        reasons.append("manifest_contract_version")
    if manifest.get("store_id") != store_id:
        reasons.append("store_id")
    if manifest.get("installation_id_sha256") != installation_hash:
        reasons.append("installation_id_sha256")
    generation = manifest.get("generation")
    if type(generation) is not int or generation < 0:
        reasons.append("generation")
    for field in ("canonical_records", "reviews", "outcome_events"):
        if not isinstance(manifest.get(field), list):
            reasons.append(field)
    reasons.extend(validate_content_hash(manifest, hash_field="manifest_sha256", label="manifest"))
    return reasons


def ensure_researcher_memory_store(
    root: Path,
    *,
    installation_id: str,
    repo_root: Path | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=workspace,
        create=True,
    )
    manifest_path = resolved / _MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest = _read_store_json(resolved, _MANIFEST_NAME)
        reasons = _manifest_reasons(manifest, installation_id=installation_id)
        if reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
        with _store_lock(resolved):
            _recover_store_transactions_locked(
                resolved,
                installation_id=installation_id,
            )
        validate_researcher_memory_store(
            resolved,
            installation_id=installation_id,
            repo_root=repo_root,
            workspace=workspace,
        )
        return _read_store_json(resolved, _MANIFEST_NAME)
    try:
        existing_entries = {path.name for path in resolved.iterdir()}
    except OSError as exc:
        _raise(BLOCK_MEMORY_ROOT_INVALID, f"root_directory_unreadable:{exc}")
    if existing_entries:
        _raise(BLOCK_MEMORY_ROOT_INVALID, "uninitialized_root_not_empty")
    with _store_lock(resolved):
        if manifest_path.exists() or manifest_path.is_symlink():
            manifest = _read_store_json(resolved, _MANIFEST_NAME)
            reasons = _manifest_reasons(manifest, installation_id=installation_id)
            if reasons:
                _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
            return manifest
        unexpected = {
            path.name for path in resolved.iterdir() if path.name != _LOCK_NAME
        }
        if unexpected:
            _raise(BLOCK_MEMORY_ROOT_INVALID, "uninitialized_root_not_empty")
        for relative in (
            "canonical",
            "reviews",
            "outcomes",
            "transactions",
            _TEMP_DIR_NAME,
        ):
            _ensure_private_directory(resolved, relative)
        _atomic_store_json(
            resolved,
            _MANIFEST_NAME,
            _new_manifest(installation_id),
            replace=False,
        )
        manifest = _read_store_json(resolved, _MANIFEST_NAME)
        reasons = _manifest_reasons(manifest, installation_id=installation_id)
        if reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
        return manifest


def _validate_index_reference(reference: Any, *, kind: str) -> list[str]:
    if not isinstance(reference, dict):
        return [f"{kind}_reference_object"]
    common = {"path", "sha256"}
    expected = {
        "canonical": common | {"memory_id", "role_scope", "promoted_generation"},
        "review": common | {"review_id", "candidate_id", "decision"},
        "outcome": common
        | {"event_id", "factor_id", "research_id", "report_id", "roles", "factor_verdict"},
    }[kind]
    reasons: list[str] = []
    if set(reference) != expected:
        reasons.append(f"{kind}_reference_fields")
    if not isinstance(reference.get("path"), str):
        reasons.append(f"{kind}_reference_path")
    else:
        try:
            _safe_store_relative(str(reference["path"]))
        except ResearchOrganizationError:
            reasons.append(f"{kind}_reference_path")
    if not isinstance(reference.get("sha256"), str) or not SHA256_RE.fullmatch(
        str(reference.get("sha256") or "")
    ):
        reasons.append(f"{kind}_reference_sha256")
    return reasons


def _identity_shape_reasons(identity: Any, *, label: str) -> list[str]:
    expected = {"factor_id", "research_id", "report_id", "job_id"}
    if not isinstance(identity, Mapping):
        return [f"{label}_object"]
    reasons: list[str] = []
    if set(identity) != expected:
        reasons.append(f"{label}_fields")
    for key in expected:
        if not SAFE_ID_RE.fullmatch(str(identity.get(key) or "")):
            reasons.append(f"{label}_{key}")
    return reasons


def _portable_reference_reasons(
    reference: Any,
    *,
    label: str,
    id_field: str | None = None,
) -> list[str]:
    expected = {"path", "sha256"} if id_field is None else {id_field, "sha256"}
    if not isinstance(reference, Mapping):
        return [f"{label}_object"]
    reasons: list[str] = []
    if set(reference) != expected:
        reasons.append(f"{label}_fields")
    if id_field is None:
        raw_path = str(reference.get("path") or "")
        path = Path(raw_path)
        if (
            not raw_path
            or not _SAFE_RELATIVE_RE.fullmatch(raw_path)
            or path.is_absolute()
            or ".." in path.parts
        ):
            reasons.append(f"{label}_path")
    elif not SAFE_ID_RE.fullmatch(str(reference.get(id_field) or "")):
        reasons.append(f"{label}_{id_field}")
    if not SHA256_RE.fullmatch(str(reference.get("sha256") or "")):
        reasons.append(f"{label}_sha256")
    return reasons


def _source_runtime_provenance_reasons(
    provenance: Any,
    *,
    candidate: Mapping[str, Any],
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    trust_store: Any | None,
) -> list[str]:
    if not isinstance(provenance, Mapping):
        return ["source_runtime_provenance_object"]
    if set(provenance) != {"adapter_receipt", "host_admission_receipt"}:
        return ["source_runtime_provenance_fields"]
    adapter = provenance.get("adapter_receipt")
    host = provenance.get("host_admission_receipt")
    reasons: list[str] = []
    adapter_fields = {
        "contract_version",
        "receipt_type",
        "identity",
        "ordering",
        "bindings",
        "session",
        "outcome",
        "issuer",
        "receipt_id",
        "signature",
    }
    host_fields = {
        "contract_version",
        "receipt_type",
        "identity",
        "ordering",
        "bindings",
        "outcome",
        "issuer",
        "receipt_id",
        "signature",
    }
    if not isinstance(adapter, Mapping) or set(adapter) != adapter_fields:
        reasons.append("source_adapter_receipt_fields")
        adapter = {}
    if not isinstance(host, Mapping) or set(host) != host_fields:
        reasons.append("source_host_receipt_fields")
        host = {}
    expected_identity = dict(candidate.get("identity") or {})
    adapter_identity = adapter.get("identity") if isinstance(adapter.get("identity"), Mapping) else {}
    host_identity = host.get("identity") if isinstance(host.get("identity"), Mapping) else {}
    shared_runtime_fields = {"runtime_id", "task_id", "role_id", "attempt_id"}
    if (
        set(adapter_identity) != set(expected_identity) | shared_runtime_fields | {"attempt_no"}
        or set(host_identity) != set(expected_identity) | shared_runtime_fields
        or any(adapter_identity.get(key) != value for key, value in expected_identity.items())
        or any(host_identity.get(key) != value for key, value in expected_identity.items())
        or any(
            host_identity.get(key) != adapter_identity.get(key)
            for key in shared_runtime_fields
        )
        or adapter_identity.get("task_id") != task.get("task_id")
        or adapter_identity.get("role_id") != result.get("role_id")
        or type(adapter_identity.get("attempt_no")) is not int
        or int(adapter_identity.get("attempt_no") or 0) < 1
    ):
        reasons.append("source_runtime_identity")
    adapter_session = adapter.get("session") if isinstance(adapter.get("session"), Mapping) else {}
    if (
        set(adapter_session)
        != {
            "session_uid",
            "runtime_handle_sha256",
            "provider_handle_sha256",
            "adapter_id",
            "adapter_build_sha256",
            "container_image_digest",
            "isolation_profile_sha256",
            "runtime",
            "parent_session_uid",
            "lease_epoch",
        }
        or adapter_session.get("session_uid") != candidate.get("source_session_id")
        or not SAFE_ID_RE.fullmatch(str(adapter_session.get("adapter_id") or ""))
        or type(adapter_session.get("lease_epoch")) is not int
        or any(
            not SHA256_RE.fullmatch(str(adapter_session.get(field) or ""))
            for field in (
                "provider_handle_sha256",
                "adapter_build_sha256",
                "isolation_profile_sha256",
            )
        )
    ):
        reasons.append("source_runtime_session")
    adapter_runtime = (
        adapter_session.get("runtime")
        if isinstance(adapter_session.get("runtime"), Mapping)
        else {}
    )
    if adapter_runtime != {
        "provider": "deepseek",
        "model": "deepseek/deepseek-v4-flash",
        "transport": "openclaw_disposable_container",
        "isolation_class": "container_staged_context",
        "owned_termination_supported": True,
    }:
        reasons.append("source_runtime_execution_profile")
    adapter_bindings = adapter.get("bindings") if isinstance(adapter.get("bindings"), Mapping) else {}
    if (
        set(adapter_bindings)
        != {
            "plan_sha256",
            "task_sha256",
            "context_manifest_sha256",
            "dependency_admissions",
            "idempotency_key",
            "adapter_challenge",
        }
        or adapter_bindings.get("task_sha256") != task.get("task_sha256")
        or any(
            not SHA256_RE.fullmatch(str(adapter_bindings.get(field) or ""))
            for field in ("plan_sha256", "task_sha256", "context_manifest_sha256")
        )
        or not isinstance(adapter_bindings.get("dependency_admissions"), list)
        or not isinstance(adapter_bindings.get("idempotency_key"), str)
        or not adapter_bindings.get("idempotency_key")
        or not isinstance(adapter_bindings.get("adapter_challenge"), str)
        or not adapter_bindings.get("adapter_challenge")
    ):
        reasons.append("source_adapter_bindings")
    adapter_outcome = adapter.get("outcome") if isinstance(adapter.get("outcome"), Mapping) else {}
    if (
        adapter.get("receipt_type") != "COMPLETED"
        or set(adapter_outcome)
        != {
            "returncode",
            "cancelled",
            "error_class",
            "private_output_sha256",
            "private_output_size_bytes",
            "termination_confirmed",
        }
        or adapter_outcome.get("returncode") != 0
        or adapter_outcome.get("cancelled") is not False
        or adapter_outcome.get("error_class") is not None
        or adapter_outcome.get("termination_confirmed") is not True
        or not SHA256_RE.fullmatch(str(adapter_outcome.get("private_output_sha256") or ""))
        or type(adapter_outcome.get("private_output_size_bytes")) is not int
        or int(adapter_outcome.get("private_output_size_bytes") or 0) <= 0
    ):
        reasons.append("source_adapter_outcome")
    host_bindings = host.get("bindings") if isinstance(host.get("bindings"), Mapping) else {}
    host_outcome = host.get("outcome") if isinstance(host.get("outcome"), Mapping) else {}
    if (
        host.get("receipt_type") != "RESULT_ADMITTED"
        or set(host_bindings)
        != {
            "plan_sha256",
            "task_sha256",
            "context_manifest_sha256",
            "dependency_admissions",
            "adapter_receipt_id",
            "result_sha256",
        }
        or host_bindings.get("plan_sha256") != adapter_bindings.get("plan_sha256")
        or host_bindings.get("task_sha256") != task.get("task_sha256")
        or host_bindings.get("context_manifest_sha256")
        != adapter_bindings.get("context_manifest_sha256")
        or host_bindings.get("dependency_admissions")
        != adapter_bindings.get("dependency_admissions")
        or host_bindings.get("adapter_receipt_id") != adapter.get("receipt_id")
        or host_bindings.get("result_sha256") != result.get("result_sha256")
        or host_outcome
        != {
            "result_status": result.get("status"),
            "evidence_class": "signed_adapter",
        }
    ):
        reasons.append("source_host_admission_binding")
    if trust_store is not None:
        reasons.extend(
            f"source_adapter_signature:{reason}"
            for reason in trust_store.verify(adapter, expected_issuer="runtime_adapter")
        )
        reasons.extend(
            f"source_host_signature:{reason}"
            for reason in trust_store.verify(host, expected_issuer="host_admission")
        )
        if adapter_session.get("adapter_id") != trust_store.installation_id:
            reasons.append("source_runtime_installation")
    return reasons


def _candidate_content_hash_reasons(candidate: Mapping[str, Any]) -> list[str]:
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"materialization_receipt", "candidate_sha256"}
    }
    if candidate.get("candidate_sha256") != stable_json_hash(payload):
        return ["candidate_content_hash"]
    return []


def _candidate_materialization_receipt_reasons(
    receipt: Any,
    *,
    candidate: Mapping[str, Any],
    trust_store: Any | None,
) -> list[str]:
    if not isinstance(receipt, Mapping):
        return ["candidate_materialization_receipt_object"]
    expected_fields = {
        "contract_version",
        "receipt_type",
        "identity",
        "bindings",
        "outcome",
        "issuer",
        "receipt_id",
        "signature",
    }
    reasons: list[str] = []
    if set(receipt) != expected_fields:
        reasons.append("candidate_materialization_receipt_fields")
    identity = candidate.get("identity") or {}
    candidate_relative = (
        f"objects/research_organization/{identity.get('report_id')}"
        f"/memory_candidates/{candidate.get('source_role_id')}__"
        f"{candidate.get('candidate_id')}.json"
    )
    provenance = candidate.get("source_runtime_provenance") or {}
    adapter = provenance.get("adapter_receipt") or {}
    host = provenance.get("host_admission_receipt") or {}
    adapter_outcome = adapter.get("outcome") or {}
    expected_bindings = {
        "candidate_ref": {
            "path": candidate_relative,
            "sha256": candidate.get("candidate_sha256"),
        },
        "source_task_ref": candidate.get("source_task_ref"),
        "source_result_ref": candidate.get("source_result_ref"),
        "source_memory_snapshot_ref": candidate.get(
            "source_memory_snapshot_ref"
        ),
        "source_session_id": candidate.get("source_session_id"),
        "source_private_output_sha256": adapter_outcome.get(
            "private_output_sha256"
        ),
        "source_adapter_receipt_id": adapter.get("receipt_id"),
        "source_host_admission_receipt_id": host.get("receipt_id"),
    }
    if (
        receipt.get("receipt_type")
        != "RESEARCHER_MEMORY_CANDIDATE_MATERIALIZED"
        or receipt.get("identity") != identity
        or receipt.get("bindings") != expected_bindings
        or receipt.get("outcome")
        != {"authority": "candidate_only", "promotion_allowed": False}
    ):
        reasons.append("candidate_materialization_receipt_binding")
    if trust_store is not None:
        reasons.extend(
            f"candidate_materialization_signature:{reason}"
            for reason in trust_store.verify(
                receipt,
                expected_issuer="host_admission",
            )
        )
    return reasons


def _embedded_candidate_reasons(
    candidate: Any,
    *,
    trust_store: Any | None,
) -> list[str]:
    if not isinstance(candidate, Mapping):
        return ["embedded_candidate_object"]
    expected_fields = {
        "contract_version",
        "candidate_id",
        "identity",
        "source_role_id",
        "source_task_ref",
        "source_result_ref",
        "source_session_id",
        "source_runtime_provenance",
        "source_memory_snapshot_ref",
        "role_scope",
        "memory_kind",
        "title",
        "lesson",
        "applicability_conditions",
        "failure_conditions",
        "evidence_refs",
        "authority",
        "promotion_allowed",
        "materialization_receipt",
        "candidate_sha256",
    }
    reasons: list[str] = []
    if set(candidate) != expected_fields:
        reasons.append("embedded_candidate_fields")
    if candidate.get("contract_version") != CANDIDATE_CONTRACT_VERSION:
        reasons.append("embedded_candidate_contract_version")
    reasons.extend(
        _identity_shape_reasons(
            candidate.get("identity"),
            label="embedded_candidate_identity",
        )
    )
    task_ref = candidate.get("source_task_ref")
    result_ref = candidate.get("source_result_ref")
    if (
        not isinstance(task_ref, Mapping)
        or set(task_ref) != {"task_id", "sha256"}
        or not SAFE_ID_RE.fullmatch(str(task_ref.get("task_id") or ""))
        or not SHA256_RE.fullmatch(str(task_ref.get("sha256") or ""))
    ):
        reasons.append("embedded_candidate_task_ref")
    reasons.extend(
        _portable_reference_reasons(
            result_ref,
            label="embedded_candidate_result_ref",
        )
    )
    if (
        not SAFE_ID_RE.fullmatch(str(candidate.get("source_role_id") or ""))
        or not SAFE_ID_RE.fullmatch(str(candidate.get("source_session_id") or ""))
        or candidate.get("role_scope") != [candidate.get("source_role_id")]
        or candidate.get("authority") != "candidate_only"
        or candidate.get("promotion_allowed") is not False
        or candidate.get("memory_kind") not in MEMORY_KINDS
    ):
        reasons.append("embedded_candidate_authority")
    host_receipt = (
        (candidate.get("source_runtime_provenance") or {}).get(
            "host_admission_receipt"
        )
        if isinstance(candidate.get("source_runtime_provenance"), Mapping)
        else {}
    )
    host_outcome = (
        host_receipt.get("outcome")
        if isinstance(host_receipt, Mapping)
        and isinstance(host_receipt.get("outcome"), Mapping)
        else {}
    )
    reasons.extend(
        _source_runtime_provenance_reasons(
            candidate.get("source_runtime_provenance"),
            candidate=candidate,
            task={
                "task_id": str((task_ref or {}).get("task_id") or ""),
                "task_sha256": str((task_ref or {}).get("sha256") or ""),
            },
            result={
                "role_id": str(candidate.get("source_role_id") or ""),
                "result_sha256": str((result_ref or {}).get("sha256") or ""),
                "status": host_outcome.get("result_status"),
            },
            trust_store=trust_store,
        )
    )
    reasons.extend(
        _candidate_materialization_receipt_reasons(
            candidate.get("materialization_receipt"),
            candidate=candidate,
            trust_store=trust_store,
        )
    )
    core = {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "contract_version",
            "candidate_id",
            "candidate_sha256",
            "materialization_receipt",
        }
    }
    if candidate.get("candidate_id") != f"candidate_{stable_json_hash(core)[:24]}":
        reasons.append("embedded_candidate_id_content_binding")
    reasons.extend(_candidate_content_hash_reasons(candidate))
    if _contains_absolute_path(candidate):
        reasons.append("embedded_candidate_absolute_path_disclosure")
    return reasons


def _review_claim_sha256(
    *,
    identity: Mapping[str, Any],
    candidate_ref: Mapping[str, Any],
    outcome_event_ref: Mapping[str, Any],
    reviewer: Mapping[str, Any],
    source_session_id: str,
    decision: str,
    rationale: str,
    canonical_write_authorized: bool,
    review_parent: Mapping[str, Any],
    expected_parent_generation: int,
) -> str:
    return stable_json_hash(
        {
            "identity": dict(identity),
            "candidate_ref": dict(candidate_ref),
            "outcome_event_ref": dict(outcome_event_ref),
            "reviewer": dict(reviewer),
            "source_session_id": source_session_id,
            "decision": decision,
            "rationale": rationale,
            "canonical_write_authorized": canonical_write_authorized,
            "review_parent": dict(review_parent),
            "expected_parent_generation": expected_parent_generation,
        }
    )


def _review_session_receipt_reasons(
    receipt: Any,
    *,
    identity: Any,
    candidate_ref: Any,
    outcome_event_ref: Any,
    source_session_id: str,
    decision: str,
    rationale: str,
    review_parent: Any,
    expected_parent_generation: int,
    trust_store: Any | None,
) -> list[str]:
    if not isinstance(receipt, Mapping):
        return ["review_session_receipt_object"]
    expected_fields = {
        "contract_version",
        "receipt_type",
        "identity",
        "reviewer",
        "bindings",
        "runtime_evidence",
        "outcome",
        "issuer",
        "receipt_id",
        "signature",
    }
    reasons: list[str] = []
    reviewer = receipt.get("reviewer")
    bindings = receipt.get("bindings")
    runtime_evidence = receipt.get("runtime_evidence")
    outcome = receipt.get("outcome")
    if set(receipt) != expected_fields:
        reasons.append("review_session_receipt_fields")
    if receipt.get("receipt_type") != "RESEARCHER_MEMORY_REVIEW_COMPLETED":
        reasons.append("review_session_receipt_type")
    if receipt.get("identity") != identity:
        reasons.append("review_session_receipt_identity")
    if (
        not isinstance(reviewer, Mapping)
        or set(reviewer)
        != {
            "reviewer_id",
            "reviewer_session_id",
            "runtime_instance_id",
            "independence_class",
        }
        or reviewer.get("independence_class")
        != "runtime_attested_independent_review"
        or any(
            not SAFE_ID_RE.fullmatch(str(reviewer.get(field) or ""))
            for field in ("reviewer_id", "reviewer_session_id", "runtime_instance_id")
        )
        or reviewer.get("reviewer_session_id") == source_session_id
    ):
        reasons.append("review_session_receipt_reviewer")
    public_reviewer = {
        "reviewer_id": str((reviewer or {}).get("reviewer_id") or ""),
        "reviewer_session_id": str((reviewer or {}).get("reviewer_session_id") or ""),
        "independence_class": "host_attested_independent_review",
    }
    claim_sha256 = _review_claim_sha256(
        identity=identity if isinstance(identity, Mapping) else {},
        candidate_ref=candidate_ref if isinstance(candidate_ref, Mapping) else {},
        outcome_event_ref=(
            outcome_event_ref if isinstance(outcome_event_ref, Mapping) else {}
        ),
        reviewer=public_reviewer,
        source_session_id=source_session_id,
        decision=decision,
        rationale=rationale,
        canonical_write_authorized=decision == "APPROVE_CANONICAL",
        review_parent=(review_parent if isinstance(review_parent, Mapping) else {}),
        expected_parent_generation=expected_parent_generation,
    )
    if (
        not isinstance(bindings, Mapping)
        or set(bindings)
        != {
            "candidate_ref",
            "outcome_event_ref",
            "source_session_id",
            "review_claim_sha256",
            "review_parent",
            "expected_parent_generation",
        }
        or bindings.get("candidate_ref") != candidate_ref
        or bindings.get("outcome_event_ref") != outcome_event_ref
        or bindings.get("source_session_id") != source_session_id
        or bindings.get("review_claim_sha256") != claim_sha256
        or bindings.get("review_parent") != review_parent
        or bindings.get("expected_parent_generation")
        != expected_parent_generation
    ):
        reasons.append("review_session_receipt_bindings")
    if outcome != {
        "returncode": 0,
        "termination_confirmed": True,
        "secret_scan": "PASS",
    }:
        reasons.append("review_session_receipt_outcome")
    if (
        not isinstance(runtime_evidence, Mapping)
        or set(runtime_evidence)
        != {
            "adapter_completion_receipt",
            "review_request",
            "review_output",
            "review_output_sha256",
            "model_execution",
        }
    ):
        reasons.append("review_runtime_evidence_fields")
    else:
        adapter_completion = runtime_evidence.get(
            "adapter_completion_receipt"
        )
        request = runtime_evidence.get("review_request")
        review_output = runtime_evidence.get("review_output")
        model_execution = runtime_evidence.get("model_execution")
        review_output_sha256 = runtime_evidence.get("review_output_sha256")
        identity_mapping = identity if isinstance(identity, Mapping) else {}
        request_mapping = request if isinstance(request, Mapping) else {}
        if trust_store is not None and isinstance(adapter_completion, Mapping):
            reasons.extend(
                f"review_adapter_completion_signature:{reason}"
                for reason in trust_store.verify(
                    adapter_completion,
                    expected_issuer="runtime_adapter",
                )
            )
        adapter_identity = (
            adapter_completion.get("identity")
            if isinstance(adapter_completion, Mapping)
            and isinstance(adapter_completion.get("identity"), Mapping)
            else {}
        )
        adapter_session = (
            adapter_completion.get("session")
            if isinstance(adapter_completion, Mapping)
            and isinstance(adapter_completion.get("session"), Mapping)
            else {}
        )
        adapter_bindings = (
            adapter_completion.get("bindings")
            if isinstance(adapter_completion, Mapping)
            and isinstance(adapter_completion.get("bindings"), Mapping)
            else {}
        )
        adapter_outcome = (
            adapter_completion.get("outcome")
            if isinstance(adapter_completion, Mapping)
            and isinstance(adapter_completion.get("outcome"), Mapping)
            else {}
        )
        if (
            not isinstance(request, Mapping)
            or request.get("contract_version")
            != "factorforge_researcher_memory_review_request_v1"
            or validate_content_hash(
                request,
                hash_field="request_sha256",
                label="review_runtime_request",
            )
            or request.get("identity") != identity
            or request.get("candidate_ref") != candidate_ref
            or request.get("outcome_event_ref") != outcome_event_ref
            or request.get("source_session_id") != source_session_id
            or request.get("review_parent") != review_parent
        ):
            reasons.append("review_runtime_request_binding")
        try:
            if not isinstance(review_output, Mapping):
                raise ResearchOrganizationError(
                    BLOCK_MEMORY_REVIEW_INVALID,
                    ["review_output_object"],
                )
            from factor_factory.researcher_memory_review import (
                validate_reviewer_private_output,
            )

            output_decision, output_rationale = (
                validate_reviewer_private_output(
                    review_output,
                    request=(request if isinstance(request, Mapping) else {}),
                )
            )
            if output_decision != decision or output_rationale != rationale:
                reasons.append("review_runtime_output_claim")
        except ResearchOrganizationError:
            reasons.append("review_runtime_output_contract")
        if (
            not isinstance(adapter_completion, Mapping)
            or adapter_completion.get("receipt_type") != "COMPLETED"
            or adapter_identity.get("role_id")
            != "researcher_memory_reviewer"
            or adapter_identity.get("job_id")
            != identity_mapping.get("job_id")
            or adapter_session.get("session_uid")
            != (reviewer or {}).get("reviewer_session_id")
            or adapter_identity.get("attempt_no") != 1
            or adapter_bindings.get("task_sha256")
            != request_mapping.get("request_sha256")
            or adapter_outcome.get("returncode") != 0
            or adapter_outcome.get("cancelled") is not False
            or adapter_outcome.get("termination_confirmed") is not True
            or adapter_outcome.get("private_output_sha256")
            != review_output_sha256
            or not SHA256_RE.fullmatch(str(review_output_sha256 or ""))
        ):
            reasons.append("review_adapter_completion_binding")
        if (
            not isinstance(model_execution, Mapping)
            or set(model_execution)
            != {
                "provider",
                "model",
                "transport",
                "isolation_class",
                "owned_termination_supported",
            }
            or any(
                not isinstance(model_execution.get(field), str)
                or not model_execution.get(field)
                for field in ("provider", "model", "transport")
            )
            or model_execution.get("isolation_class")
            != "container_staged_context"
            or model_execution.get("owned_termination_supported") is not True
        ):
            reasons.append("review_model_execution")
    if trust_store is not None:
        reasons.extend(
            f"review_session_receipt_signature:{reason}"
            for reason in trust_store.verify(receipt, expected_issuer="runtime_adapter")
        )
    return reasons


def _reviewer_attestation_reasons(
    attestation: Any,
    *,
    identity: Any,
    candidate_ref: Any,
    outcome_event_ref: Any,
    reviewer: Any,
    source_session_id: str | None,
    review_session_receipt: Any,
    review_claim_sha256: str,
    review_parent: Any,
    expected_parent_generation: int,
    trust_store: Any | None,
) -> list[str]:
    if not isinstance(attestation, Mapping):
        return ["reviewer_attestation_object"]
    expected_fields = {
        "contract_version",
        "receipt_type",
        "identity",
        "bindings",
        "reviewer",
        "issuer",
        "receipt_id",
        "signature",
    }
    reasons: list[str] = []
    bindings = attestation.get("bindings")
    if set(attestation) != expected_fields:
        reasons.append("reviewer_attestation_fields")
    if attestation.get("contract_version") != "factorforge_signed_runtime_receipt_v1":
        reasons.append("reviewer_attestation_contract_version")
    if attestation.get("receipt_type") != "RESEARCHER_MEMORY_REVIEW_ATTESTED":
        reasons.append("reviewer_attestation_type")
    if attestation.get("identity") != identity:
        reasons.append("reviewer_attestation_identity")
    if attestation.get("reviewer") != reviewer:
        reasons.append("reviewer_attestation_reviewer")
    observed_source_session = (
        str(bindings.get("source_session_id") or "")
        if isinstance(bindings, Mapping)
        else ""
    )
    if (
        not isinstance(bindings, Mapping)
        or set(bindings)
        != {
            "candidate_ref",
            "outcome_event_ref",
            "source_session_id",
            "review_session_receipt_id",
            "review_claim_sha256",
            "review_parent",
            "expected_parent_generation",
        }
        or bindings.get("candidate_ref") != candidate_ref
        or bindings.get("outcome_event_ref") != outcome_event_ref
        or bindings.get("review_session_receipt_id")
        != str((review_session_receipt or {}).get("receipt_id") or "")
        or bindings.get("review_claim_sha256") != review_claim_sha256
        or bindings.get("review_parent") != review_parent
        or bindings.get("expected_parent_generation")
        != expected_parent_generation
        or not SAFE_ID_RE.fullmatch(observed_source_session)
        or (
            source_session_id is not None
            and observed_source_session != source_session_id
        )
        or observed_source_session
        == str((reviewer or {}).get("reviewer_session_id") or "")
    ):
        reasons.append("reviewer_attestation_bindings")
    issuer = attestation.get("issuer")
    if not isinstance(issuer, Mapping) or issuer.get("kind") != "host_admission":
        reasons.append("reviewer_attestation_issuer")
    if trust_store is not None:
        reasons.extend(
            f"reviewer_attestation_signature:{reason}"
            for reason in trust_store.verify(
                attestation,
                expected_issuer="host_admission",
            )
        )
    return reasons


def _review_payload_reasons(
    review: Any,
    *,
    source_session_id: str | None = None,
    trust_store: Any | None = None,
) -> list[str]:
    if not isinstance(review, Mapping):
        return ["review_object"]
    expected_fields = {
        "contract_version",
        "review_id",
        "identity",
        "candidate_ref",
        "candidate_snapshot",
        "decision",
        "reviewer",
        "review_session_receipt",
        "reviewer_attestation",
        "outcome_event_ref",
        "rationale",
        "canonical_write_authorized",
        "review_parent",
        "expected_parent_generation",
        "review_sha256",
    }
    reasons: list[str] = []
    if set(review) != expected_fields:
        reasons.append("review_fields")
    if review.get("contract_version") != REVIEW_CONTRACT_VERSION:
        reasons.append("review_contract_version")
    if not SAFE_ID_RE.fullmatch(str(review.get("review_id") or "")):
        reasons.append("review_id")
    reasons.extend(_identity_shape_reasons(review.get("identity"), label="review_identity"))
    reasons.extend(
        _portable_reference_reasons(
            review.get("candidate_ref"),
            label="review_candidate_ref",
        )
    )
    candidate_snapshot = review.get("candidate_snapshot")
    if (
        not isinstance(candidate_snapshot, Mapping)
        or candidate_snapshot.get("candidate_sha256")
        != (review.get("candidate_ref") or {}).get("sha256")
        or candidate_snapshot.get("candidate_id")
        not in str((review.get("candidate_ref") or {}).get("path") or "")
        or _candidate_content_hash_reasons(candidate_snapshot)
    ):
        reasons.append("review_candidate_snapshot")
    if isinstance(candidate_snapshot, Mapping):
        reasons.extend(
            _embedded_candidate_reasons(
                candidate_snapshot,
                trust_store=trust_store,
            )
        )
        if candidate_snapshot.get("identity") != review.get("identity"):
            reasons.append("review_candidate_identity")
    decision = review.get("decision")
    if decision not in REVIEW_DECISIONS:
        reasons.append("review_decision")
    if review.get("canonical_write_authorized") is not (
        decision == "APPROVE_CANONICAL"
    ):
        reasons.append("review_canonical_write_authorized")
    reviewer = review.get("reviewer")
    if (
        not isinstance(reviewer, Mapping)
        or set(reviewer)
        != {"reviewer_id", "reviewer_session_id", "independence_class"}
        or reviewer.get("independence_class") != "host_attested_independent_review"
        or not SAFE_ID_RE.fullmatch(str(reviewer.get("reviewer_id") or ""))
        or not SAFE_ID_RE.fullmatch(str(reviewer.get("reviewer_session_id") or ""))
    ):
        reasons.append("review_reviewer")
    observed_source_session_id = str(
        (candidate_snapshot or {}).get("source_session_id")
        or source_session_id
        or ""
    )
    review_parent = review.get("review_parent")
    expected_parent_generation = review.get("expected_parent_generation")
    review_claim_sha256 = _review_claim_sha256(
        identity=review.get("identity") if isinstance(review.get("identity"), Mapping) else {},
        candidate_ref=(
            review.get("candidate_ref")
            if isinstance(review.get("candidate_ref"), Mapping)
            else {}
        ),
        outcome_event_ref=(
            review.get("outcome_event_ref")
            if isinstance(review.get("outcome_event_ref"), Mapping)
            else {}
        ),
        reviewer=reviewer if isinstance(reviewer, Mapping) else {},
        source_session_id=observed_source_session_id,
        decision=str(decision or ""),
        rationale=str(review.get("rationale") or ""),
        canonical_write_authorized=bool(review.get("canonical_write_authorized")),
        review_parent=(review_parent if isinstance(review_parent, Mapping) else {}),
        expected_parent_generation=(
            expected_parent_generation
            if type(expected_parent_generation) is int
            else -1
        ),
    )
    reasons.extend(
        _review_session_receipt_reasons(
            review.get("review_session_receipt"),
            identity=review.get("identity"),
            candidate_ref=review.get("candidate_ref"),
            outcome_event_ref=review.get("outcome_event_ref"),
            source_session_id=observed_source_session_id,
            decision=str(decision or ""),
            rationale=str(review.get("rationale") or ""),
            review_parent=review_parent,
            expected_parent_generation=(
                expected_parent_generation
                if type(expected_parent_generation) is int
                else -1
            ),
            trust_store=trust_store,
        )
    )
    reasons.extend(
        _reviewer_attestation_reasons(
            review.get("reviewer_attestation"),
            identity=review.get("identity"),
            candidate_ref=review.get("candidate_ref"),
            outcome_event_ref=review.get("outcome_event_ref"),
            reviewer=review.get("reviewer"),
            source_session_id=observed_source_session_id,
            review_session_receipt=review.get("review_session_receipt"),
            review_claim_sha256=review_claim_sha256,
            review_parent=review_parent,
            expected_parent_generation=(
                expected_parent_generation
                if type(expected_parent_generation) is int
                else -1
            ),
            trust_store=trust_store,
        )
    )
    reasons.extend(
        _portable_reference_reasons(
            review.get("outcome_event_ref"),
            label="review_outcome_ref",
            id_field="event_id",
        )
    )
    rationale = review.get("rationale")
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or rationale != rationale.strip()
        or len(rationale) > 4000
    ):
        reasons.append("review_rationale")
    generation = expected_parent_generation
    if type(generation) is not int or generation < 1:
        reasons.append("review_expected_parent_generation")
    if (
        not isinstance(review_parent, Mapping)
        or set(review_parent)
        != {"store_id", "generation", "manifest_sha256"}
        or not SAFE_ID_RE.fullmatch(str(review_parent.get("store_id") or ""))
        or type(review_parent.get("generation")) is not int
        or int(review_parent.get("generation") or -1) < 0
        or not SHA256_RE.fullmatch(
            str(review_parent.get("manifest_sha256") or "")
        )
        or generation != int(review_parent.get("generation") or -1) + 1
    ):
        reasons.append("review_parent")
    core = {
        key: value
        for key, value in review.items()
        if key not in {"contract_version", "review_id", "review_sha256"}
    }
    if review.get("review_id") != f"review_{stable_json_hash(core)[:24]}":
        reasons.append("review_id_content_binding")
    reasons.extend(validate_content_hash(review, hash_field="review_sha256", label="review"))
    return reasons


def _outcome_payload_reasons(event: Any) -> list[str]:
    if not isinstance(event, Mapping):
        return ["outcome_object"]
    expected_fields = {
        "contract_version",
        "event_id",
        "identity",
        "roles",
        "execution_status",
        "protocol_status",
        "factor_verdict",
        "council_status",
        "formal_proof_eligible",
        "organization_runtime_verified",
        "host_attestation_ref",
        "model_execution",
        "interpretation_guard",
        "event_sha256",
    }
    reasons: list[str] = []
    if set(event) != expected_fields:
        reasons.append("outcome_fields")
    if event.get("contract_version") != OUTCOME_EVENT_CONTRACT_VERSION:
        reasons.append("outcome_contract_version")
    if not SAFE_ID_RE.fullmatch(str(event.get("event_id") or "")):
        reasons.append("outcome_event_id")
    reasons.extend(_identity_shape_reasons(event.get("identity"), label="outcome_identity"))
    roles = event.get("roles")
    if (
        not isinstance(roles, list)
        or not roles
        or len(set(str(role) for role in roles)) != len(roles)
        or any(not SAFE_ID_RE.fullmatch(str(role)) for role in roles)
    ):
        reasons.append("outcome_roles")
    for field in ("execution_status", "protocol_status", "council_status"):
        value = event.get(field)
        if not isinstance(value, str) or not value or len(value) > 128:
            reasons.append(f"outcome_{field}")
    if event.get("execution_status") != "COMPLETED":
        reasons.append("outcome_not_terminal")
    if event.get("factor_verdict") not in {"ACCEPT", "REJECT"}:
        reasons.append("outcome_factor_verdict")
    if type(event.get("formal_proof_eligible")) is not bool:
        reasons.append("outcome_formal_proof_eligible")
    if event.get("organization_runtime_verified") is not True:
        reasons.append("outcome_organization_runtime_unverified")
    if (
        event.get("factor_verdict") == "ACCEPT"
        and event.get("formal_proof_eligible") is not True
    ):
        reasons.append("outcome_accept_without_formal_proof")
    attestation = event.get("host_attestation_ref")
    attestation_id = (
        str(attestation.get("id") or "")
        if isinstance(attestation, Mapping)
        else ""
    )
    attestation_path = Path(attestation_id)
    if (
        not isinstance(attestation, Mapping)
        or set(attestation) != {"id", "sha256"}
        or not attestation_id
        or not _SAFE_RELATIVE_RE.fullmatch(attestation_id)
        or attestation_path.is_absolute()
        or ".." in attestation_path.parts
        or not SHA256_RE.fullmatch(str(attestation.get("sha256") or ""))
    ):
        reasons.append("outcome_host_attestation_ref")
    model_execution = event.get("model_execution")
    if (
        not isinstance(model_execution, Mapping)
        or set(model_execution) != {"provider", "model", "provenance"}
        or any(
            not isinstance(model_execution.get(field), str)
            or not model_execution.get(field)
            or len(str(model_execution.get(field))) > 256
            for field in ("provider", "model", "provenance")
        )
    ):
        reasons.append("outcome_model_execution")
    if event.get("interpretation_guard") != "protocol PASS is not factor ACCEPT":
        reasons.append("outcome_interpretation_guard")
    core = {
        key: value
        for key, value in event.items()
        if key not in {"contract_version", "event_id", "event_sha256"}
    }
    if event.get("event_id") != f"outcome_{stable_json_hash(core)[:24]}":
        reasons.append("outcome_id_content_binding")
    reasons.extend(validate_content_hash(event, hash_field="event_sha256", label="outcome"))
    return reasons


def _host_outcome_attestation_reasons(
    raw: bytes,
    *,
    event: Mapping[str, Any],
    state_root: Path,
) -> list[str]:
    try:
        attestation = strict_json_loads(raw, label="host_execution_attestation")
    except ResearchOrganizationError as exc:
        return [f"host_attestation_json:{exc.token}"]
    if not isinstance(attestation, Mapping):
        return ["host_attestation_object"]
    identity = event.get("identity") if isinstance(event.get("identity"), Mapping) else {}
    reasons: list[str] = []
    if attestation.get("version") != "factorforge_console_host_execution_attestation_v2":
        reasons.append("host_attestation_contract_version")
    if any(
        attestation.get(field) != identity.get(field)
        for field in ("job_id", "factor_id", "research_id", "report_id")
    ):
        reasons.append("host_attestation_identity")
    if (
        attestation.get("host_observed_ultimate_process") is not True
        or attestation.get("host_evidence_reader_invoked") is not True
    ):
        reasons.append("host_attestation_provenance")
    expected_outcome = {
        "execution_status": event.get("execution_status"),
        "protocol_status": event.get("protocol_status"),
        "factor_verdict": event.get("factor_verdict"),
        "council_status": event.get("council_status"),
        "formal_proof_eligible": event.get("formal_proof_eligible"),
        "organization_runtime_verified": event.get(
            "organization_runtime_verified"
        ),
        "roles": event.get("roles"),
    }
    if attestation.get("researcher_memory_outcome") != expected_outcome:
        reasons.append("host_attestation_outcome_binding")
    model_execution = event.get("model_execution") if isinstance(event.get("model_execution"), Mapping) else {}
    if (
        attestation.get("agent_provider") != model_execution.get("provider")
        or attestation.get("agent_model") != model_execution.get("model")
        or model_execution.get("provenance") != "host_pinned_agent_runtime"
    ):
        reasons.append("host_attestation_model_binding")
    formal_status = attestation.get("host_terminal_formal_validation_status")
    if event.get("formal_proof_eligible") is True and formal_status != "PASS":
        reasons.append("host_attestation_formal_proof_binding")
    if (
        event.get("factor_verdict") == "ACCEPT"
        and (
            event.get("formal_proof_eligible") is not True
            or formal_status != "PASS"
        )
    ):
        reasons.append("host_attestation_accept_binding")
    for field in (
        "formal_execution_receipt_id",
        "formal_execution_receipt_sha256",
        "workspace_evidence_tree_id",
        "workspace_evidence_tree_sha256",
        "workspace_evidence_tree_root_sha256",
    ):
        value = attestation.get(field)
        if not isinstance(value, str) or not value:
            reasons.append(f"host_attestation_{field}")
    if not SHA256_RE.fullmatch(
        str(attestation.get("formal_execution_receipt_sha256") or "")
    ):
        reasons.append("host_attestation_formal_execution_receipt_sha256")
    if not SHA256_RE.fullmatch(
        str(attestation.get("workspace_evidence_tree_sha256") or "")
    ):
        reasons.append("host_attestation_workspace_evidence_tree_sha256")
    if not SHA256_RE.fullmatch(
        str(attestation.get("workspace_evidence_tree_root_sha256") or "")
    ):
        reasons.append("host_attestation_workspace_evidence_tree_root_sha256")

    formal_receipt_id = str(
        attestation.get("formal_execution_receipt_id") or ""
    )
    evidence_tree_id = str(attestation.get("workspace_evidence_tree_id") or "")
    for label, relative, expected_sha256 in (
        (
            "formal_execution_receipt",
            formal_receipt_id,
            str(attestation.get("formal_execution_receipt_sha256") or ""),
        ),
        (
            "workspace_evidence_tree",
            evidence_tree_id,
            str(attestation.get("workspace_evidence_tree_sha256") or ""),
        ),
    ):
        path = Path(relative)
        if (
            not relative
            or not _SAFE_RELATIVE_RE.fullmatch(relative)
            or path.is_absolute()
            or ".." in path.parts
        ):
            reasons.append(f"host_attestation_{label}_id")
            continue
        try:
            observed = _read_store_bytes(state_root, relative)
        except ResearchOrganizationError as exc:
            reasons.append(f"host_attestation_{label}_readback:{exc.token}")
            continue
        if hashlib.sha256(observed).hexdigest() != expected_sha256:
            reasons.append(f"host_attestation_{label}_readback_sha256")
            continue
        try:
            payload = strict_json_loads(observed, label=label)
        except ResearchOrganizationError as exc:
            reasons.append(f"host_attestation_{label}_json:{exc.token}")
            continue
        if not isinstance(payload, Mapping):
            reasons.append(f"host_attestation_{label}_object")
            continue
        if label == "formal_execution_receipt":
            commands = payload.get("commands")
            if (
                payload.get("version")
                != "factorforge_console_host_formal_execution_v2"
                or any(
                    payload.get(field) != identity.get(field)
                    for field in ("job_id", "factor_id", "research_id", "report_id")
                )
                or not isinstance(commands, list)
                or len(commands) != 2
                or any(not isinstance(command, Mapping) for command in commands)
            ):
                reasons.append("host_attestation_formal_execution_receipt_contract")
        else:
            entries = payload.get("entries")
            tree_hash = stable_json_hash(entries) if isinstance(entries, Mapping) else ""
            if (
                payload.get("version")
                != "factorforge_console_workspace_evidence_tree_v1"
                or any(
                    payload.get(field) != identity.get(field)
                    for field in ("job_id", "factor_id", "research_id", "report_id")
                )
                or not isinstance(entries, Mapping)
                or not all(
                    isinstance(path_value, str)
                    and bool(path_value)
                    and isinstance(digest, str)
                    and SHA256_RE.fullmatch(digest) is not None
                    for path_value, digest in (entries or {}).items()
                )
                or payload.get("tree_sha256") != tree_hash
                or attestation.get("workspace_evidence_tree_root_sha256")
                != tree_hash
            ):
                reasons.append("host_attestation_workspace_evidence_tree_contract")
    return reasons


def _canonical_payload_reasons(record: Any) -> list[str]:
    if not isinstance(record, Mapping):
        return ["canonical_object"]
    expected_fields = {
        "contract_version",
        "memory_id",
        "state",
        "authority",
        "role_scope",
        "memory_kind",
        "title",
        "lesson",
        "applicability_conditions",
        "failure_conditions",
        "evidence_refs",
        "source_identity",
        "source_factor_verdict",
        "source_candidate_ref",
        "source_review_ref",
        "source_outcome_summary",
        "promotion_generation",
        "canonical_sha256",
    }
    reasons: list[str] = []
    if set(record) != expected_fields:
        reasons.append("canonical_fields")
    if record.get("contract_version") != CANONICAL_RECORD_CONTRACT_VERSION:
        reasons.append("canonical_contract_version")
    candidate_ref = record.get("source_candidate_ref")
    reasons.extend(
        _portable_reference_reasons(
            candidate_ref,
            label="canonical_candidate_ref",
            id_field="candidate_id",
        )
    )
    expected_memory_id = f"memory_{str((candidate_ref or {}).get('sha256') or '')[:24]}"
    if record.get("memory_id") != expected_memory_id:
        reasons.append("canonical_memory_id")
    if record.get("state") != "canonical":
        reasons.append("canonical_state")
    if record.get("authority") != "historical_advisory_only":
        reasons.append("canonical_authority")
    roles = record.get("role_scope")
    if (
        not isinstance(roles, list)
        or not roles
        or len(set(str(role) for role in roles)) != len(roles)
        or any(not SAFE_ID_RE.fullmatch(str(role)) for role in roles)
    ):
        reasons.append("canonical_role_scope")
    if record.get("memory_kind") not in MEMORY_KINDS:
        reasons.append("canonical_memory_kind")
    for field, limit in (("title", 200), ("lesson", 2000)):
        value = record.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > limit
        ):
            reasons.append(f"canonical_{field}")
    for field in ("applicability_conditions", "failure_conditions"):
        values = record.get(field)
        if (
            not isinstance(values, list)
            or not values
            or len(values) > 12
            or any(
                not isinstance(item, str)
                or not item.strip()
                or item != item.strip()
                or len(item) > 500
                for item in values
            )
        ):
            reasons.append(f"canonical_{field}")
    evidence_refs = record.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs or len(evidence_refs) > 12:
        reasons.append("canonical_evidence_refs")
    else:
        for reference in evidence_refs:
            reasons.extend(
                _portable_reference_reasons(
                    reference,
                    label="canonical_evidence_ref",
                )
            )
    reasons.extend(
        _identity_shape_reasons(
            record.get("source_identity"),
            label="canonical_source_identity",
        )
    )
    if record.get("source_factor_verdict") not in FACTOR_VERDICTS:
        reasons.append("canonical_source_factor_verdict")
    outcome_summary = record.get("source_outcome_summary")
    if (
        not isinstance(outcome_summary, Mapping)
        or set(outcome_summary)
        != {
            "execution_status",
            "protocol_status",
            "factor_verdict",
            "council_status",
            "formal_proof_eligible",
            "organization_runtime_verified",
        }
        or outcome_summary.get("execution_status") != "COMPLETED"
        or outcome_summary.get("factor_verdict") not in {"ACCEPT", "REJECT"}
        or outcome_summary.get("factor_verdict")
        != record.get("source_factor_verdict")
        or type(outcome_summary.get("formal_proof_eligible")) is not bool
        or outcome_summary.get("organization_runtime_verified") is not True
        or (
            outcome_summary.get("factor_verdict") == "ACCEPT"
            and outcome_summary.get("formal_proof_eligible") is not True
        )
        or any(
            not isinstance(outcome_summary.get(field), str)
            or not outcome_summary.get(field)
            for field in ("protocol_status", "council_status")
        )
    ):
        reasons.append("canonical_source_outcome_summary")
    reasons.extend(
        _portable_reference_reasons(
            record.get("source_review_ref"),
            label="canonical_review_ref",
            id_field="review_id",
        )
    )
    generation = record.get("promotion_generation")
    if type(generation) is not int or generation < 1:
        reasons.append("canonical_promotion_generation")
    if _contains_absolute_path(record):
        reasons.append("canonical_absolute_path_disclosure")
    reasons.extend(
        validate_content_hash(record, hash_field="canonical_sha256", label="canonical")
    )
    return reasons


_TRANSACTION_INDEX = {
    "canonical": ("canonical_records", "memory_id", "canonical_sha256"),
    "review": ("reviews", "review_id", "review_sha256"),
    "outcome": ("outcome_events", "event_id", "event_sha256"),
}


def _transaction_reasons(transaction: Any) -> list[str]:
    if not isinstance(transaction, Mapping):
        return ["transaction_object"]
    expected_fields = {
        "contract_version",
        "transaction_id",
        "kind",
        "expected_manifest_sha256",
        "expected_generation",
        "next_generation",
        "target_path",
        "target_sha256",
        "index_entry",
        "transaction_sha256",
    }
    reasons: list[str] = []
    if set(transaction) != expected_fields:
        reasons.append("transaction_fields")
    if transaction.get("contract_version") != STORE_TRANSACTION_CONTRACT_VERSION:
        reasons.append("transaction_contract_version")
    kind = str(transaction.get("kind") or "")
    if kind not in _TRANSACTION_INDEX:
        reasons.append("transaction_kind")
        return reasons
    list_field, id_field, _hash_field = _TRANSACTION_INDEX[kind]
    index_entry = transaction.get("index_entry")
    reasons.extend(_validate_index_reference(index_entry, kind=kind))
    identifier = (
        str(index_entry.get(id_field) or "")
        if isinstance(index_entry, Mapping)
        else ""
    )
    expected_id = f"transaction_{kind}_{identifier}"
    if transaction.get("transaction_id") != expected_id:
        reasons.append("transaction_id")
    if not SHA256_RE.fullmatch(str(transaction.get("expected_manifest_sha256") or "")):
        reasons.append("transaction_expected_manifest_sha256")
    expected_generation = transaction.get("expected_generation")
    next_generation = transaction.get("next_generation")
    if (
        type(expected_generation) is not int
        or expected_generation < 0
        or type(next_generation) is not int
        or next_generation != expected_generation + 1
    ):
        reasons.append("transaction_generation")
    if (
        not isinstance(index_entry, Mapping)
        or transaction.get("target_path") != index_entry.get("path")
        or transaction.get("target_sha256") != index_entry.get("sha256")
    ):
        reasons.append("transaction_target_binding")
    try:
        _safe_store_relative(str(transaction.get("target_path") or ""))
    except ResearchOrganizationError:
        reasons.append("transaction_target_path")
    if not SHA256_RE.fullmatch(str(transaction.get("target_sha256") or "")):
        reasons.append("transaction_target_sha256")
    if list_field not in {"canonical_records", "reviews", "outcome_events"}:
        reasons.append("transaction_index_field")
    reasons.extend(
        validate_content_hash(
            transaction,
            hash_field="transaction_sha256",
            label="transaction",
        )
    )
    return reasons


def _transaction_target_matches(
    resolved: Path,
    transaction: Mapping[str, Any],
) -> bool:
    kind = str(transaction["kind"])
    _list_field, _id_field, hash_field = _TRANSACTION_INDEX[kind]
    payload = _read_store_json(resolved, str(transaction["target_path"]))
    return bool(
        payload.get(hash_field) == transaction.get("target_sha256")
        and not validate_content_hash(payload, hash_field=hash_field, label=kind)
    )


def _recover_store_temp_files_locked(resolved: Path) -> None:
    temporary_root = resolved / _TEMP_DIR_NAME
    try:
        directory_metadata = temporary_root.lstat()
        entries = sorted(temporary_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        _raise(BLOCK_MEMORY_STORE_INVALID, f"temporary_directory:{exc}")
    if (
        stat.S_ISLNK(directory_metadata.st_mode)
        or not stat.S_ISDIR(directory_metadata.st_mode)
        or directory_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(directory_metadata.st_mode) != _PRIVATE_DIR_MODE
    ):
        _raise(BLOCK_MEMORY_STORE_INVALID, "temporary_directory")
    for path in entries:
        try:
            metadata = path.lstat()
        except OSError as exc:
            _raise(BLOCK_MEMORY_STORE_INVALID, f"temporary_unreadable:{exc}")
        if (
            not _TEMP_FILE_RE.fullmatch(path.name)
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
        ):
            _raise(BLOCK_MEMORY_STORE_INVALID, f"unsafe_temporary:{path.name}")
        _unlink_store_file(
            resolved,
            path.relative_to(resolved).as_posix(),
        )


def _recover_store_transactions_locked(
    resolved: Path,
    *,
    installation_id: str,
) -> None:
    _recover_store_temp_files_locked(resolved)
    transaction_root = resolved / "transactions"
    try:
        entries = sorted(transaction_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        _raise(BLOCK_MEMORY_STORE_INVALID, f"transaction_directory:{exc}")
    if len(entries) > 1:
        _raise(BLOCK_MEMORY_STORE_INVALID, "multiple_pending_transactions")
    for path in entries:
        try:
            metadata = path.lstat()
        except OSError as exc:
            _raise(BLOCK_MEMORY_STORE_INVALID, f"transaction_unreadable:{exc}")
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
        ):
            _raise(BLOCK_MEMORY_STORE_INVALID, f"unsafe_transaction:{path.name}")
        relative = path.relative_to(resolved).as_posix()
        transaction = _read_store_json(resolved, relative)
        reasons = _transaction_reasons(transaction)
        if reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
        if path.name != f"{transaction['transaction_id']}.json":
            _raise(BLOCK_MEMORY_STORE_INVALID, "transaction_path_binding")
        manifest = _read_store_json(resolved, _MANIFEST_NAME)
        manifest_reasons = _manifest_reasons(
            manifest,
            installation_id=installation_id,
        )
        if manifest_reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *manifest_reasons)
        kind = str(transaction["kind"])
        list_field, id_field, _hash_field = _TRANSACTION_INDEX[kind]
        index_entry = dict(transaction["index_entry"])
        identifier = str(index_entry[id_field])
        existing_ref = next(
            (
                item
                for item in manifest[list_field]
                if item.get(id_field) == identifier
            ),
            None,
        )
        target = resolved / str(transaction["target_path"])
        target_exists = target.exists() or target.is_symlink()
        manifest_is_parent = bool(
            manifest.get("manifest_sha256")
            == transaction.get("expected_manifest_sha256")
            and manifest.get("generation") == transaction.get("expected_generation")
        )
        if manifest_is_parent:
            if existing_ref is not None:
                _raise(BLOCK_MEMORY_STORE_INVALID, "transaction_parent_already_indexed")
            if not target_exists:
                _unlink_store_file(resolved, relative)
                continue
            if not _transaction_target_matches(resolved, transaction):
                _raise(BLOCK_MEMORY_STORE_INVALID, "transaction_target_mismatch")
            recovered = {
                **manifest,
                list_field: [*manifest[list_field], index_entry],
                "generation": int(transaction["next_generation"]),
            }
            recovered = with_content_hash(recovered, hash_field="manifest_sha256")
            _atomic_store_json(resolved, _MANIFEST_NAME, recovered, replace=True)
            _unlink_store_file(resolved, relative)
            continue
        if (
            manifest.get("generation") == transaction.get("next_generation")
            and existing_ref == index_entry
            and target_exists
            and _transaction_target_matches(resolved, transaction)
        ):
            _unlink_store_file(resolved, relative)
            continue
        _raise(BLOCK_MEMORY_STORE_INVALID, "transaction_state_diverged")


def _recover_and_read_manifest_locked(
    resolved: Path,
    *,
    installation_id: str,
) -> dict[str, Any]:
    _recover_store_transactions_locked(
        resolved,
        installation_id=installation_id,
    )
    manifest = _read_store_json(resolved, _MANIFEST_NAME)
    reasons = _manifest_reasons(
        manifest,
        installation_id=installation_id,
    )
    if reasons:
        _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
    return manifest


def _commit_indexed_payload_locked(
    resolved: Path,
    *,
    manifest: Mapping[str, Any],
    kind: str,
    identifier: str,
    target_relative: str,
    payload: Mapping[str, Any],
    index_entry: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    list_field, id_field, hash_field = _TRANSACTION_INDEX[kind]
    expected_index = dict(index_entry)
    if (
        expected_index.get(id_field) != identifier
        or expected_index.get("path") != target_relative
        or expected_index.get("sha256") != payload.get(hash_field)
        or _validate_index_reference(expected_index, kind=kind)
    ):
        _raise(BLOCK_MEMORY_STORE_INVALID, f"{kind}_index_entry")
    existing_ref = next(
        (
            item
            for item in manifest.get(list_field) or []
            if item.get(id_field) == identifier
        ),
        None,
    )
    if existing_ref is not None:
        if existing_ref != expected_index:
            _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"{kind}_index_conflict")
        existing_payload = _read_store_json(resolved, target_relative)
        if (
            existing_payload.get(hash_field) != payload.get(hash_field)
            or stable_json_hash(existing_payload) != stable_json_hash(dict(payload))
        ):
            _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"{kind}_payload_conflict")
        return dict(manifest), True
    target = resolved / _safe_store_relative(target_relative)
    if target.exists() or target.is_symlink():
        _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"unindexed_payload:{target_relative}")
    transaction_id = f"transaction_{kind}_{identifier}"
    transaction = with_content_hash(
        {
            "contract_version": STORE_TRANSACTION_CONTRACT_VERSION,
            "transaction_id": transaction_id,
            "kind": kind,
            "expected_manifest_sha256": manifest["manifest_sha256"],
            "expected_generation": int(manifest["generation"]),
            "next_generation": int(manifest["generation"]) + 1,
            "target_path": target_relative,
            "target_sha256": payload[hash_field],
            "index_entry": expected_index,
        },
        hash_field="transaction_sha256",
    )
    transaction_reasons = _transaction_reasons(transaction)
    if transaction_reasons:
        _raise(BLOCK_MEMORY_STORE_INVALID, *transaction_reasons)
    transaction_relative = f"transactions/{transaction_id}.json"
    _atomic_store_json(resolved, transaction_relative, transaction, replace=False)
    _atomic_store_json(resolved, target_relative, payload, replace=False)
    updated = {
        **manifest,
        list_field: [*manifest[list_field], expected_index],
        "generation": int(manifest["generation"]) + 1,
    }
    updated = with_content_hash(updated, hash_field="manifest_sha256")
    _atomic_store_json(resolved, _MANIFEST_NAME, updated, replace=True)
    _unlink_store_file(resolved, transaction_relative)
    return updated, False


def _validate_researcher_memory_store_unlocked(
    resolved: Path,
    *,
    installation_id: str,
) -> dict[str, Any]:
    manifest = _read_store_json(resolved, _MANIFEST_NAME)
    reasons = _manifest_reasons(manifest, installation_id=installation_id)
    review_trust_store: Any | None = None
    if manifest.get("reviews"):
        try:
            from factor_factory.research_org.runtime_trust import (
                load_runtime_trust_store,
            )

            review_trust_store = load_runtime_trust_store(
                resolved.parent / "research-org-trust",
                installation_id=installation_id,
            )
        except (OSError, ResearchOrganizationError) as exc:
            reasons.append(f"review_trust_store:{exc}")
    indexed_paths: set[str] = set()
    seen_outcome_identities: set[str] = set()
    loaded_payloads: dict[str, dict[str, dict[str, Any]]] = {
        "canonical": {},
        "review": {},
        "outcome": {},
    }
    indexes = (
        (
            "canonical",
            manifest.get("canonical_records") or [],
            "canonical",
            "canonical_sha256",
            CANONICAL_RECORD_CONTRACT_VERSION,
        ),
        (
            "review",
            manifest.get("reviews") or [],
            "reviews",
            "review_sha256",
            REVIEW_CONTRACT_VERSION,
        ),
        (
            "outcome",
            manifest.get("outcome_events") or [],
            "outcomes",
            "event_sha256",
            OUTCOME_EVENT_CONTRACT_VERSION,
        ),
    )
    for kind, references, directory, hash_field, contract_version in indexes:
        seen_ids: set[str] = set()
        id_field = {"canonical": "memory_id", "review": "review_id", "outcome": "event_id"}[kind]
        for reference in references:
            reasons.extend(_validate_index_reference(reference, kind=kind))
            if not isinstance(reference, dict):
                continue
            identifier = str(reference.get(id_field) or "")
            if not SAFE_ID_RE.fullmatch(identifier) or identifier in seen_ids:
                reasons.append(f"{kind}_reference_id")
            seen_ids.add(identifier)
            relative = str(reference.get("path") or "")
            if relative != f"{directory}/{identifier}.json":
                reasons.append(f"{kind}_reference_path_binding:{identifier}")
            if relative:
                indexed_paths.add(relative)
            try:
                payload = _read_store_json(resolved, relative)
            except ResearchOrganizationError as exc:
                reasons.append(str(exc))
                continue
            if payload.get(id_field) != identifier:
                reasons.append(f"{kind}_payload_id:{identifier}")
            loaded_payloads[kind][identifier] = payload
            if payload.get("contract_version") != contract_version:
                reasons.append(f"{kind}_payload_contract:{identifier}")
            if payload.get(hash_field) != reference.get("sha256") or validate_content_hash(
                payload,
                hash_field=hash_field,
                label=kind,
            ):
                reasons.append(f"{kind}_payload_hash:{identifier}")
            if kind == "review":
                semantic_reasons = _review_payload_reasons(
                    payload,
                    trust_store=review_trust_store,
                )
            else:
                semantic_reasons = {
                    "canonical": _canonical_payload_reasons,
                    "outcome": _outcome_payload_reasons,
                }[kind](payload)
            reasons.extend(
                f"{kind}_payload_semantic:{identifier}:{reason}"
                for reason in semantic_reasons
            )
            if kind == "canonical" and (
                reference.get("role_scope") != payload.get("role_scope")
                or reference.get("promoted_generation")
                != payload.get("promotion_generation")
            ):
                reasons.append(f"canonical_index_binding:{identifier}")
            elif kind == "review" and (
                reference.get("candidate_id")
                != (payload.get("candidate_ref") or {}).get("path", "").split("__")[-1].removesuffix(".json")
                or reference.get("decision") != payload.get("decision")
            ):
                reasons.append(f"review_index_binding:{identifier}")
            elif kind == "outcome":
                identity = payload.get("identity") or {}
                identity_key = stable_json_hash(identity) if isinstance(identity, Mapping) else ""
                if identity_key in seen_outcome_identities:
                    reasons.append(f"outcome_identity_duplicate:{identifier}")
                seen_outcome_identities.add(identity_key)
                if (
                    reference.get("factor_id") != identity.get("factor_id")
                    or reference.get("research_id") != identity.get("research_id")
                    or reference.get("report_id") != identity.get("report_id")
                    or reference.get("roles") != payload.get("roles")
                    or reference.get("factor_verdict")
                    != payload.get("factor_verdict")
                ):
                    reasons.append(f"outcome_index_binding:{identifier}")
                attestation = payload.get("host_attestation_ref") or {}
                attestation_id = str(attestation.get("id") or "")
                attestation_path = Path(attestation_id)
                if (
                    len(attestation_path.parts) != 3
                    or attestation_path.parts[:2]
                    != ("attestations", str(identity.get("job_id") or ""))
                    or not re.fullmatch(
                        r"attestation_[A-Za-z0-9_.-]+\.json",
                        attestation_path.name,
                    )
                ):
                    reasons.append(
                        f"outcome_attestation_path_binding:{identifier}"
                    )
                try:
                    observed_attestation = _read_store_bytes(
                        resolved.parent,
                        str(attestation.get("id") or ""),
                    )
                except ResearchOrganizationError as exc:
                    reasons.append(
                        f"outcome_attestation_readback:{identifier}:{exc}"
                    )
                else:
                    if hashlib.sha256(observed_attestation).hexdigest() != str(
                        attestation.get("sha256") or ""
                    ):
                        reasons.append(
                            f"outcome_attestation_readback:{identifier}:sha256"
                        )
                    reasons.extend(
                        f"outcome_attestation_semantic:{identifier}:{reason}"
                        for reason in _host_outcome_attestation_reasons(
                            observed_attestation,
                            event=payload,
                            state_root=resolved.parent,
                        )
                    )
        root_dir = resolved / directory
        try:
            directory_metadata = root_dir.lstat()
        except OSError:
            reasons.append(f"{kind}_directory")
        else:
            if (
                stat.S_ISLNK(directory_metadata.st_mode)
                or not stat.S_ISDIR(directory_metadata.st_mode)
                or directory_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(directory_metadata.st_mode) != _PRIVATE_DIR_MODE
            ):
                reasons.append(f"{kind}_directory")
            actual: set[str] = set()
            try:
                directory_entries = list(root_dir.iterdir())
            except OSError as exc:
                reasons.append(f"{kind}_directory_unreadable:{exc}")
                directory_entries = []
            for path in directory_entries:
                try:
                    metadata = path.lstat()
                except OSError as exc:
                    reasons.append(f"{kind}_entry_unreadable:{path.name}:{exc}")
                    continue
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
                ):
                    reasons.append(f"{kind}_unsafe_entry:{path.name}")
                    continue
                actual.add(path.relative_to(resolved).as_posix())
            expected_paths = {path for path in indexed_paths if path.startswith(f"{directory}/")}
            if actual != expected_paths:
                reasons.append(f"{kind}_directory_index")
    for memory_id, canonical in loaded_payloads["canonical"].items():
        review_ref = canonical.get("source_review_ref")
        review = (
            loaded_payloads["review"].get(str(review_ref.get("review_id") or ""))
            if isinstance(review_ref, Mapping)
            else None
        )
        if (
            review is None
            or review.get("review_sha256") != (review_ref or {}).get("sha256")
            or review.get("decision") != "APPROVE_CANONICAL"
            or review.get("canonical_write_authorized") is not True
        ):
            reasons.append(f"canonical_review_link:{memory_id}")
            continue
        candidate = review.get("candidate_snapshot")
        candidate_ref = canonical.get("source_candidate_ref")
        review_candidate_ref = review.get("candidate_ref")
        if (
            not isinstance(candidate, Mapping)
            or not isinstance(candidate_ref, Mapping)
            or not isinstance(review_candidate_ref, Mapping)
            or candidate_ref
            != {
                "candidate_id": candidate.get("candidate_id"),
                "sha256": candidate.get("candidate_sha256"),
            }
            or review_candidate_ref.get("sha256")
            != candidate.get("candidate_sha256")
            or canonical.get("source_identity") != candidate.get("identity")
            or canonical.get("role_scope") != candidate.get("role_scope")
            or canonical.get("memory_kind") != candidate.get("memory_kind")
            or canonical.get("title") != candidate.get("title")
            or canonical.get("lesson") != candidate.get("lesson")
            or canonical.get("applicability_conditions")
            != candidate.get("applicability_conditions")
            or canonical.get("failure_conditions")
            != candidate.get("failure_conditions")
            or canonical.get("evidence_refs") != candidate.get("evidence_refs")
        ):
            reasons.append(f"canonical_candidate_link:{memory_id}")
        outcome_ref = review.get("outcome_event_ref")
        outcome = (
            loaded_payloads["outcome"].get(str(outcome_ref.get("event_id") or ""))
            if isinstance(outcome_ref, Mapping)
            else None
        )
        expected_outcome_summary = (
            {
                "execution_status": outcome.get("execution_status"),
                "protocol_status": outcome.get("protocol_status"),
                "factor_verdict": outcome.get("factor_verdict"),
                "council_status": outcome.get("council_status"),
                "formal_proof_eligible": outcome.get("formal_proof_eligible"),
                "organization_runtime_verified": outcome.get(
                    "organization_runtime_verified"
                ),
            }
            if isinstance(outcome, Mapping)
            else None
        )
        if (
            outcome is None
            or outcome.get("event_sha256") != (outcome_ref or {}).get("sha256")
            or canonical.get("source_outcome_summary") != expected_outcome_summary
            or canonical.get("source_factor_verdict")
            != outcome.get("factor_verdict")
        ):
            reasons.append(f"canonical_outcome_link:{memory_id}")
    if type(manifest.get("generation")) is int and manifest["generation"] != sum(
        len(manifest.get(field) or [])
        for field in ("canonical_records", "reviews", "outcome_events")
    ):
        reasons.append("generation_event_count_mismatch")
    allowed_root_entries = {
        _MANIFEST_NAME,
        _LOCK_NAME,
        "canonical",
        "reviews",
        "outcomes",
        "transactions",
        _TEMP_DIR_NAME,
    }
    try:
        root_entries = {path.name for path in resolved.iterdir()}
    except OSError as exc:
        reasons.append(f"root_directory_unreadable:{exc}")
    else:
        if root_entries != allowed_root_entries:
            reasons.append("root_directory_index")
    transaction_root = resolved / "transactions"
    try:
        transaction_metadata = transaction_root.lstat()
        transaction_entries = list(transaction_root.iterdir())
    except OSError as exc:
        reasons.append(f"transaction_directory:{exc}")
    else:
        if (
            stat.S_ISLNK(transaction_metadata.st_mode)
            or not stat.S_ISDIR(transaction_metadata.st_mode)
            or transaction_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(transaction_metadata.st_mode) != _PRIVATE_DIR_MODE
            or transaction_entries
        ):
            reasons.append("transaction_directory")
    temporary_root = resolved / _TEMP_DIR_NAME
    try:
        temporary_metadata = temporary_root.lstat()
        temporary_entries = list(temporary_root.iterdir())
    except OSError as exc:
        reasons.append(f"temporary_directory:{exc}")
    else:
        if (
            stat.S_ISLNK(temporary_metadata.st_mode)
            or not stat.S_ISDIR(temporary_metadata.st_mode)
            or temporary_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(temporary_metadata.st_mode) != _PRIVATE_DIR_MODE
            or temporary_entries
        ):
            reasons.append("temporary_directory")
    lock_path = resolved / _LOCK_NAME
    try:
        lock_metadata = lock_path.lstat()
    except OSError:
        reasons.append("store_lock")
    else:
        if (
            stat.S_ISLNK(lock_metadata.st_mode)
            or not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_uid != os.geteuid()
            or lock_metadata.st_nlink != 1
            or stat.S_IMODE(lock_metadata.st_mode) != _PRIVATE_FILE_MODE
        ):
            reasons.append("store_lock")
    if reasons:
        _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
    return {
        "verdict": "PASS",
        "store_id": manifest["store_id"],
        "generation": manifest["generation"],
        "canonical_record_count": len(manifest["canonical_records"]),
        "review_count": len(manifest["reviews"]),
        "outcome_event_count": len(manifest["outcome_events"]),
        "manifest_sha256": manifest["manifest_sha256"],
    }


def validate_researcher_memory_store(
    root: Path,
    *,
    installation_id: str,
    repo_root: Path | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=workspace,
        create=False,
    )
    with _store_lock(resolved, create=False):
        _recover_store_transactions_locked(
            resolved,
            installation_id=installation_id,
        )
        return _validate_researcher_memory_store_unlocked(
            resolved,
            installation_id=installation_id,
        )


def _identity_projection(identity: Mapping[str, Any]) -> dict[str, str]:
    output = {
        key: str(identity.get(key) or "")
        for key in ("factor_id", "research_id", "report_id", "job_id")
    }
    invalid = [key for key, value in output.items() if not SAFE_ID_RE.fullmatch(value)]
    if invalid:
        _raise(BLOCK_MEMORY_SNAPSHOT_INVALID, *[f"identity.{key}" for key in invalid])
    return output


def _role_projection(role: Mapping[str, Any]) -> dict[str, Any]:
    role_id = str(role.get("role_id") or "")
    if not SAFE_ID_RE.fullmatch(role_id):
        _raise(BLOCK_MEMORY_SNAPSHOT_INVALID, "role_id")
    projection = {
        "role_id": role_id,
        "capability_tags": list(role.get("capability_tags") or []),
        "required_skills": list(role.get("required_skills") or []),
        "model_policy": str(role.get("model_policy") or ""),
        "independence_class": str(role.get("independence_class") or ""),
    }
    projection["role_contract_sha256"] = stable_json_hash(projection)
    return projection


def _scorecard(events: Sequence[Mapping[str, Any]], *, role_id: str) -> dict[str, Any]:
    selected = [event for event in events if role_id in (event.get("roles") or [])]
    factor_counts = Counter(str(event.get("factor_verdict") or "UNKNOWN") for event in selected)
    protocol_counts = Counter(str(event.get("protocol_status") or "UNKNOWN") for event in selected)
    return {
        "outcome_event_count": len(selected),
        "factor_verdict_counts": dict(sorted(factor_counts.items())),
        "protocol_status_counts": dict(sorted(protocol_counts.items())),
        "formal_proof_eligible_count": sum(
            1 for event in selected if event.get("formal_proof_eligible") is True
        ),
        "interpretation_guard": "protocol PASS is not factor ACCEPT",
    }


def build_role_memory_snapshots(
    root: Path,
    *,
    installation_id: str,
    identity: Mapping[str, Any],
    roles: Sequence[Mapping[str, Any]],
    repo_root: Path,
    workspace: Path,
) -> dict[str, dict[str, Any]]:
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=workspace,
        create=True,
    )
    ensure_researcher_memory_store(
        resolved,
        installation_id=installation_id,
        repo_root=repo_root,
        workspace=workspace,
    )
    frozen_identity = _identity_projection(identity)
    with _store_lock(resolved):
        _recover_store_transactions_locked(
            resolved,
            installation_id=installation_id,
        )
        _validate_researcher_memory_store_unlocked(
            resolved,
            installation_id=installation_id,
        )
        manifest = _read_store_json(resolved, _MANIFEST_NAME)
        reasons = _manifest_reasons(manifest, installation_id=installation_id)
        if reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *reasons)
        canonical_records = [
            _read_store_json(resolved, str(reference["path"]))
            for reference in manifest["canonical_records"]
        ]
        outcomes = [
            _read_store_json(resolved, str(reference["path"]))
            for reference in manifest["outcome_events"]
        ]
        semantic_reasons = [
            *(
                reason
                for record in canonical_records
                for reason in _canonical_payload_reasons(record)
            ),
            *(
                reason
                for event in outcomes
                for reason in _outcome_payload_reasons(event)
            ),
        ]
        if semantic_reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *semantic_reasons)
        snapshots: dict[str, dict[str, Any]] = {}
        for raw_role in roles:
            role = _role_projection(raw_role)
            role_id = role["role_id"]
            applicable = [
                record
                for record in canonical_records
                if role_id in (record.get("role_scope") or [])
                or "shared" in (record.get("role_scope") or [])
            ]
            applicable.sort(
                key=lambda record: (
                    -int(record.get("promotion_generation") or 0),
                    str(record.get("memory_id") or ""),
                )
            )
            applicable = applicable[:MAX_CANONICAL_RECORDS_PER_SNAPSHOT]
            payload = with_content_hash(
                {
                    "contract_version": ROLE_SNAPSHOT_CONTRACT_VERSION,
                    "store_id": manifest["store_id"],
                    "source_generation": manifest["generation"],
                    "source_manifest_sha256": manifest["manifest_sha256"],
                    "identity": frozen_identity,
                    "role": role,
                    "authority": "historical_advisory_only",
                    "cold_start": not applicable and not any(
                        role_id in (event.get("roles") or []) for event in outcomes
                    ),
                    "canonical_memories": applicable,
                    "performance_scorecard": _scorecard(outcomes, role_id=role_id),
                    "policy": {
                        "canonical_records_only": True,
                        "current_factor_inference_allowed": False,
                        "self_modification_allowed": False,
                        "candidate_writeback_only": True,
                        "candidate_self_promotion_allowed": False,
                        "economic_hypothesis_and_math_mechanism_remain_authoritative": True,
                    },
                },
                hash_field="snapshot_sha256",
            )
            snapshots[role_id] = payload
        return snapshots


def _contains_absolute_path(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_absolute_path(item)
            for key, item in value.items()
            if key not in {"signature", "value_b64", "public_key_b64"}
        )
    if isinstance(value, list):
        return any(_contains_absolute_path(item) for item in value)
    return isinstance(value, str) and (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value) is not None)


def validate_role_memory_snapshot(
    snapshot: Any,
    *,
    expected_identity: Mapping[str, Any],
    expected_role_id: str,
) -> list[str]:
    if not isinstance(snapshot, dict):
        return [f"{BLOCK_MEMORY_SNAPSHOT_INVALID}:object"]
    expected_fields = {
        "contract_version",
        "store_id",
        "source_generation",
        "source_manifest_sha256",
        "identity",
        "role",
        "authority",
        "cold_start",
        "canonical_memories",
        "performance_scorecard",
        "policy",
        "snapshot_sha256",
    }
    reasons: list[str] = []
    if set(snapshot) != expected_fields:
        reasons.append("fields")
    if snapshot.get("contract_version") != ROLE_SNAPSHOT_CONTRACT_VERSION:
        reasons.append("contract_version")
    if snapshot.get("identity") != _identity_projection(expected_identity):
        reasons.append("identity")
    role = snapshot.get("role")
    if not isinstance(role, dict) or role.get("role_id") != expected_role_id:
        reasons.append("role")
    if snapshot.get("authority") != "historical_advisory_only":
        reasons.append("authority")
    if type(snapshot.get("source_generation")) is not int:
        reasons.append("source_generation")
    if not isinstance(snapshot.get("source_manifest_sha256"), str) or not SHA256_RE.fullmatch(
        str(snapshot.get("source_manifest_sha256") or "")
    ):
        reasons.append("source_manifest_sha256")
    if not isinstance(snapshot.get("canonical_memories"), list):
        reasons.append("canonical_memories")
    if _contains_absolute_path(snapshot):
        reasons.append("absolute_path_disclosure")
    reasons.extend(validate_content_hash(snapshot, hash_field="snapshot_sha256", label="snapshot"))
    return [f"{BLOCK_MEMORY_SNAPSHOT_INVALID}:{reason}" for reason in reasons]


def build_snapshot_binding(
    *,
    role_snapshot_refs: Mapping[str, Mapping[str, Any]],
    snapshots: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    role_ids = list(role_snapshot_refs)
    if set(role_ids) != set(snapshots):
        _raise(BLOCK_MEMORY_SNAPSHOT_INVALID, "role_snapshot_coverage")
    store_ids = {str(snapshots[role_id].get("store_id") or "") for role_id in role_ids}
    generations = {int(snapshots[role_id].get("source_generation") or 0) for role_id in role_ids}
    manifests = {
        str(snapshots[role_id].get("source_manifest_sha256") or "") for role_id in role_ids
    }
    if len(store_ids) != 1 or len(generations) != 1 or len(manifests) != 1:
        _raise(BLOCK_MEMORY_SNAPSHOT_INVALID, "snapshot_source_inconsistent")
    return {
        "contract_version": SNAPSHOT_BINDING_CONTRACT_VERSION,
        "mode": "enabled",
        "store_id": next(iter(store_ids)),
        "source_generation": next(iter(generations)),
        "source_manifest_sha256": next(iter(manifests)),
        "role_snapshot_refs": {
            role_id: dict(role_snapshot_refs[role_id]) for role_id in role_ids
        },
        "canonical_write_authority": "host_review_only",
        "agent_write_authority": "workspace_candidate_only",
    }


def validate_snapshot_binding(
    binding: Any,
    *,
    required_role_ids: Sequence[str],
) -> list[str]:
    if not isinstance(binding, dict):
        return [f"{BLOCK_MEMORY_SNAPSHOT_INVALID}:binding_object"]
    expected_fields = {
        "contract_version",
        "mode",
        "store_id",
        "source_generation",
        "source_manifest_sha256",
        "role_snapshot_refs",
        "canonical_write_authority",
        "agent_write_authority",
    }
    reasons: list[str] = []
    if set(binding) != expected_fields:
        reasons.append("binding_fields")
    if binding.get("contract_version") != SNAPSHOT_BINDING_CONTRACT_VERSION:
        reasons.append("binding_contract_version")
    if binding.get("mode") != "enabled":
        reasons.append("binding_mode")
    if binding.get("canonical_write_authority") != "host_review_only":
        reasons.append("canonical_write_authority")
    if binding.get("agent_write_authority") != "workspace_candidate_only":
        reasons.append("agent_write_authority")
    refs = binding.get("role_snapshot_refs")
    if not isinstance(refs, dict) or set(refs) != set(required_role_ids):
        reasons.append("role_snapshot_refs")
    else:
        for role_id, reference in refs.items():
            if (
                not isinstance(reference, dict)
                or set(reference) != {"path", "sha256", "hash_kind"}
                or reference.get("hash_kind") != "json_content"
                or not SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
                or not str(reference.get("path") or "").endswith(
                    f"/memory_snapshots/{role_id}.json"
                )
            ):
                reasons.append(f"role_snapshot_ref:{role_id}")
    return [f"{BLOCK_MEMORY_SNAPSHOT_INVALID}:{reason}" for reason in reasons]


def task_memory_snapshot(
    *,
    workspace: Path,
    task: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    role_id = str(task.get("role_id") or "")
    role_memory = task.get("role_memory")
    if role_memory is None:
        return None, None
    if (
        not isinstance(role_memory, Mapping)
        or role_memory.get("required") is not True
        or role_memory.get("learning_output_contract") != CANDIDATE_CONTRACT_VERSION
        or role_memory.get("canonical_write_allowed") is not False
        or not isinstance(role_memory.get("snapshot_ref"), Mapping)
    ):
        _raise(BLOCK_MEMORY_SNAPSHOT_INVALID, "task_role_memory_contract")
    reference = dict(role_memory["snapshot_ref"])
    relative = normalize_workspace_relative_path(
        reference.get("path"), workspace=workspace, label="researcher_memory_snapshot"
    )
    snapshot = read_workspace_json(workspace, relative)
    reasons = validate_role_memory_snapshot(
        snapshot,
        expected_identity=task.get("identity") or {},
        expected_role_id=role_id,
    )
    if (
        reference.get("hash_kind") != "json_content"
        or reference.get("sha256") != snapshot.get("snapshot_sha256")
    ):
        reasons.append(f"{BLOCK_MEMORY_SNAPSHOT_INVALID}:task_snapshot_ref")
    if reasons:
        _raise(BLOCK_MEMORY_SNAPSHOT_INVALID, *reasons)
    return reference, dict(snapshot)


def _proposal_reasons(
    proposal: Any,
    *,
    authorized_evidence: set[tuple[str, str]],
) -> list[str]:
    if not isinstance(proposal, dict):
        return ["proposal_object"]
    expected = {
        "memory_kind",
        "title",
        "lesson",
        "applicability_conditions",
        "failure_conditions",
        "evidence_refs",
    }
    reasons: list[str] = []
    if set(proposal) != expected:
        reasons.append("proposal_fields")
    if _contains_absolute_path(proposal):
        reasons.append("absolute_path_disclosure")
    if proposal.get("memory_kind") not in MEMORY_KINDS:
        reasons.append("memory_kind")
    for field, limit in (("title", 200), ("lesson", 2000)):
        value = proposal.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            reasons.append(field)
    for field in ("applicability_conditions", "failure_conditions"):
        values = proposal.get(field)
        if (
            not isinstance(values, list)
            or not values
            or len(values) > 12
            or any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in values)
        ):
            reasons.append(field)
    evidence = proposal.get("evidence_refs")
    if not isinstance(evidence, list) or not evidence or len(evidence) > 12:
        reasons.append("evidence_refs")
    else:
        observed: set[tuple[str, str]] = set()
        for reference in evidence:
            if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
                reasons.append("evidence_ref_contract")
                continue
            key = (str(reference.get("path") or ""), str(reference.get("sha256") or ""))
            if key in observed or key not in authorized_evidence:
                reasons.append("evidence_ref_authority")
            observed.add(key)
    return reasons


def materialize_learning_candidates(
    *,
    workspace: Path,
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    proposals: Any,
    runtime_provenance: Mapping[str, Any] | None = None,
    trust_store: Any | None = None,
) -> dict[str, Any]:
    snapshot_ref, snapshot = task_memory_snapshot(workspace=workspace, task=task)
    if snapshot is None:
        return {
            "candidate_refs": [],
            "rejections": (["memory_not_enabled"] if proposals else []),
        }
    if proposals is None:
        proposals = []
    if not isinstance(proposals, list):
        return {"candidate_refs": [], "rejections": ["proposal_list_required"]}
    if len(proposals) > MAX_LEARNING_CANDIDATES_PER_RESULT:
        return {"candidate_refs": [], "rejections": ["proposal_limit"]}
    if proposals and (
        not isinstance(runtime_provenance, Mapping)
        or set(runtime_provenance)
        != {"adapter_receipt", "host_admission_receipt"}
        or not all(
            isinstance(runtime_provenance.get(field), Mapping)
            for field in ("adapter_receipt", "host_admission_receipt")
        )
    ):
        return {
            "candidate_refs": [],
            "rejections": ["source_runtime_provenance_missing_or_invalid"],
        }
    if proposals and trust_store is None:
        return {
            "candidate_refs": [],
            "rejections": ["candidate_materialization_trust_missing"],
        }
    public_record = result.get("public_research_record")
    artifact_refs = public_record.get("artifact_refs") if isinstance(public_record, Mapping) else []
    authorized = {
        (str(reference.get("path") or ""), str(reference.get("sha256") or ""))
        for reference in artifact_refs or []
        if isinstance(reference, Mapping)
    }
    candidate_refs: list[dict[str, str]] = []
    rejections: list[str] = []
    identity = _identity_projection(result.get("identity") or {})
    role_id = str(result.get("role_id") or "")
    for index, proposal in enumerate(proposals):
        reasons = _proposal_reasons(proposal, authorized_evidence=authorized)
        if reasons:
            rejections.extend(f"proposal_{index}:{reason}" for reason in reasons)
            continue
        core = {
            "identity": identity,
            "source_role_id": role_id,
            "source_task_ref": dict(result["task_ref"]),
            "source_result_ref": {
                "path": str(task["expected_result_path"]),
                "sha256": str(result["result_sha256"]),
            },
            "source_session_id": str(result["session_id"]),
            "source_runtime_provenance": {
                "adapter_receipt": dict(runtime_provenance["adapter_receipt"]),
                "host_admission_receipt": dict(
                    runtime_provenance["host_admission_receipt"]
                ),
            },
            "source_memory_snapshot_ref": {
                "path": str(snapshot_ref["path"]),
                "sha256": str(snapshot_ref["sha256"]),
                "store_id": str(snapshot["store_id"]),
                "source_generation": int(snapshot["source_generation"]),
                "snapshot_sha256": str(snapshot["snapshot_sha256"]),
            },
            "role_scope": [role_id],
            "memory_kind": proposal["memory_kind"],
            "title": proposal["title"].strip(),
            "lesson": proposal["lesson"].strip(),
            "applicability_conditions": [item.strip() for item in proposal["applicability_conditions"]],
            "failure_conditions": [item.strip() for item in proposal["failure_conditions"]],
            "evidence_refs": [dict(item) for item in proposal["evidence_refs"]],
            "authority": "candidate_only",
            "promotion_allowed": False,
        }
        candidate_id = f"candidate_{stable_json_hash(core)[:24]}"
        candidate = with_content_hash(
            {
                "contract_version": CANDIDATE_CONTRACT_VERSION,
                "candidate_id": candidate_id,
                **core,
            },
            hash_field="candidate_sha256",
        )
        relative = (
            f"objects/research_organization/{identity['report_id']}"
            f"/memory_candidates/{role_id}__{candidate_id}.json"
        )
        provenance = candidate["source_runtime_provenance"]
        adapter_receipt = provenance["adapter_receipt"]
        host_receipt = provenance["host_admission_receipt"]
        materialization_receipt = trust_store.sign(
            "host_admission",
            {
                "receipt_type": (
                    "RESEARCHER_MEMORY_CANDIDATE_MATERIALIZED"
                ),
                "identity": dict(candidate["identity"]),
                "bindings": {
                    "candidate_ref": {
                        "path": relative,
                        "sha256": candidate["candidate_sha256"],
                    },
                    "source_task_ref": dict(candidate["source_task_ref"]),
                    "source_result_ref": dict(candidate["source_result_ref"]),
                    "source_memory_snapshot_ref": dict(
                        candidate["source_memory_snapshot_ref"]
                    ),
                    "source_session_id": candidate["source_session_id"],
                    "source_private_output_sha256": adapter_receipt[
                        "outcome"
                    ]["private_output_sha256"],
                    "source_adapter_receipt_id": adapter_receipt[
                        "receipt_id"
                    ],
                    "source_host_admission_receipt_id": host_receipt[
                        "receipt_id"
                    ],
                },
                "outcome": {
                    "authority": "candidate_only",
                    "promotion_allowed": False,
                },
            },
        )
        candidate = {
            **candidate,
            "materialization_receipt": materialization_receipt,
        }
        candidate_reasons = validate_memory_candidate(
            candidate,
            task=task,
            result=result,
            trust_store=trust_store,
        )
        if candidate_reasons:
            rejections.extend(
                f"proposal_{index}:{reason}" for reason in candidate_reasons
            )
            continue
        try:
            write_workspace_json_once(workspace, relative, candidate)
        except FileExistsError:
            existing = read_workspace_json(workspace, relative)
            if stable_json_hash(existing) != stable_json_hash(candidate):
                _raise(BLOCK_MEMORY_WRITE_CONFLICT, f"candidate_conflict:{relative}")
        candidate_refs.append(
            {"path": relative, "sha256": candidate["candidate_sha256"]}
        )
    return {"candidate_refs": candidate_refs, "rejections": rejections}


def validate_memory_candidate(
    candidate: Any,
    *,
    task: Mapping[str, Any],
    result: Mapping[str, Any],
    trust_store: Any | None = None,
) -> list[str]:
    if not isinstance(candidate, dict):
        return [f"{BLOCK_MEMORY_CANDIDATE_INVALID}:object"]
    expected_fields = {
        "contract_version",
        "candidate_id",
        "identity",
        "source_role_id",
        "source_task_ref",
        "source_result_ref",
        "source_session_id",
        "source_runtime_provenance",
        "source_memory_snapshot_ref",
        "role_scope",
        "memory_kind",
        "title",
        "lesson",
        "applicability_conditions",
        "failure_conditions",
        "evidence_refs",
        "authority",
        "promotion_allowed",
        "materialization_receipt",
        "candidate_sha256",
    }
    reasons: list[str] = []
    if set(candidate) != expected_fields:
        reasons.append("fields")
    if candidate.get("contract_version") != CANDIDATE_CONTRACT_VERSION:
        reasons.append("contract_version")
    if candidate.get("identity") != result.get("identity"):
        reasons.append("identity")
    if candidate.get("source_role_id") != result.get("role_id"):
        reasons.append("source_role_id")
    if candidate.get("source_task_ref") != result.get("task_ref"):
        reasons.append("source_task_ref")
    if candidate.get("source_result_ref") != {
        "path": task.get("expected_result_path"),
        "sha256": result.get("result_sha256"),
    }:
        reasons.append("source_result_ref")
    if candidate.get("source_session_id") != result.get("session_id"):
        reasons.append("source_session_id")
    reasons.extend(
        _source_runtime_provenance_reasons(
            candidate.get("source_runtime_provenance"),
            candidate=candidate,
            task=task,
            result=result,
            trust_store=trust_store,
        )
    )
    reasons.extend(
        _candidate_materialization_receipt_reasons(
            candidate.get("materialization_receipt"),
            candidate=candidate,
            trust_store=trust_store,
        )
    )
    source_snapshot = candidate.get("source_memory_snapshot_ref")
    task_role_memory = task.get("role_memory")
    task_snapshot_ref = (
        task_role_memory.get("snapshot_ref")
        if isinstance(task_role_memory, Mapping)
        else None
    )
    if (
        not isinstance(source_snapshot, Mapping)
        or not isinstance(task_snapshot_ref, Mapping)
        or set(source_snapshot)
        != {
            "path",
            "sha256",
            "store_id",
            "source_generation",
            "snapshot_sha256",
        }
        or source_snapshot.get("path") != task_snapshot_ref.get("path")
        or source_snapshot.get("sha256") != task_snapshot_ref.get("sha256")
        or source_snapshot.get("snapshot_sha256") != task_snapshot_ref.get("sha256")
        or not isinstance(source_snapshot.get("store_id"), str)
        or not source_snapshot.get("store_id")
        or type(source_snapshot.get("source_generation")) is not int
        or int(source_snapshot.get("source_generation")) < 0
    ):
        reasons.append("source_memory_snapshot_ref")
    if candidate.get("role_scope") != [result.get("role_id")]:
        reasons.append("role_scope")
    if candidate.get("authority") != "candidate_only" or candidate.get("promotion_allowed") is not False:
        reasons.append("authority")
    if candidate.get("memory_kind") not in MEMORY_KINDS:
        reasons.append("memory_kind")
    authorized = {
        (str(reference.get("path") or ""), str(reference.get("sha256") or ""))
        for reference in (result.get("public_research_record") or {}).get("artifact_refs") or []
        if isinstance(reference, Mapping)
    }
    reasons.extend(_proposal_reasons(
        {
            key: candidate.get(key)
            for key in (
                "memory_kind",
                "title",
                "lesson",
                "applicability_conditions",
                "failure_conditions",
                "evidence_refs",
            )
        },
        authorized_evidence=authorized,
    ))
    core = {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "contract_version",
            "candidate_id",
            "candidate_sha256",
            "materialization_receipt",
        }
    }
    if candidate.get("candidate_id") != f"candidate_{stable_json_hash(core)[:24]}":
        reasons.append("candidate_id_content_binding")
    if _contains_absolute_path(candidate):
        reasons.append("absolute_path_disclosure")
    reasons.extend(_candidate_content_hash_reasons(candidate))
    return [f"{BLOCK_MEMORY_CANDIDATE_INVALID}:{reason}" for reason in reasons]


def _load_admitted_candidate_sources(
    *,
    workspace: Path,
    candidate_relative: str,
    trust_store: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from factor_factory.research_org.director import (
        validate_research_organization_bundle,
    )

    try:
        validate_research_organization_bundle(
            workspace=workspace,
            review_trust_root=(
                trust_store.root if trust_store is not None else None
            ),
            review_installation_id=(
                trust_store.installation_id if trust_store is not None else None
            ),
        )
    except ResearchOrganizationError as exc:
        _raise(
            BLOCK_MEMORY_CANDIDATE_INVALID,
            f"research_organization_bundle_not_admitted:{exc.token}",
        )
    relative = normalize_workspace_relative_path(
        candidate_relative,
        workspace=workspace,
        label="memory_candidate",
    )
    try:
        candidate = read_workspace_json(workspace, relative)
    except ResearchOrganizationError as exc:
        _raise(
            BLOCK_MEMORY_CANDIDATE_INVALID,
            f"candidate_not_admitted:{exc.token}",
        )
    identity = candidate.get("identity") if isinstance(candidate, Mapping) else {}
    report_id = str((identity or {}).get("report_id") or "")
    source_task_ref = (
        candidate.get("source_task_ref") if isinstance(candidate, Mapping) else None
    )
    if (
        not SAFE_ID_RE.fullmatch(report_id)
        or not isinstance(source_task_ref, Mapping)
        or set(source_task_ref) != {"task_id", "sha256"}
        or not SAFE_ID_RE.fullmatch(str(source_task_ref.get("task_id") or ""))
        or not SHA256_RE.fullmatch(str(source_task_ref.get("sha256") or ""))
    ):
        _raise(BLOCK_MEMORY_CANDIDATE_INVALID, "source_task_ref")
    task_relative = (
        f"objects/research_organization/{report_id}/tasks/"
        f"{source_task_ref['task_id']}.json"
    )
    try:
        task = read_workspace_json(workspace, task_relative)
    except ResearchOrganizationError as exc:
        _raise(
            BLOCK_MEMORY_CANDIDATE_INVALID,
            f"source_task_not_admitted:{exc.token}",
        )
    if (
        task.get("task_id") != source_task_ref.get("task_id")
        or task.get("task_sha256") != source_task_ref.get("sha256")
        or validate_content_hash(task, hash_field="task_sha256", label="task")
    ):
        _raise(BLOCK_MEMORY_CANDIDATE_INVALID, "source_task_not_admitted")
    source_result_ref = candidate.get("source_result_ref")
    if (
        not isinstance(source_result_ref, Mapping)
        or set(source_result_ref) != {"path", "sha256"}
    ):
        _raise(BLOCK_MEMORY_CANDIDATE_INVALID, "source_result_ref")
    result_relative = normalize_workspace_relative_path(
        source_result_ref.get("path"),
        workspace=workspace,
        label="memory_candidate.source_result_ref",
    )
    try:
        result = read_workspace_json(workspace, result_relative)
    except ResearchOrganizationError as exc:
        _raise(
            BLOCK_MEMORY_CANDIDATE_INVALID,
            f"source_result_not_admitted:{exc.token}",
        )
    if (
        result_relative != task.get("expected_result_path")
        or result.get("contract_version") != "factorforge_agent_result_v1"
        or result.get("result_sha256") != source_result_ref.get("sha256")
        or validate_content_hash(result, hash_field="result_sha256", label="result")
    ):
        _raise(BLOCK_MEMORY_CANDIDATE_INVALID, "source_result_not_admitted")
    candidate_reasons = validate_memory_candidate(
        candidate,
        task=task,
        result=result,
        trust_store=trust_store,
    )
    if candidate_reasons:
        _raise(BLOCK_MEMORY_CANDIDATE_INVALID, *candidate_reasons)
    expected_candidate = (
        f"objects/research_organization/{report_id}/memory_candidates/"
        f"{candidate['source_role_id']}__{candidate['candidate_id']}.json"
    )
    if relative != expected_candidate:
        _raise(BLOCK_MEMORY_CANDIDATE_INVALID, "candidate_path_binding")
    for reference in candidate.get("evidence_refs") or []:
        evidence_relative = normalize_workspace_relative_path(
            reference.get("path"),
            workspace=workspace,
            label="memory_candidate.evidence_ref",
        )
        evidence_path = workspace / evidence_relative
        if (
            not evidence_path.is_file()
            or evidence_path.is_symlink()
            or sha256_file(evidence_path) != reference.get("sha256")
        ):
            _raise(BLOCK_MEMORY_CANDIDATE_INVALID, "evidence_not_admitted")
    return candidate, task, result


def validate_candidate_review(
    review: Any,
    *,
    candidate: Mapping[str, Any],
    trust_store: Any | None = None,
) -> list[str]:
    if not isinstance(review, dict):
        return [f"{BLOCK_MEMORY_REVIEW_INVALID}:object"]
    expected_fields = {
        "contract_version",
        "review_id",
        "identity",
        "candidate_ref",
        "candidate_snapshot",
        "decision",
        "reviewer",
        "review_session_receipt",
        "reviewer_attestation",
        "outcome_event_ref",
        "rationale",
        "canonical_write_authorized",
        "review_parent",
        "expected_parent_generation",
        "review_sha256",
    }
    reasons: list[str] = []
    if set(review) != expected_fields:
        reasons.append("fields")
    if review.get("contract_version") != REVIEW_CONTRACT_VERSION:
        reasons.append("contract_version")
    review_id = review.get("review_id")
    if not isinstance(review_id, str) or not SAFE_ID_RE.fullmatch(review_id):
        reasons.append("review_id")
    if review.get("identity") != candidate.get("identity"):
        reasons.append("identity")
    candidate_ref = review.get("candidate_ref")
    expected_candidate_suffix = (
        f"/memory_candidates/{candidate.get('source_role_id')}__"
        f"{candidate.get('candidate_id')}.json"
    )
    if (
        not isinstance(candidate_ref, Mapping)
        or set(candidate_ref) != {"path", "sha256"}
        or candidate_ref.get("sha256") != candidate.get("candidate_sha256")
        or not str(candidate_ref.get("path") or "").endswith(
            expected_candidate_suffix
        )
    ):
        reasons.append("candidate_ref")
    if review.get("candidate_snapshot") != candidate:
        reasons.append("candidate_snapshot")
    decision = review.get("decision")
    if decision not in REVIEW_DECISIONS:
        reasons.append("decision")
    if review.get("canonical_write_authorized") is not (
        decision == "APPROVE_CANONICAL"
    ):
        reasons.append("canonical_write_authorized")
    reviewer = review.get("reviewer")
    if (
        not isinstance(reviewer, Mapping)
        or set(reviewer)
        != {"reviewer_id", "reviewer_session_id", "independence_class"}
        or reviewer.get("independence_class") != "host_attested_independent_review"
        or not SAFE_ID_RE.fullmatch(str(reviewer.get("reviewer_id") or ""))
        or not SAFE_ID_RE.fullmatch(
            str(reviewer.get("reviewer_session_id") or "")
        )
        or reviewer.get("reviewer_session_id") == candidate.get("source_session_id")
    ):
        reasons.append("reviewer")
    outcome_ref = review.get("outcome_event_ref")
    if (
        not isinstance(outcome_ref, Mapping)
        or set(outcome_ref) != {"event_id", "sha256"}
        or not SAFE_ID_RE.fullmatch(str(outcome_ref.get("event_id") or ""))
        or not SHA256_RE.fullmatch(str(outcome_ref.get("sha256") or ""))
    ):
        reasons.append("outcome_event_ref")
    review_parent = review.get("review_parent")
    expected_parent_generation = review.get("expected_parent_generation")
    reasons.extend(
        _review_session_receipt_reasons(
            review.get("review_session_receipt"),
            identity=review.get("identity"),
            candidate_ref=review.get("candidate_ref"),
            outcome_event_ref=review.get("outcome_event_ref"),
            source_session_id=str(candidate.get("source_session_id") or ""),
            decision=str(decision or ""),
            rationale=str(review.get("rationale") or ""),
            review_parent=review_parent,
            expected_parent_generation=(
                expected_parent_generation
                if type(expected_parent_generation) is int
                else -1
            ),
            trust_store=trust_store,
        )
    )
    review_claim_sha256 = _review_claim_sha256(
        identity=review.get("identity") if isinstance(review.get("identity"), Mapping) else {},
        candidate_ref=(
            review.get("candidate_ref")
            if isinstance(review.get("candidate_ref"), Mapping)
            else {}
        ),
        outcome_event_ref=(
            review.get("outcome_event_ref")
            if isinstance(review.get("outcome_event_ref"), Mapping)
            else {}
        ),
        reviewer=reviewer if isinstance(reviewer, Mapping) else {},
        source_session_id=str(candidate.get("source_session_id") or ""),
        decision=str(decision or ""),
        rationale=str(review.get("rationale") or ""),
        canonical_write_authorized=bool(review.get("canonical_write_authorized")),
        review_parent=(review_parent if isinstance(review_parent, Mapping) else {}),
        expected_parent_generation=(
            expected_parent_generation
            if type(expected_parent_generation) is int
            else -1
        ),
    )
    reasons.extend(
        _reviewer_attestation_reasons(
            review.get("reviewer_attestation"),
            identity=review.get("identity"),
            candidate_ref=review.get("candidate_ref"),
            outcome_event_ref=review.get("outcome_event_ref"),
            reviewer=review.get("reviewer"),
            source_session_id=str(candidate.get("source_session_id") or ""),
            review_session_receipt=review.get("review_session_receipt"),
            review_claim_sha256=review_claim_sha256,
            review_parent=review_parent,
            expected_parent_generation=(
                expected_parent_generation
                if type(expected_parent_generation) is int
                else -1
            ),
            trust_store=trust_store,
        )
    )
    rationale = review.get("rationale")
    if (
        not isinstance(rationale, str)
        or not rationale.strip()
        or rationale != rationale.strip()
        or len(rationale) > 4000
    ):
        reasons.append("rationale")
    if (
        type(expected_parent_generation) is not int
        or expected_parent_generation < 1
    ):
        reasons.append("expected_parent_generation")
    if (
        not isinstance(review_parent, Mapping)
        or set(review_parent)
        != {"store_id", "generation", "manifest_sha256"}
        or not SAFE_ID_RE.fullmatch(str(review_parent.get("store_id") or ""))
        or type(review_parent.get("generation")) is not int
        or int(review_parent.get("generation") or -1) < 0
        or not SHA256_RE.fullmatch(
            str(review_parent.get("manifest_sha256") or "")
        )
        or (
            type(expected_parent_generation) is int
            and expected_parent_generation
            != int(review_parent.get("generation") or -1) + 1
        )
    ):
        reasons.append("review_parent")
    if _contains_absolute_path(review):
        reasons.append("absolute_path_disclosure")
    reasons.extend(
        validate_content_hash(review, hash_field="review_sha256", label="review")
    )
    return [f"{BLOCK_MEMORY_REVIEW_INVALID}:{reason}" for reason in reasons]


def record_research_outcome(
    root: Path,
    *,
    installation_id: str,
    store_id: str,
    identity: Mapping[str, Any],
    role_ids: Sequence[str],
    execution_status: str,
    protocol_status: str,
    factor_verdict: str,
    council_status: str,
    formal_proof_eligible: bool,
    organization_runtime_verified: bool,
    host_attestation_ref: Mapping[str, str],
    model_execution: Mapping[str, Any],
    repo_root: Path,
    workspace: Path,
) -> dict[str, Any]:
    resolved = _assert_private_root(root, repo_root=repo_root, workspace=workspace, create=True)
    ensure_researcher_memory_store(
        resolved,
        installation_id=installation_id,
        repo_root=repo_root,
        workspace=workspace,
    )
    frozen_identity = _identity_projection(identity)
    if execution_status != "COMPLETED" or factor_verdict not in {"ACCEPT", "REJECT"}:
        _raise(BLOCK_MEMORY_STORE_INVALID, "outcome_not_terminal")
    if type(formal_proof_eligible) is not bool:
        _raise(BLOCK_MEMORY_STORE_INVALID, "formal_proof_eligible")
    if organization_runtime_verified is not True:
        _raise(BLOCK_MEMORY_STORE_INVALID, "organization_runtime_unverified")
    if factor_verdict == "ACCEPT" and formal_proof_eligible is not True:
        _raise(BLOCK_MEMORY_STORE_INVALID, "accept_without_formal_proof")
    if factor_verdict not in FACTOR_VERDICTS:
        _raise(BLOCK_MEMORY_STORE_INVALID, "factor_verdict")
    role_list = [str(role_id) for role_id in role_ids]
    if not role_list or any(not SAFE_ID_RE.fullmatch(role_id) for role_id in role_list):
        _raise(BLOCK_MEMORY_STORE_INVALID, "roles")
    attestation = {
        "id": str(host_attestation_ref.get("id") or ""),
        "sha256": str(host_attestation_ref.get("sha256") or ""),
    }
    attestation_relative = Path(attestation["id"])
    if (
        not attestation["id"]
        or not _SAFE_RELATIVE_RE.fullmatch(attestation["id"])
        or attestation_relative.is_absolute()
        or ".." in attestation_relative.parts
        or len(attestation_relative.parts) != 3
        or attestation_relative.parts[:2]
        != ("attestations", frozen_identity["job_id"])
        or not re.fullmatch(
            r"attestation_[A-Za-z0-9_.-]+\.json",
            attestation_relative.name,
        )
        or not SHA256_RE.fullmatch(attestation["sha256"])
    ):
        _raise(BLOCK_MEMORY_STORE_INVALID, "host_attestation_ref")
    observed_attestation = _read_store_bytes(resolved.parent, attestation["id"])
    if hashlib.sha256(observed_attestation).hexdigest() != attestation["sha256"]:
        _raise(BLOCK_MEMORY_STORE_INVALID, "host_attestation_readback")
    core = {
        "identity": frozen_identity,
        "roles": role_list,
        "execution_status": str(execution_status),
        "protocol_status": str(protocol_status),
        "factor_verdict": factor_verdict,
        "council_status": str(council_status),
        "formal_proof_eligible": bool(formal_proof_eligible),
        "organization_runtime_verified": organization_runtime_verified,
        "host_attestation_ref": attestation,
        "model_execution": {
            "provider": str(model_execution.get("provider") or ""),
            "model": str(model_execution.get("model") or ""),
            "provenance": str(model_execution.get("provenance") or ""),
        },
        "interpretation_guard": "protocol PASS is not factor ACCEPT",
    }
    attestation_reasons = _host_outcome_attestation_reasons(
        observed_attestation,
        event=core,
        state_root=resolved.parent,
    )
    if attestation_reasons:
        _raise(BLOCK_MEMORY_STORE_INVALID, *attestation_reasons)
    event_id = f"outcome_{stable_json_hash(core)[:24]}"
    event = with_content_hash(
        {
            "contract_version": OUTCOME_EVENT_CONTRACT_VERSION,
            "event_id": event_id,
            **core,
        },
        hash_field="event_sha256",
    )
    outcome_reasons = _outcome_payload_reasons(event)
    if outcome_reasons:
        _raise(BLOCK_MEMORY_STORE_INVALID, *outcome_reasons)
    relative = f"outcomes/{event_id}.json"
    with _store_lock(resolved):
        manifest = _recover_and_read_manifest_locked(
            resolved,
            installation_id=installation_id,
        )
        if manifest.get("store_id") != store_id:
            _raise(BLOCK_MEMORY_STORE_INVALID, "bound_store_id_mismatch")
        for existing_outcome_ref in manifest.get("outcome_events") or []:
            existing_outcome = _read_store_json(
                resolved,
                str(existing_outcome_ref["path"]),
            )
            if (
                existing_outcome.get("identity") == frozen_identity
                and existing_outcome.get("event_id") != event_id
            ):
                _raise(
                    BLOCK_MEMORY_WRITE_CONFLICT,
                    "terminal_outcome_identity_conflict",
                )
        manifest, idempotent = _commit_indexed_payload_locked(
            resolved,
            manifest=manifest,
            kind="outcome",
            identifier=event_id,
            target_relative=relative,
            payload=event,
            index_entry={
                "event_id": event_id,
                "factor_id": frozen_identity["factor_id"],
                "research_id": frozen_identity["research_id"],
                "report_id": frozen_identity["report_id"],
                "roles": role_list,
                "factor_verdict": factor_verdict,
                "path": relative,
                "sha256": event["event_sha256"],
            },
        )
        return {
            "event_id": event_id,
            "event_sha256": event["event_sha256"],
            "path": relative,
            "store_id": manifest["store_id"],
            "generation": manifest["generation"],
            "idempotent": idempotent,
        }


def _find_outcome(manifest: Mapping[str, Any], event_id: str) -> Mapping[str, Any] | None:
    return next(
        (item for item in manifest.get("outcome_events") or [] if item.get("event_id") == event_id),
        None,
    )


def load_candidate_review_material(
    *,
    workspace: Path,
    candidate_relative: str,
    root: Path,
    installation_id: str,
    outcome_event_id: str,
    repo_root: Path,
    trust_root: Path | None = None,
) -> dict[str, Any]:
    """Load an admitted candidate and terminal outcome for an independent review."""

    workspace = Path(workspace).expanduser().resolve(strict=True)
    relative = normalize_workspace_relative_path(
        candidate_relative,
        workspace=workspace,
        label="memory_candidate",
    )
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=workspace,
        create=False,
    )
    validate_researcher_memory_store(
        resolved,
        installation_id=installation_id,
        repo_root=repo_root,
        workspace=workspace,
    )
    from factor_factory.research_org.runtime_trust import load_runtime_trust_store

    expected_trust_root = resolved.parent / "research-org-trust"
    selected_trust_root = (
        Path(trust_root).expanduser() if trust_root is not None else expected_trust_root
    )
    if selected_trust_root.resolve(strict=False) != expected_trust_root.resolve(
        strict=False
    ):
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "trust_root_binding")
    trust_store = load_runtime_trust_store(
        selected_trust_root,
        installation_id=installation_id,
    )
    candidate, source_task, source_result = _load_admitted_candidate_sources(
        workspace=workspace,
        candidate_relative=relative,
        trust_store=trust_store,
    )
    with _store_lock(resolved, create=False):
        manifest = _recover_and_read_manifest_locked(
            resolved,
            installation_id=installation_id,
        )
        snapshot_ref = candidate.get("source_memory_snapshot_ref") or {}
        if snapshot_ref.get("store_id") != manifest.get("store_id"):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "candidate_store_id")
        outcome_ref = _find_outcome(manifest, outcome_event_id)
        if outcome_ref is None:
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "outcome_event_missing")
        outcome = _read_store_json(resolved, str(outcome_ref["path"]))
        if outcome.get("identity") != candidate.get("identity"):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "outcome_identity")
        if candidate.get("source_role_id") not in (outcome.get("roles") or []):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "outcome_role_binding")
        canonical_records = [
            _read_store_json(resolved, str(reference["path"]))
            for reference in manifest.get("canonical_records") or []
        ]
        canonical_reasons = [
            reason
            for record in canonical_records
            for reason in _canonical_payload_reasons(record)
        ]
        if canonical_reasons:
            _raise(BLOCK_MEMORY_STORE_INVALID, *canonical_reasons)
        source_role_id = str(candidate.get("source_role_id") or "")
        applicable_records = [
            record
            for record in canonical_records
            if source_role_id in (record.get("role_scope") or [])
            or "shared" in (record.get("role_scope") or [])
        ]
        review_parent = {
            "store_id": str(manifest["store_id"]),
            "generation": int(manifest["generation"]),
            "manifest_sha256": str(manifest["manifest_sha256"]),
        }
        current_memory_snapshot = with_content_hash(
            {
                "contract_version": (
                    "factorforge_researcher_memory_review_snapshot_v1"
                ),
                "identity": dict(candidate["identity"]),
                "source_role_id": source_role_id,
                "review_parent": review_parent,
                "canonical_records": applicable_records,
                "policy": {
                    "novelty_must_use_current_generation": True,
                    "historical_advisory_only": True,
                    "current_factor_inference_allowed": False,
                },
            },
            hash_field="snapshot_sha256",
        )
    return {
        "workspace": workspace,
        "memory_root": resolved,
        "trust_root": selected_trust_root.resolve(strict=True),
        "candidate_relative": relative,
        "candidate_ref": {
            "path": relative,
            "sha256": str(candidate["candidate_sha256"]),
        },
        "candidate": dict(candidate),
        "source_task": dict(source_task),
        "source_result": dict(source_result),
        "outcome_event_ref": {
            "event_id": outcome_event_id,
            "sha256": str(outcome["event_sha256"]),
        },
        "outcome_event": dict(outcome),
        "review_parent": review_parent,
        "current_memory_snapshot": current_memory_snapshot,
    }


def record_candidate_review(
    *,
    workspace: Path,
    candidate_relative: str,
    root: Path,
    installation_id: str,
    decision: str,
    reviewer_session_receipt_ref: Mapping[str, str],
    outcome_event_id: str,
    rationale: str,
    repo_root: Path,
    trust_root: Path | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve(strict=True)
    relative = normalize_workspace_relative_path(
        candidate_relative, workspace=workspace, label="memory_candidate"
    )
    if decision not in REVIEW_DECISIONS:
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "decision")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4000:
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "rationale")
    resolved = _assert_private_root(root, repo_root=repo_root, workspace=workspace, create=True)
    ensure_researcher_memory_store(
        resolved,
        installation_id=installation_id,
        repo_root=repo_root,
        workspace=workspace,
    )
    from factor_factory.research_org.runtime_trust import load_runtime_trust_store

    expected_trust_root = resolved.parent / "research-org-trust"
    selected_trust_root = (
        Path(trust_root).expanduser() if trust_root is not None else expected_trust_root
    )
    if selected_trust_root.resolve(strict=False) != expected_trust_root.resolve(
        strict=False
    ):
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "trust_root_binding")
    trust_store = load_runtime_trust_store(
        selected_trust_root,
        installation_id=installation_id,
    )
    candidate, _source_task, _source_result = _load_admitted_candidate_sources(
        workspace=workspace,
        candidate_relative=relative,
        trust_store=trust_store,
    )
    receipt_ref = {
        "id": str(reviewer_session_receipt_ref.get("id") or ""),
        "sha256": str(reviewer_session_receipt_ref.get("sha256") or ""),
    }
    if (
        not receipt_ref["id"]
        or not _SAFE_RELATIVE_RE.fullmatch(receipt_ref["id"])
        or Path(receipt_ref["id"]).is_absolute()
        or ".." in Path(receipt_ref["id"]).parts
        or not SHA256_RE.fullmatch(receipt_ref["sha256"])
    ):
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "review_session_receipt_ref")
    review_session_raw = _read_store_bytes(resolved.parent, receipt_ref["id"])
    if hashlib.sha256(review_session_raw).hexdigest() != receipt_ref["sha256"]:
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "review_session_receipt_readback")
    review_session_receipt = strict_json_loads(
        review_session_raw,
        label="review_session_receipt",
    )
    if not isinstance(review_session_receipt, Mapping):
        _raise(BLOCK_MEMORY_REVIEW_INVALID, "review_session_receipt_object")
    with _store_lock(resolved):
        manifest = _recover_and_read_manifest_locked(
            resolved,
            installation_id=installation_id,
        )
        snapshot_ref = candidate.get("source_memory_snapshot_ref") or {}
        if snapshot_ref.get("store_id") != manifest.get("store_id"):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "candidate_store_id")
        outcome_ref = _find_outcome(manifest, outcome_event_id)
        if outcome_ref is None:
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "outcome_event_missing")
        outcome = _read_store_json(resolved, str(outcome_ref["path"]))
        if outcome.get("identity") != candidate.get("identity"):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "outcome_identity")
        if candidate.get("source_role_id") not in (outcome.get("roles") or []):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "outcome_role_binding")
        runtime_reviewer = review_session_receipt.get("reviewer") or {}
        reviewer = {
            "reviewer_id": str(runtime_reviewer.get("reviewer_id") or ""),
            "reviewer_session_id": str(
                runtime_reviewer.get("reviewer_session_id") or ""
            ),
            "independence_class": "host_attested_independent_review",
        }
        candidate_reference = {
            "path": relative,
            "sha256": candidate["candidate_sha256"],
        }
        outcome_event_ref = {
            "event_id": outcome_event_id,
            "sha256": outcome["event_sha256"],
        }
        receipt_bindings = review_session_receipt.get("bindings") or {}
        review_parent = (
            dict(receipt_bindings.get("review_parent") or {})
            if isinstance(receipt_bindings, Mapping)
            else {}
        )
        expected_parent_generation = (
            receipt_bindings.get("expected_parent_generation")
            if isinstance(receipt_bindings, Mapping)
            else -1
        )
        review_claim_sha256 = _review_claim_sha256(
            identity=candidate["identity"],
            candidate_ref=candidate_reference,
            outcome_event_ref=outcome_event_ref,
            reviewer=reviewer,
            source_session_id=str(candidate["source_session_id"]),
            decision=decision,
            rationale=rationale.strip(),
            canonical_write_authorized=decision == "APPROVE_CANONICAL",
            review_parent=review_parent,
            expected_parent_generation=(
                expected_parent_generation
                if type(expected_parent_generation) is int
                else -1
            ),
        )
        session_reasons = _review_session_receipt_reasons(
            review_session_receipt,
            identity=candidate["identity"],
            candidate_ref=candidate_reference,
            outcome_event_ref=outcome_event_ref,
            source_session_id=str(candidate["source_session_id"]),
            decision=decision,
            rationale=rationale.strip(),
            review_parent=review_parent,
            expected_parent_generation=(
                expected_parent_generation
                if type(expected_parent_generation) is int
                else -1
            ),
            trust_store=trust_store,
        )
        if session_reasons:
            _raise(BLOCK_MEMORY_REVIEW_INVALID, *session_reasons)
        reviewer_attestation = trust_store.sign(
            "host_admission",
            {
                "receipt_type": "RESEARCHER_MEMORY_REVIEW_ATTESTED",
                "identity": dict(candidate["identity"]),
                "bindings": {
                    "candidate_ref": candidate_reference,
                    "outcome_event_ref": outcome_event_ref,
                    "source_session_id": candidate["source_session_id"],
                    "review_session_receipt_id": review_session_receipt[
                        "receipt_id"
                    ],
                    "review_claim_sha256": review_claim_sha256,
                    "review_parent": review_parent,
                    "expected_parent_generation": expected_parent_generation,
                },
                "reviewer": reviewer,
            },
        )
        for existing_ref in manifest["reviews"]:
            if existing_ref.get("candidate_id") != candidate.get("candidate_id"):
                continue
            existing = _read_store_json(resolved, str(existing_ref["path"]))
            existing_review_reasons = validate_candidate_review(
                existing,
                candidate=candidate,
                trust_store=trust_store,
            )
            if existing_review_reasons:
                _raise(BLOCK_MEMORY_REVIEW_INVALID, *existing_review_reasons)
            if (
                existing.get("decision") == decision
                and existing.get("reviewer") == reviewer
                and existing.get("review_session_receipt")
                == review_session_receipt
                and existing.get("reviewer_attestation") == reviewer_attestation
                and existing.get("outcome_event_ref") == outcome_event_ref
                and existing.get("rationale") == rationale.strip()
                and existing.get("review_parent") == review_parent
                and existing.get("expected_parent_generation")
                == expected_parent_generation
            ):
                existing_workspace_path = (
                    f"objects/research_organization/"
                    f"{candidate['identity']['report_id']}/memory_reviews/"
                    f"{existing['review_id']}.json"
                )
                try:
                    write_workspace_json_once(
                        workspace,
                        existing_workspace_path,
                        existing,
                    )
                except FileExistsError:
                    observed = read_workspace_json(
                        workspace,
                        existing_workspace_path,
                    )
                    if stable_json_hash(observed) != stable_json_hash(existing):
                        _raise(
                            BLOCK_MEMORY_WRITE_CONFLICT,
                            "workspace_review_conflict",
                        )
                return {
                    "review_id": existing["review_id"],
                    "review_sha256": existing["review_sha256"],
                    "workspace_path": existing_workspace_path,
                    "decision": decision,
                    "store_generation": manifest["generation"],
                    "idempotent": True,
                }
            _raise(
                BLOCK_MEMORY_WRITE_CONFLICT,
                "candidate_review_already_admitted",
            )
        if (
            review_parent
            != {
                "store_id": manifest.get("store_id"),
                "generation": manifest.get("generation"),
                "manifest_sha256": manifest.get("manifest_sha256"),
            }
            or type(expected_parent_generation) is not int
            or expected_parent_generation != int(manifest["generation"]) + 1
        ):
            _raise(BLOCK_MEMORY_REVIEW_INVALID, "stale_review_parent")
        core = {
            "identity": dict(candidate["identity"]),
            "candidate_ref": candidate_reference,
            "candidate_snapshot": dict(candidate),
            "decision": decision,
            "reviewer": reviewer,
            "review_session_receipt": dict(review_session_receipt),
            "reviewer_attestation": reviewer_attestation,
            "outcome_event_ref": outcome_event_ref,
            "rationale": rationale.strip(),
            "canonical_write_authorized": decision == "APPROVE_CANONICAL",
            "review_parent": review_parent,
            "expected_parent_generation": expected_parent_generation,
        }
        review_id = f"review_{stable_json_hash(core)[:24]}"
        review = with_content_hash(
            {
                "contract_version": REVIEW_CONTRACT_VERSION,
                "review_id": review_id,
                **core,
            },
            hash_field="review_sha256",
        )
        review_reasons = validate_candidate_review(
            review,
            candidate=candidate,
            trust_store=trust_store,
        )
        if review_reasons:
            _raise(BLOCK_MEMORY_REVIEW_INVALID, *review_reasons)
        workspace_relative = (
            f"objects/research_organization/{candidate['identity']['report_id']}"
            f"/memory_reviews/{review_id}.json"
        )
        try:
            write_workspace_json_once(workspace, workspace_relative, review)
        except FileExistsError:
            existing = read_workspace_json(workspace, workspace_relative)
            if stable_json_hash(existing) != stable_json_hash(review):
                _raise(BLOCK_MEMORY_WRITE_CONFLICT, "workspace_review_conflict")
        store_relative = f"reviews/{review_id}.json"
        manifest, idempotent = _commit_indexed_payload_locked(
            resolved,
            manifest=manifest,
            kind="review",
            identifier=review_id,
            target_relative=store_relative,
            payload=review,
            index_entry={
                "review_id": review_id,
                "candidate_id": candidate["candidate_id"],
                "decision": decision,
                "path": store_relative,
                "sha256": review["review_sha256"],
            },
        )
        return {
            "review_id": review_id,
            "review_sha256": review["review_sha256"],
            "workspace_path": workspace_relative,
            "decision": decision,
            "store_generation": manifest["generation"],
            "idempotent": idempotent,
        }


def promote_reviewed_candidate(
    *,
    workspace: Path,
    review_relative: str,
    root: Path,
    installation_id: str,
    repo_root: Path,
    trust_root: Path | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve(strict=True)
    review_path = normalize_workspace_relative_path(
        review_relative, workspace=workspace, label="memory_review"
    )
    review = read_workspace_json(workspace, review_path)
    if (
        review.get("contract_version") != REVIEW_CONTRACT_VERSION
        or review.get("decision") != "APPROVE_CANONICAL"
        or review.get("canonical_write_authorized") is not True
        or validate_content_hash(review, hash_field="review_sha256", label="review")
    ):
        _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "review_not_approved")
    candidate_ref = review.get("candidate_ref") or {}
    candidate_relative = normalize_workspace_relative_path(
        candidate_ref.get("path"), workspace=workspace, label="review.candidate_ref"
    )
    resolved = _assert_private_root(root, repo_root=repo_root, workspace=workspace, create=True)
    from factor_factory.research_org.runtime_trust import load_runtime_trust_store

    expected_trust_root = resolved.parent / "research-org-trust"
    selected_trust_root = (
        Path(trust_root).expanduser() if trust_root is not None else expected_trust_root
    )
    if selected_trust_root.resolve(strict=False) != expected_trust_root.resolve(
        strict=False
    ):
        _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "trust_root_binding")
    trust_store = load_runtime_trust_store(
        selected_trust_root,
        installation_id=installation_id,
    )
    candidate, _source_task, _source_result = _load_admitted_candidate_sources(
        workspace=workspace,
        candidate_relative=candidate_relative,
        trust_store=trust_store,
    )
    review_reasons = validate_candidate_review(
        review,
        candidate=candidate,
        trust_store=trust_store,
    )
    if review_reasons:
        _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, *review_reasons)
    if (
        candidate.get("candidate_sha256") != candidate_ref.get("sha256")
        or candidate.get("identity") != review.get("identity")
        or candidate.get("authority") != "candidate_only"
        or candidate.get("promotion_allowed") is not False
        or _candidate_content_hash_reasons(candidate)
    ):
        _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "candidate_binding")
    reviewer = review.get("reviewer") or {}
    if reviewer.get("reviewer_session_id") == candidate.get("source_session_id"):
        _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "self_review")
    ensure_researcher_memory_store(
        resolved,
        installation_id=installation_id,
        repo_root=repo_root,
        workspace=workspace,
    )
    with _store_lock(resolved):
        manifest = _recover_and_read_manifest_locked(
            resolved,
            installation_id=installation_id,
        )
        review_ref = next(
            (
                item
                for item in manifest["reviews"]
                if item.get("review_id") == review.get("review_id")
            ),
            None,
        )
        if review_ref is None or review_ref.get("sha256") != review.get("review_sha256"):
            _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "review_not_admitted")
        outcome_ref = _find_outcome(
            manifest,
            str((review.get("outcome_event_ref") or {}).get("event_id") or ""),
        )
        if outcome_ref is None or outcome_ref.get("sha256") != (
            review.get("outcome_event_ref") or {}
        ).get("sha256"):
            _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "outcome_not_admitted")
        if (candidate.get("source_memory_snapshot_ref") or {}).get("store_id") != manifest.get(
            "store_id"
        ):
            _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "store_id_mismatch")
        memory_id = f"memory_{str(candidate['candidate_sha256'])[:24]}"
        existing_ref = next(
            (
                item
                for item in manifest["canonical_records"]
                if item.get("memory_id") == memory_id
            ),
            None,
        )
        if existing_ref is None:
            candidate_semantics = {
                "role_scope": list(candidate["role_scope"]),
                "memory_kind": candidate["memory_kind"],
                "title": candidate["title"],
                "lesson": candidate["lesson"],
                "applicability_conditions": list(
                    candidate["applicability_conditions"]
                ),
                "failure_conditions": list(candidate["failure_conditions"]),
            }
            for canonical_ref in manifest["canonical_records"]:
                canonical = _read_store_json(
                    resolved,
                    str(canonical_ref["path"]),
                )
                observed_semantics = {
                    field: canonical.get(field)
                    for field in candidate_semantics
                }
                if observed_semantics == candidate_semantics:
                    _raise(
                        BLOCK_MEMORY_PROMOTION_FORBIDDEN,
                        "duplicate_canonical_memory",
                    )
        if (
            existing_ref is None
            and int(manifest["generation"])
            != int(review.get("expected_parent_generation") or -1)
        ):
            _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, "stale_parent_generation")
        promotion_generation = (
            int(existing_ref["promoted_generation"])
            if existing_ref is not None
            else int(manifest["generation"]) + 1
        )
        outcome = _read_store_json(resolved, str(outcome_ref["path"]))
        outcome_reasons = _outcome_payload_reasons(outcome)
        if outcome_reasons:
            _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, *outcome_reasons)
        record = with_content_hash(
            {
                "contract_version": CANONICAL_RECORD_CONTRACT_VERSION,
                "memory_id": memory_id,
                "state": "canonical",
                "authority": "historical_advisory_only",
                "role_scope": list(candidate["role_scope"]),
                "memory_kind": candidate["memory_kind"],
                "title": candidate["title"],
                "lesson": candidate["lesson"],
                "applicability_conditions": list(candidate["applicability_conditions"]),
                "failure_conditions": list(candidate["failure_conditions"]),
                "evidence_refs": [dict(item) for item in candidate["evidence_refs"]],
                "source_identity": dict(candidate["identity"]),
                "source_factor_verdict": outcome["factor_verdict"],
                "source_candidate_ref": {
                    "candidate_id": candidate["candidate_id"],
                    "sha256": candidate["candidate_sha256"],
                },
                "source_review_ref": {
                    "review_id": review["review_id"],
                    "sha256": review["review_sha256"],
                },
                "source_outcome_summary": {
                    "execution_status": outcome["execution_status"],
                    "protocol_status": outcome["protocol_status"],
                    "factor_verdict": outcome["factor_verdict"],
                    "council_status": outcome["council_status"],
                    "formal_proof_eligible": outcome["formal_proof_eligible"],
                    "organization_runtime_verified": outcome[
                        "organization_runtime_verified"
                    ],
                },
                "promotion_generation": promotion_generation,
            },
            hash_field="canonical_sha256",
        )
        canonical_reasons = _canonical_payload_reasons(record)
        if canonical_reasons:
            _raise(BLOCK_MEMORY_PROMOTION_FORBIDDEN, *canonical_reasons)
        store_relative = f"canonical/{memory_id}.json"
        manifest, idempotent = _commit_indexed_payload_locked(
            resolved,
            manifest=manifest,
            kind="canonical",
            identifier=memory_id,
            target_relative=store_relative,
            payload=record,
            index_entry={
                "memory_id": memory_id,
                "role_scope": list(candidate["role_scope"]),
                "promoted_generation": promotion_generation,
                "path": store_relative,
                "sha256": record["canonical_sha256"],
            },
        )
        return {
            "memory_id": memory_id,
            "canonical_sha256": record["canonical_sha256"],
            "store_id": manifest["store_id"],
            "generation": manifest["generation"],
            "idempotent": idempotent,
        }


# EVO V2 semantic truth lives exclusively in factor_factory.evo_v2.  The
# following API is a Host-private persistence envelope: it never redefines an
# experience, transfer mapping, or use receipt and never grants factor proof.
_EVO_V2_ADMISSION_AUTHORITY_GUARD = {
    "semantic_authority": "factor_factory.evo_v2",
    "payload_mutation_allowed": False,
    "skill_or_validator_mutation_allowed": False,
    "threshold_or_oos_mutation_allowed": False,
    "estimand_or_trial_budget_mutation_allowed": False,
    "current_factor_proof_authority": False,
    "canonical_factor_write_authority": False,
    "host_private_persistence_only": True,
}
_EVO_V2_ADMISSION_ROOT_ENTRIES = {
    _LOCK_NAME,
    _TEMP_DIR_NAME,
    "admissions",
}


def _evo_v2_sidecar_layout_reasons(resolved: Path) -> list[str]:
    reasons: list[str] = []
    try:
        root_entries = {path.name for path in resolved.iterdir()}
    except OSError as exc:
        return [f"root_read:{exc}"]
    if root_entries != _EVO_V2_ADMISSION_ROOT_ENTRIES:
        reasons.append("root_entries")
    for name in ("admissions", _TEMP_DIR_NAME):
        path = resolved / name
        try:
            metadata = path.lstat()
        except OSError as exc:
            reasons.append(f"{name}_directory:{exc}")
            continue
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIR_MODE
        ):
            reasons.append(f"{name}_directory")
    temporary_root = resolved / _TEMP_DIR_NAME
    try:
        if any(temporary_root.iterdir()):
            reasons.append("temporary_directory_not_empty")
    except OSError as exc:
        reasons.append(f"temporary_directory:{exc}")
    return reasons


def _evo_v2_workspace_payload(
    *,
    workspace: Path,
    reference: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"}:
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, f"{label}_ref_fields")
    relative = normalize_workspace_relative_path(
        reference.get("path"),
        workspace=workspace,
        label=label,
    )
    path = workspace / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or sha256_file(path) != reference.get("sha256")
    ):
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, f"{label}_ref_readback")
    payload = read_workspace_json(workspace, relative)
    if not isinstance(payload, dict):
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, f"{label}_object")
    return payload


def _evo_v2_transfer_use_change_receipt_reasons(
    receipt: Any,
    *,
    transfer_bundle: Mapping[str, Any],
    transfer_receipt: Mapping[str, Any],
    trust_store: Any,
    workspace: Path | None,
    verify_refs: bool,
) -> list[str]:
    """Validate actual before/after research changes claimed by transfer use."""

    reasons: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["transfer_use_change_receipt_object"]
    expected_fields = {
        "contract_version",
        "authority",
        "artifact_identity",
        "transfer_bundle_ref",
        "transfer_use_receipt_ref",
        "before_research_plan_ref",
        "after_research_plan_ref",
        "question_and_test_diff",
        "mapping_uses",
        "protected_contracts",
        "host_change_attestation",
        "authority_guard",
        "change_receipt_sha256",
    }
    if set(receipt) != expected_fields:
        reasons.append("transfer_use_change_receipt_fields")
    if (
        receipt.get("contract_version") != EVO_V2_TRANSFER_USE_CHANGE_RECEIPT_TYPE
        or receipt.get("authority")
        != "host_attested_question_and_test_change_only"
        or receipt.get("artifact_identity")
        != transfer_bundle.get("artifact_identity")
    ):
        reasons.append("transfer_use_change_receipt_identity")
    expected_transfer_bundle_ref = {
        "path": transfer_receipt.get("transfer_bundle_ref", {}).get("path"),
        "sha256": transfer_receipt.get("transfer_bundle_ref", {}).get("sha256"),
    }
    if (
        receipt.get("transfer_bundle_ref") != expected_transfer_bundle_ref
        or receipt.get("transfer_use_receipt_ref")
        != {
            "path": (
                f"objects/research_organization/"
                f"{transfer_bundle.get('artifact_identity', {}).get('report_id')}"
                "/evo_v2/transfer_use_receipt.json"
            ),
            "sha256": transfer_receipt.get("content_sha256"),
        }
    ):
        reasons.append("transfer_use_change_receipt_core_binding")
    before_ref = receipt.get("before_research_plan_ref")
    after_ref = receipt.get("after_research_plan_ref")
    before_plan: Mapping[str, Any] = {}
    after_plan: Mapping[str, Any] = {}
    for label, reference in (("before", before_ref), ("after", after_ref)):
        if (
            not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256"}
            or not SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
        ):
            reasons.append(f"transfer_use_change_{label}_ref")
            continue
        if workspace is not None and verify_refs:
            try:
                observed = _evo_v2_workspace_payload(
                    workspace=workspace,
                    reference=reference,
                    label=f"transfer_use_change_{label}",
                )
            except ResearchOrganizationError as exc:
                reasons.extend(exc.reasons)
            else:
                if label == "before":
                    before_plan = observed
                else:
                    after_plan = observed
    diff = receipt.get("question_and_test_diff")
    if (
        not isinstance(diff, Mapping)
        or set(diff)
        != {
            "before_sha256",
            "after_sha256",
            "added_question_ids",
            "added_test_ids",
            "removed_question_ids",
            "removed_test_ids",
        }
        or diff.get("before_sha256") != (before_ref or {}).get("sha256")
        or diff.get("after_sha256") != (after_ref or {}).get("sha256")
        or diff.get("before_sha256") == diff.get("after_sha256")
        or not isinstance(diff.get("added_question_ids"), list)
        or not isinstance(diff.get("added_test_ids"), list)
        or not isinstance(diff.get("removed_question_ids"), list)
        or not isinstance(diff.get("removed_test_ids"), list)
        or diff.get("removed_question_ids")
        or diff.get("removed_test_ids")
        or not (diff.get("added_question_ids") or diff.get("added_test_ids"))
        or any(
            not SAFE_ID_RE.fullmatch(str(identifier or ""))
            for field in ("added_question_ids", "added_test_ids")
            for identifier in diff.get(field) or []
        )
    ):
        reasons.append("transfer_use_change_diff")
    if before_plan and after_plan:
        before_questions = before_plan.get("research_questions")
        after_questions = after_plan.get("research_questions")
        before_tests = before_plan.get("registered_tests")
        after_tests = after_plan.get("registered_tests")
        if not all(
            isinstance(items, list)
            for items in (
                before_questions,
                after_questions,
                before_tests,
                after_tests,
            )
        ):
            reasons.append("transfer_use_change_plan_shape")
        else:
            def ids(items: list[Any], field: str) -> set[str]:
                output: set[str] = set()
                for item in items:
                    if not isinstance(item, Mapping) or set(item) != {field, "text"}:
                        reasons.append(f"transfer_use_change_plan_{field}_entry")
                        continue
                    identifier = str(item.get(field) or "")
                    if not SAFE_ID_RE.fullmatch(identifier):
                        reasons.append(f"transfer_use_change_plan_{field}_id")
                    output.add(identifier)
                return output

            before_question_ids = ids(before_questions, "question_id")
            after_question_ids = ids(after_questions, "question_id")
            before_test_ids = ids(before_tests, "test_id")
            after_test_ids = ids(after_tests, "test_id")
            if (
                sorted(after_question_ids - before_question_ids)
                != sorted(diff.get("added_question_ids") or [])
                or sorted(after_test_ids - before_test_ids)
                != sorted(diff.get("added_test_ids") or [])
                or before_question_ids - after_question_ids
                or before_test_ids - after_test_ids
            ):
                reasons.append("transfer_use_change_plan_diff_binding")
    mapping_uses = receipt.get("mapping_uses")
    expected_uses = transfer_receipt.get("uses") or []
    if not isinstance(mapping_uses, list) or len(mapping_uses) != len(expected_uses):
        reasons.append("transfer_use_change_mapping_uses")
    else:
        expected_mapping_ids = [str(item.get("mapping_id") or "") for item in expected_uses]
        observed_mapping_ids: list[str] = []
        added_question_ids = set((diff or {}).get("added_question_ids") or [])
        added_test_ids = set((diff or {}).get("added_test_ids") or [])
        for item in mapping_uses:
            if (
                not isinstance(item, Mapping)
                or set(item)
                != {
                    "mapping_id",
                    "research_effect",
                    "generated_question_ids",
                    "generated_test_ids",
                }
                or not isinstance(item.get("generated_question_ids"), list)
                or not isinstance(item.get("generated_test_ids"), list)
                or not set(item.get("generated_question_ids") or [])
                <= added_question_ids
                or not set(item.get("generated_test_ids") or []) <= added_test_ids
            ):
                reasons.append("transfer_use_change_mapping_use_entry")
                continue
            observed_mapping_ids.append(str(item["mapping_id"]))
            source_use = next(
                (
                    use
                    for use in expected_uses
                    if use.get("mapping_id") == item.get("mapping_id")
                ),
                None,
            )
            if (
                source_use is None
                or item.get("research_effect") != source_use.get("research_effect")
                or (
                    source_use.get("changed_research_question_or_test") is True
                    and not (
                        item.get("generated_question_ids")
                        or item.get("generated_test_ids")
                    )
                )
                or (
                    source_use.get("generated_test_id")
                    not in (item.get("generated_test_ids") or [])
                )
            ):
                reasons.append("transfer_use_change_mapping_use_binding")
        if observed_mapping_ids != expected_mapping_ids:
            reasons.append("transfer_use_change_mapping_order")
    protected = receipt.get("protected_contracts")
    if (
        not isinstance(protected, Mapping)
        or set(protected)
        != {
            "skill_sha256",
            "validator_sha256",
            "thresholds_sha256",
            "oos_policy_sha256",
            "estimand_sha256",
            "trial_budget_sha256",
            "unchanged",
        }
        or protected.get("unchanged") is not True
        or any(
            not SHA256_RE.fullmatch(str(protected.get(field) or ""))
            for field in set(protected) - {"unchanged"}
        )
    ):
        reasons.append("transfer_use_change_protected_contracts")
    host_attestation = receipt.get("host_change_attestation")
    if trust_store is None or not hasattr(trust_store, "verify"):
        reasons.append("transfer_use_change_trust_store")
    elif not isinstance(host_attestation, Mapping):
        reasons.append("transfer_use_change_host_attestation")
    else:
        reasons.extend(
            f"transfer_use_change_signature:{reason}"
            for reason in trust_store.verify(
                host_attestation,
                expected_issuer="host_admission",
            )
        )
        if (
            host_attestation.get("receipt_type")
            != "RESEARCHER_MEMORY_EVO_V2_TRANSFER_USE_CHANGE_ADMITTED"
            or host_attestation.get("identity")
            != transfer_bundle.get("artifact_identity")
            or host_attestation.get("bindings")
            != {
                "transfer_bundle_ref": receipt.get("transfer_bundle_ref"),
                "transfer_use_receipt_ref": receipt.get(
                    "transfer_use_receipt_ref"
                ),
                "before_research_plan_ref": before_ref,
                "after_research_plan_ref": after_ref,
                "question_and_test_diff": diff,
                "mapping_uses": mapping_uses,
                "protected_contracts": protected,
            }
            or host_attestation.get("outcome")
            != {
                "change_verified": True,
                "question_and_test_change_only": True,
                "current_factor_proof_authority": False,
                "canonical_memory_write_authority": False,
            }
        ):
            reasons.append("transfer_use_change_host_binding")
    if receipt.get("authority_guard") != {
        "actual_before_after_readback_required": True,
        "protected_contracts_unchanged": True,
        "current_factor_proof_authority": False,
        "canonical_memory_write_authority": False,
    }:
        reasons.append("transfer_use_change_authority_guard")
    reasons.extend(
        validate_content_hash(
            receipt,
            hash_field="change_receipt_sha256",
            label="evo_v2_transfer_use_change_receipt",
        )
    )
    if _contains_absolute_path(receipt):
        reasons.append("transfer_use_change_absolute_path")
    return list(dict.fromkeys(reasons))


def build_evo_v2_transfer_use_change_receipt(
    *,
    workspace: Path,
    transfer_bundle: Mapping[str, Any],
    transfer_receipt: Mapping[str, Any],
    before_research_plan_ref: Mapping[str, Any],
    after_research_plan_ref: Mapping[str, Any],
    mapping_uses: Sequence[Mapping[str, Any]],
    protected_contracts: Mapping[str, Any],
    trust_store: Any,
) -> dict[str, Any]:
    """Host-attest exact question/test changes and protected-hash invariance."""

    workspace = Path(workspace).expanduser().resolve(strict=True)
    before_plan = _evo_v2_workspace_payload(
        workspace=workspace,
        reference=before_research_plan_ref,
        label="before_research_plan",
    )
    after_plan = _evo_v2_workspace_payload(
        workspace=workspace,
        reference=after_research_plan_ref,
        label="after_research_plan",
    )
    def plan_ids(plan: Mapping[str, Any], list_field: str, id_field: str) -> set[str]:
        values = plan.get(list_field)
        if not isinstance(values, list):
            _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, f"{list_field}_list")
        return {
            str(item.get(id_field) or "")
            for item in values
            if isinstance(item, Mapping)
        }

    before_questions = plan_ids(before_plan, "research_questions", "question_id")
    after_questions = plan_ids(after_plan, "research_questions", "question_id")
    before_tests = plan_ids(before_plan, "registered_tests", "test_id")
    after_tests = plan_ids(after_plan, "registered_tests", "test_id")
    diff = {
        "before_sha256": before_research_plan_ref.get("sha256"),
        "after_sha256": after_research_plan_ref.get("sha256"),
        "added_question_ids": sorted(after_questions - before_questions),
        "added_test_ids": sorted(after_tests - before_tests),
        "removed_question_ids": sorted(before_questions - after_questions),
        "removed_test_ids": sorted(before_tests - after_tests),
    }
    transfer_bundle_ref = dict(transfer_receipt.get("transfer_bundle_ref") or {})
    transfer_use_receipt_ref = {
        "path": (
            f"objects/research_organization/"
            f"{transfer_bundle.get('artifact_identity', {}).get('report_id')}"
            "/evo_v2/transfer_use_receipt.json"
        ),
        "sha256": transfer_receipt.get("content_sha256"),
    }
    host_attestation = trust_store.sign(
        "host_admission",
        {
            "receipt_type": (
                "RESEARCHER_MEMORY_EVO_V2_TRANSFER_USE_CHANGE_ADMITTED"
            ),
            "identity": dict(transfer_bundle.get("artifact_identity") or {}),
            "bindings": {
                "transfer_bundle_ref": transfer_bundle_ref,
                "transfer_use_receipt_ref": transfer_use_receipt_ref,
                "before_research_plan_ref": dict(before_research_plan_ref),
                "after_research_plan_ref": dict(after_research_plan_ref),
                "question_and_test_diff": diff,
                "mapping_uses": [dict(item) for item in mapping_uses],
                "protected_contracts": dict(protected_contracts),
            },
            "outcome": {
                "change_verified": True,
                "question_and_test_change_only": True,
                "current_factor_proof_authority": False,
                "canonical_memory_write_authority": False,
            },
        },
    )
    change_receipt = with_content_hash(
        {
            "contract_version": EVO_V2_TRANSFER_USE_CHANGE_RECEIPT_TYPE,
            "authority": "host_attested_question_and_test_change_only",
            "artifact_identity": dict(transfer_bundle.get("artifact_identity") or {}),
            "transfer_bundle_ref": transfer_bundle_ref,
            "transfer_use_receipt_ref": transfer_use_receipt_ref,
            "before_research_plan_ref": dict(before_research_plan_ref),
            "after_research_plan_ref": dict(after_research_plan_ref),
            "question_and_test_diff": diff,
            "mapping_uses": [dict(item) for item in mapping_uses],
            "protected_contracts": dict(protected_contracts),
            "host_change_attestation": host_attestation,
            "authority_guard": {
                "actual_before_after_readback_required": True,
                "protected_contracts_unchanged": True,
                "current_factor_proof_authority": False,
                "canonical_memory_write_authority": False,
            },
        },
        hash_field="change_receipt_sha256",
    )
    reasons = _evo_v2_transfer_use_change_receipt_reasons(
        change_receipt,
        transfer_bundle=transfer_bundle,
        transfer_receipt=transfer_receipt,
        trust_store=trust_store,
        workspace=workspace,
        verify_refs=True,
    )
    if reasons:
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *reasons)
    return change_receipt


def validate_evo_v2_memory_admission(
    admission: Any,
    *,
    trust_store: Any,
    workspace: Path | None = None,
    verify_refs: bool = True,
) -> list[str]:
    """Validate an EVO V2 persistence envelope against the core contracts."""

    from factor_factory.evo_v2 import (
        EXPERIENCE_TRANSFER_BUNDLE_VERSION,
        TRANSFER_USE_RECEIPT_VERSION,
        evo_v2_relative_paths,
        validate_experience_transfer_bundle,
        validate_transfer_use_receipt,
    )
    from factor_factory.researcher_memory_review import (
        build_evo_v2_memory_review_projection,
        validate_evo_v2_memory_review_decision,
    )

    if not isinstance(admission, Mapping):
        return [f"{BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID}:object"]
    expected_fields = {
        "contract_version",
        "admission_id",
        "state",
        "authority",
        "artifact_identity",
        "experience_transfer_bundle_ref",
        "transfer_use_receipt_ref",
        "core_payloads",
        "admitted_experience_ids",
        "review_gate",
        "authority_guard",
        "host_admission_receipt",
        "admission_sha256",
    }
    reasons: list[str] = []
    if set(admission) != expected_fields:
        reasons.append("fields")
    if admission.get("contract_version") != EVO_V2_MEMORY_ADMISSION_CONTRACT_VERSION:
        reasons.append("contract_version")
    if admission.get("state") != "host_private_admitted_historical_advisory":
        reasons.append("state")
    if admission.get("authority") != "core_evo_v2_payload_only":
        reasons.append("authority")
    if admission.get("authority_guard") != _EVO_V2_ADMISSION_AUTHORITY_GUARD:
        reasons.append("authority_guard")
    core_payloads = admission.get("core_payloads")
    if not isinstance(core_payloads, Mapping) or set(core_payloads) != {
        "experience_transfer_bundle",
        "transfer_use_receipt",
    }:
        reasons.append("core_payloads_fields")
        core_payloads = {}
    transfer_bundle = core_payloads.get("experience_transfer_bundle")
    transfer_receipt = core_payloads.get("transfer_use_receipt")
    if not isinstance(transfer_bundle, Mapping):
        reasons.append("experience_transfer_bundle_object")
        transfer_bundle = {}
    if not isinstance(transfer_receipt, Mapping):
        reasons.append("transfer_use_receipt_object")
        transfer_receipt = {}
    if transfer_bundle.get("contract_version") != EXPERIENCE_TRANSFER_BUNDLE_VERSION:
        reasons.append("experience_transfer_bundle_contract")
    if transfer_receipt.get("contract_version") != TRANSFER_USE_RECEIPT_VERSION:
        reasons.append("transfer_use_receipt_contract")
    reasons.extend(
        f"core_experience_transfer_bundle:{reason}"
        for reason in validate_experience_transfer_bundle(
            transfer_bundle,
            workspace_root=workspace,
            verify_refs=verify_refs,
        )
    )
    reasons.extend(
        f"core_transfer_use_receipt:{reason}"
        for reason in validate_transfer_use_receipt(
            transfer_receipt,
            transfer_bundle=transfer_bundle,
            workspace_root=workspace,
            verify_refs=verify_refs,
        )
    )
    identity = transfer_bundle.get("artifact_identity")
    if (
        admission.get("artifact_identity") != identity
        or transfer_receipt.get("artifact_identity") != identity
    ):
        reasons.append("artifact_identity_binding")
    report_id = str((identity or {}).get("report_id") or "")
    try:
        expected_paths = evo_v2_relative_paths(report_id)
    except Exception:
        expected_paths = {}
        reasons.append("report_id")
    bundle_ref = admission.get("experience_transfer_bundle_ref")
    receipt_ref = admission.get("transfer_use_receipt_ref")
    for label, reference, expected_path in (
        (
            "experience_transfer_bundle",
            bundle_ref,
            expected_paths.get("experience_transfer_bundle"),
        ),
        (
            "transfer_use_receipt",
            receipt_ref,
            expected_paths.get("transfer_use_receipt"),
        ),
    ):
        if (
            not isinstance(reference, Mapping)
            or set(reference) != {"path", "sha256"}
            or reference.get("path") != expected_path
            or not SHA256_RE.fullmatch(str(reference.get("sha256") or ""))
        ):
            reasons.append(f"{label}_ref")
    if workspace is not None and verify_refs:
        try:
            observed_bundle = _evo_v2_workspace_payload(
                workspace=workspace,
                reference=bundle_ref if isinstance(bundle_ref, Mapping) else {},
                label="experience_transfer_bundle",
            )
            observed_receipt = _evo_v2_workspace_payload(
                workspace=workspace,
                reference=receipt_ref if isinstance(receipt_ref, Mapping) else {},
                label="transfer_use_receipt",
            )
        except ResearchOrganizationError as exc:
            reasons.extend(exc.reasons)
        else:
            if observed_bundle != transfer_bundle:
                reasons.append("experience_transfer_bundle_payload_binding")
            if observed_receipt != transfer_receipt:
                reasons.append("transfer_use_receipt_payload_binding")
    experiences = transfer_bundle.get("experiences")
    expected_experience_ids = (
        [str(item.get("experience_id") or "") for item in experiences]
        if isinstance(experiences, list)
        and all(isinstance(item, Mapping) for item in experiences)
        else []
    )
    if admission.get("admitted_experience_ids") != expected_experience_ids:
        reasons.append("admitted_experience_ids")
    review_gate = admission.get("review_gate")
    if not isinstance(review_gate, Mapping) or set(review_gate) != {
        "decision_receipt",
        "cold_start_search_receipt_ref",
        "cold_start_search_receipt",
        "transfer_use_change_receipt",
    }:
        reasons.append("review_gate_fields")
        review_gate = {}
    decision_receipt = review_gate.get("decision_receipt")
    cold_start_search_receipt_ref = review_gate.get(
        "cold_start_search_receipt_ref"
    )
    cold_start_search_receipt = review_gate.get("cold_start_search_receipt")
    transfer_use_change_receipt = review_gate.get(
        "transfer_use_change_receipt"
    )
    review_projection: Mapping[str, Any] = {}
    try:
        review_projection = build_evo_v2_memory_review_projection(
            experience_transfer_bundle=transfer_bundle,
            transfer_use_receipt=transfer_receipt,
            experience_transfer_bundle_ref=(
                bundle_ref if isinstance(bundle_ref, Mapping) else {}
            ),
            transfer_use_receipt_ref=(
                receipt_ref if isinstance(receipt_ref, Mapping) else {}
            ),
            trust_store=trust_store,
            source_workspace=(workspace if verify_refs else None),
            cold_start_search_receipt_ref=(
                cold_start_search_receipt_ref
                if isinstance(cold_start_search_receipt_ref, Mapping)
                else None
            ),
            cold_start_search_receipt=(
                cold_start_search_receipt
                if isinstance(cold_start_search_receipt, Mapping)
                else None
            ),
        )
    except (ResearchOrganizationError, KeyError, TypeError, ValueError) as exc:
        detail = exc.token if isinstance(exc, ResearchOrganizationError) else type(exc).__name__
        reasons.append(f"review_projection:{detail}")
    else:
        reasons.extend(
            f"review_decision:{reason}"
            for reason in validate_evo_v2_memory_review_decision(
                decision_receipt,
                projection=review_projection,
                trust_store=trust_store,
            )
        )
    cold_start = (
        isinstance(transfer_bundle.get("retrieval_policy"), Mapping)
        and transfer_bundle["retrieval_policy"].get("memory_state")
        == "COLD_START_NO_ADMISSIBLE_MEMORY"
    )
    if cold_start:
        if transfer_use_change_receipt is not None:
            reasons.append("transfer_use_change_receipt_for_cold_start")
    else:
        reasons.extend(
            f"transfer_use_change:{reason}"
            for reason in _evo_v2_transfer_use_change_receipt_reasons(
                transfer_use_change_receipt,
                transfer_bundle=transfer_bundle,
                transfer_receipt=transfer_receipt,
                trust_store=trust_store,
                workspace=workspace,
                verify_refs=verify_refs,
            )
        )
    host_receipt = admission.get("host_admission_receipt")
    host_receipt_reasons: list[str] = []
    if trust_store is None or not hasattr(trust_store, "verify"):
        host_receipt_reasons.append("host_admission_trust_store")
    elif not isinstance(host_receipt, Mapping):
        host_receipt_reasons.append("host_admission_receipt_object")
    else:
        host_receipt_reasons.extend(
            trust_store.verify(
                host_receipt,
                expected_issuer="host_admission",
            )
        )
        if (
            set(host_receipt)
            != {
                "contract_version",
                "receipt_type",
                "identity",
                "bindings",
                "outcome",
                "issuer",
                "receipt_id",
                "signature",
            }
            or host_receipt.get("receipt_type")
            != EVO_V2_MEMORY_ADMISSION_RECEIPT_TYPE
            or host_receipt.get("identity") != identity
            or host_receipt.get("bindings")
            != {
                "experience_transfer_bundle_ref": bundle_ref,
                "experience_transfer_bundle_content_sha256": transfer_bundle.get(
                    "content_sha256"
                ),
                "transfer_use_receipt_ref": receipt_ref,
                "transfer_use_receipt_content_sha256": transfer_receipt.get(
                    "content_sha256"
                ),
                "admitted_experience_ids": expected_experience_ids,
                "review_projection_sha256": review_projection.get(
                    "projection_sha256"
                ),
                "review_decision_sha256": (
                    decision_receipt.get("decision_sha256")
                    if isinstance(decision_receipt, Mapping)
                    else None
                ),
                "reviewer_adapter_completion_receipt_id": (
                    (
                        (decision_receipt.get("runtime_evidence") or {}).get(
                            "adapter_completion_receipt"
                        )
                        or {}
                    ).get("receipt_id")
                    if isinstance(decision_receipt, Mapping)
                    else None
                ),
                "reviewer_session_id": (
                    (decision_receipt.get("reviewer") or {}).get(
                        "reviewer_session_id"
                    )
                    if isinstance(decision_receipt, Mapping)
                    else None
                ),
                "reviewer_runtime_instance_id": (
                    (decision_receipt.get("reviewer") or {}).get(
                        "runtime_instance_id"
                    )
                    if isinstance(decision_receipt, Mapping)
                    else None
                ),
                "cold_start_search_receipt_id": (
                    cold_start_search_receipt.get("receipt_id")
                    if isinstance(cold_start_search_receipt, Mapping)
                    else None
                ),
                "transfer_use_change_receipt_sha256": (
                    transfer_use_change_receipt.get("change_receipt_sha256")
                    if isinstance(transfer_use_change_receipt, Mapping)
                    else None
                ),
            }
            or host_receipt.get("outcome")
            != {
                "state": "host_private_admitted_historical_advisory",
                "authority": "core_evo_v2_payload_only",
                "review_gate": "RUNTIME_ATTESTED_PASS",
                "current_factor_proof_authority": False,
                "canonical_factor_write_authority": False,
            }
        ):
            host_receipt_reasons.append("host_admission_receipt_binding")
    reasons.extend(host_receipt_reasons)
    core = {
        key: value
        for key, value in admission.items()
        if key not in {"contract_version", "admission_id", "admission_sha256"}
    }
    if admission.get("admission_id") != f"evo2_admission_{stable_json_hash(core)[:24]}":
        reasons.append("admission_id_content_binding")
    if _contains_absolute_path(admission):
        reasons.append("absolute_path_disclosure")
    reasons.extend(
        validate_content_hash(
            admission,
            hash_field="admission_sha256",
            label="evo_v2_memory_admission",
        )
    )
    return [f"{BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID}:{reason}" for reason in reasons]


def build_evo_v2_memory_admission(
    *,
    workspace: Path,
    experience_transfer_bundle_ref: Mapping[str, Any],
    transfer_use_receipt_ref: Mapping[str, Any],
    review_decision_receipt: Mapping[str, Any],
    trust_store: Any,
    cold_start_search_receipt_ref: Mapping[str, Any] | None = None,
    cold_start_search_receipt: Mapping[str, Any] | None = None,
    transfer_use_change_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve(strict=True)
    transfer_bundle = _evo_v2_workspace_payload(
        workspace=workspace,
        reference=experience_transfer_bundle_ref,
        label="experience_transfer_bundle",
    )
    transfer_receipt = _evo_v2_workspace_payload(
        workspace=workspace,
        reference=transfer_use_receipt_ref,
        label="transfer_use_receipt",
    )
    experiences = transfer_bundle.get("experiences") or []
    admitted_experience_ids = [
        str(item.get("experience_id") or "")
        for item in experiences
        if isinstance(item, Mapping)
    ]
    from factor_factory.researcher_memory_review import (
        build_evo_v2_memory_review_projection,
        validate_evo_v2_memory_review_decision,
    )

    review_projection = build_evo_v2_memory_review_projection(
        experience_transfer_bundle=transfer_bundle,
        transfer_use_receipt=transfer_receipt,
        experience_transfer_bundle_ref=experience_transfer_bundle_ref,
        transfer_use_receipt_ref=transfer_use_receipt_ref,
        trust_store=trust_store,
        source_workspace=workspace,
        cold_start_search_receipt_ref=cold_start_search_receipt_ref,
        cold_start_search_receipt=cold_start_search_receipt,
    )
    review_reasons = validate_evo_v2_memory_review_decision(
        review_decision_receipt,
        projection=review_projection,
        trust_store=trust_store,
    )
    if review_reasons:
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *review_reasons)
    cold_start = (
        transfer_bundle.get("retrieval_policy", {}).get("memory_state")
        == "COLD_START_NO_ADMISSIBLE_MEMORY"
    )
    if cold_start:
        if transfer_use_change_receipt is not None:
            _raise(
                BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID,
                "transfer_use_change_receipt_for_cold_start",
            )
    else:
        change_reasons = _evo_v2_transfer_use_change_receipt_reasons(
            transfer_use_change_receipt,
            transfer_bundle=transfer_bundle,
            transfer_receipt=transfer_receipt,
            trust_store=trust_store,
            workspace=workspace,
            verify_refs=True,
        )
        if change_reasons:
            _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *change_reasons)
    if trust_store is None or not hasattr(trust_store, "sign"):
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, "host_admission_trust_store")
    host_admission_receipt = trust_store.sign(
        "host_admission",
        {
            "receipt_type": EVO_V2_MEMORY_ADMISSION_RECEIPT_TYPE,
            "identity": dict(transfer_bundle.get("artifact_identity") or {}),
            "bindings": {
                "experience_transfer_bundle_ref": dict(
                    experience_transfer_bundle_ref
                ),
                "experience_transfer_bundle_content_sha256": transfer_bundle.get(
                    "content_sha256"
                ),
                "transfer_use_receipt_ref": dict(transfer_use_receipt_ref),
                "transfer_use_receipt_content_sha256": transfer_receipt.get(
                    "content_sha256"
                ),
                "admitted_experience_ids": admitted_experience_ids,
                "review_projection_sha256": review_projection[
                    "projection_sha256"
                ],
                "review_decision_sha256": review_decision_receipt[
                    "decision_sha256"
                ],
                "reviewer_adapter_completion_receipt_id": (
                    review_decision_receipt["runtime_evidence"][
                        "adapter_completion_receipt"
                    ]["receipt_id"]
                ),
                "reviewer_session_id": review_decision_receipt["reviewer"][
                    "reviewer_session_id"
                ],
                "reviewer_runtime_instance_id": review_decision_receipt[
                    "reviewer"
                ]["runtime_instance_id"],
                "cold_start_search_receipt_id": (
                    cold_start_search_receipt.get("receipt_id")
                    if isinstance(cold_start_search_receipt, Mapping)
                    else None
                ),
                "transfer_use_change_receipt_sha256": (
                    transfer_use_change_receipt.get("change_receipt_sha256")
                    if isinstance(transfer_use_change_receipt, Mapping)
                    else None
                ),
            },
            "outcome": {
                "state": "host_private_admitted_historical_advisory",
                "authority": "core_evo_v2_payload_only",
                "review_gate": "RUNTIME_ATTESTED_PASS",
                "current_factor_proof_authority": False,
                "canonical_factor_write_authority": False,
            },
        },
    )
    core = {
        "state": "host_private_admitted_historical_advisory",
        "authority": "core_evo_v2_payload_only",
        "artifact_identity": dict(transfer_bundle.get("artifact_identity") or {}),
        "experience_transfer_bundle_ref": dict(experience_transfer_bundle_ref),
        "transfer_use_receipt_ref": dict(transfer_use_receipt_ref),
        "core_payloads": {
            "experience_transfer_bundle": dict(transfer_bundle),
            "transfer_use_receipt": dict(transfer_receipt),
        },
        "admitted_experience_ids": admitted_experience_ids,
        "review_gate": {
            "decision_receipt": dict(review_decision_receipt),
            "cold_start_search_receipt_ref": (
                dict(cold_start_search_receipt_ref)
                if isinstance(cold_start_search_receipt_ref, Mapping)
                else None
            ),
            "cold_start_search_receipt": (
                dict(cold_start_search_receipt)
                if isinstance(cold_start_search_receipt, Mapping)
                else None
            ),
            "transfer_use_change_receipt": (
                dict(transfer_use_change_receipt)
                if isinstance(transfer_use_change_receipt, Mapping)
                else None
            ),
        },
        "authority_guard": dict(_EVO_V2_ADMISSION_AUTHORITY_GUARD),
        "host_admission_receipt": host_admission_receipt,
    }
    admission = with_content_hash(
        {
            "contract_version": EVO_V2_MEMORY_ADMISSION_CONTRACT_VERSION,
            "admission_id": f"evo2_admission_{stable_json_hash(core)[:24]}",
            **core,
        },
        hash_field="admission_sha256",
    )
    reasons = validate_evo_v2_memory_admission(
        admission,
        trust_store=trust_store,
        workspace=workspace,
        verify_refs=True,
    )
    if reasons:
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *reasons)
    return admission


def persist_evo_v2_memory_admission(
    *,
    root: Path,
    admission: Mapping[str, Any],
    repo_root: Path,
    workspace: Path,
    trust_store: Any,
) -> dict[str, Any]:
    """Persist one immutable envelope in a v1-disjoint Host-private sidecar."""

    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=workspace,
        create=True,
    )
    reasons = validate_evo_v2_memory_admission(
        admission,
        trust_store=trust_store,
        workspace=workspace,
        verify_refs=True,
    )
    if reasons:
        _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *reasons)
    _ensure_private_directory(resolved, "admissions")
    _ensure_private_directory(resolved, _TEMP_DIR_NAME)
    relative = f"admissions/{admission['admission_id']}.json"
    with _store_lock(resolved):
        layout_reasons = _evo_v2_sidecar_layout_reasons(resolved)
        if layout_reasons:
            _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *layout_reasons)
        path, written = _atomic_store_json(
            resolved,
            relative,
            admission,
            replace=False,
        )
        observed = _read_store_json(resolved, relative)
        if observed != admission:
            _raise(BLOCK_MEMORY_WRITE_CONFLICT, "evo_v2_admission_readback")
    return {
        "admission_id": admission["admission_id"],
        "admission_sha256": admission["admission_sha256"],
        "relative_path": relative,
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "written": written,
        "semantic_authority": "factor_factory.evo_v2",
    }


def load_evo_v2_memory_admissions(
    *,
    root: Path,
    repo_root: Path,
    trust_store: Any,
    source_workspace: Path | None = None,
) -> list[dict[str, Any]]:
    resolved = _assert_private_root(
        root,
        repo_root=repo_root,
        workspace=source_workspace,
        create=False,
    )
    with _store_lock(resolved, create=False):
        layout_reasons = _evo_v2_sidecar_layout_reasons(resolved)
        if layout_reasons:
            _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *layout_reasons)
        admission_root = resolved / "admissions"
        admissions: list[dict[str, Any]] = []
        for path in sorted(admission_root.iterdir(), key=lambda item: item.name):
            if (
                not path.is_file()
                or path.is_symlink()
                or not re.fullmatch(r"evo2_admission_[0-9a-f]{24}\.json", path.name)
            ):
                _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, "admission_file")
            relative = path.relative_to(resolved).as_posix()
            admission = _read_store_json(resolved, relative)
            reasons = validate_evo_v2_memory_admission(
                admission,
                trust_store=trust_store,
                workspace=source_workspace,
                verify_refs=source_workspace is not None,
            )
            if reasons:
                _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, *reasons)
            if path.name != f"{admission['admission_id']}.json":
                _raise(BLOCK_MEMORY_EVO_V2_ADMISSION_INVALID, "admission_path_binding")
            admissions.append(admission)
    return admissions
