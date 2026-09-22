from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping


CONVERSATION_LEDGER_CHECKPOINT_VERSION = (
    "factorforge_console_conversation_ledger_checkpoint_v1"
)
CONVERSATION_LEDGER_REFERENCE_VERSION = (
    "factorforge_console_conversation_ledger_reference_v1"
)
CONVERSATION_MESSAGE_VERSION = "factorforge_console_conversation_message_v1"
CONVERSATION_CHAIN_VERSION = "factorforge_console_conversation_chain_v1"
CONVERSATION_LEDGER_MAX_MESSAGES = 500
CONVERSATION_LEDGER_MAX_CHARACTERS = 4_000_000
CONVERSATION_LEDGER_DIRECTORY = "identity/conversation_ledger"
CONVERSATION_LEDGER_REFERENCE_FIELD = "conversation_ledger_checkpoint"
ZERO_SHA256 = "0" * 64

BLOCK_CONVERSATION_LEDGER_INVALID = (
    "BLOCK_FACTORFORGE_CONSOLE_CONVERSATION_LEDGER_INVALID"
)


def stable_json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid(detail: str) -> RuntimeError:
    return RuntimeError(f"{BLOCK_CONVERSATION_LEDGER_INVALID}: {detail}")


def _valid_attestation_id(value: Any, *, job_id: str) -> bool:
    candidate = Path(str(value or ""))
    return bool(
        not candidate.is_absolute()
        and candidate.parts[:2] == ("attestations", job_id)
        and len(candidate.parts) == 3
        and re.fullmatch(
            r"attestation_[A-Za-z0-9_-]{1,160}\.json",
            candidate.name,
        )
    )


def _message_payload(message: Mapping[str, Any] | Any) -> dict[str, Any]:
    def value(field: str) -> Any:
        if isinstance(message, Mapping):
            return message.get(field)
        return getattr(message, field, None)

    payload = {
        "version": CONVERSATION_MESSAGE_VERSION,
        "message_id": str(value("message_id") or ""),
        "sequence_no": int(value("sequence_no") or 0),
        "role": str(value("role") or ""),
        "content_kind": str(value("content_kind") or ""),
        "content": str(value("content") or "").strip(),
        "model": str(value("model") or ""),
        "created_at_utc": str(value("created_at_utc") or ""),
    }
    if (
        not re.fullmatch(r"msg_[A-Za-z0-9_-]{2,128}", payload["message_id"])
        or payload["sequence_no"] < 1
        or payload["role"] not in {"user", "assistant"}
        or not payload["content_kind"]
        or not payload["content"]
        or not payload["created_at_utc"]
    ):
        raise _invalid("message identity or content is invalid")
    return payload


def _ledger_entries(messages: Iterable[Mapping[str, Any] | Any]) -> list[dict[str, Any]]:
    payloads = [_message_payload(message) for message in messages]
    if not payloads:
        raise _invalid("conversation ledger cannot be empty")
    if len(payloads) > CONVERSATION_LEDGER_MAX_MESSAGES:
        raise _invalid("message count exceeds the checkpoint budget")
    if sum(len(item["content"]) for item in payloads) > CONVERSATION_LEDGER_MAX_CHARACTERS:
        raise _invalid("message content exceeds the checkpoint budget")
    if [item["sequence_no"] for item in payloads] != list(
        range(1, len(payloads) + 1)
    ):
        raise _invalid("message sequence is not contiguous")
    if len({item["message_id"] for item in payloads}) != len(payloads):
        raise _invalid("message identity is not unique")

    previous = ZERO_SHA256
    entries: list[dict[str, Any]] = []
    for payload in payloads:
        message_sha256 = stable_json_hash(payload)
        chain_sha256 = stable_json_hash(
            {
                "version": CONVERSATION_CHAIN_VERSION,
                "previous_chain_sha256": previous,
                "message_sha256": message_sha256,
                "sequence_no": payload["sequence_no"],
            }
        )
        entries.append(
            {
                **payload,
                "message_sha256": message_sha256,
                "previous_chain_sha256": previous,
                "chain_sha256": chain_sha256,
            }
        )
        previous = chain_sha256
    return entries


def _checkpoint_relative(message_count: int, root_sha256: str) -> str:
    return (
        f"{CONVERSATION_LEDGER_DIRECTORY}/"
        f"checkpoint__{message_count:06d}__{root_sha256}.json"
    )


