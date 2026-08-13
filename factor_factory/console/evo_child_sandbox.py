from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from factor_factory.research_org.contracts import stable_json_hash
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
    verify_signed_receipt_with_manifest,
)
from factor_factory.research_conjecture import workspace_runtime_trust_manifest


SANDBOX_ADMISSION_VERSION = "factorforge_console_evo_child_sandbox_admission_v1"
SANDBOX_PROFILE_VERSION = "factorforge_console_evo_child_sandbox_profile_v1"
SANDBOX_RECEIPT_TYPE = "EVO_CHILD_AGENT_EXECUTION_SANDBOX_ADMISSION"
SANDBOX_STATUS = "HOST_ADMITTED_FIXED_EVO_CHILD_SANDBOX"
BLOCK_EVO_CHILD_SANDBOX = "BLOCK_FACTORFORGE_EVO_CHILD_SANDBOX_ADMISSION_INVALID"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_HEX = frozenset("0123456789abcdef")


class EvoChildSandboxError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(item) for item in reasons if item))
        super().__init__(";".join(self.reasons))


def _token(reason: str) -> str:
    return f"{BLOCK_EVO_CHILD_SANDBOX}:{reason}"


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _private_dir(path: Path) -> Path:
    candidate = path.expanduser()
    if candidate.exists() or candidate.is_symlink():
        metadata = candidate.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o077
        ):
            raise EvoChildSandboxError([_token("unsafe_private_directory")])
    else:
        candidate.mkdir(parents=True, mode=0o700)
    candidate = candidate.resolve(strict=True)
    candidate.chmod(0o700)
    return candidate


def _read_private_file(path: Path, *, max_bytes: int = 256_000) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EvoChildSandboxError([_token("private_file_missing_or_symlink")])
    metadata = path.stat()
    if (
        metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= max_bytes
    ):
        raise EvoChildSandboxError([_token("unsafe_private_file")])
    before = (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_size)
    payload = path.read_bytes()
    after_metadata = path.stat()
    after = (
        after_metadata.st_dev,
        after_metadata.st_ino,
        after_metadata.st_mtime_ns,
        after_metadata.st_size,
    )
    if before != after or len(payload) != metadata.st_size:
        raise EvoChildSandboxError([_token("private_file_changed_during_read")])
    return payload


def _write_once(path: Path, payload: bytes) -> bool:
    if path.exists() or path.is_symlink():
        if _read_private_file(path) != payload:
            raise EvoChildSandboxError([_token(f"write_once_mismatch:{path.name}")])
        return False
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
    return True


def _seatbelt_literal(path: Path) -> str:
    value = str(path)
    if "\x00" in value or "\n" in value or "\r" in value:
        raise EvoChildSandboxError([_token("profile_path_control_character")])
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _runtime_read_roots() -> tuple[Path, ...]:
    candidates = {
        Path("/System"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/Library/Frameworks"),
        Path("/opt/homebrew"),
        Path(sys.executable).resolve(strict=True).parent,
        Path(sys.prefix).resolve(strict=True),
        Path(sys.base_prefix).resolve(strict=True),
    }
    return tuple(sorted((path for path in candidates if path.exists()), key=str))


def _fixed_profile(
    *,
    workspace_root: Path,
    worktree: Path,
    scratch_root: Path,
    denied_private_roots: Sequence[Path],
) -> str:
    read_roots = tuple(dict.fromkeys((*_runtime_read_roots(), worktree, workspace_root)))
    lines = [
        f";; {SANDBOX_PROFILE_VERSION}",
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow signal (target self))",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow file-read-metadata)",
        '(allow file-read* (literal "/dev/null") (literal "/dev/urandom"))',
    ]
    lines.extend(
        f"(allow file-read* (subpath {_seatbelt_literal(path)}))"
        for path in read_roots
    )
    lines.extend(
        [
            f"(allow file-write* (subpath {_seatbelt_literal(workspace_root)}))",
            f"(allow file-write* (subpath {_seatbelt_literal(scratch_root)}))",
            "(deny network*)",
        ]
    )
    # Explicit denies are intentionally last and are also protected by the
    # signed admission. process-fork remains denied by default: an Agent must
    # not daemonize and survive until a later OOS publication in the writable
    # workspace.
    lines.extend(
        f"(deny file-read* file-write* (subpath {_seatbelt_literal(path)}))"
        for path in denied_private_roots
    )
    return "\n".join(lines) + "\n"


