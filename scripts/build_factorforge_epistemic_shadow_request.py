#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.epistemic_ultimate_shadow import (  # noqa: E402
    AUTHORITY_EFFECT,
    DIAGNOSIS_INPUT_PARENT_NAME,
    HOOK_FAILURE,
    HOOK_STEP1,
    ISOLATION_POLICY,
    REQUEST_PARENT_NAME,
    REQUEST_SCHEMA_ID,
    validate_native_factor_workspace,
)
from factor_factory.research_org.contracts import strict_json_loads  # noqa: E402
from scripts.build_factorforge_epistemic_kernel_offline_candidate import (  # noqa: E402
    MAX_INPUT_BYTES,
    validate_epistemic_kernel_input_payload,
)


INPUT_PARENT_NAME = "candidate_epistemic_shadow_inputs"
KERNEL_INPUT_NAMES = (
    "source_text",
    "source_lineage",
    "author_claims",
    "analyst_notes",
    "selected_semantic_body",
    "formalization_provenance",
    "pre_a0_predictions",
    "phase_policy_candidate",
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _read_input(path: Path, workspace: Path) -> dict:
    _require(path.is_absolute(), "kernel_input:absolute_path_required")
    _require(not path.is_symlink(), "kernel_input:symlink_forbidden")
    input_parent = workspace / INPUT_PARENT_NAME
    _require(
        input_parent.is_dir() and not input_parent.is_symlink(),
        "kernel_input_parent:missing_or_symlink",
    )
    expected_parent = input_parent.resolve(strict=True)
    _require(not os.path.ismount(expected_parent), "kernel_input_parent:mount_forbidden")
    resolved = path.resolve(strict=True)
    _require(
        resolved.parent == expected_parent,
        "kernel_input:outside_candidate_input_root",
    )
    parent_fd = os.open(
        expected_parent,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    descriptor: int | None = None
    try:
        parent_stat = os.fstat(parent_fd)
        _require(
            parent_stat.st_dev == workspace.stat().st_dev,
            "kernel_input_parent:cross_device_forbidden",
        )
        descriptor = os.open(
            resolved.name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "kernel_input:regular_file_required")
        _require(before.st_nlink == 1, "kernel_input:hardlink_forbidden")
        _require(before.st_dev == parent_stat.st_dev, "kernel_input:cross_device_forbidden")
        _require(0 < before.st_size <= MAX_INPUT_BYTES, "kernel_input:size")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            _require(bool(chunk), "kernel_input:short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        _require(
            (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size, before.st_nlink)
            == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size, after.st_nlink),
            "kernel_input:mutated_during_read",
        )
        raw = b"".join(chunks)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)
    payload = strict_json_loads(raw, label="epistemic-shadow-kernel-input")
    return validate_epistemic_kernel_input_payload(payload)


def _request(
    *,
    report_id: str,
    hook: str,
    kernel_input: dict,
    target_factor_id: str | None,
) -> dict:
    diagnosis_scope = None
    if hook == HOOK_FAILURE:
        _require(
            isinstance(target_factor_id, str) and bool(target_factor_id.strip()),
            "failure_hook:target_factor_id_required",
        )
        diagnosis_scope = {
            "target_report_id": report_id,
            "target_factor_id": target_factor_id,
            "linkage_status": (
                "CALLER_CLAIMED_CURRENT_FACTOR_TARGET__NOT_INDEPENDENTLY_VERIFIED"
            ),
        }
    else:
        _require(target_factor_id is None, "step1_hook:target_factor_id_forbidden")
    return {
        "schema_id": REQUEST_SCHEMA_ID,
        "schema_version": "1.0.0",
        "report_id": report_id,
        "hook": hook,
        "kernel_input_candidate": kernel_input,
        "derivation_ledger": [
            {
                "ordinal": ordinal,
                "target_pointer": f"/kernel_input_candidate/{name}",
                "derivation_class": "CALLER_SUPPLIED_PRE_RETRIEVAL_CANDIDATE",
                "source_artifact_role": None,
                "source_pointer": None,
                "source_value_sha256": None,
            }
            for ordinal, name in enumerate(KERNEL_INPUT_NAMES)
        ],
        "diagnosis_target_scope": diagnosis_scope,
        "isolation_policy": dict(ISOLATION_POLICY),
        "candidate_only": True,
        "signed": False,
        "authority_effect": AUTHORITY_EFFECT,
    }


