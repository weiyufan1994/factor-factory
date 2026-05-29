from __future__ import annotations

import json
import subprocess
from typing import Any


def _run_aws(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run(["aws", *args], text=True, capture_output=True)
    if proc.returncode != 0:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"raw_stdout": proc.stdout}
    payload["ok"] = True
    return payload


def send_worker_command(instance_id: str, commands: list[str], *, comment: str = "FactorForge worker command") -> dict[str, Any]:
    return _run_aws(
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
            json.dumps({"commands": commands}, ensure_ascii=False),
            "--output",
            "json",
        ]
    )


def get_command_invocation(instance_id: str, command_id: str) -> dict[str, Any]:
    return _run_aws(
        [
            "ssm",
            "get-command-invocation",
            "--instance-id",
            instance_id,
            "--command-id",
            command_id,
            "--output",
            "json",
        ]
    )
