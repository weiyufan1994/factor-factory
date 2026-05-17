from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from factor_factory.runtime_context import utc_now


PROOF_VERSION = "factorforge_ultimate_loop_proof_v1"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except Exception:
        return {}


def tail(text: str, limit: int = 12000) -> str:
    return text[-limit:] if len(text) > limit else text


def should_skip_digest_path(path: Path) -> bool:
    name = path.name
    return (
        name == "__pycache__"
        or name == ".DS_Store"
        or name.endswith(".lock")
        or name.endswith(".tmp")
        or name.endswith(".swp")
        or name.endswith(".swx")
        or name.startswith(".#")
        or name.startswith("~$")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_dir():
        return None
    entries: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*"), key=lambda p: p.relative_to(path).as_posix()):
        rel = item.relative_to(path)
        if any(should_skip_digest_path(part) for part in rel.parents):
            continue
        if should_skip_digest_path(item):
            continue
        if not item.is_file():
            continue
        stat = item.stat()
        entries.append(
            {
                "relative_path": rel.as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(item),
            }
        )
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def path_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "kind": None, "sha256": None, "digest": None}
    if path.is_file():
        return {"path": str(path), "exists": True, "kind": "file", "sha256": sha256_file(path), "digest": None}
    if path.is_dir():
        return {"path": str(path), "exists": True, "kind": "directory", "sha256": None, "digest": directory_digest(path)}
    return {"path": str(path), "exists": True, "kind": "other", "sha256": None, "digest": None}


def snapshots_differ(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = ("exists", "kind", "sha256", "digest")
    return any(left.get(key) != right.get(key) for key in keys)


def make_initial_proof(
    *,
    root_report_id: str,
    factorforge_root: Path,
    max_loops: int,
    args: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": PROOF_VERSION,
        "created_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "status": "RUNNING",
        "final_outcome": None,
        "root_report_id": root_report_id,
        "factorforge_root": str(factorforge_root),
        "max_loops": max_loops,
        "args": args,
        "iterations": [],
        "stop_reason": None,
        "canonical_side_effects": [],
        "notes": [],
    }


def append_note(proof: dict[str, Any], note: str) -> None:
    proof.setdefault("notes", []).append({"created_at_utc": utc_now(), "note": note})
    proof["updated_at_utc"] = utc_now()
