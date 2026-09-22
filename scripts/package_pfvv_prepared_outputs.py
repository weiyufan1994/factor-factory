"""Package one completed local PF/VV worker run for later authorized transfer.

This is a narrow archive helper.  It does not discover files, access a
network, read raw data, or upload anything.  Every archived parquet member is
named by the producer manifest and is hash-checked before being streamed into
the create-only tarball.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import re
from typing import Any


class PackageError(ValueError):
    pass


_DATE_RE = re.compile(r"\A\d{8}\Z")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"{label}_unreadable") from exc
    if not isinstance(value, dict):
        raise PackageError(f"{label}_must_be_object")
    return value


def _required_file(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise PackageError(f"{label}_path_invalid")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or any(part in {"", "."} for part in rel.parts):
        raise PackageError(f"{label}_path_escape")
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.is_file():
        raise PackageError(f"{label}_missing_or_symlink")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise PackageError(f"{label}_symlink_ancestor")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise PackageError(f"{label}_path_escape")
    return path


def _required_dir(root: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise PackageError(f"{label}_path_invalid")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or any(part in {"", "."} for part in rel.parts):
        raise PackageError(f"{label}_path_escape")
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.is_dir():
        raise PackageError(f"{label}_missing_or_symlink")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise PackageError(f"{label}_symlink_ancestor")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents:
        raise PackageError(f"{label}_path_escape")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_member(archive: tarfile.TarFile, path: Path, arcname: str, members: set[str]) -> None:
    if arcname in members:
        raise PackageError(f"duplicate_archive_member:{arcname}")
    members.add(arcname)
    archive.add(path, arcname=arcname, recursive=False)


def package_pfvv_prepared_outputs(run_root: str | Path, output_file: str | Path) -> dict[str, Any]:
    """Validate and stream one completed worker run into a create-only tar.gz."""
    root = Path(run_root).expanduser()
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise PackageError("run_root_must_be_existing_absolute_directory")
    root = root.resolve()
    output = Path(output_file).expanduser()
    if not output.is_absolute() or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise PackageError("output_file_must_be_new_absolute_path")
    partial = Path(os.fspath(output) + ".partial")
    if partial.exists() or partial.is_symlink():
        raise PackageError("partial_output_already_exists")

    execution = _read_json(_required_file(root, "execution_summary.json", "execution_summary"), "execution_summary")
    if execution.get("status") != "COMPLETE" or execution.get("returncode") != 0:
        raise PackageError("execution_summary_not_complete")
    source_plan = _read_json(_required_file(root, "source_plan.json", "source_plan"), "source_plan")
    daily_root = _required_dir(root, "daily_measurements", "daily_measurements")
    manifest = _read_json(_required_file(daily_root, "daily_measurements_manifest.json", "daily_manifest"), "daily_manifest")
    if source_plan.get("version") != "pfvv_daily_source_plan_v1":
        raise PackageError("source_plan_version_mismatch")
    if manifest.get("version") != "pfvv_daily_measurements_manifest_v1":
        raise PackageError("daily_manifest_version_mismatch")
    if not isinstance(source_plan.get("research_id"), str) or not source_plan["research_id"]:
        raise PackageError("research_id_mismatch_or_missing")
    if manifest.get("research_id") != source_plan.get("research_id"):
        raise PackageError("daily_manifest_research_id_mismatch")
    if manifest.get("status") != "COMPLETE":
        raise PackageError("daily_manifest_not_complete")
    plan_dates = source_plan.get("trading_calendar")
    manifest_dates = manifest.get("trading_calendar")
    days = manifest.get("days")
    if not isinstance(plan_dates, list) or not isinstance(manifest_dates, list) or not plan_dates:
        raise PackageError("source_plan_manifest_calendar_mismatch")
    if (plan_dates != manifest_dates or any(not isinstance(day, str) or not _DATE_RE.match(day) for day in plan_dates)
            or len(plan_dates) != len(set(plan_dates)) or plan_dates != sorted(plan_dates)):
        raise PackageError("source_plan_manifest_calendar_mismatch")
    if not isinstance(days, list) or len(days) != len(manifest_dates) or {row.get("trade_date") for row in days if isinstance(row, dict)} != set(manifest_dates):
        raise PackageError("manifest_days_calendar_mismatch")
    inner_plan = _read_json(_required_file(daily_root, "source_plan.json", "daily_source_plan"), "daily_source_plan")
    if inner_plan != source_plan:
        raise PackageError("source_plan_content_mismatch")

    fixed = ["source_plan.json", "execution_summary.json", "progress.log",
             "daily_measurements/source_plan.json", "daily_measurements/daily_measurements_manifest.json"]
    files: list[tuple[Path, str]] = [(_required_file(root, name, name), name) for name in fixed]
    seen: set[str] = set()
    for row in days:
        if not isinstance(row, dict):
            raise PackageError("manifest_day_invalid")
        day = row.get("trade_date")
        for field, hash_field in (("path", "output_sha256"), ("execution_path", "execution_sha256")):
            relative = row.get(field)
            if not isinstance(relative, str) or not relative or hash_field not in row:
                raise PackageError(f"manifest_{field}_missing:{day}")
            expected_name = f"daily_{day}.parquet" if field == "path" else f"execution_{day}.parquet"
            if relative != expected_name:
                raise PackageError(f"manifest_{field}_name_invalid:{day}")
            path = _required_file(daily_root, relative, f"daily_{day}_{field}")
            rel = PurePosixPath("daily_measurements") / PurePosixPath(relative)
            arcname = rel.as_posix()
            if arcname in seen:
                raise PackageError(f"duplicate_archive_member:{arcname}")
            seen.add(arcname)
            expected = row[hash_field]
            if not isinstance(expected, str) or _sha256(path) != expected:
                raise PackageError(f"manifest_hash_mismatch:{day}:{field}")
            files.append((path, arcname))

    members: set[str] = set()
    try:
        with partial.open("xb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz") as archive:
                for path, arcname in files:
                    _add_member(archive, path, arcname, members)
        os.link(partial, output)
        partial.unlink()
    except Exception:
        # Preserve the partial for explicit inspection/recovery.
        raise
    result = {"status": "COMPLETE", "output_file": os.fspath(output),
              "sha256": _sha256(output), "bytes": output.stat().st_size,
              "calendar_days": len(manifest_dates), "archive_members": len(members)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--output-file", required=True)
    args = parser.parse_args()
    package_pfvv_prepared_outputs(args.run_root, args.output_file)


if __name__ == "__main__":
    main()
