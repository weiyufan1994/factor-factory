from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_factorforge_ultimate as ultimate


def test_public_command_proof_redacts_host_private_control_values() -> None:
    private_root = "/host/private/research-org-trust"
    installation_id = "host-private-installation"
    result = ultimate.CommandResult(
        name="materialize_web_evo_purged_is_checkpoint",
        command=[
            "python3",
            "checkpoint.py",
            "--host-trust-root",
            private_root,
            "--installation-id",
            installation_id,
        ],
        cwd="/repo",
        started_at_utc="2026-08-13T00:00:00Z",
        finished_at_utc="2026-08-13T00:00:01Z",
        returncode=0,
        stdout_tail=f"loaded {private_root}",
        stderr_tail=installation_id,
        status="PASS",
    )

    projected = ultimate.public_command_proof(
        result,
        denied_values=[private_root, installation_id],
    )
    serialized = json.dumps(projected, sort_keys=True)

    assert private_root not in serialized
    assert installation_id not in serialized
    assert "[HOST_PRIVATE]" in serialized
    assert result.command[-1] == installation_id


@pytest.mark.parametrize(
    "next_command",
    ["validate_step3b", "materialize_evo_pre_release_data", "run_step4", "validate_step4"],
)
def test_signed_command_recovery_projects_only_the_exact_remaining_suffix(
    next_command: str,
) -> None:
    names = [
        "run_step3b",
        "validate_step3b",
        "materialize_evo_pre_release_data",
        "run_step4",
        "validate_step4",
        "finalize_web_factor_proof",
    ]
    commands = [(name, ["python3", name]) for name in names]
    start = "3b" if next_command == "validate_step3b" else "4"
    receipt = {
        "boundary": {
            "next_command": next_command,
            "required_start_step": start,
        },
        "authority": {
            "exact_next_command": next_command,
            "required_start_step": start,
            "oos_release_allowed": False,
            "scientific_verdict_issued": False,
        },
    }
    projected = ultimate.apply_evo_child_command_recovery(commands, receipt)
    assert projected[0][0] == next_command
    assert [name for name, _command in projected] == names[names.index(next_command):]


def test_command_recovery_rejects_unknown_or_widened_authority() -> None:
    commands = [("run_step4", ["python3", "run_step4"])]
    with pytest.raises(ValueError, match="command_recovery"):
        ultimate.apply_evo_child_command_recovery(
            commands,
            {
                "boundary": {"next_command": "run_step4", "required_start_step": "4"},
                "authority": {
                    "exact_next_command": "run_step3b",
                    "required_start_step": "4",
                    "oos_release_allowed": True,
                    "scientific_verdict_issued": False,
                },
            },
        )


def _admission_resolution(
    *,
    installation_id: str = "private-installation",
    job_id: str = "private-job",
    parent_report_id: str = "PARENT",
    child_report_id: str = "PARENT__EVO_CHILD_001",
    expected_host_pin: str = "a" * 64,
) -> dict:
    return {
        "verdict": "PASS",
        "status": "HOST_ADMITTED_CLOSED_EVO_CHILD_CONTAINER",
        "factor_verdict": "NOT_ISSUED",
        "admission": {
            "receipt_id": "b" * 64,
            "content_sha256": "c" * 64,
            "status": "HOST_ADMITTED_CLOSED_EVO_CHILD_CONTAINER",
            "expected_host_trust_manifest_sha256": expected_host_pin,
            "identity": {
                "installation_id": installation_id,
                "job_id": job_id,
                "parent_report_id": parent_report_id,
                "child_report_id": child_report_id,
            },
            "container": {"image_digest": "sha256:" + "d" * 64},
        },
    }


