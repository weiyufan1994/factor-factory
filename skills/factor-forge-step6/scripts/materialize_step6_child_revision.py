#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from factor_factory.artifact_identity import stable_hash
from factor_factory.child_materialization import (
    MATERIALIZATION_READBACK_BLOCK,
    MATERIALIZATION_VERSION,
    STAGING_MANIFEST_VERSION,
    validate_child_materialization_readback,
)
from factor_factory.evo_oos import (
    WAITING_FRESH_OOS,
    child_control_paths,
    validate_fresh_child_oos_allocation,
    validate_oos_registry_allocation_prefix,
)
from factor_factory.oos_exposure_incident import (
    oos_exposure_private_registry_guard,
)
from factor_factory.evo_data_boundary import project_pre_release_data_access
from factor_factory.evo_child_execution import (
    EvoChildExecutionError,
    build_evo_transfer_diagnostic_contract,
)
from factor_factory.evo_child_materialization_ticket import (
    validate_public_child_materialization_ticket,
)
from factor_factory.evo_child_preregistration import (
    EvoChildPreregistrationError,
    validate_and_resolve_evo_child_web_research_plan,
)
from factor_factory.evo_oos import (
    sha256_file as evo_sha256_file,
)
from factor_factory.formula.parser import parse_formula
from factor_factory.console.web_research_plan import (
    build_web_evaluation_contract,
    stable_json_hash as web_stable_json_hash,
)
from factor_factory.pre_oos_human_bridge import (
    PRE_OOS_CHILD_HANDOFF_VERSION,
    WAITING_PRE_OOS_TRANSFER,
    validate_pre_oos_child_handoff,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_enabled,
    research_protocol_paths,
    validate_protocol_bundle,
)
from factor_factory.runtime_context import resolve_factorforge_context
from factor_factory.state_reuse import (
    build_state_dependency_contract_from_data_prep,
    resolve_state_dependencies,
    safe_id,
)