def _checkpoint_reference(relative: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": CONVERSATION_LEDGER_REFERENCE_VERSION,
        "path": relative,
        "sha256": stable_json_hash(payload),
        "root_sha256": payload["root_sha256"],
        "message_count": payload["message_count"],
    }


def _build_checkpoint(
    *,
    job_id: str,
    messages: Iterable[Mapping[str, Any] | Any],
    source: str,
    parent_reference: dict[str, Any] | None,
    parent_payload: dict[str, Any] | None,
    parent_attestation_id: str,
    parent_attestation_sha256: str,
    legacy_request_sha256: str = "",
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    entries = _ledger_entries(messages)
    root_sha256 = entries[-1]["chain_sha256"] if entries else ZERO_SHA256
    if parent_payload is not None:
        if parent_reference is None:
            raise _invalid("parent checkpoint reference is missing")
        parent_entries = parent_payload.get("entries")
        if (
            not isinstance(parent_entries, list)
            or len(parent_entries) >= len(entries)
            or entries[: len(parent_entries)] != parent_entries
            or not re.fullmatch(r"[0-9a-f]{64}", parent_attestation_sha256)
            or not _valid_attestation_id(
                parent_attestation_id,
                job_id=job_id,
            )
        ):
            raise _invalid("checkpoint does not extend the attested parent")
        parent = {
            **parent_reference,
            "attestation_id": parent_attestation_id,
            "attestation_sha256": parent_attestation_sha256,
        }
    else:
        parent = None
    payload = {
        "version": CONVERSATION_LEDGER_CHECKPOINT_VERSION,
        "job_id": job_id,
        "source": source,
        "message_count": len(entries),
        "root_sha256": root_sha256,
        "entries": entries,
        "parent_checkpoint": parent,
        "legacy_request_sha256": legacy_request_sha256,
    }
    relative = _checkpoint_relative(len(entries), root_sha256)
    return relative, payload, _checkpoint_reference(relative, payload)


def _safe_checkpoint_path(workspace: Path, relative: str, *, must_exist: bool) -> Path:
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or len(relative_path.parts) != 3
        or relative_path.parts[:2] != ("identity", "conversation_ledger")
        or not re.fullmatch(
            r"checkpoint__[0-9]{6}__[0-9a-f]{64}\.json",
            relative_path.name,
        )
    ):
        raise _invalid("checkpoint path is unsafe")
    root = workspace.resolve(strict=True)
    candidate = root / relative_path
    current = root
    for part in relative_path.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise _invalid("checkpoint parent uses a symlink")
    if must_exist:
        if candidate.is_symlink():
            raise _invalid("checkpoint file uses a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _invalid("checkpoint file is missing or unavailable") from exc
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise _invalid("checkpoint escapes the workspace") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise _invalid("checkpoint is not a regular file")
        return resolved
    return candidate


def write_planned_checkpoints(
    workspace: Path,
    planned: Iterable[tuple[str, dict[str, Any]]],
) -> None:
    planned_items = list(planned)
    if not planned_items:
        return
    root = workspace.resolve(strict=True)
    directory = _ensure_ledger_directory(root)
    for relative, payload in planned_items:
        path = _safe_checkpoint_path(root, relative, must_exist=False)
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        expected_sha256 = stable_json_hash(payload)
        if path.exists() or path.is_symlink():
            if (
                not path.is_file()
                or path.is_symlink()
                or sha256_file(path) != hashlib.sha256(encoded).hexdigest()
            ):
                raise _invalid("existing checkpoint does not match planned content")
            continue
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if stable_json_hash(json.loads(temporary.read_text(encoding="utf-8"))) != expected_sha256:
                raise _invalid("checkpoint write verification failed")
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _ensure_ledger_directory(workspace: Path) -> Path:
    root = workspace.resolve(strict=True)
    open_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        current_fd = os.open(root, open_flags)
        descriptors.append(current_fd)
        for part in Path(CONVERSATION_LEDGER_DIRECTORY).parts:
            try:
                metadata = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                metadata = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise _invalid("checkpoint directory parent is unsafe")
            next_fd = os.open(part, open_flags, dir_fd=current_fd)
            descriptors.append(next_fd)
            current_fd = next_fd
        os.fchmod(current_fd, 0o700)
        os.fsync(current_fd)
    except OSError as exc:
        raise _invalid("checkpoint directory is unavailable or unsafe") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    return root / CONVERSATION_LEDGER_DIRECTORY


def _load_checkpoint(
    workspace: Path,
    reference: Mapping[str, Any],
    *,
    expected_job_id: str,
) -> tuple[str, dict[str, Any]]:
    expected_reference_fields = {
        "version",
        "path",
        "sha256",
        "root_sha256",
        "message_count",
    }
    if (
        set(reference) != expected_reference_fields
        or reference.get("version") != CONVERSATION_LEDGER_REFERENCE_VERSION
        or not isinstance(reference.get("path"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", str(reference.get("sha256") or ""))
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(reference.get("root_sha256") or "")
        )
        or isinstance(reference.get("message_count"), bool)
        or not isinstance(reference.get("message_count"), int)
        or not 0 <= int(reference["message_count"]) <= CONVERSATION_LEDGER_MAX_MESSAGES
    ):
        raise _invalid("checkpoint reference is invalid")
    relative = str(reference["path"])
    path = _safe_checkpoint_path(workspace, relative, must_exist=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _invalid("checkpoint JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise _invalid("checkpoint root is invalid")
    _validate_checkpoint_payload(payload, expected_job_id=expected_job_id)
    if relative != _checkpoint_relative(
        int(payload["message_count"]),
        str(payload["root_sha256"]),
    ):
        raise _invalid("checkpoint filename does not match its count and root")
    if (
        stable_json_hash(payload) != reference.get("sha256")
        or payload.get("root_sha256") != reference.get("root_sha256")
        or payload.get("message_count") != reference.get("message_count")
    ):
        raise _invalid("checkpoint reference hash or root mismatch")
    return relative, payload


def _validate_checkpoint_payload(payload: dict[str, Any], *, expected_job_id: str) -> None:
    source = payload.get("source")
    expected_fields = {
        "version",
        "job_id",
        "source",
        "message_count",
        "root_sha256",
        "entries",
        "parent_checkpoint",
        "legacy_request_sha256",
    }
    if source == "legacy_attested_request":
        expected_fields.add("legacy_parent_attestation")
    if (
        set(payload) != expected_fields
        or payload.get("version") != CONVERSATION_LEDGER_CHECKPOINT_VERSION
        or payload.get("job_id") != expected_job_id
        or source not in {"initial", "resume", "legacy_attested_request"}
        or not isinstance(payload.get("entries"), list)
        or isinstance(payload.get("message_count"), bool)
        or not isinstance(payload.get("message_count"), int)
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(payload.get("root_sha256") or "")
        )
    ):
        raise _invalid("checkpoint identity is invalid")
    entries = _ledger_entries(payload["entries"])
    if entries != payload["entries"]:
        raise _invalid("checkpoint message or chain digest is invalid")
    root_sha256 = entries[-1]["chain_sha256"] if entries else ZERO_SHA256
    if (
        payload.get("message_count") != len(entries)
        or payload.get("root_sha256") != root_sha256
    ):
        raise _invalid("checkpoint count or root is invalid")
    parent = payload.get("parent_checkpoint")
    legacy_request_sha256 = str(payload.get("legacy_request_sha256") or "")
    if source == "initial":
        if parent is not None or legacy_request_sha256:
            raise _invalid("initial checkpoint provenance is invalid")
    elif source == "resume":
        expected_parent_fields = {
            "version",
            "path",
            "sha256",
            "root_sha256",
            "message_count",
            "attestation_id",
            "attestation_sha256",
        }
        if (
            not isinstance(parent, dict)
            or set(parent) != expected_parent_fields
            or not _valid_attestation_id(
                parent.get("attestation_id"),
                job_id=expected_job_id,
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(parent.get("attestation_sha256") or "")
            )
            or legacy_request_sha256
        ):
            raise _invalid("resume checkpoint provenance is invalid")
    else:
        legacy_parent = payload.get("legacy_parent_attestation")
        if (
            parent is not None
            or not re.fullmatch(r"[0-9a-f]{64}", legacy_request_sha256)
            or not isinstance(legacy_parent, dict)
            or set(legacy_parent) != {"attestation_id", "attestation_sha256"}
            or not _valid_attestation_id(
                legacy_parent.get("attestation_id"),
                job_id=expected_job_id,
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(legacy_parent.get("attestation_sha256") or ""),
            )
        ):
            raise _invalid("legacy checkpoint provenance is invalid")


def _validate_snapshot_against_entries(
    request: Mapping[str, Any],
    entries: list[dict[str, Any]],
    *,
    expected_job_id: str,
) -> None:
    snapshot = request.get("conversation_snapshot")
    if not isinstance(snapshot, dict):
        raise _invalid("bounded conversation snapshot is missing")
    unsigned = {key: value for key, value in snapshot.items() if key != "sha256"}
    snapshot_sha256 = stable_json_hash(unsigned)
    messages = snapshot.get("messages")
    if (
        snapshot.get("contract_version")
        != "factorforge_console_conversation_snapshot_v1"
        or snapshot.get("job_id") != expected_job_id
        or snapshot.get("sha256") != snapshot_sha256
        or request.get("conversation_snapshot_sha256") != snapshot_sha256
        or not isinstance(messages, list)
        or any(not isinstance(item, dict) for item in messages)
        or len(messages) > 40
        or (bool(entries) and not messages)
        or snapshot.get("character_budget") != 40_000
        or snapshot.get("included_character_count")
        != sum(len(str(item.get("content") or "")) for item in messages)
        or not isinstance(snapshot.get("content_truncated"), bool)
        or not isinstance(snapshot.get("history_complete"), bool)
        or snapshot.get("message_count") != len(messages)
        or snapshot.get("total_message_count") != len(entries)
        or snapshot.get("omitted_message_count") != len(entries) - len(messages)
    ):
        raise _invalid("bounded conversation snapshot identity is invalid")
    expected_sequences = list(
        range(len(entries) - len(messages) + 1, len(entries) + 1)
    )
    if [item.get("sequence_no") for item in messages] != expected_sequences:
        raise _invalid("bounded conversation snapshot is not a ledger suffix")
    partial_content = False
    for index, message in enumerate(messages):
        entry = entries[int(message["sequence_no"]) - 1]
        for field in (
            "message_id",
            "sequence_no",
            "role",
            "content_kind",
            "model",
            "created_at_utc",
        ):
            if message.get(field) != entry.get(field):
                raise _invalid("bounded conversation snapshot message identity changed")
        content = str(message.get("content") or "")
        full_content = str(entry.get("content") or "")
        if not content:
            raise _invalid("bounded conversation snapshot content is empty")
        if content == full_content:
            continue
        if index != 0 or not snapshot.get("content_truncated") or not full_content.startswith(content):
            raise _invalid("bounded conversation snapshot content changed")
        partial_content = True
    expected_truncated = partial_content or len(messages) < min(40, len(entries))
    expected_history_complete = len(messages) == len(entries) and not expected_truncated
    if (
        snapshot.get("content_truncated") is not expected_truncated
        or snapshot.get("history_complete") is not expected_history_complete
    ):
        raise _invalid("bounded conversation snapshot completeness is invalid")


def validate_request_conversation_ledger(
    workspace: Path,
    request: Mapping[str, Any],
    *,
    expected_job_id: str,
    bootstrap_reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reference = request.get(CONVERSATION_LEDGER_REFERENCE_FIELD)
    if not isinstance(reference, dict):
        raise _invalid("conversation ledger reference is missing")
    chain: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    current_reference = deepcopy(reference)
    while True:
        relative, payload = _load_checkpoint(
            workspace,
            current_reference,
            expected_job_id=expected_job_id,
        )
        if relative in seen or len(chain) >= CONVERSATION_LEDGER_MAX_MESSAGES:
            raise _invalid("checkpoint ancestry contains a cycle or is too deep")
        seen.add(relative)
        chain.append((relative, payload, deepcopy(current_reference)))
        parent = payload.get("parent_checkpoint")
        if parent is None:
            break
        if (
            not isinstance(parent, dict)
            or not _valid_attestation_id(
                parent.get("attestation_id"),
                job_id=expected_job_id,
            )
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(parent.get("attestation_sha256") or "")
            )
        ):
            raise _invalid("parent checkpoint lacks host attestation provenance")
        current_reference = {
            key: parent.get(key)
            for key in ("version", "path", "sha256", "root_sha256", "message_count")
        }
    chain.reverse()
    for (_, parent, _), (_, child, _) in zip(chain, chain[1:]):
        parent_entries = parent["entries"]
        if (
            len(parent_entries) >= len(child["entries"])
            or child["entries"][: len(parent_entries)] != parent_entries
        ):
            raise _invalid("checkpoint ancestry is not append-only")
    directory = workspace.resolve(strict=True) / CONVERSATION_LEDGER_DIRECTORY
    if not directory.is_dir() or directory.is_symlink():
        raise _invalid("checkpoint directory is missing or unsafe")
    directory_entries = list(directory.iterdir())
    if any(
        not path.is_file()
        or path.is_symlink()
        or not re.fullmatch(
            r"checkpoint__[0-9]{6}__[0-9a-f]{64}\.json",
            path.name,
        )
        for path in directory_entries
    ):
        raise _invalid("checkpoint directory contains an unsafe entry")
    checkpoint_files = {
        path.relative_to(workspace.resolve(strict=True)).as_posix()
        for path in directory_entries
    }
    if checkpoint_files != {relative for relative, _payload, _ref in chain}:
        raise _invalid("checkpoint directory contains a branch or missing ancestor")
    current_payload = chain[-1][1]
    _validate_snapshot_against_entries(
        request,
        current_payload["entries"],
        expected_job_id=expected_job_id,
    )

    if bootstrap_reference is not None:
        if not isinstance(bootstrap_reference, Mapping):
            raise _invalid("bootstrap checkpoint reference is invalid")
        bootstrap_match = any(
            all(
                checkpoint_reference.get(field) == bootstrap_reference.get(field)
                for field in ("version", "path", "sha256", "root_sha256", "message_count")
            )
            for _relative, _payload, checkpoint_reference in chain
        )
        if not bootstrap_match:
            raise _invalid("bootstrap checkpoint is not an ancestor")
    return {
        "reference": deepcopy(reference),
        "current": current_payload,
        "chain": chain,
    }


def plan_conversation_checkpoints(
    workspace: Path,
    *,
    job_id: str,
    messages: Iterable[Mapping[str, Any] | Any],
    existing_request: Mapping[str, Any] | None,
    parent_attestation_id: str = "",
    parent_attestation_sha256: str = "",
) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
    current_messages = [_message_payload(message) for message in messages]
    planned: list[tuple[str, dict[str, Any]]] = []
    parent_payload: dict[str, Any] | None = None
    parent_reference: dict[str, Any] | None = None
    if existing_request is not None:
        existing_reference = existing_request.get(CONVERSATION_LEDGER_REFERENCE_FIELD)
        if isinstance(existing_reference, dict):
            validated = validate_request_conversation_ledger(
                workspace,
                existing_request,
                expected_job_id=job_id,
            )
            parent_payload = validated["current"]
            parent_reference = validated["reference"]
        else:
            snapshot = existing_request.get("conversation_snapshot")
            if (
                not isinstance(snapshot, dict)
                or snapshot.get("history_complete") is not True
                or snapshot.get("content_truncated") is not False
                or snapshot.get("omitted_message_count") != 0
                or not isinstance(snapshot.get("messages"), list)
            ):
                raise _invalid("legacy conversation snapshot cannot anchor a checkpoint")
            if (
                not _valid_attestation_id(
                    parent_attestation_id,
                    job_id=job_id,
                )
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    parent_attestation_sha256,
                )
            ):
                raise _invalid("legacy checkpoint lacks parent attestation provenance")
            legacy_relative, legacy_payload, legacy_reference = _build_checkpoint(
                job_id=job_id,
                messages=snapshot["messages"],
                source="legacy_attested_request",
                parent_reference=None,
                parent_payload=None,
                parent_attestation_id="",
                parent_attestation_sha256="",
                legacy_request_sha256=stable_json_hash(existing_request),
            )
            legacy_payload["legacy_parent_attestation"] = {
                "attestation_id": parent_attestation_id,
                "attestation_sha256": parent_attestation_sha256,
            }
            legacy_reference = _checkpoint_reference(legacy_relative, legacy_payload)
            planned.append((legacy_relative, legacy_payload))
            parent_payload = legacy_payload
            parent_reference = legacy_reference

    if parent_payload is not None:
        parent_entries = parent_payload["entries"]
        current_entries = _ledger_entries(current_messages)
        if current_entries[: len(parent_entries)] != parent_entries:
            raise _invalid("current message store does not extend the attested ledger")
        if len(current_entries) == len(parent_entries):
            return deepcopy(parent_reference), planned
        source = "resume"
    else:
        source = "initial"

    relative, payload, reference = _build_checkpoint(
        job_id=job_id,
        messages=current_messages,
        source=source,
        parent_reference=parent_reference,
        parent_payload=parent_payload,
        parent_attestation_id=parent_attestation_id,
        parent_attestation_sha256=parent_attestation_sha256,
    )
    planned.append((relative, payload))
    return reference, planned
