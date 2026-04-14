"""Validation utilities for FactorForge Step 5."""

from pathlib import Path
from typing import List, Any


PLACEHOLDER_TOKENS = {
    "[TODO]",
    "[PLACEHOLDER]",
    "[TBD]",
    "[NOT SET]",
    "TODO",
    "PLACEHOLDER",
    "TBD",
    "NOT SET",
    "",
    "shell created",
    "implement real",
    "re-run step 5 after real run outputs exist",
}


def check_file_exists(path: Path | str) -> dict:
    """Check whether a file exists."""
    p = Path(path)
    return {
        "path": str(p.resolve()),
        "exists": p.is_file(),
        "type": "file" if p.is_file() else ("dir" if p.is_dir() else "missing"),
    }


def check_archive_dir_nonempty(path: Path | str) -> dict:
    """Check whether an archive directory contains at least one file."""
    p = Path(path)
    if not p.is_dir():
        return {
            "path": str(p.resolve()),
            "nonempty": False,
            "file_count": 0,
        }
    files = list(p.rglob("*"))
    regular_files = [f for f in files if f.is_file()]
    return {
        "path": str(p.resolve()),
        "nonempty": len(regular_files) > 0,
        "file_count": len(regular_files),
    }


def check_final_status_enum(value: Any) -> dict:
    """Validate that a value is one of the recognised Step 5 final-status strings."""
    valid_values = {"validated", "partial", "failed"}
    v = str(value).strip().lower()
    if v in valid_values:
        return {"value": v, "valid": True, "reason": ""}
    return {
        "value": v,
        "valid": False,
        "reason": f"'{v}' is not one of {sorted(valid_values)}",
    }


def check_archive_paths_exist(paths: List[Path | str]) -> dict:
    """Check that all listed paths exist (file or directory)."""
    missing = []
    for p in paths:
        if not Path(p).exists():
            missing.append(str(p))
    return {
        "total": len(paths),
        "missing": missing,
        "all_exist": len(missing) == 0,
    }


def check_no_placeholder_text(items: List[Any]) -> dict:
    """Check that strings in ``items`` do not contain placeholder text."""
    placeholders = []
    for item in items:
        s = str(item).strip()
        if s.lower() in PLACEHOLDER_TOKENS:
            placeholders.append(s)
    return {
        "total": len(items),
        "placeholders": placeholders,
        "clean": len(placeholders) == 0,
    }