def _execution(
    *,
    repo_root: Path,
    name: str = "run_step3b",
    command: list[str] | None = None,
    returncode: int = 0,
) -> dict:
    logical = command or [
        ultimate.sys.executable,
        "skills/factor-forge-step3/scripts/run_step3b.py",
        "--manifest",
        "/workspace/manifest.json",
    ]
    receipt_id = "a" * 64
    return {
        "factor_verdict": "NOT_ISSUED",
        "process_tree_absent": True,
        "stage_status": "SUCCEEDED" if returncode == 0 else "FAILED",
        "timed_out": False,
        "termination_receipt_sha256": "b" * 64,
        "command_result": {
            "name": name,
            "command": logical,
            "cwd": str(repo_root.resolve()),
            "started_at_utc": "2026-08-13T00:00:00Z",
            "finished_at_utc": "2026-08-13T00:00:01Z",
            "returncode": returncode,
            "stdout_tail": "stage output",
            "stderr_tail": "" if returncode == 0 else "stage failed",
            "status": "PASS" if returncode == 0 else "FAIL",
        },
        "termination_receipt": {
            "receipt_id": receipt_id,
            "status": "HOST_CONFIRMED_CONTAINER_PROCESS_TREE_ABSENT",
            "stage_name": name,
            "admission_ref": {"receipt_id": "c" * 64},
            "inflight_ref": {"receipt_id": "d" * 64},
            "container": {
                "image_digest": "sha256:" + "e" * 64,
                "network": "none",
            },
            "command": {
                "logical_argv": logical,
                "logical_sha256": "f" * 64,
            },
            "execution": {
                "factor_verdict": "NOT_ISSUED",
                "returncode": returncode,
                "timed_out": False,
                "stage_status": "SUCCEEDED" if returncode == 0 else "FAILED",
            },
            "process_tree": {"process_tree_absent": True},
        },
    }


@pytest.mark.parametrize(
    "name",
    ["run_step3b", "validate_step3b", "run_step4", "validate_step4"],
)
def test_closed_caller_routes_exact_stage_and_projects_termination_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    command = [ultimate.sys.executable, f"skills/{name}.py", "--report-id", "CHILD"]
    captured: dict = {}

    def run(*args, **_kwargs):
        captured["args"] = args
        return _execution(
            repo_root=tmp_path,
            name=name,
            command=command,
        )

    monkeypatch.setattr(ultimate, "run_evo_child_agent_stage", run)
    result, termination_ref = ultimate.run_evo_child_container_command(
        admission_path="/host/private/admission.json",
        name=name,
        command=command,
        env={"PATH": "/usr/bin"},
        trust_root="/host/private/trust",
        installation_id="host-installation",
        repo_root=tmp_path,
        timeout=123,
    )

    assert captured["args"] == (
        "/host/private/admission.json",
        name,
        command,
        {"PATH": "/usr/bin"},
        123,
        "/host/private/trust",
        "host-installation",
    )
    assert result.returncode == 0
    assert result.status == "PASS"
    assert termination_ref == {
        "contract_version": "factorforge_ultimate_evo_child_container_ref_v1",
        "stage_name": name,
        "stage_status": "SUCCEEDED",
        "process_tree_absent": True,
        "factor_verdict": "NOT_ISSUED",
        "admission_receipt_id": "c" * 64,
        "inflight_receipt_id": "d" * 64,
        "termination_receipt_id": "a" * 64,
        "termination_receipt_sha256": "b" * 64,
        "image_digest": "sha256:" + "e" * 64,
        "logical_command_sha256": "f" * 64,
    }
    assert "admission.json" not in json.dumps(termination_ref)
    assert "/host/private" not in json.dumps(termination_ref)


def test_closed_caller_propagates_nonzero_without_calling_it_scientific_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = [ultimate.sys.executable, "skills/run_step4.py", "--report-id", "CHILD"]
    monkeypatch.setattr(
        ultimate,
        "run_evo_child_agent_stage",
        lambda *_args, **_kwargs: _execution(
            repo_root=tmp_path,
            name="run_step4",
            command=command,
            returncode=17,
        ),
    )

    result, termination_ref = ultimate.run_evo_child_container_command(
        admission_path="/host/private/admission.json",
        name="run_step4",
        command=command,
        env={},
        trust_root="/host/private/trust",
        installation_id="host-installation",
        repo_root=tmp_path,
    )

    assert result.returncode == 17
    assert result.status == "FAIL"
    assert termination_ref["stage_status"] == "FAILED"
    assert termination_ref["factor_verdict"] == "NOT_ISSUED"


