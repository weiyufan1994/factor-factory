from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from factor_factory.runtime_context import load_runtime_manifest, manifest_factorforge_root, manifest_report_id


def safe_report_id(report_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(report_id)).strip("_") or "unknown_report"


def runtime_copy_path(factorforge_root: Path, report_id: str, *, script_stem: str) -> Path:
    safe_id = safe_report_id(report_id)
    return factorforge_root / "runs" / safe_id / "step3_runtime" / f"{script_stem}__{safe_id}.py"


def maybe_reexec_from_template_copy(
    *,
    script_stem: str,
    report_id: str | None,
    manifest_path: str | None,
    default_factorforge_root: Path,
    source_path: Path,
    copy_env: str,
    copy_version: str,
    policy: str,
    template_path_env: str,
    runtime_copy_path_env: str,
    allow_canonical_env: str = "FACTORFORGE_ALLOW_CANONICAL_STEP3_TEMPLATE_EXECUTION",
) -> None:
    """Run a formal Step3 runner from a per-report copy.

    The canonical runner remains a template. Formal runs copy it into the
    report-local runtime directory, write a metadata record, set identity env
    vars, and re-exec the copy.
    """
    if os.getenv(copy_env) == "1":
        return
    if os.getenv(allow_canonical_env) == "1":
        return

    manifest = load_runtime_manifest(manifest_path) if manifest_path else None
    resolved_report_id = report_id or (manifest_report_id(manifest) if manifest else None)
    if not resolved_report_id:
        return

    factorforge_root = manifest_factorforge_root(manifest) if manifest else default_factorforge_root
    source = source_path.resolve()
    target = runtime_copy_path(factorforge_root, resolved_report_id, script_stem=script_stem)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    meta = {
        "version": copy_version,
        "report_id": resolved_report_id,
        "source_template_path": str(source),
        "runtime_copy_path": str(target),
        "source_template_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "policy": policy,
    }
    target.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    os.environ[copy_env] = "1"
    os.environ["FACTORFORGE_REPO_ROOT"] = str(source.parents[3])
    os.environ[template_path_env] = str(source)
    os.environ[runtime_copy_path_env] = str(target)
    os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
