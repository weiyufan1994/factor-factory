from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import factor_factory.evo_pre_oos_orchestrator as orchestrator
import factor_factory.revision_council.pre_oos_outcome as outcome_module
from factor_factory.evo_staging import staging_manifest_path
from factor_factory.evo_v2 import evo_v2_paths
from factor_factory.research_conjecture import epistemic_evolution_lifecycle_path
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.revision_council.pre_oos_outcome import (
    materialize_pre_oos_council_outcome,
    pre_oos_outcome_verifier_path,
)
from tests.test_factorforge_evo_v2 import REPORT_ID
from tests.test_factorforge_pre_oos_council_outcome import _fixture, _write_json


INSTALLATION_ID = "council-test-installation-001"
REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts/orchestrate_factorforge_evo_pre_oos_outcome.py"


def _prepare(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcomes: tuple[str, ...] = (
        "MINIMAL_MECHANISM_DELTA",
        "NO_DERIVED_LAW",
    ),
    selected_index: int = 0,
) -> tuple[Path, str, str]:
    synthesis, synthesis_path = _fixture(
        root,
        outcomes=outcomes,
        selected_index=selected_index,
    )
    monkeypatch.setattr(
        outcome_module,
        "_run_existing_validators",
        lambda _root, _report, _paths: [],
    )
    materialized = materialize_pre_oos_council_outcome(
        workspace_root=root,
        report_id=REPORT_ID,
        synthesis_path=synthesis_path,
    )
    expected_state = materialized["authorized_host_transition_state"]
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(root, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    qualified_sha256 = stable_hash(lifecycle)
    private_inside = root / "host-private-trust"
    private_outside = root.parent / f"{root.name}-host-private-trust"
    private_inside.rename(private_outside)
    return private_outside, qualified_sha256, expected_state


def _orchestrate(
    root: Path,
    trust_root: Path,
    qualified_sha256: str,
    expected_state: str,
) -> dict:
    return orchestrator.orchestrate_pre_oos_council_outcome(
        workspace_root=root,
        report_id=REPORT_ID,
        expected_transition_state=expected_state,
        expected_qualified_lifecycle_sha256=qualified_sha256,
        trust_root=trust_root,
        installation_id=INSTALLATION_ID,
    )


def test_minimal_delta_orchestration_is_signed_staged_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(tmp_path, monkeypatch)
    assert expected_state == "MINIMAL_MECHANISM_DELTA"
    first = _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)
    assert first["verdict"] == "PASS"
    assert first["status"] == "ORCHESTRATED"
    assert first["actions"] == {
        "feedback_materialized": True,
        "host_lifecycle_transition_performed": True,
        "council_outcome_materialized": True,
    }
    assert first["authority"] == {
        "host_transition_verified": True,
        "human_approval_granted": False,
        "child_execution_allowed": False,
        "factor_verdict": "NOT_ISSUED",
        "canonical_memory_write_allowed": False,
        "oos_accessed": False,
    }
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["current_state"] == "MINIMAL_MECHANISM_DELTA"
    assert lifecycle["events"][-1]["evidence_refs"] == [
        first["outcome_evidence_ref"]
    ]
    paths = evo_v2_paths(tmp_path, REPORT_ID)
    assert paths["mechanism_delta"].is_file()
    assert paths["economic_backprojection"].is_file()
    assert first["staging_manifest"]["stages"] == [
        "admit-feedback",
        "admit-council-outcome",
    ]

    second = _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)
    assert second["verdict"] == "PASS"
    assert second["status"] == "IDEMPOTENT_REPLAY"
    assert not any(second["actions"].values())


