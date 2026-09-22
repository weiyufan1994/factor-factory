from __future__ import annotations

from copy import deepcopy
import json

from factor_factory.console.models import (
    HOST_PRIVATE_PUBLIC_REDACTION,
    ResearchJob,
    ResearchRequest,
)


def _job_with_private_evo_result() -> tuple[ResearchJob, dict, tuple[str, ...]]:
    state_root = "/srv/factorforge-console/state"
    trust_root = f"{state_root}/research-org-trust"
    installation_id = "host-installation-secret"
    carrier = f"{state_root}/jobs/job_1234567890/sealed-oos/oos.parquet"
    worktree = "/srv/factorforge-console/worktrees/job_1234567890"
    workspace = f"{worktree}/factor_research/FACTOR/research"
    admission = (
        f"{state_root}/jobs/job_1234567890/evo-child-container/CHILD/admission.json"
    )
    receipt = f"{state_root}/jobs/job_1234567890/evo-child-runtime/receipt.json"
    result = {
        "summary": "Child execution is ready.",
        "safe_nested": [{"status": "CHILD_EXECUTION_READY"}],
        "evo_v2_child_runtime": {
            "ready": {
                "status": "CHILD_EXECUTION_READY",
                "checkpoint_path": receipt,
                "container_admission_path": admission,
                "ultimate_argv": [
                    "python3",
                    "scripts/run_factorforge_ultimate.py",
                    "--factorforge-root",
                    worktree,
                    "--factor-workspace",
                    workspace,
                    "--research-org-runtime-private-root",
                    f"{state_root}/jobs/job_1234567890/research_org_private",
                    "--research-org-runtime-trust-root",
                    trust_root,
                    f"--research-org-runtime-installation-id={installation_id}",
                    "--agent-execution-container-admission",
                    admission,
                    "--sealed-oos-carrier",
                    carrier,
                ],
                "nested": [
                    {"identity": {"installation_id": installation_id}},
                    {"recovery_admission": {"path": admission, "sha256": "a" * 64}},
                    {
                        "host_control": {
                            "state_root": state_root,
                            "trust_root": trust_root,
                        }
                    },
                ],
            },
            "execution": {
                "status": "CHILD_RESUME_READY",
                "execution_receipt_path": receipt,
                "diagnostic": f"loaded {trust_root} for {installation_id}",
            },
            "phase_checkpoint": {
                "phase_inflight_path": (
                    f"{state_root}/jobs/job_1234567890/evo-child-runtime/phase-inflight.json"
                ),
                "phase_receipt_candidate_path": (
                    f"{state_root}/jobs/job_1234567890/evo-child-runtime/phase.json"
                ),
            },
            "private_locator": {
                "carrier": {"path": carrier, "sha256": "b" * 64}
            },
        },
    }
    return (
        ResearchJob(
            job_id="job_1234567890",
            factor_id="FACTOR",
            research_id="research",
            report_id="REPORT",
            request=ResearchRequest(title="test", hypothesis="test hypothesis"),
            worktree_path="/srv/factorforge-console/worktrees/job_1234567890",
            workspace_path="/srv/factorforge-console/workspaces/job_1234567890",
            agent_session_key="private-session-key",
            result=result,
        ),
        result,
        (
            state_root,
            trust_root,
            installation_id,
            carrier,
            admission,
            receipt,
            worktree,
            workspace,
        ),
    )


def test_research_job_public_projection_recursively_redacts_host_private_state() -> None:
    job, private_result, denied_values = _job_with_private_evo_result()
    original = deepcopy(private_result)

    public_payload = job.to_dict()
    serialized = json.dumps(public_payload, ensure_ascii=False, sort_keys=True)

    for denied in denied_values:
        assert denied not in serialized
    assert HOST_PRIVATE_PUBLIC_REDACTION in serialized
    assert public_payload["result"]["summary"] == "Child execution is ready."
    assert public_payload["result"]["safe_nested"] == [
        {"status": "CHILD_EXECUTION_READY"}
    ]
    argv = public_payload["result"]["evo_v2_child_runtime"]["ready"][
        "ultimate_argv"
    ]
    assert argv[argv.index("--research-org-runtime-trust-root") + 1] == (
        HOST_PRIVATE_PUBLIC_REDACTION
    )
    assert (
        f"--research-org-runtime-installation-id={HOST_PRIVATE_PUBLIC_REDACTION}"
        in argv
    )
    assert private_result == original
    assert job.result == original


def test_research_job_private_projection_is_unchanged_and_public_projection_is_independent() -> None:
    job, private_result, denied_values = _job_with_private_evo_result()
    original = deepcopy(private_result)

    private_payload = job.to_dict(include_private_paths=True)
    public_payload = job.to_dict(include_private_paths=False)

    assert private_payload["result"] == original
    assert private_payload["worktree_path"] == job.worktree_path
    assert private_payload["workspace_path"] == job.workspace_path
    assert private_payload["agent_session_key"] == job.agent_session_key
    private_serialized = json.dumps(private_payload, ensure_ascii=False)
    for denied in denied_values:
        assert denied in private_serialized

    public_payload["result"]["evo_v2_child_runtime"]["ready"]["nested"].append(
        {"mutated": True}
    )
    assert job.result == original
    assert private_result == original
    assert "worktree_path" not in public_payload
    assert "workspace_path" not in public_payload
    assert "agent_session_key" not in public_payload
