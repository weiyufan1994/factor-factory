from __future__ import annotations

import json
import importlib
import os
import subprocess
import sys
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pytest

import factor_factory.console.web_factor_proof as web_proof
import factor_factory.console.evo_child_container as child_container
import factor_factory.evo_oos as evo_oos
from scripts import finalize_factorforge_web_factor_proof as finalizer_cli
from factor_factory.evo_child_preregistration import _parent_contract_context
from factor_factory.evo_oos import (
    BLOCK_OOS_ALLOCATION,
    OOS_ALLOCATION_AUTHORITY_SECURE,
    allocate_fresh_child_oos,
    build_and_allocate_fresh_child_oos,
    oos_allocation_path,
    oos_allocation_receipt_path,
    oos_host_trust_manifest_path,
    oos_registry_path,
    private_oos_locator_path,
    resolve_host_private_oos_carrier,
    sha256_file,
    validate_fresh_child_oos_allocation,
    validate_oos_registry,
)
from tests.test_factorforge_pre_oos_human_bridge import (
    CHILD_ID,
    INSTALLATION_ID,
    REPORT_ID,
    _admissions_root,
    _complete_transfer_use_formal,
    _host_trust_root,
    _prepare_minimal,
    _write_parent_web_authority,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts/allocate_factorforge_evo_child_oos.py"


@pytest.fixture(autouse=True)
def _incident_host_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root = _host_trust_root(tmp_path)
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_EXPOSURE_TRUST_ROOT", str(trust_root)
    )
    monkeypatch.setenv(
        "FACTORFORGE_OOS_HOST_EXPOSURE_INSTALLATION_ID", INSTALLATION_ID
    )


def _ready_authority(root: Path) -> tuple[Path, Path]:
    _synthesis, _selected, minimal, _council = _prepare_minimal(root)
    _complete_transfer_use_formal(root, minimal)
    plan = _write_parent_web_authority(root)
    contracts = _parent_contract_context(root=root, parent_report_id=REPORT_ID)
    dates = [
        item
        for item in contracts["calendar"]["dates"]
        if "2026-04-01" <= item <= "2026-09-30"
    ]
    required = set(plan["data_plan"]["daily_fields"])
    required.update(
        contracts["metric_verifier_spec"]["panel"].get(
            "source_control_columns", []
        )
    )
    rows: list[dict] = []
    for asset_offset, code in enumerate(("000001.SZ", "000002.SZ")):
        for index, trade_date in enumerate(dates):
            close = 10.0 + asset_offset + index * 0.01
            full = {
                "ts_code": code,
                "trade_date": trade_date,
                "open": close * 0.999,
                "pre_close": close - 0.01,
                "close": close,
                "pct_chg": 0.1,
                "turnover_rate": 1.0,
                "ln_mcap_free": 10.0 + asset_offset,
                "volume_ratio": 1.0,
            }
            rows.append(
                {
                    key: value
                    for key, value in full.items()
                    if key in required or key in {"ts_code", "trade_date", "close"}
                }
            )
    private_root = root.parent / f".{root.name}-atomic-oos-private"
    private_root.mkdir(mode=0o700)
    carrier = private_root / "sealed-carrier.parquet"
    pd.DataFrame(rows).to_parquet(carrier, index=False)
    carrier.chmod(0o600)
    return private_root, carrier


def _build(root: Path, private_root: Path, carrier: Path) -> dict:
    return build_and_allocate_fresh_child_oos(
        workspace_root=root,
        allocation_id="allocation_evo_child_001",
        report_id=CHILD_ID,
        parent_report_id=REPORT_ID,
        oos_start="2026-04-01",
        oos_end="2026-09-30",
        sealed_oos_carrier_path=carrier,
        sealed_oos_private_root=private_root,
        expected_registry_sha256=None,
        trust_root=_host_trust_root(root),
        installation_id=INSTALLATION_ID,
        admissions_root=_admissions_root(root),
    )


