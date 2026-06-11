#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="factorforge_step3_template_isolation_"))
    report_id = "STEP3_TEMPLATE_ISOLATION_SMOKE"
    manifest_path = root / "runtime_manifest.json"
    manifest = {
        "contract_version": "factorforge_runtime_context_v1",
        "report_id": report_id,
        "factorforge_root": str(root),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    env = os.environ.copy()
    env["FACTORFORGE_ULTIMATE_RUN"] = "1"
    env.pop("FACTORFORGE_STEP3_TEMPLATE_COPY", None)
    copy_path = root / "runs" / report_id / "step3_runtime" / f"run_step3__{report_id}.py"
    meta_path = copy_path.with_suffix(".meta.json")
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "skills" / "factor-forge-step3" / "scripts" / "run_step3.py"),
            "--manifest",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    ok = (
        copy_path.exists()
        and meta.get("version") == "factorforge_step3_template_copy_v1"
        and meta.get("report_id") == report_id
        and meta.get("policy") == "canonical_run_step3_py_is_template_only"
        and "run_step3.py" in str(meta.get("source_template_path"))
    )
    payload = {
        "verdict": "ACCEPT" if ok else "BLOCK",
        "copy_path": str(copy_path),
        "meta_path": str(meta_path),
        "subprocess_rc": proc.returncode,
        "stderr_tail": proc.stderr[-800:],
        "stdout_tail": proc.stdout[-800:],
        "copy_exists": copy_path.exists(),
        "meta": meta,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
