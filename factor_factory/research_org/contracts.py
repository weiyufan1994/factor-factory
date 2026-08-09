from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from factor_factory.research_workspace import assert_path_under_workspace

RESEARCH_ORG_PLAN_CONTRACT_VERSION = "factorforge_research_org_plan_v1"
AGENT_REGISTRY_CONTRACT_VERSION = "factorforge_agent_registry_v1"
AGENT_TASK_CONTRACT_VERSION = "factorforge_agent_task_v1"
AGENT_RESULT_CONTRACT_VERSION = "factorforge_agent_result_v1"
DOMAIN_PROPOSAL_CONTRACT_VERSION = "factorforge_domain_research_proposal_v1"
ROLE_RESEARCH_RECORD_CONTRACT_VERSION = "factorforge_role_research_record_v1"
KNOWLEDGE_PRIOR_RECORD_CONTRACT_VERSION = (
    "factorforge_knowledge_prior_record_v1"
)
DISPATCH_MANIFEST_CONTRACT_VERSION = "factorforge_research_org_dispatch_v1"
RUNTIME_STATE_CONTRACT_VERSION = "factorforge_research_org_runtime_state_v1"
RUNTIME_EVENT_CONTRACT_VERSION = "factorforge_research_org_runtime_event_v1"
RUNTIME_ATTEMPT_CONTRACT_VERSION = "factorforge_agent_runtime_attempt_v1"
RUNTIME_CONTEXT_CONTRACT_VERSION = "factorforge_agent_runtime_context_v1"
SESSION_RECEIPT_CONTRACT_VERSION = "factorforge_agent_session_receipt_v1"
PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION = "factorforge_agent_private_output_v1"

MAX_CONTRACT_JSON_BYTES = 16 * 1024 * 1024
MAX_CONTRACT_JSON_DEPTH = 64
MAX_CONTRACT_JSON_NODES = 250_000

BLOCK_RESEARCH_ORG_PLAN_MISSING = "BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_MISSING"
BLOCK_RESEARCH_ORG_PLAN_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_INVALID"
BLOCK_RESEARCH_ORG_IDENTITY_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_IDENTITY_INVALID"
BLOCK_RESEARCH_ORG_PATH_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_PATH_INVALID"
BLOCK_RESEARCH_ORG_REGISTRY_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_REGISTRY_INVALID"
BLOCK_RESEARCH_ORG_ROUTE_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_ROUTE_INVALID"
BLOCK_RESEARCH_ORG_TASK_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_TASK_INVALID"
BLOCK_RESEARCH_ORG_RESULT_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_RESULT_INVALID"
BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_INDEPENDENCE_INVALID"
BLOCK_RESEARCH_ORG_RUNTIME_MISSING = "BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_MISSING"
BLOCK_RESEARCH_ORG_RUNTIME_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_INVALID"
BLOCK_RESEARCH_ORG_SESSION_FAILED = "BLOCK_FACTORFORGE_RESEARCH_ORG_SESSION_FAILED"
BLOCK_RESEARCH_ORG_SESSION_RECEIPT_INVALID = (
    "BLOCK_FACTORFORGE_RESEARCH_ORG_SESSION_RECEIPT_INVALID"
)
BLOCK_RESEARCH_ORG_RUNTIME_CANCELLED = "BLOCK_FACTORFORGE_RESEARCH_ORG_RUNTIME_CANCELLED"

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
PRIVATE_REASONING_KEYS = {
    "chain_of_thought",
    "chainofthought",
    "cot",
    "hidden_reasoning",
    "private_reasoning",
    "reasoning_trace",
    "scratchpad",
}


class ResearchOrganizationError(RuntimeError):
    """A fail-closed research-organization contract violation."""

    def __init__(self, token: str, reasons: Iterable[str]) -> None:
        self.token = token
        self.reasons = tuple(str(reason) for reason in reasons if str(reason))
        super().__init__(f"{token}: {'; '.join(self.reasons)}")


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def content_hash(payload: Mapping[str, Any], *, hash_field: str) -> str:
    unsigned = dict(payload)
    unsigned.pop(hash_field, None)
    return stable_json_hash(unsigned)


def with_content_hash(payload: Mapping[str, Any], *, hash_field: str) -> dict[str, Any]:
    output = dict(payload)
    output.pop(hash_field, None)
    output[hash_field] = stable_json_hash(output)
    return output


def validate_content_hash(
    payload: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> list[str]:
    actual = payload.get(hash_field)
    if not isinstance(actual, str) or not SHA256_RE.fullmatch(actual):
        return [f"{label}.{hash_field}"]
    expected = content_hash(payload, hash_field=hash_field)
    return [] if actual == expected else [f"{label}.{hash_field}_mismatch"]


def validate_identity_value(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value) or ".." in value:
        return [f"{label}={value!r}"]
    return []


def normalize_workspace_relative_path(
    raw: Any,
    *,
    workspace: Path,
    label: str,
    allow_directory: bool = False,
) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PATH_INVALID, [f"{label}:missing"])
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PATH_INVALID, [f"{label}:{raw}"])
    if not allow_directory and raw.endswith("/"):
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PATH_INVALID, [f"{label}:{raw}"])
    resolved = workspace / candidate
    try:
        assert_path_under_workspace(resolved, workspace, label=label)
    except ValueError as exc:
        raise ResearchOrganizationError(BLOCK_RESEARCH_ORG_PATH_INVALID, [str(exc)]) from exc
    return candidate.as_posix()