def test_host_private_builder_derives_authority_and_replays_atomically(
    tmp_path: Path,
) -> None:
    private_root, carrier = _ready_authority(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        initial = list(
            executor.map(
                lambda _unused: _build(tmp_path, private_root, carrier),
                range(2),
            )
        )
    assert sorted(item["status"] for item in initial) == [
        "ALLOCATED",
        "IDENTICAL_REPLAY",
    ]
    first = initial[0]
    assert first["sealed_carrier_sha256"] == sha256_file(carrier)
    assert first["dataset_snapshot_sha256"] != first["sealed_carrier_sha256"]
    assert first["oos_panel_published"] is False
    assert first["private_locator_status"] == "HOST_PRIVATE_PERSISTED"
    assert "sealed_oos_carrier_path" not in first
    assert "sealed_oos_private_root" not in first
    allocation = json.loads(
        oos_allocation_path(tmp_path, CHILD_ID).read_text(encoding="utf-8")
    )
    assert allocation["allocation_authority_mode"] == OOS_ALLOCATION_AUTHORITY_SECURE
    assert allocation["build_authority_sha256"] == first["build_authority_sha256"]
    receipt = json.loads(
        oos_allocation_receipt_path(tmp_path, CHILD_ID).read_text(encoding="utf-8")
    )
    assert receipt["build_authority"]["authority_refs"]
    assert receipt["build_authority"]["calendar_authority"]["snapshot_id"]
    assert receipt["build_authority"]["universe_binding"]
    public_bytes = (
        oos_allocation_path(tmp_path, CHILD_ID).read_bytes()
        + oos_allocation_receipt_path(tmp_path, CHILD_ID).read_bytes()
        + oos_registry_path(tmp_path).read_bytes()
    )
    assert str(carrier).encode() not in public_bytes
    assert str(private_root).encode() not in public_bytes
    locator_path = private_oos_locator_path(
        _host_trust_root(tmp_path),
        first["private_locator_id"],
    )
    assert locator_path.is_file()
    assert tmp_path not in locator_path.parents
    assert locator_path.stat().st_mode & 0o077 == 0
    resolved = resolve_host_private_oos_carrier(
        workspace_root=tmp_path,
        trust_root=_host_trust_root(tmp_path),
        installation_id=INSTALLATION_ID,
        allocation_id="allocation_evo_child_001",
        report_id=CHILD_ID,
        parent_report_id=REPORT_ID,
        expected_host_trust_manifest_sha256=json.loads(
            oos_host_trust_manifest_path(tmp_path).read_text(encoding="utf-8")
        )["manifest_sha256"],
        expected_sealed_carrier_sha256=first["sealed_carrier_sha256"],
        expected_dataset_snapshot_sha256=first["dataset_snapshot_sha256"],
        expected_build_authority_sha256=first["build_authority_sha256"],
        agent_visible_roots=[tmp_path, REPO_ROOT],
    )
    assert resolved["sealed_oos_carrier_path"] == carrier.resolve()
    assert resolved["sealed_oos_private_root"] == private_root.resolve()
    assert validate_fresh_child_oos_allocation(
        root=tmp_path,
        parent_report_id=REPORT_ID,
        child_report_id=CHILD_ID,
        allocation_id="allocation_evo_child_001",
        allocation_ref=oos_allocation_path(tmp_path, CHILD_ID)
        .relative_to(tmp_path)
        .as_posix(),
        incident_trust_root=_host_trust_root(tmp_path),
        incident_installation_id=INSTALLATION_ID,
    ) == []

    assert _build(tmp_path, private_root, carrier)["status"] == "IDENTICAL_REPLAY"
    registry = json.loads(oos_registry_path(tmp_path).read_text(encoding="utf-8"))
    assert len(registry["events"]) == 1
    assert validate_oos_registry(registry, workspace_root=tmp_path) == []


def test_private_locator_restarts_fail_closed_after_carrier_change(
    tmp_path: Path,
) -> None:
    private_root, carrier = _ready_authority(tmp_path)
    allocated = _build(tmp_path, private_root, carrier)

    def resolve() -> dict:
        trust_manifest_sha256 = json.loads(
            oos_host_trust_manifest_path(tmp_path).read_text(encoding="utf-8")
        )["manifest_sha256"]
        return resolve_host_private_oos_carrier(
            workspace_root=tmp_path,
            trust_root=_host_trust_root(tmp_path),
            installation_id=INSTALLATION_ID,
            allocation_id="allocation_evo_child_001",
            report_id=CHILD_ID,
            parent_report_id=REPORT_ID,
            expected_host_trust_manifest_sha256=trust_manifest_sha256,
            expected_sealed_carrier_sha256=allocated[
                "sealed_carrier_sha256"
            ],
            expected_dataset_snapshot_sha256=allocated[
                "dataset_snapshot_sha256"
            ],
            expected_build_authority_sha256=allocated[
                "build_authority_sha256"
            ],
            agent_visible_roots=[tmp_path, REPO_ROOT],
        )

    locator_path = private_oos_locator_path(
        _host_trust_root(tmp_path),
        allocated["private_locator_id"],
    )
    locator_hardlink = tmp_path / "runs" / "private-locator-hardlink.json"
    locator_hardlink.parent.mkdir(parents=True, exist_ok=True)
    os.link(locator_path, locator_hardlink)
    with pytest.raises(ValueError, match="private_locator_unsafe"):
        resolve()
    locator_hardlink.unlink()

    locator_path.chmod(0o644)
    with pytest.raises(ValueError, match="private_locator_unsafe") as unsafe:
        resolve()
    assert str(locator_path) not in str(unsafe.value)
    locator_path.chmod(0o600)

    missing_locator = locator_path.with_suffix(".missing")
    locator_path.rename(missing_locator)
    with pytest.raises(ValueError, match="private_locator_unsafe") as missing:
        resolve()
    assert str(locator_path) not in str(missing.value)
    missing_locator.rename(locator_path)

    hardlink = tmp_path / "runs" / "post-allocation-carrier-hardlink.parquet"
    hardlink.parent.mkdir(parents=True, exist_ok=True)
    os.link(carrier, hardlink)
    with pytest.raises(ValueError, match="private_locator_carrier_unsafe"):
        resolve()
    hardlink.unlink()

    real_private_root = private_root.with_name(f"{private_root.name}-real")
    private_root.rename(real_private_root)
    private_root.symlink_to(real_private_root, target_is_directory=True)
    with pytest.raises(ValueError, match="private_locator_carrier_symlink"):
        resolve()
    private_root.unlink()
    real_private_root.rename(private_root)


def test_allocate_restart_finalizer_resolves_private_locator_without_path_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_root, carrier = _ready_authority(tmp_path)
    allocated = _build(tmp_path, private_root, carrier)
    allocation = json.loads(
        oos_allocation_path(tmp_path, CHILD_ID).read_text(encoding="utf-8")
    )
    contracts = _parent_contract_context(
        root=tmp_path,
        parent_report_id=REPORT_ID,
    )
    calendar = contracts["calendar"]
    signal_dates = [
        item
        for item in calendar["dates"]
        if "2026-04-01" <= item <= "2026-09-30"
    ][:-2]
    plan = json.loads(json.dumps(contracts["plan"]))
    plan["identity"]["report_id"] = CHILD_ID
    plan["research_object"]["formula_or_law"] = (
        json.loads(
            oos_allocation_receipt_path(tmp_path, CHILD_ID).read_text(
                encoding="utf-8"
            )
        )["build_authority"]["selected_revision"]["child_formula"]
    )
    plan["evidence_policy"]["oos_start"] = "2026-04-01"
    plan["evidence_policy"]["oos_end"] = "2026-09-30"
    spec = evo_oos._project_allocation_metric_spec(
        root=tmp_path,
        parent_spec=contracts["metric_verifier_spec"],
        child_report_id=CHILD_ID,
        oos_start="2026-04-01",
        oos_end="2026-09-30",
        signal_dates=signal_dates,
        sealed_token_sha256=allocation["sealed_token_sha256"],
    )
    output = web_proof.web_factor_proof_paths(tmp_path, CHILD_ID)["panel"]

    # Model a hard process stop after writing the private full-panel stage.
    crashed_stage = web_proof._prepare_host_private_oos_staging(
        private_parent=private_root,
        report_id=CHILD_ID,
        output=output,
    )
    (crashed_stage / output.name).write_bytes(b"crash-residue")

    restarted_cli = importlib.reload(finalizer_cli)
    trust_pin = json.loads(
        oos_host_trust_manifest_path(tmp_path).read_text(encoding="utf-8")
    )["manifest_sha256"]
    monkeypatch.setattr(
        restarted_cli,
        "resolve_report_scoped_web_research_plan",
        lambda *_args, **_kwargs: {
            "plan": plan,
            "allocation": allocation,
            "parent_report_id": REPORT_ID,
        },
    )
    monkeypatch.setattr(
        restarted_cli,
        "validate_materialized_web_research",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )

    gate_order: list[str] = []
    termination_guard_active = False

    @contextmanager
    def termination_guard(**_kwargs):
        nonlocal termination_guard_active
        gate_order.append("termination")
        termination_guard_active = True
        try:
            yield {
                "stage_name": "validate_step4",
                "stage_succeeded": True,
                "process_tree_absent": True,
                "termination_receipt_id": "5" * 64,
                "termination_receipt_sha256": "9" * 64,
                "termination_receipt": {
                    "attempt": 4,
                    "admission_ref": {"receipt_id": "4" * 64},
                    "inflight_ref": {"receipt_id": "3" * 64},
                    "container": {
                        "image_digest": "sha256:" + "8" * 64,
                        "mounts": [],
                        "network": "none",
                    },
                    "command": {"logical_sha256": "7" * 64},
                    "workspace_tree": {
                        "post_run": {"tree_sha256": "6" * 64}
                    },
                },
            }
        finally:
            termination_guard_active = False

    monkeypatch.setattr(
        restarted_cli,
        "guard_evo_child_oos_finalization",
        termination_guard,
    )
    real_resolver = restarted_cli.resolve_host_private_oos_carrier

    def tracked_resolver(**kwargs):
        assert termination_guard_active is True
        gate_order.append("locator")
        return real_resolver(**kwargs)

    monkeypatch.setattr(
        restarted_cli,
        "resolve_host_private_oos_carrier",
        tracked_resolver,
    )

    def publish(**kwargs):
        assert termination_guard_active is True
        assert kwargs["sealed_oos_carrier_path"] == carrier.resolve()
        assert kwargs["sealed_oos_private_root"] == private_root.resolve()
        assert kwargs["host_agent_termination_authority"]["stage_name"] == (
            "validate_step4"
        )
        panel = web_proof._build_oos_panel(
            root=tmp_path,
            report_id=CHILD_ID,
            spec=spec,
            calendar=calendar,
            output=output,
            plan=plan,
            sealed_oos_carrier_path=kwargs["sealed_oos_carrier_path"],
            sealed_oos_private_root=kwargs["sealed_oos_private_root"],
            sealed_oos_agent_visible_roots=kwargs[
                "sealed_oos_agent_visible_roots"
            ],
            expected_dataset_snapshot_sha256=kwargs[
                "expected_dataset_snapshot_sha256"
            ],
            expected_sealed_carrier_sha256=kwargs[
                "expected_sealed_carrier_sha256"
            ],
        )
        return {"status": "PASS", "report_id": CHILD_ID, "panel": panel}

    monkeypatch.setattr(restarted_cli, "finalize_web_factor_proof", publish)
    public_argv = [
        "finalize_factorforge_web_factor_proof.py",
        "--workspace-root",
        str(tmp_path),
        "--report-id",
        CHILD_ID,
        "--expected-host-trust-manifest-sha256",
        trust_pin,
        "--resolve-host-private-oos",
    ]
    monkeypatch.setattr(sys, "argv", public_argv)
    monkeypatch.setenv(
        restarted_cli.OOS_HOST_TRUST_ROOT_ENV,
        str(_host_trust_root(tmp_path)),
    )
    monkeypatch.setenv(
        restarted_cli.OOS_HOST_INSTALLATION_ID_ENV,
        INSTALLATION_ID,
    )
    monkeypatch.setenv(
        restarted_cli.EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
        str(tmp_path.parent / f".{tmp_path.name}-container-state"),
    )
    monkeypatch.setenv(
        restarted_cli.EVO_CHILD_CONTAINER_JOB_ID_ENV,
        "job-evo-child-001",
    )
    monkeypatch.delenv(
        restarted_cli.EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
        raising=False,
    )
    assert restarted_cli.main() == 1
    missing_termination = capsys.readouterr().err
    assert "HOST_TERMINATION_CREDENTIALS_REQUIRED" in missing_termination
    assert str(private_root) not in missing_termination
    monkeypatch.setenv(
        restarted_cli.EVO_CHILD_CONTAINER_STATE_ROOT_ENV,
        str(tmp_path.parent / f".{tmp_path.name}-container-state"),
    )

    @contextmanager
    def blocked_termination_guard(**_kwargs):
        raise RuntimeError(
            str(tmp_path.parent / f".{tmp_path.name}-container-state")
        )
        yield  # pragma: no cover - contextmanager shape only

    monkeypatch.setattr(
        restarted_cli,
        "guard_evo_child_oos_finalization",
        blocked_termination_guard,
    )
    assert restarted_cli.main() == 1
    blocked_termination = capsys.readouterr().err
    assert "HOST_TERMINATION_GATE_FAILED" in blocked_termination
    assert str(tmp_path.parent) not in blocked_termination
    monkeypatch.setattr(
        restarted_cli,
        "guard_evo_child_oos_finalization",
        termination_guard,
    )
    missing_carrier = carrier.with_suffix(".missing")
    carrier.rename(missing_carrier)
    assert restarted_cli.main() == 1
    assert termination_guard_active is False
    failure = capsys.readouterr().err
    assert "PRIVATE_LOCATOR_RESOLUTION_FAILED" in failure
    assert str(carrier) not in failure
    assert str(private_root) not in failure
    assert str(_host_trust_root(tmp_path)) not in failure
    missing_carrier.rename(carrier)
    assert restarted_cli.main() == 0
    assert termination_guard_active is False
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "PASS"
    assert output.is_file()
    assert sha256_file(output) == allocated["dataset_snapshot_sha256"]
    assert not crashed_stage.exists()
    assert gate_order[-2:] == ["termination", "locator"]
    command_text = " ".join(public_argv)
    assert str(carrier) not in command_text
    assert str(private_root) not in command_text
    assert str(_host_trust_root(tmp_path)) not in command_text

    explicit_private_argv = [
        "finalize_factorforge_web_factor_proof.py",
        "--workspace-root",
        str(tmp_path),
        "--report-id",
        CHILD_ID,
        "--expected-host-trust-manifest-sha256",
        trust_pin,
        "--sealed-oos-carrier",
        str(carrier),
        "--sealed-oos-private-root",
        str(private_root),
    ]
    monkeypatch.setattr(sys, "argv", explicit_private_argv)
    assert restarted_cli.main() == 1
    explicit_failure = capsys.readouterr().err
    assert "PRIVATE_LOCATOR_REQUIRED" in explicit_failure
    assert str(carrier) not in explicit_failure
    assert str(private_root) not in explicit_failure

    # A fully published proof is a pure validation replay.  It must remain
    # restartable after Host deletes the now-unneeded private carrier, while
    # still replaying the signed termination receipt, and must never try to
    # reconstruct OOS data.
    finalization = web_proof.web_factor_proof_paths(tmp_path, CHILD_ID)[
        "finalization"
    ]
    finalization.write_text("{}\n", encoding="utf-8")
    carrier.unlink()

    def replay_without_private_oos(**kwargs):
        assert kwargs["sealed_oos_carrier_path"] is None
        assert kwargs["sealed_oos_private_root"] is None
        return {"status": "PASS", "report_id": CHILD_ID, "replay": True}

    monkeypatch.setattr(
        restarted_cli,
        "finalize_web_factor_proof",
        replay_without_private_oos,
    )
    replay_argv = [
        "finalize_factorforge_web_factor_proof.py",
        "--workspace-root",
        str(tmp_path),
        "--report-id",
        CHILD_ID,
        "--expected-host-trust-manifest-sha256",
        trust_pin,
    ]
    monkeypatch.setattr(sys, "argv", replay_argv)
    assert restarted_cli.main() == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay == {"report_id": CHILD_ID, "replay": True, "status": "PASS"}


def test_builder_attacks_missing_carrier_projection_mismatch_and_workspace_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root, carrier = _ready_authority(tmp_path)
    missing = private_root / "missing.parquet"
    with pytest.raises((FileNotFoundError, ValueError)):
        _build(tmp_path, private_root, missing)

    legacy_private_stage = private_root / ".factorforge_derived_oos_legacy-crash"
    legacy_private_stage.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="legacy Host-private OOS staging exists"):
        _build(tmp_path, private_root, carrier)
    legacy_private_stage.rmdir()

    leaked_hardlink = tmp_path / "runs" / "agent-visible-carrier.parquet"
    leaked_hardlink.parent.mkdir(parents=True, exist_ok=True)
    os.link(carrier, leaked_hardlink)
    with pytest.raises(ValueError, match="sealed_carrier_unsafe"):
        _build(tmp_path, private_root, carrier)
    leaked_hardlink.unlink()

    real_allocate = evo_oos._allocate_fresh_child_oos

    def crash_before_cas(**_kwargs):
        raise RuntimeError("simulated allocation crash")

    monkeypatch.setattr(evo_oos, "_allocate_fresh_child_oos", crash_before_cas)
    with pytest.raises(RuntimeError, match="simulated allocation crash"):
        _build(tmp_path, private_root, carrier)
    assert list(private_root.glob(".factorforge_oos_build__*.staging")) == []
    assert not oos_registry_path(tmp_path).exists()
    monkeypatch.setattr(evo_oos, "_allocate_fresh_child_oos", real_allocate)

    real_projection = web_proof.project_host_private_sealed_oos_panel

    def mismatched_projection(**kwargs):
        result = real_projection(**kwargs)
        return {**result, "panel_sha256": "0" * 64}

    monkeypatch.setattr(
        web_proof,
        "project_host_private_sealed_oos_panel",
        mismatched_projection,
    )
    with pytest.raises(ValueError, match="derived_panel_projection_binding"):
        _build(tmp_path, private_root, carrier)
    assert not oos_registry_path(tmp_path).exists()
    monkeypatch.setattr(
        web_proof,
        "project_host_private_sealed_oos_panel",
        real_projection,
    )

    output = web_proof.web_factor_proof_paths(tmp_path, CHILD_ID)["panel"]
    output.parent.mkdir(parents=True, exist_ok=True)
    legacy_temp = output.with_name(f".{output.name}.123.tmp")
    legacy_temp.write_bytes(b"full-panel-crash-residue")
    recovery = web_proof.web_factor_proof_oos_recovery_state(
        tmp_path,
        CHILD_ID,
    )
    assert recovery["recovery_required"] is True
    assert recovery["allowed_execution"] == "HOST_FINALIZER_OR_TERMINAL_ONLY"
    assert legacy_temp.relative_to(tmp_path).as_posix() in recovery[
        "artifact_refs"
    ]
    with pytest.raises(ValueError, match="legacy hidden OOS workspace temp exists"):
        web_proof._build_oos_panel(
            root=tmp_path,
            report_id=CHILD_ID,
            spec={},
            calendar={},
            output=output,
        )
    assert not output.exists()


