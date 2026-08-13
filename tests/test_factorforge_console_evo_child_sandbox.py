from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import factor_factory.console.evo_child_sandbox as sandbox
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store


PARENT = "SANDBOX_PARENT"
CHILD = "SANDBOX_PARENT__EVO_CHILD_001"
INSTALLATION = "sandbox-test-host"


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Path, Path]:
    worktree = tmp_path / "worktree"
    workspace = worktree / "factor_research/factor/research"
    workspace.mkdir(parents=True)
    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    trust = state / "research-org-trust"
    store = ensure_runtime_trust_store(trust, installation_id=INSTALLATION)
    monkeypatch.setattr(
        sandbox,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: store.public_manifest,
    )
    result = sandbox.materialize_evo_child_sandbox_admission(
        state_root=state,
        trust_root=trust,
        installation_id=INSTALLATION,
        job_id="job_sandbox_001",
        workspace_root=workspace,
        worktree=worktree,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=store.public_manifest["manifest_sha256"],
        denied_private_roots=(state,),
    )
    return result, state, workspace


def test_signed_admission_replays_only_code_owned_deny_default_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _state, workspace = _fixture(tmp_path, monkeypatch)
    resolved = sandbox.validate_evo_child_sandbox_admission(
        admission_path=result["admission_path"],
        workspace_root=workspace,
        worktree=workspace.parents[2],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=result["admission"][
            "expected_host_trust_manifest_sha256"
        ],
    )
    profile = Path(resolved["profile_path"]).read_text(encoding="utf-8")
    assert "(deny default)" in profile
    assert "(deny network*)" in profile
    assert "(allow default)" not in profile
    assert "(allow process-fork)" not in profile
    assert resolved["admission"]["policy"]["descendant_processes_inherit_policy"] is True


def test_caller_owned_allow_default_profile_is_not_an_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _state, workspace = _fixture(tmp_path, monkeypatch)
    arbitrary = tmp_path / "caller.sb"
    arbitrary.write_text("(version 1)\n(allow default)\n", encoding="utf-8")
    arbitrary.chmod(0o600)
    with pytest.raises(sandbox.EvoChildSandboxError):
        sandbox.validate_evo_child_sandbox_admission(
            admission_path=arbitrary,
            workspace_root=workspace,
            worktree=workspace.parents[2],
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=result["admission"][
                "expected_host_trust_manifest_sha256"
            ],
        )


def test_profile_or_signed_admission_tamper_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _state, workspace = _fixture(tmp_path, monkeypatch)
    profile = Path(result["profile_path"])
    profile.write_text("(version 1)\n(allow default)\n", encoding="utf-8")
    profile.chmod(0o600)
    with pytest.raises(sandbox.EvoChildSandboxError, match="profile_exact_replay"):
        sandbox.validate_evo_child_sandbox_admission(
            admission_path=result["admission_path"],
            workspace_root=workspace,
            worktree=workspace.parents[2],
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=result["admission"][
                "expected_host_trust_manifest_sha256"
            ],
        )

    # Restore the profile, then mutate a signed identity field.
    profile.write_text(
        sandbox._fixed_profile(
            workspace_root=workspace.resolve(),
            worktree=workspace.parents[2].resolve(),
            scratch_root=Path(result["admission"]["scratch_root"]),
            denied_private_roots=tuple(
                Path(value) for value in result["admission"]["denied_private_roots"]
            ),
        ),
        encoding="utf-8",
    )
    admission_path = Path(result["admission_path"])
    payload = json.loads(admission_path.read_text(encoding="utf-8"))
    payload["child_report_id"] = CHILD + "_TAMPER"
    admission_path.write_text(json.dumps(payload), encoding="utf-8")
    admission_path.chmod(0o600)
    with pytest.raises(sandbox.EvoChildSandboxError, match="signature"):
        sandbox.validate_evo_child_sandbox_admission(
            admission_path=admission_path,
            workspace_root=workspace,
            worktree=workspace.parents[2],
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_trust_manifest_sha256=result["admission"][
                "expected_host_trust_manifest_sha256"
            ],
        )


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file(),
    reason="macOS Seatbelt runtime required",
)
def test_real_seatbelt_denies_host_state_even_from_forked_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, state, workspace = _fixture(tmp_path, monkeypatch)
    sentinel = state / "host-private-sentinel.txt"
    sentinel.write_text("OOS_SECRET", encoding="utf-8")
    sentinel.chmod(0o600)
    attack = (
        "import os; pid=os.fork(); "
        f"os._exit(0) if pid else open({str(sentinel)!r}, 'rb').read()"
    )
    completed = subprocess.run(
        [
            "/usr/bin/sandbox-exec",
            "-f",
            result["profile_path"],
            sys.executable,
            "-c",
            attack,
        ],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "OOS_SECRET" not in completed.stdout + completed.stderr
