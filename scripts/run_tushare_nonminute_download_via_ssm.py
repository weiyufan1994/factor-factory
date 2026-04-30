#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path


DEFAULT_INSTANCE_ID = "i-01c0ceb9c04ae270e"
DEFAULT_REMOTE_ROOT = "/home/ubuntu/.openclaw/workspace/repos/quant_self/tushare数据获取"
DEFAULT_REMOTE_PYTHON = "/home/ubuntu/miniconda3/envs/rdagent/bin/python"
DEFAULT_REMOTE_SCRIPT = "22_tushare_nonminute_to_s3.py"
DEFAULT_LOCAL_SCRIPT = Path(__file__).resolve().parent / "tushare_nonminute_to_s3.py"


def run_local(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def aws_text(args: list[str]) -> str:
    return run_local(["aws", *args]).stdout


def send_ssm(instance_id: str, comment: str, commands: list[str], timeout_sec: int) -> str:
    params = json.dumps({"commands": commands, "executionTimeout": [str(timeout_sec)]})
    return aws_text(
        [
            "ssm",
            "send-command",
            "--instance-ids",
            instance_id,
            "--document-name",
            "AWS-RunShellScript",
            "--comment",
            comment,
            "--parameters",
            params,
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ]
    ).strip()


def wait_ssm(instance_id: str, command_id: str, timeout_sec: int, poll_sec: int = 10) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            raw = aws_text(
                [
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    command_id,
                    "--instance-id",
                    instance_id,
                    "--output",
                    "json",
                ]
            )
            payload = json.loads(raw)
        except subprocess.CalledProcessError:
            raw = aws_text(
                [
                    "ssm",
                    "list-command-invocations",
                    "--command-id",
                    command_id,
                    "--details",
                    "--output",
                    "json",
                ]
            )
            listing = json.loads(raw).get("CommandInvocations", [])
            if not listing:
                raise
            payload = listing[0]
            plugins = payload.get("CommandPlugins", [])
            if plugins:
                plugin = plugins[0]
                payload = {
                    "Status": payload.get("Status", plugin.get("Status")),
                    "StandardOutputContent": plugin.get("Output", ""),
                    "StandardErrorContent": plugin.get("StandardErrorContent", ""),
                }
        status = payload["Status"]
        if status not in {"Pending", "InProgress", "Delayed"}:
            return payload
        time.sleep(poll_sec)
    raise TimeoutError(f"SSM command timed out: {command_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy and run the non-minute Tushare downloader on EC2 via SSM.")
    parser.add_argument("--instance-id", default=DEFAULT_INSTANCE_ID)
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--remote-python", default=DEFAULT_REMOTE_PYTHON)
    parser.add_argument("--remote-script-name", default=DEFAULT_REMOTE_SCRIPT)
    parser.add_argument("--local-script-path", default=str(DEFAULT_LOCAL_SCRIPT))
    parser.add_argument("--start-date", default="20100101")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--max-per-minute", type=int, default=60)
    parser.add_argument("--priorities", nargs="*", default=("P0", "P1", "P2"))
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--exclude", nargs="*", default=None)
    parser.add_argument("--max-trade-dates", type=int, default=None)
    parser.add_argument("--max-months", type=int, default=None)
    parser.add_argument("--max-periods", type=int, default=None)
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--recent-days", type=int, default=None)
    parser.add_argument("--overwrite-existing", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=8 * 3600)
    return parser.parse_args()


def build_remote_commands(args: argparse.Namespace) -> list[str]:
    local_script = Path(args.local_script_path).resolve()
    script_bytes = local_script.read_bytes()
    encoded = base64.b64encode(script_bytes).decode("ascii")
    remote_script_path = f"{args.remote_root.rstrip('/')}/{args.remote_script_name}"

    cli_args = [
        "--start-date",
        args.start_date,
        "--end-date",
        args.end_date,
        "--max-per-minute",
        str(args.max_per_minute),
    ]
    if args.priorities:
        cli_args.extend(["--priorities", *args.priorities])
    if args.only:
        cli_args.extend(["--only", *args.only])
    if args.exclude:
        cli_args.extend(["--exclude", *args.exclude])
    if args.max_trade_dates is not None:
        cli_args.extend(["--max-trade-dates", str(args.max_trade_dates)])
    if args.max_months is not None:
        cli_args.extend(["--max-months", str(args.max_months)])
    if args.max_periods is not None:
        cli_args.extend(["--max-periods", str(args.max_periods)])
    if args.max_stocks is not None:
        cli_args.extend(["--max-stocks", str(args.max_stocks)])
    if args.recent_days is not None:
        cli_args.extend(["--recent-days", str(args.recent_days)])
    if args.overwrite_existing:
        cli_args.append("--overwrite-existing")
    if args.stop_on_error:
        cli_args.append("--stop-on-error")
    if args.dry_run:
        cli_args.append("--dry-run")

    remote_cmd = " ".join([shlex.quote(args.remote_python), shlex.quote(remote_script_path), *[shlex.quote(x) for x in cli_args]])

    return [
        "set -e",
        f"mkdir -p {shlex.quote(args.remote_root)}",
        f"python3 - <<'PY'\nfrom pathlib import Path\nimport base64\npayload = {encoded!r}\npath = Path({remote_script_path!r})\npath.write_bytes(base64.b64decode(payload))\npath.chmod(0o755)\nprint(path)\nPY",
        f"cd {shlex.quote(args.remote_root)}",
        remote_cmd,
    ]


def main() -> int:
    args = parse_args()
    command_id = send_ssm(
        args.instance_id,
        "tushare nonminute download via factor-factory",
        build_remote_commands(args),
        args.timeout_sec,
    )
    payload = wait_ssm(args.instance_id, command_id, timeout_sec=args.timeout_sec)
    summary = {
        "command_id": command_id,
        "status": payload["Status"],
        "stdout": payload.get("StandardOutputContent", ""),
        "stderr": payload.get("StandardErrorContent", ""),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if payload["Status"] == "Success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
