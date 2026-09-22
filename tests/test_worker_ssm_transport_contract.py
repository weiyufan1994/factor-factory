from __future__ import annotations

import json

from factor_factory.worker_execution import DEFAULT_SIDE_EFFECTS, validate_worker_command_report
from scripts import run_worker_task_via_ssm
from scripts.run_worker_task_via_ssm import build_remote_commands


def test_ssm_remote_commands_are_posix_sh_compatible() -> None:
    commands = build_remote_commands(
        {"schema_version": "worker_task_spec_v1"},
        "/tmp/task.json",
        "/opt/factorforge/run_worker_task_spec.py",
        "/tmp/report.json",
    )

    assert commands[0] == "set -eu"
    assert "pipefail" not in "\n".join(commands)


def test_worker_report_validator_honors_declared_side_effect_contract() -> None:
    side_effects = dict(DEFAULT_SIDE_EFFECTS)
    side_effects["worker_process_started"] = True
    report = {
        "schema_version": "worker_command_report_v1",
        "task_id": "bounded_canary",
        "transport": {
            "type": "ssm",
            "command_id": "command-1",
            "instance_id": "instance-1",
            "ssm_status": "Success",
        },
        "runtime": {"python_path": "/usr/bin/python3", "git_sha": "a" * 40},
        "preflight": {"status": "PASS", "checks": []},
        "execution": {
            "return_code": 0,
            "stdout_path": "/tmp/stdout.txt",
            "stderr_path": "/tmp/stderr.txt",
        },
        "business_result": {"verdict": "PASS", "validator_verdict": "PASS"},
        "side_effect_contract": side_effects,
        "side_effects": side_effects,
    }

    validation = validate_worker_command_report(report)

    assert validation["verdict"] == "ACCEPT"
    assert validation["failed_checks"] == []


def test_worker_report_validator_rejects_side_effect_contract_mismatch() -> None:
    side_effects = dict(DEFAULT_SIDE_EFFECTS)
    observed = dict(side_effects)
    observed["worker_process_started"] = True
    report = {
        "schema_version": "worker_command_report_v1",
        "task_id": "bounded_canary",
        "transport": {"type": "local"},
        "runtime": {"python_path": "/usr/bin/python3", "git_sha": "a" * 40},
        "preflight": {"status": "PASS", "checks": []},
        "execution": {
            "return_code": 0,
            "stdout_path": "/tmp/stdout.txt",
            "stderr_path": "/tmp/stderr.txt",
        },
        "business_result": {"verdict": "PASS", "validator_verdict": "PASS"},
        "side_effect_contract": side_effects,
        "side_effects": observed,
    }

    validation = validate_worker_command_report(report)

    assert validation["verdict"] == "BLOCK"
    assert validation["blocker_token"] == "BLOCK_WORKER_SIDE_EFFECT_CONTRACT_VIOLATED"


def test_worker_report_accepts_hash_bound_source_bundle_without_git() -> None:
    side_effects = dict(DEFAULT_SIDE_EFFECTS)
    report = {
        "schema_version": "worker_command_report_v1",
        "task_id": "bounded_bundle_canary",
        "transport": {
            "type": "ssm",
            "command_id": "command-1",
            "instance_id": "instance-1",
            "ssm_status": "Success",
        },
        "runtime": {
            "python_path": "/usr/bin/python3",
            "git_sha": None,
            "source_bundle_sha256": "a" * 64,
            "source_bundle_sha256_required": "a" * 64,
        },
        "preflight": {"status": "PASS", "checks": []},
        "execution": {
            "return_code": 0,
            "stdout_path": "/tmp/stdout.txt",
            "stderr_path": "/tmp/stderr.txt",
        },
        "business_result": {"verdict": "PASS", "validator_verdict": "PASS"},
        "side_effect_contract": side_effects,
        "side_effects": side_effects,
    }

    assert validate_worker_command_report(report)["verdict"] == "ACCEPT"


def test_ssm_transport_success_without_worker_report_fails_closed(
    tmp_path, monkeypatch
) -> None:
    task_spec = tmp_path / "task.json"
    task_spec.write_text(
        json.dumps(
            {
                "schema_version": "worker_task_spec_v1",
                "task_id": "bounded",
                "project": "factor-factory",
                "execution": {"runner": "/tmp/runner.py"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_worker_task_via_ssm, "send_ssm", lambda *args: "cmd-1")
    monkeypatch.setattr(
        run_worker_task_via_ssm,
        "wait_ssm",
        lambda *args: {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "runner exited without a report",
            "StandardErrorContent": "",
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_worker_task_via_ssm.py",
            "--instance-id",
            "i-test",
            "--task-spec",
            str(task_spec),
            "--remote-spec-path",
            "/tmp/task.json",
            "--remote-runner",
            "/tmp/run_worker_task_spec.py",
            "--combined-report-path",
            str(tmp_path / "combined.json"),
        ],
    )

    assert run_worker_task_via_ssm.main() == 1
    assert not (tmp_path / "combined.json").exists()