@pytest.mark.parametrize(
    "mutation",
    [
        {"process_tree_absent": False},
        {"factor_verdict": "REJECT"},
        {"termination_receipt_sha256": "not-a-digest"},
    ],
)
def test_closed_caller_rejects_tampered_execution_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict,
) -> None:
    execution = _execution(repo_root=tmp_path)
    execution.update(mutation)
    monkeypatch.setattr(
        ultimate,
        "run_evo_child_agent_stage",
        lambda *_args, **_kwargs: execution,
    )
    with pytest.raises(RuntimeError, match="CONTAINER_TERMINATION"):
        ultimate.run_evo_child_container_command(
            admission_path="/host/private/admission.json",
            name="run_step3b",
            command=execution["command_result"]["command"],
            env={},
            trust_root="/host/private/trust",
            installation_id="host-installation",
            repo_root=tmp_path,
        )


@pytest.mark.parametrize("malformed", [None, [], "private runner detail"])
def test_closed_caller_rejects_non_object_runner_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    malformed: object,
) -> None:
    monkeypatch.setattr(
        ultimate,
        "run_evo_child_agent_stage",
        lambda *_args, **_kwargs: malformed,
    )
    with pytest.raises(RuntimeError) as caught:
        ultimate.run_evo_child_container_command(
            admission_path="/host/private/admission.json",
            name="run_step3b",
            command=[ultimate.sys.executable, "skills/run_step3b.py"],
            env={},
            trust_root="/host/private/trust",
            installation_id="host-installation",
            repo_root=tmp_path,
        )
    assert str(caught.value) == (
        "BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_EXECUTION_INVALID"
    )


def test_only_four_agent_stages_are_eligible_and_no_seatbelt_caller_remains() -> None:
    assert ultimate.EVO_CHILD_AGENT_STAGE_NAMES == {
        "run_step3b",
        "validate_step3b",
        "run_step4",
        "validate_step4",
    }
    source = Path(ultimate.__file__).read_text(encoding="utf-8")
    assert "'/usr/bin/sandbox-exec'" not in source
    assert "agent_execution_sandbox_profile =" not in source
    assert "validate_evo_child_sandbox_admission" not in source
    assert "--agent-execution-container-admission" in source
    assert {
        "materialize_evo_pre_release_data",
        "finalize_web_factor_proof",
    }.isdisjoint(ultimate.EVO_CHILD_AGENT_STAGE_NAMES)
    assert "command_proof['evo_child_container_termination_ref']" in source
    assert "'content_sha256': admitted['content_sha256']" in source


def test_agent_env_strips_all_four_host_control_values_and_secrets() -> None:
    source = {
        ultimate.OOS_HOST_TRUST_ROOT_ENV: "/private/trust",
        ultimate.OOS_HOST_INSTALLATION_ID_ENV: "private-installation",
        ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: "/private/state",
        ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job",
        "AWS_SECRET_ACCESS_KEY": "private-secret",
        "PATH": "/usr/bin",
    }
    isolated = ultimate.evo_agent_execution_env(source)
    for key, value in source.items():
        if key != "PATH":
            assert key not in isolated
            assert value not in json.dumps(isolated)
    assert isolated["PATH"] == "/usr/bin"
    assert isolated["FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY"] == "DENY"


def test_host_control_capture_strips_exact_four_before_any_child_env() -> None:
    source = {
        ultimate.OOS_HOST_TRUST_ROOT_ENV: "/private/trust",
        ultimate.OOS_HOST_INSTALLATION_ID_ENV: "private-installation",
        ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: "/private/state",
        ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job",
        "PATH": "/usr/bin",
    }
    stripped, captured = ultimate.capture_host_control_environment(source)
    assert stripped == {"PATH": "/usr/bin"}
    assert captured == {key: source[key] for key in source if key != "PATH"}
    assert all(value not in json.dumps(stripped) for value in captured.values())


def test_root_finalizer_receives_incident_pair_while_agent_stages_remain_stripped() -> None:
    base = {"PATH": "/usr/bin"}
    incident = {
        ultimate.OOS_HOST_TRUST_ROOT_ENV: "/private/trust",
        ultimate.OOS_HOST_INSTALLATION_ID_ENV: "private-installation",
    }
    container = {
        ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: "/private/state",
        ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job",
    }
    finalizer_env, injected = ultimate.command_environment_for_host_controls(
        name="finalize_web_factor_proof",
        base_env=base,
        incident_host_env=incident,
        container_host_env=container,
        web_secure_child_oos=False,
    )
    assert injected is True
    assert finalizer_env == {**base, **incident}
    assert all(key not in finalizer_env for key in container)

    ordinary_env, injected = ultimate.command_environment_for_host_controls(
        name="run_step4",
        base_env=base,
        incident_host_env=incident,
        container_host_env=container,
        web_secure_child_oos=False,
    )
    assert injected is False
    assert ordinary_env == base
    agent_env = ultimate.evo_agent_execution_env(
        {**ordinary_env, **incident, **container}
    )
    assert all(key not in agent_env for key in (*incident, *container))