def _validated_relative_parts(relative: str) -> tuple[str, ...]:
    path = Path(relative)
    if (
        not relative
        or path.is_absolute()
        or path == Path(".")
        or ".." in path.parts
    ):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unsafe_relative_path:{relative}"],
        )
    return path.parts


def _open_absolute_directory_fd(path: Path) -> int:
    if not path.is_absolute():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"workspace_not_absolute:{path}"],
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"workspace_not_directory:{path}"],
            )
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _open_workspace_parent_fd(
    workspace: Path,
    relative: str,
    *,
    create_parents: bool,
) -> Iterator[tuple[int, str]]:
    parts = _validated_relative_parts(relative)
    descriptor = _open_absolute_directory_fd(workspace)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        try:
            for part in parts[:-1]:
                try:
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create_parents:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
        except OSError as exc:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"unsafe_parent:{relative}"],
            ) from exc
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def _read_stable_file_at(
    parent_descriptor: int,
    name: str,
    *,
    relative: str,
    max_bytes: int,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unsafe_or_missing:{relative}"],
        ) from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size < 0
            or before.st_size > max_bytes
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"unsafe_or_oversized:{relative}"],
            )
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
        path_after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        path_identity = (
            path_after.st_dev,
            path_after.st_ino,
            path_after.st_size,
            path_after.st_mtime_ns,
            path_after.st_ctime_ns,
        )
        if (
            before_identity != after_identity
            or after_identity != path_identity
            or len(payload) != before.st_size
        ):
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"changed_while_reading:{relative}"],
            )
        return payload
    except OSError as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"changed_while_reading:{relative}"],
        ) from exc
    finally:
        os.close(descriptor)


def read_workspace_bytes(
    workspace: Path,
    relative_path: str,
    *,
    max_bytes: int = MAX_CONTRACT_JSON_BYTES,
) -> bytes:
    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="read_bytes",
    )
    with _open_workspace_parent_fd(
        workspace,
        relative,
        create_parents=False,
    ) as (parent_descriptor, name):
        return _read_stable_file_at(
            parent_descriptor,
            name,
            relative=relative,
            max_bytes=max_bytes,
        )


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate_json_key:{key}")
        output[key] = value
    return output


def _reject_non_finite_json(value: str) -> None:
    raise ValueError(f"non_finite_json:{value}")


def _validate_json_shape(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_CONTRACT_JSON_DEPTH or nodes > MAX_CONTRACT_JSON_NODES:
            raise ValueError("json_shape_budget")
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


def strict_json_loads(raw: bytes | str, *, label: str) -> Any:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_non_finite_json,
        )
        _validate_json_shape(payload)
        return payload
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unreadable_json:{label}"],
        ) from exc


def read_workspace_json(workspace: Path, relative_path: str) -> dict[str, Any]:
    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="read_json",
    )
    payload = strict_json_loads(
        read_workspace_bytes(workspace, relative),
        label=relative,
    )
    if not isinstance(payload, dict):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"json_object_required:{relative}"],
        )
    return payload


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            ["json_payload_not_canonical"],
        ) from exc


def _write_workspace_bytes(
    workspace: Path,
    relative: str,
    payload: bytes,
    *,
    replace: bool,
) -> Path:
    with _open_workspace_parent_fd(
        workspace,
        relative,
        create_parents=True,
    ) as (parent_descriptor, name):
        if not replace:
            try:
                os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError(relative)
        temporary = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
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
            while offset < len(payload):
                offset += os.write(descriptor, payload[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            if replace:
                os.rename(
                    temporary,
                    name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
            else:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        published = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(published.st_mode) or published.st_nlink != 1:
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"unsafe_published_file:{relative}"],
            )
    return workspace / relative


def write_workspace_json(workspace: Path, relative_path: str, payload: Mapping[str, Any]) -> Path:
    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="write_json",
    )
    return _write_workspace_bytes(
        workspace,
        relative,
        _json_bytes(payload),
        replace=True,
    )


def write_workspace_json_once(
    workspace: Path,
    relative_path: str,
    payload: Mapping[str, Any],
) -> Path:
    """Atomically publish a JSON object without replacing an existing path."""

    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="write_json_once",
    )
    return _write_workspace_bytes(
        workspace,
        relative,
        _json_bytes(payload),
        replace=False,
    )


@contextmanager
def workspace_file_lock(
    workspace: Path,
    relative_path: str,
) -> Iterator[None]:
    """Serialize Host mutations against an immutable workspace file."""

    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="workspace_lock",
    )
    with _open_workspace_parent_fd(
        workspace,
        relative,
        create_parents=False,
    ) as (parent_descriptor, name):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_PATH_INVALID,
                    [f"unsafe_lock_target:{relative}"],
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise ResearchOrganizationError(
                    BLOCK_RESEARCH_ORG_PATH_INVALID,
                    [f"lock_target_replaced:{relative}"],
                )
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def private_reasoning_paths(value: Any, *, prefix: str = "") -> list[str]:
    reasons: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            path = f"{prefix}.{key}" if prefix else str(key)
            if normalized in PRIVATE_REASONING_KEYS:
                reasons.append(path)
            reasons.extend(private_reasoning_paths(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            path = f"{prefix}[{index}]"
            reasons.extend(private_reasoning_paths(nested, prefix=path))
    return reasons
