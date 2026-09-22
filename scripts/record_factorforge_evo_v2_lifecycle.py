#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.evo_v2 import sha256_file
from factor_factory.research_conjecture import (
    build_epistemic_evolution_lifecycle,
    epistemic_evolution_lifecycle_path,
    epistemic_evolution_lifecycle_snapshot_path,
    load_json,
    validate_epistemic_evolution_lifecycle,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_evidence import validate_evidence_reference
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.runtime_trust import load_runtime_trust_store

TOKEN = "BLOCK_FACTORFORGE_EPISTEMIC_EVOLUTION_LIFECYCLE_WRITE"
ALLOWED = {
    None: {"PREDICTIONS_FROZEN"},
    "PREDICTIONS_FROZEN": {
        "NO_QUALIFIED_CONTRADICTION",
        "QUALIFIED_CONTRADICTION",
    },
    "QUALIFIED_CONTRADICTION": {
        "MINIMAL_MECHANISM_DELTA",
        "NO_DERIVED_LAW",
    },
    "MINIMAL_MECHANISM_DELTA": {
        "TRANSFER_RECORDED",
        "COLD_START_RECORDED",
    },
}


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cleanup_atomic_temporaries(path: Path, *, target_is_exact: bool) -> None:
    prefix = f".{path.name}."
    for candidate in path.parent.iterdir():
        if not (candidate.name.startswith(prefix) and candidate.name.endswith(".tmp")):
            continue
        metadata = candidate.lstat()
        linked_exact_target = (
            target_is_exact and metadata.st_nlink == 2 and candidate.samefile(path)
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_nlink != 1 and not linked_exact_target)
        ):
            raise ValueError(f"{TOKEN}:UNSAFE_ATOMIC_TEMPORARY:{candidate.name}")
        candidate.unlink()


def _write_temporary(path: Path, expected: bytes) -> Path:
    descriptor, raw = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw)
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("atomic_write_made_no_progress")
            offset += written
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    return temporary


