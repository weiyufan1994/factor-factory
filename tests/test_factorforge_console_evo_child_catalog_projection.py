from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from factor_factory.console import evo_child_container, run_service
from factor_factory.console.catalog_health import catalog_admission_projection
from factor_factory.console.evo_child_catalog import (
    EvoChildCatalogProjectionError,
    materialize_evo_child_calendar_projection,
    materialize_evo_child_catalog_projection,
    materialize_host_job_frozen_catalog_snapshot,
    resolve_host_job_frozen_catalog_snapshot,
    validate_materialized_evo_child_catalog_projection,
    validate_evo_child_catalog_projection,
)
from factor_factory.console.evo_resume import PROGRESS_CHILD_HANDOFF_AUTHORIZED
from factor_factory.console.private_job_root import (
    ensure_host_private_job_subdirectory,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store


PARENT = "CATALOG_PARENT"
CHILD = "CATALOG_PARENT__EVO_CHILD_001"
JOB = "job_catalog_projection_001"
INSTALLATION = "catalog-projection-host"
COMMIT = "a" * 40
DEPLOYED_COMMIT = "d" * 40


def _catalog_fixture(tmp_path: Path) -> tuple[Path, dict]:
    external = tmp_path / "external-authority"
    external.mkdir()
    catalog = external / "production_catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "catalog-v1",
                "datasets": [
                    {
                        "dataset_id": "clean_daily_bar",
                        "storage": "s3",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    admission = {
        "version": "factorforge_console_catalog_admission_v1",
        "verdict": "NOT_APPLICABLE",
        "admission_scope": "local_or_test_catalog_snapshot",
        "formal_dataset_qa_implied": False,
    }
    return catalog, admission


def _summary(workspace: Path, catalog: Path, admission: dict) -> None:
    path = workspace / "identity/data_catalog_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "factorforge_web_data_catalog_summary_v2",
                "active_catalog_admission": admission,
                "catalogs": [
                    {
                        "catalog_name": catalog.name,
                        "catalog_sha256": hashlib.sha256(
                            catalog.read_bytes()
                        ).hexdigest(),
                        "entries": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_external_catalog_and_calendar_project_into_read_only_engine_and_tamper_block(
    tmp_path: Path,
) -> None:
    engine = tmp_path / "allocated-worktree"
    workspace = engine / "factor_research/factor/research"
    workspace.mkdir(parents=True)
    catalog, admission = _catalog_fixture(tmp_path)
    _summary(workspace, catalog, admission)

    projected = materialize_evo_child_catalog_projection(
        engine_root=engine,
        workspace_root=workspace,
        approved_catalog_path=catalog,
        approved_catalog_admission=admission,
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
    )
    calendar = materialize_evo_child_calendar_projection(
        engine_root=engine,
        workspace_root=workspace,
        trusted_calendar_path=(
            Path(__file__).parent
            / "fixtures/trusted_calendar/tushare_sse_trade_cal_19901219_20261231.csv"
        ),
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
    )

    assert Path(projected["snapshot_path"]).is_relative_to(engine)
    assert not Path(projected["snapshot_path"]).is_relative_to(workspace)
    assert Path(calendar["snapshot_path"]).is_relative_to(engine)
    source_env = {
        "FACTORFORGE_STATE_CATALOG": projected["snapshot_path"],
        "FACTORFORGE_DATA_CATALOG": projected["snapshot_path"],
        "FACTORFORGE_TRUSTED_TRADE_CAL_CSV": calendar["snapshot_path"],
    }
    for stage in evo_child_container._STAGE_SCRIPTS:
        closed = evo_child_container._closed_environment(
            source_env, workspace=workspace, engine=engine
        )
        assert closed["FACTORFORGE_STATE_CATALOG"] == projected["snapshot_path"]
        assert closed["FACTORFORGE_TRUSTED_TRADE_CAL_CSV"] == calendar[
            "snapshot_path"
        ]
        assert stage in evo_child_container._STAGE_SCRIPTS

    Path(projected["snapshot_path"]).chmod(0o600)
    Path(projected["snapshot_path"]).write_text("{}", encoding="utf-8")
    with pytest.raises(EvoChildCatalogProjectionError, match="snapshot_changed"):
        validate_evo_child_catalog_projection(
            engine_root=engine,
            workspace_root=workspace,
            approved_catalog_path=catalog,
            approved_catalog_admission=admission,
            job_id=JOB,
            parent_report_id=PARENT,
            child_report_id=CHILD,
        )


def test_job_frozen_catalog_survives_current_refresh_and_projection_restart(
    tmp_path: Path,
) -> None:
    engine = tmp_path / "allocated-worktree"
    workspace = engine / "factor_research/factor/research"
    workspace.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir(mode=0o770)
    state.chmod(0o770)
    catalog, admission = _catalog_fixture(tmp_path)
    _summary(workspace, catalog, admission)
    original = catalog.read_bytes()
    frozen = materialize_host_job_frozen_catalog_snapshot(
        state_root=state,
        workspace_root=workspace,
        approved_catalog_path=catalog,
        job_id=JOB,
    )
    projected = materialize_evo_child_catalog_projection(
        engine_root=engine,
        workspace_root=workspace,
        approved_catalog_path=frozen["snapshot_path"],
        approved_catalog_admission=frozen["catalog_admission"],
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
    )

    catalog.write_text(
        json.dumps(
            {
                "schema_version": "catalog-v2",
                "datasets": [{"dataset_id": "new_hourly_catalog"}],
            }
        ),
        encoding="utf-8",
    )
    replay = resolve_host_job_frozen_catalog_snapshot(
        state_root=state,
        workspace_root=workspace,
        job_id=JOB,
    )
    assert Path(replay["snapshot_path"]).read_bytes() == original
    validated = validate_materialized_evo_child_catalog_projection(
        engine_root=engine,
        workspace_root=workspace,
        projection_path=projected["projection_path"],
        job_id=JOB,
        parent_report_id=PARENT,
        child_report_id=CHILD,
    )
    assert validated["snapshot_sha256"] == hashlib.sha256(original).hexdigest()


def test_new_job_generation_can_bind_refreshed_catalog_without_mutating_prior(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o750)
    state.chmod(0o750)
    catalog, admission = _catalog_fixture(tmp_path)
    hashes: list[str] = []
    for suffix in ("001", "002"):
        engine = tmp_path / f"allocated-worktree-{suffix}"
        workspace = engine / "factor_research/factor/research"
        workspace.mkdir(parents=True)
        _summary(workspace, catalog, admission)
        frozen = materialize_host_job_frozen_catalog_snapshot(
            state_root=state,
            workspace_root=workspace,
            approved_catalog_path=catalog,
            job_id=f"{JOB}_{suffix}",
        )
        hashes.append(frozen["snapshot_sha256"])
        catalog.write_text(
            json.dumps(
                {
                    "schema_version": f"catalog-v{suffix}",
                    "datasets": [{"dataset_id": f"dataset_{suffix}"}],
                }
            ),
            encoding="utf-8",
        )
    assert hashes[0] != hashes[1]


@pytest.mark.parametrize("mode", [0o750, 0o770])
def test_container_state_root_accepts_controlled_shared_modes_but_private_leaf_is_0700(
    tmp_path: Path, mode: int
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=mode)
    state.chmod(mode)
    root = evo_child_container._admission_root(
        state, JOB, CHILD, create=True
    )
    assert state.stat().st_mode & 0o777 == mode
    assert root.stat().st_mode & 0o777 == 0o700
    assert root.parent.stat().st_mode & 0o777 == 0o700


def test_container_state_root_rejects_world_access_and_symlinked_jobs(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    world.mkdir(mode=0o777)
    world.chmod(0o777)
    with pytest.raises(evo_child_container.EvoChildContainerError, match="unsafe_private_job_root"):
        evo_child_container._admission_root(world, JOB, CHILD, create=True)

    state = tmp_path / "state"
    state.mkdir(mode=0o770)
    state.chmod(0o770)
    target = tmp_path / "outside-jobs"
    target.mkdir()
    (state / "jobs").symlink_to(target, target_is_directory=True)
    with pytest.raises(evo_child_container.EvoChildContainerError, match="unsafe_private_job_root"):
        evo_child_container._admission_root(state, JOB, CHILD, create=True)


@pytest.mark.parametrize("state_mode", [0o750, 0o770])
def test_private_lifecycle_allocator_precedes_container_admission_under_umask_0007(
    tmp_path: Path,
    state_mode: int,
) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=state_mode)
    state.chmod(state_mode)
    prior_umask = __import__("os").umask(0o007)
    try:
        security = ensure_host_private_job_subdirectory(
            state,
            JOB,
            ("security",),
            create=True,
        )
        lifecycle = security / "lifecycle.json"
        lifecycle.write_text("{}\n", encoding="utf-8")
        lifecycle.chmod(0o600)
        admission = evo_child_container._admission_root(
            state,
            JOB,
            CHILD,
            create=True,
        )
    finally:
        __import__("os").umask(prior_umask)

    assert (state / "jobs").stat().st_mode & 0o777 in {0o750, 0o770}
    assert (state / "jobs" / JOB).stat().st_mode & 0o777 == 0o700
    assert security.stat().st_mode & 0o777 == 0o700
    assert admission.stat().st_mode & 0o777 == 0o700


def test_production_caller_uses_allocated_worktree_and_never_external_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_repo = tmp_path / "source-control"
    source_repo.mkdir()
    worktree = tmp_path / "allocated-worktree"
    workspace = worktree / "factor_research/factor/research"
    workspace.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir(mode=0o770)
    state.chmod(0o770)
    trust = state / "research-org-trust"
    ensure_runtime_trust_store(trust, installation_id=INSTALLATION)
    catalog, admission = _catalog_fixture(tmp_path)
    _summary(workspace, catalog, admission)
    for relative in (
        run_service.EVO_CHILD_MATERIALIZER_RELATIVE,
        run_service.FORMAL_ENGINE_SCRIPTS["run_factorforge_ultimate"],
    ):
        script = worktree / relative
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# pinned engine script\n", encoding="utf-8")
    calendar = (
        Path(__file__).parent
        / "fixtures/trusted_calendar/tushare_sse_trade_cal_19901219_20261231.csv"
    )
    monkeypatch.setenv("FACTORFORGE_TRUSTED_TRADE_CAL_CSV", str(calendar))
    observed: dict = {}

    def validate_checkout(path: Path, commit: str) -> str:
        observed["checkout"] = Path(path)
        assert commit == COMMIT
        return COMMIT

    monkeypatch.setattr(run_service, "_validate_formal_engine_checkout", validate_checkout)
    monkeypatch.setattr(
        run_service,
        "_git_blob_sha256",
        lambda root, _commit, relative: run_service._sha256(Path(root) / relative),
    )
    monkeypatch.setattr(
        run_service,
        "resolve_evo_child_container_image_digest",
        lambda *_args: "sha256:" + "b" * 64,
    )

    def capture_prepare(**kwargs):
        observed.update(kwargs)
        return {
            "status": run_service.CHILD_EXECUTION_READY,
            "parent_report_id": PARENT,
            "child_report_id": CHILD,
            "checkpoint_path": str(state / "ready.json"),
            "catalog_snapshot_path": str(kwargs["catalog_snapshot_path"]),
            "calendar_snapshot_path": str(kwargs["calendar_snapshot_path"]),
        }

    monkeypatch.setattr(run_service, "prepare_evo_child_execution", capture_prepare)
    config = SimpleNamespace(
        state_root=state,
        source_repo=source_repo,
        data_catalogs=(catalog,),
        catalog_receipt=None,
        aws_readonly_role_name="",
        auth_disabled=True,
        installation_id=INSTALLATION,
        container_runtime="python",
        agent_container_image="unused-image",
        container_memory="512m",
        container_cpus=1.0,
        container_pids_limit=128,
        container_tmpfs_size="64m",
        agent_timeout_seconds=300,
    )
    assert catalog_admission_projection(config) == admission
    service = SimpleNamespace(
        config=config,
        agent_adapter=object(),
        _expected_base_commit=DEPLOYED_COMMIT,
    )
    job = SimpleNamespace(
        report_id=PARENT,
        job_id=JOB,
        base_commit=COMMIT,
        worktree_path=str(worktree),
        workspace_path=str(workspace),
    )
    result = run_service.ResearchRunService._prepare_evo_v2_child_execution_ready(
        service,
        job,
        worktree=worktree,
        workspace=workspace,
        resume_trust={
            "evo_v2_external_progress": {
                "status": PROGRESS_CHILD_HANDOFF_AUTHORIZED,
                "report_id": PARENT,
                "child_report_id": CHILD,
                "start_step": None,
            },
            "ultimate_proof_sha256": "c" * 64,
        },
        child_report_id=CHILD,
    )
    assert observed["checkout"] == worktree
    assert observed["engine_root"] == worktree
    assert observed["research_base_commit"] == COMMIT
    assert observed["execution_engine_commit"] == COMMIT
    assert Path(result["catalog_snapshot_path"]).is_relative_to(worktree)
    assert not Path(result["catalog_snapshot_path"]).is_relative_to(workspace)
    assert Path(result["catalog_snapshot_path"]) != catalog