EXECUTABLE_REVISION_SPEC_VERSION = "factorforge_executable_revision_spec_v1"
_ACTIVE_MATERIALIZER_INCIDENT_GUARD: object | None = None
_ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT: Path | None = None
_ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID: str | None = None
MAIN_AGENT_COUNCIL_SYNTHESIS_VERSION = "factorforge_main_agent_council_synthesis_v1"
TARGET_EXISTS_BLOCK = "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_TARGET_EXISTS"
DAILY_SNAPSHOT_MISSING_BLOCK = "BLOCK_FACTORFORGE_CHILD_DAILY_SNAPSHOT_MISSING"
SYNTHESIS_MISSING_BLOCK = "BLOCK_FACTORFORGE_MAIN_AGENT_COUNCIL_SYNTHESIS_MISSING"
CHILD_FORMULA_MISSING_BLOCK = (
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_CHILD_FORMULA_MISSING"
)
SELECTED_LAW_MISSING_BLOCK = (
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_SELECTED_LAW_MISSING"
)
METRIC_SIGNATURE_MISSING_BLOCK = (
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_METRIC_SIGNATURE_MISSING"
)
FALSIFICATION_MISSING_BLOCK = (
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FALSIFICATION_MISSING"
)
KILL_CRITERIA_MISSING_BLOCK = (
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_KILL_CRITERIA_MISSING"
)
ORCHESTRATOR_MISMATCH_BLOCK = (
    "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_ORCHESTRATOR_MISMATCH"
)
MATERIALIZATION_STAGING_BLOCK = (
    "BLOCK_FACTORFORGE_CHILD_MATERIALIZATION_STAGING_INVALID"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write_once(path, _json_bytes(payload))
    print(f"[WRITE] {path}")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def _workspace_relative_path(root: Path, path: Path) -> str:
    resolved_root = root.expanduser().resolve(strict=False)
    resolved_path = path.expanduser().resolve(strict=False)
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(
            f"{MATERIALIZATION_STAGING_BLOCK}: target outside workspace: {path}"
        )
    return resolved_path.relative_to(resolved_root).as_posix()


def _manifest_path(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    resolved_root = root.expanduser().resolve(strict=False)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = resolved_root / path
    path = path.resolve(strict=False)
    if path != resolved_root and resolved_root not in path.parents:
        return None
    return path


def _atomic_write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise ValueError(
                f"{MATERIALIZATION_STAGING_BLOCK}: immutable output conflict: {path}"
            )
        return
    descriptor, raw = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise ValueError(
                    f"{MATERIALIZATION_STAGING_BLOCK}: concurrent output conflict: {path}"
                )
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_publish_staged_file(staged_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=target_path.parent,
    )
    temporary = Path(raw)
    try:
        with staged_path.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        try:
            os.link(temporary, target_path)
        except FileExistsError:
            if (
                target_path.is_symlink()
                or not target_path.is_file()
                or sha256_file(target_path) != sha256_file(staged_path)
            ):
                raise ValueError(
                    f"{MATERIALIZATION_STAGING_BLOCK}: concurrent target conflict: "
                    f"{target_path}"
                )
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_path(root: Path, kind: str, report_id: str) -> Path:
    names = {
        "alpha_idea_master": (
            "alpha_idea_master",
            f"alpha_idea_master__{report_id}.json",
        ),
        "factor_spec_master": (
            "factor_spec_master",
            f"factor_spec_master__{report_id}.json",
        ),
        "data_prep_master": ("data_prep_master", f"data_prep_master__{report_id}.json"),
        "qlib_adapter_config": (
            "data_prep_master",
            f"qlib_adapter_config__{report_id}.json",
        ),
        "handoff_to_step3": ("handoff", f"handoff_to_step3__{report_id}.json"),
        "handoff_to_step4": ("handoff", f"handoff_to_step4__{report_id}.json"),
        "handoff_to_step3b": ("handoff", f"handoff_to_step3b__{report_id}.json"),
        "research_iteration_master": (
            "research_iteration_master",
            f"research_iteration_master__{report_id}.json",
        ),
        "executable_revision_spec": (
            "research_iteration_master",
            f"executable_revision_spec__{report_id}.json",
        ),
    }
    rel_dir, name = names[kind]
    return root / "objects" / rel_dir / name


def bind_child_web_runtime_contract(
    payload: dict[str, Any],
    *,
    kind: str,
    plan_ref: str,
    plan_sha256: str,
    evaluation_contract: dict[str, Any],
    research_windows: dict[str, Any],
) -> dict[str, Any]:
    """Project a frozen child Web plan into Step3B/Step4 inputs."""

    payload["web_research_plan_ref"] = plan_ref
    payload["web_research_plan_sha256"] = plan_sha256
    payload["evaluation_contract"] = evaluation_contract
    if kind == "factor_spec_master":
        canonical = payload.get("canonical_spec")
        if not isinstance(canonical, dict):
            canonical = {}
            payload["canonical_spec"] = canonical
        canonical["evaluation_contract"] = evaluation_contract
    if kind in {"data_prep_master", "handoff_to_step4"}:
        payload["research_windows"] = research_windows
        contract = payload.get("step4_data_contract")
        if not isinstance(contract, dict) or not contract:
            # A pre-OOS Council child can branch before the parent ever owns a
            # Step3A handoff.  Build the mechanical, IS-bounded data contract
            # from the already validated child plan instead of inventing an
            # empty placeholder (or inheriting a full parent query).
            daily_fields = sorted(
                {
                    str(field)
                    for field in (
                        ((payload.get("canonical_spec") or {}).get("required_fields"))
                        or []
                    )
                    if str(field).strip()
                }
            )
            if not daily_fields:
                daily_fields = [
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "volume",
                ]
            query = {
                "dataset": "clean_daily_bar",
                "start_date": str(research_windows["is_start"]).replace("-", ""),
                "end_date": str(research_windows["is_end"]).replace("-", ""),
                "universe": "a_share_all",
                "fields": daily_fields,
                "frequency": "daily",
            }
            payload["step4_data_contract"] = {
                "version": "factorforge_step4_data_contract_v1",
                "producer": "evo_child_preregistration_projection",
                "data_api_package": "factorforge_data_api",
                "catalog_path": None,
                "full_queries": {"clean_daily_bar": query},
                "sample_queries": {},
                "minute_derived_state_requirements": [],
                "research_window_contract": {
                    "requested_start": query["start_date"],
                    "requested_end": query["end_date"],
                    "query_start": query["start_date"],
                    "query_end": query["end_date"],
                },
                "formal_factor_values_owner": "Step4",
                "step3b_sample_policy": {
                    "is_formal_factor_values": False,
                    "purpose": "step3_executability_proof",
                    "full_execution_owner": "Step4",
                },
            }
        project_child_pre_release_data_access(payload, research_windows)
    return payload


_CHILD_WEB_DAILY_PATH_KEYS = (
    "daily_df_parquet",
    "daily_df_csv",
    "daily_df_csv_sample",
    "evaluation_daily_df_parquet",
    "evaluation_daily_df_csv",
    "signal_daily_df_parquet",
    "signal_daily_df_csv",
)


def project_child_pre_release_data_access(
    payload: dict[str, Any], research_windows: dict[str, Any]
) -> dict[str, Any]:
    """Compatibility wrapper over the shared parent/child EVO boundary."""

    return project_pre_release_data_access(payload, research_windows)


def materialization_report_path(root: Path, parent: str, child: str) -> Path:
    digest = hashlib.sha256(f"{parent}\0{child}".encode()).hexdigest()[:16]
    short_parent = parent[:40].rstrip("_")
    short_child = child[:40].rstrip("_")
    filename = (
        f"child_revision_materialization__{short_parent}__{short_child}__{digest}.json"
    )
    return root / "objects" / "runtime_context" / filename


def materialization_staging_manifest_path(
    root: Path,
    parent: str,
    child: str,
) -> Path:
    report = materialization_report_path(root, parent, child)
    return report.with_name(report.stem + "__staging_manifest.json")


def materialization_staging_directory(
    root: Path,
    parent: str,
    child: str,
) -> Path:
    report = materialization_report_path(root, parent, child)
    return report.parent / f".{report.stem}__staging"


def _acquire_materialization_lock(root: Path, parent: str, child: str):
    report = materialization_report_path(root, parent, child)
    lock_path = report.with_name(report.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release_materialization_lock(handle) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def _prepare_staging_directory(
    root: Path,
    parent: str,
    child: str,
) -> Path:
    staging = materialization_staging_directory(root, parent, child)
    manifest = materialization_staging_manifest_path(root, parent, child)
    if manifest.exists() or manifest.is_symlink():
        return staging
    if staging.exists() or staging.is_symlink():
        if staging.is_symlink() or not staging.is_dir():
            raise ValueError(
                f"{MATERIALIZATION_STAGING_BLOCK}: staging path is unsafe: {staging}"
            )
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=False)
    return staging


def _stage_materialization_bytes(
    *,
    root: Path,
    staging_directory: Path,
    kind: str,
    target_path: Path,
    data: bytes,
) -> dict[str, Any]:
    staged_path = _staged_file_for_kind(staging_directory, kind)
    _atomic_write_once(staged_path, data)
    return {
        "kind": kind,
        "target_path": _workspace_relative_path(root, target_path),
        "staged_path": _workspace_relative_path(root, staged_path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _staged_file_for_kind(staging_directory: Path, kind: str) -> Path:
    safe_kind = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in kind
    )
    digest = hashlib.sha256(kind.encode("utf-8")).hexdigest()[:12]
    return staging_directory / f"{digest}__{safe_kind}.staged"


def _stage_materialization_copy(
    *,
    root: Path,
    staging_directory: Path,
    kind: str,
    target_path: Path,
    source_path: Path,
) -> dict[str, Any]:
    staged_path = _staged_file_for_kind(staging_directory, kind)
    if not staged_path.exists() and not staged_path.is_symlink():
        _atomic_publish_staged_file(source_path, staged_path)
    source_sha256 = sha256_file(source_path)
    source_size = source_path.stat().st_size
    if (
        not staged_path.is_file()
        or staged_path.is_symlink()
        or staged_path.stat().st_size != source_size
        or sha256_file(staged_path) != source_sha256
    ):
        raise ValueError(
            f"{MATERIALIZATION_STAGING_BLOCK}: staged source conflict: {kind}"
        )
    return {
        "kind": kind,
        "target_path": _workspace_relative_path(root, target_path),
        "staged_path": _workspace_relative_path(root, staged_path),
        "sha256": source_sha256,
        "size_bytes": source_size,
    }


def _target_hash_projection(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": entry["kind"],
            "path": entry["target_path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
        }
        for entry in sorted(entries, key=lambda item: str(item["kind"]))
    ]


def _write_prepared_materialization_manifest(
    *,
    root: Path,
    parent: str,
    child: str,
    source_handoff_sha256: str,
    entries: list[dict[str, Any]],
    report_payload: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    manifest_path = materialization_staging_manifest_path(root, parent, child)
    unsigned = {
        "contract_version": STAGING_MANIFEST_VERSION,
        "state": "PREPARED",
        "created_at_utc": utc_now(),
        "parent_report_id": parent,
        "child_report_id": child,
        "source_handoff_sha256": source_handoff_sha256,
        "staging_directory": _workspace_relative_path(
            root,
            materialization_staging_directory(root, parent, child),
        ),
        "materialization_report_path": _workspace_relative_path(
            root,
            materialization_report_path(root, parent, child),
        ),
        "entries": sorted(entries, key=lambda item: str(item["kind"])),
        "report_payload": report_payload,
    }
    manifest = {**unsigned, "content_sha256": stable_hash(unsigned)}
    _atomic_write_once(manifest_path, _json_bytes(manifest))
    return manifest_path, manifest


def _prepared_manifest_reasons(
    *,
    root: Path,
    manifest_path: Path,
    parent: str,
    child: str,
    source_handoff_sha256: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None, [f"{MATERIALIZATION_STAGING_BLOCK}:manifest_missing_or_unsafe"]
    try:
        manifest = load_json(manifest_path)
    except (OSError, json.JSONDecodeError, TypeError):
        return None, [f"{MATERIALIZATION_STAGING_BLOCK}:manifest_invalid_json"]
    expected_keys = {
        "contract_version",
        "state",
        "created_at_utc",
        "parent_report_id",
        "child_report_id",
        "source_handoff_sha256",
        "staging_directory",
        "materialization_report_path",
        "entries",
        "report_payload",
        "content_sha256",
    }
    if set(manifest) != expected_keys:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:manifest_shape")
    unsigned = dict(manifest)
    declared_hash = unsigned.pop("content_sha256", None)
    if declared_hash != stable_hash(unsigned):
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:manifest_hash")
    if manifest.get("contract_version") != STAGING_MANIFEST_VERSION:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:manifest_version")
    if manifest.get("state") != "PREPARED":
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:manifest_state")
    if manifest.get("parent_report_id") != parent:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:parent_binding")
    if manifest.get("child_report_id") != child:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:child_binding")
    if manifest.get("source_handoff_sha256") != source_handoff_sha256:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:source_handoff_binding")
    expected_report_path = materialization_report_path(root, parent, child).resolve(
        strict=False
    )
    if (
        _manifest_path(root, manifest.get("materialization_report_path"))
        != expected_report_path
    ):
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:report_path_binding")
    expected_staging = materialization_staging_directory(root, parent, child).resolve(
        strict=False
    )
    if _manifest_path(root, manifest.get("staging_directory")) != expected_staging:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:staging_path_binding")

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:entries")
        entries = []
    seen_kinds: set[str] = set()
    seen_targets: set[str] = set()
    for index, entry in enumerate(entries):
        prefix = f"{MATERIALIZATION_STAGING_BLOCK}:entry[{index}]"
        if not isinstance(entry, dict) or set(entry) != {
            "kind",
            "target_path",
            "staged_path",
            "sha256",
            "size_bytes",
        }:
            reasons.append(f"{prefix}:shape")
            continue
        kind = entry.get("kind")
        target_raw = entry.get("target_path")
        staged_raw = entry.get("staged_path")
        digest = entry.get("sha256")
        size = entry.get("size_bytes")
        target = _manifest_path(root, target_raw)
        staged = _manifest_path(root, staged_raw)
        if not isinstance(kind, str) or not kind or kind in seen_kinds:
            reasons.append(f"{prefix}:kind")
        else:
            seen_kinds.add(kind)
        if (
            not isinstance(target_raw, str)
            or target_raw in seen_targets
            or target is None
        ):
            reasons.append(f"{prefix}:target")
        else:
            seen_targets.add(target_raw)
        if staged is None or expected_staging not in staged.parents:
            reasons.append(f"{prefix}:staged_path")
        if not isinstance(digest, str) or len(digest) != 64:
            reasons.append(f"{prefix}:sha256")
        if not isinstance(size, int) or size < 0:
            reasons.append(f"{prefix}:size")
        target_matches = bool(
            target
            and target.is_file()
            and not target.is_symlink()
            and target.stat().st_size == size
            and sha256_file(target) == digest
        )
        staged_matches = bool(
            staged
            and staged.is_file()
            and not staged.is_symlink()
            and staged.stat().st_size == size
            and sha256_file(staged) == digest
        )
        if target and (target.exists() or target.is_symlink()) and not target_matches:
            reasons.append(f"{prefix}:target_hash_mismatch")
        if not target_matches and not staged_matches:
            reasons.append(f"{prefix}:no_recoverable_copy")

    report_payload = manifest.get("report_payload")
    if not isinstance(report_payload, dict):
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:report_payload")
    elif report_payload.get("materialization_target_hashes") != _target_hash_projection(
        entries
    ):
        reasons.append(f"{MATERIALIZATION_STAGING_BLOCK}:target_hash_projection")
    return (manifest if not reasons else None), list(dict.fromkeys(reasons))


def _report_from_prepared_manifest(
    root: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    report = json.loads(json.dumps(manifest["report_payload"]))
    report["staging_manifest_ref"] = {
        "path": _workspace_relative_path(root, manifest_path),
        "content_sha256": manifest["content_sha256"],
    }
    return report


def materialization_readback_reasons(
    report_path: Path,
    *,
    parent: str,
    child: str,
    source_handoff_sha256: str,
    root: Path | None = None,
) -> list[str]:
    if root is None:
        try:
            report = load_json(report_path)
        except (OSError, json.JSONDecodeError, TypeError):
            return [f"{MATERIALIZATION_READBACK_BLOCK}:report_invalid_json"]
        root_raw = report.get("workspace_root") if isinstance(report, dict) else None
        root = Path(str(root_raw)).expanduser() if root_raw else None
    if root is None:
        return [f"{MATERIALIZATION_READBACK_BLOCK}:workspace_root_missing"]
    return validate_child_materialization_readback(
        workspace_root=root,
        report_path=report_path,
        parent_report_id=parent,
        child_report_id=child,
        source_handoff_sha256=source_handoff_sha256,
    )


def _commit_prepared_materialization(
    *,
    root: Path,
    manifest_path: Path,
    parent: str,
    child: str,
    source_handoff_sha256: str,
) -> dict[str, Any]:
    manifest, reasons = _prepared_manifest_reasons(
        root=root,
        manifest_path=manifest_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_handoff_sha256,
    )
    if manifest is None or reasons:
        raise ValueError(";".join(reasons))
    for entry in manifest["entries"]:
        target = _manifest_path(root, entry["target_path"])
        staged = _manifest_path(root, entry["staged_path"])
        if target is None or staged is None:
            raise ValueError(f"{MATERIALIZATION_STAGING_BLOCK}:entry_path")
        if target.is_file() and not target.is_symlink():
            if (
                target.stat().st_size == entry["size_bytes"]
                and sha256_file(target) == entry["sha256"]
            ):
                continue
            raise ValueError(
                f"{MATERIALIZATION_STAGING_BLOCK}:target_hash_mismatch:{entry['kind']}"
            )
        if target.exists() or target.is_symlink():
            raise ValueError(
                f"{MATERIALIZATION_STAGING_BLOCK}:target_unsafe:{entry['kind']}"
            )
        if (
            not staged.is_file()
            or staged.is_symlink()
            or staged.stat().st_size != entry["size_bytes"]
            or sha256_file(staged) != entry["sha256"]
        ):
            raise ValueError(
                f"{MATERIALIZATION_STAGING_BLOCK}:staged_hash_mismatch:{entry['kind']}"
            )
        _atomic_publish_staged_file(staged, target)
        if (
            not target.is_file()
            or target.is_symlink()
            or target.stat().st_size != entry["size_bytes"]
            or sha256_file(target) != entry["sha256"]
        ):
            raise ValueError(
                f"{MATERIALIZATION_READBACK_BLOCK}:target_publish:{entry['kind']}"
            )
        print(f"[WRITE] {target}")

    report_path = materialization_report_path(root, parent, child)
    report = _report_from_prepared_manifest(root, manifest_path, manifest)
    _atomic_write_once(report_path, _json_bytes(report))
    readback = materialization_readback_reasons(
        report_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_handoff_sha256,
        root=root,
    )
    if readback:
        raise ValueError(";".join(readback))
    staging = materialization_staging_directory(root, parent, child)
    if staging.is_dir() and not staging.is_symlink():
        shutil.rmtree(staging)
    return report


def child_daily_input_path(root: Path, child: str, suffix: str) -> Path:
    return (
        root / "runs" / child / "step3a_local_inputs" / f"daily_input__{child}.{suffix}"
    )


def child_daily_meta_path(root: Path, child: str) -> Path:
    return (
        root
        / "runs"
        / child
        / "step3a_local_inputs"
        / f"daily_input_meta__{child}.json"
    )


def child_state_reuse_paths(root: Path, child: str) -> dict[str, Path]:
    base = root / "objects" / "data_prep_master" / child
    return {
        "state_dependency_contract": base / f"state_dependency_contract__{child}.json",
        "state_resolution": base / f"state_resolution__{child}.json",
        "data_request_dir": base / "data_requests",
    }


def load_child_state_catalog(
    data_prep: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates: list[Path] = []
    for env_name in (
        "FACTORFORGE_STATE_CATALOG",
        "FACTORFORGE_DATA_API_CATALOG",
        "FACTORFORGE_DATA_CATALOG",
    ):
        raw = os.getenv(env_name)
        if raw:
            candidates.append(Path(raw).expanduser())
    step4_contract = (
        data_prep.get("step4_data_contract")
        if isinstance(data_prep.get("step4_data_contract"), dict)
        else {}
    )
    for key in ("state_catalog_path", "catalog_path"):
        if step4_contract.get(key):
            candidates.append(Path(str(step4_contract[key])).expanduser())
    checked: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        checked.append(key)
        if path.is_file() and not path.is_symlink():
            return load_json(path), {
                "type": "data_api_catalog",
                "path_or_uri": str(path),
                "checked": checked,
            }
    return {}, {"type": "data_api_catalog_missing", "checked": checked}


def build_child_state_reuse(
    root: Path,
    child: str,
    data_prep: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[Path, dict[str, Any]]]]:
    paths = child_state_reuse_paths(root, child)
    contract = build_state_dependency_contract_from_data_prep(
        data_prep,
        producer="ultimate_loop_child_materializer",
    )
    catalog, catalog_source = load_child_state_catalog(data_prep)
    if contract.get("no_state_required") is True:
        catalog = {}
        catalog_source = {
            "type": "child_materializer_noop_no_state_required",
            "reason": (
                "Child revision inherits daily/catalog inputs and declares no "
                "derived-state dependency."
            ),
        }
    resolution = resolve_state_dependencies(
        contract=contract,
        catalog=catalog,
        report_id=child,
        factor_id=str(data_prep.get("factor_id") or child),
        research_id=(
            str(data_prep.get("research_id")) if data_prep.get("research_id") else None
        ),
        dependency_contract_path=str(paths["state_dependency_contract"]),
        catalog_source=catalog_source,
    )
    artifacts: dict[str, tuple[Path, dict[str, Any]]] = {
        "state_dependency_contract": (
            paths["state_dependency_contract"],
            {"state_dependency_contract": contract},
        ),
        "state_resolution": (paths["state_resolution"], resolution),
    }
    for request in resolution.get("data_requests") or []:
        request_id = safe_id(request.get("request_id"))
        artifacts[f"state_data_request__{request_id}"] = (
            paths["data_request_dir"] / f"{request_id}.json",
            request,
        )
    result = {
        "state_dependency_contract_path": str(paths["state_dependency_contract"]),
        "state_resolution_path": str(paths["state_resolution"]),
        "data_request_dir": str(paths["data_request_dir"]),
        "state_dependencies_required": (
            resolution.get("state_dependencies_required") is not False
        ),
        "no_state_required": resolution.get("no_state_required") is True,
        "blocked": resolution.get("blocked") is True,
        "blocker_token": resolution.get("blocker_token"),
        "data_request_ids": list(resolution.get("data_request_ids") or []),
    }
    return result, artifacts


def materialize_child_state_reuse(
    root: Path,
    child: str,
    data_prep: dict[str, Any],
) -> dict[str, Any]:
    result, artifacts = build_child_state_reuse(root, child, data_prep)
    for path, payload in artifacts.values():
        write_json(path, payload)
    return result


def resolved_path(root: Path, raw: Any) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if path.is_absolute():
        if path.exists():
            return path
        parts = path.parts
        for anchor in ("runs", "objects", "generated_code", "knowledge"):
            if anchor not in parts:
                continue
            idx = parts.index(anchor)
            candidate = root.joinpath(*parts[idx:])
            if candidate.exists():
                return candidate
        return path
    candidates = [root / path]
    parts = path.parts
    if parts and parts[0] == root.name:
        candidates.append(root.parent / path)
        candidates.append(root / Path(*parts[1:]))
    candidates.append(root.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def resolved_daily_sources(root: Path, data_prep: dict[str, Any]) -> dict[str, Path]:
    local_inputs = data_prep.get("local_input_paths")
    if not isinstance(local_inputs, dict):
        return {}
    sources: dict[str, Path] = {}
    for key in _CHILD_WEB_DAILY_PATH_KEYS:
        path = resolved_path(root, local_inputs.get(key))
        if path and path.exists():
            sources[key] = path
    return sources


def declared_daily_source_keys(data_prep: dict[str, Any]) -> list[str]:
    local_inputs = data_prep.get("local_input_paths")
    if not isinstance(local_inputs, dict):
        return []
    return [
        key
        for key in _CHILD_WEB_DAILY_PATH_KEYS
        if local_inputs.get(key)
    ]


def planned_target_paths(
    root: Path, parent: str, child: str, parent_data_prep: dict[str, Any]
) -> dict[str, Path]:
    targets = {
        "alpha_idea_master": object_path(root, "alpha_idea_master", child),
        "factor_spec_master": object_path(root, "factor_spec_master", child),
        "data_prep_master": object_path(root, "data_prep_master", child),
        "executable_revision_spec": object_path(
            root, "executable_revision_spec", child
        ),
        "materialization_report": materialization_report_path(root, parent, child),
    }
    state_paths = child_state_reuse_paths(root, child)
    targets["state_dependency_contract"] = state_paths["state_dependency_contract"]
    targets["state_resolution"] = state_paths["state_resolution"]
    for key, source in resolved_daily_sources(root, parent_data_prep).items():
        if source.exists():
            prefix = key.removesuffix("_parquet").removesuffix("_csv")
            targets[f"child_daily_input_{key}"] = child_daily_input_path(
                root, child, f"{prefix}.{source.suffix.lstrip('.')}"
            )
    local_inputs = parent_data_prep.get("local_input_paths")
    if isinstance(local_inputs, dict):
        meta_source = resolved_path(root, local_inputs.get("daily_input_meta_json"))
        if meta_source and meta_source.exists():
            targets["child_daily_input_meta_json"] = child_daily_meta_path(root, child)
    targets["qlib_adapter_config"] = object_path(
        root,
        "qlib_adapter_config",
        child,
    )
    for kind in ("handoff_to_step3", "handoff_to_step4"):
        if object_path(root, kind, parent).exists():
            targets[kind] = object_path(root, kind, child)
    controls = child_control_paths(root, child)
    targets.update(
        {
            "research_state": controls["research_state"],
            "research_conjecture": controls["research_conjecture"],
            "approach_registry": controls["approach_registry"],
            "search_trial_ledger": controls["search_trial_ledger"],
            "threshold_registration": controls["threshold_registration"],
            "oos_allocation": controls["oos_allocation"],
            "oos_allocation_registry": controls["oos_allocation_registry"],
            "evo_lifecycle": research_protocol_paths(root, child)["evo_lifecycle"],
        }
    )
    return targets


def build_child_qlib_adapter_config(
    root: Path,
    parent: str,
    child: str,
) -> tuple[dict[str, Any], str]:
    parent_cfg = object_path(root, "qlib_adapter_config", parent)
    child_cfg = object_path(root, "qlib_adapter_config", child)
    if parent_cfg.exists():
        payload = rewrite_common(
            load_json(parent_cfg),
            child_report_id=child,
            branch_id=None,
            parent_run_id=None,
            artifact_role="qlib_adapter_config",
            producer="ultimate_loop_child_materializer",
        )
        payload["parent_qlib_adapter_config_ref"] = str(parent_cfg)
        payload["qlib_adapter_config_lineage"] = {
            "version": "factorforge_child_qlib_adapter_config_lineage_v1",
            "parent_report_id": parent,
            "child_report_id": child,
            "parent_qlib_adapter_config_path": str(parent_cfg),
            "parent_qlib_adapter_config_sha256": sha256_file(parent_cfg),
            "status": "copied_from_parent",
        }
        status = "copied_from_parent"
    else:
        payload = {
            "version": "factorforge_qlib_adapter_config_v1",
            "report_id": child,
            "producer": "ultimate_loop_child_materializer",
            "status": "not_applicable",
            "qlib_native_status": "not_applicable",
            "reason": "direct_code_derived_state_not_supported_by_qlib",
            "parent_report_id": parent,
            "created_at_utc": utc_now(),
            "qlib_adapter_config_lineage": {
                "version": "factorforge_child_qlib_adapter_config_lineage_v1",
                "parent_report_id": parent,
                "child_report_id": child,
                "parent_qlib_adapter_config_path": str(parent_cfg),
                "status": "not_applicable_created",
            },
        }
        status = "not_applicable_created"
    return payload, status


def ensure_child_qlib_adapter_config(
    root: Path, parent: str, child: str
) -> dict[str, Any]:
    child_cfg = object_path(root, "qlib_adapter_config", child)
    payload, status = build_child_qlib_adapter_config(root, parent, child)
    write_json(child_cfg, payload)

    child_handoff = object_path(root, "handoff_to_step4", child)
    if child_handoff.exists():
        handoff = load_json(child_handoff)
        handoff["qlib_adapter_config_ref"] = child_cfg.name
        handoff["qlib_adapter_config_path"] = str(child_cfg)
        handoff.setdefault(
            "qlib_adapter_config_lineage", payload.get("qlib_adapter_config_lineage")
        )
        write_json(child_handoff, handoff)

    return {"status": status, "path": str(child_cfg)}


def executable_revision_spec_path(root: Path, child: str) -> Path:
    return object_path(root, "executable_revision_spec", child)


def default_orchestrator_synthesis_path(root: Path, parent: str) -> Path:
    return (
        root
        / "objects"
        / "research_iteration_master"
        / "revision_council"
        / parent
        / f"main_agent_council_synthesis__{parent}.json"
    )


def formula_hash(formula_text: str) -> str:
    parsed = parse_formula(formula_text)
    if parsed.get("parse_status") != "success":
        raise ValueError(
            "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED: "
            + "; ".join(parsed.get("parse_errors") or [])
        )
    return str(parsed.get("formula_hash") or "")


def parent_formula_hash_for_audit(formula_text: str) -> str:
    parsed = parse_formula(formula_text)
    if parsed.get("parse_status") == "success":
        return str(parsed.get("formula_hash") or "")
    return stable_hash(
        {
            "formula_text": formula_text,
            "parse_status": "not_formula_ir_parent",
            "parse_errors": parsed.get("parse_errors") or [],
            "hash_role": "parent_formula_audit_hash",
        }
    )


def child_formula_or_law(selected: dict[str, Any]) -> str:
    return (
        nonempty_str(selected.get("child_formula"))
        or nonempty_str(selected.get("child_formula_or_law"))
        or nonempty_str(selected.get("direct_code_law"))
        or nonempty_str(selected.get("formula_law"))
    )


def selected_implementation_mode(
    parent_spec: dict[str, Any],
    parent_handoff: dict[str, Any],
    selected: dict[str, Any],
) -> str:
    explicit = nonempty_str(selected.get("implementation_mode"))
    if explicit:
        return explicit
    if (
        isinstance(selected.get("direct_code_revision_contract"), dict)
        and selected["direct_code_revision_contract"]
    ):
        return "direct_code"
    identity = (
        parent_spec.get("artifact_identity")
        if isinstance(parent_spec.get("artifact_identity"), dict)
        else {}
    )
    contract = (
        parent_spec.get("implementation_contract")
        if isinstance(parent_spec.get("implementation_contract"), dict)
        else {}
    )
    mode = (
        nonempty_str(identity.get("implementation_mode"))
        or nonempty_str(parent_spec.get("implementation_mode"))
        or nonempty_str(parent_handoff.get("implementation_mode"))
        or nonempty_str(parent_handoff.get("execution_mode"))
        or nonempty_str(contract.get("mode"))
        or nonempty_str(contract.get("implementation_mode"))
    )
    return mode or "operator"


def child_revision_hash(
    child_formula: str, implementation_mode: str, selected: dict[str, Any]
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    if implementation_mode == "operator":
        child_formula_ir = parse_formula(child_formula)
        if child_formula_ir.get("parse_status") != "success":
            raise ValueError(
                "BLOCK_FACTORFORGE_EXECUTABLE_REVISION_FORMULA_PARSE_FAILED: "
                + "; ".join(child_formula_ir.get("parse_errors") or [])
            )
        return child_formula_ir, str(child_formula_ir.get("formula_hash") or ""), {}
    contract_key = (
        "direct_code_revision_contract"
        if implementation_mode == "direct_code"
        else "hybrid_revision_contract"
    )
    revision_contract = selected.get(contract_key)
    if not isinstance(revision_contract, dict) or not revision_contract:
        revision_contract = selected.get("direct_code_revision_contract")
    if not isinstance(revision_contract, dict) or not revision_contract:
        raise ValueError(
            f"BLOCK_FACTORFORGE_EXECUTABLE_REVISION_DIRECT_CODE_CONTRACT_MISSING: implementation_mode={implementation_mode}"
        )
    code_law_hash = stable_hash(
        {
            "hash_role": f"{implementation_mode}_child_code_law_hash",
            "implementation_mode": implementation_mode,
            "child_formula_or_law": child_formula,
            "revision_contract": revision_contract,
        }
    )
    return None, code_law_hash, revision_contract


def nonempty_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) and value.strip() else ""


def nonempty_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) and bool(value) else []


def nonempty_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) and bool(value) else {}


def resolve_synthesis_path(
    root: Path,
    parent: str,
    parent_handoff: dict[str, Any],
    explicit_synthesis_path: str | None = None,
) -> Path:
    if explicit_synthesis_path:
        path = Path(explicit_synthesis_path).expanduser()
        return path if path.is_absolute() else root / path
    raw = (
        parent_handoff.get("orchestrator_synthesis_path")
        or parent_handoff.get("main_agent_council_synthesis_path")
        or (parent_handoff.get("selected_revision") or {}).get(
            "orchestrator_synthesis_path"
        )
    )
    if isinstance(raw, str) and raw.strip():
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = root / path
        return path
    return default_orchestrator_synthesis_path(root, parent)


def load_orchestrator_synthesis(
    root: Path,
    parent: str,
    parent_handoff: dict[str, Any],
    explicit_synthesis_path: str | None = None,
    expected_host_trust_manifest_sha256: str | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if parent_handoff.get("contract_version") == PRE_OOS_CHILD_HANDOFF_VERSION:
        validated, reasons = validate_pre_oos_child_handoff(
            workspace_root=root,
            parent_report_id=parent,
            handoff=parent_handoff,
            require_materialization_ready=False,
            expected_host_trust_manifest_sha256=(expected_host_trust_manifest_sha256),
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        if validated is None or reasons:
            raise ValueError(
                f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid pre-OOS human handoff: "
                + ";".join(reasons)
            )
        reference = parent_handoff.get("pre_oos_root_synthesis_ref") or {}
        raw_path = reference.get("path")
        path = Path(str(raw_path or "")).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve(strict=False)
        if explicit_synthesis_path:
            explicit = Path(explicit_synthesis_path).expanduser()
            if not explicit.is_absolute():
                explicit = root / explicit
            if explicit.resolve(strict=False) != path:
                raise ValueError(
                    f"{ORCHESTRATOR_MISMATCH_BLOCK}: explicit synthesis does not "
                    "match the approved pre-OOS root synthesis"
                )
        selected = parent_handoff["selected_revision"]
        synthesis_projection = {
            "contract_version": "factorforge_pre_oos_council_root_synthesis_v1",
            "producer": "agent_authored_pre_oos_root_synthesis",
            "consensus_summary": None,
            "disagreement_summary": (
                "All route dissent is preserved or resolved in the bound pre-OOS "
                "root synthesis; no vote or score selected this revision."
            ),
            "selected_revision": selected,
            "prior_revision_memory": {},
        }
        return path, synthesis_projection, selected
    path = resolve_synthesis_path(root, parent, parent_handoff, explicit_synthesis_path)
    if not path.exists():
        raise ValueError(
            f"{SYNTHESIS_MISSING_BLOCK}: main-agent council synthesis is required before child materialization"
        )
    synthesis = load_json(path)
    if synthesis.get("contract_version") != MAIN_AGENT_COUNCIL_SYNTHESIS_VERSION:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid synthesis contract_version={synthesis.get('contract_version')!r}"
        )
    if synthesis.get("report_id") != parent:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis report_id does not match parent"
        )
    if synthesis.get("canonical_write_permission") is not False:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis must set canonical_write_permission=false"
        )
    if synthesis.get("execution_allowed_by_default") is not False:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis must set execution_allowed_by_default=false"
        )
    if synthesis.get("human_approval_required") is not True:
        raise ValueError(
            f"{ORCHESTRATOR_MISMATCH_BLOCK}: synthesis must require human approval"
        )

    selected = synthesis.get("selected_revision")
    if not isinstance(selected, dict):
        raise ValueError(
            f"{CHILD_FORMULA_MISSING_BLOCK}: synthesis.selected_revision is required"
        )
    if not nonempty_str(selected.get("law_id")):
        raise ValueError(
            f"{SELECTED_LAW_MISSING_BLOCK}: synthesis.selected_revision.law_id is required"
        )
    if not child_formula_or_law(selected):
        raise ValueError(
            f"{CHILD_FORMULA_MISSING_BLOCK}: synthesis.selected_revision.child_formula is required"
        )
    if not nonempty_dict(selected.get("expected_metric_signature")):
        raise ValueError(
            f"{METRIC_SIGNATURE_MISSING_BLOCK}: synthesis.selected_revision.expected_metric_signature is required"
        )
    if not nonempty_list(selected.get("falsification_tests")):
        raise ValueError(
            f"{FALSIFICATION_MISSING_BLOCK}: synthesis.selected_revision.falsification_tests is required"
        )
    if not nonempty_list(selected.get("kill_criteria")):
        raise ValueError(
            f"{KILL_CRITERIA_MISSING_BLOCK}: synthesis.selected_revision.kill_criteria is required"
        )

    law_id = nonempty_str(selected.get("law_id"))
    prior = (
        synthesis.get("prior_revision_memory")
        if isinstance(synthesis.get("prior_revision_memory"), dict)
        else {}
    )
    if not prior and isinstance(parent_handoff.get("prior_revision_memory"), dict):
        prior = parent_handoff["prior_revision_memory"]
    if (
        prior.get("falsified_revision")
        or prior.get("prior_revision_outcome") == "falsified"
    ):
        forbidden_rules = {
            str(item) for item in (prior.get("forbidden_repeat_revision_rules") or [])
        }
        if law_id in forbidden_rules:
            raise ValueError(
                f"{ORCHESTRATOR_MISMATCH_BLOCK}: selected law repeats a falsified prior revision rule"
            )
    return path, synthesis, selected


def build_executable_revision_spec(
    *,
    root: Path,
    parent: str,
    child: str,
    branch_id: str,
    parent_spec: dict[str, Any],
    parent_handoff: dict[str, Any],
    parent_iteration: dict[str, Any],
    parent_handoff_path: Path,
    source_handoff_sha256: str,
    explicit_synthesis_path: str | None = None,
    expected_host_trust_manifest_sha256: str | None = None,
    branch_context: dict[str, Any] | None = None,
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> dict[str, Any]:
    canonical = (
        parent_spec.get("canonical_spec")
        if isinstance(parent_spec.get("canonical_spec"), dict)
        else {}
    )
    parent_formula = str(canonical.get("formula_text") or "").strip()
    if not parent_formula:
        raise ValueError("BLOCK_FACTORFORGE_EXECUTABLE_REVISION_PARENT_FORMULA_MISSING")
    synthesis_path, synthesis, selected_revision = load_orchestrator_synthesis(
        root,
        parent,
        parent_handoff,
        explicit_synthesis_path,
        expected_host_trust_manifest_sha256,
        incident_trust_root,
        incident_installation_id,
        _incident_guard,
    )
    child_formula = child_formula_or_law(selected_revision)
    derivation_rule = nonempty_str(selected_revision.get("law_id"))
    implementation_mode = selected_implementation_mode(
        parent_spec, parent_handoff, selected_revision
    )
    parent_formula_hash = parent_formula_hash_for_audit(parent_formula)
    child_formula_ir, child_formula_hash, direct_code_revision_contract = (
        child_revision_hash(child_formula, implementation_mode, selected_revision)
    )
    revision_type = str(
        (parent_handoff.get("executable_revision_spec") or {}).get("revision_type")
        or parent_handoff.get("revision_type")
        or "formula_mutation"
    )
    if implementation_mode != "operator" and revision_type == "formula_mutation":
        revision_type = f"{implementation_mode}_mutation"
    if revision_type != "audit_rerun" and child_formula_hash == parent_formula_hash:
        raise ValueError("BLOCK_FACTORFORGE_CHILD_REVISION_NO_EFFECT")
    prior = (
        synthesis.get("prior_revision_memory")
        if isinstance(synthesis.get("prior_revision_memory"), dict)
        else {}
    )
    if not prior and isinstance(parent_handoff.get("prior_revision_memory"), dict):
        prior = parent_handoff["prior_revision_memory"]
    if (
        prior.get("falsified_revision")
        or prior.get("prior_revision_outcome") == "falsified"
    ):
        forbidden_hashes = {
            str(item) for item in (prior.get("forbidden_repeat_formula_hashes") or [])
        }
        if child_formula_hash in forbidden_hashes:
            raise ValueError(
                f"{ORCHESTRATOR_MISMATCH_BLOCK}: selected child formula recreates a forbidden prior formula hash"
            )
    selected_ids = [derivation_rule]
    spec_branch_id = (
        nonempty_str(branch_context.get("law_id")) if branch_context else branch_id
    )
    spec = {
        "contract_version": EXECUTABLE_REVISION_SPEC_VERSION,
        "created_at_utc": utc_now(),
        "parent_report_id": parent,
        "child_report_id": child,
        "branch_id": spec_branch_id or branch_id,
        "source_handoff_path": str(parent_handoff_path),
        "source_handoff_sha256": source_handoff_sha256,
        "source_council_summary_path": str(
            root
            / "objects"
            / "research_iteration_master"
            / "revision_council"
            / parent
            / f"revision_council_summary__{parent}.json"
        ),
        "source_orchestrator_synthesis_path": str(synthesis_path),
        "source_orchestrator_synthesis_sha256": sha256_file(synthesis_path),
        "selected_revision_law_ids": selected_ids,
        "revision_type": revision_type,
        "implementation_mode": implementation_mode,
        "derivation_rule": derivation_rule,
        "parent_formula": parent_formula,
        "child_formula": child_formula,
        "parent_formula_hash": parent_formula_hash,
        "child_formula_hash": child_formula_hash,
        "child_code_law_hash": child_formula_hash
        if implementation_mode != "operator"
        else None,
        "child_formula_ir": child_formula_ir,
        "direct_code_revision_contract": direct_code_revision_contract or None,
        "formula_mutation_description": selected_revision.get(
            "formula_mutation_description"
        )
        or f"Apply {derivation_rule} from main-agent Council synthesis.",
        "expected_metric_signature": selected_revision.get("expected_metric_signature")
        or {},
        "falsification_tests": selected_revision.get("falsification_tests") or [],
        "kill_criteria": selected_revision.get("kill_criteria") or [],
        "orchestrator_synthesis": {
            "contract_version": synthesis.get("contract_version"),
            "producer": synthesis.get("producer"),
            "consensus_summary": synthesis.get("consensus_summary"),
            "disagreement_summary": synthesis.get("disagreement_summary"),
            "selected_revision": {
                "law_id": derivation_rule,
                "source_agent_roles": selected_revision.get("source_agent_roles") or [],
                "why_selected": selected_revision.get("why_selected"),
                "economic_mechanism_link": selected_revision.get(
                    "economic_mechanism_link"
                ),
                "math_model_link": selected_revision.get("math_model_link"),
            },
        },
        "canonical_write_permission": False,
        "execution_allowed_by_default": False,
        "human_approval": (
            {
                "status": "external_human_approval_replayed",
                "source": "factorforge_pre_oos_human_approval_v1",
                "approved_by": "signed_external_human_receipt",
            }
            if parent_handoff.get("contract_version") == PRE_OOS_CHILD_HANDOFF_VERSION
            else {
                "status": "approved_for_materialization",
                "source": "approved_step3b_handoff",
                "approved_by": "user_or_default_approval_artifact",
            }
        ),
        "parent_iteration_path": (
            None
            if parent_handoff.get("contract_version") == PRE_OOS_CHILD_HANDOFF_VERSION
            else str(object_path(root, "research_iteration_master", parent))
        ),
        "pre_oos_human_approval_path": (
            (parent_handoff.get("pre_oos_human_approval_ref") or {}).get("path")
            if parent_handoff.get("contract_version") == PRE_OOS_CHILD_HANDOFF_VERSION
            else None
        ),
    }
    if parent_handoff.get("contract_version") == PRE_OOS_CHILD_HANDOFF_VERSION:
        if not expected_host_trust_manifest_sha256:
            raise ValueError(
                f"{ORCHESTRATOR_MISMATCH_BLOCK}: external Host trust pin is required"
            )
        public_ticket, ticket_reasons = validate_public_child_materialization_ticket(
            workspace_root=root,
            parent_report_id=parent,
            child_report_id=child,
            require_materialization_ready=True,
            handoff=parent_handoff,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
        if public_ticket is None or ticket_reasons:
            raise ValueError(
                f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid ready child materialization ticket: "
                + ";".join(ticket_reasons)
            )
        try:
            spec["evo_transfer_diagnostic_contract"] = (
                build_evo_transfer_diagnostic_contract(
                    workspace_root=root,
                    parent_report_id=parent,
                    child_report_id=child,
                    public_ticket=public_ticket,
                    expected_host_trust_manifest_sha256=(
                        expected_host_trust_manifest_sha256
                    ),
                )
            )
        except EvoChildExecutionError as exc:
            raise ValueError(
                f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid EVO transfer diagnostic contract: "
                + ";".join(exc.reasons)
            ) from exc
    if branch_context:
        spec["branch_role"] = branch_context["branch_role"]
        spec["branch_index"] = branch_context["branch_index"]
        spec["branch_group_id"] = branch_context["branch_group_id"]
        spec["source_multibranch_synthesis_path"] = branch_context[
            "source_multibranch_synthesis_path"
        ]
        spec["source_multibranch_synthesis_sha256"] = branch_context[
            "source_multibranch_synthesis_sha256"
        ]
        spec["sibling_branch_count"] = branch_context["sibling_branch_count"]
        spec["branch_context"] = branch_context
    return spec


CHILD_CONTROL_PRECONDITIONS = {
    "research_state",
    "research_conjecture",
    "approach_registry",
    "search_trial_ledger",
    "threshold_registration",
    "oos_allocation",
    "oos_allocation_registry",
    "evo_lifecycle",
}


def existing_target_paths(targets: dict[str, Path]) -> dict[str, str]:
    return {
        kind: str(path)
        for kind, path in targets.items()
        if kind not in CHILD_CONTROL_PRECONDITIONS and path.exists()
    }


def _workspace_relative(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if path != resolved_root and resolved_root not in path.parents:
        return None
    return path


def evo_child_control_preflight(
    *,
    root: Path,
    parent: str,
    child: str,
    parent_handoff: dict[str, Any],
    incident_trust_root: Path | None = None,
    incident_installation_id: str | None = None,
    _incident_guard: object | None = None,
) -> list[str]:
    parent_conjecture_path = research_protocol_paths(root, parent)["conjecture"]
    if not parent_conjecture_path.is_file() or parent_conjecture_path.is_symlink():
        return []
    try:
        parent_conjecture = load_json(parent_conjecture_path)
    except (OSError, json.JSONDecodeError):
        return []
    if not epistemic_evolution_enabled(parent_conjecture):
        return []

    reasons: list[str] = []
    receipt_ref = parent_handoff.get("external_human_approval_receipt")
    intent = parent_handoff.get("fresh_oos_child_intent")
    if not isinstance(receipt_ref, dict) or set(receipt_ref) != {
        "path",
        "sha256",
        "receipt_id",
        "issuer",
    }:
        reasons.append(
            "BLOCK_FACTORFORGE_EXTERNAL_HUMAN_APPROVAL_INVALID:handoff_receipt"
        )
    else:
        receipt_path = _workspace_relative(root, receipt_ref.get("path"))
        if (
            receipt_path is None
            or not receipt_path.is_file()
            or receipt_path.is_symlink()
            or receipt_ref.get("sha256") != evo_sha256_file(receipt_path)
            or (receipt_ref.get("issuer") or {}).get("kind") != "external_human"
        ):
            reasons.append(
                "BLOCK_FACTORFORGE_EXTERNAL_HUMAN_APPROVAL_INVALID:handoff_receipt_binding"
            )
    if (
        not isinstance(intent, dict)
        or intent.get("child_report_id") != child
        or intent.get("fresh_sealed_oos_required") is not True
        or intent.get("reuse_parent_ancestor_or_sibling_oos_allowed") is not False
    ):
        reasons.append("BLOCK_FACTORFORGE_EXTERNAL_HUMAN_APPROVAL_INVALID:child_intent")
        return reasons

    declared_allocation_path = _workspace_relative(
        root, intent.get("oos_allocation_ref")
    )
    if (
        declared_allocation_path is None
        or not declared_allocation_path.is_file()
        or declared_allocation_path.is_symlink()
        or intent.get("oos_allocation_sha256")
        != evo_sha256_file(declared_allocation_path)
    ):
        reasons.append(
            "BLOCK_FACTORFORGE_EXTERNAL_HUMAN_APPROVAL_INVALID:oos_allocation_binding"
        )
    registry_prefix_reasons = validate_oos_registry_allocation_prefix(
        intent.get("oos_registry_prefix_ref"),
        root=root,
        allocation_id=str(intent.get("oos_allocation_id") or ""),
        report_id=child,
    )
    reasons.extend(
        "BLOCK_FACTORFORGE_EXTERNAL_HUMAN_APPROVAL_INVALID:oos_registry_binding:"
        + reason
        for reason in registry_prefix_reasons
    )

    reasons.extend(
        validate_fresh_child_oos_allocation(
            root=root,
            parent_report_id=parent,
            child_report_id=child,
            allocation_id=str(intent.get("oos_allocation_id") or ""),
            allocation_ref=str(intent.get("oos_allocation_ref") or ""),
            incident_trust_root=incident_trust_root,
            incident_installation_id=incident_installation_id,
            _incident_guard=_incident_guard,
        )
    )
    controls = child_control_paths(root, child)
    for name in (
        "research_state",
        "research_conjecture",
        "approach_registry",
        "search_trial_ledger",
        "threshold_registration",
    ):
        path = controls[name]
        if not path.is_file() or path.is_symlink():
            reasons.append(f"{WAITING_FRESH_OOS}:child_control_missing:{name}")
    if reasons:
        return list(dict.fromkeys(reasons))
    try:
        child_conjecture = load_json(controls["research_conjecture"])
        ledger = load_json(controls["search_trial_ledger"])
        threshold = load_json(controls["threshold_registration"])
    except (OSError, json.JSONDecodeError):
        return [f"{WAITING_FRESH_OOS}:child_control_invalid"]
    if (
        not epistemic_evolution_enabled(child_conjecture)
        or child_conjecture.get("report_id") != child
    ):
        reasons.append(f"{WAITING_FRESH_OOS}:child_conjecture_not_evo_v2")
    if (
        ledger.get("version") != "factorforge_search_trial_ledger_v1"
        or ledger.get("search_status") != "FROZEN"
        or ledger.get("report_id") != child
        or not isinstance(ledger.get("trials"), list)
        or ledger.get("trial_count") != len(ledger.get("trials") or [])
    ):
        reasons.append(f"{WAITING_FRESH_OOS}:child_trial_ledger_not_frozen")
    if threshold.get("report_id") != child:
        reasons.append(f"{WAITING_FRESH_OOS}:child_threshold_identity")
    ledger_ref = threshold.get("search_trial_ledger_ref")
    ledger_sha = threshold.get("search_trial_ledger_sha256")
    if ledger_ref is not None:
        resolved_ledger = _workspace_relative(root, ledger_ref)
        if resolved_ledger != controls["search_trial_ledger"].resolve(strict=False):
            reasons.append(f"{WAITING_FRESH_OOS}:child_threshold_ledger_path")
    if ledger_sha is not None and ledger_sha != evo_sha256_file(
        controls["search_trial_ledger"]
    ):
        reasons.append(f"{WAITING_FRESH_OOS}:child_threshold_ledger_sha256")
    protocol = validate_protocol_bundle(
        root=root,
        report_id=child,
        stage="pre_council",
    )
    if protocol.get("verdict") != "PASS":
        reasons.append(f"{WAITING_FRESH_OOS}:child_protocol_not_preregistered")
        reasons.extend(str(reason) for reason in protocol.get("block_reasons") or [])
    return list(dict.fromkeys(reasons))


def idempotent_marker_matches(
    report_path: Path,
    *,
    parent: str,
    child: str,
    source_handoff_sha256: str,
    root: Path | None = None,
) -> bool:
    return not materialization_readback_reasons(
        report_path,
        parent=parent,
        child=child,
        source_handoff_sha256=source_handoff_sha256,
        root=root,
    )


def child_identity(
    identity: dict[str, Any],
    *,
    child_report_id: str,
    branch_id: str,
    parent_run_id: str | None,
    artifact_role: str,
    producer: str,
) -> dict[str, Any]:
    out = dict(identity or {})
    out["report_id"] = child_report_id
    out["branch_id"] = branch_id
    out["run_id"] = f"{child_report_id}__run_001"
    out["parent_run_id"] = parent_run_id
    out["artifact_role"] = artifact_role
    out["producer"] = producer
    return out


def rewrite_common(
    payload: dict[str, Any],
    *,
    child_report_id: str,
    branch_id: str,
    parent_run_id: str | None,
    artifact_role: str,
    producer: str,
) -> dict[str, Any]:
    out = json.loads(json.dumps(payload))
    out["report_id"] = child_report_id
    out["parent_report_id"] = out.get("parent_report_id") or payload.get("report_id")
    out["branch_id"] = branch_id
    identity = out.get("artifact_identity")
    if isinstance(identity, dict):
        out["artifact_identity"] = child_identity(
            identity,
            child_report_id=child_report_id,
            branch_id=branch_id,
            parent_run_id=parent_run_id,
            artifact_role=artifact_role,
            producer=producer,
        )
    return out


def apply_executable_revision_contract(
    payload: dict[str, Any],
    executable_revision_spec: dict[str, Any],
    *,
    root: Path,
    child_report_id: str,
) -> dict[str, Any]:
    """Keep child control artifacts aligned with the executable revision spec."""
    implementation_mode = (
        nonempty_str(executable_revision_spec.get("implementation_mode")) or "operator"
    )
    formula_ir = (
        executable_revision_spec.get("child_formula_ir")
        if isinstance(executable_revision_spec.get("child_formula_ir"), dict)
        else {}
    )
    formula_hash_value = str(
        executable_revision_spec.get("child_formula_hash")
        or formula_ir.get("formula_hash")
        or ""
    )
    payload["implementation_mode"] = implementation_mode
    if "execution_mode" in payload:
        payload["execution_mode"] = implementation_mode
    payload["formula_hash"] = formula_hash_value or payload.get("formula_hash")
    payload["executable_revision_spec_ref"] = str(
        executable_revision_spec_path(root, child_report_id)
    )
    diagnostic_contract = executable_revision_spec.get(
        "evo_transfer_diagnostic_contract"
    )
    if isinstance(diagnostic_contract, dict):
        payload["evo_transfer_diagnostic_contract"] = json.loads(
            json.dumps(diagnostic_contract)
        )
    if implementation_mode == "operator":
        payload["code_hash"] = None
        payload["code_contract_hash"] = None
        payload["factor_impl_ref"] = None
        payload["factor_impl_stub_ref"] = None
    if isinstance(payload.get("artifact_identity"), dict):
        identity = payload["artifact_identity"]
        identity["implementation_mode"] = implementation_mode
        identity["formula_hash"] = formula_hash_value or identity.get("formula_hash")
        if implementation_mode == "operator":
            identity["code_hash"] = None
            identity["code_contract_hash"] = None
    if "factor_spec_master_ref" in payload:
        payload["factor_spec_master_ref"] = (
            f"factor_spec_master__{child_report_id}.json"
        )
    if "data_prep_master_ref" in payload:
        payload["data_prep_master_ref"] = f"data_prep_master__{child_report_id}.json"
    if "implementation_plan_master_ref" in payload:
        payload["implementation_plan_master_ref"] = None
    if "hybrid_execution_scaffold_ref" in payload:
        if implementation_mode == "operator":
            payload["hybrid_execution_scaffold_ref"] = None
    contract = payload.get("implementation_contract")
    if isinstance(contract, dict):
        contract["implementation_mode"] = implementation_mode
        contract["mode"] = implementation_mode
        contract["formula_hash"] = formula_hash_value
        if implementation_mode == "operator":
            contract["formula_ir"] = formula_ir
            contract["operator_set"] = formula_ir.get("operator_set") or []
            contract["required_fields"] = formula_ir.get("required_fields") or []
            contract.pop("source_code", None)
            contract.pop("code_hash", None)
            contract.pop("code_contract_hash", None)
        else:
            revision_contract = executable_revision_spec.get(
                "direct_code_revision_contract"
            )
            if isinstance(revision_contract, dict) and revision_contract:
                existing_code_contract = (
                    contract.get("code_contract")
                    if isinstance(contract.get("code_contract"), dict)
                    else {}
                )
                merged_code_contract = dict(existing_code_contract)
                merged_code_contract.update(revision_contract)
                contract["code_contract"] = merged_code_contract
                contract["direct_code_revision_contract"] = revision_contract
            contract["formula_ir"] = None
            contract["operator_set"] = []
            if isinstance(revision_contract, dict):
                required_fields = (
                    revision_contract.get("required_fields")
                    or revision_contract.get("fields")
                    or []
                )
                if required_fields:
                    contract["required_fields"] = required_fields
        canonical = payload.get("canonical_spec")
        if isinstance(canonical, dict):
            canonical["formula_text"] = executable_revision_spec.get(
                "child_formula"
            ) or canonical.get("formula_text")
            canonical["formula_hash"] = formula_hash_value or canonical.get(
                "formula_hash"
            )
            if implementation_mode == "operator":
                canonical["formula_ir"] = formula_ir
                canonical["operator_set"] = formula_ir.get("operator_set") or []
                canonical["required_fields"] = formula_ir.get("required_fields") or []
            else:
                canonical["formula_ir"] = None
                canonical["operator_set"] = []
                canonical["operators"] = []
                revision_contract = executable_revision_spec.get(
                    "direct_code_revision_contract"
                )
                if isinstance(revision_contract, dict):
                    canonical["required_fields"] = (
                        revision_contract.get("required_fields")
                        or canonical.get("required_fields")
                        or []
                    )
    return payload


def _incident_guarded_materializer_main(function):
    @wraps(function)
    def guarded() -> int:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--incident-trust-root")
        parser.add_argument("--incident-installation-id")
        known, _unknown = parser.parse_known_args()
        if bool(known.incident_trust_root) != bool(known.incident_installation_id):
            print("BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_INCOMPLETE")
            return 1
        if not known.incident_trust_root:
            return function()
        trust_root = Path(known.incident_trust_root).expanduser().resolve(strict=True)
        global _ACTIVE_MATERIALIZER_INCIDENT_GUARD
        global _ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT
        global _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID
        with oos_exposure_private_registry_guard(
            trust_root,
            installation_id=known.incident_installation_id,
        ) as incident_guard:
            _ACTIVE_MATERIALIZER_INCIDENT_GUARD = incident_guard
            _ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT = trust_root
            _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID = (
                known.incident_installation_id
            )
            try:
                return function()
            finally:
                _ACTIVE_MATERIALIZER_INCIDENT_GUARD = None
                _ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT = None
                _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID = None

    return guarded


@_incident_guarded_materializer_main
def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Internal Host/Ultimate materializer for an approved legacy Step6 or "
            "strict EVO pre-OOS child handoff; direct production invocation is "
            "forbidden, and EVO requires the out-of-band Host trust-manifest pin."
        )
    )
    ap.add_argument("--parent-report-id", required=True)
    ap.add_argument("--child-report-id", required=True)
    ap.add_argument("--factorforge-root", default=None)
    ap.add_argument("--synthesis-path", default=None)
    ap.add_argument("--expected-host-trust-manifest-sha256", default=None)
    ap.add_argument("--incident-trust-root", default=None)
    ap.add_argument("--incident-installation-id", default=None)
    ap.add_argument("--branch-group-id", default=None)
    ap.add_argument("--branch-index", type=int, default=None)
    ap.add_argument("--branch-role", default=None)
    ap.add_argument("--branch-law-id", default=None)
    ap.add_argument("--source-multibranch-synthesis-path", default=None)
    ap.add_argument("--source-multibranch-synthesis-sha256", default=None)
    ap.add_argument("--sibling-branch-count", type=int, default=None)
    args = ap.parse_args()

    if (
        os.getenv("FACTORFORGE_ULTIMATE_RUN") != "1"
        and os.getenv("FACTORFORGE_ULTIMATE_LOOP_MATERIALIZE") != "1"
    ):
        print(
            "BLOCKED_DIRECT_MATERIALIZE: child revision materialization must be invoked by the ultimate loop orchestrator."
        )
        return 1

    ctx = resolve_factorforge_context(args.factorforge_root)
    root = ctx.factorforge_root
    parent = args.parent_report_id
    child = args.child_report_id
    if parent == child:
        print("BLOCK_FACTORFORGE_LOOP_CHILD_REPORT_ID_COLLISION")
        return 1

    parent_handoff_path = object_path(root, "handoff_to_step3b", parent)
    parent_iteration_path = object_path(root, "research_iteration_master", parent)
    if not parent_handoff_path.exists():
        print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
        return 1

    source_handoff_sha256 = sha256_file(parent_handoff_path)
    parent_handoff = load_json(parent_handoff_path)
    pre_oos_handoff = (
        parent_handoff.get("contract_version") == PRE_OOS_CHILD_HANDOFF_VERSION
    )
    child_web_resolution: dict[str, Any] | None = None
    if pre_oos_handoff:
        if (
            _ACTIVE_MATERIALIZER_INCIDENT_GUARD is None
            or _ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT is None
            or not _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID
        ):
            print("BLOCK_FACTORFORGE_OOS_INCIDENT_HOST_CONTEXT_REQUIRED")
            return 1
        if parent_handoff.get("child_report_id") != child:
            print(f"{ORCHESTRATOR_MISMATCH_BLOCK}: child report id mismatch")
            return 1
        validated_handoff, handoff_reasons = validate_pre_oos_child_handoff(
            workspace_root=root,
            parent_report_id=parent,
            handoff=parent_handoff,
            require_materialization_ready=True,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
            incident_trust_root=_ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT,
            incident_installation_id=(
                _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID
            ),
            _incident_guard=_ACTIVE_MATERIALIZER_INCIDENT_GUARD,
        )
        if validated_handoff is None or handoff_reasons:
            waiting = WAITING_PRE_OOS_TRANSFER in handoff_reasons
            print(WAITING_PRE_OOS_TRANSFER if waiting else ORCHESTRATOR_MISMATCH_BLOCK)
            print(
                json.dumps(
                    {
                        "parent_report_id": parent,
                        "child_report_id": child,
                        "status": "PAUSED" if waiting else "BLOCK",
                        "reasons": handoff_reasons,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 3 if waiting else 1
        try:
            child_web_resolution = (
                validate_and_resolve_evo_child_web_research_plan(
                    workspace_root=root,
                    parent_report_id=parent,
                    child_report_id=child,
                    expected_host_trust_manifest_sha256=str(
                        args.expected_host_trust_manifest_sha256 or ""
                    ),
                    incident_trust_root=(
                        _ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT
                    ),
                    incident_installation_id=(
                        _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID
                    ),
                    _incident_guard=_ACTIVE_MATERIALIZER_INCIDENT_GUARD,
                )
            )
        except EvoChildPreregistrationError as exc:
            print(str(exc))
            return 1
        parent_iteration = {}
    else:
        if not parent_iteration_path.exists():
            print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
            return 1
        parent_iteration = load_json(parent_iteration_path)
        revision_strategy = (
            (parent_iteration.get("research_judgment") or {}).get("research_memo") or {}
        ).get("revision_strategy") or {}
        if revision_strategy.get("loop_authorization") != "approved_for_step3b_handoff":
            print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
            return 1

    branch_id = str(
        parent_handoff.get("new_branch_id")
        or parent_handoff.get("revision_id")
        or parent_handoff.get("branch_id")
        or child.rsplit("__", 1)[-1]
    ).strip()
    if not branch_id:
        print("BLOCK_FACTORFORGE_LOOP_APPROVED_CHILD_REVISION_MISSING")
        return 1
    parent_identity = parent_handoff.get("parent_identity") or {}
    parent_run_id = parent_handoff.get("parent_run_id") or parent_identity.get("run_id")

    required_parent_paths = {
        "alpha_idea_master": object_path(root, "alpha_idea_master", parent),
        "factor_spec_master": object_path(root, "factor_spec_master", parent),
        "data_prep_master": object_path(root, "data_prep_master", parent),
    }
    missing = [
        str(path) for path in required_parent_paths.values() if not path.exists()
    ]
    if missing:
        print("BLOCK_FACTORFORGE_LOOP_CHILD_MATERIALIZATION_FAILED")
        print(
            json.dumps(
                {"missing_parent_artifacts": missing}, ensure_ascii=False, indent=2
            )
        )
        return 1
    parent_data_prep = load_json(required_parent_paths["data_prep_master"])
    parent_runtime_inputs = json.loads(json.dumps(parent_data_prep))
    parent_step4_handoff_path = object_path(root, "handoff_to_step4", parent)
    if parent_step4_handoff_path.is_file() and not parent_step4_handoff_path.is_symlink():
        parent_step4_handoff = load_json(parent_step4_handoff_path)
        handoff_local_inputs = parent_step4_handoff.get("local_input_paths")
        if isinstance(handoff_local_inputs, dict):
            runtime_local_inputs = parent_runtime_inputs.setdefault(
                "local_input_paths", {}
            )
            if not isinstance(runtime_local_inputs, dict):
                runtime_local_inputs = {}
                parent_runtime_inputs["local_input_paths"] = runtime_local_inputs
            runtime_local_inputs.update(handoff_local_inputs)
    declared_daily_keys = declared_daily_source_keys(parent_runtime_inputs)
    resolved_daily = resolved_daily_sources(root, parent_runtime_inputs)
    missing_daily = sorted(
        key
        for key in declared_daily_keys
        if key not in resolved_daily
    )
    if missing_daily:
        local_inputs = (
            parent_data_prep.get("local_input_paths")
            if isinstance(parent_data_prep.get("local_input_paths"), dict)
            else {}
        )
        print(DAILY_SNAPSHOT_MISSING_BLOCK)
        print(
            json.dumps(
                {
                    "parent_report_id": parent,
                    "child_report_id": child,
                    "missing_daily_source_keys": missing_daily,
                    "declared_paths": {
                        key: local_inputs.get(key) for key in missing_daily
                    },
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    child_control_reasons = evo_child_control_preflight(
        root=root,
        parent=parent,
        child=child,
        parent_handoff=parent_handoff,
        incident_trust_root=_ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT,
        incident_installation_id=(
            _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID
        ),
        _incident_guard=_ACTIVE_MATERIALIZER_INCIDENT_GUARD,
    )
    if child_control_reasons:
        waiting = any(
            reason.startswith(WAITING_FRESH_OOS) for reason in child_control_reasons
        )
        print(
            WAITING_FRESH_OOS
            if waiting
            else "BLOCK_FACTORFORGE_EVO_CHILD_CONTROL_INVALID"
        )
        print(
            json.dumps(
                {
                    "parent_report_id": parent,
                    "child_report_id": child,
                    "status": "WAITING_DATA" if waiting else "BLOCK",
                    "reasons": child_control_reasons,
                    "planned_child_control_paths": {
                        key: str(path)
                        for key, path in child_control_paths(root, child).items()
                    },
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 3 if waiting else 1
    targets = planned_target_paths(root, parent, child, parent_runtime_inputs)
    materialization_lock = _acquire_materialization_lock(root, parent, child)

    def locked_return(code: int) -> int:
        _release_materialization_lock(materialization_lock)
        return code

    report_path = materialization_report_path(root, parent, child)
    staging_manifest_path = materialization_staging_manifest_path(
        root,
        parent,
        child,
    )
    if report_path.exists() or report_path.is_symlink():
        readback_reasons = materialization_readback_reasons(
            report_path,
            parent=parent,
            child=child,
            source_handoff_sha256=source_handoff_sha256,
            root=root,
        )
        if not readback_reasons:
            report = load_json(report_path)
            print(
                json.dumps(
                    {
                        "status": "idempotent_noop",
                        "report_path": str(report_path),
                        **report,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return locked_return(0)
        print(MATERIALIZATION_READBACK_BLOCK)
        print(
            json.dumps(
                {
                    "parent_report_id": parent,
                    "child_report_id": child,
                    "report_path": str(report_path),
                    "reasons": readback_reasons,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return locked_return(1)

    if staging_manifest_path.exists() or staging_manifest_path.is_symlink():
        try:
            report = _commit_prepared_materialization(
                root=root,
                manifest_path=staging_manifest_path,
                parent=parent,
                child=child,
                source_handoff_sha256=source_handoff_sha256,
            )
        except ValueError as exc:
            print(str(exc))
            return locked_return(1)
        print(
            json.dumps(
                {
                    "status": "recovered_materialization",
                    "report_path": str(report_path),
                    **report,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return locked_return(0)

    existing_targets = existing_target_paths(targets)
    if existing_targets:
        print(TARGET_EXISTS_BLOCK)
        print(
            json.dumps(
                {
                    "reason": "child_materialization_target_already_exists",
                    "parent_report_id": parent,
                    "child_report_id": child,
                    "existing_targets": existing_targets,
                    "materialization_report_path": str(report_path),
                    "source_handoff_sha256": source_handoff_sha256,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return locked_return(1)

    try:
        staging_directory = _prepare_staging_directory(root, parent, child)
    except ValueError as exc:
        print(str(exc))
        return locked_return(1)
    entries: list[dict[str, Any]] = []

    def stage_json(kind: str, target: Path, payload: dict[str, Any]) -> None:
        entries.append(
            _stage_materialization_bytes(
                root=root,
                staging_directory=staging_directory,
                kind=kind,
                target_path=target,
                data=_json_bytes(payload),
            )
        )

    def stage_copy(kind: str, target: Path, source: Path) -> None:
        entries.append(
            _stage_materialization_copy(
                root=root,
                staging_directory=staging_directory,
                kind=kind,
                target_path=target,
                source_path=source,
            )
        )

    def stage_daily_copy(kind: str, target: Path, source: Path) -> None:
        if child_web_research_windows is None:
            stage_copy(kind, target, source)
            return
        suffix = source.suffix.lower()
        frame = (
            pd.read_parquet(source)
            if suffix == ".parquet"
            else pd.read_csv(source)
        )
        if "trade_date" not in frame.columns:
            raise ValueError("BLOCK_FACTORFORGE_EVO_CHILD_PURGED_IS_INPUT_DATE_MISSING")
        dates = pd.to_datetime(
            frame["trade_date"].astype(str).str.replace("-", "", regex=False),
            format="%Y%m%d",
            errors="coerce",
        )
        start = pd.Timestamp(child_web_research_windows["is_start"])
        end = pd.Timestamp(child_web_research_windows["is_end"])
        filtered = frame.loc[dates.between(start, end)].copy()
        if filtered.empty or bool((dates.loc[filtered.index] > end).any()):
            raise ValueError("BLOCK_FACTORFORGE_EVO_CHILD_PURGED_IS_INPUT_EMPTY")
        if suffix == ".parquet":
            buffer = io.BytesIO()
            filtered.to_parquet(buffer, index=False)
            data = buffer.getvalue()
        elif suffix == ".csv":
            data = filtered.to_csv(index=False).encode("utf-8")
        else:
            raise ValueError("BLOCK_FACTORFORGE_EVO_CHILD_PURGED_IS_INPUT_FORMAT")
        entries.append(
            _stage_materialization_bytes(
                root=root,
                staging_directory=staging_directory,
                kind=kind,
                target_path=target,
                data=data,
            )
        )

    materialized: dict[str, str] = {}
    child_daily_bindings = {
        source_key: _workspace_relative_path(
            root, targets[f"child_daily_input_{source_key}"]
        )
        for source_key in resolved_daily
    }
    producer = "ultimate_loop_child_materializer"
    parent_spec = load_json(required_parent_paths["factor_spec_master"])
    child_web_plan: dict[str, Any] | None = None
    child_web_plan_ref: str | None = None
    child_web_plan_sha256: str | None = None
    child_web_evaluation_contract: dict[str, Any] | None = None
    child_web_research_windows: dict[str, Any] | None = None
    if child_web_resolution is not None:
        child_web_plan = dict(child_web_resolution["raw_plan"])
        child_web_plan_ref = Path(child_web_resolution["plan_path"]).relative_to(
            root
        ).as_posix()
        child_web_plan_sha256 = web_stable_json_hash(child_web_plan)
        child_web_evaluation_contract = build_web_evaluation_contract(
            child_web_plan
        )
        child_evidence = child_web_plan["evidence_policy"]
        allocation_window = child_web_resolution["allocation"]["oos_window"]
        child_web_research_windows = {
            "is_start": str(child_evidence["is_start"]),
            "is_end": str(child_evidence["is_end"]),
            "oos_start": str(allocation_window["start"]),
            "oos_end": str(allocation_window["end"]),
            "purge_days": int(child_evidence["purge_days"]),
            "embargo_days": int(child_evidence["embargo_days"]),
        }
    try:
        branch_context = None
        branch_args = {
            "branch_group_id": args.branch_group_id,
            "branch_index": args.branch_index,
            "branch_role": args.branch_role,
            "law_id": args.branch_law_id,
            "source_multibranch_synthesis_path": args.source_multibranch_synthesis_path,
            "source_multibranch_synthesis_sha256": args.source_multibranch_synthesis_sha256,
            "sibling_branch_count": args.sibling_branch_count,
        }
        if any(value is not None for value in branch_args.values()):
            missing_branch_args = sorted(
                key
                for key, value in branch_args.items()
                if value is None or value == ""
            )
            if missing_branch_args:
                print(
                    f"{ORCHESTRATOR_MISMATCH_BLOCK}: incomplete branch context: {','.join(missing_branch_args)}"
                )
                return locked_return(1)
            if args.branch_role not in {"exploit", "exploration"}:
                print(
                    f"{ORCHESTRATOR_MISMATCH_BLOCK}: invalid branch_role={args.branch_role!r}"
                )
                return locked_return(1)
            branch_context = {
                "parent_report_id": parent,
                "child_report_id": child,
                "branch_group_id": str(args.branch_group_id),
                "branch_index": int(args.branch_index),
                "branch_role": str(args.branch_role),
                "law_id": str(args.branch_law_id),
                "source_multibranch_synthesis_path": str(
                    args.source_multibranch_synthesis_path
                ),
                "source_multibranch_synthesis_sha256": str(
                    args.source_multibranch_synthesis_sha256
                ),
                "sibling_branch_count": int(args.sibling_branch_count),
            }
        executable_revision_spec = build_executable_revision_spec(
            root=root,
            parent=parent,
            child=child,
            branch_id=branch_id,
            parent_spec=parent_spec,
            parent_handoff=parent_handoff,
            parent_iteration=parent_iteration,
            parent_handoff_path=parent_handoff_path,
            source_handoff_sha256=source_handoff_sha256,
            explicit_synthesis_path=args.synthesis_path,
            expected_host_trust_manifest_sha256=(
                args.expected_host_trust_manifest_sha256
            ),
            branch_context=branch_context,
            incident_trust_root=_ACTIVE_MATERIALIZER_INCIDENT_TRUST_ROOT,
            incident_installation_id=(
                _ACTIVE_MATERIALIZER_INCIDENT_INSTALLATION_ID
            ),
            _incident_guard=_ACTIVE_MATERIALIZER_INCIDENT_GUARD,
        )
    except ValueError as exc:
        print(str(exc))
        return locked_return(1)
    executable_path = executable_revision_spec_path(root, child)
    stage_json("executable_revision_spec", executable_path, executable_revision_spec)
    materialized["executable_revision_spec"] = str(executable_path)

    for kind, source in required_parent_paths.items():
        role = kind
        payload = rewrite_common(
            load_json(source),
            child_report_id=child,
            branch_id=branch_id,
            parent_run_id=parent_run_id,
            artifact_role=role,
            producer=producer,
        )
        if kind == "factor_spec_master":
            payload = apply_executable_revision_contract(
                payload,
                executable_revision_spec,
                root=root,
                child_report_id=child,
            )
            payload["revision_identity"] = {
                "contract_version": "factorforge_child_revision_identity_v1",
                "parent_report_id": parent,
                "child_report_id": child,
                "revision_spec_path": str(executable_revision_spec_path(root, child)),
                "parent_formula_hash": executable_revision_spec["parent_formula_hash"],
                "child_formula_hash": executable_revision_spec["child_formula_hash"],
                "implementation_mode": executable_revision_spec.get(
                    "implementation_mode"
                ),
                "revision_noop": executable_revision_spec["parent_formula_hash"]
                == executable_revision_spec["child_formula_hash"],
                "revision_identity_status": "audit_rerun"
                if executable_revision_spec["revision_type"] == "audit_rerun"
                else "changed",
            }
        if kind == "data_prep_master":
            local_inputs = payload.setdefault("local_input_paths", {})
            if isinstance(local_inputs, dict):
                copied_daily: dict[str, str] = {}
                for source_key, daily_source in resolved_daily.items():
                    child_daily = targets[f"child_daily_input_{source_key}"]
                    stage_daily_copy(
                        f"child_daily_input_{source_key}", child_daily, daily_source
                    )
                    source_format = daily_source.suffix.lstrip(".")
                    copied_daily[source_key] = _workspace_relative_path(
                        root, child_daily
                    )
                    local_inputs[source_key] = copied_daily[source_key]
                    materialized[f"child_daily_input_{source_key}"] = str(child_daily)
                meta_source = resolved_path(
                    root,
                    (parent_data_prep.get("local_input_paths") or {}).get(
                        "daily_input_meta_json"
                    ),
                )
                if (
                    meta_source
                    and meta_source.exists()
                    and "child_daily_input_meta_json" in targets
                ):
                    child_meta = targets["child_daily_input_meta_json"]
                    stage_copy("child_daily_input_meta_json", child_meta, meta_source)
                    local_inputs["daily_input_meta_json"] = str(child_meta)
                    materialized["child_daily_input_meta_json"] = str(child_meta)
                if local_inputs.get("daily_df_parquet"):
                    local_inputs["preferred_daily_format"] = "parquet"
                if local_inputs.get("daily_df_csv"):
                    local_inputs["audit_daily_format"] = "csv"
                daily_io = local_inputs.get("daily_io_contract")
                if isinstance(daily_io, dict):
                    if "daily_df_parquet" in copied_daily:
                        daily_io["performance_path"] = "parquet"
                    if "daily_df_csv" in copied_daily:
                        daily_io["audit_path"] = "csv"
                        daily_io["csv_path"] = copied_daily["daily_df_csv"]
                    if "daily_df_csv" not in copied_daily:
                        daily_io["csv_path"] = None
                    daily_io["csv_sample_path"] = None
                local_inputs["input_mode"] = (
                    local_inputs.get("input_mode") or "daily_only"
                )
            if child_web_research_windows is not None:
                project_child_pre_release_data_access(
                    payload, dict(child_web_research_windows)
                )
            state_reuse_contract, state_artifacts = build_child_state_reuse(
                root,
                child,
                payload,
            )
            for state_kind, (state_path, state_payload) in state_artifacts.items():
                stage_json(state_kind, state_path, state_payload)
            payload["state_reuse_contract"] = state_reuse_contract
            materialized["state_dependency_contract"] = state_reuse_contract[
                "state_dependency_contract_path"
            ]
            materialized["state_resolution"] = state_reuse_contract[
                "state_resolution_path"
            ]
            if state_reuse_contract["data_request_ids"]:
                materialized["state_data_request_dir"] = state_reuse_contract[
                    "data_request_dir"
                ]
        payload = apply_executable_revision_contract(
            payload,
            executable_revision_spec,
            root=root,
            child_report_id=child,
        )
        if child_web_plan is not None:
            payload = bind_child_web_runtime_contract(
                payload,
                kind=kind,
                plan_ref=str(child_web_plan_ref),
                plan_sha256=str(child_web_plan_sha256),
                evaluation_contract=dict(child_web_evaluation_contract),
                research_windows=dict(child_web_research_windows),
            )
        target = object_path(root, kind, child)
        stage_json(kind, target, payload)
        materialized[kind] = str(target)

    optional_roles = {
        "handoff_to_step3": "handoff_to_step3",
        "handoff_to_step4": "handoff_to_step4_seed",
    }
    optional_payloads: dict[str, tuple[Path, dict[str, Any]]] = {}
    for kind, role in optional_roles.items():
        source = object_path(root, kind, parent)
        if source.exists():
            source_payload = load_json(source)
        elif kind == "handoff_to_step4" and child_web_plan is not None:
            # A pre-OOS child is allowed to branch before the parent ever ran
            # Step3A.  In that case there is no parent Step4 handoff to copy,
            # but the child still needs the canonical Step3B/Step4 seed.  Its
            # contents are derived only from already validated parent inputs
            # and the frozen child Web plan; no empirical result is invented.
            source_payload = {
                "report_id": parent,
                "artifact_identity": {
                    "report_id": parent,
                    "factor_id": parent_data_prep.get("factor_id"),
                    "research_id": parent_data_prep.get("research_id"),
                    "artifact_role": "handoff_to_step4_seed",
                    "implementation_mode": parent_data_prep.get(
                        "implementation_mode"
                    )
                    or "operator",
                },
                "step3a_ready": True,
                "step3b_ready": False,
                "data_prep_master_ref": object_path(
                    root, "data_prep_master", child
                ).name,
                "qlib_adapter_config_ref": object_path(
                    root, "qlib_adapter_config", child
                ).name,
                "factor_spec_master_ref": object_path(
                    root, "factor_spec_master", child
                ).name,
                "local_input_paths": {},
                "step4_data_contract": json.loads(
                    json.dumps(parent_data_prep.get("step4_data_contract") or {})
                ),
            }
        else:
            continue
        payload = rewrite_common(
            source_payload,
            child_report_id=child,
            branch_id=branch_id,
            parent_run_id=parent_run_id,
            artifact_role=role,
            producer=producer,
        )
        if kind == "handoff_to_step4":
            payload["factor_impl_ref"] = None
            payload["factor_impl_stub_ref"] = None
            payload["step6_parent_handoff_ref"] = str(parent_handoff_path)
            local_inputs = payload.setdefault("local_input_paths", {})
            if not isinstance(local_inputs, dict):
                local_inputs = {}
                payload["local_input_paths"] = local_inputs
            for source_key in _CHILD_WEB_DAILY_PATH_KEYS:
                local_inputs.pop(source_key, None)
            local_inputs.update(child_daily_bindings)
        payload = apply_executable_revision_contract(
            payload,
            executable_revision_spec,
            root=root,
            child_report_id=child,
        )
        if child_web_plan is not None:
            payload = bind_child_web_runtime_contract(
                payload,
                kind=kind,
                plan_ref=str(child_web_plan_ref),
                plan_sha256=str(child_web_plan_sha256),
                evaluation_contract=dict(child_web_evaluation_contract),
                research_windows=dict(child_web_research_windows),
            )
        target = object_path(root, kind, child)
        optional_payloads[kind] = (target, payload)
        materialized[kind] = str(target)

    qlib_payload, qlib_status = build_child_qlib_adapter_config(
        root,
        parent,
        child,
    )
    qlib_path = object_path(root, "qlib_adapter_config", child)
    if "handoff_to_step4" in optional_payloads:
        handoff_path, handoff_payload = optional_payloads["handoff_to_step4"]
        handoff_payload["qlib_adapter_config_ref"] = qlib_path.name
        handoff_payload["qlib_adapter_config_path"] = str(qlib_path)
        handoff_payload.setdefault(
            "qlib_adapter_config_lineage",
            qlib_payload.get("qlib_adapter_config_lineage"),
        )
        optional_payloads["handoff_to_step4"] = (handoff_path, handoff_payload)
    for kind, (target, payload) in optional_payloads.items():
        stage_json(kind, target, payload)
    stage_json("qlib_adapter_config", qlib_path, qlib_payload)
    materialized["qlib_adapter_config"] = str(qlib_path)
    materialized["qlib_adapter_config_status"] = qlib_status

    report_branch_id = executable_revision_spec.get("branch_id") or branch_id
    report = {
        "materialization_version": MATERIALIZATION_VERSION,
        "created_at_utc": utc_now(),
        "workspace_root": str(root.resolve(strict=False)),
        "parent_report_id": parent,
        "child_report_id": child,
        "parent_handoff_path": str(parent_handoff_path),
        "source_handoff_sha256": source_handoff_sha256,
        "branch_id": report_branch_id,
        "source_branch_id": branch_id,
        "parent_run_id": parent_run_id,
        "materialized_artifacts": materialized,
        "materialization_target_hashes": _target_hash_projection(entries),
        "planned_child_control_paths": {
            key: str(path) for key, path in child_control_paths(root, child).items()
        },
        "executable_revision_spec_path": str(
            executable_revision_spec_path(root, child)
        ),
        "parent_formula_hash": executable_revision_spec.get("parent_formula_hash"),
        "child_formula_hash": executable_revision_spec.get("child_formula_hash"),
        "revision_identity_status": "audit_rerun"
        if executable_revision_spec.get("revision_type") == "audit_rerun"
        else "changed",
        "generated_code_written": False,
        "clean_data_touched": False,
        "official_promotion_written": False,
    }
    if child_web_plan is not None:
        report["child_web_research_plan"] = {
            "path": child_web_plan_ref,
            "sha256": child_web_plan_sha256,
            "evaluation_contract_sha256": web_stable_json_hash(
                child_web_evaluation_contract
            ),
        }
    if branch_context:
        report.update(
            {
                "branch_role": branch_context["branch_role"],
                "branch_index": branch_context["branch_index"],
                "branch_group_id": branch_context["branch_group_id"],
                "source_multibranch_synthesis_path": branch_context[
                    "source_multibranch_synthesis_path"
                ],
                "source_multibranch_synthesis_sha256": branch_context[
                    "source_multibranch_synthesis_sha256"
                ],
                "sibling_branch_count": branch_context["sibling_branch_count"],
                "branch_context": branch_context,
            }
        )
    try:
        staging_manifest_path, _manifest = _write_prepared_materialization_manifest(
            root=root,
            parent=parent,
            child=child,
            source_handoff_sha256=source_handoff_sha256,
            entries=entries,
            report_payload=report,
        )
        report = _commit_prepared_materialization(
            root=root,
            manifest_path=staging_manifest_path,
            parent=parent,
            child=child,
            source_handoff_sha256=source_handoff_sha256,
        )
    except ValueError as exc:
        print(str(exc))
        return locked_return(1)
    print(
        json.dumps(
            {"status": "materialized", "report_path": str(report_path), **report},
            ensure_ascii=False,
            indent=2,
        )
    )
    return locked_return(0)


if __name__ == "__main__":
    raise SystemExit(main())
