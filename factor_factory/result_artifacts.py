"""One result-file convention for producers, Step4/5 and continuation.

``artifacts`` names concrete files; ``artifact_directories`` is location-only
metadata. Directories are never expanded implicitly. Relative references need
an explicit base. Existing file-only payloads and explicit nulls remain valid.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from factor_factory.runtime_context import FactorForgeContext


class ResultArtifactError(ValueError):
    pass


def resolve_result_path(value: str, base_dir: str | Path | None = None) -> Path:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ResultArtifactError('RESULT_ARTIFACT_PATH_REQUIRED: nonempty unpadded path string')
    base = Path(base_dir).expanduser() if base_dir is not None else None
    if base is not None and not base.is_absolute():
        raise ResultArtifactError('RESULT_ARTIFACT_ABSOLUTE_BASE_REQUIRED')
    path = Path(value).expanduser()
    if not path.is_absolute():
        if base_dir is None:
            raise ResultArtifactError(f'RESULT_ARTIFACT_BASE_REQUIRED:{value}')
        path = base / path
    return path.resolve()


def result_artifact_paths(payload: Mapping[str, Any], *, base_dir: str | Path | None = None,
                          check_paths: bool = True) -> dict[str, Path]:
    """Validate both collections; return only explicitly declared concrete files."""
    if not isinstance(payload, dict):
        raise ResultArtifactError('RESULT_PAYLOAD_OBJECT_REQUIRED')
    files: dict[str, Path] = {}
    for field, want_directory in (('artifacts', False), ('artifact_directories', True)):
        values = payload.get(field)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise ResultArtifactError(f'{field} must be a JSON object')
        for role, raw in values.items():
            if not isinstance(role, str) or not role.strip() or role != role.strip():
                raise ResultArtifactError(f'{field} requires nonempty role names')
            if raw is None and not want_directory:
                continue  # Explicitly unavailable optional file, not a directory.
            path = resolve_result_path(raw, base_dir)
            if check_paths:
                if not path.exists():
                    raise ResultArtifactError(f'ARTIFACT_MISSING:{path}')
                if want_directory and not path.is_dir():
                    raise ResultArtifactError(f'ARTIFACT_DIRECTORY_REQUIRED:{path}')
                if not want_directory and not path.is_file():
                    raise ResultArtifactError(f'ARTIFACT_FILE_REQUIRED:{path}; declare concrete files, not a directory tree')
            if not want_directory:
                files[role] = path
    return files


def validate_result_artifacts(payload: Any, *, base_dir: str | Path | None = None,
                              check_paths: bool = True) -> list[str]:
    try:
        result_artifact_paths(payload, base_dir=base_dir, check_paths=check_paths)
    except (OSError, ValueError, TypeError) as exc:
        return [str(exc)]
    return []


def build_result_artifacts(*, files: Mapping[str, str | Path | None],
                           directories: Mapping[str, str | Path] | None = None,
                           base_dir: str | Path | None = None,
                           check_paths: bool = True) -> dict:
    """Producer entry: explicitly separate roles; never infer them from names."""
    if not isinstance(files, Mapping) or (directories is not None and not isinstance(directories, Mapping)):
        raise ResultArtifactError('RESULT_ARTIFACT_MAPPINGS_REQUIRED')
    for path in (*files.values(), *(directories or {}).values()):
        if path is not None and not isinstance(path, (str, Path)):
            raise ResultArtifactError('RESULT_ARTIFACT_PATH_REQUIRED: string or Path')
    if any(path is None for path in (directories or {}).values()):
        raise ResultArtifactError('RESULT_ARTIFACT_DIRECTORY_PATH_REQUIRED')
    fields = {'artifacts': {role: None if path is None else str(resolve_result_path(str(path), base_dir))
                            for role, path in files.items()}}
    if directories is not None:
        fields['artifact_directories'] = {role: str(resolve_result_path(str(path), base_dir))
                                          for role, path in directories.items()}
    result_artifact_paths(fields, check_paths=check_paths)
    return fields


def write_result_payload(path: str | Path, payload: dict, *, base_dir: str | Path | None = None) -> None:
    """Validate real file references before the producer publishes its payload."""
    from factor_factory.runtime_context import write_json_atomic
    result_artifact_paths(payload, base_dir=base_dir)
    write_json_atomic(resolve_result_path(str(path), base_dir), payload)


def prepare_result_paths(context: FactorForgeContext, report_id: str, backend: str, *,
                         files: Mapping[str, str | Path],
                         directories: Mapping[str, str | Path] | None = None) -> dict:
    """Allocate explicit backend output paths in the existing workspace layout.

    This creates parent directories only, never moves or overwrites a result.
    The producer writes its files, then calls build_result_artifacts/write_result_payload.
    Input/source locations and factor runs remain owned by the existing context.
    """
    from factor_factory.research_workspace import assert_path_under_workspace
    for name in (report_id, backend):
        if (not isinstance(name, str) or not name.strip() or name != name.strip()
                or name in {'.', '..'} or any(c in name for c in ('/', '\\', '\x00'))):
            raise ResultArtifactError('RESULT_OUTPUT_ID_INVALID')
    base = resolve_result_path(str(context.active_root))
    payload_path = context.evaluation_payload_path(report_id, backend).resolve()
    assert_path_under_workspace(payload_path, base, label='backend payload')
    root = payload_path.parent
    refs = build_result_artifacts(files=files, directories=directories, base_dir=root, check_paths=False)
    # Validate the entire allocation before creating anything.
    file_paths = [Path(raw) for raw in refs['artifacts'].values() if raw is not None]
    dir_paths = [Path(raw) for raw in refs.get('artifact_directories', {}).values()]
    if any(other != path and other.is_relative_to(path) for path in file_paths for other in file_paths) or any(
            directory.is_relative_to(path) for path in [*file_paths, payload_path] for directory in dir_paths):
        raise ResultArtifactError('RESULT_OUTPUT_FILE_DIRECTORY_CONFLICT')
    for field, values in refs.items():
        for path in values.values():
            if path is None:
                raise ResultArtifactError('RESULT_OUTPUT_FILENAME_REQUIRED')
            target = Path(path)
            assert_path_under_workspace(target, root, label=field)
            if any(parent.exists() and not parent.is_dir() for parent in target.parents):
                raise ResultArtifactError(f'RESULT_OUTPUT_PARENT_IS_FILE:{target}')
            if field == 'artifacts' and (target == payload_path or target == root or target.is_dir()):
                raise ResultArtifactError(f'RESULT_OUTPUT_FILE_CONFLICT:{target}')
            if field == 'artifact_directories' and target.exists() and not target.is_dir():
                raise ResultArtifactError(f'ARTIFACT_DIRECTORY_REQUIRED:{target}')
    root.mkdir(parents=True, exist_ok=True)
    for field, values in refs.items():
        for path in values.values():
            (Path(path) if field == 'artifact_directories' else Path(path).parent).mkdir(parents=True, exist_ok=True)
    return {'payload_path': str(payload_path), **refs}


def repair_result_references(original: dict, repair: dict, *, base_dir: str | Path) -> dict:
    """Pure metadata projection for the journal's explicitly evidenced recovery.

    The manager checks original hashes/times and preserves bytes before writing.
    No caller-supplied metrics, status, identities or file-role renames accepted.
    """
    if set(repair) != {'path', 'sha256', 'artifacts', 'artifact_directories'}:
        raise ResultArtifactError('REFERENCE_REPAIR_FIELDS_INVALID')
    old_files = original.get('artifacts') or {}
    if not isinstance(old_files, dict):
        raise ResultArtifactError('REFERENCE_REPAIR_REQUIRES_EXISTING_ARTIFACTS')
    legacy_dirs = {role: raw for role, raw in old_files.items()
                   if isinstance(raw, str) and resolve_result_path(raw, base_dir).is_dir()}
    if not legacy_dirs:
        raise ResultArtifactError('REFERENCE_REPAIR_REQUIRES_MISDECLARED_DIRECTORY')
    old_dirs = original.get('artifact_directories') or {}
    if not isinstance(old_dirs, dict) or any(role in old_dirs and old_dirs[role] != raw for role, raw in legacy_dirs.items()):
        raise ResultArtifactError('REFERENCE_REPAIR_DIRECTORY_METADATA_CONFLICT')
    required_dirs = {**old_dirs, **legacy_dirs}
    if repair['artifact_directories'] != required_dirs:
        raise ResultArtifactError('REFERENCE_REPAIR_DIRECTORY_METADATA_CHANGED')
    new_files = repair['artifacts']
    if not isinstance(new_files, dict):
        raise ResultArtifactError('REFERENCE_REPAIR_FILES_REQUIRED')
    for role, raw in old_files.items():
        if role not in legacy_dirs and (role not in new_files or new_files[role] != raw):
            raise ResultArtifactError(f'REFERENCE_REPAIR_EXISTING_FILE_CHANGED:{role}')
    if set(legacy_dirs) & set(new_files):
        raise ResultArtifactError('REFERENCE_REPAIR_DIRECTORY_STILL_IN_FILES')
    roots = [resolve_result_path(raw, base_dir) for raw in legacy_dirs.values()]
    added = {role: resolve_result_path(raw, base_dir) for role, raw in new_files.items() if role not in old_files}
    if any(not any(path.is_relative_to(root) for root in roots) for path in added.values()):
        raise ResultArtifactError('REFERENCE_REPAIR_NEW_FILE_OUTSIDE_ORIGINAL_DIRECTORIES')
    for root in roots:
        if not any(path.is_relative_to(root) for path in added.values()):
            raise ResultArtifactError(f'REFERENCE_REPAIR_EXPLICIT_DIRECTORY_FILES_REQUIRED:{root}')
    corrected = {**original, 'artifacts': dict(new_files), 'artifact_directories': dict(required_dirs)}
    result_artifact_paths(corrected, base_dir=base_dir)
    # Only these two reference fields may differ, including nested metric values.
    without_refs = lambda obj: json.dumps({k: v for k, v in obj.items()
        if k not in {'artifacts', 'artifact_directories'}}, sort_keys=True, ensure_ascii=False)
    if without_refs(original) != without_refs(corrected):
        raise ResultArtifactError('REFERENCE_REPAIR_NON_REFERENCE_CHANGE')
    return corrected