def _canonical_path(path: Path | str, *, strict: bool = True) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise EvoChildSandboxError([_token("symlink_path")])
    return candidate.resolve(strict=strict)


def _assert_disjoint(path: Path, roots: Sequence[Path], *, label: str) -> None:
    for root in roots:
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            raise EvoChildSandboxError([_token(f"overlapping_roots:{label}")])


def materialize_evo_child_sandbox_admission(
    *,
    state_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    job_id: str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    denied_private_roots: Sequence[Path | str] = (),
) -> dict[str, Any]:
    if (
        not all(_SAFE_ID.fullmatch(value or "") for value in (job_id, parent_report_id, child_report_id))
        or parent_report_id == child_report_id
        or not _is_sha256(expected_host_trust_manifest_sha256)
    ):
        raise EvoChildSandboxError([_token("identity_or_pin")])
    state = _canonical_path(state_root)
    workspace = _canonical_path(workspace_root)
    tree = _canonical_path(worktree)
    workspace.relative_to(tree)
    trust = _canonical_path(trust_root)
    denied = tuple(
        dict.fromkeys(
            _canonical_path(path)
            for path in (state, trust, *denied_private_roots)
        )
    )
    _assert_disjoint(workspace, denied, label="workspace_private")
    _assert_disjoint(tree, denied, label="worktree_private")
    store = load_runtime_trust_store(trust, installation_id=installation_id)
    manifest = workspace_runtime_trust_manifest(workspace, report_id=parent_report_id)
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest != store.public_manifest
        or manifest.get("manifest_sha256") != expected_host_trust_manifest_sha256
    ):
        raise EvoChildSandboxError([_token("trust_manifest_pin")])
    root = _private_dir(state / "jobs" / job_id / "evo-child-sandbox")
    scratch = _private_dir(
        Path(tempfile.gettempdir())
        / f"factorforge-evo-child-{hashlib.sha256((job_id + child_report_id).encode()).hexdigest()[:20]}"
    )
    profile_path = root / f"sandbox__{child_report_id}.sb"
    admission_path = root / f"admission__{child_report_id}.json"
    profile = _fixed_profile(
        workspace_root=workspace,
        worktree=tree,
        scratch_root=scratch,
        denied_private_roots=denied,
    )
    profile_bytes = profile.encode("utf-8")
    _write_once(profile_path, profile_bytes)
    core = {
        "receipt_type": SANDBOX_RECEIPT_TYPE,
        "admission_version": SANDBOX_ADMISSION_VERSION,
        "status": SANDBOX_STATUS,
        "job_id": job_id,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "expected_host_trust_manifest_sha256": expected_host_trust_manifest_sha256,
        "workspace_root": str(workspace),
        "worktree": str(tree),
        "profile": {
            "contract_version": SANDBOX_PROFILE_VERSION,
            "path": str(profile_path),
            "sha256": hashlib.sha256(profile_bytes).hexdigest(),
            "size_bytes": len(profile_bytes),
        },
        "scratch_root": str(scratch),
        "denied_private_roots": [str(path) for path in denied],
        "policy": {
            "default_action": "DENY",
            "network": "DENY",
            "agent_data_credentials": "FORBIDDEN",
            "host_private_state": "DENY",
            "descendant_processes_inherit_policy": True,
            "allowed_stages": ["run_step3b", "validate_step3b", "run_step4", "validate_step4"],
        },
    }
    core["content_sha256"] = stable_json_hash(core)
    admission = store.sign("host_admission", core)
    _write_once(admission_path, _canonical_bytes(admission))
    resolved = validate_evo_child_sandbox_admission(
        admission_path=admission_path,
        workspace_root=workspace,
        worktree=tree,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    return {
        "verdict": "PASS",
        "status": SANDBOX_STATUS,
        "admission_path": str(admission_path),
        "admission_sha256": _sha256(admission_path),
        "profile_path": str(resolved["profile_path"]),
        "profile_sha256": resolved["admission"]["profile"]["sha256"],
        "admission": resolved["admission"],
    }


def validate_evo_child_sandbox_admission(
    *,
    admission_path: Path | str,
    workspace_root: Path | str,
    worktree: Path | str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    if not _is_sha256(expected_host_trust_manifest_sha256):
        raise EvoChildSandboxError([_token("external_host_trust_pin_required")])
    workspace = _canonical_path(workspace_root)
    tree = _canonical_path(worktree)
    workspace.relative_to(tree)
    path = _canonical_path(admission_path)
    raw = _read_private_file(path)
    try:
        admission = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvoChildSandboxError([_token("admission_json")]) from exc
    manifest = workspace_runtime_trust_manifest(workspace, report_id=parent_report_id)
    reasons = []
    if (
        manifest is None
        or validate_public_trust_manifest(manifest)
        or manifest.get("manifest_sha256") != expected_host_trust_manifest_sha256
    ):
        reasons.append(_token("trust_manifest_pin"))
        manifest = {}
    reasons.extend(
        _token(f"signature:{reason}")
        for reason in verify_signed_receipt_with_manifest(
            admission,
            trust_manifest=manifest,
            expected_issuer="host_admission",
        )
    )
    profile = admission.get("profile") if isinstance(admission, dict) else None
    denied_values = admission.get("denied_private_roots") if isinstance(admission, dict) else None
    policy = admission.get("policy") if isinstance(admission, dict) else None
    if (
        not isinstance(admission, dict)
        or admission.get("receipt_type") != SANDBOX_RECEIPT_TYPE
        or admission.get("admission_version") != SANDBOX_ADMISSION_VERSION
        or admission.get("status") != SANDBOX_STATUS
        or admission.get("parent_report_id") != parent_report_id
        or admission.get("child_report_id") != child_report_id
        or admission.get("expected_host_trust_manifest_sha256")
        != expected_host_trust_manifest_sha256
        or admission.get("workspace_root") != str(workspace)
        or admission.get("worktree") != str(tree)
        or not isinstance(profile, dict)
        or set(profile) != {"contract_version", "path", "sha256", "size_bytes"}
        or profile.get("contract_version") != SANDBOX_PROFILE_VERSION
        or not _is_sha256(profile.get("sha256"))
        or not isinstance(denied_values, list)
        or not denied_values
        or len(denied_values) != len(set(denied_values))
        or policy
        != {
            "default_action": "DENY",
            "network": "DENY",
            "agent_data_credentials": "FORBIDDEN",
            "host_private_state": "DENY",
            "descendant_processes_inherit_policy": True,
            "allowed_stages": ["run_step3b", "validate_step3b", "run_step4", "validate_step4"],
        }
    ):
        reasons.append(_token("admission_shape_or_identity"))
    unsigned = {
        key: value
        for key, value in admission.items()
        if key not in {"contract_version", "issuer", "receipt_id", "signature"}
    }
    content = dict(unsigned)
    content_sha = content.pop("content_sha256", None)
    if content_sha != stable_json_hash(content):
        reasons.append(_token("content_sha256"))
    try:
        profile_path = _canonical_path(str((profile or {}).get("path") or ""))
        if profile_path.parent != path.parent:
            reasons.append(_token("profile_not_co_located"))
        denied = tuple(_canonical_path(value) for value in denied_values or [])
        scratch = _canonical_path(str(admission.get("scratch_root") or ""))
        _assert_disjoint(workspace, denied, label="workspace_private")
        _assert_disjoint(tree, denied, label="worktree_private")
        expected_profile = _fixed_profile(
            workspace_root=workspace,
            worktree=tree,
            scratch_root=scratch,
            denied_private_roots=denied,
        ).encode("utf-8")
        actual_profile = _read_private_file(profile_path)
        if (
            actual_profile != expected_profile
            or profile.get("sha256") != hashlib.sha256(expected_profile).hexdigest()
            or profile.get("size_bytes") != len(expected_profile)
        ):
            reasons.append(_token("profile_exact_replay"))
        if b"(allow default)" in actual_profile or b"(deny network*)" not in actual_profile:
            reasons.append(_token("profile_policy"))
    except (EvoChildSandboxError, FileNotFoundError, RuntimeError, ValueError) as exc:
        reasons.extend(
            exc.reasons if isinstance(exc, EvoChildSandboxError) else [_token("profile_readback")]
        )
        profile_path = Path("/")
    if reasons:
        raise EvoChildSandboxError(reasons)
    return {
        "verdict": "PASS",
        "status": SANDBOX_STATUS,
        "admission": admission,
        "admission_path": path,
        "profile_path": profile_path,
    }


__all__ = [
    "BLOCK_EVO_CHILD_SANDBOX",
    "EvoChildSandboxError",
    "SANDBOX_ADMISSION_VERSION",
    "SANDBOX_PROFILE_VERSION",
    "SANDBOX_STATUS",
    "materialize_evo_child_sandbox_admission",
    "validate_evo_child_sandbox_admission",
]
