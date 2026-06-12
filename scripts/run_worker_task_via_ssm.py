#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factor_factory.worker_execution import IN_PROGRESS_SSM_STATUSES


def run_local(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def aws_text(args: list[str]) -> str:
    return run_local(["aws", *args]).stdout


def build_remote_commands(task_spec: dict, remote_spec_path: str, remote_runner: str, remote_report_path: str | None) -> list[str]:
    encoded = base64.b64encode(json.dumps(task_spec, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii")
    report_arg = f" --report-path {json.dumps(remote_report_path)}" if remote_report_path else ""
    return [
        "set -euo pipefail",
        f"mkdir -p {json.dumps(str(Path(remote_spec_path).parent))}",
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "import base64\n"
        f"payload = {encoded!r}\n"
        f"path = Path({remote_spec_path!r})\n"
        "path.write_bytes(base64.b64decode(payload))\n"
        "print(path)\n"
        "PY",
        f"python3 {json.dumps(remote_runner)} {json.dumps(remote_spec_path)}{report_arg}",
    ]


def send_ssm(instance_id: str, comment: str, commands: list[str], timeout_sec: int) -> str:
    params = json.dumps({"commands": commands, "executionTimeout": [str(timeout_sec)]})
    return aws_text([
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
    ]).strip()


def wait_ssm(instance_id: str, command_id: str, timeout_sec: int, poll_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        raw = aws_text([
            "ssm",
            "get-command-invocation",
            "--command-id",
            command_id,
            "--instance-id",
            instance_id,
            "--output",
            "json",
        ])
        payload = json.loads(raw)
        if payload.get("Status") not in IN_PROGRESS_SSM_STATUSES:
            return payload
        time.sleep(poll_sec)
    raise TimeoutError(f"SSM command timed out: {command_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Transport a worker_task_spec_v1 to EC2 via SSM and run the remote bootstrap.")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--task-spec", required=True)
    parser.add_argument("--remote-spec-path", required=True)
    parser.add_argument("--remote-runner", required=True, help="Remote path to scripts/run_worker_task_spec.py or equivalent bootstrap.")
    parser.add_argument("--remote-report-path", default=None)
    parser.add_argument("--comment", default="worker task spec via ssm")
    parser.add_argument("--timeout-sec", type=int, default=3600)
    parser.add_argument("--poll-sec", type=int, default=10)
    parser.add_argument("--dry-run-local", action="store_true", help="Print the SSM command payload without calling AWS.")
    args = parser.parse_args()

    task_spec = json.loads(Path(args.task_spec).expanduser().read_text(encoding="utf-8"))
    task_spec.setdefault("transport", {})
    task_spec["transport"].update({"type": "ssm", "instance_id": args.instance_id})
    commands = build_remote_commands(task_spec, args.remote_spec_path, args.remote_runner, args.remote_report_path)
    if args.dry_run_local:
        print(json.dumps({"dry_run": True, "instance_id": args.instance_id, "commands": commands}, ensure_ascii=False, indent=2))
        return 0

    command_id = send_ssm(args.instance_id, args.comment, commands, args.timeout_sec)
    payload = wait_ssm(args.instance_id, command_id, args.timeout_sec, args.poll_sec)
    summary = {
        "transport": {
            "type": "ssm",
            "instance_id": args.instance_id,
            "command_id": command_id,
            "ssm_status": payload.get("Status"),
            "response_code": payload.get("ResponseCode"),
        },
        "stdout": payload.get("StandardOutputContent", ""),
        "stderr": payload.get("StandardErrorContent", ""),
        "remote_report_path": args.remote_report_path,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if payload.get("Status") == "Success" and payload.get("ResponseCode", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