def test_direct_hash_api_and_old_cli_hash_arguments_are_not_production_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="direct_hash_allocator_forbidden"):
        allocate_fresh_child_oos(
            workspace_root=tmp_path,
            allocation_id="allocation_child_001",
            report_id="CHILD_001",
            parent_report_id="PARENT_001",
            dataset_snapshot_sha256="a" * 64,
            oos_start="2026-01-01",
            oos_end="2026-06-30",
            sealed_token_sha256="b" * 64,
            expected_registry_sha256=None,
            trust_root=tmp_path.parent / "private-trust",
            installation_id="test-installation",
        )
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--workspace-root",
            str(tmp_path),
            "--allocation-id",
            "allocation_child_001",
            "--report-id",
            "CHILD_001",
            "--parent-report-id",
            "PARENT_001",
            "--oos-start",
            "2026-01-01",
            "--oos-end",
            "2026-06-30",
            "--sealed-oos-carrier",
            str(tmp_path / "carrier.parquet"),
            "--sealed-oos-private-root",
            str(tmp_path.parent / "private-oos"),
            "--expected-registry-sha256",
            "ABSENT",
            "--trust-root",
            str(tmp_path.parent / "private-trust"),
            "--installation-id",
            "test-installation",
            "--dataset-snapshot-sha256",
            "a" * 64,
            "--sealed-token-sha256",
            "b" * 64,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "unrecognized arguments" in completed.stderr


