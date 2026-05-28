#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

BLOCK_RUN_MANIFEST = "BLOCK_RUN_MANIFEST_MISMATCH"
MANIFEST_ENV = "FACTORFORGE_FORMAL_RUN_MANIFEST"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_repo_sha() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def _resolve_manifest_path(raw: str | None) -> Path:
    value = raw or os.getenv(MANIFEST_ENV)
    if not value:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: {MANIFEST_ENV} or --run-manifest is required for formal command bridge runs")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    if not path.exists():
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest not found: {path}")
    return path


def load_required_manifest(raw: str | None = None) -> tuple[Path, dict[str, Any]]:
    path = _resolve_manifest_path(raw)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest JSON invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest root must be an object: {path}")
    return path, payload


def _manifest_value(manifest: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in manifest:
            return manifest.get(key)
    return None


def _manifest_root(manifest: dict[str, Any]) -> Path:
    value = _manifest_value(manifest, "factorforge_root", "artifact_root")
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest factorforge_root/artifact_root is required")
    return Path(value).expanduser().resolve()


def _manifest_step(manifest: dict[str, Any], step: str) -> dict[str, Any]:
    steps = manifest.get("steps")
    if isinstance(steps, dict) and isinstance(steps.get(step), dict):
        return steps[step]
    return {}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _matches(expected: str, actual: str) -> bool:
    return expected.lower() == actual.lower()


def _root_report_ids(root: Path) -> list[str]:
    objects = root / "objects"
    if not objects.exists():
        return []
    found: set[str] = set()
    raw_root = objects / "raw_llm"
    if raw_root.exists():
        for child in raw_root.iterdir():
            if child.is_dir() and child.name:
                found.add(child.name)
    for subdir in ["alpha_idea_master", "factor_spec_master", "data_prep_master", "runtime_context"]:
        base = objects / subdir
        if not base.exists():
            continue
        for path in base.glob("*.json"):
            name = path.stem
            if "__" in name:
                found.add(name.rsplit("__", 1)[-1])
    return sorted(found)


def validate_manifest(
    manifest: dict[str, Any],
    *,
    report_id: str,
    factorforge_root: Path | None = None,
    report_pdf: Path | None = None,
    step: str | None = None,
    provider_request: dict[str, Any] | None = None,
    expected_out_dir: Path | None = None,
) -> None:
    manifest_report_id = _normalize(_manifest_value(manifest, "report_id"))
    if not manifest_report_id:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest report_id is required")
    if manifest_report_id != report_id:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: report_id expected={report_id} manifest={manifest_report_id}")

    manifest_root = _manifest_root(manifest)
    if factorforge_root is not None and manifest_root != factorforge_root.resolve():
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: factorforge_root expected={factorforge_root.resolve()} manifest={manifest_root}")

    if expected_out_dir is not None and step is not None:
        expected = manifest_root / "objects" / "raw_llm" / report_id / step
        if expected_out_dir.resolve() != expected.resolve():
            raise SystemExit(f"{BLOCK_RUN_MANIFEST}: {step} out_dir expected={expected.resolve()} actual={expected_out_dir.resolve()}")

    current_sha = current_repo_sha()
    manifest_sha = _normalize(_manifest_value(manifest, "repo_sha", "git_sha", "production_repo_sha"))
    if not manifest_sha:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest repo_sha is required")
    if manifest_sha != current_sha:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: repo_sha expected={current_sha} manifest={manifest_sha}")

    if report_pdf is not None:
        manifest_pdf_sha = _normalize(_manifest_value(manifest, "report_pdf_sha256", "pdf_sha256"))
        if not manifest_pdf_sha:
            raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest report_pdf_sha256/pdf_sha256 is required")
        actual_pdf_sha = sha256_file(report_pdf)
        if manifest_pdf_sha != actual_pdf_sha:
            raise SystemExit(f"{BLOCK_RUN_MANIFEST}: report_pdf_sha256 expected={actual_pdf_sha} manifest={manifest_pdf_sha}")

    if step and provider_request is not None:
        step_manifest = _manifest_step(manifest, step)
        manifest_provider = _normalize(step_manifest.get("provider") or manifest.get(f"{step}_provider"))
        manifest_model = _normalize(step_manifest.get("model") or manifest.get(f"{step}_model"))
        provider = _normalize(provider_request.get("provider"))
        model = _normalize(provider_request.get("model"))
        if not manifest_provider or not manifest_model:
            raise SystemExit(f"{BLOCK_RUN_MANIFEST}: manifest {step}.provider and {step}.model are required")
        if not _matches(manifest_provider, provider):
            raise SystemExit(f"{BLOCK_RUN_MANIFEST}: {step} provider expected={provider or 'NOT_SET'} manifest={manifest_provider}")
        if not _matches(manifest_model, model):
            raise SystemExit(f"{BLOCK_RUN_MANIFEST}: {step} model expected={model or 'NOT_SET'} manifest={manifest_model}")

    existing_report_ids = [rid for rid in _root_report_ids(manifest_root) if rid != report_id]
    if existing_report_ids:
        raise SystemExit(f"{BLOCK_RUN_MANIFEST}: factorforge_root contains other report_ids={existing_report_ids[:10]}")