def _write_once_or_cas(
    path: Path,
    payload: dict[str, Any],
    expected_hash: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError(f"{TOKEN}:UNSAFE_PARENT")
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{TOKEN}:CURRENT_LIFECYCLE_UNSAFE")
        current = load_json(path)
        if path.read_bytes() != _json_bytes(current):
            raise ValueError(f"{TOKEN}:CURRENT_LIFECYCLE_NONCANONICAL")
        if current == payload:
            _cleanup_atomic_temporaries(path, target_is_exact=True)
            return
        if expected_hash is None or stable_hash(current) != expected_hash:
            raise ValueError(f"{TOKEN}:STALE_PARENT")
    elif expected_hash is not None:
        raise ValueError(f"{TOKEN}:PARENT_MISSING")
    _cleanup_atomic_temporaries(path, target_is_exact=False)
    temporary = _write_temporary(path, _json_bytes(payload))
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _write_immutable_json(
    path: Path,
    payload: dict[str, Any],
    *,
    conflict: str = "SNAPSHOT_CONFLICT",
) -> None:
    expected = _json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError(f"{TOKEN}:UNSAFE_PARENT")
    target_exists = path.exists() or path.is_symlink()
    target_is_exact = (
        target_exists
        and not path.is_symlink()
        and path.is_file()
        and path.read_bytes() == expected
    )
    if target_exists and not target_is_exact:
        raise ValueError(f"{TOKEN}:{conflict}")
    _cleanup_atomic_temporaries(path, target_is_exact=target_is_exact)
    if target_is_exact:
        return
    temporary = _write_temporary(path, expected)
    try:
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise ValueError(f"{TOKEN}:{conflict}")
            return
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _lifecycle_parent_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    events = payload.get("events")
    if not isinstance(events, list) or len(events) <= 1:
        return None
    prior = events[-2]
    if not isinstance(prior, dict):
        return None
    parent = {
        "contract_version": payload.get("contract_version"),
        "report_id": payload.get("report_id"),
        "current_state": prior.get("to_state"),
        "events": events[:-1],
        "host_authority": payload.get("host_authority"),
    }
    parent["content_sha256"] = stable_hash(parent)
    return parent


def _is_exact_transition_replay(
    payload: dict[str, Any] | None,
    *,
    to_state: str,
    evidence_refs: list[dict[str, Any]],
    expected_parent_sha256: str | None,
) -> bool:
    if not isinstance(payload, dict) or payload.get("current_state") != to_state:
        return False
    events = payload.get("events")
    if not isinstance(events, list) or not events or not isinstance(events[-1], dict):
        return False
    event = events[-1]
    parent = _lifecycle_parent_payload(payload)
    parent_sha256 = stable_hash(parent) if parent is not None else None
    return (
        parent_sha256 == expected_parent_sha256
        and event.get("to_state") == to_state
        and event.get("evidence_refs") == evidence_refs
        and event.get("actor") == "Ultimate Host"
        and isinstance(event.get("actor_receipt_ref"), dict)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Host-only append/CAS writer for the Factor Forge EVO V2 lifecycle."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--to-state", required=True)
    parser.add_argument("--evidence-ref", action="append", required=True)
    parser.add_argument("--expected-parent-sha256")
    parser.add_argument("--trust-root", required=True)
    parser.add_argument("--installation-id", required=True)
    args = parser.parse_args()
    root = Path(args.workspace_root).expanduser().resolve(strict=True)
    private_root = Path(args.trust_root).expanduser().resolve(strict=True)
    if (
        private_root == root
        or root in private_root.parents
        or private_root in root.parents
    ):
        print(f"{TOKEN}:TRUST_ROOT_OVERLAPS_WORKSPACE", file=sys.stderr)
        return 1
    path = epistemic_evolution_lifecycle_path(root, args.report_id)
    evidence_refs = [json.loads(item) for item in args.evidence_ref]
    reasons = [
        reason
        for index, reference in enumerate(evidence_refs)
        for reason in validate_evidence_reference(
            reference,
            workspace_root=root,
            token_prefix=f"{TOKEN}:EVIDENCE:{index}",
            require_verifier_pass=True,
        )
    ]
    if reasons:
        print(
            json.dumps({"verdict": "BLOCK", "reasons": reasons}, indent=2),
            file=sys.stderr,
        )
        return 1
    try:
        trust_store = load_runtime_trust_store(
            private_root,
            installation_id=args.installation_id,
        )
        projected_manifest = workspace_runtime_trust_manifest(
            root, report_id=args.report_id
        )
        if projected_manifest != trust_store.public_manifest:
            raise ValueError(f"{TOKEN}:TRUST_MANIFEST_MISMATCH")
        lock_path = path.with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_descriptor = os.open(
            lock_path,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            if path.is_symlink():
                raise ValueError(f"{TOKEN}:CURRENT_LIFECYCLE_UNSAFE")
            locked_existing = load_json(path) if path.is_file() else None
            locked_parent = stable_hash(locked_existing) if locked_existing else None
            exact_replay = _is_exact_transition_replay(
                locked_existing,
                to_state=args.to_state,
                evidence_refs=evidence_refs,
                expected_parent_sha256=args.expected_parent_sha256,
            )
            if exact_replay:
                assert locked_existing is not None
                payload = locked_existing
                event = payload["events"][-1]
                receipt_ref = event["actor_receipt_ref"]
                receipt_path = (root / receipt_ref["path"]).resolve(strict=False)
                try:
                    receipt_path.relative_to(root)
                except ValueError as exc:
                    raise ValueError(f"{TOKEN}:RECEIPT_PATH_ESCAPE") from exc
                if receipt_path.is_symlink() or not receipt_path.is_file():
                    raise ValueError(f"{TOKEN}:RECEIPT_UNSAFE")
                receipt = load_json(receipt_path)
                _write_immutable_json(
                    receipt_path,
                    receipt,
                    conflict="RECEIPT_CONFLICT",
                )
            else:
                if locked_parent != args.expected_parent_sha256:
                    raise ValueError(f"{TOKEN}:STALE_PARENT")
                from_state = (
                    locked_existing.get("current_state") if locked_existing else None
                )
                if args.to_state not in ALLOWED.get(from_state, set()):
                    raise ValueError(
                        f"{TOKEN}:INVALID_TRANSITION:{from_state}->{args.to_state}"
                    )
                sequence = len((locked_existing or {}).get("events") or []) + 1
                receipt = trust_store.sign(
                    "host_admission",
                    {
                        "receipt_type": "EVO_V2_LIFECYCLE_TRANSITION",
                        "report_id": args.report_id,
                        "sequence": sequence,
                        "from_state": from_state,
                        "to_state": args.to_state,
                        "lifecycle_parent_sha256": locked_parent,
                        "evidence_refs_sha256": stable_hash(evidence_refs),
                        "trust_manifest_sha256": projected_manifest["manifest_sha256"],
                        "authority_scope": (
                            "HOST_LIFECYCLE_TRANSITION_ONLY_NO_RESEARCH_"
                            "SEMANTIC_AUTHORITY"
                        ),
                        "oos_accessed": False,
                    },
                )
                receipt_path = (
                    path.parent / f"lifecycle_transition_receipt__{sequence:04d}.json"
                )
                _write_immutable_json(
                    receipt_path,
                    receipt,
                    conflict="RECEIPT_CONFLICT",
                )
                host_receipt_ref = {
                    "path": receipt_path.relative_to(root).as_posix(),
                    "sha256": sha256_file(receipt_path),
                    "receipt_id": receipt["receipt_id"],
                    "trust_manifest_sha256": projected_manifest["manifest_sha256"],
                }
                payload = build_epistemic_evolution_lifecycle(
                    report_id=args.report_id,
                    to_state=args.to_state,
                    evidence_refs=evidence_refs,
                    existing=locked_existing,
                    actor_receipt_ref=host_receipt_ref,
                )
            validation = validate_epistemic_evolution_lifecycle(
                payload,
                report_id=args.report_id,
                workspace_root=root,
                trust_manifest=projected_manifest,
            )
            if validation:
                raise ValueError(f"{TOKEN}:" + ";".join(validation))
            prior = (
                _lifecycle_parent_payload(payload) if exact_replay else locked_existing
            )
            if prior is not None:
                prior_generation = len(prior.get("events") or [])
                prior_snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
                    root,
                    args.report_id,
                    prior_generation,
                )
                _write_immutable_json(prior_snapshot_path, prior)
            generation = len(payload.get("events") or [])
            snapshot_path = epistemic_evolution_lifecycle_snapshot_path(
                root,
                args.report_id,
                generation,
            )
            _write_immutable_json(snapshot_path, payload)
            _write_once_or_cas(path, payload, args.expected_parent_sha256)
        finally:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            os.close(lock_descriptor)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "verdict": "PASS",
                "path": str(path),
                "current_state": args.to_state,
                "lifecycle_sha256": stable_hash(payload),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