def test_finalizer_rejects_hardlinked_private_carrier_and_existing_panel(
    tmp_path: Path,
) -> None:
    private_root, carrier = _ready_authority(tmp_path)
    contracts = _parent_contract_context(root=tmp_path, parent_report_id=REPORT_ID)
    plan = dict(contracts["plan"])
    plan["research_object"]["formula_or_law"] = "-(pre_close / open - 1.0)"
    plan["evidence_policy"]["oos_start"] = "2026-04-01"
    plan["evidence_policy"]["oos_end"] = "2026-09-30"
    spec = json.loads(json.dumps(contracts["metric_verifier_spec"]))
    dates = [
        item
        for item in contracts["calendar"]["dates"]
        if "2026-04-01" <= item <= "2026-09-30"
    ]
    window = spec["window_contract"]
    window.update(
        {
            "oos_window": "2026-04-01/2026-09-30",
            "observed_start_date": dates[0],
            "observed_end_date": dates[-3],
            "oos_release_token_hash": "a" * 64,
        }
    )
    output = private_root / "private-derived.parquet"
    leaked = tmp_path / "runs" / "carrier-hardlink.parquet"
    leaked.parent.mkdir(parents=True, exist_ok=True)
    os.link(carrier, leaked)
    with pytest.raises(ValueError, match="sealed carrier unsafe"):
        web_proof.project_host_private_sealed_oos_panel(
            workspace_root=tmp_path,
            report_id=CHILD_ID,
            plan=plan,
            metric_verifier_spec=spec,
            calendar=contracts["calendar"],
            sealed_oos_carrier_path=carrier,
            sealed_oos_private_root=private_root,
            expected_sealed_carrier_sha256=sha256_file(carrier),
            private_output_path=output,
        )
    leaked.unlink()

    projection = web_proof.project_host_private_sealed_oos_panel(
        workspace_root=tmp_path,
        report_id=CHILD_ID,
        plan=plan,
        metric_verifier_spec=spec,
        calendar=contracts["calendar"],
        sealed_oos_carrier_path=carrier,
        sealed_oos_private_root=private_root,
        expected_sealed_carrier_sha256=sha256_file(carrier),
        private_output_path=output,
    )
    expected_panel_sha256 = projection["panel_sha256"]
    output.unlink()

    # Existing workspace publication must also be a unique inode before replay.
    output = tmp_path / "runs" / CHILD_ID / f"factor_proof_panel__{CHILD_ID}.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": [1]}).to_parquet(output, index=False)
    hardlink = private_root / "workspace-panel-hardlink.parquet"
    os.link(output, hardlink)
    with pytest.raises(ValueError, match="OOS proof panel is hardlinked"):
        web_proof._build_oos_panel(
            root=tmp_path,
            report_id=CHILD_ID,
            spec=spec,
            calendar=contracts["calendar"],
            output=output,
            plan=plan,
            sealed_oos_carrier_path=carrier,
            sealed_oos_private_root=private_root,
            expected_sealed_carrier_sha256=sha256_file(carrier),
            expected_dataset_snapshot_sha256=expected_panel_sha256,
        )


