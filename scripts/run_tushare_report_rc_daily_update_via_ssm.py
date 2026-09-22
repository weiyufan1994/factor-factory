#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path


DEFAULT_RUNNER = Path(__file__).resolve().parent / "run_tushare_nonminute_download_via_ssm.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily incremental report_rc updates on EC2 via SSM.")
    parser.add_argument("--runner", default=str(DEFAULT_RUNNER))
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--recent-days", type=int, default=3, help="Refetch this many recent trade dates to cover late-arriving reports.")
    parser.add_argument("--timeout-sec", type=int, default=12 * 3600)
    parser.add_argument("--overwrite-existing", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cmd = [
        "python3",
        str(Path(args.runner).resolve()),
        "--only",
        "report_rc",
        "--end-date",
        args.end_date,
        "--recent-days",
        str(args.recent_days),
        "--max-per-minute",
        "2",
        "--timeout-sec",
        str(args.timeout_sec),
    ]
    if args.overwrite_existing:
        cmd.append("--overwrite-existing")
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
