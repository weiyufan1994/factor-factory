from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.factorforge_run_registry import assert_formal_run_root_allowed

REGISTRY_VERSION = "factorforge_active_run_registry_v2"
PROOF_LEDGER_VERSION = "factorforge_proof_ledger_v2"

BLOCK_ACTIVE_RUN_NOT_FOUND = "BLOCK_ACTIVE_RUN_NOT_FOUND"
BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH = "BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH"
BLOCK_PROOF_LEDGER_WRITE_FAILED = "BLOCK_PROOF_LEDGER_WRITE_FAILED"


class FactorForgeBlock(Exception):
    def __init__(self, token: str, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.token = token
        self.payload = payload or {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def current_repo_sha() -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root(), text=True, capture_output=True, check=True)
    return proc.stdout.strip()


def default_registry_path() -> Path:
    return Path(os.getenv("FACTORFORGE_ACTIVE_RUN_REGISTRY", "/var/lib/factorforge/registry/active_run_registry.json")).expanduser()


def resolve_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_active_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"registry_version": REGISTRY_VERSION, "updated_at_utc": utc_now(), "active_runs": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FactorForgeBlock(BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH, f"registry is not a JSON object: {path}")
    payload.setdefault("registry_version", REGISTRY_VERSION)
    payload.setdefault("active_runs", {})
    if not isinstance(payload["active_runs"], dict):
        raise FactorForgeBlock(BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH, f"registry active_runs is not an object: {path}")
    return payload


def write_active_registry(path: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload["registry_version"] = REGISTRY_VERSION
    payload["updated_at_utc"] = utc_now()
    payload.setdefault("active_runs", {})
    write_json_atomic(path, payload)


def active_run_for_report(registry: dict[str, Any], report_id: str) -> dict[str, Any]:
    run = (registry.get("active_runs") or {}).get(report_id)
    if not isinstance(run, dict):
        raise FactorForgeBlock(
            BLOCK_ACTIVE_RUN_NOT_FOUND,
            f"no active run registered for report_id={report_id}",
            payload={"report_id": report_id},
        )
    if run.get("report_id") != report_id:
        raise FactorForgeBlock(
            BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH,
            f"active run report_id mismatch: expected={report_id} actual={run.get('report_id')}",
            payload={"report_id": report_id, "actual_report_id": run.get("report_id")},
        )
    return run


def assert_active_identity(
    run: dict[str, Any],
    *,
    report_id: str,
    artifact_root: Path | None = None,
    repo_sha: str | None = None,
) -> None:
    if run.get("report_id") != report_id:
        raise FactorForgeBlock(
            BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH,
            f"run report_id mismatch: expected={report_id} actual={run.get('report_id')}",
        )
    root_value = run.get("artifact_root")
    if not isinstance(root_value, str) or not root_value.strip():
        raise FactorForgeBlock(BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH, "active run artifact_root missing")
    registry_root = resolve_path(root_value)
    assert_formal_run_root_allowed(registry_root)
    if artifact_root is not None and resolve_path(artifact_root) != registry_root:
        raise FactorForgeBlock(
            BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH,
            f"artifact_root mismatch: registry={registry_root} requested={resolve_path(artifact_root)}",
            payload={"registry_artifact_root": str(registry_root), "requested_artifact_root": str(resolve_path(artifact_root))},
        )
    if repo_sha is not None and run.get("repo_sha") and run.get("repo_sha") != repo_sha:
        raise FactorForgeBlock(
            BLOCK_ACTIVE_RUN_IDENTITY_MISMATCH,
            f"repo_sha mismatch: registry={run.get('repo_sha')} requested={repo_sha}",
            payload={"registry_repo_sha": run.get("repo_sha"), "requested_repo_sha": repo_sha},
        )


def proof_ledger_path(artifact_root: Path, report_id: str) -> Path:
    return resolve_path(artifact_root) / "objects" / "proof" / f"proof_ledger__{report_id}.json"


def write_proof_ledger(artifact_root: Path, report_id: str, payload: dict[str, Any]) -> Path:
    try:
        assert_formal_run_root_allowed(artifact_root)
        out = proof_ledger_path(artifact_root, report_id)
        ledger = {
            "proof_ledger_version": PROOF_LEDGER_VERSION,
            "report_id": report_id,
            "artifact_root": str(resolve_path(artifact_root)),
            "created_at_utc": utc_now(),
        }
        ledger.update(payload)
        write_json_atomic(out, ledger)
        return out
    except FactorForgeBlock:
        raise
    except Exception as exc:  # pragma: no cover - defensive wrapper for CLI block output.
        raise FactorForgeBlock(BLOCK_PROOF_LEDGER_WRITE_FAILED, str(exc)) from exc


def block_payload(token: str, message: str, *, report_id: str | None = None, **extra: Any) -> dict[str, Any]:
    payload = {
        "status": "BLOCK",
        "block_token": token,
        "reason": message,
        "created_at_utc": utc_now(),
    }
    if report_id:
        payload["report_id"] = report_id
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def pass_payload(*, report_id: str, run: dict[str, Any], command: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "status": "PASS",
        "command": command,
        "report_id": report_id,
        "run_id": run.get("run_id"),
        "artifact_root": run.get("artifact_root"),
        "repo_sha": run.get("repo_sha"),
        "created_at_utc": utc_now(),
    }
    payload.update(extra)
    return payload