def test_missing_or_tampered_admission_blocks_with_fixed_nonprivate_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = {
        ultimate.OOS_HOST_TRUST_ROOT_ENV: "/private/trust",
        ultimate.OOS_HOST_INSTALLATION_ID_ENV: "private-installation",
        ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: "/private/state",
        ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job",
    }
    common = {
        "host_control": control,
        "workspace_root": tmp_path / "workspace",
        "worktree": tmp_path / "worktree",
        "parent_report_id": "PARENT",
        "child_report_id": "PARENT__EVO_CHILD_001",
        "expected_host_pin": "a" * 64,
    }
    with pytest.raises(RuntimeError, match="CONTAINER_ADMISSION_REQUIRED"):
        ultimate.resolve_evo_child_container_admission_for_ultimate(
            admission_path=None,
            **common,
        )

    private_detail = "/private/trust/tampered-admission.json"
    monkeypatch.setattr(
        ultimate,
        "validate_evo_child_container_admission",
        lambda **_kwargs: (_ for _ in ()).throw(
            ultimate.EvoChildContainerError([private_detail])
        ),
    )
    with pytest.raises(RuntimeError) as caught:
        ultimate.resolve_evo_child_container_admission_for_ultimate(
            admission_path=private_detail,
            **common,
        )
    assert str(caught.value) == (
        "BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_ADMISSION_INVALID"
    )
    assert private_detail not in str(caught.value)


def test_admission_resolver_passes_only_captured_host_control_to_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}
    validated = _admission_resolution()
    monkeypatch.setattr(
        ultimate,
        "validate_evo_child_container_admission",
        lambda **kwargs: captured.update(kwargs) or validated,
    )
    control = {
        ultimate.OOS_HOST_TRUST_ROOT_ENV: "/private/trust",
        ultimate.OOS_HOST_INSTALLATION_ID_ENV: "private-installation",
        ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: "/private/state",
        ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job",
    }
    result = ultimate.resolve_evo_child_container_admission_for_ultimate(
        admission_path="/private/admission.json",
        host_control=control,
        workspace_root=tmp_path / "workspace",
        worktree=tmp_path / "worktree",
        parent_report_id="PARENT",
        child_report_id="PARENT__EVO_CHILD_001",
        expected_host_pin="a" * 64,
    )
    assert result == validated
    assert captured == {
        "admission_path": "/private/admission.json",
        "state_root": "/private/state",
        "trust_root": "/private/trust",
        "installation_id": "private-installation",
        "job_id": "private-job",
        "workspace_root": tmp_path / "workspace",
        "worktree": tmp_path / "worktree",
        "parent_report_id": "PARENT",
        "child_report_id": "PARENT__EVO_CHILD_001",
        "expected_host_pin": "a" * 64,
    }


def test_admission_resolver_rejects_malformed_validator_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ultimate,
        "validate_evo_child_container_admission",
        lambda **_kwargs: {"verdict": "PASS", "private": "/private/state"},
    )
    with pytest.raises(RuntimeError) as caught:
        ultimate.resolve_evo_child_container_admission_for_ultimate(
            admission_path="/private/admission.json",
            host_control={
                ultimate.OOS_HOST_TRUST_ROOT_ENV: "/private/trust",
                ultimate.OOS_HOST_INSTALLATION_ID_ENV: "private-installation",
                ultimate.EVO_CHILD_CONTAINER_STATE_ROOT_ENV: "/private/state",
                ultimate.EVO_CHILD_CONTAINER_JOB_ID_ENV: "private-job",
            },
            workspace_root=tmp_path / "workspace",
            worktree=tmp_path / "worktree",
            parent_report_id="PARENT",
            child_report_id="PARENT__EVO_CHILD_001",
            expected_host_pin="a" * 64,
        )
    assert str(caught.value) == (
        "BLOCK_FACTORFORGE_EVO_CHILD_CONTAINER_ADMISSION_INVALID"
    )
    assert "/private/state" not in str(caught.value)
