from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import factor_factory.console.ultimate_reader as ultimate_reader
import factor_factory.oos_exposure_incident as incident_module
from factor_factory.console.run_service import (
    _host_current_authority_transaction,
)
from factor_factory.console.ultimate_reader import UltimateRunSummary
from factor_factory.console.web_factor_proof import web_factor_proof_paths
from factor_factory.evo_oos import oos_allocation_path
from factor_factory.evo_terminal_closure import terminal_closure_path
from factor_factory.oos_exposure_incident import (
    build_oos_exposure_incident,
    prepare_oos_exposure_incident_host_private,
)
from factor_factory.research_conjecture import (
    epistemic_evolution_lifecycle_path,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store


REPORT_ID = "CONSOLE_CURRENT_AUTHORITY_REPORT"
FACTOR_ID = "CONSOLE_CURRENT_AUTHORITY_FACTOR"
INSTALLATION_ID = "console-current-authority-test"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _incident_payload(workspace: Path) -> dict:
    evidence_root = workspace / "incident-evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    paths = {
        name: evidence_root / filename
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
        workspace_root=workspace,
        report_id=REPORT_ID,
        factor_id=FACTOR_ID,
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


def _formal_summary() -> UltimateRunSummary:
    return UltimateRunSummary(
        report_id=REPORT_ID,
        factor_id=FACTOR_ID,
        research_id="console_current_authority_research",
        execution_status="COMPLETED",
        protocol_status="PASS",
        factor_verdict="REJECT",
        council_status="PASS",
        formal_proof_eligible=True,
        current_stage="completed",
    )


def test_console_commit_guard_covers_attestation_memory_and_db_then_current_read_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trust_root = state_root / "research-org-trust"
    ensure_runtime_trust_store(
        trust_root,
        installation_id=INSTALLATION_ID,
    )
    payload = _incident_payload(workspace)
    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_errors: list[BaseException] = []

    def writer() -> None:
        writer_started.set()
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=workspace,
                payload=payload,
                trust_root=trust_root,
                installation_id=INSTALLATION_ID,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    committed_steps: list[str] = []
    with _host_current_authority_transaction(
        state_root=state_root,
        workspace_root=workspace,
        installation_id=INSTALLATION_ID,
    ) as guard:
        current = ultimate_reader.validate_current_ultimate_authority(
            workspace,
            report_id=REPORT_ID,
            expected_factor_verdict="REJECT",
            formal_proof_eligible=False,
            incident_trust_root=trust_root,
            incident_installation_id=INSTALLATION_ID,
            _incident_guard=guard,
        )
        assert current["status"] == "NOT_APPLICABLE"
        thread = threading.Thread(target=writer)
        thread.start()
        assert writer_started.wait(2)
        for step in ("host_attestation", "formal_memory", "store_update_job"):
            committed_steps.append(step)
            assert not writer_finished.wait(0.05)

    thread.join(2)
    assert not thread.is_alive()
    assert writer_errors == []
    assert writer_finished.is_set()
    assert committed_steps == [
        "host_attestation",
        "formal_memory",
        "store_update_job",
    ]

    # The old structural ACCEPT/REJECT artifact is not current authority after
    # the incident writer linearizes immediately after the Console transaction.
    monkeypatch.setattr(
        ultimate_reader,
        "read_ultimate_workspace",
        lambda *_args, **_kwargs: _formal_summary(),
    )
    reread = ultimate_reader.read_current_ultimate_workspace(
        workspace,
        report_id=REPORT_ID,
        incident_trust_root=trust_root,
        incident_installation_id=INSTALLATION_ID,
    )
    assert reread.authority_validation["status"] == "BLOCK"
    assert reread.authority_validation["authority_source"] == (
        "durable_oos_incident_registry"
    )
    assert reread.summary.execution_status == "BLOCKED"
    assert reread.summary.factor_verdict == "BLOCK"
    assert reread.summary.formal_proof_eligible is False


def test_incident_writer_wins_before_console_commit_no_formal_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trust_root = state_root / "research-org-trust"
    ensure_runtime_trust_store(
        trust_root,
        installation_id=INSTALLATION_ID,
    )
    payload = _incident_payload(workspace)
    real_append = incident_module._append_private_incident_event
    writer_has_guard = threading.Event()
    release_writer = threading.Event()
    writer_errors: list[BaseException] = []

    def paused_append(**kwargs):
        writer_has_guard.set()
        assert release_writer.wait(2)
        return real_append(**kwargs)

    monkeypatch.setattr(
        incident_module,
        "_append_private_incident_event",
        paused_append,
    )

    def writer() -> None:
        try:
            prepare_oos_exposure_incident_host_private(
                workspace_root=workspace,
                payload=payload,
                trust_root=trust_root,
                installation_id=INSTALLATION_ID,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_has_guard.wait(2)

    outcomes: list[dict] = []
    formal_writes: list[str] = []

    def console_commit() -> None:
        with _host_current_authority_transaction(
            state_root=state_root,
            workspace_root=workspace,
            installation_id=INSTALLATION_ID,
        ) as guard:
            current = ultimate_reader.validate_current_ultimate_authority(
                workspace,
                report_id=REPORT_ID,
                expected_factor_verdict="REJECT",
                formal_proof_eligible=True,
                incident_trust_root=trust_root,
                incident_installation_id=INSTALLATION_ID,
                _incident_guard=guard,
            )
            outcomes.append(current)
            if current["status"] == "PASS":
                formal_writes.extend(
                    ["host_attestation", "formal_memory", "store_update_job"]
                )

    console_thread = threading.Thread(target=console_commit)
    console_thread.start()
    assert console_thread.is_alive()
    release_writer.set()
    writer_thread.join(2)
    console_thread.join(2)

    assert not writer_thread.is_alive()
    assert not console_thread.is_alive()
    assert writer_errors == []
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "BLOCK"
    assert outcomes[0]["factor_verdict"] == "BLOCK"
    assert outcomes[0]["formal_proof_eligible"] is False
    assert outcomes[0]["authority_source"] == "durable_oos_incident_registry"
    assert formal_writes == []


@pytest.mark.parametrize(
    ("marker_kind", "expected_marker"),
    [
        ("lifecycle", "evo_lifecycle"),
        ("secure_child", "secure_child_oos_allocation"),
        ("runtime_report", "evo_runtime_report"),
    ],
)
def test_deleted_evo_terminal_closure_cannot_fallback_to_web_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_kind: str,
    expected_marker: str,
) -> None:
    import factor_factory.evo_oos as evo_oos
    import factor_factory.console.web_factor_proof as web_factor_proof

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trust_root = tmp_path / "state" / "research-org-trust"
    ensure_runtime_trust_store(
        trust_root,
        installation_id=INSTALLATION_ID,
    )

    if marker_kind == "lifecycle":
        _write_json(
            epistemic_evolution_lifecycle_path(workspace, REPORT_ID),
            {"report_id": REPORT_ID, "state": "TERMINAL"},
        )
    elif marker_kind == "secure_child":
        _write_json(
            oos_allocation_path(workspace, REPORT_ID),
            {
                "report_id": REPORT_ID,
                "allocation_authority_mode": "HOST_PRIVATE_CARRIER_DERIVED",
            },
        )
    else:
        _write_json(
            workspace
            / "objects"
            / "runtime_context"
            / f"ultimate_run_report__{REPORT_ID}.json",
            {
                "report_id": REPORT_ID,
                "evo_v2_execution_gate": {"enabled": True},
            },
        )
    closure_path = terminal_closure_path(workspace, REPORT_ID)
    _write_json(closure_path, {"report_id": REPORT_ID, "stale": True})
    closure_path.unlink()

    # Preserve an apparently successful older Web finalization.  The current
    # reader must never consult it once durable report markers establish EVO.
    finalization_path = web_factor_proof_paths(workspace, REPORT_ID)[
        "finalization"
    ]
    _write_json(
        finalization_path,
        {
            "status": "PASS",
            "factor_verdict": "REJECT",
            "formal_proof_eligible": True,
        },
    )
    web_replays: list[str] = []

    def forged_web_replay(*_args, **_kwargs):
        web_replays.append("called")
        return {
            "status": "PASS",
            "factor_verdict": "REJECT",
            "formal_proof_eligible": True,
        }

    monkeypatch.setattr(
        web_factor_proof,
        "validate_web_factor_proof_finalization",
        forged_web_replay,
    )
    # Incident ordering is covered by the barrier tests above.  Isolate the
    # authority-source selection here so even a valid secure-child registry
    # cannot make a missing terminal closure fall through to legacy Web proof.
    monkeypatch.setattr(
        evo_oos,
        "formal_oos_incident_reasons",
        lambda **_kwargs: [],
    )
    current = ultimate_reader.validate_current_ultimate_authority(
        workspace,
        report_id=REPORT_ID,
        expected_factor_verdict="REJECT",
        formal_proof_eligible=True,
        incident_trust_root=trust_root,
        incident_installation_id=INSTALLATION_ID,
    )

    assert current["status"] == "BLOCK"
    assert current["factor_verdict"] == "BLOCK"
    assert current["formal_proof_eligible"] is False
    assert current["authority_source"] == "evo_post_oos_terminal_closure"
    assert expected_marker in current["evo_authority_markers"]
    assert current["block_reasons"] == [
        "BLOCK_FACTORFORGE_CONSOLE_CURRENT_FORMAL_AUTHORITY_INVALID:"
        "evo_terminal_closure_missing"
    ]
    assert web_replays == []
