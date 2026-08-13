from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import stat
import tempfile
import threading
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from factor_factory.human_approval import canonical_json_bytes
from factor_factory.research_org.runtime_trust import (
    ensure_runtime_trust_store,
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)


OOS_EXPOSURE_INCIDENT_VERSION = "factorforge_oos_exposure_incident_v1"
OOS_EXPOSURE_PROVENANCE_ADDENDUM_VERSION = (
    "factorforge_oos_exposure_incident_provenance_addendum_v1"
)
OOS_EXPOSURE_INCIDENT_AUTHORITY = "NEGATIVE_EVIDENCE_ONLY"
OOS_EXPOSURE_RUNNER_REF_ROLE = "CURRENT_REMEDIATION_RECONSTRUCTION_ONLY"
OOS_EXPOSURE_PRIVATE_REGISTRY_VERSION = (
    "factorforge_oos_exposure_private_registry_v1"
)
OOS_EXPOSURE_PRIVATE_RECEIPT_TYPE = "OOS_EXPOSURE_INCIDENT_NEGATIVE_EVIDENCE"
OOS_EXPOSURE_PREPARED_RECEIPT_TYPE = "OOS_EXPOSURE_INCIDENT_PREPARED"
OOS_EXPOSURE_COMMITTED_RECEIPT_TYPE = "OOS_EXPOSURE_INCIDENT_COMMITTED"
OOS_EXPOSURE_TRANSACTION_RECEIPT_TYPE = "OOS_EXPOSURE_REGISTRY_TRANSACTION"
OOS_EXPOSURE_TRUST_ROOT_ENV = "FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT"
OOS_EXPOSURE_INSTALLATION_ID_ENV = (
    "FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID"
)
BLOCK_OOS_EXPOSURE_INCIDENT = "BLOCK_FACTORFORGE_OOS_EXPOSURE_INCIDENT"

_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,191}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_ARTIFACT_NAMES = ("source", "panel", "metrics", "runner")


_PRIVATE_GUARD_SECRET = object()
_ACTIVE_PRIVATE_GUARDS: dict[int, "_PrivateRegistryGuardToken"] = {}
_ACTIVE_PRIVATE_GUARDS_LOCK = threading.RLock()


class _PrivateRegistryGuardToken:
    """Unforgeable, process-local proof that ``registry.lock`` is held.

    The class is deliberately private.  Construction requires a module-private
    sentinel and validation also requires membership in the live-token table,
    so a copied mapping or a token retained after context exit carries no
    authority.
    """

    __slots__ = (
        "_secret",
        "_active",
        "_trust_root",
        "_installation_id",
        "_registry_path",
        "_event_count",
        "_head_receipt_id",
        "_head_receipt_sha256",
    )

    def __init__(
        self,
        secret: object,
        *,
        trust_root: Path,
        installation_id: str,
        registry_path: Path,
        event_count: int,
        head_receipt_id: Any,
        head_receipt_sha256: str,
    ) -> None:
        if secret is not _PRIVATE_GUARD_SECRET:
            raise TypeError("private registry guard tokens are not constructible")
        self._secret = secret
        self._active = True
        self._trust_root = trust_root
        self._installation_id = installation_id
        self._registry_path = registry_path
        self._event_count = event_count
        self._head_receipt_id = head_receipt_id
        self._head_receipt_sha256 = head_receipt_sha256


def validate_oos_exposure_private_registry_guard(
    guard: object,
    *,
    trust_root: Path,
    installation_id: str,
) -> None:
    """Fail unless ``guard`` is the active token for this Host registry head."""

    token = f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_guard_invalid"
    if not isinstance(guard, _PrivateRegistryGuardToken):
        raise ValueError(token)
    with _ACTIVE_PRIVATE_GUARDS_LOCK:
        if (
            guard._secret is not _PRIVATE_GUARD_SECRET
            or not guard._active
            or _ACTIVE_PRIVATE_GUARDS.get(id(guard)) is not guard
        ):
            raise ValueError(token)
    resolved = trust_root.expanduser().resolve(strict=True)
    if (
        guard._trust_root != resolved
        or guard._installation_id != installation_id
        or guard._registry_path != oos_exposure_private_registry_path(resolved)
    ):
        raise ValueError(f"{token}:host_binding")
    registry = load_and_validate_oos_exposure_private_registry(
        resolved,
        installation_id=installation_id,
    )
    anchor_path = _private_registry_anchor_path(resolved)
    try:
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{token}:head_binding") from exc
    if (
        len(registry["events"]) != guard._event_count
        or anchor.get("head_receipt_id") != guard._head_receipt_id
        or _sha256_file(anchor_path) != guard._head_receipt_sha256
    ):
        raise ValueError(f"{token}:head_binding")


def _stable_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _pretty_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace_bytes(path: Path, encoded: bytes, *, mode: int = 0o600) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_report_id(report_id: str) -> str:
    if not isinstance(report_id, str) or not _SAFE_ID_RE.fullmatch(report_id):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:report_id")
    return report_id


def oos_exposure_incident_path(workspace_root: Path, report_id: str) -> Path:
    return (
        workspace_root.expanduser().resolve(strict=False)
        / "objects"
        / "research_protocol"
        / f"oos_exposure_incident__{_safe_report_id(report_id)}.json"
    )


def oos_exposure_provenance_addendum_path(
    workspace_root: Path,
    report_id: str,
) -> Path:
    return (
        workspace_root.expanduser().resolve(strict=False)
        / "objects"
        / "research_protocol"
        / f"oos_exposure_incident_provenance_addendum__{_safe_report_id(report_id)}.json"
    )


def _path_lexists(path: Path) -> bool:
    """Return true for every directory entry, including a broken symlink."""

    return os.path.lexists(os.fspath(path))


