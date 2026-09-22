"""I/O utilities for FactorForge Step 5."""

import json
from pathlib import Path
from typing import Any


def load_json(path: Path | str) -> dict | list:
    """Load a JSON file and return its parsed content.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON content as dict or list.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path | str, data: dict | list) -> None:
    """Write data to a JSON file with UTF-8 encoding.

    Args:
        path: Destination file path.
        data: Data to serialise (dict or list).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_dir(path: Path | str) -> None:
    """Ensure a directory exists, creating it and all parents if necessary.

    Args:
        path: Path to the directory.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)