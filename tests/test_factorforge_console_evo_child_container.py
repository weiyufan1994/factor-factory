from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import factor_factory.console.evo_child_container as container
import factor_factory.oos_exposure_incident as incident_module
from factor_factory.console.evo_child_catalog import (
    materialize_evo_child_calendar_projection,
    materialize_evo_child_catalog_projection,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store
from factor_factory.oos_exposure_incident import (
    build_oos_exposure_incident,
    oos_exposure_private_registry_guard,
    prepare_oos_exposure_incident_host_private,
)

PARENT = "EVO_CONTAINER_PARENT"
CHILD = "EVO_CONTAINER_PARENT__EVO_CHILD_001"
INSTALLATION = "container-test-host"
JOB = "job_evo_container_001"
IMAGE = "sha256:" + "a" * 64


def _write_fake_runtime(path: Path, state: Path) -> None:
    state.mkdir(mode=0o700)
    source = f'''#!/usr/bin/env python3
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path({str(state)!r})
OBJECTS = ROOT / "objects"
OBJECTS.mkdir(exist_ok=True)
args = sys.argv[1:]
with (ROOT / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(args, separators=(",", ":")) + "\\n")

def object_path(name):
    return OBJECTS / hashlib.sha256(name.encode()).hexdigest()

if not args:
    raise SystemExit(64)
if args[0] == "inspect":
    name = args[-1]
    if object_path(name).exists():
        print(json.dumps({{"Name": name, "State": {{"Running": True}}}}))
        raise SystemExit(0)
    print(f"Error: No such object: {{name}}", file=sys.stderr)
    raise SystemExit(1)
if args[0] == "rm":
    name = args[-1]
    target = object_path(name)
    if (ROOT / "sticky").exists():
        print("runtime refused removal", file=sys.stderr)
        raise SystemExit(2)
    if target.exists():
        target.unlink()
        print(name)
        raise SystemExit(0)
    print(f"Error: No such object: {{name}}", file=sys.stderr)
    raise SystemExit(1)
if args[:4] == ["image", "inspect", "--format", "{{{{.Id}}}}"]:
    image_mode = ROOT / "image_mode"
    mode = image_mode.read_text(encoding="utf-8").strip() if image_mode.exists() else "valid"
    if mode == "failure":
        print("PRIVATE DAEMON DETAIL", file=sys.stderr)
        raise SystemExit(3)
    if mode == "malformed":
        print("not-a-digest")
        raise SystemExit(0)
    if mode == "multiple":
        print("sha256:" + "b" * 64)
        print("sha256:" + "c" * 64)
        raise SystemExit(0)
    print("sha256:" + "b" * 64)
    raise SystemExit(0)
if args[0] != "run":
    if args[0] == "ps":
        raise SystemExit(0)
    raise SystemExit(65)

name = args[args.index("--name") + 1]
cidfile = Path(args[args.index("--cidfile") + 1])
object_path(name).write_text("running", encoding="utf-8")
cidfile.write_text(hashlib.sha256(name.encode()).hexdigest() + "\\n", encoding="ascii")
mode_path = ROOT / "mode"
mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "success"
if mode == "timeout":
    time.sleep(60)
if mode == "block":
    (ROOT / "run_started").write_text("1", encoding="utf-8")
    deadline = time.monotonic() + 10
    while not (ROOT / "release_run").exists():
        if time.monotonic() >= deadline:
            print("test release missing", file=sys.stderr)
            raise SystemExit(70)
        time.sleep(0.01)
if mode == "fail":
    print("simulated stage failure", file=sys.stderr)
    raise SystemExit(9)
print("simulated stage success")
raise SystemExit(0)
'''
    path.write_text(source, encoding="utf-8")
    path.chmod(0o700)


def _calls(fake_state: Path) -> list[list[str]]:
    path = fake_state / "calls.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    worktree = tmp_path / "worktree"
    workspace = worktree / "factor_research" / "factor" / "research"
    workspace.mkdir(parents=True)
    for relative in container._STAGE_SCRIPTS.values():
        script = worktree / relative
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(f"# admitted script: {relative}\n", encoding="utf-8")
    monkeypatch.setattr(
        container,
        "_validate_engine_commit",
        lambda _engine, expected: expected,
    )
    manifest = (
        workspace
        / "objects"
        / "runtime_context"
        / f"factorforge_runtime_manifest__{CHILD}.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"report_id": CHILD}), encoding="utf-8")
    state = tmp_path / "host-state"
    state.mkdir(mode=0o700)
    trust = state / "research-org-trust"
    store = ensure_runtime_trust_store(trust, installation_id=INSTALLATION)
    monkeypatch.setattr(
        container,
        "workspace_runtime_trust_manifest",
        lambda *_args, **_kwargs: store.public_manifest,
    )
    fake_state = tmp_path / "fake-runtime-state"
    runtime = tmp_path / "fake-container-runtime"
    _write_fake_runtime(runtime, fake_state)
    external = tmp_path / "external-authority"
    external.mkdir()
    catalog_path = external / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "test-v1",
                "datasets": [{"dataset_id": "clean_daily_bar"}],
            }
        ),
        encoding="utf-8",
    )
    catalog_admission = {
        "version": "factorforge_console_catalog_admission_v1",
        "verdict": "NOT_APPLICABLE",
        "admission_scope": "local_or_test_catalog_snapshot",
        "formal_dataset_qa_implied": False,
    }
    summary = workspace / "identity/data_catalog_summary.json"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(
        json.dumps(
            {
                "version": "factorforge_web_data_catalog_summary_v2",
                "active_catalog_admission": catalog_admission,
                "catalogs": [
                    {
                        "catalog_name": catalog_path.name,
                        "catalog_sha256": container.hashlib.sha256(
                            catalog_path.read_bytes()
                        ).hexdigest(),
                        "entries": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog_projection = materialize_evo_child_catalog_projection(
        engine_root=worktree,
        workspace_root=workspace,
        approved_catalog_path=catalog_path,
        approved_catalog_admission=catalog_admission,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
    )
    calendar_projection = materialize_evo_child_calendar_projection(
        engine_root=worktree,
        workspace_root=workspace,
        trusted_calendar_path=(
            Path(__file__).parent
            / "fixtures/trusted_calendar/tushare_sse_trade_cal_19901219_20261231.csv"
        ),
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
    )
    admission = container.materialize_evo_child_container_admission(
        state_root=state,
        trust_root=trust,
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=workspace,
        worktree=worktree,
        engine_root=worktree,
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_trust_manifest_sha256=store.public_manifest[
            "manifest_sha256"
        ],
        container_runtime=runtime,
        image_digest=IMAGE,
        memory="512m",
        cpus="1.25",
        pids=128,
        tmpfs="size=64m,mode=1777,noexec,nosuid,nodev",
        engine_commit="f" * 40,
        catalog_snapshot_path=catalog_projection["snapshot_path"],
        catalog_projection_path=catalog_projection["projection_path"],
        calendar_projection_path=calendar_projection["projection_path"],
    )
    return {
        "worktree": worktree,
        "workspace": workspace,
        "manifest": manifest,
        "state": state,
        "trust": trust,
        "store": store,
        "runtime": runtime,
        "fake_state": fake_state,
        "admission": admission,
        "catalog": catalog_projection,
        "calendar": calendar_projection,
    }


def _logical(fixture: dict[str, Any], stage: str) -> list[str]:
    relative = container._STAGE_SCRIPTS[stage]
    if stage in {"run_step3b", "validate_step3b"}:
        return [sys.executable, relative, "--manifest", str(fixture["manifest"])]
    if stage == "run_step4":
        return [
            sys.executable,
            relative,
            "--manifest",
            str(fixture["manifest"]),
            "--expected-host-trust-manifest-sha256",
            fixture["store"].public_manifest["manifest_sha256"],
        ]
    return [
        sys.executable,
        relative,
        "--report-id",
        CHILD,
        "--expected-host-trust-manifest-sha256",
        fixture["store"].public_manifest["manifest_sha256"],
    ]


def _run(
    fixture: dict[str, Any],
    stage: str,
    *,
    timeout: float = 5,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return container.run_evo_child_agent_stage(
        fixture["admission"]["admission_path"],
        stage,
        _logical(fixture, stage),
        env
        or {
            "FACTORFORGE_ULTIMATE_RUN": "1",
            "FACTORFORGE_ROOT": str(fixture["workspace"]),
            "FACTORFORGE_STATE_CATALOG": fixture["catalog"]["snapshot_path"],
            "FACTORFORGE_DATA_CATALOG": fixture["catalog"]["snapshot_path"],
            "FACTORFORGE_TRUSTED_TRADE_CAL_CSV": fixture["calendar"]["snapshot_path"],
            "AWS_SECRET_ACCESS_KEY": "must-not-enter-container",
        },
        timeout,
        fixture["trust"],
        INSTALLATION,
    )


@pytest.mark.parametrize("stage", list(container._STAGE_SCRIPTS))
def test_signed_admission_restores_scrubbed_catalog_and_calendar_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    result = _run(
        fixture,
        stage,
        env={
            "PATH": "/usr/bin:/bin",
            "AWS_SECRET_ACCESS_KEY": "must-not-enter-container",
        },
    )
    assert result["stage_status"] == "SUCCEEDED"
    run_call = next(call for call in _calls(fixture["fake_state"]) if call[0] == "run")
    rendered = "\n".join(run_call)
    assert (
        f"FACTORFORGE_STATE_CATALOG={fixture['catalog']['snapshot_path']}"
        in rendered
    )
    assert (
        f"FACTORFORGE_DATA_CATALOG={fixture['catalog']['snapshot_path']}"
        in rendered
    )
    assert (
        "FACTORFORGE_TRUSTED_TRADE_CAL_CSV="
        f"{fixture['calendar']['snapshot_path']}" in rendered
    )
    assert "must-not-enter-container" not in rendered


def _validate_latest(
    fixture: dict[str, Any], *, required_stage: str | None = None
) -> dict[str, Any]:
    return container.validate_latest_evo_child_agent_termination(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["worktree"],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_pin=fixture["store"].public_manifest["manifest_sha256"],
        required_stage=required_stage,
    )


def _reconcile(fixture: dict[str, Any]) -> dict[str, Any]:
    return container.reconcile_evo_child_agent_stage_containers(
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["worktree"],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_pin=fixture["store"].public_manifest["manifest_sha256"],
    )


def _incident_payload(fixture: dict[str, Any]) -> dict[str, Any]:
    evidence = fixture["workspace"] / "incident-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    paths = {
        name: evidence / filename
        for name, filename in {
            "source": "source.csv",
            "panel": "panel.parquet",
            "metrics": "metrics.json",
            "runner": "runner.py",
        }.items()
    }
    for name, path in paths.items():
        path.write_text(name, encoding="utf-8")
    return build_oos_exposure_incident(
        workspace_root=fixture["workspace"],
        report_id=CHILD,
        factor_id="factor",
        frozen_oos_start="2022-09-02",
        frozen_oos_end="2025-07-11",
        frozen_oos_release_token_sha256="a" * 64,
        exposed_overlap_start="2025-01-02",
        exposed_overlap_end="2025-07-11",
        exposed_row_count=100,
        exposed_period_count=10,
        source_path=paths["source"],
        panel_path=paths["panel"],
        metrics_path=paths["metrics"],
        runner_path=paths["runner"],
        incident_at="2026-08-13T06:00:00Z",
    )


def _wait_for_path(path: Path, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


def _finalizer_guard_kwargs(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "state_root": fixture["state"],
        "trust_root": fixture["trust"],
        "installation_id": INSTALLATION,
        "job_id": JOB,
        "workspace_root": fixture["workspace"],
        "worktree": fixture["worktree"],
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_pin": fixture["store"].public_manifest[
            "manifest_sha256"
        ],
    }


def test_signed_admission_replays_runtime_scripts_resources_and_closed_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    result = container.validate_evo_child_container_admission(
        admission_path=fixture["admission"]["admission_path"],
        state_root=fixture["state"],
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
        job_id=JOB,
        workspace_root=fixture["workspace"],
        worktree=fixture["worktree"],
        parent_report_id=PARENT,
        child_report_id=CHILD,
        expected_host_pin=fixture["store"].public_manifest["manifest_sha256"],
    )
    admission = result["admission"]
    assert admission["issuer"]["kind"] == "host_admission"
    assert admission["policy"] == container._FIXED_POLICY
    assert admission["policy"]["network"] == "none"
    assert admission["container"]["image_digest"] == IMAGE
    assert admission["engine_identity"] == {
        "commit": "f" * 40,
        "source": "HOST_VALIDATED_DETACHED_WORKTREE",
    }
    assert set(admission["stages"]) == set(container._STAGE_SCRIPTS)

    script = fixture["worktree"] / container._STAGE_SCRIPTS["run_step3b"]
    script.write_text("# mutated\n", encoding="utf-8")
    with pytest.raises(container.EvoChildContainerError, match="stage_hash_mismatch"):
        container.validate_evo_child_container_admission(
            admission_path=fixture["admission"]["admission_path"],
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            workspace_root=fixture["workspace"],
            worktree=fixture["worktree"],
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_pin=fixture["store"].public_manifest["manifest_sha256"],
        )


def test_engine_commit_is_recomputed_from_the_admitted_worktree(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["/usr/bin/git", "init", "-q"],
        ["/usr/bin/git", "config", "user.email", "factorforge@example.invalid"],
        ["/usr/bin/git", "config", "user.name", "Factor Forge Test"],
    ):
        result = container.subprocess.run(command, cwd=repo, check=False)
        assert result.returncode == 0
    tracked = repo / "tracked.txt"
    tracked.write_text("engine\n", encoding="utf-8")
    for command in (
        ["/usr/bin/git", "add", "tracked.txt"],
        ["/usr/bin/git", "commit", "-qm", "engine"],
    ):
        result = container.subprocess.run(command, cwd=repo, check=False)
        assert result.returncode == 0
    head = container.subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert container._validate_engine_commit(repo, head) == head
    with pytest.raises(container.EvoChildContainerError, match="engine_commit_mismatch"):
        container._validate_engine_commit(repo, "0" * 40)


def test_image_reference_resolves_to_one_closed_digest_and_redacts_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    assert container.resolve_evo_child_container_image_digest(
        fixture["runtime"], "factorforge-agent:production"
    ) == "sha256:" + "b" * 64
    for mode, token in (
        ("malformed", "resolution_invalid"),
        ("multiple", "resolution_invalid"),
        ("failure", "resolution_failed"),
    ):
        (fixture["fake_state"] / "image_mode").write_text(mode, encoding="utf-8")
        with pytest.raises(container.EvoChildContainerError, match=token) as caught:
            container.resolve_evo_child_container_image_digest(
                fixture["runtime"], "factorforge-agent:production"
            )
        assert "PRIVATE DAEMON DETAIL" not in str(caught.value)


def test_success_uses_exact_network_mount_env_and_command_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    result = _run(fixture, "run_step4")
    assert result["stage_status"] == "SUCCEEDED"
    assert result["process_tree_absent"] is True
    assert result["factor_verdict"] == "NOT_ISSUED"
    assert result["command_result"]["status"] == "PASS"
    assert result["command_result"]["name"] == "run_step4"
    receipt = result["termination_receipt"]
    assert receipt["container"]["network"] == "none"
    assert receipt["container"]["pid_namespace"] == "private"
    assert receipt["process_tree"]["post_run"]["inspect_not_found"] is True
    assert receipt["process_tree"]["process_tree_absent"] is True
    assert receipt["execution"]["factor_verdict"] == "NOT_ISSUED"

    run_call = next(call for call in _calls(fixture["fake_state"]) if call[0] == "run")
    assert run_call[run_call.index("--network") + 1] == "none"
    assert "--pid=" in run_call
    mounts = [run_call[index + 1] for index, value in enumerate(run_call) if value == "--mount"]
    assert len(mounts) == 2
    assert "readonly" in mounts[0]
    assert "readonly" not in mounts[1]
    assert all(str(fixture["state"]) not in value for value in mounts)
    assert all(str(fixture["trust"]) not in value for value in mounts)
    env_values = [run_call[index + 1] for index, value in enumerate(run_call) if value == "--env"]
    assert "FACTORFORGE_AGENT_EXECUTION_NETWORK_POLICY=DENY" in env_values
    assert (
        f"FACTORFORGE_STATE_CATALOG={fixture['catalog']['snapshot_path']}"
        in env_values
    )
    assert (
        f"FACTORFORGE_TRUSTED_TRADE_CAL_CSV={fixture['calendar']['snapshot_path']}"
        in env_values
    )
    assert not any("AWS_SECRET_ACCESS_KEY" in value for value in env_values)
    assert IMAGE in run_call
    assert run_call[run_call.index(IMAGE) + 1 :] == ["python3", *_logical(fixture, "run_step4")[1:]]
    assert _validate_latest(fixture, required_stage="run_step4")["stage_succeeded"] is True


@pytest.mark.parametrize("authority", ["catalog", "calendar"])
def test_admission_replay_rejects_projected_authority_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    snapshot = Path(fixture[authority]["snapshot_path"])
    snapshot.chmod(0o600)
    snapshot.write_bytes(snapshot.read_bytes() + b"\n")
    with pytest.raises(container.EvoChildContainerError, match=authority):
        container.validate_evo_child_container_admission(
            admission_path=fixture["admission"]["admission_path"],
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id=INSTALLATION,
            job_id=JOB,
            workspace_root=fixture["workspace"],
            worktree=fixture["worktree"],
            parent_report_id=PARENT,
            child_report_id=CHILD,
            expected_host_pin=fixture["store"].public_manifest[
                "manifest_sha256"
            ],
        )


def test_stage_failure_still_has_signed_absent_process_tree_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    (fixture["fake_state"] / "mode").write_text("fail", encoding="utf-8")
    result = _run(fixture, "validate_step3b")
    assert result["returncode"] == 9
    assert result["stage_status"] == "FAILED"
    assert result["command_result"]["status"] == "FAIL"
    assert result["process_tree_absent"] is True
    latest = _validate_latest(fixture, required_stage="validate_step3b")
    assert latest["stage_succeeded"] is False
    assert latest["factor_verdict"] == "NOT_ISSUED"


def test_timeout_kills_runtime_group_then_removes_container_and_signs_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    (fixture["fake_state"] / "mode").write_text("timeout", encoding="utf-8")
    result = _run(fixture, "run_step3b", timeout=1)
    assert result["timed_out"] is True
    assert result["stage_status"] == "TIMED_OUT"
    assert result["process_tree_absent"] is True
    latest = _validate_latest(fixture, required_stage="run_step3b")
    assert latest["termination_receipt"]["execution"]["timed_out"] is True


def test_inspect_still_present_blocks_receipt_then_public_reconcile_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    (fixture["fake_state"] / "sticky").write_text("1", encoding="utf-8")
    with pytest.raises(container.EvoChildContainerError, match="process_tree_not_absent"):
        _run(fixture, "run_step3b")
    root = Path(fixture["admission"]["admission_path"]).parent
    assert list(root.glob("inflight__*.json"))
    assert not list(root.glob("termination__*.json"))

    (fixture["fake_state"] / "sticky").unlink()
    reconciliation = _reconcile(fixture)
    assert reconciliation["process_tree_absent"] is True
    assert reconciliation["retry_authorized"] is True
    assert len(reconciliation["reconciled"]) == 1
    with pytest.raises(container.EvoChildContainerError, match="termination_receipt_missing"):
        _validate_latest(fixture, required_stage="run_step3b")

    result = _run(fixture, "run_step3b")
    assert result["termination_receipt"]["attempt"] == 2
    assert _validate_latest(fixture, required_stage="run_step3b")["stage_succeeded"] is True


def test_command_mutation_and_state_path_injection_never_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    command = _logical(fixture, "run_step4")
    command.extend(["--trusted-data-prefetch-only"])
    with pytest.raises(container.EvoChildContainerError, match="logical_command_template"):
        container.run_evo_child_agent_stage(
            fixture["admission"]["admission_path"],
            "run_step4",
            command,
            {},
            5,
            fixture["trust"],
            INSTALLATION,
        )
    with pytest.raises(container.EvoChildContainerError, match="outside_mounts"):
        container.run_evo_child_agent_stage(
            fixture["admission"]["admission_path"],
            "run_step3b",
            _logical(fixture, "run_step3b"),
            {"FACTORFORGE_DATA_CACHE": str(fixture["state"])},
            5,
            fixture["trust"],
            INSTALLATION,
        )
    assert not any(call[0] == "run" for call in _calls(fixture["fake_state"]))


def test_required_stage_is_global_latest_and_unresolved_inflight_blocks_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _run(fixture, "validate_step4")
    (fixture["fake_state"] / "sticky").write_text("1", encoding="utf-8")
    with pytest.raises(container.EvoChildContainerError):
        _run(fixture, "run_step3b")
    with pytest.raises(container.EvoChildContainerError, match="unreconciled_inflight"):
        _validate_latest(fixture, required_stage="validate_step4")

    (fixture["fake_state"] / "sticky").unlink()
    _reconcile(fixture)
    with pytest.raises(container.EvoChildContainerError, match="latest_attempt_is_not_termination"):
        _validate_latest(fixture, required_stage="validate_step4")

    _run(fixture, "run_step3b")
    with pytest.raises(
        container.EvoChildContainerError,
        match="latest_termination_required_stage_mismatch",
    ):
        _validate_latest(fixture, required_stage="validate_step4")


def test_incident_writer_before_launch_wins_and_popen_is_never_reached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    payload = _incident_payload(fixture)
    writer_has_guard = threading.Event()
    release_writer = threading.Event()
    stage_requested_guard = threading.Event()
    writer_errors: list[BaseException] = []
    stage_errors: list[BaseException] = []

    real_append = incident_module._append_private_incident_event

    def paused_append(**kwargs):
        writer_has_guard.set()
        assert release_writer.wait(3)
        return real_append(**kwargs)

    monkeypatch.setattr(
        incident_module,
        "_append_private_incident_event",
        paused_append,
    )
    real_container_guard = container.oos_exposure_private_registry_guard

    @contextmanager
    def observed_container_guard(*args, **kwargs):
        stage_requested_guard.set()
        with real_container_guard(*args, **kwargs) as guard:
            yield guard

    monkeypatch.setattr(
        container,
        "oos_exposure_private_registry_guard",
        observed_container_guard,
    )

    def writer() -> None:
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=fixture["workspace"],
                payload=payload,
                trust_root=fixture["trust"],
                installation_id=INSTALLATION,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    def stage_runner() -> None:
        try:
            _run(fixture, "run_step3b")
        except BaseException as exc:  # pragma: no cover - asserted below
            stage_errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_has_guard.wait(2)
    stage_thread = threading.Thread(target=stage_runner)
    stage_thread.start()
    assert stage_requested_guard.wait(2)
    assert not any(call[0] == "run" for call in _calls(fixture["fake_state"]))
    release_writer.set()
    writer_thread.join(3)
    stage_thread.join(3)

    assert not writer_thread.is_alive()
    assert not stage_thread.is_alive()
    assert writer_errors == []
    assert len(stage_errors) == 1
    assert "oos_exposure_incident" in str(stage_errors[0])
    assert not any(call[0] == "run" for call in _calls(fixture["fake_state"]))
    root = Path(fixture["admission"]["admission_path"]).parent
    assert not list(root.glob("inflight__*.json"))
    assert not list(root.glob("termination__*.json"))


def test_incident_after_popen_blocks_termination_authority_but_cleanup_completes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    payload = _incident_payload(fixture)
    (fixture["fake_state"] / "mode").write_text("block", encoding="utf-8")
    stage_results: list[dict[str, Any]] = []
    stage_errors: list[BaseException] = []
    writer_errors: list[BaseException] = []
    writer_done = threading.Event()

    def stage_runner() -> None:
        try:
            stage_results.append(_run(fixture, "run_step3b"))
        except BaseException as exc:  # pragma: no cover - asserted below
            stage_errors.append(exc)

    def writer() -> None:
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=fixture["workspace"],
                payload=payload,
                trust_root=fixture["trust"],
                installation_id=INSTALLATION,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_done.set()

    stage_thread = threading.Thread(target=stage_runner)
    stage_thread.start()
    assert _wait_for_path(fixture["fake_state"] / "run_started")
    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    writer_completed_while_running = writer_done.wait(2)
    (fixture["fake_state"] / "release_run").write_text("1", encoding="utf-8")
    writer_thread.join(3)
    stage_thread.join(3)

    assert writer_completed_while_running is True
    assert not writer_thread.is_alive()
    assert not stage_thread.is_alive()
    assert writer_errors == []
    assert stage_results == []
    assert len(stage_errors) == 1
    assert "oos_exposure_incident" in str(stage_errors[0])
    root = Path(fixture["admission"]["admission_path"]).parent
    assert list(root.glob("inflight__*.json"))
    assert not list(root.glob("termination__*.json"))
    assert not list((fixture["fake_state"] / "objects").iterdir())


def test_final_authority_guard_serializes_termination_before_incident_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    payload = _incident_payload(fixture)
    termination_sign_entered = threading.Event()
    release_termination_sign = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    stage_results: list[dict[str, Any]] = []
    stage_errors: list[BaseException] = []
    writer_errors: list[BaseException] = []

    store_type = type(fixture["store"])
    real_sign = store_type.sign

    def paused_sign(self, issuer_kind, payload_to_sign):
        if (
            payload_to_sign.get("receipt_type")
            == container.CONTAINER_TERMINATION_TYPE
        ):
            termination_sign_entered.set()
            assert release_termination_sign.wait(3)
        return real_sign(self, issuer_kind, payload_to_sign)

    monkeypatch.setattr(store_type, "sign", paused_sign)

    def stage_runner() -> None:
        try:
            stage_results.append(_run(fixture, "run_step3b"))
        except BaseException as exc:  # pragma: no cover - asserted below
            stage_errors.append(exc)

    def writer() -> None:
        writer_started.set()
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=fixture["workspace"],
                payload=payload,
                trust_root=fixture["trust"],
                installation_id=INSTALLATION,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_done.set()

    stage_thread = threading.Thread(target=stage_runner)
    stage_thread.start()
    assert termination_sign_entered.wait(3)
    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_started.wait(1)
    assert not writer_done.wait(0.1)
    release_termination_sign.set()
    stage_thread.join(3)
    writer_thread.join(3)

    assert not stage_thread.is_alive()
    assert not writer_thread.is_alive()
    assert stage_errors == []
    assert writer_errors == []
    assert len(stage_results) == 1
    assert stage_results[0]["stage_status"] == "SUCCEEDED"
    assert writer_done.is_set()
    root = Path(fixture["admission"]["admission_path"]).parent
    assert len(list(root.glob("termination__*.json"))) == 1


def test_reconciliation_cleans_process_tree_but_never_authorizes_retry_after_incident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    payload = _incident_payload(fixture)
    (fixture["fake_state"] / "sticky").write_text("1", encoding="utf-8")
    with pytest.raises(
        container.EvoChildContainerError,
        match="container_process_tree_not_absent",
    ):
        _run(fixture, "run_step3b")
    root = Path(fixture["admission"]["admission_path"]).parent
    assert list(root.glob("inflight__*.json"))
    assert list((fixture["fake_state"] / "objects").iterdir())

    prepare_oos_exposure_incident_host_private(
        workspace_root=fixture["workspace"],
        payload=payload,
        trust_root=fixture["trust"],
        installation_id=INSTALLATION,
    )
    (fixture["fake_state"] / "sticky").unlink()
    with pytest.raises(container.EvoChildContainerError, match="oos_exposure_incident"):
        _reconcile(fixture)

    assert not list((fixture["fake_state"] / "objects").iterdir())
    assert not list(root.glob("reconciliation__*.json"))
    assert not list(root.glob("termination__*.json"))


def test_internal_cleanup_replay_rejects_missing_fake_and_stale_incident_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    admission = fixture["admission"]["admission"]
    kwargs = {
        "admission_path": fixture["admission"]["admission_path"],
        "state_root": fixture["state"],
        "trust_root": fixture["trust"],
        "installation_id": INSTALLATION,
        "job_id": JOB,
        "workspace_root": fixture["workspace"],
        "worktree": fixture["worktree"],
        "parent_report_id": PARENT,
        "child_report_id": CHILD,
        "expected_host_pin": admission[
            "expected_host_trust_manifest_sha256"
        ],
        "allow_oos_incident_for_cleanup": True,
    }
    for invalid in (None, object()):
        with pytest.raises(ValueError, match="private_registry_guard_invalid"):
            container._validate_evo_child_container_admission_impl(
                **kwargs,
                incident_guard=invalid,
            )
    with oos_exposure_private_registry_guard(
        fixture["trust"],
        installation_id=INSTALLATION,
    ) as guard:
        assert container._validate_evo_child_container_admission_impl(
            **kwargs,
            incident_guard=guard,
        )["verdict"] == "PASS"
        stale = guard
    with pytest.raises(ValueError, match="private_registry_guard_invalid"):
        container._validate_evo_child_container_admission_impl(
            **kwargs,
            incident_guard=stale,
        )


def test_oos_finalizer_guard_requires_a_live_outer_incident_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    _run(fixture, "validate_step4")
    kwargs = _finalizer_guard_kwargs(fixture)

    with pytest.raises(TypeError, match="_incident_guard"):
        container.guard_evo_child_oos_finalization(**kwargs)

    with oos_exposure_private_registry_guard(
        fixture["trust"],
        installation_id=INSTALLATION,
    ) as active_guard:
        with container.guard_evo_child_oos_finalization(
            **kwargs,
            _incident_guard=active_guard,
        ) as validated:
            assert validated["stage_name"] == "validate_step4"
            assert validated["stage_succeeded"] is True
        stale_guard = active_guard

    with pytest.raises(ValueError, match="private_registry_guard_invalid"):
        with container.guard_evo_child_oos_finalization(
            **kwargs,
            _incident_guard=stale_guard,
        ):
            pytest.fail("stale guard unexpectedly acquired finalizer authority")
