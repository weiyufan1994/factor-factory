#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOKEN_BUSY = "BLOCK_FACTORFORGE_WORKER_RESOURCE_BUSY"

BUSY_COMMAND_PATTERNS = {
    "clean_data_backfill": [
        "build_clean_daily_layer.py",
        "append_clean_daily_layer.py",
        "update_clean_daily_bar_after_daily_update.py",
        "run_tushare_daily_update",
        "run_tushare_nonminute",
    ],
    "factorforge_run": [
        "run_step3b.py",
        "run_step4.py",
        "prepare_factorforge_formal_artifacts.py",
        "run_factorforge_ultimate.py",
        "factorforgectl",
    ],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def ps_snapshot() -> str:
    return subprocess.check_output(["ps", "-axo", "pid,ppid,%cpu,%mem,command"], text=True)


def parse_ps_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("PID "):
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        pid, ppid, cpu_raw, mem_raw, command = parts
        try:
            cpu = float(cpu_raw)
            mem = float(mem_raw)
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": ppid, "cpu": cpu, "mem": mem, "command": command})
    return rows


def process_reasons(row: dict[str, Any], *, max_cpu: float, max_mem: float) -> list[str]:
    command = str(row.get("command") or "")
    reasons: list[str] = []
    for reason, patterns in BUSY_COMMAND_PATTERNS.items():
        if any(pattern in command for pattern in patterns):
            reasons.append(reason)
    if float(row.get("cpu") or 0.0) >= max_cpu:
        reasons.append("cpu_threshold")
    if float(row.get("mem") or 0.0) >= max_mem:
        reasons.append("mem_threshold")
    return reasons


def evaluate(snapshot: str, *, max_cpu: float, max_mem: float) -> dict[str, Any]:
    busy: list[dict[str, Any]] = []
    for row in parse_ps_rows(snapshot):
        reasons = process_reasons(row, max_cpu=max_cpu, max_mem=max_mem)
        if reasons:
            busy.append({**row, "reasons": reasons})
    status = "blocked" if busy else "pass"
    return {
        "contract_version": "factorforge_worker_resource_guard_v1",
        "checked_at_utc": utc_now(),
        "status": status,
        "block_token": TOKEN_BUSY if busy else None,
        "max_cpu": max_cpu,
        "max_mem": max_mem,
        "busy_processes": busy,
        "worker_started": False,
        "side_effects": {
            "worker_start_attempted": False,
            "process_kill_attempted": False,
            "clean_data_touched": False,
            "factorforge_task_started": False,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Block Factor Forge production dispatch when worker resources are already busy.")
    parser.add_argument("--ps-snapshot", default=None, help="Optional file containing ps output with pid, ppid, cpu, mem, command columns.")
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--max-cpu", type=float, default=90.0)
    parser.add_argument("--max-mem", type=float, default=80.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.ps_snapshot:
        snapshot = Path(args.ps_snapshot).read_text(encoding="utf-8")
    else:
        snapshot = ps_snapshot()
    report = evaluate(snapshot, max_cpu=args.max_cpu, max_mem=args.max_mem)
    if args.report_path:
        write_json(Path(args.report_path), report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["status"] != "pass":
        print(TOKEN_BUSY, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