def oos_exposure_incident_block_reasons(
    workspace_root: Path,
    report_id: str,
    *,
    trust_root: Path | None = None,
    installation_id: str | None = None,
) -> list[str]:
    """Block formal OOS authority on marker presence, independent of validity.

    Validation is intentionally not a precondition for blocking.  An attacker
    cannot regain formal-OOS eligibility by truncating the marker, deleting a
    field, changing its hash, replacing it with a directory, or making it a
    symlink (including a broken symlink).
    """

    path = oos_exposure_incident_path(workspace_root, report_id)
    if _path_lexists(path):
        return [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_present"]
    explicit_trust = (
        os.fspath(trust_root.expanduser().resolve(strict=False))
        if trust_root is not None
        else os.environ.get(OOS_EXPOSURE_TRUST_ROOT_ENV, "")
    )
    explicit_installation = (
        installation_id
        if installation_id is not None
        else os.environ.get(OOS_EXPOSURE_INSTALLATION_ID_ENV, "")
    )
    if bool(explicit_trust) != bool(explicit_installation):
        return [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:host_context_incomplete"]
    trust_root_raw = explicit_trust
    installation_id = explicit_installation
    if not trust_root_raw:
        fallback_trust = os.environ.get("FACTORFORGE_OOS_HOST_TRUST_ROOT", "")
        fallback_installation = os.environ.get(
            "FACTORFORGE_OOS_HOST_INSTALLATION_ID", ""
        )
        if fallback_trust or fallback_installation:
            trust_root_raw = fallback_trust
            installation_id = fallback_installation
    if bool(trust_root_raw) != bool(installation_id):
        return [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:host_context_incomplete"]
    if trust_root_raw:
        registry_path = oos_exposure_private_registry_path(Path(trust_root_raw))
        anchor_path = _private_registry_anchor_path(Path(trust_root_raw))
        heads_path = _private_registry_heads_path(Path(trust_root_raw))
        journal_path = _private_registry_journal_path(Path(trust_root_raw))
        initialized = any(
            _path_lexists(item)
            for item in (registry_path, anchor_path, heads_path, journal_path)
        )
        if not initialized:
            return []
        try:
            resolved_workspace = workspace_root.expanduser().resolve(strict=False)
            resolved_trust = Path(trust_root_raw).expanduser().resolve(strict=True)
            if resolved_trust == resolved_workspace or resolved_workspace in resolved_trust.parents:
                raise ValueError("private registry inside workspace")
            registry = load_and_validate_oos_exposure_private_registry(
                resolved_trust,
                installation_id=installation_id,
            )
        except (OSError, ValueError):
            return [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_invalid"]
        if any(
            isinstance(event, Mapping) and event.get("report_id") == report_id
            for event in registry["events"]
        ):
            return [f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_incident"]
    return []


def oos_exposure_private_registry_path(trust_root: Path) -> Path:
    return (
        trust_root.expanduser().resolve(strict=False)
        / "oos_exposure_incidents"
        / "registry.json"
    )


@contextmanager
def oos_exposure_private_registry_guard(
    trust_root: Path,
    *,
    installation_id: str,
):
    """Linearize one Host authority decision against incident registration."""

    resolved = trust_root.expanduser().resolve(strict=False)
    ensure_runtime_trust_store(resolved, installation_id=installation_id)
    incident_root = oos_exposure_private_registry_path(resolved).parent
    incident_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(incident_root, 0o700)
    lock_path = oos_exposure_private_registry_path(resolved).with_suffix(".lock")
    descriptor = os.open(
        lock_path,
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:registry_lock_unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        registry = ensure_empty_oos_exposure_private_registry(
            resolved,
            installation_id=installation_id,
        )
        anchor_path = _private_registry_anchor_path(resolved)
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        guard = _PrivateRegistryGuardToken(
            _PRIVATE_GUARD_SECRET,
            trust_root=resolved.resolve(strict=True),
            installation_id=installation_id,
            registry_path=oos_exposure_private_registry_path(resolved),
            event_count=len(registry["events"]),
            head_receipt_id=anchor.get("head_receipt_id"),
            head_receipt_sha256=_sha256_file(anchor_path),
        )
        with _ACTIVE_PRIVATE_GUARDS_LOCK:
            _ACTIVE_PRIVATE_GUARDS[id(guard)] = guard
        try:
            yield guard
        finally:
            with _ACTIVE_PRIVATE_GUARDS_LOCK:
                guard._active = False
                _ACTIVE_PRIVATE_GUARDS.pop(id(guard), None)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _private_registry_anchor_path(trust_root: Path) -> Path:
    return oos_exposure_private_registry_path(trust_root).with_name("registry.anchor.json")


def _private_registry_heads_path(trust_root: Path) -> Path:
    return oos_exposure_private_registry_path(trust_root).with_name("heads")


def _private_registry_journal_path(trust_root: Path) -> Path:
    return oos_exposure_private_registry_path(trust_root).with_name(
        "registry.transaction.json"
    )


def _write_private_head_once(trust_root: Path, head: Mapping[str, Any]) -> Path:
    heads = _private_registry_heads_path(trust_root)
    heads.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(heads, 0o700)
    sequence = head.get("event_count")
    receipt_id = str(head.get("receipt_id") or "")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_head")
    path = heads / f"head__{sequence:020d}__{receipt_id}.json"
    encoded = _pretty_json_bytes(head)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file() or path.is_symlink() or path.read_bytes() != encoded:
            raise ValueError(
                f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_head_conflict"
            )
        return path
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(heads)
    return path


def _recover_private_registry_transaction(
    trust_root: Path,
    *,
    installation_id: str,
) -> bool:
    journal_path = _private_registry_journal_path(trust_root)
    if not _path_lexists(journal_path):
        return False
    if not journal_path.is_file() or journal_path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:transaction_unsafe")
    store = load_runtime_trust_store(trust_root, installation_id=installation_id)
    transaction = json.loads(journal_path.read_text(encoding="utf-8"))
    if (
        verify_signed_receipt_with_manifest(
            transaction,
            trust_manifest=store.public_manifest,
            expected_issuer="host_admission",
        )
        or transaction.get("receipt_type") != OOS_EXPOSURE_TRANSACTION_RECEIPT_TYPE
        or transaction.get("installation_id") != installation_id
        or not isinstance(transaction.get("next_registry"), dict)
        or not isinstance(transaction.get("next_head"), dict)
    ):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:transaction_invalid")
    next_registry = transaction["next_registry"]
    next_head = transaction["next_head"]
    if (
        verify_signed_receipt_with_manifest(
            next_head,
            trust_manifest=store.public_manifest,
            expected_issuer="host_admission",
        )
        or next_head.get("receipt_type") != "OOS_EXPOSURE_PRIVATE_REGISTRY_HEAD"
        or next_head.get("installation_id") != installation_id
        or next_head.get("registry_content_sha256")
        != next_registry.get("content_sha256")
        or next_head.get("registry_payload_sha256") != _stable_hash(next_registry)
    ):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:transaction_binding")
    _write_private_head_once(trust_root, next_head)
    registry_path = oos_exposure_private_registry_path(trust_root)
    anchor_path = _private_registry_anchor_path(trust_root)
    _atomic_replace_bytes(registry_path, _pretty_json_bytes(next_registry))
    _atomic_replace_bytes(anchor_path, _pretty_json_bytes(next_head))
    journal_path.unlink()
    _fsync_directory(journal_path.parent)
    return True


def _apply_private_registry_transaction(
    trust_root: Path,
    *,
    installation_id: str,
    next_registry: dict[str, Any],
    next_head: dict[str, Any],
) -> None:
    store = load_runtime_trust_store(trust_root, installation_id=installation_id)
    transaction = store.sign(
        "host_admission",
        {
            "receipt_type": OOS_EXPOSURE_TRANSACTION_RECEIPT_TYPE,
            "installation_id": installation_id,
            "next_registry": next_registry,
            "next_head": next_head,
        },
    )
    journal_path = _private_registry_journal_path(trust_root)
    encoded = _pretty_json_bytes(transaction)
    if _path_lexists(journal_path):
        if (
            journal_path.is_symlink()
            or not journal_path.is_file()
            or journal_path.read_bytes() != encoded
        ):
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:transaction_conflict")
    else:
        descriptor = os.open(
            journal_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(journal_path.parent)
    _recover_private_registry_transaction(
        trust_root,
        installation_id=installation_id,
    )


def _private_registry_payload(
    *,
    installation_id: str,
    trust_manifest: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    unsigned = {
        "contract_version": OOS_EXPOSURE_PRIVATE_REGISTRY_VERSION,
        "installation_id": installation_id,
        "trust_manifest": dict(trust_manifest),
        "events": events,
    }
    return {**unsigned, "content_sha256": _stable_hash(unsigned)}


def load_and_validate_oos_exposure_private_registry(
    trust_root: Path,
    *,
    installation_id: str,
) -> dict[str, Any]:
    _recover_private_registry_transaction(
        trust_root,
        installation_id=installation_id,
    )
    path = oos_exposure_private_registry_path(trust_root)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "contract_version",
            "installation_id",
            "trust_manifest",
            "events",
            "content_sha256",
        }
        or payload.get("contract_version") != OOS_EXPOSURE_PRIVATE_REGISTRY_VERSION
        or payload.get("installation_id") != installation_id
    ):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_shape")
    unsigned = dict(payload)
    digest = unsigned.pop("content_sha256")
    if digest != _stable_hash(unsigned):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_hash")
    manifest = payload.get("trust_manifest")
    expected_manifest = load_runtime_trust_store(
        trust_root,
        installation_id=installation_id,
    ).public_manifest
    if (
        not isinstance(manifest, dict)
        or validate_public_trust_manifest(manifest)
        or manifest != expected_manifest
    ):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_trust")
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_events")
    previous_id: str | None = None
    report_states: dict[str, str] = {}
    for sequence, event in enumerate(events, 1):
        if not isinstance(event, dict) or verify_signed_receipt_with_manifest(
            event,
            trust_manifest=manifest,
            expected_issuer="host_admission",
        ):
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_signature")
        receipt_type = event.get("receipt_type")
        report_id = str(event.get("report_id") or "")
        common_invalid = (
            event.get("sequence") != sequence
            or event.get("previous_receipt_id") != previous_id
            or event.get("authority") != OOS_EXPOSURE_INCIDENT_AUTHORITY
            or event.get("formal_oos_eligible") is not False
            or not _SHA256_RE.fullmatch(str(event.get("incident_file_sha256") or ""))
            or not _SHA256_RE.fullmatch(str(event.get("incident_content_sha256") or ""))
            or not _SAFE_ID_RE.fullmatch(str(event.get("report_id") or ""))
        )
        if common_invalid:
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_event")
        prior_state = report_states.get(report_id)
        if receipt_type == OOS_EXPOSURE_PRIVATE_RECEIPT_TYPE:
            if prior_state is not None:
                raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_event")
            report_states[report_id] = "COMMITTED"
        elif receipt_type == OOS_EXPOSURE_PREPARED_RECEIPT_TYPE:
            incident_payload = event.get("incident_payload")
            if (
                prior_state is not None
                or event.get("incident_state") != "PREPARED"
                or not isinstance(incident_payload, dict)
                or validate_oos_exposure_incident(incident_payload)
                or incident_payload.get("report_id") != report_id
                or event.get("incident_content_sha256")
                != incident_payload.get("incident_sha256")
                or event.get("incident_file_sha256")
                != hashlib.sha256(_pretty_json_bytes(incident_payload)).hexdigest()
            ):
                raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_prepare")
            report_states[report_id] = "PREPARED"
        elif receipt_type == OOS_EXPOSURE_COMMITTED_RECEIPT_TYPE:
            if (
                prior_state != "PREPARED"
                or event.get("incident_state") != "COMMITTED"
                or not _SHA256_RE.fullmatch(
                    str(event.get("prepared_receipt_id") or "")
                )
            ):
                raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_commit")
            prepared = next(
                item
                for item in events[: sequence - 1]
                if item.get("report_id") == report_id
                and item.get("receipt_type") == OOS_EXPOSURE_PREPARED_RECEIPT_TYPE
            )
            if (
                event.get("prepared_receipt_id") != prepared.get("receipt_id")
                or event.get("incident_content_sha256")
                != prepared.get("incident_content_sha256")
                or event.get("incident_file_sha256")
                != prepared.get("incident_file_sha256")
            ):
                raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_commit")
            report_states[report_id] = "COMMITTED"
        else:
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_event")
        previous_id = str(event.get("receipt_id") or "")
    anchor_path = _private_registry_anchor_path(trust_root)
    if not anchor_path.is_file() or anchor_path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_anchor")
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    if (
        verify_signed_receipt_with_manifest(
            anchor,
            trust_manifest=manifest,
            expected_issuer="host_admission",
        )
        or anchor.get("receipt_type") != "OOS_EXPOSURE_PRIVATE_REGISTRY_HEAD"
        or anchor.get("installation_id") != installation_id
        or anchor.get("event_count") != len(events)
        or anchor.get("head_receipt_id") != previous_id
        or anchor.get("registry_content_sha256") != payload.get("content_sha256")
        or (
            anchor.get("registry_payload_sha256") is not None
            and anchor.get("registry_payload_sha256") != _stable_hash(payload)
        )
    ):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_head")
    heads_path = _private_registry_heads_path(trust_root)
    if not heads_path.is_dir() or heads_path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_heads")
    witnessed: list[dict[str, Any]] = []
    for witness_path in heads_path.iterdir():
        if not witness_path.is_file() or witness_path.is_symlink():
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_heads")
        witness = json.loads(witness_path.read_text(encoding="utf-8"))
        if (
            verify_signed_receipt_with_manifest(
                witness,
                trust_manifest=manifest,
                expected_issuer="host_admission",
            )
            or witness.get("receipt_type") != "OOS_EXPOSURE_PRIVATE_REGISTRY_HEAD"
            or witness.get("installation_id") != installation_id
        ):
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_witness")
        witnessed.append(witness)
    if not witnessed:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_witness")
    maximal = max(witnessed, key=lambda item: int(item.get("event_count", -1)))
    if maximal != anchor:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_rollback")
    return payload


def ensure_empty_oos_exposure_private_registry(
    trust_root: Path,
    *,
    installation_id: str,
) -> dict[str, Any]:
    store = ensure_runtime_trust_store(trust_root, installation_id=installation_id)
    path = oos_exposure_private_registry_path(trust_root)
    anchor_path = _private_registry_anchor_path(trust_root)
    heads_path = _private_registry_heads_path(trust_root)
    journal_path = _private_registry_journal_path(trust_root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if _path_lexists(journal_path):
        _recover_private_registry_transaction(
            trust_root,
            installation_id=installation_id,
        )
    initialized = any(_path_lexists(item) for item in (path, anchor_path, heads_path))
    if not initialized:
        existing = _private_registry_payload(
            installation_id=installation_id,
            trust_manifest=store.public_manifest,
            events=[],
        )
        anchor = store.sign(
            "host_admission",
            {
                "receipt_type": "OOS_EXPOSURE_PRIVATE_REGISTRY_HEAD",
                "installation_id": installation_id,
                "trust_manifest_sha256": store.public_manifest["manifest_sha256"],
                "event_count": 0,
                "head_receipt_id": None,
                "registry_content_sha256": existing["content_sha256"],
                "registry_payload_sha256": _stable_hash(existing),
            },
        )
        _apply_private_registry_transaction(
            trust_root,
            installation_id=installation_id,
            next_registry=existing,
            next_head=anchor,
        )
        return load_and_validate_oos_exposure_private_registry(
            trust_root,
            installation_id=installation_id,
        )
    if anchor_path.exists() or anchor_path.is_symlink():
        if not anchor_path.is_file() or anchor_path.is_symlink() or not path.is_file():
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_deleted")
        existing_anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        if (
            existing_anchor.get("receipt_type")
            == "OOS_EXPOSURE_PRIVATE_REGISTRY_ANCHOR"
            and not verify_signed_receipt_with_manifest(
                existing_anchor,
                trust_manifest=store.public_manifest,
                expected_issuer="host_admission",
            )
            and existing_anchor.get("installation_id") == installation_id
        ):
            # One-time migration from the identity-only v1 prototype anchor.
            # The replacement is signed from the current private registry head;
            # the full validator immediately replays every event/signature.
            current = json.loads(path.read_text(encoding="utf-8"))
            current_events = current.get("events") if isinstance(current, dict) else None
            if not isinstance(current_events, list):
                raise ValueError(
                    f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_events"
                )
            migrated_anchor = store.sign(
                "host_admission",
                {
                    "receipt_type": "OOS_EXPOSURE_PRIVATE_REGISTRY_HEAD",
                    "installation_id": installation_id,
                    "trust_manifest_sha256": store.public_manifest[
                        "manifest_sha256"
                    ],
                    "event_count": len(current_events),
                    "head_receipt_id": (
                        current_events[-1].get("receipt_id")
                        if current_events and isinstance(current_events[-1], dict)
                        else None
                    ),
                    "registry_content_sha256": current.get("content_sha256"),
                    "registry_payload_sha256": _stable_hash(current),
                },
            )
            temporary_anchor = anchor_path.with_name(
                f".{anchor_path.name}.{os.getpid()}.migration.tmp"
            )
            temporary_anchor.write_bytes(_pretty_json_bytes(migrated_anchor))
            os.chmod(temporary_anchor, 0o600)
            _write_private_head_once(trust_root, migrated_anchor)
            os.replace(temporary_anchor, anchor_path)
        elif not _private_registry_heads_path(trust_root).exists():
            _write_private_head_once(trust_root, existing_anchor)
        return load_and_validate_oos_exposure_private_registry(
            trust_root,
            installation_id=installation_id,
        )
    raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_partial")


def _append_private_incident_event(
    *,
    trust_root: Path,
    installation_id: str,
    event_payload: Mapping[str, Any],
) -> dict[str, Any]:
    store = load_runtime_trust_store(trust_root, installation_id=installation_id)
    registry = load_and_validate_oos_exposure_private_registry(
        trust_root,
        installation_id=installation_id,
    )
    events = list(registry["events"])
    event = store.sign(
        "host_admission",
        {
            **dict(event_payload),
            "sequence": len(events) + 1,
            "previous_receipt_id": events[-1]["receipt_id"] if events else None,
            "authority": OOS_EXPOSURE_INCIDENT_AUTHORITY,
            "formal_oos_eligible": False,
        },
    )
    next_registry = _private_registry_payload(
        installation_id=installation_id,
        trust_manifest=store.public_manifest,
        events=[*events, event],
    )
    next_head = store.sign(
        "host_admission",
        {
            "receipt_type": "OOS_EXPOSURE_PRIVATE_REGISTRY_HEAD",
            "installation_id": installation_id,
            "trust_manifest_sha256": store.public_manifest["manifest_sha256"],
            "event_count": len(events) + 1,
            "head_receipt_id": event["receipt_id"],
            "registry_content_sha256": next_registry["content_sha256"],
            "registry_payload_sha256": _stable_hash(next_registry),
        },
    )
    _apply_private_registry_transaction(
        trust_root,
        installation_id=installation_id,
        next_registry=next_registry,
        next_head=next_head,
    )
    validated = load_and_validate_oos_exposure_private_registry(
        trust_root,
        installation_id=installation_id,
    )
    return validated["events"][-1]


def register_oos_exposure_incident_host_private(
    *,
    workspace_root: Path,
    report_id: str,
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    resolved_trust = trust_root.expanduser().resolve(strict=False)
    if resolved_trust == root or root in resolved_trust.parents:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_inside_workspace")
    incident = load_and_validate_oos_exposure_incident(root, report_id)
    incident_path = oos_exposure_incident_path(root, report_id)
    ensure_runtime_trust_store(resolved_trust, installation_id=installation_id)
    with oos_exposure_private_registry_guard(
        resolved_trust,
        installation_id=installation_id,
    ):
        registry = load_and_validate_oos_exposure_private_registry(
            resolved_trust,
            installation_id=installation_id,
        )
        existing = [
            event for event in registry["events"] if event.get("report_id") == report_id
        ]
        if existing:
            return {"status": "IDEMPOTENT_PRIVATE_INCIDENT", "event": existing[0]}
        event = _append_private_incident_event(
            trust_root=resolved_trust,
            installation_id=installation_id,
            event_payload={
                "receipt_type": OOS_EXPOSURE_PRIVATE_RECEIPT_TYPE,
                "report_id": report_id,
                "factor_id": incident["factor_id"],
                "incident_file_sha256": _sha256_file(incident_path),
                "incident_content_sha256": incident["incident_sha256"],
            },
        )
        return {"status": "REGISTERED_PRIVATE_INCIDENT", "event": event}


def prepare_oos_exposure_incident_host_private(
    *,
    workspace_root: Path,
    payload: Mapping[str, Any],
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    resolved_trust = trust_root.expanduser().resolve(strict=False)
    candidate = dict(payload)
    reasons = validate_oos_exposure_incident(candidate)
    if reasons:
        raise ValueError(";".join(reasons))
    if resolved_trust == root or root in resolved_trust.parents:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_registry_inside_workspace")
    with oos_exposure_private_registry_guard(
        resolved_trust,
        installation_id=installation_id,
    ):
        registry = load_and_validate_oos_exposure_private_registry(
            resolved_trust,
            installation_id=installation_id,
        )
        report_events = [
            event
            for event in registry["events"]
            if event.get("report_id") == candidate["report_id"]
        ]
        prepared = next(
            (
                event
                for event in report_events
                if event.get("receipt_type") == OOS_EXPOSURE_PREPARED_RECEIPT_TYPE
            ),
            None,
        )
        if prepared is not None:
            if prepared.get("incident_payload") != candidate:
                raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:prepared_conflict")
            committed = next(
                (
                    event
                    for event in report_events
                    if event.get("receipt_type")
                    in {
                        OOS_EXPOSURE_COMMITTED_RECEIPT_TYPE,
                        OOS_EXPOSURE_PRIVATE_RECEIPT_TYPE,
                    }
                ),
                None,
            )
            return {
                "status": "IDEMPOTENT_COMMITTED" if committed else "IDEMPOTENT_PREPARED",
                "event": committed or prepared,
                "prepared_event": prepared,
            }
        if report_events:
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:private_incident_conflict")
        encoded = _pretty_json_bytes(candidate)
        event = _append_private_incident_event(
            trust_root=resolved_trust,
            installation_id=installation_id,
            event_payload={
                "receipt_type": OOS_EXPOSURE_PREPARED_RECEIPT_TYPE,
                "incident_state": "PREPARED",
                "report_id": candidate["report_id"],
                "factor_id": candidate["factor_id"],
                "incident_file_sha256": hashlib.sha256(encoded).hexdigest(),
                "incident_content_sha256": candidate["incident_sha256"],
                "incident_payload": candidate,
            },
        )
        return {"status": "PREPARED", "event": event, "prepared_event": event}


def commit_oos_exposure_incident_host_private(
    *,
    workspace_root: Path,
    report_id: str,
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    resolved_trust = trust_root.expanduser().resolve(strict=False)
    incident = load_and_validate_oos_exposure_incident(root, report_id)
    incident_path = oos_exposure_incident_path(root, report_id)
    with oos_exposure_private_registry_guard(
        resolved_trust,
        installation_id=installation_id,
    ):
        registry = load_and_validate_oos_exposure_private_registry(
            resolved_trust,
            installation_id=installation_id,
        )
        report_events = [
            event for event in registry["events"] if event.get("report_id") == report_id
        ]
        prepared = next(
            (
                event
                for event in report_events
                if event.get("receipt_type") == OOS_EXPOSURE_PREPARED_RECEIPT_TYPE
            ),
            None,
        )
        if prepared is None:
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:prepare_missing")
        if (
            prepared.get("incident_payload") != incident
            or prepared.get("incident_file_sha256") != _sha256_file(incident_path)
        ):
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:public_marker_binding")
        committed = next(
            (
                event
                for event in report_events
                if event.get("receipt_type") == OOS_EXPOSURE_COMMITTED_RECEIPT_TYPE
            ),
            None,
        )
        if committed is not None:
            return {"status": "IDEMPOTENT_COMMITTED", "event": committed}
        event = _append_private_incident_event(
            trust_root=resolved_trust,
            installation_id=installation_id,
            event_payload={
                "receipt_type": OOS_EXPOSURE_COMMITTED_RECEIPT_TYPE,
                "incident_state": "COMMITTED",
                "prepared_receipt_id": prepared["receipt_id"],
                "report_id": report_id,
                "factor_id": incident["factor_id"],
                "incident_file_sha256": _sha256_file(incident_path),
                "incident_content_sha256": incident["incident_sha256"],
            },
        )
        return {"status": "COMMITTED", "event": event}


def record_oos_exposure_incident_durable(
    *,
    workspace_root: Path,
    payload: Mapping[str, Any],
    trust_root: Path,
    installation_id: str,
) -> dict[str, Any]:
    prepared = prepare_oos_exposure_incident_host_private(
        workspace_root=workspace_root,
        payload=payload,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    public = write_oos_exposure_incident_create_only(
        workspace_root=workspace_root,
        payload=payload,
    )
    committed = commit_oos_exposure_incident_host_private(
        workspace_root=workspace_root,
        report_id=str(payload["report_id"]),
        trust_root=trust_root,
        installation_id=installation_id,
    )
    return {
        "status": committed["status"],
        "authority": OOS_EXPOSURE_INCIDENT_AUTHORITY,
        "formal_oos_eligible": False,
        "prepared": prepared,
        "public": public,
        "committed": committed,
    }


def _parse_window(raw: Any) -> tuple[date, date] | None:
    if not isinstance(raw, Mapping) or set(raw) != {"start", "end"}:
        return None
    try:
        start = date.fromisoformat(str(raw.get("start") or ""))
        end = date.fromisoformat(str(raw.get("end") or ""))
    except ValueError:
        return None
    return (start, end) if start <= end else None


def validate_oos_exposure_incident(payload: Any) -> list[str]:
    token = BLOCK_OOS_EXPOSURE_INCIDENT
    fields = {
        "contract_version",
        "report_id",
        "factor_id",
        "frozen_oos_window",
        "frozen_oos_release_token_sha256",
        "exposed_overlap_window",
        "exposed_row_count",
        "exposed_period_count",
        "artifacts",
        "incident_at",
        "authority",
        "formal_oos_eligible",
        "incident_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        return [f"{token}:shape"]
    reasons: list[str] = []
    if payload.get("contract_version") != OOS_EXPOSURE_INCIDENT_VERSION:
        reasons.append(f"{token}:version")
    for field in ("report_id", "factor_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
            reasons.append(f"{token}:{field}")
    frozen_window = _parse_window(payload.get("frozen_oos_window"))
    overlap_window = _parse_window(payload.get("exposed_overlap_window"))
    if frozen_window is None:
        reasons.append(f"{token}:frozen_oos_window")
    if overlap_window is None:
        reasons.append(f"{token}:exposed_overlap_window")
    if (
        frozen_window is not None
        and overlap_window is not None
        and not (
            frozen_window[0] <= overlap_window[0]
            and overlap_window[1] <= frozen_window[1]
        )
    ):
        reasons.append(f"{token}:overlap_outside_frozen_oos")
    if not _SHA256_RE.fullmatch(
        str(payload.get("frozen_oos_release_token_sha256") or "")
    ):
        reasons.append(f"{token}:frozen_oos_release_token_sha256")
    for field in ("exposed_row_count", "exposed_period_count"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            reasons.append(f"{token}:{field}")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(_ARTIFACT_NAMES):
        reasons.append(f"{token}:artifacts_shape")
    else:
        for name in _ARTIFACT_NAMES:
            artifact = artifacts.get(name)
            if (
                not isinstance(artifact, Mapping)
                or set(artifact) != {"path", "sha256"}
                or not isinstance(artifact.get("path"), str)
                or not artifact.get("path")
                or not _SHA256_RE.fullmatch(str(artifact.get("sha256") or ""))
            ):
                reasons.append(f"{token}:artifact:{name}")
    incident_at = payload.get("incident_at")
    try:
        parsed_incident_at = datetime.fromisoformat(
            str(incident_at or "").replace("Z", "+00:00")
        )
    except ValueError:
        parsed_incident_at = None
    if (
        parsed_incident_at is None
        or parsed_incident_at.tzinfo is None
        or not isinstance(incident_at, str)
        or not incident_at.endswith("Z")
    ):
        reasons.append(f"{token}:incident_at")
    if payload.get("authority") != OOS_EXPOSURE_INCIDENT_AUTHORITY:
        reasons.append(f"{token}:authority")
    if payload.get("formal_oos_eligible") is not False:
        reasons.append(f"{token}:formal_oos_eligible")
    unsigned = dict(payload)
    digest = unsigned.pop("incident_sha256", None)
    if not isinstance(digest, str) or digest != _stable_hash(unsigned):
        reasons.append(f"{token}:incident_sha256")
    return list(dict.fromkeys(reasons))


def load_and_validate_oos_exposure_incident(
    workspace_root: Path,
    report_id: str,
) -> dict[str, Any]:
    path = oos_exposure_incident_path(workspace_root, report_id)
    if not _path_lexists(path):
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_missing")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_invalid_json") from exc
    reasons = validate_oos_exposure_incident(payload)
    if reasons:
        raise ValueError(";".join(reasons))
    if payload.get("report_id") != report_id:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_report_binding")
    return payload


def validate_oos_exposure_provenance_addendum(payload: Any) -> list[str]:
    token = f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum"
    fields = {
        "contract_version",
        "report_id",
        "factor_id",
        "incident_ref",
        "incident_sha256",
        "original_runner_available",
        "runner_ref_role",
        "correction_at",
        "authority",
        "formal_oos_eligible",
        "addendum_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        return [f"{token}:shape"]
    reasons: list[str] = []
    if payload.get("contract_version") != OOS_EXPOSURE_PROVENANCE_ADDENDUM_VERSION:
        reasons.append(f"{token}:version")
    for field in ("report_id", "factor_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
            reasons.append(f"{token}:{field}")
    if not isinstance(payload.get("incident_ref"), str) or not payload.get(
        "incident_ref"
    ):
        reasons.append(f"{token}:incident_ref")
    if not _SHA256_RE.fullmatch(str(payload.get("incident_sha256") or "")):
        reasons.append(f"{token}:incident_sha256")
    if payload.get("original_runner_available") is not False:
        reasons.append(f"{token}:original_runner_available")
    if payload.get("runner_ref_role") != OOS_EXPOSURE_RUNNER_REF_ROLE:
        reasons.append(f"{token}:runner_ref_role")
    correction_at = payload.get("correction_at")
    try:
        parsed = datetime.fromisoformat(str(correction_at or "").replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.tzinfo is None
        or not isinstance(correction_at, str)
        or not correction_at.endswith("Z")
    ):
        reasons.append(f"{token}:correction_at")
    if payload.get("authority") != OOS_EXPOSURE_INCIDENT_AUTHORITY:
        reasons.append(f"{token}:authority")
    if payload.get("formal_oos_eligible") is not False:
        reasons.append(f"{token}:formal_oos_eligible")
    unsigned = dict(payload)
    digest = unsigned.pop("addendum_sha256", None)
    if not isinstance(digest, str) or digest != _stable_hash(unsigned):
        reasons.append(f"{token}:addendum_sha256")
    return list(dict.fromkeys(reasons))


def build_oos_exposure_provenance_addendum(
    *,
    workspace_root: Path,
    report_id: str,
    correction_at: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    incident = load_and_validate_oos_exposure_incident(root, report_id)
    incident_path = oos_exposure_incident_path(root, report_id)
    unsigned: dict[str, Any] = {
        "contract_version": OOS_EXPOSURE_PROVENANCE_ADDENDUM_VERSION,
        "report_id": report_id,
        "factor_id": incident["factor_id"],
        "incident_ref": incident_path.relative_to(root).as_posix(),
        "incident_sha256": _sha256_file(incident_path),
        "original_runner_available": False,
        "runner_ref_role": OOS_EXPOSURE_RUNNER_REF_ROLE,
        "correction_at": correction_at,
        "authority": OOS_EXPOSURE_INCIDENT_AUTHORITY,
        "formal_oos_eligible": False,
    }
    payload = {**unsigned, "addendum_sha256": _stable_hash(unsigned)}
    reasons = validate_oos_exposure_provenance_addendum(payload)
    if reasons:
        raise ValueError(";".join(reasons))
    return payload


def load_and_validate_oos_exposure_provenance_addendum(
    workspace_root: Path,
    report_id: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    path = oos_exposure_provenance_addendum_path(root, report_id)
    if not _path_lexists(path) or not path.is_file() or path.is_symlink():
        raise ValueError(
            f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:missing_or_unsafe"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:invalid_json"
        ) from exc
    reasons = validate_oos_exposure_provenance_addendum(payload)
    if reasons:
        raise ValueError(";".join(reasons))
    incident_path = oos_exposure_incident_path(root, report_id)
    if (
        payload.get("report_id") != report_id
        or payload.get("incident_ref") != incident_path.relative_to(root).as_posix()
        or not incident_path.is_file()
        or incident_path.is_symlink()
        or payload.get("incident_sha256") != _sha256_file(incident_path)
    ):
        raise ValueError(
            f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:incident_binding"
        )
    incident = load_and_validate_oos_exposure_incident(root, report_id)
    if payload.get("factor_id") != incident.get("factor_id"):
        raise ValueError(
            f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:factor_binding"
        )
    return payload


def write_oos_exposure_provenance_addendum_create_only(
    *,
    workspace_root: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    candidate = dict(payload)
    reasons = validate_oos_exposure_provenance_addendum(candidate)
    if reasons:
        raise ValueError(";".join(reasons))
    report_id = str(candidate["report_id"])
    target = oos_exposure_provenance_addendum_path(root, report_id)
    encoded = _pretty_json_bytes(candidate)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _path_lexists(target):
        if target.is_symlink() or not target.is_file() or target.read_bytes() != encoded:
            raise ValueError(
                f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:conflict"
            )
        existing = load_and_validate_oos_exposure_provenance_addendum(root, report_id)
        return {"status": "IDEMPOTENT_EXACT", "path": target, "addendum": existing}
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, target, follow_symlinks=False)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != encoded:
                raise ValueError(
                    f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:conflict"
                )
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    existing = load_and_validate_oos_exposure_provenance_addendum(root, report_id)
    if existing != candidate:
        raise ValueError(
            f"{BLOCK_OOS_EXPOSURE_INCIDENT}:provenance_addendum:post_write_mismatch"
        )
    return {"status": "CREATED_PROVENANCE_CORRECTION", "path": target, "addendum": existing}


def _artifact_reference(workspace_root: Path, raw_path: Path) -> dict[str, str]:
    path = raw_path.expanduser().resolve(strict=True)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:artifact_unsafe:{raw_path}")
    root = workspace_root.expanduser().resolve(strict=True)
    try:
        reference = path.relative_to(root).as_posix()
    except ValueError:
        reference = path.as_posix()
    return {"path": reference, "sha256": _sha256_file(path)}


def build_oos_exposure_incident(
    *,
    workspace_root: Path,
    report_id: str,
    factor_id: str,
    frozen_oos_start: str,
    frozen_oos_end: str,
    frozen_oos_release_token_sha256: str,
    exposed_overlap_start: str,
    exposed_overlap_end: str,
    exposed_row_count: int,
    exposed_period_count: int,
    source_path: Path,
    panel_path: Path,
    metrics_path: Path,
    runner_path: Path,
    incident_at: str,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    unsigned: dict[str, Any] = {
        "contract_version": OOS_EXPOSURE_INCIDENT_VERSION,
        "report_id": _safe_report_id(report_id),
        "factor_id": _safe_report_id(factor_id),
        "frozen_oos_window": {
            "start": frozen_oos_start,
            "end": frozen_oos_end,
        },
        "frozen_oos_release_token_sha256": frozen_oos_release_token_sha256,
        "exposed_overlap_window": {
            "start": exposed_overlap_start,
            "end": exposed_overlap_end,
        },
        "exposed_row_count": exposed_row_count,
        "exposed_period_count": exposed_period_count,
        "artifacts": {
            "source": _artifact_reference(root, source_path),
            "panel": _artifact_reference(root, panel_path),
            "metrics": _artifact_reference(root, metrics_path),
            "runner": _artifact_reference(root, runner_path),
        },
        "incident_at": incident_at,
        "authority": OOS_EXPOSURE_INCIDENT_AUTHORITY,
        "formal_oos_eligible": False,
    }
    payload = {**unsigned, "incident_sha256": _stable_hash(unsigned)}
    reasons = validate_oos_exposure_incident(payload)
    if reasons:
        raise ValueError(";".join(reasons))
    return payload


def write_oos_exposure_incident_create_only(
    *,
    workspace_root: Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Create immutable negative evidence; never issues or restores authority."""

    root = workspace_root.expanduser().resolve(strict=True)
    candidate = dict(payload)
    reasons = validate_oos_exposure_incident(candidate)
    if reasons:
        raise ValueError(";".join(reasons))
    report_id = str(candidate["report_id"])
    target = oos_exposure_incident_path(root, report_id)
    encoded = _pretty_json_bytes(candidate)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _path_lexists(target):
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_conflict_unsafe")
        if target.read_bytes() != encoded:
            raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_conflict_tamper")
        existing = load_and_validate_oos_exposure_incident(root, report_id)
        return {
            "status": "IDEMPOTENT_EXACT",
            "authority": OOS_EXPOSURE_INCIDENT_AUTHORITY,
            "formal_oos_eligible": False,
            "path": target,
            "incident": existing,
        }

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, target, follow_symlinks=False)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != encoded:
                raise ValueError(
                    f"{BLOCK_OOS_EXPOSURE_INCIDENT}:marker_conflict_tamper"
                )
        _fsync_directory(target.parent)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    existing = load_and_validate_oos_exposure_incident(root, report_id)
    if existing != candidate:
        raise ValueError(f"{BLOCK_OOS_EXPOSURE_INCIDENT}:post_write_mismatch")
    return {
        "status": "CREATED_NEGATIVE_EVIDENCE",
        "authority": OOS_EXPOSURE_INCIDENT_AUTHORITY,
        "formal_oos_eligible": False,
        "path": target,
        "incident": existing,
    }


__all__ = [
    "BLOCK_OOS_EXPOSURE_INCIDENT",
    "OOS_EXPOSURE_INCIDENT_AUTHORITY",
    "OOS_EXPOSURE_INCIDENT_VERSION",
    "OOS_EXPOSURE_INSTALLATION_ID_ENV",
    "OOS_EXPOSURE_PRIVATE_REGISTRY_VERSION",
    "OOS_EXPOSURE_PROVENANCE_ADDENDUM_VERSION",
    "OOS_EXPOSURE_RUNNER_REF_ROLE",
    "OOS_EXPOSURE_TRUST_ROOT_ENV",
    "build_oos_exposure_provenance_addendum",
    "build_oos_exposure_incident",
    "load_and_validate_oos_exposure_incident",
    "load_and_validate_oos_exposure_private_registry",
    "load_and_validate_oos_exposure_provenance_addendum",
    "oos_exposure_incident_block_reasons",
    "oos_exposure_incident_path",
    "oos_exposure_private_registry_guard",
    "oos_exposure_private_registry_path",
    "oos_exposure_provenance_addendum_path",
    "validate_oos_exposure_incident",
    "validate_oos_exposure_private_registry_guard",
    "validate_oos_exposure_provenance_addendum",
    "ensure_empty_oos_exposure_private_registry",
    "register_oos_exposure_incident_host_private",
    "write_oos_exposure_incident_create_only",
    "write_oos_exposure_provenance_addendum_create_only",
]
