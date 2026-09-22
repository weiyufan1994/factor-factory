from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from factor_factory.console.catalog_health import CATALOG_MAX_BYTES
from factor_factory.console.private_job_root import (
    PrivateJobRootError,
    ensure_host_private_job_subdirectory,
)
from factor_factory.console.web_factor_proof import (
    validate_trusted_calendar_snapshot,
)
from factor_factory.research_org.contracts import stable_json_hash


PROJECTION_VERSION = "factorforge_console_evo_child_catalog_projection_v1"
BLOCK_EVO_CHILD_CATALOG = "BLOCK_FACTORFORGE_EVO_CHILD_CATALOG_PROJECTION_INVALID"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_FROZEN_CATALOG_VERSION = "factorforge_console_job_frozen_catalog_v1"


class EvoChildCatalogProjectionError(RuntimeError):
    pass


def _fail(reason: str) -> EvoChildCatalogProjectionError:
    return EvoChildCatalogProjectionError(f"{BLOCK_EVO_CHILD_CATALOG}:{reason}")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _read_stable_regular(path: Path, *, limit: int, label: str) -> bytes:
    candidate = path.expanduser()
    try:
        if candidate.is_symlink():
            raise _fail(f"{label}_symlink")
        descriptor = os.open(
            candidate,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as exc:
        raise _fail(f"{label}_missing_or_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink < 1
            or before.st_size <= 0
            or before.st_size > limit
        ):
            raise _fail(f"{label}_not_bounded_regular")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise _fail(f"{label}_short_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise _fail(f"{label}_grew_during_read")
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise _fail(f"{label}_changed_during_read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _safe_parent(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise _fail("projection_outside_engine") from exc
    current = root
    for part in relative.parent.parts:
        current = current / part
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise _fail("projection_parent_unsafe")
        try:
            current.resolve(strict=True).relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise _fail("projection_parent_unsafe") from exc


def _write_once(root: Path, path: Path, raw: bytes) -> None:
    _safe_parent(root, path)
    if path.exists() or path.is_symlink():
        if (
            path.is_symlink()
            or not path.is_file()
            or _read_stable_regular(
                path,
                limit=max(CATALOG_MAX_BYTES, 2 * 1024 * 1024),
                label="existing_projection",
            )
            != raw
        ):
            raise _fail(f"immutable_projection_conflict:{path.name}")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o400)
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise _fail("projection_short_write")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if (
                path.is_symlink()
                or not path.is_file()
                or _read_stable_regular(
                    path,
                    limit=max(CATALOG_MAX_BYTES, 2 * 1024 * 1024),
                    label="existing_projection",
                )
                != raw
            ):
                raise _fail(f"immutable_projection_conflict:{path.name}")
        directory = os.open(
            path.parent,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _read_frozen_catalog_summary(workspace: Path) -> dict[str, Any]:
    summary_path = workspace / "identity" / "data_catalog_summary.json"
    summary_raw = _read_stable_regular(
        summary_path,
        limit=CATALOG_MAX_BYTES,
        label="workspace_catalog_summary",
    )
    try:
        summary = json.loads(summary_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("workspace_catalog_summary_json") from exc
    catalogs = summary.get("catalogs") if isinstance(summary, dict) else None
    admission = (
        summary.get("active_catalog_admission")
        if isinstance(summary, dict)
        else None
    )
    if (
        not isinstance(summary, dict)
        or summary.get("version") != "factorforge_web_data_catalog_summary_v2"
        or not isinstance(catalogs, list)
        or len(catalogs) != 1
        or not isinstance(catalogs[0], dict)
        or not isinstance(admission, dict)
    ):
        raise _fail("workspace_catalog_summary_shape")
    digest = str(catalogs[0].get("catalog_sha256") or "").lower()
    filename = str(catalogs[0].get("catalog_name") or "")
    if _HEX64.fullmatch(digest) is None or Path(filename).name != filename:
        raise _fail("workspace_catalog_summary_identity")
    if admission.get("version") != "factorforge_console_catalog_admission_v1":
        raise _fail("catalog_admission_version")
    if admission.get("formal_dataset_qa_implied") is not False:
        raise _fail("catalog_admission_authority")
    if admission.get("verdict") == "PASS":
        if (
            admission.get("catalog_sha256") != digest
            or admission.get("host_catalog_filename") != filename
        ):
            raise _fail("catalog_admission_binding")
    elif not (
        admission.get("verdict") == "NOT_APPLICABLE"
        and admission.get("admission_scope") == "local_or_test_catalog_snapshot"
    ):
        raise _fail("catalog_admission_verdict")
    return {
        "summary_path": summary_path,
        "summary_raw": summary_raw,
        "summary": summary,
        "catalog_digest": digest,
        "catalog_filename": filename,
        "catalog_admission": admission,
    }


def _private_write_once(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or _read_private_once(path) != raw:
            raise _fail(f"immutable_frozen_catalog_conflict:{path.name}")
        return
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
        if path.is_symlink() or _read_private_once(path) != raw:
            raise _fail(f"immutable_frozen_catalog_conflict:{path.name}")
        return
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise _fail("frozen_catalog_short_write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(
        path.parent,
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_private_once(path: Path) -> bytes:
    raw = _read_stable_regular(
        path,
        limit=max(CATALOG_MAX_BYTES, 2 * 1024 * 1024),
        label="frozen_catalog_artifact",
    )
    metadata = path.lstat()
    if (
        path.is_symlink()
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise _fail("frozen_catalog_artifact_permissions")
    return raw


def _frozen_catalog_paths(
    state_root: Path | str,
    *,
    job_id: str,
    digest: str,
    create: bool,
) -> tuple[Path, Path]:
    if _HEX64.fullmatch(digest) is None:
        raise _fail("frozen_catalog_digest")
    try:
        root = ensure_host_private_job_subdirectory(
            state_root,
            job_id,
            ("catalog-snapshots",),
            create=create,
        )
    except PrivateJobRootError as exc:
        raise _fail("frozen_catalog_private_root") from exc
    return root / f"{digest}.json", root / f"{digest}.receipt.json"


def resolve_host_job_frozen_catalog_snapshot(
    *,
    state_root: Path | str,
    workspace_root: Path | str,
    job_id: str,
) -> dict[str, Any]:
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    frozen = _read_frozen_catalog_summary(workspace)
    snapshot_path, receipt_path = _frozen_catalog_paths(
        state_root,
        job_id=job_id,
        digest=frozen["catalog_digest"],
        create=False,
    )
    snapshot_raw = _read_private_once(snapshot_path)
    receipt_raw = _read_private_once(receipt_path)
    try:
        receipt = json.loads(receipt_raw)
        catalog = json.loads(snapshot_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("frozen_catalog_json") from exc
    datasets = catalog.get("datasets") if isinstance(catalog, dict) else None
    core = dict(receipt) if isinstance(receipt, dict) else {}
    content_sha256 = core.pop("content_sha256", None)
    expected_summary_ref = {
        "path": frozen["summary_path"].relative_to(workspace).as_posix(),
        "sha256": _sha256_bytes(frozen["summary_raw"]),
        "size_bytes": len(frozen["summary_raw"]),
    }
    if (
        not isinstance(receipt, dict)
        or receipt.get("version") != _FROZEN_CATALOG_VERSION
        or receipt.get("status") != "HOST_FROZEN_JOB_CATALOG"
        or receipt.get("job_id") != job_id
        or receipt.get("catalog_sha256") != frozen["catalog_digest"]
        or receipt.get("catalog_filename") != frozen["catalog_filename"]
        or receipt.get("catalog_bytes") != len(snapshot_raw)
        or receipt.get("catalog_admission") != frozen["catalog_admission"]
        or receipt.get("workspace_catalog_summary") != expected_summary_ref
        or content_sha256 != stable_json_hash(core)
        or _sha256_bytes(snapshot_raw) != frozen["catalog_digest"]
        or not isinstance(datasets, list)
        or not datasets
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("dataset_id"), str)
            and bool(item["dataset_id"].strip())
            for item in datasets
        )
    ):
        raise _fail("frozen_catalog_replay")
    return {
        "verdict": "PASS",
        "snapshot_path": str(snapshot_path.resolve(strict=True)),
        "snapshot_sha256": frozen["catalog_digest"],
        "catalog_admission": frozen["catalog_admission"],
        "receipt_path": str(receipt_path.resolve(strict=True)),
        "receipt_sha256": _sha256_bytes(receipt_raw),
    }


def materialize_host_job_frozen_catalog_snapshot(
    *,
    state_root: Path | str,
    workspace_root: Path | str,
    approved_catalog_path: Path | str,
    job_id: str,
) -> dict[str, Any]:
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    frozen = _read_frozen_catalog_summary(workspace)
    snapshot_path, receipt_path = _frozen_catalog_paths(
        state_root,
        job_id=job_id,
        digest=frozen["catalog_digest"],
        create=True,
    )
    if snapshot_path.exists() and receipt_path.exists():
        return resolve_host_job_frozen_catalog_snapshot(
            state_root=state_root,
            workspace_root=workspace,
            job_id=job_id,
        )
    if receipt_path.exists() and not snapshot_path.exists():
        raise _fail("frozen_catalog_snapshot_missing")
    if snapshot_path.exists():
        raw = _read_private_once(snapshot_path)
    else:
        source = Path(approved_catalog_path).expanduser()
        if source.name != frozen["catalog_filename"]:
            raise _fail("current_catalog_filename_changed_before_freeze")
        raw = _read_stable_regular(
            source,
            limit=CATALOG_MAX_BYTES,
            label="approved_catalog",
        )
    if _sha256_bytes(raw) != frozen["catalog_digest"]:
        raise _fail("current_catalog_changed_before_freeze")
    core = {
        "version": _FROZEN_CATALOG_VERSION,
        "status": "HOST_FROZEN_JOB_CATALOG",
        "job_id": job_id,
        "catalog_sha256": frozen["catalog_digest"],
        "catalog_filename": frozen["catalog_filename"],
        "catalog_bytes": len(raw),
        "catalog_admission": frozen["catalog_admission"],
        "workspace_catalog_summary": {
            "path": frozen["summary_path"].relative_to(workspace).as_posix(),
            "sha256": _sha256_bytes(frozen["summary_raw"]),
            "size_bytes": len(frozen["summary_raw"]),
        },
        "authority": {
            "host_private_job_snapshot": True,
            "current_catalog_replay_authority": False,
            "workspace_summary_selects_hash_only": True,
        },
    }
    receipt = {**core, "content_sha256": stable_json_hash(core)}
    if not snapshot_path.exists():
        _private_write_once(snapshot_path, raw)
    _private_write_once(receipt_path, _canonical_bytes(receipt))
    return resolve_host_job_frozen_catalog_snapshot(
        state_root=state_root,
        workspace_root=workspace,
        job_id=job_id,
    )


def evo_child_catalog_projection_paths(
    engine_root: Path | str,
    *,
    job_id: str,
    child_report_id: str,
) -> tuple[Path, Path]:
    if not all(_SAFE_ID.fullmatch(value or "") for value in (job_id, child_report_id)):
        raise _fail("unsafe_identity")
    engine = Path(engine_root).expanduser().resolve(strict=True)
    root = (
        engine
        / "factor_research"
        / ".host_catalog_projections"
        / job_id
        / child_report_id
    )
    return root / "data_catalog.json", root / "catalog_projection.json"


def evo_child_calendar_projection_paths(
    engine_root: Path | str,
    *,
    job_id: str,
    child_report_id: str,
) -> tuple[Path, Path]:
    catalog_path, _ = evo_child_catalog_projection_paths(
        engine_root, job_id=job_id, child_report_id=child_report_id
    )
    return catalog_path.parent / "trusted_trade_calendar.csv", catalog_path.parent / "calendar_projection.json"


def _load_projection_inputs(
    *,
    engine_root: Path | str,
    workspace_root: Path | str,
    approved_catalog_path: Path | str,
    approved_catalog_admission: Mapping[str, Any],
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    if not all(
        _SAFE_ID.fullmatch(value or "")
        for value in (job_id, parent_report_id, child_report_id)
    ) or parent_report_id == child_report_id:
        raise _fail("unsafe_or_colliding_identity")
    engine = Path(engine_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    try:
        workspace.relative_to(engine)
    except ValueError as exc:
        raise _fail("workspace_outside_engine") from exc
    source = Path(approved_catalog_path).expanduser()
    catalog_raw = _read_stable_regular(
        source, limit=CATALOG_MAX_BYTES, label="approved_catalog"
    )
    try:
        catalog = json.loads(catalog_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("approved_catalog_json") from exc
    datasets = catalog.get("datasets") if isinstance(catalog, dict) else None
    if (
        not isinstance(catalog, dict)
        or not isinstance(datasets, list)
        or not datasets
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("dataset_id"), str)
            and bool(item["dataset_id"].strip())
            for item in datasets
        )
    ):
        raise _fail("approved_catalog_schema")
    digest = _sha256_bytes(catalog_raw)
    admission = dict(approved_catalog_admission)
    if admission.get("version") != "factorforge_console_catalog_admission_v1":
        raise _fail("catalog_admission_version")
    if admission.get("formal_dataset_qa_implied") is not False:
        raise _fail("catalog_admission_authority")
    if admission.get("verdict") == "PASS":
        if (
            admission.get("catalog_sha256") != digest
            or admission.get("catalog_bytes") != len(catalog_raw)
            or admission.get("dataset_count") != len(datasets)
            or admission.get("schema_version") != catalog.get("schema_version")
        ):
            raise _fail("catalog_admission_binding")
    elif not (
        admission.get("verdict") == "NOT_APPLICABLE"
        and admission.get("admission_scope") == "local_or_test_catalog_snapshot"
    ):
        raise _fail("catalog_admission_verdict")
    summary_path = workspace / "identity" / "data_catalog_summary.json"
    summary_raw = _read_stable_regular(
        summary_path, limit=CATALOG_MAX_BYTES, label="workspace_catalog_summary"
    )
    try:
        summary = json.loads(summary_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("workspace_catalog_summary_json") from exc
    summaries = summary.get("catalogs") if isinstance(summary, dict) else None
    matching_summaries = [
        item
        for item in (summaries or [])
        if isinstance(item, dict) and item.get("catalog_sha256") == digest
    ]
    if (
        not isinstance(summary, dict)
        or summary.get("active_catalog_admission") != admission
        or not isinstance(summaries, list)
        or len(matching_summaries) != 1
    ):
        raise _fail("workspace_catalog_summary_binding")
    catalog_filename = str(matching_summaries[0].get("catalog_name") or "")
    if (
        Path(catalog_filename).name != catalog_filename
        or (
            admission.get("verdict") == "PASS"
            and admission.get("host_catalog_filename") != catalog_filename
        )
    ):
        raise _fail("workspace_catalog_summary_filename")
    snapshot_path, projection_path = evo_child_catalog_projection_paths(
        engine, job_id=job_id, child_report_id=child_report_id
    )
    try:
        snapshot_path.relative_to(engine)
        projection_path.relative_to(engine)
        snapshot_path.relative_to(workspace)
    except ValueError:
        pass
    else:
        raise _fail("projection_must_be_outside_writable_workspace")
    catalog_identity = {
        "catalog_sha256": digest,
        "catalog_bytes": len(catalog_raw),
        "schema_version": catalog.get("schema_version"),
        "dataset_count": len(datasets),
        "dataset_ids_sha256": stable_json_hash(
            [str(item["dataset_id"]) for item in datasets]
        ),
        "host_catalog_filename": catalog_filename,
    }
    snapshot_ref = {
        "path": snapshot_path.relative_to(engine).as_posix(),
        "sha256": digest,
        "size_bytes": len(catalog_raw),
    }
    summary_ref = {
        "path": summary_path.relative_to(engine).as_posix(),
        "sha256": _sha256_bytes(summary_raw),
        "size_bytes": len(summary_raw),
    }
    core = {
        "projection_version": PROJECTION_VERSION,
        "status": "HOST_PROJECTED_APPROVED_CATALOG",
        "identity": {
            "job_id": job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
        },
        "catalog_identity": catalog_identity,
        "catalog_admission": admission,
        "catalog_admission_sha256": stable_json_hash(admission),
        "snapshot": snapshot_ref,
        "workspace_catalog_summary": summary_ref,
        "authority": {
            "host_projection_only": True,
            "external_source_path_disclosed_to_agent": False,
            "formal_dataset_qa_implied": False,
            "container_engine_mount_required": "READ_ONLY",
            "container_workspace_mount_source_allowed": False,
        },
    }
    projection = {**core, "content_sha256": stable_json_hash(core)}
    return {
        "engine": engine,
        "workspace": workspace,
        "catalog_raw": catalog_raw,
        "snapshot_path": snapshot_path,
        "projection_path": projection_path,
        "projection": projection,
    }


def materialize_evo_child_catalog_projection(
    *,
    engine_root: Path | str,
    workspace_root: Path | str,
    approved_catalog_path: Path | str,
    approved_catalog_admission: Mapping[str, Any],
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    expected = _load_projection_inputs(
        engine_root=engine_root,
        workspace_root=workspace_root,
        approved_catalog_path=approved_catalog_path,
        approved_catalog_admission=approved_catalog_admission,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
    )
    _write_once(
        expected["engine"], expected["snapshot_path"], expected["catalog_raw"]
    )
    _write_once(
        expected["engine"],
        expected["projection_path"],
        _canonical_bytes(expected["projection"]),
    )
    return validate_evo_child_catalog_projection(
        engine_root=engine_root,
        workspace_root=workspace_root,
        approved_catalog_path=approved_catalog_path,
        approved_catalog_admission=approved_catalog_admission,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
    )


def validate_evo_child_catalog_projection(
    *,
    engine_root: Path | str,
    workspace_root: Path | str,
    approved_catalog_path: Path | str,
    approved_catalog_admission: Mapping[str, Any],
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    expected = _load_projection_inputs(
        engine_root=engine_root,
        workspace_root=workspace_root,
        approved_catalog_path=approved_catalog_path,
        approved_catalog_admission=approved_catalog_admission,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
    )
    snapshot_raw = _read_stable_regular(
        expected["snapshot_path"], limit=CATALOG_MAX_BYTES, label="catalog_snapshot"
    )
    projection_raw = _read_stable_regular(
        expected["projection_path"],
        limit=2 * 1024 * 1024,
        label="catalog_projection",
    )
    try:
        projection = json.loads(projection_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("catalog_projection_json") from exc
    if snapshot_raw != expected["catalog_raw"]:
        raise _fail("catalog_snapshot_changed")
    if projection != expected["projection"]:
        raise _fail("catalog_projection_changed")
    return {
        "verdict": "PASS",
        "status": "HOST_PROJECTED_APPROVED_CATALOG",
        "snapshot_path": str(expected["snapshot_path"].resolve(strict=True)),
        "snapshot_sha256": _sha256_bytes(snapshot_raw),
        "projection_path": str(expected["projection_path"].resolve(strict=True)),
        "projection_sha256": _sha256_bytes(projection_raw),
        "projection": projection,
    }


def validate_materialized_evo_child_catalog_projection(
    *,
    engine_root: Path | str,
    workspace_root: Path | str,
    projection_path: Path | str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    if not all(
        _SAFE_ID.fullmatch(value or "")
        for value in (job_id, parent_report_id, child_report_id)
    ) or parent_report_id == child_report_id:
        raise _fail("unsafe_or_colliding_identity")
    engine = Path(engine_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    expected_snapshot, expected_projection = evo_child_catalog_projection_paths(
        engine,
        job_id=job_id,
        child_report_id=child_report_id,
    )
    candidate = Path(projection_path).expanduser()
    if candidate.is_symlink():
        raise _fail("catalog_projection_symlink")
    try:
        projection_file = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail("catalog_projection_missing") from exc
    if projection_file != expected_projection:
        raise _fail("catalog_projection_location")
    if expected_snapshot == workspace or expected_snapshot.is_relative_to(workspace):
        raise _fail("projection_must_be_outside_writable_workspace")
    projection_raw = _read_stable_regular(
        projection_file,
        limit=2 * 1024 * 1024,
        label="catalog_projection",
    )
    snapshot_raw = _read_stable_regular(
        expected_snapshot,
        limit=CATALOG_MAX_BYTES,
        label="catalog_snapshot",
    )
    try:
        projection = json.loads(projection_raw)
        catalog = json.loads(snapshot_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("materialized_catalog_projection_json") from exc
    frozen = _read_frozen_catalog_summary(workspace)
    datasets = catalog.get("datasets") if isinstance(catalog, dict) else None
    core = dict(projection) if isinstance(projection, dict) else {}
    content_sha256 = core.pop("content_sha256", None)
    snapshot_ref = projection.get("snapshot") if isinstance(projection, dict) else None
    summary_ref = (
        projection.get("workspace_catalog_summary")
        if isinstance(projection, dict)
        else None
    )
    expected_catalog_identity = {
        "catalog_sha256": frozen["catalog_digest"],
        "catalog_bytes": len(snapshot_raw),
        "schema_version": catalog.get("schema_version") if isinstance(catalog, dict) else None,
        "dataset_count": len(datasets) if isinstance(datasets, list) else -1,
        "dataset_ids_sha256": stable_json_hash(
            [str(item["dataset_id"]) for item in datasets]
        )
        if isinstance(datasets, list)
        and all(isinstance(item, dict) and "dataset_id" in item for item in datasets)
        else "",
        "host_catalog_filename": frozen["catalog_filename"],
    }
    expected_authority = {
        "host_projection_only": True,
        "external_source_path_disclosed_to_agent": False,
        "formal_dataset_qa_implied": False,
        "container_engine_mount_required": "READ_ONLY",
        "container_workspace_mount_source_allowed": False,
    }
    if (
        not isinstance(projection, dict)
        or set(projection)
        != {
            "projection_version",
            "status",
            "identity",
            "catalog_identity",
            "catalog_admission",
            "catalog_admission_sha256",
            "snapshot",
            "workspace_catalog_summary",
            "authority",
            "content_sha256",
        }
        or projection.get("projection_version") != PROJECTION_VERSION
        or projection.get("status") != "HOST_PROJECTED_APPROVED_CATALOG"
        or projection.get("identity")
        != {
            "job_id": job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
        }
        or content_sha256 != stable_json_hash(core)
        or projection.get("catalog_identity") != expected_catalog_identity
        or projection.get("catalog_admission") != frozen["catalog_admission"]
        or projection.get("catalog_admission_sha256")
        != stable_json_hash(frozen["catalog_admission"])
        or projection.get("authority") != expected_authority
        or not isinstance(snapshot_ref, dict)
        or set(snapshot_ref) != {"path", "sha256", "size_bytes"}
        or engine / str(snapshot_ref.get("path") or "") != expected_snapshot
        or snapshot_ref.get("sha256") != frozen["catalog_digest"]
        or snapshot_ref.get("size_bytes") != len(snapshot_raw)
        or _sha256_bytes(snapshot_raw) != frozen["catalog_digest"]
        or not isinstance(summary_ref, dict)
        or summary_ref
        != {
            "path": frozen["summary_path"].relative_to(engine).as_posix(),
            "sha256": _sha256_bytes(frozen["summary_raw"]),
            "size_bytes": len(frozen["summary_raw"]),
        }
        or not isinstance(datasets, list)
        or not datasets
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("dataset_id"), str)
            and bool(item["dataset_id"].strip())
            for item in datasets
        )
    ):
        raise _fail("materialized_catalog_projection_replay")
    return {
        "verdict": "PASS",
        "status": "HOST_PROJECTED_APPROVED_CATALOG",
        "snapshot_path": str(expected_snapshot.resolve(strict=True)),
        "snapshot_sha256": frozen["catalog_digest"],
        "projection_path": str(projection_file),
        "projection_sha256": _sha256_bytes(projection_raw),
        "projection": projection,
    }


def materialize_evo_child_calendar_projection(
    *,
    engine_root: Path | str,
    workspace_root: Path | str,
    trusted_calendar_path: Path | str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    if not all(
        _SAFE_ID.fullmatch(value or "")
        for value in (job_id, parent_report_id, child_report_id)
    ) or parent_report_id == child_report_id:
        raise _fail("calendar_identity")
    engine = Path(engine_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    source = Path(trusted_calendar_path).expanduser()
    raw = _read_stable_regular(
        source, limit=CATALOG_MAX_BYTES, label="trusted_calendar"
    )
    prior = os.environ.get("FACTORFORGE_TRUSTED_TRADE_CAL_CSV")
    os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = str(source)
    try:
        validation = validate_trusted_calendar_snapshot()
    finally:
        if prior is None:
            os.environ.pop("FACTORFORGE_TRUSTED_TRADE_CAL_CSV", None)
        else:
            os.environ["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] = prior
    if validation.get("raw_file_sha256") != _sha256_bytes(raw):
        raise _fail("trusted_calendar_validation_binding")
    snapshot, projection_path = evo_child_calendar_projection_paths(
        engine, job_id=job_id, child_report_id=child_report_id
    )
    try:
        snapshot.relative_to(engine)
        snapshot.relative_to(workspace)
    except ValueError:
        pass
    else:
        raise _fail("calendar_projection_inside_writable_workspace")
    calendar_identity = {
        key: validation[key]
        for key in (
            "open_dates_sha256",
            "raw_file_sha256",
            "registry_sha256",
            "registry_git_commit",
            "registry_git_blob",
            "snapshot_id",
        )
    }
    calendar_identity.update(
        {
            "date_count": len(validation["dates"]),
            "date_min": validation["dates"][0],
            "date_max": validation["dates"][-1],
        }
    )
    snapshot_ref = {
        "path": snapshot.relative_to(engine).as_posix(),
        "sha256": _sha256_bytes(raw),
        "size_bytes": len(raw),
    }
    core = {
        "projection_version": "factorforge_console_evo_child_calendar_projection_v1",
        "status": "HOST_PROJECTED_TRUSTED_CALENDAR",
        "identity": {
            "job_id": job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
        },
        "calendar_identity": calendar_identity,
        "snapshot": snapshot_ref,
        "authority": {
            "host_projection_only": True,
            "external_source_path_disclosed_to_agent": False,
            "container_engine_mount_required": "READ_ONLY",
            "registry_validated_before_projection": True,
        },
    }
    projection = {**core, "content_sha256": stable_json_hash(core)}
    _write_once(engine, snapshot, raw)
    _write_once(engine, projection_path, _canonical_bytes(projection))
    return validate_materialized_evo_child_calendar_projection(
        engine_root=engine,
        workspace_root=workspace,
        projection_path=projection_path,
        job_id=job_id,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
    )


def validate_materialized_evo_child_calendar_projection(
    *,
    engine_root: Path | str,
    workspace_root: Path | str,
    projection_path: Path | str,
    job_id: str,
    parent_report_id: str,
    child_report_id: str,
) -> dict[str, Any]:
    engine = Path(engine_root).expanduser().resolve(strict=True)
    workspace = Path(workspace_root).expanduser().resolve(strict=True)
    expected_snapshot, expected_projection = evo_child_calendar_projection_paths(
        engine, job_id=job_id, child_report_id=child_report_id
    )
    candidate = Path(projection_path).expanduser()
    if candidate.is_symlink():
        raise _fail("calendar_projection_symlink")
    try:
        projection_file = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise _fail("calendar_projection_missing") from exc
    if projection_file != expected_projection:
        raise _fail("calendar_projection_location")
    raw = _read_stable_regular(
        projection_file, limit=2 * 1024 * 1024, label="calendar_projection"
    )
    try:
        projection = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("calendar_projection_json") from exc
    core = dict(projection) if isinstance(projection, dict) else {}
    content_sha256 = core.pop("content_sha256", None)
    snapshot_ref = projection.get("snapshot") if isinstance(projection, dict) else None
    if (
        not isinstance(projection, dict)
        or projection.get("projection_version")
        != "factorforge_console_evo_child_calendar_projection_v1"
        or projection.get("status") != "HOST_PROJECTED_TRUSTED_CALENDAR"
        or projection.get("identity")
        != {
            "job_id": job_id,
            "parent_report_id": parent_report_id,
            "child_report_id": child_report_id,
        }
        or content_sha256 != stable_json_hash(core)
        or not isinstance(snapshot_ref, dict)
        or set(snapshot_ref) != {"path", "sha256", "size_bytes"}
        or engine / str(snapshot_ref.get("path") or "") != expected_snapshot
    ):
        raise _fail("calendar_projection_shape")
    if expected_snapshot == workspace or expected_snapshot.is_relative_to(workspace):
        raise _fail("calendar_projection_inside_writable_workspace")
    snapshot_raw = _read_stable_regular(
        expected_snapshot, limit=CATALOG_MAX_BYTES, label="calendar_snapshot"
    )
    if (
        _sha256_bytes(snapshot_raw) != snapshot_ref.get("sha256")
        or len(snapshot_raw) != snapshot_ref.get("size_bytes")
        or projection.get("calendar_identity", {}).get("raw_file_sha256")
        != snapshot_ref.get("sha256")
    ):
        raise _fail("calendar_snapshot_changed")
    return {
        "verdict": "PASS",
        "snapshot_path": str(expected_snapshot.resolve(strict=True)),
        "snapshot_sha256": snapshot_ref["sha256"],
        "projection_path": str(projection_file),
        "projection_sha256": _sha256_bytes(raw),
        "projection": projection,
    }