def _stub_container_termination_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifacts: list[tuple[str, int, str]],
    *,
    present_attempts: set[int] | None = None,
) -> dict:
    state = tmp_path / "private-container-state"
    trust = tmp_path / "private-container-trust"
    workspace = tmp_path / "worktree" / "workspace"
    worktree = tmp_path / "worktree"
    for path in (state, trust, worktree, workspace):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    root = (
        state
        / "jobs"
        / "job-001"
        / "evo-child-container"
        / "CHILD_001"
    )
    root.mkdir(parents=True, mode=0o700)
    current = state
    for part in root.relative_to(state).parts:
        current = current / part
        current.chmod(0o700)
    admission = {
        "receipt_id": "admission-001",
        "expected_host_trust_manifest_sha256": "3" * 64,
        "identity": {
            "installation_id": "installation-001",
            "job_id": "job-001",
            "parent_report_id": "PARENT_001",
            "child_report_id": "CHILD_001",
        },
        "roots": {
            "state_root": str(state),
            "trust_root": str(trust),
            "worktree": str(worktree),
            "engine_root": str(worktree),
            "workspace_root": str(workspace),
        },
        "container": {
            "runtime": {"path": "/runtime", "sha256": "1" * 64},
            "image_digest": "sha256:" + "2" * 64,
            "resources": {},
        },
        "stages": {},
    }
    (root / "admission.json").write_text("{}\n", encoding="utf-8")
    (root / "admission.json").chmod(0o600)
    payloads: dict[str, dict] = {"admission.json": admission}
    for kind, attempt, stage in artifacts:
        name = f"{kind}__{attempt:06d}__{stage}.json"
        path = root / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
        if kind == "inflight":
            payloads[name] = {"attempt": attempt, "stage_name": stage}
        elif kind == "termination":
            payloads[name] = {
                "attempt": attempt,
                "stage_name": stage,
                "receipt_id": f"termination-{attempt}",
                "container": {
                    "container_name": child_container._prepare_container_name(
                        admission, attempt
                    )
                },
                "execution": {"stage_status": "SUCCEEDED"},
            }
        else:
            payloads[name] = {"attempt": attempt, "stage_name": stage}

    monkeypatch.setattr(
        child_container,
        "validate_evo_child_container_admission",
        lambda **_kwargs: {
            "admission": admission,
            "admission_path": root / "admission.json",
        },
    )
    monkeypatch.setattr(
        child_container,
        "_validate_host_trust",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        child_container,
        "_validate_inflight_receipt",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        child_container,
        "_validate_termination_receipt",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        child_container,
        "_validate_reconciliation_receipt",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        child_container,
        "_load_private_json",
        lambda path: payloads[Path(path).name],
    )
    present = set(present_attempts or set())

    def runtime(_runtime: str, args: list[str]):
        if args[0] == "ps":
            stdout = "a" * 64 + "\n" if present else ""
            return subprocess.CompletedProcess(args, 0, stdout, "")
        attempt = next(
            (
                item
                for item in {attempt for _kind, attempt, _stage in artifacts}
                if child_container._prepare_container_name(admission, item)
                == args[1]
            ),
            None,
        )
        if attempt in present:
            return subprocess.CompletedProcess(args, 0, "{}", "")
        return subprocess.CompletedProcess(
            args,
            1,
            "",
            f"Error: No such object: {args[1]}",
        )

    monkeypatch.setattr(child_container, "_runtime_completed", runtime)
    return {
        "state": state,
        "trust": trust,
        "workspace": workspace,
        "worktree": worktree,
        "root": root,
        "admission": admission,
    }


