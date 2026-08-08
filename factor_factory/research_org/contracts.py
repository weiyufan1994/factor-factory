from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
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
DISPATCH_MANIFEST_CONTRACT_VERSION = "factorforge_research_org_dispatch_v1"

BLOCK_RESEARCH_ORG_PLAN_MISSING = "BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_MISSING"
BLOCK_RESEARCH_ORG_PLAN_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_PLAN_INVALID"
BLOCK_RESEARCH_ORG_IDENTITY_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_IDENTITY_INVALID"
BLOCK_RESEARCH_ORG_PATH_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_PATH_INVALID"
BLOCK_RESEARCH_ORG_REGISTRY_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_REGISTRY_INVALID"
BLOCK_RESEARCH_ORG_ROUTE_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_ROUTE_INVALID"
BLOCK_RESEARCH_ORG_TASK_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_TASK_INVALID"
BLOCK_RESEARCH_ORG_RESULT_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_RESULT_INVALID"
BLOCK_RESEARCH_ORG_INDEPENDENCE_INVALID = "BLOCK_FACTORFORGE_RESEARCH_ORG_INDEPENDENCE_INVALID"

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


def read_workspace_json(workspace: Path, relative_path: str) -> dict[str, Any]:
    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="read_json",
    )
    path = workspace / relative
    if not path.is_file() or path.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unsafe_or_missing:{relative}"],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unreadable_json:{relative}"],
        ) from exc
    if not isinstance(payload, dict):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"json_object_required:{relative}"],
        )
    return payload


def write_workspace_json(workspace: Path, relative_path: str, payload: Mapping[str, Any]) -> Path:
    relative = normalize_workspace_relative_path(
        relative_path,
        workspace=workspace,
        label="write_json",
    )
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unsafe_write_target:{relative}"],
        )
    for parent in (path.parent, *path.parent.parents):
        if parent == workspace.parent:
            break
        if parent.is_symlink():
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"symlink_parent:{parent}"],
            )
        if parent == workspace:
            break
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


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
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unsafe_write_target:{relative}"],
        )
    for parent in (path.parent, *path.parent.parents):
        if parent == workspace.parent:
            break
        if parent.is_symlink():
            raise ResearchOrganizationError(
                BLOCK_RESEARCH_ORG_PATH_INVALID,
                [f"symlink_parent:{parent}"],
            )
        if parent == workspace:
            break
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


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
    path = workspace / relative
    if not path.is_file() or path.is_symlink():
        raise ResearchOrganizationError(
            BLOCK_RESEARCH_ORG_PATH_INVALID,
            [f"unsafe_lock_target:{relative}"],
        )
    with path.open("rb") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
