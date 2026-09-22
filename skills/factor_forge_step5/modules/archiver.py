"""Archival utilities for FactorForge Step 5."""

import shutil
from pathlib import Path
from typing import List, Tuple


def _resolve_factorforge_root(root: Path) -> Path:
    if (root / "objects").exists():
        return root
    return root / "factorforge"


def init_archive_dir(report_id: str, workspace_root: Path | str) -> Path:
    """Initialise the canonical archive directory for a given report.

    Args:
        report_id: The report identifier, used as the directory name.
        workspace_root: Workspace root. Archive is created at
            ``factorforge/archive/<report_id>`` under this root.

    Returns:
        Path to the created archive directory.
    """
    root = _resolve_factorforge_root(Path(workspace_root))
    archive_dir = root / "archive" / report_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


def copy_file_if_exists(src: Path | str, dst: Path | str) -> bool:
    """Copy a file from src to dst if src exists.

    Args:
        src: Source file path.
        dst: Destination file path.

    Returns:
        True if the file was copied, False if src does not exist.
    """
    src_p = Path(src)
    dst_p = Path(dst)
    if not src_p.exists() or not src_p.is_file():
        return False
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_p, dst_p)
    return True


def copy_many_preserve_existing(
    candidates: List[Tuple[Path | str, Path | str]]
) -> List[str]:
    """Copy multiple files, skipping any where the destination already exists.

    Args:
        candidates: List of ``(src, dst)`` path pairs.

    Returns:
        List of dst paths that were actually copied.
    """
    copied = []
    for src, dst in candidates:
        dst_p = Path(dst)
        if dst_p.exists():
            continue
        if copy_file_if_exists(src, dst):
            copied.append(str(dst_p))
    return copied


def normalize_archive_subdirs(base_dir: Path | str) -> dict:
    """Ensure Step 5 standard subdirectory structure exists under base_dir.

    Creates the following subdirs if missing:
        - runs/
        - evaluations/
        - objects/

    Args:
        base_dir: Base directory under which subdirs are created.

    Returns:
        A dict mapping subdir name to its absolute Path.
    """
    base = Path(base_dir)
    subdirs = ["runs", "evaluations", "objects"]
    result = {}
    for name in subdirs:
        p = base / name
        p.mkdir(parents=True, exist_ok=True)
        result[name] = p
    return result