@pytest.mark.parametrize(
    ("artifacts", "present_attempts", "reason"),
    [
        (
            [
                ("inflight", 1, "validate_step4"),
                ("termination", 1, "validate_step4"),
                ("inflight", 2, "run_step4"),
                ("termination", 2, "run_step4"),
            ],
            set(),
            "latest_termination_required_stage_mismatch",
        ),
        (
            [
                ("inflight", 1, "validate_step4"),
                ("termination", 1, "validate_step4"),
                ("inflight", 2, "validate_step4"),
            ],
            set(),
            "unreconciled_inflight",
        ),
        (
            [
                ("inflight", 1, "validate_step4"),
                ("termination", 1, "validate_step4"),
            ],
            {1},
            "termination_reinspection_not_absent",
        ),
    ],
)
def test_container_termination_gate_rejects_stale_inflight_and_present_attacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifacts: list[tuple[str, int, str]],
    present_attempts: set[int],
    reason: str,
) -> None:
    fixture = _stub_container_termination_runtime(
        tmp_path,
        monkeypatch,
        artifacts,
        present_attempts=present_attempts,
    )
    with pytest.raises(child_container.EvoChildContainerError, match=reason):
        child_container.validate_latest_evo_child_agent_termination(
            state_root=fixture["state"],
            trust_root=fixture["trust"],
            installation_id="installation-001",
            job_id="job-001",
            workspace_root=fixture["workspace"],
            worktree=fixture["worktree"],
            parent_report_id="PARENT_001",
            child_report_id="CHILD_001",
            expected_host_pin="3" * 64,
            required_stage="validate_step4",
        )