def test_no_derived_law_orchestration_is_terminal_without_inventing_law(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(
        tmp_path,
        monkeypatch,
        outcomes=("NO_DERIVED_LAW", "NO_DERIVED_LAW"),
        selected_index=1,
    )
    assert expected_state == "NO_DERIVED_LAW"
    result = _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)
    assert result["verdict"] == "PASS"
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["current_state"] == "NO_DERIVED_LAW"
    paths = evo_v2_paths(tmp_path, REPORT_ID)
    assert not paths["mechanism_delta"].exists()
    assert not paths["economic_backprojection"].exists()
    no_law = paths["feedback_ledger"].parent / "no_derived_law.json"
    assert no_law.is_file()
    manifest = json.loads(
        staging_manifest_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    assert [event["stage"] for event in manifest["events"]] == [
        "admit-feedback",
        "admit-council-outcome",
    ]


def test_host_cli_executes_the_same_signed_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(tmp_path, monkeypatch)
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--workspace-root",
            str(tmp_path),
            "--report-id",
            REPORT_ID,
            "--expected-transition-state",
            expected_state,
            "--expected-qualified-lifecycle-sha256",
            qualified_sha,
            "--trust-root",
            str(trust_root),
            "--installation-id",
            INSTALLATION_ID,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["status"] == "ORCHESTRATED"
    assert payload["authority"]["oos_accessed"] is False


def test_selected_proposal_mutation_blocks_before_any_host_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(tmp_path, monkeypatch)
    verifier = json.loads(
        pre_oos_outcome_verifier_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    selected = verifier["evidence_bindings"]["selected_proposal_ref"]
    selected_path = tmp_path / selected["path"]
    payload = json.loads(selected_path.read_text(encoding="utf-8"))
    payload["agent_identifier"] = "tampered_agent"
    _write_json(selected_path, payload)
    with pytest.raises(Exception, match="outcome_verifier|SHA256|sha256"):
        _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["current_state"] == "QUALIFIED_CONTRADICTION"
    assert not staging_manifest_path(tmp_path, REPORT_ID).exists()


def test_stale_qualified_cas_or_wrong_selected_outcome_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(tmp_path, monkeypatch)
    with pytest.raises(Exception, match="qualified_lifecycle_cas_mismatch"):
        _orchestrate(tmp_path, trust_root, "0" * 64, expected_state)
    with pytest.raises(Exception, match="transition_state|verifier"):
        _orchestrate(
            tmp_path,
            trust_root,
            qualified_sha,
            "NO_DERIVED_LAW",
        )
    lifecycle = json.loads(
        epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID).read_text(
            encoding="utf-8"
        )
    )
    assert lifecycle["current_state"] == "QUALIFIED_CONTRADICTION"
    assert not staging_manifest_path(tmp_path, REPORT_ID).exists()


def test_crash_after_signed_transition_recovers_without_duplicate_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(tmp_path, monkeypatch)
    real_materialize = orchestrator.materialize_evo_v2_stage

    def crash_on_council(**kwargs: object) -> dict:
        if kwargs.get("stage") == "admit-council-outcome":
            raise RuntimeError("simulated_crash_after_lifecycle")
        return real_materialize(**kwargs)

    monkeypatch.setattr(orchestrator, "materialize_evo_v2_stage", crash_on_council)
    with pytest.raises(RuntimeError, match="simulated_crash_after_lifecycle"):
        _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)
    lifecycle_path = epistemic_evolution_lifecycle_path(tmp_path, REPORT_ID)
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    assert lifecycle["current_state"] == expected_state
    assert len(lifecycle["events"]) == 3
    manifest = json.loads(
        staging_manifest_path(tmp_path, REPORT_ID).read_text(encoding="utf-8")
    )
    assert [event["stage"] for event in manifest["events"]] == ["admit-feedback"]

    monkeypatch.setattr(orchestrator, "materialize_evo_v2_stage", real_materialize)
    recovered = _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)
    assert recovered["verdict"] == "PASS"
    assert recovered["actions"] == {
        "feedback_materialized": False,
        "host_lifecycle_transition_performed": False,
        "council_outcome_materialized": True,
    }
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    assert len(lifecycle["events"]) == 3


def test_self_reported_authority_human_or_child_and_oos_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trust_root, qualified_sha, expected_state = _prepare(tmp_path, monkeypatch)
    verifier_path = pre_oos_outcome_verifier_path(tmp_path, REPORT_ID)
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    verifier["authority"]["host_transition_performed"] = True
    verifier.pop("content_sha256", None)
    verifier["content_sha256"] = stable_hash(verifier)
    _write_json(verifier_path, verifier)
    with pytest.raises(Exception, match="outcome_verifier"):
        _orchestrate(tmp_path, trust_root, qualified_sha, expected_state)

    # Restore the canonical verifier by rebuilding this case in a fresh root,
    # then attack each forbidden side surface independently.
    other = tmp_path.parent / f"{tmp_path.name}-surface"
    other.mkdir()
    trust_root, qualified_sha, expected_state = _prepare(other, monkeypatch)
    _write_json(
        other / "objects/handoff" / f"handoff_to_step3b__{REPORT_ID}.json",
        {"status": "approved_for_step3b_handoff"},
    )
    with pytest.raises(Exception, match="human_or_child_surface_present"):
        _orchestrate(other, trust_root, qualified_sha, expected_state)

    third = tmp_path.parent / f"{tmp_path.name}-oos"
    third.mkdir()
    trust_root, qualified_sha, expected_state = _prepare(third, monkeypatch)
    _write_json(
        third
        / "objects/research_protocol"
        / f"oos_release_manifest__{REPORT_ID}.json",
        {"release_status": "RELEASED", "report_id": REPORT_ID},
    )
    with pytest.raises(Exception, match="outcome_verifier|OOS|oos"):
        _orchestrate(third, trust_root, qualified_sha, expected_state)
