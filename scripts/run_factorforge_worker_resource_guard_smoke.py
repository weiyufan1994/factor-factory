#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN_NON_TMP_ROOT = "BLOCK_NON_TMP_WORKER_RESOURCE_GUARD_SMOKE_ROOT"


def is_tmp(path: Path) -> bool:
    raw = str(path)
    resolved = str(path.resolve(strict=False))
    return raw.startswith("/tmp/") or resolved.startswith("/tmp/") or resolved.startswith("/private/tmp/")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_guard(root: Path, snapshot: str, *, max_cpu: float = 90.0, max_mem: float = 80.0) -> dict[str, Any]:
    ps_path = root / "ps_snapshot.txt"
    report_path = root / "worker_resource_guard_report.json"
    write_text(ps_path, snapshot)
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/check_factorforge_worker_resource_guard.py",
            "--ps-snapshot",
            str(ps_path),
            "--report-path",
            str(report_path),
            "--max-cpu",
            str(max_cpu),
            "--max-mem",
            str(max_mem),
        ],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return {
        "rc": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
        "report": report,
    }


def case_busy_data_backfill_blocks(root: Path) -> dict[str, Any]:
    result = run_guard(
        root,
        """
PID    PPID %CPU %MEM COMMAND
111    1    104.0 38.8 python3 scripts/build_clean_daily_layer.py --append
222    1    1.0   0.2  python3 harmless.py
""".strip(),
    )
    text = result["stdout_tail"] + result["stderr_tail"] + json.dumps(result["report"], ensure_ascii=False)
    token = "BLOCK_FACTORFORGE_WORKER_RESOURCE_BUSY"
    busy = result["report"].get("busy_processes") if isinstance(result["report"].get("busy_processes"), list) else []
    return {
        "case": "worker_resource_busy_data_backfill_blocks",
        "ok": result["rc"] == 1 and token in text and bool(busy) and "build_clean_daily_layer.py" in text,
        "token_present": token in text,
        "result": result,
    }


def case_busy_factorforge_process_blocks(root: Path) -> dict[str, Any]:
    result = run_guard(
        root,
        """
PID    PPID %CPU %MEM COMMAND
333    1    12.0  10.0 python3 skills/factor-forge-step4/scripts/run_step4.py --report-id EXISTING
""".strip(),
    )
    text = result["stdout_tail"] + result["stderr_tail"] + json.dumps(result["report"], ensure_ascii=False)
    token = "BLOCK_FACTORFORGE_WORKER_RESOURCE_BUSY"
    return {
        "case": "worker_resource_busy_factorforge_process_blocks",
        "ok": result["rc"] == 1 and token in text and "run_step4.py" in text,
        "token_present": token in text,
        "result": result,
    }


def case_idle_worker_passes(root: Path) -> dict[str, Any]:
    result = run_guard(
        root,
        """
PID    PPID %CPU %MEM COMMAND
444    1    2.0  0.5 /usr/bin/python3 scripts/auto_s3_report_intake.py --once
555    1    0.1  0.1 /bin/sh -c sleep 1
""".strip(),
    )
    return {
        "case": "worker_resource_idle_passes",
        "ok": result["rc"] == 0 and result["report"].get("status") == "pass" and not result["report"].get("busy_processes"),
        "result": result,
    }


def case_non_tmp_root_blocks() -> dict[str, Any]:
    root = Path("/dev/null/factorforge_worker_resource_guard_smoke_probe")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_factorforge_worker_resource_guard_smoke.py"), "--root", str(root), "--fresh"],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
    )
    text = proc.stdout + proc.stderr
    return {
        "case": "worker_resource_guard_non_tmp_root_blocks",
        "ok": proc.returncode == 1 and TOKEN_NON_TMP_ROOT in text,
        "token_present": TOKEN_NON_TMP_ROOT in text,
        "rc": proc.returncode,
    }


def run_case(root: Path, name: str, fn) -> dict[str, Any]:
    case_root = root / name
    if case_root.exists():
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True, exist_ok=True)
    try:
        return fn(case_root)
    except Exception as exc:
        return {"case": name, "ok": False, "error": repr(exc)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/tmp/factorforge_worker_resource_guard_smoke")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).expanduser()
    if not is_tmp(root):
        print(TOKEN_NON_TMP_ROOT, file=sys.stderr)
        return 1
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    cases = [
        run_case(root, "busy_data_backfill", case_busy_data_backfill_blocks),
        run_case(root, "busy_factorforge_process", case_busy_factorforge_process_blocks),
        run_case(root, "idle_worker", case_idle_worker_passes),
        case_non_tmp_root_blocks(),
    ]
    summary = {
        "verdict": "ACCEPT" if all(case.get("ok") for case in cases) else "BLOCK",
        "cases": cases,
        "notes": [
            "Synthetic resource guard smoke; no worker was contacted or started.",
            "ps snapshots are local fixtures.",
        ],
    }
    summary_path = root / "worker_resource_guard_smoke_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"[SUMMARY] {summary_path}")
    return 0 if summary["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