def test_container_agent_stage_is_permanently_blocked_after_oos_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _stub_container_termination_runtime(
        tmp_path,
        monkeypatch,
        [],
    )
    panel = web_proof.web_factor_proof_paths(
        fixture["workspace"], "CHILD_001"
    )["panel"]
    panel.parent.mkdir(parents=True, exist_ok=True)
    panel.write_bytes(b"published-oos")
    with pytest.raises(
        child_container.EvoChildContainerError,
        match="agent_stage_forbidden_after_oos_publication",
    ):
        child_container.run_evo_child_agent_stage(
            admission_path=fixture["root"] / "admission.json",
            stage_name="validate_step4",
            logical_command=[],
            env={},
            timeout=60,
            trust_root=fixture["trust"],
            installation_id="installation-001",
        )


def test_public_termination_authority_is_closed_and_report_bound() -> None:
    authority = {
        "authority_version": (
            web_proof.HOST_AGENT_TERMINATION_AUTHORITY_VERSION
        ),
        "termination_receipt_ref": (
            "HOST_PRIVATE_SIGNED_EVO_CHILD_CONTAINER_TERMINATION"
        ),
        "termination_receipt_id": "8" * 64,
        "termination_receipt_sha256": "1" * 64,
        "stage_name": "validate_step4",
        "attempt": 4,
        "parent_report_id": REPORT_ID,
        "child_report_id": CHILD_ID,
        "job_id_sha256": "2" * 64,
        "expected_host_trust_manifest_sha256": "3" * 64,
        "admission_receipt_id": "9" * 64,
        "inflight_receipt_id": "a" * 64,
        "logical_command_sha256": "4" * 64,
        "image_digest_sha256": "5" * 64,
        "mounts_sha256": "6" * 64,
        "workspace_post_tree_sha256": "7" * 64,
        "network": "none",
        "process_tree_absent": True,
    }
    assert web_proof._validate_host_agent_termination_authority(
        authority,
        report_id=CHILD_ID,
    ) == authority
    for tampered in (
        {**authority, "child_report_id": "OTHER_CHILD"},
        {**authority, "stage_name": "run_step4"},
        {**authority, "process_tree_absent": False},
        {**authority, "termination_receipt_sha256": "typo"},
        {**authority, "private_receipt_path": "/host/private/receipt.json"},
    ):
        with pytest.raises(ValueError, match="termination authority invalid"):
            web_proof._validate_host_agent_termination_authority(
                tampered,
                report_id=CHILD_ID,
            )