def _publish(
    workspace: Path,
    name: str,
    payload: bytes,
    *,
    expected_workspace_device: str,
    expected_workspace_inode: str,
) -> Path:
    _require(re.fullmatch(r"shadow_request_[0-9a-f]{32}\.json", name) is not None, "output:name")
    workspace_fd = os.open(
        workspace,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    parent_fd: int | None = None
    try:
        workspace_stat = os.fstat(workspace_fd)
        _require(
            str(workspace_stat.st_dev) == expected_workspace_device
            and str(workspace_stat.st_ino) == expected_workspace_inode,
            "output:workspace_binding_mismatch",
        )
        try:
            os.mkdir(REQUEST_PARENT_NAME, mode=0o700, dir_fd=workspace_fd)
        except FileExistsError:
            pass
        parent_fd = os.open(
            REQUEST_PARENT_NAME,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=workspace_fd,
        )
        parent_stat = os.fstat(parent_fd)
        _require(stat.S_ISDIR(parent_stat.st_mode), "output:parent_not_directory")
        _require(
            not os.path.ismount(workspace / REQUEST_PARENT_NAME),
            "output:parent_mount_forbidden",
        )
        _require(
            parent_stat.st_dev == workspace_stat.st_dev,
            "output:parent_cross_device_forbidden",
        )
        try:
            descriptor = os.open(
                name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            try:
                existing_stat = os.fstat(descriptor)
                _require(
                    stat.S_ISREG(existing_stat.st_mode),
                    "output:idempotent_target_not_regular",
                )
                _require(
                    existing_stat.st_nlink == 1,
                    "output:idempotent_target_hardlink_forbidden",
                )
                _require(
                    existing_stat.st_dev == parent_stat.st_dev,
                    "output:idempotent_target_cross_device_forbidden",
                )
                existing = bytearray()
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    existing.extend(chunk)
                _require(
                    bytes(existing) == payload,
                    "output:idempotent_bytes_mismatch",
                )
            finally:
                os.close(descriptor)
            return workspace / REQUEST_PARENT_NAME / name
        try:
            created_stat = os.fstat(descriptor)
            _require(
                stat.S_ISREG(created_stat.st_mode)
                and created_stat.st_nlink == 1
                and created_stat.st_dev == parent_stat.st_dev,
                "output:new_target_physical_identity",
            )
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                _require(written > 0, "output:short_write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return workspace / REQUEST_PARENT_NAME / name
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(workspace_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one closed, candidate-only Ultimate epistemic shadow request."
    )
    parser.add_argument("--factor-workspace", type=Path, required=True)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--kernel-input", type=Path, required=True)
    parser.add_argument(
        "--hook",
        choices=(HOOK_STEP1, HOOK_FAILURE),
        default=HOOK_STEP1,
    )
    parser.add_argument("--diagnosis-target-factor-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        workspace_path = args.factor_workspace.expanduser()
        _require(
            workspace_path.is_absolute()
            and workspace_path.is_dir()
            and not workspace_path.is_symlink(),
            "factor_workspace:real_absolute_directory_required",
        )
        workspace = workspace_path.resolve(strict=True)
        _, workspace_binding, _ = validate_native_factor_workspace(
            workspace=workspace, repo_root=REPO_ROOT
        )
        kernel_input = _read_input(args.kernel_input.expanduser(), workspace)
        if args.hook == HOOK_FAILURE:
            diagnosis = kernel_input.get("diagnosis_inputs")
            _require(isinstance(diagnosis, dict), "failure_hook:diagnosis_inputs_required")
            diagnosis_root = workspace / DIAGNOSIS_INPUT_PARENT_NAME
            _require(
                diagnosis_root.is_dir() and not diagnosis_root.is_symlink(),
                "failure_hook:diagnosis_input_parent_missing_or_symlink",
            )
            resolved_root = diagnosis_root.resolve(strict=True)
            root_stat = resolved_root.stat()
            _require(
                resolved_root.parent == workspace,
                "failure_hook:diagnosis_input_parent_not_direct_workspace_child",
            )
            _require(
                not os.path.ismount(resolved_root),
                "failure_hook:diagnosis_input_parent_mount_forbidden",
            )
            _require(
                root_stat.st_dev == workspace.stat().st_dev,
                "failure_hook:diagnosis_input_parent_cross_device_forbidden",
            )
            physical_identities: set[tuple[int, int]] = set()
            for field in (
                "stage2_manifest_path",
                "fixture_json_path",
                "assertion_dependency_json_path",
            ):
                raw_path = diagnosis.get(field)
                _require(isinstance(raw_path, str), f"failure_hook:{field}:path_required")
                path = Path(raw_path).expanduser()
                _require(
                    path.is_absolute() and path.is_file() and not path.is_symlink(),
                    f"failure_hook:{field}:regular_absolute_file_required",
                )
                resolved = path.resolve(strict=True)
                _require(
                    resolved.parent == resolved_root,
                    f"failure_hook:{field}:outside_dedicated_diagnosis_root",
                )
                _require(
                    not os.path.ismount(resolved),
                    f"failure_hook:{field}:mount_forbidden",
                )
                metadata = resolved.stat()
                _require(
                    metadata.st_nlink == 1,
                    f"failure_hook:{field}:hardlink_forbidden",
                )
                _require(
                    metadata.st_dev == root_stat.st_dev,
                    f"failure_hook:{field}:cross_device_forbidden",
                )
                identity = (metadata.st_dev, metadata.st_ino)
                _require(
                    identity not in physical_identities,
                    "failure_hook:diagnosis_input_physical_identity_reuse_forbidden",
                )
                physical_identities.add(identity)
        request = _request(
            report_id=args.report_id,
            hook=args.hook,
            kernel_input=kernel_input,
            target_factor_id=args.diagnosis_target_factor_id,
        )
        payload = _json_bytes(request)
        # The content address covers the complete closed request, including the
        # current-factor diagnosis target.  Repeated construction is therefore
        # byte-idempotent while distinct scopes can never collide by filename.
        name = (
            "shadow_request_" + hashlib.sha256(payload).hexdigest()[:32] + ".json"
        )
        output = _publish(
            workspace,
            name,
            payload,
            expected_workspace_device=workspace_binding["workspace_device"],
            expected_workspace_inode=workspace_binding["workspace_inode"],
        )
    except Exception as exc:
        print(f"BLOCK_FACTORFORGE_EPISTEMIC_SHADOW_REQUEST: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
