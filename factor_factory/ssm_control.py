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


def describe_ec2_instance(instance_id: str) -> dict[str, Any]:
    payload = _run_aws(["ec2", "describe-instances", "--instance-ids", instance_id, "--output", "json"])
    if not payload.get("ok"):
        return payload
    reservations = payload.get("Reservations") or []
    instances: list[dict[str, Any]] = []
    for reservation in reservations:
        if isinstance(reservation, dict):
            for instance in reservation.get("Instances") or []:
                if isinstance(instance, dict):
                    instances.append(instance)
    instance = instances[0] if instances else {}
    state = ((instance.get("State") or {}).get("Name")) if isinstance(instance, dict) else None
    return {
        "ok": True,
        "instance_id": instance_id,
        "state": state,
        "instance": instance,
    }


def start_ec2_instance(instance_id: str) -> dict[str, Any]:
    return _run_aws(["ec2", "start-instances", "--instance-ids", instance_id, "--output", "json"])


def stop_ec2_instance(instance_id: str) -> dict[str, Any]:
    return _run_aws(["ec2", "stop-instances", "--instance-ids", instance_id, "--output", "json"])


def wait_ec2_instance_state(instance_id: str, state: str) -> dict[str, Any]:
    waiter = {"running": "instance-running", "stopped": "instance-stopped"}.get(state)
    if not waiter:
        return {"ok": False, "stderr": f"unsupported EC2 wait state: {state}"}
    return _run_aws(["ec2", "wait", waiter, "--instance-ids", instance_id])


def describe_ssm_instance(instance_id: str) -> dict[str, Any]:
    payload = _run_aws(
        [
            "ssm",
            "describe-instance-information",
            "--filters",
            f"Key=InstanceIds,Values={instance_id}",
            "--output",
            "json",
        ]
    )
    if not payload.get("ok"):
        return payload
    infos = payload.get("InstanceInformationList") or []
    info = infos[0] if infos else {}
    return {
        "ok": True,
        "instance_id": instance_id,
        "ping_status": info.get("PingStatus") if isinstance(info, dict) else None,
        "instance_information": info,
    }
