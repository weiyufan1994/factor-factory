"""Optional local advisory storage, separate from code and research roots."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

INDEX_RELATIVE_PATH = Path("knowledge/retrieval/factorforge_retrieval_index.jsonl")


def configured_advisory_root(environ: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    # This opt-in is for ordinary local research/inspection only. Hosted and
    # closed child execution continue to use their existing bound roots.
    if (env.get("FACTORFORGE_ULTIMATE_RUN") == "1"
            and env.get("FACTORFORGE_LOCAL_IS_ONLY") != "1"):
        return None
    if any(value and key.startswith(("FACTORFORGE_OOS_HOST_", "FACTORFORGE_EVO_CHILD_CONTAINER_"))
           for key, value in env.items()):
        return None
    raw = env.get("FACTORFORGE_ADVISORY_ROOT")
    return Path(raw).expanduser() if raw else None


def source_snapshot(root: Path, selectors: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Hash the small knowledge source directories, including retired versions.

    Checking the complete selected filenames also detects a newly added
    withdrawal before an index rebuild succeeds. No factor/data files are read.
    """
    root = Path(root).resolve(strict=True)
    result = []
    for selector in selectors:
        relative, pattern = selector["directory"], selector["pattern"]
        directory = root / relative
        if Path(relative).is_absolute() or not directory.resolve().is_relative_to(root):
            raise ValueError("advisory_source_outside_root")
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError("advisory source directory must not be a symlink and must be a directory")
        if "/" in pattern or "\\" in pattern:
            raise ValueError("invalid_advisory_source_pattern")
        files = {}
        for path in sorted(directory.glob(pattern)):
            if path.is_symlink() or not path.is_file():
                raise ValueError("advisory source must not be a symlink and must be a regular file")
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append({"directory": relative, "pattern": pattern, "files": files})
    return result


def read_visible_experience(index: Path) -> tuple[list[dict[str, Any]], str]:
    """Read one version-bound index or fail the whole experience lane closed."""
    index = Path(index)
    manifest = index.with_name("factorforge_retrieval_manifest.json")
    if index.parent.is_symlink() or index.parent.parent.is_symlink():
        raise ValueError("unsafe_advisory_index_directory")
    if not index.is_file() or index.is_symlink() or not manifest.is_file() or manifest.is_symlink():
        raise ValueError("advisory_index_or_manifest_missing_or_unsafe")
    raw = index.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    metadata = json.loads(manifest.read_bytes())
    if index.parent.name == 'retrieval' and index.parent.parent.name == 'knowledge':
        if (index.parents[2].is_symlink()
                or Path(metadata['source_root']).resolve() != index.parents[2].resolve()):
            raise ValueError('advisory_index_source_root_mismatch')
    if metadata.get("index_sha256") != digest:
        raise ValueError("advisory_index_version_mismatch")
    snapshot = metadata.get("source_snapshot")
    if not isinstance(snapshot, list) or not snapshot:
        raise ValueError("advisory_source_version_missing")
    if source_snapshot(Path(metadata["source_root"]), snapshot) != snapshot:
        raise ValueError("advisory_source_version_changed")
    from factor_factory.knowledge_reference import project_knowledge_case
    rows, seen = [], set()
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"] or row["id"] in seen
                or not isinstance(row.get("advisory_projection", {}), dict)):
            raise ValueError("invalid_advisory_document")
        if row.get("validity_status") == "withdrawn":
            raise ValueError("withdrawn_document_in_active_index")
        project_knowledge_case(row)
        seen.add(row["id"])
        rows.append(row)
    return rows, digest


def carried_reference_is_current(contract: Mapping[str, Any], index: Path) -> bool:
    try:
        _, digest = read_visible_experience(index)
        return (contract.get("experience_index_sha256") == digest
                and contract.get("index_paths_checked") == [str(index)])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
