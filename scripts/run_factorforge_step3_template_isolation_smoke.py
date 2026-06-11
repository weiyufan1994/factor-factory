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
    checks = {}
    for script_name, version, policy in [
        ("run_step3.py", "factorforge_step3_template_copy_v1", "canonical_run_step3_py_is_template_only"),
        ("run_step3b.py", "factorforge_step3b_template_copy_v1", "canonical_run_step3b_py_is_template_only"),
    ]:
        copy_name = script_name.replace(".py", f"__{report_id}.py")
        copy_path = root / "runs" / report_id / "step3_runtime" / copy_name
        meta_path = copy_path.with_suffix(".meta.json")
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "skills" / "factor-forge-step3" / "scripts" / script_name),
                "--manifest",
                str(manifest_path),
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        checks[script_name] = {
            "ok": bool(
                copy_path.exists()
                and meta.get("version") == version
                and meta.get("report_id") == report_id
                and meta.get("policy") == policy
                and script_name in str(meta.get("source_template_path"))
            ),
            "copy_exists": copy_path.exists(),
            "copy_path": str(copy_path),
            "meta_path": str(meta_path),
            "subprocess_rc": proc.returncode,
            "stderr_tail": proc.stderr[-800:],
            "stdout_tail": proc.stdout[-800:],
            "meta": meta,
        }
    ok = all(item["ok"] for item in checks.values())
    payload = {
        "verdict": "ACCEPT" if ok else "BLOCK",
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
